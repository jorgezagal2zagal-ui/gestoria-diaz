"""Persist short cooldowns for unavailable mailboxes, without credentials."""

from pathlib import Path
from contextlib import contextmanager, closing

import sqlite3
import time


class MailboxHealth:
    def __init__(self, root):
        self.path = Path(root) / "estado_correos.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS cooldowns(email TEXT PRIMARY KEY, until REAL NOT NULL, reason TEXT NOT NULL)"
            )

    @contextmanager
    def connect(self):
        with closing(sqlite3.connect(self.path, timeout=5)) as db:
            with db:
                yield db

    def block(self, email, reason, seconds=600):
        if reason not in {"login", "verification", "omitted"}:
            raise ValueError("Motivo no permitido")
        if not 1 <= seconds <= 86400:
            raise ValueError("Espera no permitida")
        with self.connect() as db:
            db.execute(
                "INSERT INTO cooldowns VALUES(?,?,?) ON CONFLICT(email) DO UPDATE SET until=excluded.until,reason=excluded.reason",
                (email.casefold(), time.time() + seconds, reason),
            )

    def clear(self, email):
        with self.connect() as db:
            db.execute("DELETE FROM cooldowns WHERE email=?", (email.casefold(),))

    def excluded(self):
        with self.connect() as db:
            return {
                row[0]
                for row in db.execute(
                    "SELECT email FROM cooldowns WHERE until>?", (time.time(),)
                )
            }
