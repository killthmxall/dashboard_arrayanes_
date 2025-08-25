# build_dashboard.py
import csv
from collections import defaultdict, Counter, OrderedDict
from pathlib import Path
from datetime import datetime

CSV_FILE = Path("detecciones_server.csv")
HTML_FILE = Path("dashboard.html")

def leer_csv(ruta: Path):
    """
    Lee el CSV con columnas: fecha, person_id, conteo
    Devuelve:
      - registros: lista de dicts crudos
      - agg: dict[(fecha, person_id)] = suma_conteo
      - fechas_ordenadas: lista de fechas (str) ordenadas asc
      - personas_ordenadas: lista de person_id ordenados por total desc
    """
    registros = []
    agg = defaultdict(int)
    fechas = set()
    personas_total = Counter()

    if not ruta.exists():
        raise FileNotFoundError(f"No se encontró {ruta.resolve()}")

    with ruta.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Normaliza/valida columnas esperadas
            fecha = str(row.get("fecha", "")).strip()
            person_id = str(row.get("person_id", "")).strip()
            try:
                conteo = int(row.get("conteo", "1"))
            except ValueError:
                conteo = 1

            if not fecha or not person_id:
                continue

            # Normaliza fecha a YYYY-MM-DD si viniera como date object str()
            # (por si el script original escribió como 2025-08-21 sin hora)
            try:
                # Si viene como '2025-08-21', esto no cambia nada
                # Si viniera como '2025-08-21 00:00:00', lo reducimos
                fecha_dt = datetime.fromisoformat(str(fecha).split(" ")[0])
                fecha = fecha_dt.date().isoformat()
            except Exception:
                # deja la fecha tal cual si no se puede parsear
                pass

            registros.append({"fecha": fecha, "person_id": person_id, "conteo": conteo})
            agg[(fecha, person_id)] += conteo
            fechas.add(fecha)
            personas_total[person_id] += conteo

    fechas_ordenadas = sorted(fechas)  # asc
    # personas ordenadas por total desc, luego id asc para estabilidad
    personas_ordenadas = [pid for pid, _ in sorted(personas_total.items(), key=lambda x: (-x[1], x[0]))]

    return registros, agg, fechas_ordenadas, personas_ordenadas, personas_total

def html_escape(s: str) -> str:
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )

def construir_html(registros, agg, fechas, personas, personas_total):
    total_registros = sum(r["conteo"] for r in registros)
    total_fechas = len(set(r["fecha"] for r in registros))
    total_personas = len(set(r["person_id"] for r in registros))

    # --- Datos para gráfico de barras por fecha ---
    conteo_por_fecha = defaultdict(int)
    for r in registros:
        conteo_por_fecha[r["fecha"]] += r["conteo"]

    labels_chart = list(sorted(conteo_por_fecha.keys()))
    data_chart = [conteo_por_fecha[f] for f in labels_chart]

    # --- Datos para gráfico por person_id (top 10) ---
    top_personas = sorted(personas_total.items(), key=lambda x: -x[1])[:10]
    labels_personas = [pid for pid, _ in top_personas]
    data_personas = [cnt for _, cnt in top_personas]

    # Tabla agregada (igual que antes)
    filas_agg = []
    for (fecha, person_id), suma in sorted(agg.items(), key=lambda x: (x[0][0], -x[1])):
        filas_agg.append(
            f"<tr>"
            f"<td class='td'>{html_escape(fecha)}</td>"
            f"<td class='td mono'>{html_escape(person_id)}</td>"
            f"<td class='td num'>{suma}</td>"
            f"</tr>"
        )

    # Tabla pivot (igual que antes)
    pivot = {pid: {f: 0 for f in fechas} for pid in personas}
    for (fecha, person_id), suma in agg.items():
        if person_id in pivot and fecha in pivot[person_id]:
            pivot[person_id][fecha] += suma

    th_fechas = "".join(f"<th class='th'>{html_escape(f)}</th>" for f in fechas)
    filas_pivot = []
    for pid in personas:
        celdas = "".join(f"<td class='td num'>{pivot[pid][f]}</td>" for f in fechas)
        filas_pivot.append(
            f"<tr><td class='td mono'>{html_escape(pid)}</td>{celdas}"
            f"<td class='td num strong'>{sum(pivot[pid].values())}</td></tr>"
        )

    top_items = "".join(
        f"<li><span class='mono'>{html_escape(pid)}</span> · <strong>{cnt}</strong></li>"
        for pid, cnt in top_personas
    )

    # HTML con dos gráficos
    return f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<title>Dashboard de detecciones VerifyFaces</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="60">
