# -*- coding: utf-8 -*-
"""V12: entrada rápida y condicionada, sin modificar los archivos V7/V8/V11.

Se usa SOLO con la app IMSS Digital en primer plano. No automatiza
códigos OTP, CAPTCHA, vinculación, descarga de PDF ni acceso a Outlook.
"""
from __future__ import annotations
import re
import shlex
import time
from gestoria_prueba_v7 import adb_run, foreground
from imss_paso1 import editable_fields, login_detected, norm, screen_size, tap
from validacion_pin import pin_prompt, waiting_email_code
from imss_flujo_v11 import quick_ui, is_email_notice, confirm_email_notice

_FIELD = re.compile(r'[a-zA-Z0-9@._+\-]+\Z')


def fast_fill_fields(adb, serial, steps):
    """Rellena los dos campos sin enviar borrados a ciegas.

    El uso anterior de 45 KEYCODE_DEL cuando no había jerarquía detectable
    bloqueaba la interfaz mucho tiempo y podía dejar el CURP vacío. Se envían
    sólo pulsaciones para borrar un valor REAL que Android reporte, y sólo
    cuando parece una CURP o dirección de correo previamente introducida.
    La validación final ocurre en fast_login_v12, antes de Enviar.
    """
    script=[]
    for x,y,value,existing in steps:
        if not _FIELD.fullmatch(value):
            raise ValueError('El dato no es compatible con Android.')
        script.append(f'input tap {int(x)} {int(y)}')
        previous=(existing or '').strip()
        # Un placeholder visible (p. ej. "Ingresa CURP") NO es valor editable.
        actual_value=bool(previous and (
            re.fullmatch(r'[A-Za-z0-9]{18}',previous) or
            re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',previous)
        ))
        if actual_value:
            # Nunca 45-100 borrados cuando sólo existe un placeholder.
            script.append('input keyevent 123')
            script.append('input keyevent ' + ' '.join(['67'] * min(64,len(previous)+1)))
        script.append('input text '+shlex.quote(value))
    script.append('input keyevent 4')
    rc,_=adb_run(adb,serial,'shell','sh','-c',' && '.join(script),timeout=28)
    if rc:
        raise RuntimeError('ADB no pudo rellenar los campos de IMSS Digital.')


def fast_login_v12(adb, serial, curp, email, ready_confirmed_by_operator=False,
                   update=lambda message:None):
    if foreground(adb, serial) is not True:
        return False, 'IMSS Digital no está en primer plano.'
    try:
        nodes = quick_ui(adb, serial)
    except Exception:
        nodes = []
    if is_email_notice(nodes) or pin_prompt(nodes) or waiting_email_code(nodes):
        return False, 'El Android está en una verificación. No se escribió otra solicitud.'
    if not login_detected(nodes) and not ready_confirmed_by_operator:
        return False, 'No se confirmó la pantalla inicial con CURP y correo.'
    w, h = screen_size(adb, serial)
    if not (w < h and 400 <= w <= 2000 and 700 <= h <= 3200):
        return False, 'Resolución/orientación del Android no compatible.'

    defaults = {'curp':(0.52,0.176),'email':(0.52,0.255),
                'privacy':(0.11,0.393),'submit':(0.51,0.578)}
    def point(name,node=None):
        return node.mid if node else (int(w*defaults[name][0]),int(h*defaults[name][1]))
    cfield, efield = editable_fields(nodes)
    # Una sola invocación ADB para ambos datos (y para ocultar el teclado).
    update('Escribiendo CURP y correo en modo rápido')
    fast_fill_fields(adb, serial, [
        (*point('curp',cfield), curp, cfield.text if cfield else None),
        (*point('email',efield), email, efield.text if efield else None),
    ])

    # Verificar antes de enviar, especialmente para evitar usar CURP equivocada.
    try:
        fresh = quick_ui(adb, serial)
    except Exception:
        return False, 'No fue posible verificar los datos escritos; no se inició sesión.'
    a,b = editable_fields(fresh)
    # Si los campos editables están expuestos, exigir ambos valores exactos.
    # Una pantalla con correo visible pero CURP vacía no puede continuar.
    if a is not None and a.text.strip() != curp:
        return False, 'La CURP está vacía o no coincide. Se detuvo antes de Iniciar sesión.'
    if b is not None and b.text.strip().casefold() != email.casefold():
        return False, 'El correo está vacío o no coincide. Se detuvo antes de Iniciar sesión.'
    if a is not None and b is not None and a.mid == b.mid:
        return False, 'Android expuso un mismo control para ambos campos; revisa la pantalla.'
    # Los campos dejan de decir 'Ingresa CURP'/'Correo' al llenarse. Por eso
    # verificamos el formulario por sus dos editables y el botón Iniciar sesión.
    has_login_button = any('iniciar sesion' in n.words for n in fresh)
    editable_count = sum('EditText' in n.clazz or 'AutoCompleteTextView' in n.clazz for n in fresh if n.enabled)
    if not (has_login_button and editable_count >= 2 and a is not None and b is not None):
        return False, 'La pantalla cambió durante la escritura. No se pulsó Iniciar sesión.'

    checkbox = next((n for n in fresh if n.checkable and
                     ('checkbox' in n.clazz.casefold() or 'aviso' in n.words)), None)
    if checkbox and not checkbox.checked:
        tap(adb, serial, *checkbox.mid)
    elif checkbox is None:
        label = next((n for n in fresh if 'he leido' in n.words and 'aviso' in n.words),None)
        tap(adb,serial,int(w*defaults['privacy'][0]),
            label.mid[1] if label else int(h*defaults['privacy'][1]))
    # Si el control es detectable, exigir palomita antes de continuar.
    if checkbox and not checkbox.checked:
        checked_ui = quick_ui(adb, serial)
        after = next((n for n in checked_ui if n.checkable and
                      ('checkbox' in n.clazz.casefold() or 'aviso' in n.words)), None)
        if after and not after.checked:
            return False, 'El aviso de privacidad sigue sin aceptar; no se inició sesión.'
    submit = next((n for n in fresh if 'iniciar sesion' in n.words and n.clickable),None)
    if submit is None:
        submit = next((n for n in fresh if 'iniciar sesion' in n.words and n.clazz.endswith('Button')),None)
    update('Iniciando sesión')
    tap(adb, serial, *point('submit',submit))
    return True, 'Datos enviados. Esperando respuesta del IMSS.'


