"""Recuperación de contraseña: datos ficticios; no conecta con Microsoft."""
import threading
import unittest
from unittest.mock import Mock, patch

import navegador as n

NOTICE = 'El inicio de sesión con contraseña no está disponible en este momento.'


class Page:
    def __init__(self, text=NOTICE, url=n.OUTLOOK_LOGIN_LANDING, events=None):
        self.text = text
        self.url = url
        self.closed = False
        self.events = events if events is not None else []

    def locator(self, selector):
        return Mock(inner_text=Mock(return_value=self.text))

    def is_closed(self):
        return self.closed

    def close(self, **kwargs):
        self.events.append(('close', self))
        self.closed = True

    def goto(self, url, **kwargs):
        self.events.append(('goto', self, url))
        self.url = url


class Context:
    def __init__(self, texts):
        self.texts = iter(texts)
        self.pages = []
        self.events = []

    def new_page(self):
        page = Page(next(self.texts), events=self.events)
        self.events.append(('new', page))
        self.pages.append(page)
        return page

    def close(self):
        pass


class Detection(unittest.TestCase):
    def test_spanish_and_english_variants(self):
        for text in (
            NOTICE,
            'El inicio de sesion con contrasena no esta disponible.',
            'INICIAR SESIÓN CON TU CONTRASEÑA NO ESTÁ DISPONIBLE',
            'Inicio de sesión con contraseña\nno está disponible temporalmente.',
            'El acceso con la contraseña no está disponible.',
            'No se puede iniciar sesión con una contraseña en este momento.',
            'Password sign-in is currently unavailable.',
            'Password sign in is not available right now.',
            'Password login is temporarily unavailable.',
            'Password sign-in isn’t available right now.',
            "Password sign-in isn't currently available.",
            'Sign in with a password is not available.',
        ):
            with self.subTest(text=text):
                self.assertTrue(n.is_password_signin_unavailable(Page(text)))

    def test_unrelated_messages_do_not_restart(self):
        for text in (
            'Iniciar sesión con contraseña', 'La contraseña es incorrecta.',
            'Incorrect password.', 'El correo no está disponible.',
            'Esta cuenta no existe.', 'Password reset is unavailable.',
        ):
            with self.subTest(text=text):
                self.assertFalse(n.is_password_signin_unavailable(Page(text)))

    def test_only_official_https_auth_pages(self):
        for url in ('https://example.invalid/', 'http://login.live.com/',
                    'https://login.live.com.example.invalid/', n.OUTLOOK_WEB_URL):
            with self.subTest(url=url):
                self.assertFalse(n.is_password_signin_unavailable(Page(url=url)))

    def test_rate_limit_and_identity_check_take_priority(self):
        for text in ('Too Many Requests', 'HTTP 429', 'Demasiadas solicitudes',
                     'Verifica tu identidad', 'Enter your code'):
            with self.subTest(text=text):
                self.assertFalse(n.is_password_signin_unavailable(Page(NOTICE+' '+text)))

    def test_loading_page_is_not_an_error(self):
        page = Mock(url=n.OUTLOOK_LOGIN_LANDING)
        page.locator.side_effect = RuntimeError('not loaded')
        self.assertFalse(n.is_password_signin_unavailable(page))


class Recovery(unittest.TestCase):
    def setUp(self):
        self.logs = []
        self.engine = n.BrowserLogin(self.logs.append)
        self.page = Mock()
        self.context = Mock()

    def test_close_wait_open_and_navigate_in_that_order(self):
        order = []
        self.page.close.side_effect = lambda **kw: order.append('close')
        def wait(seconds):
            order.append(('wait', seconds))
            return False
        self.context.new_page.side_effect = lambda: order.append('open') or Mock()
        with patch.object(self.engine.stop_event, 'wait', side_effect=wait):
            replacement = self.engine._restart_password_signin(self.context, self.page, 1)
        self.assertEqual(order, ['close', ('wait', 5), 'open'])
        self.page.close.assert_called_once_with(run_before_unload=False)
        replacement.goto.assert_called_once_with(n.OUTLOOK_LOGIN_LANDING,
                                                 wait_until='domcontentloaded', timeout=22000)

    def test_second_retry_waits_ten_seconds(self):
        with patch.object(self.engine.stop_event, 'wait', return_value=False) as wait:
            self.engine._restart_password_signin(self.context, self.page, 2)
        wait.assert_called_once_with(10)

    def test_stop_during_wait_does_not_reopen(self):
        with patch.object(self.engine.stop_event, 'wait', return_value=True):
            result = self.engine._restart_password_signin(self.context, self.page, 1)
        self.assertIsNone(result)
        self.context.new_page.assert_not_called()

    def test_stop_after_page_creation_does_not_navigate(self):
        replacement = self.context.new_page.return_value
        self.context.new_page.side_effect = lambda: self.engine.stop() or replacement
        with patch.object(self.engine.stop_event, 'wait', return_value=False):
            result = self.engine._restart_password_signin(self.context, self.page, 1)
        self.assertIsNone(result)
        replacement.goto.assert_not_called()

    def test_close_failure_does_not_open_another_page(self):
        self.page.close.side_effect = RuntimeError('PRIVATE_VALUE')
        self.assertIsNone(self.engine._restart_password_signin(self.context, self.page, 1))
        self.context.new_page.assert_not_called()
        self.assertNotIn('PRIVATE_VALUE', ' '.join(self.logs))

    def test_creation_failure_is_reported_without_exception_values(self):
        self.context.new_page.side_effect = RuntimeError('PRIVATE_VALUE')
        with patch.object(self.engine.stop_event, 'wait', return_value=False):
            self.assertIsNone(self.engine._restart_password_signin(self.context, self.page, 1))
        self.assertNotIn('PRIVATE_VALUE', ' '.join(self.logs))

    def test_navigation_timeout_keeps_new_page_for_inspection(self):
        replacement = self.context.new_page.return_value
        replacement.goto.side_effect = TimeoutError('PRIVATE_VALUE')
        with patch.object(self.engine.stop_event, 'wait', return_value=False):
            result = self.engine._restart_password_signin(self.context, self.page, 1)
        self.assertIs(result, replacement)
        self.assertNotIn('PRIVATE_VALUE', ' '.join(self.logs))


