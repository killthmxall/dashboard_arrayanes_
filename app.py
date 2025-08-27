from flask import Flask, render_template_string, redirect, url_for, request
import requests
from collections import defaultdict, Counter
from datetime import datetime, timedelta, timezone
from dateutil import parser
import csv
import os
from pathlib import Path
import time
import math
import json
import random

#  Se crea una instancia de la aplicación Flask.
app = Flask(__name__)

# --- Variables Globales
detecciones = defaultdict(lambda: defaultdict(int))
fecha_ultimo_check = datetime.now() - timedelta(minutes=2)
CSV_FILE = Path("detecciones_server.csv")
API_URL = "https://dashboard-api.verifyfaces.com/companies/54/search/realtime"
AUTH_URL = "https://dashboard-api.verifyfaces.com/auth/login"
AUTH_EMAIL = "eangulo@blocksecurity.com.ec"
AUTH_PASSWORD = "Scarling//07052022.?"
TOKEN = None
PER_PAGE = 100
TOTAL_RECORDS_NEEDED = 100
gallery_cache = {}

# --- Funciones Auxiliares
def cargar_cache_galeria():

    # --- Se carga TODA la galería en la cache
    global TOKEN, gallery_cache

    if not TOKEN and not obtener_nuevo_token():
        print("Error: No se pudo obtener un token para la galería")
        return False

    base_url = "https://dashboard-api.verifyfaces.com/companies/54/galleries/531"
    headers = {"Authorization": f"Bearer {TOKEN}"}
    per_page = 100 
    page = 1

    gallery_cache.clear()
    total_cargados = 0

    try:
        while True:
            params = {"perPage": per_page, "page": page}
            resp = requests.get(base_url, headers=headers, params=params, timeout=10)

            # Si el token expiró, reintenta una única vez
            if resp.status_code == 401:
                if not obtener_nuevo_token():
                    print("401: no se pudo renovar el token.")
                    return False
                headers["Authorization"] = f"Bearer {TOKEN}"
                resp = requests.get(base_url, headers=headers, params=params, timeout=10)

            resp.raise_for_status()
            data = resp.json()

            images = data.get("images", [])
            if not images:
                break

            for image_data in images:
                original_filename = image_data.get("originalFilename")
                metadata = image_data.get("metadata")
                # Evita colisiones / entradas vacías
                if original_filename and isinstance(metadata, dict):
                    gallery_cache[original_filename] = metadata
                    total_cargados += 1

            # Si esta página trajo menos que el tope, ya estamos en la última
            if len(images) < per_page:
                break

            page += 1

        print(f"Galería cargada: {total_cargados} imágenes en caché.")
        return True

    except requests.exceptions.RequestException as e:
        print(f"Error al cargar la caché de la galería: {e}")
        return False


def leer_csv(ruta: Path):
    registros = []
    agg = defaultdict(int)
    agg_hora_latest = {}  # (fecha, person_id) -> "HH:MM:SS" más reciente
    fechas = set()
    personas_total = Counter()

    if not ruta.exists():
        return [], {}, {}, [], [], {}

    def _is_time_b_greater(a: str, b: str) -> bool:
        # compara lexicográficamente HH:MM:SS de forma segura
        return (b or "") > (a or "")

    with ruta.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            fecha = str(row.get("fecha", "")).strip()
            hora = str(row.get("hora", "")).strip()          # <- NUEVO
            person_id = str(row.get("nombre_persona", "")).strip()

            try:
                conteo = int(row.get("conteo", "1"))
            except ValueError:
                conteo = 1

            if not fecha or not person_id:
                continue

            # normaliza fecha si viniera con hora
            try:
                fecha_dt = datetime.fromisoformat(str(fecha).split(" ")[0])
                fecha = fecha_dt.date().isoformat()
            except Exception:
                pass

            registros.append({"fecha": fecha, "hora": hora, "person_id": person_id, "conteo": conteo})
            agg[(fecha, person_id)] += conteo
            fechas.add(fecha)
            personas_total[person_id] += conteo

            # guarda la hora más reciente por (fecha, persona)
            key = (fecha, person_id)
            if key not in agg_hora_latest or _is_time_b_greater(agg_hora_latest.get(key, ""), hora):
                agg_hora_latest[key] = hora

    fechas_ordenadas = sorted(fechas)
    personas_ordenadas = [pid for pid, _ in sorted(personas_total.items(), key=lambda x: (-x[1], x[0]))]

    return registros, agg, agg_hora_latest, fechas_ordenadas, personas_ordenadas, personas_total


