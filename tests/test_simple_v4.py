import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from conexion.bridge import Bridge
from conexion.reader import OutlookReader, ROW, PANE
from conexion.reader import extract_code
from test_connected_bots import Row, Pane

CURP = "AAAA900101HDFBCD00"


class AutomaticReaderTests(unittest.TestCase):
    def test_curp_birth_date_is_not_mistaken_for_the_verification_code(self):
        self.assertIsNone(extract_code(f"Código de validación para CURP {CURP}"))
        self.assertEqual(
            extract_code(
                f"Código de validación para CURP {CURP}. Tu código es: 012345"
            ),
            "012345",
        )

    def reader(self):
        driver = Mock()
        driver.current_url = "https://outlook.live.com/mail/0/inbox"
        rows = [Row("old", "IMSS código anterior")]
        panes = []
        driver.find_elements.side_effect = lambda by, selector: (
            rows if selector == ROW else panes if selector == PANE else []
        )
        r = OutlookReader(driver, expected_curp=CURP)
        r.baseline()
        return r, rows, panes

    def test_official_imss_message_needs_no_sender_or_subject_configuration(self):
        r, rows, panes = self.reader()
        row = Row("new", "IMSS Digital: validación de identidad")
        pane = Pane("new", "Tu código de validación es: 012345", "avisos@imss.gob.mx")
        self.assertEqual(r.inspect(row, pane, time.time()), "012345")

    def test_imss_message_from_another_sender_must_match_active_curp(self):
        r, rows, panes = self.reader()
        row = Row("new", "IMSS Digital")
        pane = Pane(
            "new",
            f"IMSS Digital - CURP {CURP}. Código de validación: 012345",
            "avisos@proveedor.test",
        )
        self.assertEqual(r.inspect(row, pane, time.time()), "012345")
        pane.text = (
            "IMSS Digital - CURP BBBB900101HDFBCD00. Código de validación: 012345"
        )
        self.assertIsNone(r.inspect(row, pane, time.time()))

    def test_other_services_codes_and_imss_lookalike_domains_are_not_forwarded(self):
        r, rows, panes = self.reader()
        row = Row("new", "Código de validación")
        for address in ("bank@bank.test", "avisos@imss.gob.mx.evil.test"):
            pane = Pane("new", "Código de validación: 012345", address)
            self.assertIsNone(r.inspect(row, pane, time.time()))

    def test_wrong_curp_in_official_mail_and_ambiguous_codes_are_rejected(self):
        r, rows, panes = self.reader()
        row = Row("new", "IMSS código")
        for text in (
            "CURP BBBB900101HDFBCD00. Código: 012345",
            "Código: 012345. Código: 987654",
        ):
            self.assertIsNone(
                r.inspect(row, Pane("new", text, "avisos@imss.gob.mx"), time.time())
            )

    def test_automatic_request_carries_curp_without_requiring_configuration(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = Bridge(tmp)
            b.create("a@example.test", "INSTANCE", "", "", curp=CURP)
            request = b.pending()[0]
            self.assertEqual(request["curp"], CURP)
            self.assertEqual(request["sender"], "")
            self.assertEqual(request["subject"], "")
            self.assertNotIn("password", request)

    def test_settings_never_opens_a_window(self):
        from conexion.imss_link import ImssConnection

        c = ImssConnection.__new__(ImssConnection)
        c.app = Mock()
        with patch("conexion.imss_link.tk.Toplevel") as popup:
            c.settings()
        popup.assert_not_called()

    def test_all_launchers_open_the_same_single_panel(self):
        root = Path(__file__).resolve().parents[1]
        for name in (
            "INICIAR_TODO.bat",
            "INICIAR_IMSS.bat",
            "INICIAR_OUTLOOK_CONECTADO.bat",
        ):
            data = (root / name).read_text()
            self.assertIn("ABRIR_BOT.bat", data)
            self.assertNotIn("outlook_conectado.py", data)
            self.assertNotIn("gestoria_5_instancias.py", data)
        self.assertIn("panel_unificado.py", (root / "ABRIR_BOT.bat").read_text())


if __name__ == "__main__":
    unittest.main()
