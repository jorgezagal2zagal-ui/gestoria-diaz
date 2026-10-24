# -*- coding: utf-8 -*-
"""Paso 1, exclusivamente la pantalla de inicio de sesión IMSS Digital.

IMPORTANTE: El módulo gestoria_prueba_v7.py se entrega sin modificar.
Este archivo es una extensión independiente, no una alteración de V7.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
import time
import unicodedata
import xml.etree.ElementTree as ET
from typing import Callable, Optional

from gestoria_prueba_v7 import PACKAGE, adb_run, foreground


def norm(value: str) -> str:
    return ''.join(c for c in unicodedata.normalize('NFKD', value or '')
                   if not unicodedata.combining(c)).casefold()


@dataclass(frozen=True)
class Node:
    clazz: str
    text: str
    desc: str
    rid: str
    bounds: tuple[int, int, int, int]
    checked: bool
    checkable: bool
    enabled: bool
    clickable: bool

    @property
    def mid(self):
        a, b, c, d = self.bounds
        return ((a + c) // 2, (b + d) // 2)

    @property
    def words(self):
        return norm(' '.join((self.text, self.desc, self.rid)))


def parse_ui(xml: str) -> list[Node]:
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return []
    result = []
    for elem in root.iter('node'):
        a = elem.attrib
        m = re.fullmatch(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', a.get('bounds', ''))
        if not m:
            continue
        result.append(Node(clazz=a.get('class', ''), text=a.get('text', ''),
                           desc=a.get('content-desc', ''), rid=a.get('resource-id', ''),
                           bounds=tuple(map(int, m.groups())),
                           checked=a.get('checked') == 'true',
                           checkable=a.get('checkable') == 'true',
                           enabled=a.get('enabled', 'true') == 'true',
                           clickable=a.get('clickable') == 'true'))
    return result


def ui_dump(adb: str, serial: str) -> list[Node]:
    # No almacenar XML en disco del equipo Windows; Android genera un XML temporal.
    rc, output = adb_run(adb, serial, 'shell', 'uiautomator', 'dump', '/sdcard/window.xml', timeout=25)
    if rc != 0:
        raise RuntimeError('No fue posible leer los controles de Android.')
    try:
        rc, xml = adb_run(adb, serial, 'shell', 'cat', '/sdcard/window.xml', timeout=12)
        if rc != 0 or '<hierarchy' not in xml:
            raise RuntimeError('ADB no devolvió una jerarquía de pantalla válida.')
        return parse_ui(xml)
    finally:
        try:
            adb_run(adb, serial, 'shell', 'rm', '-f', '/sdcard/window.xml', timeout=6)
        except Exception:
            pass


def login_detected(nodes: list[Node]) -> bool:
    words = ' '.join(x.words for x in nodes)
    return ('inicia sesion' in words and
            ('curp' in words or 'correo electronico' in words))


def validation_detected(nodes: list[Node]) -> bool:
    words = ' '.join(x.words for x in nodes)
    return any(k in words for k in ('validacion de identidad', 'codigo de validacion',
                                    'escribe el codigo', 'confirma tu identidad',
                                    'verificacion de identidad', 'ingresa tu codigo'))


def editable_fields(nodes: list[Node]):
    edits = [n for n in nodes if n.enabled and
             ('EditText' in n.clazz or 'AutoCompleteTextView' in n.clazz)]
    edits.sort(key=lambda n: (n.mid[1], n.mid[0]))
    # Prefer labeled EditText, fall back to first two editables on login page.
    curp = next((n for n in edits if 'curp' in n.words), None)
    email = next((n for n in edits if 'correo' in n.words or 'email' in n.words), None)
    if not curp and len(edits) >= 1: curp = edits[0]
    if not email and len(edits) >= 2: email = next((n for n in edits if n != curp), None)
    return curp, email


def screen_size(adb: str, serial: str) -> tuple[int, int]:
    rc, out = adb_run(adb, serial, 'shell', 'wm', 'size', timeout=10)
    if rc != 0:
        raise RuntimeError('No se pudo obtener la resolución del emulador.')
    m = re.search(r'(?:Physical|Override) size:\s*(\d+)x(\d+)', out)
    if not m:
        raise RuntimeError('Android no informó la resolución.')
    return int(m.group(1)), int(m.group(2))


def tap(adb: str, serial: str, x: int, y: int):
    rc, out = adb_run(adb, serial, 'shell', 'input', 'tap', str(x), str(y), timeout=12)
    if rc != 0:
        raise RuntimeError('Falló el toque ADB.')


def clear_field(adb: str, serial: str, max_chars: int):
    """Cursor al final y suprimir texto persistente, sin depender del teclado físico."""
    rc, _ = adb_run(adb, serial, 'shell', 'input', 'keyevent', '123', timeout=10)
    if rc != 0:
        raise RuntimeError('No fue posible colocar el cursor en el campo.')
    # KEYCODE_DEL=67. Ejecutar varios eventos en una sola llamada ADB.
    rc, _ = adb_run(adb, serial, 'shell', 'input', 'keyevent',
                    *(['67'] * max_chars), timeout=25)
    if rc != 0:
        raise RuntimeError('No fue posible limpiar el campo.')


def type_ascii(adb: str, serial: str, text: str):
    if not re.fullmatch(r'[a-zA-Z0-9@._+\-]+', text):
        raise ValueError('El campo contiene caracteres que no admite esta prueba.')
    rc, _ = adb_run(adb, serial, 'shell', 'input', 'text', text, timeout=15)
    if rc != 0:
        raise RuntimeError('ADB no logró escribir el dato.')


def check_login(adb: str, serial: str) -> tuple[bool, str]:
    if foreground(adb, serial) is not True:
        return False, 'IMSS Digital no está en primer plano'
    try:
        nodes = ui_dump(adb, serial)
    except Exception:
        return False, 'IMSS abierto; no se pudo leer su pantalla'
    if login_detected(nodes):
        return True, 'Pantalla inicial detectada'
    if validation_detected(nodes):
        return False, 'Pantalla de verificación; sigue ocupado'
    return False, 'IMSS abierto; revisa la pantalla actual'


def do_login(adb: str, serial: str, curp: str, email: str,
             ready_confirmed_by_operator: bool,
             update: Callable[[str], None]) -> tuple[str, str]:
    """Solo ingreso, checkbox, iniciar; JAMÁS manipular OTP, PIN ni vínculo."""
    if foreground(adb, serial) is not True:
        return 'REVISAR', 'IMSS Digital no está abierto en primer plano.'
    try:
        nodes = ui_dump(adb, serial)
    except Exception:
        nodes = []
    if not login_detected(nodes) and not ready_confirmed_by_operator:
        return 'REVISAR', 'No se confirmó la pantalla de inicio de sesión.'
    if nodes and validation_detected(nodes):
        return 'REVISAR', 'Ya está en verificación; no escribir otra CURP.'
    w, h = screen_size(adb, serial)
    if w >= h:
        return 'REVISAR', 'Se requiere Android en orientación vertical.'
    if not 400 <= w <= 2000 or not 700 <= h <= 3200:
        return 'REVISAR', 'Resolución de emulador no compatible con esta prueba.'
    curp_field, email_field = editable_fields(nodes)
    # Coordenadas relativas provenientes del video del usuario (LDPlayer 720x1280).
    # Solo se usan cuando el operador confirmó manualmente la pantalla inicial,
    # o cuando UIAutomator detecta la pantalla pero no etiqueta los campos.
    default = {'curp': (0.52, 0.176), 'email': (0.52, 0.255),
               'privacy': (0.11, 0.393), 'submit': (0.51, 0.578)}
    def point(key, node: Optional[Node] = None):
        if node:
            return node.mid
        x, y = default[key]
        return int(w * x), int(h * y)

    update('Escribiendo CURP y correo')
    tap(adb, serial, *point('curp', curp_field))
    # Sustituir texto previo; algunas instalaciones conservan el último correo.
    clear_field(adb, serial, 22)
    type_ascii(adb, serial, curp)
    tap(adb, serial, *point('email', email_field))
    clear_field(adb, serial, 100)
    type_ascii(adb, serial, email)
    # Ocultar teclado para revelar casilla y botón.
    adb_run(adb, serial, 'shell', 'input', 'keyevent', '4', timeout=9)
    update('Comprobando datos introducidos')
    try:
        fresh = ui_dump(adb, serial)
    except Exception:
        fresh = []
    # Detenerse si Android expone los valores y detectamos un error de escritura.
    check_curp, check_email = editable_fields(fresh)
    if check_curp and check_curp.text and check_curp.text != curp:
        return 'REVISAR', 'La CURP escrita no coincide. No se pulsó Iniciar sesión.'
    if check_email and check_email.text and check_email.text.casefold() != email.casefold():
        return 'REVISAR', 'El correo escrito no coincide. No se pulsó Iniciar sesión.'
    update('Aceptando aviso de privacidad')
    checkbox = next((n for n in fresh if n.checkable and
                     ('checkbox' in n.clazz.casefold() or 'aviso' in n.words)), None)
    if checkbox and not checkbox.checked:
        tap(adb, serial, *checkbox.mid)
    elif not checkbox:
        # Tocar la caja pequeña, no solamente el texto del aviso.
        label = next((n for n in fresh if 'he leido' in n.words and 'aviso' in n.words), None)
        if label:
            tap(adb, serial, int(w * 0.11), label.mid[1])
        else:
            tap(adb, serial, *point('privacy'))
    if checkbox and not checkbox.checked:
        try:
            after_check = ui_dump(adb, serial)
            check_node = next((n for n in after_check if n.checkable and
                               ('checkbox' in n.clazz.casefold() or 'aviso' in n.words)), None)
            if check_node and not check_node.checked:
                return 'REVISAR', 'No se pudo marcar el aviso de privacidad.'
        except Exception:
            pass
    submit = next((n for n in fresh if 'iniciar sesion' in n.words and n.clickable), None)
    if not submit:
        submit = next((n for n in fresh if 'iniciar sesion' in n.words and n.clazz.endswith('Button')), None)
    update('Presionando Iniciar sesión')
    tap(adb, serial, *point('submit', submit))
    # Desde aquí la solicitud queda ocupada incluso si el resultado es indeterminado.
    for _ in range(7):
        time.sleep(1.3)
        if foreground(adb, serial) is not True:
            return 'REVISAR', 'IMSS Digital salió de primer plano tras Iniciar sesión.'
        try:
            after = ui_dump(adb, serial)
        except Exception:
            continue
        if validation_detected(after):
            return 'ESPERANDO CÓDIGO', 'Inicio enviado; verifica identidad/código en IMSS Digital.'
    return 'REVISAR', 'Se pulsó Iniciar sesión; verifica si avanzó a validación.'
