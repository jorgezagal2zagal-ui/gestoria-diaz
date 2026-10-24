# -*- coding: utf-8 -*-
"""Outlook V26: administración manual de la lista compartida con IMSS V22."""
from __future__ import annotations
import tkinter as tk
from tkinter import ttk, messagebox
from app_v25 import OutlookV25
from gestion_correos_v26 import AccountListEditor
from app import BG, BOX, GOLD, WHITE, GRAY


class OutlookV26(OutlookV25):
    def __init__(self):
        super().__init__()
        self.title('GESTORÍA DÍAZ · OUTLOOK V26 · ADMINISTRAR CUENTAS')
        self.geometry('880x850')
        self.list_editor = AccountListEditor(self.shared_pool)
        # La vista CUENTAS ya existe en el panel principal. Reutiliza el botón
        # y muestra controles para borrar, sin cambiar el enlace IMSS.
        self.info.set('En CUENTAS puedes borrar correos elegidos o vaciar la lista. Las cuentas ocupadas se protegen.')

    def _delete_accounts(self, selection, owner, update_ui):
        if self.browser.running:
            messagebox.showwarning('Navegador abierto',
                'Cierra primero la sesión activa de Outlook para modificar la lista.', parent=owner)
            return
        try:
            removed, busy = self.list_editor.remove(selection)
        except Exception as exc:
            messagebox.showerror('No se pudieron borrar', f'{type(exc).__name__}: {str(exc)[:180]}', parent=owner)
            return
        failures = []
        vault = None
        if removed:
            try:
                vault = self._vault()
            except Exception:
                failures = removed[:]
            if vault:
                for email in removed:
                    try: vault.remove(email)
                    except Exception: failures.append(email)
        if self.email.get().strip().lower() in removed:
            self.email.set('')
        update_ui()
        self._update_counts()
        result = f'Se borraron {len(removed)} correos de la lista compartida.'
        if busy:
            result += f' {len(busy)} ocupados no se borraron (trámite en curso).'
        if failures:
            result += f' No se pudieron quitar {len(failures)} claves individuales: revisar permisos.'
        self.info.set(result)
        messagebox.showinfo('Resultado del borrado',
            result + '\n\nLa lista de bloqueos históricos se conserva para evitar reutilizar cuentas restringidas.\n'
            'La contraseña común, si está configurada, se conserva en AJUSTES.', parent=owner)

    def manage_accounts(self):
        win = tk.Toplevel(self)
        win.title('GESTORÍA DÍAZ · Administrar cuentas · V26')
        win.geometry('850x610'); win.minsize(700,490); win.configure(bg=BG)
        self.label(win, 'LISTA COMPARTIDA DE CORREOS · OUTLOOK + IMSS', GOLD, 12, True).pack(anchor='w', padx=14, pady=(14,5))
        self.label(win, 'Selecciona con Ctrl o Mayús. Borrar aquí también los quita de la lista de IMSS.', GRAY, 9).pack(anchor='w',padx=14)
        self.label(win, 'Los correos OCUPADO no se borran durante un trámite. Los bloqueados siguen excluidos aunque vuelvas a importarlos.', GRAY, 9).pack(anchor='w',padx=14,pady=(1,7))
        frame=tk.Frame(win,bg=BG);frame.pack(fill='both',expand=True,padx=14,pady=(2,8))
        scrollbar=ttk.Scrollbar(frame,orient='vertical');scrollbar.pack(side='right',fill='y')
        style=ttk.Style(win)
        style.configure('GD26.Treeview',background=BOX,foreground=WHITE,fieldbackground=BOX,rowheight=26)
        style.map('GD26.Treeview',background=[('selected','#705C34')],foreground=[('selected',WHITE)])
        tree=ttk.Treeview(frame,columns=('email','estado'),show='headings',selectmode='extended',
            yscrollcommand=scrollbar.set,style='GD26.Treeview')
        tree.heading('email',text='CORREO');tree.heading('estado',text='ESTADO')
        tree.column('email',width=550,anchor='w');tree.column('estado',width=160,anchor='center')
        tree.pack(side='left',fill='both',expand=True);scrollbar.configure(command=tree.yview)
        counts=tk.StringVar()
        def refresh():
            selected={tree.set(iid,'email') for iid in tree.selection()}
            for iid in tree.get_children():tree.delete(iid)
            rows=self.shared_pool.entries()
            for i,row in enumerate(rows):
                tree.insert('','end',iid=str(i),values=(row['email'],row['estado']))
            for iid in tree.get_children():
                if tree.set(iid,'email') in selected:tree.selection_add(iid)
            counts.set(f'{len(rows)} correos en lista · Seleccionados: {len(tree.selection())}')
        tree.bind('<<TreeviewSelect>>', lambda _e: counts.set(f'{len(tree.get_children())} correos en lista · Seleccionados: {len(tree.selection())}'))
        def emails_selected():return [tree.set(iid,'email') for iid in tree.selection()]
        def remove_selected():
            selected=emails_selected()
            if not selected:
                messagebox.showinfo('Seleccionar correos','Marca los correos que deseas borrar.',parent=win);return
            if not messagebox.askyesno('Confirmar borrado',
                f'¿Quitar {len(selected)} correos seleccionados de la lista compartida?\n\n'
                'No se borrará ninguna cuenta OCUPADO.',parent=win):return
            self._delete_accounts(selected,win,refresh)
        def remove_all():
            num=len(self.shared_pool.entries())
            if not num:
                messagebox.showinfo('Lista vacía','No quedan correos en la lista.',parent=win);return
            if not messagebox.askyesno('Confirmar vaciado',
                f'¿Borrar TODOS los {num} correos de la lista compartida?\n\n'
                'Las cuentas OCUPADO se conservarán hasta que termine el trámite.\n'
                'La lista histórica de bloqueos NO se borrará.',parent=win):return
            self._delete_accounts(None,win,refresh)
        refresh()
        self.label(win,'La eliminación borra la contraseña individual guardada, pero no modifica la contraseña común.', GRAY, 9).pack(anchor='w',padx=14)
        self.label(win,'Seleccionar todos no borra nada: siempre aparece confirmación.', GRAY, 9).pack(anchor='w',padx=14,pady=(2,4))
        controls=tk.Frame(win,bg=BG);controls.pack(fill='x',padx=14,pady=(5,6))
        self.button(controls,'SELECCIONAR TODOS',lambda:tree.selection_set(tree.get_children())).pack(side='left',padx=(0,6))
        self.button(controls,'BORRAR SELECCIONADOS',remove_selected,True).pack(side='left',padx=(0,6))
        self.button(controls,'BORRAR TODA LA LISTA',remove_all).pack(side='left')
        controls2=tk.Frame(win,bg=BG);controls2.pack(fill='x',padx=14,pady=(0,12))
        self.button(controls2,'ACTUALIZAR',refresh).pack(side='left',padx=(0,8))
        self.button(controls2,'CERRAR',win.destroy).pack(side='left')
        tk.Label(controls2,textvariable=counts,bg=BG,fg=GOLD,font=('Segoe UI',10,'bold')).pack(side='right')

if __name__=='__main__':
    OutlookV26().mainloop()
