"""One active request with a bounded, journaled handoff to Outlook."""

import queue
import re
import sqlite3
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

from .bridge import Bridge, read_json
from .history import RequestHistory, FIELDS
from .locking import ProcessLock
from .reader import normalized
from .result import RequestResult

STEPS = {
    "listo": 0,
    "emuladores": 5,
    "outlook": 15,
    "consulta": 40,
    "codigo": 60,
    "validando": 80,
    "tramite": 90,
    "terminado": 100,
}


class ImssConnection:
    def __init__(self, app):
        self.app = app
        self.bridge = Bridge()
        self.active = False
        self.cancel = threading.Event()
        self.skip = threading.Event()
        self.job = None
        self.rejected = False
        self.reset_ready = False
        self.stage = "listo"
        self.deadline = None
        self.ui = queue.SimpleQueue()
        self.auto = tk.BooleanVar(value=True)
        self.lock = ProcessLock(self.bridge.root / "imss.lock")
        try:
            self.available = self.lock.acquire()
        except OSError:
            self.available = False
        if not self.available:
            messagebox.showerror(
                "IMSS V4",
                "Ya hay otro panel IMSS V4 abierto, o no se puede acceder a la carpeta de conexión. Cierra esta copia.",
                parent=self.app.root,
            )
            self.app.root.destroy()
            raise SystemExit(0)
        self.bridge.interrupt_previous(client_restarted=True)
        self.history = None
        self.history_error = False
        if self.available:
            try:
                self.history = RequestHistory(self.bridge.root)
                self.history.recover_interrupted()
            except (OSError, sqlite3.Error):
                self.history_error = True
        saved = read_json(self.bridge.root / "preferencias.json") or {}
        self.sender = tk.StringVar(value="")
        self.subject = tk.StringVar(value="")
        self.preferred_email = tk.StringVar(value="")
        saved_timeout = saved.get("code_timeout", 180)
        self.code_timeout = tk.IntVar(
            value=saved_timeout
            if type(saved_timeout) is int and 60 <= saved_timeout <= 300
            else 180
        )
        self.status = tk.StringVar(value="Escribe el correo y la CURP. Pulsa INICIAR.")
        self.detail = tk.StringVar(
            value="Outlook abre primero y el código pasa automáticamente a IMSS."
        )
        self.app.root.protocol("WM_DELETE_WINDOW", self.close_window)
        self.app.root.after(200, self.tick)
        from .batch_ui import BatchPanel

        self.batch = BatchPanel(self)

    def close_window(self):
        parallel = self.__dict__.get("parallel")
        if parallel:
            parallel.stop()
        batch = self.__dict__.get("batch")
        if batch:
            batch.runner.stop()
        self.cancel.set()
        if self.job:
            self.bridge.finish(self.job)
        # Do not release a live worker's lock before the process exits.
        outlook = self.app.__dict__.get("outlook")
        if outlook:
            outlook.close()
            deadline = time.monotonic() + 5

            def finish_close():
                if (
                    outlook.thread.is_alive() or (parallel and parallel.alive())
                ) and time.monotonic() < deadline:
                    self.app.root.after(100, finish_close)
                else:
                    self.app.root.destroy()

            finish_close()
        else:
            self.app.root.destroy()

    def controls(self, parent):
        frame = tk.Frame(parent, bg="#222229", padx=12, pady=8)
        frame.pack(fill="x", padx=24, pady=6)
        tk.Label(
            frame,
            textvariable=self.status,
            bg="#222229",
            fg="white",
            font=("Segoe UI", 11, "bold"),
            anchor="w",
            wraplength=850,
        ).pack(fill="x")
        tk.Label(
            frame,
            textvariable=self.detail,
            bg="#222229",
            fg="#c9c9c9",
            anchor="w",
            wraplength=850,
        ).pack(fill="x", pady=(2, 5))
        self.progress = ttk.Progressbar(frame, maximum=100)
        self.progress.pack(fill="x", pady=4)
        actions = tk.Frame(frame, bg="#222229")
        actions.pack(fill="x")
        self.skip_button = ttk.Button(
            actions, text="Omitir correo", command=self.skip_current, state="disabled"
        )
        self.skip_button.pack(side="left")
        self.stop_button = ttk.Button(actions, text="Detener", command=self.stop)
        self.stop_button.pack(side="right")

    def tick(self):
        if self.app.__dict__.get("outlook") and "entrada_codigo" in self.app.__dict__:
            automatic = self.auto.get()
            self.app.entrada_codigo.configure(
                state="readonly" if automatic else "normal"
            )
            self.app.btn_codigo.configure(
                text="Código automático" if automatic else "Enviar código",
                state="disabled"
                if automatic or self.active or not self.app.pendiente
                else "normal",
            )
        try:
            while True:
                text, detail, stage, deadline = self.ui.get_nowait()
                self.status.set(text)
                self.detail.set(detail)
                self.progress.configure(value=STEPS.get(stage, 0))
                self.skip_button.configure(
                    state="normal"
                    if self.active and stage in ("outlook", "codigo")
                    else "disabled"
                )
        except queue.Empty:
            pass
        if self.deadline and self.active:
            seconds = max(0, int(self.deadline - time.monotonic()))
            self.detail.set(
                f"{self.attempt_detail} · Tiempo de espera restante: {seconds} s"
            )
        self.app.root.after(200, self.tick)

    def state(self, stage, text, detail="", timeout=None):
        self.stage = stage
        self.deadline = time.monotonic() + timeout if timeout else None
        self.attempt_detail = detail
        if "ui" in self.__dict__:
            self.ui.put((text, detail, stage, self.deadline))

    def settings(self):
        self.app.emit(
            "El lector reconoce automáticamente el correo del IMSS. No requiere configurar remitente ni asunto."
        )

    def preflight(self):
        presence = self.bridge.presence()
        checks = [
            ("Lector IMSS único", self.available),
            ("Historial disponible", self.history is not None),
            ("Outlook V4 conectado", bool(presence)),
            ("Correos importados", bool(presence and presence["emails"])),
            ("Lector automático IMSS", True),
            ("Ruta de LDPlayer válida", bool(self.app.ruta())),
        ]
        text = "\n".join(("✓ " if ok else "✗ ") + label for label, ok in checks)
        messagebox.showinfo(
            "Comprobación de conexión",
            text
            + "\n\nEsto comprueba configuración local; no prueba la llegada de un mensaje real.",
            parent=self.app.root,
        )

    def show_history(self):
        if self.history is None:
            messagebox.showerror(
                "Historial",
                "No se pudo abrir el historial local.",
                parent=self.app.root,
            )
            return
        window = tk.Toplevel(self.app.root)
        window.title("Solicitudes IMSS · historial V4")
        window.geometry("1100x520")
        ttk.Label(
            window,
            text="Últimos 500 intentos. Una fila por correo; el CSV incluye el historial completo.",
        ).pack(padx=12, pady=8)
        frame = ttk.Frame(window)
        frame.pack(fill="both", expand=True, padx=12)
        table = ttk.Treeview(frame, columns=FIELDS, show="headings")
        for field in FIELDS:
            table.heading(field, text=field.capitalize())
            table.column(field, width=150, stretch=False)
        y = ttk.Scrollbar(frame, orient="vertical", command=table.yview)
        y.pack(side="right", fill="y")
        x = ttk.Scrollbar(frame, orient="horizontal", command=table.xview)
        x.pack(side="bottom", fill="x")
        table.configure(yscrollcommand=y.set, xscrollcommand=x.set)
        table.pack(fill="both", expand=True)

        def refresh():
            try:
                rows = self.history.rows()
                table.delete(*table.get_children())
                for row in rows:
                    table.insert("", "end", values=[row[key] for key in FIELDS])
            except Exception:
                messagebox.showerror(
                    "Historial", "No se pudo leer el historial.", parent=window
                )

        def export():
            path = filedialog.asksaveasfilename(
                parent=window,
                defaultextension=".csv",
                initialfile="solicitudes_imss.csv",
                filetypes=[("CSV", "*.csv")],
            )
            if path:
                try:
                    self.history.export(path)
                except Exception:
                    messagebox.showerror(
                        "Historial", "No se pudo exportar el historial.", parent=window
                    )

        actions = ttk.Frame(window)
        actions.pack(pady=10)
        ttk.Button(actions, text="Actualizar", command=refresh).pack(
            side="left", padx=8
        )
        ttk.Button(actions, text="Exportar CSV", command=export).pack(
            side="left", padx=8
        )
        refresh()

    def journal(
        self,
        request,
        curp,
        instance,
        procedure,
        number,
        email,
        stage,
        outcome,
        reason="",
    ):
        history = self.__dict__.get("history")
        if history:
            try:
                history.record(
                    request,
                    curp,
                    instance,
                    procedure,
                    number,
                    email,
                    stage,
                    outcome,
                    reason,
                )
            except Exception:
                self.history_error = True
                self.app.emit(
                    "No se pudo guardar el historial; el resultado requiere revisión manual."
                )

    def start(self, path, curp, instance, procedure):
        if self.__dict__.get("parallel"):
            return self.parallel.submit(path, curp, instance, procedure)
        if self.__dict__.get("batch") and self.batch.runner.running:
            self.app.emit("Pausa el lote antes de iniciar una solicitud individual.")
            return
        if not self.available:
            self.app.emit("Ya hay otro panel IMSS V4 abierto. Cierra esta copia.")
            return
        if self.history is None:
            self.app.emit(
                "No se pudo abrir el historial local. Revisa el permiso de escritura."
            )
            return
        if self.active or self.app.busy or self.app.__dict__.get("desbloqueando"):
            self.app.emit("Espera a que termine la operación actual.")
            return
        outlook = self.app.__dict__.get("outlook")
        if outlook and not outlook.activate_for_request():
            return
        sender, subject = "", ""
        presence = self.bridge.presence()
        if not presence or not presence["emails"]:
            self.app.emit(
                "Abre Outlook V4, importa las cuentas y pulsa ACTIVAR CONEXIÓN IMSS."
            )
            return
        try:
            self.current_timeout = self.code_timeout.get()
        except tk.TclError:
            self.settings()
            return
        if not 60 <= self.current_timeout <= 300:
            self.settings()
            return
        self.active = True
        self.current_max_attempts = 3
        self.attempt_offset = 0
        self.current_request_id = None
        self.current_preferred_email = self.preferred_email.get().strip().casefold()
        self.app.busy = True
        self.cancel.clear()
        self.skip.clear()
        self.app.btn_consulta.configure(state="disabled")
        self.app.btn_codigo.configure(state="disabled")
        self.app.selector_cantidad.configure(state="disabled")
        threading.Thread(
            target=self.run,
            args=(path, curp, instance, procedure, sender, subject),
            daemon=True,
        ).start()

    def stop(self):
        if self.__dict__.get("parallel"):
            return self.parallel.stop()
        batch = self.__dict__.get("batch")
        if batch:
            batch.runner.stop()
        if not self.active:
            return
        self.cancel.set()
        if self.job:
            self.bridge.finish(self.job)
        self.state(
            "listo",
            "Deteniendo; no inicies otro trámite hasta que termine el paso actual.",
        )
        self.app.emit(
            "Solicitud detenida. Una acción ya enviada a IMSS puede seguir procesándose."
        )

    def skip_current(self):
        if self.__dict__.get("parallel"):
            return self.parallel.skip_selected()
        if self.active and self.stage in ("outlook", "codigo"):
            self.skip.set()
            if self.job:
                self.bridge.finish(self.job)
            self.app.emit(
                "Omitiendo este correo; comprobaré la pantalla de IMSS antes de pasar al siguiente."
            )

    def response(self, key, email, instance, statuses, timeout):
        end = time.monotonic() + timeout
        while time.monotonic() < end and not self.cancel.is_set():
            if self.__dict__.get("skip") and self.skip.is_set():
                return {"status": "error", "reason": "Correo omitido por el usuario."}
            response = self.bridge.response(key)
            if (
                response
                and response.get("id") == key
                and response.get("email", "").casefold() == email.casefold()
                and response.get("instance") == instance
                and response.get("status") in statuses
            ):
                return response
            if not self.bridge.presence():
                return {"status": "stopped", "reason": "Se desconectó Outlook."}
            diagnostic = read_json(self.bridge.job(key) / "reader.json")
            if diagnostic and isinstance(diagnostic.get("reason"), str):
                text = diagnostic["reason"][:250]
                label = self.__dict__.get("attempt_label", "")
                self.attempt_detail = f"{label} · {text}"
            self.cancel.wait(0.15)
        return {
            "status": "error",
            "reason": "Tiempo de espera agotado o solicitud detenida.",
        }

    def tramite_started(self):
        self.state(
            "tramite",
            "Código aceptado; solicitando la constancia.",
            "Esperando confirmación del envío por IMSS",
        )

    def return_to_login(self, path, idx, nodes=None):
        # Navigation helpers are imported from the actual bot instance's module.
        import sys

        module = sys.modules[type(self.app).__module__]
        cancelled = False
        accepted = False
        for _ in range(12):
            if self.cancel.is_set():
                return False
            if nodes is None:
                nodes = module.pantalla(path, idx)
            visible = [
                n for n in nodes if n.get("visible", True) and n.get("area", 0) > 0
            ]
            words = module.texto_normalizado(module.todo_texto(visible))
            code_screen = "codigo de validacion" in words or bool(
                module.cajas_codigo_validacion(visible)
            )
            fields = [n for n in visible if n.get("enabled")]
            validation_error = self.is_validation_error(visible)
            if (
                not code_screen
                and not validation_error
                and module.buscar(fields, "txtCURP")
                and module.buscar(fields, "txtCorreo")
            ):
                return True
            target = (
                "aceptar"
                if validation_error and not accepted
                else "cancelar"
                if code_screen and not cancelled
                else None
            )
            if target:
                buttons = [
                    n
                    for n in fields
                    if any(
                        module.texto_normalizado(label) == target
                        for label in (
                            n.get("valor", ""),
                            n.get("descripcion", ""),
                            n.get("texto", ""),
                        )
                    )
                ]
                if buttons:
                    module.tocar(path, idx, min(buttons, key=lambda n: n["area"])["xy"])
                    if target == "aceptar":
                        accepted = True
                    else:
                        cancelled = True
            nodes = None
            self.cancel.wait(0.5)
        return False

    def is_validation_error(self, nodes):
        text = normalized(
            " ".join(
                n.get("texto", "")
                for n in nodes
                if n.get("visible", True) and n.get("area", 0) > 0
            )
        )
        return bool(
            re.search(
                r"error al validar|codigo (?:incorrecto|invalido|vencido|expirado|no es valido)",
                text,
            )
        )

    def code_rejected(self, path, idx, instance, curp, email, procedure, nodes):
        self.rejected = True
        self.app.pendiente = None
        self.reset_ready = self.return_to_login(path, idx, nodes)
        return self.reset_ready

    def run(self, path, curp, instance, procedure, sender, subject):
        attempted = set()
        request = self.__dict__.get("current_request_id") or RequestHistory.request_id()
        reason = "No se completó la solicitud."
        email = ""
        number = 0
        status = "fallida"
        submitted = False
        offset = self.__dict__.get("attempt_offset", 0)
        budget = self.__dict__.get("current_max_attempts", 3)
        try:
            self.app.pendiente = None
            if self.app.__dict__.get("unified_mode") and not self.__dict__.get(
                "preparation"
            ):
                self.state("emuladores", "IMSS: preparando la multiinstancia", instance)
                if not self.app.preparar_solicitud(
                    path, instance, self.cancel.is_set, self.cancel.wait
                ):
                    status = "emulador_no_listo"
                    reason = "No se confirmó la instancia lista y desbloqueada. Revisa IMSS y PREPARAR / ENCENDER."
                    self.journal(
                        request,
                        curp,
                        instance,
                        procedure,
                        0,
                        "",
                        "emuladores",
                        "fallida",
                        reason,
                    )
                    self.state("terminado", "No se pudo preparar el emulador", reason)
                    return
            for number in range(1, budget + 1):
                if self.cancel.is_set():
                    return
                if self.__dict__.get("skip"):
                    self.skip.clear()
                presence = self.bridge.presence()
                if not presence:
                    status = "stopped"
                    reason = "Outlook no está conectado."
                    break
                module = sys.modules[type(self.app).__module__]
                excluded = {
                    v.casefold()
                    for v in module.correos_usados()
                    | self.app.usados_sesion
                    | attempted
                    | self.bridge.excluded_emails()
                }
                pool = presence["emails"]
                preferred = self.__dict__.get("current_preferred_email", "")
                if preferred in pool:
                    start = pool.index(preferred)
                    pool = pool[start:] + pool[:start]
                if not attempted and preferred:
                    email = next(
                        (
                            v
                            for v in pool
                            if v.casefold() == preferred
                            and v.casefold() not in excluded
                        ),
                        None,
                    )
                else:
                    email = next(
                        (v for v in pool if v.casefold() not in excluded), None
                    )
                if self.__dict__.get("claim_email"):
                    email = self.claim_email(
                        pool, excluded, preferred if not attempted else ""
                    )
                if email is None:
                    status = "sin_correos"
                    reason = (
                        "El correo elegido no está disponible. Elige otro o usa el modo automático."
                        if preferred and not attempted
                        else "No quedan correos importados y disponibles en Outlook."
                    )
                    break
                attempted.add(email.casefold())
                detail = f"Intento {number + offset}/3 · {email} · {instance}"
                self.attempt_label = detail
                self.state("outlook", "Abriendo la bandeja de Outlook", detail, 330)
                self.app.emit(
                    f"Intento conectado {number + offset}/3: abriendo la bandeja de {email}"
                )
                timeout = self.__dict__.get("current_timeout", 180)
                self.job = self.bridge.create(
                    email, instance, sender, subject, timeout, curp=curp
                )
                outcome = "fallida"
                attempt_reason = "No se confirmó el resultado de este intento."
                self.journal(
                    request,
                    curp,
                    instance,
                    procedure,
                    number + offset,
                    email,
                    "outlook",
                    "en_curso",
                )
                try:
                    ready = self.response(
                        self.job,
                        email,
                        instance,
                        {"ready", "error", "reader_error", "limited", "stopped"},
                        330,
                    )
                    if ready["status"] != "ready":
                        reason = ready.get("reason", "No se pudo abrir la bandeja.")
                        attempt_reason = reason
                        outcome = (
                            "omitido"
                            if self.__dict__.get("skip") and self.skip.is_set()
                            else "fallida"
                        )
                        if ready["status"] == "reader_error":
                            status = "lector_no_listo"
                            break
                        if ready["status"] in ("limited", "stopped"):
                            status = ready["status"]
                            break
                        continue
                    if self.__dict__.get("preparation") and not self.preparation():
                        status = "emulador_no_listo"
                        reason = attempt_reason = (
                            "La bandeja está lista, pero no se confirmó Android desbloqueado. Revisa la instancia."
                        )
                        break
                    if self.__dict__.get("batch_mode") or self.app.__dict__.get(
                        "outlook"
                    ):
                        from .navigation import prepare_login

                        self.state(
                            "consulta", "Preparando IMSS para la siguiente CURP", detail
                        )
                        if not prepare_login(
                            self.app,
                            path,
                            instance,
                            self.cancel.is_set,
                            self.cancel.wait,
                        ):
                            status = "sin_confirmar"
                            reason = attempt_reason = (
                                "No pude confirmar el formulario de IMSS; revisa la sesión anterior."
                            )
                            outcome = "sin_confirmar"
                            break
                    self.bridge.started(self.job)
                    self.rejected = False
                    self.reset_ready = False
                    self.app.resultado_tramite = False
                    self.app.pendiente = None
                    self.state(
                        "consulta", "Bandeja lista; iniciando la solicitud IMSS", detail
                    )
                    self.journal(
                        request,
                        curp,
                        instance,
                        procedure,
                        number + offset,
                        email,
                        "consulta",
                        "en_curso",
                    )
                    self.app.root.after(0, lambda: self.app.codigo.set(""))
                    submitted = True
                    self.app._consulta(path, curp, email, instance, procedure)
                    pending = self.app.pendiente
                    if self.cancel.is_set():
                        return
                    if not pending or pending[2:5] != (instance, curp, email):
                        reason = attempt_reason = (
                            "IMSS no llegó a solicitar el código. Revisa la instancia antes de repetir."
                        )
                        outcome = "sin_confirmar"
                        status = "sin_confirmar"
                        break
                    self.bridge.waiting(self.job)
                    self.state(
                        "codigo", "Esperando un correo nuevo del IMSS", detail, timeout
                    )
                    self.journal(
                        request,
                        curp,
                        instance,
                        procedure,
                        number + offset,
                        email,
                        "codigo",
                        "en_curso",
                    )
                    response = self.response(
                        self.job,
                        email,
                        instance,
                        {"code", "error", "reader_error", "limited", "stopped"},
                        timeout + 10,
                    )
                    if response["status"] != "code":
                        reason = response.get(
                            "reason", "No llegó un código verificable."
                        )
                        attempt_reason = reason
                        outcome = (
                            "omitido"
                            if self.__dict__.get("skip") and self.skip.is_set()
                            else "fallida"
                        )
                        self.app.pendiente = None
                        if response["status"] == "reader_error":
                            status = "sin_confirmar"
                            break
                        if response["status"] in ("limited", "stopped"):
                            status = response["status"]
                            break
                        if not self.return_to_login(path, pending[1]):
                            status = "sin_confirmar"
                            break
                        continue
                    code = response.get("code", "")
                    if self.__dict__.get("skip") and self.skip.is_set():
                        outcome = "omitido"
                        reason = attempt_reason = "Correo omitido por el usuario."
                        self.app.pendiente = None
                        if not self.return_to_login(path, pending[1]):
                            status = "sin_confirmar"
                            break
                        continue
                    if (
                        not re.fullmatch(r"[0-9]{6}", code)
                        or self.app.pendiente != pending
                        or self.cancel.is_set()
                    ):
                        reason = attempt_reason = (
                            "La respuesta no corresponde a la solicitud activa."
                        )
                        status = "sin_confirmar"
                        break
                    self.state(
                        "validando",
                        "Código recibido; comprobando seis dígitos en IMSS",
                        detail,
                    )
                    self.journal(
                        request,
                        curp,
                        instance,
                        procedure,
                        number + offset,
                        email,
                        "validando",
                        "en_curso",
                    )
                    self.app.root.after(
                        0, lambda value=code: self.app.codigo.set(value)
                    )
                    self.app._codigo(code, *pending)
                    if self.app.resultado_tramite:
                        status = "completada"
                        reason = "IMSS confirmó el envío al correo."
                        outcome = "completada"
                        attempt_reason = "IMSS confirmó el envío al correo."
                        self.state(
                            "terminado",
                            "Solicitud completada: IMSS confirmó el envío",
                            detail,
                        )
                        self.app.emit(
                            "✔ Solicitud completada y envío de la constancia confirmado por IMSS."
                        )
                        self.app.events.put(
                            (
                                "aviso",
                                "✔ Solicitud completada. Revisa el correo de la constancia.",
                            )
                        )
                        return
                    if self.rejected:
                        reason = attempt_reason = "IMSS rechazó el código."
                        outcome = "rechazado"
                    else:
                        reason = attempt_reason = (
                            "IMSS no confirmó el resultado. Revisa la instancia antes de repetir."
                        )
                        outcome = "sin_confirmar"
                        status = "sin_confirmar"
                    if not self.rejected or not self.reset_ready:
                        if not self.reset_ready:
                            status = "sin_confirmar"
                        break
                finally:
                    if self.job:
                        self.bridge.finish(self.job)
                    if self.__dict__.get("release_email"):
                        self.release_email(email, self.job)
                    self.job = None
                    if self.cancel.is_set():
                        outcome = "detenida"
                        attempt_reason = (
                            "Solicitud detenida; revisar IMSS antes de repetir."
                        )
                    self.journal(
                        request,
                        curp,
                        instance,
                        procedure,
                        number + offset,
                        email,
                        "terminado",
                        outcome,
                        attempt_reason,
                    )
            if not self.cancel.is_set():
                if not attempted and offset == 0:
                    self.journal(
                        request,
                        curp,
                        instance,
                        procedure,
                        0,
                        "",
                        "terminado",
                        "fallida",
                        reason,
                    )
                self.state(
                    "terminado",
                    "No se logró completar la solicitud",
                    f"{len(attempted) + offset}/3 correos intentados · {reason}",
                )
                self.app.emit(
                    f"No se logró completar la solicitud. Correos intentados: {len(attempted) + offset}/3. {reason}"
                )
                self.app.events.put(
                    ("aviso", "No se logró completar la solicitud; revisa el registro.")
                )
        except Exception:
            status = "sin_confirmar"
            self.journal(
                request,
                curp,
                instance,
                procedure,
                max(1, len(attempted)) + offset,
                email or "",
                "terminado",
                "sin_confirmar"
                if self.stage in ("consulta", "validando", "tramite")
                else "fallida",
                "Operación interrumpida; revisar la instancia antes de repetir.",
            )
            self.state(
                "terminado",
                "Solicitud interrumpida; revisa la instancia y el historial.",
            )
            self.app.emit(
                "No se logró completar la solicitud conectada. Revisa la conexión y la instancia; puedes usar el modo manual."
            )
        finally:
            if self.job:
                self.bridge.finish(self.job)
                self.job = None
            if self.cancel.is_set() and status != "completada":
                status = "detenida"
                reason = "Solicitud detenida; revisar IMSS antes de repetir."
            self.last_result = RequestResult(
                status, len(attempted), email or "", reason, request, submitted
            )
            self.active = False
            self.app.busy = False
            self.deadline = None
            if self.cancel.is_set():
                self.state(
                    "terminado", "Solicitud detenida; revisa IMSS antes de repetir."
                )

            def restore():
                self.app.btn_consulta.configure(state="normal")
                self.app.selector_cantidad.configure(state="readonly")
                self.app.btn_codigo.configure(
                    state="normal" if self.app.pendiente else "disabled"
                )
                if not self.app.pendiente or self.cancel.is_set():
                    self.app.codigo.set("")
                if "skip_button" in self.__dict__:
                    self.skip_button.configure(state="disabled")

            try:
                self.app.root.after(0, restore)
            except (RuntimeError, tk.TclError):
                pass
