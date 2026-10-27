"""Build V3 unified control panel and preserve the exact V1 and V2 backups."""

import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
BACKUP_SHA256 = "cfe001fd6ba214aaae84262480b489c5be30492dba884dd21628727b34c99ebb"
OUTLOOK_FILES = (
    "app.py",
    "core.py",
    "automation.py",
    "history.py",
    "requirements.txt",
    "INICIAR.bat",
    "LEEME.txt",
)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build():
    backup = ROOT / "respaldos/GESTORIA_DIAZ_CONECTADOS_V2_RESPALDO.zip"
    assert digest(backup) == BACKUP_SHA256, "El respaldo V2 cambió"
    originals = {}
    with zipfile.ZipFile(backup) as v1:
        for name in OUTLOOK_FILES:
            path = ROOT / "outlook_bot" / name
            assert path.read_bytes() == v1.read(
                "GESTORIA_DIAZ_CONECTADOS_V2/outlook_bot/" + name
            ), "Cambió Outlook original: " + name
            originals["outlook_bot/" + name] = digest(path)
    files = [
        "gestoria_5_instancias.py",
        "outlook_conectado.py",
        "panel_unificado.py",
        "preparar_entorno.py",
        "diagnostico_conexion.py",
        "INICIAR_TODO.bat",
        "INICIAR_IMSS.bat",
        "INICIAR_OUTLOOK_CONECTADO.bat",
        "DIAGNOSTICO.bat",
        "LEEME_CONECTADOS.txt",
        "VALIDACION_V3.txt",
        "ejemplos/FORMATO_LOTE.txt",
        "ejemplos/FORMATO_LOTE.csv",
        "respaldos/GESTORIA_DIAZ_CONECTADOS_V1_RESPALDO.zip",
        "respaldos/GESTORIA_DIAZ_CONECTADOS_V2_RESPALDO.zip",
        "respaldos/LEEME_RESPALDO.json",
        "respaldos/LEEME_RESPALDO_V2.json",
    ]
    files += [
        str(p.relative_to(ROOT)) for p in sorted((ROOT / "conexion").glob("*.py"))
    ]
    files += ["outlook_bot/" + name for name in OUTLOOK_FILES]
    manifest = {
        "version": "3.0",
        "respaldo_v2_sha256": BACKUP_SHA256,
        "outlook_original": originals,
        "validacion": "Ver VALIDACION_V3.txt: pruebas locales y bandejas simuladas; sin prueba real en Windows.",
        "archivos": {name: digest(ROOT / name) for name in sorted(files)},
    }
    manifest_path = ROOT / "MANIFIESTO_V3.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    files += ["MANIFIESTO_V3.json"]
    target = ROOT / "GESTORIA_DIAZ_CONECTADOS_V3.zip"
    temporary = target.with_suffix(".zip.tmp")
    prefix = "GESTORIA_DIAZ_CONECTADOS_V3/"
    with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(files):
            archive.write(ROOT / name, prefix + name)
    with zipfile.ZipFile(temporary) as archive:
        assert archive.testzip() is None
        for name in files:
            assert archive.read(prefix + name) == (ROOT / name).read_bytes()
    temporary.replace(target)
    print(
        f"V3: {len(files)} archivos, {target.stat().st_size} bytes, SHA256 {digest(target)}"
    )
    print("V2 y los siete archivos originales de Outlook: idénticos")


if __name__ == "__main__":
    build()
