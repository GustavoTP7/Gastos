# Mis Gastos — Streamlit

Aplicación local de control y análisis de gastos personales.

## Requisitos
- Python 3.10 o superior recomendado.
- pip.

## Instalación
```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate
pip install -r requirements.txt
```

## Ejecutar
```bash
streamlit run app.py
```

Se abrirá en el navegador. La base de datos SQLite se crea automáticamente en `data/gastos.db`.

## Incluye
Registro persistente, categorías y métodos personalizados, dashboard, historial con filtros, análisis, resúmenes mensual/anual, presupuestos, recurrentes, gráficos, exportación CSV/Excel/PDF y respaldo JSON.

## Notas
- Moneda por defecto: soles peruanos (S/).
- Los datos se almacenan localmente; no se necesita servidor externo.
- Para seguridad, conserva una copia del archivo `data/gastos.db` y/o el backup JSON.
