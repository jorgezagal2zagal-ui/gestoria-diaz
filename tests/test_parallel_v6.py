"""Concurrent handoff and reservations with real bridges and synthetic services."""

from concurrent.futures import ThreadPoolExecutor
import queue
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import gestoria_5_instancias as imss
import outlook_conectado as out
from conexion.batch import BatchStore, QueueInput
from conexion.bridge import Bridge, write_json
from conexion.history import RequestHistory
from conexion.parallel import ConcurrentRunner, EmailLeases, JobEngine
from conexion.result import RequestResult
from conexion.timing import accelerated
from test_batch_v3 import curp, PROCEDURE, INSTANCES


class ReservationTests(unittest.TestCase):
    def test_atomic_claims_never_share_an_instance_or_exceed_three(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = BatchStore(tmp)
            store.import_items([QueueInput(curp(i), PROCEDURE) for i in range(20)])
            with ThreadPoolExecutor(max_workers=10) as executor:
                items = list(
                    executor.map(
                        lambda _: store.claim(INSTANCES, capacity=3), range(10)
                    )
                )
            active = [i for i in items if i]
            self.assertEqual(len(active), 3)
            self.assertEqual(len({i["instancia"] for i in active}), 3)
            self.assertEqual(store.counts()["en_curso"], 3)

    def test_review_blocks_only_its_instance_and_same_curp_is_not_parallelized(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = BatchStore(tmp)
            store.import_items(
                [
                    QueueInput(curp(0), PROCEDURE, INSTANCES[0], "a0@example.test"),
                    QueueInput(curp(0), "Other"),
                    QueueInput(curp(1), PROCEDURE),
                    QueueInput(curp(2), PROCEDURE),
                ]
            )
            first = store.claim(INSTANCES, capacity=3)
            second = store.claim(INSTANCES, capacity=3)
            self.assertNotEqual(first["curp"], second["curp"])
            store.finish(first, RequestResult("sin_confirmar"))
            third = store.claim(INSTANCES, capacity=3)
            self.assertIsNotNone(third)
            self.assertNotEqual(third["instancia"], INSTANCES[0])
            store.resolve(first["id"], "pendiente")
            reset = next(row for row in store.rows() if row["id"] == first["id"])
            self.assertEqual(reset["preferido"], "")

    def test_email_lease_waits_for_release_and_honors_cancellation(self):
        pool = EmailLeases(lambda: set(), lambda: set())
        stop = threading.Event()
        self.assertEqual(
            pool.claim(1, ["a@test.example"], set(), "", stop.is_set), "a@test.example"
        )
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(
                pool.claim, 2, ["a@test.example"], set(), "", stop.is_set
            )
            time.sleep(0.03)
            self.assertFalse(future.done())
            pool.release(1, "a@test.example")
            self.assertEqual(future.result(1), "a@test.example")
        stop.set()
        self.assertIsNone(pool.claim(3, ["a@test.example"], set(), "", stop.is_set))

    def test_queue_refills_a_finished_slot_while_other_requests_stay_active(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = BatchStore(tmp)
            store.import_items([QueueInput(curp(i), PROCEDURE) for i in range(4)])
            started = threading.Barrier(3)
            release = threading.Event()
            fourth = threading.Event()
            live = set()
            peak = [0]
            lock = threading.Lock()

            def execute(item):
                with lock:
                    self.assertNotIn(item["instancia"], live)
                    live.add(item["instancia"])
                    peak[0] = max(peak[0], len(live))
                if item["id"] <= 3:
                    started.wait(2)
                if item["id"] in (2, 3):
                    release.wait(3)
                if item["id"] == 4:
                    fourth.set()
                with lock:
                    live.remove(item["instancia"])
                return RequestResult("completada", 1)

            runner = ConcurrentRunner(store, execute)
            runner.start(INSTANCES)
            self.assertTrue(fourth.wait(3))
            self.assertTrue(runner.running)
            release.set()
            runner.thread.join(3)
            self.assertFalse(runner.running)
            self.assertEqual(peak[0], 3)
            self.assertEqual(store.counts()["completada"], 4)


class Driver:
    def __init__(self, address, audit):
        self.address = address
        self.audit = audit
        self.owner = threading.get_ident()
        self.closed = False
        self.current_url = "https://outlook.live.com/mail/0/inbox"

    def set_page_load_timeout(self, value):
        assert self.owner == threading.get_ident()

    def set_script_timeout(self, value):
        assert self.owner == threading.get_ident()

    def quit(self):
        assert self.owner == threading.get_ident()
        self.closed = True


class EngineTests(unittest.TestCase):
    def fixture(self, tmp):
        app = imss.App.__new__(imss.App)
        app.root = Mock()
        app.events = queue.Queue()
        app.usados_sesion = set()
        app.emit = Mock()
        app.estado = Mock()
        app.unified_mode = True
        for name in (
            "arranque",
            "enviados",
            "bloqueada",
            "sesion",
            "ultimo_abrir",
            "intentos_pin",
        ):
            setattr(app, name, {})
        app.conexion = SimpleNamespace(bridge=Bridge(tmp), history=RequestHistory(tmp))
        app.outlook = SimpleNamespace(
            _record_result=Mock(),
            warm_email=None,
            thread=Mock(),
            commands=queue.SimpleQueue(),
        )
        app.registrar_correo = lambda person, email, *args: app.usados_sesion.add(email)
        events = []
        engine = JobEngine(app, lambda *event: events.append(event))
        accounts = tuple(
            SimpleNamespace(address=f"a{i}@example.test", password="synthetic")
            for i in range(6)
        )
        engine.snapshot = {"path": "console", "timeout": 60, "accounts": accounts}
        items = [
            {
                "id": i + 1,
                "curp": curp(i),
                "instancia": INSTANCES[i],
                "tramite": PROCEDURE,
                "intentos": 0,
                "solicitud": "",
                "preferido": "",
            }
            for i in range(3)
        ]
        return app, engine, items, events

    def test_three_jobs_overlap_and_out_of_order_codes_cannot_cross_requests(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, engine, items, events = self.fixture(tmp)
            prep = threading.Barrier(3)
            login = threading.Barrier(3)
            drivers = []
            received = []
            rejected = set()

            def prepare(worker, *args):
                prep.wait(3)
                return True

            def open_account(account, *args):
                driver = Driver(account.address, [])
                drivers.append(driver)
                return driver

            class Reader:
                last_diagnostic = "synthetic"

                def __init__(self, driver, *args, **kwargs):
                    self.driver = driver

                def baseline(self):
                    if int(self.driver.address[1]) < 3:
                        login.wait(3)

                def scan(self, at):
                    assert self.driver.owner == threading.get_ident()
                    return f"{100000 + int(self.driver.address[1]):06d}"

            def consult(worker, path, person, email, instance, procedure):
                self.assertIn(
                    worker.conexion.bridge.response(worker.conexion.job)["status"],
                    ("ready", "code"),
                )
                worker.registrar_correo(person, email, instance, procedure)
                worker.pendiente = (path, "1", instance, person, email, procedure)

            def enter(worker, code, *pending):
                self.assertEqual(code, f"{100000 + int(pending[4][1]):06d}")
                self.assertEqual(worker.nombres, (pending[2],))
                received.append((pending[3], pending[4], code))
                if pending[3] == curp(0) and pending[3] not in rejected:
                    rejected.add(pending[3])
                    worker.conexion.rejected = True
                    worker.conexion.reset_ready = True
                    worker.pendiente = None
                    return
                worker.pendiente = None
                worker.resultado_tramite = True

            special = Mock()
            special.handle.return_value = None
            with (
                patch.object(imss.App, "preparar_solicitud", prepare),
                patch.object(imss.App, "_consulta", consult),
                patch.object(imss.App, "_codigo", enter),
                patch.object(out, "try_account", side_effect=open_account),
                patch.object(out, "OutlookReader", Reader),
                patch.object(out, "SpecialPages", return_value=special),
                patch("automation.available_browsers", return_value=["edge"]),
                patch("conexion.navigation.prepare_login", return_value=True),
                patch.object(imss, "correos_usados", return_value=set()),
                ThreadPoolExecutor(max_workers=3) as executor,
            ):
                results = list(executor.map(engine.execute, items))
            self.assertTrue(all(r.status == "completada" for r in results), results)
            self.assertEqual(len(received), 4)
            self.assertEqual(len({row[1] for row in received}), 4)
            self.assertEqual(results[0].attempts, 2)
            self.assertEqual([r.attempts for r in results[1:]], [1, 1])
            self.assertTrue(all(d.closed for d in drivers))
            self.assertEqual(engine.leases.owners, {})
            self.assertEqual(engine.contexts, {})

    def test_reader_failure_keeps_inbox_without_rotating_and_other_job_completes(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, engine, items, events = self.fixture(tmp)
            drivers = []
            received = []

            def open_account(account, *args):
                driver = Driver(account.address, [])
                drivers.append(driver)
                return driver

            class Reader:
                last_diagnostic = "synthetic"

                def __init__(self, driver, *args, **kwargs):
                    self.driver = driver

                def baseline(self):
                    if self.driver.address == "a0@example.test":
                        raise RuntimeError(
                            "No se pudo reconocer la lista de mensajes; IMSS no se iniciará."
                        )

                def scan(self, at):
                    return "012345"

            def consult(worker, path, person, email, instance, procedure):
                received.append(email)
                worker.pendiente = (path, "1", instance, person, email, procedure)

            def enter(worker, *args):
                worker.pendiente = None
                worker.resultado_tramite = True

            items[0]["preferido"] = "a0@example.test"
            items[1]["preferido"] = "a1@example.test"
            special = Mock()
            special.handle.return_value = None
            with (
                patch.object(imss.App, "preparar_solicitud", return_value=True),
                patch.object(imss.App, "_consulta", consult),
                patch.object(imss.App, "_codigo", enter),
                patch.object(out, "try_account", side_effect=open_account),
                patch.object(out, "OutlookReader", Reader),
                patch.object(out, "SpecialPages", return_value=special),
                patch("automation.available_browsers", return_value=["edge"]),
                patch("conexion.navigation.prepare_login", return_value=True),
                patch.object(imss, "correos_usados", return_value=set()),
                ThreadPoolExecutor(max_workers=2) as executor,
            ):
                bad = executor.submit(engine.execute, items[0])
                good = executor.submit(engine.execute, items[1])
                try:
                    self.assertEqual(good.result(5).status, "completada")
                    deadline = time.monotonic() + 13
                    while (
                        not any(e[0] == 1 and e[1] == "lector_no_listo" for e in events)
                        and time.monotonic() < deadline
                    ):
                        time.sleep(0.02)
                    self.assertTrue(
                        any(e[0] == 1 and e[1] == "lector_no_listo" for e in events)
                    )
                    self.assertFalse(bad.done())
                    inbox = next(d for d in drivers if d.address == "a0@example.test")
                    self.assertFalse(inbox.closed)
                    self.assertEqual(received, ["a1@example.test"])
                    self.assertEqual(
                        sum(d.address == "a0@example.test" for d in drivers), 1
                    )
                finally:
                    engine.cancel(1)
                self.assertEqual(bad.result(5).status, "lector_no_listo")
            self.assertTrue(all(d.closed for d in drivers))
            self.assertEqual(engine.leases.owners, {})


class FastInteractionTests(unittest.TestCase):
    def test_code_timeout_is_a_reader_error_instead_of_another_login_attempt(self):
        with tempfile.TemporaryDirectory() as tmp:
            bridge = Bridge(tmp)
            key = bridge.create("a0@example.test", "INSTANCE", "", "", 60)
            bridge.started(key)
            write_json(bridge.job(key) / "waiting.json", {"at": time.time() - 61})
            server = out.OutlookWorker()
            server.bridge = bridge
            server.accounts = [
                SimpleNamespace(address="a0@example.test", password="synthetic")
            ]
            server.shutdown = threading.Event()
            server.job_cancel = threading.Event()
            server.accepting = True
            server.manage_buttons = []
            server._post = lambda callback: callback()
            server._record_result = Mock()
            server._account_status = Mock()
            for name in ("start_button", "skip_button", "stop_button", "status"):
                setattr(server, name, Mock())
            reader = Mock()
            reader.last_diagnostic = "synthetic"
            reader.scan.return_value = None
            driver = Driver("a0@example.test", [])
            with (
                patch.object(out, "try_account", return_value=driver) as login,
                patch.object(out, "OutlookReader", return_value=reader),
                patch("automation.available_browsers", return_value=["edge"]),
            ):
                server.process(bridge.pending()[0])
            self.assertEqual(bridge.response(key)["status"], "reader_error")
            login.assert_called_once()

    def test_fast_observation_checks_ready_screen_before_sleeping(self):
        app = imss.App.__new__(imss.App)
        app.fast_mode = True
        with (
            patch.object(imss, "pantalla", return_value=["ready"]),
            patch.object(imss.time, "sleep") as sleep,
        ):
            stream = app.observar("console", "1", 12, 2)
            self.assertEqual(next(stream), ["ready"])
            sleep.assert_not_called()

    def test_fast_otp_keeps_six_digit_readback_and_repairs_a_dropped_digit(self):
        import test_verification_code as otp

        app = otp.bot.App.__new__(otp.bot.App)
        app.emit = Mock()
        app.foto = Mock()
        screen = otp.AdvancingOtpScreen(drop_once=4)
        with (
            patch.object(otp.bot, "pantalla", side_effect=screen.screenshot),
            patch.object(otp.bot, "adb", side_effect=screen.adb),
            patch.object(otp.bot.time, "sleep"),
            accelerated(),
        ):
            self.assertTrue(app.meter_codigo("console", "1", "012345"))
        self.assertEqual("".join(screen.values), "012345")
        self.assertFalse(screen.background_writes)


if __name__ == "__main__":
    unittest.main()
