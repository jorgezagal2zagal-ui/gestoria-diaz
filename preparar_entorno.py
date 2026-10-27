"""Prepare the companion environment once; original Outlook files stay unchanged."""

from pathlib import Path
import hashlib
import json
import os
import subprocess
import sys
import time
import venv
from conexion.locking import ProcessLock


def main():
    root = Path(__file__).resolve().parent
    if sys.version_info < (3, 10):
        print("Instala Python 3.10 o superior con Tcl/Tk y el lanzador py.")
        return 1
    lock = ProcessLock(root / ".entorno.lock")
    deadline = time.monotonic() + 90
    while not lock.acquire():
        if time.monotonic() > deadline:
            print(
                "La preparación está ocupada en otra ventana. Espera y vuelve a abrir."
            )
            return 1
        time.sleep(0.5)
    try:
        folder = root / ".venv"
        interpreter = folder / (
            "Scripts/python.exe" if os.name == "nt" else "bin/python"
        )
        requirements = root / "outlook_bot/requirements.txt"
        signature = hashlib.sha256(requirements.read_bytes()).hexdigest()
        marker = folder / "gestoria-requisitos.json"
        if not interpreter.exists():
            print("Preparando entorno local de Gestoría Díaz V3...")
            venv.EnvBuilder(with_pip=True, symlinks=os.name != "nt").create(folder)
        installed = False
        try:
            saved = json.loads(marker.read_text())
            installed = (
                saved.get("requisitos") == signature
                and subprocess.run(
                    [str(interpreter), "-c", "import selenium, tkinter"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=15,
                ).returncode
                == 0
            )
        except (OSError, ValueError, subprocess.TimeoutExpired):
            pass
        if not installed:
            subprocess.run(
                [str(interpreter), "-m", "pip", "install", "-r", str(requirements)],
                check=True,
                timeout=240,
            )
            subprocess.run(
                [str(interpreter), "-c", "import selenium, tkinter"],
                check=True,
                timeout=15,
            )
            marker.write_text(json.dumps({"requisitos": signature}), encoding="utf-8")
        print("Entorno V3 listo.")
        return 0
    except (OSError, subprocess.SubprocessError):
        print(
            "No se pudo preparar el entorno. Revisa Python, Tcl/Tk y la conexión a Internet."
        )
        return 1
    finally:
        lock.release()


if __name__ == "__main__":
    raise SystemExit(main())
