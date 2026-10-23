# -*- coding: utf-8 -*-
"""Acceso asistido a Outlook. Abre directamente el login oficial Microsoft.
Nunca introduce credenciales en sitios ajenos a los hosts de inicio de Microsoft.
Las verificaciones de identidad quedan a cargo del titular.
"""
from __future__ import annotations
import re
import sys
import threading
import time
import unicodedata
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse, urlsplit, urlunsplit, quote, parse_qsl

ALLOWED_AUTH_HOSTS = {
    'login.live.com', 'login.microsoftonline.com', 'account.live.com',
    'login.microsoft.com', 'account.microsoft.com'
}
MAIL_HOSTS = {'outlook.live.com', 'outlook.office.com'}
# La portada de Microsoft 365 puede abrirse antes de la página de acceso.
MARKETING_HOSTS = {'www.microsoft.com', 'microsoft.com'}
SIGN_IN_TEXT = re.compile(r'\b(?:iniciar sesi[oó]n|inicia sesi[oó]n|sign\s*in|log\s*in|entrar)\b', re.I)
OUTLOOK_WEB_URL = 'https://outlook.live.com/mail/'
OUTLOOK_LOGIN_LANDING = 'https://login.live.com/login.srf'
STAY_SIGNED_IN = re.compile(r'(?:[q¿]?uieres\s+mantener\s+la\s+sesi[oó]n\s+iniciada|stay\s+signed\s+in)', re.I)
IMSS_WORDS = re.compile(r'(?:\bIMSS\b|semanas\s+cotizadas|c[oó]digo\s+de\s+(?:validaci[oó]n|verificaci[oó]n))', re.I)

# Facilita a Microsoft la cuenta ya elegida sin omitir validaciones ni enviar datos a terceros.
LOGIN_HINT_HOSTS = {'login.microsoftonline.com', 'login.live.com'}
# Official Microsoft selectors are checked by priority, not one broad CSS query.
# React pages sometimes keep a hidden legacy field while rendering the real one.
EMAIL_PRIORITY = (
    '#i0116', '#usernameEntry',
    'input[name="loginfmt"]', 'input[name="username"]',
    'input[autocomplete="username"]', 'input[type="email"]',
    'input[placeholder*="Correo electrónico" i]',
    'input[placeholder*="email" i]',
)

PASSWORD_OPTION = re.compile(
    r'(?:usar|utilizar|escribir)(?:\s+(?:mi|tu|la))?\s+contraseñ?a|'
    r'iniciar\s+sesi[oó]n\s+con\s+(?:mi\s+|la\s+)?contraseñ?a|'
    r'use\s+(?:your|a|my)\s+password|'
    r'sign\s+in\s+with\s+(?:your\s+|a\s+)?password', re.I)
PASSWORD_INPUT = '#i0118, input[name="passwd"], input[type="password"], input[autocomplete="current-password"]'
EMAIL_INPUT = (
    '#i0116, #usernameEntry, input[name="loginfmt"], input[name="username"], '
    'input[name="email"], input[name="login"], input[name="identifier"], '
    'input[autocomplete="username"], input[autocomplete="email"], '
    'input[aria-label*="correo" i], input[aria-label*="email" i], '
    'input[aria-label*="skype" i], input[placeholder*="correo" i], '
    'input[placeholder*="email" i], input[placeholder*="skype" i]'
)
SUBMIT = ('#idSIButton9, #identifierNext, #passwordNext, '
          '#primaryButton, button[data-testid="primaryButton"], '
          'button[type="submit"], input[type="submit"]')
RATE_LIMIT_TEXT = re.compile(
    r'(?i)(?:\btoo\s+many\s+requests\b|\b(?:http\s*)?429\b|\bdemasiadas\s+solicitudes\b)'
)
PASSWORD_RETRY_DELAYS = (5, 10)
PASSWORD_UNAVAILABLE_TEXT = re.compile(
    r'\b(?:inicio\s+de\s+sesion|iniciar\s+sesion|acceso)\s+con\s+'
    r'(?:(?:la|tu|una)\s+)?contrasena\s+(?:actualmente\s+)?no\s+'
    r'(?:esta\s+)?disponible\b|'
    r'\b(?:password\s+(?:sign[ -]?in|login)|sign[ -]?in\s+with\s+'
    r'(?:(?:a|your)\s+)?password)\s+(?:is\s+)?(?:currently\s+|temporarily\s+)?'
    r'(?:unavailable|not\s+available)\b|'
    r'\bpassword\s+(?:sign[ -]?in|login)\s+isn[\x27\u2019]t\s+'
    r'(?:currently\s+)?available\b|'
    r'\bno\s+se\s+puede\s+iniciar\s+sesion\s+con\s+(?:una\s+|la\s+)?'
    r'contrasena\s+en\s+este\s+momento\b', re.I)


def is_microsoft_rate_limited(page):
    """Identifica el rechazo visible de Microsoft, sin reintentar ni eludir límites.

    No interpreta una redirección normal como bloqueo; debe aparecer un
    aviso explícito de límite en el contenido de una página Microsoft.
    """
    if not trusted_login_url(getattr(page, 'url', '')):
        return False
    try:
        body = page.locator('body').inner_text(timeout=1200)
        return bool(RATE_LIMIT_TEXT.search(body[:1500]))
    except Exception:
        return False


CHALLENGE = re.compile(
    r'Verifica tu correo|Verify your email|Ayúdanos a proteger|'
    r'Help us protect|Verifica tu identidad|Approve sign in|'
    r'Ingresa (?:tu |el )?c[oó]digo|Enter (?:the |your )?code', re.I)


def trusted_login_url(url):
    parsed = urlparse(url)
    return parsed.scheme == 'https' and (parsed.hostname or '').lower() in ALLOWED_AUTH_HOSTS


def is_password_signin_unavailable(page):
    """Solo el aviso visible de acceso con contraseña no disponible, en Microsoft."""
    if not trusted_login_url(getattr(page, 'url', '')) or is_passkey_enrollment_url(page.url):
        return False
    try:
        body = page.locator('body').inner_text(timeout=1200)[:12000]
    except Exception:
        return False
    # Las verificaciones y los límites tienen prioridad sobre la recuperación.
    if RATE_LIMIT_TEXT.search(body) or CHALLENGE.search(body):
        return False
    normalized = ''.join(c for c in unicodedata.normalize('NFKD', body)
                         if not unicodedata.combining(c))
    return bool(PASSWORD_UNAVAILABLE_TEXT.search(normalized))


def is_passkey_enrollment_url(url):
    return trusted_login_url(url) and bool(re.search(r'/fido/create/?$',urlparse(url).path,re.I))



def with_official_login_hint(url, email):
    """Añade login_hint SOLO en el endpoint OAuth oficial de Microsoft.

    La sugerencia de cuenta es una opción documentada de Microsoft OAuth;
    no autentica ni sustituye los pasos de verificación.
    """
    parts=urlsplit(url)
    if parts.scheme!='https' or (parts.hostname or '').lower() not in LOGIN_HINT_HOSTS:
        return url
    if not (parts.path.lower().endswith('/authorize') or parts.path.lower().endswith('/authorize/')):
        return url
    # Evitar duplicar la sugerencia, no alterar otros parámetros OAuth.
    if any(k.lower()=='login_hint' for k,_ in parse_qsl(parts.query,keep_blank_values=True)):
        return url
    query=parts.query+'&login_hint='+quote(email,safe='') if parts.query else 'login_hint='+quote(email,safe='')
    return urlunsplit((parts.scheme,parts.netloc,parts.path,query,parts.fragment))


