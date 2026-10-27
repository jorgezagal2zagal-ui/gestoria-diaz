import csv
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

from conexion.batch import BatchStore, BatchRunner, QueueInput, parse_batch, valid_curp
from conexion.bridge import Bridge, read_json, write_json
from conexion.health import MailboxHealth
from conexion.result import RequestResult
from conexion.navigation import prepare_login

PROCEDURE = "Constancia de semanas cotizadas"
INSTANCES = ("GESTORIA_DIAZ_001", "GESTORIA_DIAZ_002", "GESTORIA_DIAZ_003")


def curp(n):
    prefix = "".join(chr(65 + (n // 26**i) % 26) for i in range(4))
    return prefix + "900101HDFBCD00"


def inputs(n):
    return [QueueInput(curp(i), PROCEDURE) for i in range(n)]


class ImportTests(unittest.TestCase):
    def test_txt_normalization_and_duplicate_detection(self):
        rows, dups = parse_batch(
            f"{curp(0).lower()}\n# comment\n{curp(1)}\n{curp(0)}",
            PROCEDURE,
            [PROCEDURE],
            INSTANCES,
        )
        self.assertEqual(len(rows), 2)
        self.assertEqual(dups, 1)
        self.assertFalse(valid_curp("AAAA909932HDFBCD00"))

    def test_csv_can_pin_instances_and_preserve_quoted_procedure(self):
        data = f'curp;tramite;instancia\n{curp(0)};"{PROCEDURE}";{INSTANCES[1]}\n'
        rows, _ = parse_batch(data, PROCEDURE, [PROCEDURE], INSTANCES, csv_file=True)
        self.assertEqual(rows[0].instance, INSTANCES[1])

    def test_invalid_files_are_rejected_before_any_import(self):
        for data, csv_file in [
            (curp(0) + "\nINVALID", False),
            ("correo,password\na@b.test,secret", True),
            (f"curp,instancia\n{curp(0)},OTHER", True),
            (f"curp,tramite\n{curp(0)},UNKNOWN", True),
        ]:
            with self.subTest(csv=csv_file), self.assertRaises(ValueError):
                parse_batch(data, PROCEDURE, [PROCEDURE], INSTANCES, csv_file)

    def test_ten_thousand_items_import_atomically_and_ui_pages_stay_bounded(self):
        with tempfile.TemporaryDirectory() as tmp:
            rows, duplicates = parse_batch(
                "\n".join(curp(i) for i in range(10000)),
                PROCEDURE,
                [PROCEDURE],
                INSTANCES,
            )
            self.assertEqual(duplicates, 0)
            store = BatchStore(tmp)
            self.assertEqual(store.import_items(rows), (10000, 0))
            self.assertEqual(store.import_items(rows), (0, 10000))
            self.assertEqual(store.counts()["pendiente"], 10000)
            self.assertEqual(len(store.rows()), 100)
            self.assertEqual(len(store.rows(offset=9900)), 100)
            with self.assertRaises(ValueError):
                parse_batch(
                    "\n".join(curp(i) for i in range(10001)),
                    PROCEDURE,
                    [PROCEDURE],
                    INSTANCES,
                )

    def test_failed_transaction_does_not_insert_partial_batch(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = BatchStore(tmp)
            with self.assertRaises(ValueError):
                s.import_items([inputs(1)[0], QueueInput("INVALID", PROCEDURE)])
            self.assertEqual(sum(s.counts().values()), 0)


class QueueTests(unittest.TestCase):
    def test_claim_is_exclusive_and_rotates_instances(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = BatchStore(tmp)
            s.import_items(inputs(3))
            claimed = []

            def worker():
                claimed.append(s.claim(INSTANCES))

            threads = [threading.Thread(target=worker) for _ in range(4)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(5)
            self.assertEqual(len([r for r in claimed if r]), 1)
            row = next(r for r in claimed if r)
            self.assertEqual(row["instancia"], INSTANCES[0])
            s.finish(
                row,
                RequestResult(
                    "completada", 1, "a@example.test", "Confirmed", "request"
                ),
            )
            row = s.claim(INSTANCES)
            self.assertEqual(row["instancia"], INSTANCES[1])

    def test_interrupted_work_requires_manual_resolution_before_next_claim(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = BatchStore(tmp)
            s.import_items(inputs(2))
            row = s.claim(INSTANCES)
            self.assertEqual(s.recover_interrupted(), 1)
            self.assertIsNone(s.claim(INSTANCES))
            self.assertEqual(s.counts()["revision"], 1)
            s.resolve(row["id"], "completada")
            self.assertEqual(s.claim(INSTANCES)["curp"], curp(1))

    def test_no_mailboxes_keeps_current_request_pending(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = BatchStore(tmp)
            s.import_items(inputs(2))
            row = s.claim(INSTANCES)
            self.assertEqual(
                s.finish(row, RequestResult("sin_correos", reason="No accounts")),
                "pendiente",
            )
            self.assertEqual(s.counts()["pendiente"], 2)

    def test_throttle_before_submission_is_pending_but_after_submission_requires_review(
        self,
    ):
        for submitted, expected in [(False, "pendiente"), (True, "revision")]:
            with (
                self.subTest(submitted=submitted),
                tempfile.TemporaryDirectory() as tmp,
            ):
                s = BatchStore(tmp)
                s.import_items(inputs(1))
                row = s.claim(INSTANCES)
                self.assertEqual(
                    s.finish(row, RequestResult("limited", submitted=submitted)),
                    expected,
                )

    def test_completed_rows_cannot_be_implicitly_requeued_and_export_is_complete(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = BatchStore(tmp)
            s.import_items(inputs(2))
            row = s.claim(INSTANCES)
            s.finish(
                row,
                RequestResult(
                    "completada", 3, "example@example.test", "sent", "REQUEST"
                ),
            )
            with self.assertRaises(ValueError):
                s.resolve(row["id"], "pendiente")
            self.assertEqual(s.cancel_pending(), 1)
            p = Path(tmp) / "results.csv"
            s.export(p)
            with p.open(encoding="utf-8-sig") as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["intentos"], "3")
            self.assertEqual(rows[1]["estado"], "cancelada")


class RunnerTests(unittest.TestCase):
    def run_batch(self, store, execute):
        r = BatchRunner(store, execute)
        r.start(INSTANCES, 0)
        r.thread.join(10)
        self.assertFalse(r.running)
        return r

    def test_large_synthetic_flow_is_serial_and_every_result_is_correlated(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = BatchStore(tmp)
            s.import_items(inputs(500))
            seen = []
            active = 0

            def execute(item):
                nonlocal active
                active += 1
                self.assertEqual(active, 1)
                self.assertEqual(s.counts()["en_curso"], 1)
                seen.append((item["id"], item["curp"], item["instancia"]))
                active -= 1
                return RequestResult(
                    "completada",
                    1,
                    f"example{item['id']}@example.test",
                    "simulated",
                    f"request{item['id']}",
                    True,
                )

            self.run_batch(s, execute)
            self.assertEqual(s.counts()["completada"], 500)
            self.assertEqual(len({r[1] for r in seen}), 500)
            self.assertEqual([r[2] for r in seen[:3]], list(INSTANCES))

    def test_three_failures_pause_the_rest_of_the_queue(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = BatchStore(tmp)
            s.import_items(inputs(10))
            self.run_batch(
                s, lambda item: RequestResult("fallida", 3, reason="Rejected")
            )
            self.assertEqual(s.counts()["fallida"], 3)
            self.assertEqual(s.counts()["pendiente"], 7)
            self.assertIn("Tres", s.pause_reason())

    def test_unknown_external_result_never_advances_to_another_curp(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = BatchStore(tmp)
            s.import_items(inputs(5))
            execute = Mock(
                return_value=RequestResult("sin_confirmar", 1, submitted=True)
            )
            runner = self.run_batch(s, execute)
            execute.assert_called_once()
            self.assertEqual(s.counts()["revision"], 1)
            with self.assertRaises(ValueError):
                runner.start(INSTANCES, 0)

    def test_pause_after_current_preserves_pending_and_resume_does_not_repeat_completed(
        self,
    ):
        with tempfile.TemporaryDirectory() as tmp:
            s = BatchStore(tmp)
            s.import_items(inputs(3))
            seen = []
            holder = {}

            def execute(item):
                seen.append(item["id"])
                if len(seen) == 1:
                    holder["runner"].pause()
                return RequestResult("completada")

            runner = BatchRunner(s, execute)
            holder["runner"] = runner
            runner.start(INSTANCES, 0)
            runner.thread.join(5)
            self.assertEqual(s.counts()["completada"], 1)
            self.assertEqual(s.counts()["pendiente"], 2)
            runner.start(INSTANCES, 0)
            runner.thread.join(5)
            self.assertEqual(seen, [1, 2, 3])
            self.assertEqual(s.counts()["completada"], 3)

    def test_worker_error_and_shutdown_do_not_replay_current_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = BatchStore(tmp)
            s.import_items(inputs(3))

            def execute(item):
                raise RuntimeError("synthetic")

            self.run_batch(s, execute)
            self.assertEqual(s.counts()["revision"], 1)
            self.assertEqual(s.counts()["pendiente"], 2)


class CatalogAndHealthTests(unittest.TestCase):
    def test_fifty_thousand_accounts_use_a_small_heartbeat_and_unchanged_catalog(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = Bridge(tmp)
            addresses = [f"example{i}@example.test" for i in range(50000)]
            b.publish(addresses, True)
            catalog = Path(tmp) / "cuentas.json"
            stamp = catalog.stat().st_mtime_ns
            self.assertLess((Path(tmp) / "outlook.json").stat().st_size, 1024)
            self.assertGreater(catalog.stat().st_size, 65536)
            self.assertEqual(len(b.presence()["emails"]), 50000)
            b.publish(addresses, True)
            self.assertEqual(catalog.stat().st_mtime_ns, stamp)
            with self.assertRaises(ValueError):
                b.publish(addresses + ["extra@example.test"], True)

    def test_expired_and_wrong_version_catalog_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = Bridge(tmp)
            b.publish(["a@example.test"], True)
            info = read_json(Path(tmp) / "outlook.json")
            info["protocol"] = 2
            write_json(Path(tmp) / "outlook.json", info)
            self.assertIsNone(b.presence())

    def test_bad_mailboxes_are_temporarily_excluded_and_success_clears_them(self):
        with tempfile.TemporaryDirectory() as tmp:
            h = MailboxHealth(tmp)
            h.block("A@example.test", "login", 600)
            self.assertEqual(h.excluded(), {"a@example.test"})
            with patch("conexion.health.time.time", return_value=time.time() + 601):
                self.assertEqual(h.excluded(), set())
            h.clear("a@example.test")
            self.assertEqual(h.excluded(), set())


class NavigationTests(unittest.TestCase):
    def node(self, text="", rid="", xy=(10, 10)):
        return {
            "texto": text,
            "valor": text,
            "descripcion": text,
            "rid": rid,
            "xy": xy,
            "enabled": True,
            "visible": True,
            "area": 1000,
            "clase": "android.widget.TextView",
        }

    def test_known_session_logs_out_through_visible_menu_and_returns_to_login(self):
        import test_connected_bots as base

        bot = base.bot
        app = bot.App.__new__(bot.App)
        screens = [
            [self.node("Tramita"), self.node("Abrir menú", xy=(1, 1))],
            [self.node("Cerrar sesión", xy=(2, 2))],
            [self.node("¿Deseas cerrar la sesión?"), self.node("Sí", xy=(3, 3))],
            [self.node(rid="p:id/txtCURP"), self.node(rid="p:id/txtCorreo")],
        ]
        with (
            patch.object(
                bot,
                "listar",
                return_value={"INSTANCE": {"android": True, "index": "1"}},
            ),
            patch.object(bot, "abrir_app"),
            patch.object(bot, "pantalla", side_effect=screens),
            patch.object(bot, "tocar") as touch,
        ):
            self.assertTrue(
                prepare_login(
                    app, "console", "INSTANCE", lambda: False, lambda seconds: False
                )
            )
        self.assertEqual(
            [c.args[2] for c in touch.call_args_list], [(1, 1), (2, 2), (3, 3)]
        )

    def test_unknown_or_pending_validation_is_not_blindly_cancelled(self):
        import test_connected_bots as base

        bot = base.bot
        app = bot.App.__new__(bot.App)
        for text in ("Pantalla desconocida", "Código de validación"):
            with (
                patch.object(
                    bot,
                    "listar",
                    return_value={"INSTANCE": {"android": True, "index": "1"}},
                ),
                patch.object(bot, "abrir_app"),
                patch.object(bot, "pantalla", return_value=[self.node(text)]),
                patch.object(bot, "tocar") as touch,
            ):
                self.assertFalse(
                    prepare_login(
                        app, "console", "INSTANCE", lambda: False, lambda seconds: False
                    )
                )
                touch.assert_not_called()


class ConnectedBatchTests(unittest.TestCase):
    def test_queue_connects_four_curps_through_six_mailboxes_without_crossing_codes(
        self,
    ):
        import queue as queues
        from types import SimpleNamespace
        import test_connected_bots as base
        import outlook_conectado as out
        import automation
        from conexion.batch_ui import BatchPanel
        from conexion.imss_link import ImssConnection
        from conexion.history import RequestHistory

        class FastEvent(threading.Event):
            def wait(self, timeout=None):
                return super().wait(min(timeout or 0.005, 0.005))

        with tempfile.TemporaryDirectory() as tmp:
            bridge = Bridge(tmp)
            store = BatchStore(tmp)
            store.import_items(inputs(4))
            server = out.ConnectedOutlook.__new__(out.ConnectedOutlook)
            server.bridge = bridge
            server.accepting = True
            server.shutdown = FastEvent()
            server.job_cancel = FastEvent()
            server.accounts = [
                SimpleNamespace(
                    address=f"example{i}@example.test", password="synthetic"
                )
                for i in range(10)
            ]
            server._post = lambda cb: cb()
            server._account_status = Mock()
            server._record_result = Mock()
            server.manage_buttons = []
            server.start_button = Mock()
            server.stop_button = Mock()
            server.skip_button = Mock()
            server.status = Mock()
            app = base.bot.App.__new__(base.bot.App)
            app.emit = Mock()
            app.events = queues.Queue()
            app.root = Mock()
            app.root.after.side_effect = lambda delay, cb: cb()
            app.btn_consulta = Mock()
            app.btn_codigo = Mock()
            app.selector_cantidad = Mock()
            app.codigo = Mock()
            app.usados_sesion = set()
            app.pendiente = None
            c = ImssConnection.__new__(ImssConnection)
            c.app = app
            c.bridge = bridge
            c.history = RequestHistory(tmp)
            c.active = False
            c.cancel = FastEvent()
            c.skip = FastEvent()
            c.job = None
            panel = BatchPanel.__new__(BatchPanel)
            panel.app = app
            panel.connection = c
            panel.snapshot = {
                "path": "console",
                "sender": "sender@provider.test",
                "subject": "Código",
                "timeout": 180,
            }
            runner = BatchRunner(store, panel.execute)
            panel.runner = runner
            contexts = []

            def consult(path, person, email, instance, procedure):
                self.assertIn(bridge.response(c.job)["status"], ("ready", "code"))
                contexts.append((person, email, instance))
                app.usados_sesion.add(email)
                app.pendiente = (path, "1", instance, person, email, procedure)

            app._consulta = Mock(side_effect=consult)

            def enter(code, *pending):
                self.assertEqual(
                    pending[2:5], (contexts[-1][2], contexts[-1][0], contexts[-1][1])
                )
                self.assertEqual(code, "870621")
                app.pendiente = None
                if app._codigo.call_count <= 2:
                    c.rejected = True
                    c.reset_ready = True
                else:
                    app.resultado_tramite = True

            app._codigo = Mock(side_effect=enter)
            fake_reader = Mock()
            fake_reader.scan.return_value = "870621"
            fake_reader.last_diagnostic = "synthetic"
            fake_special = Mock()
            fake_special.handle.return_value = None
            drivers = []

            def login(*args):
                driver = Mock()
                drivers.append(driver)
                return driver

            def pulse():
                while not server.shutdown.wait(0.01):
                    bridge.publish([a.address for a in server.accounts], True)

            bridge.publish([a.address for a in server.accounts], True)
            with (
                patch.object(out, "try_account", side_effect=login),
                patch.object(out, "OutlookReader", return_value=fake_reader),
                patch.object(out, "SpecialPages", return_value=fake_special),
                patch.object(automation, "available_browsers", return_value=["chrome"]),
                patch.object(base.bot, "correos_usados", return_value=set()),
                patch("conexion.navigation.prepare_login", return_value=True),
            ):
                worker = threading.Thread(target=server.listen)
                heartbeat = threading.Thread(target=pulse)
                worker.start()
                heartbeat.start()
                try:
                    runner.start(INSTANCES, 0)
                    runner.thread.join(10)
                    self.assertFalse(runner.running)
                finally:
                    runner.stop()
                    c.cancel.set()
                    server.shutdown.set()
                    server.job_cancel.set()
                    worker.join(3)
                    heartbeat.join(3)
            self.assertEqual(store.counts()["completada"], 4)
            self.assertEqual(len(contexts), 6)
            self.assertEqual(len({x[1] for x in contexts}), 6)
            self.assertEqual([x[0] for x in contexts[:3]], [curp(0)] * 3)
            for driver in drivers:
                driver.quit.assert_called_once()
            self.assertEqual(list(Path(tmp).glob("solicitudes/*/response.json")), [])
            rows = store.rows()
            self.assertEqual([r["intentos"] for r in rows], [3, 1, 1, 1])

    def test_stop_race_before_worker_submission_never_starts_an_imss_request(self):
        from types import SimpleNamespace
        from conexion.batch_ui import BatchPanel

        panel = BatchPanel.__new__(BatchPanel)
        panel.runner = SimpleNamespace(stopping=threading.Event())
        panel.connection = SimpleNamespace(
            batch_mode=False,
            active=False,
            cancel=Mock(),
            skip=threading.Event(),
            run=Mock(),
        )
        panel.connection.cancel.clear.side_effect = panel.runner.stopping.set
        panel.app = SimpleNamespace(busy=False, root=Mock())
        panel.snapshot = {"timeout": 180}
        result = panel.execute({"id": 1})
        self.assertEqual(result.status, "detenida")
        panel.connection.run.assert_not_called()
        self.assertFalse(panel.connection.active)
        self.assertFalse(panel.app.busy)


class ResumeBudgetTests(unittest.TestCase):
    def test_paused_request_keeps_total_attempts_and_the_last_slot_uses_same_request_id(
        self,
    ):
        from types import SimpleNamespace
        from conexion.batch_ui import BatchPanel

        with tempfile.TemporaryDirectory() as tmp:
            store = BatchStore(tmp)
            store.import_items(inputs(1))
            item = store.claim(INSTANCES)
            store.finish(
                item,
                RequestResult(
                    "sin_correos",
                    2,
                    "example@example.test",
                    "Pool exhausted",
                    "PERSISTED",
                    True,
                ),
            )
            item = store.claim(INSTANCES)
            self.assertEqual(item["intentos"], 2)
            connection = SimpleNamespace(
                cancel=threading.Event(), skip=threading.Event()
            )

            def execute(*args):
                self.assertEqual(connection.current_max_attempts, 1)
                self.assertEqual(connection.attempt_offset, 2)
                self.assertEqual(connection.current_request_id, "PERSISTED")
                connection.last_result = RequestResult(
                    "completada", 1, "last@example.test", "sent", "PERSISTED", True
                )

            connection.run = execute
            panel = BatchPanel.__new__(BatchPanel)
            panel.connection = connection
            panel.app = SimpleNamespace(
                busy=False,
                root=Mock(),
                btn_consulta=Mock(),
                btn_codigo=Mock(),
                selector_cantidad=Mock(),
            )
            panel.runner = SimpleNamespace(stopping=threading.Event())
            panel.snapshot = {
                "path": "console",
                "sender": "sender@provider.test",
                "subject": "Código",
                "timeout": 180,
            }
            result = panel.execute(item)
            store.finish(item, result)
            row = store.rows()[0]
            self.assertEqual(row["intentos"], 3)
            self.assertEqual(row["solicitud"], "PERSISTED")
            self.assertEqual(row["estado"], "completada")

    def test_connector_resumes_only_one_remaining_mailbox_and_journals_attempt_three(
        self,
    ):
        import test_connected_bots as base
        from conexion.imss_link import ImssConnection

        original = ImssConnection.run

        def remaining(connection, *args):
            connection.current_max_attempts = 1
            connection.attempt_offset = 2
            connection.current_request_id = "PERSISTED"
            return original(connection, *args)

        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(ImssConnection, "run", new=remaining),
        ):
            app, c = base.WorkflowTests().workflow(tmp, reject=True)
            app._codigo.assert_called_once()
            app._consulta.assert_called_once()
            self.assertEqual(c.last_result.attempts, 1)
            self.assertEqual(c.history.rows()[0]["intento"], 3)
            self.assertEqual(c.history.rows()[0]["solicitud"], "PERSISTED")

    def test_successful_batch_does_not_generate_thousands_of_unnecessary_screenshots(
        self,
    ):
        import test_connected_bots as base
        from types import SimpleNamespace

        bot = base.bot
        app = bot.App.__new__(bot.App)
        app.emit = Mock()
        app.events = base.queue.Queue()
        app.foto = Mock()
        app.conexion = SimpleNamespace(
            active=True,
            batch_mode=True,
            cancel=threading.Event(),
            tramite_started=Mock(),
        )
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
            patch.object(bot, "tocar_texto", return_value=True),
            patch.object(bot, "pantalla", return_value=nodes),
            patch.object(bot.time, "sleep"),
        ):
            app.hacer_tramite(
                "console", "1", "INSTANCE", "SYNTHETIC", next(iter(bot.TRAMITES))
            )
        self.assertTrue(app.resultado_tramite)
        app.foto.assert_not_called()


class SharedMailboxTests(unittest.TestCase):
    def test_explicit_email_is_selected_in_both_bots_before_imss_starts(self):
        import test_connected_bots as base
        from conexion.imss_link import ImssConnection

        original = ImssConnection.run

        def selected(connection, *args):
            connection.current_preferred_email = "example3@example.test"
            return original(connection, *args)

        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(ImssConnection, "run", new=selected),
        ):
            app, c = base.WorkflowTests().workflow(tmp, reject=False)
            self.assertEqual(app._consulta.call_args.args[2], "example3@example.test")
            self.assertEqual(app._codigo.call_args.args[5], "example3@example.test")

    def test_rejected_selected_mailbox_rotates_both_bots_from_that_position(self):
        import test_connected_bots as base
        from conexion.imss_link import ImssConnection

        original = ImssConnection.run

        def selected(connection, *args):
            connection.current_preferred_email = "example3@example.test"
            return original(connection, *args)

        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(ImssConnection, "run", new=selected),
        ):
            app, c = base.WorkflowTests().workflow(tmp, reject=True)
            self.assertEqual(
                [call.args[2] for call in app._consulta.call_args_list],
                [
                    "example3@example.test",
                    "example4@example.test",
                    "example0@example.test",
                ],
            )
            self.assertEqual(
                [call.args[5] for call in app._codigo.call_args_list],
                [
                    "example3@example.test",
                    "example4@example.test",
                    "example0@example.test",
                ],
            )


if __name__ == "__main__":
    unittest.main()
