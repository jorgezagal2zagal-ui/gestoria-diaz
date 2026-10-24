# -*- coding: utf-8 -*-
import unittest
from unittest.mock import patch
from datetime import datetime,timezone
from lector_reciente_v38 import scan_visible_inbox,compact_inbox_verified,_text_rows

class Locator:
    def __init__(self,text='',visible=True,parents=None):
        self.text=text;self.visible=visible;self.parents=list(parents or []);self.clicked=0
    def inner_text(self,timeout=1200):return self.text
    def is_visible(self):return self.visible
    def locator(self,query):return self.parents[0] if self.parents else self
    def get_attribute(self,key):return None
    def click(self,timeout=4500):self.clicked+=1
    def count(self):return 1
    @property
    def first(self):return self
    def nth(self,index):return self

class Page:
    url='https://outlook.live.com/mail/'
    def __init__(self):
        self.subject=Locator('Código de Verificación')
        parent=Locator('verifica-noreplay@imss.gob.mx\nCódigo de Verificación\nEstimado usuario')
        self.subject.parents=[parent]
        self.parent=parent
        self.body=Locator('Outlook  New mail  Focused Other\nverifica-noreplay@imss.gob.mx Código de Verificación')
    def locator(self,selector):
        if selector=='body':return self.body
        return Locator('mail UI',True)
    def get_by_text(self,pattern):return self.subject
    def wait_for_timeout(self,ms):pass

class Tests(unittest.TestCase):
    def test_compact_mailbox(self):
        page=Page()
        with patch('lector_reciente_v38._original_inbox_verified',return_value=False):
            self.assertTrue(compact_inbox_verified(page))
    def test_ignores_non_mail_url(self):
        p=Page();p.url='https://example.com/mail/'
        self.assertFalse(compact_inbox_verified(p))
    def test_find_subject_without_aria_row(self):
        p=Page();rows=list(_text_rows(p,'verifica-noreplay@imss.gob.mx'))
        self.assertEqual(len(rows),1)
        self.assertIn('verifica-noreplay@',rows[0][2])
    def test_not_ignored_if_click_has_not_opened(self):
        p=Page();seen=set()
        with patch('lector_reciente_v38._rows_v29',return_value=[]),patch('lector_reciente_v38._correct_sender',return_value=False):
            self.assertIsNone(scan_visible_inbox(p,'verifica-noreplay@imss.gob.mx',datetime.now(timezone.utc).isoformat(),seen))
        self.assertEqual(seen,set());self.assertEqual(p.parent.clicked,1)
    def test_valid_email_only_then_deliver(self):
        p=Page();seen=set();now=datetime.now(timezone.utc).isoformat()
        body='Código de Verificación\nverifica-noreplay@imss.gob.mx\nHoy, código de verificación: 654321'
        with patch('lector_reciente_v38._rows_v29',return_value=[]),\
             patch('lector_reciente_v38._correct_sender',return_value=True),\
             patch('lector_reciente_v38._message_data',return_value=(now,body)),\
             patch('lector_reciente_v38.nav.imss_code_from_message',return_value='654321'):
            self.assertEqual(scan_visible_inbox(p,'verifica-noreplay@imss.gob.mx',now,seen),'654321')
        self.assertEqual(len(seen),1)
    def test_ambiguous_code_not_transmitted(self):
        p=Page();seen=set();now=datetime.now(timezone.utc).isoformat()
        body='Código de Verificación\nTu código 654321, otro 123456'
        with patch('lector_reciente_v38._rows_v29',return_value=[]),\
             patch('lector_reciente_v38._correct_sender',return_value=True),\
             patch('lector_reciente_v38._message_data',return_value=(now,body)):
            self.assertIsNone(scan_visible_inbox(p,'verifica-noreplay@imss.gob.mx',now,seen))
    def test_closed_pane_retried(self):
        p=Page();seen=set();now=datetime.now(timezone.utc).isoformat()
        with patch('lector_reciente_v38._rows_v29',return_value=[]),\
             patch('lector_reciente_v38._correct_sender',return_value=True),\
             patch('lector_reciente_v38._message_data',return_value=(None,'')):
            self.assertIsNone(scan_visible_inbox(p,'verifica-noreplay@imss.gob.mx',now,seen))
        self.assertEqual(seen,set())
if __name__=='__main__':unittest.main()
