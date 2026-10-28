"""Flujo nuevo, por estados visibles; nunca da por enviado un trámite sin evidencia."""
from dataclasses import dataclass, field
from datetime import date
import re
import time
import unicodedata

try:
    from .adb import AdbError, Cancelled
except ImportError:
    from adb import AdbError, Cancelled


class FlowError(RuntimeError):
    pass


def norm(value):
    value = unicodedata.normalize("NFD", value.casefold())
    return " ".join("".join(c for c in value if not unicodedata.combining(c)).split())


def labels(node):
    return tuple(norm(v) for v in (node.get("text", ""), node.get("desc", "")) if v)


def words(nodes):
    return " | ".join(v for n in nodes for v in labels(n))


def button(nodes, pattern):
    candidates = [n for n in nodes if n.get("enabled") and any(re.fullmatch(pattern, v) for v in labels(n))]
    return min(candidates, key=lambda n: n["area"]) if candidates else None


def by_id(nodes, rid):
    return next((n for n in nodes if n["rid"] == rid and n["enabled"]), None)


def login_screen(nodes):
    return bool(by_id(nodes, "txtCURP") and by_id(nodes, "txtCorreo"))


def home_screen(nodes):
    return (not login_screen(nodes) and button(nodes, r"vigencia de derechos") is not None
            and button(nodes, r"(?:cita medica(?: familiar)?|cedula digital de salud)") is not None)


def otp_fields(nodes):
    edits = [n for n in nodes if n["enabled"] and n["class"].endswith("EditText")]
    rows = {}
    for ref in edits:
        h = ref["bounds"][3] - ref["bounds"][1]
        row = []
        for n in edits:
            w2, h2 = n["bounds"][2] - n["bounds"][0], n["bounds"][3] - n["bounds"][1]
            if .3 <= w2 / h2 <= 2 and abs(n["xy"][1] - ref["xy"][1]) <= min(h, h2) * .25:
                row.append(n)
        if len(row) != 6:
            continue
        row.sort(key=lambda n: n["xy"][0])
        widths = [n["bounds"][2] - n["bounds"][0] for n in row]
        heights = [n["bounds"][3] - n["bounds"][1] for n in row]
        gaps = [row[i + 1]["xy"][0] - row[i]["xy"][0] for i in range(5)]
        if max(widths) <= min(widths) * 1.8 and max(heights) <= min(heights) * 1.5 and min(gaps) >= min(widths) * .6 and max(gaps) <= max(widths) * 2.2:
            rows[tuple(n["xy"] for n in row)] = row
    if len(rows) == 1:
        return next(iter(rows.values()))
    if rows:
        return []
    single = [n for n in edits if re.sub(r"[^a-z]", "", n["rid"].casefold()) in (
        "otp", "otpinput", "codeinput", "verificationcode", "validationcode", "txtcodigo", "codigovalidacion")]
    return single if len(single) == 1 else []


def otp_value(fields):
    if len(fields) == 6 and all(re.fullmatch(r"[0-9]?", n["text"]) for n in fields):
        return "".join(n["text"] for n in fields)
    if len(fields) == 1 and re.fullmatch(r"[0-9]{0,6}", fields[0]["text"]):
        return fields[0]["text"]
    return ""


def android_locked(text):
    flags = re.findall(
        r"\b(?:isKeyguardShowing|mKeyguardShowing|mIsKeyguardShowing|keyguardShowing|"
        r"isStatusBarKeyguard|mShowingLockscreen|mDreamingLockscreen)\s*(?:\(\))?\s*[:=]\s*(true|false)\b", text, re.I)
    lines = text.splitlines()
    for pos, line in enumerate(lines):
        if not re.search(r"\b(?:KeyguardServiceDelegate|mKeyguardDelegate)\b", line, re.I):
            continue
        indent = len(line) - len(line.lstrip())
        block = [line]
        for following in lines[pos + 1:]:
            if following.strip() and len(following) - len(following.lstrip()) <= indent:
                break
            block.append(following)
        flags.extend(re.findall(r"\b(?:showing|inputRestricted)\s*[:=]\s*(true|false)\b", "\n".join(block), re.I))
    return True if any(v.lower() == "true" for v in flags) else False if flags else None


