"""Exercise six-digit IMSS entry with an advancing Android OTP focus."""
import importlib.util
from pathlib import Path
import queue
import unittest
from unittest.mock import Mock, patch
from xml.etree import ElementTree


SOURCE = Path(__file__).resolve().parents[1] / 'gestoria_5_instancias.py'
SPEC = importlib.util.spec_from_file_location('gestoria_verification_tests', SOURCE)
bot = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bot)


def node(value='', rid='', kind='android.widget.TextView', bounds=(20, 20, 300, 60),
         enabled=True, visible=True, description=''):
    x1, y1, x2, y2 = bounds
    return {'valor': value, 'descripcion': description,
            'texto': ' '.join(part for part in (value, description) if part),
            'rid': rid, 'clase': kind, 'bounds': bounds,
            'xy': ((x1 + x2) // 2, (y1 + y2) // 2),
            'area': (x2 - x1) * (y2 - y1),
            'enabled': enabled, 'visible': visible}


def cells(values='', y=500):
    return [node(values[i] if i < len(values) else '',
                 rid=f'example:id/otp_{i}', kind='android.widget.EditText',
                 bounds=(30 + 100 * i, y, 110 + 100 * i, y + 96),
                 description=f'Dígito {i + 1}') for i in range(6)]


def background():
    return [
        node('SYNTHETIC920101HDFXXX01', rid='example:id/txtCURP',
             kind='android.widget.EditText', bounds=(30, 100, 670, 180)),
        node('person72@example.test', rid='example:id/txtCorreo',
             kind='android.widget.EditText', bounds=(30, 200, 670, 280)),
    ]


def verification_button(enabled=True):
    return node('Verificar', rid='example:id/verify', kind='android.widget.Button',
                bounds=(50, 680, 650, 770), enabled=enabled)


class CodeFieldSelectionTests(unittest.TestCase):
    def test_real_android_xml_keeps_raw_text_separate_from_numeric_descriptions(self):
        tree = ElementTree.Element('hierarchy')
        for field in background() + cells('001177'):
            x1, y1, x2, y2 = field['bounds']
            ElementTree.SubElement(tree, 'node', {
                'resource-id': field['rid'], 'class': field['clase'],
                'text': field['valor'],
                'content-desc': field['valor'] + ' ' + field['descripcion'],
                'enabled': 'true', 'visible-to-user': 'true',
                'bounds': f'[{x1},{y1}][{x2},{y2}]'})
        xml = ElementTree.tostring(tree, encoding='unicode')
        with patch.object(bot, 'adb', side_effect=['UI dump complete', xml]):
            nodes = bot.pantalla('synthetic-console', '1')
        selected = bot.cajas_codigo_validacion(nodes)
        self.assertEqual(len(selected), 6)
        self.assertEqual(bot.codigo_escrito(selected), '001177')

    def test_real_android_visibility_attribute_excludes_hidden_inputs(self):
        tree = ElementTree.Element('hierarchy')
        for i, field in enumerate(cells()):
            x1, y1, x2, y2 = field['bounds']
            ElementTree.SubElement(tree, 'node', {
                'resource-id': field['rid'], 'class': field['clase'],
                'text': '', 'content-desc': '', 'enabled': 'true',
                'visible-to-user': 'false' if i == 5 else 'true',
                'bounds': f'[{x1},{y1}][{x2},{y2}]'})
        xml = ElementTree.tostring(tree, encoding='unicode')
        with patch.object(bot, 'adb', side_effect=['UI dump complete', xml]):
            nodes = bot.pantalla('synthetic-console', '1')
        self.assertEqual(bot.cajas_codigo_validacion(nodes), [])

    def test_selects_six_aligned_cells_excluding_background_curp_and_email(self):
        row = cells()
        nodes = background() + [node('Ingresa tu código de validación')] + row
        self.assertEqual(bot.cajas_codigo_validacion(nodes), row)

    def test_selection_is_left_to_right_even_if_accessibility_tree_is_reversed(self):
        row = cells()
        self.assertEqual(bot.cajas_codigo_validacion(background() + list(reversed(row))), row)

    def test_disabled_invisible_or_zero_area_nodes_do_not_form_an_otp_row(self):
        for change in ({'enabled': False}, {'visible': False}, {'area': 0}):
            with self.subTest(change=change):
                row = cells()
                row[-1].update(change)
                self.assertEqual(bot.cajas_codigo_validacion(background() + row), [])

    def test_known_single_otp_field_is_supported_without_selecting_login_fields(self):
        aggregate = node('001177', rid='example:id/otp_input',
                         kind='android.widget.EditText', bounds=(30, 500, 670, 590))
        self.assertEqual(bot.cajas_codigo_validacion(background() + [aggregate]), [aggregate])

    def test_readback_uses_raw_value_without_description_numbers(self):
        row = cells('001177')
        for i, field in enumerate(row):
            field['texto'] = f"{field['valor']} {field['valor']} Dígito {i + 1}"
        self.assertEqual(bot.codigo_escrito(row), '001177')
        aggregate = node('001177', rid='example:id/otp_input',
                         kind='android.widget.EditText', description='Código 001177')
        self.assertEqual(bot.codigo_escrito([aggregate]), '001177')

    def test_missing_or_masked_digits_are_not_read_from_accessibility_descriptions(self):
        for value in ('', '•'):
            with self.subTest(value=value):
                row = cells('001177')
                row[-1]['valor'] = value
                row[-1]['texto'] = value + ' Dígito 6: 7'
                self.assertNotEqual(bot.codigo_escrito(row), '001177')


class AdvancingOtpScreen:
    """Model OTP widgets where backspace on an empty box moves focus left."""
    def __init__(self, drop_once=None, masked=False):
        self.values = [''] * 6
        self.focus = None
        self.drop_once = drop_once
        self.dropped = False
        self.masked = masked
        self.commands = []
        self.background_writes = []

    def screenshot(self, *args):
        row = cells(''.join(value or ' ' for value in self.values))
        for i, field in enumerate(row):
            value = self.values[i]
            if self.masked and value:
                value = '•'
            field['valor'] = value
            field['texto'] = ' '.join(p for p in (value, field['descripcion']) if p)
        return background() + [node('Ingresa tu código de validación')] + row + [
            verification_button(all(self.values))]

    def tap(self, console, index, xy):
        for i, field in enumerate(cells()):
            if tuple(xy) == field['xy']:
                self.focus = i
                return
        self.focus = 'background'

    def adb(self, console, index, *args, **kwargs):
        command = tuple(map(str, args))
        self.commands.append(command)
        if command[:3] == ('shell', 'input', 'tap'):
            return self.tap(console, index, tuple(map(int, command[3:5]))) or ''
        if command[:3] == ('shell', 'input', 'text'):
            raise AssertionError('OTP digits must use Android numeric key events')
        if command[:3] != ('shell', 'input', 'keyevent'):
            return ''
        for key in command[3:]:
            if not isinstance(self.focus, int):
                if key.startswith('KEYCODE_') and key[8:].isdigit():
                    self.background_writes.append(key)
                continue
            if key == 'KEYCODE_DEL':
                if not self.values[self.focus] and self.focus > 0:
                    self.focus -= 1
                self.values[self.focus] = ''
            elif key in ('KEYCODE_FORWARD_DEL', 'KEYCODE_CLEAR'):
                self.values[self.focus] = ''
            elif key.startswith('KEYCODE_') and key[8:].isdigit() and len(key[8:]) == 1:
                if self.focus == self.drop_once and not self.dropped:
                    self.dropped = True
                    continue
                self.values[self.focus] = key[8:]
                self.focus = min(self.focus + 1, 5)
        return ''


class SingleOtpScreen:
    def __init__(self):
        self.value = '99'
        self.cursor = 2
        self.focused = False
        self.commands = []

    def screenshot(self, *args):
        return background() + [node('Ingresa tu código de validación'),
            node(self.value, rid='example:id/otp_input', kind='android.widget.EditText',
                 bounds=(30, 500, 670, 590), description='Código de seis dígitos'),
            verification_button(len(self.value) == 6)]

    def tap(self, console, index, xy):
        self.focused = tuple(xy) == (350, 545)
        self.cursor = len(self.value)

    def adb(self, console, index, *args, **kwargs):
        command = tuple(map(str, args))
        self.commands.append(command)
        if command[:3] == ('shell', 'input', 'tap'):
            return self.tap(console, index, tuple(map(int, command[3:5]))) or ''
        if command[:3] == ('shell', 'input', 'text'):
            raise AssertionError('Use numeric key events for the OTP')
        if command[:3] != ('shell', 'input', 'keyevent') or not self.focused:
            return ''
        for key in command[3:]:
            if key == 'KEYCODE_MOVE_END':
                self.cursor = len(self.value)
            elif key == 'KEYCODE_MOVE_HOME':
                self.cursor = 0
            elif key == 'KEYCODE_DEL' and self.cursor:
                self.value = self.value[:self.cursor - 1] + self.value[self.cursor:]
                self.cursor -= 1
            elif key == 'KEYCODE_FORWARD_DEL':
                self.value = self.value[:self.cursor] + self.value[self.cursor + 1:]
            elif key == 'KEYCODE_CLEAR':
                self.value, self.cursor = '', 0
            elif key.startswith('KEYCODE_') and key[8:].isdigit() and len(key[8:]) == 1:
                self.value = self.value[:self.cursor] + key[8:] + self.value[self.cursor:]
                self.cursor += 1
        return ''


class CodeEntryTests(unittest.TestCase):
    def application(self):
        app = bot.App.__new__(bot.App)
        app.emit = Mock()
        app.foto = Mock(return_value=Path('synthetic-code.png'))
        return app

    def run_entry(self, screen, code='001177'):
        app = self.application()
        with patch.object(bot, 'pantalla', side_effect=screen.screenshot), \
                patch.object(bot, 'adb', side_effect=screen.adb), \
                patch.object(bot, 'tocar', side_effect=screen.tap), \
                patch.object(bot.time, 'sleep'):
            result = app.meter_codigo('synthetic-console', '1', code)
        return result, app

    def test_all_six_digits_survive_empty_box_backspace_and_automatic_focus_advance(self):
        screen = AdvancingOtpScreen()
        result, _ = self.run_entry(screen)
        self.assertTrue(result)
        self.assertEqual(''.join(screen.values), '001177')
        self.assertEqual(screen.background_writes, [])

    def test_partial_existing_code_is_replaced_without_appending_or_losing_digits(self):
        screen = AdvancingOtpScreen()
        screen.values = list('9832') + ['', '']
        result, _ = self.run_entry(screen, '701199')
        self.assertTrue(result)
        self.assertEqual(''.join(screen.values), '701199')
        self.assertEqual(screen.background_writes, [])

    def test_single_known_otp_field_is_cleared_and_receives_all_six_digits(self):
        screen = SingleOtpScreen()
        result, _ = self.run_entry(screen)
        self.assertTrue(result)
        self.assertEqual(screen.value, '001177')

    def test_a_dropped_digit_is_detected_and_corrected_with_bounded_input(self):
        screen = AdvancingOtpScreen(drop_once=3)
        result, _ = self.run_entry(screen)
        self.assertTrue(result)
        self.assertTrue(screen.dropped)
        self.assertEqual(''.join(screen.values), '001177')
        numeric = [key for command in screen.commands for key in command[3:]
                   if key.startswith('KEYCODE_') and key[8:].isdigit() and len(key[8:]) == 1]
        self.assertLessEqual(len(numeric), 12, 'Use at most two full input attempts')

    def test_masked_readback_is_not_accepted_as_complete_code(self):
        result, _ = self.run_entry(AdvancingOtpScreen(masked=True))
        self.assertFalse(result)

    def test_no_otp_boxes_never_succeeds_or_types_into_background_fields(self):
        app = self.application()
        with patch.object(bot, 'pantalla', return_value=background()), \
                patch.object(bot, 'adb') as adb, patch.object(bot, 'tocar') as tap, \
                patch.object(bot.time, 'sleep'):
            self.assertFalse(app.meter_codigo('synthetic-console', '1', '001177'))
        adb.assert_not_called()
        tap.assert_not_called()

    def test_only_exact_six_numeric_digits_can_be_entered(self):
        app = self.application()
        for code in ('1234', '1234567', '12x456', ''):
            with self.subTest(code=code), patch.object(bot, 'adb') as adb, \
                    patch.object(bot, 'pantalla') as screen, patch.object(bot, 'tocar') as tap, \
                    patch.object(bot.time, 'sleep'):
                self.assertFalse(app.meter_codigo('synthetic-console', '1', code))
                adb.assert_not_called()
                tap.assert_not_called()
                screen.assert_not_called()


class CodeSubmissionTests(unittest.TestCase):
    def run_submission(self, meter_ok=True, enabled=True, status='pending', decoynodes=()):
        app = bot.App.__new__(bot.App)
        app.root = Mock()
        app.root.after.side_effect = lambda delay, callback: callback()
        app.btn_codigo = Mock()
        app.emit = Mock()
        app.events = queue.Queue()
        app.pendiente = ('synthetic-pending',)
        app.hacer_tramite = Mock()
        app.meter_codigo = Mock(return_value=meter_ok)
        app.cambiar_correo_tras_error = Mock(return_value=False)
        app.foto = Mock(return_value=Path('synthetic-code.png'))
        first = [node('Ingresa tu código de validación'), *cells('001177'),
                 verification_button(enabled), *decoynodes]
        states = {
            'success': [node('Tu correo ha sido confirmado')],
            'error': [node('Error al validar el código')],
            'pending': [node('Ingresa tu código de validación'), *cells('001177'),
                        verification_button(), node('Tramita', visible=False)],
        }
        calls = 0

        def page(*args):
            nonlocal calls
            calls += 1
            return first if calls == 1 else states[status]

        with patch.object(bot, 'pantalla', side_effect=page), \
                patch.object(bot, 'adb') as adb, patch.object(bot, 'tocar') as tap, \
                patch.object(bot, 'tocar_texto'), patch.object(bot.time, 'sleep'):
            app._codigo('001177', 'synthetic-console', '1', 'SYNTHETIC',
                        'SYNTHETIC-CURP', 'person@example.test', 'synthetic')
        return app, adb, tap

    def test_partial_or_unverified_entry_cannot_press_verify_or_start_a_tramite(self):
        app, adb, tap = self.run_submission(meter_ok=False)
        tap.assert_not_called()
        adb.assert_not_called()
        app.hacer_tramite.assert_not_called()
        self.assertIsNotNone(app.pendiente)

    def test_disabled_verify_does_not_fall_back_to_enter(self):
        app, adb, tap = self.run_submission(enabled=False)
        tap.assert_not_called()
        adb.assert_not_called()
        app.hacer_tramite.assert_not_called()
        self.assertIsNotNone(app.pendiente)

    def test_an_enabled_button_and_explicit_confirmation_start_the_tramite(self):
        app, _, tap = self.run_submission(status='success')
        tap.assert_called_once()
        app.hacer_tramite.assert_called_once()
        self.assertIsNone(app.pendiente)

    def test_disabled_verify_cannot_be_replaced_by_an_enabled_background_action(self):
        for label in ('Continuar', 'Aceptar', 'Confirmar', 'Enviar'):
            with self.subTest(label=label):
                decoy = node(label, rid='example:id/background_action',
                             kind='android.widget.Button', bounds=(40, 310, 100, 350))
                app, adb, tap = self.run_submission(
                    enabled=False, status='success', decoynodes=[decoy])
                tap.assert_not_called()
                adb.assert_not_called()
                app.hacer_tramite.assert_not_called()
                self.assertIsNotNone(app.pendiente)

    def test_real_verify_is_selected_even_when_a_background_action_is_smaller(self):
        for label in ('Continuar', 'Aceptar', 'Confirmar', 'Enviar'):
            with self.subTest(label=label):
                decoy = node(label, rid='example:id/background_action',
                             kind='android.widget.Button', bounds=(40, 310, 100, 350))
                app, _, tap = self.run_submission(status='success', decoynodes=[decoy])
                tap.assert_called_once_with('synthetic-console', '1', verification_button()['xy'])
                app.hacer_tramite.assert_called_once()
                self.assertIsNone(app.pendiente)

    def test_error_routes_to_email_rotation_and_unconfirmed_screen_keeps_pending(self):
        for status in ('error', 'pending'):
            with self.subTest(status=status):
                app, _, _ = self.run_submission(status=status)
                app.hacer_tramite.assert_not_called()
                self.assertIsNotNone(app.pendiente)
                if status == 'error':
                    app.cambiar_correo_tras_error.assert_called_once()
                else:
                    app.cambiar_correo_tras_error.assert_not_called()


if __name__ == '__main__':
    unittest.main()
