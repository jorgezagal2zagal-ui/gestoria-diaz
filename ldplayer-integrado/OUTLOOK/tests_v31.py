# -*- coding: utf-8 -*-
import unittest
from unittest.mock import Mock
import avisos_windows_v28 as ui
from opciones_v28 import decline_web_passkey_setup
from tests_v28 import Page

class NativePasskeyV31(unittest.TestCase):
    def test_accept_official_creation_only(self):
        self.assertEqual('clave de paso de Windows',
            ui.requested_action('Seguridad de Windows',
                'Guardar la clave de paso Clave de paso para login.microsoft.com',
                'Cancelar',False,True))
        self.assertEqual('clave de paso de Windows',
            ui.requested_action('Windows Security',
                'Save a passkey login.microsoft.com', 'Cancel',False,True))
        self.assertEqual('clave de paso de Windows',
            ui.requested_action('Seguridad de Windows',
                'Guardar una clave de paso login.microsoft.com', 'No',False,True))
    def test_never_cancel_security_challenge(self):
        for title,text,button,armed in [
            ('Seguridad de Windows','Inicia sesión con tu clave de paso login.microsoft.com','Cancelar',True),
            ('Seguridad de Windows','Guardar la clave de paso login.microsoft.com','Continuar',True),
            ('Seguridad de Windows','Guardar la clave de paso login.microsoft.com','Cancelar',False),
            ('Seguridad de Windows','Guardar la clave de paso otro-sitio.com','Cancelar',True),
            ('Chrome','Guardar la clave de paso login.microsoft.com','Cancelar',True),
        ]:
            self.assertIsNone(ui.requested_action(title,text,button,False,armed))
    def test_web_only_creation_path(self):
        page=Page('https://login.microsoft.com/consumers/fido/create?mkt=es-MX',
                  'Configurando la clave de paso...',button='Cancelar')
        self.assertTrue(decline_web_passkey_setup(page))
        self.assertEqual(page.button.clicked,1)
        malicious=Page('https://login.microsoft.com/consumers/fido/get',
                       'Configurando la clave de paso...',button='Cancelar')
        self.assertFalse(decline_web_passkey_setup(malicious))
    def test_timeout(self):
        guard=ui.OptionalWindowsPromptsV28(lambda _:None)
        self.assertFalse(guard.is_passkey_armed())
        guard.arm_passkey(True)
        self.assertTrue(guard.is_passkey_armed())
        guard.arm_passkey(False)
        self.assertTrue(guard.is_passkey_armed())
        guard.passkey_until=0
        self.assertFalse(guard.is_passkey_armed())
if __name__=='__main__':unittest.main(verbosity=2)
