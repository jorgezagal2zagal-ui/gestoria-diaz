# -*- coding: utf-8 -*-
"""Outlook V20: salida automática de acceso no admitido, sin evadir MFA ni 429."""
import tkinter as tk
from tkinter import ttk
import app as baseapp
import navegador_v20 as navegador
from lector_reciente_v14 import scan_visible_inbox
from app_v19 import OutlookV19
from metodos_v20 import MethodRegistry
from preparacion_v20 import PreparationV20
navegador.scan_visible_inbox=scan_visible_inbox
baseapp.BrowserLogin=navegador.BrowserLogin

class OutlookV20(OutlookV19):
    def __init__(self):
        self.method_registry=MethodRegistry()
        super().__init__()
        self.preparacion=PreparationV20()
        self.title('GESTORÍA DÍAZ · OUTLOOK V20 · REVISIÓN AUTOMÁTICA')
        self.geometry('820x760')
        main=self.winfo_children()[0]
        self.button(main,'VER CUENTAS QUE REQUIEREN OTRO MÉTODO',self.show_method_accounts).pack(fill='x',pady=5)
        self.method_label=tk.StringVar(value='')
        tk.Label(main,textvariable=self.method_label,bg='#101419',fg='#E8BB62').pack(anchor='w')
        self._update_counts()

    def show_method_accounts(self):
        popup=tk.Toplevel(self); popup.title('Acceso con contraseña no disponible')
        popup.geometry('780x430')
        tk.Label(popup,text='Cuentas apartadas: Microsoft requiere un método distinto. No equivale a bloqueo de cuenta.').pack(anchor='w',padx=10,pady=10)
        table=ttk.Treeview(popup,columns=('email','fecha','motivo'),show='headings')
        for name,width in [('email',290),('fecha',170),('motivo',290)]:
            table.heading(name,text=name.title());table.column(name,width=width)
        table.pack(fill='both',expand=True,padx=10,pady=8)
        for row in self.method_registry.entries():
            table.insert('','end',values=(row['email'],row['fecha'],row['motivo']))

    def _update_counts(self):
        super()._update_counts()
        if hasattr(self,'method_label'):
            try:self.method_label.set('OTRO MÉTODO: '+str(self.method_registry.count())+' · apartadas de disponibles')
            except Exception:self.method_label.set('No fue posible consultar las cuentas pendientes')

    def _tick_once(self):
        if getattr(self.browser,'rate_limited',False):
            folio=getattr(self,'prep_id',None)
            email=getattr(self,'prep_email',None)
            if folio and email:
                self.preparacion.set(folio,email,'LIMITE_MICROSOFT')
            self.info.set('429 de Microsoft: todas las cuentas en pausa. No se intentará otra cuenta.')
        if (getattr(self.browser,'password_unavailable',False) and
            not self.browser.rate_limited):
            folio=getattr(self,'prep_id',None)
            email=getattr(self,'prep_email',None)
            if folio and email:
                # Primero establecer estado, inmediatamente apartar cuenta.
                if self.preparacion.set(folio,email,'METODO_NO_DISPONIBLE'):
                    self.method_registry.mark(email,folio)
                    self.info.set('Cuenta apartada automáticamente: Microsoft requiere otro método. No se intentará desbloquear.')
                    self.recovery_info.set('La coordinación decidirá si hay una alternativa autorizada. Sin reintentar esta cuenta.')
            self.browser.password_unavailable=False
            if self.browser.running:self.close_private()
        super()._tick_once()

if __name__=='__main__':OutlookV20().mainloop()
