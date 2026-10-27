"""Embedded Outlook controls and worker; owns no second Tk root or bot panel."""

from pathlib import Path
import queue
import re
import threading
from urllib.parse import urlsplit
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from outlook_conectado import OutlookWorker, App as OutlookApp
from core import parse_accounts, merge_accounts
from history import HistoryStore, FIELDS, GROUPS, group_results
from .bridge import Bridge
from .locking import ProcessLock

AUTO = "Automático · siguiente correo disponible"


class OutlookSection(OutlookWorker):
    _record_result = OutlookApp._record_result

    def __init__(self, parent, connection):
        self.connection = connection
        self.root = connection.app.root
        self.bridge = Bridge()
        self.process_lock = ProcessLock(self.bridge.root / "outlook.lock")
        if not self.process_lock.acquire():
            messagebox.showerror(
                "Panel único",
                "Ya hay un bot abierto. Usa esa ventana o ciérrala antes de abrir otra copia.",
                parent=self.root,
            )
            self.root.destroy()
            raise SystemExit(0)
        self.bridge.interrupt_previous()
        self.accounts = []
        self.account_lookup = {}
        self.states = {}
        self.accepting = False
        self.catalog_dirty = True
        self.shutdown = threading.Event()
        self.job_cancel = threading.Event()
        self._running = False
        self.mailbox_opening = threading.Event()
        self.commands = queue.SimpleQueue()
        self.warm_driver = None
        self.warm_email = None
        self._events = queue.SimpleQueue()
        self.history = HistoryStore()
        self.history_status = tk.StringVar(value="")
        self.email = tk.StringVar(value=AUTO)
        self.password = tk.StringVar()
        self.count = tk.StringVar(value="Sin cuentas cargadas")
        self.status = tk.StringVar(
            value="Carga las cuentas una vez. Elige el correo aquí; ambos bots usarán el mismo."
        )
        self.active_email = tk.StringVar(value="Correo activo en ambos bots: pendiente")
        frame = tk.Frame(parent, bg="#222229")
        frame.pack(fill="x")
        row = tk.Frame(frame, bg="#222229")
        row.pack(fill="x")
        tk.Label(row, text="Correo", fg="white", bg="#222229").grid(
            row=0, column=0, sticky="w"
        )
        self.choice = ttk.Combobox(
            row, textvariable=self.email, values=(AUTO,), width=38
        )
        self.choice.grid(row=0, column=1, padx=6, sticky="ew")
        self.choice.bind("<<ComboboxSelected>>", lambda event: self.choose())
        tk.Label(row, text="Contraseña", fg="white", bg="#222229").grid(row=0, column=2)
        self.password_entry = ttk.Entry(
            row, textvariable=self.password, show="*", width=20
        )
        self.password_entry.grid(row=0, column=3, padx=6)
        row.columnconfigure(1, weight=1)
        self.start_button = ttk.Button(
            frame, text="Usar correo", command=self.add_or_use
        )
        actions = tk.Frame(frame, bg="#222229")
        actions.pack(fill="x", pady=(6, 0))
        self.open_button = ttk.Button(
            actions, text="ABRIR BANDEJA", command=self.open_mailbox
        )
        self.open_button.pack(side="left", padx=(0, 6))
        self.close_button = ttk.Button(
            actions, text="Cerrar Outlook", command=self.stop_mailbox
        )
        self.close_button.pack(side="right")
        self.import_button = ttk.Button(
            actions, text="Cargar cuentas TXT", command=self.load
        )
        self.import_button.pack(side="left")
        self.auto_button = ttk.Button(
            actions, text="Siguiente disponible", command=self.use_auto
        )
        self.auto_button.pack(side="left", padx=6)
        tk.Label(actions, textvariable=self.count, fg="#c9c9c9", bg="#222229").pack(
            side="left", padx=6
        )
        self.skip_button = connection.skip_button
        self.stop_button = connection.stop_button
        self.manage_buttons = [
            self.open_button,
            self.import_button,
            self.auto_button,
            self.choice,
            self.password_entry,
        ]
        tk.Label(
            frame,
            textvariable=self.status,
            bg="#222229",
            fg="#d9b75b",
            anchor="w",
            wraplength=850,
        ).pack(fill="x", pady=(6, 0))
        tk.Label(
            frame,
            textvariable=self.active_email,
            bg="#222229",
            fg="#c9c9c9",
            anchor="w",
            wraplength=850,
        ).pack(fill="x", pady=(2, 0))
        self.root.after(100, self.drain)
        self.root.after(200, self.heartbeat)
        self.thread = threading.Thread(target=self.listen, daemon=True)
        self.thread.start()

    def locked(self):
        return (
            self._running
            or self.mailbox_opening.is_set()
            or self.connection.active
            or self.connection.batch.runner.running
        )

    def open_mailbox(self):
        """Open Outlook independently; the same browser is handed to the IMSS job."""
        if self.locked() or not self.activate_for_request():
            return
        preferred = self.connection.preferred_email.get().casefold()
        excluded = self.bridge.excluded_emails()
        account = (
            next((a for a in self.accounts if a.address.casefold() == preferred), None)
            if preferred
            else next(
                (a for a in self.accounts if a.address.casefold() not in excluded), None
            )
        )
        if account is None:
            self.status.set("No quedan cuentas disponibles. Elige otra cuenta.")
            return
        self.job_cancel.clear()
        self.mailbox_opening.set()
        self.status.set("Abriendo Outlook; IMSS permanece independiente.")
        self.commands.put(("open", account))

    def stop_mailbox(self):
        if self.connection.active:
            self.connection.stop()
        self.job_cancel.set()
        self.commands.put(("close", None))
        self.status.set("Cerrando Outlook; las instancias IMSS permanecen encendidas.")

    def discard_mailbox(self):
        from automation import close_driver

        driver, self.warm_driver = self.warm_driver, None
        self.warm_email = None
        close_driver(driver)

    def open_account(self, account, browsers, cancelled, report):
        if (
            self.warm_driver is not None
            and self.warm_email == account.address.casefold()
        ):
            driver, self.warm_driver = self.warm_driver, None
            self.warm_email = None
            try:
                url = urlsplit(driver.current_url)
                if url.hostname == "outlook.live.com" and url.path.startswith("/mail"):
                    report("Usando la bandeja que ya estaba abierta.")
                    return driver
            except Exception:
                pass
            from automation import close_driver

            close_driver(driver)
        self.discard_mailbox()
        return super().open_account(account, browsers, cancelled, report)

    def prepare_mailbox(self, account):
        from automation import (
            available_browsers,
            RateLimited,
            VerificationRequired,
            SkipRequested,
        )

        cancelled = lambda: self.shutdown.is_set() or self.job_cancel.is_set()

        def report(text):
            self._post(
                lambda value=text: self.status.set(f"{account.address} | {value}")
            )

        try:
            if cancelled():
                raise SkipRequested()
            browsers = available_browsers()
            if not browsers:
                raise RuntimeError("No hay navegador compatible.")
            driver = self.open_account(account, browsers, cancelled, report)
            self.warm_driver, self.warm_email = driver, account.address.casefold()
            if cancelled():
                raise SkipRequested()
            self.bridge.email_ready(account.address)
            self._record_result(
                account.address,
                "Entró a la bandeja",
                "Bandeja abierta desde el panel Outlook",
            )
            self._post(lambda: self._account_status(account.address, "Bandeja abierta"))
            report("Bandeja lista. Ya puedes iniciar el trámite IMSS.")
        except RateLimited:
            self.accepting = False
            self._record_result(
                account.address, "Interrumpido", "Microsoft limita solicitudes"
            )
            report("Microsoft limita solicitudes; Outlook se ha detenido.")
            self.discard_mailbox()
        except VerificationRequired:
            self.bridge.email_failed(account.address, "verification", 3600)
            self._record_result(
                account.address,
                "No logró entrar",
                "Verificación adicional de Microsoft",
            )
            report("Se requiere verificación adicional. Elige otro correo.")
            self.discard_mailbox()
        except SkipRequested:
            self._record_result(
                account.address, "Omitido", "Apertura detenida por el usuario"
            )
            report("Apertura detenida.")
            self.discard_mailbox()
        except Exception:
            self.bridge.email_failed(account.address, "login", 600)
            self._record_result(
                account.address, "No logró entrar", "No se completó el acceso al correo"
            )
            report("No se pudo abrir la bandeja. Revisa la cuenta.")
            self.discard_mailbox()
        finally:
            self.mailbox_opening.clear()

    def listen(self):
        # Only this worker owns Selenium drivers, including manual mailbox actions.
        try:
            while not self.shutdown.wait(0.2):
                try:
                    command, account = self.commands.get_nowait()
                except queue.Empty:
                    command = None
                if command == "close":
                    self.discard_mailbox()
                    self._post(lambda: self.active_email.set("Outlook cerrado."))
                elif command == "open":
                    self.prepare_mailbox(account)
                elif command == "connected":
                    server, request = account
                    opener = server.open_account
                    finished = server.on_job_finished
                    # A pre-opened driver stays on the thread which created it.
                    server.open_account = self.open_account
                    server.on_job_finished = lambda key: None
                    try:
                        server.process(request)
                    finally:
                        server.open_account = opener
                        server.on_job_finished = finished
                        finished(request["id"])
                if self.accepting:
                    try:
                        for request in self.bridge.pending():
                            if self.shutdown.is_set() or not self.accepting:
                                break
                            self.process(request)
                    except Exception:
                        self.accepting = False
                        self._post(
                            lambda: self.status.set(
                                "Conexión local interrumpida. Revisa el registro."
                            )
                        )
        finally:
            self.discard_mailbox()

    def _post(self, callback):
        self._events.put(callback)

    def drain(self):
        try:
            while True:
                self._events.get_nowait()()
        except queue.Empty:
            pass
        if not self.shutdown.is_set():
            self.root.after(100, self.drain)

    def publish(self):
        self.account_lookup = {a.address.casefold(): a for a in self.accounts}
        self.bridge.publish([a.address for a in self.accounts], self.accepting)
        self.catalog_dirty = False
        self.count.set(f"{len(self.accounts)} cuentas cargadas")
        self.choice.configure(
            values=(AUTO,) + tuple(a.address for a in self.accounts[:200])
        )

    def heartbeat(self):
        try:
            if self.catalog_dirty:
                self.publish()
            else:
                self.bridge.pulse(self.accepting)
        except (OSError, ValueError):
            self.accepting = False
            self.status.set(
                "No se pudo publicar la conexión local; revisa el almacenamiento."
            )
        if not self.shutdown.is_set():
            self.root.after(1000, self.heartbeat)

    def activate_for_request(self):
        if self.email.get() == AUTO and not self.accounts:
            messagebox.showerror(
                "Correo",
                "Escribe el correo y contraseña, o carga tus cuentas TXT.",
                parent=self.root,
            )
            return False
        return bool(self.add_or_use())

    def add_or_use(self):
        if self.locked():
            self.status.set("Espera o pausa el lote antes de cambiar el correo.")
            return
        address = self.email.get().strip()
        if address == AUTO:
            return self.use_auto()
        existing = self.account_lookup.get(address.casefold())
        try:
            if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", address):
                raise ValueError(
                    "Escribe un correo completo o selecciona el modo automático."
                )
            if not existing or self.password.get():
                if not self.password.get():
                    raise ValueError(
                        "Importa la cuenta o escribe su contraseña inicial para que Outlook pueda entrar."
                    )
                incoming = parse_accounts(address + ":" + self.password.get())
                merged, _ = merge_accounts(self.accounts, incoming)
                if existing:
                    merged = [
                        incoming[0] if a.address.casefold() == address.casefold() else a
                        for a in merged
                    ]
                if len(merged) > 50000:
                    raise ValueError("El panel admite hasta 50 000 cuentas.")
                self.accounts = merged
                self.bridge.email_ready(address)
            self.password.set("")
            self.connection.preferred_email.set(address.casefold())
            self.accepting = True
            self.publish()
            self.status.set("Correo compartido listo.")
            return True
        except ValueError as exc:
            messagebox.showerror("Correo compartido", str(exc), parent=self.root)
        except OSError:
            self.status.set(
                "No se pudo activar la conexión local. Revisa la carpeta de datos."
            )

    def choose(self):
        if self.locked():
            return
        if self.email.get() == AUTO:
            self.use_auto()
        elif self.email.get().casefold() in self.account_lookup:
            self.add_or_use()

    def use_auto(self):
        if self.locked():
            self.status.set(
                "Pausa o termina la solicitud antes de cambiar la selección."
            )
            return
        self.email.set(AUTO)
        self.password.set("")
        self.connection.preferred_email.set("")
        self.accepting = bool(self.accounts)
        try:
            self.bridge.pulse(self.accepting)
        except OSError:
            self.status.set(
                "No se pudo activar el modo automático; revisa el almacenamiento."
            )
            return
        self.status.set("Siguiente correo disponible.")
        return self.accepting

    def load(self):
        if self.locked():
            self.status.set("Pausa el lote antes de importar cuentas.")
            return
        path = filedialog.askopenfilename(
            parent=self.root, filetypes=[("Cuentas correo:contraseña", "*.txt")]
        )
        if not path:
            return
        try:
            source = Path(path)
            if source.stat().st_size > 16 * 1024 * 1024:
                raise ValueError("El TXT supera 16 MB.")
            incoming = parse_accounts(source.read_text(encoding="utf-8-sig"))
            merged, added = merge_accounts(self.accounts, incoming)
            if len(merged) > 50000:
                raise ValueError("Importa hasta 50 000 cuentas.")
            self.accounts = merged
            self.accepting = True
            self.publish()
            self.status.set(
                f"{added} cuentas añadidas. El correo se selecciona solo una vez, arriba."
            )
        except ValueError as exc:
            messagebox.showerror("Importar cuentas", str(exc), parent=self.root)
        except (OSError, UnicodeError):
            messagebox.showerror(
                "Importar cuentas",
                "No se pudo leer el TXT UTF-8 o activar la conexión local.",
                parent=self.root,
            )

    def _account_status(self, address, state):
        self.states[address.casefold()] = state
        self.active_email.set(f"Correo activo en ambos bots: {address} · {state}")
        label = self.connection.app.__dict__.get("info_correos")
        if label:
            label.configure(text=f"Correo compartido con IMSS: {address}")

    def close(self):
        self.accepting = False
        self.shutdown.set()
        self.job_cancel.set()
        try:
            self.bridge.pulse(False)
        except OSError:
            pass

    def show_history(self):
        if self.locked():
            self.status.set(
                "Pausa o termina la solicitud antes de abrir el historial completo de Outlook."
            )
            return
        w = tk.Toplevel(self.root)
        w.title("Resultados de correos Outlook")
        w.geometry("1000x550")
        notebook = ttk.Notebook(w)
        notebook.pack(fill="both", expand=True, padx=12, pady=12)
        try:
            grouped = group_results(self.history.read())
        except Exception:
            messagebox.showerror(
                "Historial", "No se pudo leer el historial Outlook.", parent=w
            )
            w.destroy()
            return
        for category in GROUPS:
            frame = ttk.Frame(notebook)
            notebook.add(frame, text=f"{category} ({len(grouped[category])})")
            table = ttk.Treeview(frame, columns=FIELDS, show="headings")
            for field in FIELDS:
                table.heading(field, text=field.capitalize())
                table.column(field, width=200)
            y = ttk.Scrollbar(frame, orient="vertical", command=table.yview)
            y.pack(side="right", fill="y")
            table.configure(yscrollcommand=y.set)
            table.pack(fill="both", expand=True)
            for row in grouped[category]:
                table.insert("", "end", values=[row.get(field, "") for field in FIELDS])

        def export():
            path = filedialog.asksaveasfilename(
                parent=w, defaultextension=".csv", initialfile="resultados_outlook.csv"
            )
            if path:
                try:
                    self.history.export(path)
                except OSError:
                    messagebox.showerror(
                        "Historial", "No se pudo exportar el historial.", parent=w
                    )

        ttk.Button(w, text="Exportar historial Outlook CSV", command=export).pack(
            pady=(0, 12)
        )

        def export_list():
            category = GROUPS[notebook.index(notebook.select())]
            path = filedialog.asksaveasfilename(
                parent=w, defaultextension=".txt", initialfile="correos_outlook.txt"
            )
            if path:
                try:
                    Path(path).write_text(
                        "".join(row["correo"] + "\n" for row in grouped[category]),
                        encoding="utf-8",
                    )
                except OSError:
                    messagebox.showerror(
                        "Historial", "No se pudo guardar la lista.", parent=w
                    )

        ttk.Button(w, text="Exportar lista seleccionada TXT", command=export_list).pack(
            pady=(0, 12)
        )
