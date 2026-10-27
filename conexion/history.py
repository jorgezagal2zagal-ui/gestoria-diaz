"""Local per-request journal. Passwords, message bodies and verification codes are excluded."""

from contextlib import contextmanager, closing

import csv
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import uuid

FIELDS = (
    "solicitud",
    "fecha",
    "curp",
    "instancia",
    "tramite",
    "intento",
    "correo",
    "etapa",
    "resultado",
    "motivo",
)
STAGES = {"emuladores", "outlook", "consulta", "codigo", "validando", "tramite", "terminado"}
OUTCOMES = {
    "en_curso",
    "completada",
    "fallida",
    "omitido",
    "rechazado",
    "detenida",
    "sin_confirmar",
    "interrumpida",
}


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class RequestHistory:
    def __init__(self, root):
        self.path = Path(root) / "solicitudes.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("""CREATE TABLE IF NOT EXISTS attempts (
                solicitud TEXT NOT NULL, fecha TEXT NOT NULL, curp TEXT NOT NULL,
                instancia TEXT NOT NULL, tramite TEXT NOT NULL, intento INTEGER NOT NULL,
                correo TEXT NOT NULL, etapa TEXT NOT NULL, resultado TEXT NOT NULL, motivo TEXT NOT NULL,
                PRIMARY KEY(solicitud,intento))""")

    @contextmanager
    def connect(self):
        with closing(sqlite3.connect(self.path, timeout=5)) as db:
            with db:
                yield db

    def recover_interrupted(self):
        with self.connect() as db:
            return db.execute(
                "UPDATE attempts SET resultado='interrumpida', motivo='El proceso anterior se cerró sin confirmar el resultado; revisar IMSS antes de repetir.' WHERE resultado='en_curso'"
            ).rowcount

    def record(
        self,
        request,
        curp,
        instance,
        procedure,
        number,
        email,
        stage,
        outcome="en_curso",
        reason="",
    ):
        if stage not in STAGES or outcome not in OUTCOMES:
            raise ValueError("Estado de solicitud no reconocido")
        # Callers pass static reasons only, never provider exception strings or mail content.
        values = (
            request,
            now(),
            curp,
            instance,
            procedure,
            number,
            email,
            stage,
            outcome,
            reason,
        )
        with self.connect() as db:
            db.execute(
                """INSERT INTO attempts VALUES (?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(solicitud,intento) DO UPDATE SET fecha=excluded.fecha,
                etapa=excluded.etapa,resultado=excluded.resultado,motivo=excluded.motivo""",
                values,
            )

    def rows(self, limit=500):
        with self.connect() as db:
            db.row_factory = sqlite3.Row
            return [
                dict(row)
                for row in db.execute(
                    "SELECT * FROM attempts ORDER BY fecha DESC, solicitud, intento DESC LIMIT ?",
                    (limit,),
                )
            ]

    def export(self, path):
        with (
            self.connect() as db,
            Path(path).open("w", encoding="utf-8-sig", newline="") as stream,
        ):
            writer = csv.writer(stream)
            writer.writerow(FIELDS)
            for row in db.execute(
                "SELECT * FROM attempts ORDER BY fecha,solicitud,intento"
            ):
                writer.writerow(
                    [
                        "'" + str(value)
                        if str(value).startswith(("=", "+", "-", "@"))
                        else value
                        for value in row
                    ]
                )

    @staticmethod
    def request_id():
        return uuid.uuid4().hex
