import threading
import unittest
from unittest.mock import Mock, patch

from core import Account, parse_accounts
import automation as engine
import app as panel


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.account = Account('synthetic@example.test', 'synthetic-password')

    def test_password_unavailable_variants(self):
        for text in ('Password sign-in is not available',
                     'El inicio de sesión con contraseña no está disponible',
                     "You can't sign in with a password"):
            self.assertTrue(engine.password_unavailable(text))
        self.assertFalse(engine.password_unavailable('Use your password'))

    def test_alternative_browser_then_success(self):
        driver = Mock()
        attempt = Mock(side_effect=[engine.LoginFailure('stuck'), driver])
        result = engine.try_account(self.account, ['chrome', 'edge'], lambda: False, Mock(), attempt)
        self.assertIs(result, driver)
        self.assertEqual([c.args[1] for c in attempt.call_args_list], ['chrome', 'edge'])

    def test_no_more_than_two_browsers_and_no_password_in_report(self):
        report = Mock()
        attempt = Mock(side_effect=RuntimeError(self.account.password))
        with self.assertRaises(engine.LoginFailure):
            engine.try_account(self.account, ['chrome', 'edge', 'firefox'], lambda: False, report, attempt)
        self.assertEqual(attempt.call_count, 2)
        self.assertNotIn(self.account.password, str(report.call_args_list))

    def test_manual_skip_does_not_try_another_browser(self):
        attempt = Mock(side_effect=engine.SkipRequested)
        with self.assertRaises(engine.SkipRequested):
            engine.try_account(self.account, ['chrome', 'edge'], lambda: False, Mock(), attempt)
        self.assertEqual(attempt.call_count, 1)

    def test_cancelled_before_launch_never_opens_browser(self):
        factory = Mock()
        with self.assertRaises(engine.SkipRequested):
            engine.open_inbox(self.account, 'chrome', lambda: True, Mock(), factory)
        factory.assert_not_called()

    def test_passwordless_screen_closes_failed_driver(self):
        driver = Mock()
        body = Mock()
        body.text = 'El inicio de sesión con contraseña no está disponible'
        driver.find_elements.return_value = [body]
        with self.assertRaises(engine.LoginFailure):
            engine.open_inbox(self.account, 'chrome', lambda: False, Mock(), lambda _: driver)
        driver.quit.assert_called_once()

    def test_unknown_screen_times_out_and_closes_driver(self):
        driver = Mock()
        driver.current_url = 'https://login.live.com/'
        driver.find_elements.return_value = []
        with patch.object(engine.time, 'sleep'):
            with self.assertRaises(engine.LoginFailure):
                engine.open_inbox(self.account, 'chrome', lambda: False, Mock(),
                                  lambda _: driver, stage_timeout=.002)
        driver.quit.assert_called_once()

    def test_inbox_url_alone_is_not_success(self):
        driver = Mock()
        driver.current_url = 'https://outlook.live.com/mail/0/inbox'
        driver.find_elements.return_value = []
        self.assertFalse(engine.inbox_ready(driver))

    def test_complete_login_direct_password_and_alternate_signin(self):
        for alternate in (False, True):
            with self.subTest(alternate=alternate):
                driver = Mock()
                state = ['email']
                typed = {}
                class Element:
                    text = 'Microsoft sign in'
                    def __init__(self, kind, page):
                        self.kind, self.page = kind, page
                    def is_displayed(self): return state[0] == self.page
                    def is_enabled(self): return True
                    def clear(self): typed[self.kind] = ''
                    def send_keys(self, text): typed[self.kind] = text
                    def click(self):
                        if self.kind == 'next':
                            state[0] = ('other' if alternate else 'password') if self.page == 'email' else 'stay'
                        elif self.kind == 'other': state[0] = 'option'
                        elif self.kind == 'option': state[0] = 'password'
                        elif self.kind == 'no':
                            state[0] = 'inbox'
                            driver.current_url = 'https://outlook.live.com/mail/0/inbox'
                def find(by, selector):
                    page = state[0]
                    if selector == 'body': return [Element('body', page)]
                    if selector == engine.EMAIL and page == 'email': return [Element('email', page)]
                    if selector == engine.PASSWORD and page == 'password': return [Element('password', page)]
                    if selector == engine.NEXT and page in ('email','password'): return [Element('next', page)]
                    if selector == engine.OTHER and page == 'other': return [Element('other', page)]
                    if selector == engine.USE_PASSWORD and page == 'option': return [Element('option', page)]
                    if selector == engine.STAY_NO and page == 'stay': return [Element('no', page)]
                    if '[role="main"]' in selector and page == 'inbox': return [Element('inbox', page)]
                    return []
                driver.current_url = 'https://login.live.com/'
                driver.find_elements.side_effect = find
                with patch.object(engine.time, 'sleep'):
                    result = engine.open_inbox(self.account, 'chrome', lambda: False,
                        Mock(), lambda _: driver, stage_timeout=.05)
                self.assertIs(result, driver)
                self.assertEqual(typed, {'email': self.account.address, 'password': self.account.password})
                driver.quit.assert_not_called()
        driver.current_url = 'https://login.live.com/'
        driver.find_elements.return_value = [Mock()]
        self.assertFalse(engine.inbox_ready(driver))

    def test_failed_account_advances_and_success_waits_for_user(self):
        application = panel.App.__new__(panel.App)
        application._stop_event = threading.Event()
        application._skip_event = threading.Event()
        application._post = lambda callback: callback()
        application._account_status = Mock()
        application._finish_run = Mock()
        application.status = Mock()
        accounts = parse_accounts('one@example.test:synthetic\ntwo@example.test:synthetic')
        driver = Mock()
        def attempt(account, *args):
            if account.address == accounts[0].address:
                raise engine.LoginFailure('both failed')
            application._stop_event.set()
            return driver
        with patch.object(panel, 'try_account', side_effect=attempt) as run:
            application._run_accounts(accounts, ['chrome', 'edge'])
        self.assertEqual(run.call_count, 2)
        application._account_status.assert_any_call(accounts[0].address, 'Omitido: acceso no disponible')
        application._account_status.assert_any_call(accounts[1].address, 'Bandeja abierta')
        driver.quit.assert_called_once()
        application._finish_run.assert_called_once()


if __name__ == '__main__':
    unittest.main()
