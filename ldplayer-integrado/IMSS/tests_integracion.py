import threading
import unittest
from unittest.mock import Mock, patch
from imss_paso1 import Node
import flujo_integrado as flow
from gestoria_imss_integrado import PanelIntegrado
from gestoria_prueba_v23 import select_serials

EMAIL = 'autorizada@example.invalid'
SERIAL = 'emulator-5554'
FOLIO = 'a' * 32


def node(text='', clazz='android.widget.TextView', y=10, clickable=False):
    return Node(clazz, text, '', '', (0, y, 100, y+20), False, False, True, clickable)


def otp_screen(email=EMAIL):
    return [node('Ingresa tu código de verificación ' + email),
            node('', 'android.widget.EditText', 80), node('Verificar', y=120, clickable=True)]


class FakeClient:
    def __init__(self):
        self.calls = []
        self.available = True
        self.other = False
    def ready(self):
        self.calls.append('ready')
        return dict(protocol=2, ready=self.available, email=EMAIL)
    def begin(self, email, folio, serial):
        self.calls.append('begin')
        return dict(email=email, request_id=folio, serial=serial, status='PREPARANDO_IMSS', new_request=True)
    def waiting(self, folio):self.calls.append('waiting')
    def requesting(self, folio):self.calls.append('requesting')
    def status(self, folio):
        self.calls.append('status')
        return dict(request_id='b'*32 if self.other else folio, email=EMAIL,
                    serial=SERIAL, status='CODIGO_DISPONIBLE', code='001234')
    def ack(self, folio):self.calls.append('ack')
    def done(self, folio):self.calls.append('done')


