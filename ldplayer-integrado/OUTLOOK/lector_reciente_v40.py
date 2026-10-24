# -*- coding: utf-8 -*-
"""Lector Outlook V40. Correo IMSS de un solo uso por folio activo.
Valida remitente, asunto, un único OTP y una solicitud activa; cuando Outlook
no expone fecha técnica, el modo de cuentas nuevas sin reutilización utiliza
la primera coincidencia y evita cualquier segundo envío del mismo folio.
"""
from __future__ import annotations
import re
import os
import time
from diagnostico_v36 import record
from datetime import datetime, timezone, timedelta
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
    # Mensaje seleccionado en el dominio del buzón (no un formulario Microsoft).
    # Se valida de nuevo remitente, folio y OTP antes de depositar el código.
    if '/id/' in getattr(page,'url','').casefold():
        try:
            body=(page.locator('body').inner_text(timeout=1100) or '')[:6500]
            if SUBJECT.search(body) and _single_visible_otp(page):
                return True
        except Exception:pass
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


def _single_visible_otp(page):
    """Only accept one clearly visible six-digit OTP in the open page.

    Called *after* checking sender in the opened message, never on login pages.
    This fallback is for Outlook layouts whose reading pane has no ARIA role.
    """
    try:
        loc=page.get_by_text(re.compile(r'^\s*\d{6}\s*$'))
        values=set()
        for idx in range(min(loc.count(), 20)):
            item=loc.nth(idx)
            if not item.is_visible():
                continue
            value=(item.inner_text(timeout=900) or '').strip()
            if re.fullmatch(r'\d{6}',value):values.add(value)
        return next(iter(values)) if len(values)==1 else None
    except Exception:
        return None


def scan_open_imss_message(page, sender, started, ignore_ids):
    """Lector rápido del mensaje YA abierto; nunca consulta otras páginas.

    En Outlook Web el panel de lectura a veces no tiene ARIA de fila. En vez
    de pulsar repetidamente una fila que ya está abierta, se valida el
    remitente oficial y el OTP visible del mensaje seleccionado.
    """
    url=getattr(page,'url','')
    if not nav.is_outlook_mail_url(url):return None
    current=nav.iso_dt(started)
    if current is None:return None
    now=datetime.now(timezone.utc)
    if current>now+timedelta(minutes=2) or now-current>timedelta(minutes=15):return None
    # /id/ identifica el correo seleccionado por Outlook; si Outlook mantiene
    # /mail/inbox, es necesario que una fila se marque como seleccionada.
    selected='/id/' in url.casefold()
    if not selected:
        try:
            for selector in ('[aria-selected="true"]','[data-selected="true"]'):
                loc=page.locator(selector)
                if loc.count() and loc.first.is_visible():
                    selected=True;break
        except Exception:pass
    if not selected:return None
    if not _correct_sender(page,sender):
        _log_once('LECTURA ABIERTA: encabezado no confirma el remitente configurado',interval=5)
        return None
    code=_single_visible_otp(page)
    if not code:return None
    try:
        body=(page.locator('body').inner_text(timeout=1400) or '')[:25000]
    except Exception:return None
    if not SUBJECT.search(body):return None
    if not re.search(r'(?:tu\s+c[oó]digo\s+de\s+verificaci[oó]n\s+es|your\s+verification\s+code\s+is)',body,re.I):
        return None
    # Verificar que la OTP está dentro del texto abierto, sin inferir dígitos
    # de la bandeja, anuncios o la URL.
    if code not in body:return None
    key='seleccionado:'+url.split('?',1)[0]
    if key in ignore_ids:return None
    ignore_ids.add(key)
    _log_once('IMSS: mensaje seleccionado verificado; código detectado en pantalla',interval=0)
    return code


def scan_visible_inbox(page,sender,started,ignore_ids):
    if not nav.is_outlook_mail_url(getattr(page,'url','')):
        return None
    opened=scan_open_imss_message(page,sender,started,ignore_ids)
    if opened:return opened
    started_at=nav.iso_dt(started)
    if not sender or not started_at:
        return None
    now=datetime.now(timezone.utc)
    # El correo de un solo uso únicamente se inspecciona durante la solicitud actual.
    if started_at>now+timedelta(minutes=2) or now-started_at>timedelta(minutes=15):
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
                _log_once('V40: correo visible, pero remitente del mensaje aún no verificable')
                continue
            received,body=_message_data(page,row)
            if not body or not SUBJECT.search(body):
                # A few Outlook Web layouts expose the sender and subject but
                # do not expose the message itself through a ReadingPane role.
                # Use exactly one on-screen OTP after sender confirmation.
                visual=_single_visible_otp(page)
                if visual and SUBJECT.search(summary):
                    body='Código de Verificación\nTu código de verificación es: '+visual
                    _log_once('V40: código visto en mensaje abierto sin panel ARIA')
                else:
                    _log_once('V40: remitente confirmado; falta contenido verificable del mensaje')
                    continue
            if not received:
                if _fresh_visible_header(body,started):
                    # Fecha visible completa: validación normal del lector existente.
                    received=started
                else:
                    # MODO UN SOLO USO (solicitado): la cuenta nunca se reutiliza.
                    # Requiere solicitud activa reciente, mensaje abierto con
                    # remitente verificado y exactamente un OTP en contexto IMSS.
                    # No se supone que el correo tenga fecha verificable.
                    _log_once('IMSS V39: fecha técnica ausente; validando primer mensaje de cuenta de un solo uso')
                    received=started
            candidates=set(re.findall(r'(?<!\d)\d{6}(?!\d)',body))
            if len(candidates)!=1 or not SUBJECT.search(summary) or not SUBJECT.search(body):
                _log_once('V40: mensaje visible, pero código o asunto ambiguo; no enviar')
                continue
            code=nav.imss_code_from_message(sender,received,summary,body,sender,started)
            if code:
                _log_once('V40: OTP IMSS VALIDADO; transfiriendo al canal local (sin mostrar dígitos)')
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
