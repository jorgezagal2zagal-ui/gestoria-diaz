# -*- coding: utf-8 -*-
"""Tests V28 sin credenciales ni conexión a Microsoft, Windows o IMSS."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
import opciones_v28 as opt
import avisos_windows_v28 as ui
import navegador_v28 as nav

class Button:
    def __init__(self):self.clicked=0
    def is_visible(self):return True
    def is_enabled(self):return True
    def click(self,**kwargs):self.clicked+=1

class Locator:
    def __init__(self,text='',button=None):self.text=text;self.button=button
    def inner_text(self,**kwargs):return self.text
    def count(self):return int(self.button is not None)
    def nth(self,i):return self.button

class Page:
    def __init__(self,url,text,button='No'):
        self.url=url;self.text=text;self.target_name=button;self.button=Button();self.names=[]
    def locator(self,sel):return Locator(text=self.text)
    def get_by_role(self,role,name):
        self.names.append((role,str(name)))
        import re
        return Locator(button=self.button if re.fullmatch(name,self.target_name) else None)
    def get_by_text(self,regex):
        return Locator(button=self.button if regex.search(self.text) else None)

class OptionalDialogs(unittest.TestCase):
    def test_passkey_decline_only_setup_url(self):
        page=Page('https://login.microsoft.com/consumers/fido/create?mtk=es-MX',
                  'Configurando la clave de paso...',button='Cancelar')
        self.assertTrue(opt.decline_web_passkey_setup(page))
        self.assertEqual(1,page.button.clicked)
        dangerous=Page('https://login.microsoft.com/consumers/fido/get',
                       'Configurando la clave de paso...',button='Cancelar')
        self.assertFalse(opt.decline_web_passkey_setup(dangerous))
        self.assertEqual(0,dangerous.button.clicked)
        phishing=Page('https://microsoft.example.invalid/consumers/fido/create',
                      'Configurando la clave de paso...',button='Cancelar')
        self.assertFalse(opt.decline_web_passkey_setup(phishing))
    def test_recovery_only_outlook_and_exact_offer(self):
        p=Page('https://outlook.live.com/mail/0/inbox',
               'Keep access to your account with a recovery method',button='Not now')
        self.assertTrue(opt.decline_optional_recovery(p))
        self.assertEqual(1,p.button.clicked)
        x=Page('https://login.microsoft.com/consumers',
               'Keep access to your account with a recovery method',button='Not now')
        self.assertFalse(opt.decline_optional_recovery(x))
        x=Page('https://outlook.live.com/mail/0/inbox',
               'Verify your identity using another method',button='Not now')
        self.assertFalse(opt.decline_optional_recovery(x))
    def test_keep_signed_in_declined_at_official_site(self):
        page=Page('https://login.live.com/login.srf','¿Quieres mantener la sesión iniciada?',button='No')
        self.assertTrue(nav.click_no_keep_session(page))
        self.assertEqual(1,page.button.clicked)
        page=Page('https://example.invalid/login','¿Quieres mantener la sesión iniciada?',button='No')
        self.assertFalse(nav.click_no_keep_session(page))
        self.assertEqual(0,page.button.clicked)
    def test_native_passkey_strictly_requires_context(self):
        self.assertEqual('clave de paso de Windows',ui.requested_action(
            'Seguridad de Windows','Guardar la clave de paso para login.microsoft.com',
            'Cancelar',False,True))
        self.assertIsNone(ui.requested_action(
            'Seguridad de Windows','Guardar la clave de paso para login.microsoft.com',
            'Continuar',False,True))
        self.assertIsNone(ui.requested_action(
            'Seguridad de Windows','Guardar la clave de paso para login.microsoft.com',
            'Cancelar',False,False))
        self.assertIsNone(ui.requested_action(
            'Seguridad de Windows','Guardar la clave de paso para example.invalid',
            'Cancelar',False,True))
        self.assertEqual('guardado de contraseña de Chrome',ui.requested_action(
            'Chrome','¿Quieres guardar la contraseña?', 'Nunca',True,False))
        self.assertIsNone(ui.requested_action(
            'Chrome','¿Quieres guardar la contraseña?', 'Guardar',True,False))
    def test_preferences_only_dedicated_path_and_keep_cookies(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);prefs=root/'Default'/'Preferences';prefs.parent.mkdir()
            prefs.write_text(json.dumps({'profile':{'other':3},'cookies':{'keep':True}}))
            self.assertTrue(opt.prepare_browser_preferences(root))
            after=json.loads(prefs.read_text())
            self.assertTrue(after['cookies']['keep'])
            self.assertEqual(3,after['profile']['other'])
            self.assertFalse(after['profile']['password_manager_enabled'])
            self.assertEqual(2,after['profile']['default_content_setting_values']['notifications'])
            self.assertEqual(2,after['profile']['default_content_setting_values']['protocol_handlers'])
    def test_legacy_429_and_mfa_guards_not_disabled(self):
        self.assertTrue(hasattr(nav,'is_microsoft_rate_limited'))
        self.assertTrue(hasattr(nav,'is_additional_verification_required'))
        self.assertTrue(hasattr(nav,'is_microsoft_account_blocked'))
        self.assertEqual('verifica-noreplay@imss.gob.mx',
                          __import__('app_v28').DEFAULT_SENDER_IMSS)

if __name__=='__main__':unittest.main(verbosity=2)