def install_login_hint(context, email, on_status):
    """Microsoft puede usar login_hint para mostrar el correo precargado.

    La redirección se limita a HTTPS y los dos hosts de inicio Microsoft.
    No toca contraseñas, cookies, OTP ni enlaces ajenos.
    """
    applied={'done':False}
    def handler(route):
        try:
            old=route.request.url
            new=with_official_login_hint(old,email)
            if new!=old:
                if not applied['done']:
                    on_status('Microsoft recibe la sugerencia oficial de correo al abrir el inicio de sesión.')
                    applied['done']=True
                route.continue_(url=new)
                return
        except Exception:
            pass
        route.continue_()
    context.route('**/authorize*',handler)


def is_outlook_mail_url(url):
    parsed = urlparse(url)
    return (parsed.scheme == 'https' and (parsed.hostname or '').lower() in MAIL_HOSTS
            and parsed.path.lower().startswith('/mail'))


def is_account_dashboard(page):
    """Portada de cuenta después de autenticar; excluye páginas de seguridad."""
    parsed=urlparse(page.url)
    if (parsed.scheme!='https' or parsed.hostname!='account.microsoft.com'
            or parsed.path.rstrip('/') not in ('','/account','/profile','/home')):
        return False
    try:
        body=page.locator('body').inner_text(timeout=1200)
        return not (CHALLENGE.search(body) or RATE_LIMIT_TEXT.search(body))
    except Exception:
        return False


def is_marketing_url(url):
    parsed = urlparse(url)
    return parsed.scheme == 'https' and (parsed.hostname or '').lower() in MARKETING_HOSTS


def click_marketing_signin(page):
    """Abre el inicio de sesión oficial desde una portada Microsoft.

    Microsoft carga botones de forma asíncrona. Esta función es de un solo
    intento; el bucle externo vuelve a probar si aún no aparece el botón.
    """
    if not is_marketing_url(page.url):
        return False
    for role in ('link', 'button'):
        try:
            actions = page.get_by_role(role, name=SIGN_IN_TEXT)
            for index in range(min(actions.count(), 20)):
                action = actions.nth(index)
                if not action.is_visible():
                    continue
                # Los botones de navegación internos sólo pueden continuar a
                # páginas legítimas de Microsoft, no a proveedores externos.
                if role == 'link':
                    href = action.get_attribute('href')
                    if href:
                        target = urlparse(href)
                        if target.scheme and (target.scheme != 'https' or
                              target.hostname not in (
                                ALLOWED_AUTH_HOSTS | MARKETING_HOSTS |
                                MAIL_HOSTS | {'go.microsoft.com'})):
                            continue
                action.click(timeout=6000)
                return True
        except Exception:
            continue
    try:
        action = page.get_by_text(SIGN_IN_TEXT).first
        if action.is_visible():
            action.click(timeout=6000)
            return True
    except Exception:
        pass
    return False


def find_password_option(page):
    return page.locator('a, button, [role="button"]', has_text=PASSWORD_OPTION).first


def wait_for_password_or_challenge(page, stop_event, on_status, seconds=30):
    deadline = time.monotonic() + seconds
    switched = False
    while time.monotonic() < deadline and not stop_event.is_set():
        if is_outlook_mail_url(page.url):
            return 'mail'
        if not trusted_login_url(page.url):
            on_status('Microsoft cambió de dirección; se detuvo el relleno automático por seguridad.')
            return 'untrusted'
        pwd = page.locator(PASSWORD_INPUT).first
        try:
            if pwd.count() and pwd.is_visible():
                return 'password'
        except Exception:
            pass
        if not switched:
            try:
                option = find_password_option(page)
                if option.count() and option.is_visible():
                    option.click(timeout=4000)
                    switched = True
                    on_status('Microsoft ofreció «Usar la contraseña» y el bot seleccionó esa opción.')
                    continue
            except Exception:
                pass
        time.sleep(.4)
    if not stop_event.is_set():
        on_status('Microsoft solicita verificación u otro paso. Complétalo en el navegador; no se omite.')
    return 'challenge'


class BrowserLaunchError(RuntimeError):
    """Fallo de arranque con ayuda estática, sin credenciales ni excepciones crudas."""


def browser_candidates(p):
    """En Windows reutiliza Edge/Chrome instalados dentro de un contexto privado."""
    args = ['--incognito', '--no-first-run', '--no-default-browser-check', '--disable-sync',
            '--disable-features=PasswordManagerOnboarding,AutofillServerCommunication,msEdgeSidebarV2',
            '--disable-save-password-bubble']
    chromium=('Chromium privado', lambda: p.chromium.launch(headless=False, args=args,timeout=15000))
    chrome=('Google Chrome privado', lambda: p.chromium.launch(channel='chrome', headless=False, args=args,timeout=15000))
    edge_args=[arg for arg in args if arg!='--incognito']+['--inprivate']
    edge=('Microsoft Edge privado', lambda: p.chromium.launch(channel='msedge', headless=False, args=edge_args,timeout=15000))
    return [chromium,chrome,edge]


def launch_private_browser(p, on_status):
    problems = []
    for name, start in browser_candidates(p):
        try:
            on_status('Abriendo '+name+'…')
            browser = start()
            on_status('MODO INCÓGNITO: ' + name + '. Sesión temporal independiente, sin sincronizar perfiles.')
            if name.startswith('Microsoft Edge'):
                on_status('Si Edge muestra su asistente de sincronización, elige «No, gracias». No es una verificación de Outlook.')
            return browser
        except Exception as exc:
            problems.append(name + ': ' + type(exc).__name__)
    raise BrowserLaunchError('No se pudo abrir Edge, Chrome ni Chromium. Ejecuta INSTALAR.bat y vuelve a pulsar INICIAR.')


def visible_control(page, selector):
    """Busca controles solamente en formularios oficiales de Microsoft."""
    if selector == EMAIL_INPUT:
        field,frame,_ = locate_email_input(page)
        return field,frame
    for frame in [page.main_frame, *[f for f in page.frames if f != page.main_frame]]:
        try:
            # Nunca llenar un formulario de un iframe de un dominio ajeno a Microsoft.
            if frame.url and not trusted_login_url(frame.url):
                continue
            fields=frame.locator(selector)
            for i in range(min(fields.count(), 8)):
                field=fields.nth(i)
                if field.is_visible() and field.is_enabled():
                    return field, frame
        except Exception:
            pass
    return None, None


# Names used by the current and earlier Microsoft personal-account sign-in screens.
USERNAME_LABEL = re.compile(
    r'correo(?:\s+electr[oó]nico)?|email|e-mail|tel[eé]fono|phone|skype|'
    r'cuenta\s+(?:de\s+)?microsoft|sign[- ]?in\s+name',re.I)
NOT_USERNAME = re.compile(r'c[oó]digo|verification|one[- ]?time|otp|pin|captcha|'
                          r'authenticator|seguridad|security|recuperaci[oó]n|recovery',re.I)
NEXT_TEXT = re.compile(r'^(?:siguiente|continuar|next|continue|iniciar sesi[oó]n|sign in|entrar)$',re.I)


