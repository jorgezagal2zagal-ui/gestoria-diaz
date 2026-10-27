"""Conservative, read-only code reader for the already authenticated Outlook page."""
from datetime import datetime
from email.utils import parseaddr
import hashlib
import re
import time
from urllib.parse import urlsplit
import unicodedata


ROW = '[role="option"], [data-item-id], [data-convid], [role="row"]'
PANE = '[data-app-section*="ReadPane"], [data-app-section*="ReadingPane"], [class*="ReadingPane"], [class*="ReadPane"], [role="article"]'


def normalized(text):
    return ''.join(c for c in unicodedata.normalize('NFD', text.casefold()) if not unicodedata.combining(c))


def extract_code(text):
    matches = re.findall(r'(?:codigo(?:\s+de\s+(?:validacion|verificacion|confirmacion|seguridad))?|verification code)'
                         r'[^0-9]{0,100}((?:[0-9][ \t\r\n]*){6})(?![ \t\r\n]*[0-9])', normalized(text))
    codes = {re.sub(r'\s', '', value) for value in matches}
    return next(iter(codes)) if len(codes) == 1 else None


class OutlookReader:
    def __init__(self, driver, sender, subject):
        self.driver, self.sender = driver, sender.strip().casefold()
        self.subject = normalized(subject.strip())
        self.seen = set()

    def rows(self):
        if urlsplit(self.driver.current_url).hostname != 'outlook.live.com':
            raise RuntimeError('La bandeja de Outlook ya no está abierta.')
        result = []
        for row in self.driver.find_elements('css selector', ROW)[:80]:
            if not row.is_displayed():
                continue
            identity = row.get_attribute('data-item-id') or row.get_attribute('data-convid')
            if not identity:
                continue         # los índices visuales o IDs temporales no prueban un mensaje nuevo
            preview = row.text
            marker = identity + ':' + hashlib.sha256(preview.encode()).hexdigest()
            result.append((marker, row, preview))
        return result

    def baseline(self):
        self.seen = {marker for marker, _, _ in self.rows()}

    def scan(self, started):
        for marker, row, preview in self.rows():
            if marker in self.seen or self.subject not in normalized(preview):
                continue
            row.click()
            time.sleep(.4)
            for pane in self.driver.find_elements('css selector', PANE):
                if not pane.is_displayed():
                    continue
                opened_id = pane.get_attribute('data-item-id') or pane.get_attribute('data-convid')
                row_id = row.get_attribute('data-item-id') or row.get_attribute('data-convid')
                if opened_id and opened_id != row_id:
                    continue          # el panel todavía muestra otro mensaje
                # Use native sender metadata, not a sender name or address in the body.
                senders = pane.find_elements('css selector', '[email], [data-email-address]')
                visible_senders = [node for node in senders if node.is_displayed()]
                # The sender is the first native address in the opened message's
                # header; recipient addresses later in the header are not senders.
                addresses = {parseaddr(visible_senders[0].get_attribute(attr) or '')[1].casefold()
                             for attr in ('email', 'data-email-address')} if visible_senders else set()
                if self.sender not in addresses:
                    if addresses and opened_id == row_id:
                        self.seen.add(marker)
                    continue
                # A verifiable date, when exposed by Outlook, must belong to this request.
                dates = pane.find_elements('css selector', 'time[datetime], [data-received-date], [data-receiveddatetime]')
                timestamps = []
                for node in dates:
                    for attr in ('datetime', 'data-received-date', 'data-receiveddatetime'):
                        value = node.get_attribute(attr)
                        if value:
                            try:
                                parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
                                if parsed.tzinfo:
                                    timestamps.append(parsed.timestamp())
                            except ValueError:
                                pass
                if timestamps and max(timestamps) < started:
                    if opened_id == row_id:
                        self.seen.add(marker)
                    continue
                if not timestamps and opened_id != row_id:
                    continue          # no atribuir el cuerpo de un panel todavía desactualizado
                if self.subject not in normalized(pane.text):
                    continue
                code = extract_code(pane.text)
                self.seen.add(marker)
                if code:
                    return code
        return None
