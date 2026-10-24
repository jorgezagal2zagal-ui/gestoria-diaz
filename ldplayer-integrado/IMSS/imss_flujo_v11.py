# -*- coding: utf-8 -*-
"""Gestoría Díaz V11: flujo rápido y confirmado del aviso de correo.

Importa el motor ADB de V7 y deja el código V7/V8/V10 sin modificar.
Solo verifica aviso de correo y PIN propio del dispositivo; NO lee correos.
"""
from __future__ import annotations
import re
import time
from gestoria_prueba_v7 import adb_run, foreground
from imss_paso1 import (parse_ui, ui_dump, login_detected, editable_fields,
                       screen_size, tap, clear_field, type_ascii, norm)
from validacion_pin import pin_prompt, waiting_email_code


def quick_ui(adb, serial):
    """Una llamada ADB para volcar/leer/borrar XML, sin almacenarlo en Windows."""
    command = 'uiautomator dump /sdcard/window.xml >/dev/null 2>&1 && cat /sdcard/window.xml; rm -f /sdcard/window.xml'
    try:
        rc, output = adb_run(adb, serial, 'shell', 'sh', '-c', command, timeout=17)
        if '<hierarchy' in output:
            return parse_ui(output[output.index('<hierarchy'):])
    except (RuntimeError, ValueError):
        pass
    return ui_dump(adb, serial)


def is_email_notice(nodes):
    """Identifica SOLAMENTE el aviso exacto que pide confirmar correo."""
    text = ' '.join(norm(n.text + ' ' + n.desc) for n in nodes)
    return ('para poder acceder' in text and
            ('debes de haber confirmado tu correo electronico' in text or
             'debes haber confirmado tu correo electronico' in text))


def confirm_email_notice(adb, serial, nodes, update=lambda msg:None):
    if not is_email_notice(nodes):
        return False, 'No se detectó el aviso de confirmación del correo.'
    # Comprobar que IMSS está delante antes de presionar un aviso.
    if foreground(adb, serial) is not True:
        return False, 'IMSS no está en primer plano; no se pulsó Confirmar.'
    button = next((n for n in nodes if n.enabled and
                   norm(n.text).strip() == 'confirmar' and
                   n.bounds[2] > n.bounds[0] and n.bounds[3] > n.bounds[1]), None)
    if button is None:
        # No hacer clic por coordenadas a ciegas, ni si existe otro botón distinto.
        return False, 'Se detectó el aviso, pero no el botón Confirmar por accesibilidad.'
    update('Aviso de correo detectado; pulsando Confirmar')
    tap(adb, serial, *button.mid)
    return True, 'Se pulsó Confirmar en el aviso de correo.'


def fast_login(adb, serial, curp, email, ready_confirmed_by_operator=False, update=lambda msg:None):
    """Mismo paso 1 que V8, evitando borrado de 100 teclas y esperas extra."""
    if foreground(adb, serial) is not True:
        return False, 'IMSS Digital no está abierto en primer plano.'
    try: nodes = quick_ui(adb, serial)
    except Exception: nodes = []
    if is_email_notice(nodes):
        return False, 'Hay un aviso abierto; no se escribieron datos.'
    if not login_detected(nodes) and not ready_confirmed_by_operator:
        return False, 'No se comprobó la pantalla inicial de IMSS.'
    if pin_prompt(nodes) or waiting_email_code(nodes):
        return False, 'El Android está en verificación; no se escribieron datos.'
    w,h = screen_size(adb, serial)
    if w >= h or w < 400 or h < 700 or w > 2000 or h > 3200:
        return False, 'La resolución/orientación no es compatible.'
    defaults = {'curp':(0.52,0.176),'email':(0.52,0.255),'privacy':(0.11,0.393),'submit':(0.51,0.578)}
    def pos(name,node=None):
        return node.mid if node else (int(w*defaults[name][0]),int(h*defaults[name][1]))
    cfield, efield = editable_fields(nodes)
    update('Ingresando CURP y correo')
    tap(adb, serial, *pos('curp',cfield))
    # Si el campo está vacío NO borrar veinte teclas innecesarias.
    if cfield is None or cfield.text:
        clear_field(adb, serial, max(20, len(cfield.text)+2) if cfield else 20)
    type_ascii(adb,serial,curp)
    tap(adb,serial,*pos('email',efield))
    # V10 borraba 100 caracteres SIEMPRE; usar solo lo que ya hay escrito.
    if efield is None or efield.text:
        clear_field(adb,serial, max(26, len(efield.text)+2) if efield else 35)
    type_ascii(adb,serial,email)
    adb_run(adb, serial,'shell','input','keyevent','4',timeout=8)
    try: fresh=quick_ui(adb,serial)
    except Exception: fresh=[]
    a,b=editable_fields(fresh)
    if a and a.text and a.text != curp:
        return False, 'La CURP ingresada no coincide; revisa el Android.'
    if b and b.text and b.text.casefold()!=email.casefold():
        return False, 'El correo ingresado no coincide; revisa el Android.'
    checkbox=next((n for n in fresh if n.checkable and ('checkbox' in n.clazz.casefold() or 'aviso' in n.words)),None)
    if checkbox and not checkbox.checked:
        tap(adb,serial,*checkbox.mid)
    elif not checkbox:
        label=next((n for n in fresh if 'he leido' in n.words and 'aviso' in n.words),None)
        tap(adb,serial,int(w*0.11),label.mid[1] if label else int(h*defaults['privacy'][1]))
    # Asegurar la palomita antes de iniciar (salvo Android que no exponga accesibilidad).
    if checkbox and not checkbox.checked:
        verify=quick_ui(adb,serial)
        newbox=next((n for n in verify if n.checkable and ('checkbox' in n.clazz.casefold() or 'aviso' in n.words)),None)
        if newbox is not None and not newbox.checked:
            return False, 'No quedó aceptado el aviso de privacidad.'
    submit=next((n for n in fresh if 'iniciar sesion' in n.words and n.clickable),None)
    if submit is None:
        submit=next((n for n in fresh if 'iniciar sesion' in n.words and n.clazz.endswith('Button')),None)
    update('Iniciando sesión')
    tap(adb,serial,*pos('submit',submit))
    return True, 'Datos enviados; esperando respuesta del IMSS.'


