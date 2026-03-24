import os
import io
import math
import wave
import struct
import random
import sqlite3
import smtplib
from datetime import datetime
from email.message import EmailMessage
from pymongo import MongoClient

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from dotenv import load_dotenv

try:
    import ngrok
    NGROK_AVAILABLE = True
except Exception:
    ngrok = None
    NGROK_AVAILABLE = False


# ==================== CONFIGURACIÓN INICIAL ====================
st.set_page_config(
    page_title="HappySteps 🎵",
    page_icon="🎵",
    layout="centered"
)

load_dotenv()

# ==================== VARIABLES DESDE .ENV ====================
NGROK_AUTHTOKEN = os.getenv("NGROK_AUTHTOKEN", "")
NGROK_DOMAIN = os.getenv("NGROK_DOMAIN", "")

EMAIL_SENDER = os.getenv("EMAIL_SENDER", "tu_correo@gmail.com")
EMAIL_RECEIVER = os.getenv("EMAIL_RECEIVER", "correo_tutor@ejemplo.com")
EMAIL_APP_PASSWORD = os.getenv("EMAIL_APP_PASSWORD", "")

PUBLIC_ACCESS_PASSWORD = os.getenv("PUBLIC_ACCESS_PASSWORD", "contrasena_familiar_123")
DEVELOPER_PASSWORD = os.getenv("DEVELOPER_PASSWORD", "contrasena_desarrollador_secreta")

STUDENT_NAME = os.getenv("STUDENT_NAME", "Champion")
STUDENT_AVATAR = os.getenv("STUDENT_AVATAR", "😄")

DB_NAME = "database.db"
MONGO_URI = os.getenv("MONGO_URI")
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME")


# ==================== ESTADO DE SESIÓN ====================
def init_session_state():
    defaults = {
        "email_configured": bool(EMAIL_APP_PASSWORD),
        "email_sender": EMAIL_SENDER,
        "email_receiver": EMAIL_RECEIVER,
        "email_app_password": EMAIL_APP_PASSWORD,
        "authenticated": False,
        "history_unlocked": False,
        "ngrok_url": None,
        "ngrok_started": False,
        "play_step_sound": False,
        "play_task_song": False,
        "play_day_song": False,
        "student_name": STUDENT_NAME,
        "student_avatar": STUDENT_AVATAR if STUDENT_AVATAR else "😄",
        "tune_tokens": 0,
        "streak": 0,
        "usuario": None,
    }

    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


init_session_state()


# ==================== ESTILOS ====================
st.markdown("""
<style>
    .main {
        background: linear-gradient(180deg, #0b1020 0%, #111827 100%);
    }
    h1, h2, h3, h4 {
        color: #ffffff;
    }
    .stMetric {
        background-color: rgba(255,255,255,0.03);
        padding: 12px;
        border-radius: 14px;
        border: 1px solid rgba(255,255,255,0.08);
    }
    div[data-testid="stExpander"] {
        border-radius: 14px;
        border: 1px solid rgba(255,255,255,0.08);
    }
    div[data-testid="stAlert"] {
        border-radius: 14px;
    }
</style>
""", unsafe_allow_html=True)


# ==================== UTILIDADES GENERALES ====================
def get_conn():
    return sqlite3.connect(DB_NAME, check_same_thread=False)

@st.cache_resource
def get_mongo_client():
    return MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)

def get_mongo_db():
    client = get_mongo_client()
    return client[MONGO_DB_NAME]


def table_exists(conn, table_name: str) -> bool:
    c = conn.cursor()
    c.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,)
    )
    return c.fetchone() is not None


def get_table_columns(conn, table_name: str) -> list[str]:
    c = conn.cursor()
    c.execute(f"PRAGMA table_info({table_name})")
    return [row[1] for row in c.fetchall()]


def ensure_column(conn, table_name: str, column_name: str, column_def: str):
    columns = get_table_columns(conn, table_name)
    if column_name not in columns:
        c = conn.cursor()
        c.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_def}")


