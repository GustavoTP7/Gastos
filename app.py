import sqlite3
import io
import json
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet


# ============================================================
# CONFIGURACIÓN
# ============================================================

BASE = Path(__file__).resolve().parent

# IMPORTANTE:
# Streamlit Cloud puede no tener creada la carpeta "data".
# La creamos automáticamente antes de utilizar SQLite.
DATA_DIR = BASE / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

DB = DATA_DIR / "gastos.db"


DEFAULT_CATEGORIES = [
    "Alimentación",
    "Transporte",
    "Vivienda",
    "Servicios",
    "Educación",
    "Salud",
    "Entretenimiento",
    "Compras",
    "Ropa",
    "Tecnología",
    "Suscripciones",
    "Viajes",
    "Deudas",
    "Otros",
]

DEFAULT_METHODS = [
    "Efectivo",
    "Tarjeta de débito",
    "Tarjeta de crédito",
    "Transferencia",
    "Yape",
    "Plin",
    "Otro",
]

EXPENSE_TYPES = [
    "Necesario",
    "Opcional",
    "Extraordinario",
]


# ============================================================
# BASE DE DATOS
# ============================================================

def get_connection():
    """
    Crea una conexión segura con SQLite.
    La carpeta data se crea automáticamente.
    """

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(
        str(DB),
        timeout=10,
        check_same_thread=False
    )

    connection.row_factory = sqlite3.Row

    return connection


def execute(query, parameters=()):
    """
    Ejecuta INSERT, UPDATE o DELETE.
    """

    connection = get_connection()

    try:
        cursor = connection.cursor()
        cursor.execute(query, parameters)
        connection.commit()

        return cursor.lastrowid

    finally:
        connection.close()


def fetch_all(query, parameters=()):
    """
    Devuelve múltiples registros.
    """

    connection = get_connection()

    try:
        cursor = connection.cursor()
        cursor.execute(query, parameters)

        return cursor.fetchall()

    finally:
        connection.close()


def fetch_one(query, parameters=()):
    """
    Devuelve un registro.
    """

    connection = get_connection()

    try:
        cursor = connection.cursor()
        cursor.execute(query, parameters)

        return cursor.fetchone()

    finally:
        connection.close()


def initialize_database():

    connection = get_connection()

    try:

        cursor = connection.cursor()

        # Categorías
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                icon TEXT DEFAULT '💰',
                is_default INTEGER DEFAULT 0
            )
        """)

        # Subcategorías
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS subcategories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                UNIQUE(category_id, name),
                FOREIGN KEY(category_id)
                    REFERENCES categories(id)
                    ON DELETE CASCADE
            )
        """)

        # Métodos de pago
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS payment_methods (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                is_default INTEGER DEFAULT 0
            )
        """)

        # Gastos
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS expenses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                amount REAL NOT NULL,

                spent_at TEXT NOT NULL,

                spent_time TEXT,

                category_id INTEGER NOT NULL,

                subcategory_id INTEGER,

                description TEXT,

                payment_method_id INTEGER NOT NULL,

                expense_type TEXT NOT NULL,

                recurring INTEGER DEFAULT 0,

                tags TEXT DEFAULT '',

                created_at TEXT DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY(category_id)
                    REFERENCES categories(id),

                FOREIGN KEY(subcategory_id)
                    REFERENCES subcategories(id),

                FOREIGN KEY(payment_method_id)
                    REFERENCES payment_methods(id)
            )
        """)

        # Gastos recurrentes
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS recurring_expenses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                name TEXT NOT NULL,

                amount REAL NOT NULL,

                category_id INTEGER NOT NULL,

                frequency TEXT NOT NULL,

                start_date TEXT NOT NULL,

                next_payment TEXT NOT NULL,

                active INTEGER DEFAULT 1,

                FOREIGN KEY(category_id)
                    REFERENCES categories(id)
            )
        """)

        # Presupuestos
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS budgets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                month TEXT NOT NULL,

                category_id INTEGER,

                amount REAL NOT NULL,

                UNIQUE(month, category_id),

                FOREIGN KEY(category_id)
                    REFERENCES categories(id)
            )
        """)

        # Insertar categorías predeterminadas
        for category in DEFAULT_CATEGORIES:

            cursor.execute("""
                INSERT OR IGNORE INTO categories
                (name, icon, is_default)
                VALUES (?, ?, 1)
            """, (category, "💰"))

        # Insertar métodos predeterminados
        for method in DEFAULT_METHODS:

            cursor.execute("""
                INSERT OR IGNORE INTO payment_methods
                (name, is_default)
                VALUES (?, 1)
            """, (method,))

        connection.commit()

    finally:

        connection.close()


# Inicializar DB
initialize_database()


# ============================================================
# FUNCIONES DE DATOS
# ============================================================

