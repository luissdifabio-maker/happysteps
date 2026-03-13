import streamlit as st
import sqlite3
import pandas as pd
import os
import json  # Agregado para download JSON
from datetime import datetime
import smtplib
from email.message import EmailMessage
import ngrok
from dotenv import load_dotenv

# ==================== CARGAR VARIABLES SENSIBLES DE .ENV ====================
load_dotenv()

# ==================== IMPORTS NECESARIOS ====================
import os
from dotenv import load_dotenv
import streamlit as st
import ngrok

# ==================== CARGAR .ENV ====================
load_dotenv()

# ==================== VARIABLES DESDE .ENV ====================
NGROK_AUTHTOKEN = os.getenv("NGROK_AUTHTOKEN")
NGROK_DOMAIN = os.getenv("NGROK_DOMAIN")

# EMAILS (todo desde .env, sin hardcodeo)
EMAIL_SENDER = os.getenv("EMAIL_SENDER", "tu_correo@gmail.com")
EMAIL_RECEIVER = os.getenv("EMAIL_RECEIVER", "correo_abuelo@ejemplo.com")
EMAIL_APP_PASSWORD = os.getenv("EMAIL_APP_PASSWORD", "")

# PASSWORDS
PUBLIC_ACCESS_PASSWORD = os.getenv("PUBLIC_ACCESS_PASSWORD", "contrasena_familiar_123")
DEVELOPER_PASSWORD = os.getenv("DEVELOPER_PASSWORD", "contrasena_desarrollador_secreta")

# ==================== NGROK TUNNELING ====================
if "ngrok_url" not in st.session_state:
    try:
        if NGROK_AUTHTOKEN and NGROK_DOMAIN:
            listener = ngrok.forward(
                8501,
                authtoken=NGROK_AUTHTOKEN,
                domain=NGROK_DOMAIN
            )

            # En algunas versiones la URL viene como atributo
            public_url = listener.url if hasattr(listener, "url") else str(listener)

            st.session_state["ngrok_url"] = public_url

            print("✅ ¡Túnel ngrok iniciado correctamente!")
            print(f"🌍 URL pública: {public_url}")
            print("🔗 Solo las acciones desde este enlace guardarán en la DB")

        else:
            print("⚠️ No se encontraron NGROK_AUTHTOKEN o NGROK_DOMAIN en el .env")
            print(f"NGROK_AUTHTOKEN: {NGROK_AUTHTOKEN}")
            print(f"NGROK_DOMAIN: {NGROK_DOMAIN}")

    except Exception as e:
        print(f"❌ Error al iniciar ngrok: {e}")

# ==================== CONFIGURACIÓN ====================
DB_NAME = "database.db"

st.set_page_config(
    page_title="Recordatorio Abuelitos ❤️",
    page_icon="🩺",
    layout="centered"
)

# Inicializar configuración de email desde .env (sin hardcodeo)
if "email_configured" not in st.session_state:
    st.session_state.email_configured = bool(EMAIL_APP_PASSWORD)
    st.session_state.email_sender = EMAIL_SENDER
    st.session_state.email_receiver = EMAIL_RECEIVER
    st.session_state.email_app_password = EMAIL_APP_PASSWORD

# ==================== DETECTAR SI VIENE DEL DOMINIO PÚBLICO ====================
def is_from_public_domain():
    """Retorna True SOLO si el usuario entró por el dominio ngrok"""
    try:
        host = st.context.headers.get("host", "").lower()
        if "ngrok" in host or "ngrok-free.app" in host:
            return True
        if "ngrok_url" in st.session_state:
            public_host = st.session_state.ngrok_url.split("//")[1].split("/")[0].lower()
            return public_host in host
    except:
        pass
    return False

