# -*- coding: utf-8 -*-
"""Pruebas simuladas que no usan servicios del IMSS ni los datos de clientes."""
import unittest
from unittest.mock import patch, MagicMock
from imss_paso1 import Node
import imss_flujo_v12 as f
import gestoria_panel_v12 as g
from gestoria_prueba_v7 import select_serials

def node(text='',clazz='android.widget.TextView',y=100,checkable=False,checked=False,clickable=False):
    return Node(clazz,text,'','',(15,y,500,y+40),checked,checkable,True,clickable)
LOGIN=[node('Inicia sesión'),node('Ingresa CURP','android.widget.EditText',180),
       node('Correo electrónico','android.widget.EditText',275),
       node('He leído y acepto el Aviso de Privacidad','android.widget.CheckBox',500,True,True),
       node('INICIAR SESIÓN','android.widget.Button',710,clickable=True)]
FILLED=[node('Inicia sesión'),node('ABCD1234EFGH5678IJ','android.widget.EditText',180),
       node('test@example.com','android.widget.EditText',275),
       node('He leído y acepto el Aviso de Privacidad','android.widget.CheckBox',500,True,True),
       node('INICIAR SESIÓN','android.widget.Button',710,clickable=True)]
PIN=[node('Validación de identidad'),node('Confirma tu identidad para ingresar.'),node('','android.widget.EditText',630)]
OTP=[node('Código enviado a tu correo')]

class TestsV12(unittest.TestCase):
    def test_identifica_los_tres(self):
        found={'127.0.0.1:5555':'device','emulator-5554':'device',
               'emulator-5556':'device','emulator-5558':'device'}
        self.assertEqual([s for _,s in select_serials(found)],
                         ['emulator-5554','emulator-5556','emulator-5558'])

    def test_llenado_una_sola_llamada_adb(self):
        with patch.object(f,'adb_run',return_value=(0,'')) as adb:
            f.fast_fill_fields('adb','emulator-5554',[(30,40,'ABCD1234', ''),(30,100,'test@example.com','')])
        self.assertEqual(adb.call_count,1)
        args=adb.call_args.args
        self.assertEqual(args[:4],('adb','emulator-5554','shell','sh'))
        self.assertEqual(args[4],'-c')
        self.assertEqual(args[5].count('input text'),2)
        self.assertEqual(args[5].count('input tap'),2)
        self.assertIn('input keyevent 4',args[5])

    def test_no_sugerir_inyeccion_shell(self):
        with self.assertRaises(ValueError):
            f.fast_fill_fields('adb','emulator-5554',[(1,2,'CORREO;rm -rf /','')])

    def test_login_rapido_valida_antes_de_enviar(self):
        with patch.object(f,'foreground',return_value=True), \
             patch.object(f,'quick_ui',side_effect=[LOGIN,FILLED]), \
             patch.object(f,'screen_size',return_value=(720,1280)), \
             patch.object(f,'fast_fill_fields') as fill, patch.object(f,'tap') as tap:
            ok,_=f.fast_login_v12('adb','emulator-5554','ABCD1234EFGH5678IJ','test@example.com')
        self.assertTrue(ok)
        fill.assert_called_once()
        tap.assert_called_once()  # aviso estaba marcado => solo login

    def test_sin_validacion_campos_no_envia(self):
        wrong=[*LOGIN[:1],node('CURP INCORRECTO','android.widget.EditText',180),*LOGIN[2:]]
        with patch.object(f,'foreground',return_value=True), \
             patch.object(f,'quick_ui',side_effect=[LOGIN,wrong]), \
             patch.object(f,'screen_size',return_value=(720,1280)), \
             patch.object(f,'fast_fill_fields'), patch.object(f,'tap') as tap:
            ok,_=f.fast_login_v12('adb','emulator-5554','ABCD1234EFGH5678IJ','test@example.com')
        self.assertFalse(ok);tap.assert_not_called()

    def test_pin_una_vez_y_enter(self):
        with patch.object(f,'adb_run',return_value=(0,'')) as adb, \
             patch.object(f,'quick_ui',return_value=PIN):
            ok,_=f.fast_pin_v12('adb','emulator-5558','0000',PIN)
        self.assertTrue(ok)
        self.assertEqual(adb.call_count,2)
        self.assertEqual(adb.call_args.args[-3:],('input','keyevent','66'))

    def test_no_pin_en_pantalla_otp(self):
        with patch.object(f,'adb_run') as adb:
            ok,_=f.fast_pin_v12('adb','emulator-5558','0000',OTP)
        self.assertFalse(ok);adb.assert_not_called()

    def test_si_imss_ya_esta_abierto_no_relanza(self):
        with patch.object(g,'adb_run',return_value=(0,'GESTORIA_OK')), \
             patch.object(g,'foreground',return_value=True), \
             patch.object(g,'quick_ui',return_value=LOGIN), \
             patch.object(g,'launch_imss') as launch:
            state,detail=g.PanelV12.start_and_assess('adb','emulator-5554')
        self.assertEqual(state,'LIBRE');launch.assert_not_called()

    def test_si_imss_cerrado_abre_v7(self):
        with patch.object(g,'adb_run',return_value=(0,'GESTORIA_OK')), \
             patch.object(g,'foreground',return_value=False), \
             patch.object(g,'quick_ui',return_value=LOGIN), \
             patch.object(g,'launch_imss',return_value=('ABIERTA','ok')) as launch:
            state,detail=g.PanelV12.start_and_assess('adb','emulator-5556')
        self.assertEqual(state,'LIBRE');launch.assert_called_once()

    def test_si_en_otp_no_libera(self):
        with patch.object(g,'adb_run',return_value=(0,'GESTORIA_OK')), \
             patch.object(g,'foreground',return_value=True), \
             patch.object(g,'quick_ui',return_value=OTP):
            state,_=g.PanelV12.start_and_assess('adb','emulator-5558')
        self.assertNotEqual(state,'LIBRE')

    def test_un_solo_boton_conecta_abre(self):
        # Prueba sin Tkinter: capturar el resultado entregado al panel.
        shell=object.__new__(g.PanelV12)
        delivered=[]
        shell.send=lambda *args:delivered.append(args)
        emulators='List of devices attached\nemulator-5554 device\nemulator-5556 device\nemulator-5558 device\n'
        def fake_process(args,timeout=15):
            return (0,emulators) if 'devices' in args else (0,'')
        with patch.object(g,'locate_adb',return_value='D:/LDPlayer/adb.exe'),\
             patch.object(g,'process',side_effect=fake_process),\
             patch.object(g.PanelV12,'start_and_assess',return_value=('LIBRE','IMSS abierto')) as check:
            shell.connect_worker()
        attached=[x for x in delivered if x[0]=='attached']
        self.assertEqual(len(attached),1)
        self.assertEqual(check.call_count,3)
        self.assertEqual(attached[0][2],['emulator-5554','emulator-5556','emulator-5558'])
        self.assertTrue(all(item[0]=='LIBRE' for item in attached[0][3]))

if __name__=='__main__':unittest.main(verbosity=2)
