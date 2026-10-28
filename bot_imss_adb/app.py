"""Panel independiente de IMSS por ADB. Ejecutar con ABRIR_BOT.bat."""
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

try:
    from .adb import Adb, AdbError, Cancelled, find_adb
    from .flow import Flow, FlowError, Job
    from .mail_service import ManualMailbox, OutlookMailbox
    from .storage import History, data_dir, device_lock, load_config, save_config
except ImportError:
    from adb import Adb, AdbError, Cancelled, find_adb
    from flow import Flow, FlowError, Job
    from mail_service import ManualMailbox, OutlookMailbox
    from storage import History, data_dir, device_lock, load_config, save_config


BG, CARD, FG, MUTED, GOLD = "#10151d", "#1b2430", "#edf2f7", "#a9b7c7", "#e2bb61"
STAGES = (("adb", "Conexión ADB"), ("correo", "Bandeja Outlook"), ("imss", "Acceso a IMSS"),
          ("codigo", "Código de verificación"), ("nss", "Consulta NSS"),
          ("vigencia", "Vigencia de derechos"), ("semanas", "Semanas cotizadas"), ("cerrando", "Cierre de sesión"))


class App:
    def __init__(self, root, folder=None):
        self.root, self.folder = root, Path(folder) if folder else data_dir()
        self.history = History(self.folder)
        self.history.recover()
        self.events = queue.Queue()
        self.cancelled = threading.Event()
        self.code_queue = queue.Queue(maxsize=1)
        self.worker = None
        self.waiting_code = self.closing = False
        self.device_map = {}
        self.controls = []
        self.selected_stage = None
        config = load_config(self.folder)
        self.adb_path = tk.StringVar(value=config.get("adb") or find_adb())
        self.endpoint = tk.StringVar(value=config.get("endpoint", "127.0.0.1:5555"))
        self.device = tk.StringVar()
        self.saved_serial = config.get("serial", "")
        self.curp = tk.StringVar()
        self.email = tk.StringVar()
        self.password = tk.StringVar()
        self.pin = tk.StringVar()
        self.mode = tk.StringVar(value="Outlook automático")
        self.code = tk.StringVar()
        self.relink = tk.BooleanVar(value=False)
        self.logout = tk.BooleanVar(value=True)
        self.procedures = {k: tk.BooleanVar(value=True) for k in ("nss", "vigencia", "semanas")}
        self.status = tk.StringVar(value="1. Selecciona adb.exe y pulsa Detectar emuladores.")
        self._build()
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.after(100, self.drain)

    def _build(self):
        root = self.root
        root.title("GESTORÍA DÍAZ · BOT NUEVO ADB · V1")
        root.geometry("1030x900")
        root.minsize(850, 680)
        root.configure(bg=BG)
        style = ttk.Style(root)
        style.theme_use("clam")
        style.configure("TFrame", background=BG)
        style.configure("TLabelframe", background=CARD, bordercolor="#334355")
        style.configure("TLabelframe.Label", background=CARD, foreground=GOLD, font=("Segoe UI", 11, "bold"))
        style.configure("TLabel", background=CARD, foreground=FG, font=("Segoe UI", 10))
        style.configure("TCheckbutton", background=CARD, foreground=FG)
        style.map("TCheckbutton", background=[("active", CARD)])
        style.configure("TButton", padding=(12, 6), font=("Segoe UI", 10))
        style.configure("Go.TButton", background=GOLD, foreground=BG, font=("Segoe UI", 11, "bold"))
        style.configure("Treeview", rowheight=25, background=CARD, fieldbackground=CARD, foreground=FG)
        style.configure("Treeview.Heading", background="#293747", foreground=FG)
        # A canvas keeps every button accessible on smaller Windows displays.
        outer = ttk.Frame(root)
        outer.pack(fill="both", expand=True)
        canvas = tk.Canvas(outer, bg=BG, highlightthickness=0)
        bar = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=bar.set)
        bar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        body = ttk.Frame(canvas, padding=18)
        window = canvas.create_window((0, 0), window=body, anchor="nw")
        body.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(window, width=e.width))
        root.bind("<MouseWheel>", lambda e: canvas.yview_scroll(-int(e.delta / 120), "units"))
        tk.Label(body, text="GESTORÍA DÍAZ", font=("Segoe UI", 24, "bold"), bg=BG, fg=GOLD).pack(anchor="w")
        tk.Label(body, text="BOT NUEVO · ADB + OUTLOOK + IMSS DIGITAL", font=("Segoe UI", 10), bg=BG, fg=MUTED).pack(anchor="w", pady=(0, 14))
        connection = ttk.LabelFrame(body, text="1 · CONEXIÓN AL EMULADOR", padding=12)
        connection.pack(fill="x", pady=5)
        connection.columnconfigure(1, weight=1)
        ttk.Label(connection, text="Ruta de adb.exe").grid(row=0, column=0, sticky="w", padx=(0, 10))
        self.entry(connection, self.adb_path, row=0, column=1, sticky="ew")
        self.action(connection, "Examinar", self.browse, row=0, column=2, padx=6)
        self.action(connection, "Detectar emuladores", self.detect, row=1, column=2, pady=8, padx=6)
        ttk.Label(connection, text="Dispositivo").grid(row=1, column=0, sticky="w")
        combo = ttk.Combobox(connection, textvariable=self.device, state="readonly", width=44)
        combo.grid(row=1, column=1, sticky="ew", pady=8)
        self.device_combo = combo
        self.controls.append((combo, "readonly"))
        ttk.Label(connection, text="Puerto local opcional").grid(row=2, column=0, sticky="w")
        self.entry(connection, self.endpoint, row=2, column=1, sticky="ew")
        self.action(connection, "Conectar puerto", self.connect_endpoint, row=2, column=2, padx=6)
        row = ttk.Frame(connection)
        row.grid(row=3, column=0, columnspan=3, sticky="w", pady=(9, 0))
        self.action(row, "Probar conexión ADB", self.probe, row=0, column=0)
        self.action(row, "Abrir IMSS Digital", self.open_imss, row=0, column=1, padx=8)

        form = ttk.LabelFrame(body, text="2 · UNA SOLICITUD · EL MISMO CORREO", padding=12)
        form.pack(fill="x", pady=8)
        form.columnconfigure(1, weight=1)
        form.columnconfigure(3, weight=1)
        ttk.Label(form, text="CURP").grid(row=0, column=0, sticky="w", padx=(0, 12))
        self.entry(form, self.curp, row=0, column=1, sticky="ew", width=24)
        ttk.Label(form, text="Correo").grid(row=0, column=2, padx=12)
        self.entry(form, self.email, row=0, column=3, sticky="ew", width=30)
        ttk.Label(form, text="Código").grid(row=1, column=0, sticky="w", pady=10)
        mode = ttk.Combobox(form, textvariable=self.mode, values=("Outlook automático", "Código manual"), state="readonly")
        mode.grid(row=1, column=1, sticky="ew")
        self.controls.append((mode, "readonly"))
        ttk.Label(form, text="Contraseña Outlook").grid(row=1, column=2, padx=12)
        self.entry(form, self.password, show="●", row=1, column=3, sticky="ew")
        ttk.Label(form, text="PIN Android opcional").grid(row=2, column=0, sticky="w")
        self.entry(form, self.pin, show="●", row=2, column=1, sticky="ew")
        checks = ttk.Frame(form)
        checks.grid(row=3, column=0, columnspan=4, sticky="w", pady=10)
        for col, (key, label) in enumerate((("nss", "NSS"), ("vigencia", "Vigencia de derechos"), ("semanas", "Semanas cotizadas"))):
            widget = ttk.Checkbutton(checks, text=label, variable=self.procedures[key])
            widget.grid(row=0, column=col, padx=(0, 18))
            self.controls.append((widget, "normal"))
        for n, (variable, label) in enumerate(((self.relink, "Autorizar «Sí, quiero hacer el cambio» si IMSS lo solicita"),
                                               (self.logout, "Cerrar sesión al terminar los trámites confirmados"))):
            widget = ttk.Checkbutton(form, text=label, variable=variable)
            widget.grid(row=4 + n, column=0, columnspan=4, sticky="w", pady=3)
            self.controls.append((widget, "normal"))
        run = ttk.Frame(form)
        run.grid(row=6, column=0, columnspan=4, sticky="ew", pady=(12, 0))
        self.action(run, "INICIAR SOLICITUD", self.start, style="Go.TButton", row=0, column=0)
        self.stop_button = ttk.Button(run, text="Detener", command=self.stop, state="disabled")
        self.stop_button.grid(row=0, column=1, padx=10)
        self.action(run, "Exportar registro", self.export, row=0, column=2)
        manual = ttk.Frame(form)
        manual.grid(row=7, column=0, columnspan=4, sticky="ew", pady=(12, 0))
        ttk.Label(manual, text="Código manual / respaldo").pack(side="left", padx=(0, 12))
        self.code_entry = ttk.Entry(manual, textvariable=self.code, width=10, state="disabled")
        self.code_entry.pack(side="left")
        self.code_button = ttk.Button(manual, text="Enviar código", command=self.send_code, state="disabled")
        self.code_button.pack(side="left", padx=8)

        ttk.Label(body, textvariable=self.status, background=BG, foreground=GOLD, wraplength=930).pack(fill="x", pady=10)
        progress = ttk.LabelFrame(body, text="3 · AVANCE VISIBLE", padding=8)
        progress.pack(fill="x")
        self.table = ttk.Treeview(progress, columns=("paso", "estado"), show="headings", height=8)
        self.table.heading("paso", text="Paso")
        self.table.heading("estado", text="Resultado")
        self.table.column("paso", width=190, stretch=False)
        self.table.column("estado", width=650)
        self.table.pack(fill="x")
        for key, title in STAGES:
            self.table.insert("", "end", iid=key, values=(title, "Pendiente"))
        self.log = tk.Text(body, height=7, bg=CARD, fg=MUTED, relief="flat", wrap="word", state="disabled", font=("Consolas", 9))
        self.log.pack(fill="both", expand=True, pady=(10, 0))

    def entry(self, parent, variable, **kwargs):
        show = kwargs.pop("show", None)
        width = kwargs.pop("width", None)
        widget = ttk.Entry(parent, textvariable=variable, show=show or "", width=width or 20)
        widget.grid(**kwargs)
        self.controls.append((widget, "normal"))
        return widget

    def action(self, parent, label, command, **kwargs):
        style = kwargs.pop("style", "TButton")
        widget = ttk.Button(parent, text=label, command=command, style=style)
        widget.grid(**kwargs)
        self.controls.append((widget, "normal"))
        return widget

    def busy(self, value):
        for widget, state in self.controls:
            widget.configure(state="disabled" if value else state)
        self.stop_button.configure(state="normal" if value else "disabled")

    def post(self, stage, detail):
        self.events.put(("stage", (stage, detail)))

    def browse(self):
        path = filedialog.askopenfilename(title="Selecciona adb.exe", filetypes=(("ADB", "adb.exe"), ("Todos", "*")))
        if path:
            self.adb_path.set(path)

    def client(self, require_device=True):
        serial = self.device_map.get(self.device.get(), "")
        if require_device and not serial:
            raise ValueError("Pulsa Detectar emuladores y selecciona el dispositivo.")
        return Adb(self.adb_path.get().strip().strip('"'), serial, self.cancelled)

    def launch_task(self, function):
        if self.worker and self.worker.is_alive():
            return
        self.cancelled.clear()
        self.busy(True)

        def run():
            try:
                function()
            except (AdbError, FlowError, Cancelled, ValueError) as exc:
                self.events.put(("error", str(exc)))
            except Exception:
                self.events.put(("error", "Ocurrió un error interno. La solicitud se detuvo; revisa el emulador antes de repetir."))
            finally:
                self.events.put(("idle", None))

        self.worker = threading.Thread(target=run, name="imss-adb-worker", daemon=False)
        self.worker.start()

    def detect(self):
        client = self.client(False)
        self.launch_task(lambda: self.events.put(("devices", client.devices())))

    def connect_endpoint(self):
        client, endpoint = self.client(False), self.endpoint.get()
        self.launch_task(lambda: self.events.put(("devices", client.connect(endpoint))))

    def probe(self):
        try:
            client = self.client()
        except ValueError as exc:
            messagebox.showerror("Conexión ADB", str(exc))
            return
        self.launch_task(lambda: self.post("adb", client.probe()))

    def open_imss(self):
        try:
            client = self.client()
        except ValueError as exc:
            messagebox.showerror("Conexión ADB", str(exc))
            return

        def open_it():
            client.probe()
            client.launch()
            self.post("adb", "ADB conectado. Se solicitó abrir IMSS Digital en el dispositivo elegido.")

        self.launch_task(open_it)

    def start(self):
        if self.worker and self.worker.is_alive():
            return
        try:
            client = self.client()
            job = Job(self.curp.get().strip().upper(), self.email.get().strip(),
                      tuple(k for k, v in self.procedures.items() if v.get()), self.pin.get(), self.relink.get(), self.logout.get())
            job.validate()
            automatic = self.mode.get() == "Outlook automático"
            password = self.password.get()
            if automatic and not password:
                raise ValueError("Escribe la contraseña de Outlook para leer el código automáticamente.")
            save_config(self.folder, adb=client.executable, serial=client.serial, endpoint=self.endpoint.get())
        except (OSError, ValueError) as exc:
            messagebox.showerror("Nueva solicitud", str(exc))
            return
        self.password.set("")
        self.pin.set("")
        self.code.set("")
        self.selected_stage = None
        self.code_queue = queue.Queue(maxsize=1)
        for key, title in STAGES:
            self.table.item(key, values=(title, "Pendiente"))
        mailbox = OutlookMailbox(password, self.cancelled) if automatic else ManualMailbox(self.ask_code)
        lock = device_lock(self.folder, client.serial)

        def run():
            if not lock.acquire():
                raise FlowError("Otra ventana de este bot está usando el mismo emulador. Detén esa solicitud primero.")
            flow, ident = Flow(client, self.post), None
            state, detail = "revision", "Solicitud sin confirmar. Revisa IMSS antes de repetir."
            try:
                ident = self.history.start(job, client.serial)
                flow.run(job, mailbox)
                state, detail = "completada", "IMSS confirmó los trámites seleccionados."
            except Cancelled:
                state, detail = "detenida", "Se detuvo la solicitud. Revisa los resultados parciales antes de repetir."
                raise
            except (FlowError, AdbError) as exc:
                detail = str(exc)
                raise
            finally:
                mailbox.close()
                try:
                    if ident:
                        self.history.finish(ident, state, detail, flow.results)
                finally:
                    lock.release()

        self.launch_task(run)

    def ask_code(self, email):
        self.events.put(("ask_code", email))
        import time
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline:
            if self.cancelled.is_set():
                raise Cancelled("Solicitud detenida.")
            try:
                return self.code_queue.get(timeout=.2)
            except queue.Empty:
                pass
        raise FlowError("No se ingresó el código manual en cinco minutos.")

    def send_code(self):
        import re
        value = self.code.get().strip()
        if not self.waiting_code or not re.fullmatch(r"[0-9]{6}", value):
            messagebox.showerror("Código", "Escribe exactamente los seis dígitos del correo de esta solicitud.")
            return
        try:
            self.code_queue.put_nowait(value)
        except queue.Full:
            return
        self.waiting_code = False
        self.code.set("")
        self.code_entry.configure(state="disabled")
        self.code_button.configure(state="disabled")

    def stop(self):
        self.cancelled.set()
        self.status.set("Deteniendo. Se esperará a que termine el comando actual de ADB o navegador.")
        self.stop_button.configure(state="disabled")

    def export(self):
        path = filedialog.asksaveasfilename(title="Exportar resultados", defaultextension=".csv", initialfile="registro_imss_adb.csv", filetypes=(("CSV", "*.csv"),))
        if path:
            try:
                self.history.export(path)
                self.status.set("Registro exportado. No contiene contraseñas, PIN ni códigos.")
            except OSError:
                messagebox.showerror("Registro", "No se pudo guardar el archivo. Revisa la carpeta de destino.")

    def drain(self):
        from datetime import datetime
        while True:
            try:
                kind, value = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == "devices":
                self.device_map = {f"{d.serial} · {d.state}" + (f" · {d.model}" if d.model else ""): d.serial for d in value}
                self.device_combo.configure(values=tuple(self.device_map))
                online = [d.serial for d in value if d.state == "device"]
                choice = self.saved_serial if self.saved_serial in online else online[0] if len(online) == 1 else ""
                self.device.set(next((label for label, serial in self.device_map.items() if serial == choice), ""))
                self.status.set(f"Detectados {len(online)} dispositivos disponibles. Elige uno y prueba la conexión." if online else "No hay dispositivos disponibles. Enciende el emulador y activa su depuración ADB; revisa el puerto local.")
            elif kind in ("stage", "error"):
                stage, detail = value if kind == "stage" else ("error", value)
                self.status.set(detail)
                if stage in dict(STAGES):
                    self.selected_stage = stage
                    self.table.item(stage, values=(dict(STAGES)[stage], detail))
                elif stage == "error" and self.selected_stage:
                    self.table.item(self.selected_stage, values=(dict(STAGES)[self.selected_stage], detail))
                self.log.configure(state="normal")
                self.log.insert("end", datetime.now().strftime("%H:%M:%S") + "  " + detail + "\n")
                self.log.see("end")
                self.log.configure(state="disabled")
            elif kind == "ask_code":
                self.waiting_code = True
                self.status.set("Pega el código más reciente enviado a " + value)
                self.code_entry.configure(state="normal")
                self.code_button.configure(state="normal")
                self.code_entry.focus_set()
            elif kind == "idle":
                self.waiting_code = False
                self.code.set("")
                self.code_entry.configure(state="disabled")
                self.code_button.configure(state="disabled")
                self.busy(False)
        if self.closing:
            if not self.worker or not self.worker.is_alive():
                self.root.destroy()
                return
            self.busy(True)
            self.stop_button.configure(state="disabled")
        self.root.after(100, self.drain)

    def close(self):
        self.closing = True
        if self.worker and self.worker.is_alive():
            self.stop()
        else:
            self.root.destroy()


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