def html_escape(s: str) -> str:
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )

def construir_html(registros, agg, agg_hora_latest, fechas, personas, personas_total, total_records_needed):
    # --- HTML del dashboard
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
    for (fecha, person_id), suma in sorted(agg.items(), key=lambda item: (item[0][0], agg_hora_latest.get((item[0][0], item[0][1]), "00:00:00"), item[1]), reverse=True):
        hora = agg_hora_latest.get((fecha, person_id), "")
        filas_agg.append(
            f"<tr>"
            f"<td class='td'>{html_escape(fecha)}</td>"
            f"<td class='td mono'>{html_escape(hora)}</td>"
            f"<td class='td mono'>{html_escape(person_id)}</td>"
            f"<td class='td num'>{suma}</td>"
            f"</tr>"
        )


    pivot = {pid: {f: 0 for f in fechas} for pid in personas}
    for (fecha, person_id), suma in agg.items():
        if person_id in pivot and fecha in pivot[person_id]:
            pivot[person_id][fecha] += suma

    fechas_ordenadas = sorted(fechas, reverse=True)

    th_fechas = "".join(f"<th class='th'>{html_escape(f)}</th>" for f in fechas_ordenadas)
    filas_pivot = []
    for pid in personas:
        celdas = "".join(f"<td class='td num'>{pivot[pid][f]}</td>" for f in fechas_ordenadas)
        filas_pivot.append(
            f"<tr><td class='td mono'>{html_escape(pid)}</td>{celdas}"
            f"<td class='td num strong'>{sum(pivot[pid].values())}</td></tr>"
        )

    top_items = "".join(
        f"<li><span class='mono'>{html_escape(pid)}</span> · <strong>{cnt}</strong></li>"
        for pid, cnt in top_personas
    )

    # Genera colores aleatorios para gráficos
    def generate_random_color():
        r = lambda: random.randint(0,255)
        return f'rgba({r()},{r()},{r()},.7)'

    # Datasets apilados (todas las personas)
    datasets_all = []
    for person_id in personas:
        person_data = [pivot.get(person_id, {}).get(fecha, 0) for fecha in fechas]
        datasets_all.append({
            'label': html_escape(person_id),
            'data': person_data,
            'backgroundColor': generate_random_color(),
            'stack': 'Stack 1'
        })
    datasets_all_json = json.dumps(datasets_all)

    # Datasets apilados (Top 10)
    datasets_top10 = []
    top_10_ids = [pid for pid, _ in top_personas]
    for person_id in top_10_ids:
        person_data = [pivot.get(person_id, {}).get(fecha, 0) for fecha in fechas]
        datasets_top10.append({
            'label': html_escape(person_id),
            'data': person_data,
            'backgroundColor': generate_random_color(),
            'stack': 'Stack 1'
        })
    datasets_top10_json = json.dumps(datasets_top10)

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
  .toolbar {{ display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin-bottom: 12px; }}
  .input {{ background: #0b1226; border: 1px solid var(--border); color: var(--text); padding: 10px 12px; border-radius: 12px; outline: none; }}
  .input.w100 {{ width: 100%; }}
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
  .filters {{ display:flex; gap:8px; flex-wrap:wrap; width:100%; }}
  .filters .group {{ display:flex; gap:8px; align-items:center; }}
  .filters label {{ font-size:12px; color:var(--muted); }}
  .date-input::-webkit-calendar-picker-indicator {{filter: invert(1); cursor: pointer;}}
</style>
</head>
<body>

  <div class="wrap">
    <span><img src="https://res.cloudinary.com/df5olfhrq/image/upload/v1756228647/logo_tpskcd.png" alt="BlockSecurity" style="height:80px; margin-bottom:16px;"></span> <span style="padding: 5px"> <img src="https://arrayanes.com/wp-content/uploads/2025/05/LOGO-ARRAYANES-1024x653.webp" alt="Arrayanes" style="height:80px; margin-bottom:16px;"><h1>Dashboard de detecciones Arrayanes Country Club</h1>
    <div class="grid cards">
      <div class="card"><h3>Registros totales</h3><div class="val">{total_registros}</div></div>
      <div class="card"><h3>Fechas únicas</h3><div class="val">{total_fechas}</div></div>
      <div class="card"><h3>Personas únicas</h3><div class="val">{total_personas}</div></div>
      <div class="card"><h3>Registros</h3><div class="val"><input type="number" id="num_registros" name="num_registros" class="input" value="{total_records_needed}" min="100" step="100" style="width:100px;"></div></div>
    </div>

    <!--
    <div class="section">
      <div class="toolbar">
        <h2 style="margin-right:auto">Detecciones por persona y fecha (últimos {total_records_needed} registros)</h2>
        <label for="num_registros" class="hint">Mostrar:</label>
      </div>
      <canvas id="allPersonsChart" height="100"></canvas>
    </div>
    -->

    <div class="section">
      <div class="toolbar"><h2 style="margin-right:auto">Detecciones por nombre (Top 10)</h2></div>
      <canvas id="personasChart" height="100"></canvas>
    </div>
    
    <div class="section">
      <div class="toolbar"><h2 style="margin-right:auto">Detecciones por persona y fecha (Top 10)</h2></div>
      <canvas id="top10Chart" height="100"></canvas>
    </div>

    <div class="section">
      <div class="toolbar">
        <h2 style="margin-right:auto">Top personas detectadas</h2>
      </div>
      <ul class="list">{top_items}</ul>
    </div>

    <!-- === TABLA AGREGADA CON NUEVOS FILTROS === -->
    <div class="section">
      <div class="toolbar" style="gap:12px;">
        <h2 style="margin-right:auto">Tabla de detecciones (fecha · nombre · conteo)</h2>
        <!-- Filtro libre existente -->
        <input class="input" id="filterAgg" placeholder="Filtra por texto (fecha o nombre)..." style="min-width:260px; display:none;">
      </div>

      <div class="filters" style="margin-bottom:8px;">
        <div class="group">
          <label for="dateStart" class="date-input">Desde</label>
          <input type="date" id="dateStart" class="input">
        </div>
        
        <div class="group">
          <label for="dateEnd">Hasta</label>
          <input type="date" id="dateEnd" class="input">
        </div>
        <div class="group" style="flex:1;">
          <label for="nameFilter">Persona</label>
          <input type="text" id="nameFilter" class="input w100" placeholder="Ej.: Juan Pérez">
        </div>
        <div class="group">
          <button id="clearFilters" class="input" style="cursor:pointer;">Limpiar</button>
        </div>
      </div>

      <div class="table-wrap">
        <table id="aggTable">
          <thead>
            <tr><th class="th">fecha</th><th class="th">hora</th><th class="th">nombre</th><th class="th right">conteo</th></tr>
          </thead>
          <tbody>{''.join(filas_agg)}</tbody>
        </table>
      </div>
      <div class="hint">Se agrupan múltiples filas del CSV ({html_escape(CSV_FILE.name)}) sumando su columna <code>conteo</code>. Los filtros de fecha y persona se aplican a las filas visibles.</div>
    </div>

    <!-- === TABLA PIVOT === -->
    <div class="section">
      <div class="toolbar">
        <h2 style="margin-right:auto">Tabla de detecciones (nombre × fecha)</h2>
        <input class="input" id="filterPivot" placeholder="Filtra por nombre...">
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

    <div class="footer">Generado {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</div>
  </div>

<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<script>
  // --- Filtro libre (texto contiene) para tabla agregada
  (function(){{
    const input = document.getElementById('filterAgg');
    const tbody = document.querySelector('#aggTable tbody');
    input.addEventListener('input', function(){{
      const q = this.value.toLowerCase();
      for (const tr of tbody.rows) {{
        const txt = tr.innerText.toLowerCase();
        tr.style.display = txt.includes(q) ? '' : 'none';
      }}
      // Al usar filtro libre, también respetamos filtros específicos si existen
      applySpecificFilters();
    }});
  }})();

  // --- Filtro tabla pivot por nombre
  (function(){{
    const input = document.getElementById('filterPivot');
    const tbody = document.querySelector('#pivotTable tbody');
    input.addEventListener('input', function(){{
      const q = this.value.toLowerCase();
      for (const tr of tbody.rows) {{
        const firstCell = tr.cells[0].innerText.toLowerCase();
        tr.style.display = firstCell.includes(q) ? '' : 'none';
      }}
    }});
  }})();

  // --- NUEVOS FILTROS: fecha desde/hasta + persona para tabla agregada
  (function(){{
    const tbody = document.querySelector('#aggTable tbody');
    const dateStart = document.getElementById('dateStart');
    const dateEnd = document.getElementById('dateEnd');
    const nameFilter = document.getElementById('nameFilter');
    const clearBtn = document.getElementById('clearFilters');

    function normalizeDateStr(d) {{
      // Espera formato YYYY-MM-DD; devuelve Date o null
      if (!d) return null;
      const parts = d.split('-');
      if (parts.length !== 3) return null;
      const year = parseInt(parts[0],10);
      const month = parseInt(parts[1],10)-1;
      const day = parseInt(parts[2],10);
      const dt = new Date(Date.UTC(year, month, day));
      return isNaN(dt.getTime()) ? null : dt;
    }}

    function parseCellDateStr(s) {{
      // La celda viene en ISO (YYYY-MM-DD)
      return normalizeDateStr(s.trim());
    }}

    function applySpecificFilters() {{
      const start = normalizeDateStr(dateStart.value);
      const end = normalizeDateStr(dateEnd.value);
      const nameQ = nameFilter.value.toLowerCase();

      for (const tr of tbody.rows) {{
        const cellDateStr = tr.cells[0].innerText || ''; // fecha
        const cellNameStr = tr.cells[2].innerText || ''; // nombre
        const rowDate = parseCellDateStr(cellDateStr);
        const nameOk = !nameQ || cellNameStr.toLowerCase().includes(nameQ);

        // Si hay rango de fechas, evaluar
        let dateOk = true;
        if (start && (!rowDate || rowDate < start)) dateOk = false;
        if (end) {{
          // end inclusive: ajustar a fin del día UTC sumando 23:59:59
          const endAdj = new Date(end.getTime() + 24*60*60*1000 - 1);
          if (!rowDate || rowDate > endAdj) dateOk = false;
        }}

        // También respetar el filtro libre si está activo
        const freeQ = (document.getElementById('filterAgg').value || '').toLowerCase();
        const freeOk = !freeQ || tr.innerText.toLowerCase().includes(freeQ);

        tr.style.display = (nameOk && dateOk && freeOk) ? '' : 'none';
      }}
    }}

    dateStart.addEventListener('change', applySpecificFilters);
    dateEnd.addEventListener('change', applySpecificFilters);
    nameFilter.addEventListener('input', applySpecificFilters);

    clearBtn.addEventListener('click', function(){{
      dateStart.value = '';
      dateEnd.value = '';
      nameFilter.value = '';
      document.getElementById('filterAgg').value = '';
      applySpecificFilters();
    }});

    // Inicial
    applySpecificFilters();
  }})();

  // --- Cambiar número de registros (recarga con query param)
  document.getElementById('num_registros').addEventListener('change', function(){{
    window.location.href = '/?records=' + this.value;
  }});

  /* 
  // --- Gráfico de barras apiladas (todas)
  (function(){{
    const ctx = document.getElementById('allPersonsChart').getContext('2d');
    new Chart(ctx, {{
      type: 'bar',
      data: {{
        labels: {labels_chart},
        datasets: {datasets_all_json}
      }},
      options: {{
        responsive: true,
        scales: {{
          x: {{ stacked: true }},
          y: {{
            stacked: true,
            beginAtZero: true,
            ticks: {{ precision:0 }}
          }}
        }}
      }}
    }});
  }})();*/

  // --- Gráfico de barras apiladas (Top 10)
  (function(){{
    const ctx = document.getElementById('top10Chart').getContext('2d');
    new Chart(ctx, {{
      type: 'bar',
      data: {{
        labels: {labels_chart},
        datasets: {datasets_top10_json}
      }},
      options: {{
        responsive: true,
        scales: {{
          x: {{ stacked: true }},
          y: {{
            stacked: true,
            beginAtZero: true,
            ticks: {{ precision:0 }}
          }}
        }}
      }}
    }});
  }})();

  // --- Gráfico Top 10 (barras horizontales)
  (function(){{
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
        indexAxis: 'y',
        scales: {{
          x: {{
            beginAtZero: true,
            ticks: {{ precision:0 }}
          }}
        }}
      }}
    }});
  }})();