def get_categories():

    rows = fetch_all("""
        SELECT *
        FROM categories
        ORDER BY name
    """)

    return pd.DataFrame([dict(row) for row in rows])


def get_payment_methods():

    rows = fetch_all("""
        SELECT *
        FROM payment_methods
        ORDER BY name
    """)

    return pd.DataFrame([dict(row) for row in rows])


def get_expenses():

    rows = fetch_all("""
        SELECT
            e.id,
            e.amount,
            e.spent_at,
            e.spent_time,
            e.description,
            e.expense_type,
            e.recurring,
            e.tags,

            c.name AS category,
            c.icon AS category_icon,

            s.name AS subcategory,

            pm.name AS payment_method

        FROM expenses e

        INNER JOIN categories c
            ON e.category_id = c.id

        LEFT JOIN subcategories s
            ON e.subcategory_id = s.id

        INNER JOIN payment_methods pm
            ON e.payment_method_id = pm.id

        ORDER BY
            e.spent_at DESC,
            e.id DESC
    """)

    return pd.DataFrame([dict(row) for row in rows])


def filter_period(df, start_date, end_date):

    if df.empty:
        return df.copy()

    result = df[
        (df["spent_at"] >= start_date.isoformat())
        &
        (df["spent_at"] <= end_date.isoformat())
    ]

    return result.copy()


def format_money(value):

    return f"S/ {float(value):,.2f}"


def percentage_change(current, previous):

    if previous == 0:

        if current == 0:
            return 0

        return None

    return ((current - previous) / previous) * 100


def get_period(period):

    today = date.today()

    if period == "Hoy":

        return today, today

    if period == "Ayer":

        yesterday = today - timedelta(days=1)

        return yesterday, yesterday

    if period == "Esta semana":

        start = today - timedelta(days=today.weekday())

        return start, today

    if period == "Este mes":

        return today.replace(day=1), today

    if period == "Mes anterior":

        current_month_start = today.replace(day=1)

        last_day_previous = current_month_start - timedelta(days=1)

        previous_start = last_day_previous.replace(day=1)

        return previous_start, last_day_previous

    if period == "Este año":

        return date(today.year, 1, 1), today

    if period == "Año anterior":

        return (
            date(today.year - 1, 1, 1),
            date(today.year - 1, 12, 31)
        )

    return today, today


# ============================================================
# CONFIGURACIÓN STREAMLIT
# ============================================================

st.set_page_config(
    page_title="Mis Gastos",
    page_icon="💸",
    layout="wide"
)


st.markdown("""
<style>

.block-container {
    padding-top: 1.5rem;
}

.metric-card {
    padding: 15px;
    border-radius: 15px;
    border: 1px solid rgba(128,128,128,0.25);
}

h1 {
    font-weight: 700;
}

</style>
""", unsafe_allow_html=True)


# ============================================================
# SIDEBAR
# ============================================================

if "page" not in st.session_state:

    st.session_state.page = "Dashboard"


with st.sidebar:

    st.title("💸 Mis Gastos")

    st.session_state.page = st.radio(
        "Navegación",

        [
            "Dashboard",
            "➕ Registrar gasto",
            "Historial",
            "Resumen mensual",
            "Resumen anual",
            "Análisis",
            "Presupuestos",
            "Recurrentes",
            "Categorías",
            "Métodos de pago",
            "Configuración"
        ]
    )

    st.divider()

    if st.button(
        "🔄 Actualizar",
        use_container_width=True
    ):

        st.rerun()


# ============================================================
# CARGAR DATOS
# ============================================================

expenses = get_expenses()
categories = get_categories()
payment_methods = get_payment_methods()

today = date.today()

month_start = today.replace(day=1)

previous_month_end = month_start - timedelta(days=1)

previous_month_start = previous_month_end.replace(day=1)


# ============================================================
# FORMULARIO DE GASTO
# ============================================================

