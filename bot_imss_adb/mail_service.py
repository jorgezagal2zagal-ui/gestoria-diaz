"""One mailbox per request; optional manual entry; no credential persistence."""
from dataclasses import dataclass, field
import re
import time

try:
    from .adb import Cancelled
    from .flow import FlowError
    from .correo import automation
    from .correo.reader import OutlookReader
except ImportError:
    from adb import Cancelled
    from flow import FlowError
    from correo import automation
    from correo.reader import OutlookReader


@dataclass
class Account:
    address: str
    password: str = field(repr=False)


class ManualMailbox:
    started = None

    def __init__(self, ask_code):
        self.ask_code = ask_code

    def prepare(self, job, report):
        report("correo", "Modo manual: el código se pegará en el panel cuando IMSS lo solicite.")

    def code(self, job, report):
        report("codigo", "Pega el código más reciente del correo de esta solicitud y pulsa Enviar código.")
        code = self.ask_code(job.email)
        if not re.fullmatch(r"[0-9]{6}", code or ""):
            raise FlowError("Se necesita el código de seis dígitos del correo de esta solicitud.")
        return code

    def close(self):
        pass


class OutlookMailbox:
    started = None

    def __init__(self, password, cancelled, timeout=180, login=None, reader_factory=OutlookReader):
        self.password, self.cancelled, self.timeout = password, cancelled, timeout
        self.login = login or automation.try_account
        self.reader_factory = reader_factory
        self.driver = self.reader = None

    def prepare(self, job, report):
        if not self.password:
            raise FlowError("Escribe la contraseña de Outlook o elige Código manual.")
        report("correo", "Abriendo Outlook antes de iniciar la solicitud IMSS.")
        browsers = automation.available_browsers()
        if not browsers:
            raise FlowError("Instala Chrome o Edge para leer Outlook automáticamente.")
        try:
            self.driver = self.login(Account(job.email, self.password), browsers, self.cancelled.is_set,
                                     lambda _msg: report("correo", "Esperando acceso a Outlook."))
            self.password = ""
            self.reader = self.reader_factory(self.driver, cancelled=self.cancelled.is_set,
                                             expected_curp=job.curp,
                                             report=lambda _msg: report("correo", "Esperando que cargue la bandeja."))
            deadline = time.monotonic() + 12
            refreshed = False
            while True:
                if self.cancelled.is_set():
                    raise Cancelled("Solicitud detenida.")
                try:
                    self.reader.baseline()
                    break
                except RuntimeError:
                    if time.monotonic() >= deadline:
                        if refreshed:
                            raise FlowError("Outlook abrió, pero no pude preparar el lector. IMSS no se inició.") from None
                        self.driver.refresh()
                        deadline = time.monotonic() + 12
                        refreshed = True
                    self.cancelled.wait(.3)
            report("correo", "Bandeja lista. Continuando en IMSS con el mismo correo.")
        except (Cancelled, FlowError):
            raise
        except ImportError:
            raise FlowError("Falta Selenium. Ejecuta ABRIR_BOT.bat para instalar el lector.") from None
        except automation.RateLimited:
            raise FlowError("Microsoft limitó las solicitudes. Espera antes de volver a intentar; no se inició IMSS.") from None
        except automation.VerificationRequired:
            raise FlowError("Microsoft solicita verificación adicional. Completa el acceso manualmente o usa Código manual.") from None
        except Exception:
            raise FlowError("No se pudo abrir la bandeja de Outlook. Revisa las credenciales o usa Código manual.") from None

    def code(self, job, report):
        if self.started is None or self.reader is None:
            raise FlowError("El lector no está asociado a una solicitud IMSS.")
        report("codigo", "Buscando únicamente el nuevo correo de verificación del IMSS.")
        deadline, refresh_at = time.monotonic() + self.timeout, time.monotonic() + 30
        while time.monotonic() < deadline:
            if self.cancelled.is_set():
                raise Cancelled("Solicitud detenida.")
            try:
                code = self.reader.scan(self.started)
                if code:
                    return code
                if time.monotonic() >= refresh_at:
                    self.driver.refresh()
                    refresh_at = time.monotonic() + 30
            except Exception:
                raise FlowError("Se perdió la lectura de Outlook. No se reenviará el código ni se cambiará de correo.") from None
            self.cancelled.wait(.5)
        raise FlowError("No llegó un código nuevo verificable en tres minutos. Revisa Outlook e IMSS.")

    def close(self):
        automation.close_driver(self.driver)
        self.driver = self.reader = None
        self.password = ""
