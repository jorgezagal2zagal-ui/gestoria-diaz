"""Regressions for first-account failures, bounded recovery and queue progress."""

from contextlib import contextmanager
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
from conexion.bridge import Bridge
from conexion.parallel import ConcurrentRunner, EmailLeases, Value
from conexion.unified import OutlookSection
import test_parallel_v6 as v6
from test_batch_v3 import curp, PROCEDURE, INSTANCES


@contextmanager
def services(reader, login, consult, enter, cleanup=True):
    special = SimpleNamespace(handle=lambda: None)
    with (
        patch.object(imss.App, "preparar_solicitud", return_value=True),
        patch.object(imss.App, "_consulta", consult),
        patch.object(imss.App, "_codigo", enter),
        patch.object(out, "try_account", side_effect=login),
        patch.object(out, "OutlookReader", reader),
        patch.object(out, "SpecialPages", return_value=special),
        patch("automation.available_browsers", return_value=["edge"]),
        patch("conexion.navigation.prepare_login", return_value=True),
        patch.object(imss, "correos_usados", return_value=set()),
        patch(
            "conexion.imss_link.ImssConnection.return_to_login", return_value=cleanup
        ) as reset,
    ):
        yield reset


def consult(worker, path, person, email, instance, procedure):
    worker.registrar_correo(person, email, instance, procedure)
    worker.pendiente = (path, "1", instance, person, email, procedure)


def enter(worker, code, *pending):
    assert code == "012345"
    worker.pendiente = None
    worker.resultado_tramite = True


