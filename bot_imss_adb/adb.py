"""ADB local: selección explícita, comandos limitados y errores visibles."""
from dataclasses import dataclass
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import threading
import xml.etree.ElementTree as ET


class AdbError(RuntimeError):
    pass


class Cancelled(RuntimeError):
    pass


@dataclass(frozen=True)
class Device:
    serial: str
    state: str
    model: str = ""


def devices_from(text):
    result = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 2 or parts[0].startswith(("*", "List", "adb:")):
            continue
        if parts[1] not in ("device", "offline", "unauthorized", "recovery", "sideload"):
            continue
        model = next((p[6:] for p in parts[2:] if p.startswith("model:")), "")
        result.append(Device(parts[0], parts[1], model.replace("_", " ")))
    return result


def find_adb():
    candidates = [shutil.which("adb")]
    for drive in ("D:", "C:", "E:"):
        for version in ("LDPlayer14", "LDPlayer9", "LDPlayer4.0"):
            candidates.append(drive + "\\LDPlayer\\" + version + "\\adb.exe")
    for variable in ("ANDROID_HOME", "ANDROID_SDK_ROOT"):
        if os.environ.get(variable):
            candidates.append(str(Path(os.environ[variable]) / "platform-tools" / ("adb.exe" if os.name == "nt" else "adb")))
    local = os.environ.get("LOCALAPPDATA")
    if local:
        candidates.append(str(Path(local) / "Android/Sdk/platform-tools/adb.exe"))
    return next((p for p in candidates if p and Path(p).is_file()), "")