<style>
  :root {{
    --bg: #0b1020;
    --card: #12172a;
    --muted: #8ea0c0;
    --text: #e8eefc;
    --accent: #6aa7ff;
    --grid: #1e2742;
    --border: #223052;
  }}
  * {{ box-sizing: border-box; }}
  html, body {{ margin: 0; padding: 0; background: var(--bg); color: var(--text); font-family: ui-sans-serif, system-ui; }}
  .wrap {{ max-width: 1200px; margin: 32px auto; padding: 0 16px; }}
  h1 {{ margin: 0 0 16px; font-size: 28px; font-weight: 700; letter-spacing: .2px; }}
  .muted {{ color: var(--muted); }}
  .grid {{ display: grid; gap: 16px; }}
  .cards {{ grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); margin-bottom: 20px; }}
  .card {{ background: linear-gradient(180deg, var(--card), #0f1528 80%); border: 1px solid var(--border); border-radius: 16px; padding: 16px 18px; }}
  .card h3 {{ margin: 0; font-size: 13px; font-weight: 600; color: var(--muted); }}
  .card .val {{ margin-top: 8px; font-size: 28px; font-weight: 800; color: var(--text); }}
  .section {{ background: rgba(18,23,42,.6); border: 1px solid var(--border); border-radius: 16px; padding: 16px; margin-bottom: 22px; }}
  .section h2 {{ margin: 0 0 12px; font-size: 18px; }}
  .toolbar {{ display: flex; gap: 8px; align-items: center; margin-bottom: 12px; }}
  .input {{ background: #0b1226; border: 1px solid var(--border); color: var(--text); padding: 10px 12px; border-radius: 12px; outline: none; width: 100%; }}
  .table-wrap {{ overflow: auto; border: 1px solid var(--border); border-radius: 12px; }}
  table {{ width: 100%; border-collapse: collapse; min-width: 640px; }}
  .th, .td {{ text-align: left; padding: 10px 12px; border-bottom: 1px solid var(--grid); white-space: nowrap; }}
  thead .th {{ position: sticky; top: 0; background: #0d1330; z-index: 1; }}
  .num {{ text-align: right; }}
  .mono {{ font-family: ui-monospace, monospace; font-size: 12px; color: #c8d5f5; }}
  .strong {{ font-weight: 700; }}
  .pill {{ display: inline-block; padding: 4px 8px; border: 1px solid var(--border); border-radius: 999px; color: var(--muted); font-size: 12px; }}
  .list {{ display: grid; grid-template-columns: repeat(auto-fit,minmax(220px,1fr)); gap: 8px; margin: 0; padding: 0; list-style: none; }}
  .list li {{ background: #0b1226; border: 1px solid var(--border); border-radius: 12px; padding: 10px 12px; }}
  .hint {{ font-size: 12px; color: var(--muted); }}
  .right {{ text-align: right; }}
  .footer {{ margin: 16px 0 4px; color: var(--muted); font-size: 12px; }}
</style>
</head>
<body>
  <div class="wrap">
    <h1>Dashboard de Detecciones <span class="pill">auto-refresh 60s</span></h1>
    <div class="grid cards">
      <div class="card"><h3>Registros totales</h3><div class="val">{total_registros}</div></div>
      <div class="card"><h3>Fechas únicas</h3><div class="val">{total_fechas}</div></div>
      <div class="card"><h3>Personas únicas</h3><div class="val">{total_personas}</div></div>
    </div>

    <!-- Gráfico de barras por fecha -->
    <div class="section">
      <div class="toolbar"><h2 style="margin-right:auto">Detecciones por fecha</h2></div>
      <canvas id="deteccionesChart" height="100"></canvas>
    </div>

    <!-- NUEVO: gráfico de barras por person_id -->
    <div class="section">
      <div class="toolbar"><h2 style="margin-right:auto">Detecciones por person_id (Top 10)</h2></div>
      <canvas id="personasChart" height="100"></canvas>
    </div>

    <div class="section">
      <div class="toolbar"><h2 style="margin-right:auto">Top personas por detecciones</h2></div>
      <ul class="list">{top_items}</ul>
    </div>

    <div class="section">
      <div class="toolbar">
        <h2 style="margin-right:auto">Tabla agregada (fecha · person_id · conteo)</h2>
        <input class="input" id="filterAgg" placeholder="Filtra por fecha o person_id...">
      </div>
      <div class="table-wrap">
        <table id="aggTable">
          <thead>
            <tr><th class="th">fecha</th><th class="th">person_id</th><th class="th right">conteo</th></tr>
          </thead>
          <tbody>{''.join(filas_agg)}</tbody>
        </table>
      </div>
      <div class="hint">Se agrupan múltiples filas del CSV ({html_escape(CSV_FILE.name)}) sumando su columna <code>conteo</code>.</div>
    </div>

    <div class="section">
      <div class="toolbar">
        <h2 style="margin-right:auto">Pivot (person_id × fecha)</h2>
        <input class="input" id="filterPivot" placeholder="Filtra por person_id...">
      </div>
      <div class="table-wrap">
        <table id="pivotTable">
          <thead>
            <tr><th class="th">person_id</th>{th_fechas}<th class="th right">total</th></tr>
          </thead>
          <tbody>{''.join(filas_pivot)}</tbody>
        </table>
      </div>
      <div class="hint">Cada celda muestra la suma de <code>conteo</code> para ese <code>person_id</code> en la fecha correspondiente.</div>
    </div>

    <div class="footer">Fuente: {html_escape(CSV_FILE.name)} · Generado {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</div>
  </div>

<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<script>
  // Filtro simple tabla agregada
  (function() {{
    const input = document.getElementById('filterAgg');
    const tbody = document.querySelector('#aggTable tbody');
    input.addEventListener('input', function() {{
      const q = this.value.toLowerCase();
      for (const tr of tbody.rows) {{
        const txt = tr.innerText.toLowerCase();
        tr.style.display = txt.includes(q) ? '' : 'none';
      }}
    }});
  }})();

  // Filtro simple tabla pivot
  (function() {{
    const input = document.getElementById('filterPivot');
    const tbody = document.querySelector('#pivotTable tbody');
    input.addEventListener('input', function() {{
      const q = this.value.toLowerCase();
      for (const tr of tbody.rows) {{
        const firstCell = tr.cells[0].innerText.toLowerCase();
        tr.style.display = firstCell.includes(q) ? '' : 'none';
      }}
    }});
  }})();

  // Gráfico de barras por fecha
  (function() {{
    const ctx = document.getElementById('deteccionesChart').getContext('2d');
    new Chart(ctx, {{
      type: 'bar',
      data: {{
        labels: {labels_chart},
        datasets: [{{
          label: 'Detecciones',
          data: {data_chart},
          backgroundColor: 'rgba(106, 167, 255, 0.7)',
          borderColor: 'rgba(106, 167, 255, 1)',
          borderWidth: 1
        }}]
      }},
      options: {{
        responsive: true,
        scales: {{
          y: {{ beginAtZero: true, ticks: {{ precision:0 }} }}
        }}
      }}
    }});
  }})();

  // Gráfico de barras por person_id
  (function() {{
    const ctx2 = document.getElementById('personasChart').getContext('2d');
    new Chart(ctx2, {{
      type: 'bar',
      data: {{
        labels: {labels_personas},
        datasets: [{{
          label: 'Detecciones',
          data: {data_personas},
          backgroundColor: 'rgba(255, 206, 86, 0.7)',
          borderColor: 'rgba(255, 206, 86, 1)',
          borderWidth: 1
        }}]
      }},
      options: {{
        responsive: true,
        indexAxis: 'y', // horizontal bars para que se lean mejor los IDs
        scales: {{
          x: {{ beginAtZero: true, ticks: {{ precision:0 }} }}
        }}
      }}
    }});
  }})();
</script>
</body>
</html>
"""



def main():
    registros, agg, fechas, personas, personas_total = leer_csv(CSV_FILE)
    html = construir_html(registros, agg, fechas, personas, personas_total)
    HTML_FILE.write_text(html, encoding="utf-8")
    print(f"Dashboard generado: {HTML_FILE.resolve()}")

if __name__ == "__main__":
    main()
