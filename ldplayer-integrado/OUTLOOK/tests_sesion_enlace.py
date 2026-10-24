"""Avisos de perfil, conservación de sesión y entrega confirmada, con datos ficticios."""
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch

from app import App
import navegador as n
from avisos_perfil import is_profile_offer,descendant_browser_pids,decline_profile_dialog


class ProfileOffers(unittest.TestCase):
    def test_edge_offer_from_video_declines_no_thanks(self):
        self.assertTrue(is_profile_offer('Asistencia de Microsoft Edge',
            'Inicia sesión en Microsoft Edge, inicia sesión en todas partes.','No, gracias'))

    def test_chrome_and_cancel_are_limited_to_profile_offer(self):
        self.assertTrue(is_profile_offer('Iniciar sesión en Chrome','Iniciar sesión en Chrome','Cancelar'))
        self.assertFalse(is_profile_offer('Verifica tu identidad','Iniciar sesión en Chrome','Cancelar'))
        self.assertFalse(is_profile_offer('Seguridad de Windows','Guardar la clave de paso','Cancelar'))

    def test_accept_buttons_and_generic_errors_are_not_clicked(self):
        self.assertFalse(is_profile_offer('Asistencia de Microsoft Edge','Inicia sesión en Microsoft Edge','Continuar'))
        self.assertFalse(is_profile_offer('Error','Cancelar operación','Cancelar'))

    def test_only_browser_descendants_of_this_application_are_owned(self):
        rows=[(10,1,'python.exe'),(20,10,'node.exe'),(30,20,'msedge.exe'),
              (31,30,'msedge.exe'),(40,1,'chrome.exe'),(50,30,'CredentialUIBroker.exe')]
        self.assertEqual(descendant_browser_pids(rows,10),{30,31})

    def dialog(self,pid=30):
        button=SimpleNamespace(Name='No, gracias',ControlTypeName='ButtonControl',
            IsEnabled=True,IsOffscreen=False,GetChildren=lambda:[],GetInvokePattern=Mock())
        title=SimpleNamespace(Name='Inicia sesión en Microsoft Edge, inicia sesión en todas partes.',
            ControlTypeName='TextControl',GetChildren=lambda:[])
        window=SimpleNamespace(Name='Asistencia de Microsoft Edge',ControlTypeName='WindowControl',
            ProcessId=pid,IsOffscreen=False,GetChildren=lambda:[title,button])
        return window,button

    def test_recognized_owned_dialog_invokes_decline_only(self):
        dialog,button=self.dialog()
        self.assertTrue(decline_profile_dialog(dialog,{30}))
        button.GetInvokePattern.return_value.Invoke.assert_called_once()

    def test_unrelated_browser_is_untouched(self):
        dialog,button=self.dialog(40)
        self.assertFalse(decline_profile_dialog(dialog,{30}))
        button.GetInvokePattern.assert_not_called()

    def test_stopping_guard_prevents_a_late_click(self):
        dialog,button=self.dialog();stop=threading.Event();stop.set()
        self.assertFalse(decline_profile_dialog(dialog,{30},stop))
        button.GetInvokePattern.assert_not_called()

    def test_web_document_cannot_impersonate_native_profile_dialog(self):
        dialog,button=self.dialog();dialog.ControlTypeName='DocumentControl'
        self.assertFalse(decline_profile_dialog(dialog,{30}))
        button.GetInvokePattern.assert_not_called()


