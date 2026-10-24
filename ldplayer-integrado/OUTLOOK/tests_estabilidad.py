import json, queue, tempfile, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from app import App
from navegador import BrowserLogin
import app

class BrowserFailures(unittest.TestCase):
    def test_thread_start_failure_does_not_leave_running_true(self):
        engine=BrowserLogin(Mock())
        with patch('navegador.threading.Thread') as thread:
            thread.return_value.start.side_effect=RuntimeError('no threads')
            with self.assertRaises(RuntimeError):engine.start('synthetic@example.invalid','synthetic')
        self.assertFalse(engine.running)
    def test_exception_diagnostic_never_saves_values(self):
        manager=Mock();manager.__enter__=Mock(return_value=Mock());manager.__exit__=Mock(return_value=False)
        browser=Mock();browser.new_context.side_effect=RuntimeError('PRIVATE_VALUE')
        with tempfile.TemporaryDirectory() as d,patch('pathlib.Path.home',return_value=Path(d)), \
             patch('playwright.sync_api.sync_playwright',return_value=manager), \
             patch('navegador.launch_private_browser',return_value=browser):
            engine=BrowserLogin(Mock());engine.running=True;engine._worker('synthetic@example.invalid','PRIVATE_PASSWORD')
            data=(Path(d)/'GestoriaDiaz_Outlook_error.txt').read_text()
            self.assertNotIn('PRIVATE_VALUE',data);self.assertNotIn('PRIVATE_PASSWORD',data)
            self.assertNotIn('synthetic@example.invalid',data);self.assertEqual(json.loads(data)['type'],'RuntimeError')
        browser.close.assert_called_once();self.assertFalse(engine.running)

class UITimers(unittest.TestCase):
    def fake(self):return SimpleNamespace(_ui_events=queue.Queue(),_tick_once=Mock(),_closed=False,after=Mock(),tick=Mock())
    def test_background_callbacks_are_queued_without_touching_tk(self):
        f=self.fake();callback=Mock();App.post_ui(f,callback)
        callback.assert_not_called();App.tick(f);callback.assert_called_once()
        f.after.assert_called_once_with(1000,f.tick)
    def test_exception_does_not_stop_timer(self):
        f=self.fake();f._tick_once.side_effect=RuntimeError('failure')
        with patch('app.record') as record:App.tick(f)
        record.assert_called_once();f.after.assert_called_once_with(1000,f.tick)
    def test_bad_callback_does_not_block_following_events(self):
        f=self.fake();good=Mock()
        f._ui_events.put(Mock(side_effect=ValueError('bad event')));f._ui_events.put(good)
        with patch('app.record'):App.tick(f)
        good.assert_called_once();f._tick_once.assert_called_once()
    def test_closing_prevents_rescheduling(self):
        f=self.fake();f._closed=True;App.tick(f);f.after.assert_not_called()
    def test_corrupt_or_non_object_settings_are_recoverable(self):
        with tempfile.TemporaryDirectory() as d,patch.object(app,'SETTINGS',Path(d)/'settings.json'):
            for content in ('{','[]','null'):
                app.SETTINGS.write_text(content);self.assertEqual(app.get_settings(),{})
            app.save_settings({'sender':'synthetic@example.invalid'})
            self.assertEqual(app.get_settings(),{'sender':'synthetic@example.invalid'})
            self.assertFalse(app.SETTINGS.with_suffix('.tmp').exists())
    def test_busy_mismatched_account_and_429_reject_incoming_request(self):
        f=SimpleNamespace(browser=SimpleNamespace(rate_limited=False,running=True),
            active_email='one@example.com',cooldown=SimpleNamespace(remaining=lambda:0))
        self.assertTrue(App._can_begin(f,'one@example.com'))
        self.assertFalse(App._can_begin(f,'two@example.com'))
        f.browser.rate_limited=True;self.assertFalse(App._can_begin(f,'one@example.com'))
    def test_reservation_requires_explicit_automatic_mode(self):
        f=SimpleNamespace(_auto_queue_enabled=Mock(is_set=lambda:False),
            browser=SimpleNamespace(running=False,rate_limited=False),cooldown=SimpleNamespace(remaining=lambda:0))
        self.assertFalse(App._reservation_available(f))
if __name__=='__main__':unittest.main()
