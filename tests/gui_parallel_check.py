"""Real Tk: enqueue three CURPs, reuse a pre-opened mailbox, isolated handoffs."""

from pathlib import Path
import sys
import tempfile
import threading
import time
import tkinter as tk
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gestoria_5_instancias as imss
import conexion.imss_link as link
import conexion.unified as unified
import outlook_conectado as out
from conexion.bridge import Bridge
from conexion.parallel_ui import ParallelPanel, AUTO_INSTANCE
from history import HistoryStore


class Driver:
    def __init__(self, email):
        self.address = email
        self.owner = threading.get_ident()
        self.closed = False
        self.refreshes = 0
        self.current_url = "https://outlook.live.com/mail/0/inbox"

    def set_page_load_timeout(self, timeout):
        assert self.owner == threading.get_ident()

    def set_script_timeout(self, timeout):
        assert self.owner == threading.get_ident()

    def quit(self):
        assert self.owner == threading.get_ident()
        self.closed = True

    def refresh(self):
        assert self.owner == threading.get_ident()
        self.refreshes += 1


with tempfile.TemporaryDirectory() as tmp:
    bridge = Bridge(tmp)
    drivers = []
    codes = []
    errors = []
    passed = [False]
    baseline = threading.Barrier(3)

    def login(account, *args):
        if "--first-fails" in sys.argv and account.address == "a0@example.test":
            raise RuntimeError("Synthetic first login failure")
        driver = Driver(account.address)
        drivers.append(driver)
        return driver

    class Reader:
        last_diagnostic = "synthetic"

        def __init__(self, driver, *args, **kwargs):
            self.driver = driver

        def baseline(self):
            if "--reader-fails" in sys.argv:
                if self.driver.address == "a0@example.test":
                    raise RuntimeError(
                        "No se pudo reconocer la lista de mensajes; IMSS no se iniciará."
                    )
                return
            baseline.wait(4)

        def scan(self, at):
            assert self.driver.owner == threading.get_ident()
            return f"{100000 + int(self.driver.address[1]):06d}"

    def consult(worker, path, curp, email, instance, procedure):
        assert worker.conexion.bridge.response(worker.conexion.job)["status"] in (
            "ready",
            "code",
        )
        worker.pendiente = (path, "1", instance, curp, email, procedure)
        worker.registrar_correo(curp, email, instance, procedure)

    def enter(worker, code, *pending):
        assert code == f"{100000 + int(pending[4][1]):06d}"
        codes.append((pending[3], pending[4], pending[2], code))
        worker.pendiente = None
        worker.resultado_tramite = True

    special = SimpleNamespace(handle=lambda: None)
    with (
        patch.object(link, "Bridge", return_value=bridge),
        patch.object(unified, "Bridge", return_value=bridge),
        patch.object(
            unified,
            "HistoryStore",
            return_value=HistoryStore(Path(tmp) / "outlook.csv"),
        ),
        patch.object(imss, "CARPETA", Path(tmp)),
        patch.object(imss, "USADOS", Path(tmp) / "used.csv"),
        patch.object(imss.App, "monitor", return_value=None),
        patch.object(imss.App, "preparar_solicitud", return_value=True),
        patch.object(imss.App, "_consulta", consult),
        patch.object(imss.App, "_codigo", enter),
        patch.object(out, "try_account", side_effect=login),
        patch.object(out, "OutlookReader", Reader),
        patch.object(out, "SpecialPages", return_value=special),
        patch("automation.available_browsers", return_value=["edge"]),
        patch("conexion.navigation.prepare_login", return_value=True),
    ):
        root = tk.Tk()
        app = imss.App(root, outlook_factory=unified.OutlookSection)
        panel = ParallelPanel(app)
        if "--reader-fails" in sys.argv:
            execute = panel.runner.execute

            def fast_baseline(item):
                panel.engine.snapshot["baseline_timeout"] = 0.01
                return execute(item)

            panel.runner.execute = fast_baseline
        app.outlook.accounts = [
            SimpleNamespace(address=f"a{i}@example.test", password="synthetic")
            for i in range(
                4 if "--first-fails" in sys.argv or "--reader-fails" in sys.argv else 3
            )
        ]
        app.outlook.publish()
        app.outlook.email.set("a0@example.test")
        console = Path(tmp) / "ldconsole.exe"
        console.touch()
        app.console.set(str(console))
        start = time.monotonic()

        def callback_error(kind, value, tb):
            errors.append(str(value))
            app.conexion.close_window()

        root.report_callback_exception = callback_error

        def submit():
            if app.outlook.warm_driver is None or app.outlook.mailbox_opening.is_set():
                if time.monotonic() - start > 5:
                    errors.append("No abrió Outlook independiente")
                    app.conexion.close_window()
                    return
                root.after(30, submit)
                return
            assert app.inst_sel.get() == AUTO_INSTANCE
            for prefix in ("AAAA", "BAAA", "CAAA"):
                app.curp.set(prefix + "900101HDFBCD00")
                app.consulta()
            root.after(50, check)

        def check():
            try:
                counts = panel.store.counts()
                if not panel.runner.running and counts["completada"] == 3:
                    assert len(codes) == 3
                    assert len({v[1] for v in codes}) == 3
                    assert len({v[2] for v in codes}) == 3
                    assert len(drivers) == (4 if "--reader-fails" in sys.argv else 3), (
                        "No reutilizó la bandeja preabierta"
                    )
                    assert all(d.closed for d in drivers)
                    assert (
                        app.outlook_panel.winfo_ismapped()
                        and app.imss_panel.winfo_ismapped()
                    )
                    assert panel.table.winfo_ismapped()
                    assert not [
                        w for w in root.winfo_children() if isinstance(w, tk.Toplevel)
                    ]
                    if "--screenshot" in sys.argv:
                        from PIL import ImageGrab

                        root.update_idletasks()
                        ImageGrab.grab().save("/workspace/.cloud-setup/v6-panel.png")
                    passed[0] = True
                    app.conexion.close_window()
                    return
                if time.monotonic() - start > 15:
                    raise AssertionError(f"Tiempo agotado: {counts}, {codes}")
            except Exception as error:
                errors.append(str(error))
                app.conexion.close_window()
                return
            root.after(50, check)

        root.after(10, app.outlook.open_mailbox)
        root.after(50, submit)
        root.mainloop()
        app.conexion.lock.release()
        app.outlook.process_lock.release()
    assert not errors, errors
    assert passed[0]
print(
    "V6 TK: 3 solicitudes simultáneas, bandeja reutilizada sin cruzar hilos, correos/códigos/instancias separados OK"
)
