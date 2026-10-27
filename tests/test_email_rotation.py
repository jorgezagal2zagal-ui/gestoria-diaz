"""Change email only after the exact IMSS validation-error dialog."""
import importlib.util
from pathlib import Path
import queue
import unittest
from unittest.mock import Mock, patch


SOURCE = Path(__file__).resolve().parents[1] / 'gestoria_5_instancias.py'
SPEC = importlib.util.spec_from_file_location('gestoria_email_rotation_tests', SOURCE)
bot = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bot)

PATH = 'synthetic-console'
INDEX = '2'
NAME = 'GESTORIA_DIAZ_002'
CURP = 'SYNTHETIC-CURP'
FAILED = 'failed@example.test'
NEXT = 'next@example.test'
TRAMITE = 'synthetic-tramite'
ACCEPT = (420, 600)
CANCEL = (330, 920)
VERIFY = (330, 720)


def node(value='', rid='', xy=(160, 240), kind='android.widget.TextView',
         enabled=True, visible=True, area=2000, description=''):
    return {'valor': value, 'descripcion': description,
            'texto': ' '.join(part for part in (value, description) if part),
            'rid': rid, 'xy': xy, 'clase': kind,
            'enabled': enabled, 'visible': visible, 'area': area}


def error_modal(message='Error al validar el código', accept=True, **button_options):
    nodes = [node('IMSS Digital'), node(message)]
    if accept:
        nodes.append(node('ACEPTAR', rid='android:id/button1', xy=ACCEPT,
                          kind='android.widget.Button', **button_options))
    return nodes


def otp_page():
    return [node('Ingresa tu código de validación'),
            node('Cancelar', rid='example:id/cancel', xy=CANCEL,
                 kind='android.widget.Button')]


def login_page(email_visible=True, email_enabled=True):
    return [node('Inicia sesión'),
            node(rid='example:id/txtCURP', kind='android.widget.EditText'),
            node(rid='example:id/txtCorreo', kind='android.widget.EditText',
                 visible=email_visible, enabled=email_enabled)]


class AndroidRecoveryScreen:
    """Allow actions only when their actual screen has become current."""
    def __init__(self, modal=None, stuck_at=None, login=None):
        self.modal = error_modal() if modal is None else modal
        self.login = login_page() if login is None else login
        self.state = 'error'
        self.stuck_at = stuck_at
        self.taps = []
        self.polls = 0

    def screenshot(self, *args):
        self.polls += 1
        if self.polls > 30:
            raise AssertionError('Email recovery exceeded bounded screen polling')
        return {'error': self.modal, 'otp': otp_page(), 'login': self.login}[self.state]

    def tap(self, console, index, xy):
        self.taps.append((console, index, tuple(xy)))
        if tuple(xy) == ACCEPT:
            if self.state != 'error':
                raise AssertionError('Aceptar tapped outside the error dialog')
            if self.stuck_at != 'error':
                self.state = 'otp'
        elif tuple(xy) == CANCEL:
            if self.state != 'otp':
                raise AssertionError('Cancelar tapped before dismissing the error')
            if self.stuck_at != 'otp':
                self.state = 'login'
        else:
            raise AssertionError(f'Unexpected recovery control at {xy}')


def application(available=None):
    app = bot.App.__new__(bot.App)
    app.root = Mock()
    app.root.after.side_effect = lambda delay, callback: callback()
    app.btn_codigo = Mock()
    app.btn_consulta = Mock()
    app.codigo = Mock()
    app.curp = Mock()
    app.inst_sel = Mock()
    app.tramite = Mock()
    app.emit = Mock()
    app.events = queue.Queue()
    app.foto = Mock(return_value=Path('synthetic-email-error.png'))
    app.refrescar_correos = Mock()
    app.registrar_correo = Mock()
    app.usados_sesion = {FAILED}
    app.correos = [FAILED, NEXT]
    app.disponibles = Mock(return_value=[NEXT] if available is None else available)
    app.pendiente = (PATH, INDEX, NAME, CURP, FAILED, TRAMITE)

    def next_lookup(path, curp, correo, nombre, tramite):
        app.pendiente = (path, INDEX, nombre, curp, correo, tramite)

    app._consulta = Mock(side_effect=next_lookup)
    return app


