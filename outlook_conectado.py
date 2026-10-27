"""Connection launcher. The uploaded Outlook source files are imported unchanged."""
from pathlib import Path
import sys
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parent / 'outlook_bot'))
from app import App
from automation import try_account, close_driver, RateLimited, SkipRequested, SpecialPages, VerificationRequired
from conexion.bridge import Bridge, read_json
from conexion.reader import OutlookReader


class ConnectedOutlook(App):
    def __init__(self):
        super().__init__()
        self.bridge = Bridge()
        self.accepting = False
        self.shutdown = threading.Event()
        self.job_cancel = threading.Event()
        self.start_button.configure(text='ACTIVAR CONEXIÓN IMSS')
        self.status.set('Importa tus cuentas y activa la conexión. El bot del IMSS elegirá el correo.')
        self.after(500, self.heartbeat)
        threading.Thread(target=self.listen, daemon=True).start()

    def open_private_login(self):
        if not self.accounts:
            self.status.set('Primero importa tus cuentas en este panel.')
            return
        self.accepting = True
        self.stop_button.configure(state='normal')
        self.status.set('Conexión activa. Introduce la CURP e inicia desde el panel del IMSS.')

    def heartbeat(self):
        try:
            self.bridge.publish([a.address for a in self.accounts], self.accepting)
        except OSError:
            self.status.set('No pude publicar la conexión local. Revisa la carpeta de datos.')
        if not self.shutdown.is_set():
            self.after(1000, self.heartbeat)

    def skip_account(self):
        self.job_cancel.set()

    def stop_accounts(self):
        self.accepting = False
        self.job_cancel.set()
        self.status.set('Conexión detenida.')

    def close_panel(self):
        self.accepting = False
        self.shutdown.set()
        self.job_cancel.set()
        try:
            self.bridge.publish([], False)
        except OSError:
            pass
        super().close_panel()

    def listen(self):
        while not self.shutdown.wait(.5):
            if not self.accepting:
                continue
            try:
                for request in self.bridge.pending():
                    if self.shutdown.is_set() or not self.accepting:
                        break
                    self.process(request)
            except Exception:
                self.accepting = False
                self._post(lambda: self.status.set('Se detuvo la conexión local. Revisa la carpeta de datos y vuelve a activarla.'))

    def process(self, request):
        key, email = request['id'], request['email']
        account = next((a for a in list(self.accounts) if a.address.casefold() == email.casefold()), None)
        if account is None:
            self.bridge.reply(key, 'error', reason='El correo no está importado en Outlook.')
            return
        self.job_cancel.clear()
        def running_controls():
            self._running = True
            for button in self.manage_buttons:
                button.configure(state='disabled')
            self.start_button.configure(state='disabled')
            self.skip_button.configure(state='normal')
        self._post(running_controls)
        cancelled = lambda: (self.shutdown.is_set() or self.job_cancel.is_set()
                             or self.bridge.cancelled(key) or time.time() >= request['expires'])
        driver = None
        def report(text):
            self._post(lambda: self.status.set(f'{email} | {text}'))
        self._post(lambda: self.skip_button.configure(state='normal'))
        self._post(lambda: self._account_status(email, 'Intentando'))
        self.bridge.reply(key, 'opening')
        try:
            from automation import available_browsers
            browsers = available_browsers()
            if not browsers:
                raise RuntimeError('No hay navegador compatible instalado.')
            driver = try_account(account, browsers, cancelled, report)
            self._record_result(email, 'Entró a la bandeja', 'Modo conectado al IMSS')
            self._post(lambda: self._account_status(email, 'Bandeja abierta'))
            reader = OutlookReader(driver, request['sender'], request['subject'])
            special = SpecialPages(driver, cancelled, report)
            reader.baseline()
            self.bridge.reply(key, 'ready')
            report('Bandeja lista; esperando que IMSS solicite el código.')
            notified = False
            while not cancelled():
                armed = read_json(self.bridge.job(key) / 'started.json')
                if armed:
                    if not notified:
                        report('Buscando un mensaje nuevo del IMSS con remitente y asunto configurados.')
                        notified = True
                    if time.time() - armed['at'] > 180:
                        self.bridge.reply(key, 'error', reason='No llegó un código nuevo verificable en tres minutos.')
                        break
                    if special.handle() is not None:
                        continue
                    code = reader.scan(armed['at'])
                    if code:
                        self.bridge.reply(key, 'code', code=code)
                        self._post(lambda: self.skip_button.configure(state='disabled'))
                        report('Código entregado a la instancia solicitante.')
                        while not cancelled():
                            self.job_cancel.wait(.5)
                        break
                self.job_cancel.wait(2)
        except RateLimited:
            self.accepting = False
            self._record_result(email, 'Interrumpido', 'Microsoft limita solicitudes: Too Many Requests')
            self._post(lambda: self._account_status(email, 'Microsoft limita solicitudes'))
            self.bridge.reply(key, 'limited', reason='Microsoft limita solicitudes; conexión detenida.')
        except VerificationRequired:
            self._record_result(email, 'No logró entrar', 'Verificación adicional: Almost there')
            self._post(lambda: self._account_status(email, 'Omitido: verificación adicional'))
            self.bridge.reply(key, 'error', reason='Cuenta omitida por verificación adicional de Microsoft.')
        except SkipRequested:
            self._record_result(email, 'Omitido' if self.accepting else 'Interrumpido', 'Intento omitido o detenido')
            self.bridge.reply(key, 'error' if self.accepting else 'stopped', reason='Intento omitido o detenido.')
        except Exception:
            self._record_result(email, 'No logró entrar', 'No se completó el acceso o la lectura del correo')
            self._post(lambda: self._account_status(email, 'Omitido: error de acceso o lectura'))
            self.bridge.reply(key, 'error', reason='No se pudo abrir o leer esta cuenta de Outlook.')
        finally:
            close_driver(driver)
            if self.job_cancel.is_set() and not self.bridge.cancelled(key):
                response = self.bridge.response(key) or {}
                if response.get('status') in ('opening', 'ready'):
                    self.bridge.reply(key, 'error' if self.accepting else 'stopped', reason='Intento omitido o detenido.')
            if self.bridge.cancelled(key):
                import shutil
                shutil.rmtree(self.bridge.job(key), ignore_errors=True)
            def restore_controls():
                self._running = False
                for button in self.manage_buttons:
                    button.configure(state='normal')
                self.start_button.configure(state='normal')
                self.skip_button.configure(state='disabled')
                self.stop_button.configure(state='normal' if self.accepting else 'disabled')
            self._post(restore_controls)


if __name__ == '__main__':
    ConnectedOutlook().mainloop()
