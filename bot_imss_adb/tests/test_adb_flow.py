import copy
from pathlib import Path
import subprocess
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from bot_imss_adb.adb import Adb, AdbError, Cancelled, devices_from, parse_nodes
from bot_imss_adb.flow import Flow, FlowError, Job, android_locked, otp_fields, otp_value, sent_confirmation
from bot_imss_adb.locking import ProcessLock
from bot_imss_adb.mail_service import ManualMailbox, OutlookMailbox
from bot_imss_adb.storage import History, device_lock, load_config, save_config
from bot_imss_adb.tests.fakes import Clock, FakeAdb, FakeMailbox, node

JOB = Job("AAAA900101HDFBCD00", "synthetic@example.test")


class AdbTests(unittest.TestCase):
    def test_device_list_does_not_treat_daemon_logs_as_devices(self):
        text = "* daemon started successfully *\nList of devices attached\nemulator-5554 device product:vbox model:LD_Player transport_id:1\n127.0.0.1:5557 offline\nAB123 unauthorized\n"
        rows = devices_from(text)
        self.assertEqual([(d.serial, d.state) for d in rows], [("emulator-5554", "device"), ("127.0.0.1:5557", "offline"), ("AB123", "unauthorized")])
        self.assertEqual(rows[0].model, "LD Player")

    def test_serial_is_explicit_and_android_shell_is_quoted(self):
        runner = Mock(return_value=SimpleNamespace(returncode=0, stdout=b"ok", stderr=b""))
        adb = Adb("C:/Program Files/adb.exe", "emulator-5556", runner=runner)
        adb.shell("echo", "x;$(secret)")
        args, kwargs = runner.call_args
        self.assertEqual(args[0], ["C:/Program Files/adb.exe", "-s", "emulator-5556", "shell", "echo 'x;$(secret)'"])
        self.assertNotIn("shell", kwargs)
        self.assertEqual(kwargs["timeout"], 15)

    def test_missing_device_refuses_command(self):
        runner = Mock()
        with self.assertRaises(AdbError):
            Adb("adb", runner=runner).shell("input", "tap", 1, 2)
        runner.assert_not_called()

    def test_connection_refused_is_error_even_with_zero_exit_code(self):
        runner = Mock(return_value=SimpleNamespace(returncode=0, stdout=b"cannot connect to 127.0.0.1:5555", stderr=b""))
        with self.assertRaisesRegex(AdbError, "No se conectó"):
            Adb("adb", runner=runner).connect("127.0.0.1:5555")

    def test_connect_disallows_remote_or_shell_injection(self):
        for value in ("host.test:5555", "127.0.0.1:0", "127.0.0.1:65536", "127.0.0.1:5555;ls"):
            with self.subTest(value=value), self.assertRaises(AdbError):
                Adb("adb").connect(value)

    def test_offline_unauthorized_and_timeouts_are_distinct_and_bounded(self):
        for text, expected in (("error: device offline", "offline"), ("error: device unauthorized", "autorizado")):
            runner = Mock(return_value=SimpleNamespace(returncode=1, stdout=b"", stderr=text.encode()))
            with self.assertRaisesRegex(AdbError, expected):
                Adb("adb", "emulator-5554", runner=runner).probe()
        runner = Mock(side_effect=subprocess.TimeoutExpired("adb", 15))
        with self.assertRaisesRegex(AdbError, "tiempo"):
            Adb("adb", "emulator-5554", runner=runner).probe()

    def test_cancellation_prevents_any_command(self):
        cancel = threading.Event()
        cancel.set()
        runner = Mock()
        with self.assertRaises(Cancelled):
            Adb("adb", "emulator-5554", cancel, runner).launch()
        runner.assert_not_called()

    def test_screen_parse_rejects_bad_xml_and_hidden_nodes(self):
        with self.assertRaises(AdbError):
            parse_nodes("old unrelated data")
        xml = '<hierarchy><node text="A &amp; B" bounds="[10,20][100,80]"/><node text="hidden" bounds="[10,20][100,80]" visible-to-user="false"/></hierarchy>'
        self.assertEqual([n["text"] for n in parse_nodes(xml)], ["A & B"])

    def test_dump_uses_new_file_each_time_and_removes_it(self):
        adb = Adb("adb", "device")
        paths = []
        def shell(*args, **kwargs):
            if args[0] == "uiautomator":
                paths.append(args[-1])
            if args[0] == "cat":
                return '<hierarchy><node text="ok" bounds="[0,0][2,2]"/></hierarchy>'
            return ""
        with patch.object(adb, "shell", side_effect=shell) as command:
            adb.screen()
            adb.screen()
        self.assertEqual(len(set(paths)), 2)
        self.assertEqual(sum(c.args[0] == "rm" for c in command.call_args_list), 2)

    def test_boot_and_app_presence_checked_before_launch(self):
        adb = Adb("adb", "device")
        with patch.object(adb, "run", return_value="device"), patch.object(adb, "shell", return_value="0"):
            with self.assertRaisesRegex(AdbError, "iniciando"):
                adb.probe()
        with patch.object(adb, "run", return_value="device"), patch.object(adb, "shell", side_effect=["1", ""]):
            with self.assertRaisesRegex(AdbError, "instalado"):
                adb.probe()


