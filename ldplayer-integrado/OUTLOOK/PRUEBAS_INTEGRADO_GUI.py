"""Pruebas de coordinación del panel sin fingir una ejecución de Tk/Windows."""
import os
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from outlook_integrado import IntegrationMixin, OutlookIntegrado

EMAIL = 'autorizada@example.invalid'


class Parent:
    def _tick_once(self):self.parent_calls += 1


class Host(IntegrationMixin, Parent):
    def __init__(self):
        self.active_email = EMAIL
        self.browser = SimpleNamespace(running=True, phase='mail', rate_limited=False,
            manual_security_pending=False, _mailbox_verified_email=EMAIL, _mailbox_verified_at=time.monotonic())
        self.preparacion = Mock()
        self.shared_pool = Mock()
        self.state = Mock()
        self.state.status.return_value = dict(status='SIN_SOLICITUD')
        self.info = Mock();self.browser_status = Mock();self.link_status = Mock()
        self.parent_calls = 0


class PanelContractTests(unittest.TestCase):
    def test_fresh_readiness(self):self.assertTrue(Host()._mailbox_ready()['ready'])

    def test_stale_readiness_rejected(self):
        host = Host();host.browser._mailbox_verified_at -= 6
        self.assertFalse(host._mailbox_ready()['ready'])

    def test_other_signed_in_identity_rejected(self):
        host = Host();host.browser._mailbox_verified_email = 'otra@example.invalid'
        self.assertFalse(host._mailbox_ready()['ready'])

    def test_phase_and_limit_block_readiness(self):
        for phase, limited in [('security_manual', False), ('mail_loading', False), ('mail', True)]:
            host = Host();host.browser.phase = phase;host.browser.rate_limited = limited
            self.assertFalse(host._mailbox_ready()['ready'])

    def test_security_pause_preserves_window_and_heartbeat_without_parent(self):
        host = Host();host.browser.manual_security_pending = True
        host._tick_once()
        self.assertEqual(host.parent_calls, 0)
        self.assertTrue(host.browser.running)
        host.preparacion.heartbeat.assert_called_once()
        self.assertTrue(host._security_was_paused)

    def test_resumption_uses_same_task(self):
        host = Host();host._security_was_paused = True
        host._tick_once()
        self.assertEqual(host.parent_calls, 1);self.assertFalse(host._security_was_paused)

    def test_children_use_integrated_entry(self):
        host = SimpleNamespace(children={})
        with patch('outlook_integrado.subprocess.Popen') as process:
            OutlookIntegrado.start_worker(host, 2)
        args = process.call_args.args[0]
        self.assertTrue(args[1].endswith('outlook_integrado.py'))
        self.assertEqual(args[-2:], ['--worker', '2'])
        self.assertEqual(process.call_args.kwargs['env']['GD_HEADLESS'], '0')


if __name__ == '__main__':unittest.main()
