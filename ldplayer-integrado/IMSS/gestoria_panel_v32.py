# -*- coding: utf-8 -*-
"""IMSS V32: Outlook V41 estable, 4 Android, reintento seguro por falta de avance."""
import time,uuid,threading,tkinter as tk
from collections import deque
from gestoria_panel_v30 import PanelV30
from puente_imss_outlook_v14 import tramitar_con_outlook
from gestoria_paso1_v8 import GOLD

MAX_ALTERNATIVAS=2
MAX_REINTENTOS_ANDROID=1

class PanelV32(PanelV30):
    def __init__(self,root):
        # CURP permanece sólo en RAM hasta terminar/cancelar la operación.
        self._queued_inputs={}
        self._retry_count={}
        self._code_submitted=set()
        super().__init__(root)
        root.title('GESTORÍA DÍAZ · IMSS V32 · V41 ESTABLE · 4 ANDROID RÁPIDOS')
        tk.Label(root,text='V32 · OUTLOOK PRIMERO · 4 ANDROID · AUTORECUPERACIÓN + 1 REINTENTO',
                 bg='#111215',fg=GOLD,font=('Segoe UI',10,'bold')).pack(
                 anchor='w',padx=20,before=self.add_btn.master)
        self.log('V32: Outlook confirma bandeja antes de iniciar IMSS; Android se recupera tras inactividad.')

    def send(self,*message):
        if message and message[0]=='status' and len(message)>=4:
            if message[2]=='OCUPADO' and any(term in str(message[3]).casefold() for term in
                    ('código nuevo recibido','código enviado','código introducido','código depositado')):
                job=self.active_jobs.get(message[1])
                if job:self._code_submitted.add(job['reqid'])
        return super().send(*message)

    def dispatch(self):
        for item in list(getattr(self,'pending',())):
            rid,curp,_=item
            self._queued_inputs.setdefault(rid,curp)
        return super().dispatch()

    def login_worker(self,slot,reqid,curp,email,override,pin,stop,folio):
        done=threading.Event()
        self._worker_done[slot]=done
        old_folio=folio
        try:
            chosen_email=email
            chosen_folio=folio
            for attempt in range(MAX_ALTERNATIVAS+1):
                stage=None
                deadline=time.monotonic()+150
                self.send('status',slot,'OCUPADO','Outlook verificando bandeja antes de iniciar IMSS')
                while time.monotonic()<deadline and not stop.is_set():
                    try:
                        info=self.preparacion.status(chosen_folio)
                        stage=info['estado'] if info else 'REVISAR'
                    except Exception:stage='REVISAR'
                    if stage in ('LISTO','BLOQUEADA','REVISAR','LIMITE_MICROSOFT','METODO_NO_DISPONIBLE'):
                        break
                    stop.wait(.65)
                if stop.is_set():
                    self.send('bridge_result',slot,reqid,'REVISAR','Preparación cancelada por recuperación del Android.',chosen_folio,False)
                    return
                if stage=='LISTO':
                    self.send('status',slot,'OCUPADO','Bandeja confirmada; rellenando CURP y correo')
                    status,desc,linked,finished=tramitar_con_outlook(
                        self.adb,self.serials[slot],curp,chosen_email,pin,override,
                        update=lambda msg:self.send('status',slot,'OCUPADO',msg),
                        stop=stop,puente=self.peers[slot],folio_id=chosen_folio)
                    self.send('bridge_result',slot,reqid,status,desc,linked,finished)
                    return
                # CORREO IMPEDIDO: nunca reusar ni modificar mecanismos de seguridad.
                try:self.pool.review(chosen_folio)
                except Exception:pass
                try:self.preparacion.finish(chosen_folio)
                except Exception:pass
                if stage=='LIMITE_MICROSOFT':
                    self.send('bridge_result',slot,reqid,'REVISAR','Microsoft rechazó accesos (429); sin rotación automática.',chosen_folio,False)
                    return
                if stage not in ('BLOQUEADA','METODO_NO_DISPONIBLE') or attempt>=MAX_ALTERNATIVAS:
                    self.send('bridge_result',slot,reqid,'REVISAR','Outlook no confirmó una cuenta utilizable.',chosen_folio,False)
                    return
                new_folio=uuid.uuid4().hex
                try:new_email=self.pool.reserve(new_folio)
                except Exception:new_email=None
                if not new_email:
                    self.send('bridge_result',slot,reqid,'REVISAR','No quedan correos disponibles.',chosen_folio,False)
                    return
                try:self.preparacion.create(new_folio,new_email,worker=slot+1)
                except Exception:
                    try:self.pool.review(new_folio)
                    except Exception:pass
                    self.send('bridge_result',slot,reqid,'REVISAR','No se pudo registrar una nueva sesión Outlook.',chosen_folio,False)
                    return
                # Enlace aún no iniciado en IMSS; solamente sustituir la reserva local.
                self.folios[slot]=new_folio
                if slot in self.active_jobs:self.active_jobs[slot]['folio']=new_folio
                chosen_email,chosen_folio=new_email,new_folio
                self.send('status',slot,'OCUPADO','Correo que exige recuperación apartado; probando siguiente correo autorizado')
            self.send('bridge_result',slot,reqid,'REVISAR','No se confirmó bandeja Outlook.',chosen_folio,False)
        except Exception as exc:
            self.send('bridge_result',slot,reqid,'REVISAR',
                'IMSS / Outlook: excepción '+type(exc).__name__+'.',self.folios[slot],False)
        finally:
            done.set()
            del pin

    def _finish_recovery(self,slot,record,ok,detail):
        # Mantener el mecanismo probado de cancelación y verificación del inicio.
        folio=record['folio']
        reqid=record['reqid']
        previous=self.folios[slot]
        super()._finish_recovery(slot,record,ok,detail)
        if not ok or previous!=folio:return
        curp=self._queued_inputs.get(reqid)
        used=self._retry_count.get(reqid,0)
        if curp and used<MAX_REINTENTOS_ANDROID and reqid not in self._code_submitted:
            self._retry_count[reqid]=used+1
            self.pending.appendleft((reqid,curp,None))
            self.log('Solicitud #'+str(reqid)+': Android recuperado; reintento único con correo NUEVO.')
        else:
            self._queued_inputs.pop(reqid,None)
            self._retry_count.pop(reqid,None)
            self._code_submitted.discard(reqid)
            self.log('Solicitud #'+str(reqid)+': sin más reintentos; se liberó Android, revisar trámite.')
        self.update_count()

def main():
    root=tk.Tk();PanelV32(root);root.mainloop()
if __name__=='__main__':main()
