# -*- coding: utf-8 -*-
import unittest,sqlite3,tempfile,os
from pathlib import Path
from datetime import datetime, timezone, timedelta
from unittest.mock import patch
from lector_reciente_v39 import scan_visible_inbox, compact_inbox_verified
from tests_v38 import Page
from pool_v14 import SharedPool,PoolError
from administrar_correos_v39 import clear_available_list

SENDER='verifica-noreplay@imss.gob.mx'
class Tests39(unittest.TestCase):
    def test_first_code_without_technical_date(self):
        page=Page(); seen=set(); now=datetime.now(timezone.utc).isoformat()
        body='Código de Verificación\nEstimado usuario, tu código de verificación es: 654321\nIMSS'
        with patch('lector_reciente_v39._rows_v29',return_value=[]),\
             patch('lector_reciente_v39._correct_sender',return_value=True),\
             patch('lector_reciente_v39._message_data',return_value=(None,body)):
            result=scan_visible_inbox(page,SENDER,now,seen)
            self.assertEqual(result,'654321')
            self.assertEqual(len(seen),1)
            self.assertIsNone(scan_visible_inbox(page,SENDER,now,seen))
    def test_old_request_rejected(self):
        page=Page(); seen=set()
        started=(datetime.now(timezone.utc)-timedelta(minutes=20)).isoformat()
        with patch('lector_reciente_v39._rows_v29',return_value=[]):
            self.assertIsNone(scan_visible_inbox(page,SENDER,started,seen))
    def test_no_sender_no_code(self):
        page=Page(); seen=set(); started=datetime.now(timezone.utc).isoformat()
        with patch('lector_reciente_v39._rows_v29',return_value=[]),\
             patch('lector_reciente_v39._correct_sender',return_value=False):
            self.assertIsNone(scan_visible_inbox(page,SENDER,started,seen))
    def test_two_codes_not_delivered(self):
        page=Page(); seen=set(); started=datetime.now(timezone.utc).isoformat()
        with patch('lector_reciente_v39._rows_v29',return_value=[]),\
             patch('lector_reciente_v39._correct_sender',return_value=True),\
             patch('lector_reciente_v39._message_data',return_value=(None,'Código de Verificación, IMSS, 654321 y 123456')):
            self.assertIsNone(scan_visible_inbox(page,SENDER,started,seen))
    def test_list_clear_and_busy_block(self):
        with tempfile.TemporaryDirectory() as d:
            pool=SharedPool(Path(d)/'pool.sqlite3')
            pool.add(['a@example.com','b@example.com'])
            self.assertEqual(len(clear_available_list(pool)),2)
            self.assertEqual(pool.counts()['EN_LISTA'],0)
            pool.add(['c@example.com','d@example.com'])
            with pool.db() as db:db.execute("UPDATE cuentas SET estado='OCUPADO' WHERE email='c@example.com'")
            with self.assertRaises(PoolError):clear_available_list(pool)
            self.assertEqual(pool.counts()['EN_LISTA'],2)
    def test_completed_count_preserved(self):
        with tempfile.TemporaryDirectory() as d:
            pool=SharedPool(Path(d)/'pool.sqlite3')
            pool.add(['x@example.com'])
            with pool.db() as db:db.execute("UPDATE contadores SET cantidad=8 WHERE clave='eliminados'")
            clear_available_list(pool)
            self.assertEqual(pool.counts()['ELIMINADOS'],8)

if __name__=='__main__':unittest.main()
