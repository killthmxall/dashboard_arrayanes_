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
# En una aplicación real, esto se manejaría con una base de datos o caché.
# Para este ejemplo, usamos variables globales para mantener el estado entre peticiones.
detecciones = defaultdict(lambda: defaultdict(int))
fecha_ultimo_check = datetime.now() - timedelta(minutes=2) # Inicializa para forzar la primera llamada
CSV_FILE = Path("detecciones_server.csv")

# --- Configuración del API (Mover a variables de entorno en producción) ---
API_URL = "https://dashboard-api.verifyfaces.com/companies/54/search/realtime"
# Nota: La clave de API es un dato sensible. En una aplicación real, no debe estar
# hardcodeada. Se recomienda usar variables de entorno.
TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ1c2VySWQiOjE4NCwiaWF0IjoxNzU2MTUxOTU2LCJleHAiOjE3NTYxNTU1NTZ9.ixgnd44DhMUh_uPMeWSGVnUG3CCzbyRXCA7JHXLR5O8"
PER_PAGE = 100

# --- Configuración del API ---
API_URL = "https://dashboard-api.verifyfaces.com/companies/54/search/realtime"

# --- Credenciales de autenticación ---
AUTH_URL = "https://dashboard-api.verifyfaces.com/auth/login"
AUTH_EMAIL = "eangulo@blocksecurity.com.ec"
AUTH_PASSWORD = "Scarling//07052022.?"

TOKEN = None # Inicializamos el token como None
PER_PAGE = 100

# --- Funciones para construir el dashboard desde el CSV (integradas desde build_dashboard.py) ---

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
        return [], {}, [], [], {}

    with ruta.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            fecha = str(row.get("fecha", "")).strip()
            person_id = str(row.get("person_id", "")).strip()
            try:
                conteo = int(row.get("conteo", "1"))
            except ValueError:
                conteo = 1

            if not fecha or not person_id:
                continue

            try:
                fecha_dt = datetime.fromisoformat(str(fecha).split(" ")[0])
                fecha = fecha_dt.date().isoformat()
            except Exception:
                pass

            registros.append({"fecha": fecha, "person_id": person_id, "conteo": conteo})
            agg[(fecha, person_id)] += conteo
            fechas.add(fecha)
            personas_total[person_id] += conteo

    fechas_ordenadas = sorted(fechas)
    personas_ordenadas = [pid for pid, _ in sorted(personas_total.items(), key=lambda x: (-x[1], x[0]))]

    return registros, agg, fechas_ordenadas, personas_ordenadas, personas_total

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

def construir_html(registros, agg, fechas, personas, personas_total):
    """Construye el HTML completo del dashboard."""
    total_registros = sum(r["conteo"] for r in registros) if registros else 0
    total_fechas = len(set(r["fecha"] for r in registros)) if registros else 0
    total_personas = len(set(r["person_id"] for r in registros)) if registros else 0

    conteo_por_fecha = defaultdict(int)
    for r in registros:
        conteo_por_fecha[r["fecha"]] += r["conteo"]

    labels_chart = list(sorted(conteo_por_fecha.keys()))
    data_chart = [conteo_por_fecha[f] for f in labels_chart]

    top_personas = sorted(personas_total.items(), key=lambda x: -x[1])[:10]
    labels_personas = [pid for pid, _ in top_personas]
    data_personas = [cnt for _, cnt in top_personas]

    filas_agg = []
    for (fecha, person_id), suma in sorted(agg.items(), key=lambda x: (x[0][0], -x[1])):
        filas_agg.append(
            f"<tr>"
            f"<td class='td'>{html_escape(fecha)}</td>"
            f"<td class='td mono'>{html_escape(person_id)}</td>"
            f"<td class='td num'>{suma}</td>"
            f"</tr>"
        )

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
      <div class="card"><h3>Personas únicas</h3><div class="val">{total_personas}</div></div>
    </div>

    <div class="section">
      <div class="toolbar"><h2 style="margin-right:auto">Detecciones por fecha</h2></div>
      <canvas id="deteccionesChart" height="100"></canvas>
    </div>

    <div class="section">
      <div class="toolbar"><h2 style="margin-right:auto">Detecciones por person_id (Top 10)</h2></div>
      <canvas id="personasChart" height="100"></canvas>
    </div>

    <div class="section">
      <div class="toolbar">
        <h2 style="margin-right:auto">Top personas detectadas</h2>
      </div>
      <ul class="list">{top_items}</ul>
    </div>

    <div class="section">
      <div class="toolbar">
        <h2 style="margin-right:auto">Tabla de detecciones (fecha · person_id · conteo)</h2>
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
        <h2 style="margin-right:auto">Tabla de detecciones (person_id × fecha)</h2>
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
        # Petición POST con los datos de autenticación
        auth_data = {
            "email": AUTH_EMAIL,
            "password": AUTH_PASSWORD
        }
        response = requests.post(AUTH_URL, json=auth_data, timeout=10)
        response.raise_for_status()
        
        # Extrae el nuevo token de la respuesta
        new_token = response.json().get("token")
        if new_token:
            TOKEN = new_token
            print("Token actualizado correctamente.")
            return True
        return False
    except requests.exceptions.RequestException as e:
        print(f"Error al obtener el token: {e}")
        return False

