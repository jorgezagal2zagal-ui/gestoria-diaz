"""LDPlayer V32: detenerse después de verificar el código, sin pasos posteriores."""
from __future__ import annotations
import re
import time
from enlace_integrado import Client, LinkError
from gestoria_prueba_v7 import foreground, launch_imss, adb_run
from imss_paso1 import norm, tap, login_detected
from imss_flujo_v11 import quick_ui
from imss_flujo_v14 import step_flow_v12
from puente_imss_outlook_v14 import es_pantalla_codigo as _pantalla_codigo_original
from validacion_pin import waiting_email_code, pin_prompt


def es_pantalla_codigo(nodes, email):
    words = ' '.join(n.words for n in nodes)
    return bool(_pantalla_codigo_original(nodes, email) and re.search(
        r'(?<![\w.+@-])' + re.escape(norm(email)) + r'(?![\w.+@-])', words))


def resultado_codigo(nodes, email):
    if not nodes:
        return 'DESCONOCIDO'
    words = ' '.join(n.words for n in nodes)
    addresses = set(re.findall(r'[\w.+-]+@[\w.-]+\.[a-z]{2,}', words))
    if addresses and norm(email) not in addresses:return 'DESCONOCIDO'
    if any(term in words for term in ('codigo incorrecto', 'codigo invalido',
            'codigo expirado', 'codigo vencido', 'codigo no valido', 'intenta nuevamente',
            'error', 'no se pudo', 'captcha')):
        return 'RECHAZADO'
    if waiting_email_code(nodes) or pin_prompt(nodes) or login_detected(nodes):
        return 'PENDIENTE'
    # Un cambio de pantalla, un spinner o una vinculación NO acreditan aceptación.
    if any(term in words for term in ('codigo verificado', 'codigo validado',
            'codigo aceptado', 'verificacion exitosa', 'validacion exitosa',
            'correo verificado', 'correo confirmado', 'correo validado')):
        return 'CONFIRMADO'
    return 'DESCONOCIDO'


def escribir_una_vez(adb, serial, email, code, stop):
    if stop.is_set():
        raise RuntimeError('Cancelado')
    if not re.fullmatch(r'[0-9]{6}', code or ''):
        raise ValueError('Formato de código inválido')
    if foreground(adb, serial) is not True:
        raise RuntimeError('IMSS no está en primer plano')
    nodes = quick_ui(adb, serial)
    if not es_pantalla_codigo(nodes, email):
        raise RuntimeError('No coincide la pantalla y el correo del folio')
    edits = sorted((n for n in nodes if n.enabled and
        ('EditText' in n.clazz or 'AutoCompleteTextView' in n.clazz)),
        key=lambda n: (n.mid[1], n.mid[0]))
    if len(edits) not in (1, 6) or any(n.text.strip() for n in edits):
        raise RuntimeError('No hay campos de código vacíos identificables; revisión manual')
    # Conservar ADB V7. Sólo se elimina el antiguo fallback de coordenadas a ciegas.
    if len(edits) == 1:
        if stop.is_set():raise RuntimeError('Cancelado')
        tap(adb, serial, *edits[0].mid)
        if stop.is_set():raise RuntimeError('Cancelado')
        rc, _ = adb_run(adb, serial, 'shell', 'input', 'text', code, timeout=15)
        if rc:raise RuntimeError('No se confirmó la escritura ADB')
    else:
        for digit, field in zip(code, edits):
            if stop.is_set():raise RuntimeError('Cancelado durante escritura; no repetir')
            tap(adb, serial, *field.mid)
            if stop.is_set():raise RuntimeError('Cancelado durante escritura; no repetir')
            rc, _ = adb_run(adb, serial, 'shell', 'input', 'text', digit, timeout=15)
            if rc:raise RuntimeError('Escritura parcial; no repetir')
    if stop.is_set():return
    if foreground(adb, serial) is not True:
        raise RuntimeError('La aplicación cambió; no pulsar Verificar')
    fresh = quick_ui(adb, serial)
    # Algunos formularios verifican automáticamente tras el sexto dígito.
    if not es_pantalla_codigo(fresh, email):return
    verify = [n for n in fresh if n.enabled and n.clickable and
              norm(n.text or n.desc).strip() in ('verificar', 'validar codigo', 'confirmar codigo')]
    if len(verify) != 1:
        raise RuntimeError('Código escrito; no se identificó Verificar de forma única')
    if not stop.is_set():tap(adb, serial, *verify[0].mid)


