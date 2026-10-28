"""Real Tk import/use/omit/export, stored password reuse and separate Outlook/IMSS results."""
from pathlib import Path
import sys
import tempfile
import time
import tkinter as tk
from unittest.mock import patch

from bot_imss_adb import app as gui
from bot_imss_adb.accounts_ui import EXPORTS
from bot_imss_adb.mail_service import OutlookMailbox
from bot_imss_adb.storage import MAIL_GROUPS
from bot_imss_adb.tests.fakes import FakeAdb


def main():
    errors, credentials = [], []
    fail = "--imss-fails" in sys.argv

    class Adb(FakeAdb):
        def __init__(self, executable, serial="", cancelled=None):
            super().__init__(fail="code" if fail else None)
            self.executable, self.serial, self.cancelled = executable, serial, cancelled

    class Driver:
        def quit(self):
            pass

    class Reader:
        def __init__(self, *args, **kwargs):
            pass

        def baseline(self):
            pass

        def scan(self, started):
            return "001177"

    def login(account, *args):
        credentials.append((account.address, account.password))
        return Driver()

    def mail(password, cancelled):
        return OutlookMailbox(password, cancelled, login=login, reader_factory=Reader)

    with tempfile.TemporaryDirectory() as folder, patch.object(gui, "Adb", Adb), patch.object(gui, "OutlookMailbox", side_effect=mail), patch("bot_imss_adb.mail_service.automation.available_browsers", return_value=["chrome"]):
        folder = Path(folder)
        source = folder / "cuentas.txt"
        source.write_text("a0@example.test:SECRET_0\na1@example.test:SECRET_1\n")
        root = tk.Tk()
        app = gui.App(root, folder)
        panel = app.accounts_panel
        app.adb_path.set("synthetic/adb.exe")
        app.device_map = {"Synthetic": "emulator-5554"}
        app.device.set("Synthetic")
        app.curp.set("AAAA900101HDFBCD00")
        assert panel.import_file(source) == 2
        assert app.email.get() == "a0@example.test"
        table = panel.tables["Cargados"]
        table.selection_set(table.get_children()[0])
        panel.omit()
        assert app.email.get() == "a1@example.test"
        assert app.password.get() == ""
        assert len(app.history.mail_groups()[MAIL_GROUPS[2]]) == 1
        started = time.monotonic()
        app.start()

        def exception(_kind, value, _trace):
            errors.append(str(value))
            app.close()

        root.report_callback_exception = exception

        def tick():
            if time.monotonic() - started > 15:
                errors.append("Timed out: " + app.status.get())
                app.close()
                return
            if app.worker and not app.worker.is_alive():
                try:
                    panel.refresh()
                    groups = app.history.mail_groups()
                    assert [len(groups[g]) for g in MAIL_GROUPS] == [1, 0, 1], groups
                    assert credentials == [("a1@example.test", "SECRET_1")]
                    assert app.history.recent()[0][4] == ("revision" if fail else "completada")
                    txt = folder / "entraron.txt"
                    assert panel.export_to(txt, EXPORTS[0], MAIL_GROUPS[0]) == 1
                    assert txt.read_text() == "a1@example.test\n"
                    all_txt = folder / "cargados.txt"
                    assert panel.export_to(all_txt, EXPORTS[1]) == 2
                    assert "SECRET" not in all_txt.read_text()
                    panel.export_to(folder / "correos.csv", EXPORTS[2])
                    panel.export_to(folder / "solicitudes.csv", EXPORTS[3])
                    assert "SECRET" not in (folder / "correos.csv").read_text()
                except Exception as error:
                    errors.append(repr(error))
                root.after(100, app.close)
                return
            root.after(30, tick)

        root.after(30, tick)
        root.mainloop()
        assert not errors, errors
        print("GUI accounts PASS:", "IMSS failure kept separate" if fail else "complete request", "import, skip, next, saved RAM credentials, TXT/CSV export")


if __name__ == "__main__":
    main()
