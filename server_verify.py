import requests
from collections import defaultdict
from datetime import datetime, timedelta
import time

import csv
import os

# Configuración
API_URL = "https://dashboard-api.verifyfaces.com/companies/54/search/realtime"
TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ1c2VySWQiOjE4NCwiaWF0IjoxNzU2MTQ2MzA0LCJleHAiOjE3NTYxNDk5MDR9.fgUWRJgnhcvPkQ26ftIcEBtYzvxdpnobp_dE0UbX7rU"
PER_PAGE = 100

detecciones = defaultdict(lambda: defaultdict(int))

fecha_ultimo_check = datetime.now() - timedelta(days=1)

CSV_FILE = "detecciones_server.csv"

if not os.path.exists(CSV_FILE):
    with open(CSV_FILE, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["fecha", "person_id", "conteo"])

def obtener_detecciones():
    global fecha_ultimo_check
    from_str = fecha_ultimo_check.strftime("2025-08-01T00:00:00.000Z")
    to_str = datetime.now().strftime("%Y-%m-%dT%H:%M:%S.000Z")

    params = {
        "from": from_str,
        "to": to_str,
        "page": 2,
        "perPage": PER_PAGE
    }
    headers = {"Authorization": f"Bearer {TOKEN}"}

    response = requests.get(API_URL, headers=headers, params=params)
    data = response.json()

    # Guardar siempre CSV nuevo
    with open(CSV_FILE, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["fecha", "person_id", "conteo"])

        for search in data.get("searches", []):
            person_id = search["result"]["image"]["personId"]
            timestamp = search["result"]["image"]["time"]
            fecha = datetime.strptime(timestamp[:8], "%Y%m%d").date()
            detecciones[str(fecha)][person_id] += 1
            writer.writerow([fecha, person_id, 1])

    fecha_ultimo_check = datetime.now()

while True:
    obtener_detecciones()
    print("Conteo actual:", dict(detecciones))
    time.sleep(60)
