import csv
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

import app as panel
import automation as engine
from core import Account
from history import HistoryStore, FIELDS, GROUPS, group_results


class HistoryTests(unittest.TestCase):
    def test_three_lists_distinguish_entered_issues_and_manual_or_automatic_skip(self):
        rows = [
            {'correo':'ok@example.test','resultado':'Entró a la bandeja'},
            {'correo':'error@example.test','resultado':'No logró entrar','detalle':'Acceso no disponible'},
            {'correo':'limit@example.test','resultado':'Interrumpido','detalle':'Too Many Requests'},
            {'correo':'manual@example.test','resultado':'Omitido'},
            {'correo':'challenge@example.test','resultado':'No logró entrar','detalle':'Verificación adicional: Almost there'},
        ]
        grouped = group_results(rows)
        self.assertEqual([r['correo'] for r in grouped[GROUPS[0]]], ['ok@example.test'])
        self.assertEqual({r['correo'] for r in grouped[GROUPS[1]]}, {'error@example.test','limit@example.test'})
        self.assertEqual({r['correo'] for r in grouped[GROUPS[2]]}, {'manual@example.test','challenge@example.test'})
        self.assertEqual(len(rows),5)

    def test_repeated_account_has_one_latest_result_across_all_lists(self):
        rows = [
            {'correo':'Same@example.test','resultado':'No logró entrar'},
            {'correo':'other@example.test','resultado':'Omitido'},
            {'correo':'same@EXAMPLE.test','resultado':'Entró a la bandeja'},
        ]
        grouped = group_results(rows)
        self.assertEqual(len(grouped[GROUPS[0]]),1)
        self.assertEqual(grouped[GROUPS[1]],[])
        self.assertEqual(len(grouped[GROUPS[2]]),1)
        self.assertEqual(len(rows),3)

    def test_empty_history_and_incomplete_rows_do_not_crash_lists(self):
        self.assertEqual(group_results([]), {name:[] for name in GROUPS})
        grouped = group_results([{'correo':None,'detalle':None},
                                {'correo':'incomplete@example.test','detalle':None}])
        self.assertEqual(len(grouped[GROUPS[1]]),1)

    def test_results_survive_reopening_without_password_fields(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'nested'/'history.csv'
            store = HistoryStore(path)
            store.append('one@example.test', 'Entró a la bandeja', 'Bandeja abierta')
            store.append('two@example.test', 'No logró entrar', 'Verificación adicional')
            rows = HistoryStore(path).read()
            self.assertEqual(len(rows), 2)
            self.assertEqual(tuple(rows[0]), FIELDS)
            self.assertTrue(rows[0]['fecha'])
            self.assertEqual(rows[0]['resultado'], 'Entró a la bandeja')
            self.assertEqual(rows[1]['correo'], 'two@example.test')

    def test_export_csv_preserves_records_and_protects_spreadsheet_formulas(self):
        with tempfile.TemporaryDirectory() as folder:
            source, target = Path(folder)/'log.csv', Path(folder)/'export.csv'
            store = HistoryStore(source)
            store.append('=synthetic@example.test', 'Omitido', 'Usuario')
            store.export(target)
            self.assertEqual(source.read_bytes(), target.read_bytes())
            self.assertEqual(store.read()[0]['correo'], '=synthetic@example.test')
            with target.open(encoding='utf-8-sig', newline='') as stream:
                self.assertTrue(next(csv.DictReader(stream))['correo'].startswith("'="))
            store.export(source)
            self.assertEqual(len(store.read()), 1)

    def test_concurrent_appends_do_not_duplicate_header_or_lose_rows(self):
        with tempfile.TemporaryDirectory() as folder:
            store = HistoryStore(Path(folder)/'log.csv')
            threads = [threading.Thread(target=store.append,
                args=(f'example{i}@example.test','Omitido','Usuario')) for i in range(20)]
            for thread in threads: thread.start()
            for thread in threads: thread.join()
            self.assertEqual(len(store.read()), 20)
            self.assertEqual(len({row['correo'] for row in store.read()}),20)

    def run_account(self, outcome):
        application = panel.App.__new__(panel.App)
        application._stop_event = threading.Event()
        application._skip_event = threading.Event()
        application._post = lambda callback: callback()
        application._account_status = Mock()
        application._finish_run = Mock()
        application.status = Mock()
        application.history_status = Mock()
        account = Account('synthetic@example.test','DO-NOT-LOG-THIS-PASSWORD')
        with tempfile.TemporaryDirectory() as folder:
            application.history = HistoryStore(Path(folder)/'log.csv')
            driver = Mock()
            def login(*args):
                if outcome == 'success':
                    application._stop_event.set()
                    return driver
                if outcome == 'stop':
                    application._stop_event.set()
                    raise engine.SkipRequested()
                raise outcome
            with patch.object(panel,'try_account',side_effect=login):
                application._run_accounts([account],['chrome','edge'])
            raw = application.history.path.read_text(encoding='utf-8-sig')
            self.assertNotIn(account.password, raw)
            return application.history.read()

    def test_success_is_saved_once_before_inbox_is_closed(self):
        rows = self.run_account('success')
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['resultado'],'Entró a la bandeja')

    def test_failed_skipped_and_interrupted_are_distinguished(self):
        for outcome, expected in (
            (engine.LoginFailure('password details must not leak'),'No logró entrar'),
            (engine.VerificationRequired('challenge'),'No logró entrar'),
            (engine.SkipRequested(),'Omitido'),
            (engine.RateLimited('throttle'),'Interrumpido'),
            (RuntimeError('unexpected'),'No logró entrar'),
            ('stop','Interrumpido'),
        ):
            with self.subTest(expected=expected, outcome=type(outcome).__name__):
                self.assertEqual(self.run_account(outcome)[0]['resultado'],expected)

    def test_logging_failure_does_not_abort_browser_work(self):
        application = panel.App.__new__(panel.App)
        application.history = Mock()
        application.history.append.side_effect = PermissionError('not writable')
        application.history_status = Mock()
        application._post = lambda callback: callback()
        application._record_result('synthetic@example.test','Entró a la bandeja','Bandeja abierta')
        application.history_status.set.assert_called_once()


if __name__ == '__main__': unittest.main()
