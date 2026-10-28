"""Actual Chromium + shipped Outlook reader + new flow; ADB and mail delivery simulated."""
from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import threading
from unittest.mock import patch

from playwright.sync_api import sync_playwright
from bot_imss_adb.flow import Flow, Job
from bot_imss_adb.mail_service import OutlookMailbox
from bot_imss_adb.tests.fakes import Clock, FakeAdb


def main():
    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location("local_browser_adapter", root / "tests/browser_reader_check.py")
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    fixture = (root / "tests/fixtures/outlook_reader.html").read_text()
    trace, login_accounts = [], []
    with sync_playwright() as play:
        browser = play.chromium.launch(executable_path="/usr/bin/chromium", headless=True,
                                      args=["--no-sandbox", "--disable-dev-shm-usage"])
        context = browser.new_context()
        context.route("**/*", lambda route: route.fulfill(status=200, content_type="text/html", body=fixture))
        page = context.new_page()
        page.goto("https://outlook.live.com/mail/0/inbox")
        driver = helper.BrowserAdapter(page)
        cancelled = threading.Event()

        def login(account, *args):
            trace.append("mail-login")
            login_accounts.append(account.address)
            return driver

        class Android(FakeAdb):
            def tap(self, node):
                super().tap(node)
                if node["rid"] == "btnIniciar":
                    page.evaluate("(a)=>addMessage(...a)", ["new-imss-code", "Código de validación",
                                  "verifica-noreplay@imss.gob.mx", "001177",
                                  datetime.now(timezone.utc).isoformat(), {}])

        adb = Android(trace=trace)
        adb.cancelled = cancelled
        mailbox = OutlookMailbox("SYNTHETIC_PASSWORD", cancelled, login=login)
        with patch("bot_imss_adb.mail_service.automation.available_browsers", return_value=["chrome"]):
            result = Flow(adb, clock=Clock(), poll=0).run(Job("AAAA900101HDFBCD00", "synthetic@example.test"), mailbox)
        assert result == {"nss": "confirmado", "vigencia": "confirmado", "semanas": "confirmado"}, result
        assert login_accounts == [adb.email]
        assert trace.index("mail-login") < trace.index("imss-login") < trace.index("verify")
        assert "".join(adb.digits) == "001177"
        assert adb.verify_taps == 1 and adb.state == "login"
        assert driver.closed
        context.close()
        browser.close()
        print("PASS: new bot + real Chromium/reader + matching new code + three simulated ADB procedures and logout")


if __name__ == "__main__":
    main()