def trusted_auth_frame(frame, page):
    """Check the frame origin. about:blank inherits an official auth parent."""
    if trusted_login_url(frame.url):
        return True
    if frame.url in ('about:blank',''):
        parent=frame.parent_frame
        return (trusted_auth_frame(parent,page) if parent else trusted_login_url(page.url))
    return False


def auth_frames(page):
    return [f for f in [page.main_frame,*[f for f in page.frames if f!=page.main_frame]]
            if trusted_auth_frame(f,page)]


def _is_safe_username_field(field):
    """Avoid filling verification/recovery codes, even if the name changes."""
    try:
        kind=(field.get_attribute('type') or 'text').lower()
        if kind not in ('text', 'email', 'tel', 'search'):
            return False
        attrs=' '.join(str(field.get_attribute(k) or '') for k in
            ('id','name','placeholder','aria-label','autocomplete','data-testid',
             'inputmode','aria-describedby'))
        return not NOT_USERNAME.search(attrs)
    except Exception:
        return False


def locate_email_input(page):
    """Locate the visible email input inside an official Microsoft frame.

    Microsoft sometimes renders several identical (hidden) copies of the
    login form. Looking for a *single* combined selector can pick a hidden
    legacy textbox ahead of the editable textbox the user can see.
    """
    for frame in auth_frames(page):
        # Prefer the EXACT known Microsoft sign-in identifiers. Evaluate
        # every visible match rather than relying on the first DOM element.
        for selector in EMAIL_PRIORITY:
            try:
                items=frame.locator(selector)
                for i in range(min(items.count(),16)):
                    field=items.nth(i)
                    if (field.is_visible() and field.is_enabled()
                            and _is_safe_username_field(field)):
                        return field,frame,'campo Microsoft: '+selector
            except Exception:
                continue
        # Broader locale/attribute selectors are used only as fallbacks.
        try:
            items=frame.locator(EMAIL_INPUT)
            for i in range(min(items.count(),20)):
                field=items.nth(i)
                if (field.is_visible() and field.is_enabled()
                        and _is_safe_username_field(field)):
                    return field,frame,'selector alternativo'
        except Exception:
            pass
        try:
            field=frame.get_by_role('textbox',name=USERNAME_LABEL).first
            if field.count() and field.is_visible() and field.is_enabled():
                return field,frame,'etiqueta'
        except Exception:
            pass
        # Newer Microsoft login variants use custom IDs. The field must look
        # like a username and NOT like a secondary code verification field.
        try:
            inputs=frame.locator('input')
            for i in range(min(inputs.count(),20)):
                field=inputs.nth(i)
                if not field.is_visible() or not field.is_enabled(): continue
                kind=(field.get_attribute('type') or 'text').lower()
                if kind not in ('text','email','tel'): continue
                attrs=' '.join(str(field.get_attribute(k) or '') for k in
                    ('id','name','placeholder','aria-label','autocomplete','data-testid'))
                if USERNAME_LABEL.search(attrs) and not NOT_USERNAME.search(attrs):
                    return field,frame,'atributos'
        except Exception:
            pass
    # Microsoft sometimes shows a textbox without identifying attributes.
    # Only accept a *single* visible, editable text field on the official
    # Microsoft sign-in page, with a sign-in heading and no code challenge.
    # This intentionally refuses to fill arbitrary single fields (e.g. OTP).
    for frame in auth_frames(page):
        try:
            headings=frame.locator('h1, h2, [role="heading"]')
            titles=' '.join((headings.nth(i).inner_text(timeout=900) or '')
                            for i in range(min(headings.count(),8)))
            if not re.search(r'iniciar sesi[oó]n|sign in|inicia sesi[oó]n', titles, re.I):
                continue
            if re.search(r'c[oó]digo|code|verifica|verify|identidad|identity|authenticator', titles,re.I):
                continue
            items=frame.locator('input')
            candidates=[]
            for i in range(min(items.count(),25)):
                f=items.nth(i)
                if not f.is_visible() or not f.is_enabled(): continue
                typ=(f.get_attribute('type') or 'text').lower()
                if typ not in ('text','email','tel'):continue
                attrs=' '.join(str(f.get_attribute(k) or '') for k in
                     ('id','name','placeholder','aria-label','autocomplete','data-testid','inputmode'))
                if NOT_USERNAME.search(attrs): continue
                candidates.append(f)
            if len(candidates)==1:
                return candidates[0],frame,'campo único de inicio'
        except Exception:
            continue
    # Microsoft sometimes generates a login input with no name/id and no
    # accessible heading. Accept the ONLY editable text input when the
    # body explicitly shows the username prompt and is NOT an OTP page.
    for frame in auth_frames(page):
        try:
            body=(frame.locator('body').inner_text(timeout=1200) or '')[:1600]
            if not re.search(r'correo electr[oó]nico|tel[eé]fono o skype|email, phone|email or phone',body,re.I):
                continue
            if re.search(r'c[oó]digo de verificaci[oó]n|enter (?:the |your )?code|security code|authenticator',body,re.I):
                continue
            fields=frame.locator('input[type="text"],input[type="email"],input:not([type])')
            eligible=[]
            for i in range(min(fields.count(),12)):
                f=fields.nth(i)
                if not f.is_visible() or not f.is_enabled():continue
                attrs=' '.join(str(f.get_attribute(k) or '') for k in ('id','name','placeholder','aria-label','autocomplete'))
                if NOT_USERNAME.search(attrs):continue
                eligible.append(f)
            if len(eligible)==1:
                return eligible[0],frame,'campo único (respaldo)'
        except Exception:
            continue
    return conservative_username_fallback(page)



def conservative_username_fallback(page):
    """Para formularios de login Microsoft sin selectores clásicos.

    Solo si hay exactamente un campo de texto editable y el sitio muestra
    las palabras del paso de identificación; nunca en pantalla de códigos.
    """
    for frame in auth_frames(page):
        try:
            body=(frame.locator('body').inner_text(timeout=1300) or '')[:2400]
            if NOT_USERNAME.search(body) and re.search(r'verifica|verification|c[oó]digo de seguridad|one.time|authenticator',body,re.I):
                continue
            if not re.search(r'iniciar sesi[oó]n|sign in|correo electr[oó]nico|email, phone|skype',body,re.I):
                continue
            inputs=frame.locator('input:visible')
            valid=[]
            for idx in range(min(inputs.count(),16)):
                fld=inputs.nth(idx)
                if fld.is_enabled() and _is_safe_username_field(fld):
                    valid.append(fld)
            if len(valid)==1:
                return valid[0],frame,'único campo visible'
        except Exception:
            pass
    return None,None,'sin coincidencia'


def input_value_matches(field,email):
    try:
        return field.input_value(timeout=2000).strip().casefold()==email.strip().casefold()
    except Exception:
        return False


