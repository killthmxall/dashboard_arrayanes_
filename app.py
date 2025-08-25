from flask import Flask, send_from_directory, render_template_string
import os
import sys

# Agregar el directorio actual al path para importar tus scripts
sys.path.append(os.path.dirname(__file__))

# Importa las funciones de tus scripts
from server_verify import obtener_detecciones
from dashboard import leer_csv, construir_html

app = Flask(__name__)

# Configura las rutas para servir archivos estáticos (si los tuvieras)
@app.route('/<path:path>')
def serve_static(path):
    return send_from_directory('static', path)

@app.route('/')
def home():
    # 1. Obtener los últimos datos y actualizar el CSV
    obtener_detecciones()

    # 2. Leer el CSV y construir el HTML del dashboard
    try:
        registros, agg, fechas, personas, personas_total = leer_csv('detecciones_server.csv')
        dashboard_html = construir_html(registros, agg, fechas, personas, personas_total)
    except FileNotFoundError:
        return "El archivo CSV no fue encontrado. Asegúrate de que server_verify.py se haya ejecutado.", 404

    # 3. Renderizar el HTML
    return render_template_string(dashboard_html)

if __name__ == '__main__':
    # Asegúrate de que la aplicación esté lista para el despliegue
    # En producción, Gunicorn manejará esto.
    # En desarrollo, puedes usar app.run(debug=True)
    app.run(debug=True, host='0.0.0.0', port=os.environ.get("PORT", 5000))