def fast_pin_once(adb,serial,pin,nodes,update=lambda msg:None):
    """Introducir PIN y confirmar con Enter una sola vez; no OTP."""
    if not pin_prompt(nodes):
        return False, 'No es la pantalla de PIN.'
    if not re.fullmatch(r'\d{4,8}',pin or ''):
        return False, 'Escribe el PIN del dispositivo en el panel.'
    editable=[n for n in nodes if n.enabled and ('EditText' in n.clazz or 'AutoCompleteTextView' in n.clazz)]
    if len(editable)!=1: return False, 'No se identificó un campo único de PIN.'
    update('Escribiendo PIN del Android')
    tap(adb,serial,*editable[0].mid)
    if editable[0].text: clear_field(adb,serial,len(editable[0].text)+2)
    type_ascii(adb,serial,pin)
    # Una lectura inmediata: si todavía hay pantalla PIN, enviar Enter tal como V10.
    now=quick_ui(adb,serial)
    if pin_prompt(now):
        update('Confirmando PIN con Enter')
        rc,_=adb_run(adb,serial,'shell','input','keyevent','66',timeout=9)
        if rc: return False,'ADB no logró pulsar Enter para el PIN.'
    return True,'PIN enviado (sin reintentos automáticos).'


def step_flow(adb,serial,curp,email,pin,ready_confirmed_by_operator=False,update=lambda msg:None):
    """Un único intento por PIN y por aviso; las pantallas no reconocidas requieren revisión."""
    ok,msg=fast_login(adb,serial,curp,email,ready_confirmed_by_operator,update)
    if not ok: return 'REVISAR',msg
    used_pin=False
    used_notice=False
    last='Esperando respuesta de IMSS Digital.'
    after_action_checks=0
    for attempt in range(12):
        if attempt: time.sleep(.25)
        try: nodes=quick_ui(adb,serial)
        except Exception:
            last='No se pudo leer la pantalla. Revisa el emulador.'
            continue
        if is_email_notice(nodes):
            if used_notice:
                after_action_checks += 1
                if after_action_checks >= 4:
                    return 'REVISAR','El mismo aviso sigue visible tras Confirmar. Revisa el emulador.'
                continue
            ok,msg=confirm_email_notice(adb,serial,nodes,update)
            if not ok: return 'REVISAR',msg
            used_notice=True
            after_action_checks=0
            last=msg
            continue
        if waiting_email_code(nodes):
            return 'ESPERANDO CÓDIGO','Esperando código del correo autorizado (no se introducen códigos automáticamente).'
        if pin_prompt(nodes):
            if used_pin:
                after_action_checks += 1
                if after_action_checks >= 4:
                    return 'REVISAR','La pantalla PIN sigue visible después de Enter; no se vuelve a escribir.'
                continue
            ok,msg=fast_pin_once(adb,serial,pin,nodes,update)
            if not ok: return 'ESPERANDO PIN' if 'Escribe el PIN' in msg else 'REVISAR',msg
            used_pin=True
            after_action_checks=0
            last=msg
            continue
        words=' '.join(n.words for n in nodes)
        if 'si quiero hacer el cambio' in words or 'vincular' in words or 'vinculacion' in words:
            return 'VALIDACIÓN EN CURSO','Se requiere revisar la pantalla de vinculación del dispositivo.'
        # La solicitud puede seguir mostrando la pantalla de ingreso mientras responde el servidor.
        if login_detected(nodes):
            last='IMSS está procesando el inicio de sesión.'
            continue
        # Algunas transiciones presentan una pantalla sin texto antes del nuevo formulario.
        last='IMSS cambió de pantalla; verifica el paso siguiente.'
    return ('VALIDACIÓN EN CURSO' if (used_notice or used_pin) else 'REVISAR'),last
