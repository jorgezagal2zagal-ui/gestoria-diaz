"""Durable, sequential batch queue. Unknown external outcomes require review."""

from contextlib import contextmanager, closing

import csv
from dataclasses import dataclass
from datetime import datetime, timezone, date
import io
from pathlib import Path
import re
import sqlite3
import threading

from .result import RequestResult

CURP = re.compile(r"[A-Z]{4}\d{6}[HM][A-Z]{5}[A-Z0-9]\d")
STATUSES = {
    "pendiente",
    "en_curso",
    "completada",
    "fallida",
    "revision",
    "omitida",
    "cancelada",
}
EXPORT_FIELDS = (
    "id",
    "curp",
    "tramite",
    "instancia",
    "estado",
    "intentos",
    "correo",
    "motivo",
    "solicitud",
    "creada",
    "actualizada",
)


def utcnow():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class QueueInput:
    curp: str
    procedure: str
    instance: str = ""


def valid_curp(value):
    if not CURP.fullmatch(value):
        return False
    try:
        date(
            (1900 if value[16].isdigit() else 2000) + int(value[4:6]),
            int(value[6:8]),
            int(value[8:10]),
        )
    except ValueError:
        return False
    return True


def parse_batch(text, default_procedure, procedures, instances, csv_file=False):
    if len(text) > 16 * 1024 * 1024:
        raise ValueError("Archivo demasiado grande; máximo 16 MB.")
    allowed = set(procedures)
    known = set(instances)
    items = []
    seen = set()
    duplicates = 0
    if default_procedure not in allowed:
        raise ValueError("Selecciona un trámite válido.")
    if csv_file:
        try:
            dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel
        reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff")), dialect=dialect)
        headers = reader.fieldnames or []
        mapped = {h.strip().casefold(): h for h in headers if h is not None}
        if (
            "curp" not in mapped
            or set(mapped) - {"curp", "tramite", "instancia"}
            or len(mapped) != len(headers)
        ):
            raise ValueError(
                "CSV: usa columnas curp, tramite e instancia; las dos últimas son opcionales."
            )
        records = (
            (
                n,
                {key: row.get(original, "") for key, original in mapped.items()},
                None in row,
            )
            for n, row in enumerate(reader, 2)
        )
    else:
        records = (
            (n, {"curp": line}, False)
            for n, line in enumerate(text.lstrip("\ufeff").splitlines(), 1)
            if line.strip() and not line.lstrip().startswith("#")
        )
    for number, row, extra in records:
        curp = (row.get("curp") or "").strip().upper()
        procedure = (row.get("tramite") or "").strip() or default_procedure
        instance = (row.get("instancia") or "").strip()
        if extra or not valid_curp(curp):
            raise ValueError(
                f"Línea {number}: CURP o columnas no válidas. No se importó el lote."
            )
        if procedure not in allowed:
            raise ValueError(f"Línea {number}: trámite no reconocido.")
        if instance and instance not in known:
            raise ValueError(f"Línea {number}: instancia no reconocida.")
        key = (curp, procedure)
        if key in seen:
            duplicates += 1
            continue
        seen.add(key)
        items.append(QueueInput(curp, procedure, instance))
        if len(items) > 10000:
            raise ValueError("Importa como máximo 10 000 solicitudes por archivo.")
    if not items:
        raise ValueError("El archivo no contiene CURP válidas.")
    return items, duplicates


