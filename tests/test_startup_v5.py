"""Startup regressions: real orchestration, synthetic LDPlayer and mailbox only."""
import json
from pathlib import Path
import queue
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import gestoria_5_instancias as bot
from conexion.unified import OutlookSection
from test_instance_count import application, instance
import test_connected_bots as connected_tests


class EmulatorStartupTests(unittest.TestCase):
    def app(self, count=1):
        # Use the real class whose module contains the patched LDPlayer functions.
        app = bot.App.__new__(bot.App)
        app.__dict__.update(application(count).__dict__)
        app.preparando = threading.Event()
        app.intentos_pin = {}
        app.sesion = {}
        app.bloqueada = {}
        app.abrir_imss = Mock()
        return app

    def test_automatic_start_launches_only_selected_instances_before_imss(self):
        for count in (1, 3, 5):
            with self.subTest(count=count):
                app = self.app(count)
                data = {n: instance(i, False) for i,n in enumerate(bot.TODOS_NOMBRES,1)}
                def command(console, *args, **kwargs):
                    if args[0] == 'launch':
                        next(v for v in data.values() if v['index'] == args[2]).update(running=True, android=True)
                    return ''
                with patch.object(bot,'listar',side_effect=lambda p: dict(data)), \
                     patch.object(bot,'reparar',side_effect=lambda *a: dict(data)), \
                     patch.object(bot,'run',side_effect=command) as run, \
                     patch.object(bot,'celular'), \
                     patch.object(bot,'adb',return_value='mKeyguardShowing=false'):
                    self.assertTrue(app.preparar_solicitud('console',app.nombres[0],lambda:False,lambda s:False))
                self.assertEqual([c.args[3] for c in run.call_args_list if c.args[1]=='launch'],
                                 [str(i) for i in range(1,count+1)])
                app.abrir_imss.assert_called_once()
                self.assertTrue(app.iniciado)
                self.assertFalse(app.preparando.is_set())
                self.assertFalse(any(e[0]=='done' for e in list(app.events.queue)))

    def test_locked_android_is_confirmed_before_imss_opens(self):
        for unlock in (True,False):
            with self.subTest(unlock=unlock):
                app=self.app()
                with patch.object(bot,'listar',return_value={app.nombres[0]:instance(1)}), \
                     patch.object(bot,'adb',return_value='mKeyguardShowing=true'), \
                     patch.object(bot,'desbloquear_android',return_value=unlock) as pin:
                    self.assertEqual(app.preparar_solicitud('console',app.nombres[0],lambda:False,lambda s:False),unlock)
                pin.assert_called_once_with('console','1',bot.PIN_EMULADOR)
                self.assertEqual(app.abrir_imss.call_count, int(unlock))

    def test_failed_pin_is_not_repeated_for_the_same_android_session(self):
        app=self.app()
        with patch.object(bot,'listar',return_value={app.nombres[0]:instance(1)}), \
             patch.object(bot,'adb',return_value='mKeyguardShowing=true'), \
             patch.object(bot,'desbloquear_android',return_value=False) as pin:
            for _ in range(2):
                self.assertFalse(app.preparar_solicitud('console',app.nombres[0],lambda:False,lambda s:False))
        self.assertEqual(pin.call_count,1)

    def test_cancelled_start_never_opens_imss(self):
        app=self.app()
        with patch.object(bot,'listar',return_value={app.nombres[0]:instance(1)}):
            self.assertFalse(app.preparar_solicitud('console',app.nombres[0],lambda:True,lambda s:True))
        app.abrir_imss.assert_not_called()
        self.assertFalse(app.preparando.is_set())

    def test_saved_installation_is_recovered_and_missing_route_is_reported(self):
        app=self.app()
        del app.ruta
        app.console=Mock()
        with tempfile.TemporaryDirectory() as tmp, patch.object(bot,'CARPETA',Path(tmp)):
            exe=Path(tmp)/'LDPlayer9'/'ldconsole.exe'
            exe.parent.mkdir(); exe.touch()
            app.console.get.return_value=str(exe)
            self.assertEqual(app.ruta(),str(exe))
            self.assertEqual(bot.ruta_ldplayer(),str(exe))
            self.assertEqual(json.loads((Path(tmp)/'ldplayer.json').read_text())['console'],str(exe))
            exe.unlink()
            self.assertEqual(bot.ruta_ldplayer(),bot.DEFAULT)
        app.ruta=Mock(return_value=None)
        app.curp=Mock()
        with patch.object(bot.messagebox,'showerror') as error:
            app.consulta()
        error.assert_called_once()

    def test_missing_emulator_never_consumes_an_email_or_starts_outlook(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture=connected_tests.WorkflowTests()
            app,c=fixture.workflow(tmp)
            c.app.unified_mode=True
            c.app.preparar_solicitud=Mock(return_value=False)
            c.app._consulta.reset_mock()
            c.bridge.create=Mock(wraps=c.bridge.create)
            c.run('console','CURP','INSTANCE','procedure','','')
            self.assertEqual(c.last_result.status,'emulador_no_listo')
            self.assertEqual(c.last_result.attempts,0)
            c.app._consulta.assert_not_called()
            c.bridge.create.assert_not_called()
            self.assertEqual(c.bridge.pending(),[])


class IndependentOutlookTests(unittest.TestCase):
    def section(self):
        o=OutlookSection.__new__(OutlookSection)
        o.warm_driver=None; o.warm_email=None
        o.shutdown=threading.Event(); o.job_cancel=threading.Event()
        o.mailbox_opening=threading.Event()
        o.bridge=Mock(); o._record_result=Mock(); o._post=lambda cb:cb()
        o._account_status=Mock(); o.status=Mock(); o.accepting=True
        return o

    def test_independent_mailbox_is_reused_by_the_matching_imss_request(self):
        o=self.section()
        account=SimpleNamespace(address='a@example.test',password='synthetic')
        driver=Mock();driver.current_url='https://outlook.live.com/mail/0/inbox'
        with patch('automation.available_browsers',return_value=['chrome']), \
             patch('outlook_conectado.try_account',return_value=driver) as login:
            o.prepare_mailbox(account)
            self.assertIs(o.open_account(account,['chrome'],lambda:False,Mock()),driver)
        login.assert_called_once()
        self.assertIsNone(o.warm_driver)
        driver.quit.assert_not_called()

    def test_switching_accounts_or_closed_browser_cannot_reuse_another_mailbox(self):
        for address,url in [('b@example.test','https://outlook.live.com/mail/0/inbox'),
                            ('a@example.test','https://login.live.com/')]:
            o=self.section()
            old=Mock();old.current_url=url
            o.warm_driver=old;o.warm_email='a@example.test'
            fresh=Mock()
            with patch('outlook_conectado.try_account',return_value=fresh) as login:
                self.assertIs(o.open_account(SimpleNamespace(address=address),['chrome'],lambda:False,Mock()),fresh)
            old.quit.assert_called_once();login.assert_called_once()

    def test_outlook_closes_without_stopping_idle_imss_instances(self):
        o=self.section();o.commands=queue.SimpleQueue()
        o.connection=SimpleNamespace(active=False,stop=Mock())
        o.stop_mailbox()
        o.connection.stop.assert_not_called()
        self.assertEqual(o.commands.get_nowait(),('close',None))
        self.assertTrue(o.job_cancel.is_set())


if __name__=='__main__':
    unittest.main()
