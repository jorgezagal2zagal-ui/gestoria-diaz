# -*- coding: utf-8 -*-
"""V15: comprobar bandeja ANTES de que IMSS use un correo."""
import time
import tkinter as tk
import app as previous
import navegador_v15 as nv
from lector_reciente_v14 import scan_visible_inbox
nv.scan_visible_inbox=scan_visible_inbox
previous.BrowserLogin=nv.BrowserLogin
from app_v14 import OutlookV14
from preparacion_v15 import Preparation

class OutlookV15(OutlookV14):
    def __init__(self):
        self.preparacion=Preparation()
        self.prep_id=None
        self.prep_email=None
        self.prep_started=0
        super().__init__()
        self.title('GESTORÍA DÍAZ · OUTLOOK V15 · PRIMERO BANDEJA')
        self.info.set('Primero se confirma acceso real a la bandeja. Después comienza IMSS Digital.')
        self._auto_queue_enabled.set()
        self.auto_queue.set(True)
    def _maybe_auto_start(self,state):
        # Prohibido abrir cuentas por solicitud IMSS hasta que preparación diga LISTO.
        return None
    def _tick_once(self):
        super()._tick_once()
        if self._closed or not self.server:return
        self.preparacion.heartbeat()
        p=self.preparacion.pending()
        if self.prep_id:
            cur=self.preparacion.status(self.prep_id)
            if not cur or cur['estado'] not in ('ABRIENDO','PENDIENTE'):
                self.prep_id=None;self.prep_email=None
            elif self.browser.rate_limited:
                self.preparacion.set(self.prep_id,self.prep_email,'LIMITE_MICROSOFT')
                self.info.set('Microsoft limitó accesos. DETENIDO: no se probarán otras cuentas.')
                return
            elif getattr(self.browser,'blocked',False):
                self.preparacion.set(self.prep_id,self.prep_email,'BLOQUEADA')
                self.info.set('Microsoft bloqueó esta cuenta. Apartada para revisión; no se intenta desbloquear.')
                if self.browser.running:self.close_private()
                return
            elif self.browser.running and self.active_email==self.prep_email and self.browser.phase=='mail':
                self.preparacion.set(self.prep_id,self.prep_email,'LISTO')
                self.info.set('Bandeja confirmada. IMSS ya puede iniciar con la cuenta reservada.')
                self.prep_id=None;self.prep_email=None
                return
            elif time.monotonic()-self.prep_started>145:
                self.preparacion.set(self.prep_id,self.prep_email,'REVISAR')
                self.info.set('Outlook no confirmó su bandeja; verificar antes de reintentar.')
                if self.browser.running:self.close_private()
                return
        if not p or self.prep_id or self.browser.running or self.browser.rate_limited or self.cooldown.remaining():return
        if self.state.status()['status'] not in ('SIN_SOLICITUD','CANCELADA','CADUCADA','SOLICITUD_IMSS_ENVIADA'):return
        email,folio=p['email'],p['folio']
        if p['estado']=='ABRIENDO':
            # Reinicio de Outlook mientras se preparaba la cuenta: no iniciar dos veces sin revisión.
            self.preparacion.set(folio,email,'REVISAR');return
        try: password=self._vault().password(email)
        except Exception: password=None
        if not password:
            self.preparacion.set(folio,email,'REVISAR')
            self.info.set('No existe contraseña cifrada para la cuenta reservada.');return
        if self.preparacion.set(folio,email,'ABRIENDO'):
            self.prep_id=folio;self.prep_email=email;self.prep_started=time.monotonic()
            if not self._start_browser(email,password):
                self.preparacion.set(folio,email,'REVISAR')
                self.prep_id=None;self.prep_email=None

if __name__=='__main__':OutlookV15().mainloop()