def init_db():
    
    conn = get_conn()
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT,
            category TEXT,
            task_time TEXT,
            difficulty TEXT,
            status TEXT DEFAULT 'Pending',
            reward_message TEXT,
            notify_tutor INTEGER DEFAULT 1,
            created_at TEXT
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS task_steps (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL,
            step_number INTEGER,
            step_description TEXT,
            completed INTEGER DEFAULT 0,
            FOREIGN KEY (task_id) REFERENCES tasks(id)
        )
    """)

    if not table_exists(conn, "logs"):
        c.execute("""
            CREATE TABLE logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT,
                event_type TEXT,
                task_name TEXT,
                detail TEXT,
                success INTEGER,
                source TEXT
            )
        """)
    else:
        ensure_column(conn, "logs", "timestamp", "TEXT")
        ensure_column(conn, "logs", "event_type", "TEXT")
        ensure_column(conn, "logs", "task_name", "TEXT")
        ensure_column(conn, "logs", "detail", "TEXT")
        ensure_column(conn, "logs", "success", "INTEGER")
        ensure_column(conn, "logs", "source", "TEXT")

    c.execute("""
        CREATE TABLE IF NOT EXISTS estudiantes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL,
            edad INTEGER,
            grado TEXT,
            tutor_nombre TEXT,
            tutor_email TEXT,
            nivel_apoyo TEXT,
            color_favorito TEXT,
            meta_personal TEXT
        )
    """)

    conn.commit()
    conn.close()


init_db()


# ==================== NGROK ====================
def start_ngrok():
    if st.session_state.get("ngrok_started"):
        return

    if not NGROK_AVAILABLE:
        return

    if not NGROK_AUTHTOKEN or not NGROK_DOMAIN:
        return

    try:
        listener = ngrok.forward(
            8501,
            authtoken=NGROK_AUTHTOKEN,
            domain=NGROK_DOMAIN
        )

        public_url = listener.url if hasattr(listener, "url") else str(listener)
        if callable(public_url):
            public_url = public_url()

        st.session_state.ngrok_url = str(public_url)
        st.session_state.ngrok_started = True

        print("✅ Túnel ngrok iniciado")
        print(f"🌍 URL pública: {public_url}")

    except Exception as e:
        print(f"❌ Error al iniciar ngrok: {e}")


def is_from_public_domain():
    try:
        host = st.context.headers.get("host", "").lower()
        if "ngrok" in host or "ngrok-free.app" in host or "ngrok-free.dev" in host:
            return True

        public_url = st.session_state.get("ngrok_url")
        if public_url and isinstance(public_url, str) and "//" in public_url:
            public_host = public_url.split("//", 1)[1].split("/", 1)[0].lower()
            return public_host in host
    except Exception:
        pass
    return False


start_ngrok()


# ==================== AUDIO ====================
def generate_tone_wav_bytes(frequency=440, duration=0.25, volume=0.35, sample_rate=44100):
    buffer = io.BytesIO()
    n_samples = int(sample_rate * duration)

    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)

        for i in range(n_samples):
            value = volume * math.sin(2 * math.pi * frequency * i / sample_rate)
            packed_value = struct.pack("<h", int(value * 32767))
            wav_file.writeframesraw(packed_value)

    buffer.seek(0)
    return buffer.read()


def generate_melody_wav_bytes(notes, volume=0.35, sample_rate=44100):
    buffer = io.BytesIO()

    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)

        for frequency, duration in notes:
            n_samples = int(sample_rate * duration)
            for i in range(n_samples):
                value = volume * math.sin(2 * math.pi * frequency * i / sample_rate)
                packed_value = struct.pack("<h", int(value * 32767))
                wav_file.writeframesraw(packed_value)

    buffer.seek(0)
    return buffer.read()


STEP_SOUND = generate_tone_wav_bytes(frequency=880, duration=0.18)
TASK_SONG = generate_melody_wav_bytes([
    (523.25, 0.18),
    (659.25, 0.18),
    (783.99, 0.20),
    (1046.50, 0.30)
])

DAY_SONG = generate_melody_wav_bytes([
    (523.25, 0.18),
    (587.33, 0.18),
    (659.25, 0.18),
    (783.99, 0.18),
    (1046.50, 0.35)
])


# ==================== MENSAJES Y RECOMPENSAS ====================
MOTIVATIONAL_MESSAGES = [
    "You are doing amazing! 🌟",
    "One step at a time! 🎵",
    "You can do it! 💪",
    "Keep going, superstar! ⭐",
    "Great effort today! 🎉"
]

REWARD_SONGS = [
    {
        "title": "Happy Reward Song",
        "artist": "Favorite Pick 1",
        "youtube_url": "https://www.youtube.com/watch?v=a1Femq4NPxs&list=RDa1Femq4NPxs&start_radio=1",
        "cost": 5
    },
    {
        "title": "Super Star Song",
        "artist": "Favorite Pick 2",
        "youtube_url": "https://www.youtube.com/watch?v=gGdGFtwCNBE&list=RDgGdGFtwCNBE&start_radio=1",
        "cost": 10
    },
    {
        "title": "Big Celebration Song",
        "artist": "Favorite Pick 3",
        "youtube_url": "https://www.youtube.com/watch?v=WHejvUhX6rk&list=RDWHejvUhX6rk&start_radio=1",
        "cost": 15
    }
]


# ==================== PERFIL DEL ESTUDIANTE ====================
def guardar_estudiante(nombre, edad, grado, tutor_nombre, tutor_email,
                       nivel_apoyo, color_favorito, meta_personal):
    conn = get_conn()
    c = conn.cursor()

    c.execute("""
        INSERT INTO estudiantes (
            nombre, edad, grado, tutor_nombre, tutor_email,
            nivel_apoyo, color_favorito, meta_personal
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        nombre,
        edad,
        grado,
        tutor_nombre,
        tutor_email,
        nivel_apoyo,
        color_favorito,
        meta_personal
    ))

    conn.commit()
    conn.close()


