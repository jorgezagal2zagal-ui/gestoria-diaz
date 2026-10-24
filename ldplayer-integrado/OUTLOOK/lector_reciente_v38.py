# -*- coding: utf-8 -*-
"""Corrección Outlook web compacto: localizar la fila del IMSS, abrirla
antes de leer y volver a intentar si el panel aún está cargando.

No modifica los controles de seguridad: el código se transmite solamente
tras comprobar remitente, fecha y una solicitud activa en el enlace local.
"""
from __future__ import annotations
import re
import os
import time
from diagnostico_v36 import record
from lector_reciente_v29 import (
    _freshest_rows as _rows_v29, _correct_sender, _message_data,
    _fresh_visible_header, _containers, CANDIDATE,
)
import navegador_v28 as nav

# Las páginas de Outlook personal pueden no exponer una fila ARIA. En ese caso
# el elemento de texto del asunto es el punto más estable para abrir el mensaje.
_LAST_LOG={}

def _log_once(event,interval=14):
    slot=int(os.environ.get('GD_WORKER_SLOT','1'))
    k=(slot,event)
    now=time.monotonic()
    if now-_LAST_LOG.get(k,0)>=interval:
        _LAST_LOG[k]=now
        try:record(slot,event)
        except Exception:pass

SUBJECT = re.compile(r'c[oó]digo\s+de\s+(?:verificaci[oó]n|validaci[oó]n)', re.I)
READY_WORDS = re.compile(r'\b(?:new\s+mail|nuevo\s+correo|correo\s+nuevo|focused|prioritarios|otros|other)\b', re.I)


def compact_inbox_verified(page):
    if not nav.is_outlook_mail_url(getattr(page, 'url', '')):
        return False
    if _original_inbox_verified(page):
        return True
    # Outlook con barra lateral compactada oculta la palabra Inbox. Exigimos
    # simultáneamente URL Outlook + controles de correo y una lista visible.
    try:
        body=(page.locator('body').inner_text(timeout=1400) or '')[:6500]
        if nav.RATE_LIMIT_TEXT.search(body) or nav.CHALLENGE.search(body):
            return False
        if not READY_WORDS.search(body):
            return False
        for css in ('[role="main"]', '[role="listbox"]',
                    '[data-app-section="Mail"]', '[data-testid="messageList"]',
                    '[role="option"]', '[data-convid]', '[data-item-id]'):
            try:
                target=page.locator(css)
                if target.count() and target.first.is_visible():
                    return True
            except Exception:
                continue
    except Exception:
        pass
    return False


# Guardar la función original ANTES de parchear navegador_v28.
_original_inbox_verified = nav.inbox_ui_verified


def _text_rows(page, sender):
    """Fallback a los textos visibles del asunto, sin leer otros sitios."""
    try:
        loc=page.get_by_text(SUBJECT)
        count=min(loc.count(),24)
    except Exception:
        return
    seen=set()
    for idx in range(count):
        try:
            item=loc.nth(idx)
            if not item.is_visible():
                continue
            target=item
            summary=(item.inner_text(timeout=900) or '').strip()
            # En la lista compacta remitente y asunto son nodos hermanos.
            # No ascender hasta el cuerpo entero ni abrir mensajes ajenos.
            for depth in range(4):
                if sender.casefold() in summary.casefold() and len(summary)<1200:
                    break
                target=target.locator('xpath=..')
                candidate=(target.inner_text(timeout=850) or '').strip()
                if len(candidate)>1200:
                    break
                summary=candidate
            if not SUBJECT.search(summary):
                continue
            # El remitente puede mostrarse reducido en la lista, pero siempre
            # será verificado estrictamente en el mensaje abierto.
            key=(target.get_attribute('data-item-id') or
                 target.get_attribute('data-convid') or summary[:180]).strip()
            if key and key not in seen:
                seen.add(key)
                yield key, target, summary
        except Exception:
            continue


def _candidate_rows(page,sender):
    """Primero selectores actuales, después asunto visible sin rol ARIA."""
    seen=set()
    for key,row,summary in _rows_v29(page):
        if key not in seen:
            seen.add(key)
            yield key,row,summary
    for key,row,summary in _text_rows(page,sender):
        if key not in seen:
            yield key,row,summary


def scan_visible_inbox(page,sender,started,ignore_ids):
    if not nav.is_outlook_mail_url(getattr(page,'url','')):
        return None
    if not sender or not nav.iso_dt(started):
        return None
    candidates=list(_candidate_rows(page,sender))
    if not candidates:
        _log_once('LECTURA IMSS: no hay una fila visible del asunto de verificación')
    for key,row,summary in candidates:
        if key in ignore_ids:
            continue
        try:
            _log_once('LECTURA IMSS: encontré el asunto y pulsé el mensaje')
            row.click(timeout=4500)
            page.wait_for_timeout(450)
            # Si el mensaje no se abrió (pane aún mostrando 'Select an item'
            # o se está cargando), reintentar luego; NO ignorarlo para siempre.
            if not _correct_sender(page,sender):
                _log_once('LECTURA IMSS: el panel del correo aún no muestra el remitente')
                continue
            received,body=_message_data(page,row)
            if not body or not SUBJECT.search(body):
                _log_once('LECTURA IMSS: esperando cuerpo del correo en el panel')
                continue
            if not received:
                if _fresh_visible_header(body,started):
                    received=started
                else:
                    _log_once('LECTURA IMSS: correo abierto, falta fecha verificable')
                    return 'fecha_no_verificable'
            candidates=set(re.findall(r'(?<!\d)\d{6}(?!\d)',body))
            if len(candidates)>1:
                # Mensaje abierto ambiguo: no utilizar ningún código.
                return None
            code=nav.imss_code_from_message(sender,received,summary,body,sender,started)
            if code:
                _log_once('LECTURA IMSS: código válido; enviando al enlace local')
                ignore_ids.add(key)
                return code
            # Ignorar únicamente el mensaje ABIERTO que no sea de la solicitud;
            # así uno antiguo no bloquea la llegada de uno nuevo.
            ignore_ids.add(key)
        except Exception as exc:
            _log_once('LECTURA IMSS: reintentar clic; fallo '+type(exc).__name__)
            # Playwright puede fallar mientras Outlook reorganiza la lista.
            # Reintentar después, sin perder el mensaje activo.
            continue
    return None
