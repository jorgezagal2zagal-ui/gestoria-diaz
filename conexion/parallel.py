"""Three bounded jobs; independent IMSS state, browser thread and bridge per job."""

from dataclasses import dataclass
from dataclasses import replace
import queue
import threading
import time
from types import SimpleNamespace

from .bridge import Bridge
from .imss_link import ImssConnection
from .result import RequestResult
from .timing import accelerated


class Value:
    """Worker-owned value/control. Never calls Tcl from a worker thread."""

    def __init__(self, value=""):
        self.value = value

    def set(self, value):
        self.value = value

    def get(self):
        return self.value

    def configure(self, **kwargs):
        pass


class WorkerRoot:
    def after(self, delay, callback):
        # These callbacks only update the worker's Value controls.
        callback()


class JobBridge(Bridge):
    def __init__(self, root, shared, accounts, stopped):
        super().__init__(root)
        self.shared, self.accounts, self.stopped = shared, accounts, stopped

    def presence(self):
        alive = self.__dict__.get("worker_alive")
        return (
            None
            if self.stopped.is_set() or (alive and not alive())
            else {"emails": [a.address.casefold() for a in self.accounts]}
        )

    def excluded_emails(self):
        return self.shared.excluded_emails()

    def email_failed(self, *args):
        return self.shared.email_failed(*args)

    def email_ready(self, *args):
        return self.shared.email_ready(*args)


class EmailLeases:
    def __init__(self, used, excluded):
        self.condition = threading.Condition()
        self.owners = {}
        self.used, self.excluded = used, excluded

    def claim(self, owner, pool, excluded, preferred, cancelled, timeout=90):
        deadline = time.monotonic() + timeout
        with self.condition:
            while not cancelled():
                blocked = set(excluded) | self.used() | self.excluded()
                candidates = [e for e in pool if e.casefold() not in blocked]
                if preferred:
                    candidates.sort(key=lambda e: e.casefold() != preferred)
                if not candidates:
                    return None
                for email in candidates:
                    key = email.casefold()
                    if key not in self.owners:
                        self.owners[key] = owner
                        return email
                if time.monotonic() >= deadline:
                    return None
                self.condition.wait(0.2)
        return None

    def release(self, owner, email):
        with self.condition:
            if self.owners.get(email.casefold()) == owner:
                del self.owners[email.casefold()]
                self.condition.notify_all()

    def release_owner(self, owner):
        with self.condition:
            for key in [key for key, value in self.owners.items() if value == owner]:
                del self.owners[key]
            self.condition.notify_all()


class ConcurrentRunner:
    def __init__(self, store, execute, notify=None, can_dispatch=None):
        self.store, self.execute = store, execute
        self.notify = notify or (lambda text: None)
        self.can_dispatch = can_dispatch or (lambda: True)
        self.running = False
        self.capacity = 3
        self.pausing = threading.Event()
        self.stopping = threading.Event()
        self.wake = threading.Event()
        self.thread = None
        self.lock = threading.Lock()

    def start(self, instances, interval=0):
        with self.lock:
            if self.running:
                raise ValueError("Ya hay solicitudes activas.")
            if not instances or not 1 <= self.capacity <= 3:
                raise ValueError("Elige instancias y de 1 a 3 solicitudes simultáneas.")
            self.running = True
            self.stopping.clear()
            self.pausing.clear()
            self.wake.clear()
            self.thread = threading.Thread(
                target=self._work, args=(tuple(instances),), daemon=True
            )
            self.thread.start()

    def pause(self):
        self.pausing.set()
        self.wake.set()

    def stop(self):
        self.stopping.set()
        self.wake.set()

    def _work(self, instances):
        completed = queue.SimpleQueue()
        threads = {}
        deferred = set()
        storage_failed = False

        def work(item):
            try:
                result = self.execute(item)
            except Exception:
                result = RequestResult(
                    "sin_confirmar",
                    reason="Error del trabajador; revisa la instancia antes de repetir.",
                )
            completed.put((item, result))
            self.wake.set()

        try:
            self.store.set_pause("")
            while True:
                try:
                    while True:
                        item, result = completed.get_nowait()
                        threads.pop(item["id"]).join()
                        state = self.store.finish(item, result)
                        self.notify(
                            f"Solicitud {item['id']}: {state} · {result.reason}"
                        )
                        if (
                            result.status in ("sin_correos", "stopped")
                            and state == "pendiente"
                        ):
                            deferred.add(item["id"])
                        if result.status == "limited":
                            self.pausing.set()
                            self.store.set_pause(
                                result.reason
                                or "Microsoft limita solicitudes; cola pausada."
                            )
                except queue.Empty:
                    pass
                if not self.stopping.is_set() and not self.pausing.is_set():
                    while len(threads) < self.capacity:
                        if not self.can_dispatch():
                            break
                        item = self.store.claim(
                            instances, capacity=3, excluded_ids=deferred
                        )
                        if item is None:
                            break
                        thread = threading.Thread(
                            target=work, args=(item,), daemon=True
                        )
                        threads[item["id"]] = thread
                        thread.start()
                if not threads:
                    if self.stopping.is_set():
                        self.store.set_pause(
                            "Detenido por el operador; pendientes conservados."
                        )
                    elif self.pausing.is_set() and not self.store.pause_reason():
                        self.store.set_pause(
                            "Pausa solicitada; pendientes conservados."
                        )
                    elif self.store.counts()["pendiente"]:
                        self.store.set_pause(
                            "No quedan correos disponibles; carga más cuentas y reanuda la cola."
                            if not self.can_dispatch() or deferred
                            else "Hay pendientes; revisa las instancias ocupadas o en revisión."
                        )
                    break
                self.wake.wait(0.15)
                self.wake.clear()
        except Exception:
            storage_failed = True
            self.pausing.set()
            self.notify(
                "No se pudo actualizar la cola. Las solicitudes activas terminarán antes de liberar sus recursos."
            )
        finally:
            # Never declare idle while a browser/IMSS worker still owns resources.
            for thread in threads.values():
                thread.join()
            if storage_failed:
                try:
                    self.store.recover_interrupted()
                    self.store.set_pause(
                        "Error de almacenamiento; revisar los resultados antes de reanudar."
                    )
                except Exception:
                    self.notify(
                        "No se pudo guardar el estado de la cola; conserva el historial para revisión."
                    )
            self.running = False


