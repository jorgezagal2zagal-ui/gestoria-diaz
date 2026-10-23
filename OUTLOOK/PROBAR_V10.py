# -*- coding: utf-8 -*-
import unittest
from navegador import is_microsoft_rate_limited, BrowserLogin
class Body:
    def __init__(self,value):self.value=value
    def inner_text(self, timeout=None): return self.value
class Page:
    def __init__(self,url,text):self.url=url;self.text=text
    def locator(self,key):return Body(self.text)
class Tests(unittest.TestCase):
    def test_limit(self):
        self.assertTrue(is_microsoft_rate_limited(Page('https://login.live.com/ppsecure/post.srf','Too Many Requests')))
    def test_spanish(self):
        self.assertTrue(is_microsoft_rate_limited(Page('https://login.live.com/login.srf','Demasiadas solicitudes')))
    def test_normal(self):
        self.assertFalse(is_microsoft_rate_limited(Page('https://login.live.com/login.srf','Iniciar sesión')))
    def test_other_host(self):
        self.assertFalse(is_microsoft_rate_limited(Page('https://example.com','Too Many Requests')))
    def test_disable_reopen_after_limit(self):
        logs=[];b=BrowserLogin(logs.append);b.rate_limited=True;b.reopen_form();b.retry_email();b.open_mail()
        self.assertEqual(len(logs),3)
        self.assertFalse(b.reopen_requested.is_set())
        self.assertFalse(b.retry_requested.is_set())
        self.assertFalse(b.open_mail_requested.is_set())
if __name__=='__main__': unittest.main(verbosity=2)