def ejecutar(adb, serial, curp, email, stop, client, update=lambda text: None,
             pin='', override=False, max_espera=520, folio=None):
    """El único lugar que conduce Android en el flujo integrado."""
    import uuid
    folio = folio or uuid.uuid4().hex
    entered = False
    try:
        ready = client.ready()
        if (ready.get('protocol') != 2 or not ready.get('ready') or
                str(ready.get('email', '')).casefold() != email.casefold()):
            return 'REVISAR', 'Outlook no confirma esta bandeja; no se tocó Android.', folio, False
        registered = client.begin(email, folio, serial)
        if (registered.get('serial') != serial or registered.get('email') != email.casefold() or
                registered.get('status') != 'PREPARANDO_IMSS' or registered.get('new_request') is not True):
            raise RuntimeError('Asignación del enlace incorrecta')
        if stop.is_set():return 'REVISAR', 'Cancelado antes de abrir IMSS.', folio, False
        # Verificar otra vez justo antes del primer comando Android.
        ready = client.ready()
        if not ready.get('ready') or ready.get('email') != email.casefold():
            return 'REVISAR', 'La bandeja perdió disponibilidad; Android retenido.', folio, False
        if foreground(adb, serial) is not True:
            state, _ = launch_imss(adb, serial, lambda text: update(text))
            if state != 'ABIERTA':
                return 'REVISAR', 'No se pudo abrir IMSS Digital.', folio, False
        update('Bandeja confirmada: iniciando IMSS en el LDPlayer asignado')
        requested = False
        def solicitar():
            nonlocal requested
            if requested:raise RuntimeError('No se permite repetir el formulario')
            client.requesting(folio)
            requested = True
        state, _ = step_flow_v12(adb, serial, curp, email, pin,
            ready_confirmed_by_operator=override, update=update, stop=stop, before_submit=solicitar)
        deadline = time.monotonic() + 85
        while not stop.is_set() and time.monotonic() < deadline:
            if foreground(adb, serial) is not True:break
            if es_pantalla_codigo(quick_ui(adb, serial), email):break
            if state in ('REVISAR', 'ESPERANDO PIN'):break
            stop.wait(.7)
        else:
            return 'REVISAR', 'No se confirmó la pantalla del código.', folio, False
        if stop.is_set() or not requested or not es_pantalla_codigo(quick_ui(adb, serial), email):
            return 'REVISAR', 'Pantalla de código no confirmada; revisar sin repetir.', folio, False
        client.waiting(folio)
        update('IMSS espera el código: Outlook notificado del folio actual')
        deadline = time.monotonic() + max_espera
        while not stop.is_set() and time.monotonic() < deadline:
            info = client.status(folio)
            if info.get('request_id') != folio or info.get('email') != email.casefold() or info.get('serial') != serial:
                raise RuntimeError('Respuesta ajena al folio, correo o emulador')
            if info['status'] == 'CODIGO_DISPONIBLE':
                update('Código recibido del folio; escritura única en LDPlayer')
                entered = True  # Desde aquí no se permite reintento, incluso con fallo parcial.
                escribir_una_vez(adb, serial, email, info.get('code'), stop)
                info.clear()
                update('Código introducido; comprobando aceptación sin pulsar pasos posteriores')
                for _ in range(20):
                    if stop.is_set():break
                    if foreground(adb, serial) is not True:break
                    outcome = resultado_codigo(quick_ui(adb, serial), email)
                    if outcome == 'RECHAZADO':
                        return 'REVISAR', 'IMSS muestra rechazo/error. No se reenvió el código.', folio, False
                    if outcome == 'CONFIRMADO':
                        client.ack(folio)
                        client.done(folio)
                        update('Código aceptado explícitamente. FIN: no se ejecutan pasos posteriores')
                        return 'CODIGO CONFIRMADO FIN', 'Aceptación visible confirmada; LDPlayer retenido en FIN.', folio, True
                    stop.wait(.7)
                return 'REVISAR', 'Código escrito; aceptación no demostrada. Sin pasos posteriores ni reintentos.', folio, False
            if info['status'] in ('CANCELADA', 'CADUCADA', 'CODIGO_CONFIRMADO_FIN'):
                return 'REVISAR', 'El enlace dejó de esperar el código; no se escribió nada.', folio, False
            stop.wait(.6)
        return 'REVISAR', 'Espera detenida o agotada; folio retenido para revisión.', folio, False
    except Exception as exc:
        prefix = 'Escritura posiblemente parcial; no repetir. ' if entered else ''
        return 'REVISAR', prefix + 'Revisión necesaria (' + type(exc).__name__ + ').', folio, False
