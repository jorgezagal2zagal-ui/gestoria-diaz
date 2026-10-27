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

independent = '--independent' in sys.argv
instances = {f'GESTORIA_DIAZ_00{i}': {'index':str(i),'real':f'GESTORIA_DIAZ_00{i}',
    'running':False,'android':False,'pid':'0'} for i in range(1,6)}
launched = []
def ldplayer(path,*args,**kwargs):
    if args[0]=='launch':
        launched.append(args[2])
        next(v for v in instances.values() if v['index']==args[2]).update(
            running=True,android=True,pid='100')
    return ''

with tempfile.TemporaryDirectory() as tmp:
    bridge = Bridge(tmp)
    fake_reader = Mock()
    fake_reader.scan.return_value = "870621"
    fake_reader.last_diagnostic = "synthetic"
    fake_special = Mock()
    fake_special.handle.return_value = None
    driver = Mock()
    driver.current_url = 'https://outlook.live.com/mail/0/inbox'
    with (
        patch.object(link, "Bridge", return_value=bridge),
        patch.object(unified, "Bridge", return_value=bridge),
        patch.object(
            unified,
            "HistoryStore",
            return_value=HistoryStore(Path(tmp) / "outlook.csv"),
        ),
        patch.object(bot.App, "monitor", return_value=None),
        patch.object(bot, 'listar', side_effect=lambda path:dict(instances)),
        patch.object(bot, 'reparar', side_effect=lambda *a:dict(instances)),
        patch.object(bot, 'run', side_effect=ldplayer),
        patch.object(bot, 'celular'),
        patch.object(bot, 'adb', return_value='mKeyguardShowing=false'),
        patch.object(bot, 'abrir_app'),
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
        if not independent:
            app.curp.set("AAAA900101HDFBCD00")
        assert c.sender.get() == "" and c.subject.get() == ""
        o.email.set("chosen@example.test")
        o.password.set("synthetic")
        assert not o.accounts
        seen = []

        def consult(path, person, email, instance, procedure):
            assert bridge.response(c.job)["status"] in ("ready", "code")
            assert c.preferred_email.get() == "chosen@example.test"
            assert o.password.get() == ""
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
                    assert not o.start_button.winfo_ismapped()
                    assert app.outlook_panel.winfo_ismapped()
                    assert app.imss_panel.winfo_ismapped()
                    assert app.btn.winfo_ismapped()
                    assert o.open_button.winfo_ismapped()
                    assert list(app.tabs_unificados.tab(i,'text') for i in range(3)) == ['Outlook + IMSS','Registro','Lotes']
                    assert launched == ['1','2','3'], launched
                    assert login.call_count == 1
                    if '--screenshot' in sys.argv:
                        from PIL import ImageGrab
                        root.update_idletasks()
                        ImageGrab.grab().save('/workspace/.cloud-setup/v5-panel.png')
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

        def start_independent():
            assert not app.curp.get()
            o.open_mailbox()
            app.start()
            def continue_when_ready():
                if o.warm_driver is not None and not app.busy and not o.mailbox_opening.is_set():
                    assert not c.active
                    assert launched == ['1','2','3']
                    app.curp.set('AAAA900101HDFBCD00')
                    app.consulta()
                elif time.monotonic()-start<10:
                    root.after(50,continue_when_ready)
            root.after(50,continue_when_ready)
        root.after(10, start_independent if independent else app.consulta)
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
    "V5: dos bots visibles, apertura independiente y flujo sincronizado, arranque de 3 instancias y misma bandeja OK"
)
