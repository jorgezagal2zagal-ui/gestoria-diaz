# -*- coding: utf-8 -*-
"""Gestoría Díaz Outlook V40: primer código IMSS y limpieza manual del catálogo."""
from __future__ import annotations
import os,sys,subprocess,tkinter as tk
from pathlib import Path
from tkinter import messagebox
if '--worker' in sys.argv:
    i=sys.argv.index('--worker');os.environ['GD_WORKER_SLOT']=sys.argv[i+1]
else:os.environ['GD_WORKER_SLOT']='1'
os.environ['GD_HEADLESS']='0'
from app_v38 import OutlookV38
from app_v36 import OutlookWorkerV36
from enlace import Client
from pool_v14 import PoolError
from administrar_correos_v39 import clear_available_list
from app import BG,BOX,GOLD,GRAY
import navegador_v28 as browser
from lector_reciente_v40 import scan_visible_inbox,compact_inbox_verified
browser.inbox_ui_verified=compact_inbox_verified
browser.scan_visible_inbox=scan_visible_inbox

class OutlookV40(OutlookV38):
    def start_worker(self,n):
        if n not in (2,3,4):return
        old=self.children.get(n)
        if old and old.poll() is None:return
        env=os.environ.copy()
        env.update(GD_WORKER_SLOT=str(n),GD_HEADLESS='0',GD_BG_WORKER='1')
        self.children[n]=subprocess.Popen(
            [sys.executable,str(Path(__file__).resolve()),'--worker',str(n)],
            env=env,cwd=str(Path(__file__).resolve().parent),close_fds=True)

    def __init__(self):
        super().__init__()
        self.title('GESTORÍA DÍAZ · OUTLOOK V40 · DIAGNÓSTICO DE ENTREGA + CÓDIGO ÚNICO')
        root=self.winfo_children()[0]
        panel=tk.Frame(root,bg=BOX,padx=12,pady=9)
        panel.pack(fill='x',padx=4,pady=4,before=root.winfo_children()[0])
        tk.Label(panel,text='CORREOS DE UN SOLO USO · PRIMER CÓDIGO IMSS DEL FOLIO',
                 bg=BOX,fg=GOLD,font=('Segoe UI',10,'bold')).pack(anchor='w')
        tk.Label(panel,text='La lista es compartida por IMSS y Outlook. Borrar aquí no elimina correos reales de Microsoft.',
                 bg=BOX,fg=GRAY,font=('Segoe UI',9)).pack(anchor='w')
        self.button(panel,'ELIMINAR CORREOS REGISTRADOS (MANUAL)',self.delete_all_registered_v39,True).pack(fill='x',pady=(6,0))
        self._diag('V40: lector de mensaje abierto y envío automático al enlace local')
        self.after(1000,self._offer_cleanup_v39)

    def _channels_busy_v39(self):
        # Cada enlace conserva su folio, incluso si Outlook aún no está abierto.
        active=[]
        for n in (1,2,3,4):
            try:
                st=Client(port=8796+n,timeout=.35).call('/v1/estado')
                if st.get('status') in ('ESPERANDO_CODIGO','CODIGO_DISPONIBLE',
                        'CODIGO_ENVIADO_AL_CELULAR'):
                    active.append(n)
            except Exception:
                # Una ventana Outlook todavía iniciando puede no tener el servidor
                # local levantado. El control transaccional del catálogo impide
                # borrar correos OCUPADO aunque un canal no conteste.
                continue
        return active

    def delete_all_registered_v39(self):
        try:
            num=self.shared_pool.counts()['EN_LISTA']
            if not num:
                messagebox.showinfo('Sin correos','No hay correos registrados en la lista local.',parent=self)
                return
            busy=self._channels_busy_v39()
            if busy:raise PoolError('Hay solicitudes abiertas en Android '+', '.join(map(str,busy))+'. Termina o cancela esos trámites antes de vaciar la lista.')
            if self.browser.running:
                raise PoolError('Cierra la sesión activa de Outlook antes de borrar los correos.')
            if not messagebox.askyesno('ELIMINAR CORREOS REGISTRADOS',
                f'¿Eliminar los {num} correos registrados de la lista LOCAL de Gestoría Díaz?\n\n'
                'Se borrarán también sus contraseñas individuales guardadas por el bot.\n'
                'NO se borrarán las cuentas ni mensajes de Microsoft.\n'
                'Esta acción no se puede deshacer.',parent=self):return
            removed=clear_available_list(self.shared_pool)
            vault=self._vault()
            errors=0
            for email in removed:
                try:vault.remove(email)
                except Exception:errors+=1
            if not self.shared_pool.entries():
                try:vault.clear_common_password()
                except Exception:errors+=1
            self.email.set('')
            self._update_counts()
            msg=f'Eliminados {len(removed)} correos de la lista compartida local.'
            if errors:msg+=f' Aviso: {errors} secretos no pudieron eliminarse; revisa CUENTAS.'
            self.info.set(msg)
            self._diag('ADMINISTRACIÓN V39: lista local vaciada; sin registrar correos ni contraseñas en diagnóstico')
            messagebox.showinfo('Lista vaciada',msg+'\nYa puedes importar un TXT nuevo.',parent=self)
        except (PoolError,Exception) as e:
            messagebox.showwarning('No se borró la lista',str(e)[:320],parent=self)

    def _offer_cleanup_v39(self):
        # Solo ofrecer si existe un catálogo anterior, sin borrado automático.
        try:
            from pathlib import Path
            marker=self.shared_pool.path.parent/'aviso_limpieza_v39.txt'
            if marker.exists():return
            count=self.shared_pool.counts()['EN_LISTA']
            if not count:return
            marker.write_text('mostrado',encoding='utf8')
            if messagebox.askyesno('Cambiar de lote',
                f'Se encontraron {count} correos registrados anteriormente.\n'
                '¿Quieres vaciarlos ahora para cargar los nuevos?\n'
                'Solamente se borrarán después de verificar que no hay trámites activos.',parent=self):
                self.delete_all_registered_v39()
        except Exception:pass

def main():
    if '--worker' in sys.argv:
        slot=int(sys.argv[sys.argv.index('--worker')+1]);
        if slot not in (2,3,4):raise ValueError('Canal inválido')
        app=OutlookWorkerV36();app.withdraw()
    else:app=OutlookV40()
    app.mainloop()
if __name__=='__main__':main()