class FlowTests(unittest.TestCase):
    def make_flow(self, **kwargs):
        adb = FakeAdb(**kwargs)
        return adb, Flow(adb, clock=Clock(), poll=0)

    def test_entire_video_order_same_mail_and_confirmed_logout(self):
        trace = []
        adb, flow = self.make_flow(trace=trace)
        mail = FakeMailbox(trace)
        result = flow.run(JOB, mail)
        self.assertEqual(result, dict(nss="confirmado", vigencia="confirmado", semanas="confirmado"))
        self.assertLess(trace.index("mail-ready"), trace.index("imss-login"))
        self.assertLess(trace.index("mail-code"), trace.index("verify"))
        self.assertEqual(adb.email, JOB.email)
        self.assertEqual(adb.sent, ["nss", "vigencia", "semanas"])
        self.assertEqual(adb.verify_taps, 1)
        self.assertEqual(adb.state, "login")
        self.assertTrue(mail.closed)

    def test_mail_failure_never_starts_imss(self):
        adb, flow = self.make_flow()
        mail = FakeMailbox(fail=True)
        with self.assertRaises(FlowError):
            flow.run(JOB, mail)
        self.assertNotIn("imss-login", adb.trace)
        self.assertEqual(adb.sent, [])
        self.assertTrue(mail.closed)

    def test_rejected_code_does_not_submit_any_request(self):
        adb, flow = self.make_flow(fail="code")
        with self.assertRaisesRegex(FlowError, "rechazó"):
            flow.run(JOB, FakeMailbox())
        self.assertEqual(adb.sent, [])
        self.assertEqual(adb.verify_taps, 1)

    def test_incomplete_entry_is_repaired_with_readback_including_leading_zeros(self):
        adb, flow = self.make_flow(drop=True)
        adb.state = "otp"
        flow.enter_code("001177")
        self.assertEqual("".join(adb.digits), "001177")
        self.assertEqual(adb.verify_taps, 0)

    def test_never_infers_digits_from_descriptions(self):
        adb, flow = self.make_flow()
        adb.state = "otp"
        fields = otp_fields(adb.screen())
        for i, n in enumerate(fields):
            n["desc"] = "Dígito " + str(i+1)
        self.assertEqual(otp_value(fields), "")

    def test_invisible_or_ambiguous_otp_row_refused(self):
        adb, flow = self.make_flow()
        adb.state = "otp"
        row = otp_fields(adb.screen())
        second = copy.deepcopy(row)
        for n in second:
            x1, y1, x2, y2 = n["bounds"]
            n["bounds"] = (x1, y1+200, x2, y2+200)
            n["xy"] = (n["xy"][0], n["xy"][1]+200)
        self.assertEqual(otp_fields(row+second), [])

    def test_timeout_after_send_never_clicks_again_or_calls_next_step(self):
        adb, flow = self.make_flow(fail="nss")
        with self.assertRaisesRegex(FlowError, "no confirmó"):
            flow.run(JOB, FakeMailbox())
        self.assertEqual(adb.sent, ["nss"])
        self.assertEqual(flow.results, {"nss": "envio_solicitado_sin_confirmar"})
        self.assertNotEqual(adb.state, "login")

    def test_weeks_external_portal_left_visible_not_marked_success(self):
        adb, flow = self.make_flow(fail="external")
        with self.assertRaisesRegex(FlowError, "portal externo"):
            flow.run(JOB, FakeMailbox())
        self.assertEqual(adb.sent, ["nss", "vigencia"])
        self.assertEqual(flow.results["semanas"], "continuar_pulsado_sin_confirmar")
        self.assertEqual(adb.state, "external")

    def test_existing_session_is_never_overwritten(self):
        adb, flow = self.make_flow()
        adb.state = "home"
        with self.assertRaisesRegex(FlowError, "Ya existe una sesión"):
            flow.run(JOB, FakeMailbox())
        self.assertEqual(adb.curp, "")
        self.assertEqual(adb.sent, [])

    def test_wrong_recipient_in_otp_view_stops_before_reading_code(self):
        adb, flow = self.make_flow()
        original = adb.screen
        def wrong_email():
            ns = original()
            if adb.state == "otp":
                ns[1]["text"] = "other@example.test"
            return ns
        with patch.object(adb, "screen", side_effect=wrong_email), self.assertRaisesRegex(FlowError, "correo de esta solicitud"):
            flow.run(JOB, FakeMailbox())
        self.assertEqual(adb.verify_taps, 0)

    def test_only_selected_procedure_runs_and_logout_option_respected(self):
        adb, flow = self.make_flow()
        flow.run(Job(JOB.curp, JOB.email, ("vigencia",), logout=False), FakeMailbox())
        self.assertEqual(adb.sent, ["vigencia"])
        self.assertNotEqual(adb.state, "login")

    def test_non_keyguard_showing_flag_never_triggers_pin(self):
        self.assertIsNone(android_locked("SomeApp showing=true inputRestricted=true"))
        self.assertFalse(android_locked("mShowingLockscreen=false"))
        self.assertTrue(android_locked("mShowingLockscreen=false\nmKeyguardShowing=true"))
        self.assertTrue(android_locked("KeyguardServiceDelegate\n  showing=true\n  inputRestricted=true\nOther\n  showing=false"))

    def test_pin_not_guessed_when_locked(self):
        adb, flow = self.make_flow()
        with patch.object(adb, "shell", return_value="mShowingLockscreen=true"), self.assertRaisesRegex(FlowError, "PIN opcional"):
            flow.run(JOB, FakeMailbox())
        self.assertEqual(adb.sent, [])

    def test_future_negative_and_wrong_recipient_confirmation_rejected(self):
        for text in ("La constancia de vigencia se enviará a tu correo", "La constancia de vigencia no se ha enviado a tu correo", "Error: la constancia se ha enviado a tu correo", "La constancia se ha enviado a tu correo other@example.test"):
            with self.subTest(text=text):
                self.assertFalse(sent_confirmation([node(text)], "vigencia", JOB.email))
        self.assertTrue(sent_confirmation([node("La constancia de su vigencia de derechos se ha enviado a tu correo electrónico: " + JOB.email)], "vigencia", JOB.email))

    def test_bad_curp_email_pin_and_duplicate_procedure_rejected(self):
        for job in (Job("bad", JOB.email), Job("AAAA900231HDFBCD00", JOB.email), Job(JOB.curp, "bad"), Job(JOB.curp, JOB.email, pin="123"), Job(JOB.curp, JOB.email, ("nss", "nss"))):
            with self.subTest(job=job), self.assertRaises(ValueError):
                job.validate()


