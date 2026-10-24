"""Arranque automático, pausa de 30 s y preparación del navegador, sin cuentas reales."""
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch

import app
from app import App
from cooldown import Cooldown
import navegador as n
import preparar


class Automation(unittest.TestCase):
    def fake(self):
        vault=Mock(password=Mock(return_value='synthetic-password'))
        return SimpleNamespace(auto_queue=Mock(get=Mock(return_value=True)),
            browser=SimpleNamespace(running=False,rate_limited=False),
            cooldown=Mock(remaining=Mock(return_value=0)),
            email=Mock(get=Mock(return_value='chosen@example.invalid')),
            queue=Mock(choose=Mock(return_value='next@example.invalid')),
            _vault=lambda:vault,_auto_start_attempted=False,
            _start_browser=Mock(return_value=True),_maybe_start_request_account=Mock(),
            info=Mock(),browser_status=Mock())

    def test_saved_account_starts_once_without_manual_clicks(self):
        fake=self.fake()
        App._maybe_auto_start(fake,{'status':'SIN_SOLICITUD'})
        App._maybe_auto_start(fake,{'status':'SIN_SOLICITUD'})
        fake._start_browser.assert_called_once_with('chosen@example.invalid','synthetic-password')

    def test_pause_running_and_429_prevent_auto_start(self):
        for condition in ('pause','running','rate_limit'):
            with self.subTest(condition=condition):
                fake=self.fake()
                if condition=='pause':fake.auto_queue.get.return_value=False
                if condition=='running':fake.browser.running=True
                if condition=='rate_limit':fake.browser.rate_limited=True
                App._maybe_auto_start(fake,{'status':'SIN_SOLICITUD'})
                fake._start_browser.assert_not_called()

    def test_cooldown_blocks_until_thirty_seconds_are_complete(self):
        fake=self.fake();now=[100.]
        fake.cooldown=Cooldown(clock=lambda:now[0]);fake.cooldown.begin()
        self.assertEqual(fake.cooldown.remaining(),30)
        now[0]=129.;App._maybe_auto_start(fake,{'status':'SIN_SOLICITUD'})
        fake._start_browser.assert_not_called()
        now[0]=130.;App._maybe_auto_start(fake,{'status':'SIN_SOLICITUD'})
        fake._start_browser.assert_called_once()

    def test_no_password_waits_for_configuration(self):
        fake=self.fake();fake._vault().password.return_value=None
        App._maybe_auto_start(fake,{'status':'SIN_SOLICITUD'})
        fake._start_browser.assert_not_called()
        self.assertFalse(fake._auto_start_attempted)

    def test_request_selects_exact_account_workflow(self):
        fake=self.fake()
        state={'status':'ESPERANDO_CODIGO','email':'requested@example.invalid'}
        App._maybe_auto_start(fake,state)
        fake._maybe_start_request_account.assert_called_once_with(state)
        fake._start_browser.assert_not_called()

    def test_explicit_start_can_resume_same_selected_used_account(self):
        fake=self.fake()
        fake._auto_started_request=None
        fake.queue.is_selected_new.return_value=False
        fake.queue.entries.return_value=[{'email':'chosen@example.invalid','seleccionado':1,'estado':'USADO'}]
        fake.password=Mock()
        state={'status':'ESPERANDO_CODIGO','email':'chosen@example.invalid','request_id':'synthetic-request'}
        App._maybe_start_request_account(fake,state)
        fake._start_browser.assert_not_called()
        App._maybe_start_request_account(fake,state,explicit=True)
        fake._start_browser.assert_called_once_with('chosen@example.invalid','synthetic-password')

    def test_launch_failure_does_not_loop_or_rotate_accounts(self):
        fake=self.fake();fake._start_browser.return_value=False
        for _ in range(3):App._maybe_auto_start(fake,{'status':'SIN_SOLICITUD'})
        fake._start_browser.assert_called_once()
        fake.queue.choose.assert_not_called()

    def test_stop_disables_automation_before_stopping_browser(self):
        fake=self.fake();fake._auto_queue_enabled=threading.Event();fake._auto_queue_enabled.set()
        fake.close_private=Mock()
        with patch.object(app,'save_settings') as save:
            App.stop_automation(fake)
        self.assertFalse(fake._auto_queue_enabled.is_set())
        fake.auto_queue.set.assert_called_once_with(False)
        save.assert_called_once_with({'auto_queue':False})
        fake.close_private.assert_called_once()

    def test_final_closed_event_does_not_hide_launch_error(self):
        fake=SimpleNamespace(browser=SimpleNamespace(last_error='synthetic startup error'),
                             browser_status=Mock(),browser_events=[])
        App._show_browser_event(fake,'Navegador cerrado.')
        fake.browser_status.set.assert_called_once_with('synthetic startup error')

    def test_start_request_does_not_mark_account_used_before_real_page_exists(self):
        fake=SimpleNamespace(_guard_new_login=lambda:True,browser=Mock(),
            browser_status=Mock(),queue=Mock(),active_email_label=Mock(),password=Mock(),
            _update_counts=Mock(),info=Mock(),sender=Mock(get=Mock(return_value='')))
        self.assertTrue(App._start_browser(fake,'chosen@example.invalid','synthetic-password'))
        fake.browser.start.assert_called_once_with('chosen@example.invalid','synthetic-password')
        fake.queue.mark_started.assert_not_called()

    def test_account_is_marked_used_once_after_real_page_exists(self):
        opened=threading.Event()
        fake=SimpleNamespace(browser=SimpleNamespace(browser_opened=opened,running=False,
                    rate_limited=False,last_error=''),_launch_recorded=False,
            active_email='chosen@example.invalid',queue=Mock(),_previous_browser_running=False,
            cooldown=Mock(remaining=Mock(return_value=0)),cooldown_label=Mock(),
            _update_counts=Mock(),sender=Mock(get=Mock(return_value='')),
            state=Mock(status=Mock(return_value={'status':'SIN_SOLICITUD'})),
            _maybe_auto_start=Mock(),link_status=Mock(),server=True)
        fake.browser.set_sender=Mock()
        App._tick_once(fake)
        fake.queue.mark_started.assert_not_called()
        opened.set()
        App._tick_once(fake);App._tick_once(fake)
        fake.queue.mark_started.assert_called_once_with('chosen@example.invalid')

    def test_settings_partial_update_preserves_automation_migration(self):
        with tempfile.TemporaryDirectory() as d,patch.object(app,'SETTINGS',Path(d)/'settings.json'):
            app.save_settings({'automation_version':15,'auto_queue':False})
            app.save_settings({'sender':'sender@example.invalid'})
            self.assertEqual(app.get_settings()['automation_version'],15)
            self.assertFalse(app.get_settings()['auto_queue'])


