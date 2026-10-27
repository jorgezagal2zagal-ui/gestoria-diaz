"""Optional browser checks: runs production reader against local synthetic Outlook DOM.
Use the test venv with playwright and an installed Chromium; no Microsoft connection.
"""

from datetime import datetime, timezone
from pathlib import Path
import time
import unittest
from playwright.sync_api import sync_playwright
from conexion.reader import OutlookReader, PANE


class Element:
    def __init__(self, node):
        self.node = node

    @property
    def text(self):
        return self.node.inner_text()

    def get_attribute(self, name):
        return self.node.get_attribute(name)

    def is_displayed(self):
        return self.node.is_visible()

    def click(self):
        self.node.click(timeout=1500)

    def find_elements(self, by, selector):
        return [Element(n) for n in self.node.query_selector_all(selector)]


class Switch:
    def __init__(self, driver):
        self.driver = driver

    def frame(self, element):
        self.driver.context = element.node.content_frame()

    def default_content(self):
        self.driver.context = self.driver.page


class BrowserAdapter:
    def __init__(self, page):
        self.page = page
        self.context = page
        self.switch_to = Switch(self)

    @property
    def current_url(self):
        return self.page.url

    def find_elements(self, by, selector):
        return [Element(n) for n in self.context.query_selector_all(selector)]


class BrowserReaderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.play = sync_playwright().start()
        cls.browser = cls.play.chromium.launch(
            executable_path="/usr/bin/chromium",
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        cls.fixture = (
            Path(__file__).parent / "fixtures/outlook_reader.html"
        ).read_text()

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.play.stop()

    def setUp(self):
        self.context = self.browser.new_context()
        self.context.route(
            "**/*",
            lambda route: route.fulfill(
                status=200, content_type="text/html", body=self.fixture
            ),
        )
        self.page = self.context.new_page()
        self.page.goto("https://outlook.live.com/mail/0/inbox")
        self.driver = BrowserAdapter(self.page)
        self.reader = OutlookReader(
            self.driver, "sender@provider.test", "Código de validación"
        )
        self.reader.baseline()
        self.started = time.time()

    def tearDown(self):
        self.context.close()

    def add(
        self,
        key="new",
        code="870621",
        sender="sender@provider.test",
        offset=1,
        **options,
    ):
        date = (
            datetime.fromtimestamp(self.started + offset, timezone.utc).isoformat()
            if offset is not None
            else None
        )
        self.page.evaluate(
            "(a)=>addMessage(...a)",
            [key, "Código de validación", sender, code, date, options],
        )

    def add_tabs(self):
        self.page.evaluate("""() => {
          const bar=document.createElement('div');
          for(const label of ['Focused','Other']){
            const tab=document.createElement('button');tab.setAttribute('role','tab');
            tab.textContent=label;tab.setAttribute('aria-selected',label==='Focused'?'true':'false');
            tab.onclick=()=>{
              for(const t of bar.children)t.setAttribute('aria-selected',t===tab?'true':'false');
              for(const row of document.querySelectorAll('[role=option]'))row.style.display=(row.dataset.view||'Focused')===label?'block':'none';
            };bar.append(tab);
          }document.body.prepend(bar);
        }""")
        self.reader.baseline()

    def test_other_tab_is_checked_but_only_fresh_dated_mail_can_pass(self):
        self.add_tabs()
        self.add()
        self.page.locator("[data-row=new]").evaluate(
            "e=>{e.dataset.view='Other';e.style.display='none'}"
        )
        self.assertIsNone(self.reader.scan(self.started))
        self.assertEqual(self.reader.scan(self.started), "870621")

    def test_undated_mail_in_other_tab_is_not_mistaken_for_new_arrival(self):
        self.add_tabs()
        self.add(offset=None)
        self.page.locator("[data-row=new]").evaluate(
            "e=>{e.dataset.view='Other';e.style.display='none'}"
        )
        self.assertIsNone(self.reader.scan(self.started))
        self.assertIsNone(self.reader.scan(self.started))

    def test_new_code_from_real_dom(self):
        self.add()
        self.assertEqual(self.reader.scan(self.started), "870621")

    def test_body_inside_iframe(self):
        self.add(iframe=True)
        self.assertEqual(self.reader.scan(self.started), "870621")
        self.assertIs(self.driver.context, self.page)

    def test_native_header_mailto_and_international_code(self):
        self.add(mailto=True, code="０１２３４５")
        self.assertEqual(self.reader.scan(self.started), "012345")

    def test_delayed_loading_does_not_take_previous_message(self):
        self.page.locator("[role=option]").click()
        self.add(delay=400)
        self.assertEqual(self.reader.scan(self.started), "870621")

    def test_old_preview_and_older_code_never_pass(self):
        self.page.locator("[role=option]").evaluate(
            '(e)=>e.textContent += " hace un minuto"'
        )
        self.assertIsNone(self.reader.scan(self.started))
        self.add(offset=-3600)
        self.assertIsNone(self.reader.scan(self.started))

    def test_wrong_header_sender_cannot_be_spoofed_by_message_body(self):
        self.add(sender="other@provider.test")
        self.page.locator("[data-row=new]").click()
        self.page.locator(".content").evaluate(
            '(e)=>{const n=document.createElement("span");n.setAttribute("email","sender@provider.test");e.append(n)}'
        )
        row = next(
            r
            for _, r, _ in self.reader.rows()
            if r.get_attribute("data-item-id") == "new"
        )
        pane = self.driver.find_elements("css selector", PANE)[0]
        self.assertIsNone(self.reader.inspect(row, pane, self.started))

    def test_ambiguous_message_and_future_date_are_rejected(self):
        self.add(code="870621. Código: 123456")
        self.assertIsNone(self.reader.scan(self.started))
        self.add(key="future", offset=3600)
        self.assertIsNone(self.reader.scan(self.started))

    def test_reference_survives_view_reloading(self):
        self.page.reload()
        self.add()
        self.assertEqual(self.reader.scan(self.started), "870621")


if __name__ == "__main__":
    unittest.main(verbosity=2)