def obtener_estudiante_por_nombre(nombre):
    conn = get_conn()
    c = conn.cursor()

    c.execute("""
        SELECT id, nombre, edad, grado, tutor_nombre, tutor_email,
               nivel_apoyo, color_favorito, meta_personal
        FROM estudiantes
        WHERE nombre = ?
        ORDER BY id DESC
        LIMIT 1
    """, (nombre,))

    usuario = c.fetchone()
    conn.close()
    return usuario


def mostrar_login_o_registro():
    st.subheader("👤 Perfil del estudiante")

    opcion = st.radio(
        "Selecciona una opción",
        ["Iniciar sesión", "Crear perfil"],
        horizontal=True
    )

    if opcion == "Iniciar sesión":
        nombre_login = st.text_input("Escribe tu nombre")

        if st.button("Entrar"):
            usuario = obtener_estudiante_por_nombre(nombre_login.strip())

            if usuario:
                st.session_state.usuario = usuario
                st.session_state.student_name = usuario[1] if usuario[1] else STUDENT_NAME
                if usuario[5]:
                    st.session_state.email_receiver = usuario[5]
                st.success(f"¡Hola, {usuario[1]}! Bienvenido a HappySteps 💙")
                st.rerun()
            else:
                st.error("No encontramos ese perfil. Primero crea uno.")

    else:
        with st.form("perfil_form"):
            nombre = st.text_input("Nombre del estudiante")
            edad = st.number_input("Edad", min_value=5, max_value=25, step=1)
            grado = st.text_input("¿En qué grado vas?")
            tutor_nombre = st.text_input("Nombre del tutor")
            tutor_email = st.text_input("Correo del tutor")
            nivel_apoyo = st.selectbox("Nivel de apoyo", ["Bajo", "Medio", "Alto"])
            color_favorito = st.text_input("Color favorito")
            meta_personal = st.text_input("Meta personal")

            submitted = st.form_submit_button("Guardar perfil")

            if submitted:
                if not nombre.strip():
                    st.error("El nombre es obligatorio.")
                else:
                    guardar_estudiante(
                        nombre.strip(),
                        int(edad),
                        grado.strip(),
                        tutor_nombre.strip(),
                        tutor_email.strip(),
                        nivel_apoyo,
                        color_favorito.strip(),
                        meta_personal.strip()
                    )

                    usuario = obtener_estudiante_por_nombre(nombre.strip())
                    st.session_state.usuario = usuario
                    st.session_state.student_name = nombre.strip()
                    if tutor_email.strip():
                        st.session_state.email_receiver = tutor_email.strip()

                    st.success("Perfil creado correctamente.")
                    st.rerun()


