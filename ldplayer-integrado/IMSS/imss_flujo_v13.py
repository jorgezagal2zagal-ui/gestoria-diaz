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


def _actual_input_text(value):
    """Placeholders do not represent a filled Android text field."""
    value=(value or '').strip()
    return value if (re.fullmatch(r'[A-Za-z0-9]{18}',value) or
       re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',value)) else ''


def _write_exact(adb,serial,target,expected,label,update,return_snapshot=False):
    """Write one field and confirm its value before moving to the next.

    A keyboard opening can move form coordinates; therefore we reacquire
    UI nodes between fields and use the actual EditText bounds, never a
    tap from a stale screen measurement.
    """
    if target is None:
        return False, f'No se detectó el campo {label}; no se escribió en otro.'
    update('Escribiendo '+label)
    x,y=target.mid
    old=_actual_input_text(target.text)
    # A single ADB subprocess executes tap+type, rather than waiting for two
    # separate Windows->emulator roundtrips. Coordinates come from a verified
    # EditText bound; never from fixed screen positions.
    script=f'input tap {int(x)} {int(y)}'
    if old:
        script+=' && input keyevent 123'
        script+=' && input keyevent '+ ' '.join(['67']*(len(old)+1))
    script+=' && input text '+shlex.quote(expected)
    rc,_=adb_run(adb,serial,'shell','sh','-c',script,timeout=22)
    if rc:return False,f'ADB no pudo escribir {label}.'
    for verification in range(3):
        try:now=quick_ui(adb,serial)
        except Exception:
            if verification==2:return False,f'No se pudo verificar {label} después de escribir.'
            time.sleep(.25)
            continue
        first,second=editable_fields(now)
        current=first if label=='CURP' else second
        if first is None or second is None or first.mid==second.mid:
            return False,'La pantalla no expone dos campos independientes; detuve la escritura por seguridad.'
        if current is not None and current.text.strip().casefold()==expected.casefold():
            break
        if verification==2:
            return False,f'{label} NO quedó escrito correctamente; detenido antes de continuar.'
        time.sleep(.25)
    return (True,'OK',now) if return_snapshot else (True,'OK')


def fast_login_v13(adb,serial,curp,email,ready_confirmed_by_operator=False,
                   update=lambda message:None):
    if foreground(adb,serial) is not True:
        return False,'IMSS Digital no está en primer plano.'
    try:nodes=quick_ui(adb,serial)
    except Exception:nodes=[]
    if is_email_notice(nodes) or pin_prompt(nodes) or waiting_email_code(nodes):
        return False,'El Android está en una verificación. No se escribió otra solicitud.'
    if not login_detected(nodes) and not ready_confirmed_by_operator:
        return False,'No se confirmó la pantalla inicial con CURP y correo.'
    w,h=screen_size(adb,serial)
    if not (w<h and 400<=w<=2000 and 700<=h<=3200):
        return False,'Resolución/orientación del Android no compatible.'
    cfield,efield=editable_fields(nodes)
    if cfield is None or efield is None or cfield.mid==efield.mid:
        return False,'No se identificaron por separado CURP y correo. No escribiré en posiciones a ciegas.'
    # The first field's fresh verified UI doubles as the screen snapshot for
    # locating the second field: skip one expensive uiautomator dump.
    answer=_write_exact(adb,serial,cfield,curp,'CURP',update,return_snapshot=True)
    ok,detail=answer[:2]
    if not ok:return False,detail
    nodes2=answer[2]
    c2,e2=editable_fields(nodes2)
    if c2 is None or e2 is None or c2.mid==e2.mid or c2.text.strip().upper()!=curp:
        return False,'La CURP se perdió al cambiar el enfoque; no se escribió el correo.'
    update('CURP confirmada; enfocando campo de correo')
    ok,detail=_write_exact(adb,serial,e2,email,'correo',update)
    if not ok:
        # El teclado Android puede cambiar la posición real del segundo input.
        # Se permite un único reintento, pero únicamente si la CURP permanece
        # intacta y la pantalla sigue siendo el formulario inicial.
        update('Correo no confirmado; reubicando el campo una sola vez')
        adb_run(adb,serial,'shell','input','keyevent','4',timeout=9)
        try:
            retry_nodes=quick_ui(adb,serial)
        except Exception:
            return False,'Fallo correo: no pude volver a leer los controles; no envié el formulario.'
        a2,b2=editable_fields(retry_nodes)
        if (not login_detected(retry_nodes) or a2 is None or b2 is None or
                a2.mid==b2.mid or a2.text.strip().upper()!=curp):
            return False,'Fallo correo: la pantalla o CURP cambió; no envié el formulario.'
        if b2.text.strip().casefold()!=email.casefold():
            ok,detail=_write_exact(adb,serial,b2,email,'correo',update)
            if not ok:
                return False,'El campo de correo siguió vacío o incorrecto tras reintento: '+detail
        update('Correo recuperado y comprobado')
    adb_run(adb,serial,'shell','input','keyevent','4',timeout=10)
    try:fresh=quick_ui(adb,serial)
    except Exception:return False,'No se pudieron verificar ambos datos; formulario no enviado.'
    a,b=editable_fields(fresh)
    if (a is None or b is None or a.mid==b.mid or
        a.text.strip().upper()!=curp or b.text.strip().casefold()!=email.casefold()):
        return False,'Verificación final fallida: CURP y correo no coinciden; formulario NO enviado.'
    update('CURP y correo verificados')
    has_login=any('iniciar sesion' in n.words for n in fresh)
    if not has_login:
        return False,'El formulario cambió antes de enviarlo. Revisa IMSS Digital.'
    checkbox=next((n for n in fresh if n.checkable and
              ('checkbox' in n.clazz.casefold() or 'aviso' in n.words)),None)
    if checkbox and not checkbox.checked:
        tap(adb,serial,*checkbox.mid)
        checked_ui=quick_ui(adb,serial)
        again=next((n for n in checked_ui if n.checkable and
             ('checkbox' in n.clazz.casefold() or 'aviso' in n.words)),None)
        if again and not again.checked:return False,'El aviso de privacidad no quedó aceptado.'
        fresh=checked_ui
    elif checkbox is None:
        label=next((n for n in fresh if 'he leido' in n.words and 'aviso' in n.words),None)
        if label:tap(adb,serial,*label.mid)
        else:
            # Preserve V25's privacy-control fallback on builds that omit labels.
            tap(adb,serial,int(w*.11),int(h*.393))
        try:
            checked_ui=quick_ui(adb,serial)
            check=next((n for n in checked_ui if n.checkable and 'checkbox' in n.clazz.casefold()),None)
            if check is not None and not check.checked:
                return False,'El aviso de privacidad no quedó aceptado.'
        except Exception:
            return False,'No se pudo verificar el aviso de privacidad.'
    # Check the fields again after the consent click.
    a,b=editable_fields(fresh)
    if (a is None or b is None or a.text.strip().upper()!=curp or
        b.text.strip().casefold()!=email.casefold()):
        return False,'Los campos cambiaron al aceptar el aviso; formulario NO enviado.'
    submit=next((n for n in fresh if 'iniciar sesion' in n.words and
                 (n.clickable or n.clazz.endswith('Button'))),None)
    if not submit:return False,'No se encontró el botón Iniciar sesión; no se presionó a ciegas.'
    update('Enviando CURP y correo verificados')
    tap(adb,serial,*submit.mid)
    return True,'CURP y correo comprobados y enviados.'


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
    ok, msg=fast_login_v13(adb,serial,curp,email,ready_confirmed_by_operator,update)
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
