# -*- coding: utf-8 -*-
"""Pruebas unitarias con correos y códigos inventados (sin conexión real)."""
import unittest
from unittest.mock import patch, Mock
import lector_reciente_v14 as reader
import navegador as base
from enlace import State

SENDER='avisos@example.invalid'
TIME='2026-10-23T20:10:00Z'
START='2026-10-23T20:00:00Z'
BODY='IMSS Digital. Tu código de validación es: 012345.'

class FakeRow:
    def click(self, **kwargs):pass

class FakePage:
    url='https://outlook.live.com/mail/0/inbox'
    def wait_for_timeout(self, ms):pass

class LectorRecienteTests(unittest.TestCase):
    def scan(self,sender=SENDER,when=TIME,body=BODY,started=START,rows=None):
        rows=rows if rows is not None else [('nuevo',FakeRow(),'IMSS Digital código de validación')]
        with patch.object(reader,'_freshest_rows',return_value=rows),\
             patch.object(reader,'_correct_sender',return_value=sender==SENDER),\
             patch.object(reader,'_message_data',return_value=(when,body)):
            return reader.scan_visible_inbox(FakePage(),SENDER,started,set())

    def test_reciente_seis_digitos(self):
        self.assertEqual(self.scan(),'012345')

    def test_remitente_ajeno_no_se_entrega(self):
        self.assertIsNone(self.scan(sender='phishing@example.invalid'))

    def test_viejo_no_se_entrega(self):
        self.assertIsNone(self.scan(when='2026-10-23T19:30:00Z'))

    def test_fecha_no_verificable_no_entrega(self):
        self.assertEqual(self.scan(when=None),'fecha_no_verificable')

    def test_no_admite_codigos_multiples(self):
        self.assertIsNone(self.scan(body='IMSS código 012345 y 567890'))

    def test_unicos_codigos_seis(self):
        self.assertIsNone(self.scan(body='IMSS código 12345'))

    def test_outlook_other_site_rejected(self):
        page=FakePage();page.url='https://example.invalid/mail/'
        self.assertIsNone(reader.scan_visible_inbox(page,SENDER,START,set()))

    def test_fecha_rfc_complementaria(self):
        self.assertIsNotNone(reader._iso_utc('Fri, 23 Oct 2026 20:12:00 +0000'))
        self.assertIsNone(reader._iso_utc('10:04'))

    def test_reintento_no_descarta_correo_si_falta_fecha(self):
        row=FakeRow();ignore=set()
        with patch.object(reader,'_freshest_rows',return_value=[('uno',row,'IMSS validación')]),\
             patch.object(reader,'_correct_sender',return_value=True),\
             patch.object(reader,'_message_data',side_effect=[(None,BODY),(TIME,BODY)]):
            self.assertEqual(reader.scan_visible_inbox(FakePage(),SENDER,START,ignore),'fecha_no_verificable')
            self.assertEqual(ignore,set())
            self.assertEqual(reader.scan_visible_inbox(FakePage(),SENDER,START,ignore),'012345')

    def test_entrega_al_enlace_local_con_folio_correcto(self):
        state=State();folio='d'*32
        state.start('titular@example.invalid',folio)
        code=self.scan()
        state.put_code(folio,code,email='titular@example.invalid')
        self.assertEqual(state.status(folio)['status'],'CODIGO_DISPONIBLE')
        self.assertEqual(state.status(folio)['code'], '012345')
        with self.assertRaises(ValueError):
            state.put_code(folio,'012345',email='otro@example.invalid')
        state.acknowledge(folio)
        self.assertIsNone(state.status(folio)['code'])

if __name__=='__main__':unittest.main(verbosity=2)