def mostrar_perfil_estudiante():
    usuario = st.session_state.usuario
    if not usuario:
        return

    st.success(f"Hola, {usuario[1]} 👋")
    st.write(f"**Edad:** {usuario[2]}")
    st.write(f"**Grado:** {usuario[3]}")
    st.write(f"**Tutor:** {usuario[4]}")
    st.write(f"**Correo del tutor:** {usuario[5]}")
    st.write(f"**Nivel de apoyo:** {usuario[6]}")
    st.write(f"**Color favorito:** {usuario[7]}")
    st.write(f"**Meta personal:** {usuario[8]}")

    if st.button("Cerrar sesión"):
        st.session_state.usuario = None
        st.session_state.student_name = STUDENT_NAME
        st.rerun()


# ==================== ACCESO SIMPLE ====================
if is_from_public_domain() and not st.session_state.authenticated:
    st.title("🔒 HappySteps - Protected Access")
    password_input = st.text_input("Enter family access password:", type="password")
    if st.button("Enter"):
        if password_input == PUBLIC_ACCESS_PASSWORD:
            st.session_state.authenticated = True
            st.rerun()
        else:
            st.error("Incorrect password.")
    st.stop()

if st.session_state.usuario is None:
    mostrar_login_o_registro()
    st.stop()


# ==================== LOGS ====================
def registrar_evento(event_type: str, task_name: str = "", detail: str = "", success: bool = True):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    source = "public_ngrok" if is_from_public_domain() else "local"

    # Guardado en SQLite (se conserva)
    try:
        conn = get_conn()
        c = conn.cursor()
        c.execute("""
            INSERT INTO logs (timestamp, event_type, task_name, detail, success, source)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (timestamp, event_type, task_name, detail, int(success), source))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"SQLite log error: {e}")

    # Guardado en MongoDB (nuevo)
    try:
        mongo_db = get_mongo_db()
        mongo_db.logs.insert_one({
            "timestamp": timestamp,
            "event_type": event_type,
            "task_name": task_name,
            "detail": detail,
            "success": bool(success),
            "source": source
        })
    except Exception as e:
        print(f"Mongo log error: {e}")


# ==================== EMAIL ====================
def enviar_email_tutor(task_name: str):
    if not st.session_state.email_configured:
        registrar_evento("email_not_sent", task_name, "Email not configured", False)
        return False

    try:
        msg = EmailMessage()
        msg["Subject"] = f"🎉 Task completed - {task_name}"
        msg["From"] = st.session_state.email_sender
        msg["To"] = st.session_state.email_receiver

        msg.set_content(
            f"""Hello!

HappySteps update:
{st.session_state.student_name} completed the task "{task_name}".

Completion time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

Great progress today! 🎵
"""
        )

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(
                st.session_state.email_sender,
                st.session_state.email_app_password
            )
            server.send_message(msg)

        registrar_evento("email_sent", task_name, "Tutor email sent", True)
        return True

    except Exception as e:
        registrar_evento("email_error", task_name, f"Error: {e}", False)
        st.error(f"Error sending email: {e}")
        return False


# ==================== TASKS ====================
def get_tasks():
    conn = get_conn()
    df = pd.read_sql_query("SELECT * FROM tasks ORDER BY id DESC", conn)
    conn.close()
    return df


def get_task_by_id(task_id: int):
    conn = get_conn()
    df = pd.read_sql_query("SELECT * FROM tasks WHERE id = ?", conn, params=(task_id,))
    conn.close()
    return None if df.empty else df.iloc[0].to_dict()


def get_steps_for_task(task_id: int):
    conn = get_conn()
    df = pd.read_sql_query(
        "SELECT * FROM task_steps WHERE task_id = ? ORDER BY step_number ASC",
        conn,
        params=(task_id,)
    )
    conn.close()
    return df


def create_task(name, description, category, task_time, difficulty, reward_message, notify_tutor, steps):
    conn = get_conn()
    c = conn.cursor()

    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    c.execute("""
        INSERT INTO tasks (name, description, category, task_time, difficulty, status, reward_message, notify_tutor, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        name,
        description,
        category,
        task_time,
        difficulty,
        "Pending",
        reward_message,
        int(notify_tutor),
        created_at
    ))

    task_id = c.lastrowid

    for i, step in enumerate(steps, start=1):
        if step.strip():
            c.execute("""
                INSERT INTO task_steps (task_id, step_number, step_description, completed)
                VALUES (?, ?, ?, 0)
            """, (task_id, i, step.strip()))

    conn.commit()
    conn.close()

    registrar_evento(
        "task_created",
        name,
        f"Task created with {len([s for s in steps if s.strip()])} steps",
        True
    )