def write_email_reliably(field,email,on_status):
    """Write only in a located username input, using normal page keyboard.

    Retry if React or the Microsoft form rejects a direct Playwright fill.
    Never send keystrokes to arbitrary browser chrome/desktop controls.
    """
    attempts = ('fill','click_and_type','click_and_insert')
    for method in attempts:
        try:
            if input_value_matches(field,email):
                return True
            field.scroll_into_view_if_needed(timeout=1500)
            if method=='fill':
                field.fill(email,timeout=3500)
            elif method=='click_and_type':
                field.click(timeout=2500)
                field.press('ControlOrMeta+A',timeout=1600)
                field.press('Backspace',timeout=1600)
                field.press_sequentially(email,delay=25,timeout=8000)
            else:
                field.click(timeout=2500)
                field.press('ControlOrMeta+A',timeout=1600)
                field.press('Backspace',timeout=1600)
                # input event is dispatched by Playwright, not OS-level input.
                field.press_sequentially(email,delay=60,timeout=10000)
            # React can recreate the input between fill and inspection. Wait
            # briefly for the value to settle before trying a slower method.
            for _ in range(5):
                if input_value_matches(field,email):
                    if method!='fill':
                        on_status('Correo ingresado usando el teclado original del navegador.')
                    return True
                time.sleep(.12)
        except Exception as exc:
            on_status('Microsoft aún no aceptó el correo ('+type(exc).__name__+'); reintentando.')
    if js_input_event_fallback(field,email):
        on_status('El correo quedó escrito con eventos de formulario Microsoft.')
        return True
    return False



def js_input_event_fallback(field, email):
    """Último respaldo cuando Microsoft crea un control React no estándar.

    Actúa exclusivamente sobre el input de usuario ya identificado.
    Dispara eventos de input/change que usan las interfaces SPA.
    """
    try:
        field.evaluate("""(el, value) => {
          if (!(el instanceof HTMLInputElement)) return;
          el.focus();
          const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set;
          setter.call(el,value);
          el.dispatchEvent(new InputEvent('input',{bubbles:true,inputType:'insertText',data:value}));
          el.dispatchEvent(new Event('change',{bubbles:true}));
        }""",email,timeout=3000)
        return input_value_matches(field,email)
    except Exception:
        return False


def submit_form(page, frame, on_status, input_field=None):
    """Click Continue on Microsoft's auth form; fall back to Enter."""
    for selector in (SUBMIT,):
        try:
            controls=frame.locator(selector)
            for i in range(min(controls.count(),8)):
                item=controls.nth(i)
                if item.is_visible() and item.is_enabled():
                    item.click(timeout=5000)
                    return True
        except Exception:
            pass
    try:
        controls=frame.get_by_role('button',name=NEXT_TEXT)
        for i in range(min(controls.count(),8)):
            item=controls.nth(i)
            if item.is_visible() and item.is_enabled():
                item.click(timeout=5000)
                return True
    except Exception:
        pass
    # Some Microsoft forms have no semantic button. Enter submits that form.
    if input_field is not None:
        try:
            input_field.press('Enter',timeout=5000)
            on_status('Microsoft no mostró Siguiente como botón estándar; se pulsó Enter.')
            return True
        except Exception:
            pass
    on_status('Campo completado, pero no se encontró Siguiente. Dejo el formulario abierto.')
    return False


def fill_email_step(page,email,on_status):
    if not trusted_login_url(page.url):
        return 'notfound'
    field,frame,method=locate_email_input(page)
    if field is None:
        return 'notfound'
    on_status('Campo de correo detectado en Microsoft. Escribiendo…')
    if not write_email_reliably(field,email,on_status):
        on_status('El correo sigue vacío o diferente. Verifica la ventana de Microsoft y pulsa REINTENTAR CORREO.')
        return 'mismatch'
    on_status('Correo escrito y comprobado en Microsoft ('+method+').')
    return 'submitted' if submit_form(page,frame,on_status,field) else 'needs_click'


def describe_login_fields(page):
    """Safe diagnostic: field types, not entered values or passwords."""
    found=[]
    for frame in auth_frames(page):
        try:
            fields=frame.locator('input')
            for i in range(min(fields.count(),15)):
                item=fields.nth(i)
                if item.is_visible():
                    t=str(item.get_attribute('type') or 'text')[:20]
                    name=str(item.get_attribute('name') or item.get_attribute('id') or '')[:35]
                    found.append(t+':'+name)
        except Exception:
            pass
    status=', '.join(found[:8]) or 'sin campos visibles'
    return status+'; marcos reconocidos: '+str(len(auth_frames(page)))


def choose_account_tile(page, email):
    """Selecciona una cuenta SOLO si coincide exactamente con la indicada."""
    try:
        tile=page.get_by_text(email,exact=True).first
        if tile.count() and tile.is_visible():
            tile.click(timeout=4000)
            return True
    except Exception:
        pass
    return False


def choose_other_account(page):
    """Si Microsoft muestra un selector de cuentas, revela el formulario nuevo."""
    options=re.compile(r'usar otra cuenta|use another account|iniciar sesi[oó]n con otra cuenta|otra cuenta', re.I)
    try:
        target=page.get_by_text(options).first
        if target.count() and target.is_visible():
            target.click(timeout=4000)
            return True
    except Exception:
        pass
    return False


def try_password_choice(page):
    try:
        choice=find_password_option(page)
        if choice.count() and choice.is_visible():
            choice.click(timeout=4000)
            return True
    except Exception:
        pass
    return False




def click_no_keep_session(page):
    """Solo pulsa 'No' en el cuadro exacto de Microsoft, no en avisos genéricos."""
    if not trusted_login_url(page.url):
        return False
    try:
        headings=page.get_by_text(STAY_SIGNED_IN)
        if not any(headings.nth(i).is_visible() for i in range(min(headings.count(),5))):
            return False
        controls=page.get_by_role('button',name=re.compile(r'^\s*(?:No|Not now)\s*$',re.I))
        for i in range(min(controls.count(),5)):
            button=controls.nth(i)
            if button.is_visible() and button.is_enabled():
                button.click(timeout=5500)
                return True
        # Algunos cuadros anteriores usan input[type=submit] con value No.
        for sel in ('input[type="submit"][value="No"]', 'input#idBtn_Back'):
            el=page.locator(sel)
            if el.count() and el.first.is_visible():
                el.first.click(timeout=5500)
                return True
    except Exception:
        return False
    return False


def iso_dt(value):
    try:
        dt=datetime.fromisoformat(str(value).replace('Z','+00:00'))
        if dt.tzinfo is None:return None
        return dt.astimezone(timezone.utc)
    except (TypeError,ValueError):
        return None


def imss_code_from_message(sender, received, subject, body, expected_sender, started):
    """Validación estricta: remitente exacto, después de la solicitud, 6 dígitos."""
    if not expected_sender or sender.strip().casefold()!=expected_sender.strip().casefold():
        return None
    received_dt=iso_dt(received)
    started_dt=iso_dt(started)
    if received_dt is None or started_dt is None or received_dt < started_dt-timedelta(minutes=1):
        return None
    combined=(subject or '')+'\n'+(body or '')
    if not IMSS_WORDS.search(combined):return None
    patterns=[
        r'(?:c[oó]digo\s+(?:de\s+)?(?:validaci[oó]n|verificaci[oó]n|confirmaci[oó]n)|'
        r'c[oó]digo|clave)\s*(?:es|:|\-|=)?\s*([0-9]{6})(?![0-9])',
        r'(?<![0-9])([0-9]{6})(?![0-9])',
    ]
    for pattern in patterns:
        codes=re.findall(pattern,combined,re.I)
        if len(set(codes))==1 and codes:return codes[0]
        if len(set(codes))>1:return None
    return None


