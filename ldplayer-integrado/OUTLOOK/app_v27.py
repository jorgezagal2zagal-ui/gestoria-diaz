# -*- coding: utf-8 -*-
"""Outlook V27: borrar cuentas atascadas y agregar TXT sin reemplazo destructivo.
No modifica la lógica de la bandeja ni los límites de Microsoft.
"""
from __future__ import annotations
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
from app_v26 import OutlookV26
from gestion_correos_v27 import AccountListEditorV27
from credenciales import decode_file
from app import BG, BOX, GOLD, WHITE, GRAY

class OutlookV27(OutlookV26):
    def __init__(self):
        super().__init__()
        self.title('GESTORÍA DÍAZ · OUTLOOK V27 · LISTA CORREGIDA')
        self.list_editor = AccountListEditorV27(self.shared_pool)
        self.info.set('V27: importar AGREGA correos, sin borrar reservas. CUENTAS permite limpieza de reservas antiguas confirmada.')

    def import_txt(self):
        """Agregar solo correos NUEVOS sin bloquear por reservas viejas.
        Una cuenta ya incluida o apartada nunca recibe otra contraseña mediante importación.
        """
        path=filedialog.askopenfilename(title='Importar TXT de correos verificados',filetypes=[('TXT','*.txt')])
        if not path:return
        try:
            accounts=decode_file(path)
            if not accounts or any(not pwd for _,pwd in accounts):
                raise ValueError('Cada línea debe contener correo | contraseña.')
            old={r['email'] for r in self.shared_pool.entries()}
            excluded=set()
            try:
                excluded.update(r['email'] for r in self.blocked_registry.entries())
            except AttributeError:
                pass
            try:
                excluded.update(r['email'] for r in self.method_registry.entries())
            except AttributeError:
                pass
            new=[(email,password) for email,password in accounts if email not in old and email not in excluded]
            if not messagebox.askyesno('AGREGAR CORREOS NUEVOS',
                f'El archivo tiene {len(accounts)} correos. Se pueden AGREGAR {len(new)} nuevos.\n\n'
                f'Se omiten {len(accounts)-len(new)} repetidos o apartados.\n'
                'NO se borrarán las cuentas anteriores, ni las reservas, ni el historial de bloqueos.\n\n'
                '¿Agregar solamente los nuevos?',parent=self):return
            if not new:
                self.info.set('No se encontraron correos nuevos elegibles en el TXT.');return
            # Guardar primero la credencial cifrada: no dejar una dirección sin contraseña.
            self._vault().save(new)
            n=self.shared_pool.add([e for e,_ in new])
            self._update_counts()
            self.info.set(f'Se agregaron {n} correos nuevos. {len(accounts)-len(new)} omitidos. No se reemplazó la lista anterior.')
            messagebox.showinfo('Importación lista',f'Se agregaron {n} correos nuevos. La lista y los apartados anteriores se conservaron.',parent=self)
        except Exception as exc:
            messagebox.showerror('Error importando TXT',f'{type(exc).__name__}: {str(exc)[:180]}',parent=self)

    def _delete_accounts(self, selection, owner, update_ui):
        if self.browser.running:
            messagebox.showwarning('Sesión activa','Detén Outlook y cierra su navegador antes de borrar cuentas.',parent=owner)
            return
        try:
            rows={r['email']:r for r in self.shared_pool.entries()}
            scope=list(rows) if selection is None else [str(e).strip().lower() for e in selection]
            occupied=[e for e in scope if e in rows and rows[e]['estado']=='OCUPADO']
            if occupied:
                messagebox.showwarning('Hay reservas antiguas',
                    f'Hay {len(occupied)} correo(s) OCUPADO entre los elegidos.\n\n'
                    'Antes de quitarlos: cierra IMSS Digital V22 y comprueba que ningún trámite esté activo.\n'
                    'Si borras reservas activas, podrías interrumpirlas.\n\n'
                    'Continuar requerirá escribir una confirmación.',parent=owner)
                confirm=simpledialog.askstring('Confirmar limpieza de reservas',
                    'Confirma que cerraste el panel IMSS y cancelaste sus trámites.\n'
                    'Escribe LIMPIAR para borrar también las cuentas OCUPADO:',parent=owner)
                if confirm!='LIMPIAR':
                    self.info.set('Borrado cancelado: se conservaron las reservas ocupadas.');return
                removed,folios,backup=self.list_editor.remove_with_stale_reservations(selection)
                # Si hay un enlace pendiente de uno de los folios, cancelarlo ahora.
                try:
                    current=self.state.status()
                    if current.get('request_id') in folios:
                        self.state.cancel(current['request_id'])
                except Exception: pass
                extra=f' Reservas anteriores liberadas: {len(folios)}. Respaldo local: {backup}'
            else:
                removed,not_removed=self.list_editor.remove(selection)
                extra=''
        except Exception as exc:
            messagebox.showerror('Error al borrar',f'{type(exc).__name__}: {str(exc)[:200]}',parent=owner)
            return
        failures=[]
        if removed:
            try:
                vault=self._vault()
                for email in removed:
                    try:vault.remove(email)
                    except Exception:failures.append(email)
            except Exception: failures=removed[:]
        if self.email.get().strip().lower() in removed:self.email.set('')
        update_ui();self._update_counts()
        text=f'Se borraron {len(removed)} correos de la lista compartida.'+extra
        if failures:text+=f' No se pudieron eliminar {len(failures)} contraseñas individuales.'
        self.info.set(text)
        messagebox.showinfo('Resultado',text+'\n\nLa lista de bloqueos sigue protegida, para no volver a utilizar esas cuentas.',parent=owner)

    def manage_accounts(self):
        win=tk.Toplevel(self)
        win.title('GESTORÍA DÍAZ · CORREOS · V27')
        win.geometry('900x650');win.minsize(720,500);win.configure(bg=BG)
        self.label(win,'ADMINISTRAR CORREOS · LISTA COMPARTIDA IMSS / OUTLOOK',GOLD,12,True).pack(anchor='w',padx=14,pady=(14,6))
        self.label(win,'Puedes eliminar cualquiera. Para OCUPADO debes cerrar IMSS y confirmar LIMPIAR.',GRAY,9).pack(anchor='w',padx=14)
        self.label(win,'El historial de cuentas bloqueadas sigue separado y protegido.',GRAY,9).pack(anchor='w',padx=14,pady=(0,8))
        frame=tk.Frame(win,bg=BG);frame.pack(fill='both',expand=True,padx=14,pady=8)
        scrollbar=ttk.Scrollbar(frame,orient='vertical');scrollbar.pack(side='right',fill='y')
        style=ttk.Style(win)
        style.configure('GD27.Treeview',background=BOX,foreground=WHITE,fieldbackground=BOX,rowheight=26)
        style.map('GD27.Treeview',background=[('selected','#705C34')],foreground=[('selected',WHITE)])
        tree=ttk.Treeview(frame,columns=('email','estado'),show='headings',selectmode='extended',yscrollcommand=scrollbar.set,style='GD27.Treeview')
        tree.heading('email',text='CORREO');tree.heading('estado',text='ESTADO')
        tree.column('email',width=570);tree.column('estado',width=160,anchor='center')
        tree.pack(side='left',fill='both',expand=True);scrollbar.configure(command=tree.yview)
        counts=tk.StringVar()
        def refresh():
            selected={tree.set(i,'email') for i in tree.selection()}
            for i in tree.get_children():tree.delete(i)
            rows=self.shared_pool.entries()
            for i,row in enumerate(rows):tree.insert('','end',iid=str(i),values=(row['email'],row['estado']))
            for i in tree.get_children():
                if tree.set(i,'email') in selected:tree.selection_add(i)
            counts.set(f'{len(rows)} correos · Marcados: {len(tree.selection())}')
        tree.bind('<<TreeviewSelect>>',lambda _e:counts.set(f'{len(tree.get_children())} correos · Marcados: {len(tree.selection())}'))
        def selected():return [tree.set(i,'email') for i in tree.selection()]
        def delete_selected():
            emails=selected()
            if not emails:
                messagebox.showinfo('Seleccionar','Selecciona primero al menos un correo.',parent=win);return
            if messagebox.askyesno('Borrar seleccionados',f'¿Eliminar {len(emails)} correo(s) seleccionados?',parent=win):
                self._delete_accounts(emails,win,refresh)
        def delete_all():
            num=len(self.shared_pool.entries())
            if num==0:
                messagebox.showinfo('Lista vacía','No queda ningún correo en la lista compartida.',parent=win);return
            if messagebox.askyesno('Vaciar lista',f'¿Eliminar los {num} correos de la lista?\n\nSi hay OCUPADOS, deberás cerrar IMSS y confirmar la limpieza.',parent=win):
                self._delete_accounts(None,win,refresh)
        refresh()
        controls=tk.Frame(win,bg=BG);controls.pack(fill='x',padx=14,pady=(4,6))
        self.button(controls,'SELECCIONAR TODOS',lambda:tree.selection_set(tree.get_children())).pack(side='left',padx=(0,6))
        self.button(controls,'BORRAR SELECCIONADOS',delete_selected,True).pack(side='left',padx=(0,6))
        self.button(controls,'BORRAR TODA LA LISTA',delete_all).pack(side='left')
        controls2=tk.Frame(win,bg=BG);controls2.pack(fill='x',padx=14,pady=(0,12))
        self.button(controls2,'ACTUALIZAR',refresh).pack(side='left',padx=(0,8))
        self.button(controls2,'CERRAR',win.destroy).pack(side='left')
        tk.Label(controls2,textvariable=counts,bg=BG,fg=GOLD,font=('Segoe UI',10,'bold')).pack(side='right')

if __name__=='__main__':OutlookV27().mainloop()