def update_task_status(task_id: int):
    steps_df = get_steps_for_task(task_id)
    task = get_task_by_id(task_id)

    if task is None:
        return

    if steps_df.empty:
        new_status = "Pending"
    else:
        completed_count = int(steps_df["completed"].sum())
        total_count = len(steps_df)

        if completed_count == 0:
            new_status = "Pending"
        elif completed_count < total_count:
            new_status = "In Progress"
        else:
            new_status = "Completed"

    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE tasks SET status = ? WHERE id = ?", (new_status, task_id))
    conn.commit()
    conn.close()

    if new_status == "Completed" and task["status"] != "Completed":
        registrar_evento("task_completed", task["name"], "Task completed", True)
        st.session_state.play_task_song = True
        st.session_state.tune_tokens += 3
        st.session_state.streak += 1

        all_tasks = get_tasks()
        if not all_tasks.empty and (all_tasks["status"] == "Completed").all():
            st.session_state.play_day_song = True

        if int(task["notify_tutor"]) == 1:
            enviar_email_tutor(task["name"])


def toggle_step(step_id: int, task_id: int, current_completed: int, task_name: str, step_description: str):
    new_value = 0 if current_completed == 1 else 1

    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE task_steps SET completed = ? WHERE id = ?", (new_value, step_id))
    conn.commit()
    conn.close()

    registrar_evento(
        "step_completed" if new_value == 1 else "step_unchecked",
        task_name,
        f"Step: {step_description}",
        True
    )

    if new_value == 1:
        st.session_state.play_step_sound = True
        st.session_state.tune_tokens += 1

    update_task_status(task_id)


def delete_task(task_id: int):
    task = get_task_by_id(task_id)
    if task is None:
        return

    conn = get_conn()
    c = conn.cursor()
    c.execute("DELETE FROM task_steps WHERE task_id = ?", (task_id,))
    c.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
    conn.commit()
    conn.close()

    registrar_evento("task_deleted", task["name"], "Task deleted", True)


# ==================== UTILIDADES UI ====================
def render_audio_rewards():
    if st.session_state.play_step_sound:
        st.audio(STEP_SOUND, format="audio/wav", autoplay=True)
        st.success(f"✨ Great job, {st.session_state.student_name}! You earned 1 Tune Token!")
        st.session_state.play_step_sound = False

    if st.session_state.play_task_song:
        st.audio(TASK_SONG, format="audio/wav", autoplay=True)
        st.balloons()
        st.success(f"🎉 Congratulations, {st.session_state.student_name}! You completed a task and earned 3 Tune Tokens!")
        st.session_state.play_task_song = False

    if st.session_state.play_day_song:
        st.audio(DAY_SONG, format="audio/wav", autoplay=True)
        st.success(f"🌟 Amazing, {st.session_state.student_name}! You completed all tasks today!")
        st.session_state.play_day_song = False