def expense_form():

    categories = get_categories()

    methods = get_payment_methods()

    with st.form(
        "new_expense",
        clear_on_submit=True
    ):

        st.subheader("Nuevo gasto")

        col1, col2, col3 = st.columns(3)

        amount = col1.number_input(
            "Monto (S/)",
            min_value=0.01,
            value=1.00,
            step=0.50
        )

        expense_date = col2.date_input(
            "Fecha",
            value=today
        )

        expense_time = col3.text_input(
            "Hora (opcional)",
            placeholder="Ej. 14:30"
        )

        category_names = categories["name"].tolist()

        category = col1.selectbox(
            "Categoría",
            category_names
        )

        category_id = int(
            categories.loc[
                categories["name"] == category,
                "id"
            ].iloc[0]
        )

        subcategories = fetch_all("""
            SELECT *
            FROM subcategories
            WHERE category_id = ?
            ORDER BY name
        """, (category_id,))

        subcategory_names = ["—"]

        subcategory_names += [
            row["name"]
            for row in subcategories
        ]

        subcategory = col2.selectbox(
            "Subcategoría",
            subcategory_names
        )

        description = col3.text_input(
            "Descripción / nota"
        )

        method_names = methods["name"].tolist()

        payment_method = col1.selectbox(
            "Método de pago",
            method_names
        )

        expense_type = col2.selectbox(
            "Tipo de gasto",
            EXPENSE_TYPES
        )

        recurring = col3.checkbox(
            "Gasto recurrente"
        )

        tags = st.text_input(
            "Etiquetas",
            placeholder="Ej. comida, colegio, transporte"
        )

        submitted = st.form_submit_button(
            "💾 Guardar gasto",
            type="primary",
            use_container_width=True
        )

    if submitted:

        if amount <= 0:

            st.error(
                "El monto debe ser mayor que cero."
            )

            return

        if not expense_date:

            st.error(
                "Debes seleccionar una fecha."
            )

            return

        if not category:

            st.error(
                "Debes seleccionar una categoría."
            )

            return

        subcategory_id = None

        if subcategory != "—":

            subcategory_id = next(
                (
                    row["id"]
                    for row in subcategories
                    if row["name"] == subcategory
                ),
                None
            )

        payment_method_id = int(
            methods.loc[
                methods["name"] == payment_method,
                "id"
            ].iloc[0]
        )

        execute("""
            INSERT INTO expenses (
                amount,
                spent_at,
                spent_time,
                category_id,
                subcategory_id,
                description,
                payment_method_id,
                expense_type,
                recurring,
                tags
            )

            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            amount,
            expense_date.isoformat(),
            expense_time,
            category_id,
            subcategory_id,
            description,
            payment_method_id,
            expense_type,
            int(recurring),
            tags
        ))

        st.success(
            "✅ Gasto guardado correctamente."
        )

        st.rerun()


# ============================================================
# DASHBOARD
# ============================================================

if st.session_state.page == "Dashboard":

    st.title("📊 Dashboard")

    current_month = filter_period(
        expenses,
        month_start,
        today
    )

    previous_month = filter_period(
        expenses,
        previous_month_start,
        previous_month_end
    )

    current_day = filter_period(
        expenses,
        today,
        today
    )

    week_start, week_end = get_period(
        "Esta semana"
    )

    current_week = filter_period(
        expenses,
        week_start,
        week_end
    )

    current_year = filter_period(
        expenses,
        date(today.year, 1, 1),
        today
    )

    col1, col2, col3, col4 = st.columns(4)

    col1.metric(
        "💰 Hoy",
        format_money(
            current_day["amount"].sum()
        )
    )

    col2.metric(
        "📅 Esta semana",
        format_money(
            current_week["amount"].sum()
        )
    )

    col3.metric(
        "🗓️ Este mes",
        format_money(
            current_month["amount"].sum()
        )
    )

    col4.metric(
        "📈 Este año",
        format_money(
            current_year["amount"].sum()
        )
    )

    st.divider()

    col1, col2, col3, col4 = st.columns(4)

    col1.metric(
        "Cantidad de gastos",
        len(expenses)
    )

    if not current_month.empty:

        category_totals = (
            current_month
            .groupby("category")["amount"]
            .sum()
            .sort_values(ascending=False)
        )

        highest_category = category_totals.index[0]

        lowest_category = category_totals.index[-1]

        col2.metric(
            "Mayor categoría",
            highest_category
        )

        col3.metric(
            "Menor categoría",
            lowest_category
        )

        average_daily = (
            current_month["amount"].sum()
            / today.day
        )

        col4.metric(
            "Promedio diario",
            format_money(average_daily)
        )

    else:

        col2.metric(
            "Mayor categoría",
            "—"
        )

        col3.metric(
            "Menor categoría",
            "—"
        )

        col4.metric(
            "Promedio diario",
            "S/ 0.00"
        )

    current_total = current_month["amount"].sum()

    previous_total = previous_month["amount"].sum()

    change = percentage_change(
        current_total,
        previous_total
    )

    if change is not None:

        if change > 0:

            st.warning(
                f"📈 Este mes estás gastando "
                f"**{change:.1f}% más** que el mes anterior."
            )

        elif change < 0:

            st.success(
                f"📉 Este mes estás gastando "
                f"**{abs(change):.1f}% menos** que el mes anterior."
            )

        else:

            st.info(
                "Tu gasto es igual al del mes anterior."
            )

    if current_month.empty:

        st.info(
            "Todavía no tienes gastos registrados este mes."
        )

    else:

        col1, col2 = st.columns(2)

        category_chart = (
            current_month
            .groupby("category", as_index=False)["amount"]
            .sum()
            .sort_values("amount", ascending=False)
        )

        col1.plotly_chart(
            px.pie(
                category_chart,
                names="category",
                values="amount",
                title="Distribución por categorías"
            ),
            use_container_width=True
        )

        daily_chart = (
            current_month
            .groupby("spent_at", as_index=False)["amount"]
            .sum()
        )

        col2.plotly_chart(
            px.bar(
                daily_chart,
                x="spent_at",
                y="amount",
                title="Gastos diarios"
            ),
            use_container_width=True
        )


# ============================================================
# REGISTRAR
# ============================================================

elif st.session_state.page == "➕ Registrar gasto":

    st.title("➕ Registrar gasto")

    expense_form()


# ============================================================
# HISTORIAL
# ============================================================

elif st.session_state.page == "Historial":

    st.title("📋 Historial de gastos")

    if expenses.empty:

        st.info(
            "Todavía no tienes gastos registrados."
        )

    else:

        col1, col2, col3 = st.columns(3)

        search = col1.text_input(
            "🔎 Buscar"
        )

        category_filter = col2.selectbox(
            "Categoría",
            ["Todas"] +
            sorted(
                expenses["category"]
                .dropna()
                .unique()
                .tolist()
            )
        )

        method_filter = col3.selectbox(
            "Método de pago",
            ["Todos"] +
            sorted(
                expenses["payment_method"]
                .dropna()
                .unique()
                .tolist()
            )
        )

        min_date = pd.to_datetime(
            expenses["spent_at"].min()
        ).date()

        max_date = today

        selected_range = st.date_input(
            "Rango de fechas",
            value=(min_date, max_date)
        )

        filtered = expenses.copy()

        if search:

            mask = (
                filtered
                .astype(str)
                .apply(
                    lambda column:
                    column.str.contains(
                        search,
                        case=False,
                        na=False
                    )
                )
                .any(axis=1)
            )

            filtered = filtered[mask]

        if category_filter != "Todas":

            filtered = filtered[
                filtered["category"]
                == category_filter
            ]

        if method_filter != "Todos":

            filtered = filtered[
                filtered["payment_method"]
                == method_filter
            ]

        if len(selected_range) == 2:

            start_date, end_date = selected_range

            filtered = filtered[
                (filtered["spent_at"] >= start_date.isoformat())
                &
                (filtered["spent_at"] <= end_date.isoformat())
            ]

        order = st.selectbox(
            "Ordenar",
            [
                "Más recientes",
                "Más antiguos",
                "Mayor monto",
                "Menor monto"
            ]
        )

        if order == "Más recientes":

            filtered = filtered.sort_values(
                ["spent_at", "id"],
                ascending=False
            )

        elif order == "Más antiguos":

            filtered = filtered.sort_values(
                ["spent_at", "id"]
            )

        elif order == "Mayor monto":

            filtered = filtered.sort_values(
                "amount",
                ascending=False
            )

        else:

            filtered = filtered.sort_values(
                "amount"
            )

        st.dataframe(
            filtered[
                [
                    "id",
                    "spent_at",
                    "spent_time",
                    "amount",
                    "category",
                    "subcategory",
                    "payment_method",
                    "expense_type",
                    "description",
                    "tags"
                ]
            ],
            use_container_width=True,
            hide_index=True
        )

        st.write(
            f"**{len(filtered)} gastos** · "
            f"**{format_money(filtered['amount'].sum())}**"
        )

        st.download_button(
            "⬇️ Exportar CSV",
            filtered.to_csv(
                index=False
            ).encode("utf-8"),
            "gastos.csv",
            "text/csv"
        )

        st.divider()

        expense_ids = filtered["id"].tolist()

        if expense_ids:

            selected_id = st.selectbox(
                "Seleccionar gasto",
                expense_ids
            )

            selected = filtered[
                filtered["id"] == selected_id
            ].iloc[0]

            col1, col2 = st.columns(2)

            if col1.button(
                "🗑️ Eliminar gasto",
                use_container_width=True
            ):

                execute(
                    "DELETE FROM expenses WHERE id = ?",
                    (selected_id,)
                )

                st.success(
                    "Gasto eliminado."
                )

                st.rerun()

            if col2.button(
                "📋 Duplicar gasto",
                use_container_width=True
            ):

                category_row = fetch_one("""
                    SELECT id
                    FROM categories
                    WHERE name = ?
                """, (selected["category"],))

                method_row = fetch_one("""
                    SELECT id
                    FROM payment_methods
                    WHERE name = ?
                """, (selected["payment_method"],))

                execute("""
                    INSERT INTO expenses (
                        amount,
                        spent_at,
                        spent_time,
                        category_id,
                        description,
                        payment_method_id,
                        expense_type,
                        recurring,
                        tags
                    )

                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    selected["amount"],
                    today.isoformat(),
                    selected["spent_time"],
                    category_row["id"],
                    selected["description"],
                    method_row["id"],
                    selected["expense_type"],
                    selected["recurring"],
                    selected["tags"]
                ))

                st.success(
                    "Gasto duplicado para hoy."
                )

                st.rerun()


