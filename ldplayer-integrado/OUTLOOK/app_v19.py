# -*- coding: utf-8 -*-
"""V19: detectar bloqueos explícitos, apartar cuentas, no evadir límites Microsoft."""
import tkinter as tk
from tkinter import ttk
import app as baseapp
import navegador_v19 as navegador
from lector_reciente_v14 import scan_visible_inbox
from app_v18 import OutlookV18
from bloqueadas_v19 import BlockedRegistry
navegador.scan_visible_inbox=scan_visible_inbox
baseapp.BrowserLogin=navegador.BrowserLogin

class OutlookV19(OutlookV18):
    def __init__(self):
        self.blocked_registry=BlockedRegistry()
        super().__init__()
        self.title('GESTORÍA DÍAZ · OUTLOOK V19 · CORREOS BLOQUEADOS')
        main=self.winfo_children()[0]
        self.button(main,'VER CORREOS BLOQUEADOS',self.show_blocked).pack(fill='x',pady=(5,5))
        self.blocked_status=tk.StringVar(value='Bloqueados: 0')
        tk.Label(main,textvariable=self.blocked_status,bg='#101419',fg='#E8BB62').pack(anchor='w')
        self._update_counts()

    def show_blocked(self):
        popup=tk.Toplevel(self);popup.title('Correos bloqueados por Microsoft (solo lectura)')
        popup.geometry('780x430')
        tk.Label(popup,text='Cuentas retiradas de las disponibles. Su recuperación requiere acciones oficiales del titular.').pack(anchor='w',padx=10,pady=10)
        table=ttk.Treeview(popup,columns=('email','fecha','motivo'),show='headings')
        for name,width in [('email',280),('fecha',170),('motivo',290)]:
            table.heading(name,text=name.title());table.column(name,width=width)
        table.pack(fill='both',expand=True,padx=10,pady=8)
        for r in self.blocked_registry.entries():
            table.insert('','end',values=(r['email'],r['fecha'],r['motivo']))

    def _update_counts(self):
        super()._update_counts()
        if hasattr(self,'blocked_status'):
            try:
                n=self.blocked_registry.count()
                self.blocked_status.set(f'CORREOS BLOQUEADOS: {n} · fuera de disponibles · sin reintentos')
            except Exception:self.blocked_status.set('No fue posible consultar bloqueos')

    def _tick_once(self):
        prev_folio=getattr(self,'prep_id',None)
        prev_email=getattr(self,'prep_email',None)
        super()._tick_once()
        # V15 marks BLOQUEADA after BrowserLogin sees the official warning.
        # IMSS V17 already handles this state and checks the next authorized
        # account in its bounded queue. A shared HTTP 429 pauses ALL accounts.
        if prev_folio and prev_email and not self.browser.rate_limited:
            cur=self.preparacion.status(prev_folio)
            if cur and cur['estado']=='BLOQUEADA':
                if self.blocked_registry.mark(prev_email,prev_folio):
                    self.info.set('Cuenta bloqueada apartada. IMSS decidirá la siguiente cuenta autorizada según su cola.')
                    self.recovery_info.set('Esta cuenta queda en Correos bloqueados. No se intentará entrar en ella.')
        self._update_counts()

if __name__=='__main__':OutlookV19().mainloop()
