# -*- coding: utf-8 -*-
"""Outlook V22: detecta cola vacía y usa pausa corta solo tras una sesión válida.

No salta límites ni verificaciones de Microsoft; no cambia la lista de correos.
"""
import tkinter as tk
from app_v21 import OutlookV21
from pausa_v22 import completed_mailbox,interval_seconds

class OutlookV22(OutlookV21):
    def __init__(self):
        super().__init__()
        self.title('GESTORÍA DÍAZ · OUTLOOK V22 · ESPERA CONTROLADA')
        main=self.winfo_children()[0]
        self.queue_hint=tk.StringVar(value='Comprobando solicitudes IMSS…')
        tk.Label(main,textvariable=self.queue_hint,bg='#101419',fg='#E8BB62',
                 wraplength=730,justify='left').pack(anchor='w',pady=6)
        self._previous_success=False
        self._update_explain()

    def _healthy(self):
        b=self.browser
        return completed_mailbox(getattr(b,'phase',''),
            rate_limited=bool(getattr(b,'rate_limited',False)),
            blocked=bool(getattr(b,'blocked',False)),
            extra_verification=bool(getattr(b,'extra_verification',False)),
            password_unavailable=bool(getattr(b,'password_unavailable',False)))

    def close_private(self):
        # Solo éxito con bandeja ya comprobada; bloqueo/verificación/429 siempre >=30s.
        self._previous_success=self._healthy()
        self.cooldown.seconds=interval_seconds(self._previous_success)
        return super().close_private()

    def _tick_once(self):
        # El cierre por excepción también activa la pausa larga.
        if self.browser.running:
            self._previous_success=self._healthy()
        if getattr(self,'_previous_browser_running',False) and not self.browser.running:
            self.cooldown.seconds=interval_seconds(self._previous_success)
        try:
            super()._tick_once()
        finally:
            if not self.browser.running and not self.cooldown.remaining():
                self.cooldown.seconds=30
            self._update_explain()

    def _update_explain(self):
        if not hasattr(self,'queue_hint'):return
        try:
            current=self.preparacion.pending()
            if self.browser.rate_limited:
                msg='MICROSOFT 429 · Los accesos están pausados; no se intentarán otras cuentas.'
            elif current:
                msg='SOLICITUD IMSS RECIBIDA · Outlook preparará solo la cuenta asignada; sin reintentos de verificación.'
            elif self.browser.running and getattr(self.browser,'phase','')=='mail':
                msg='BANDEJA ABIERTA · Esperando el código solicitado por IMSS.'
            else:
                msg='SIN SOLICITUDES NUEVAS · Outlook espera a que IMSS reciba una CURP. No abrirá correos por su cuenta.'
            self.queue_hint.set(msg)
        except Exception:
            self.queue_hint.set('No se pudo consultar la cola; verifica que ambos bots utilicen la misma lista compartida.')

if __name__=='__main__':OutlookV22().mainloop()
