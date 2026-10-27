"""Read-only Outlook reader. Never submits credentials, follows links, or reads attachments."""

from datetime import datetime
from email.utils import parseaddr, parsedate_to_datetime
import hashlib
import re
import time
from urllib.parse import urlsplit, unquote
import unicodedata

ROW = '[role="option"], [role="row"], [data-app-section="MailList"] [data-item-id], [data-app-section="MailList"] [data-convid], [data-testid="message-list"] [data-message-id]'
PANE = '[data-app-section*="ReadPane"], [data-app-section*="ReadingPane"], [data-app-section="MailReadCompose"], #ReadingPaneContainerId, [aria-label="Reading pane"], [aria-label="Panel de lectura"], [class*="ReadingPane"], [class*="ReadPane"], [role="article"]'
HEADER = '[data-testid="message-header"], [data-app-section="MessageHeader"], [class*="MessageHeader"], [class*="messageHeader"], header'
IDENTITY = (
    "data-item-id",
    "data-message-id",
    "data-itemid",
    "data-messageid",
    "data-convid",
    "data-conversation-id",
)
DATE = ("datetime", "data-received-date", "data-receiveddatetime")
DATE_SELECTOR = "time[datetime], [data-received-date], [data-receiveddatetime], [title], [aria-label]"

# Read native Outlook chrome only. Message HTML, including iframe content, is
# excluded so a sender/date written inside a message cannot authenticate itself.
NATIVE_HEADER = """
const pane=arguments[0];
const body=pane.querySelector('#UniqueMessageBody')||pane.querySelector('[aria-label="Message body"], [aria-label="Cuerpo del mensaje"]')||pane.querySelector('[role="document"]')||pane.querySelector('.allowTextSelection')||pane.querySelector('iframe');
if(!body)return null;
const outside=n=>n.getClientRects().length&&getComputedStyle(n).visibility!=='hidden'&&n!==body&&!body.contains(n)&&!n.contains(body)&&
    Boolean(n.compareDocumentPosition(body)&Node.DOCUMENT_POSITION_FOLLOWING);
const nodes=Array.from(pane.querySelectorAll('[email],[data-email-address],[title],[aria-label],time,span,a[href^="mailto:"]')).filter(outside);
const addresses=[];const dates=[];
for(const n of nodes){
  const text=(n.textContent||'').trim();if(text.length<100&&/\\d{4}/.test(text))dates.push(text);
  if(n.matches('a[href^="mailto:"]'))addresses.push(n.getAttribute('href').slice(7).split('?')[0]);
  for(const a of ['email','data-email-address','title']){
    const v=(n.getAttribute(a)||'').trim();
    if(/^[^\\s<>@]+@[^\\s<>@]+\\.[^\\s<>@]+$/.test(v))addresses.push(v);
  }
  for(const a of ['datetime','data-received-date','data-receiveddatetime','title','aria-label']){
    const v=n.getAttribute(a);if(v&&v.length<200)dates.push(v);
  }
}
return {recognized:true,addresses:addresses.slice(0,8),dates:dates.slice(0,60)};
"""


def display_date(value):
    """Native Outlook calendar dates without ISO attributes; never message text."""
    if not isinstance(value, str):
        return None
    value = normalized(value).strip().replace("\u202f", " ")
    value = re.sub(
        r"^(?:mon(?:day)?|tue(?:sday)?|wed(?:nesday)?|thu(?:rsday)?|fri(?:day)?|sat(?:urday)?|sun(?:day)?|lunes|martes|miercoles|jueves|viernes|sabado|domingo)[,.]?\s+",
        "",
        value,
    )
    # A full calendar date is required; "17:10", "Sun 23:08" and relative
    # labels cannot establish which day an old message was received.
    formats = (
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d %H:%M:%S",
        "%m/%d/%Y %I:%M %p",
        "%m/%d/%Y %H:%M",
        "%B %d, %Y %I:%M %p",
        "%b %d, %Y %I:%M %p",
    )
    if re.match(r"(?:1[3-9]|2[0-9]|3[01])/", value):
        formats += ("%d/%m/%Y %H:%M", "%d/%m/%Y %I:%M %p")
    spanish = re.fullmatch(
        r"(\d{1,2}) de ([a-z]+) de (\d{4})[, ]+(\d{1,2}):(\d{2})", value
    )
    if spanish:
        day, month, year, hour, minute = spanish.groups()
        months = (
            "enero",
            "febrero",
            "marzo",
            "abril",
            "mayo",
            "junio",
            "julio",
            "agosto",
            "septiembre",
            "octubre",
            "noviembre",
            "diciembre",
        )
        try:
            return datetime(
                int(year), months.index(month) + 1, int(day), int(hour), int(minute)
            ).timestamp(), 60
        except ValueError:
            return None
    for fmt in formats:
        try:
            date = datetime.strptime(value, fmt)
            return date.timestamp(), 1 if "%S" in fmt else 60
        except ValueError:
            pass
    return None