class EmailRotationRecoveryTests(unittest.TestCase):
    def recover(self, screen=None, app=None, error_nodes=None):
        screen = AndroidRecoveryScreen() if screen is None else screen
        app = application() if app is None else app
        error_nodes = screen.modal if error_nodes is None else error_nodes
        with patch.object(bot, 'pantalla', side_effect=screen.screenshot), \
                patch.object(bot, 'tocar', side_effect=screen.tap), \
                patch.object(bot, 'adb', side_effect=AssertionError('No blind Android key input')), \
                patch.object(bot.time, 'sleep'):
            result = app.cambiar_correo_tras_error(
                PATH, INDEX, NAME, CURP, FAILED, TRAMITE, error_nodes)
        return result, app, screen

    def test_accepts_error_cancels_otp_and_restarts_same_request_with_next_email(self):
        result, app, screen = self.recover()
        self.assertTrue(result)
        self.assertEqual(screen.taps, [(PATH, INDEX, ACCEPT), (PATH, INDEX, CANCEL)])
        app._consulta.assert_called_once_with(PATH, CURP, NEXT, NAME, TRAMITE)
        self.assertEqual(app.pendiente, (PATH, INDEX, NAME, CURP, NEXT, TRAMITE))
        self.assertIn(FAILED, app.usados_sesion)
        self.assertLessEqual(screen.polls, 30)

    def test_failed_email_is_excluded_case_insensitively_before_selecting_next(self):
        app = application([FAILED.upper(), NEXT, 'third@example.test'])
        result, app, _ = self.recover(app=app)
        self.assertTrue(result)
        app._consulta.assert_called_once_with(PATH, CURP, NEXT, NAME, TRAMITE)

    def test_old_code_is_cleared_and_new_email_is_not_reserved_prematurely(self):
        app = application()

        def start_lookup(path, curp, correo, nombre, tramite):
            app.codigo.set.assert_called_with('')
            app.btn_codigo.configure.assert_any_call(state='disabled')
            self.assertIsNone(app.pendiente)
            app.registrar_correo.assert_not_called()
            self.assertNotIn(NEXT, app.usados_sesion)
            app.pendiente = (path, INDEX, nombre, curp, correo, tramite)

        app._consulta.side_effect = start_lookup
        result, app, _ = self.recover(app=app)
        self.assertTrue(result)
        app._consulta.assert_called_once()

    def test_exhausted_email_list_warns_without_reusing_the_rejected_email(self):
        for available in ([], [FAILED], [FAILED.upper()]):
            with self.subTest(available=available):
                result, app, _ = self.recover(app=application(available))
                self.assertFalse(result)
                app._consulta.assert_not_called()
                self.assertIn(FAILED, app.usados_sesion)
                self.assertTrue(app.emit.called)

    def test_unrelated_hidden_and_expired_code_errors_do_not_start_rotation(self):
        for nodes in (error_modal('Error de conexión'), error_modal('Código expirado'),
                      error_modal('Código incorrecto'), error_modal('Error al validar otro dato')):
            with self.subTest(message=nodes[1]['valor']):
                result, app, screen = self.recover(error_nodes=nodes)
                self.assertFalse(result)
                self.assertEqual(screen.taps, [])
                app._consulta.assert_not_called()
        hidden = error_modal()
        hidden[1]['visible'] = False
        result, app, screen = self.recover(error_nodes=hidden)
        self.assertFalse(result)
        self.assertEqual(screen.taps, [])
        app._consulta.assert_not_called()

    def test_exact_error_accepts_case_accents_and_duplicate_accessibility_text(self):
        modal = error_modal('  ERROR AL VALIDAR EL CODIGO.  ')
        modal[1]['descripcion'] = 'ERROR AL VALIDAR EL CODIGO'
        modal[1]['texto'] += ' ERROR AL VALIDAR EL CODIGO'
        modal[-1]['descripcion'] = 'Aceptar'
        modal[-1]['texto'] += ' Aceptar'
        result, app, _ = self.recover(screen=AndroidRecoveryScreen(modal=modal))
        self.assertTrue(result)
        app._consulta.assert_called_once()

    def test_missing_disabled_or_hidden_accept_never_causes_blind_navigation(self):
        for modal in (error_modal(accept=False), error_modal(enabled=False),
                      error_modal(visible=False), error_modal(area=0)):
            with self.subTest(modal=modal):
                result, app, screen = self.recover(screen=AndroidRecoveryScreen(modal=modal))
                self.assertFalse(result)
                self.assertEqual(screen.taps, [])
                app._consulta.assert_not_called()

    def test_stuck_error_or_cancel_screen_never_loops_or_submits_a_new_login(self):
        for state in ('error', 'otp'):
            with self.subTest(state=state):
                result, app, screen = self.recover(screen=AndroidRecoveryScreen(stuck_at=state))
                self.assertFalse(result)
                app._consulta.assert_not_called()
                self.assertLessEqual(screen.polls, 30)
                self.assertEqual(sum(tap[2] == ACCEPT for tap in screen.taps), 1)
                self.assertLessEqual(sum(tap[2] == CANCEL for tap in screen.taps), 1)

    def test_both_login_fields_must_be_enabled_and_visible_before_restart(self):
        for page in (login_page(email_visible=False), login_page(email_enabled=False),
                     login_page()[:-1]):
            with self.subTest(page=page):
                result, app, screen = self.recover(screen=AndroidRecoveryScreen(login=page))
                self.assertFalse(result)
                app._consulta.assert_not_called()
                self.assertLessEqual(screen.polls, 30)