# ==================== SQLITE PARA MEDICAMENTOS Y LOGS ====================
def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    # Tabla de medicamentos
    c.execute('''CREATE TABLE IF NOT EXISTS medicamentos (
                 id INTEGER PRIMARY KEY,
                 nombre TEXT,
                 dosis TEXT,
                 horarios TEXT  -- String separado por comas
                 )''')
    
    # Tabla de logs (usage_logs)
    c.execute('''CREATE TABLE IF NOT EXISTS usage_logs (
                 id INTEGER PRIMARY KEY,
                 timestamp TEXT,
                 tipo TEXT,
                 medicamento TEXT,
                 exito BOOLEAN,
                 accedido_desde TEXT
                 )''')
    
    conn.commit()
    conn.close()

# Inicializar DB al arrancar
init_db()

# ==================== FUNCIONES DE DATOS (SQLITE) ====================
def cargar_medicamentos():
    conn = sqlite3.connect(DB_NAME)
    df = pd.read_sql_query("SELECT * FROM medicamentos", conn)
    conn.close()
    meds = df.to_dict(orient='records')
    for med in meds:
        med['horarios'] = med['horarios'].split(',') if med['horarios'] else []
    return meds

def guardar_medicamentos(meds):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("DELETE FROM medicamentos")
    for med in meds:
        horarios_str = ','.join(med['horarios'])
        c.execute("INSERT INTO medicamentos (nombre, dosis, horarios) VALUES (?, ?, ?)",
                  (med['nombre'], med['dosis'], horarios_str))
    conn.commit()
    conn.close()

def registrar_evento(tipo: str, medicamento: str, exito: bool = None):
    """SOLO guarda si viene del dominio público (ngrok)"""
    if not is_from_public_domain():
        return
    
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    accedido_desde = "dominio_público_ngrok"
    c.execute("INSERT INTO usage_logs (timestamp, tipo, medicamento, exito, accedido_desde) VALUES (?, ?, ?, ?, ?)",
              (timestamp, tipo, medicamento, exito, accedido_desde))
    conn.commit()
    conn.close()

# ==================== CORREO ====================
def enviar_email(medicamento):
    if not st.session_state.email_configured:
        st.error("⚠️ Configura primero el correo en el sidebar")
        registrar_evento("email_enviado", medicamento['nombre'], exito=False)
        return False
    
    try:
        msg = EmailMessage()
        msg["Subject"] = f"🩺 ¡Hora de tomar! {medicamento['nombre']}"
        msg["From"] = st.session_state.email_sender
        msg["To"] = st.session_state.email_receiver
        msg.set_content(f"""¡Hola! ❤️

Es hora de tomar:

🧴 Medicamento: {medicamento['nombre']}
💊 Dosis: {medicamento['dosis']}
⏰ Hora: {datetime.now().strftime('%H:%M')}

¡No lo olvides! Gracias por cuidarte.

Tu familia ❤️
""")

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(st.session_state.email_sender, st.session_state.email_app_password)
            server.send_message(msg)
        
        registrar_evento("email_enviado", medicamento['nombre'], exito=True)
        return True
    except Exception as e:
        st.error(f"Error enviando correo: {e}")
        registrar_evento("email_enviado", medicamento['nombre'], exito=False)
        return False

# ==================== PROTECCIÓN DE ACCESO PARA DOMINIO NGROK ====================
if is_from_public_domain():
    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False
    
    if not st.session_state.authenticated:
        st.title("🔒 Acceso Protegido")
        password_input = st.text_input("Ingresa la contraseña para acceder a la app (para familiar):", type="password")
        if st.button("Ingresar"):
            if password_input == PUBLIC_ACCESS_PASSWORD:
                st.session_state.authenticated = True
                st.rerun()
            else:
                st.error("❌ Contraseña incorrecta")
        st.stop()  # Detiene la ejecución hasta autenticar

# ==================== INTERFAZ ====================
st.title("🩺 Recordatorio de Medicamentos")
st.markdown("### Para abuelitos ❤️ – Versión educativa (datos en SQLite)")

