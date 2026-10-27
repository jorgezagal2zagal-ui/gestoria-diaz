import csv
from datetime import datetime, timezone
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

from conexion.bridge import Bridge, PROTOCOL, read_json, write_json
from conexion.history import RequestHistory
from conexion.locking import ProcessLock
from conexion.reader import OutlookReader, extract_code, timestamp, ROW, PANE
from test_connected_bots import Row, Pane


class LockTests(unittest.TestCase):
    def test_only_one_process_holds_lock_and_crash_releases_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "app.lock"
            first = ProcessLock(path)
            second = ProcessLock(path)
            self.assertTrue(first.acquire())
            self.assertFalse(second.acquire())
            first.release()
            self.assertTrue(second.acquire())
            second.release()
            program = "from conexion.locking import ProcessLock; import sys,time; l=ProcessLock(sys.argv[1]); print(l.acquire(),flush=True); time.sleep(30)"
            child = subprocess.Popen(
                [sys.executable, "-c", program, str(path)],
                stdout=subprocess.PIPE,
                text=True,
            )
            try:
                self.assertEqual(child.stdout.readline().strip(), "True")
                self.assertFalse(first.acquire())
            finally:
                child.kill()
                child.wait(5)
                child.stdout.close()
            self.assertTrue(first.acquire())
            first.release()


