from flask import Flask, render_template_string
import requests
from collections import defaultdict, Counter, OrderedDict
from datetime import datetime, timedelta
import csv
import os
from pathlib import Path
import time

# Crea una instancia de la aplicación Flask.
app = Flask(__name__)

# --- Variables Globales para el Conteo de Detecciones ---
detecciones = defaultdict(lambda: defaultdict(int))
fecha_ultimo_check = datetime.now() - timedelta(minutes=2)
CSV_FILE = Path("detecciones_server.csv")

# --- Configuración del API ---
API_URL = "https://dashboard-api.verifyfaces.com/companies/54/search/realtime"
AUTH_URL = "https://dashboard-api.verifyfaces.com/auth/login"
AUTH_EMAIL = "eangulo@blocksecurity.com.ec"
AUTH_PASSWORD = "Scarling//07052022.?"

TOKEN = None
PER_PAGE = 100

def leer_csv(ruta: Path):
    """
    Lee el CSV con columnas: fecha, deteccion_id, conteo
    Devuelve:
      - registros: lista de dicts crudos
      - agg: dict[(fecha, deteccion_id)] = suma_conteo
      - fechas_ordenadas: lista de fechas (str) ordenadas asc
      - ids_ordenados: lista de id ordenados por total desc
    """
    registros = []
    agg = defaultdict(int)
    fechas = set()
    ids_total = Counter()

    if not ruta.exists():
        return [], {}, [], [], {}

    with ruta.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            fecha = str(row.get("fecha", "")).strip()
            # Cambio aquí: de person_id a deteccion_id
            deteccion_id = str(row.get("deteccion_id", "")).strip()
            try:
                conteo = int(row.get("conteo", "1"))
            except ValueError:
                conteo = 1

            if not fecha or not deteccion_id:
                continue

            try:
                fecha_dt = datetime.fromisoformat(str(fecha).split(" ")[0])
                fecha = fecha_dt.date().isoformat()
            except Exception:
                pass

            registros.append({"fecha": fecha, "deteccion_id": deteccion_id, "conteo": conteo})
            agg[(fecha, deteccion_id)] += conteo
            fechas.add(fecha)
            ids_total[deteccion_id] += conteo

    fechas_ordenadas = sorted(fechas)
    # Cambio aquí: personas_ordenadas a ids_ordenados
    ids_ordenados = [did for did, _ in sorted(ids_total.items(), key=lambda x: (-x[1], x[0]))]

    # Cambio aquí: personas_total a ids_total
    return registros, agg, fechas_ordenadas, ids_ordenados, ids_total

def html_escape(s: str) -> str:
    """Escapa caracteres HTML."""
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )

