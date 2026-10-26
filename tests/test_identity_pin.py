"""Regression tests for Android identity PIN entry without a real device."""
import importlib.util
from pathlib import Path
import queue
import unittest
from unittest.mock import Mock, patch


SOURCE = Path(__file__).resolve().parents[1] / 'gestoria_5_instancias.py'
SPEC = importlib.util.spec_from_file_location('gestoria_identity_pin_tests', SOURCE)
bot = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bot)


def node(text='', rid='', kind='android.widget.TextView', xy=(100, 100), enabled=True):
    return {'texto': text, 'rid': rid, 'clase': kind, 'xy': xy,
            'enabled': enabled, 'area': 2000}


def identity_nodes(field=True):
    nodes = [node('Validación de identidad'), node('Ingresa tu PIN')]
    if field:
        nodes.append(node(rid='com.android.settings:id/password_entry',
                          kind='android.widget.EditText', xy=(180, 300)))
    return nodes


class IdentityPinEntryTests(unittest.TestCase):
    def setUp(self):
        self.transport = patch.object(bot, 'adb', return_value='')
        self.adb = self.transport.start()
        self.addCleanup(self.transport.stop)
        self.sleeps = patch.object(bot.time, 'sleep')
        self.sleeps.start()
        self.addCleanup(self.sleeps.stop)

    def test_field_is_focused_before_digit_events_and_pin_is_not_plain_text(self):
        self.assertTrue(bot.enviar_pin_identidad('test-console', '2', identity_nodes(), '8706'))
        commands = [call.args[2:] for call in self.adb.call_args_list]
        self.assertEqual(commands[0], ('shell', 'input', 'tap', '180', '300'))
        digits = [command[-1] for command in commands if command[-1] in
                  {'KEYCODE_8', 'KEYCODE_7', 'KEYCODE_0', 'KEYCODE_6'}]
        self.assertEqual(digits, ['KEYCODE_8', 'KEYCODE_7', 'KEYCODE_0', 'KEYCODE_6'])
        self.assertEqual(commands[-1], ('shell', 'input', 'keyevent', 'KEYCODE_ENTER'))
        self.assertFalse(any(command[:3] == ('shell', 'input', 'text') for command in commands))

    def test_enabled_edit_text_can_supply_focus_under_confirmed_identity_prompt(self):
        nodes = [node('Confirma tu identidad'),
                 node(rid='android:id/custom', kind='android.widget.EditText', xy=(90, 220))]
        self.assertTrue(bot.enviar_pin_identidad('test-console', '2', nodes, '8706'))
        self.assertEqual(self.adb.call_args_list[0].args[2:],
                         ('shell', 'input', 'tap', '90', '220'))

    def test_numeric_keypad_is_tapped_when_no_editable_field_is_exposed(self):
        nodes = identity_nodes(field=False) + [
            node(str(i), rid=f'com.android.systemui:id/key{i}',
                 kind='android.widget.Button', xy=(20 + i * 10, 500))
            for i in range(10)]
        self.assertTrue(bot.enviar_pin_identidad('test-console', '2', nodes, '8706'))
        taps = [call.args[2:] for call in self.adb.call_args_list
                if call.args[2:5] == ('shell', 'input', 'tap')]
        self.assertEqual(taps, [
            ('shell', 'input', 'tap', '100', '500'),
            ('shell', 'input', 'tap', '90', '500'),
            ('shell', 'input', 'tap', '20', '500'),
            ('shell', 'input', 'tap', '80', '500')])

    def test_android_key_ids_take_priority_over_combined_accessibility_labels(self):
        nodes = identity_nodes(field=False) + [
            # The earlier generic label must not hide the Android key resource.
            node('8', xy=(900, 900)),
            *[node(f'{i} {i} ABC', rid=f'com.android.systemui:id/key{i}',
                   kind='android.widget.Button', xy=(20 + i * 10, 500))
              for i in range(10)]]
        self.assertTrue(bot.enviar_pin_identidad('test-console', '2', nodes, '8706'))
        taps = [call.args[-2:] for call in self.adb.call_args_list
                if call.args[2:5] == ('shell', 'input', 'tap')]
        self.assertEqual(taps, [('100', '500'), ('90', '500'), ('20', '500'), ('80', '500')])

    def test_keypad_labels_accept_repeated_digit_and_telephone_letters(self):
        letters = ['', '', 'ABC', 'DEF', 'GHI', 'JKL', 'MNO', 'PQRS', 'TUV', 'WXYZ']
        for labels in ([f'{i} {i}' for i in range(10)],
                       [f'{i} {letters[i]}'.strip() for i in range(10)],
                       [f'{i} {letters[i]} {i} {letters[i]}'.strip() for i in range(10)]):
            with self.subTest(labels=labels):
                self.adb.reset_mock()
                nodes = identity_nodes(field=False) + [
                    node(label, kind='android.widget.Button', xy=(20 + i * 10, 500))
                    for i, label in enumerate(labels)]
                self.assertTrue(bot.enviar_pin_identidad('test-console', '2', nodes, '8706'))
                taps = [call.args[-2:] for call in self.adb.call_args_list
                        if call.args[2:5] == ('shell', 'input', 'tap')]
                self.assertEqual(taps, [('100', '500'), ('90', '500'), ('20', '500'), ('80', '500')])

    def test_ambiguous_multi_digit_labels_do_not_form_a_keypad(self):
        for ambiguous in ('12', '1 2', '1 11', '1 ABC 2', '1.0'):
            with self.subTest(label=ambiguous):
                self.adb.reset_mock()
                nodes = identity_nodes(field=False) + [
                    node(ambiguous if i == 1 else str(i),
                         kind='android.widget.Button', xy=(20 + i * 10, 500))
                    for i in range(10)]
                self.assertFalse(bot.enviar_pin_identidad('test-console', '2', nodes, '8706'))
                self.adb.assert_not_called()

    def test_email_code_non_identity_and_missing_target_never_receive_pin(self):
        scenarios = [
            identity_nodes() + [node('Código de validación')],
            [node('IMSS Digital'), node(kind='android.widget.EditText')],
            identity_nodes(field=False),
            [node('Ingresa tu PIN'), node(kind='android.widget.EditText', enabled=False)],
            [node('Confirma tu identidad'), node(kind='android.widget.EditText'),
             node(kind='android.widget.EditText')],
        ]
        for nodes in scenarios:
            with self.subTest(nodes=nodes):
                self.adb.reset_mock()
                self.assertFalse(bot.enviar_pin_identidad('test-console', '2', nodes, '8706'))
                self.adb.assert_not_called()

    def test_invalid_pin_has_no_input_side_effects(self):
        for pin in ('', '87', '87x6', '1234567890123'):
            with self.subTest(pin=pin):
                self.assertFalse(bot.enviar_pin_identidad('test-console', '2', identity_nodes(), pin))
        self.adb.assert_not_called()


