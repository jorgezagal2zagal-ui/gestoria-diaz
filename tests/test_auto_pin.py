"""Regression checks for automatic Android unlock without real emulators."""
import importlib.util
from pathlib import Path
import queue
import unittest
from unittest.mock import Mock, patch


SOURCE = Path(__file__).resolve().parents[1] / 'gestoria_5_instancias.py'
SPEC = importlib.util.spec_from_file_location('gestoria_auto_pin_tests', SOURCE)
bot = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bot)

LOCKED = 'mKeyguardShowing=true\nmCurrentFocus=Window{com.android.systemui}'
UNLOCKED = 'mKeyguardShowing=false\nmCurrentFocus=Window{com.android.launcher}'


class AndroidLockStateTests(unittest.TestCase):
    def test_explicit_android_flags_accept_case_whitespace_and_separators(self):
        examples = [
            ('mKeyguardShowing=true', True),
            ('isKeyguardShowing = TRUE', True),
            ('  mShowingLockscreen : true  ', True),
            ('mDreamingLockscreen=true', True),
            ('mKeyguardShowing = false', False),
            ('ISKEYGUARDSHOWING: FALSE', False),
            ('mShowingLockscreen=false', False),
            ('mDreamingLockscreen : false', False),
        ]
        for output, expected in examples:
            with self.subTest(output=output):
                self.assertIs(bot.estado_bloqueo_android(output), expected)

    def test_keyguard_delegate_state_from_android_policy_dump(self):
        for expected in (True, False):
            value = str(expected).lower()
            output = (
                'WINDOW MANAGER POLICY STATE\n'
                '  KeyguardServiceDelegate\n'
                f'    showing = {value}\n'
                f'    inputRestricted: {value}\n'
                '    occluded=false\n'
            )
            with self.subTest(locked=expected):
                self.assertIs(bot.estado_bloqueo_android(output), expected)

    def test_unknown_or_failed_adb_output_is_not_an_unlocked_device(self):
        examples = [
            '',
            'mCurrentFocus=Window{com.example/.EmailCodeActivity}',
            'error: device offline',
            'error: device unauthorized',
            '/system/bin/sh: dumpsys: not found',
            'showing=true\ninputRestricted=false',
            'error: device offline\nmKeyguardShowing=false',
        ]
        for output in examples:
            with self.subTest(output=output):
                self.assertIsNone(bot.estado_bloqueo_android(output))