# ============================================================
# RESUMEN MENSUAL
# ============================================================

elif st.session_state.page == "Resumen mensual":

    st.title("🗓️ Resumen mensual")

    selected_month = st.date_input(
        "Selecciona un mes",
        today.replace(day=1)
    )

    year = selected_month.year
    month = selected_month.month

    start = date(
        year,
        month,
        1
    )

    if month == 12:

        end = date(
            year,
            12,
            31
        )

    else:

        end = (
            date(year, month + 1, 1)
            - timedelta(days=1)
        )

    monthly = filter_period(
        expenses,
        start,
        end
    )

    total = monthly["amount"].sum()

    col1, col2, col3 = st.columns(3)

    col1.metric(
        "Total gastado",
        format_money(total)
    )

    col2.metric(
        "Número de gastos",
        len(monthly)
    )

    col3.metric(
        "Promedio diario",
        format_money(
            total / end.day
        )
    )

    if monthly.empty:

        st.info(
            "No hay gastos registrados en este mes."
        )

    else:

        category_totals = (
            monthly
            .groupby("category", as_index=False)["amount"]
            .sum()
            .sort_values(
                "amount",
                ascending=False
            )
        )

        daily_totals = (
            monthly
            .groupby("spent_at", as_index=False)["amount"]
            .sum()
        )

        col1, col2 = st.columns(2)

        col1.plotly_chart(
            px.bar(
                category_totals,
                x="category",
                y="amount",
                title="Gasto por categoría"
            ),
            use_container_width=True
        )

        col2.plotly_chart(
            px.bar(
                daily_totals,
                x="spent_at",
                y="amount",
                title="Gasto por día"
            ),
            use_container_width=True
        )

        st.subheader(
            "Categorías"
        )

        category_totals["porcentaje"] = (
            category_totals["amount"]
            / total
            * 100
        )

        st.dataframe(
            category_totals,
            use_container_width=True,
            hide_index=True
        )