def visible_inbox_rows(page):
    """Elementos de lista típicos de Outlook; no lee otros sitios."""
    if not is_outlook_mail_url(page.url):return []
    found=[]
    seen=set()
    for selector in ('[role="option"]','[data-convid]','[data-item-id]','[role="row"]'):
        try:
            rows=page.locator(selector)
            for idx in range(min(rows.count(),80)):
                row=rows.nth(idx)
                if not row.is_visible():continue
                content=(row.inner_text(timeout=900) or '')[:600]
                if not IMSS_WORDS.search(content):continue
                marker=(content[:180],idx,selector)
                if marker not in seen:
                    found.append((row,content)); seen.add(marker)
            if found:break
        except Exception:
            continue
    return found


READ_PANE = ('[data-app-section*="ReadPane" i], [data-app-section*="ReadingPane" i], '
             '[class*="ReadingPane"], [class*="ReadPane"], [role="article"]')


def _read_panes(page):
    """En Outlook solo usamos el mensaje abierto (no otra fila del buzón)."""
    panes=[]
    try:
        loc=page.locator(READ_PANE)
        for i in range(min(loc.count(),12)):
            candidate=loc.nth(i)
            if candidate.is_visible():panes.append(candidate)
    except Exception:
        pass
    return panes


def _visible_sender_in_message(page, sender):
    """Verifica el remitente del mensaje abierto, sin aceptar filas adyacentes."""
    if not sender:return False
    for pane in _read_panes(page):
        try:
            candidates=pane.get_by_text(sender,exact=False)
            if any(candidates.nth(i).is_visible() for i in range(min(candidates.count(),12))):
                return True
        except Exception:
            continue
    return False


def _received_timestamp(page):
    """Fecha ISO comprobable de mensaje ABIERTO, nunca de filas de la bandeja."""
    for pane in _read_panes(page):
        try:
            dates=pane.locator('time[datetime], [data-received-date], [data-receiveddatetime]')
            for i in range(min(dates.count(),20)):
                loc=dates.nth(i)
                if not loc.is_visible():continue
                for attr in ('datetime','data-received-date','data-receiveddatetime'):
                    value=loc.get_attribute(attr)
                    if iso_dt(value):return value
        except Exception:
            continue
    return None


def _open_message_text(page):
    for pane in _read_panes(page):
        try:
            body=pane.inner_text(timeout=3000)
            if len(body)>20:return body[:16000]
        except Exception:
            continue
    return ''


def scan_visible_inbox(page, sender, started, ignore_ids):
    """Busca candidatos NUEVOS en la bandeja usando solo controles visibles.

    No se envía si no se puede verificar el remitente y la fecha. Devuelve un
    único código; ante ambigüedad, el usuario puede usar el campo manual.
    """
    if not is_outlook_mail_url(page.url) or not sender or not iso_dt(started):return None
    for row, summary in visible_inbox_rows(page):
        try:
            identity=(row.get_attribute('data-item-id') or row.get_attribute('data-convid') or summary[:250])
            if identity in ignore_ids:continue
            row.click(timeout=4500)
            page.wait_for_timeout(500)
            # Aun si el contenido de la lista es engañoso, se exige remitente
            # visible y fecha comprobable en el mensaje ABIERTO.
            if not _visible_sender_in_message(page,sender):
                ignore_ids.add(identity);continue
            received=_received_timestamp(page)
            if not received:
                # No usar códigos antiguos con fecha no verificable.
                ignore_ids.add(identity)
                return 'fecha_no_verificable'
            body=_open_message_text(page)
            result=imss_code_from_message(sender, received,summary,body,sender,started)
            ignore_ids.add(identity)
            if result:return result
        except Exception:
            continue
    return None


