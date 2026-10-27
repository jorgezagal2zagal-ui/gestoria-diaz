"""Connection launcher. The uploaded Outlook source files are imported unchanged."""

from pathlib import Path
import sys
import threading
import time
from urllib.parse import urlsplit
from tkinter import messagebox

sys.path.insert(0, str(Path(__file__).resolve().parent / "outlook_bot"))
from app import App
from automation import (
    try_account,
    close_driver,
    RateLimited,
    SkipRequested,
    SpecialPages,
    VerificationRequired,
)
from conexion.bridge import Bridge, read_json
from conexion.reader import OutlookReader
from conexion.locking import ProcessLock
from core import parse_accounts, merge_accounts


class OutlookWorker:
    def listen(self):
        while not self.shutdown.wait(0.5):
            if not self.accepting:
                continue
            try:
                for request in self.bridge.pending():
                    if self.shutdown.is_set() or not self.accepting:
                        break
                    self.process(request)
            except Exception:
                self.accepting = False
                self._post(
                    lambda: self.status.set(
                        "Se detuvo la conexión local. Revisa la carpeta de datos y vuelve a activarla."
                    )
                )

    def process(self, request):
        key, email = request["id"], request["email"]
        account = self.__dict__.get("account_lookup", {}).get(email.casefold()) or next(
            (
                a
                for a in list(self.accounts)
                if a.address.casefold() == email.casefold()
            ),
            None,
        )
        if account is None:
            self.bridge.reply(
                key, "error", reason="El correo no está importado en Outlook."
            )
            return
        self.job_cancel.clear()
        self.code_delivered = False

        def running_controls():
            self._running = True
            for button in self.manage_buttons:
                button.configure(state="disabled")
            self.start_button.configure(state="disabled")
            self.skip_button.configure(state="normal")

        self._post(running_controls)
        cancelled = lambda: (
            self.shutdown.is_set()
            or self.job_cancel.is_set()
            or self.bridge.cancelled(key)
            or time.time() >= request["expires"]
        )
        driver = None
        inbox_opened = False

        def report(text):
            self._post(lambda: self.status.set(f"{email} | {text}"))
            self.bridge.reader_status(key, "outlook", text)

        self._post(lambda: self.skip_button.configure(state="normal"))
        self._post(lambda: self._account_status(email, "Intentando"))
        self.bridge.reply(key, "opening")
        try:
            from automation import available_browsers

            browsers = available_browsers()
            if not browsers:
                raise RuntimeError("No hay navegador compatible instalado.")
            driver = try_account(account, browsers, cancelled, report)
            inbox_opened = True
            self.bridge.email_ready(email)
            driver.set_page_load_timeout(25)
            driver.set_script_timeout(10)
            self._record_result(email, "Entró a la bandeja", "Modo conectado al IMSS")
            self._post(lambda: self._account_status(email, "Bandeja abierta"))
            reader = OutlookReader(
                driver,
                request["sender"],
                request["subject"],
                cancelled,
                report,
                expected_curp=request.get("curp", ""),
            )
            special = SpecialPages(driver, cancelled, report)
            baseline_deadline = time.monotonic() + 10
            while True:
                if cancelled():
                    raise SkipRequested()
                try:
                    reader.baseline()
                    break
                except RuntimeError:
                    if time.monotonic() >= baseline_deadline:
                        raise
                    report(
                        "Esperando que Outlook termine de cargar su lista de mensajes."
                    )
                    self.job_cancel.wait(1)
            self.bridge.reply(key, "ready")
            report("Bandeja lista; esperando que IMSS solicite el código.")
            notified = False
            last_refresh = time.monotonic()
            refreshes = 0
            while not cancelled():
                armed = read_json(self.bridge.job(key) / "started.json")
                if armed:
                    if not notified:
                        report("Leyendo el mensaje nuevo de validación del IMSS.")
                        notified = True
                    waiting = read_json(self.bridge.job(key) / "waiting.json")
                    waiting_since = waiting["at"] if waiting else armed["at"]
                    deadline = request.get("code_timeout", 180) if waiting else 240
                    if time.time() - waiting_since > deadline:
                        self.bridge.reply(
                            key,
                            "error",
                            reason="No llegó un código nuevo verificable dentro del tiempo configurado. "
                            + reader.last_diagnostic,
                        )
                        break
                    if special.handle() is not None:
                        continue
                    code = reader.scan(armed["at"])
                    if code:
                        self.code_delivered = True
                        self.bridge.reply(key, "code", code=code)
                        self._post(lambda: self.skip_button.configure(state="disabled"))
                        report("Código entregado a la instancia solicitante.")
                        while not cancelled():
                            self.job_cancel.wait(0.5)
                        break
                    url = urlsplit(driver.current_url)
                    if (
                        refreshes < 3
                        and time.monotonic() - last_refresh >= 25
                        and url.hostname == "outlook.live.com"
                        and url.path.startswith("/mail")
                    ):
                        report(
                            "Actualizando la bandeja; mantengo la referencia de mensajes anteriores."
                        )
                        driver.refresh()
                        refreshes += 1
                        last_refresh = time.monotonic()
                self.job_cancel.wait(2)
        except RateLimited:
            self.accepting = False
            self._record_result(
                email, "Interrumpido", "Microsoft limita solicitudes: Too Many Requests"
            )
            self._post(
                lambda: self._account_status(email, "Microsoft limita solicitudes")
            )
            self.bridge.reply(
                key,
                "limited",
                reason="Microsoft limita solicitudes; conexión detenida.",
            )
        except VerificationRequired:
            self.bridge.email_failed(email, "verification", 3600)
            self._record_result(
                email, "No logró entrar", "Verificación adicional: Almost there"
            )
            self._post(
                lambda: self._account_status(email, "Omitido: verificación adicional")
            )
            self.bridge.reply(
                key,
                "error",
                reason="Cuenta omitida por verificación adicional de Microsoft.",
            )
        except SkipRequested:
            if self.accepting and not inbox_opened:
                self.bridge.email_failed(email, "omitted", 600)
            self._record_result(
                email,
                "Omitido" if self.accepting else "Interrumpido",
                "Intento omitido o detenido",
            )
            self.bridge.reply(
                key,
                "error" if self.accepting else "stopped",
                reason="Intento omitido o detenido.",
            )
        except Exception:
            if not inbox_opened:
                self.bridge.email_failed(email, "login", 600)
            self._record_result(
                email,
                "Entró a la bandeja" if inbox_opened else "No logró entrar",
                "Bandeja abierta; la lectura del código no se completó"
                if inbox_opened
                else "No se completó el acceso al correo",
            )
            self._post(
                lambda: self._account_status(
                    email, "Omitido: error de acceso o lectura"
                )
            )
            self.bridge.reply(
                key, "error", reason="No se pudo abrir o leer esta cuenta de Outlook."
            )
        finally:
            close_driver(driver)
            self.code_delivered = False
            if self.job_cancel.is_set() and not self.bridge.cancelled(key):
                response = self.bridge.response(key) or {}
                if response.get("status") in ("opening", "ready"):
                    self.bridge.reply(
                        key,
                        "error" if self.accepting else "stopped",
                        reason="Intento omitido o detenido.",
                    )
            if self.bridge.cancelled(key):
                import shutil

                shutil.rmtree(self.bridge.job(key), ignore_errors=True)

            def restore_controls():
                self._running = False
                for button in self.manage_buttons:
                    button.configure(state="normal")
                self.start_button.configure(state="normal")
                self.skip_button.configure(state="disabled")
                self.stop_button.configure(
                    state="normal" if self.accepting else "disabled"
                )

            self._post(restore_controls)