class BatchStore:
    def __init__(self, root):
        self.path = Path(root) / "cola.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""CREATE TABLE IF NOT EXISTS jobs(
                id INTEGER PRIMARY KEY AUTOINCREMENT,curp TEXT NOT NULL,tramite TEXT NOT NULL,
                instancia TEXT NOT NULL DEFAULT '',estado TEXT NOT NULL DEFAULT 'pendiente',
                intentos INTEGER NOT NULL DEFAULT 0,correo TEXT NOT NULL DEFAULT '',motivo TEXT NOT NULL DEFAULT '',
                solicitud TEXT NOT NULL DEFAULT '',creada TEXT NOT NULL,actualizada TEXT NOT NULL,
                UNIQUE(curp,tramite));
                CREATE INDEX IF NOT EXISTS jobs_state ON jobs(estado,id);
                CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY,job INTEGER,fecha TEXT,accion TEXT);
                CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);""")

    @contextmanager
    def connect(self):
        with closing(sqlite3.connect(self.path, timeout=10)) as db:
            db.row_factory = sqlite3.Row
            with db:
                yield db

    def import_items(self, items):
        if not items or len(items) > 10000:
            raise ValueError("Lote fuera de rango")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            total = db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
            before = db.total_changes
            for item in items:
                if not valid_curp(item.curp) or not item.procedure:
                    raise ValueError("Solicitud inválida")
                stamp = utcnow()
                db.execute(
                    "INSERT OR IGNORE INTO jobs(curp,tramite,instancia,creada,actualizada) VALUES(?,?,?,?,?)",
                    (item.curp, item.procedure, item.instance, stamp, stamp),
                )
            added = db.total_changes - before
            if total + added > 100000:
                raise ValueError(
                    "La cola admite 100 000 registros; exporta y conserva este lote antes de crear otro almacén."
                )
        return added, len(items) - added

    def counts(self):
        with self.connect() as db:
            return {
                **dict.fromkeys(STATUSES, 0),
                **{
                    r[0]: r[1]
                    for r in db.execute(
                        "SELECT estado,COUNT(*) FROM jobs GROUP BY estado"
                    )
                },
            }

    def rows(self, status=None, offset=0, limit=100):
        if status is not None and status not in STATUSES:
            raise ValueError("Filtro no válido")
        if not 1 <= limit <= 500:
            raise ValueError("Página fuera de rango")
        with self.connect() as db:
            query = (
                "SELECT * FROM jobs"
                + (" WHERE estado=?" if status else "")
                + " ORDER BY id LIMIT ? OFFSET ?"
            )
            args = ((status,) if status else ()) + (limit, max(0, offset))
            return [dict(row) for row in db.execute(query, args)]

    def claim(self, instances):
        if not instances or len(instances) > 5:
            raise ValueError("Elige de 1 a 5 instancias")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute(
                "SELECT 1 FROM jobs WHERE estado IN ('en_curso','revision') LIMIT 1"
            ).fetchone():
                return None
            row = db.execute(
                "SELECT * FROM jobs WHERE estado='pendiente' ORDER BY id LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            if row["instancia"] and row["instancia"] not in instances:
                raise ValueError(
                    "La primera solicitud necesita una instancia que no está seleccionada."
                )
            assigned = row["instancia"] or instances[(row["id"] - 1) % len(instances)]
            db.execute(
                "UPDATE jobs SET estado='en_curso',instancia=?,actualizada=? WHERE id=?",
                (assigned, utcnow(), row["id"]),
            )
            return {**dict(row), "estado": "en_curso", "instancia": assigned}

    def finish(self, item, result):
        mapping = {
            "completada": "completada",
            "fallida": "fallida",
            "sin_confirmar": "revision",
            "detenida": "revision",
            "limited": "revision",
            "stopped": "revision",
            "sin_correos": "pendiente",
        }
        state = mapping.get(result.status, "revision")
        if result.status in ("limited", "stopped", "detenida") and not result.submitted:
            state = "pendiente"
        with self.connect() as db:
            updated = db.execute(
                "UPDATE jobs SET estado=?,intentos=intentos+?,correo=?,motivo=?,solicitud=?,actualizada=? WHERE id=? AND estado='en_curso'",
                (
                    state,
                    result.attempts,
                    result.email,
                    result.reason,
                    result.request_id,
                    utcnow(),
                    item["id"],
                ),
            ).rowcount
            if updated != 1:
                raise RuntimeError("La solicitud ya no pertenece al trabajador activo")
        return state

    def recover_interrupted(self):
        with self.connect() as db:
            return db.execute(
                "UPDATE jobs SET estado='revision',motivo='Cierre inesperado; comprobar IMSS antes de repetir.',actualizada=? WHERE estado='en_curso'",
                (utcnow(),),
            ).rowcount

    def resolve(self, item_id, action):
        if action not in {"completada", "omitida", "pendiente"}:
            raise ValueError("Resolución no válida")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            updated = db.execute(
                "UPDATE jobs SET estado=?,intentos=CASE WHEN ?='pendiente' THEN 0 ELSE intentos END,motivo='Revisión manual del operador',actualizada=? WHERE id=? AND estado IN ('revision','fallida')",
                (action, action, utcnow(), item_id),
            ).rowcount
            if updated != 1:
                raise ValueError("Selecciona una solicitud fallida o en revisión.")
            db.execute(
                "INSERT INTO events(job,fecha,accion) VALUES(?,?,?)",
                (item_id, utcnow(), action),
            )

    def cancel_pending(self):
        with self.connect() as db:
            return db.execute(
                "UPDATE jobs SET estado='cancelada',motivo='Cancelada por el operador',actualizada=? WHERE estado='pendiente'",
                (utcnow(),),
            ).rowcount

    def set_pause(self, reason):
        with self.connect() as db:
            db.execute(
                "INSERT INTO metadata VALUES('pausa',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (reason,),
            )

    def pause_reason(self):
        with self.connect() as db:
            row = db.execute("SELECT value FROM metadata WHERE key='pausa'").fetchone()
            return row[0] if row else ""

    def export(self, path):
        with (
            self.connect() as db,
            Path(path).open("w", encoding="utf-8-sig", newline="") as stream,
        ):
            writer = csv.writer(stream)
            writer.writerow(EXPORT_FIELDS)
            for row in db.execute(
                "SELECT " + ",".join(EXPORT_FIELDS) + " FROM jobs ORDER BY id"
            ):
                writer.writerow(
                    [
                        "'" + str(v) if str(v).startswith(("=", "+", "-", "@")) else v
                        for v in row
                    ]
                )


class BatchRunner:
    def __init__(self, store, execute, notify=None):
        self.store = store
        self.execute = execute
        self.notify = notify or (lambda text: None)
        self.lock = threading.Lock()
        self.running = False
        self.pausing = threading.Event()
        self.stopping = threading.Event()
        self.wake = threading.Event()
        self.thread = None

    def start(self, instances, interval=10):
        if not instances or len(instances) > 5 or not 0 <= interval <= 120:
            raise ValueError("Configuración del lote no válida")
        with self.lock:
            if self.running:
                raise ValueError("Ya hay un lote activo")
            if self.store.counts()["revision"]:
                raise ValueError(
                    "Resuelve las solicitudes en revisión antes de continuar."
                )
            self.running = True
            self.pausing.clear()
            self.stopping.clear()
            self.wake.clear()
            self.thread = threading.Thread(
                target=self._work, args=(tuple(instances), interval), daemon=True
            )
            self.thread.start()

    def pause(self):
        self.pausing.set()
        self.wake.set()

    def stop(self):
        self.stopping.set()
        self.wake.set()

    def _work(self, instances, interval):
        failed = 0
        try:
            self.store.set_pause("")
            while not self.stopping.is_set():
                if self.pausing.is_set():
                    self.store.set_pause(
                        "Pausa solicitada; se conservan los pendientes."
                    )
                    break
                item = self.store.claim(instances)
                if item is None:
                    counts = self.store.counts()
                    self.notify(
                        "Cola terminada."
                        if not counts["pendiente"]
                        else "Cola detenida: revisa las solicitudes pendientes."
                    )
                    break
                self.notify(f"Solicitud {item['id']}: preparando {item['instancia']}")
                try:
                    result = self.execute(item)
                except Exception:
                    result = RequestResult(
                        "sin_confirmar",
                        reason="Error del trabajador; revisar la instancia antes de repetir.",
                    )
                state = self.store.finish(item, result)
                self.notify(f"Solicitud {item['id']}: {state}")
                if (
                    result.status
                    in {
                        "limited",
                        "stopped",
                        "sin_correos",
                        "sin_confirmar",
                        "detenida",
                    }
                    or state == "revision"
                ):
                    self.store.set_pause(
                        result.reason
                        or "Es necesario revisar la solicitud antes de continuar."
                    )
                    break
                failed = 0 if state == "completada" else failed + 1
                if failed >= 3:
                    self.store.set_pause(
                        "Tres solicitudes consecutivas sin completar. Revisa correos e instancias."
                    )
                    break
                if not self.store.counts()["pendiente"]:
                    self.notify("Cola terminada.")
                    break
                if self.stopping.is_set() or self.pausing.is_set():
                    continue
                self.notify(
                    f"Esperando {interval} segundos antes de la siguiente solicitud."
                )
                self.wake.wait(interval)
                self.wake.clear()
            if self.stopping.is_set():
                self.store.set_pause(
                    "Lote detenido por el operador; se conservan los pendientes."
                )
        except Exception:
            self.store.recover_interrupted()
            self.store.set_pause(
                "No se pudo continuar la cola; revisa almacenamiento e instancias."
            )
        finally:
            self.running = False
