import csv
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from bot_imss_adb.accounts import Account, Catalog, export_addresses, parse_accounts
from bot_imss_adb.correo import automation
from bot_imss_adb.flow import Job
from bot_imss_adb.mail_service import OutlookMailbox
from bot_imss_adb.storage import History, MAIL_GROUPS, atomic_text

JOB = Job("AAAA900101HDFBCD00", "synthetic@example.test")


class AccountTests(unittest.TestCase):
    def test_original_account_format_delimiters_and_password_with_colon(self):
        rows = parse_accounts("\ufeff# comment\nAccount: a@example.test:secret:with:colon\nb@example.test|other\nc@example.test\n")
        self.assertEqual([(a.address, a.password) for a in rows], [("a@example.test", "secret:with:colon"), ("b@example.test", "other"), ("c@example.test", "")])
        self.assertNotIn("secret", repr(rows))

    def test_invalid_or_duplicate_input_does_not_partially_mutate_catalog(self):
        catalog = Catalog()
        catalog.merge([Account("original@example.test", "old")])
        for text in ("a@example.test:pw\nbad", "A@example.test:pw\na@example.test:other", "a@example.test:"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                catalog.merge(parse_accounts(text))
            self.assertEqual(list(catalog.accounts), ["original@example.test"])

    def test_merging_blank_password_preserves_known_credentials(self):
        catalog = Catalog()
        catalog.merge([Account("a@example.test", "known")])
        catalog.merge([Account("A@example.test")])
        self.assertEqual(catalog.get("A@EXAMPLE.TEST").password, "known")
        catalog.merge([Account("A@example.test", "updated")])
        self.assertEqual(catalog.get("a@example.test").password, "updated")

    def test_next_skips_omitted_and_does_not_return_current(self):
        catalog = Catalog()
        catalog.merge([Account(f"a{i}@example.test", "pw") for i in range(3)])
        catalog.omitted.add("a1@example.test")
        self.assertEqual(catalog.next("a0@example.test").address, "a2@example.test")
        catalog.omitted.add("a2@example.test")
        self.assertIsNone(catalog.next("a0@example.test"))

    def test_loaded_and_selected_txt_exports_are_address_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            catalog = Catalog()
            catalog.merge([Account("a@example.test", "SYNTHETIC_SECRET"), Account("b@example.test", "OTHER_SECRET")])
            path = Path(tmp)/"correos.txt"
            self.assertEqual(catalog.export(path), 2)
            self.assertEqual(path.read_text(), "a@example.test\nb@example.test\n")
            self.assertEqual(catalog.export(path, ["B@EXAMPLE.TEST"]), 1)
            self.assertEqual(path.read_text(), "b@example.test\n")
            export_addresses(path, ["a@example.test", "A@example.test"])
            self.assertEqual(path.read_text(), "a@example.test\n")


class MailExportTests(unittest.TestCase):
    def test_lists_use_latest_mail_result_case_insensitively(self):
        with tempfile.TemporaryDirectory() as tmp:
            h = History(tmp)
            h.record_mail("a@example.test", "No logró entrar", "No accedió")
            h.record_mail("A@example.test", "Entró a la bandeja", "Sí accedió")
            h.record_mail("b@example.test", "Interrumpido", "Límite")
            h.record_mail("c@example.test", "Omitido", "Usuario")
            groups = h.mail_groups()
            self.assertEqual([len(groups[k]) for k in MAIL_GROUPS], [1, 1, 1])
            self.assertEqual(groups[MAIL_GROUPS[0]][0][1], "A@example.test")

    def test_histories_export_every_record_beyond_display_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            h = History(tmp)
            with h.connect() as db:
                db.executemany("INSERT INTO solicitudes VALUES (?,?,?,?,?,?,?,?)", [(str(i), "2026-10-27", JOB.curp, f"a{i}@example.test", "emulator-5554", "revision", "Prueba", "{}") for i in range(620)])
                db.executemany("INSERT INTO correos (fecha,correo,resultado,detalle) VALUES (?,?,?,?)", [("2026-10-27", f"a{i}@example.test", "Omitido", "Prueba") for i in range(620)])
            self.assertEqual(len(h.recent()), 500)
            for filename, exporter in (("imss.csv", h.export), ("outlook.csv", h.export_mail)):
                path = Path(tmp)/filename
                exporter(path)
                with path.open(encoding="utf-8-sig", newline="") as source:
                    self.assertEqual(len(list(csv.reader(source))), 621)
            self.assertEqual(len(h.mail_groups()[MAIL_GROUPS[2]]), 620)

    def test_imss_failure_does_not_reclassify_successful_outlook_access(self):
        with tempfile.TemporaryDirectory() as tmp:
            h = History(tmp)
            h.record_mail(JOB.email, "Entró a la bandeja", "Acceso confirmado")
            ident = h.start(JOB, "emulator-5554")
            h.finish(ident, "revision", "IMSS rechazó el código", {})
            self.assertEqual(len(h.mail_groups()[MAIL_GROUPS[0]]), 1)
            self.assertEqual(len(h.mail_groups()[MAIL_GROUPS[1]]), 0)

    def test_existing_v1_database_migrates_without_losing_requests(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/"solicitudes.sqlite3"
            db = sqlite3.connect(path)
            db.execute("CREATE TABLE solicitudes (id TEXT PRIMARY KEY, fecha TEXT, curp TEXT, correo TEXT, dispositivo TEXT, estado TEXT, detalle TEXT, tramites TEXT)")
            db.execute("INSERT INTO solicitudes VALUES ('old','date','curp','mail','device','completada','ok','{}')")
            db.commit()
            db.close()
            h = History(tmp)
            self.assertEqual(h.recent()[0][4], "completada")
            self.assertEqual(sum(map(len, h.mail_groups().values())), 0)

    def test_failed_export_keeps_previous_file_and_never_overwrites_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/"export.txt"
            path.write_text("previous")
            with self.assertRaises(ValueError):
                with atomic_text(path) as stream:
                    stream.write("partial")
                    raise ValueError("Simulated failure")
            self.assertEqual(path.read_text(), "previous")
            h = History(tmp)
            for exporter in (h.export, h.export_mail):
                with self.assertRaises(ValueError):
                    exporter(h.path)
            self.assertEqual(list(Path(tmp).glob(".export_*.tmp")), [])

    def test_mailbox_records_real_inbox_before_imss_not_full_request_success(self):
        recorded = Mock()
        reader = Mock()
        mail = OutlookMailbox("secret", threading.Event(), login=Mock(return_value=Mock()), reader_factory=Mock(return_value=reader), record=recorded)
        with patch.object(automation, "available_browsers", return_value=["chrome"]):
            mail.prepare(JOB, Mock())
        self.assertEqual(recorded.call_args.args[:2], (JOB.email, "Entró a la bandeja"))
        recorded.assert_called_once()
        mail.close()

    def test_login_mfa_throttle_and_cancel_outcomes_are_distinct(self):
        for error, expected in ((automation.LoginFailure(), "No logró entrar"), (automation.VerificationRequired(), "Omitido"), (automation.RateLimited(), "Interrumpido"), (automation.SkipRequested(), "Omitido")):
            with self.subTest(expected=expected):
                record = Mock()
                mail = OutlookMailbox("secret", threading.Event(), login=Mock(side_effect=error), record=record)
                with patch.object(automation, "available_browsers", return_value=["chrome"]), self.assertRaises(Exception):
                    mail.prepare(JOB, Mock())
                self.assertEqual(record.call_args.args[:2], (JOB.email, expected))
                self.assertNotIn("secret", str(record.call_args))


if __name__ == "__main__":
    unittest.main()
