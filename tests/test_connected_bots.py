import importlib.util
import json
from pathlib import Path
import queue
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace

from conexion.bridge import Bridge, read_json, write_json
from conexion.imss_link import ImssConnection
from conexion.history import RequestHistory
from conexion.reader import OutlookReader, ROW, PANE, extract_code

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('connected_imss_test', ROOT/'gestoria_5_instancias.py')
bot = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = bot
spec.loader.exec_module(bot)


class BridgeTests(unittest.TestCase):
    def test_requests_are_unique_correlated_private_and_expire(self):
        with tempfile.TemporaryDirectory() as folder:
            bridge = Bridge(folder)
            bridge.publish(['synthetic@example.test'], True)
            self.assertTrue(bridge.presence())
            key = bridge.create('synthetic@example.test','INSTANCE','sender@provider.test','Código de validación')
            self.assertEqual(len(bridge.pending()),1)
            request = read_json(bridge.job(key)/'request.json')
            self.assertNotIn('password',request)
            bridge.reply(key,'ready')
            self.assertEqual(bridge.response(key)['email'],request['email'])
            self.assertEqual(bridge.pending(),[])
            bridge.started(key)
            bridge.reply(key,'code',code='870621')
            bridge.finish(key)
            self.assertFalse((bridge.job(key)/'response.json').exists())
            bridge.reply(key,'code',code='765432')
            self.assertFalse((bridge.job(key)/'response.json').exists())
            bridge.pending()
            self.assertFalse(bridge.job(key).exists())
            bridge.finish(key)
            self.assertFalse(bridge.job(key).exists())

    def test_rejects_unsafe_paths_invalid_sender_and_stale_presence(self):
        with tempfile.TemporaryDirectory() as folder:
            bridge = Bridge(folder)
            with self.assertRaises(ValueError): bridge.job('../../outside')
            with self.assertRaises(ValueError): bridge.create('a@example.test','i','','subject')
            write_json(bridge.root/'outlook.json',{'at':time.time()-60,'active':True})
            self.assertIsNone(bridge.presence())


class Row:
    def __init__(self, key, text): self.key,self.text=key,text
    def is_displayed(self): return True
    def get_attribute(self,name): return self.key if name=='data-item-id' else None
    def click(self): pass
    def find_elements(self,by,selector): return []


class Pane(Row):
    def __init__(self,key,text,sender): super().__init__(key,text);self.sender=sender
    def find_elements(self,by,selector):
        if selector=='[email], [data-email-address]':
            node=Mock();node.get_attribute.side_effect=lambda attr:self.sender if attr=='email' else None
            return [node]
        return []


