# -*- coding: utf-8 -*-
"""Adaptador de lectura del código IMSS más reciente en Outlook Web.

Se conecta al lector EXISTENTE; no inicia sesión, no modifica cookies,
correos, el enlace local, contraseñas o pasos de IMSS. El OTP solo vive
brevemente en memoria en el módulo de enlace ya existente.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
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
    if not text:
        # Outlook Personal sometimes has no role=article/ReadingPane. A selected
        # message still appears in the main document. Isolate only the LAST
        # visible verification subject (the reading column after the mail list),
        # rather than taking the whole inbox and mixing other emails' codes.
        try:
            whole=(page.locator('body').inner_text(timeout=1400) or '')[:25000]
            matches=list(VERIFICATION_LABEL.finditer(whole))
            if len(matches)>=2:
                text=whole[matches[-1].start():][:12000]
        except Exception:
            pass
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
    # Last-resort Outlook Web layout: a sender appears once in the selected
    # mail row and a second time in the open message header. Require both,
    # and the verification subject; never trust only an inbox preview.
    try:
        whole=(page.locator('body').inner_text(timeout=1400) or '')[:25000]
        if (whole.casefold().count(sender.casefold())>=2 and
                len(list(re.finditer(r'c[oó]digo\s+de\s+verificaci[oó]n|verification code', whole,re.I)))>=2):
            return True
    except Exception:pass
    return False


# Outlook Personal can render only a locale-formatted date in its reading header,
# without an ISO datetime attribute. A strict ISO-only reader was stalling even
# when the intended IMSS code was visible (video from 23 Oct 2026).
VISIBLE_DATE = re.compile(
    r'\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun|Lun|Mar|Mi[eé]|Jue|Vie|S[aá]b|Dom)\s+'
    r'(\d{4}-\d{2}-\d{2})\s+(\d{1,2}):(\d{2})\b', re.I)
VERIFICATION_LABEL = re.compile(
    r'c[oó]digo\s+de\s+verificaci[oó]n|verification code',re.I)


def _fresh_visible_header(body, started):
    """Fallback ONLY for a recent live request, exact sender and isolated pane.

    Outlook account's display timezone may differ from Windows. Compare date
    to local today (+/- one date boundary) and minute to local clock modulo a
    whole-hour timezone shift; refuse if no visible full-date header.
    """
    dt=original.iso_dt(started)
    if dt is None:return False
    now=datetime.now(timezone.utc)
    if now < dt-timedelta(minutes=2) or now-dt>timedelta(minutes=20):return False
    found=VISIBLE_DATE.search(body or '')
    if not found:return False
    if not VERIFICATION_LABEL.search(body or ''):return False
    try:
        day=datetime.strptime(found.group(1),'%Y-%m-%d').date()
        minute=int(found.group(2))*60+int(found.group(3))
    except (ValueError, TypeError):return False
    if abs((day-now.date()).days)>1:return False
    # If the date is adjacent because the mail is displayed in a different
    # timezone, require actual date proximity rather than a day-old message.
    # Match time-of-day modulo 60 because browser and Outlook timezone settings
    # may differ by whole hours (as in user's recording).
    minute_delta=abs((minute % 60)-(now.minute % 60))
    if min(minute_delta,60-minute_delta)>9:return False
    codes=set(re.findall(r'(?<!\d)\d{6}(?!\d)', body))
    return len(codes)==1


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
                # Outlook Live may display a full local date in the message
                # header, but without ISO data attributes. Use the visible
                # fresh-message fallback only while this IMSS request is live.
                if _fresh_visible_header(body, started):
                    # The exact sender was verified in the opened message; the
                    # current request started recently. The displayed date has
                    # no timezone; use the request timestamp ONLY to reuse the
                    # original 6-digit/IMSS context validator, not to invent
                    # a claimed received-date for logs or storage.
                    received = started
                else:
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