class ConnectedOutlook(App, OutlookWorker):
    def refresh(self):
        super().refresh()
        self.account_rows = {
            account.address.casefold(): str(i)
            for i, account in enumerate(self.accounts)
        }
        self.account_lookup = {
            account.address.casefold(): account for account in self.accounts
        }
        self.catalog_dirty = True

    def _account_status(self, address, state):
        self.states[address.casefold()] = state
        row = self.__dict__.get("account_rows", {}).get(address.casefold())
        if row is not None and self.table.exists(row):
            values = list(self.table.item(row, "values"))
            values[2] = state
            self.table.item(row, values=values)

    def add_text(self, content):
        incoming = parse_accounts(content)
        merged, added = merge_accounts(self.accounts, incoming)
        if len(merged) > 50000:
            raise ValueError(
                "Importa como máximo 50 000 cuentas en el panel conectado."
            )
        self.accounts = merged
        self.refresh()
        self.status.set(
            f"Leídas: {len(incoming)} | Añadidas: {added} | Duplicadas omitidas: {len(incoming) - added}"
        )

    def __init__(self):
        super().__init__()
        self.bridge = Bridge()
        self.process_lock = ProcessLock(self.bridge.root / "outlook.lock")
        try:
            acquired = self.process_lock.acquire()
        except (OSError, ValueError):
            acquired = False
        if not acquired:
            messagebox.showerror(
                "Outlook V3",
                "Ya hay otro Outlook V3 conectado, o no se puede acceder a la carpeta de conexión. Cierra esta copia.",
                parent=self,
            )
            self.destroy()
            raise SystemExit(0)
        self.bridge.interrupt_previous()
        self.title("Gestoría Díaz | Outlook conectado V3")
        self.accepting = False
        self.shutdown = threading.Event()
        self.job_cancel = threading.Event()
        self.start_button.configure(text="ACTIVAR CONEXIÓN IMSS")
        self.status.set(
            "Importa tus cuentas y activa la conexión. El bot del IMSS elegirá el correo."
        )
        self.after(500, self.heartbeat)
        threading.Thread(target=self.listen, daemon=True).start()

    def open_private_login(self):
        if not self.accounts:
            self.status.set("Primero importa tus cuentas en este panel.")
            return
        self.accepting = True
        self.stop_button.configure(state="normal")
        self.status.set(
            "Conexión activa. Introduce la CURP e inicia desde el panel del IMSS."
        )

    def heartbeat(self):
        try:
            if self.__dict__.get("catalog_dirty", True):
                self.bridge.publish([a.address for a in self.accounts], self.accepting)
                self.catalog_dirty = False
            else:
                self.bridge.pulse(self.accepting)
        except OSError:
            self.status.set(
                "No pude publicar la conexión local. Revisa la carpeta de datos."
            )
        if not self.shutdown.is_set():
            self.after(1000, self.heartbeat)

    def skip_account(self):
        if self.__dict__.get("code_delivered"):
            self.status.set("El código ya fue entregado; espera el resultado en IMSS.")
            return
        self.job_cancel.set()

    def stop_accounts(self):
        self.accepting = False
        self.job_cancel.set()
        self.status.set("Conexión detenida.")

    def close_panel(self):
        self.accepting = False
        self.shutdown.set()
        self.job_cancel.set()
        try:
            self.bridge.publish([], False)
        except OSError:
            pass
        super().close_panel()


if __name__ == "__main__":
    from panel_unificado import main

    main()
