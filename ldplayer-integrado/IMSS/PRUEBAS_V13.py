# -*- coding: utf-8 -*-
import unittest
from unittest import mock
from pathlib import Path
import hashlib
import zipfile
import threading
from imss_paso1 import Node
import puente_imss_outlook_v13 as m

EMAIL='correo.prueba@example.com'

def node(text, cl='android.widget.TextView', rect=(1,1,500,80), clickable=False, enabled=True):
    return Node(clazz=cl,text=text,desc='',rid='',bounds=rect,
                checked=False,checkable=False,enabled=enabled,clickable=clickable)

def code_nodes(email=EMAIL, n=1,verify=False):
    nodes=[node('Ingresa tu código de validación'),node('Enviamos un código de validación al correo: '+email)]
    for i in range(n):
        nodes.append(node('', 'android.widget.EditText',(30+i*55,100,60+i*55,170)))
    if verify:
        nodes.append(node('Verificar','android.widget.Button',(100,250,350,310),clickable=True))
    return nodes

class BridgeTests(unittest.TestCase):
    def test_match_email(self):
        self.assertTrue(m.es_pantalla_codigo(code_nodes(),'correo.prueba@example.com'))
        self.assertFalse(m.es_pantalla_codigo(code_nodes(),'otro@example.com'))
    def test_refuse_unrecognized_screen(self):
        actions=[]
        with mock.patch.object(m,'foreground',return_value=True),mock.patch.object(m,'tap',side_effect=lambda *v:actions.append(v)):
            with self.assertRaises(m.IntegracionError):
                m.escribir_codigo_imss('adb','emulator-5554','bad@example.com','123456',ui=lambda *a:code_nodes())
        self.assertEqual(actions,[])
    def test_single_input_and_click_verify(self):
        seen=[]
        def send(*a,**kw):seen.append(a);return 0,''
        with mock.patch.object(m,'foreground',return_value=True),mock.patch.object(m,'tap',side_effect=lambda *a:seen.append(('tap',*a))):
            result=m.escribir_codigo_imss('adb','emulator-5554',EMAIL,'123456',ui=lambda *a:code_nodes(verify=True),enviar=send)
        self.assertEqual(result[0],'PULSADO')
        self.assertEqual(sum(x[0]=='tap' for x in seen),2)
    def test_six_inputs(self):
        calls=[]
        with mock.patch.object(m,'foreground',return_value=True),mock.patch.object(m,'tap'):
            result=m.escribir_codigo_imss('adb','emulator-5556',EMAIL,'123456',ui=lambda *a:code_nodes(n=6),enviar=lambda *a,**kw:(calls.append(a) or (0,'')))
        self.assertEqual(result[0],'MANUAL')
        self.assertIn('input text 1',calls[0][-1]);self.assertIn('input text 6',calls[0][-1])
    def test_no_code_echo(self):
        with mock.patch.object(m,'foreground',return_value=True),mock.patch.object(m,'tap'):
            result=m.escribir_codigo_imss('adb','emulator-5554',EMAIL,'123456',ui=lambda *a:code_nodes(),enviar=lambda *a,**kw:(0,''))
        self.assertNotIn('123456',repr(result))
    def test_manual_if_outlook_absent(self):
        class NoOutlook:
            def iniciar(self,*a):raise m.LinkError('Outlook no disponible')
        with mock.patch.object(m,'step_flow_v12') as fl:
            state=m.tramitar_con_outlook('adb','emulator-5554','CURP',EMAIL,'',False,lambda x:None,threading.Event(),puente=NoOutlook())
        self.assertEqual(state[0],'REVISAR');fl.assert_not_called()
    def test_deliver_end_to_end_fake(self):
        class Outlook:
            def __init__(self):self.calls=[]
            def iniciar(self,*a):self.calls.append('begin')
            def estado(self,*a):self.calls.append('status');return {'status':'CODIGO_DISPONIBLE','email':EMAIL,'code':'123456'}
            def confirmar_recepcion(self,*a):self.calls.append('ack')
            def terminar_enlace(self,*a):self.calls.append('done')
        p=Outlook()
        with mock.patch.object(m,'step_flow_v12',return_value=('ESPERANDO CÓDIGO','OK')),\
             mock.patch.object(m,'esperar_pantalla',return_value=True),\
             mock.patch.object(m,'escribir_codigo_imss',return_value=('PULSADO','OK')),\
             mock.patch.object(m,'quick_ui',return_value=[]):
            ans=m.tramitar_con_outlook('adb','emulator-5554','CURP',EMAIL,'',False,lambda x:None,threading.Event(),puente=p,uuid_factory=lambda:'a'*32)
        self.assertEqual(ans[0],'VALIDACIÓN EN CURSO')
        self.assertEqual(p.calls,['begin','status','ack','done'])
        self.assertTrue(ans[3])
    def test_link_compatible_files_unchanged(self):
        here=Path(__file__).resolve().parent
        outlook=here.parent/'OUTLOOK'/'enlace.py'
        self.assertEqual(hashlib.sha256((here/'enlace.py').read_bytes()).hexdigest(),hashlib.sha256(outlook.read_bytes()).hexdigest())
        src=Path('/mnt/data/GESTORIA_DIAZ_IMSS_DIGITAL_V12_CONEXION_APERTURA_RAPIDA.zip')
        if src.exists():
            with zipfile.ZipFile(src) as z:
                for name in z.namelist():
                    if name.endswith('/'):continue
                    self.assertEqual((here/Path(name).name).read_bytes(),z.read(name))

if __name__=='__main__': unittest.main(verbosity=2)