# ============================================================
# RESUMEN ANUAL
# ============================================================

elif st.session_state.page == "Resumen anual":

    st.title("📈 Resumen anual")

    selected_year = st.number_input(
        "Año",
        min_value=2000,
        max_value=2100,
        value=today.year,
        step=1
    )

    yearly = filter_period(
        expenses,
        date(selected_year, 1, 1),
        date(selected_year, 12, 31)
    )

    total = yearly["amount"].sum()

    col1, col2 = st.columns(2)

    col1.metric(
        "Total anual",
        format_money(total)
    )

    col2.metric(
        "Promedio mensual",
        format_money(total / 12)
    )

    if yearly.empty:

        st.info(
            "No hay gastos registrados durante este año."
        )

    else:

        yearly["month"] = pd.to_datetime(
            yearly["spent_at"]
        ).dt.strftime("%Y-%m")

        monthly = (
            yearly
            .groupby("month", as_index=False)["amount"]
            .sum()
        )

        categories_year = (
            yearly
            .groupby("category", as_index=False)["amount"]
            .sum()
            .sort_values(
                "amount",
                ascending=False
            )
        )

        col1, col2 = st.columns(2)

        col1.plotly_chart(
            px.line(
                monthly,
                x="month",
                y="amount",
                markers=True,
                title="Evolución mensual"
            ),
            use_container_width=True
        )

        col2.plotly_chart(
            px.bar(
                categories_year,
                x="category",
                y="amount",
                title="Gasto anual por categoría"
            ),
            use_container_width=True
        )

        most_expensive_month = monthly.loc[
            monthly["amount"].idxmax()
        ]

        st.success(
            f"📌 Tu mes con mayor gasto fue "
            f"**{most_expensive_month['month']}** "
            f"con **{format_money(most_expensive_month['amount'])}**."
        )


# ============================================================
# ANÁLISIS
# ============================================================