def parse_nodes(xml):
    start = xml.find("<?xml")
    if start < 0:
        start = xml.find("<hierarchy")
    end = xml.rfind("</hierarchy>")
    if start < 0 or end < start:
        raise AdbError("ADB no devolvió una pantalla válida; revisa que Android esté desbloqueado.")
    try:
        root = ET.fromstring(xml[start:end + len("</hierarchy>")])
    except ET.ParseError:
        raise AdbError("La lectura de la pantalla quedó incompleta. Vuelve a probar ADB.") from None
    nodes = []
    for element in root.iter("node"):
        a = element.attrib
        bounds = tuple(map(int, re.findall(r"-?\d+", a.get("bounds", ""))))
        if len(bounds) != 4 or bounds[2] <= bounds[0] or bounds[3] <= bounds[1]:
            continue
        if a.get("visible-to-user") == "false":
            continue
        nodes.append({
            "rid": a.get("resource-id", "").rsplit("/", 1)[-1],
            "text": a.get("text", ""), "desc": a.get("content-desc", ""),
            "class": a.get("class", ""), "package": a.get("package", ""),
            "enabled": a.get("enabled", "true") == "true",
            "clickable": a.get("clickable", "false") == "true",
            "checked": a.get("checked", "false") == "true",
            "bounds": bounds, "xy": ((bounds[0] + bounds[2]) // 2, (bounds[1] + bounds[3]) // 2),
            "area": (bounds[2] - bounds[0]) * (bounds[3] - bounds[1]),
        })
    return nodes


class Adb:
    def __init__(self, executable, serial="", cancelled=None, runner=None):
        self.executable, self.serial = str(executable), serial
        self.cancelled = cancelled or threading.Event()
        self.runner = runner or subprocess.run

    def check_cancel(self):
        if self.cancelled.is_set():
            raise Cancelled("Solicitud detenida. No se repitió ningún envío.")

    def run(self, *args, device=True, timeout=15):
        self.check_cancel()
        if not self.executable:
            raise AdbError("Selecciona adb.exe (está junto a ldconsole.exe o en platform-tools).")
        if device and (not self.serial or self.serial.startswith("-")):
            raise AdbError("Selecciona un dispositivo ADB antes de continuar.")
        command = [self.executable]
        if device:
            command += ["-s", self.serial]
        command += [str(a) for a in args]
        try:
            result = self.runner(command, stdin=subprocess.DEVNULL, capture_output=True,
                                 timeout=timeout, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except FileNotFoundError:
            raise AdbError("No se encontró adb.exe. Selecciona su ubicación con Examinar.") from None
        except subprocess.TimeoutExpired:
            raise AdbError("ADB agotó el tiempo de respuesta; revisa la conexión del emulador.") from None
        except OSError:
            raise AdbError("Windows no pudo ejecutar ADB. Revisa su ubicación y permisos.") from None
        out = result.stdout.decode("utf-8", "replace")
        err = result.stderr.decode("utf-8", "replace")
        combined = (out + "\n" + err).lower()
        if "unauthorized" in combined:
            raise AdbError("Dispositivo no autorizado: acepta la autorización de depuración en Android.")
        if "device offline" in combined:
            raise AdbError("El dispositivo está offline. Reinicia esa instancia y vuelve a detectarla.")
        if result.returncode or re.search(r"(?m)^\s*(?:adb:\s*)?error:", combined):
            # Never echo arbitrary stdout: it can contain personal data or codes.
            raise AdbError("Falló un comando ADB. Comprueba el dispositivo seleccionado y la depuración ADB.")
        self.check_cancel()
        return out

    def devices(self):
        self.run("start-server", device=False)
        return devices_from(self.run("devices", "-l", device=False))

    def connect(self, endpoint):
        match = re.fullmatch(r"(127\.0\.0\.1|localhost):([0-9]{1,5})", endpoint.strip())
        if not match or not 1 <= int(match[2]) <= 65535:
            raise AdbError("Usa una dirección local como 127.0.0.1:5555 (puerto de tu emulador).")
        out = self.run("connect", endpoint.strip(), device=False)
        if not re.search(r"(?:already )?connected to\b", out, re.I):
            raise AdbError("No se conectó ese puerto. Revisa el puerto ADB y que el emulador esté encendido.")
        return self.devices()

    def shell(self, *args, timeout=15):
        # adb shell invokes a remote shell: quote each argument for Android too.
        return self.run("shell", " ".join(shlex.quote(str(a)) for a in args), timeout=timeout)

    def probe(self):
        if self.run("get-state").strip() != "device":
            raise AdbError("El dispositivo ADB todavía no está disponible.")
        if self.shell("getprop", "sys.boot_completed").strip() != "1":
            raise AdbError("Android todavía está iniciando. Espera y pulsa Probar conexión.")
        if "package:" not in self.shell("pm", "path", "st.android.imsspublico"):
            raise AdbError("IMSS Digital no está instalado en el dispositivo seleccionado.")
        return "ADB conectado · Android listo · IMSS Digital instalado"

    def screen(self):
        # A fresh unique file prevents reading a stale dump after a failed command.
        import uuid
        path = "/sdcard/imss_adb_" + uuid.uuid4().hex + ".xml"
        self.shell("uiautomator", "dump", path, timeout=15)
        try:
            return parse_nodes(self.shell("cat", path))
        finally:
            if not self.cancelled.is_set():
                try:
                    self.shell("rm", "-f", path, timeout=3)
                except AdbError:
                    pass

    def tap(self, node):
        if not node.get("enabled"):
            raise AdbError("El botón todavía no está disponible.")
        self.shell("input", "tap", *node["xy"])

    def key(self, *keys):
        self.shell("input", "keyevent", *keys)

    def fill(self, node, value):
        if not re.fullmatch(r"[A-Za-z0-9@._+\-]{1,254}", value):
            raise ValueError("El campo contiene caracteres no admitidos.")
        self.tap(node)
        self.key("KEYCODE_MOVE_END")
        remaining = min(len(node.get("text", "")), 254)
        if remaining:
            self.key(*(["KEYCODE_DEL"] * remaining))
        self.shell("input", "text", value)

    def swipe_up(self, nodes):
        width = max((n["bounds"][2] for n in nodes), default=720)
        height = max((n["bounds"][3] for n in nodes), default=1280)
        self.shell("input", "swipe", width // 2, int(height * .8), width // 2, int(height * .35), 250)

    def launch(self):
        self.shell("monkey", "-p", "st.android.imsspublico", "-c", "android.intent.category.LAUNCHER", "1")