class ReaderTests(unittest.TestCase):
    def test_loading_another_message_cannot_discard_the_requested_message(self):
        reader,rows,panes=self.setup_reader()
        rows.append(Row('new','Código de validación'))
        panes[:]=[Pane('previous','Código de validación: 123456','wrong@provider.test')]
        with patch('conexion.reader.time.sleep'):
            self.assertIsNone(reader.scan(time.time()))
            panes[:]=[Pane('new','Código de validación: 870621','sender@provider.test')]
            self.assertEqual(reader.scan(time.time()),'870621')

    def test_extracts_exact_code_with_context_and_rejects_ambiguous_or_unrelated_numbers(self):
        self.assertEqual(extract_code('Tu código de validación es: 870621'),'870621')
        self.assertIsNone(extract_code('CURP DEMO920101... Telefono 5512345678'))
        self.assertIsNone(extract_code('Código: 870621. Código: 765432'))
        self.assertIsNone(extract_code('Código: 1234567'))

    def setup_reader(self):
        driver=Mock();driver.current_url='https://outlook.live.com/mail/0/inbox'
        rows=[Row('old','Código de validación anterior')]
        panes=[]
        driver.find_elements.side_effect=lambda by,selector: rows if selector==ROW else panes if selector==PANE else []
        reader=OutlookReader(driver,'sender@provider.test','Código de validación')
        reader.baseline()
        return reader,rows,panes

    def test_ignores_old_mail_and_returns_only_new_verified_sender(self):
        reader,rows,panes=self.setup_reader()
        panes.append(Pane('old','Código de validación: 123456','sender@provider.test'))
        self.assertIsNone(reader.scan(time.time()))
        rows.append(Row('new','Nuevo Código de validación'))
        panes[:]=[Pane('new','Código de validación: 870621','sender@provider.test')]
        with patch('conexion.reader.time.sleep'):
            self.assertEqual(reader.scan(time.time()),'870621')

    def test_wrong_sender_or_stale_pane_cannot_deliver_code(self):
        reader,rows,panes=self.setup_reader()
        rows.append(Row('new','Código de validación'))
        panes[:]=[Pane('other','Código de validación: 870621','sender@provider.test')]
        with patch('conexion.reader.time.sleep'):
            self.assertIsNone(reader.scan(time.time()))
            panes[0].key='new'
            self.assertEqual(reader.scan(time.time()),'870621')
        reader,rows,panes=self.setup_reader()
        rows.append(Row('new','Código de validación'))
        panes[:]=[Pane('new','Código de validación: 870621','wrong@provider.test')]
        with patch('conexion.reader.time.sleep'):
            self.assertIsNone(reader.scan(time.time()))