elif st.session_state.page == "Análisis":

    st.title("🔎 Análisis de gastos")

    selected_period = st.selectbox(
        "Periodo",
        [
            "Este mes",
            "Mes anterior",
            "Este año",
            "Año anterior"
        ]
    )

    start, end = get_period(
        selected_period
    )

    analysis = filter_period(
        expenses,
        start,
        end
    )

    if analysis.empty:

        st.info(
            "No hay gastos en este periodo."
        )

    else:

        total = analysis["amount"].sum()

        category_totals = (
            analysis
            .groupby("category", as_index=False)["amount"]
            .sum()
            .sort_values(
                "amount",
                ascending=False
            )
        )

        st.metric(
            "Total gastado",
            format_money(total)
        )

        st.write(
            f"### 🥇 Mayor gasto"
        )

        st.write(
            f"**{category_totals.iloc[0]['category']}** — "
            f"{format_money(category_totals.iloc[0]['amount'])}"
        )

        st.write(
            f"### 🟢 Menor gasto"
        )

        st.write(
            f"**{category_totals.iloc[-1]['category']}** — "
            f"{format_money(category_totals.iloc[-1]['amount'])}"
        )

        st.plotly_chart(
            px.bar(
                category_totals,
                x="category",
                y="amount",
                text_auto=".2f",
                title="Ranking de categorías"
            ),
            use_container_width=True
        )

        methods = (
            analysis
            .groupby(
                "payment_method",
                as_index=False
            )["amount"]
            .sum()
        )

        st.plotly_chart(
            px.pie(
                methods,
                names="payment_method",
                values="amount",
                title="Gasto por método de pago"
            ),
            use_container_width=True
        )

        # Comparación mensual
        if selected_period == "Este mes":

            previous = filter_period(
                expenses,
                previous_month_start,
                previous_month_end
            )

            if not previous.empty:

                current_categories = (
                    analysis
                    .groupby("category")["amount"]
                    .sum()
                )

                previous_categories = (
                    previous
                    .groupby("category")["amount"]
                    .sum()
                )

                comparison = pd.concat(
                    [
                        current_categories,
                        previous_categories
                    ],
                    axis=1
                ).fillna(0)

                comparison.columns = [
                    "actual",
                    "anterior"
                ]

                comparison["cambio_%"] = (
                    (
                        comparison["actual"]
                        -
                        comparison["anterior"]
                    )
                    /
                    comparison["anterior"].replace(
                        0,
                        pd.NA
                    )
                    * 100
                )

                st.subheader(
                    "Comparación con el mes anterior"
                )

                st.dataframe(
                    comparison,
                    use_container_width=True
                )


# ============================================================
# PRESUPUESTOS
# ============================================================

elif st.session_state.page == "Presupuestos":

    st.title("💰 Presupuestos")

    selected_month = st.date_input(
        "Mes",
        today.replace(day=1)
    )

    month_key = selected_month.strftime(
        "%Y-%m"
    )

    # Presupuesto general
    total_budget = fetch_one("""
        SELECT amount
        FROM budgets
        WHERE month = ?
        AND category_id IS NULL
    """, (month_key,))

    current_budget = (
        float(total_budget["amount"])
        if total_budget
        else 0
    )

    with st.form("total_budget"):

        budget_value = st.number_input(
            "Presupuesto mensual total",
            min_value=0.0,
            value=current_budget,
            step=10.0
        )

        save = st.form_submit_button(
            "Guardar presupuesto"
        )

        if save:

            execute("""
                INSERT INTO budgets (
                    month,
                    category_id,
                    amount
                )

                VALUES (?, ?, ?)

                ON CONFLICT(month, category_id)
                DO UPDATE SET amount = excluded.amount
            """, (
                month_key,
                None,
                budget_value
            ))

            st.success(
                "Presupuesto guardado."
            )

            st.rerun()

    st.divider()

    st.subheader(
        "Presupuesto por categoría"
    )

    categories = get_categories()

    selected_start = selected_month.replace(day=1)

    if selected_start.month == 12:

        selected_end = date(
            selected_start.year,
            12,
            31
        )

    else:

        selected_end = (
            date(
                selected_start.year,
                selected_start.month + 1,
                1
            )
            - timedelta(days=1)
        )

    month_expenses = filter_period(
        expenses,
        selected_start,
        selected_end
    )

    for _, category in categories.iterrows():

        category_id = int(category["id"])

        existing = fetch_one("""
            SELECT amount
            FROM budgets
            WHERE month = ?
            AND category_id = ?
        """, (
            month_key,
            category_id
        ))

        existing_value = (
            float(existing["amount"])
            if existing
            else 0
        )

        value = st.number_input(
            f"{category['icon']} {category['name']}",
            min_value=0.0,
            value=existing_value,
            step=10.0,
            key=f"budget_{category_id}"
        )

        if st.button(
            f"Guardar {category['name']}",
            key=f"save_budget_{category_id}"
        ):

            execute("""
                INSERT INTO budgets (
                    month,
                    category_id,
                    amount
                )

                VALUES (?, ?, ?)

                ON CONFLICT(month, category_id)
                DO UPDATE SET amount = excluded.amount
            """, (
                month_key,
                category_id,
                value
            ))

            st.rerun()

        spent = month_expenses.loc[
            month_expenses["category"]
            == category["name"],
            "amount"
        ].sum()

        if value > 0:

            used_percentage = (
                spent / value * 100
            )

            remaining = value - spent

            st.progress(
                min(
                    used_percentage / 100,
                    1.0
                )
            )

            if used_percentage >= 100:

                st.error(
                    f"🚨 Superaste el presupuesto. "
                    f"Usado: {format_money(spent)}"
                )

            elif used_percentage >= 80:

                st.warning(
                    f"⚠️ Has utilizado "
                    f"{used_percentage:.1f}% del presupuesto. "
                    f"Restante: {format_money(remaining)}"
                )

            else:

                st.caption(
                    f"Usado: {format_money(spent)} · "
                    f"Restante: {format_money(remaining)} · "
                    f"{used_percentage:.1f}%"
                )


