# -*- coding: utf-8 -*-
"""Entrega local de códigos Outlook V15.2 -> IMSS Digital. Nada se guarda en disco.

Outlook V15.2 solo gestiona una petición de código simultáneamente. La interfaz
V13 serializa esa fase, aunque conserva la conexión ADB de los 3 emuladores.
Nunca intenta sortear MFA, bloqueos ni verificaciones que no reconoce.
"""
from __future__ import annotations
import re
import time
import uuid
import threading
from enlace import Client, LinkError
from gestoria_prueba_v7 import adb_run, foreground
from imss_flujo_v12 import step_flow_v12
from imss_flujo_v11 import quick_ui
from imss_paso1 import norm, screen_size, tap
from validacion_pin import waiting_email_code


class IntegracionError(RuntimeError):
    pass


def es_pantalla_codigo(nodes, email: str) -> bool:
    """Debe mostrar solicitud de un código y el correo EXACTO de esta solicitud."""
    if not nodes or not waiting_email_code(nodes):
        return False
    words = ' '.join(n.words for n in nodes)
    expected = norm(email)
    if expected not in words:
        return False
    return ('codigo de validacion' in words or 'codigo de verificacion' in words or
            'ingresa tu codigo' in words or 'escribe el codigo' in words or
            'ingresa el codigo' in words)


def escribir_codigo_imss(adb: str, serial: str, email: str, codigo: str,
                         ui=quick_ui, enviar=adb_run):
    """Solo introduce OTP de 6 dígitos, en la pantalla y correo esperados.

    No emite Enter: solo pulsa Verificar si está expuesto como control activo.
    En los demás casos deja una confirmación para el usuario.
    """
    if not re.fullmatch(r'\d{6}', codigo or ''):
        raise IntegracionError('Outlook devolvió un código con formato inválido.')
    if foreground(adb,serial) is not True:
        raise IntegracionError('IMSS Digital no está en primer plano; no se envió el código.')
    nodes = ui(adb,serial)
    if not es_pantalla_codigo(nodes,email):
        raise IntegracionError('No coincide el correo o la pantalla del código; no se envió nada.')
    edits = sorted([n for n in nodes if n.enabled and
                    ('EditText' in n.clazz or 'AutoCompleteTextView' in n.clazz)],
                   key=lambda n:(n.mid[1],n.mid[0]))
    if len(edits)==1:
        tap(adb,serial,*edits[0].mid)
        # No se borra un campo desconocido: hacerlo requeriría verificar el estado anterior.
        if edits[0].text:
            raise IntegracionError('El campo del código ya contiene texto: revisa manualmente.')
        rc,_ = enviar(adb,serial,'shell','input','text',codigo,timeout=15)
        if rc:raise IntegracionError('ADB no pudo introducir el código.')
    elif len(edits)==6:
        if any(n.text for n in edits):
            raise IntegracionError('Algunas casillas ya tienen texto: revisa manualmente.')
        # Seis casillas visibles: un dígito por casilla, en una sola llamada ADB.
        commands=[]
        for d,node in zip(codigo,edits):
            x,y=node.mid
            commands.extend([f'input tap {x} {y}', f'input text {d}'])
        rc,_=enviar(adb,serial,'shell','sh','-c',' && '.join(commands),timeout=25)
        if rc:raise IntegracionError('ADB no pudo completar las seis casillas.')
    elif len(edits)==0:
        # Captura del trámite del usuario: seis casillas gráficas sin EditText expuesto.
        # Únicamente actuar en el formulario identificado y con correo coincidente.
        w,h=screen_size(adb,serial)
        if h<=w or not (700<=h<=3200):
            raise IntegracionError('Resolución inesperada; es necesario introducir el código manualmente.')
        tap(adb,serial,int(w*.10),int(h*.39))
        rc,_=enviar(adb,serial,'shell','input','text',codigo,timeout=15)
        if rc:raise IntegracionError('ADB no pudo introducir el código en las casillas.')
    else:
        raise IntegracionError('Hay varios campos de código inesperados; revisión manual necesaria.')

    # Refrescar jerarquía y pulsar solo un botón Verificar explícito y activo.
    nodes2=ui(adb,serial)
    if not es_pantalla_codigo(nodes2,email):
        return 'ESCRITO','Se introdujo el código; la pantalla cambió automáticamente.'
    verify = next((n for n in nodes2 if n.enabled and n.clickable and
                   'verificar' in n.words and 'reenv' not in n.words),None)
    if verify is not None:
        tap(adb,serial,*verify.mid)
        return 'PULSADO','Se introdujo el código y se pulsó Verificar.'
    return 'MANUAL','Código escrito. Pulsa Verificar en el emulador y comprueba el resultado.'