def get_summary_metrics():
    tasks_df = get_tasks()

    if tasks_df.empty:
        return 0, 0, 0, 0, 0.0

    total = len(tasks_df)
    completed = int((tasks_df["status"] == "Completed").sum())
    pending = int((tasks_df["status"] == "Pending").sum())
    in_progress = int((tasks_df["status"] == "In Progress").sum())
    completion_rate = round((completed / total) * 100, 1) if total > 0 else 0.0

    return total, completed, pending, in_progress, completion_rate


def convert_youtube_to_embed(url: str):
    if "watch?v=" in url:
        video_id = url.split("watch?v=")[-1].split("&")[0]
        return f"https://www.youtube.com/embed/{video_id}"
    if "youtu.be/" in url:
        video_id = url.split("youtu.be/")[-1].split("?")[0]
        return f"https://www.youtube.com/embed/{video_id}"
    return None


def render_youtube_embed(url: str, height: int = 315):
    embed_url = convert_youtube_to_embed(url)
    if embed_url:
        components.html(
            f"""
            <iframe width="100%" height="{height}"
            src="{embed_url}"
            title="YouTube video player"
            frameborder="0"
            allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
            allowfullscreen></iframe>
            """,
            height=height + 20
        )
    else:
        st.error("Invalid YouTube URL.")


# ==================== INTERFAZ ====================
st.markdown(f"# {st.session_state.student_avatar} HappySteps 🎵")
st.markdown("### Complete tasks, earn music, celebrate progress!")
st.image("foto1.png", width=900)

mostrar_perfil_estudiante()
render_audio_rewards()

with st.sidebar:
    st.header("⚙️ Settings")

    email_sender = st.text_input("Gmail sender", value=st.session_state.email_sender)
    email_receiver = st.text_input("Tutor email", value=st.session_state.email_receiver)

    with st.expander("🔐 App Password"):
        email_app_password = st.text_input(
            "Gmail App Password",
            value=st.session_state.email_app_password,
            type="password"
        )

    if st.button("Save email settings"):
        st.session_state.email_sender = email_sender.strip()
        st.session_state.email_receiver = email_receiver.strip()
        st.session_state.email_app_password = email_app_password.strip()
        st.session_state.email_configured = bool(email_app_password.strip())
        st.success("Saved!")
        st.rerun()

    st.divider()
    st.subheader("👤 Student Profile")

    student_name_input = st.text_input(
        "Student name",
        value=st.session_state.student_name
    )

    avatar_options = ["😄", "🦁", "🚀", "🎨", "⚽", "🎵"]
    current_avatar = (
        st.session_state.student_avatar
        if st.session_state.student_avatar in avatar_options
        else "😄"
    )

    student_avatar = st.selectbox(
        "Choose an avatar",
        avatar_options,
        index=avatar_options.index(current_avatar)
    )

    if st.button("Save student profile"):
        st.session_state.student_name = student_name_input.strip() if student_name_input.strip() else "Champion"
        st.session_state.student_avatar = student_avatar
        st.success("Student profile saved!")
        st.rerun()

    st.divider()

    if st.session_state.ngrok_url:
        st.success(f"🌍 Public URL:\n{st.session_state.ngrok_url}")
    elif not NGROK_AVAILABLE:
        st.caption("ngrok library is not installed.")
    elif not NGROK_AUTHTOKEN or not NGROK_DOMAIN:
        st.caption("ngrok variables missing in .env")

    st.divider()

    page = st.radio(
        "Menu",
        ["Home", "My Tasks", "Add Task", "Progress", "History", "Music Zone"]
    )


