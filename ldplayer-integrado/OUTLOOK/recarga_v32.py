# -*- coding: utf-8 -*-
"""Safe, at-most-once retry of a blank Outlook page. Never reload login or MFA."""
import time
from urllib.parse import urlparse

class PageStallGuard:
    def __init__(self,seconds=26):
        self.seconds=seconds;self.started={};self.attempted=set()
    def consider(self,page,now=None):
        now=time.monotonic() if now is None else now
        url=str(getattr(page,'url','') or '')
        parts=urlparse(url)
        if not (parts.scheme=='https' and (parts.hostname or '').lower() in ('outlook.live.com','outlook.office.com') and parts.path.lower().startswith('/mail')):return False
        key=urlparse(url).netloc.lower()
        if key in self.attempted:return False
        try:
            state=page.evaluate('document.readyState')
            content=(page.locator('body').inner_text(timeout=900) or '')[:400]
            # Nonempty page text / a legitimate load in progress is not a blank page.
            blank=(not content.strip())
        except Exception:return False
        if not blank:
            self.started.pop(key,None)
            return False
        start=self.started.setdefault(key,now)
        if now-start<self.seconds:return False
        self.attempted.add(key)
        try:
            page.reload(wait_until='domcontentloaded',timeout=16000)
            return True
        except Exception:
            # A navigation timeout is not a reason to close the window.
            return False
