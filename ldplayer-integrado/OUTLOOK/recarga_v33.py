# -*- coding: utf-8 -*-
"""One controlled reload per blank-screen incident (only Outlook mail and MS privacy notice).
Never reload login pages, MFA, passkeys, rate limits, or a populated page.
"""
import time
from urllib.parse import urlparse

MAIL_HOSTS={'outlook.live.com','outlook.office.com'}
PRIVACY_HOST='privacynotice.account.microsoft.com'

class PageStallGuard:
    def __init__(self, seconds=5):
        self.seconds=max(5,float(seconds))
        self.started={}; self.attempted=set(); self.last_url={}
    def consider(self,page,now=None):
        now=time.monotonic() if now is None else now
        url=str(getattr(page,'url','') or '')
        parts=urlparse(url)
        if parts.scheme!='https':return False
        host=(parts.hostname or '').lower()
        if not ((host in MAIL_HOSTS and parts.path.lower().startswith('/mail')) or host==PRIVACY_HOST):
            return False
        # Include URL in key; changing mailboxes/navigation starts a new incident.
        key=(host,parts.path,parts.query)
        if key in self.attempted:return False
        try:
            content=(page.locator('body').inner_text(timeout=950) or '').strip()
            # Don't reload any page showing an authentic prompt, login form or message.
            if content:
                self.started.pop(key,None)
                return False
            # Blank body plus no visible interactive inputs is required.
            if page.locator('input:visible, button:visible, a:visible').count():
                self.started.pop(key,None)
                return False
        except Exception:
            return False
        started=self.started.setdefault(key,now)
        if now-started<self.seconds:return False
        self.attempted.add(key)
        try:
            page.reload(wait_until='commit',timeout=10000)
            return True
        except Exception:
            # Even if navigation times out, don't aggressively retry Microsoft.
            return False
