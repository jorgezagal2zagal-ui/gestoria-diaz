"""Main-thread queue dashboard and a sequential worker adapter."""

from pathlib import Path
import queue
import sys
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from .batch import BatchStore, BatchRunner, parse_batch, STATUSES
from .result import RequestResult


class BatchPanel:
    def __init__(self, connection):
        self.connection = connection
        self.app = connection.app
        self.store = BatchStore(connection.bridge.root)
        self.store.recover_interrupted()
        self.events = queue.SimpleQueue()
        self.runner = BatchRunner(
            self.store, self.execute, lambda text: self.events.put(("status", text))
        )
        self.summary = tk.StringVar(value="Cola de CURP: lista para importar")
        self.notice = tk.StringVar(
            value=self.store.pause_reason()
            or "Importa TXT o CSV. Cada solicitud usa hasta tres correos."
        )
        self.interval = tk.IntVar(value=10)
        self.filter = tk.StringVar(value="todas")
        self.offset = 0
        self.window = None
        self.importing = False
        self.snapshot = {}
        self._busy_before = False
        self.app.root.after(1000, self.tick)

    def controls(self, parent):
        row = tk.Frame(parent, bg="#222229")
        row.pack(fill="x", pady=(10, 0))
        ttk.Button(row, text="COLA DE CURP · LOTES", command=self.show).pack(
            side="left", padx=(0, 10)
        )
        tk.Label(
            row,
            textvariable=self.summary,
            bg="#222229",
            fg="#d9b75b",
            anchor="w",
            wraplength=620,
        ).pack(side="left", fill="x", expand=True)

    def show(self):
        if self.window is not None and self.window.winfo_exists():
            self.window.lift()
            return
        self.window = tk.Toplevel(self.app.root)
        w = self.window
        w.title("Gestoría Díaz V4 | Cola de solicitudes")
        w.geometry("1160x650")
        w.minsize(900, 550)
        outer = ttk.Frame(w, padding=12)
        outer.pack(fill="both", expand=True)
        ttk.Label(
            outer, text="COLA DE CURP · FLUJO POR LOTES", font=("Segoe UI", 18, "bold")
        ).pack(anchor="w")
        ttk.Label(outer, textvariable=self.summary).pack(anchor="w", pady=6)
        ttk.Label(outer, textvariable=self.notice, wraplength=1050).pack(
            anchor="w", pady=(0, 8)
        )
        actions = ttk.Frame(outer)
        actions.pack(fill="x", pady=6)
        for text, action in [
            ("Importar TXT / CSV", self.import_file),
            ("Iniciar / reanudar", self.start),
            ("Pausar al terminar actual", self.pause),
            ("Detener ahora", self.stop),
        ]:
            ttk.Button(actions, text=text, command=action).pack(
                side="left", padx=(0, 6)
            )
        settings = ttk.Frame(outer)
        settings.pack(fill="x", pady=6)
        ttk.Label(settings, text="Pausa entre solicitudes (5–120 s):").pack(side="left")
        ttk.Spinbox(
            settings, from_=5, to=120, textvariable=self.interval, width=5
        ).pack(side="left", padx=6)
        ttk.Label(settings, text="Filtrar:").pack(side="left", padx=(20, 6))
        select = ttk.Combobox(
            settings,
            values=("todas",) + tuple(sorted(STATUSES)),
            textvariable=self.filter,
            state="readonly",
            width=15,
        )
        select.pack(side="left")
        select.bind("<<ComboboxSelected>>", lambda event: self.first_page())
        frame = ttk.Frame(outer)
        frame.pack(fill="both", expand=True)
        columns = (
            "id",
            "curp",
            "tramite",
            "instancia",
            "estado",
            "intentos",
            "correo",
            "motivo",
        )
        self.table = ttk.Treeview(
            frame, columns=columns, show="headings", selectmode="browse"
        )
        for name, width in zip(columns, (55, 185, 260, 160, 110, 65, 240, 400)):
            self.table.heading(name, text=name.capitalize())
            self.table.column(name, width=width, stretch=False)
        y = ttk.Scrollbar(frame, orient="vertical", command=self.table.yview)
        y.pack(side="right", fill="y")
        x = ttk.Scrollbar(frame, orient="horizontal", command=self.table.xview)
        x.pack(side="bottom", fill="x")
        self.table.configure(yscrollcommand=y.set, xscrollcommand=x.set)
        self.table.pack(fill="both", expand=True)
        footer = ttk.Frame(outer)
        footer.pack(fill="x", pady=8)
        ttk.Button(footer, text="Anterior", command=lambda: self.page(-100)).pack(
            side="left"
        )
        ttk.Button(footer, text="Siguiente", command=lambda: self.page(100)).pack(
            side="left", padx=6
        )
        ttk.Button(footer, text="Exportar lote CSV", command=self.export).pack(
            side="right"
        )
        review = ttk.Frame(outer)
        review.pack(fill="x")
        ttk.Label(review, text="Tras revisar IMSS, para la fila seleccionada:").pack(
            side="left"
        )
        for text, action in [
            ("Confirmar completada", "completada"),
            ("Omitir solicitud", "omitida"),
            ("Volver a pendientes", "pendiente"),
        ]:
            ttk.Button(
                review, text=text, command=lambda value=action: self.resolve(value)
            ).pack(side="left", padx=4)
        ttk.Button(
            outer,
            text="Cancelar únicamente las pendientes",
            command=self.cancel_pending,
        ).pack(anchor="w", pady=(8, 0))
        self.refresh()

    def first_page(self):
        self.offset = 0
        self.refresh()

    def page(self, delta):
        self.offset = max(0, self.offset + delta)
        self.refresh()

    def refresh(self, force=True):
        counts = self.store.counts()
        self.summary.set(
            f"{sum(counts.values())} solicitudes · {counts['pendiente']} pendientes · {counts['completada']} completadas · {counts['fallida']} fallidas · {counts['revision']} por revisar"
        )
        if self.window is not None and self.window.winfo_exists():
            key = (tuple(sorted(counts.items())), self.offset, self.filter.get())
            if not force and self.__dict__.get("_last_render_key") == key:
                return
            self._last_render_key = key
            selected = self.table.selection()
            status = self.filter.get()
            rows = self.store.rows(
                None if status == "todas" else status, offset=self.offset
            )
            self.table.delete(*self.table.get_children())
            for row in rows:
                self.table.insert(
                    "",
                    "end",
                    iid=str(row["id"]),
                    values=[row[key] for key in self.table["columns"]],
                )
            if selected and self.table.exists(selected[0]):
                self.table.selection_set(selected[0])

    def tick(self):
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == "imported":
                    self.importing = False
                    self.notice.set(value)
                    self.refresh()
                elif kind == "error":
                    self.importing = False
                    self.notice.set(value)
                    messagebox.showerror("Cola", value, parent=self.dialog_parent())
                else:
                    self.notice.set(value)
        except queue.Empty:
            pass
        try:
            self.refresh(force=False)
            reason = self.store.pause_reason()
            if not self.runner.running and reason:
                self.notice.set(reason)
        except Exception:
            self.notice.set("No se pudo leer la cola. Revisa el almacenamiento local.")
        self.app.root.after(1000, self.tick)

    def dialog_parent(self):
        return (
            self.window
            if self.window is not None and self.window.winfo_exists()
            else self.app.root
        )

    def import_file(self):
        if self.runner.running or self.importing:
            self.notice.set(
                "Pausa el lote y espera a que termine la importación actual."
            )
            return
        path = filedialog.askopenfilename(
            parent=self.window, filetypes=[("CURP TXT / CSV", "*.txt *.csv")]
        )
        if not path:
            return
        module = sys.modules[type(self.app).__module__]
        default = self.app.tramite.get()
        instances = tuple(module.TODOS_NOMBRES)
        procedures = tuple(module.TRAMITES)
        self.importing = True
        self.notice.set(
            "Validando e importando; ninguna solicitud se envía durante la importación."
        )

        def work():
            try:
                source = Path(path)
                if source.stat().st_size > 16 * 1024 * 1024:
                    raise ValueError("El archivo supera 16 MB.")
                items, duplicates = parse_batch(
                    source.read_text(encoding="utf-8-sig"),
                    default,
                    procedures,
                    instances,
                    csv_file=source.suffix.casefold() == ".csv",
                )
                added, existing = self.store.import_items(items)
                self.events.put(
                    (
                        "imported",
                        f"{added} solicitudes añadidas · {duplicates + existing} duplicadas omitidas.",
                    )
                )
            except (OSError, UnicodeError):
                self.events.put(
                    (
                        "error",
                        "No se pudo leer el archivo TXT/CSV. Usa UTF-8 y una carpeta accesible.",
                    )
                )
            except ValueError as exc:
                self.events.put(("error", str(exc)))
            except Exception:
                self.events.put(
                    (
                        "error",
                        "No se pudo importar la cola; no se inició ninguna solicitud.",
                    )
                )

        import threading

        threading.Thread(target=work, daemon=True).start()

    def start(self):
        c = self.connection
        if c.__dict__.get('parallel'):
            return c.parallel.start_from_batch()
        try:
            if self.importing or c.active or self.app.busy or self.runner.running:
                raise ValueError("Espera a que termine la operación actual.")
            if c.history is None or not c.available:
                raise ValueError("El historial y la conexión deben estar disponibles.")
            if not self.app.iniciado:
                raise ValueError(
                    "Prepara y enciende las instancias antes de iniciar el lote."
                )
            path = self.app.ruta()
            sender = ""
            subject = ""
            timeout = c.code_timeout.get()
            interval = self.interval.get()
            if not path:
                raise ValueError("Revisa la ruta de LDPlayer en Instancias.")
            outlook = self.app.__dict__.get("outlook")
            if outlook and not outlook.activate_for_request():
                return
            if not 60 <= timeout <= 300 or not 5 <= interval <= 120:
                raise ValueError(
                    "Tiempo del lector: 60–300 s; pausa del lote: 5–120 s."
                )
            presence = c.bridge.presence()
            if not presence or not presence["emails"]:
                raise ValueError("Activa Outlook e importa las cuentas primero.")
            if not self.store.counts()["pendiente"]:
                raise ValueError("No hay solicitudes pendientes.")
            self.snapshot = {
                "path": path,
                "sender": sender,
                "subject": subject,
                "timeout": timeout,
            }
            self.runner.start(tuple(self.app.nombres), interval)
            self.notice.set(
                "Lote iniciado. Cada código se entrega únicamente a su solicitud activa."
            )
        except (ValueError, tk.TclError) as exc:
            messagebox.showerror("Cola", str(exc), parent=self.dialog_parent())

    def execute(self, item):
        c = self.connection
        if self.runner.stopping.is_set():
            return RequestResult(
                "detenida", reason="Lote detenido antes de iniciar la solicitud."
            )
        if item.get("intentos", 0) >= 3:
            return RequestResult(
                "fallida", reason="Se alcanzaron los tres correos de esta solicitud."
            )
        c.batch_mode = True
        c.active = True
        self.app.busy = True
        c.cancel.clear()
        c.skip.clear()
        c.current_timeout = self.snapshot["timeout"]
        c.current_max_attempts = 3 - item.get("intentos", 0)
        c.attempt_offset = item.get("intentos", 0)
        c.current_request_id = (
            item.get("solicitud") if item.get("intentos", 0) > 0 else None
        )
        c.current_preferred_email = ""

        def lock_controls():
            self.app.btn_consulta.configure(state="disabled")
            self.app.btn_codigo.configure(state="disabled")
            self.app.selector_cantidad.configure(state="disabled")

        try:
            if self.runner.stopping.is_set():
                c.cancel.set()
                return RequestResult(
                    "detenida", reason="Lote detenido antes de iniciar la solicitud."
                )
            self.app.root.after(0, lock_controls)
            c.run(
                self.snapshot["path"],
                item["curp"],
                item["instancia"],
                item["tramite"],
                self.snapshot["sender"],
                self.snapshot["subject"],
            )
            return c.last_result
        finally:
            c.batch_mode = False
            c.current_max_attempts = 3
            c.attempt_offset = 0
            c.current_request_id = None
            c.current_preferred_email = ""
            c.active = False
            self.app.busy = False

    def pause(self):
        self.runner.pause()
        self.notice.set(
            "Se pausará al terminar la solicitud actual; se conservan los pendientes."
        )

    def stop(self):
        self.runner.stop()
        self.connection.stop()
        self.notice.set(
            "Deteniendo. Si IMSS ya recibió una acción, revisa su resultado."
        )

    def resolve(self, action):
        if self.runner.running:
            self.notice.set("Pausa el lote antes de resolver una solicitud.")
            return
        selected = self.table.selection()
        if not selected:
            self.notice.set("Selecciona una solicitud fallida o en revisión.")
            return
        if not messagebox.askyesno(
            "Revisión de solicitud",
            "Confirma que revisaste la instancia y el correo. ¿Aplicar la resolución a esta fila?",
            parent=self.window,
        ):
            return
        try:
            self.store.resolve(int(selected[0]), action)
            self.refresh()
            self.notice.set("Resolución guardada. Puedes reanudar los pendientes.")
        except ValueError as exc:
            messagebox.showerror("Cola", str(exc), parent=self.window)

    def cancel_pending(self):
        if self.runner.running:
            self.notice.set("Pausa el lote antes de cancelar las pendientes.")
            return
        if messagebox.askyesno(
            "Cancelar pendientes",
            "¿Cancelar todas las solicitudes pendientes? Las completadas y las que requieren revisión se conservan.",
            parent=self.window,
        ):
            self.store.cancel_pending()
            self.refresh()

    def export(self):
        path = filedialog.asksaveasfilename(
            parent=self.window,
            defaultextension=".csv",
            initialfile="lote_imss.csv",
            filetypes=[("Resultados CSV", "*.csv")],
        )
        if path:
            try:
                self.store.export(path)
                self.notice.set("Lote completo exportado.")
            except Exception:
                messagebox.showerror(
                    "Cola", "No se pudo guardar el CSV.", parent=self.window
                )
