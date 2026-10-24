import unittest
from avisos_windows_v35 import verified_creation,requested_action,find_cancel_candidate,activate_verified_cancel

class Fake:
    def __init__(self,name='',typ='PaneControl',children=(),enabled=True,off=False,ok=True):
        self.Name=name;self.ControlTypeName=typ;self.children=list(children)
        self.IsEnabled=enabled;self.IsOffscreen=off;self.ok=ok;self.clicks=0
    def GetChildren(self):return self.children
    def GetInvokePattern(self):return self
    def Invoke(self):
        if not self.ok:raise Exception('Invoke not supported')
        self.clicks+=1
    def Click(self):self.clicks+=1
class Cases(unittest.TestCase):
    def test_exact_real_screenshot(self):
        body='Seguridad de Windows Guardar la clave de paso Cuenta Hotmail Clave de paso para login.microsoft.com Se guardará en tu dispositivo Windows Continuar Cancelar'
        self.assertTrue(verified_creation('Seguridad de Windows',body))
        self.assertEqual(requested_action('Seguridad de Windows',body,'Cancelar'),'Guardar la clave de paso de Microsoft')
    def test_blank_root_with_inner_title(self):
        cancel=Fake('Cancelar','ButtonControl')
        window=Fake('', 'WindowControl',[Fake('Seguridad de Windows','TextControl'),Fake('Guardar la clave de paso','TextControl'),Fake('Clave de paso para login.microsoft.com','TextControl'),cancel])
        self.assertIs(find_cancel_candidate(window,'credentialuibroker.exe'),cancel)
        self.assertTrue(activate_verified_cancel(cancel));self.assertEqual(cancel.clicks,1)
    def test_custom_button_fallback(self):
        cancel=Fake('Cancelar','CustomControl',ok=False)
        window=Fake('Seguridad de Windows','WindowControl',[Fake('Guardar la clave de paso, login.microsoft.com'),cancel])
        self.assertIs(find_cancel_candidate(window,'credentialuibroker.exe'),cancel)
        self.assertTrue(activate_verified_cancel(cancel));self.assertEqual(cancel.clicks,1)
    def test_reject_login_mfa_and_other_sites(self):
        for name,body in [
           ('Seguridad de Windows','Usar una clave de paso para iniciar sesión en login.microsoft.com'),
           ('Seguridad de Windows','Verifica tu identidad mediante un código de seguridad login.microsoft.com'),
           ('Seguridad de Windows','Guardar la clave de paso login.elsewhere.example'),
           ('Chrome','Guardar la clave de paso login.microsoft.com')]:
            self.assertFalse(verified_creation(name,body))
    def test_no_cancel_wrong_button(self):
        body='Guardar la clave de paso para login.microsoft.com'
        self.assertIsNone(requested_action('Seguridad de Windows',body,'Continuar'))
        self.assertIsNone(requested_action('Seguridad de Windows',body,'Cambiar'))
    def test_disabled_cancel(self):
        cancel=Fake('Cancelar','ButtonControl',enabled=False)
        window=Fake('Seguridad de Windows','WindowControl',[Fake('Guardar la clave de paso para login.microsoft.com'),cancel])
        self.assertIsNone(find_cancel_candidate(window))
if __name__=='__main__':unittest.main(verbosity=2)