class UnlockHelperTests(unittest.TestCase):
    def run_unlock(self, states, size='Physical size: 720x1280', initial=LOCKED, pin='8706'):
        calls = []
        state_outputs = iter([initial, *states])

        def fake_adb(console, index, *args, **kwargs):
            self.assertEqual((console, index), ('synthetic-console', '1'))
            command = ' '.join(map(str, args))
            calls.append(command)
            if 'wm size' in command:
                return size
            if 'dumpsys' in command:
                return next(state_outputs, states[-1])
            return ''

        with patch.object(bot, 'adb', side_effect=fake_adb), \
                patch.object(bot.time, 'sleep'), \
                patch.object(bot, 'run', side_effect=AssertionError('External execution forbidden')), \
                patch.object(bot, '_sin_pipes', side_effect=AssertionError('External execution forbidden')):
            result = bot.desbloquear_android('synthetic-console', '1', pin)
        return result, calls

    def test_unlock_uses_digit_key_events_and_confirms_android_state(self):
        result, calls = self.run_unlock([LOCKED, UNLOCKED])
        self.assertTrue(result)
        digit_calls = [c for c in calls if any(f'KEYCODE_{d}' in c.split() for d in '8706')]
        digits = [token for c in digit_calls for token in c.split()
                  if token in {'KEYCODE_8', 'KEYCODE_7', 'KEYCODE_0', 'KEYCODE_6'}]
        self.assertEqual(digits, ['KEYCODE_8', 'KEYCODE_7', 'KEYCODE_0', 'KEYCODE_6'])
        self.assertFalse(any('input text' in c for c in calls))
        wake = next(i for i, c in enumerate(calls) if 'KEYCODE_WAKEUP' in c)
        swipe = next(i for i, c in enumerate(calls) if 'input swipe' in c)
        clear = next(i for i, c in enumerate(calls) if 'KEYCODE_DEL' in c)
        first_digit = next(i for i, c in enumerate(calls) if 'KEYCODE_8' in c.split())
        last_digit = next(i for i, c in enumerate(calls) if 'KEYCODE_6' in c.split())
        enter = next(i for i, c in enumerate(calls) if 'KEYCODE_ENTER' in c)
        confirmation = [i for i, c in enumerate(calls) if 'dumpsys' in c and i > enter]
        self.assertLess(wake, swipe)
        self.assertLess(swipe, clear)
        self.assertLess(clear, first_digit)
        self.assertLess(last_digit, enter)
        self.assertTrue(confirmation, 'Success must be confirmed after submitting PIN')

    def test_swipe_adapts_to_android_display_resolution(self):
        _, small = self.run_unlock([UNLOCKED], 'Physical size: 720x1280')
        _, large = self.run_unlock([UNLOCKED], 'Physical size: 1080x1920')

        def coordinates(calls):
            tokens = next(c.split() for c in calls if 'input swipe' in c)
            start = tokens.index('swipe') + 1
            return tuple(map(int, tokens[start:start + 4]))

        first = coordinates(small)
        second = coordinates(large)
        self.assertNotEqual(first, second)
        for coords, width, height in [(first, 720, 1280), (second, 1080, 1920)]:
            x1, y1, x2, y2 = coords
            self.assertTrue(0 <= x1 < width and 0 <= x2 < width)
            self.assertTrue(0 <= y2 < y1 < height)

    def test_still_locked_or_unknown_state_never_reports_success(self):
        for state in (LOCKED, '', 'error: device offline', 'mCurrentFocus=Window{com.example}'):
            with self.subTest(state=state):
                result, calls = self.run_unlock([state])
                self.assertFalse(result)
                polls = sum('dumpsys' in c for c in calls)
                self.assertGreater(polls, 0)
                self.assertLessEqual(polls, 10, 'Unlock confirmation must have a finite poll limit')

    def test_lock_must_be_confirmed_again_before_sending_any_input(self):
        for initial in (UNLOCKED, '', 'error: device offline', 'mCurrentFocus=Window{com.example}'):
            with self.subTest(initial=initial):
                result, calls = self.run_unlock([UNLOCKED], initial=initial)
                self.assertFalse(result)
                self.assertFalse(any('input ' in c for c in calls))

    def test_invalid_configured_pin_is_not_sent(self):
        for pin in ('', '87', '87x6', '1234567890123'):
            with self.subTest(pin=pin):
                result, calls = self.run_unlock([UNLOCKED], pin=pin)
                self.assertFalse(result)
                self.assertFalse(any('input ' in c for c in calls))