def sent_confirmation(nodes, procedure, email):
    text = words(nodes)
    if re.search(r"\berror\b|\bno (?:se|ha|fue|pudo)\b|se enviara|sera enviad|pendiente", text):
        return False
    subjects = {"nss": r"nss|numero de seguridad|informacion solicitada|constancia|documento",
                "vigencia": r"vigencia|constancia", "semanas": r"semanas|constancia|documento"}
    if not re.search(subjects[procedure], text):
        return False
    if not re.search(r"\b(?:ha sido enviad[oa]|se (?:ha )?enviado|se envio|enviamos)\b", text):
        # Most common IMSS phrasing: "la constancia ... se ha enviado a tu correo".
        return False
    addresses = re.findall(r"[a-z0-9._+\-]+@[a-z0-9.\-]+\.[a-z]{2,}", text)
    return "correo" in text and (not addresses or all(a == email.casefold() for a in addresses))


@dataclass(frozen=True)
class Job:
    curp: str
    email: str
    procedures: tuple = ("nss", "vigencia", "semanas")
    pin: str = field(default="", repr=False)
    allow_relink: bool = False
    logout: bool = True

    def validate(self):
        if not re.fullmatch(r"[A-Z][AEIOUX][A-Z]{2}[0-9]{6}[HM][A-Z]{5}[A-Z0-9][0-9]", self.curp):
            raise ValueError("La CURP debe tener 18 caracteres y un formato válido.")
        yy, mm, dd = int(self.curp[4:6]), int(self.curp[6:8]), int(self.curp[8:10])
        try:
            date((2000 if self.curp[16].isalpha() else 1900) + yy, mm, dd)
        except ValueError:
            raise ValueError("La fecha de la CURP no es válida.") from None
        if not re.fullmatch(r"[A-Za-z0-9._+\-]{1,64}@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", self.email) or len(self.email) > 254:
            raise ValueError("Escribe un correo válido.")
        if self.pin and not re.fullmatch(r"[0-9]{4,12}", self.pin):
            raise ValueError("El PIN opcional debe tener de 4 a 12 dígitos.")
        if not self.procedures or len(set(self.procedures)) != len(self.procedures) or any(p not in ("nss", "vigencia", "semanas") for p in self.procedures):
            raise ValueError("Elige al menos un trámite válido, sin duplicados.")


