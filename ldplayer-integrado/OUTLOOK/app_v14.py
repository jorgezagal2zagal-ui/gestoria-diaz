# -*- coding: utf-8 -*-
"""Outlook V14. Usa la misma lista compartida que IMSS V14, no el DB V15."""
from __future__ import annotations
import tkinter as tk
from tkinter import messagebox, filedialog, ttk
import app as previous
# SOLO lector de correo IMSS: conexión y automatización originales intactas.
import navegador as _lector_base
from lector_reciente_v14 import scan_visible_inbox as _leer_reciente_imss
_lector_base.scan_visible_inbox = _leer_reciente_imss
from credenciales import Vault, decode_file
from pool_v14 import SharedPool, SharedQueueAdapter, VAULT_DB

class ScopedVault(Vault):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault('path', VAULT_DB)
        super().__init__(*args,**kwargs)

# La app base resuelve estas dos clases al ejecutar __init__. Los ficheros
# originales app.py, navegador.py y enlace.py no se modifican.
previous.Vault = ScopedVault
previous.QueueStore = SharedQueueAdapter

class OutlookV14(previous.App):
    def __init__(self):
        self.shared_pool=SharedPool()
        super().__init__()
        self.title('GESTORÍA DÍAZ · OUTLOOK V14 · LISTA COMPARTIDA')
        self.email.set('') # Nunca leer el correo seleccionado de versiones anteriores.
        self._auto_start_attempted=True
        self._update_counts()
        self.info.set('V14: lista NUEVA compartida. Importa correo | contraseña. IMSS elegirá automáticamente.')

    def _reservation_available(self):
        # No iniciar una cuenta nueva mientras otra ventana privada esté abierta,
        # incluso si Outlook ya entregó el código pero falta el PDF.
        return not self.browser.running and super()._reservation_available()

    def _can_begin(self,email):
        # Sólo aceptar solicitudes enviadas por IMSS que hayan reservado este correo.
        return self.shared_pool.has_occupied_email(email) and super()._can_begin(email)

    def _reserve_email(self):
        # Respaldo: no asignar espontáneamente una cuenta a un folio cualquiera.
        return None

    def _maybe_auto_start(self, state):
        # Jamás iniciar Outlook sin una solicitud IMSS del mismo correo.
        if state.get('status') == 'ESPERANDO_CODIGO':
            self._maybe_start_request_account(state)

    def import_txt(self):
        path=filedialog.askopenfilename(title='TXT NUEVO de correos y claves',filetypes=[('TXT','*.txt')])
        if not path:return
        try:
            accounts=decode_file(path)
            if not accounts or any(not p for _,p in accounts):
                raise ValueError('Cada renglón requiere correo y contraseña; ejemplo: correo@outlook.com | Clave123')
            if not messagebox.askyesno('REEMPLAZAR lista compartida',
                  f'Se encontraron {len(accounts)} cuentas. Esta acción REEMPLAZA la lista nueva V14 '
                  'y reinicia los contadores, sin modificar archivos de versiones anteriores.\n\n'
                  'Las contraseñas se cifrarán con DPAPI. El TXT original permanece en tu PC. ¿Continuar?'):
                return
            # Primero validar que la lista puede sustituirse sin trabajos activos.
            c=self.shared_pool.counts()
            if c['OCUPADO'] or c['REVISAR']:
                raise ValueError('Hay cuentas ocupadas o en revisión. No se puede reemplazar la lista.')
            self._vault().save(accounts)
            self.shared_pool.replace_fresh([email for email,_pw in accounts])
            # No conservar claves de correos que ya no pertenecen a la lista nueva.
            with self._vault()._db() as db:
                existing={e for e,_ in accounts}
                for (email,) in db.execute('SELECT email FROM credenciales').fetchall():
                    if email not in existing: db.execute('DELETE FROM credenciales WHERE email=?',(email,))
            self.email.set('')
            self._auto_start_attempted=True
            self._update_counts()
            self.info.set(f'Lista V14 nueva: {len(accounts)} disponibles. Ambos bots ya comparten estados.')
        except Exception as exc:
            messagebox.showerror('TXT compartido','No se importó la lista: '+str(exc)[:180])

    def _update_counts(self):
        try:
            c=self.shared_pool.counts()
            self.accounts_label.set('COMPARTIDA · Disponibles: {DISPONIBLE} · Ocupados: {OCUPADO} · Revisar: {REVISAR} · Eliminados: {ELIMINADOS}'.format(**c))
            picker=getattr(self,'account_picker',None)
            if picker is not None:
                picker.configure(values=[r['email'] for r in self.shared_pool.entries()])
        except Exception:
            self.accounts_label.set('Lista compartida: error de lectura')

    def _tick_once(self):
        super()._tick_once()
        # IMSS ya confirmó el PDF, eliminó el correo usado y regresó al inicio:
        # cerrar únicamente ENTONCES la sesión privada para preparar la siguiente.
        if self.active_email and not any(r['email']==self.active_email for r in self.shared_pool.entries()):
            if self.browser.running:
                self.close_private()  # conserva cooldown 30 s y respeta limitación Microsoft
            self.active_email=None
            self.active_email_label.set('Cuenta utilizada eliminada de lista compartida')
            self.email.set('')
            self._auto_started_request=None
        self._update_counts()

    def manage_accounts(self):
        panel=tk.Toplevel(self);panel.title('Lista compartida V14 — solo lectura')
        panel.geometry('680x450')
        frm=ttk.Frame(panel,padding=12);frm.pack(fill='both',expand=True)
        tk.Label(frm,text='La lista se asigna automáticamente desde IMSS. Los usados desaparecen.',font=('Segoe UI',10)).pack(anchor='w')
        tree=ttk.Treeview(frm,columns=('email','estado'),show='headings')
        tree.heading('email',text='Correo');tree.heading('estado',text='Estado')
        tree.column('email',width=450);tree.column('estado',width=150)
        tree.pack(fill='both',expand=True,pady=8)
        for r in self.shared_pool.entries():tree.insert('','end',values=(r['email'],r['estado']))

if __name__=='__main__': OutlookV14().mainloop()
