# -*- coding: utf-8 -*-
"""Safety tests with synthetic data only; never access a real mailbox."""
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch
import lector_reciente_v29 as r
from enlace import State
S='aviso@example.invalid'

class DummyRow:
    def click(self, **kw):pass

class DummyPage:
    url='https://outlook.live.com/mail/0/inbox'
    def wait_for_timeout(self,ms):pass

class NewReaderTests(unittest.TestCase):
    def setUp(self):
        now=datetime.now(timezone.utc)
        self.now=now
        self.start=(now-timedelta(minutes=4)).isoformat()
        # Different display timezone from Windows (as in the recording).
        displayed=now+timedelta(hours=2,minutes=-1)
        self.body=('Código de Verificación\n'+S+'\n'+displayed.strftime('Fri %Y-%m-%d %H:%M')+
                   '\nEstimado usuario. Tu código de verificación es: 654321\n'
                   'Este código expira en 20 minutos')

    def scan(self,body=None,correct=True,start=None,url=None):
        page=DummyPage()
        if url:page.url=url
        with patch.object(r,'_freshest_rows',return_value=[('msg-new',DummyRow(),'Código de Verificación IMSS')]),\
             patch.object(r,'_correct_sender',return_value=correct),\
             patch.object(r,'_message_data',return_value=(None,self.body if body is None else body)):
            return r.scan_visible_inbox(page,S,start or self.start,set())

    def test_live_visible_header_delivers_unique_code(self):
        self.assertEqual('654321',self.scan())

    def test_sender_mismatch_rejected(self):
        self.assertIsNone(self.scan(correct=False))

    def test_no_visible_date_refuses_to_guess(self):
        self.assertEqual('fecha_no_verificable',self.scan(body='Código de Verificación\n'+S+'\nTu código es: 654321'))

    def test_day_old_header_refused(self):
        old=self.now-timedelta(days=4)
        self.assertEqual('fecha_no_verificable',self.scan(body='Código de Verificación\n'+S+'\nFri '+old.strftime('%Y-%m-%d %H:%M')+'\nCódigo 654321'))

    def test_outdated_request_refuses_fallback(self):
        self.assertEqual('fecha_no_verificable',self.scan(start=(self.now-timedelta(minutes=40)).isoformat()))

    def test_other_domain_rejected(self):
        self.assertIsNone(self.scan(url='https://bad.invalid/mail/'))

    def test_many_codes_rejected(self):
        self.assertNotEqual('654321',self.scan(body=self.body+'\nOtro 999999'))

    def test_current_code_local_bridge_delivery(self):
        state=State(); folio='e'*32
        state.start('own@example.invalid', folio)
        code=self.scan()
        state.put_code(folio,code,email='own@example.invalid')
        self.assertEqual(state.status(folio)['status'],'CODIGO_DISPONIBLE')
        state.acknowledge(folio)
        self.assertEqual(state.status(folio)['status'],'CODIGO_ENVIADO_AL_CELULAR')
        self.assertIsNone(state.status(folio)['code'])

if __name__ == '__main__':unittest.main(verbosity=2)
