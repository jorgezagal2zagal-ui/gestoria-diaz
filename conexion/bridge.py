import json
import os
from pathlib import Path
import re
import shutil
import sys
import time
import uuid

PROTOCOL = 2


def data_directory():
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        return (
            (Path(base) if base else Path.home() / "AppData" / "Local")
            / "GestoriaDiazPuente"
            / "V2"
        )
    return Path(__file__).resolve().parents[1] / ".datos_conexion" / "v2"


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        fd = os.open(str(temporary), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def read_json(path):
    try:
        path = Path(path)
        if path.stat().st_size > 65536:
            return None
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except (OSError, ValueError, RecursionError):
        return None


class Bridge:
    def __init__(self, root=None):
        self.root = Path(root) if root is not None else data_directory()

    def publish(self, emails, active):
        clean = list(
            dict.fromkeys(
                value.strip().casefold()
                for value in emails
                if isinstance(value, str)
                and re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value.strip())
            )
        )
        write_json(
            self.root / "outlook.json",
            {
                "protocol": PROTOCOL,
                "at": time.time(),
                "emails": clean,
                "active": bool(active),
            },
        )

    def presence(self):
        info = read_json(self.root / "outlook.json")
        if (
            not info
            or info.get("protocol") != PROTOCOL
            or not isinstance(info.get("at"), (float, int))
            or not -2 <= time.time() - info["at"] < 8
            or info.get("active") is not True
            or not isinstance(info.get("emails"), list)
            or any(
                not isinstance(value, str)
                or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value)
                for value in info["emails"]
            )
        ):
            return None
        return info

    def create(self, email, instance, sender, subject, code_timeout=180):
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", sender) or not subject.strip():
            raise ValueError(
                "Configura el remitente completo y el asunto del mensaje del IMSS."
            )
        key = uuid.uuid4().hex
        job = self.job(key)
        if type(code_timeout) is not int or not 60 <= code_timeout <= 300:
            raise ValueError("Tiempo del lector fuera de rango")
        write_json(
            job / "request.json",
            {
                "protocol": PROTOCOL,
                "id": key,
                "email": email,
                "instance": instance,
                "sender": sender.strip().casefold(),
                "subject": subject.strip(),
                "code_timeout": code_timeout,
                "created": time.time(),
                "expires": time.time() + 900,
            },
        )
        return key

    def job(self, key):
        if not re.fullmatch(r"[a-f0-9]{32}", key):
            raise ValueError("Solicitud local inválida")
        return self.root / "solicitudes" / key

    def pending(self):
        parent = self.root / "solicitudes"
        if not parent.exists():
            return []
        result = []
        for directory in parent.iterdir():
            if (
                not re.fullmatch(r"[a-f0-9]{32}", directory.name)
                or not directory.is_dir()
            ):
                continue
            request = read_json(directory / "request.json")
            if (
                not request
                or request.get("protocol") != PROTOCOL
                or request.get("id") != directory.name
                or not all(
                    isinstance(request.get(k), str)
                    for k in ("email", "instance", "sender", "subject")
                )
                or not all(
                    isinstance(request.get(k), (float, int))
                    for k in ("created", "expires")
                )
                or type(request.get("code_timeout")) is not int
                or not 60 <= request["code_timeout"] <= 300
            ):
                continue
            if (
                request.get("expires", 0) < time.time()
                or (directory / "finished.json").exists()
            ):
                shutil.rmtree(directory, ignore_errors=True)
            elif not (directory / "response.json").exists():
                result.append(request)
        return sorted(result, key=lambda row: row["created"])

    def reply(self, key, status, **values):
        request = read_json(self.job(key) / "request.json")
        if (
            request
            and request.get("expires", 0) > time.time()
            and not self.cancelled(key)
        ):
            write_json(
                self.job(key) / "response.json",
                {
                    "id": key,
                    "email": request["email"],
                    "instance": request["instance"],
                    "status": status,
                    **values,
                },
            )
            if self.cancelled(key):
                (self.job(key) / "response.json").unlink(missing_ok=True)

    def response(self, key):
        return read_json(self.job(key) / "response.json")

    def started(self, key):
        write_json(self.job(key) / "started.json", {"at": time.time()})

    def waiting(self, key):
        if not self.cancelled(key):
            write_json(self.job(key) / "waiting.json", {"at": time.time()})

    def finish(self, key):
        try:
            descriptor = os.open(
                str(self.job(key) / "finished.json"), os.O_CREAT | os.O_WRONLY, 0o600
            )
            os.close(descriptor)
            (self.job(key) / "response.json").unlink(missing_ok=True)
        except FileNotFoundError:
            pass

    def cancelled(self, key):
        return (
            not (self.job(key) / "request.json").exists()
            or (self.job(key) / "finished.json").exists()
        )

    def reader_status(self, key, stage, reason):
        if not self.cancelled(key):
            write_json(
                self.job(key) / "reader.json",
                {"stage": stage, "reason": reason, "at": time.time()},
            )

    def interrupt_previous(self, client_restarted=False):
        """Only call while holding this bot's OS lock at process startup."""
        parent = self.root / "solicitudes"
        if not parent.exists():
            return
        for directory in parent.iterdir():
            if (
                directory.is_symlink()
                or not directory.is_dir()
                or not re.fullmatch(r"[a-f0-9]{32}", directory.name)
            ):
                continue
            if client_restarted:
                self.finish(directory.name)
            else:
                self.reply(
                    directory.name,
                    "stopped",
                    reason="Outlook se reinició; revisa la solicitud antes de repetir.",
                )