class EmailRotationIntegrationTests(unittest.TestCase):
    def submit(self, status):
        app = application()
        app.hacer_tramite = Mock()
        app.meter_codigo = Mock(return_value=True)
        app.cambiar_correo_tras_error = Mock(return_value=False)
        first = [node('Ingresa tu código de validación'),
                 node('Verificar', xy=VERIFY, kind='android.widget.Button')]
        pages = iter([first, status])
        with patch.object(bot, 'pantalla', side_effect=lambda *args: next(pages, status)), \
                patch.object(bot, 'tocar'), patch.object(bot.time, 'sleep'):
            app._codigo('001177', PATH, INDEX, NAME, CURP, FAILED, TRAMITE)
        return app

    def test_codigo_routes_the_exact_rejection_to_recovery_without_starting_tramite(self):
        error = error_modal()
        app = self.submit(error)
        app.cambiar_correo_tras_error.assert_called_once_with(
            PATH, INDEX, NAME, CURP, FAILED, TRAMITE, error)
        app.hacer_tramite.assert_not_called()

    def test_other_errors_pending_and_hidden_rejection_do_not_rotate_email(self):
        hidden = error_modal()
        hidden[1]['visible'] = False
        for status in ([node('Código expirado')], [node('Código incorrecto')],
                       [node('Ingresa tu código de validación')], hidden):
            with self.subTest(status=status):
                app = self.submit(status)
                app.cambiar_correo_tras_error.assert_not_called()
                app.hacer_tramite.assert_not_called()

    def test_successful_confirmation_uses_existing_tramite_flow_without_rotation(self):
        app = self.submit([node('Tu correo ha sido confirmado')])
        app.cambiar_correo_tras_error.assert_not_called()
        app.hacer_tramite.assert_called_once_with(PATH, INDEX, NAME, CURP, TRAMITE)
        self.assertIsNone(app.pendiente)


if __name__ == '__main__':
    unittest.main()