class BrowserPreparation(unittest.TestCase):
    def test_chromium_has_priority_and_edge_fallback_is_private(self):
        playwright=Mock()
        with patch.object(n.sys,'platform','win32'):
            candidates=n.browser_candidates(playwright)
            candidates[0][1]()
            self.assertNotIn('channel',playwright.chromium.launch.call_args.kwargs)
            candidates[-1][1]()
        arguments=playwright.chromium.launch.call_args.kwargs
        self.assertEqual(arguments['channel'],'msedge')
        self.assertIn('--inprivate',arguments['args'])
        self.assertFalse(arguments['headless'])

    def test_browser_failure_tries_fallback_and_reports_actionable_error(self):
        with patch.object(n,'browser_candidates',return_value=[
            ('Edge',Mock(side_effect=RuntimeError('PRIVATE_VALUE'))),
            ('Chrome',Mock(side_effect=RuntimeError('PRIVATE_VALUE'))) ]):
            with self.assertRaises(n.BrowserLaunchError) as result:
                n.launch_private_browser(Mock(),Mock())
        self.assertIn('INSTALAR.bat',str(result.exception))
        self.assertNotIn('PRIVATE_VALUE',str(result.exception))

    def test_existing_chromium_needs_no_download(self):
        with tempfile.TemporaryDirectory() as d:
            executable=Path(d)/'chromium';executable.touch()
            manager=Mock();manager.__enter__=Mock(return_value=SimpleNamespace(
                chromium=SimpleNamespace(executable_path=str(executable))))
            manager.__exit__=Mock(return_value=False)
            with patch('playwright.sync_api.sync_playwright',return_value=manager), \
                 patch.object(preparar.subprocess,'run') as run:
                self.assertEqual(preparar.ensure_browser(),0)
        run.assert_not_called()

    def test_missing_browser_installs_with_active_python_and_preserves_failure(self):
        for exit_code in (0,7):
            with self.subTest(exit_code=exit_code),tempfile.TemporaryDirectory() as d:
                manager=Mock();manager.__enter__=Mock(return_value=SimpleNamespace(
                    chromium=SimpleNamespace(executable_path=str(Path(d)/'missing'))))
                manager.__exit__=Mock(return_value=False)
                with patch.object(preparar,'installed_windows_browser',return_value=False), \
                     patch('playwright.sync_api.sync_playwright',return_value=manager), \
                     patch.object(preparar.subprocess,'run',return_value=SimpleNamespace(returncode=exit_code)) as run:
                    self.assertEqual(preparar.ensure_browser(),exit_code)
                run.assert_called_once_with([preparar.sys.executable,'-m','playwright','install','chromium'])

    def test_account_dashboard_excludes_security_and_challenges(self):
        page=Mock(url='https://account.microsoft.com/')
        page.locator.return_value.inner_text.return_value='Cuenta Microsoft'
        self.assertTrue(n.is_account_dashboard(page))
        page.locator.return_value.inner_text.return_value='Verifica tu identidad'
        self.assertFalse(n.is_account_dashboard(page))
        page.url='https://account.microsoft.com/security'
        self.assertFalse(n.is_account_dashboard(page))


if __name__=='__main__':unittest.main(verbosity=2)