class FlowTests(unittest.TestCase):
    def setUp(self):self.stop = threading.Event()

    def test_explicit_acceptance(self):
        self.assertEqual(flow.resultado_codigo([node('Código verificado')], EMAIL), 'CONFIRMADO')

    def test_empty_dump_never_accepts(self):
        self.assertEqual(flow.resultado_codigo([], EMAIL), 'DESCONOCIDO')

    def test_arbitrary_screen_never_accepts(self):
        for text in ('Cargando', 'Vinculación del dispositivo', 'Semanas cotizadas', 'Inicio'):
            self.assertEqual(flow.resultado_codigo([node(text)], EMAIL), 'DESCONOCIDO')

    def test_error_wins_over_success_words(self):
        self.assertEqual(flow.resultado_codigo([node('Error. Código verificado')], EMAIL), 'RECHAZADO')

    def test_login_is_not_acceptance(self):
        self.assertEqual(flow.resultado_codigo([node('Inicia sesión CURP')], EMAIL), 'PENDIENTE')

    def test_no_android_before_mailbox(self):
        c = FakeClient();c.available = False
        with patch.object(flow, 'foreground') as adb:
            result = flow.ejecutar('adb', SERIAL, 'A'*18, EMAIL, self.stop, c, folio=FOLIO)
        self.assertEqual(result[0], 'REVISAR');adb.assert_not_called()

    def test_loss_of_readiness_prevents_android(self):
        c = FakeClient()
        c.ready = Mock(side_effect=[dict(protocol=2, ready=True, email=EMAIL), dict(ready=False)])
        with patch.object(flow, 'foreground') as adb:
            result = flow.ejecutar('adb', SERIAL, 'A'*18, EMAIL, self.stop, c, folio=FOLIO)
        adb.assert_not_called();self.assertEqual(result[0], 'REVISAR')

    def test_existing_registration_never_repeats_form(self):
        c = FakeClient()
        c.begin = Mock(return_value=dict(email=EMAIL, serial=SERIAL, status='PREPARANDO_IMSS'))
        with patch.object(flow, 'foreground') as adb:
            result = flow.ejecutar('adb', SERIAL, 'A'*18, EMAIL, self.stop, c, folio=FOLIO)
        adb.assert_not_called();self.assertEqual(result[0], 'REVISAR')

    def run_flow(self, outcome, other=False):
        c = FakeClient();c.other = other
        sent = []
        def ui(*args):return [node(outcome)] if sent else otp_screen()
        def write(*args):sent.append('written')
        def form(*args, **kwargs):
            kwargs['before_submit']()
            return 'ESPERANDO CÓDIGO', ''
        self.stop.wait = Mock(return_value=False)
        with patch.object(flow, 'foreground', return_value=True), \
             patch.object(flow, 'step_flow_v12', side_effect=form), \
             patch.object(flow, 'quick_ui', side_effect=ui), \
             patch.object(flow, 'escribir_una_vez', side_effect=write):
            result = flow.ejecutar('adb', SERIAL, 'A'*18, EMAIL, self.stop, c, folio=FOLIO)
        return result, c, sent

    def test_success_stops_after_ack_done(self):
        result, c, sent = self.run_flow('Código verificado')
        self.assertEqual(result[0], 'CODIGO CONFIRMADO FIN')
        self.assertEqual(sent, ['written']);self.assertEqual(c.calls[-2:], ['ack', 'done'])
        self.assertLess(c.calls.index('begin'), c.calls.index('waiting'))

    def test_unknown_transition_holds_without_ack_or_retry(self):
        result, c, sent = self.run_flow('Vinculación')
        self.assertEqual(result[0], 'REVISAR');self.assertEqual(sent, ['written'])
        self.assertNotIn('ack', c.calls);self.assertNotIn('done', c.calls)

    def test_rejected_code_never_acknowledged(self):
        result, c, sent = self.run_flow('Código incorrecto')
        self.assertEqual(result[0], 'REVISAR');self.assertNotIn('ack', c.calls)

    def test_other_folio_never_written(self):
        result, c, sent = self.run_flow('Código verificado', other=True)
        self.assertEqual(sent, []);self.assertEqual(result[0], 'REVISAR')

    def test_single_input_preserves_leading_zero_and_only_verify(self):
        with patch.object(flow, 'foreground', return_value=True), \
             patch.object(flow, 'quick_ui', return_value=otp_screen()), \
             patch.object(flow, 'tap') as tap, patch.object(flow, 'adb_run', return_value=(0, '')) as adb:
            flow.escribir_una_vez('adb', SERIAL, EMAIL, '001234', self.stop)
        self.assertEqual(adb.call_args.args[-1], '001234')
        self.assertEqual(tap.call_count, 2)

    def test_six_inputs_written_once(self):
        screen = [node('Ingresa tu código de verificación ' + EMAIL)] + [
            node('', 'android.widget.EditText', 30*i) for i in range(6)] + [node('Verificar', y=300, clickable=True)]
        with patch.object(flow, 'foreground', return_value=True), patch.object(flow, 'quick_ui', return_value=screen), \
             patch.object(flow, 'tap') as tap, patch.object(flow, 'adb_run', return_value=(0, '')) as adb:
            flow.escribir_una_vez('adb', SERIAL, EMAIL, '001234', self.stop)
        self.assertEqual([c.args[-1] for c in adb.call_args_list], list('001234'))
        self.assertEqual(tap.call_count, 7)

    def test_partial_adb_error_not_retried(self):
        with patch.object(flow, 'foreground', return_value=True), patch.object(flow, 'quick_ui', return_value=otp_screen()), \
             patch.object(flow, 'tap'), patch.object(flow, 'adb_run', return_value=(1, '')) as adb:
            with self.assertRaises(RuntimeError):flow.escribir_una_vez('adb', SERIAL, EMAIL, '001234', self.stop)
        self.assertEqual(adb.call_count, 1)

    def test_no_coordinate_fallback_when_fields_missing(self):
        with patch.object(flow, 'foreground', return_value=True), \
             patch.object(flow, 'quick_ui', return_value=[node('Ingresa tu código de verificación ' + EMAIL)]), \
             patch.object(flow, 'tap') as tap:
            with self.assertRaises(RuntimeError):flow.escribir_una_vez('adb', SERIAL, EMAIL, '001234', self.stop)
        tap.assert_not_called()

    def test_other_email_no_write(self):
        with patch.object(flow, 'foreground', return_value=True), patch.object(flow, 'quick_ui', return_value=otp_screen('otra@example.invalid')), \
             patch.object(flow, 'tap') as tap:
            with self.assertRaises(RuntimeError):flow.escribir_una_vez('adb', SERIAL, EMAIL, '001234', self.stop)
        tap.assert_not_called()

    def test_email_substring_is_not_match(self):
        self.assertFalse(flow.es_pantalla_codigo(otp_screen('x'+EMAIL), EMAIL))

    def test_acceptance_for_another_address_is_unknown(self):
        self.assertEqual(flow.resultado_codigo([node('Código verificado otra@example.invalid')], EMAIL), 'DESCONOCIDO')

    def test_cancelled_no_write(self):
        self.stop.set()
        with patch.object(flow, 'adb_run') as adb:
            with self.assertRaises(RuntimeError):flow.escribir_una_vez('adb', SERIAL, EMAIL, '001234', self.stop)
        adb.assert_not_called()

    def test_detection_filters_physical_offline_and_deduplicates(self):
        actual = select_serials({'emulator-5554':'device', '127.0.0.1:5555':'device',
            'emulator-5556':'device', 'emulator-5558':'offline', 'HONOR_PHYSICAL':'device', '192.168.1.2:5555':'device'})
        self.assertEqual(actual, [(0, 'emulator-5554'), (1, 'emulator-5556')])

    def test_connect_assessment_does_not_launch_imss(self):
        with patch('gestoria_imss_integrado.adb_run', return_value=(0, 'GESTORIA_OK')) as adb:
            state, _ = PanelIntegrado.start_and_assess('adb', SERIAL)
        self.assertEqual(state, 'LIBRE');self.assertEqual(adb.call_count, 1)


if __name__ == '__main__':unittest.main()