def normalized(text):
    value = unicodedata.normalize("NFKC", str(text)).casefold()
    return "".join(
        c
        for c in unicodedata.normalize("NFD", value)
        if not unicodedata.combining(c) and unicodedata.category(c) != "Cf"
    )


def extract_code(text):
    """Accept one contextual six-digit code; quoted older replies never contribute."""
    value = normalized(text).replace("\u00a0", " ")
    value = re.split(
        r"\n\s*(?:from:|de:|el .+escribio:|on .+wrote:|[-_]{4,}\s*original)",
        value,
        maxsplit=1,
    )[0]
    label = r"(?:\bcodigo(?:\s+(?:de\s+)?(?:validacion|verificacion|confirmacion|seguridad|acceso))?|\bverification\s+code|\bsecurity\s+code|\bone.time\s+(?:code|password))"
    matches = re.findall(
        label
        + r"[^0-9]{0,100}(?<![a-z0-9])((?:[0-9][ \t\r\n-]*){5}[0-9])(?![a-z0-9])(?![ \t\r\n-]*[0-9])",
        value,
    )
    codes = {re.sub(r"[^0-9]", "", item) for item in matches}
    return next(iter(codes)) if len(codes) == 1 else None


def timestamp(value):
    if not value or not isinstance(value, str):
        return None
    try:
        if re.fullmatch(r"\d{10}(?:\.\d+)?|\d{13}", value):
            return float(value) / (1000 if len(value) == 13 else 1)
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.timestamp() if parsed.tzinfo else None
    except ValueError:
        try:
            parsed = parsedate_to_datetime(value)
            return parsed.timestamp() if parsed.tzinfo else None
        except (ValueError, TypeError, OverflowError):
            return None


def identity(element):
    for name in IDENTITY:
        value = element.get_attribute(name)
        if isinstance(value, str) and value:
            return value
    return None


def correlated(row, pane):
    """Compare matching native ID types; conversation and message IDs differ."""
    compared = []
    for name in IDENTITY:
        left, right = row.get_attribute(name), pane.get_attribute(name)
        if isinstance(left, str) and left and isinstance(right, str) and right:
            compared.append(left == right)
    return any(compared) if compared else None


def visible(elements):
    result = []
    for element in elements:
        try:
            if element.is_displayed():
                result.append(element)
        except Exception as error:
            if type(error).__name__ not in (
                "StaleElementReferenceException",
                "NoSuchElementException",
            ):
                raise
    return result


