"""Lector estricto: cuenta, remitente estructurado, fecha real y un único código."""
from datetime import datetime, timezone, timedelta
import re
import time
from urllib.parse import unquote
import navegador_v28 as nav
from lector_reciente_v40 import _candidate_rows, SUBJECT
from lector_reciente_v29 import _containers

ACCOUNT_SELECTORS = (
    '#O365_MainLink_Me', '[data-testid="accountManagerButton"]',
    '[data-testid="account-manager-button"]',
    'button[aria-label*="Account manager" i]',
    'button[aria-label*="Administrador de cuentas" i]',
    '#mectrl_currentAccount_primary', '[data-testid="account-email"]',
    '[data-testid="me-control-current-account"]',
)
SENDER_SELECTORS = (
    '[data-testid="sender"]', '[data-testid="message-sender"]',
    '[data-testid="SenderPersona"]',
    '[data-testid="message-header"] [email]',
    '[data-app-section*="MessageHeader"] [email]',
    '[aria-label^="De:"]', '[aria-label^="From:"]',
)
DATE_SELECTOR = 'time[datetime], [data-received-date], [data-receiveddatetime]'


def exact_email(value, expected):
    return bool(re.search(r'(?<![\w.+@-])' + re.escape(expected) + r'(?![\w.+@-])', value or '', re.I))


def mailbox_identity_verified(page, email):
    if not nav.is_outlook_mail_url(getattr(page, 'url', '')):return False
    for selector in ACCOUNT_SELECTORS:
        try:
            controls = page.locator(selector)
            for i in range(min(controls.count(), 8)):
                item = controls.nth(i)
                if not item.is_visible():continue
                for attr in ('aria-label', 'title', 'data-email', 'data-upn'):
                    if exact_email(item.get_attribute(attr), email):return True
                if exact_email(item.inner_text(timeout=700), email):return True
        except Exception:continue
    return False


def inbox_verified(page):
    from lector_reciente_v38 import compact_inbox_verified
    if not compact_inbox_verified(page):return False
    if '/inbox' in str(getattr(page, 'url', '')).casefold():return True
    try:
        headings = page.get_by_role('heading', name=re.compile(r'^(?:Bandeja de entrada|Inbox)$', re.I))
        return any(headings.nth(i).is_visible() for i in range(min(headings.count(), 5)))
    except Exception:return False


def validate_message(sender, received, subject, body, expected_sender, started, now=None):
    if not expected_sender or sender.casefold() != expected_sender.casefold():return None
    start = nav.iso_dt(started)
    date = nav.iso_dt(received)
    now = now or datetime.now(timezone.utc)
    if not start or not date or date < start or date > now + timedelta(seconds=30):return None
    if start > now or now - start > timedelta(minutes=15):return None
    if not SUBJECT.search(subject or '') or not SUBJECT.search(body or ''):return None
    codes = set(re.findall(r'(?<![0-9])[0-9]{6}(?![0-9])', body or ''))
    return next(iter(codes)) if len(codes) == 1 else None


def _sender(pane, expected):
    for selector in SENDER_SELECTORS:
        try:
            items = pane.locator(selector)
            for i in range(min(items.count(), 12)):
                item = items.nth(i)
                if not item.is_visible():continue
                for attr in ('email', 'data-email-address', 'data-email', 'title', 'aria-label'):
                    if exact_email(item.get_attribute(attr), expected):return expected
                links = item.locator('a[href^="mailto:"]')
                for j in range(min(links.count(), 5)):
                    link = links.nth(j)
                    address = unquote((link.get_attribute('href') or '')[7:].split('?', 1)[0])
                    if link.is_visible() and address.casefold() == expected.casefold():return expected
        except Exception:continue
    return None


def _received(pane):
    try:
        dates = pane.locator(DATE_SELECTOR)
        values = set()
        for i in range(min(dates.count(), 20)):
            item = dates.nth(i)
            if not item.is_visible():continue
            for attr in ('datetime', 'data-received-date', 'data-receiveddatetime'):
                value = nav.iso_dt(item.get_attribute(attr))
                if value:values.add(value.isoformat())
        # Varios mensajes de una conversación no se mezclan.
        return next(iter(values)) if len(values) == 1 else None
    except Exception:return None


def scan_visible_inbox(page, sender, started, ignore_ids):
    if not nav.is_outlook_mail_url(getattr(page, 'url', '')) or not nav.iso_dt(started):return None
    for key, row, summary in _candidate_rows(page, sender):
        if key in ignore_ids or not SUBJECT.search(summary):continue
        try:
            row.click(timeout=3500)
            page.wait_for_timeout(400)
            panes = list(_containers(page))
            for pane in panes:
                actual_sender = _sender(pane, sender)
                received = _received(pane)
                if not actual_sender or not received:continue
                body = pane.inner_text(timeout=1500) or ''
                code = validate_message(actual_sender, received, summary, body, sender, started)
                if code:
                    ignore_ids.add(key)
                    return code
            # No marcar como ignorado un mensaje que todavía se esté cargando.
        except Exception:continue
    return None
