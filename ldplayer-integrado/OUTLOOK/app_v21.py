# -*- coding: utf-8 -*-
"""V21: apartar MFA adicional y copiar correos sin credenciales."""
import tkinter as tk
from tkinter import ttk, messagebox
import app as baseapp
import navegador_v21 as navegador
from lector_reciente_v14 import scan_visible_inbox
from app_v20 import OutlookV20
from bloqueadas_v21 import BlockedRegistryV21
navegador.scan_visible_inbox=scan_visible_inbox
baseapp.BrowserLogin=navegador.BrowserLogin

class OutlookV21(OutlookV20):
    def __init__(self):
        super().__init__()
        self.blocked_registry=BlockedRegistryV21()
        self.title('GESTORÍA DÍAZ · OUTLOOK V21 · APARTADOS Y COPIAR')
        self.geometry('860x800')
        main=self.winfo_children()[0]
        self.button(main,'COPIAR CORREOS BLOQUEADOS / VERIFICACIÓN',self.copy_blocked).pack(fill='x',pady=(4,5))
        self._update_counts()

    def copy_blocked(self):
        rows=self.blocked_registry.entries()
        emails=list(dict.fromkeys(r['email'] for r in rows))
        if not emails:
            self.info.set('No hay correos apartados para copiar.')
            return
        self.clipboard_clear()
        self.clipboard_append('\n'.join(emails))
        self.update_idletasks()
        self.info.set(f'{len(emails)} correos apartados copiados; sin contraseñas.')

    def _tick_once(self):
        # Procesar ANTES del resto de la cadena para preservar el folio activo.
        browser=getattr(self,'browser',None)
        if browser and getattr(browser,'extra_verification',False) and not browser.rate_limited:
            folio=getattr(self,'prep_id',None)
            email=getattr(self,'prep_email',None)
            if folio and email:
                if self.preparacion.set(folio,email,'BLOQUEADA'):
                    # 'Bloqueados' = no utilizar por este bot. NO declarar
                    # que Microsoft bloqueó la cuenta si sólo pide otro factor.
                    self.blocked_registry.mark(email,folio,
                        'Requiere verificación adicional del titular (Microsoft)')
                    self.info.set('Cuenta apartada: Microsoft exige verificación adicional; no se reutilizará.')
                    self.recovery_info.set('Se pidió otro factor de identidad. No se intenta automatizarlo.')
            browser.extra_verification=False
            if browser.running:self.close_private()
        super()._tick_once()

    def show_blocked(self):
        popup=tk.Toplevel(self)
        popup.title('Correos apartados del uso automático')
        popup.geometry('860x490')
        tk.Label(popup,text='Bloqueo real o verificación adicional. Se excluyen del bot; no implica que Microsoft los haya bloqueado.',
                 wraplength=820,justify='left').pack(anchor='w',padx=10,pady=10)
        table=ttk.Treeview(popup,columns=('email','fecha','motivo'),show='headings')
        for name,width in [('email',300),('fecha',170),('motivo',345)]:
            table.heading(name,text=name.title());table.column(name,width=width)
        table.pack(fill='both',expand=True,padx=10,pady=8)
        for row in self.blocked_registry.entries():
            table.insert('','end',values=(row['email'],row['fecha'],row['motivo']))
        self.button(popup,'COPIAR LISTA DE CORREOS',self.copy_blocked).pack(fill='x',padx=10,pady=(0,12))

if __name__=='__main__':OutlookV21().mainloop()
