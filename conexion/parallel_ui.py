"""Main-thread controls for the persistent three-request queue."""

import queue
import sqlite3
import tkinter as tk
from tkinter import ttk, messagebox

from .batch import QueueInput
from .parallel import ConcurrentRunner, JobEngine

AUTO_INSTANCE = "Automática"
STATES = {
    "inicio": "Preparando",
    "outlook": "Abriendo bandeja",
    "emuladores": "Iniciando Android",
    "consulta": "Solicitud IMSS",
    "codigo": "Esperando código",
    "validando": "Validando código",
    "tramite": "Generando constancia",
    "terminado": "Finalizando",
    "completada": "Completada",
    "lector_no_listo": "Revisar lector",
    "emulador_no_listo": "Revisar emulador",
    "sin_confirmar": "Revisar resultado",
    "sin_correos": "Faltan correos",
    "fallida": "No completada",
    "cancelada": "Cancelada",
    "detenida": "Detenida",
    "limited": "Microsoft limita accesos",
    "stopped": "Conexión detenida",
    "recuperando": "Reintentando con otro correo",
}


class ParallelPanel:
    def __init__(self, app):
        self.app = app
        self.connection = app.conexion
        self.store = self.connection.batch.store
        recovered = self.store.recover_reader_blocks()
        self.events = queue.SimpleQueue()
        self.engine = JobEngine(
            app, lambda key, stage, text: self.events.put((key, stage, text))
        )
        self.runner = ConcurrentRunner(
            self.store,
            self.engine.execute,
            lambda text: self.connection.batch.events.put(("status", text)),
            can_dispatch=self.engine.has_mailboxes,
        )
        self.connection.batch.runner = self.runner
        self.connection.parallel = self
        self.limit = tk.IntVar(value=3)
        self.summary = tk.StringVar(
            value="Hasta 3 solicitudes · correos e instancias separados"
        )
        self.detail = tk.StringVar(
            value="Escribe una CURP y pulsa AGREGAR / INICIAR. Puedes añadir las siguientes mientras trabajan."
        )
        if recovered:
            self.detail.set(
                f"{recovered} solicitudes recuperadas del bloqueo V6; se comprobará IMSS antes de reintentar."
            )
        frame = tk.LabelFrame(
            app.imss_panel.master,
            text="SOLICITUDES SIMULTÁNEAS",
            bg="#222229",
            fg="#d9b75b",
            padx=8,
            pady=6,
        )
        frame.pack(fill="x", padx=16, pady=6, before=app.imss_panel)
        row = tk.Frame(frame, bg="#222229")
        row.pack(fill="x")
        tk.Label(row, text="A la vez:", bg="#222229", fg="white").pack(side="left")
        self.selector = ttk.Combobox(
            row, textvariable=self.limit, values=(1, 2, 3), state="readonly", width=3
        )
        self.selector.pack(side="left", padx=6)
        tk.Label(row, textvariable=self.summary, bg="#222229", fg="white").pack(
            side="left", padx=8
        )
        self.table = ttk.Treeview(
            frame,
            columns=("curp", "instancia", "correo", "estado"),
            show="headings",
            height=3,
        )
        for name, width in [
            ("curp", 175),
            ("instancia", 155),
            ("correo", 250),
            ("estado", 220),
        ]:
            self.table.heading(name, text=name.upper())
            self.table.column(name, width=width, minwidth=60)
        self.table.pack(fill="x", pady=5)
        self.table.bind("<<TreeviewSelect>>", lambda event: self.selected_detail())
        actions = tk.Frame(frame, bg="#222229")
        actions.pack(fill="x")
        for text, command in [
            ("Detener seleccionada", self.stop_selected),
            ("Omitir correo seleccionado", self.skip_selected),
            ("Pausar cola", self.runner.pause),
        ]:
            ttk.Button(actions, text=text, command=command).pack(
                side="left", padx=(0, 6)
            )
        tk.Label(
            frame,
            textvariable=self.detail,
            bg="#222229",
            fg="#c9c9c9",
            wraplength=850,
            anchor="w",
        ).pack(fill="x", pady=(5, 0))
        self.rows = {}
        self.managing = False
        self.connection.skip_button.pack_forget()
        self.connection.stop_button.configure(text="Detener todas")
        app.btn_consulta.configure(text="▶ AGREGAR / INICIAR")
        # Keep the CURP entry above the instance settings while requests run.
        app.btn_consulta.master.pack_configure(
            before=app.imss_panel.winfo_children()[0]
        )
        app.inst_sel.set(AUTO_INSTANCE)
        app.selector_instancia.configure(values=(AUTO_INSTANCE,) + tuple(app.nombres))
        app.root.after(100, self.tick)

    def alive(self):
        return self.runner.running or bool(self.engine.contexts)

    def selected_id(self):
        selected = self.table.selection()
        return int(selected[0]) if selected else None

    def selected_detail(self):
        key = self.selected_id()
        if key in self.rows:
            self.detail.set(self.rows[key].get("detalle", ""))

    def stop_selected(self):
        key = self.selected_id()
        if key is not None:
            self.engine.cancel(key)

    def skip_selected(self):
        key = self.selected_id()
        if key is not None:
            self.engine.cancel(key, skip=True)

    def stop(self):
        self.runner.stop()
        self.engine.cancel()
        self.detail.set(
            "Deteniendo las solicitudes activas; los pendientes se conservan."
        )

    def start_from_batch(self):
        self.start(self.app.ruta())

    def start(self, path):
        if self.runner.running:
            self.runner.wake.set()
            return True
        try:
            if self.app.busy or self.app.desbloqueando:
                raise ValueError(
                    "Espera a que termine la preparación de las instancias."
                )
            if not path:
                raise ValueError("Selecciona ldconsole.exe en la sección IMSS.")
            if self.connection.history is None or not self.connection.available:
                raise ValueError("No se pudo abrir el historial local.")
            if not self.app.outlook.activate_for_request():
                return False
            count = self.limit.get()
            if count not in (1, 2, 3):
                raise ValueError("Elige de 1 a 3 solicitudes simultáneas.")
            self.runner.capacity = min(count, len(self.app.nombres))
            self.engine.snapshot = {
                "path": path,
                "timeout": self.connection.code_timeout.get(),
                "accounts": tuple(self.app.outlook.accounts),
                "stopping": self.runner.stopping,
                "used": __import__("gestoria_5_instancias").correos_usados(),
            }
            self.connection.batch.snapshot = {
                "path": path,
                "timeout": self.connection.code_timeout.get(),
                "sender": "",
                "subject": "",
            }
            self.engine.provider_limited.clear()
            self.app.iniciado = True
            self.connection.active = True
            self.app.busy = True
            self.managing = True
            self.runner.start(tuple(self.app.nombres), 0)
            return True
        except (ValueError, tk.TclError) as error:
            messagebox.showerror("Solicitudes", str(error), parent=self.app.root)
            return False

    def submit(self, path, curp, instance, procedure):
        if self.store.counts().get("pendiente", 0) >= 10000:
            self.detail.set(
                "La cola ya tiene 10 000 pendientes. Espera o revisa Lotes."
            )
            return
        if not self.runner.running:
            if self.app.busy or not self.app.outlook.activate_for_request():
                return
        preferred = (
            ""
            if self.runner.running
            else self.connection.preferred_email.get().casefold()
        )
        item = QueueInput(
            curp, procedure, "" if instance == AUTO_INSTANCE else instance, preferred
        )
        try:
            added, _ = self.store.import_items([item])
            if not added:
                self.detail.set(
                    "Esta CURP y trámite ya están en la cola o en el historial. Revisa Lotes."
                )
                return
            self.app.emit(f"CURP añadida a la cola: {curp}")
            self.app.curp.set("")
            if self.runner.running:
                self.runner.wake.set()
            else:
                self.start(path)
        except (ValueError, OSError) as error:
            messagebox.showerror("Solicitudes", str(error), parent=self.app.root)

    def tick(self):
        try:
            while True:
                key, stage, text = self.events.get_nowait()
                row = self.rows.setdefault(
                    key,
                    {
                        "curp": "",
                        "instancia": "",
                        "correo": "",
                        "estado": "",
                        "detalle": "",
                    },
                )
                with self.engine.lock:
                    context = self.engine.contexts.get(key)
                if context:
                    row.update(
                        curp=context.item["curp"], instancia=context.item["instancia"]
                    )
                elif stage == "inicio" and " · " in text:
                    row["curp"], row["instancia"] = text.split(" · ", 1)
                if stage == "correo":
                    row["correo"] = text
                elif stage != "detalle":
                    row["estado"] = stage
                if stage != "detalle" or row["estado"] not in (
                    "lector_no_listo",
                    "sin_confirmar",
                    "emulador_no_listo",
                ):
                    row["detalle"] = text
                values = (
                    row["curp"],
                    row["instancia"],
                    row["correo"],
                    STATES.get(row["estado"], row["estado"]),
                )
                if self.table.exists(str(key)):
                    self.table.item(str(key), values=values)
                else:
                    self.table.insert("", "end", iid=str(key), values=values)
                    self.table.see(str(key))
                if len(self.table.get_children()) > 50:
                    first = self.table.get_children()[0]
                    if int(first) not in self.engine.contexts:
                        self.table.delete(first)
                        self.rows.pop(int(first), None)
        except queue.Empty:
            pass
        running = self.runner.running
        self.connection.active = running
        if running:
            self.app.busy = True
            self.managing = True
            self.app.outlook.active_email.set(
                "Cada fila usa su propio correo para Outlook e IMSS."
            )
            for control in self.app.outlook.manage_buttons:
                control.configure(state="disabled")
        elif self.managing:
            self.app.busy = False
            self.managing = False
            if (
                not self.app.outlook._running
                and not self.app.outlook.mailbox_opening.is_set()
            ):
                for control in self.app.outlook.manage_buttons:
                    control.configure(state="normal")
        self.selector.configure(state="disabled" if running else "readonly")
        self.app.selector_cantidad.configure(
            state="disabled" if self.app.busy else "readonly"
        )
        self.app.btn.configure(state="disabled" if self.app.busy else "normal")
        self.app.btn_imss.configure(state="disabled" if self.app.busy else "normal")
        try:
            counts = self.store.counts()
        except (OSError, sqlite3.Error):
            self.summary.set("No se pudo leer la cola; revisa el almacenamiento.")
            self.app.root.after(500, self.tick)
            return
        self.connection.progress.configure(
            value=min(100, counts["completada"] * 100 / max(1, sum(counts.values())))
        )
        self.summary.set(
            f"{counts['en_curso']}/{self.runner.capacity} activas · {counts['pendiente']} pendientes · {counts['revision']} por revisar"
        )
        self.connection.status.set(
            "Solicitudes trabajando por separado"
            if running
            else "Listo para añadir solicitudes"
        )
        self.connection.detail.set(
            self.store.pause_reason()
            or "Outlook prepara la bandeja mientras arranca cada instancia IMSS."
        )
        self.app.root.after(150, self.tick)
