"""Prueba Chromium con HTML sintético: todas las solicitudes se interceptan localmente.

python PROBAR_REINTENTO_NAVEGADOR.py
Opcional: --chromium /ruta/al/ejecutable
No inicia sesión ni transmite datos a Microsoft.
"""
import argparse
import json
import threading
from unittest.mock import patch

import navegador as n


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--chromium', help='Ejecutable Chromium alternativo')
    args = parser.parse_args()
    state = {'login_pages': 0, 'mail': False, 'pages': [], 'contexts': 0}
    logs = []
    engine = n.BrowserLogin(logs.append)
    email = 'synthetic@example.invalid'
    password = 'synthetic-password'
    notice = 'El inicio de sesión con contraseña no está disponible en este momento.'

    def route(request_route):
        url = request_route.request.url
        if url == n.OUTLOOK_LOGIN_LANDING:
            state['login_pages'] += 1
            # Primera pestaña: el error aparece DESPUÉS de enviar el correo.
            # Segunda pestaña: formulario de contraseña y buzón simulado.
            fail = state['login_pages'] == 1
            html = '''<!doctype html><meta charset="utf-8">
              <h1>Iniciar sesión</h1><form id="emailform">
              <input id="i0116" name="loginfmt" autocomplete="username">
              <button id="idSIButton9" type="submit">Siguiente</button></form>
              <script>
              document.querySelector('form').onsubmit = event => {
                event.preventDefault();
                if (document.querySelector('input').value !== EMAIL) return;
                if (FAIL) {document.body.textContent = NOTICE; return;}
                document.body.innerHTML = '<form><input id="i0118" name="passwd" '
                  + 'type="password" autocomplete="current-password">'
                  + '<button id="idSIButton9" type="submit">Iniciar sesión</button></form>';
                document.querySelector('form').onsubmit = event => {
                  event.preventDefault();
                  if (document.querySelector('input').value === PASSWORD) location.href = MAIL;
                };
              };
              </script>'''
            for key, value in (('EMAIL', email), ('FAIL', fail), ('NOTICE', notice),
                               ('PASSWORD', password), ('MAIL', n.OUTLOOK_WEB_URL)):
                html = html.replace(key, json.dumps(value, ensure_ascii=False))
            request_route.fulfill(status=200, content_type='text/html; charset=utf-8', body=html)
        elif n.is_outlook_mail_url(url):
            request_route.fulfill(status=200, content_type='text/html; charset=utf-8',
                                  body='<h1 id="synthetic-inbox">Buzón simulado</h1>')
        else:
            request_route.fulfill(status=404, body='No external requests allowed')

    class Browser:
        def __init__(self, browser):
            self.browser = browser

        def new_context(self, **kwargs):
            state['contexts'] += 1
            context = self.browser.new_context(**kwargs)
            context.route('**/*', route)
            context.on('page', lambda page: state['pages'].append(page))
            return context

        def is_connected(self):
            return self.browser.is_connected()

        def close(self):
            self.browser.close()

    def launch(playwright, emit):
        kwargs = {'headless': True}
        if args.chromium:
            kwargs['executable_path'] = args.chromium
        return Browser(playwright.chromium.launch(**kwargs))

    def inbox(page, account):
        assert account == email
        assert page.locator('#synthetic-inbox').inner_text() == 'Buzón simulado'
        assert state['pages'][0].is_closed()
        state['mail'] = True
        engine.stop()

    watchdog = threading.Timer(25, engine.stop)
    watchdog.start()
    try:
        # La pausa productiva de 5/10 s se prueba en tests_reintento.py.
        with patch.object(n, 'launch_private_browser', side_effect=launch), \
             patch.object(n, 'PASSWORD_RETRY_DELAYS', (0, 0)), \
             patch.object(engine, '_check_inbox', side_effect=inbox):
            engine._worker(email, password)
    finally:
        watchdog.cancel()
    assert state['mail'], 'No se llegó al buzón simulado: '+repr(logs)
    assert state['login_pages'] == 2, state['login_pages']
    assert state['contexts'] == 1, state['contexts']
    assert len(state['pages']) == 2, len(state['pages'])
    print('PASS: Chromium cerró el error, abrió otra pestaña y accedió al buzón simulado con la misma cuenta.')


if __name__ == '__main__':
    main()
