# -*- coding: utf-8 -*-
"""V24: explicación del enfriamiento; conserva V23 y límites de Microsoft."""
import tkinter as tk
from app_v23 import OutlookV23


def explanation(rate_limited, remaining, success, running):
    if rate_limited:
        return 'MICROSOFT 429: accesos suspendidos. No se abrirán otras cuentas.'
    if remaining:
        return ('Pausa por BANDEJA CONFIRMADA: ' if success else
                'Pausa tras ACCESO NO CONFIRMADO: ')+f'{remaining} s restantes.'
    if running:
        return 'Sesión abierta: no se inicia otra cuenta mientras esté activa.'
    return 'Listo. Próxima sesión solo cuando IMSS tenga una solicitud autorizada.'

class OutlookV24(OutlookV23):
    def __init__(self):
        super().__init__()
        self.title('GESTORÍA DÍAZ · OUTLOOK V24 · PAUSA CLARA')
        main=self.winfo_children()[0]
        self.pause_reason=tk.StringVar(value='10 s tras éxito / 30 s tras acceso rechazado.')
        tk.Label(main,textvariable=self.pause_reason,bg='#101419',fg='#E8BB62',
                 wraplength=730,justify='left',font=('Segoe UI',10,'bold')).pack(anchor='w',pady=5)

    def _tick_once(self):
        super()._tick_once()
        if hasattr(self,'pause_reason'):
            self.pause_reason.set(explanation(
                bool(self.browser.rate_limited),
                int(self.cooldown.remaining()),
                bool(getattr(self,'_previous_success',False)),
                bool(self.browser.running)))

if __name__=='__main__':
    OutlookV24().mainloop()
