"""Handle only the explicitly requested IMSS device-link change confirmation."""
import importlib.util
from pathlib import Path
import queue
import unittest
from unittest.mock import Mock, patch


SOURCE = Path(__file__).resolve().parents[1] / 'gestoria_5_instancias.py'
SPEC = importlib.util.spec_from_file_location('gestoria_device_change_tests', SOURCE)
bot = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bot)


MESSAGE = 'Esta CURP está vinculada a otro dispositivo móvil ¿Deseas vincularla a este?'
YES = 'SÍ, QUIERO HACER EL CAMBIO'
YES_XY = (420, 680)
NO_XY = (100, 680)


def node(value='', description='', xy=(150, 300), visible=True, enabled=True,
         area=2000, kind='android.widget.TextView', rid=''):
    return {'valor': value, 'descripcion': description,
            'texto': ' '.join(text for text in (value, description) if text),
            'xy': xy, 'visible': visible, 'enabled': enabled, 'area': area,
            'clase': kind, 'rid': rid}


def dialog(label=YES, enabled=True, visible=True, area=2000, body=MESSAGE):
    return [
        node('IMSS Digital'), node(body),
        node('NO', xy=NO_XY, kind='android.widget.Button', rid='android:id/button2'),
        node(label, xy=YES_XY, enabled=enabled, visible=visible, area=area,
             kind='android.widget.Button', rid='android:id/button1'),
    ]


class DeviceChangeButtonTests(unittest.TestCase):
    def test_shown_dialog_selects_yes_instead_of_no(self):
        nodes = dialog()
        self.assertIs(bot.boton_cambio_dispositivo(nodes), nodes[-1])
        self.assertNotEqual(bot.boton_cambio_dispositivo(nodes)['xy'], NO_XY)

    def test_case_accents_punctuation_and_repeated_description_are_supported(self):
        for label in (YES, 'Si quiero hacer el cambio', '  sí,  quiero\n hacer el cambio.  '):
            with self.subTest(label=label):
                nodes = dialog(label=label)
                nodes[-1]['descripcion'] = label
                nodes[-1]['texto'] = label + ' ' + label
                self.assertIs(bot.boton_cambio_dispositivo(nodes), nodes[-1])

    def test_no_disabled_hidden_or_zero_area_affirmative_is_selected(self):
        for options in ({'enabled': False}, {'visible': False}, {'area': 0}):
            with self.subTest(options=options):
                self.assertIsNone(bot.boton_cambio_dispositivo(dialog(**options)))
        self.assertIsNone(bot.boton_cambio_dispositivo(dialog()[:-1]))

    def test_matching_affirmative_requires_the_specific_visible_device_link_message(self):
        unrelated = [
            '¿Deseas eliminar permanentemente tus datos?',
            '¿Deseas cambiar el correo de contacto?',
            'Esta CURP tiene una consulta pendiente.',
        ]
        for message in unrelated:
            with self.subTest(message=message):
                self.assertIsNone(bot.boton_cambio_dispositivo(dialog(body=message)))
        nodes = dialog()
        nodes[1]['visible'] = False
        self.assertIsNone(bot.boton_cambio_dispositivo(nodes))

    def test_generic_yes_or_negative_buttons_never_replace_the_explicit_change_action(self):
        for label in ('Sí', 'Aceptar', 'Continuar', 'NO', 'NO QUIERO HACER EL CAMBIO'):
            with self.subTest(label=label):
                self.assertIsNone(bot.boton_cambio_dispositivo(dialog(label=label)))


class DeviceChangeFlowTests(unittest.TestCase):
    def run_flow(self, after_login):
        app = bot.App.__new__(bot.App)
        app.events = queue.Queue()
        app.emit = Mock()
        app.root = Mock()
        app.refrescar_correos = Mock()
        app.registrar_correo = Mock()
        app.btn_codigo = Mock()
        app.btn_consulta = Mock()
        app.pendiente = None
        app.foto = Mock(return_value=Path('synthetic-device-change.png'))
        login = [
            node(rid='example:id/txtCURP'), node(rid='example:id/txtCorreo'),
            node('Iniciar sesión', rid='example:id/btnIniciar'),
        ]
        frames = iter([login, login, *after_login])
        last_frame = after_login[-1]

        def screenshot(*args):
            return next(frames, last_frame)

        with patch.object(bot, 'listar', return_value={'SYNTHETIC': {'index': '2', 'android': True}}), \
                patch.object(bot, 'adb', return_value='OK'), \
                patch.object(bot, 'abrir_app'), patch.object(bot, 'escribir'), \
                patch.object(bot, 'tocar') as tap, patch.object(bot, 'tocar_texto'), \
                patch.object(bot, 'PIN_EMULADOR', '8706'), \
                patch.object(bot.time, 'sleep'), \
                patch.object(bot, 'pantalla', side_effect=screenshot), \
                patch.object(bot, 'enviar_pin_identidad', return_value=True) as pin:
            app._consulta('test-console', 'SYNTHETIC-CURP', 'person@example.test',
                          'SYNTHETIC', 'synthetic')
        return app, tap, pin

    @staticmethod
    def change_taps(tap):
        return [call for call in tap.call_args_list if call.args[2] == YES_XY]

    def test_accepts_change_once_then_continues_to_pin_and_email_code(self):
        challenge = [node('Validación de identidad'), node('Confirma tu identidad para ingresar.')]
        app, tap, pin = self.run_flow([
            dialog(), dialog(), dialog(), challenge, [node('Código de validación')],
        ])
        self.assertEqual(len(self.change_taps(tap)), 1)
        self.assertFalse(any(call.args[2] == NO_XY for call in tap.call_args_list))
        pin.assert_called_once()
        self.assertIsNotNone(app.pendiente)
        self.assertFalse(any('ERROR' in call.args[0] for call in app.emit.call_args_list))

    def test_device_dialog_is_handled_before_background_email_code_text(self):
        app, tap, pin = self.run_flow([
            dialog() + [node('Código de validación')], [node('Código de validación')],
        ])
        self.assertEqual(len(self.change_taps(tap)), 1)
        pin.assert_not_called()
        self.assertIsNotNone(app.pendiente)

    def test_missing_or_disabled_change_button_warns_and_never_taps_no(self):
        for modal in (dialog(enabled=False), dialog()[:-1]):
            with self.subTest(modal=modal):
                app, tap, pin = self.run_flow([modal])
                self.assertEqual(self.change_taps(tap), [])
                self.assertFalse(any(call.args[2] == NO_XY for call in tap.call_args_list))
                pin.assert_not_called()
                self.assertIsNone(app.pendiente)
                messages = [call.args[0].lower() for call in app.emit.call_args_list]
                self.assertTrue(any('cambio' in text or 'botón' in text for text in messages))

    def test_disabled_button_can_be_accepted_when_it_becomes_enabled(self):
        app, tap, _ = self.run_flow([
            dialog(enabled=False), dialog(), dialog(), [node('Código de validación')],
        ])
        self.assertEqual(len(self.change_taps(tap)), 1)
        self.assertIsNotNone(app.pendiente)

    def test_unrelated_yes_dialog_is_not_accepted(self):
        app, tap, pin = self.run_flow([
            dialog(body='¿Deseas eliminar permanentemente tus datos?', label='Sí'),
            [node('Código de validación')],
        ])
        self.assertEqual(self.change_taps(tap), [])
        pin.assert_not_called()
        self.assertIsNotNone(app.pendiente)


if __name__ == '__main__':
    unittest.main()