class PuenteOutlook:
    def __init__(self, cliente=None):
        self.cliente = cliente or Client(timeout=2)

    def comprobar(self):
        return self.cliente.ping()

    def iniciar(self,email: str,folio: str):
        self.cliente.ping()       # Evitar solicitar IMSS cuando Outlook no está abierto.
        return self.cliente.begin(email,folio)

    def estado(self,folio: str):
        return self.cliente.status(folio)

    def confirmar_recepcion(self,folio: str):
        return self.cliente.ack(folio)

    def terminar_enlace(self,folio: str):
        return self.cliente.done(folio)

    def cancelar(self,folio: str):
        return self.cliente.cancel(folio)


def esperar_pantalla(adb,serial,email,stop,update,limite_seg=85, ui=quick_ui):
    until=time.monotonic()+limite_seg
    while time.monotonic()<until:
        if stop.is_set():return False
        if foreground(adb,serial) is not True:
            return False
        try:
            nodes=ui(adb,serial)
            if es_pantalla_codigo(nodes,email):return True
        except Exception:pass
        stop.wait(1.4)
    update('No se confirmó la pantalla del código. Comprueba IMSS Digital.')
    return False


def tramitar_con_outlook(adb,serial,curp,email,pin,override,update,stop,
                         puente=None, uuid_factory=None, max_espera=520):
    """Ejecuta V12 sin modificarla, y añade el traspaso de OTP verificado.

    Retorna (estado_imss, descripcion, folio_local_o_None, enlace_terminado).
    Si hay error en mitad de verificación, se conserva el folio para recuperación
    manual y NO se reutiliza otra cuenta de Outlook a ciegas.
    """
    p=puente or PuenteOutlook()
    folio=(uuid_factory or (lambda:uuid.uuid4().hex))()
    try:
        update('Reservando únicamente el correo correspondiente en Outlook')
        p.iniciar(email,folio)
    except (LinkError,ValueError,OSError) as e:
        return 'REVISAR','Outlook no aceptó esta solicitud: '+str(e)[:140],None,True
    try:
        update('Iniciando IMSS Digital con la V12')
        estado,detalle=step_flow_v12(adb,serial,curp,email,pin,
                                    ready_confirmed_by_operator=override,update=update)
        if stop.is_set():
            return 'REVISAR','Proceso detenido por el operador.',folio,False
        if not esperar_pantalla(adb,serial,email,stop,update):
            return estado if estado!='ESPERANDO CÓDIGO' else 'REVISAR',\
                   'Enlace Outlook activo; no se confirmó en IMSS la pantalla del código y correo.',folio,False
        update('Pantalla de código confirmada; esperando Outlook')
        cutoff=time.monotonic()+max_espera
        while time.monotonic()<cutoff and not stop.is_set():
            try: info=p.estado(folio)
            except LinkError:
                stop.wait(3)
                continue
            status=info.get('status')
            if status=='CODIGO_DISPONIBLE':
                if info.get('email','').casefold()!=email.casefold():
                    raise IntegracionError('El correo de Outlook no coincide con esta solicitud.')
                # Códigos se mantienen solamente en variables locales (no logs).
                code=info.get('code')
                update('Código nuevo recibido; entregándolo al emulador asignado')
                action,msg=escribir_codigo_imss(adb,serial,email,code)
                if action=='MANUAL':
                    return 'REVISAR',msg+' El enlace seguirá reservado hasta confirmar el resultado.',folio,False
                # Confirmación visible de cambio de pantalla, sin repetir OTP.
                for _ in range(5):
                    if stop.wait(1.2):break
                    try:
                        if not es_pantalla_codigo(quick_ui(adb,serial),email):
                            p.confirmar_recepcion(folio)
                            p.terminar_enlace(folio)
                            return 'VALIDACIÓN EN CURSO',\
                                'Código enviado y pantalla de validación superada. Revisa siguiente paso del IMSS.',folio,True
                    except Exception:pass
                return 'REVISAR',\
                       'Se escribió el código, pero IMSS no confirmó el avance. Revisar antes de continuar.',folio,False
            if status in ('CADUCADA','CANCELADA'):
                return 'REVISAR','La solicitud del enlace Outlook expiró o se canceló.',folio,True
            if status=='SOLICITUD_IMSS_ENVIADA':
                return 'REVISAR','Outlook marcó esta solicitud como finalizada sin entregar código.',folio,True
            stop.wait(2.5)
        return 'REVISAR','No llegó un código verificable a tiempo o el proceso fue detenido.',folio,False
    except Exception as exc:
        # Excepciones pueden contener información sensible: no se registran.
        return 'REVISAR',('Se necesita revisar la pantalla del IMSS / enlace local ('+
                         type(exc).__name__+').'),folio,False
