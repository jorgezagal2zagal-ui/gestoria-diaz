"""ZIP independiente: sin datos personales ni dependencia del bot anterior."""
import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "bot_imss_adb"
OUTPUT = ROOT / "BOT_DIAZ_IMSS_ADB_NUEVO_V1.zip"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def build():
    files = ["__init__.py", "ABRIR_BOT.bat", "LEEME.txt", "VALIDACION.txt", "requirements.txt",
             "adb.py", "app.py", "flow.py", "locking.py", "mail_service.py", "storage.py",
             "correo/__init__.py", "correo/automation.py", "correo/reader.py"]
    # New independent reader and login backend preserve their verified source.
    assert (SOURCE / "correo/reader.py").read_bytes() == (ROOT / "conexion/reader.py").read_bytes()
    assert (SOURCE / "correo/automation.py").read_bytes() == (ROOT / "outlook_bot/automation.py").read_bytes()
    payload = {}
    for name in files:
        data = (SOURCE / name).read_bytes()
        if name.endswith(".bat"):
            data = data.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
        payload[name] = data
    manifest = {"version": "nuevo-adb-1", "archivos": {n: digest(d) for n, d in payload.items()}}
    payload["MANIFIESTO.json"] = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode()
    with zipfile.ZipFile(OUTPUT, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in payload.items():
            info = zipfile.ZipInfo("BOT_DIAZ_IMSS_ADB_V1/" + name, date_time=(2026, 10, 27, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, data)
    with zipfile.ZipFile(OUTPUT) as archive:
        assert archive.testzip() is None
        for name, data in payload.items():
            assert archive.read("BOT_DIAZ_IMSS_ADB_V1/" + name) == data
    print(OUTPUT.name, len(payload), "archivos", OUTPUT.stat().st_size, "bytes", "SHA256", digest(OUTPUT.read_bytes()))


if __name__ == "__main__":
    build()
