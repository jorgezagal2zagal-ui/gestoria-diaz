# -*- coding: utf-8 -*-
"""Adaptador de lectura del código IMSS más reciente en Outlook Web.

Se conecta al lector EXISTENTE; no inicia sesión, no modifica cookies,
correos, el enlace local, contraseñas o pasos de IMSS. El OTP solo vive
brevemente en memoria en el módulo de enlace ya existente.
"""
from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import re

import navegador as original

# Dos variantes de interfaz de Outlook; no se inspeccionan otras páginas.
ROW_SELECTORS = (
    '[role="option"]', '[data-convid]', '[data-item-id]',
    '[data-testid="message-row"]', '[data-testid="messageListItem"]',
    '[role="row"]',
)
PANE_SELECTORS = (
    original.READ_PANE + ', '
    '[data-testid="readingPane"], [data-testid="reading-pane"], '
    '[aria-label="Panel de lectura"], [aria-label="Reading pane"], '
    '[data-app-section="MessageReadingPane"]'
)
CANDIDATE = re.compile(r'\bIMSS\b|instituto mexicano del seguro social|'
                       r'c[oó]digo\s+de\s+(?:validaci[oó]n|verificaci[oó]n)|'
                       r'semanas\s+cotizadas', re.I)
DATE_SELECTORS = (
    'time[datetime], [data-received-date], [data-receiveddatetime], '
    '[data-time], [data-timestamp], [data-date], [title], [datetime]'
)
DATE_ATTRIBUTES = (
    'datetime', 'data-received-date', 'data-receiveddatetime',
    'data-time', 'data-timestamp', 'data-date', 'title'
)


def _iso_utc(value):
    if not value:
        return None
    value=str(value).strip()
    if len(value)>100:
        return None
    parsed=original.iso_dt(value)
    if parsed is not None:
        return parsed.isoformat()
    try:
        parsed=parsedate_to_datetime(value)
        if parsed.tzinfo is not None:
            return parsed.astimezone(timezone.utc).isoformat()
    except (ValueError, TypeError, IndexError, OverflowError):
        pass
    return None


def _containers(page):
    try:
        loc=page.locator(PANE_SELECTORS)
        for i in range(min(loc.count(),20)):
            pane=loc.nth(i)
            if pane.is_visible():yield pane
    except Exception:
        return


def _freshest_rows(page):
    """Outlook muestra el correo más nuevo arriba; no escanea otros sitios."""
    seen=set()
    for selector in ROW_SELECTORS:
        try:
            rows=page.locator(selector)
            matched=[]
            for i in range(min(rows.count(),45)):
                row=rows.nth(i)
                if not row.is_visible():continue
                summary=(row.inner_text(timeout=1100) or '')[:800]
                if not CANDIDATE.search(summary):continue
                key=(row.get_attribute('data-item-id') or
                     row.get_attribute('data-convid') or summary[:180]).strip()
                if key not in seen:
                    matched.append((key,row,summary));seen.add(key)
            # Orden natural de Outlook: arriba está el más reciente.
            if matched:
                yield from matched
                return
        except Exception:
            continue


def _message_data(page, row):
    """Solo admite datos de la lectura del mensaje abierto y su misma fila."""
    panes=list(_containers(page))
    text=''
    for pane in panes:
        try:
            candidate=pane.inner_text(timeout=1800)
            if len(candidate)>len(text):text=candidate[:16000]
        except Exception:
            continue
    if not text:
        text=original._open_message_text(page)
    received=original._received_timestamp(page)
    if received:return received,text
    for container in [*panes,row]:
        try:
            dates=container.locator(DATE_SELECTORS)
            for i in range(min(dates.count(),50)):
                loc=dates.nth(i)
                if not loc.is_visible():continue
                for attr in DATE_ATTRIBUTES:
                    received=_iso_utc(loc.get_attribute(attr))
                    if received:return received,text
        except Exception:
            pass
        for attr in DATE_ATTRIBUTES:
            try:
                received=_iso_utc(container.get_attribute(attr))
                if received:return received,text
            except Exception:
                pass
    return None,text


def _correct_sender(page,sender):
    if original._visible_sender_in_message(page,sender):return True
    # Interfaz Outlook nueva: remitente en panel de lectura con un enlace mailto.
    for pane in _containers(page):
        try:
            links=pane.locator('a[href^="mailto:"]')
            for i in range(min(links.count(),12)):
                link=links.nth(i)
                if link.is_visible() and (link.get_attribute('href') or '').split('?',1)[0][7:].casefold()==sender.casefold():
                    return True
        except Exception:
            continue
    return False


def scan_visible_inbox(page,sender,started,ignore_ids):
    """Lee el primer correo IMSS de la lista, solo si es de ESTA solicitud.

    Valida cuenta (en BrowserLogin), remitente exacto, recepción posterior,
    contexto IMSS y único código de 6 cifras. Nunca usa correos antiguos;
    si Outlook aún no muestra fecha verificable vuelve a intentarlo.
    """
    if not original.is_outlook_mail_url(getattr(page,'url','')):
        return None
    if not sender or not original.iso_dt(started):return None
    for key,row,summary in _freshest_rows(page):
        if key in ignore_ids:continue
        try:
            row.click(timeout=4500)
            page.wait_for_timeout(350)
            if not _correct_sender(page,sender):
                ignore_ids.add(key)
                continue
            received,body=_message_data(page,row)
            if not received:
                # No ignorar de manera irreversible: Outlook puede cargar el
                # encabezado y su fecha después de abrir la lectura.
                return 'fecha_no_verificable'
            # Si el cuerpo contiene distintos códigos de seis dígitos,
            # no elegir uno arbitrariamente aunque aparezca cerca de «código».
            candidates=set(re.findall(r"(?<!\d)\d{6}(?!\d)",body))
            if len(candidates)>1:
                ignore_ids.add(key)
                return None
            code=original.imss_code_from_message(sender,received,summary,body,sender,started)
            if code:
                ignore_ids.add(key)
                return code
            # Si es correo IMSS viejo, no reciclarlo; esperar el reciente.
            ignore_ids.add(key)
        except Exception:
            continue
    return None
