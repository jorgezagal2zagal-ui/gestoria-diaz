"""Dispositivo sintético con estados, foco OTP y confirmaciones reales simuladas."""
import threading


def node(text="", rid="", kind="android.widget.TextView", bounds=(20, 20, 500, 80), **extra):
    x1, y1, x2, y2 = bounds
    return dict(text=text, rid=rid, desc="", enabled=True, clickable=True, checked=False,
                **{"class": kind}, bounds=bounds, xy=((x1+x2)//2, (y1+y2)//2),
                area=(x2-x1)*(y2-y1), package="st.android.imsspublico") | extra


class Clock:
    def __init__(self):
        self.value = 0

    def __call__(self):
        self.value += 1
        return self.value


class FakeAdb:
    def __init__(self, trace=None, fail=None, drop=False):
        self.trace = trace if trace is not None else []
        self.fail, self.drop = fail, drop
        self.cancelled = threading.Event()
        self.state = "login"
        self.curp = self.email = ""
        self.agreed = False
        self.digits = [""] * 6
        self.focus = 0
        self.sent = []
        self.verify_taps = 0
        self.procedure = None
        self.owner = None

    def check_cancel(self):
        from bot_imss_adb.adb import Cancelled
        if self.cancelled.is_set():
            raise Cancelled("Solicitud detenida.")

    def probe(self):
        self.trace.append("adb-ready")
        self.check_cancel()

    def launch(self):
        self.trace.append("imss-open")

    def shell(self, *args):
        if args == ("dumpsys", "window", "policy"):
            return "mShowingLockscreen=false"
        return "mInputShown=false"

    def fill(self, n, value):
        if n["rid"] == "txtCURP":
            self.curp = value
        elif n["rid"] == "txtCorreo":
            self.email = value

    def screen(self):
        self.check_cancel()
        if self.state == "login":
            ns = [node(self.curp, "txtCURP", "android.widget.EditText", (30, 100, 670, 170)),
                  node(self.email, "txtCorreo", "android.widget.EditText", (30, 200, 670, 270)),
                  node("He leído y acepto", "consent", "android.widget.CheckBox", (30, 300, 90, 360)),
                  node("INICIAR SESIÓN", "btnIniciar", bounds=(30, 400, 670, 470))]
            ns[2]["checked"] = self.agreed
            ns[3]["enabled"] = self.agreed and bool(self.curp and self.email)
            return ns
        if self.state == "otp":
            ns = [node("Ingresa tu código de validación"), node(self.email, bounds=(20, 150, 670, 220))]
            ns += [node(v, f"digit_{i}", "android.widget.EditText", (20+i*100, 400, 100+i*100, 490)) for i, v in enumerate(self.digits)]
            verify = node("Verificar", "verify", bounds=(30, 600, 670, 680))
            verify["enabled"] = all(self.digits)
            return ns + [verify]
        if self.state == "confirmed":
            return [node("El correo ha sido confirmado"), node("ACEPTAR", "confirm-accept", bounds=(400, 600, 650, 680))]
        if self.state == "home":
            return [node("IMSS Digital"), node("Cita médica familiar", "cita", bounds=(30, 200, 300, 400)),
                    node("Vigencia de derechos", "vigencia", bounds=(30, 600, 300, 800)),
                    node("NSS", "nss", bounds=(500, 100, 650, 170)),
                    node("Semanas cotizadas", "semanas", bounds=(350, 600, 650, 800)),
                    node("", "menu", bounds=(10, 80, 60, 130)) | {"desc": "Abrir menú"}]
        if self.state == "detail":
            title = {"nss": "Asignación/Consulta NSS", "vigencia": "Consulta vigencia de derechos", "semanas": "Semanas cotizadas"}[self.procedure]
            send = node("ENVIAR A TU CORREO ELECTRÓNICO", "send", bounds=(30, 600, 670, 680))
            send["enabled"] = self.procedure not in self.sent
            return [node(title), send]
        if self.state == "weeks":
            return [node("Semanas cotizadas"), node("CONTINUAR", "continue", bounds=(30, 600, 670, 680))]
        if self.state == "external":
            return [node("Portal externo", package="com.android.chrome")]
        if self.state == "sent":
            title = {"nss": "El documento de NSS", "vigencia": "La constancia de su vigencia de derechos", "semanas": "La constancia de semanas cotizadas"}[self.procedure]
            return [node(title + " se ha enviado a tu correo electrónico: " + self.email),
                    node("ACEPTAR", "sent-accept", bounds=(400, 600, 650, 680))]
        if self.state == "rejected":
            return [node("Error al validar el código"), node("ACEPTAR", "rejected", bounds=(400, 600, 650, 680))]
        if self.state == "menu":
            return [node("Cerrar sesión", "logout", bounds=(20, 400, 400, 480))]
        if self.state == "logout":
            return [node("¿Estás seguro de cerrar tu sesión?"), node("ACEPTAR", "logout-accept", bounds=(400, 600, 650, 680))]
        return []

    def tap(self, n):
        self.check_cancel()
        assert n["enabled"]
        rid = n["rid"]
        if rid == "consent":
            self.agreed = True
        elif rid == "btnIniciar":
            self.trace.append("imss-login")
            self.state = "otp"
        elif rid.startswith("digit_"):
            self.focus = int(rid[6:])
        elif rid == "verify":
            self.trace.append("verify")
            self.verify_taps += 1
            self.state = "rejected" if self.fail == "code" else "confirmed"
        elif rid == "confirm-accept":
            self.state = "home"
        elif rid in ("nss", "vigencia", "semanas"):
            self.procedure = rid
            self.state = "weeks" if rid == "semanas" else "detail"
        elif rid == "continue":
            self.trace.append("weeks-continue")
            self.state = "external" if self.fail == "external" else "detail"
        elif rid == "send":
            self.sent.append(self.procedure)
            self.trace.append("send-" + self.procedure)
            if self.fail != self.procedure:
                self.state = "sent"
        elif rid == "sent-accept":
            self.state = "detail"
        elif rid == "menu":
            self.state = "menu"
        elif rid == "logout":
            self.state = "logout"
        elif rid == "logout-accept":
            self.state = "login"

    def key(self, *keys):
        self.check_cancel()
        for key in keys:
            if key == "KEYCODE_BACK" and self.state in ("detail", "menu"):
                self.state = "home"
            elif key == "KEYCODE_DEL" and self.state == "otp":
                if self.digits[self.focus]:
                    self.digits[self.focus] = ""
                else:
                    self.focus = max(0, self.focus - 1)
                    self.digits[self.focus] = ""
            elif key.startswith("KEYCODE_") and len(key) == 9 and key[-1].isdigit() and self.state == "otp":
                if self.drop:
                    self.drop = False
                    continue
                self.digits[self.focus] = key[-1]
                self.focus = min(5, self.focus + 1)

    def swipe_up(self, nodes):
        pass


class FakeMailbox:
    started = None

    def __init__(self, trace=None, fail=False):
        self.trace = trace if trace is not None else []
        self.closed = False
        self.fail = fail

    def prepare(self, job, report):
        from bot_imss_adb.flow import FlowError
        self.trace.append("mail-ready")
        if self.fail:
            raise FlowError("No abrió Outlook.")

    def code(self, job, report):
        assert self.started is not None
        self.trace.append("mail-code")
        return "001177"

    def close(self):
        self.closed = True
