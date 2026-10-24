# -*- coding: utf-8 -*-
"""Pruebas simuladas, sin acceder a IMSS ni leer datos reales."""
import unittest
from unittest.mock import patch
import imss_flujo_v11 as f
from imss_paso1 import parse_ui
from gestoria_prueba_v7 import select_serials

def nodes(*items):
    xml='<hierarchy>'+''.join('<node class="%s" text="%s" enabled="true" clickable="%s" bounds="%s"/>' % (clazz,txt,str(click).lower(),rect) for clazz,txt,click,rect in items)+'</hierarchy>'
    return parse_ui(xml)

NOTICE=nodes(('android.widget.TextView','Para poder acceder, debes de haber confirmado tu correo electrónico.',False,'[0,0][480,300]'),
             ('android.widget.Button','CANCELAR',True,'[190,410][340,450]'),
             ('android.widget.Button','CONFIRMAR',True,'[345,410][480,450]'))
NOT_OTHER=nodes(('android.widget.TextView','¿Desea cambiar su dispositivo?',False,'[0,0][480,300]'),
             ('android.widget.Button','CONFIRMAR',True,'[345,410][480,450]'))
PIN=nodes(('android.widget.TextView','Validación de identidad',False,'[0,0][500,120]'),
          ('android.widget.TextView','Confirma tu identidad para ingresar.',False,'[0,170][500,260]'),
          ('android.widget.EditText','',True,'[100,600][400,660]'))
CODE=nodes(('android.widget.TextView','Código enviado a tu correo',False,'[0,0][500,200]'))
LOGIN=nodes(('android.widget.TextView','Inicia sesión CURP correo electrónico',False,'[0,0][500,130]'),
            ('android.widget.EditText','',True,'[0,190][500,230]'),
            ('android.widget.EditText','',True,'[0,290][500,330]'))
class TestV11(unittest.TestCase):
    def test_connect_three_same_as_v7(self):
        x=select_serials({'emulator-5554':'device','emulator-5556':'device','emulator-5558':'device','127.0.0.1:5555':'device'})
        self.assertEqual([b for a,b in x],['emulator-5554','emulator-5556','emulator-5558'])
    def test_exact_notice(self):
        self.assertTrue(f.is_email_notice(NOTICE))
        self.assertFalse(f.is_email_notice(NOT_OTHER))
        self.assertFalse(f.is_email_notice(PIN))
    def test_click_only_confirm_not_cancel(self):
        with patch.object(f,'foreground',return_value=True),patch.object(f,'tap') as tap:
            ok,msg=f.confirm_email_notice('adb','emulator-5554',NOTICE)
        self.assertTrue(ok)
        tap.assert_called_once_with('adb','emulator-5554',412,430)
    def test_no_click_unrelated(self):
        with patch.object(f,'foreground',return_value=True),patch.object(f,'tap') as tap:
            ok,_=f.confirm_email_notice('adb','emulator-5554',NOT_OTHER)
        self.assertFalse(ok); tap.assert_not_called()
    def test_notice_without_button_stops(self):
        bare=[n for n in NOTICE if n.text!='CONFIRMAR']
        with patch.object(f,'foreground',return_value=True),patch.object(f,'tap') as tap:
            ok,msg=f.confirm_email_notice('adb','emulator-5554',bare)
        self.assertFalse(ok);tap.assert_not_called()
    def test_fast_ui_single_call(self):
        with patch.object(f,'adb_run',return_value=(0,'<?xml version="1.0"?><hierarchy><node text="OK" class="android.widget.TextView" bounds="[0,0][200,100]"/></hierarchy>')) as adb:
            result=f.quick_ui('adb','emulator-5554')
        self.assertEqual(len(result),1)
        adb.assert_called_once()
    def test_skip_clear_on_empty(self):
        checked=nodes(('android.widget.TextView','Inicia sesión',False,'[0,0][500,130]'),
            ('android.widget.EditText','ABCD1234',True,'[0,190][500,230]'),
            ('android.widget.EditText','bad@example.com',True,'[0,290][500,330]'))
        # Test empty case: no 100-key deletion.
        with patch.object(f,'foreground',return_value=True),patch.object(f,'quick_ui',side_effect=[LOGIN,LOGIN]), \
             patch.object(f,'screen_size',return_value=(720,1280)),patch.object(f,'tap'), \
             patch.object(f,'clear_field') as clear,patch.object(f,'type_ascii'),patch.object(f,'adb_run',return_value=(0,'')):
            ok,_=f.fast_login('adb','emulator-5554','AAAA1111BBBB2222CC','me@example.com')
        self.assertTrue(ok);clear.assert_not_called()
    def test_flow_notice_after_pin(self):
        seq=iter([LOGIN,PIN,NOTICE,NOTICE,CODE])
        with patch.object(f,'fast_login',return_value=(True,'ok')), patch.object(f,'quick_ui',side_effect=lambda *_:next(seq)), \
             patch.object(f,'fast_pin_once',return_value=(True,'PIN')) as pin, \
             patch.object(f,'confirm_email_notice',return_value=(True,'confirmed')) as confirm, \
             patch.object(f.time,'sleep'):
            state,_=f.step_flow('adb','emulator-5556','CURP','email','pin')
        self.assertEqual(state,'ESPERANDO CÓDIGO');pin.assert_called_once();confirm.assert_called_once()
    def test_flow_doesnt_click_duplicate_notice(self):
        with patch.object(f,'fast_login',return_value=(True,'ok')),patch.object(f,'quick_ui',return_value=NOTICE), \
             patch.object(f,'confirm_email_notice',return_value=(True,'confirmed')) as click,patch.object(f.time,'sleep'):
            state,_=f.step_flow('adb','emulator-5558','CURP','email','pin')
        self.assertEqual(state,'REVISAR');click.assert_called_once()
    def test_pin_entry_confirm_once(self):
        with patch.object(f,'tap'),patch.object(f,'type_ascii') as typed,patch.object(f,'quick_ui',return_value=PIN),patch.object(f,'adb_run',return_value=(0,'')) as adb:
            ok,_=f.fast_pin_once('adb','emulator-5558','0000',PIN)
        self.assertTrue(ok)
        typed.assert_called_once_with('adb','emulator-5558','0000')
        adb.assert_called_once_with('adb','emulator-5558','shell','input','keyevent','66',timeout=9)
if __name__=='__main__': unittest.main(verbosity=2)