class QueueRecoveryTests(unittest.TestCase):
    def test_four_failed_requests_do_not_pause_the_fifth_healthy_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = BatchStore(tmp)
            store.import_items([QueueInput(curp(i), PROCEDURE) for i in range(5)])
            runner = ConcurrentRunner(
                store,
                lambda item: Request("fallida" if item["id"] <= 4 else "completada"),
            )
            runner.capacity = 1
            runner.start(INSTANCES)
            runner.thread.join(3)
            self.assertFalse(runner.running)
            self.assertEqual(store.counts()["fallida"], 4)
            self.assertEqual(store.counts()["completada"], 1)

    def test_one_request_without_mail_does_not_loop_or_block_another(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = BatchStore(tmp)
            store.import_items([QueueInput(curp(i), PROCEDURE) for i in range(2)])
            called = []

            def execute(item):
                called.append(item["id"])
                return Request("sin_correos" if item["id"] == 1 else "completada")

            runner = ConcurrentRunner(store, execute)
            runner.capacity = 1
            runner.start(INSTANCES)
            runner.thread.join(3)
            self.assertEqual(called, [1, 2])
            self.assertEqual(store.counts()["pendiente"], 1)
            self.assertEqual(store.counts()["completada"], 1)

    def test_no_accounts_preserves_pending_without_starting_or_spinning(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = BatchStore(tmp)
            store.import_items([QueueInput(curp(0), PROCEDURE)])
            execute = Mock()
            runner = ConcurrentRunner(store, execute, can_dispatch=lambda: False)
            runner.start(INSTANCES)
            runner.thread.join(2)
            execute.assert_not_called()
            self.assertEqual(store.counts()["pendiente"], 1)
            self.assertIn("correos disponibles", store.pause_reason())

    def test_unavailable_or_busy_preferred_email_falls_back_to_a_free_one(self):
        leases = EmailLeases(lambda: {"a0@example.test"}, lambda: set())
        self.assertEqual(
            leases.claim(
                1,
                ["a0@example.test", "a1@example.test"],
                set(),
                "a0@example.test",
                lambda: False,
            ),
            "a1@example.test",
        )
        self.assertEqual(
            leases.claim(
                2,
                ["a1@example.test", "a2@example.test"],
                set(),
                "a1@example.test",
                lambda: False,
            ),
            "a2@example.test",
        )

    def test_only_the_exact_legacy_reader_hold_is_recovered_with_budget_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = BatchStore(tmp)
            store.import_items([QueueInput(curp(i), PROCEDURE) for i in range(3)])
            reason = "Bandeja abierta, lector sin confirmar. Revisa la solicitud; no se cambió de cuenta."
            for attempts, text in (
                (1, reason),
                (3, reason),
                (1, "Resultado desconocido"),
            ):
                item = store.claim(INSTANCES, capacity=3)
                store.finish(item, Request("sin_confirmar", attempts, reason=text))
            self.assertEqual(store.recover_reader_blocks(), 1)
            recovered = store.rows()[0]
            self.assertEqual(recovered["estado"], "pendiente")
            self.assertEqual(recovered["intentos"], 1)
            self.assertTrue(recovered["motivo"].startswith("Recuperación del lector:"))
            self.assertEqual(store.counts()["revision"], 2)


class HandoffRecoveryTests(unittest.TestCase):
    def fixture(self, tmp):
        return v6.EngineTests().fixture(tmp)

    def test_three_reader_failures_finish_and_the_next_queued_request_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, engine, items, events = self.fixture(tmp)
            drivers = []

            def login(account, *args):
                d = v6.Driver(account.address, [])
                drivers.append(d)
                return d

            class Reader:
                last_diagnostic = "synthetic"

                def __init__(self, driver, *args, **kwargs):
                    self.person = kwargs["expected_curp"]

                def baseline(self):
                    if self.person == curp(0):
                        raise RuntimeError(
                            "No se pudo reconocer la lista de mensajes; IMSS no se iniciará."
                        )

                def scan(self, at):
                    return "012345"

            store = BatchStore(tmp)
            store.import_items([QueueInput(curp(i), PROCEDURE) for i in range(2)])
            runner = ConcurrentRunner(
                store, engine.execute, can_dispatch=engine.has_mailboxes
            )
            runner.capacity = 1
            with services(Reader, login, consult, enter):
                runner.start(INSTANCES)
                try:
                    runner.thread.join(7)
                    self.assertFalse(runner.running)
                finally:
                    runner.stop()
                    engine.cancel()
                    runner.thread.join(3)
            rows = store.rows()
            self.assertEqual([r["estado"] for r in rows], ["fallida", "completada"])
            self.assertEqual(rows[0]["intentos"], 3)
            self.assertEqual(len(drivers), 4)
            self.assertTrue(all(d.closed for d in drivers))
            self.assertEqual(engine.leases.owners, {})

    def test_refresh_of_the_same_inbox_recovers_without_another_login(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, engine, items, events = self.fixture(tmp)
            drivers = []

            def login(account, *args):
                d = v6.Driver(account.address, [])
                drivers.append(d)
                return d

            class Reader:
                last_diagnostic = "synthetic"

                def __init__(self, driver, *args, **kwargs):
                    self.driver = driver

                def baseline(self):
                    if not self.driver.refreshes:
                        raise RuntimeError("Loading")

                def scan(self, at):
                    return "012345"

            with services(Reader, login, consult, enter):
                result = engine.execute(items[0])
            self.assertEqual(result.status, "completada")
            self.assertEqual(len(drivers), 1)
            self.assertEqual(drivers[0].refreshes, 1)
            self.assertEqual(result.attempts, 1)

    def test_reader_failure_after_code_request_retries_only_after_known_cancellation(
        self,
    ):
        for safe in (True, False):
            with self.subTest(safe=safe), tempfile.TemporaryDirectory() as tmp:
                app, engine, items, events = self.fixture(tmp)
                drivers = []

                def login(account, *args):
                    d = v6.Driver(account.address, [])
                    drivers.append(d)
                    return d

                class Reader:
                    last_diagnostic = "synthetic"

                    def __init__(self, driver, *args, **kwargs):
                        self.driver = driver

                    def baseline(self):
                        pass

                    def scan(self, at):
                        if self.driver.address == "a0@example.test":
                            raise RuntimeError("View changed")
                        return "012345"

                with services(Reader, login, consult, enter, cleanup=safe) as reset:
                    result = engine.execute(items[0])
                self.assertEqual(
                    result.status, "completada" if safe else "sin_confirmar"
                )
                self.assertEqual(len(drivers), 2 if safe else 1)
                reset.assert_called_once()
                self.assertTrue(all(d.closed for d in drivers))

    def test_recovered_v6_request_cleans_only_known_code_screen_before_resuming(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, engine, items, events = self.fixture(tmp)
            item = items[0]
            item["intentos"] = 1
            item["motivo"] = "Recuperación del lector: comprobar acceso"
            order = []

            class Reader:
                last_diagnostic = "synthetic"

                def __init__(self, *args, **kwargs):
                    pass

                def baseline(self):
                    pass

                def scan(self, at):
                    return "012345"

            def login(account, *args):
                return v6.Driver(account.address, [])

            def request(worker, *args):
                order.append("consulta")
                consult(worker, *args)

            with (
                services(Reader, login, request, enter) as reset,
                patch.object(
                    imss, "listar", return_value={item["instancia"]: {"index": "1"}}
                ),
            ):
                reset.side_effect = lambda *args: order.append("cancelar") or True
                result = engine.execute(item)
            self.assertEqual(result.status, "completada")
            self.assertEqual(order, ["cancelar", "consulta"])
            self.assertEqual(result.attempts, 1)


class ManualOutlookRecoveryTests(unittest.TestCase):
    def exercise(self, error, success=True):
        with tempfile.TemporaryDirectory() as tmp:
            o = OutlookSection.__new__(OutlookSection)
            o.accounts = [
                SimpleNamespace(address=f"a{i}@example.test", password="synthetic")
                for i in range(5)
            ]
            o.bridge = Bridge(tmp)
            o.email = Value("a0@example.test")
            o.status = Value()
            o.active_email = Value()
            o.connection = SimpleNamespace(
                active=False,
                preferred_email=Value("a0@example.test"),
                batch=SimpleNamespace(runner=SimpleNamespace(running=False)),
            )
            o._running = False
            o.mailbox_opening = threading.Event()
            o.shutdown = threading.Event()
            o.job_cancel = threading.Event()
            o.accepting = True
            o.warm_driver = None
            o.warm_email = None
            o.commands = queue.SimpleQueue()
            o._post = lambda cb: cb()
            o._record_result = Mock()
            o._account_status = Mock()
            o.activate_for_request = lambda: True
            attempted = []
            drivers = []

            def login(account, *args):
                attempted.append(account.address)
                if len(attempted) == 1 or not success:
                    raise error
                driver = v6.Driver(account.address, [])
                drivers.append(driver)
                return driver

            with (
                patch.object(out, "try_account", side_effect=login),
                patch("automation.available_browsers", return_value=["edge"]),
            ):
                o.open_mailbox()
                o.thread = threading.Thread(target=o.listen, daemon=True)
                o.thread.start()
                deadline = time.monotonic() + 4
                try:
                    while o.mailbox_opening.is_set() and time.monotonic() < deadline:
                        time.sleep(0.02)
                    self.assertFalse(o.mailbox_opening.is_set())
                    chosen = o.connection.preferred_email.get()
                finally:
                    o.shutdown.set()
                    o.job_cancel.set()
                    o.thread.join(3)
            self.assertFalse(o.thread.is_alive())
            self.assertTrue(all(d.closed for d in drivers))
            return attempted, chosen

    def test_manual_first_login_failure_moves_to_next_email_and_syncs_selection(self):
        attempted, chosen = self.exercise(RuntimeError("Login failed"))
        self.assertEqual(attempted, ["a0@example.test", "a1@example.test"])
        self.assertEqual(chosen, "a1@example.test")

    def test_manual_all_failures_are_bounded_to_three_accounts(self):
        attempted, chosen = self.exercise(RuntimeError("Login failed"), success=False)
        self.assertEqual(len(attempted), 3)

    def test_rate_limit_stops_manual_retries_instead_of_changing_accounts(self):
        from automation import RateLimited

        attempted, chosen = self.exercise(RateLimited("Limited"))
        self.assertEqual(len(attempted), 1)


from conexion.result import RequestResult as Request

if __name__ == "__main__":
    unittest.main()