@dataclass
class LiveJob:
    item: dict
    client: object
    server: object
    browser_thread: object
    preparation_thread: object


class JobEngine:
    def __init__(self, app, notify):
        self.app = app
        self.notify = notify
        self.lock = threading.RLock()
        self.setup_lock = threading.Lock()
        self.contexts = {}
        self.snapshot = {}
        self.leases = EmailLeases(
            lambda: app.usados_sesion.copy(), app.conexion.bridge.excluded_emails
        )
        self.provider_limited = threading.Event()

    def has_mailboxes(self):
        excluded = (
            self.app.usados_sesion.copy()
            | self.app.conexion.bridge.excluded_emails()
            | set(self.snapshot.get("used", ()))
        )
        return not self.provider_limited.is_set() and any(
            a.address.casefold() not in excluded
            for a in self.snapshot.get("accounts", ())
        )

    def cancel(self, item_id=None, skip=False):
        with self.lock:
            contexts = list(self.contexts.items())
        for key, job in contexts:
            if item_id is not None and item_id != key:
                continue
            if skip:
                job.client.skip_current()
            else:
                job.client.user_stop = item_id is not None
                job.client.stop()

    def execute(self, item):
        from outlook_conectado import OutlookWorker

        app = self.app
        owner = item["id"]
        worker = type(app).__new__(type(app))
        worker.__dict__ = app.__dict__.copy()
        worker.root = WorkerRoot()
        worker.nombres = (item["instancia"],)
        worker.console = Value(self.snapshot["path"])
        worker.codigo = Value()
        for name in ("btn_consulta", "btn_codigo", "selector_cantidad"):
            setattr(worker, name, Value())
        worker.pendiente = None
        worker.resultado_tramite = False
        worker.fast_mode = True
        worker.busy = True
        worker.preparando = threading.Event()
        for name in (
            "arranque",
            "enviados",
            "bloqueada",
            "sesion",
            "ultimo_abrir",
            "intentos_pin",
        ):
            setattr(worker, name, dict(getattr(app, name)))
        worker.registrar_correo = app.registrar_correo
        worker.estado = app.estado
        worker.refrescar_correos = lambda: None
        worker.emit = lambda text: app.emit(f"[{owner} · {item['instancia']}] {text}")
        worker.events = SimpleNamespace(
            put=lambda event: (
                self.notify(owner, "detalle", event[1]) if event[0] == "aviso" else None
            )
        )
        foto = worker.foto
        worker.foto = lambda path, idx, name: foto(path, idx, f"{owner}_{name}")
        original_work = worker.work

        def setup(path, **kwargs):
            with self.setup_lock:
                return original_work(path, **kwargs, wait_boot=False)

        worker.work = setup
        c = ImssConnection.__new__(ImssConnection)
        c.app = worker
        c.active = True
        c.cancel = threading.Event()
        c.skip = threading.Event()
        c.job = None
        c.rejected = False
        c.reset_ready = False
        c.stage = "listo"
        c.deadline = None
        c.history = app.conexion.history
        c.history_error = False
        c.batch_mode = True
        c.current_timeout = self.snapshot["timeout"]
        c.current_max_attempts = 3 - item.get("intentos", 0)
        c.attempt_offset = item.get("intentos", 0)
        c.current_preferred_email = (
            "" if item.get("intentos", 0) > 0 else item.get("preferido", "")
        )
        c.current_request_id = item.get("solicitud") or None
        c.recover_previous_code = item.get("motivo", "").startswith(
            "Recuperación del lector:"
        )
        worker.conexion = c
        server = OutlookWorker()
        server.baseline_timeout = self.snapshot.get("baseline_timeout", 10)
        server.shutdown = threading.Event()
        server.job_cancel = threading.Event()
        server.accepting = True
        accounts = self.snapshot["accounts"]
        c.bridge = JobBridge(
            app.conexion.bridge.root / "paralelo" / str(owner),
            app.conexion.bridge,
            accounts,
            server.shutdown,
        )
        # Only requests created in this execution may run after a restart.
        c.bridge.interrupt_previous(client_restarted=True)
        server.bridge = c.bridge
        server.accounts = accounts
        server.account_lookup = {a.address.casefold(): a for a in accounts}
        server._post = lambda callback: callback()
        server.manage_buttons = []
        for name in ("start_button", "skip_button", "stop_button", "status"):
            setattr(server, name, Value())
        server._record_result = app.outlook._record_result
        server._account_status = lambda address, state: self.notify(
            owner, "outlook", f"{address} · {state}"
        )
        done = {}

        def attempt_done(key):
            done.setdefault(key, threading.Event()).set()

        server.on_job_finished = attempt_done

        def claim(pool, excluded, preferred):
            if self.provider_limited.is_set():
                return None
            email = self.leases.claim(owner, pool, excluded, preferred, c.cancel.is_set)
            self.notify(owner, "correo", email or "Esperando un correo disponible")
            return email

        c.claim_email = claim

        def release(email, key):
            if key:
                event = done.setdefault(key, threading.Event())
                # The mailbox stays reserved until its browser really closes.
                while not event.wait(0.2):
                    if not browser_thread.is_alive():
                        break
            self.leases.release(owner, email)

        c.release_email = release
        state = c.state

        def report(stage, text, detail="", timeout=None):
            state(stage, text, detail, timeout)
            self.notify(owner, stage, text + " " + detail)

        c.state = report
        ready = threading.Event()
        prepared = [False]

        def prepare():
            try:
                with accelerated():
                    prepared[0] = worker.preparar_solicitud(
                        self.snapshot["path"],
                        item["instancia"],
                        c.cancel.is_set,
                        c.cancel.wait,
                    )
            finally:
                for name in (
                    "arranque",
                    "enviados",
                    "bloqueada",
                    "sesion",
                    "ultimo_abrir",
                    "intentos_pin",
                ):
                    source = getattr(worker, name)
                    target = getattr(app, name)
                    if item["instancia"] in source:
                        target[item["instancia"]] = source[item["instancia"]]
                ready.set()

        def wait_prepared():
            self.notify(
                owner, "emuladores", "Bandeja lista; esperando la instancia IMSS"
            )
            while not ready.wait(0.15):
                if c.cancel.is_set():
                    return False
            return prepared[0] and not c.cancel.is_set()

        c.preparation = wait_prepared

        def serve():
            while not server.shutdown.wait(0.15):
                for request in server.bridge.pending():
                    if server.shutdown.is_set():
                        break
                    outlook = app.outlook
                    if (
                        outlook.warm_email == request["email"].casefold()
                        and outlook.thread.is_alive()
                    ):
                        event = done.setdefault(request["id"], threading.Event())
                        outlook.commands.put(("connected", (server, request)))
                        while not event.wait(0.15):
                            if not outlook.thread.is_alive():
                                server.bridge.reply(
                                    request["id"],
                                    "stopped",
                                    reason="Se cerró Outlook antes de conectar la bandeja.",
                                )
                                event.set()
                    else:
                        server.process(request)

        browser_thread = threading.Thread(target=serve, daemon=True)
        c.bridge.worker_alive = browser_thread.is_alive
        prep_thread = threading.Thread(target=prepare, daemon=True)
        with self.lock:
            self.contexts[owner] = LiveJob(item, c, server, browser_thread, prep_thread)
        try:
            self.notify(owner, "inicio", f"{item['curp']} · {item['instancia']}")
            if self.snapshot.get("stopping") and self.snapshot["stopping"].is_set():
                c.cancel.set()
            browser_thread.start()
            prep_thread.start()
            with accelerated():
                c.run(
                    self.snapshot["path"],
                    item["curp"],
                    item["instancia"],
                    item["tramite"],
                    "",
                    "",
                )
            result = c.last_result
            if result.status == "detenida" and c.__dict__.get("user_stop"):
                result = replace(
                    result, status="sin_confirmar" if result.submitted else "cancelada"
                )
            if result.status == "limited":
                self.provider_limited.set()
            self.notify(owner, result.status, result.reason)
            return result
        finally:
            c.cancel.set()
            if c.job:
                c.bridge.finish(c.job)
            server.shutdown.set()
            server.job_cancel.set()
            browser_thread.join()
            prep_thread.join()
            self.leases.release_owner(owner)
            with self.lock:
                self.contexts.pop(owner, None)