</script>
</body>
</html>
"""


def obtener_nuevo_token():
  
    # --- Se conecta a la API de autenticación y actualiza el token global
    global TOKEN
    try:
        # Se realiza un POST con los datos de autenticación
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
      
# --- Ruta principal que muestra el dashboard
@app.route('/')

# --- Función principal que maneja la lógica del dashboard
def mostrar_detecciones():
    global fecha_ultimo_check, TOKEN, gallery_cache
    
    # Obtener el número de registros desde la URL o en caso de no haber usar el valor predeterminado
    try:
        total_records_needed = int(request.args.get('records', TOTAL_RECORDS_NEEDED))
    except (ValueError, TypeError):
        total_records_needed = TOTAL_RECORDS_NEEDED

    if total_records_needed < PER_PAGE:
        total_records_needed = PER_PAGE
    
    if datetime.now() - fecha_ultimo_check > timedelta(minutes=1) or not TOKEN:
        if not obtener_nuevo_token():
            return "<h1>Error de autenticación</h1><p>No se pudo obtener un nuevo token.</p>", 500
        
        # Cargar el caché de la galería
        if not cargar_cache_galeria():
            return "<h1>Error de la API</h1><p>No se pudieron obtener los datos de la galería.</p>", 500
        
        all_searches = []
        headers = {"Authorization": f"Bearer {TOKEN}"}
        
        try:
            from_dt_utc = datetime.now(timezone.utc) - timedelta(days=1)
            to_dt_utc   = datetime.now(timezone.utc)
            
            from_str = from_dt_utc.strftime("2025-08-01T01:00:00.000Z")
            to_str   = to_dt_utc.strftime("%Y-%m-%dT%H:%M:%S.000Z")
            
            num_pages = math.ceil(total_records_needed / PER_PAGE)
            
            for page_num in range(1, num_pages + 1):
                params = {
                    "from": from_str,
                    "to": to_str,
                    "page": page_num,
                    "perPage": PER_PAGE
                }
                response = requests.get(API_URL, headers=headers, params=params, timeout=10)
                response.raise_for_status()
                data = response.json()
                
                searches_on_page = data.get("searches", [])
                all_searches.extend(searches_on_page)
                
                if len(searches_on_page) < PER_PAGE:
                    break

            all_searches = all_searches[:total_records_needed]
            
            print(f"Total de registros obtenidos: {len(all_searches)}")
            
            with open(CSV_FILE, mode="w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["fecha", "hora", "nombre_persona", "conteo"])

                for search in all_searches:
                    if not search.get("payload") or not search["payload"].get("image"):
                        continue
                    
                    original_filename = search["payload"]["image"].get("originalFilename")
                    ts_raw = search["result"]["image"]["time"]  # ejemplo: "20250826232714.945"
                    
                    metadata = gallery_cache.get(original_filename, {})
                    person_name = metadata.get("name", "Nombre Desconocido")

                    try:
                        dt_utc  = datetime.strptime(ts_raw, "%Y%m%d%H%M%S.%f")  # si el 'time' está en UTC
                        dt_local = dt_utc - timedelta(hours=5) 
                        fecha_str = dt_local.date().isoformat()
                        hora_str  = dt_local.strftime("%H:%M:%S")
                        writer.writerow([fecha_str, hora_str, person_name, 1])
                    except (ValueError, IndexError, TypeError):
                        continue

            
            fecha_ultimo_check = datetime.now()

        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 401:
                print("Token expirado. Intentando obtener uno nuevo...")
                TOKEN = None
                return redirect(url_for('mostrar_detecciones', records=total_records_needed))
            else:
                error_message = f"Error de la API: {e}"
                return f"<h1>Error</h1><p>{error_message}</p>", 500
        except requests.exceptions.RequestException as e:
            error_message = f"Error al conectar con la API: {e}"
            return f"<h1>Error</h1><p>{error_message}</p>", 500
        except Exception as e:
            error_message = f"Ocurrió un error inesperado: {e}"
            return f"<h1>Error</h1><p>{error_message}</p>", 500     
            
    registros, agg, agg_hora_latest, fechas_ordenadas, personas_ordenadas, personas_total = leer_csv(CSV_FILE)
    html_dashboard = construir_html(registros, agg, agg_hora_latest, fechas_ordenadas, personas_ordenadas, personas_total, total_records_needed)

    return render_template_string(html_dashboard)

def obtener_imagenes_galeria():
    global TOKEN
    
    if not TOKEN:
        if not obtener_nuevo_token():
            print("Error: No se pudo obtener un token de autenticación.")
            return

    gallery_url = "https://dashboard-api.verifyfaces.com/companies/54/galleries/531"
    headers = {"Authorization": f"Bearer {TOKEN}"}
    params = {"perPage": 100, "page": 1}

    try:
        print("Haciendo llamada a la API de la galería...")
        response = requests.get(gallery_url, headers=headers, params=params, timeout=10)
        response.raise_for_status()

        data = response.json()
        print("Respuesta de la API de la galería:")
        
    except requests.exceptions.HTTPError as e:
        print(f"Error HTTP al obtener imágenes: {e.response.status_code} - {e.response.text}")
    except requests.exceptions.RequestException as e:
        print(f"Error de conexión al obtener imágenes: {e}")
    except Exception as e:
        print(f"Ocurrió un error inesperado: {e}")


if __name__ == '__main__':
    obtener_imagenes_galeria()
    app.run(debug=True)