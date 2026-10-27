"""Non-invasive local checks. Does not import account files or contact Microsoft."""

from pathlib import Path
import hashlib
import json
import sys
import tempfile


def main():
    root = Path(__file__).resolve().parent
    sys.path.insert(0, str(root / "outlook_bot"))
    from automation import available_browsers
    from conexion.bridge import Bridge, read_json, write_json
    from conexion.reader import extract_code

    checks = []
    checks.append(("Python 3.10 o superior", sys.version_info >= (3, 10)))
    try:
        import tkinter

        checks.append(("Tk disponible", bool(tkinter.TkVersion)))
    except ImportError:
        checks.append(("Tk disponible", False))
    try:
        import selenium

        checks.append(("Selenium disponible", bool(selenium.__version__)))
    except ImportError:
        checks.append(("Selenium disponible", False))
    checks.append(("Navegador compatible instalado", bool(available_browsers())))
    bridge = Bridge()
    try:
        bridge.root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=bridge.root) as tmp:
            path = Path(tmp) / "test.json"
            write_json(path, {"test": True})
            checks.append(
                ("Escritura y lectura local", read_json(path) == {"test": True})
            )
    except OSError:
        checks.append(("Escritura y lectura local", False))
    checks.append(
        (
            "Extractor de código: ejemplo sintético",
            extract_code("Tu código de validación es: 012345") == "012345",
        )
    )
    manifest = root / "MANIFIESTO_V4.json"
    if manifest.exists():
        info = json.loads(manifest.read_text(encoding="utf-8"))
        checks.append(
            (
                "Archivos del paquete íntegros",
                all(
                    (root / name).is_file()
                    and hashlib.sha256((root / name).read_bytes()).hexdigest() == digest
                    for name, digest in info["archivos"].items()
                ),
            )
        )
    for label, ok in checks:
        print(("OK   " if ok else "FALTA ") + label)
    print("\nNo se abrió ninguna cuenta ni se inició un trámite.")
    print(
        "Estas comprobaciones locales no prueban la recepción real del correo ni LDPlayer."
    )
    return 0 if all(ok for _, ok in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
