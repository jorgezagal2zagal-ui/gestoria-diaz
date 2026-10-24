# -*- coding: utf-8 -*-
"""V10: Verificación conservadora del PIN del PROPIO Android, y retorno asistido.
No sortea verificaciones: solamente escribe el PIN configurado por el operador,
una vez, si el UI expone la pantalla de verificación de identidad del dispositivo.
Nunca guardar PIN, CURP, correo ni XML en diagnóstico.
"""
from __future__ import annotations
import re
import time
from gestoria_prueba_v7 import adb_run, foreground, launch_imss
from imss_paso1 import ui_dump, login_detected, editable_fields, tap, clear_field, type_ascii, norm


def pin_prompt(nodes):
    words = ' '.join(n.words for n in nodes)
    # Exigimos indicadores distintivos de PIN del dispositivo. Código de correo NO es PIN.
    header = any(term in words for term in (
        'validacion de identidad', 'confirma tu identidad para ingresar',
        'introduce el pin', 'ingresa tu pin', 'pin del dispositivo',
        'contrasena del dispositivo', 'desbloquear el dispositivo'))
    if not header: return False
    if any(term in words for term in ('codigo enviado', 'codigo de verificacion',
                                      'codigo de validacion', 'verifica tu correo',
                                      'codigo recibido', 'otp', 'correo electronico')):
        return False
    editable = [n for n in nodes if n.enabled and
                ('EditText' in n.clazz or 'AutoCompleteTextView' in n.clazz)]
    return len(editable) == 1


def waiting_email_code(nodes):
    words=' '.join(n.words for n in nodes)
    return any(term in words for term in ('codigo enviado', 'codigo de verificacion',
                                          'codigo de validacion', 'codigo recibido',
                                          'revisa tu correo', 'enviamos un codigo',
                                          'confirma tu correo'))


def read_android(adb, serial):
    if foreground(adb, serial) is not True:
        return None
    try: return ui_dump(adb, serial)
    except Exception: return None


def enter_pin_once(adb, serial, pin, update=lambda msg: None):
    """Return UI state/description. Never sends PIN to unrecognized screen."""
    nodes = None
    for _ in range(5):
        nodes = read_android(adb, serial)
        if nodes is not None and (pin_prompt(nodes) or waiting_email_code(nodes)):
            break
        time.sleep(0.7)
    if nodes is None:
        return 'REVISAR', 'No se pudo comprobar el contenido de la pantalla.'
    if waiting_email_code(nodes):
        return 'ESPERANDO CÓDIGO', 'Ya se solicita el código del correo; no se ingresó PIN.'
    if not pin_prompt(nodes):
        return 'REVISAR', 'No se identificó una pantalla segura de PIN; no se envió ningún dato.'
    if not re.fullmatch(r'\d{4,8}', pin or ''):
        return 'ESPERANDO PIN', 'Introduce en el panel el PIN del dispositivo (4 a 8 dígitos).'
    editables=[n for n in nodes if n.enabled and ('EditText' in n.clazz or 'AutoCompleteTextView' in n.clazz)]
    if len(editables) != 1:
        return 'REVISAR', 'Hay más de un campo editable, se requiere revisión manual.'
    update('Validando PIN del dispositivo')
    tap(adb, serial, *editables[0].mid)
    clear_field(adb, serial, 12)
    type_ascii(adb, serial, pin)
    # Algunos Android confirman automáticamente el PIN; otros necesitan Enter.
    # Volver a leer el UI ANTES de mandar Enter evita confirmar por error el
    # formulario de correo si el PIN ya hizo avanzar a la siguiente pantalla.
    current = read_android(adb, serial)
    if current is None:
        return 'REVISAR', 'PIN escrito, pero no se confirmó la pantalla actual; pulsa Enter manualmente si sigue en validación.'
    if waiting_email_code(current):
        return 'ESPERANDO CÓDIGO', 'PIN aceptado automáticamente; continúa verificación por correo.'
    if login_detected(current):
        return 'REVISAR', 'Tras introducir el PIN regresó a inicio de sesión; revisa la pantalla.'
    if pin_prompt(current):
        update('PIN escrito; confirmando con Enter')
        # Android KEYCODE_ENTER = 66. Se envía SOLO al emulador asignado y una vez.
        rc, _ = adb_run(adb, serial, 'shell', 'input', 'keyevent', '66', timeout=10)
        if rc != 0:
            return 'REVISAR', 'PIN escrito, pero ADB no logró enviar Enter. Revisa el emulador.'
    else:
        return 'VALIDACIÓN EN CURSO', 'El PIN produjo un cambio de pantalla; no se envió Enter adicional.'
    # Tras pulsar Enter, comprobar el resultado sin volver a escribir el PIN.
    for _ in range(6):
        time.sleep(0.9)
        current = read_android(adb, serial)
        if current is None: continue
        if waiting_email_code(current):
            return 'ESPERANDO CÓDIGO', 'PIN confirmado con Enter; continúa verificación por correo.'
        if login_detected(current):
            return 'REVISAR', 'Regresó a inicio de sesión; comprueba la autenticación.'
        if not pin_prompt(current):
            return 'VALIDACIÓN EN CURSO', 'PIN confirmado con Enter; revisa el siguiente paso.'
    return 'REVISAR', 'Se envió Enter, pero sigue visible la pantalla de PIN. Revisa manualmente; no se reintentará.'


def return_to_login(adb, serial, update=lambda msg: None):
    """Return to the start *only after explicit operator confirmation*.

    Try the app's exposed logout/back navigation, never force-stop or reset data.
    Do not mark LIBRE unless login page is actually detected.
    """
    if foreground(adb, serial) is not True:
        return 'REVISAR', 'IMSS no está en primer plano. Ábrelo con el botón V7.'
    nodes = read_android(adb,serial)
    if nodes is not None and login_detected(nodes):
        return 'LIBRE', 'IMSS Digital permanece en pantalla inicial (CURP y correo).'
    # Prefer visible, explicit app controls over blind back navigation.
    for step in range(4):
        nodes = read_android(adb,serial)
        if nodes is None:
            return 'REVISAR','No se puede leer la pantalla. Vuelve manualmente al inicio.'
        if login_detected(nodes):
            return 'LIBRE', 'Pantalla inicial verificada; Android disponible.'
        words=' '.join(n.words for n in nodes)
        if 'codigo' in words or 'validacion de identidad' in words or 'pin' in words:
            return 'REVISAR', 'Sigue en una verificación; no se interrumpe automáticamente.'
        logout = next((n for n in nodes if n.clickable and any(x in n.words for x in ('cerrar sesion','finalizar sesion','salir de mi cuenta'))), None)
        if logout:
            update('Cerrando sesión en IMSS')
            tap(adb,serial,*logout.mid)
        else:
            update('Volviendo a la pantalla inicial')
            rc,_ = adb_run(adb,serial,'shell','input','keyevent','4',timeout=10)
            if rc != 0: return 'REVISAR', 'Android no respondió a Volver.'
        time.sleep(0.8)
        if foreground(adb,serial) is not True:
            return 'REVISAR', 'IMSS salió de primer plano. No se reinició la app automáticamente.'
    nodes=read_android(adb,serial)
    if nodes is not None and login_detected(nodes):
        return 'LIBRE','Pantalla inicial verificada; Android disponible.'
    return 'REVISAR','No se confirmó pantalla inicial. Ajusta manualmente y usa Comprobar libre.'
