"""Optional browser checks: runs production reader against local synthetic Outlook DOM.
Use the test venv with playwright and an installed Chromium; no Microsoft connection.
"""

from datetime import datetime, timezone
from pathlib import Path
import queue
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch
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
        callback = getattr(self, "before_read", None)
        if callback:
            callback()
        return [Element(n) for n in self.context.query_selector_all(selector)]

    def set_page_load_timeout(self, seconds):
        self.page.set_default_navigation_timeout(seconds * 1000)

    def set_script_timeout(self, seconds):
        pass

    def quit(self):
        self.closed = True

    def execute_script(self, script, *args):
        return self.page.evaluate(
            "(args)=>{return (function(){" + script + "}).apply(null,args)}",
            [a.node if isinstance(a, Element) else a for a in args],
        )


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

    def test_undated_new_mail_in_baselined_other_tab_can_pass_with_matching_ids(self):
        self.add_tabs()
        self.add(offset=None)
        self.page.locator("[data-row=new]").evaluate(
            "e=>{e.dataset.view='Other';e.style.display='none'}"
        )
        self.assertIsNone(self.reader.scan(self.started))
        self.assertEqual(self.reader.scan(self.started), "870621")

    def test_preexisting_undated_other_tab_mail_is_not_mistaken_for_new_arrival(self):
        self.add_tabs()
        self.add(offset=None)
        self.page.locator("[data-row=new]").evaluate(
            "e=>{e.dataset.view='Other';e.style.display='none'}"
        )
        self.reader.baseline()
        self.assertIsNone(self.reader.scan(self.started))
        self.assertIsNone(self.reader.scan(self.started))

    def native_layout(self, offset=0, body_extra=""):
        sender = self.reader.sender or "verifica-noreplay@imss.gob.mx"
        date = datetime.fromtimestamp(self.started + offset).strftime(
            "%a %Y-%m-%d %H:%M"
        )
        # Native tooltip/header variant seen in current Outlook: no email attr,
        # no ISO datetime and no shared ID on the reading pane.
        self.page.evaluate(
            """({sender,date,extra})=>{
          const pane=document.querySelector('[role=article]');pane.remove();
          const native=document.createElement('div');native.dataset.appSection='MailReadCompose';
          document.body.append(native);
          addMessage('new','Código de validación',sender,'012345',null);
          const row=document.querySelector('[data-row=new]');
          row.onclick=()=>{
            native.innerHTML='';
            const subject=document.createElement('h2');subject.textContent='Código de validación';native.append(subject);
            const address=document.createElement('span');address.title=sender;address.textContent=sender;native.append(address);
            const t=document.createElement('span');t.title=date;t.textContent=date;native.append(t);
            const body=document.createElement('div');body.id='UniqueMessageBody';
            body.innerHTML='<p>Estimado usuario</p><p>Tu código de verificación es: <b>012345</b></p>'+extra;
            native.append(body);
          };
        }""",
            {"sender": sender, "date": date, "extra": body_extra},
        )

    def test_native_tooltip_sender_and_calendar_date_deliver_code_without_shared_id(
        self,
    ):
        self.native_layout()
        self.assertEqual(self.reader.scan(self.started), "012345")

    def test_old_native_tooltip_date_and_body_forgery_cannot_deliver_code(self):
        self.native_layout(
            offset=-86400,
            body_extra='<span title="2099-01-01 17:10" email="avisos@imss.gob.mx">test</span>',
        )
        self.assertIsNone(self.reader.scan(self.started))

    def test_message_body_cannot_spoof_sender_when_native_header_is_unrecognized(self):
        self.native_layout(
            body_extra='<header><span email="avisos@imss.gob.mx">test</span></header>'
        )
        self.page.locator("[data-row=new]").click()
        self.page.locator(
            "[data-app-section=MailReadCompose]>span[title]"
        ).first.evaluate(
            "e=>{e.title='other@provider.test';e.textContent='other@provider.test'}"
        )
        row = next(
            r
            for _, r, _ in self.reader.rows()
            if r.get_attribute("data-item-id") == "new"
        )
        pane = self.driver.find_elements("css selector", PANE)[0]
        self.assertIsNone(self.reader.inspect(row, pane, self.started))

    def test_old_imss_request_and_attachment_messages_are_not_opened_during_code_wait(
        self,
    ):
        self.page.evaluate("""()=>{
          addMessage('request','IMSS: Solicitud de Constancia','avisos@imss.gob.mx','',null);
          addMessage('document','IMSS: Constancia de semanas cotizadas','avisos@imss.gob.mx','',null);
          for(const r of document.querySelectorAll('[role=option]'))r.onclick=()=>{throw Error('Unrelated old mail opened')};
        }""")
        self.assertIsNone(self.reader.scan(self.started))

    def test_native_message_code_crosses_real_bridge_and_reaches_matching_imss_request(
        self,
    ):
        import gestoria_5_instancias as imss
        import outlook_conectado as out
        from conexion.bridge import Bridge
        from conexion.history import RequestHistory
        from conexion.imss_link import ImssConnection
        from types import SimpleNamespace

        with tempfile.TemporaryDirectory() as tmp:
            bridge = Bridge(tmp)
            email = "synthetic@example.test"
            bridge.publish([email], True)
            app = imss.App.__new__(imss.App)
            app.root = Mock()
            app.root.after.side_effect = lambda delay, cb: cb()
            app.emit = Mock()
            app.events = queue.Queue()
            app.usados_sesion = set()
            app.pendiente = None
            app.resultado_tramite = False
            app.btn_consulta = Mock()
            app.btn_codigo = Mock()
            app.selector_cantidad = Mock()
            app.codigo = Mock()
            c = ImssConnection.__new__(ImssConnection)
            c.app = app
            c.bridge = bridge
            c.history = RequestHistory(tmp)
            c.cancel = threading.Event()
            c.skip = threading.Event()
            c.active = True
            c.job = None
            c.rejected = False
            c.reset_ready = False

            def consult(path, person, address, instance, procedure):
                self.assertEqual(bridge.response(c.job)["status"], "ready")
                app.pendiente = (path, "1", instance, person, address, procedure)

            app._consulta = Mock(side_effect=consult)

            def code(value, *pending):
                self.assertEqual(value, "012345")
                self.assertEqual(
                    pending[2:5], ("INSTANCE", "AAAA900101HDFBCD00", email)
                )
                app.pendiente = None
                app.resultado_tramite = True

            app._codigo = Mock(side_effect=code)
            server = out.OutlookWorker()
            server.bridge = bridge
            server.accounts = [SimpleNamespace(address=email, password="synthetic")]
            server.shutdown = threading.Event()
            server.job_cancel = threading.Event()
            server.accepting = True
            server._post = lambda cb: cb()
            server._record_result = Mock()
            server._account_status = Mock()
            server.manage_buttons = []
            server.start_button = Mock()
            server.skip_button = Mock()
            server.stop_button = Mock()
            server.status = Mock()
            delivered = [False]

            def deliver_mail():
                if (
                    c.job
                    and not delivered[0]
                    and (bridge.job(c.job) / "started.json").exists()
                ):
                    delivered[0] = True
                    self.native_layout()

            self.driver.before_read = deliver_mail
            special = Mock()
            special.handle.return_value = None
            with (
                patch.object(out, "try_account", return_value=self.driver),
                patch.object(out, "SpecialPages", return_value=special),
                patch("automation.available_browsers", return_value=["edge"]),
                patch.object(imss, "correos_usados", return_value=set()),
            ):
                thread = threading.Thread(
                    target=c.run,
                    args=(
                        "console",
                        "AAAA900101HDFBCD00",
                        "INSTANCE",
                        "procedure",
                        self.reader.sender,
                        self.reader.subject,
                    ),
                    daemon=True,
                )
                thread.start()
                deadline = time.monotonic() + 3
                while not bridge.pending() and time.monotonic() < deadline:
                    time.sleep(0.02)
                try:
                    requests = bridge.pending()
                    self.assertEqual(len(requests), 1)
                    server.process(requests[0])
                    thread.join(3)
                    self.assertFalse(thread.is_alive())
                    self.assertEqual(c.last_result.status, "completada")
                    app._codigo.assert_called_once()
                    self.assertTrue(self.driver.closed)
                finally:
                    c.cancel.set()
                    server.shutdown.set()
                    thread.join(3)

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


class AutomaticBrowserReaderTests(BrowserReaderTests):
    # Run the production reader with both optional filters empty.
    def setUp(self):
        super().setUp()
        self.reader = OutlookReader(self.driver, expected_curp="AAAA900101HDFBCD00")
        self.reader.baseline()

    def add(
        self, key="new", code="870621", sender="avisos@imss.gob.mx", offset=1, **options
    ):
        return super().add(key, code, sender, offset, **options)

    def test_native_header_mailto_and_international_code(self):
        self.add(mailto=True, code="０１２３４５")
        self.assertEqual(self.reader.scan(self.started), "012345")

    def test_wrong_header_sender_cannot_be_spoofed_by_message_body(self):
        self.add(sender="other@provider.test")
        self.page.locator("[data-row=new]").click()
        row = next(
            r
            for _, r, _ in self.reader.rows()
            if r.get_attribute("data-item-id") == "new"
        )
        pane = self.driver.find_elements("css selector", PANE)[0]
        self.assertIsNone(self.reader.inspect(row, pane, self.started))


if __name__ == "__main__":
    unittest.main(verbosity=2)