# --- Nueva ruta para las detecciones de la API ---
@app.route('/')
def mostrar_detecciones():
    """
    Obtiene los datos de la API, los guarda en un CSV y luego
    lee ese mismo CSV para construir y mostrar el dashboard.
    """
    global fecha_ultimo_check, TOKEN
    
    # Comprobar si ha pasado al menos un minuto o si el token es nulo
    if datetime.now() - fecha_ultimo_check > timedelta(minutes=1) or TOKEN is None:
        if not obtener_nuevo_token():
            # Si la autenticación falla, mostramos un error
            return "<h1>Error de autenticación</h1><p>No se pudo obtener un nuevo token.</p>", 500
    
    # A partir de aquí, el token ya está actualizado y listo para usarse
    
        try:
            from_str = (datetime.now() - timedelta(days=1)).strftime("2025-08-01T00:00:00.000Z")
            to_str = datetime.now().strftime("%Y-%m-%dT%H:%M:%S.000Z")

            params = {
                "from": from_str,
                "to": to_str,
                "page": 1,
                "perPage": PER_PAGE
            }
            headers = {"Authorization": f"Bearer {TOKEN}"}
            
            # Usar un tiempo de espera para evitar bloqueos
            response = requests.get(API_URL, headers=headers, params=params, timeout=10)
            response.raise_for_status()

            data = response.json()

            # Guardar en CSV
            with open(CSV_FILE, mode="w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["fecha", "person_id", "conteo"])

                for search in data.get("searches", []):
                    # El campo result puede ser None
                    if not search.get("result"):
                        continue
                    person_id = search["result"]["image"]["personId"]
                    timestamp = search["result"]["image"]["time"]
                    try:
                        fecha = datetime.strptime(timestamp[:8], "%Y%m%d").date()
                        writer.writerow([fecha, person_id, 1])
                    except (ValueError, IndexError):
                        # Ignora filas con timestamp inválido
                        continue
            
            fecha_ultimo_check = datetime.now()

        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 401:
                print("Token expirado. Intentando obtener uno nuevo...")
                # Si el token expira, forzamos la obtención de uno nuevo en la siguiente carga
                TOKEN = None
                return redirect(url_for('mostrar_detecciones'))
            else:
                error_message = f"Error de la API: {e}"
                return f"<h1>Error</h1><p>{error_message}</p>", 500
        except requests.exceptions.RequestException as e:
            error_message = f"Error al conectar con la API: {e}"
            return f"<h1>Error</h1><p>{error_message}</p>", 500
        except Exception as e:
            error_message = f"Ocurrió un error inesperado: {e}"
            return f"<h1>Error</h1><p>{error_message}</p>", 500      
              
    # Leer el CSV (ya sea actualizado o el existente) y construir el dashboard.
    registros, agg, fechas_ordenadas, personas_ordenadas, personas_total = leer_csv(CSV_FILE)
    html_dashboard = construir_html(registros, agg, fechas_ordenadas, personas_ordenadas, personas_total)
    
    return render_template_string(html_dashboard)


# Esta parte del código se asegura de que la aplicación solo se ejecute
# cuando el script es el programa principal.
if __name__ == '__main__':
    # Ejecuta el servidor de desarrollo de Flask en modo de depuración.
    app.run(debug=True)