class OutlookReader:
    def __init__(
        self,
        driver,
        sender="",
        subject="",
        cancelled=None,
        report=None,
        expected_curp="",
    ):
        self.driver, self.sender = driver, sender.strip().casefold()
        self.subject = normalized(subject.strip())
        self.automatic = not self.sender and not self.subject
        self.expected_curp = normalized(expected_curp.strip())
        self.cancelled = cancelled or (lambda: False)
        self.report = report or (lambda text: None)
        self.seen = set()
        self.baseline_ids = set()
        self.last_diagnostic = "Preparando referencia de la bandeja."
        self._diagnostic_at = 0
        self.transient_errors = 0
        self.initial_view = None
        self.require_received_date = False
        self.baselined_views = set()
        self.date_precision = {}

    def inbox_tabs(self):
        tabs = {}
        for tab in visible(self.driver.find_elements("css selector", '[role="tab"]')):
            name = normalized(tab.text.strip())
            if name in ("focused", "prioritarios", "other", "otros"):
                tabs[name] = tab
        return tabs if len(tabs) == 2 else {}

    def selected_view(self, tabs):
        return next(
            (
                name
                for name, tab in tabs.items()
                if tab.get_attribute("aria-selected") == "true"
            ),
            None,
        )

    def diagnostic(self, text):
        changed = text != self.last_diagnostic
        self.last_diagnostic = text
        if changed and time.monotonic() - self._diagnostic_at >= 3:
            self._diagnostic_at = time.monotonic()
            self.report(
                text
            )  # fixed messages only: never send body, code or sender headers

    def rows(self):
        url = urlsplit(self.driver.current_url)
        if url.hostname != "outlook.live.com" or not url.path.startswith("/mail"):
            raise RuntimeError("La bandeja de Outlook ya no está abierta.")
        result, deduplicated = [], set()
        for row in visible(self.driver.find_elements("css selector", ROW))[:120]:
            key = identity(row)
            if not key or key in deduplicated:
                continue
            deduplicated.add(key)
            preview = row.text
            # Relative times and read/unread styles may change: they do not prove new mail.
            date_marker = repr(self.dates(row))
            marker = (
                key
                + ":"
                + hashlib.sha256(
                    (normalized(preview) + date_marker).encode()
                ).hexdigest()
            )
            result.append((marker, row, preview))
        return result

    def baseline(self):
        rows = self.rows()
        if not rows:
            containers = visible(
                self.driver.find_elements(
                    "css selector",
                    '[role="listbox"], [data-app-section="MailList"], [aria-label="Message list"], [aria-label="Lista de mensajes"]',
                )
            )
            if not containers:
                raise RuntimeError(
                    "No se pudo reconocer la lista de mensajes; IMSS no se iniciará."
                )
        self.seen = {marker for marker, _, _ in rows}
        self.baseline_ids = {identity(row) for _, row, _ in rows}
        self.initial_view = self.selected_view(self.inbox_tabs())
        self.baselined_views = {self.initial_view} if self.initial_view else set()
        tabs = self.inbox_tabs()
        if self.initial_view and tabs:
            try:
                for name, tab in tabs.items():
                    if name == self.initial_view or self.cancelled():
                        continue
                    tab.click()
                    deadline = time.monotonic() + 2
                    previous = None
                    while not self.cancelled():
                        rows = self.rows()
                        markers = {marker for marker, _, _ in rows}
                        if self.selected_view(self.inbox_tabs()) == name:
                            self.seen.update(markers)
                            self.baseline_ids.update(
                                identity(row) for _, row, _ in rows
                            )
                            if markers == previous:
                                self.baselined_views.add(name)
                                break
                            previous = markers
                        if time.monotonic() >= deadline:
                            raise RuntimeError(
                                "No se pudo confirmar la referencia de ambas pestañas de Outlook."
                            )
                        time.sleep(0.2)
            finally:
                tabs[self.initial_view].click()
        self.diagnostic("Bandeja reconocida; referencia anterior al código guardada.")

    def native_header(self, pane):
        execute = getattr(self.driver, "execute_script", None)
        if execute:
            result = execute(NATIVE_HEADER, pane)
            if (
                isinstance(result, dict)
                and isinstance(result.get("addresses"), list)
                and isinstance(result.get("dates"), list)
            ):
                return result
        return {"recognized": False, "addresses": [], "dates": []}

    def dates(self, element, children=True):
        nodes = [element] + (
            visible(element.find_elements("css selector", DATE_SELECTOR))
            if children
            else []
        )
        values = [
            timestamp(node.get_attribute(attr)) for node in nodes for attr in DATE
        ]
        for node in nodes:
            for attr in ("title", "aria-label"):
                parsed = display_date(node.get_attribute(attr))
                if parsed:
                    value, precision = parsed
                    values.append(value)
                    self.date_precision[value] = precision
        return [value for value in values if value is not None]

    def sender_address(self, pane):
        headers = visible(pane.find_elements("css selector", HEADER))
        container = headers[0] if headers else pane
        senders = visible(
            container.find_elements("css selector", "[email], [data-email-address]")
        )
        if senders:
            # First address in native message header is the sender; never match recipients.
            return {
                parseaddr(senders[0].get_attribute(attr) or "")[1].casefold()
                for attr in ("email", "data-email-address")
            } - {""}
        if headers:
            links = visible(
                container.find_elements("css selector", 'a[href^="mailto:"]')
            )
            if links:
                address = unquote(links[0].get_attribute("href")[7:]).split("?", 1)[0]
                return {parseaddr(address)[1].casefold()}
        return set()

    def body(self, pane):
        text = pane.text
        # Outlook sometimes places its message body in a separate iframe.
        for frame in visible(pane.find_elements("css selector", "iframe"))[:3]:
            if self.cancelled():
                return ""
            try:
                self.driver.switch_to.frame(frame)
                bodies = visible(self.driver.find_elements("tag name", "body"))
                if bodies:
                    text += "\n" + bodies[0].text
            finally:
                self.driver.switch_to.default_content()
        return text

    def inspect(self, row, pane, started):
        row_id = identity(row)
        same_message = correlated(row, pane)
        if same_message is False:
            self.diagnostic("Esperando que el panel muestre el mensaje seleccionado.")
            return None
        headers = visible(pane.find_elements("css selector", HEADER))
        metadata = self.native_header(pane)
        dates = (
            []
            if metadata.get("recognized")
            else self.dates(headers[0])
            if headers
            else self.dates(pane, children=False)
        )
        if not dates:
            for raw in metadata["dates"]:
                if not isinstance(raw, str):
                    continue
                stamp = timestamp(raw)
                parsed = (stamp, 1) if stamp is not None else display_date(raw)
                if parsed:
                    value, precision = parsed
                    dates.append(value)
                    self.date_precision[value] = precision
        if not dates:
            dates = self.dates(row)
        received = max(dates) if dates else None
        if self.require_received_date and received is None:
            self.diagnostic(
                "La vista alternativa necesita una fecha verificable del mensaje nuevo."
            )
            return None
        if received is not None and (
            (
                received < started
                and not (
                    row_id not in self.baseline_ids
                    and self.date_precision.get(received) == 60
                    and received + 60 > started
                )
            )
            or received > time.time() + 120
        ):
            self.diagnostic(
                "Mensaje anterior a la solicitud o fecha no válida; esperando otro."
            )
            return None
        if row_id in self.baseline_ids and received is None:
            return None  # changed previews on old conversations are not new messages
        if received is None and same_message is not True:
            self.diagnostic(
                "Outlook no expone aún la fecha o identidad del mensaje abierto."
            )
            return None
        addresses = set() if metadata.get("recognized") else self.sender_address(pane)
        if not addresses:
            addresses = {
                parseaddr(unquote(v))[1].casefold()
                for v in metadata["addresses"][:1]
                if isinstance(v, str)
            }
        body = self.body(pane)
        if self.automatic:
            official = any(
                address.rsplit("@", 1)[-1] == "imss.gob.mx"
                or address.rsplit("@", 1)[-1].endswith(".imss.gob.mx")
                for address in addresses
            )
            branded = bool(
                re.search(
                    r"\bimss\b|instituto mexicano del seguro social", normalized(body)
                )
            )
            matches_curp = bool(
                self.expected_curp and self.expected_curp in normalized(body)
            )
            if not official and not (branded and matches_curp):
                self.diagnostic(
                    "No se pudo comprobar el remitente de la cabecera de Outlook."
                    if not addresses
                    else "Esperando el mensaje nuevo de validación del IMSS."
                )
                return None
            # If a CURP is present, it must be the active request's CURP.
            mentioned = set(
                re.findall(
                    r"\b[a-z]{4}[0-9]{6}[hm][a-z]{5}[a-z0-9][0-9]\b", normalized(body)
                )
            )
            if self.expected_curp and mentioned and self.expected_curp not in mentioned:
                return None
        elif self.sender not in addresses:
            self.diagnostic(
                "El remitente visible no coincide; sigo esperando el correo del IMSS."
            )
            return None
        if self.subject and self.subject not in normalized(pane.text):
            return None
        code = extract_code(body)
        self.diagnostic(
            "Código nuevo comprobado para la solicitud activa."
            if code
            else "Mensaje abierto; esperando un código único de seis dígitos."
        )
        return code

    def scan(self, started):
        if self.cancelled():
            return None
        try:
            tabs = self.inbox_tabs()
            selected = self.selected_view(tabs)
            self.require_received_date = bool(
                self.initial_view
                and selected
                and selected != self.initial_view
                and selected not in self.baselined_views
            )
            for marker, row, preview in self.rows():
                if self.cancelled():
                    return None
                candidate = (
                    bool(
                        re.search(
                            r"codigo|verification code|security code",
                            normalized(preview),
                        )
                    )
                    if self.automatic
                    else self.subject in normalized(preview)
                )
                if marker in self.seen or not candidate:
                    continue
                if identity(row) in self.baseline_ids:
                    dates = self.dates(row)
                    if not dates or max(dates) < started:
                        continue
                # Retain candidates with a partially loaded body for the next poll.
                row.click()
                end = time.monotonic() + 1.5
                while not self.cancelled():
                    for pane in visible(
                        self.driver.find_elements("css selector", PANE)
                    ):
                        code = self.inspect(row, pane, started)
                        if code:
                            self.seen.add(marker)
                            self.transient_errors = 0
                            return code
                    if time.monotonic() >= end:
                        break
                    time.sleep(0.15)
            self.transient_errors = 0
            if tabs and selected and not self.cancelled():
                next(tab for name, tab in tabs.items() if name != selected).click()
                self.diagnostic(
                    "Revisando también la otra pestaña de la bandeja, sin abrir enlaces del mensaje."
                )
            return None
        except Exception as error:
            if type(error).__name__ in (
                "StaleElementReferenceException",
                "NoSuchElementException",
                "ElementClickInterceptedException",
            ):
                self.transient_errors += 1
                self.diagnostic("Outlook está actualizando la vista; volveré a leerla.")
                if self.transient_errors <= 8:
                    return None
            raise
