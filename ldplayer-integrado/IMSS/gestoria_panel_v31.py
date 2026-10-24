# -*- coding: utf-8 -*-
"""IMSS V31: solo tomar correos prevalidos, desechar tras codigo confirmado."""
import time,threading,uuid,tkinter as tk
from gestoria_panel_v30 import PanelV30
from gestoria_paso1_v8 import GOLD
from pool_v14 import VAULT_DB
from preflight_v42 import Preflight
from puente_imss_outlook_v14 import PuenteOutlook

class PuenteOutlookV31(PuenteOutlook):
    def confirmar_recepcion(self,folio):
        # Solo se llega aquí cuando IMSS cambió de pantalla después de escribir
        # el OTP: no descartar correo si solo fue LEÍDO o ENVIADO al enlace.
        response=super().confirmar_recepcion(folio)
        if response.get('ok') is not True:
            raise RuntimeError('El bot Outlook no reconoció la confirmación de IMSS')
        from pool_v14 import SharedPool
        try:
            email=SharedPool().consume(folio)
        except Exception:
            # Si SQLite está indisponible, OCUPADO sigue sin poder reservarse;
            # no declarar fallida una validación que IMSS sí realizó.
            email=None
        if email:
            try:
                from credenciales import Vault
                Vault(path=VAULT_DB).remove(email)
            except Exception:
                # Cuenta ya retirada de la lista. La clave deberá revisarse
                # localmente, no reactivar el correo.
                pass
        return response

class PanelV31(PanelV30):
    def __init__(self,root):
        self.preflight=Preflight()
        super().__init__(root)
        self.peers=[PuenteOutlookV31(p.cliente) for p in self.peers]
        root.title('GESTORÍA DÍAZ · IMSS V31 · 4 ANDROID · SOLO CORREOS LISTOS')
        tk.Label(root,text='IMSS V31 · OUTLOOK PRIMERO: bandeja verificada → Android · correo descartado tras código confirmado',
             bg='#111215',fg=GOLD,font=('Segoe UI',10,'bold')).pack(
             anchor='w',padx=20,before=self.add_btn.master)
        self.log('V31: no ocupa un Android mientras Microsoft sigue preparando correo.')
        self.log('V31: después de verificar que IMSS aceptó el código, correo USADO retirado localmente.')

    def probe_outlook_loop(self):
        # El navegador estará ABIERTO cuando esté preparado, así que ping.available
        # no debe bloquearlo. Consultar readiness real del mismo canal.
        while not self.monitor_stop.wait(1.3):
            available=[]
            for i,peer in enumerate(self.peers):
                try:
                    peer.comprobar()
                    ok=bool(self.preflight.ready_for(i+1)) and self.preparacion.live(i+1)
                except Exception:ok=False
                available.append(ok)
            self.peer_ok[:]=available
            self.send('outlook_state',f'OUTLOOK PREPARADO: {sum(available)}/4 bandejas verificadas · {len(self.active_jobs)}/4 en trámite')

    def dispatch(self):
        if self.working or not self.pending or not hasattr(self,'preparacion'):return
        for slot in range(4):
            if not self.pending:break
            if slot in self.active_jobs or not self.serials[slot] or self.states[slot]!='LIBRE':continue
            if not self.peer_ok[slot]:continue
            folio=uuid.uuid4().hex
            try:email=self.preflight.take_ready(slot+1,folio)
            except Exception:
                self.log(f'Android {slot+1}: no se pudo reservar bandeja preparada.');continue
            if not email:continue
            try:
                self.preparacion.create(folio,email,worker=slot+1)
                if not self.preparacion.set(folio,email,'LISTO'):
                    raise RuntimeError('No se pudo confirmar la preparación del folio')
            except Exception:
                try:self.pool.review(folio)
                except Exception:pass
                self.log(f'Android {slot+1}: fallo al asignar correo preparado; se apartó de uso.')
                continue
            reqid,curp,_unused=self.pending.popleft()
            self.folios[slot]=folio
            self.set_status(slot,'OCUPADO',f'Outlook {slot+1}: bandeja comprobada; comenzando IMSS')
            pin=self.pin_var.get() if self.use_pin.get() else ''
            override=self.allow_manual[slot];self.allow_manual[slot]=False
            stop=threading.Event()
            self.active_jobs[slot]={'folio':folio,'reqid':reqid}
            self.job_stops[slot]=stop
            self.peer_ok[slot]=False
            self.update_count();self.update_pool_label()
            self.log(f'Android {slot+1}: solicitud #{reqid} asignada después de verificar Outlook.')
            self.executor.submit(self.login_worker,slot,reqid,curp,email,override,pin,stop,folio)
        self.active_outlook=bool(self.active_jobs)

def main():
    root=tk.Tk();PanelV31(root);root.mainloop()
if __name__=='__main__':main()
