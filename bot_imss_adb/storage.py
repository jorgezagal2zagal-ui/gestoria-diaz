"""Datos propios del bot nuevo, separados del anterior. Sin contraseñas ni OTP."""
import csv
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import uuid

try:
    from .locking import ProcessLock
except ImportError:
    from locking import ProcessLock


def device_lock(folder, serial):
    return ProcessLock(Path(folder) / ("dispositivo_" + hashlib.sha256(serial.encode()).hexdigest()[:20] + ".lock"))


def data_dir():
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData/Local")
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share")
    return base / "GestoriaDiazAdbNuevo"


def load_config(folder):
    try:
        value = json.loads((Path(folder) / "config.json").read_text(encoding="utf-8"))
        if isinstance(value, dict):
            return {k: v for k, v in value.items() if k in ("adb", "serial", "endpoint") and isinstance(v, str)}
    except (OSError, ValueError):
        pass
    return {}


def save_config(folder, **values):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "config.json"
    temp = folder / ("config_" + uuid.uuid4().hex + ".tmp")
    safe = {k: str(v) for k, v in values.items() if k in ("adb", "serial", "endpoint")}
    try:
        with temp.open("x", encoding="utf-8") as stream:
            if os.name != "nt":
                os.chmod(temp, 0o600)
            json.dump(safe, stream, ensure_ascii=False, indent=2)
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def atomic_text(path, encoding="utf-8-sig"):
    target = Path(path)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding=encoding, newline="", dir=target.parent,
                                         prefix=".export_", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            yield stream
        temporary.replace(target)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


def spreadsheet_cell(value):
    value = str(value)
    return "'" + value if value.startswith(("=", "+", "-", "@", "\t", "\r")) else value


MAIL_GROUPS = ("Entraron a la bandeja", "Con inconvenientes", "Omitidos")
MAIL_RESULTS = ("Entró a la bandeja", "No logró entrar", "Omitido", "Interrumpido")


class History:
    def __init__(self, folder):
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        self.folder = folder
        self.path = folder / "solicitudes.sqlite3"
        with self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS solicitudes (id TEXT PRIMARY KEY, fecha TEXT, curp TEXT, correo TEXT, dispositivo TEXT, estado TEXT, detalle TEXT, tramites TEXT)")
            db.execute("CREATE TABLE IF NOT EXISTS correos (id INTEGER PRIMARY KEY AUTOINCREMENT, fecha TEXT NOT NULL, correo TEXT NOT NULL, resultado TEXT NOT NULL, detalle TEXT NOT NULL)")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        try:
            with db:
                yield db
        finally:
            db.close()

    def recover(self):
        with self.connect() as db:
            pending = db.execute("SELECT id,dispositivo FROM solicitudes WHERE estado='en_curso'").fetchall()
        recovered = 0
        for ident, serial in pending:
            lock = device_lock(self.folder, serial)
            if not lock.acquire():
                continue  # Another live window still owns this device.
            try:
                with self.connect() as db:
                    recovered += db.execute("UPDATE solicitudes SET estado='interrumpida', detalle='El programa se cerró antes de confirmar el resultado. Revisa IMSS antes de repetir.' WHERE id=? AND estado='en_curso'", (ident,)).rowcount
            finally:
                lock.release()
        return recovered

    def start(self, job, serial):
        ident = uuid.uuid4().hex
        with self.connect() as db:
            db.execute("INSERT INTO solicitudes VALUES (?,?,?,?,?,?,?,?)", (ident, now(), job.curp, job.email, serial, "en_curso", "Iniciando", "{}"))
        return ident

    def finish(self, ident, state, detail, results):
        with self.connect() as db:
            db.execute("UPDATE solicitudes SET estado=?, detalle=?, tramites=? WHERE id=?", (state, detail, json.dumps(results, ensure_ascii=False), ident))

    def recent(self):
        with self.connect() as db:
            return db.execute("SELECT fecha,curp,correo,dispositivo,estado,detalle,tramites FROM solicitudes ORDER BY fecha DESC, rowid DESC LIMIT 500").fetchall()

    def record_mail(self, address, result, detail):
        if result not in MAIL_RESULTS:
            raise ValueError("Resultado de correo desconocido.")
        with self.connect() as db:
            db.execute("INSERT INTO correos (fecha,correo,resultado,detalle) VALUES (?,?,?,?)", (now(), address, result, detail))

    def mail_groups(self):
        with self.connect() as db:
            rows = db.execute("SELECT fecha,correo,resultado,detalle FROM correos WHERE id IN (SELECT MAX(id) FROM correos GROUP BY LOWER(correo)) ORDER BY id DESC").fetchall()
        grouped = {category: [] for category in MAIL_GROUPS}
        for row in rows:
            category = MAIL_GROUPS[0] if row[2] == "Entró a la bandeja" else MAIL_GROUPS[2] if row[2] == "Omitido" else MAIL_GROUPS[1]
            grouped[category].append(row)
        return grouped

    def export_mail(self, path):
        if Path(path).resolve() == self.path.resolve():
            raise ValueError("Elige un archivo CSV distinto de la base de datos.")
        with self.connect() as db, atomic_text(path) as stream:
            writer = csv.writer(stream)
            writer.writerow(("Fecha UTC", "Correo", "Resultado Outlook", "Detalle"))
            for row in db.execute("SELECT fecha,correo,resultado,detalle FROM correos ORDER BY id"):
                writer.writerow([spreadsheet_cell(v) for v in row])

    def export(self, path):
        if Path(path).resolve() == self.path.resolve():
            raise ValueError("Elige un archivo CSV distinto de la base de datos.")
        with self.connect() as db, atomic_text(path) as stream:
            writer = csv.writer(stream)
            writer.writerow(("Fecha UTC", "CURP", "Correo", "Dispositivo", "Estado", "Detalle", "Trámites"))
            for row in db.execute("SELECT fecha,curp,correo,dispositivo,estado,detalle,tramites FROM solicitudes ORDER BY fecha, rowid"):
                writer.writerow([spreadsheet_cell(v) for v in row])