with st.sidebar:
    st.header("⚙️ Configuración")
    
    email_sender = st.text_input(
        "Tu correo Gmail", 
        value=st.session_state.email_sender, 
        key="sender"
    )
    email_receiver = st.text_input(
        "Correo del abuelo", 
        value=st.session_state.email_receiver, 
        key="receiver"
    )
    
    with st.expander("🔐 Configuración segura – App Password"):
        email_app_password = st.text_input(
            "App Password (16 dígitos)", 
            value=st.session_state.email_app_password, 
            type="password", 
            key="app_pass"
        )
    
    if st.button("Guardar configuración de correo"):
        st.session_state.email_sender = email_sender
        st.session_state.email_receiver = email_receiver
        st.session_state.email_app_password = email_app_password
        st.session_state.email_configured = bool(email_app_password)
        st.success("✅ Configuración guardada")
        st.rerun()

    st.divider()
    
    # Mostrar URL pública
    if "ngrok_url" in st.session_state:
        st.success(f"🌍 App pública:\n{st.session_state.ngrok_url}")
        st.caption("✅ Solo acciones desde este enlace guardan en la DB")

    opcion = st.radio("Menú", 
                      ["Inicio", "Agregar medicamento", "Ver todos", "Recordatorios de hoy", "📊 Historial"])

medicamentos = cargar_medicamentos()

# ==================== PÁGINAS ====================
if opcion == "Inicio":
    st.subheader("Bienvenido")
    st.write("Esta app ayuda a recordar los medicamentos del abuelo de forma sencilla y automática.")
    
    
    col1, col2 = st.columns(2)
    with col1:
        st.metric("Medicamentos registrados", len(medicamentos))
    with col2:
        conn = sqlite3.connect(DB_NAME)
        num_logs = pd.read_sql_query("SELECT COUNT(*) FROM usage_logs", conn).iloc[0, 0]
        conn.close()
        st.metric("Eventos en logs", num_logs)

elif opcion == "Agregar medicamento":
    st.subheader("➕ Agregar nuevo medicamento")
    with st.form("agregar_form"):
        nombre = st.text_input("Nombre del medicamento")
        dosis = st.text_input("Dosis (ej: 1 pastilla de 50 mg)")
        horarios = st.text_input("Horarios (separados por coma)", placeholder="08:00, 20:00")
        
        submitted = st.form_submit_button("Guardar medicamento")
        if submitted and nombre and dosis and horarios:
            nuevos_horarios = [h.strip() for h in horarios.split(",")]
            medicamentos.append({
                "nombre": nombre,
                "dosis": dosis,
                "horarios": nuevos_horarios
            })
            guardar_medicamentos(medicamentos)
            st.success(f"✅ {nombre} guardado correctamente!")
            st.rerun()

elif opcion == "Ver todos":
    st.subheader("📋 Todos los medicamentos")
    if not medicamentos:
        st.info("Aún no hay medicamentos. Agrega uno.")
    else:
        for i, med in enumerate(medicamentos):
            with st.expander(f"💊 {med['nombre']} — {med['dosis']}"):
                st.write(f"**Horarios:** {', '.join(med['horarios'])}")
                if st.button("Eliminar", key=f"del_{i}"):
                    del medicamentos[i]
                    guardar_medicamentos(medicamentos)
                    st.success("Eliminado")
                    st.rerun()
        
        # Opción de download JSON (nuevo: descarga los medicamentos como JSON)
        json_data = json.dumps(medicamentos, ensure_ascii=False, indent=4)
        st.download_button(
            label="📥 Descargar medicamentos como JSON",
            data=json_data,
            file_name="medicamentos.json",
            mime="application/json"
        )