class IdentityChallengeFlowTests(unittest.TestCase):
    def run_flow(self, after_login):
        app = bot.App.__new__(bot.App)
        app.events = queue.Queue()
        app.emit = Mock()
        app.root = Mock()
        app.refrescar_correos = Mock()
        app.btn_codigo = Mock()
        app.btn_consulta = Mock()
        app.pendiente = None
        app.foto = Mock(return_value=Path('synthetic.png'))
        login = [node(rid='example:id/txtCURP'), node(rid='example:id/txtCorreo'),
                 node('Iniciar sesión', rid='example:id/btnIniciar')]
        pages = iter([login, login, *after_login])
        with patch.object(bot, 'listar', return_value={'SYNTHETIC': {'index': '2', 'android': True}}), \
                patch.object(bot, 'adb', return_value='OK') as adb, \
                patch.object(bot, 'abrir_app'), patch.object(bot, 'escribir'), \
                patch.object(bot, 'tocar'), patch.object(bot, 'marcar_usado'), \
                patch.object(bot, 'PIN_EMULADOR', '8706'), \
                patch.object(bot.time, 'sleep'), \
                patch.object(bot, 'pantalla', side_effect=lambda *args: next(pages)), \
                patch.object(bot, 'enviar_pin_identidad', return_value=True) as send:
            app._consulta('test-console', 'SYNTHETIC-CURP', 'synthetic@example.test', 'SYNTHETIC', 'synthetic')
        return app, send, adb

    def test_one_submission_while_same_challenge_persists_then_manual_email_code(self):
        challenge = identity_nodes()
        app, send, adb = self.run_flow([challenge, challenge, challenge,
                                      [node('Código de validación')]])
        send.assert_called_once()
        self.assertIsNotNone(app.pendiente)
        self.assertTrue(any('Esperando código' in call.args[0] for call in app.emit.call_args_list))
        self.assertFalse(any('ERROR' in call.args[0] for call in app.emit.call_args_list))
        self.assertFalse(any(call.args[2:5] == ('shell', 'input', 'text') for call in adb.call_args_list))

    def test_email_code_screen_takes_priority_over_identity_words(self):
        app, send, _ = self.run_flow([identity_nodes() + [node('Código de validación')]])
        send.assert_not_called()
        self.assertIsNotNone(app.pendiente)

    def test_rejected_pin_is_not_automatically_submitted_again(self):
        challenge = identity_nodes()
        app, send, _ = self.run_flow([challenge, challenge + [node('PIN incorrecto')]])
        send.assert_called_once()
        self.assertIsNone(app.pendiente)
        self.assertTrue(any('no lo volveré a enviar' in call.args[0] for call in app.emit.call_args_list))


if __name__ == '__main__':
    unittest.main()