class Worker(unittest.TestCase):
    def run_worker(self, texts, on_log=None, fill=None, password_field=None, submit=None):
        logs = []
        context = Context(texts)
        browser = Mock(is_connected=Mock(return_value=True))
        browser.new_context.return_value = context
        engine = n.BrowserLogin(lambda message: receive(message))
        def receive(message):
            logs.append(message)
            if on_log:
                on_log(engine, context, message)
        manager = Mock()
        manager.__enter__ = Mock(return_value=Mock())
        manager.__exit__ = Mock(return_value=False)
        # Un fallo debe terminar como prueba fallida en vez de quedar colgado.
        watchdog = threading.Timer(3, engine.stop)
        watchdog.start()
        try:
            with patch('playwright.sync_api.sync_playwright', return_value=manager), \
                 patch.object(n, 'launch_private_browser', return_value=browser), \
                 patch.object(n.time, 'sleep'), \
                 patch.object(engine.stop_event, 'wait', side_effect=lambda _: engine.stop_event.is_set()), \
                 patch.object(n, 'click_no_keep_session', return_value=False), \
                 patch.object(n, 'fill_email_step', side_effect=fill or (lambda *_: 'missing')), \
                 patch.object(n, 'visible_control', side_effect=password_field or (lambda *_: (None, None))), \
                 patch.object(n, 'submit_form', side_effect=submit or (lambda *_: False)), \
                 patch.object(n, 'choose_account_tile', return_value=False), \
                 patch.object(n, 'choose_other_account', return_value=False), \
                 patch.object(n, 'describe_login_fields', return_value='synthetic'), \
                 patch.object(n, 'try_password_choice', return_value=False), \
                 patch.object(engine, '_check_inbox', side_effect=lambda *_: engine.stop()):
                engine._worker('synthetic@example.invalid', 'synthetic-password')
        finally:
            watchdog.cancel()
        browser.close.assert_called_once()
        self.assertFalse(any(message.startswith('Error de Outlook') for message in logs), logs)
        return engine, context, logs

    def test_exactly_two_restarts_then_leave_last_page_for_review(self):
        state = {}
        def receive(engine, context, message):
            if 'tras dos reintentos' in message:
                state['open'] = not context.pages[-1].is_closed()
                engine.stop()
        _, context, logs = self.run_worker([NOTICE, NOTICE, NOTICE], on_log=receive)
        self.assertEqual(len(context.pages), 3)
        self.assertTrue(context.pages[0].closed)
        self.assertTrue(context.pages[1].closed)
        self.assertTrue(state.get('open'))
        self.assertEqual(sum('tras dos reintentos' in line for line in logs), 1)

    def test_reset_flow_refills_same_email_and_reaches_password_and_mail(self):
        emails = []
        password = Mock()
        def fill(page, email, emit):
            emails.append(email)
            page.text = NOTICE if len(emails) == 1 else 'Contraseña'
            return 'submitted'
        def field(page, selector):
            return (password, page) if page.text == 'Contraseña' else (None, None)
        def submit(page, frame, emit, control):
            page.url = n.OUTLOOK_WEB_URL
            return True
        _, context, logs = self.run_worker(['Correo', 'Correo'], fill=fill,
                                          password_field=field, submit=submit)
        self.assertEqual(emails, ['synthetic@example.invalid'] * 2)
        password.fill.assert_called_once_with('synthetic-password', timeout=7500)
        self.assertEqual(len(context.pages), 2)
        self.assertTrue(any('Outlook abierto en incógnito' in line for line in logs))

    def test_429_does_not_close_or_restart(self):
        def receive(engine, context, message):
            if 'TOO MANY REQUESTS' in message:
                engine.stop()
        engine, context, _ = self.run_worker([NOTICE+' Too Many Requests'], on_log=receive)
        self.assertTrue(engine.rate_limited)
        self.assertEqual(len(context.pages), 1)
        self.assertFalse(context.pages[0].closed)

    def test_identity_challenge_does_not_close_or_restart(self):
        def receive(engine, context, message):
            if message.startswith('Buscando correo en'):
                engine.stop()
        _, context, _ = self.run_worker([NOTICE+' Verifica tu identidad'], on_log=receive)
        self.assertEqual(len(context.pages), 1)
        self.assertFalse(context.pages[0].closed)


if __name__ == '__main__':
    unittest.main(verbosity=2)
