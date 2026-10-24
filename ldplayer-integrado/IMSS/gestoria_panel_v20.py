# -*- coding: utf-8 -*-
"""IMSS V20: coordinación de cuentas no utilizables, motor V7 sin cambios."""
import threading,time,uuid,tkinter as tk
from gestoria_panel_v17 import PanelV17
from preparacion_v20 import PreparationV20
from puente_imss_outlook_v14 import tramitar_con_outlook
MAX_CUENTAS_POR_SOLICITUD=3
class PanelV20(PanelV17):
    def __init__(self,root):
        super().__init__(root)
        self.preparacion=PreparationV20()
        root.title('GESTORÍA DÍAZ · IMSS V20 · OUTLOOK AUTOMÁTICO')
        self.log('V20: no se reintentan cuentas rechazadas. Si Microsoft exige otro método, se apartan; 429 detiene los accesos.')
    def login_worker(self,slot,reqid,curp,email,override,pin,stop,folio):
        chosen_email=email;chosen_folio=folio
        try:
            for attempt in range(MAX_CUENTAS_POR_SOLICITUD):
                deadline=time.monotonic()+190
                stage=None
                while time.monotonic()<deadline and not stop.is_set():
                    info=self.preparacion.status(chosen_folio)
                    stage=info['estado'] if info else 'REVISAR'
                    if stage in ('LISTO','BLOQUEADA','REVISAR','LIMITE_MICROSOFT','METODO_NO_DISPONIBLE'):break
                    stop.wait(1.25)
                if stop.is_set():break
                if stage=='LISTO':
                    self.send('status',slot,'OCUPADO','Bandeja Outlook comprobada; iniciando IMSS Digital')
                    estado,detalle,fol,fin=tramitar_con_outlook(
                        self.adb,self.serials[slot],curp,chosen_email,pin,override,
                        update=lambda msg:self.send('status',slot,'OCUPADO',msg),
                        stop=stop,puente=self.puente,folio_id=chosen_folio)
                    self.send('bridge_result',slot,reqid,estado,detalle,fol,fin)
                    return
                if stage=='LIMITE_MICROSOFT':
                    self.pool.review(chosen_folio)
                    self.folios[slot]=None
                    self.send('bridge_result',slot,reqid,'REVISAR',
                       'Microsoft limitó solicitudes: detenido sin cambiar de cuenta.',None,True)
                    return
                # Cuenta bloqueada/inaccesible: dejarla en REVISAR. Ningún intento
                # adicional contra ella ni método para eludir MFA/429.
                self.pool.review(chosen_folio)
                self.preparacion.finish(chosen_folio)
                if stage not in ('BLOQUEADA','METODO_NO_DISPONIBLE'):
                    self.folios[slot]=None
                    self.send('bridge_result',slot,reqid,'REVISAR',
                         'No se confirmó bandeja Outlook; requiere revisión manual.',None,True)
                    return
                # Máximo UNA cuenta alternativa si Microsoft rechazó el método
                # de contraseña. No se atraviesan decenas de cuentas para evadir
                # una restricción que pudiera ser general.
                if stage=='METODO_NO_DISPONIBLE' and attempt>=1:break
                if attempt+1>=MAX_CUENTAS_POR_SOLICITUD:break
                next_folio=uuid.uuid4().hex
                next_email=self.pool.reserve(next_folio)
                if not next_email:break
                try:self.preparacion.create(next_folio,next_email)
                except Exception:self.pool.review(next_folio);break
                chosen_email,chosen_folio=next_email,next_folio
                self.folios[slot]=next_folio
                self.send('status',slot,'OCUPADO',f'Cuenta anterior no utilizable; comprobando alternativa autorizada {attempt+2}/{MAX_CUENTAS_POR_SOLICITUD}')
            self.folios[slot]=None
            self.send('bridge_result',slot,reqid,'REVISAR',
               'No hay bandeja autorizada disponible. Las cuentas que piden otro método quedan apartadas; no se omiten verificaciones.',None,True)
        except Exception as exc:
            self.pool.review(chosen_folio)
            self.folios[slot]=None
            self.send('bridge_result',slot,reqid,'REVISAR',
                'Error durante preparación de Outlook ('+type(exc).__name__+').',None,True)
        finally:
            # No guardar nunca PIN ni CURP en registros, TXT ni cola compartida.
            del pin

def main():
    root=tk.Tk();PanelV20(root);root.mainloop()
if __name__=='__main__':main()