# ==================== PÁGINAS ====================
if page == "Home":
    st.markdown(f"## Welcome, **{st.session_state.student_name}**! 👋")
    st.markdown("### Ready to shine today? 🎵🌟")
    st.info(random.choice(MOTIVATIONAL_MESSAGES))

    total, completed, pending, in_progress, completion_rate = get_summary_metrics()

    c1, c2 = st.columns(2)
    c1.metric("Total Tasks", total)
    c2.metric("Completed", completed)

    c3, c4 = st.columns(2)
    c3.metric("Pending", pending)
    c4.metric("In Progress", in_progress)

    st.metric("Completion Rate", f"{completion_rate}%")

    st.markdown("### Music Rewards 🎵")
    r1, r2 = st.columns(2)
    r1.metric("Tune Tokens", st.session_state.tune_tokens)
    r2.metric("Task Streak", st.session_state.streak)

    if total == 0:
        st.info("No tasks yet. Go to 'Add Task' to create the first one.")
    elif completed == total:
        st.success(f"🎵 Amazing, {st.session_state.student_name}! All tasks are done today!")
    else:
        st.info(f"Keep going, {st.session_state.student_name}! One step at a time.")

    tasks_df = get_tasks()
    if not tasks_df.empty:
        st.markdown("#### Today's Task List")
        st.dataframe(
            tasks_df[["name", "category", "task_time", "difficulty", "status"]],
            use_container_width=True
        )


elif page == "My Tasks":
    st.subheader("My Tasks 📋")
    tasks_df = get_tasks()

    if tasks_df.empty:
        st.info("No tasks available yet.")
    else:
        for _, row in tasks_df.iterrows():
            with st.expander(f"{row['name']} - {row['status']}"):
                st.write(f"**Description:** {row['description'] or 'No description'}")
                st.write(f"**Category:** {row['category']}")
                st.write(f"**Time:** {row['task_time']}")
                st.write(f"**Difficulty:** {row['difficulty']}")
                st.write(f"**Reward Message:** {row['reward_message'] or 'Great job!'}")

                steps_df = get_steps_for_task(int(row["id"]))

                if steps_df.empty:
                    st.warning("This task has no steps.")
                else:
                    st.markdown("##### Steps")
                    for _, step in steps_df.iterrows():
                        checked = bool(step["completed"])
                        st.checkbox(
                            f"Step {int(step['step_number'])}: {step['step_description']}",
                            value=checked,
                            key=f"step_{int(step['id'])}",
                            on_change=toggle_step,
                            args=(
                                int(step["id"]),
                                int(row["id"]),
                                int(step["completed"]),
                                row["name"],
                                step["step_description"]
                            )
                        )

                st.divider()

                if row["status"] == "Completed":
                    st.success(
                        f"🎉 Congratulations, {st.session_state.student_name}! "
                        f"{row['reward_message'] or 'You did it!'}"
                    )

                col_a, col_b = st.columns(2)

                with col_a:
                    if st.button("Refresh task", key=f"refresh_{int(row['id'])}"):
                        update_task_status(int(row["id"]))
                        st.rerun()

                with col_b:
                    if st.button("Delete task", key=f"delete_{int(row['id'])}"):
                        delete_task(int(row["id"]))
                        st.warning("Task deleted.")
                        st.rerun()


elif page == "Add Task":
    st.subheader("Add Task ➕")

    with st.form("add_task_form"):
        name = st.text_input("Task name")
        description = st.text_area("Short description")
        category = st.selectbox("Category", ["School", "Home", "Personal Routine", "Therapy", "Other"])
        task_time = st.text_input("Time or moment of day", placeholder="5:00 PM or After lunch")
        difficulty = st.selectbox("Difficulty", ["Easy", "Medium", "Hard"])
        reward_message = st.text_input("Reward message", value="Great job! You did it! 🎵")
        notify_tutor = st.checkbox("Notify tutor by email when task is completed", value=True)

        st.markdown("##### Task Steps")
        step1 = st.text_input("Step 1")
        step2 = st.text_input("Step 2")
        step3 = st.text_input("Step 3")
        step4 = st.text_input("Step 4")
        step5 = st.text_input("Step 5")

        submitted = st.form_submit_button("Create task")

        if submitted:
            steps = [step1, step2, step3, step4, step5]

            if not name.strip():
                st.error("Task name is required.")
            elif len([s for s in steps if s.strip()]) == 0:
                st.error("Add at least one step.")
            else:
                create_task(
                    name=name.strip(),
                    description=description.strip(),
                    category=category,
                    task_time=task_time.strip(),
                    difficulty=difficulty,
                    reward_message=reward_message.strip(),
                    notify_tutor=notify_tutor,
                    steps=steps
                )
                st.success("✅ Task created successfully!")
                st.rerun()