class MailAndHistoryTests(unittest.TestCase):
    def test_mailbox_binds_same_account_and_preserves_baseline_until_fresh_code(self):
        cancel = threading.Event()
        driver, reader = Mock(), Mock()
        reader.scan.side_effect = [None, "001177"]
        login = Mock(return_value=driver)
        mail = OutlookMailbox("SYNTHETIC_PASSWORD", cancel, login=login, reader_factory=Mock(return_value=reader))
        with patch("bot_imss_adb.mail_service.automation.available_browsers", return_value=["chrome"]):
            mail.prepare(JOB, Mock())
        self.assertEqual(login.call_args.args[0].address, JOB.email)
        self.assertEqual(mail.password, "")
        mail.started = 1000
        self.assertEqual(mail.code(JOB, Mock()), "001177")
        reader.baseline.assert_called_once()
        self.assertEqual([c.args for c in reader.scan.call_args_list], [(1000,), (1000,)])
        mail.close()
        driver.quit.assert_called_once()

    def test_reader_failure_after_inbox_closes_same_browser(self):
        driver, reader = Mock(), Mock()
        reader.baseline.side_effect = ValueError("SYNTHETIC_PRIVATE_PAYLOAD")
        mail = OutlookMailbox("secret", threading.Event(), login=Mock(return_value=driver), reader_factory=Mock(return_value=reader))
        with patch("bot_imss_adb.mail_service.automation.available_browsers", return_value=["chrome"]):
            with self.assertRaises(FlowError) as err:
                Flow(FakeAdb(), clock=Clock(), poll=0).run(JOB, mail)
        self.assertNotIn("PRIVATE", str(err.exception))
        driver.quit.assert_called_once()

    def test_manual_code_requires_exactly_six_digits(self):
        self.assertEqual(ManualMailbox(lambda email: "001177").code(JOB, Mock()), "001177")
        with self.assertRaises(FlowError):
            ManualMailbox(lambda email: "1234").code(JOB, Mock())

    def test_history_and_configuration_never_persist_password_pin_otp(self):
        with tempfile.TemporaryDirectory() as tmp:
            job = Job(JOB.curp, JOB.email, pin="999999")
            save_config(tmp, adb="adb.exe", serial="emulator-5554", password="SECRET", pin="999999", code="001177")
            self.assertEqual(load_config(tmp), {"adb": "adb.exe", "serial": "emulator-5554"})
            history = History(tmp)
            ident = history.start(job, "emulator-5554")
            history.finish(ident, "completada", "Trámites confirmados.", {"nss": "confirmado"})
            history.export(Path(tmp)/"registro.csv")
            data = b"".join(p.read_bytes() for p in Path(tmp).iterdir())
            for secret in (b"SECRET", b"999999", b"001177"):
                self.assertNotIn(secret, data)

    def test_crash_recovery_and_device_lock_do_not_allow_duplicate_execution(self):
        with tempfile.TemporaryDirectory() as tmp:
            h = History(tmp)
            h.start(JOB, "emulator-5554")
            self.assertEqual(h.recover(), 1)
            self.assertEqual(h.recent()[0][4], "interrumpida")
            first, second = ProcessLock(Path(tmp)/"device.lock"), ProcessLock(Path(tmp)/"device.lock")
            self.assertTrue(first.acquire())
            self.assertFalse(second.acquire())
            first.release()
            self.assertTrue(second.acquire())
            second.release()

    def test_opening_second_window_does_not_interrupt_live_request_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            history = History(tmp)
            lock = device_lock(tmp, "emulator-5554")
            self.assertTrue(lock.acquire())
            history.start(JOB, "emulator-5554")
            try:
                second = History(tmp)
                self.assertEqual(second.recover(), 0)
                self.assertEqual(second.recent()[0][4], "en_curso")
            finally:
                lock.release()
            self.assertEqual(history.recover(), 1)


if __name__ == "__main__":
    unittest.main()
