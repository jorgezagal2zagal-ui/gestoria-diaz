# Pruebas locales sin contraseñas ni acceso externo; no abren Microsoft.
import unittest
from unittest.mock import patch
import sys
from types import SimpleNamespace
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import navegador as n

class NavTests(unittest.TestCase):
    def test_01_inicio_oficial(self):
        self.assertEqual(n.OUTLOOK_LOGIN_LANDING,'https://login.live.com/login.srf')
        self.assertTrue(n.trusted_login_url(n.OUTLOOK_LOGIN_LANDING))
    def test_02_sin_portada_comercial(self):
        self.assertFalse(n.is_marketing_url(n.OUTLOOK_LOGIN_LANDING))
        self.assertTrue(n.is_marketing_url('https://www.microsoft.com/es-mx/microsoft-365/outlook/'))
    def test_03_solo_hosts_reconocidos(self):
        for url in ['http://login.live.com/login.srf','https://login.live.com.ejemplo.com','https://outlook-login.live.com.fake.net']:
            self.assertFalse(n.trusted_login_url(url))
    def test_04_permite_form_login(self):
        self.assertTrue(n.trusted_login_url('https://login.microsoftonline.com/common/oauth2/v2.0/authorize'))
    def test_05_nunca_rellena_portada(self):
        self.assertEqual(n.fill_email_step(SimpleNamespace(url='https://www.microsoft.com/es-mx/microsoft-365/outlook/'), 'user@example.com',lambda x:None),'notfound')
    def test_06_bandeja_independiente(self):
        self.assertTrue(n.is_outlook_mail_url('https://outlook.live.com/mail/0/inbox'))
        self.assertFalse(n.is_outlook_mail_url(n.OUTLOOK_LOGIN_LANDING))
    def test_07_incognito(self):
        logged=[]
        b=SimpleNamespace(chromium=SimpleNamespace(launch=lambda **kwargs:logged.append(kwargs) or object()))
        n.launch_private_browser(b,lambda x:None)
        self.assertIn('--incognito',logged[0]['args'])
    def test_08_reintento_controlado(self):
        events=[]
        b=n.BrowserLogin(events.append)
        b.running=True
        b.reopen_form(); self.assertTrue(b.reopen_requested.is_set())
        b.open_mail(); self.assertTrue(b.open_mail_requested.is_set())
    def test_09_inicio_abre_login_y_no_portada(self):
        events=[]
        class FakePage:
            def __init__(self):self.url='about:blank';self.urls=[];self.stopped=None
            def goto(self,url,**kwargs):
                self.urls.append(url);self.url=url
            def is_closed(self):return False
        page=FakePage()
        class FakeContext:
            pages=[page]
            def new_page(self):return page
            def close(self):pass
        class FakeBrowser:
            def new_context(self,**kw):return FakeContext()
            def is_connected(self):return True
            def close(self):pass
        fake_browser=FakeBrowser()
        class Context:
            def __enter__(self):return object()
            def __exit__(self,*a):pass
        b=n.BrowserLogin(events.append)
        def stop_after_read(*a):
            b.stop_event.set()
            return 'notfound'
        with patch.dict(sys.modules,{'playwright.sync_api':SimpleNamespace(sync_playwright=lambda:Context())}),\
             patch.object(n,'launch_private_browser',return_value=fake_browser),\
             patch.object(n,'fill_email_step',side_effect=stop_after_read):
            b._worker('user@example.com','password')
        self.assertEqual(page.urls,[n.OUTLOOK_LOGIN_LANDING])
    def test_10_redireccion_marketing_recupera_login(self):
        events=[]
        class FakePage:
            def __init__(self):self.url='about:blank';self.urls=[]
            def goto(self,url,**kwargs):
                self.urls.append(url)
                # primera navegación simula rebote comercial de Outlook/Microsoft
                self.url='https://www.microsoft.com/es-mx/microsoft-365/outlook/' if len(self.urls)==1 else url
            def is_closed(self):return False
        page=FakePage()
        class FakeContext:
            pages=[page]
            def new_page(self):return page
            def close(self):pass
        class FakeBrowser:
            def new_context(self,**kw):return FakeContext()
            def is_connected(self):return True
            def close(self):pass
        class Context:
            def __enter__(self):return object()
            def __exit__(self,*a):pass
        b=n.BrowserLogin(events.append)
        def stop_after_read(*a):
            b.stop_event.set()
            return 'notfound'
        with patch.dict(sys.modules,{'playwright.sync_api':SimpleNamespace(sync_playwright=lambda:Context())}),\
             patch.object(n,'launch_private_browser',return_value=FakeBrowser()),\
             patch.object(n,'fill_email_step',side_effect=stop_after_read):
            b._worker('user@example.com','password')
        self.assertEqual(page.urls,[n.OUTLOOK_LOGIN_LANDING,n.OUTLOOK_LOGIN_LANDING])
        self.assertTrue(any('publicidad' in x for x in events))

if __name__=='__main__':unittest.main(verbosity=2)