def fast_pin_v12(adb, serial, pin, nodes, update=lambda message:None):
    """Escribe una sola vez el PIN en un campo ya reconocido; confirma con Enter."""
    if not pin_prompt(nodes):
        return False, 'No es la pantalla de PIN del dispositivo.'
    if not re.fullmatch(r'\d{4,8}', pin or ''):
        return False, 'Introduce en el panel el PIN del Android.'
    fields=[n for n in nodes if n.enabled and
            ('EditText' in n.clazz or 'AutoCompleteTextView' in n.clazz)]
    if len(fields)!=1:
        return False, 'No se identificó un campo único de PIN.'
    update('Escribiendo PIN del dispositivo')
    x,y=fields[0].mid
    # Una invocación ADB. No incluye Enter: se verifica antes si avanzó solo.
    script=f'input tap {x} {y}'
    if fields[0].text:
        script+=' && input keyevent 123 && input keyevent '+ ' '.join(['67']*(len(fields[0].text)+2))
    script+=' && input text '+shlex.quote(pin)
    rc,_=adb_run(adb,serial,'shell','sh','-c',script,timeout=14)
    if rc: return False, 'ADB no logró escribir el PIN.'
    current=quick_ui(adb,serial)
    if pin_prompt(current):
        update('Confirmando PIN con Enter')
        rc,_=adb_run(adb,serial,'shell','input','keyevent','66',timeout=9)
        if rc: return False, 'No se logró pulsar Enter para el PIN.'
    return True, 'PIN enviado; el bot no lo repetirá automáticamente.'


def step_flow_v12(adb,serial,curp,email,pin,
                   ready_confirmed_by_operator=False, update=lambda msg:None):
    ok, msg=fast_login_v12(adb,serial,curp,email,ready_confirmed_by_operator,update)
    if not ok: return 'REVISAR',msg
    used_pin = used_notice = False
    repeated = 0
    last='Esperando respuesta de IMSS Digital.'
    # El número de consultas no se reduce arbitrariamente; la red/IMSS puede tardar.
    for attempt in range(12):
        if attempt: time.sleep(.15)
        try: nodes=quick_ui(adb,serial)
        except Exception:
            last='No se pudo leer la pantalla. Revisa el emulador.'
            continue
        if is_email_notice(nodes):
            if used_notice:
                repeated += 1
                if repeated>=4:
                    return 'REVISAR','El aviso sigue visible después de Confirmar.'
                continue
            ok,msg=confirm_email_notice(adb,serial,nodes,update)
            if not ok: return 'REVISAR',msg
            used_notice=True; repeated=0; last=msg; continue
        if waiting_email_code(nodes):
            return 'ESPERANDO CÓDIGO','Esperando el código del correo autorizado (entrada manual pendiente).'
        if pin_prompt(nodes):
            if used_pin:
                repeated+=1
                if repeated>=4:
                    return 'REVISAR','La pantalla de PIN sigue visible tras Enter; no se repitió.'
                continue
            ok,msg=fast_pin_v12(adb,serial,pin,nodes,update)
            if not ok:
                return ('ESPERANDO PIN' if 'Introduce en el panel' in msg else 'REVISAR'),msg
            used_pin=True; repeated=0; last=msg;continue
        words=' '.join(n.words for n in nodes)
        if any(s in words for s in ('si quiero hacer el cambio','vincular','vinculacion')):
            return 'VALIDACIÓN EN CURSO','Se requiere revisar la vinculación del dispositivo.'
        last=('IMSS está procesando el inicio de sesión.' if login_detected(nodes)
              else 'IMSS cambió de pantalla; revisa el siguiente paso.')
    return ('VALIDACIÓN EN CURSO' if (used_notice or used_pin) else 'REVISAR'),last
