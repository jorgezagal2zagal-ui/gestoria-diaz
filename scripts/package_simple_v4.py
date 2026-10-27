"""Clean single-panel release. Preserve V3 and omit old standalone entry points."""

import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
V3_SHA = "073d33ce2d53b3445f1ddbb27aeae6d9d622a54f138304bb6d2feba1f8cd190c"
OUTLOOK = ("app.py", "core.py", "automation.py", "history.py", "requirements.txt")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build():
    backup = ROOT / "respaldos/GESTORIA_DIAZ_CONECTADOS_V3_RESPALDO.zip"
    assert digest(backup) == V3_SHA
    with zipfile.ZipFile(backup) as z:
        for name in OUTLOOK:
            assert (ROOT / "outlook_bot" / name).read_bytes() == z.read(
                "GESTORIA_DIAZ_CONECTADOS_V3/outlook_bot/" + name
            )
    files = [
        "ABRIR_BOT.bat",
        "INICIAR_TODO.bat",
        "INICIAR_IMSS.bat",
        "INICIAR_OUTLOOK_CONECTADO.bat",
        "panel_unificado.py",
        "gestoria_5_instancias.py",
        "outlook_conectado.py",
        "preparar_entorno.py",
        "diagnostico_conexion.py",
        "LEEME_CONECTADOS.txt",
        "VALIDACION_V4.txt",
        "respaldos/GESTORIA_DIAZ_CONECTADOS_V3_RESPALDO.zip",
    ]
    files += [
        str(p.relative_to(ROOT)) for p in sorted((ROOT / "conexion").glob("*.py"))
    ]
    files += ["outlook_bot/" + n for n in OUTLOOK]
    manifest = {
        "version": "4-simple",
        "respaldo_v3_sha256": V3_SHA,
        "archivos": {n: digest(ROOT / n) for n in files},
    }
    (ROOT / "MANIFIESTO_V4.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    files += ["MANIFIESTO_V4.json"]
    output = ROOT / "GESTORIA_DIAZ_PANEL_UNICO_SIMPLE_V4.zip"
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as z:
        for name in files:
            z.write(ROOT / name, "GESTORIA_DIAZ_SIMPLE/" + name)
    with zipfile.ZipFile(output) as z:
        assert z.testzip() is None
        for name in files:
            assert z.read("GESTORIA_DIAZ_SIMPLE/" + name) == (ROOT / name).read_bytes()
    print(
        "ZIP simple:",
        len(files),
        "archivos;",
        output.stat().st_size,
        "bytes; SHA256",
        digest(output),
    )


if __name__ == "__main__":
    build()