# ============================================================
# RECURRENTES
# ============================================================

elif st.session_state.page == "Recurrentes":

    st.title("🔁 Gastos recurrentes")

    categories = get_categories()

    with st.form("recurring_form"):

        name = st.text_input(
            "Nombre"
        )

        amount = st.number_input(
            "Monto",
            min_value=0.01,
            step=1.0
        )

        category = st.selectbox(
            "Categoría",
            categories["name"].tolist()
        )

        frequency = st.selectbox(
            "Frecuencia",
            [
                "Semanal",
                "Mensual",
                "Anual"
            ]
        )

        start_date = st.date_input(
            "Fecha de inicio",
            today
        )

        next_payment = st.date_input(
            "Próximo pago",
            today
        )

        save = st.form_submit_button(
            "Guardar gasto recurrente"
        )

        if save:

            if not name.strip():

                st.error(
                    "Debes introducir un nombre."
                )

            else:

                category_id = int(
                    categories.loc[
                        categories["name"] == category,
                        "id"
                    ].iloc[0]
                )

                execute("""
                    INSERT INTO recurring_expenses (
                        name,
                        amount,
                        category_id,
                        frequency,
                        start_date,
                        next_payment
                    )

                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    name,
                    amount,
                    category_id,
                    frequency,
                    start_date.isoformat(),
                    next_payment.isoformat()
                ))

                st.success(
                    "Gasto recurrente guardado."
                )

                st.rerun()

    recurring = pd.DataFrame(
        [
            dict(row)
            for row in fetch_all("""
                SELECT
                    r.id,
                    r.name,
                    r.amount,
                    c.name AS category,
                    r.frequency,
                    r.start_date,
                    r.next_payment,
                    r.active

                FROM recurring_expenses r

                INNER JOIN categories c
                    ON r.category_id = c.id

                ORDER BY r.next_payment
            """)
        ]
    )

    if recurring.empty:

        st.info(
            "No tienes gastos recurrentes."
        )

    else:

        st.dataframe(
            recurring,
            use_container_width=True,
            hide_index=True
        )


# ============================================================
# CATEGORÍAS
# ============================================================

elif st.session_state.page == "Categorías":

    st.title("🏷️ Categorías")

    categories = get_categories()

    with st.form("new_category"):

        name = st.text_input(
            "Nombre"
        )

        icon = st.text_input(
            "Icono",
            value="💰",
            max_chars=4
        )

        save = st.form_submit_button(
            "Crear categoría"
        )

        if save:

            if not name.strip():

                st.error(
                    "El nombre no puede estar vacío."
                )

            else:

                try:

                    execute("""
                        INSERT INTO categories (
                            name,
                            icon,
                            is_default
                        )

                        VALUES (?, ?, 0)
                    """, (
                        name.strip(),
                        icon
                    ))

                    st.success(
                        "Categoría creada."
                    )

                    st.rerun()

                except sqlite3.IntegrityError:

                    st.error(
                        "Ya existe una categoría con ese nombre."
                    )

    st.subheader(
        "Categorías existentes"
    )

    st.dataframe(
        categories[
            [
                "id",
                "icon",
                "name",
                "is_default"
            ]
        ],
        use_container_width=True,
        hide_index=True
    )

    custom_categories = categories[
        categories["is_default"] == 0
    ]

    if not custom_categories.empty:

        selected_category = st.selectbox(
            "Categoría personalizada",
            custom_categories["id"].tolist(),
            format_func=lambda category_id:
            custom_categories.loc[
                custom_categories["id"] == category_id,
                "name"
            ].iloc[0]
        )

        if st.button(
            "🗑️ Eliminar categoría"
        ):

            category_name = custom_categories.loc[
                custom_categories["id"]
                == selected_category,
                "name"
            ].iloc[0]

            used = expenses[
                expenses["category"]
                == category_name
            ]

            if not used.empty:

                st.error(
                    "No puedes eliminar una categoría "
                    "que tiene gastos registrados."
                )

            else:

                execute(
                    "DELETE FROM categories WHERE id = ?",
                    (selected_category,)
                )

                st.success(
                    "Categoría eliminada."
                )

                st.rerun()


# ============================================================
# MÉTODOS DE PAGO
# ============================================================

elif st.session_state.page == "Métodos de pago":

    st.title("💳 Métodos de pago")

    methods = get_payment_methods()

    with st.form("new_method"):

        name = st.text_input(
            "Nuevo método"
        )

        save = st.form_submit_button(
            "Agregar método"
        )

        if save:

            if not name.strip():

                st.error(
                    "El nombre no puede estar vacío."
                )

            else:

                try:

                    execute("""
                        INSERT INTO payment_methods (
                            name,
                            is_default
                        )

                        VALUES (?, 0)
                    """, (
                        name.strip(),
                    ))

                    st.success(
                        "Método agregado."
                    )

                    st.rerun()

                except sqlite3.IntegrityError:

                    st.error(
                        "Ese método ya existe."
                    )

    if not expenses.empty:

        method_totals = (
            expenses
            .groupby(
                "payment_method",
                as_index=False
            )["amount"]
            .sum()
            .sort_values(
                "amount",
                ascending=False
            )
        )

        st.plotly_chart(
            px.bar(
                method_totals,
                x="payment_method",
                y="amount",
                title="Gasto por método de pago"
            ),
            use_container_width=True
        )

    st.dataframe(
        methods,
        use_container_width=True,
        hide_index=True
    )


# ============================================================
# CONFIGURACIÓN / EXPORTACIÓN
# ============================================================

elif st.session_state.page == "Configuración":

    st.title("⚙️ Configuración")

    st.info(
        f"Base de datos local: `{DB}`"
    )

    st.subheader(
        "Exportación"
    )

    if expenses.empty:

        st.info(
            "No hay gastos para exportar."
        )

    else:

        # CSV
        csv_data = expenses.to_csv(
            index=False
        ).encode("utf-8")

        st.download_button(
            "⬇️ Exportar CSV",
            csv_data,
            "gastos.csv",
            "text/csv"
        )

        # Excel
        excel_buffer = io.BytesIO()

        with pd.ExcelWriter(
            excel_buffer,
            engine="openpyxl"
        ) as writer:

            expenses.to_excel(
                writer,
                index=False,
                sheet_name="Gastos"
            )

        st.download_button(
            "📊 Exportar Excel",
            excel_buffer.getvalue(),
            "gastos.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

        # PDF
        styles = getSampleStyleSheet()

        pdf_buffer = io.BytesIO()

        document = SimpleDocTemplate(
            pdf_buffer,
            pagesize=A4
        )

        story = []

        story.append(
            Paragraph(
                "Resumen de gastos",
                styles["Title"]
            )
        )

        story.append(
            Spacer(1, 12)
        )

        story.append(
            Paragraph(
                f"Generado: {datetime.now():%Y-%m-%d %H:%M}",
                styles["Normal"]
            )
        )

        story.append(
            Paragraph(
                f"Total registrado: "
                f"{format_money(expenses['amount'].sum())}",
                styles["Normal"]
            )
        )

        story.append(
            Spacer(1, 12)
        )

        table_data = [
            [
                "Fecha",
                "Categoría",
                "Monto",
                "Método"
            ]
        ]

        for _, row in expenses.iterrows():

            table_data.append(
                [
                    row["spent_at"],
                    row["category"],
                    format_money(row["amount"]),
                    row["payment_method"]
                ]
            )

        table = Table(
            table_data,
            repeatRows=1
        )

        table.setStyle(
            TableStyle(
                [
                    (
                        "BACKGROUND",
                        (0, 0),
                        (-1, 0),
                        colors.lightgrey
                    ),

                    (
                        "GRID",
                        (0, 0),
                        (-1, -1),
                        0.25,
                        colors.grey
                    )
                ]
            )
        )

        story.append(table)

        document.build(story)

        st.download_button(
            "📄 Exportar PDF",
            pdf_buffer.getvalue(),
            "resumen_gastos.pdf",
            "application/pdf"
        )

        # BACKUP
        backup = {

            "categories": [
                dict(row)
                for row in fetch_all(
                    "SELECT * FROM categories"
                )
            ],

            "subcategories": [
                dict(row)
                for row in fetch_all(
                    "SELECT * FROM subcategories"
                )
            ],

            "payment_methods": [
                dict(row)
                for row in fetch_all(
                    "SELECT * FROM payment_methods"
                )
            ],

            "expenses": [
                dict(row)
                for row in fetch_all(
                    "SELECT * FROM expenses"
                )
            ],

            "recurring_expenses": [
                dict(row)
                for row in fetch_all(
                    "SELECT * FROM recurring_expenses"
                )
            ],

            "budgets": [
                dict(row)
                for row in fetch_all(
                    "SELECT * FROM budgets"
                )
            ]
        }

        backup_json = json.dumps(
            backup,
            ensure_ascii=False,
            indent=2
        )

        st.download_button(
            "💾 Crear copia de seguridad",
            backup_json.encode("utf-8"),
            "backup_gastos.json",
            "application/json"
        )


# ============================================================
# PIE DE APLICACIÓN
# ============================================================

st.sidebar.divider()

st.sidebar.caption(
    "💸 Mis Gastos\n"
    "Control personal de gastos"
)