class WorkflowTests(unittest.TestCase):
    def test_closing_imss_cancels_the_active_reader_job(self):
        connection=ImssConnection.__new__(ImssConnection)
        connection.cancel=threading.Event();connection.bridge=Mock();connection.job='job'
        connection.app=SimpleNamespace(root=Mock())
        connection.close_window()
        self.assertTrue(connection.cancel.is_set())
        connection.bridge.finish.assert_called_once_with('job')
        connection.app.root.destroy.assert_called_once()

    def test_connected_mode_recognizes_other_explicit_code_validation_failures(self):
        connection=ImssConnection.__new__(ImssConnection)
        for text in ('Código incorrecto','El código no es válido','Código expirado','Error al validar el código'):
            with self.subTest(text=text):
                self.assertTrue(connection.is_validation_error([{'texto':text,'area':2000,'visible':True}]))
        self.assertFalse(connection.is_validation_error([{'texto':'Error de ubicación','area':2000}]))
        self.assertFalse(connection.is_validation_error([{'texto':'Código incorrecto','area':2000,'visible':False}]))

    def test_actual_local_bridge_connects_both_workers_and_rotates_three_accounts(self):
        import outlook_conectado as outlook
        import automation
        class FastEvent(threading.Event):
            def wait(self, timeout=None): return super().wait(min(timeout or .01, .01))
        with tempfile.TemporaryDirectory() as folder:
            bridge=Bridge(folder)
            server=outlook.ConnectedOutlook.__new__(outlook.ConnectedOutlook)
            server.bridge=bridge;server.accepting=True
            server.shutdown=FastEvent();server.job_cancel=FastEvent()
            server.accounts=[SimpleNamespace(address=f'example{i}@example.test',password='synthetic') for i in range(3)]
            server._post=lambda callback:callback()
            server._account_status=Mock();server._record_result=Mock()
            server.manage_buttons=[];server.start_button=Mock();server.stop_button=Mock();server.skip_button=Mock();server.status=Mock()
            app=bot.App.__new__(bot.App)
            app.emit=Mock();app.events=queue.Queue();app.root=Mock();app.root.after.side_effect=lambda delay,callback:callback()
            app.btn_consulta=Mock();app.btn_codigo=Mock();app.selector_cantidad=Mock();app.codigo=Mock()
            app.usados_sesion=set();app.pendiente=None;app.resultado_tramite=False
            client=ImssConnection.__new__(ImssConnection)
            client.app=app;client.bridge=bridge;client.active=True;client.cancel=FastEvent();client.job=None;client.rejected=False;client.reset_ready=False
            client.history=RequestHistory(folder)
            def lookup(path,curp,email,instance,procedure):
                self.assertIn(bridge.response(client.job)['status'],('ready','code'))
                app.pendiente=(path,'1',instance,curp,email,procedure)
                app.usados_sesion.add(email)
            app._consulta=Mock(side_effect=lookup)
            def validate(*args):
                app.pendiente=None
                if app._codigo.call_count < 3:
                    client.rejected=True;client.reset_ready=True
                else:
                    app.resultado_tramite=True
            app._codigo=Mock(side_effect=validate)
            fake_reader=Mock();fake_reader.scan.return_value='870621'
            fake_special=Mock();fake_special.handle.return_value=None
            drivers=[]
            def login(*args):
                driver=Mock();drivers.append(driver);return driver
            def heartbeat():
                while not server.shutdown.wait(.01): bridge.publish([a.address for a in server.accounts],True)
            bridge.publish([a.address for a in server.accounts],True)
            with patch.object(outlook,'OutlookReader',return_value=fake_reader),patch.object(outlook,'SpecialPages',return_value=fake_special),patch.object(outlook,'try_account',side_effect=login) as login_call,patch.object(automation,'available_browsers',return_value=['chrome','edge']),patch.object(bot,'correos_usados',return_value=set()):
                worker=threading.Thread(target=server.listen);pulse=threading.Thread(target=heartbeat)
                worker.start();pulse.start()
                try:
                    client.run('console','SYNTHETIC-CURP','INSTANCE','procedure','sender@provider.test','Código')
                finally:
                    server.shutdown.set();server.job_cancel.set();worker.join(3);pulse.join(3)
            self.assertFalse(worker.is_alive())
            self.assertEqual(login_call.call_count,3)
            self.assertEqual(app._consulta.call_count,3)
            self.assertEqual(app._codigo.call_count,3)
            self.assertTrue(app.resultado_tramite)
            self.assertEqual(fake_reader.baseline.call_count,3)
            for driver in drivers: driver.quit.assert_called_once()
            self.assertEqual(list(Path(folder).glob('solicitudes/*/response.json')),[])
            self.assertEqual(sorted(r['resultado'] for r in client.history.rows()),['completada','rechazado','rechazado'])

    def test_navigation_acknowledges_error_then_cancels_only_the_code_screen(self):
        app=bot.App.__new__(bot.App)
        connection=ImssConnection.__new__(ImssConnection)
        connection.app=app;connection.cancel=threading.Event()
        def node(text='',rid='',xy=(10,10)):
            return {'texto':text,'valor':text,'rid':rid,'xy':xy,'area':2000,'enabled':True,'visible':True,'clase':'android.widget.TextView'}
        error=[node('Error al validar el código'),node('ACEPTAR',xy=(10,20))]
        code=[node('Código de validación'),node('Cancelar',xy=(30,40))]
        login=[node(rid='example:id/txtCURP'),node(rid='example:id/txtCorreo')]
        with patch.object(bot,'pantalla',side_effect=[code,login]),patch.object(bot,'tocar') as touch,patch.object(connection.cancel,'wait'):
            self.assertTrue(connection.return_to_login('console','1',error))
        self.assertEqual([call.args[2] for call in touch.call_args_list],[(10,20),(30,40)])

    def workflow(self, folder, reject=True, ready_status='ready', stale=False):
        app=bot.App.__new__(bot.App)
        app.emit=Mock();app.events=queue.Queue();app.root=Mock()
        app.root.after.side_effect=lambda delay,callback:callback()
        app.btn_consulta=Mock();app.btn_codigo=Mock();app.selector_cantidad=Mock();app.codigo=Mock()
        app.usados_sesion=set();app.pendiente=None;app.resultado_tramite=False
        connection=ImssConnection.__new__(ImssConnection)
        connection.app=app;connection.bridge=Bridge(folder);connection.active=True
        connection.history=RequestHistory(folder)
        connection.cancel=threading.Event();connection.job=None
        connection.rejected=False;connection.reset_ready=False
        emails=[f'example{i}@example.test' for i in range(5)]
        connection.bridge.publish(emails,True)
        ready_count=[]
        def response(key,email,instance,statuses,timeout):
            if 'ready' in statuses:
                ready_count.append(email)
                return {'status':ready_status,'reason':'synthetic reason'}
            return {'status':'code','code':'870621'}
        connection.response=Mock(side_effect=response)
        def lookup(path,curp,email,instance,procedure):
            self.assertIn(email,ready_count,'IMSS cannot start before Outlook is ready')
            app.pendiente=(path,'1',instance,curp,'wrong@example.test' if stale else email,procedure)
            app.usados_sesion.add(email)
        app._consulta=Mock(side_effect=lookup)
        def enter(*args):
            if reject:
                connection.rejected=True;connection.reset_ready=True;app.pendiente=None
            else:
                app.resultado_tramite=True;app.pendiente=None
        app._codigo=Mock(side_effect=enter)
        with patch.object(bot,'correos_usados',return_value=set()):
            connection.run('console','SYNTHETIC-CURP','INSTANCE','procedure','sender@provider.test','Código')
        return app,connection

    def test_three_rejected_codes_rotate_both_bots_and_then_report_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            app,connection=self.workflow(folder)
            self.assertEqual(app._consulta.call_count,3)
            self.assertEqual(app._codigo.call_count,3)
            self.assertEqual(len({call.args[2] for call in app._consulta.call_args_list}),3)
            self.assertTrue(any('3/3' in call.args[0] for call in app.emit.call_args_list))
            self.assertFalse(connection.active)

    def test_success_stops_after_one_mailbox(self):
        with tempfile.TemporaryDirectory() as folder:
            app,_=self.workflow(folder,reject=False)
            app._consulta.assert_called_once();app._codigo.assert_called_once()
            self.assertTrue(app.resultado_tramite)

    def test_no_imss_submission_before_outlook_ready_and_never_on_throttling(self):
        for status,count in [('error',3),('limited',1),('stopped',1)]:
            with self.subTest(status=status),tempfile.TemporaryDirectory() as folder:
                app,connection=self.workflow(folder,ready_status=status)
                app._consulta.assert_not_called();app._codigo.assert_not_called()
                self.assertEqual(connection.response.call_count,count)

    def test_stale_mailbox_pending_never_receives_another_accounts_code(self):
        with tempfile.TemporaryDirectory() as folder:
            app,_=self.workflow(folder,stale=True)
            app._codigo.assert_not_called()


class PreparationTests(unittest.TestCase):
    def test_ready_instances_advance_without_fixed_delays(self):
        data={'a':{'running':True,'android':True}}
        with patch.object(bot,'listar',return_value=data),patch.object(bot.time,'sleep') as sleep:
            self.assertEqual(bot.esperar_instancias('console',lambda rows:rows['a']['android']),data)
        sleep.assert_not_called()

    def test_readiness_timeout_is_bounded(self):
        now=[0]
        with patch.object(bot,'listar',return_value={}),patch.object(bot.time,'monotonic',side_effect=lambda:now[0]),patch.object(bot.time,'sleep',side_effect=lambda seconds:now.__setitem__(0,now[0]+seconds)):
            self.assertEqual(bot.esperar_instancias('console',lambda rows:True,timeout=2),{})
        self.assertEqual(now[0],2)

    def test_success_requires_explicit_document_delivery_not_just_confirmation_of_email(self):
        self.assertTrue(bot.tramite_confirmado('La información solicitada se ha enviado a tu correo electrónico.'))
        self.assertFalse(bot.tramite_confirmado('Tu correo ha sido confirmado'))
        self.assertFalse(bot.tramite_confirmado('Error al enviar documento al correo'))


if __name__=='__main__':unittest.main()
