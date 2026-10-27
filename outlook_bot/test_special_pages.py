import threading
import unittest
from unittest.mock import Mock, patch

import automation as engine
import app as panel
from core import Account


class SpecialPageTests(unittest.TestCase):
    def test_almost_there_screen_skips_without_clicking_or_requesting_a_code(self):
        for apostrophe in ("'", '’'):
            driver, _, button = self.page('Almost there\nJust one more step to verify it' + apostrophe + 's you.\nSend a code to synthetic@example.test')
            recovery, _ = self.recovery(driver)
            with self.assertRaises(engine.VerificationRequired): recovery.handle()
            button.click.assert_not_called()
            driver.refresh.assert_not_called()

    def test_unrelated_almost_there_text_does_not_skip(self):
        driver, _, _ = self.page('Almost there: loading your settings')
        recovery, _ = self.recovery(driver)
        self.assertIsNone(recovery.handle())
        driver, _, _ = self.page("Almost there. Just one more step to verify it's you.",
                                'https://outlook.live.com/mail/0/inbox')
        recovery, _ = self.recovery(driver)
        self.assertIsNone(recovery.handle())

    def test_verification_required_closes_browser_and_never_retries_account(self):
        driver, _, button = self.page("Almost there. Just one more step to verify it's you.")
        with self.assertRaises(engine.VerificationRequired):
            engine.open_inbox(Account('synthetic@example.test','synthetic'), 'chrome',
                              lambda: False, Mock(), lambda _: driver)
        driver.quit.assert_called_once()
        button.click.assert_not_called()
        attempt = Mock(side_effect=engine.VerificationRequired('verification'))
        with self.assertRaises(engine.VerificationRequired):
            engine.try_account(Account('synthetic@example.test','synthetic'),
                               ['chrome','edge'], lambda: False, Mock(), attempt)
        attempt.assert_called_once()

    def test_verification_required_advances_to_next_account(self):
        application = panel.App.__new__(panel.App)
        application._stop_event = threading.Event()
        application._skip_event = threading.Event()
        application._post = lambda callback: callback()
        application._account_status = Mock()
        application._finish_run = Mock()
        application.status = Mock()
        accounts = [Account('one@example.test','synthetic'),Account('two@example.test','synthetic')]
        driver = Mock()
        def login(account, *args):
            if account.address == accounts[0].address:
                raise engine.VerificationRequired('verification')
            application._stop_event.set()
            return driver
        with patch.object(panel,'try_account',side_effect=login) as attempt:
            application._run_accounts(accounts,['chrome','edge'])
        self.assertEqual([call.args[0] for call in attempt.call_args_list],accounts)
        application._account_status.assert_any_call(accounts[0].address,'Omitido: verificación adicional')
        application._account_status.assert_any_call(accounts[1].address,'Bandeja abierta')
        driver.quit.assert_called_once()

    def page(self, text, url='https://login.live.com/ppsecure/post.srf'):
        driver = Mock()
        driver.current_url = url
        body = Mock()
        body.text = text
        button = Mock()
        driver.find_elements.side_effect = lambda by, selector: [body] if selector == 'body' else [button]
        return driver, body, button

    def recovery(self, driver, cancelled=lambda: False):
        return engine.SpecialPages(driver, cancelled, Mock()), None

    def test_rate_limit_refreshes_immediately_once_and_can_continue(self):
        driver, body, _ = self.page('Too Many Requests')
        driver.refresh.side_effect = lambda: setattr(body, 'text', 'Sign in')
        recovery, _ = self.recovery(driver)
        with patch.object(engine.time, 'sleep', side_effect=AssertionError('Refresh must be immediate')):
            self.assertEqual(recovery.handle(), 0)
        driver.refresh.assert_called_once()
        self.assertIsNone(recovery.handle())

    def test_persistent_rate_limit_does_not_refresh_again_or_try_another_browser(self):
        driver, _, _ = self.page('Too Many Requests')
        recovery, _ = self.recovery(driver)
        recovery.handle()
        with self.assertRaises(engine.RateLimited): recovery.handle()
        driver.refresh.assert_called_once()
        attempt = Mock(side_effect=engine.RateLimited('throttled'))
        with self.assertRaises(engine.RateLimited):
            engine.try_account(Account('synthetic@example.test','synthetic'),
                ['chrome','edge'], lambda: False, Mock(), attempt)
        attempt.assert_called_once()

    def test_cancelled_attempt_does_not_refresh(self):
        driver, _, _ = self.page('Too Many Requests')
        recovery, _ = self.recovery(driver, cancelled=lambda: True)
        with self.assertRaises(engine.SkipRequested): recovery.handle()
        driver.refresh.assert_not_called()

    def test_refresh_error_does_not_switch_browsers(self):
        driver, _, _ = self.page('Too Many Requests')
        driver.refresh.side_effect = RuntimeError('transport error')
        recovery, _ = self.recovery(driver)
        with self.assertRaises(engine.RateLimited): recovery.handle()

    def test_privacy_notice_clicks_ok_once_on_actual_microsoft_host(self):
        driver, _, button = self.page('A quick note about your Microsoft account',
            'https://privacynotice.account.microsoft.com/notice')
        recovery, _ = self.recovery(driver)
        self.assertEqual(recovery.handle(), 0)
        self.assertIsNone(recovery.handle())
        button.click.assert_called_once()

    def test_ok_is_not_clicked_on_other_sites_or_when_disabled(self):
        driver, _, button = self.page('A quick note about your Microsoft account')
        recovery, _ = self.recovery(driver)
        self.assertIsNone(recovery.handle())
        button.click.assert_not_called()
        driver.current_url = 'https://privacynotice.account.microsoft.com/notice'
        button.is_enabled.return_value = False
        self.assertIsNone(recovery.handle())
        button.click.assert_not_called()

    def test_exact_password_signin_screenshot_retries_only_one_alternative(self):
        text = "Password sign-in isn't available. Try another method."
        self.assertTrue(engine.password_unavailable(text))
        driver, _, _ = self.page(text)
        recovery, _ = self.recovery(driver)
        with self.assertRaises(engine.LoginFailure): recovery.handle()
        attempt = Mock(side_effect=engine.LoginFailure('password unavailable'))
        with self.assertRaises(engine.LoginFailure):
            engine.try_account(Account('synthetic@example.test','synthetic'),
                ['chrome','edge','firefox'], lambda: False, Mock(), attempt)
        self.assertEqual(attempt.call_count, 2)

    def test_queue_stops_on_rate_limit_instead_of_rotating_accounts(self):
        application = panel.App.__new__(panel.App)
        application._stop_event = threading.Event()
        application._skip_event = threading.Event()
        application._post = lambda callback: callback()
        application._account_status = Mock()
        application._finish_run = Mock()
        application.status = Mock()
        accounts = [Account('one@example.test','synthetic'), Account('two@example.test','synthetic')]
        with patch.object(panel,'try_account',side_effect=engine.RateLimited('rate limit')) as attempt:
            application._run_accounts(accounts,['chrome','edge'])
        attempt.assert_called_once()
        self.assertIn('Too Many Requests', application.status.set.call_args.args[0])
        application._finish_run.assert_called_once()


if __name__ == '__main__': unittest.main()
