from flask import Flask, render_template_string, redirect, url_for, request, jsonify
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
AUTH_EMAIL = "eangulo@blocksecurity.com.ec"   # Sugerencia: usa variables de entorno en producción
AUTH_PASSWORD = "Scarling//07052022.?"        # Sugerencia: usa variables de entorno en producción
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
            hora = str(row.get("hora", "")).strip()
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

def construir_html(registros, agg, agg_hora_latest, fechas, personas, personas_total, total_records_needed, last_ts_iso: str, percent_gallery: float, recognized_in_gallery: int, total_gallery_persons: int, ingresos_hoy: int):

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
            f"<tr data-fecha='{html_escape(fecha)}' data-hora='{html_escape(hora)}'>"
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

    top_items = "".join(
        f"<li><span class='mono'>{html_escape(pid)}</span> · <strong>{cnt}</strong></li>"
        for pid, cnt in top_personas
    )

    # Genera colores aleatorios para gráficos
    def generate_random_color():
        r = lambda: random.randint(0,255)
        return f'rgba({r()},{r()},{r()},.7)'

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

    # JS necesita conocer el total actual y el último TS
    js_current_total = total_registros
    js_last_ts = json.dumps(last_ts_iso)

    return f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<title>Dashboard de Detecciones</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
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

  /* === NUEVO: Animación de parpadeo de fondo y resaltado === */
  @keyframes bg-flash {{
    0%   {{ background: #0b1020; }}
    20%  {{ background: #103b2b; }}
    50%  {{ background: #0b1020; }}
    70%  {{ background: #3b1010; }}
    100% {{ background: #0b1020; }}
  }}
  body.flash {{ animation: bg-flash 1.2s ease-in-out 1; }}

  #newAlert {{
    position: fixed; z-index: 9999; left: 50%; top: 16px; transform: translateX(-50%);
    background: #12b981; color: #08111e; border: 1px solid #0ea371;
    padding: 10px 14px; border-radius: 999px; font-weight: 700; box-shadow: 0 10px 20px rgba(0,0,0,.25);
    opacity: 0; pointer-events: none; transition: opacity .25s ease, transform .25s ease;
  }}
  #newAlert.show {{ opacity: 1; transform: translateX(-50%) translateY(2px); }}

  .tr-new {{
    animation: pulseRow 1.5s ease-in-out 1;
    background: rgba(18, 185, 129, .15);
  }}
  @keyframes pulseRow {{
    0% {{ background: rgba(18,185,129,.4); }}
    100% {{ background: rgba(18,185,129,.15); }}
  }}
</style>
</head>
<body>

  <div id="newAlert">¡Nueva detección!</div>

  <div class="wrap">
    <span><img src="https://res.cloudinary.com/df5olfhrq/image/upload/v1756228647/logo_tpskcd.png" alt="BlockSecurity" style="height:80px; margin-bottom:16px;"></span> <span style="padding: 5px"> <img src="https://arrayanes.com/wp-content/uploads/2025/05/LOGO-ARRAYANES-1024x653.webp" alt="Arrayanes" style="height:80px; margin-bottom:16px;"><h1>Dashboard de detecciones Arrayanes Country Club</h1>
    <div class="grid cards">
      <!-- 1) Cobertura de galería -->
      <div class="card">
        <h3>Cobertura de galería</h3>
        <div class="val">{percent_gallery:.1f}%</div>
        <div class="muted">{recognized_in_gallery}/{total_gallery_persons} personas reconocidas</div>
      </div>

      <!-- 2) Ingresos hoy -->
      <div class="card">
        <h3>Ingresos hoy</h3>
        <div class="val">{ingresos_hoy}</div>
        <div class="muted">Suma de detecciones de </div><div>{datetime.now().date().isoformat()}</div>
      </div>

      <!-- 3) Personas únicas (puedes cambiar por otra métrica si prefieres) -->
      <div class="card">
        <h3>Personas únicas</h3>
        <div class="val">{total_personas}</div>
        <div class="muted">Total de personas detectadas en el rango de registros</div>
      </div>
      <div class="card"><h3>Registros</h3><div class="val"><input type="number" id="num_registros" name="num_registros" class="input" value="{total_records_needed}" min="100" step="100" style="width:100px;"></div></div>
    </div>
    
    

    <div class="section">
      <div class="toolbar"><h2 style="margin-right:auto">Detecciones por nombre (Top 10 personas)</h2></div>
      <canvas id="personasChart" height="100"></canvas>
    </div>

    <div class="section">
      <div class="toolbar"><h2 style="margin-right:auto">Detecciones por persona y fecha (Top 10 personas)</h2></div>
      <canvas id="top10Chart" height="100"></canvas>
    </div>

    <div class="section">
      <div class="toolbar">
        <h2 style="margin-right:auto">Top personas detectadas</h2>
      </div>
      <ul class="list">{top_items}</ul>
    </div>

    <!-- === TABLA AGREGADA CON FILTROS === -->
    <div class="section">
      <div class="toolbar" style="gap:12px;">
        <h2 style="margin-right:auto">Tabla de detecciones (fecha · nombre · conteo)</h2>
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

    <div class="footer">Generado {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</div>
  </div>

<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>

<script>
  // === Estado inicial desde servidor (para detección de cambios) ===
  let CURRENT_TOTAL = {js_current_total};
  let CURRENT_LAST_TS = {js_last_ts};

  // --- Filtro libre (texto contiene) para tabla agregada
  (function(){{
    const input = document.getElementById('filterAgg');
    const tbody = document.querySelector('#aggTable tbody');
    input && input.addEventListener('input', function(){{
      const q = this.value.toLowerCase();
      for (const tr of tbody.rows) {{
        const txt = tr.innerText.toLowerCase();
        tr.style.display = txt.includes(q) ? '' : 'none';
      }}
      applySpecificFilters();
    }});
  }})();

  // --- Filtro tabla pivot por nombre
  (function(){{
    const input = document.getElementById('filterPivot');
    const tbody = document.querySelector('#pivotTable tbody');
    input && input.addEventListener('input', function(){{
      const q = this.value.toLowerCase();
      for (const tr of tbody.rows) {{
        const firstCell = tr.cells[0].innerText.toLowerCase();
        tr.style.display = firstCell.includes(q) ? '' : 'none';
      }}
    }});
  }})();

  // --- Filtros: fecha desde/hasta + persona para tabla agregada
  (function(){{
    const tbody = document.querySelector('#aggTable tbody');
    const dateStart = document.getElementById('dateStart');
    const dateEnd = document.getElementById('dateEnd');
    const nameFilter = document.getElementById('nameFilter');
    const clearBtn = document.getElementById('clearFilters');

    function normalizeDateStr(d) {{
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
      return normalizeDateStr(s.trim());
    }}

    function applySpecificFilters() {{
      const start = normalizeDateStr(dateStart.value);
      const end = normalizeDateStr(dateEnd.value);
      const nameQ = (nameFilter.value || '').toLowerCase();

      for (const tr of tbody.rows) {{
        const cellDateStr = tr.cells[0].innerText || '';
        const cellNameStr = tr.cells[2].innerText || '';
        const rowDate = parseCellDateStr(cellDateStr);
        const nameOk = !nameQ || cellNameStr.toLowerCase().includes(nameQ);

        let dateOk = true;
        if (start && (!rowDate || rowDate < start)) dateOk = false;
        if (end) {{
          const endAdj = new Date(end.getTime() + 24*60*60*1000 - 1);
          if (!rowDate || rowDate > endAdj) dateOk = false;
        }}

        const freeQ = (document.getElementById('filterAgg')?.value || '').toLowerCase();
        const freeOk = !freeQ || tr.innerText.toLowerCase().includes(freeQ);

        tr.style.display = (nameOk && dateOk && freeOk) ? '' : 'none';
      }}
    }}

    dateStart && dateStart.addEventListener('change', applySpecificFilters);
    dateEnd && dateEnd.addEventListener('change', applySpecificFilters);
    nameFilter && nameFilter.addEventListener('input', applySpecificFilters);
    clearBtn && clearBtn.addEventListener('click', function(){{
      dateStart.value = '';
      dateEnd.value = '';
      nameFilter.value = '';
      const fa = document.getElementById('filterAgg');
      if (fa) fa.value = '';
      applySpecificFilters();
    }});

    applySpecificFilters();
  }})();

  // --- Cambiar número de registros (recarga con query param)
  document.getElementById('num_registros').addEventListener('change', function(){{
    window.location.href = '/?records=' + this.value;
  }});

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

  // === NUEVO: utilidades TS y visual alert ===
  function parseIsoLocal(s) {{
    if (!s) return null;
    const d = new Date(s);
    return isNaN(d.getTime()) ? null : d;
  }}

  function rowToIsoString(tr) {{
    const f = tr.getAttribute('data-fecha') || '';
    const h = tr.getAttribute('data-hora') || '';
    if (!f || !h) return '';
    return f + 'T' + h;
  }}

  function triggerVisualAlert() {{
    const alertEl = document.getElementById('newAlert');
    document.body.classList.add('flash');
    alertEl.classList.add('show');
    setTimeout(() => {{
      alertEl.classList.remove('show');
      document.body.classList.remove('flash');
    }}, 1200);
  }}

  // === NUEVO: resaltar filas nuevas tras recarga
  (function highlightNewRowsAfterReload(){{
    const threshold = localStorage.getItem('highlightAfterReloadGT');
    if (!threshold) return;
    localStorage.removeItem('highlightAfterReloadGT');
    const tbody = document.querySelector('#aggTable tbody');
    if (!tbody) return;

    const thr = parseIsoLocal(threshold);
    for (const tr of tbody.rows) {{
      const iso = rowToIsoString(tr);
      const dt = parseIsoLocal(iso);
      if (thr && dt && dt > thr) {{
        tr.classList.add('tr-new');
      }}
    }}
  }})();

  // === NUEVO: Polling de cambios
  async function pollStats() {{
    try {{
      const r = await fetch('/api/stats', {{ cache: 'no-store' }});
      if (!r.ok) throw new Error('HTTP ' + r.status);
      const data = await r.json();
      const newTotal = Number(data.total_registros || 0);
      const newLast = data.ultima_ts_iso || "";

      if (newTotal > CURRENT_TOTAL) {{
        // Guardamos umbral para resaltar filas posteriores al último visto
        if (CURRENT_LAST_TS) {{
          localStorage.setItem('highlightAfterReloadGT', CURRENT_LAST_TS);
        }}
        triggerVisualAlert();

        CURRENT_TOTAL = newTotal;
        CURRENT_LAST_TS = newLast;

        setTimeout(() => {{ window.location.reload(); }}, 1000);
      }} else {{
        if (newLast) CURRENT_LAST_TS = newLast;
      }}
    }} catch (e) {{
      // Silencioso
    }}
  }}

  // Inicia polling cada 3s
  setInterval(pollStats, 3000);
</script>
</body>
</html>
"""


def obtener_nuevo_token():
    # --- Se conecta a la API de autenticación y actualiza el token global
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

# --- Endpoint ligero para polling del front
@app.route('/api/stats')
def api_stats():
  
    registros, _, _, _, _, _ = leer_csv(CSV_FILE)
    total = sum((r.get("conteo", 0) or 0) for r in registros) if registros else 0

    ultima = None
    for r in registros:
        f = r.get("fecha") or ""
        h = r.get("hora") or ""
        if f and h:
            try:
                dt = datetime.fromisoformat(f)
                hh, mm, ss = h.split(":")
                dt = dt.replace(hour=int(hh), minute=int(mm), second=int(ss))
                if (ultima is None) or (dt > ultima):
                    ultima = dt
            except Exception:
                continue

    ultima_iso = ultima.isoformat() if ultima else ""
    return jsonify({"total_registros": total, "ultima_ts_iso": ultima_iso})

# --- Ruta principal que muestra el dashboard
@app.route('/')
def mostrar_detecciones():
    global fecha_ultimo_check, TOKEN, gallery_cache

    # Obtener el número de registros desde la URL o predeterminado
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

            from_str = from_dt_utc.strftime("2025-08-01T01:00:00.000Z")   # Ajusta ventana si lo deseas
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

    # --- Carga CSV para construir HTML y calcular último TS
    registros, agg, agg_hora_latest, fechas_ordenadas, personas_ordenadas, personas_total = leer_csv(CSV_FILE)

    # Último timestamp
    last_ts = None
    for r in registros:
        f = r.get("fecha") or ""
        h = r.get("hora") or ""
        if f and h:
            try:
                dt = datetime.fromisoformat(f)
                hh, mm, ss = h.split(":")
                dt = dt.replace(hour=int(hh), minute=int(mm), second=int(ss))
                if (last_ts is None) or (dt > last_ts):
                    last_ts = dt
            except Exception:
                pass
    last_ts_iso = last_ts.isoformat() if last_ts else ""

    # 1) Cobertura de galería
    gallery_names = set()
    try:
        for meta in (gallery_cache or {}).values():
            name = (meta or {}).get("name")
            if name:
                gallery_names.add(name)
    except Exception:
        pass

    recognized_names = set(personas_ordenadas or [])
    recognized_in_gallery = len(recognized_names.intersection(gallery_names))
    total_gallery_persons = len(gallery_names)
    percent_gallery = (recognized_in_gallery / total_gallery_persons * 100.0) if total_gallery_persons else 0.0

    hoy_iso = datetime.now().date().isoformat()
    ingresos_hoy = sum((r.get("conteo", 0) or 0) for r in registros if r.get("fecha") == hoy_iso)

    html_dashboard = construir_html(
        registros, agg, agg_hora_latest, fechas_ordenadas, personas_ordenadas, personas_total,
        total_records_needed, last_ts_iso,
        # === NUEVO: argumentos para cards ===
        percent_gallery, recognized_in_gallery, total_gallery_persons, ingresos_hoy
    )

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
        # print(json.dumps(data, indent=2))  # opcional

    except requests.exceptions.HTTPError as e:
        print(f"Error HTTP al obtener imágenes: {e.response.status_code} - {e.response.text}")
    except requests.exceptions.RequestException as e:
        print(f"Error de conexión al obtener imágenes: {e}")
    except Exception as e:
        print(f"Ocurrió un error inesperado: {e}")


if __name__ == '__main__':
    obtener_imagenes_galeria()
    app.run(debug=True)