elif opcion == "Recordatorios de hoy":
    st.subheader("🕒 Recordatorios de hoy")
    
    if st.button("🔄 Actualizar hora"):
        st.rerun()
    
    ahora = datetime.now()
    st.write(f"**Hora actual:** {ahora.strftime('%H:%M:%S')}  |  **Fecha:** {ahora.strftime('%d/%m/%Y')}")
    
    meds_hoy = cargar_medicamentos()
    if not meds_hoy:
        st.info("No hay medicamentos")
    else:
        for med in meds_hoy:
            st.write(f"### 💊 {med['nombre']} — {med['dosis']}")
            for h in med["horarios"]:
                if h == ahora.strftime("%H:%M"):
                    st.error(f"🚨 ¡ES HORA AHORA! → {h}")
                    
                    col1, col2 = st.columns(2)
                    with col1:
                        if st.button(f"📧 Enviar correo recordatorio", key=f"send_{med['nombre']}_{h}"):
                            if enviar_email(med):
                                st.success("✅ Correo enviado al abuelo!")
                    with col2:
                        if st.button(f"✅ Yo tomé el medicamento", key=f"tomado_{med['nombre']}_{h}"):
                            registrar_evento("medicamento_tomado", med['nombre'], exito=True)
                            st.success(f"✅ Toma de {med['nombre']} registrada correctamente")
                else:
                    st.info(f"⏰ Próximo: {h}")

elif opcion == "📊 Historial":
    st.subheader("📊 Historial completo de eventos (visualización live)")
    
    # Protección con contraseña separada para developer (tú)
    password = st.text_input("Contraseña para ver logs (solo para desarrollador):", type="password")
    if password != DEVELOPER_PASSWORD:
        st.warning("Contraseña incorrecta. Solo para el creador.")
        st.stop()
    
    conn = sqlite3.connect(DB_NAME)
    df = pd.read_sql_query("SELECT * FROM usage_logs ORDER BY timestamp DESC", conn)
    conn.close()
    
    if df.empty:
        st.info("Aún no hay eventos. Abre la app desde el enlace público y prueba los botones.")
    else:
        # Tabla live
        st.dataframe(df)
        
        # Métricas
        col1, col2, col3 = st.columns(3)
        col1.metric("Total eventos", len(df))
        col2.metric("Éxitos", len(df[df['exito'] == True]))
        col3.metric("Fallos", len(df[df['exito'] == False]))
        
        # Gráfico simple de usos por día
        df['date'] = pd.to_datetime(df['timestamp']).dt.date
        usos_por_dia = df.groupby('date').size()
        st.bar_chart(usos_por_dia, use_container_width=True)
        
        # Botón para actualizar live
        if st.button("🔄 Actualizar logs"):
            st.rerun()
    
    # Opción de download de database.db (SQLite) - nuevo
    if os.path.exists(DB_NAME):
        with open(DB_NAME, "rb") as f:
            db_data = f.read()
        st.download_button(
            label="📥 Descargar base de datos SQLite (database.db)",
            data=db_data,
            file_name="database.db",
            mime="application/octet-stream"
        )
    else:
        st.warning("⚠️ El archivo database.db no existe aún.")

# ==================== PIE EDUCATIVO ====================
st.caption("💡 Datos guardados en: `database.db` (SQLite)  \n"
           "→ Los logs **solo** se escriben cuando alguien entra por el dominio ngrok.  \n"
           "Usa DB Browser for SQLite para ver el archivo database.db.")

# ==================== MIGRACIÓN ÚNICA DE JSON A SQLITE (corre una vez y borra) ====================
# if __name__ == "__main__":
#     # Migra medicamentos.json si existe
#     if os.path.exists("medicamentos.json"):
#         with open("medicamentos.json", "r", encoding="utf-8") as f:
#             old_meds = json.load(f)
#         guardar_medicamentos(old_meds)
#         print("✅ Medicamentos migrados de JSON a SQLite.")
#     
#     # Migra historial.json si existe
#     if os.path.exists("historial.json"):
#         with open("historial.json", "r", encoding="utf-8") as f:
#             old_hist = json.load(f)
#         conn = sqlite3.connect(DB_NAME)
#         c = conn.cursor()
#         for evento in old_hist:
#             c.execute("INSERT INTO usage_logs (timestamp, tipo, medicamento, exito, accedido_desde) VALUES (?, ?, ?, ?, ?)",
#                       (evento['timestamp'], evento['tipo'], evento['medicamento'], evento.get('exito'), evento.get('accedido_desde')))
#         conn.commit()
#         conn.close()
#         print("✅ Logs migrados de JSON a SQLite.")