def construir_html(registros, agg, fechas, ids, ids_total):
    """Construye el HTML completo del dashboard."""
    total_registros = sum(r["conteo"] for r in registros) if registros else 0
    total_fechas = len(set(r["fecha"] for r in registros)) if registros else 0
    # Cambio aquí: total_personas a total_ids
    total_ids = len(set(r["deteccion_id"] for r in registros)) if registros else 0

    conteo_por_fecha = defaultdict(int)
    for r in registros:
        conteo_por_fecha[r["fecha"]] += r["conteo"]

    labels_chart = list(sorted(conteo_por_fecha.keys()))
    data_chart = [conteo_por_fecha[f] for f in labels_chart]

    # Cambio aquí: top_personas a top_ids
    top_ids = sorted(ids_total.items(), key=lambda x: -x[1])[:10]
    labels_ids = [did for did, _ in top_ids]
    data_ids = [cnt for _, cnt in top_ids]

    filas_agg = []
    # Cambio aquí: person_id a deteccion_id
    for (fecha, deteccion_id), suma in sorted(agg.items(), key=lambda x: (x[0][0], -x[1])):
        filas_agg.append(
            f"<tr>"
            f"<td class='td'>{html_escape(fecha)}</td>"
            f"<td class='td mono'>{html_escape(deteccion_id)}</td>"
            f"<td class='td num'>{suma}</td>"
            f"</tr>"
        )

    # Cambio aquí: person_id a deteccion_id
    pivot = {did: {f: 0 for f in fechas} for did in ids}
    for (fecha, deteccion_id), suma in agg.items():
        if deteccion_id in pivot and fecha in pivot[deteccion_id]:
            pivot[deteccion_id][fecha] += suma

    th_fechas = "".join(f"<th class='th'>{html_escape(f)}</th>" for f in fechas)
    filas_pivot = []
    # Cambio aquí: pid in personas a did in ids
    for did in ids:
        celdas = "".join(f"<td class='td num'>{pivot[did][f]}</td>" for f in fechas)
        filas_pivot.append(
            # Cambio aquí: pid a did
            f"<tr><td class='td mono'>{html_escape(did)}</td>{celdas}"
            f"<td class='td num strong'>{sum(pivot[did].values())}</td></tr>"
        )

    top_items = "".join(
        # Cambio aquí: pid a did
        f"<li><span class='mono'>{html_escape(did)}</span> · <strong>{cnt}</strong></li>"
        for did, cnt in top_ids
    )

    # Cambios en el HTML para reflejar el uso de "ID" en lugar de "Personas"
    return f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<title>Dashboard de Detecciones</title>
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
    <h1>Dashboard de detecciones Arrayanes</h1>
    <div class="grid cards">
      <div class="card"><h3>Registros totales</h3><div class="val">{total_registros}</div></div>
      <div class="card"><h3>Fechas únicas</h3><div class="val">{total_fechas}</div></div>
      <div class="card"><h3>IDs únicos</h3><div class="val">{total_ids}</div></div>
    </div>

    <div class="section">
      <div class="toolbar"><h2 style="margin-right:auto">Detecciones por fecha</h2></div>
      <canvas id="deteccionesChart" height="100"></canvas>
    </div>

    <div class="section">
      <div class="toolbar"><h2 style="margin-right:auto">Detecciones por ID (Top 10)</h2></div>
      <canvas id="personasChart" height="100"></canvas>
    </div>

    <div class="section">
      <div class="toolbar">
        <h2 style="margin-right:auto">Top IDs detectados</h2>
      </div>
      <ul class="list">{top_items}</ul>
    </div>

    <div class="section">
      <div class="toolbar">
        <h2 style="margin-right:auto">Tabla de detecciones (fecha · ID · conteo)</h2>
        <input class="input" id="filterAgg" placeholder="Filtra por fecha o ID...">
      </div>
      <div class="table-wrap">
        <table id="aggTable">
          <thead>
            <tr><th class="th">fecha</th><th class="th">ID</th><th class="th right">conteo</th></tr>
          </thead>
          <tbody>{''.join(filas_agg)}</tbody>
        </table>
      </div>
      <div class="hint">Se agrupan múltiples filas del CSV ({html_escape(CSV_FILE.name)}) sumando su columna <code>conteo</code>.</div>
    </div>

    <div class="section">
      <div class="toolbar">
        <h2 style="margin-right:auto">Tabla de detecciones (ID × fecha)</h2>
        <input class="input" id="filterPivot" placeholder="Filtra por ID...">
      </div>
      <div class="table-wrap">
        <table id="pivotTable">
          <thead>
            <tr><th class="th">ID</th>{th_fechas}<th class="th right">total</th></tr>
          </thead>
          <tbody>{''.join(filas_pivot)}</tbody>
        </table>
      </div>
      <div class="hint">Cada celda muestra la suma de <code>conteo</code> para ese <code>ID</code> en la fecha correspondiente.</div>
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
  }})(); // <--- CORRECCIÓN

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
  }})(); // <--- CORRECCIÓN

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
          y: {{
            beginAtZero: true,
            ticks: {{ precision:0 }}
          }}
        }}
      }}
    }});
  }})(); // <--- CORRECCIÓN

  // Gráfico de barras por ID
  (function() {{
    const ctx2 = document.getElementById('personasChart').getContext('2d');
    new Chart(ctx2, {{
      type: 'bar',
      data: {{
        labels: {labels_ids},
        datasets: [{{
          label: 'Detecciones',
          data: {data_ids},
          backgroundColor: 'rgba(255, 206, 86, 0.7)',
          borderColor: 'rgba(255, 206, 86, 1)',
          borderWidth: 1
        }}]
      }},
      options: {{
        responsive: true,
        indexAxis: 'y', // horizontal bars para que se lean mejor los IDs
        scales: {{
          x: {{
            beginAtZero: true,
            ticks: {{ precision:0 }}
          }}
        }}
      }}
    }});
  }})(); // <--- CORRECCIÓN