class ReaderDelivery(unittest.TestCase):
    def engine(self):
        state={'status':'ESPERANDO_CODIGO','email':'test@example.invalid','request_id':'r',
               'started':'2026-10-23T00:00:00Z'}
        engine=n.BrowserLogin(Mock(),request_supplier=lambda:state,deliver_code=Mock())
        engine.set_sender('sender@example.invalid')
        return engine,state

    def test_failed_delivery_is_retried_without_losing_scanned_code(self):
        engine,state=self.engine()
        engine.deliver_code.side_effect=[RuntimeError('temporary'),None]
        with patch.object(n,'scan_visible_inbox',return_value='012345') as scan:
            engine._check_inbox(Mock(),state['email'])
            self.assertEqual(engine.pending_code,'012345')
            engine.last_scan=0
            engine._check_inbox(Mock(),state['email'])
        self.assertIsNone(engine.pending_code)
        self.assertEqual(engine.deliver_code.call_count,2)
        scan.assert_called_once()

    def test_old_pending_code_is_never_given_to_a_new_request(self):
        engine,state=self.engine();engine.last_scan_request='old';engine.pending_code='012345'
        with patch.object(n,'scan_visible_inbox',return_value=None):
            engine._check_inbox(Mock(),state['email'])
        engine.deliver_code.assert_not_called();self.assertIsNone(engine.pending_code)

    def test_wrong_account_clears_pending_delivery(self):
        engine,state=self.engine();engine.pending_code='012345'
        engine._check_inbox(Mock(),'other@example.invalid')
        engine.deliver_code.assert_not_called();self.assertIsNone(engine.pending_code)

    def test_reader_failure_keeps_browser_open_and_does_not_stop_engine(self):
        engine,state=self.engine();page=Mock()
        with patch.object(engine,'_check_inbox',side_effect=RuntimeError('PRIVATE_VALUE')):
            engine._check_inbox_safely(page,state['email'])
        page.close.assert_not_called()
        self.assertFalse(engine.stop_event.is_set())
        self.assertNotIn('PRIVATE_VALUE',str(engine.callback.call_args))

    def test_passkey_creation_cannot_trigger_password_restart(self):
        page=Mock(url='https://login.microsoft.com/consumers/fido/create?mkt=es-MX')
        page.locator.return_value.inner_text.return_value='El inicio de sesión con contraseña no está disponible.'
        self.assertTrue(n.is_passkey_enrollment_url(page.url))
        self.assertFalse(n.is_password_signin_unavailable(page))

    def test_recovery_watcher_pauses_on_429_without_reading_or_closing(self):
        engine,state=self.engine();page=Mock();browser=Mock()
        context=SimpleNamespace(pages=[page]);page.is_closed.return_value=False
        engine.stop_event.wait=Mock(side_effect=[False,False,True])
        with patch.object(n,'is_microsoft_rate_limited',return_value=True) as limited, \
             patch.object(engine,'_check_inbox_safely') as reader:
            engine._watch_session(browser,context,state['email'])
        self.assertTrue(engine.rate_limited)
        reader.assert_not_called();limited.assert_called_once()
        page.close.assert_not_called();browser.close.assert_not_called()


class ActiveSessionReservation(unittest.TestCase):
    def fake(self):
        enabled=threading.Event();enabled.set()
        fake=SimpleNamespace(browser=SimpleNamespace(running=True,rate_limited=False,phase='mail'),
            active_email='test@example.invalid',_auto_queue_enabled=enabled,
            cooldown=SimpleNamespace(remaining=lambda:0),
            state=SimpleNamespace(status=lambda:{'status':'SIN_SOLICITUD'}),
            queue=SimpleNamespace(entries=lambda:[{'email':'test@example.invalid','estado':'USADO','seleccionado':1}]))
        fake._active_session_email=lambda:App._active_session_email(fake)
        return fake

    def test_open_mail_session_can_be_reserved_without_starting_another_account(self):
        fake=self.fake()
        self.assertTrue(App._reservation_available(fake))
        self.assertEqual(App._reserve_email(fake),'test@example.invalid')

    def test_login_passkey_429_and_existing_request_do_not_advertise_a_free_session(self):
        for phase in ('login','passkey','attention'):
            fake=self.fake();fake.browser.phase=phase
            self.assertFalse(App._reservation_available(fake))
        fake=self.fake();fake.browser.rate_limited=True
        self.assertFalse(App._reservation_available(fake))
        fake=self.fake();fake.state.status=lambda:{'status':'ESPERANDO_CODIGO'}
        self.assertFalse(App._reservation_available(fake))

    def test_terminal_request_frees_the_same_open_session_for_a_new_reservation(self):
        for status in ('CADUCADA','CANCELADA','SOLICITUD_IMSS_ENVIADA'):
            fake=self.fake();fake.state.status=lambda:{'status':status}
            self.assertTrue(App._reservation_available(fake))


if __name__=='__main__':unittest.main(verbosity=2)