class MonitorUnlockTests(unittest.TestCase):
    def setUp(self):
        self.name = bot.NOMBRES[0]
        self.info = {'index': '1', 'pid': '101', 'running': True, 'android': True}
        self.app = bot.App.__new__(bot.App)
        for attr in ('bloqueada', 'arranque', 'enviados', 'sesion', 'ultimo_abrir', 'intentos_pin'):
            setattr(self.app, attr, {})
        self.app.events = queue.Queue()
        self.app.estado = Mock()
        self.app.emit = Mock()
        self.app.ocupada = Mock(return_value=False)
        self.app.abrir_imss = Mock()
        self.app.busy = False
        self.app.iniciado = True
        self.app.nombres = (self.name,)
        self.app.desbloqueando = False
        status = Mock()
        status.cget.return_value = 'Sin revisar'
        self.app.filas = {self.name: (Mock(), 1, status)}

    def poll(self, info=None):
        self.app.vigilar('synthetic-console', self.name, self.info if info is None else info)

    def test_locked_then_unlocked_device_attempts_once_and_opens_imss(self):
        with patch.object(bot, 'adb', side_effect=[LOCKED, LOCKED, UNLOCKED]), \
                patch.object(bot, 'desbloquear_android', return_value=False) as unlock:
            self.poll()
            self.app.abrir_imss.assert_not_called()
            self.assertIn(self.name, self.app.intentos_pin)
            self.poll()
            self.app.abrir_imss.assert_not_called()
            self.poll()
        unlock.assert_called_once()
        self.app.abrir_imss.assert_called_once()
        self.assertNotIn(self.name, self.app.intentos_pin)
        self.assertIs(self.app.bloqueada[self.name], False)

    def test_successful_unlock_can_open_imss_after_helper_confirmation(self):
        with patch.object(bot, 'adb', return_value=LOCKED), \
                patch.object(bot, 'desbloquear_android', return_value=True) as unlock:
            self.poll()
        unlock.assert_called_once()
        self.app.abrir_imss.assert_called_once()
        self.assertNotIn(self.name, self.app.intentos_pin)

    def test_transient_state_before_input_does_not_spend_the_pin_attempt(self):
        with patch.object(bot, 'adb', return_value=LOCKED), \
                patch.object(bot, 'desbloquear_android', side_effect=[None, True]) as unlock:
            self.poll()
            self.assertNotIn(self.name, self.app.intentos_pin)
            self.app.abrir_imss.assert_not_called()
            self.poll()
        self.assertEqual(unlock.call_count, 2)
        self.app.abrir_imss.assert_called_once()

    def test_selection_stays_frozen_until_unlock_and_open_finish(self):
        def during_unlock(*args):
            self.assertTrue(self.app.desbloqueando)
            return True

        def during_open(*args):
            self.assertTrue(self.app.desbloqueando)

        self.app.abrir_imss.side_effect = during_open
        with patch.object(bot, 'adb', return_value=LOCKED), \
                patch.object(bot, 'desbloquear_android', side_effect=during_unlock):
            self.poll()
        self.assertFalse(self.app.desbloqueando)

    def test_unlock_exception_releases_selection_without_repeating_input(self):
        with patch.object(bot, 'adb', return_value=LOCKED), \
                patch.object(bot, 'desbloquear_android', side_effect=RuntimeError('synthetic failure')):
            with self.assertRaisesRegex(RuntimeError, 'synthetic failure'):
                self.poll()
        self.assertFalse(self.app.desbloqueando)
        self.assertIn(self.name, self.app.intentos_pin)

    def test_instance_removed_from_selection_while_reading_state_is_not_unlocked(self):
        def changed_selection(*args, **kwargs):
            self.app.nombres = ()
            return LOCKED

        with patch.object(bot, 'adb', side_effect=changed_selection), \
                patch.object(bot, 'desbloquear_android') as unlock:
            self.poll()
        unlock.assert_not_called()
        self.assertFalse(self.app.desbloqueando)

    def test_no_pin_input_for_offline_unknown_or_already_unlocked_android(self):
        for state in ('error: device offline', '', 'mCurrentFocus=Window{com.example/.EmailCode}', UNLOCKED):
            with self.subTest(state=state):
                self.setUp()
                with patch.object(bot, 'adb', return_value=state), \
                        patch.object(bot, 'desbloquear_android') as unlock, \
                        patch.object(bot, 'run', side_effect=AssertionError('External execution forbidden')):
                    self.poll()
                unlock.assert_not_called()
                if state != UNLOCKED:
                    self.app.abrir_imss.assert_not_called()

    def test_unknown_state_does_not_clear_attempt_and_cause_repeated_pin_submission(self):
        with patch.object(bot, 'adb', side_effect=[LOCKED, 'mCurrentFocus=Window{com.example}', LOCKED]), \
                patch.object(bot, 'desbloquear_android', return_value=False) as unlock:
            self.poll()
            self.poll()
            self.assertIn(self.name, self.app.intentos_pin)
            self.poll()
        unlock.assert_called_once()
        self.app.abrir_imss.assert_not_called()

    def test_new_emulator_session_can_attempt_again(self):
        restarted = dict(self.info, pid='202')
        with patch.object(bot, 'adb', return_value=LOCKED), \
                patch.object(bot, 'desbloquear_android', return_value=False) as unlock:
            self.poll()
            self.poll()
            self.poll(restarted)
        self.assertEqual(unlock.call_count, 2)
        self.assertEqual(self.app.sesion[self.name], ('1', '202'))

    def test_attempt_is_recorded_before_input_and_forgetting_clears_it(self):
        def observe(*args, **kwargs):
            self.assertIn(self.name, self.app.intentos_pin)
            return False

        with patch.object(bot, 'adb', return_value=LOCKED), \
                patch.object(bot, 'desbloquear_android', side_effect=observe):
            self.poll()
        self.app.olvidar(self.name)
        self.assertNotIn(self.name, self.app.intentos_pin)
        self.assertNotIn(self.name, self.app.sesion)


if __name__ == '__main__':
    unittest.main()