class BrowserLogin:
    def __init__(self, callback, request_supplier=None, deliver_code=None):
        self.callback=callback
        self.request_supplier=request_supplier
        self.deliver_code=deliver_code
        self.sender=""
        self.scanned_ids=set()
        self.last_scan=0.0
        self.last_scan_request=None
        self._last_missing_sender=None
        self.stop_event=threading.Event()
        self.retry_requested=threading.Event()
        self.reopen_requested=threading.Event()
        self.open_mail_requested=threading.Event()
        self.running=False
        self.rate_limited=False
        self.phase='idle'
        self.last_error=''
        self.browser_opened=threading.Event()
        self.pending_code=None
        self._last_read_error=0.0

    def start(self, email, password):
        if self.running:
            raise RuntimeError('Ya hay una ventana de inicio abierta.')
        self.stop_event.clear()
        self.rate_limited=False
        self.retry_requested.clear()
        self.reopen_requested.clear()
        self.open_mail_requested.clear()
        self.scanned_ids.clear()
        self.last_scan_request=None
        self._last_missing_sender=None
        self.running=True
        self.phase='starting'
        self.last_error=''
        self.browser_opened.clear()
        self.pending_code=None
        try:
            threading.Thread(target=self._worker,args=(email,password),daemon=True).start()
        except Exception:
            self.running=False
            self.phase='error'
            self.last_error='No se pudo iniciar el proceso del navegador. Cierra el programa y vuelve a abrirlo.'
            raise

    def set_sender(self, sender):
        self.sender=(sender or "").strip().lower()

    def stop(self):
        self.stop_event.set()

    def retry_email(self):
        if self.rate_limited:
            self._emit('Microsoft limitó los intentos. Cierra la sesión privada y espera a que permita intentar de nuevo.')
            return
        if not self.running:
            self._emit('Primero abre la ventana de Outlook en incógnito.')
            return
        self.retry_requested.set()
        self._emit('Voy a buscar el campo de correo en la ventana de Microsoft y rellenarlo.')

    def reopen_form(self):
        """Solicita recargar la entrada oficial en el MISMO contexto privado."""
        if self.rate_limited:
            self._emit('No volveré a solicitar Microsoft: Too Many Requests. Cierra y espera antes de probar nuevamente.')
            return
        if not self.running:
            self._emit('Primero abre Outlook en incógnito.')
            return
        self.reopen_requested.set()
        self._emit('Volveré a abrir el formulario oficial de Microsoft dentro de la misma sesión privada.')

    def open_mail(self):
        """Abrir Outlook en el mismo contexto privado después de autenticarse."""
        if self.rate_limited:
            self._emit('Microsoft está limitando solicitudes. No abriré más páginas en esta sesión.')
            return
        if not self.running:
            self._emit('Primero inicia sesión en Microsoft en modo incógnito.')
            return
        self.open_mail_requested.set()
        self._emit('Abriré la bandeja de Outlook en la misma ventana privada.')

    def _emit(self, message):
        self.callback(message)

    def _restart_password_signin(self, context, page, attempt):
        """Reemplaza solo la pestaña fallida; conserva cuenta, contexto y cookies."""
        delay = PASSWORD_RETRY_DELAYS[attempt - 1]
        self._emit('Microsoft indica que el inicio con contraseña no está disponible. '
                   'Cerraré esa pestaña y abriré otra en '+str(delay)+' segundos '
                   '(reintento '+str(attempt)+'/'+str(len(PASSWORD_RETRY_DELAYS))+').')
        try:
            page.close(run_before_unload=False)
        except Exception as exc:
            self._emit('No se pudo cerrar la pestaña ('+type(exc).__name__+
                       '). Recuperación automática detenida; revisa el navegador.')
            return None
        # Espera interrumpible: DETENER no abre otra pestaña después de cancelar.
        if self.stop_event.wait(delay):
            return None
        try:
            replacement = context.new_page()
        except Exception as exc:
            self._emit('No se pudo abrir otra pestaña ('+type(exc).__name__+
                       '). Recuperación automática detenida.')
            return None
        if self.stop_event.is_set():
            return None
        try:
            replacement.goto(OUTLOOK_LOGIN_LANDING, wait_until='domcontentloaded', timeout=22000)
        except Exception as exc:
            # Una redirección lenta puede dejar un formulario funcional abierto.
            self._emit('El nuevo formulario tarda en cargar ('+type(exc).__name__+
                       '). Revisaré la pestaña abierta antes de continuar.')
        return replacement

    def _check_inbox(self, page, email):
        if not self.request_supplier or not self.deliver_code:
            return
        now=time.monotonic()
        if now-self.last_scan<8:return
        self.last_scan=now
        try: request=self.request_supplier()
        except Exception:return
        if not isinstance(request,dict) or request.get('status')!='ESPERANDO_CODIGO':
            self.pending_code=None
            return
        if str(request.get('email') or '').casefold()!=email.casefold():
            self.pending_code=None
            self._emit('La solicitud IMSS corresponde a otro correo; no leeré códigos de esta cuenta.')
            return
        sender=self.sender
        if not sender or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',sender):
            if self._last_missing_sender!=request.get('request_id'):
                self._emit('Para buscar el código automáticamente, configura una vez el remitente exacto de IMSS en el panel.')
                self._last_missing_sender=request.get('request_id')
            return
        request_id=request.get('request_id')
        if not request_id:return
        if self.last_scan_request!=request_id:
            self.scanned_ids=set()
            self.last_scan_request=request_id
            self.pending_code=None
        result=self.pending_code or scan_visible_inbox(page,sender,request.get('started'),self.scanned_ids)
        if result=='fecha_no_verificable':
            self._emit('Encontré un posible correo IMSS, pero Outlook no mostró la fecha verificable. Usa el código manualmente.')
        elif result:
            self.pending_code=result
            try:
                self.deliver_code(request_id,result,email)
                self.pending_code=None
                self._emit('Código verificado disponible en el enlace local. Esperando confirmación del bot IMSS.')
            except Exception as ex:
                self._emit('No se confirmó el envío al enlace ('+type(ex).__name__+'). Conservo el código en memoria para reintentar la misma solicitud.')

    def _check_inbox_safely(self,page,email):
        try:self._check_inbox(page,email)
        except Exception as exc:
            now=time.monotonic()
            if now-self._last_read_error>=8:
                self._last_read_error=now
                self._emit('La lectura del correo falló ('+type(exc).__name__+'). La ventana permanece abierta; volveré a comprobarla.')

    def _watch_session(self,browser,context,email):
        """Mantiene el navegador y el lector; ningún fallo de lectura cierra la cuenta."""
        previous=''
        while not self.stop_event.wait(.5):
            if not browser.is_connected():return
            try:
                pages=[page for page in context.pages if not page.is_closed()]
                if not pages:
                    try:context.wait_for_event('page',timeout=2000)
                    except Exception:pass
                    pages=[page for page in context.pages if not page.is_closed()]
                    if not pages:return
                page=pages[-1]
                pump=getattr(page,'wait_for_timeout',None)
                if callable(pump):pump(100)
                if self.rate_limited:continue
                if is_microsoft_rate_limited(page):
                    self.rate_limited=True
                    self.retry_requested.clear()
                    self.reopen_requested.clear()
                    self.open_mail_requested.clear()
                    self._emit('Microsoft respondió TOO MANY REQUESTS (429). Pausé el bot y mantengo la ventana abierta. Espera a que Microsoft retire el límite temporal.')
                    continue
                if is_outlook_mail_url(page.url):
                    self.phase='mail'
                    self.last_error=''
                    if previous!='mail':self._emit('Bandeja abierta. Mantengo la sesión mientras el bot IMSS espera o recoge el código.')
                    previous='mail'
                    self._check_inbox_safely(page,email)
                elif is_passkey_enrollment_url(page.url):
                    self.phase='passkey'
                    if previous!='passkey':self._emit('Microsoft pide guardar una clave de paso. La ventana permanece abierta para que decidas; no aceptaré esa operación automáticamente.')
                    previous='passkey'
            except Exception as exc:
                if not browser.is_connected():return
                self.phase='attention'
                if previous!='error':self._emit('Navegador conservado tras un error ('+type(exc).__name__+'). No cerraré la sesión por este fallo.')
                previous='error'

    def _worker(self, email, password):
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                browser=launch_private_browser(p,self._emit)
                context=None
                profile_guard=None
                try:
                    # Each context is an isolated private session: no cookies/history are
                    # reused between accounts. On close the complete context is discarded.
                    context=browser.new_context(locale='es-MX',accept_downloads=False)
                    self._emit('Ventana privada creada: al pasar a otra cuenta se borran sus cookies y sesión local.')
                    # No reescribir OAuth ni interceptar los formularios de Microsoft:
                    # esto interrumpía la carga en ciertas cuentas/tenants.
                    page=context.new_page()
                    self.phase='login'
                    self.browser_opened.set()
                    from avisos_perfil import ProfilePromptGuard
                    profile_guard=ProfilePromptGuard(self._emit)
                    profile_guard.start()
                    try:
                        page.goto(OUTLOOK_LOGIN_LANDING,wait_until='domcontentloaded',timeout=22000)
                    except Exception as exc:
                        # The Microsoft sign-in can keep redirecting while its form
                        # is already visible; a navigation timeout must not kill
                        # the private browser or abandon the login.
                        self._emit('Microsoft tardó en abrir Outlook ('+type(exc).__name__+'). Buscaré el formulario en la ventana abierta.')
                    self._emit('Abriendo formulario oficial de inicio de sesión Microsoft en incógnito…')
                    # No cerrar sesión por timeout: formularios pueden seguir cargando.
                    # Do not give up after a hard-coded timeout while the
                    # user is still looking at the username screen.
                    deadline=time.monotonic()+900
                    email_submitted_at=0.0
                    browser_open_at=time.monotonic()
                    auth_page_seen=False
                    auth_fallback_attempted=False
                    email_submit_retries=0
                    marketing_at=None
                    last_marketing_click=0
                    fallback_used=False
                    mail_open_attempted=False
                    stage='start'
                    stay_dialog_handled=False
                    mail_announced=False
                    last_message=''
                    last_action=0
                    password_restart_count=0
                    while time.monotonic()<deadline and not self.stop_event.is_set():
                        if not browser.is_connected():
                            break
                        pages=[item for item in context.pages if not item.is_closed()]
                        if not pages:
                            try:context.wait_for_event('page',timeout=2000)
                            except Exception:pass
                            pages=[item for item in context.pages if not item.is_closed()]
                            if not pages:break
                        # La pestaña más reciente puede estar en blanco mientras
                        # la autenticación real queda en la anterior.
                        page=pages[-1]
                        if len(pages)>1:
                            for candidate in reversed(pages):
                                try:
                                    if trusted_login_url(candidate.url):
                                        page=candidate
                                        if locate_email_input(candidate)[0] is not None:
                                            break
                                except Exception:
                                    continue
                        pump=getattr(page,'wait_for_timeout',None)
                        if callable(pump):
                            try:pump(60)
                            except Exception:continue
                        url=page.url
                        now=time.monotonic()
                        # Si Microsoft responde 429, no hacer más clics, envíos
                        # ni navegación. No buscar rutas alternativas ni recargar.
                        if is_microsoft_rate_limited(page):
                            self.rate_limited=True
                            self.retry_requested.clear()
                            self.reopen_requested.clear()
                            self.open_mail_requested.clear()
                            self._emit('Microsoft respondió TOO MANY REQUESTS (429). Pausé el bot; no intentaré nuevamente. Cierra el navegador y espera a que Microsoft retire el límite temporal.')
                            # Evitar que el resto del flujo continúe mientras
                            # la ventana muestra la restricción.
                            while not self.stop_event.wait(1):
                                if not browser.is_connected():
                                    break
                            break
                        if is_passkey_enrollment_url(url):
                            self.phase='passkey'
                            if last_message!='passkey_enrollment':
                                self._emit('Microsoft pide guardar una clave de paso. Puedes cancelar ese guardado si no lo deseas; mantendré la ventana abierta.')
                                last_message='passkey_enrollment'
                            pump=getattr(page,'wait_for_timeout',None)
                            if callable(pump):pump(200)
                            self.stop_event.wait(.4)
                            continue
                        if self.reopen_requested.is_set():
                            self.reopen_requested.clear()
                            # Reabrir sitio oficial sin cerrar el contexto privado.
                            try:
                                target=next((p for p in pages if is_outlook_mail_url(p.url)),pages[0])
                                target.bring_to_front()
                                target.goto(OUTLOOK_LOGIN_LANDING,wait_until='domcontentloaded',timeout=22000)
                                page=target
                                stage='start'
                                auth_page_seen=False
                                browser_open_at=time.monotonic()
                                auth_fallback_attempted=False
                                marketing_at=None
                                mail_open_attempted=False
                                self._emit('Formulario oficial de Microsoft reabierto en incógnito. Buscando correo…')
                            except Exception as ex:
                                self._emit('No se pudo reabrir Outlook: '+type(ex).__name__+'. Comprueba Internet/DNS.')
                            continue
                        if self.open_mail_requested.is_set():
                            self.open_mail_requested.clear()
                            try:
                                page.bring_to_front()
                                page.goto(OUTLOOK_WEB_URL,wait_until='commit',timeout=18000)
                                mail_open_attempted=True
                                self._emit('Bandeja de Outlook solicitada en la sesión privada actual.')
                            except Exception as ex:
                                self._emit('La bandeja todavía no cargó: '+type(ex).__name__+'.')
                            continue
                        if self.retry_requested.is_set():
                            self.retry_requested.clear()
                            if trusted_login_url(url):
                                field,_,_=locate_email_input(page)
                                password_field,_=visible_control(page,PASSWORD_INPUT)
                                if field is not None and password_field is None:
                                    stage='start'
                                    email_submit_retries=0
                                    self._emit('Reintentando el paso del correo en el formulario actual…')
                                else:
                                    self._emit('Todavía no se ve el campo de correo; mantén abierta esta ventana de Microsoft.')
                            else:
                                self._emit('Esperando a que Microsoft muestre su pantalla de inicio de sesión.')
                        if is_password_signin_unavailable(page):
                            if password_restart_count >= len(PASSWORD_RETRY_DELAYS):
                                if last_message != 'password_unavailable_limit':
                                    self._emit('El inicio con contraseña sigue sin estar disponible tras dos reintentos. '
                                               'Dejé la página abierta para revisión; no volveré a intentarlo automáticamente.')
                                    last_message='password_unavailable_limit'
                                self.stop_event.wait(.5)
                                continue
                            password_restart_count += 1
                            self.retry_requested.clear()
                            self.reopen_requested.clear()
                            self.open_mail_requested.clear()
                            replacement=self._restart_password_signin(context,page,password_restart_count)
                            if replacement is None:
                                break
                            page=replacement
                            # Reiniciar el flujo completo de la MISMA cuenta. El contador
                            # y el plazo total no se reinician al cambiar de pestaña.
                            stage='start'
                            email_submitted_at=0.0
                            browser_open_at=time.monotonic()
                            auth_page_seen=False
                            auth_fallback_attempted=False
                            email_submit_retries=0
                            marketing_at=None
                            last_marketing_click=0
                            fallback_used=False
                            mail_open_attempted=False
                            stay_dialog_handled=False
                            mail_announced=False
                            last_message=''
                            last_action=0
                            continue
                        if trusted_login_url(url):
                            auth_page_seen=True
                            if not stay_dialog_handled and click_no_keep_session(page):
                                stay_dialog_handled=True
                                stage='password_sent'
                                self._emit('Microsoft preguntó si conservar la sesión. Pulsé No; la ventana seguirá en incógnito.')
                                try:
                                    page.goto(OUTLOOK_WEB_URL,wait_until='commit',timeout=20000)
                                    self._emit('Abriendo la bandeja de entrada de Outlook en esta misma ventana privada…')
                                except Exception as ex:
                                    self._emit('Outlook tarda en abrir la bandeja ('+type(ex).__name__+').')
                                continue
                        # Nunca quedarse pulsando botones en la portada de Microsoft 365.
                        # Si Outlook redirige allí antes de autenticar, abrir una vez
                        # el formulario directo y oficial de Microsoft (login.live.com).
                        if is_marketing_url(url):
                            if stage in ('password_sent','password_needs_click','challenge'):
                                # Después de iniciar sesión puede haber redirección
                                # a marketing. Intentar el buzón una sola vez.
                                if not mail_open_attempted:
                                    mail_open_attempted=True
                                    self._emit('Sesión enviada; abriendo la bandeja Outlook en esta misma ventana privada…')
                                    try:page.goto(OUTLOOK_WEB_URL,wait_until='commit',timeout=18000)
                                    except Exception as ex:self._emit('Outlook tardó en abrir: '+type(ex).__name__+'.')
                                else:
                                    if last_message!='marketing_post_auth':
                                        self._emit('Microsoft muestra su portada. Completa cualquier validación pendiente y pulsa ABRIR BANDEJA.')
                                        last_message='marketing_post_auth'
                                time.sleep(.6)
                                continue
                            if not auth_fallback_attempted:
                                auth_fallback_attempted=True
                                self._emit('Microsoft redirigió a publicidad; abriendo el formulario oficial de inicio de sesión directamente…')
                                try:page.goto(OUTLOOK_LOGIN_LANDING,wait_until='domcontentloaded',timeout=22000)
                                except Exception as ex:self._emit('Formulario lento: '+type(ex).__name__+'.')
                            else:
                                if last_message!='marketing_unexpected':
                                    self._emit('La portada continúa. Pulsa REABRIR FORMULARIO; si sigue así, revisa el diagnóstico.')
                                    last_message='marketing_unexpected'
                            time.sleep(.6)
                            continue
                        # Si aparece una pestaña vacía durante el arranque, volver
                        # una sola vez al formulario y evitar bucles de navegación.
                        if (url=='about:blank' and now-browser_open_at>6 and not auth_fallback_attempted):
                            auth_fallback_attempted=True
                            try:page.goto(OUTLOOK_LOGIN_LANDING,wait_until='domcontentloaded',timeout=22000)
                            except Exception as ex:self._emit('Aún esperando formulario: '+type(ex).__name__+'.')
                            continue
                        marketing_at=None
                        if is_outlook_mail_url(url):
                            self.phase='mail'
                            if not mail_announced:
                                self._emit('Outlook abierto en incógnito. Buscando el código nuevo si IMSS tiene una solicitud pendiente…')
                                mail_announced=True
                            self._check_inbox_safely(page,email)
                            time.sleep(1.0)
                            continue
                        if stage=='password_sent' and not mail_open_attempted and is_account_dashboard(page):
                            mail_open_attempted=True
                            self._emit('Acceso completado. Abriendo automáticamente la bandeja de Outlook…')
                            try:page.goto(OUTLOOK_WEB_URL,wait_until='domcontentloaded',timeout=20000)
                            except Exception as ex:self._emit('La bandeja tarda en cargar ('+type(ex).__name__+').')
                            continue
                        if not trusted_login_url(url):
                            # Algunos pasos OAuth cambian momentáneamente de página.
                            # Nunca se rellenan campos en dominios no autorizados.
                            if last_message!='waiting_navigation':
                                self._emit('Esperando formulario de Microsoft. Si sigue en blanco, pulsa REABRIR FORMULARIO y revisa Internet.')
                                last_message='waiting_navigation'
                            time.sleep(.65)
                            continue
                        # El formulario puede aparecer después de varios segundos;
                        # reintentar cada 0.5 s en lugar de mirar una sola vez.
                        if stage=='start':
                            try:
                                state=fill_email_step(page,email,self._emit)
                                if state=='submitted':
                                    stage='email_sent'
                                    email_submitted_at=time.monotonic()
                                    self._emit('Siguiente pulsado. Confirmaré que Microsoft avance a la contraseña…')
                                    time.sleep(.6)
                                    continue
                                if state=='needs_click':
                                    stage='email_needs_click'
                                    email_submitted_at=time.monotonic()
                                    continue
                                if state=='mismatch':
                                    last_action=now
                                    time.sleep(1.0)
                                    continue
                            except Exception as ex:
                                if now-last_action>6:
                                    last_action=now
                                    self._emit('Microsoft todavía no permite escribir el correo ('+type(ex).__name__+').')
                            # If a previously used Microsoft account is shown, change it.
                            if now-last_action>2.0:
                                if choose_account_tile(page,email):
                                    stage='email_sent'
                                    email_submitted_at=time.monotonic()
                                    last_action=now
                                    self._emit('Cuenta seleccionada: '+email+'.')
                                    continue
                                if choose_other_account(page):
                                    last_action=now
                                    self._emit('Abrí «Usar otra cuenta». Esperando el campo de correo…')
                                    continue
                            if now-last_action>6:
                                last_action=now
                                self._emit('Buscando correo en '+(urlparse(url).hostname or '')+': '+describe_login_fields(page))
                        if stage in ('email_sent','email_needs_click'):
                            # A click may be ignored by Microsoft while the
                            # form is loading. If the username input is STILL
                            # visible, check the value and retry Siguiente at
                            # most twice, without adding another email.
                            # No repetir automáticamente «Siguiente». Si Microsoft
                            # tarda, el usuario decide cuándo reintentar.
                            field,frame=visible_control(page,PASSWORD_INPUT)
                            if field is not None:
                                try:
                                    field.fill(password,timeout=7500)
                                    self._emit('Contraseña introducida en el formulario oficial.')
                                    if submit_form(page,frame,self._emit,field):
                                        stage='password_sent'
                                        self._emit('Inicio de sesión enviado; esperando respuesta de Microsoft…')
                                    else:
                                        stage='password_needs_click'
                                    time.sleep(.65)
                                    continue
                                except Exception as ex:
                                    if now-last_action>5:
                                        last_action=now
                                        self._emit('No se pudo completar la contraseña ('+type(ex).__name__+').')
                            if now-last_action>3 and try_password_choice(page):
                                last_action=now
                                self._emit('Se seleccionó «Usar la contraseña».')
                                continue
                            if stage=='email_needs_click' and now-last_action>6:
                                last_action=now
                                self._emit('Correo escrito pero no se confirmó Siguiente. Usa REINTENTAR CORREO solo si Microsoft no ha avanzado.')
                        if stage=='password_needs_click' and now-last_action>6:
                            last_action=now
                            self._emit('Contraseña escrita; espera respuesta de Microsoft. No repetiré el acceso automáticamente.')
                        if stage=='password_sent':
                            # No rellenar códigos de segundo factor. Solo identificar el paso.
                            if now-last_action>12:
                                last_action=now
                                self._emit('Si Microsoft solicita un código, confírmalo en su página oficial.')
                        time.sleep(.52)
                    else:
                        if not self.stop_event.is_set():
                            self._emit('Microsoft todavía no confirmó el inicio de sesión. La ventana privada permanece abierta para revisión.')
                    self._watch_session(browser,context,email)
                except Exception as exc:
                    pages=[] if context is None else [item for item in context.pages if not item.is_closed()]
                    if not pages or not browser.is_connected():raise
                    self.phase='attention'
                    self.last_error='El acceso se pausó ('+type(exc).__name__+'). Mantengo la ventana abierta y el enlace disponible.'
                    try:
                        from diagnostico import record
                        record('outlook_session_preserved',exc)
                    except Exception:pass
                    self._emit(self.last_error)
                    self._watch_session(browser,context,email)
                finally:
                    if profile_guard is not None:profile_guard.stop()
                    try:
                        if context is not None:context.close()
                    except Exception:pass
                    try:browser.close()
                    except Exception:pass
        except Exception as exc:
            self.phase='error'
            if isinstance(exc,BrowserLaunchError):
                self.last_error='No se pudo abrir Edge, Chrome ni Chromium. Ejecuta INSTALAR.bat y vuelve a pulsar INICIAR.'
            elif isinstance(exc,ModuleNotFoundError):
                self.last_error='Faltan dependencias del navegador. Ejecuta INSTALAR.bat y vuelve a pulsar INICIAR.'
            else:
                self.last_error='El acceso se detuvo ('+type(exc).__name__+'). Revisa Ajustes > Diagnóstico.'
            self._emit(self.last_error)
            # Conservar el diagnóstico aun cuando el navegador cierre la sesión.
            try:
                import traceback
                from pathlib import Path
                diag=Path.home() / 'GestoriaDiaz_Outlook_error.txt'
                import json
                frames=[{'file':Path(f.filename).name,'line':f.lineno,'function':f.name}
                        for f in traceback.extract_tb(exc.__traceback__)]
                diag.write_text(json.dumps({'type':type(exc).__name__,'frames':frames}), encoding='utf-8')
                self._emit('Error de Outlook ('+type(exc).__name__+'). Diagnóstico guardado: '+str(diag))
            except Exception:
                self._emit('Error de Outlook ('+type(exc).__name__+'). Revisa el diagnóstico local.')
        finally:
            self.pending_code=None
            self.running=False
            if self.phase!='error':
                if not self.stop_event.is_set() and self.browser_opened.is_set() and not self.rate_limited:
                    self.last_error='El navegador perdió su ventana o conexión. El enlace local permanece disponible; revisa su estado.'
                self.phase='closed'
            self._emit('Navegador cerrado.')

# Compatible diagnostic name for integrations expecting the previous helper.
describe_login_form = describe_login_fields
