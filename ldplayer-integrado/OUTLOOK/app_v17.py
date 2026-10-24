# -*- coding: utf-8 -*-
"""V17: detectar bloqueo entre un código anterior y una nueva preparación.
Nunca cancela verificación previa ni cierra una sesión sin permiso del operador.
"""
from __future__ import annotations
import tkinter as tk
from tkinter import messagebox
from app_v15 import OutlookV15
from preparacion_v17 import PreparationV17

_ACTIVE=('ESPERANDO_CODIGO','CODIGO_DISPONIBLE','CODIGO_ENVIADO_AL_CELULAR')
_TERMINAL=('SIN_SOLICITUD','CANCELADA','CADUCADA','SOLICITUD_IMSS_ENVIADA')

class OutlookV17(OutlookV15):
    def __init__(self):
        super().__init__()
        self.preparacion=PreparationV17()
        self.title('GESTORÍA DÍAZ · OUTLOOK V17 · COORDINACIÓN')
        self.geometry('800x660')
        main=self.winfo_children()[0]  # panel principal, sin alterar sus controles
        self.recovery_button=self.button(main,'LIBERAR SESIÓN ANTERIOR (CONFIRMAR)',self.recover_previous_session)
        self.recovery_button.pack(fill='x',pady=(7,5))
        self.recovery_info=tk.StringVar(value='V17: espera solicitudes del IMSS. No pulses INICIAR manualmente.')
        self.label(main,'COORDINACIÓN IMSS V17',color='#E8BB62',size=9,bold=True).pack(anchor='w')
        tk.Label(main,textvariable=self.recovery_info,bg='#101419',fg='#ACB6C1',
                 font=('Segoe UI',9),wraplength=690,justify='left',anchor='w').pack(fill='x')
        self.info.set('V17 activo. IMSS enviará un correo a la vez; Outlook comprobará su bandeja.')

    def recover_previous_session(self):
        """Acción explícita para soltar SOLO un enlace antiguo, sin tocar lista ni claves."""
        status=self.state.status()
        active=status.get('status')
        # No abortar una preparación que YA comenzó a autenticar una cuenta.
        if self.prep_id:
            current=self.preparacion.status(self.prep_id)
            if current and current['estado'] in ('PENDIENTE','ABRIENDO'):
                messagebox.showwarning('Preparación en curso',
                    'Outlook está preparando una cuenta. Espera o revisa esa sesión; no se canceló nada.')
                return False
        if active not in _ACTIVE and not self.browser.running:
            self.recovery_info.set('No hay una sesión anterior activa para liberar.')
            return False
        ok=messagebox.askyesno('Liberar sesión anterior',
           'CONFIRMA que NO hay un trámite IMSS vigente esperando el código de esta sesión.\n\n'
           'Se cancelará únicamente el enlace local anterior y se cerrará su ventana privada.\n'
           'NO se borrarán correos, contraseñas ni la cola. Se respetará la pausa de seguridad.\n\n'
           '¿Continuar?')
        if not ok:return False
        if active in _ACTIVE:
            try:self.state.cancel(status['request_id'])
            except Exception:
                self.recovery_info.set('No se pudo cancelar el enlace anterior; revisa antes de continuar.')
                return False
        if self.browser.running:self.close_private()
        self._auto_started_request=None
        self._auto_start_attempted=True
        self.recovery_info.set('Enlace antiguo liberado. Outlook reanudará la cola después del enfriamiento.')
        self.info.set('Solicitud anterior cancelada con confirmación. No se eliminaron cuentas.')
        return True

    def _tick_once(self):
        super()._tick_once()
        if not self.server:
            self.recovery_info.set('Puerto 8797 ocupado: cierra las demás versiones de Outlook e inicia solo la V17.')
            return
        p=self.preparacion.pending()
        old=self.state.status()
        if p:
            if old.get('status') in _ACTIVE and old.get('request_id')!=p['folio']:
                self.recovery_info.set('Hay un código antiguo pendiente. Comprueba que no siga en trámite y usa LIBERAR SESIÓN ANTERIOR.')
            elif self.browser.rate_limited:
                self.recovery_info.set('Microsoft limitó el acceso: no probar otras cuentas hasta que se resuelva.')
            elif self.browser.running and self.browser.phase=='mail' and self.active_email==p['email']:
                # Reutilizar SOLO la misma bandeja y únicamente si el enlace previo está terminado.
                if old.get('status') in _TERMINAL and self.preparacion.set(p['folio'],p['email'],'LISTO'):
                    self.recovery_info.set('Bandeja correcta ya abierta; IMSS puede iniciar sin nuevo login.')
            elif self.browser.running and self.active_email!=p['email']:
                self.recovery_info.set('Está abierto otro correo. Libera la sesión anterior SOLO si no tiene un trámite activo.')
            elif self.cooldown.remaining():
                self.recovery_info.set('Pausa de Microsoft activa; el correo asignado espera sin reintentarse.')
            elif not self.browser.running:
                self.recovery_info.set('Solicitud recibida de IMSS; verificando credenciales e iniciando Outlook.')
            else:
                self.recovery_info.set('Preparando bandeja del correo asignado para la solicitud IMSS.')
        elif old.get('status') in _ACTIVE:
            self.recovery_info.set('Existe una solicitud anterior esperando código. Si ya se abandonó, libera su sesión.')
        elif self.browser.running:
            self.recovery_info.set('Outlook tiene una sesión activa. Se conservará hasta confirmar el trámite.')
        else:
            self.recovery_info.set('Conectado. Esperando solicitudes IMSS; no necesitas pulsar INICIAR.')

if __name__=='__main__':OutlookV17().mainloop()
