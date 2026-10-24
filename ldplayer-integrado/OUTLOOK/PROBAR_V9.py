# -*- coding: utf-8 -*-
"""Pruebas locales (SIN conectarse a Microsoft ni enviar códigos)."""
import sys,unittest
from datetime import datetime,timezone,timedelta
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from navegador import (click_no_keep_session,imss_code_from_message,iso_dt,
    is_outlook_mail_url,BrowserLogin,STAY_SIGNED_IN)
from enlace import State

class FakeControl:
    def __init__(self,visible=True):self.visible=visible;self.clicks=0
    def is_visible(self):return self.visible
    def is_enabled(self):return True
    def click(self,**kwargs):self.clicks+=1

class FakeControls:
    def __init__(self,controls):self.controls=controls
    def count(self):return len(self.controls)
    def nth(self,i):return self.controls[i]

class FakePage:
    def __init__(self,url,stay=True):
        self.url=url;self.stay=stay;self.button=FakeControl()
    def get_by_text(self,regex):
        return FakeControls([FakeControl()] if self.stay else [])
    def get_by_role(self,role,name):
        return FakeControls([self.button])
    def locator(self,selector):
        return FakeControls([])

class V9Tests(unittest.TestCase):
    def test_01_stay_prompt_no(self):
        page=FakePage('https://login.live.com/ppsecure/post.srf')
        self.assertTrue(click_no_keep_session(page))
        self.assertEqual(page.button.clicks,1)
    def test_02_no_general_page(self):
        page=FakePage('https://outlook.live.com/mail/0/inbox')
        self.assertFalse(click_no_keep_session(page));self.assertEqual(page.button.clicks,0)
    def test_03_no_when_prompt_absent(self):
        page=FakePage('https://login.live.com/ppsecure/post.srf',False)
        self.assertFalse(click_no_keep_session(page));self.assertEqual(page.button.clicks,0)
    def test_04_stay_regex_es_en(self):
        self.assertIsNotNone(STAY_SIGNED_IN.search('¿Quieres mantener la sesión iniciada?'))
        self.assertIsNotNone(STAY_SIGNED_IN.search('Stay signed in?'))
    def test_05_outlook_inbox(self):
        self.assertTrue(is_outlook_mail_url('https://outlook.live.com/mail/0/inbox'))
        self.assertFalse(is_outlook_mail_url('https://evil.com/mail/'))
    def test_06_code_after_request(self):
        started='2026-10-22T23:00:00+00:00'
        received='2026-10-22T23:04:00Z'
        code=imss_code_from_message('avisos@example.com',received,
                  'IMSS - Código de validación','Tu código de validación es: 012345',
                  'avisos@example.com',started)
        self.assertEqual(code,'012345')
    def test_07_no_wrong_sender(self):
        self.assertIsNone(imss_code_from_message('no@example.com','2026-10-22T23:04:00Z',
           'IMSS código','Código 012345','avisos@example.com','2026-10-22T23:00:00Z'))
    def test_08_no_stale_code(self):
        self.assertIsNone(imss_code_from_message('avisos@example.com','2026-10-22T22:00:00Z',
           'IMSS código','Código 012345','avisos@example.com','2026-10-22T23:00:00Z'))
    def test_09_no_without_date(self):
        self.assertIsNone(imss_code_from_message('avisos@example.com','',
           'IMSS código','Código 012345','avisos@example.com','2026-10-22T23:00:00Z'))
    def test_10_no_without_imss_context(self):
        self.assertIsNone(imss_code_from_message('avisos@example.com','2026-10-22T23:04:00Z',
           'Oferta general','Compra 012345','avisos@example.com','2026-10-22T23:00:00Z'))
    def test_11_no_multiple_codes(self):
        self.assertIsNone(imss_code_from_message('avisos@example.com','2026-10-22T23:04:00Z',
           'IMSS Código de validación','Código 012345 y código 456789','avisos@example.com','2026-10-22T23:00:00Z'))
    def test_12_link_to_imss_state(self):
        state=State()
        id='a'*32
        state.start('usuario@example.com',id)
        events=[]
        b=BrowserLogin(events.append,request_supplier=state.status,
            deliver_code=lambda req,code,email:state.put_code(req,code,email=email))
        b.set_sender('avisos@example.com')
        self.assertEqual(b.sender,'avisos@example.com')
        b.deliver_code(id,'012345','usuario@example.com')
        self.assertEqual(state.status(id)['status'],'CODIGO_DISPONIBLE')
        state.acknowledge(id)
        self.assertIsNone(state.status(id)['code'])
    def test_13_no_code_from_other_account(self):
        state=State();id='b'*32
        state.start('real@example.com',id)
        b=BrowserLogin(lambda *_:None,request_supplier=state.status,
            deliver_code=lambda req,code,email:state.put_code(req,code,email=email))
        with self.assertRaises(ValueError):
            b.deliver_code(id,'012345','otra@example.com')
    def test_14_time_zone(self):
        self.assertEqual(iso_dt('2026-10-22T18:00:00-06:00'),iso_dt('2026-10-23T00:00:00Z'))
    def test_15_no_naive_timestamp(self):
        self.assertIsNone(iso_dt('2026-10-22T22:00:00'))

if __name__=='__main__':unittest.main(verbosity=2)
