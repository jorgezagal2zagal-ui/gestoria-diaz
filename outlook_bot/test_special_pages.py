import threading
import unittest
from unittest.mock import Mock, patch

import automation as engine
import app as panel
from core import Account


class SpecialPageTests(unittest.TestCase):
    def page(self, text, url='https://login.live.com/ppsecure/post.srf'):
        driver = Mock()
        driver.current_url = url
        body = Mock()
        body.text = text
        button = Mock()
        driver.find_elements.side_effect = lambda by, selector: [body] if selector == 'body' else [button]
        return driver, body, button

    def recovery(self, driver, cancelled=lambda: False):
        now = [0.0]
        def sleep(seconds): now[0] += seconds
        return engine.SpecialPages(driver, cancelled, Mock(),
                                   clock=lambda: now[0], sleep=sleep), now

    def test_rate_limit_waits_then_refreshes_once_and_can_continue(self):
        driver, body, _ = self.page('Too Many Requests')
        driver.refresh.side_effect = lambda: setattr(body, 'text', 'Sign in')
        recovery, clock = self.recovery(driver)
        self.assertGreaterEqual(recovery.handle(), 60)
        self.assertGreaterEqual(clock[0], 60)
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

    def test_pause_is_cancellable_without_waiting_a_minute(self):
        driver, _, _ = self.page('Too Many Requests')
        now = [0.0]
        recovery = engine.SpecialPages(driver, lambda: now[0] >= 1, Mock(),
            clock=lambda: now[0], sleep=lambda value: now.__setitem__(0, now[0]+value))
        with self.assertRaises(engine.RateLimited): recovery.handle()
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