elif page == "Progress":
    st.subheader("Progress 🌟")

    total, completed, pending, in_progress, completion_rate = get_summary_metrics()

    c1, c2 = st.columns(2)
    c1.metric("Total Tasks", total)
    c2.metric("Completed Tasks", completed)

    c3, c4 = st.columns(2)
    c3.metric("Pending Tasks", pending)
    c4.metric("In Progress", in_progress)

    st.metric("Completion Rate", f"{completion_rate}%")

    st.markdown("### Rewards Summary")
    s1, s2 = st.columns(2)
    s1.metric("Tune Tokens", st.session_state.tune_tokens)
    s2.metric("Streak", st.session_state.streak)

    tasks_df = get_tasks()
    if not tasks_df.empty:
        status_counts = tasks_df["status"].value_counts()
        st.markdown("#### Task Status Overview")
        st.bar_chart(status_counts)

        category_counts = tasks_df["category"].value_counts()
        st.markdown("#### Tasks by Category")
        st.bar_chart(category_counts)
    else:
        st.info("No task data available yet.")


elif page == "History":
    st.subheader("History 📜")

    if not st.session_state.history_unlocked:
        dev_password_input = st.text_input("Enter developer password to view history:", type="password")
        if st.button("Unlock History"):
            if dev_password_input == DEVELOPER_PASSWORD:
                st.session_state.history_unlocked = True
                st.rerun()
            else:
                st.error("Incorrect developer password.")
        st.stop()

    conn = get_conn()
    logs_df = pd.read_sql_query("SELECT * FROM logs ORDER BY id DESC", conn)
    conn.close()

    if logs_df.empty:
        st.info("No history yet.")
    else:
        st.dataframe(logs_df, use_container_width=True)

        if "event_type" in logs_df.columns:
            st.markdown("#### Event Counts")
            event_counts = logs_df["event_type"].value_counts()
            st.bar_chart(event_counts)

        if st.button("Refresh history"):
            st.rerun()


elif page == "Music Zone":
    st.subheader("Music Zone 🎵")
    st.write(f"Welcome to the reward music area, {st.session_state.student_name}!")

    st.markdown("### Your Music Rewards")
    st.metric("Tune Tokens", st.session_state.tune_tokens)

    st.markdown("#### Celebration Sounds")
    st.markdown("**Step Complete Sound**")
    st.audio(STEP_SOUND, format="audio/wav")

    st.markdown("**Task Celebration Song**")
    st.audio(TASK_SONG, format="audio/wav")

    st.markdown("**Full Day Celebration Song**")
    st.audio(DAY_SONG, format="audio/wav")

    st.divider()
    st.markdown("### Reward Songs Store 🎶")
    st.write("Complete tasks to earn Tune Tokens and unlock favorite songs!")

    for i, song in enumerate(REWARD_SONGS):
        unlocked = st.session_state.tune_tokens >= song["cost"]

        with st.expander(f"{song['title']} - {song['cost']} Tune Tokens"):
            st.write(f"**Artist/Label:** {song['artist']}")
            st.write(f"**Cost:** {song['cost']} Tune Tokens")

            if unlocked:
                st.success("Unlocked! 🎉")
                if st.button(f"Play {song['title']}", key=f"play_song_{i}"):
                    st.session_state[f"selected_song_{i}"] = True

                if st.session_state.get(f"selected_song_{i}", False):
                    render_youtube_embed(song["youtube_url"], height=315)
            else:
                st.warning(f"Locked 🔒 You need {song['cost']} Tune Tokens.")


# ==================== FOOTER ====================
st.caption("HappySteps stores information using SQLite and MongoDB, and tracks task progress with music, rewards, and personalized messages.")