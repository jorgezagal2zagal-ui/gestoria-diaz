"""Real Tk, simulated ADB/Outlook: automatic, manual and failed-mail scenarios."""
from pathlib import Path
import sys
import tempfile
import time
import tkinter as tk
from unittest.mock import patch

from bot_imss_adb import app as gui
from bot_imss_adb.adb import Device
from bot_imss_adb.tests.fakes import FakeAdb, FakeMailbox


def main():
    trace, devices, errors = [], [], []
    mode = "manual" if "--manual" in sys.argv else "mail-fails" if "--mail-fails" in sys.argv else "auto"

    class Adb(FakeAdb):
        def __init__(self, executable, serial="", cancelled=None):
            super().__init__(trace=trace)
            self.executable, self.serial, self.cancelled = executable, serial, cancelled
            devices.append(self)

        def devices(self):
            return [Device("emulator-5554", "device", "Synthetic Android"), Device("emulator-5556", "offline")]

    def mailbox(*args):
        return FakeMailbox(trace, fail=(mode == "mail-fails"))

    with tempfile.TemporaryDirectory() as folder, patch.object(gui, "Adb", Adb), patch.object(gui, "OutlookMailbox", side_effect=mailbox):
        root = tk.Tk()
        app = gui.App(root, Path(folder))
        started = time.monotonic()
        phase = 0

        def exception(_type, error, _trace):
            errors.append(str(error))
            app.close()

        root.report_callback_exception = exception
        app.adb_path.set("synthetic/adb.exe")
        app.curp.set("AAAA900101HDFBCD00")
        app.email.set("synthetic@example.test")
        app.password.set("SYNTHETIC_PASSWORD")
        if mode == "manual":
            app.mode.set("Código manual")
        app.detect()

        def tick():
            nonlocal phase
            if time.monotonic() - started > 18:
                errors.append("GUI timeout, " + app.status.get())
                app.close()
                return
            if phase == 0 and app.device.get() and not app.worker.is_alive():
                assert "emulator-5554" in app.device.get()
                app.start()
                phase = 1
            elif phase == 1:
                if mode == "manual" and app.waiting_code:
                    app.code.set("001177")
                    app.send_code()
                if app.worker and not app.worker.is_alive():
                    try:
                        rows = app.history.recent()
                        assert len(rows) == 1, rows
                        assert app.password.get() == ""
                        if mode == "mail-fails":
                            assert rows[0][4] == "revision", rows
                            assert "imss-login" not in trace
                        else:
                            assert rows[0][4] == "completada", rows
                            client = devices[-1]
                            assert client.serial == "emulator-5554"
                            assert client.sent == ["nss", "vigencia", "semanas"]
                            assert client.verify_taps == 1
                            assert client.state == "login"
                            if mode != "manual":
                                assert trace.index("mail-ready") < trace.index("imss-login")
                    except Exception as error:
                        errors.append(repr(error))
                    root.after(100, app.close)
                    return
            root.after(30, tick)

        root.after(30, tick)
        root.mainloop()
        assert not errors, errors
        print("GUI PASS:", mode, "real Tk, simulated services")


if __name__ == "__main__":
    main()