class Flow:
    def __init__(self, adb, report=None, clock=time.monotonic, poll=.4):
        self.adb, self.clock, self.poll = adb, clock, poll
        self.report = report or (lambda stage, detail: None)
        self.results = {}
        self.pin_used = False

    def wait(self, probe, seconds, error):
        deadline = self.clock() + seconds
        while True:
            self.adb.check_cancel()
            nodes = self.adb.screen()
            result = probe(nodes)
            if result:
                return result
            if self.clock() >= deadline:
                raise FlowError(error)
            if self.adb.cancelled.wait(self.poll):
                self.adb.check_cancel()

    def keyguard(self, job):
        text = self.adb.shell("dumpsys", "window", "policy").lower()
        if android_locked(text) is not True:
            return
        if not job.pin:
            raise FlowError("Android está bloqueado. Desbloquéalo o escribe su PIN opcional en el panel.")
        self.report("desbloqueo", "Desbloqueando Android con el PIN indicado, una sola vez.")
        self.adb.key("KEYCODE_WAKEUP")
        size = self.adb.shell("wm", "size")
        dimensions = re.findall(r"([0-9]+)x([0-9]+)", size)
        w, h = map(int, dimensions[-1]) if dimensions else (720, 1280)
        self.adb.shell("input", "swipe", w // 2, int(h * .8), w // 2, int(h * .25), 250)
        for digit in job.pin:
            self.adb.key("KEYCODE_" + digit)
        self.adb.key("KEYCODE_ENTER")
        deadline = self.clock() + 8
        while True:
            text = self.adb.shell("dumpsys", "window", "policy").lower()
            if android_locked(text) is False:
                return
            if self.clock() >= deadline:
                raise FlowError("No se confirmó el desbloqueo. Revisa el PIN; no se volverá a enviar.")
            self.adb.cancelled.wait(self.poll)

    def login(self, job, mailbox):
        self.report("imss", "Abriendo IMSS Digital.")
        self.keyguard(job)
        self.adb.launch()

        def find_login(nodes):
            if "permiso de ubicacion" in words(nodes):
                cancel = button(nodes, "cancelar")
                if cancel:
                    self.adb.tap(cancel)
                return None
            if home_screen(nodes):
                raise FlowError("Ya existe una sesión IMSS. Ciérrala en el emulador antes de iniciar otra solicitud.")
            return nodes if login_screen(nodes) else None

        nodes = self.wait(find_login, 35, "No apareció Inicia sesión. Revisa el emulador y que IMSS esté desbloqueado.")
        self.adb.fill(by_id(nodes, "txtCURP"), job.curp)
        email_field = by_id(self.adb.screen(), "txtCorreo")
        if not email_field:
            raise FlowError("La pantalla cambió antes de escribir el correo. No se inició la sesión.")
        self.adb.fill(email_field, job.email)
        nodes = self.adb.screen()
        for rid, expected in (("txtCURP", job.curp), ("txtCorreo", job.email)):
            field_node = by_id(nodes, rid)
            if not field_node or field_node["text"].casefold() != expected.casefold():
                raise FlowError("IMSS no conservó correctamente la CURP o el correo. No se inició la sesión.")
        # Hide the keyboard only when Android reports it visible.
        ime = self.adb.shell("dumpsys", "input_method")
        if re.search(r"(?:mInputShown|mIsInputViewShown)\s*=\s*true", ime):
            self.adb.key("KEYCODE_BACK")
            nodes = self.adb.screen()
        consent = [n for n in nodes if n["class"].endswith("CheckBox") and not n["checked"] and n["enabled"]]
        if len(consent) == 1:
            self.adb.tap(consent[0])
        else:
            agree = button(nodes, r"he leido y acepto(?: el aviso de privacidad)?\.?")
            start = by_id(nodes, "btnIniciar")
            if agree and (not start or not start["enabled"]):
                self.adb.tap(agree)
        nodes = self.wait(lambda ns: ns if by_id(ns, "btnIniciar") else None, 8, "INICIAR SESIÓN sigue desactivado. Revisa CURP, correo y aviso de privacidad.")
        # Freshness boundary immediately precedes the one and only login click.
        mailbox.started = time.time()
        self.adb.tap(by_id(nodes, "btnIniciar"))
        self.report("codigo", "Esperando que IMSS solicite el código del mismo correo.")
        relink_used = False
        confirm_used = False

        def waiting_code(ns):
            nonlocal relink_used, confirm_used
            text = words(ns)
            if "curp" in text and "vinculada" in text and "otro dispositivo" in text:
                if not job.allow_relink:
                    raise FlowError("IMSS solicita cambiar de dispositivo. Autorízalo en el panel antes de empezar.")
                relink = button(ns, "si,? quiero hacer el cambio")
                if relink and not relink_used:
                    self.adb.tap(relink)
                    relink_used = True
                return None
            if otp_fields(ns) and re.search(r"codigo de (?:validacion|verificacion)", text):
                addresses = re.findall(r"[a-z0-9._+\-]+@[a-z0-9.\-]+\.[a-z]{2,}", text)
                if not addresses or any(a != job.email.casefold() for a in addresses):
                    raise FlowError("No pude confirmar que IMSS envió el código al correo de esta solicitud.")
                return ns
            if re.search(r"validacion de identidad|confirma tu identidad|(?:ingresa|introduce) (?:tu |el )?pin", text):
                if re.search(r"incorrect|demasiados intentos", text):
                    raise FlowError("Android rechazó el PIN de identidad. No se volverá a enviar.")
                if not self.pin_used:
                    if not job.pin:
                        raise FlowError("IMSS solicita el PIN de Android. Escríbelo en el panel o valida manualmente en el emulador.")
                    edits = [n for n in ns if n["enabled"] and n["class"].endswith("EditText")]
                    if len(edits) != 1:
                        raise FlowError("No identifiqué el campo de PIN. Valida la identidad en el emulador.")
                    self.adb.tap(edits[0])
                    if edits[0]["text"]:
                        self.adb.key("KEYCODE_MOVE_END", *(["KEYCODE_DEL"] * min(len(edits[0]["text"]), 12)))
                    for digit in job.pin:
                        self.adb.key("KEYCODE_" + digit)
                    self.adb.key("KEYCODE_ENTER")
                    self.pin_used = True
                return None
            if "confirmado tu correo" in text and not confirm_used:
                confirm = button(ns, "confirmar")
                if confirm:
                    self.adb.tap(confirm)
                    confirm_used = True
                return None
            if re.search(r"\berror\b|curp (?:incorrecta|invalida)|no existe", text):
                raise FlowError("IMSS mostró un error al iniciar sesión. Revisa el aviso en el emulador.")
            return None

        self.wait(waiting_code, 75, "No apareció la pantalla del código. Revisa el emulador antes de repetir.")

    def enter_code(self, code):
        if not re.fullmatch(r"[0-9]{6}", code or ""):
            raise FlowError("El código debe contener exactamente seis dígitos.")
        for attempt in range(2):
            fields = otp_fields(self.adb.screen())
            if len(fields) not in (1, 6):
                raise FlowError("No identifiqué las seis casillas del código; no escribiré en otro campo.")
            if otp_value(fields) == code:
                return
            count = len(fields)
            for pos in reversed(range(count)):
                fresh = otp_fields(self.adb.screen())
                if len(fresh) != count:
                    raise FlowError("La pantalla cambió mientras se borraba el código.")
                if fresh[pos]["text"]:
                    self.adb.tap(fresh[pos])
                    self.adb.key("KEYCODE_MOVE_END", *(["KEYCODE_DEL"] * min(len(fresh[pos]["text"]), 6 if count == 1 else 1)))
            for pos, digit in enumerate(code):
                fresh = otp_fields(self.adb.screen())
                if len(fresh) != count:
                    raise FlowError("La pantalla cambió mientras se escribía el código.")
                if count == 6 or pos == 0:
                    self.adb.tap(fresh[pos if count == 6 else 0])
                self.adb.key("KEYCODE_" + digit)
            if otp_value(otp_fields(self.adb.screen())) == code:
                return
            if not attempt:
                self.report("codigo", "El código quedó incompleto. Reescribiéndolo una sola vez.")
        raise FlowError("No quedaron escritos los seis dígitos. No se pulsó Verificar.")

    def verify(self, code):
        self.enter_code(code)
        nodes = self.adb.screen()
        if otp_value(otp_fields(nodes)) != code:
            raise FlowError("Las seis casillas cambiaron antes de verificar. No se envió el código.")
        verify = button(nodes, r"verificar|validar")
        if not verify:
            raise FlowError("Verificar no está habilitado. No se envió el código.")
        self.adb.tap(verify)
        accepted = False

        def confirmed(nodes):
            nonlocal accepted
            text = words(nodes)
            if re.search(r"error al validar|codigo (?:incorrecto|invalido|expirado|vencido)", text):
                raise FlowError("IMSS rechazó el código. No se solicitó ningún trámite ni se cambió de correo.")
            if "correo ha sido confirmado" in text:
                accept = button(nodes, "aceptar")
                if accept and not accepted:
                    self.adb.tap(accept)
                    accepted = True
                return None
            return nodes if home_screen(nodes) else None

        self.wait(confirmed, 35, "IMSS no confirmó el acceso. No se volverá a enviar el código automáticamente.")

    def home(self):
        nodes = self.adb.screen()
        if home_screen(nodes):
            return nodes
        for _ in range(3):
            if login_screen(nodes) or otp_fields(nodes):
                raise FlowError("La sesión terminó; no se continuará con otro trámite.")
            # A modal with Aceptar requires explicit recognition, not generic clicks.
            if button(nodes, "aceptar"):
                raise FlowError("Hay un aviso pendiente. Revísalo en el emulador antes de continuar.")
            self.adb.key("KEYCODE_BACK")
            try:
                return self.wait(lambda ns: ns if home_screen(ns) else None, 3, "inicio")
            except FlowError:
                nodes = self.adb.screen()
        raise FlowError("No se pudo volver al inicio de IMSS. Revisa la pantalla.")

    def select_procedure(self, name):
        nodes = self.home()
        patterns = {"nss": r"(?:consulta\s+)?nss|asignacion/consulta nss|asignacion / consulta nss",
                    "vigencia": r"vigencia de derechos", "semanas": r"(?:constancia de )?semanas cotizadas"}
        for attempt in range(8):
            target = button(nodes, patterns[name])
            if target:
                self.adb.tap(target)
                return
            if attempt == 3:
                menu = button(nodes, r"(?:abrir )?menu(?: de navegacion)?|open navigation drawer|navigate up")
                if menu:
                    self.adb.tap(menu)
                    nodes = self.adb.screen()
                    tramita = button(nodes, "tramita")
                    if tramita:
                        self.adb.tap(tramita)
                        nodes = self.adb.screen()
                        continue
            self.adb.swipe_up(nodes)
            nodes = self.adb.screen()
        raise FlowError("No encontré el trámite seleccionado en IMSS.")

    def procedure(self, name, job):
        self.report(name, "Abriendo trámite " + name + ".")
        self.select_procedure(name)
        sent = False
        continued = False

        def progress(nodes):
            nonlocal sent, continued
            text = words(nodes)
            if sent_confirmation(nodes, name, job.email):
                accept = button(nodes, "aceptar")
                if accept:
                    self.adb.tap(accept)
                return "confirmado"
            if re.search(r"\berror\b|no se pudo|servicio no disponible", text):
                raise FlowError("IMSS mostró un error en " + name + ". Revisa el aviso.")
            external = any(n.get("package") and n["package"] not in ("st.android.imsspublico", "com.android.systemui", "com.google.android.inputmethod.latin", "com.android.inputmethod.latin") for n in nodes)
            if external:
                raise FlowError("El trámite abrió otra aplicación o un portal externo. Continúa ahí manualmente; no se confirmó el envío.")
            send = button(nodes, r"enviar a tu correo(?: electronico)?")
            if send and not sent:
                self.adb.tap(send)
                sent = True
                self.results[name] = "envio_solicitado_sin_confirmar"
                self.report(name, "Se pulsó Enviar una vez; esperando confirmación de IMSS.")
            elif name == "semanas" and not continued:
                proceed = button(nodes, "continuar")
                if proceed:
                    self.adb.tap(proceed)
                    continued = True
                    self.results[name] = "continuar_pulsado_sin_confirmar"
                    self.report(name, "Se pulsó Continuar; esperando el resultado real.")
            return None

        try:
            result = self.wait(progress, 35, "IMSS no confirmó el envío de " + name + ". No se repetirá automáticamente.")
        except (FlowError, AdbError, Cancelled):
            self.results.setdefault(name, "sin_confirmar")
            raise
        self.results[name] = result
        self.report(name, "IMSS confirmó el envío de " + name + " al correo de esta solicitud.")
        return result

    def logout(self):
        self.report("cerrando", "Cerrando únicamente esta sesión de IMSS.")
        nodes = self.home()
        menu = button(nodes, r"(?:abrir )?menu(?: de navegacion)?|open navigation drawer|navigate up")
        if not menu:
            raise FlowError("Los trámites terminaron, pero no identifiqué el menú para cerrar sesión.")
        self.adb.tap(menu)
        nodes = self.wait(lambda ns: ns if button(ns, "cerrar sesion") else None, 8, "No apareció Cerrar sesión.")
        self.adb.tap(button(nodes, "cerrar sesion"))
        clicked = False

        def closed(ns):
            nonlocal clicked
            if login_screen(ns):
                return True
            if re.search(r"(?:estas seguro|deseas).*cerrar.*sesion", words(ns)) and not clicked:
                accept = button(ns, r"aceptar|si")
                if accept:
                    self.adb.tap(accept)
                    clicked = True
            return False

        self.wait(closed, 12, "No se confirmó el cierre de sesión; revisa IMSS.")
        self.report("cerrando", "Cierre de sesión confirmado: IMSS volvió al formulario de acceso.")

    def run(self, job, mailbox):
        job.validate()
        self.report("adb", "Comprobando ADB y la aplicación.")
        self.adb.probe()
        try:
            # Outlook is ready, and old messages baselined, before requesting a new code.
            mailbox.prepare(job, self.report)
            self.login(job, mailbox)
            code = mailbox.code(job, self.report)
            self.verify(code)
            code = None
            self.report("codigo", "Código de seis dígitos verificado y aceptado por IMSS.")
            self.report("imss", "Sesión IMSS iniciada con el correo de esta solicitud.")
            for name in job.procedures:
                self.procedure(name, job)
            if job.logout:
                self.logout()
            self.report("terminado", "Trámites confirmados" + (" y sesión cerrada." if job.logout else "."))
            return dict(self.results)
        finally:
            mailbox.close()