class ProtocolTests(unittest.TestCase):
    def test_restarting_imss_cancels_previous_reader_and_removes_unconsumed_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = Bridge(tmp)
            key = b.create(
                "a@example.test", "INSTANCE", "sender@provider.test", "Código"
            )
            b.reply(key, "code", code="123456")
            b.interrupt_previous(client_restarted=True)
            self.assertTrue(b.cancelled(key))
            self.assertIsNone(b.response(key))

    def test_restarting_outlook_stops_old_handoff_instead_of_replaying_ready_or_code(
        self,
    ):
        with tempfile.TemporaryDirectory() as tmp:
            b = Bridge(tmp)
            key = b.create(
                "a@example.test", "INSTANCE", "sender@provider.test", "Código"
            )
            b.reply(key, "code", code="123456")
            b.interrupt_previous()
            self.assertEqual(b.response(key)["status"], "stopped")
            self.assertNotIn("code", b.response(key))

    def test_wrong_protocol_and_malformed_heartbeat_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            bridge = Bridge(tmp)
            for malformed in (
                {"at": "bad", "active": True},
                {"protocol": 1, "at": time.time(), "active": True, "emails": []},
                {
                    "protocol": PROTOCOL,
                    "at": time.time() + 99,
                    "active": True,
                    "emails": [],
                },
                {
                    "protocol": PROTOCOL,
                    "at": time.time(),
                    "active": True,
                    "emails": [None],
                },
            ):
                write_json(Path(tmp) / "outlook.json", malformed)
                self.assertIsNone(bridge.presence())
            bridge.publish(["A@example.test", "a@example.test", "bad"], True)
            self.assertEqual(bridge.presence()["emails"], ["a@example.test"])

    def test_dead_jobs_are_cancelled_and_cannot_recreate_code_payloads(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = Bridge(tmp)
            key = b.create(
                "a@example.test", "INSTANCE", "sender@provider.test", "Código"
            )
            b.started(key)
            b.waiting(key)
            self.assertTrue(read_json(b.job(key) / "waiting.json"))
            b.finish(key)
            b.pending()
            self.assertTrue(b.cancelled(key))
            b.reply(key, "code", code="123456")
            self.assertFalse(b.job(key).exists())

    def test_code_wait_has_separate_clock_from_imss_navigation(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = Bridge(tmp)
            key = b.create(
                "a@example.test", "INSTANCE", "sender@provider.test", "Código", 300
            )
            b.started(key)
            with patch("conexion.bridge.time.time", return_value=time.time() + 100):
                b.waiting(key)
            self.assertGreater(
                read_json(b.job(key) / "waiting.json")["at"],
                read_json(b.job(key) / "started.json")["at"] + 90,
            )
            with self.assertRaises(ValueError):
                b.create("a@example.test", "i", "sender@provider.test", "subject", 1000)


class HistoryTests(unittest.TestCase):
    def test_journal_recovers_interrupted_attempts_without_replaying_them(self):
        with tempfile.TemporaryDirectory() as tmp:
            h = RequestHistory(tmp)
            h.record(
                "request",
                "SYNTHETIC",
                "INSTANCE",
                "Semanas",
                1,
                "a@example.test",
                "codigo",
            )
            self.assertEqual(h.recover_interrupted(), 1)
            self.assertEqual(h.rows()[0]["resultado"], "interrumpida")
            h.record(
                "request2",
                "SYNTHETIC",
                "INSTANCE",
                "Semanas",
                1,
                "b@example.test",
                "terminado",
                "completada",
                "Envío confirmado",
            )
            self.assertEqual(h.recover_interrupted(), 0)
            h.export(Path(tmp) / "hist.csv")
            rows = list(
                csv.DictReader((Path(tmp) / "hist.csv").open(encoding="utf-8-sig"))
            )
            self.assertEqual(len(rows), 2)
            self.assertNotIn("codigo", rows[0])
            self.assertNotIn(
                "password", (Path(tmp) / "hist.csv").read_text(encoding="utf-8-sig")
            )

    def test_concurrent_writes_keep_one_result_per_attempt(self):
        with tempfile.TemporaryDirectory() as tmp:
            h = RequestHistory(tmp)
            errors = []

            def work(n):
                try:
                    for stage in ("outlook", "consulta", "codigo", "terminado"):
                        h.record(
                            "request",
                            "SYNTHETIC",
                            "INSTANCE",
                            "Semanas",
                            n,
                            f"example{n}@example.test",
                            stage,
                            "fallida" if stage == "terminado" else "en_curso",
                        )
                except Exception as e:
                    errors.append(type(e).__name__)

            threads = [threading.Thread(target=work, args=(i,)) for i in range(1, 4)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(5)
            self.assertEqual(errors, [])
            self.assertEqual(len(h.rows()), 3)
            self.assertTrue(all(r["resultado"] == "fallida" for r in h.rows()))

    def test_csv_escapes_formulas_and_invalid_stage_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            h = RequestHistory(tmp)
            h.record(
                "req",
                "SYNTHETIC",
                "INSTANCE",
                "Semanas",
                1,
                "a@example.test",
                "terminado",
                "fallida",
                "=INVALID",
            )
            p = Path(tmp) / "a.csv"
            h.export(p)
            self.assertIn("'=INVALID", p.read_text(encoding="utf-8-sig"))
            with self.assertRaises(ValueError):
                h.record("req", "c", "i", "t", 1, "mail", "raw-code")


class ReaderV2Tests(unittest.TestCase):
    def test_new_message_in_old_conversation_is_detected_when_native_date_changes(self):
        r, rows, panes = self.reader()
        started = time.time()

        class DatedRow(Row):
            date = datetime.fromtimestamp(started - 3600, timezone.utc).isoformat()

            def get_attribute(self, name):
                return (
                    self.date
                    if name == "data-received-date"
                    else super().get_attribute(name)
                )

        rows[:] = [DatedRow("old", "Código de validación")]
        r.baseline()
        rows[0].date = datetime.fromtimestamp(started + 1, timezone.utc).isoformat()
        panes[:] = [Pane("old", "Código de validación: 345678", "sender@provider.test")]
        self.assertEqual(r.scan(started), "345678")

    def reader(self):
        driver = Mock()
        driver.current_url = "https://outlook.live.com/mail/0/inbox"
        rows = [Row("old", "Código de validación")]
        panes = []
        driver.find_elements.side_effect = lambda by, selector: (
            rows if selector == ROW else panes if selector == PANE else []
        )
        reader = OutlookReader(driver, "sender@provider.test", "Código de validación")
        reader.baseline()
        return reader, rows, panes

    def test_old_preview_changing_relative_time_is_not_a_new_message(self):
        r, rows, panes = self.reader()
        rows[0].text += " hace un minuto"
        pane = Pane("old", "Código de validación: 123456", "sender@provider.test")
        self.assertIsNone(r.inspect(rows[0], pane, time.time()))

    def test_new_message_waits_for_partial_body_instead_of_being_discarded(self):
        r, rows, panes = self.reader()
        row = Row("new", "Código de validación")
        pane = Pane("new", "Código de validación: Cargando", "sender@provider.test")
        self.assertIsNone(r.inspect(row, pane, time.time()))
        pane.text = "Código de validación: 345678"
        self.assertEqual(r.inspect(row, pane, time.time()), "345678")

    def test_old_and_future_dates_are_rejected_even_if_message_appears_new(self):
        r, rows, panes = self.reader()
        row = Row("new", "Código de validación")
        pane = Pane("new", "Código de validación: 345678", "sender@provider.test")
        for offset in (-3600, 3600):
            with patch.object(r, "dates", return_value=[time.time() + offset]):
                self.assertIsNone(r.inspect(row, pane, time.time()))

    def test_recipient_is_never_accepted_as_sender(self):
        r, rows, panes = self.reader()
        row = Row("new", "Código de validación")
        pane = Pane("new", "Código de validación: 345678", "other@provider.test")
        self.assertIsNone(r.inspect(row, pane, time.time()))

    def test_international_spacing_and_hyphenated_codes_without_old_reply(self):
        for text in (
            "Tu código de verificación es ０１２３４５",
            "Código: 0 1 2 3 4 5",
            "Código de acceso: 012-345",
            "Security code: 012345",
            "Código:\u200b 012345",
        ):
            with self.subTest(text=text):
                self.assertEqual(extract_code(text), "012345")
        self.assertEqual(
            extract_code("Código: 012345\nFrom: old\nCódigo: 654321"), "012345"
        )
        self.assertIsNone(extract_code("Código: 1234567"))
        self.assertIsNone(extract_code("Código: 123456. Código: 012345"))

    def test_date_formats_require_timezone_and_support_millisecond_epoch(self):
        self.assertEqual(
            timestamp("2026-10-27T10:00:00Z"),
            timestamp("Tue, 27 Oct 2026 10:00:00 +0000"),
        )
        self.assertEqual(timestamp("1700000000000"), 1700000000)
        self.assertIsNone(timestamp("2026-10-27T10:00:00"))
        self.assertIsNone(timestamp("not a date"))

    def test_unrecognized_list_cannot_start_imss_and_cancellation_prevents_clicks(self):
        r, rows, panes = self.reader()
        rows.clear()
        with self.assertRaises(RuntimeError):
            r.baseline()
        row = Mock()
        row.is_displayed.return_value = True
        row.get_attribute.return_value = "new"
        row.text = "Código de validación"
        rows.append(row)
        r.cancelled = lambda: True
        self.assertIsNone(r.scan(time.time()))
        row.click.assert_not_called()


class WorkflowV2Tests(unittest.TestCase):
    def test_history_matches_real_three_attempt_workflow_and_success(self):
        import test_connected_bots as base

        helper = base.WorkflowTests()
        with tempfile.TemporaryDirectory() as tmp:
            app, connection = helper.workflow(tmp)
            rows = connection.history.rows()
            self.assertEqual(len(rows), 3)
            self.assertEqual({r["resultado"] for r in rows}, {"rechazado"})
            self.assertEqual({r["intento"] for r in rows}, {1, 2, 3})
            self.assertEqual(len({r["solicitud"] for r in rows}), 1)
        with tempfile.TemporaryDirectory() as tmp:
            app, connection = helper.workflow(tmp, reject=False)
            self.assertEqual(connection.history.rows()[0]["resultado"], "completada")

    def test_skip_finishes_reader_job_but_cannot_interrupt_code_already_submitting(
        self,
    ):
        from conexion.imss_link import ImssConnection

        with tempfile.TemporaryDirectory() as tmp:
            c = ImssConnection.__new__(ImssConnection)
            c.app = Mock()
            c.bridge = Bridge(tmp)
            c.active = True
            c.skip = threading.Event()
            c.cancel = threading.Event()
            c.job = c.bridge.create(
                "a@example.test", "INSTANCE", "sender@provider.test", "Código"
            )
            c.bridge.publish(["a@example.test"], True)
            c.bridge.reply(c.job, "code", code="123456")
            for stage in ("consulta", "validando", "tramite"):
                c.stage = stage
                c.skip_current()
                self.assertFalse(c.skip.is_set())
            c.stage = "codigo"
            c.skip_current()
            self.assertTrue(c.skip.is_set())
            self.assertFalse((c.bridge.job(c.job) / "response.json").exists())
            self.assertEqual(
                c.response(c.job, "a@example.test", "INSTANCE", {"code"}, 1)["status"],
                "error",
            )

    def test_confirmed_result_is_preserved_before_accept_can_close_the_dialog(self):
        import test_connected_bots as base

        b = base.bot
        app = b.App.__new__(b.App)
        app.emit = Mock()
        app.events = base.queue.Queue()
        app.foto = Mock(return_value=Path("synthetic.png"))
        nodes = [
            {
                "texto": "La información solicitada se ha enviado a tu correo electrónico.",
                "xy": (1, 1),
                "area": 100,
                "enabled": True,
                "visible": True,
            }
        ]
        with (
            patch.object(b, "tocar_texto", return_value=True),
            patch.object(b, "pantalla", return_value=nodes),
            patch.object(b, "tocar") as touch,
            patch.object(b.time, "sleep"),
        ):
            app.hacer_tramite(
                "console", "1", "INSTANCE", "SYNTHETIC", next(iter(b.TRAMITES))
            )
        self.assertTrue(app.resultado_tramite)
        touch.assert_not_called()

    def test_document_send_waits_for_delayed_confirmation_without_repeating_submission(
        self,
    ):
        import test_connected_bots as base

        b = base.bot
        app = b.App.__new__(b.App)
        app.emit = Mock()
        app.events = base.queue.Queue()
        app.foto = Mock(return_value=Path("synthetic.png"))

        def node(text):
            return [
                {
                    "texto": text,
                    "xy": (1, 1),
                    "area": 100,
                    "enabled": True,
                    "visible": True,
                }
            ]

        screens = [
            node("Procesando"),
            node("Procesando"),
            node("La constancia fue enviada a tu correo"),
        ]
        with (
            patch.object(b, "tocar_texto", return_value=True),
            patch.object(b, "pantalla", side_effect=screens),
            patch.object(b, "tocar") as touch,
            patch.object(b.time, "sleep"),
        ):
            app.hacer_tramite(
                "console", "1", "INSTANCE", "SYNTHETIC", next(iter(b.TRAMITES))
            )
        self.assertTrue(app.resultado_tramite)
        touch.assert_not_called()

    def test_stopping_before_document_step_never_submits_it(self):
        import test_connected_bots as base

        b = base.bot
        app = b.App.__new__(b.App)
        connection = Mock()
        connection.active = True
        connection.cancel.is_set.return_value = True
        app.conexion = connection
        with patch.object(b, "tocar_texto") as touch:
            app.hacer_tramite(
                "console", "1", "INSTANCE", "SYNTHETIC", next(iter(b.TRAMITES))
            )
        self.assertFalse(app.resultado_tramite)
        touch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
