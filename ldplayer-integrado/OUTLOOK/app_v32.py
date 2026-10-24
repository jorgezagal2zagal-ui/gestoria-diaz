# -*- coding: utf-8 -*-
"""Outlook V32: 1 of 4 separate Windows Chrome + local OTP bridges."""
import os,time
from app_v31 import OutlookV31
from preparacion_v32 import PreparationV32
class OutlookV32(OutlookV31):
    def __init__(self):
        super().__init__()
        worker=int(os.environ.get('GD_WORKER_SLOT','1'))
        self.preparacion=PreparationV32(worker)
        self._terminal_since=None
        self.title(f'GESTORÍA DÍAZ · OUTLOOK V32 · SESIÓN {worker}/4 · PUERTO {8796+worker}')
        self.info.set(f'SESIÓN {worker}/4: solo consulta el correo asignado a este Android. Cancelar clave de paso opcional · Outlook en blanco: una recarga controlada.')
    def _tick_once(self):
        super()._tick_once()
        if not hasattr(self,'_terminal_since'):return
        try:
            status=self.state.status()['status']
            ready=status in ('SOLICITUD_IMSS_ENVIADA','CANCELADA','CADUCADA')
            if ready and self.browser.running and not self.preparacion.pending():
                if self._terminal_since is None:self._terminal_since=time.monotonic()
                if time.monotonic()-self._terminal_since>=5:
                    self.close_private()
                    self._terminal_since=None
                    self.info.set('Solicitud terminada: cerré únicamente la ventana privada para liberar esta sesión.')
            else:self._terminal_since=None
        except Exception:pass

if __name__=='__main__':OutlookV32().mainloop()
