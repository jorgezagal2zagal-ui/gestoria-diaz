from pathlib import Path
import sys, tempfile, tkinter as tk, time
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gestoria_5_instancias as bot
import conexion.imss_link as link
import conexion.unified as unified
import outlook_conectado as out
import automation
from conexion.bridge import Bridge
from history import HistoryStore

with tempfile.TemporaryDirectory() as tmp:
    bridge = Bridge(tmp)
    fake_reader = Mock()
    fake_reader.scan.return_value = "870621"
    fake_reader.last_diagnostic = "synthetic"
    fake_special = Mock()
    fake_special.handle.return_value = None
    driver = Mock()
    with (
        patch.object(link, "Bridge", return_value=bridge),
        patch.object(unified, "Bridge", return_value=bridge),
        patch.object(
            unified,
            "HistoryStore",
            return_value=HistoryStore(Path(tmp) / "outlook.csv"),
        ),
        patch.object(bot.App, "monitor", return_value=None),
        patch.object(bot, "CARPETA", Path(tmp)),
        patch.object(bot, "USADOS", Path(tmp) / "used.csv"),
        patch.object(out, "try_account", return_value=driver) as login,
        patch.object(out, "OutlookReader", return_value=fake_reader),
        patch.object(out, "SpecialPages", return_value=fake_special),
        patch.object(automation, "available_browsers", return_value=["chrome"]),
        patch("conexion.navigation.prepare_login", return_value=True),
    ):
        root = tk.Tk()
        app = bot.App(root, outlook_factory=unified.OutlookSection)
        c = app.conexion
        o = app.outlook
        console = Path(tmp) / "ldconsole.exe"
        console.touch()
        app.console.set(str(console))
        app.curp.set("AAAA900101HDFBCD00")
        c.sender.set("sender@provider.test")
        c.subject.set("Código")
        o.email.set("chosen@example.test")
        o.password.set("synthetic")
        o.add_or_use()
        assert c.preferred_email.get() == "chosen@example.test"
        assert o.password.get() == ""
        assert len(o.accounts) == 1
        assert bridge.presence()["emails"] == ["chosen@example.test"]
        seen = []

        def consult(path, person, email, instance, procedure):
            assert bridge.response(c.job)["status"] in ("ready", "code")
            seen.append(email)
            app.pendiente = (path, "1", instance, person, email, procedure)
            app.usados_sesion.add(email)

        def code(value, *pending):
            assert value == "870621"
            assert pending[4] == "chosen@example.test"
            app.pendiente = None
            app.resultado_tramite = True

        app._consulta = Mock(side_effect=consult)
        app._codigo = Mock(side_effect=code)
        start = time.monotonic()
        errors = []
        finished = [False]

        def check():
            try:
                if not c.active and c.__dict__.get("last_result"):
                    assert c.last_result.status == "completada"
                    assert seen == ["chosen@example.test"]
                    assert "chosen@example.test" in o.active_email.get()
                    assert not [
                        w for w in root.winfo_children() if isinstance(w, tk.Toplevel)
                    ]
                    finished[0] = True
                    c.close_window()
                    return
                if time.monotonic() - start > 12:
                    raise AssertionError("Tiempo agotado")
            except Exception as exc:
                errors.append(str(exc))
                c.close_window()
                return
            root.after(50, check)

        root.after(10, app.consulta)
        root.after(100, check)
        root.mainloop()
        assert not errors, errors
        assert finished[0]
        assert login.call_args.args[0].address == "chosen@example.test"
        driver.quit.assert_called_once()
        assert not o.thread.is_alive()
        c.lock.release()
        o.process_lock.release()
print(
    "PANEL UNICO: correo escrito una vez, bandeja antes de IMSS, codigo correlacionado, tramite confirmado y cierre del navegador OK"
)