</script>
</body>
</html>
"""

def obtener_nuevo_token():
    """
    Se conecta a la API de autenticación y actualiza el token global.
    """
    global TOKEN
    try:
        auth_data = {
            "email": AUTH_EMAIL,
            "password": AUTH_PASSWORD
        }
        response = requests.post(AUTH_URL, json=auth_data, timeout=10)
        response.raise_for_status()
        
        new_token = response.json().get("token")
        if new_token:
            TOKEN = new_token
            print("Token actualizado correctamente.")
            return True
        return False
    except requests.exceptions.RequestException as e:
        print(f"Error al obtener el token: {e}")
        return False

@app.route('/')
def mostrar_detecciones():
    """
    Obtiene los datos de la API, los guarda en un CSV y luego
    lee ese mismo CSV para construir y mostrar el dashboard.
    """
    global fecha_ultimo_check, TOKEN
    
    if datetime.now() - fecha_ultimo_check > timedelta(minutes=1) or TOKEN is None:
        if not obtener_nuevo_token():
            return "<h1>Error de autenticación</h1><p>No se pudo obtener un nuevo token.</p>", 500
    
    try:
        from_str = (datetime.now() - timedelta(days=1)).strftime("2025-08-01T00:00:00.000Z")
        to_str = datetime.now().strftime("%Y-%m-%dT%H:%M:%S.000Z")

        params = {
            "from": from_str,
            "to": to_str,
            "page": 2,
            "perPage": PER_PAGE
        }
        headers = {"Authorization": f"Bearer {TOKEN}"}
        
        response = requests.get(API_URL, headers=headers, params=params, timeout=10)
        response.raise_for_status()

        data = response.json()

        with open(CSV_FILE, mode="w", newline="", encoding="utf-8") as f:
            # Cambio aquí: encabezado del CSV a "deteccion_id"
            writer = csv.writer(f)
            writer.writerow(["fecha", "deteccion_id", "conteo"])

            for search in data.get("searches", []):
                # Extrae el 'id' del nivel 'search'
                deteccion_id = search.get("id")
                
                # Accede al timestamp desde 'search' y maneja si 'result' es nulo
                timestamp = search.get("result", {}).get("image", {}).get("time")

                if not deteccion_id or not timestamp:
                    continue

                try:
                    fecha = datetime.strptime(timestamp[:8], "%Y%m%d").date()
                    # Escribe el id de la detección en lugar del personId
                    writer.writerow([fecha, deteccion_id, 1])
                except (ValueError, IndexError):
                    continue
            
            fecha_ultimo_check = datetime.now()

    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 401:
            print("Token expirado. Intentando obtener uno nuevo...")
            TOKEN = None
            # No hay `redirect` en esta función, simplemente se actualizará en la próxima carga
            # En un caso real, aquí podrías usar `werkzeug.utils.redirect` para redirigir
            pass
        else:
            error_message = f"Error de la API: {e}"
            return f"<h1>Error</h1><p>{error_message}</p>", 500
    except requests.exceptions.RequestException as e:
        error_message = f"Error al conectar con la API: {e}"
        return f"<h1>Error</h1><p>{error_message}</p>", 500
    except Exception as e:
        error_message = f"Ocurrió un error inesperado: {e}"
        return f"<h1>Error</h1><p>{error_message}</p>", 500
            
    registros, agg, fechas_ordenadas, ids_ordenados, ids_total = leer_csv(CSV_FILE)
    html_dashboard = construir_html(registros, agg, fechas_ordenadas, ids_ordenados, ids_total)
    
    return render_template_string(html_dashboard)

if __name__ == '__main__':
    app.run(debug=True)