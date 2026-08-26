
import sqlite3, csv, io, json
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet

BASE = Path(__file__).parent
DB = BASE / "data" / "gastos.db"
DEFAULT_CATS = ["Alimentación","Transporte","Vivienda","Servicios","Educación","Salud",
                "Entretenimiento","Compras","Ropa","Tecnología","Suscripciones","Viajes","Deudas","Otros"]
DEFAULT_METHODS = ["Efectivo","Tarjeta de débito","Tarjeta de crédito","Transferencia","Yape","Plin","Otro"]
TYPES = ["Necesario","Opcional","Extraordinario"]

def conn():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c

def init_db():
    c = conn()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS categories(
      id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL, icon TEXT DEFAULT '💰', is_default INTEGER DEFAULT 0);
    CREATE TABLE IF NOT EXISTS subcategories(
      id INTEGER PRIMARY KEY, category_id INTEGER NOT NULL, name TEXT NOT NULL,
      UNIQUE(category_id,name), FOREIGN KEY(category_id) REFERENCES categories(id) ON DELETE CASCADE);
    CREATE TABLE IF NOT EXISTS methods(
      id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL, is_default INTEGER DEFAULT 0);
    CREATE TABLE IF NOT EXISTS expenses(
      id INTEGER PRIMARY KEY, amount REAL NOT NULL, spent_at TEXT NOT NULL, time TEXT,
      category_id INTEGER NOT NULL, subcategory_id INTEGER, note TEXT, method_id INTEGER NOT NULL,
      expense_type TEXT NOT NULL, recurring INTEGER DEFAULT 0, tags TEXT DEFAULT '',
      FOREIGN KEY(category_id) REFERENCES categories(id),
      FOREIGN KEY(subcategory_id) REFERENCES subcategories(id),
      FOREIGN KEY(method_id) REFERENCES methods(id));
    CREATE TABLE IF NOT EXISTS recurring(
      id INTEGER PRIMARY KEY, name TEXT NOT NULL, amount REAL NOT NULL, category_id INTEGER NOT NULL,
      frequency TEXT NOT NULL, start_date TEXT NOT NULL, next_date TEXT NOT NULL, active INTEGER DEFAULT 1,
      FOREIGN KEY(category_id) REFERENCES categories(id));
    CREATE TABLE IF NOT EXISTS budgets(
      id INTEGER PRIMARY KEY, month TEXT NOT NULL, category_id INTEGER, amount REAL NOT NULL,
      UNIQUE(month,category_id), FOREIGN KEY(category_id) REFERENCES categories(id));
    """)
    for i,n in enumerate(DEFAULT_CATS):
        c.execute("INSERT OR IGNORE INTO categories(name,is_default) VALUES(?,1)",(n,))
    for n in DEFAULT_METHODS:
        c.execute("INSERT OR IGNORE INTO methods(name,is_default) VALUES(?,1)",(n,))
    c.commit(); c.close()

def q(sql, params=(), one=False):
    c=conn(); r=c.execute(sql,params); out=r.fetchone() if one else r.fetchall(); c.close(); return out

def exec_sql(sql, params=()):
    c=conn(); c.execute(sql,params); c.commit(); c.close()

def expenses_df():
    rows=q("""SELECT e.*, c.name category, c.icon, m.name method, s.name subcategory
              FROM expenses e JOIN categories c ON c.id=e.category_id
              JOIN methods m ON m.id=e.method_id
              LEFT JOIN subcategories s ON s.id=e.subcategory_id
              ORDER BY e.spent_at DESC, e.id DESC""")
    return pd.DataFrame([dict(x) for x in rows])

def cats_df(): return pd.DataFrame([dict(x) for x in q("SELECT * FROM categories ORDER BY name")])
def methods_df(): return pd.DataFrame([dict(x) for x in q("SELECT * FROM methods ORDER BY name")])

def period_df(start, end):
    return expenses_df().query("spent_at >= @start and spent_at <= @end").copy()

def money(x): return f"S/ {x:,.2f}"

def pct(a,b):
    if b == 0: return None
    return (a-b)/b*100

def date_range(kind):
    today=date.today()
    if kind=="Hoy": return today,today
    if kind=="Ayer": return today-timedelta(days=1),today-timedelta(days=1)
    if kind=="Esta semana":
        s=today-timedelta(days=today.weekday()); return s,today
    if kind=="Este mes": return today.replace(day=1),today
    if kind=="Mes anterior":
        last=today.replace(day=1)-timedelta(days=1); return last.replace(day=1),last
    if kind=="Este año": return today.replace(month=1,day=1),today
    if kind=="Año anterior":
        return date(today.year-1,1,1),date(today.year-1,12,31)
    return today.replace(day=1),today

init_db()
st.set_page_config(page_title="Mis Gastos", page_icon="💸", layout="wide")
st.markdown("""<style>
.block-container{padding-top:1.2rem}.metric-card{padding:14px;border:1px solid rgba(128,128,128,.25);border-radius:14px}
</style>""", unsafe_allow_html=True)

if "page" not in st.session_state: st.session_state.page="Dashboard"

with st.sidebar:
    st.title("💸 Mis Gastos")
    page=st.radio("Navegación",["Dashboard","➕ Registrar gasto","Historial","Resumen mensual","Resumen anual",
                                "Análisis","Presupuestos","Recurrentes","Categorías","Métodos de pago","Configuración"])
    st.session_state.page=page
    st.divider()
    if st.button("🔄 Actualizar datos", use_container_width=True): st.rerun()

df=expenses_df()
today=date.today()
month_start=today.replace(day=1)
prev_month_end=month_start-timedelta(days=1)
prev_month_start=prev_month_end.replace(day=1)

def add_expense_form(prefill=None):
    cats=cats_df(); methods=methods_df()
    with st.form("expense_form", clear_on_submit=True):
        c1,c2,c3=st.columns(3)
        amount=c1.number_input("Monto (S/)",min_value=0.01,value=float(prefill["amount"]) if prefill else 1.0,step=0.50)
        d=c2.date_input("Fecha", value=pd.to_datetime(prefill["spent_at"]).date() if prefill else today)
        t=c3.text_input("Hora (opcional)",value=prefill.get("time","") if prefill else "")
        cat_names=cats.name.tolist()
        cat=c1.selectbox("Categoría",cat_names,index=cat_names.index(prefill["category"]) if prefill and prefill["category"] in cat_names else 0)
        cat_id=int(cats.loc[cats.name==cat,"id"].iloc[0])
        subs=q("SELECT * FROM subcategories WHERE category_id=? ORDER BY name",(cat_id,))
        sub_names=["—"]+[x["name"] for x in subs]
        sub=c2.selectbox("Subcategoría (opcional)",sub_names)
        note=c3.text_input("Nota / descripción",value=prefill.get("note","") if prefill else "")
        meth_names=methods.name.tolist()
        method=c1.selectbox("Método de pago",meth_names,index=meth_names.index(prefill["method"]) if prefill and prefill["method"] in meth_names else 0)
        typ=c2.selectbox("Tipo de gasto",TYPES,index=TYPES.index(prefill["expense_type"]) if prefill and prefill["expense_type"] in TYPES else 0)
        recurring=c3.checkbox("Gasto recurrente",value=bool(prefill["recurring"]) if prefill else False)
        tags=c1.text_input("Etiquetas (separadas por comas)",value=prefill.get("tags","") if prefill else "")
        ok=st.form_submit_button("💾 Guardar gasto",type="primary",use_container_width=True)
    if ok:
        if amount<=0: st.error("El monto debe ser mayor que cero."); return
        if not cat: st.error("Selecciona una categoría."); return
        sid=None if sub=="—" else next((x["id"] for x in subs if x["name"]==sub),None)
        mid=int(methods.loc[methods.name==method,"id"].iloc[0])
        exec_sql("""INSERT INTO expenses(amount,spent_at,time,category_id,subcategory_id,note,method_id,expense_type,recurring,tags)
                    VALUES(?,?,?,?,?,?,?,?,?,?)""",
                 (amount,d.isoformat(),t,cat_id,sid,note,mid,typ,int(recurring),tags))
        st.success("Gasto guardado correctamente.")
        st.rerun()

if st.session_state.page=="Dashboard":
    st.title("Dashboard")
    cur=period_df(month_start.isoformat(),today.isoformat())
    prev=period_df(prev_month_start.isoformat(),prev_month_end.isoformat())
    td=period_df(today.isoformat(),today.isoformat())
    week=date_range("Esta semana"); wd=period_df(week[0].isoformat(),week[1].isoformat())
    year=period_df(date(today.year,1,1).isoformat(),today.isoformat())
    vals=[td.amount.sum(),wd.amount.sum(),cur.amount.sum(),year.amount.sum()]
    cols=st.columns(4)
    for c,label,val in zip(cols,["Hoy","Esta semana","Este mes","Este año"],vals):
        c.metric(label,money(val))
    st.divider()
    c1,c2,c3=st.columns(3)
    c1.metric("Gastos registrados",len(df))
    top=cur.groupby("category").amount.sum().sort_values(ascending=False)
    c2.metric("Mayor gasto", top.index[0] if len(top) else "—", money(top.iloc[0]) if len(top) else "S/ 0.00")
    c3.metric("Promedio diario",money(cur.amount.sum()/max(today.day,1)))
    change=pct(cur.amount.sum(),prev.amount.sum())
    st.info(f"Este mes llevas **{money(cur.amount.sum())}**. " + (f"Eso es **{abs(change):.1f}% {'más' if change>0 else 'menos'}** que el mes anterior." if change is not None else "No hay datos del mes anterior para comparar."))
    if len(cur):
        a,b=st.columns(2)
        bycat=cur.groupby("category",as_index=False).amount.sum().sort_values("amount",ascending=False)
        a.plotly_chart(px.pie(bycat,names="category",values="amount",title="Distribución por categorías"),use_container_width=True)
        daily=cur.groupby("spent_at",as_index=False).amount.sum()
        b.plotly_chart(px.bar(daily,x="spent_at",y="amount",title="Gasto diario"),use_container_width=True)
    else: st.info("Todavía no hay gastos este mes. Usa «Registrar gasto» para comenzar.")

elif st.session_state.page=="➕ Registrar gasto":
    st.title("Registrar gasto")
    add_expense_form()

elif st.session_state.page=="Historial":
    st.title("Historial de gastos")
    if len(df):
        a,b,c,d=st.columns(4)
        search=a.text_input("Buscar")
        cats=["Todas"]+sorted(df.category.dropna().unique().tolist())
        cat=b.selectbox("Categoría",cats)
        methods=["Todos"]+sorted(df.method.dropna().unique().tolist())
        meth=c.selectbox("Método",methods)
        sort=d.selectbox("Ordenar",["Más recientes","Más antiguos","Mayor monto","Menor monto"])
        start,end=st.date_input("Rango de fechas",[df.spent_at.min() and pd.to_datetime(df.spent_at.min()).date(),today])
        x=df.copy()
        if search: x=x[x.astype(str).apply(lambda col: col.str.contains(search,case=False,na=False)).any(axis=1)]
        if cat!="Todas": x=x[x.category==cat]
        if meth!="Todos": x=x[x.method==meth]
        x=x[(x.spent_at>=start.isoformat())&(x.spent_at<=end.isoformat())]
        if sort=="Más recientes": x=x.sort_values(["spent_at","id"],ascending=False)
        elif sort=="Más antiguos": x=x.sort_values(["spent_at","id"])
        elif sort=="Mayor monto": x=x.sort_values("amount",ascending=False)
        else: x=x.sort_values("amount")
        st.dataframe(x[["id","spent_at","time","amount","category","subcategory","method","expense_type","note"]],use_container_width=True,hide_index=True)
        st.caption(f"{len(x)} gastos · {money(x.amount.sum())}")
        st.download_button("⬇️ Exportar CSV",x.to_csv(index=False).encode("utf-8"),"gastos.csv","text/csv")
        ids=x.id.tolist()
        if ids:
            eid=st.selectbox("Selecciona un gasto para editar/eliminar",ids)
            row=x[x.id==eid].iloc[0].to_dict()
            e1,e2=st.columns(2)
            if e1.button("✏️ Editar",use_container_width=True): st.session_state.edit=row
            if e2.button("🗑️ Eliminar",use_container_width=True):
                exec_sql("DELETE FROM expenses WHERE id=?",(eid,)); st.rerun()
            if st.button("📋 Duplicar",use_container_width=True):
                exec_sql("""INSERT INTO expenses(amount,spent_at,time,category_id,subcategory_id,note,method_id,expense_type,recurring,tags)
                         SELECT amount,?,?,category_id,subcategory_id,note,method_id,expense_type,recurring,tags FROM expenses WHERE id=?""",
                         (today.isoformat(),row.get("time",""),eid)); st.success("Gasto duplicado para hoy."); st.rerun()
    else: st.info("No hay gastos registrados.")

elif st.session_state.page=="Resumen mensual":
    st.title("Resumen mensual")
    selected=st.date_input("Selecciona un mes",today.replace(day=1))
    y,m=selected.year,selected.month
    start=date(y,m,1); end=date(y+1,1,1)-timedelta(days=1) if m==12 else date(y,m+1,1)-timedelta(days=1)
    x=period_df(start.isoformat(),end.isoformat())
    st.metric("Total gastado",money(x.amount.sum()))
    a,b,c=st.columns(3); a.metric("Transacciones",len(x)); b.metric("Promedio diario",money(x.amount.sum()/end.day))
    if len(x): c.metric("Día de mayor gasto",str(x.groupby("spent_at").amount.sum().idxmax()))
    if len(x):
        by=x.groupby("category",as_index=False).amount.sum().sort_values("amount",ascending=False)
        d1,d2=st.columns(2)
        d1.plotly_chart(px.bar(by,x="amount",y="category",orientation="h",title="Gasto por categoría"),use_container_width=True)
        daily=x.groupby("spent_at",as_index=False).amount.sum()
        d2.plotly_chart(px.bar(daily,x="spent_at",y="amount",title="Gasto por día"),use_container_width=True)
        st.dataframe(by.assign(porcentaje=lambda z:z.amount/z.amount.sum()*100),use_container_width=True,hide_index=True)

elif st.session_state.page=="Resumen anual":
    st.title("Resumen anual")
    y=st.number_input("Año",min_value=2000,max_value=2100,value=today.year,step=1)
    x=period_df(date(y,1,1).isoformat(),date(y,12,31).isoformat())
    st.metric("Total anual",money(x.amount.sum()))
    st.metric("Promedio mensual",money(x.amount.sum()/12))
    if len(x):
        monthly=x.assign(month=pd.to_datetime(x.spent_at).dt.strftime("%Y-%m")).groupby("month",as_index=False).amount.sum()
        by=x.groupby("category",as_index=False).amount.sum().sort_values("amount",ascending=False)
        a,b=st.columns(2)
        a.plotly_chart(px.line(monthly,x="month",y="amount",markers=True,title="Evolución mensual"),use_container_width=True)
        b.plotly_chart(px.bar(by,x="category",y="amount",title="Distribución anual por categoría"),use_container_width=True)
        st.success(f"Mes más caro: **{monthly.loc[monthly.amount.idxmax(),'month']}** · {money(monthly.amount.max())}")

elif st.session_state.page=="Análisis":
    st.title("Análisis de gastos")
    x=st.selectbox("Periodo",["Este mes","Mes anterior","Este año","Año anterior"])
    s,e=date_range(x); z=period_df(s.isoformat(),e.isoformat())
    if len(z):
        by=z.groupby("category",as_index=False).amount.sum().sort_values("amount",ascending=False)
        st.metric("Total",money(z.amount.sum()))
        st.write(f"**Mayor categoría:** {by.iloc[0].category} ({money(by.iloc[0].amount)})")
        st.write(f"**Menor categoría:** {by.iloc[-1].category} ({money(by.iloc[-1].amount)})")
        st.plotly_chart(px.bar(by,x="category",y="amount",text_auto=".2f",title="Ranking de categorías"),use_container_width=True)
        methods=z.groupby("method",as_index=False).amount.sum().sort_values("amount",ascending=False)
        st.plotly_chart(px.pie(methods,names="method",values="amount",title="Gasto por método de pago"),use_container_width=True)
        if x=="Este mes":
            prev=period_df(prev_month_start.isoformat(),prev_month_end.isoformat())
            if len(prev):
                a=z.groupby("category").amount.sum(); b=prev.groupby("category").amount.sum()
                comp=pd.concat([a,b],axis=1).fillna(0); comp.columns=["actual","anterior"]; comp["cambio_%"]=((comp.actual-comp.anterior)/comp.anterior.replace(0,pd.NA)*100).round(1)
                st.dataframe(comp.sort_values("actual",ascending=False),use_container_width=True)

elif st.session_state.page=="Presupuestos":
    st.title("Presupuestos")
    ym=st.date_input("Mes",today.replace(day=1)).strftime("%Y-%m")
    cats=cats_df()
    total=q("SELECT amount FROM budgets WHERE month=? AND category_id IS NULL",(ym,),one=True)
    current_total=float(total["amount"]) if total else 0
    with st.form("budget_total"):
        val=st.number_input("Presupuesto mensual total (S/)",min_value=0.0,value=current_total,step=10.0)
        if st.form_submit_button("Guardar presupuesto total"):
            exec_sql("INSERT INTO budgets(month,category_id,amount) VALUES(?,?,?) ON CONFLICT(month,category_id) DO UPDATE SET amount=excluded.amount",(ym,None,val)); st.rerun()
    st.subheader("Presupuestos por categoría")
    for _,r in cats.iterrows():
        old=q("SELECT amount FROM budgets WHERE month=? AND category_id=?",(ym,int(r.id)),one=True)
        default=float(old["amount"]) if old else 0
        val=st.number_input(f"{r.icon} {r.name}",min_value=0.0,value=default,step=10.0,key=f"b{r.id}")
        if st.button(f"Guardar {r.name}",key=f"save{r.id}"):
            exec_sql("INSERT INTO budgets(month,category_id,amount) VALUES(?,?,?) ON CONFLICT(month,category_id) DO UPDATE SET amount=excluded.amount",(ym,int(r.id),val)); st.rerun()
    start=date.fromisoformat(ym+"-01"); end=date(start.year+1,1,1)-timedelta(days=1) if start.month==12 else date(start.year,start.month+1,1)-timedelta(days=1)
    x=period_df(start.isoformat(),end.isoformat())
    rows=[]
    for _,r in cats.iterrows():
        budget=q("SELECT amount FROM budgets WHERE month=? AND category_id=?",(ym,int(r.id)),one=True)
        if budget:
            spent=x.loc[x.category==r.name,"amount"].sum()
            rows.append([r.name,float(budget["amount"]),spent,float(budget["amount"])-spent,spent/float(budget["amount"])*100 if float(budget["amount"]) else 0])
    if rows:
        bd=pd.DataFrame(rows,columns=["Categoría","Presupuesto","Gastado","Restante","% usado"])
        st.dataframe(bd.style.format({"Presupuesto":"S/ {:.2f}","Gastado":"S/ {:.2f}","Restante":"S/ {:.2f}","% usado":"{:.1f}%"}),use_container_width=True,hide_index=True)

elif st.session_state.page=="Recurrentes":
    st.title("Gastos recurrentes")
    cats=cats_df()
    with st.form("rec"):
        name=st.text_input("Nombre"); amount=st.number_input("Monto",min_value=0.01,step=1.0)
        cat=st.selectbox("Categoría",cats.name.tolist()); freq=st.selectbox("Frecuencia",["Mensual","Semanal","Anual"])
        start=st.date_input("Inicio",today); nxt=st.date_input("Próximo pago",today)
        if st.form_submit_button("Guardar"):
            if not name.strip(): st.error("Escribe un nombre.")
            else:
                cid=int(cats.loc[cats.name==cat,"id"].iloc[0])
                exec_sql("INSERT INTO recurring(name,amount,category_id,frequency,start_date,next_date) VALUES(?,?,?,?,?,?)",(name,amount,cid,freq,start.isoformat(),nxt.isoformat())); st.rerun()
    rec=pd.DataFrame([dict(x) for x in q("""SELECT r.*,c.name category FROM recurring r JOIN categories c ON c.id=r.category_id ORDER BY next_date""")])
    if len(rec): st.dataframe(rec,use_container_width=True,hide_index=True)

elif st.session_state.page=="Categorías":
    st.title("Categorías")
    cats=cats_df()
    with st.form("newcat"):
        name=st.text_input("Nombre de categoría"); icon=st.text_input("Icono",value="💰",max_chars=4)
        if st.form_submit_button("Crear categoría"):
            try: exec_sql("INSERT INTO categories(name,icon,is_default) VALUES(?,?,0)",(name.strip(),icon)); st.rerun()
            except sqlite3.IntegrityError: st.error("Ya existe una categoría con ese nombre.")
    st.dataframe(cats[["id","icon","name","is_default"]],use_container_width=True,hide_index=True)
    custom=cats[cats.is_default==0]
    if len(custom):
        cid=st.selectbox("Categoría personalizada",custom.id.tolist(),format_func=lambda i: custom.loc[custom.id==i,"name"].iloc[0])
        if st.button("Eliminar categoría seleccionada"):
            if len(df[df.category==custom.loc[custom.id==cid,"name"].iloc[0]]): st.error("No puedes eliminar una categoría que ya tiene gastos.")
            else: exec_sql("DELETE FROM categories WHERE id=?",(cid,)); st.rerun()

elif st.session_state.page=="Métodos de pago":
    st.title("Métodos de pago")
    m=methods_df()
    with st.form("newmethod"):
        name=st.text_input("Nuevo método")
        if st.form_submit_button("Agregar"):
            try: exec_sql("INSERT INTO methods(name,is_default) VALUES(?,0)",(name.strip(),)); st.rerun()
            except sqlite3.IntegrityError: st.error("Ese método ya existe.")
    if len(df):
        st.plotly_chart(px.bar(df.groupby("method",as_index=False).amount.sum(),x="method",y="amount",title="Gasto por método"),use_container_width=True)
    st.dataframe(m,use_container_width=True,hide_index=True)

elif st.session_state.page=="Configuración":
    st.title("Configuración y respaldo")
    st.write("Los datos se guardan localmente en SQLite, dentro de la carpeta `data/`.")
    if len(df):
        excel=io.BytesIO()
        with pd.ExcelWriter(excel,engine="openpyxl") as writer:
            df.to_excel(writer,index=False,sheet_name="Gastos")
        st.download_button("📊 Exportar Excel",excel.getvalue(),"gastos.xlsx")
        styles=getSampleStyleSheet()
        pdf=io.BytesIO()
        doc=SimpleDocTemplate(pdf,pagesize=A4)
        story=[Paragraph("Resumen de gastos",styles["Title"]),Spacer(1,12),
               Paragraph(f"Generado: {datetime.now():%Y-%m-%d %H:%M}",styles["Normal"]),
               Paragraph(f"Total registrado: {money(df.amount.sum())}",styles["Normal"]),Spacer(1,12)]
        data=[["Fecha","Categoría","Monto","Método"]]+[[r.spent_at,r.category,f"S/ {r.amount:.2f}",r.method] for r in df.itertuples()]
        tab=Table(data,repeatRows=1); tab.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),colors.lightgrey),("GRID",(0,0),(-1,-1),0.25,colors.grey)]))
        story.append(tab); doc.build(story)
        st.download_button("📄 Exportar PDF",pdf.getvalue(),"resumen_gastos.pdf","application/pdf")
    backup={
        "categories":[dict(x) for x in q("SELECT * FROM categories")],
        "subcategories":[dict(x) for x in q("SELECT * FROM subcategories")],
        "methods":[dict(x) for x in q("SELECT * FROM methods")],
        "expenses":[dict(x) for x in q("SELECT * FROM expenses")],
        "recurring":[dict(x) for x in q("SELECT * FROM recurring")],
        "budgets":[dict(x) for x in q("SELECT * FROM budgets")]
    }
    st.download_button("💾 Crear copia de seguridad JSON",json.dumps(backup,ensure_ascii=False,indent=2).encode(),"backup_gastos.json","application/json")
    st.info("La restauración de copias JSON puede añadirse como flujo separado para evitar sobrescribir datos accidentalmente.")

if "edit" in st.session_state and st.session_state.page=="Historial":
    st.divider(); st.subheader("Edición rápida")
    row=st.session_state.edit
    cats=cats_df(); methods=methods_df()
    with st.form("editform"):
        amount=st.number_input("Monto",min_value=0.01,value=float(row["amount"]))
        d=st.date_input("Fecha",pd.to_datetime(row["spent_at"]).date())
        cat=st.selectbox("Categoría",cats.name.tolist(),index=cats.name.tolist().index(row["category"]))
        method=st.selectbox("Método",methods.name.tolist(),index=methods.name.tolist().index(row["method"]))
        note=st.text_input("Nota",value=row.get("note","") or "")
        typ=st.selectbox("Tipo",TYPES,index=TYPES.index(row["expense_type"]))
        if st.form_submit_button("Actualizar"):
            cid=int(cats.loc[cats.name==cat,"id"].iloc[0]); mid=int(methods.loc[methods.name==method,"id"].iloc[0])
            exec_sql("UPDATE expenses SET amount=?,spent_at=?,category_id=?,method_id=?,note=?,expense_type=? WHERE id=?",(amount,d.isoformat(),cid,mid,note,typ,int(row["id"])))
            del st.session_state.edit; st.rerun()
