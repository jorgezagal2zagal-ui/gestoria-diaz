# -*- coding: utf-8 -*-
"""Acceso asistido a Outlook. Abre directamente el login oficial Microsoft.
Nunca introduce credenciales en sitios ajenos a los hosts de inicio de Microsoft.
Las verificaciones de identidad quedan a cargo del titular.
"""
from __future__ import annotations
import re
import os
import sys
import threading
import time
import unicodedata
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse, urlsplit, urlunsplit, quote, parse_qsl
from opciones_v28 import (decline_web_passkey_setup, decline_optional_recovery,
                         prepare_browser_preferences)

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
PASSWORD_RETRY_DELAYS = ()  # V18: never restart a blocked password sign-in automatically
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


BLOCKED_TEXT = re.compile(
    r'(?:se\s+bloque[oó]\s+la\s+cuenta|\bcuenta\s+(?:ha\s+sido|est[aá])\s+bloqueada\b|'
    r'\btu\s+cuenta\s+(?:ha\s+sido|est[aá])\s+bloqueada\b|'
    r'\byour\s+account\s+(?:has\s+been|is)\s+locked\b|'
    r'\bwe\s+have\s+locked\s+your\s+account\b)',re.I)

ADDITIONAL_CHECK_HEAD = re.compile(r'(?:ya\s+casi\s+est[aá]|you.?re\s+almost\s+there)', re.I)
ADDITIONAL_CHECK_BODY = re.compile(
    r'(?:solo\s+un\s+paso\s+m[aá]s\s+para\s+comprobar\s+que\s+eres\s+t[uú]|'
    r'one\s+more\s+step\s+to\s+(?:verify|make\s+sure)\s+)',re.I)
ADDITIONAL_CHECK_CODE = re.compile(
    r'(?:enviar\s+un\s+c[oó]digo\s+a|send\s+(?:a|an)\s+code\s+to)',re.I)

MANDATORY_RECOVERY_HEAD = re.compile(
    r'(?:ayuda\s+a\s+proteger\s+tu\s+cuenta|help\s+us\s+protect\s+your\s+account)', re.I)
MANDATORY_RECOVERY_BODY = re.compile(
    r'(?:agrega\s+un\s+correo|agregar\s+direcci[oó]n\s+de\s+correo|'
    r'add\s+(?:a|an)\s+(?:recovery\s+)?email(?:\s+address)?)', re.I)

def is_mandatory_recovery_email_interrupt(page):
    """Sólo reconocer un correo de recuperación obligatorio en account.live.com.

    El bot NO inventa una dirección, no modifica credenciales y no omite
    verificaciones obligatorias de Microsoft. Simplemente descarta esta cuenta
    de la cola local para que un titular la revise por el canal oficial.
    """
    url=getattr(page,'url','')
    p=urlparse(url)
    if p.scheme!='https' or (p.hostname or '').lower() not in (
            'account.live.com','account.microsoft.com'):
        return False
    if not re.search(r'/interrupt/credential|/proofs/manage',p.path,re.I):
        return False
    try: body=(page.locator('body').inner_text(timeout=1300) or '')[:5500]
    except Exception:return False
    return bool(MANDATORY_RECOVERY_HEAD.search(body) and
                MANDATORY_RECOVERY_BODY.search(body))

def is_additional_verification_required(page):
    """Sólo una pantalla inequívoca de Microsoft pidiendo otro factor.

    No trata un inicio en progreso, un CAPTCHA o 429 como cuenta bloqueada.
    Nunca intenta completar ni saltarse la verificación.
    """
    if not trusted_login_url(getattr(page,'url','')):return False
    try: body=(page.locator('body').inner_text(timeout=1200) or '')[:5500]
    except Exception:return False
    if RATE_LIMIT_TEXT.search(body):return False
    return bool(ADDITIONAL_CHECK_HEAD.search(body) and
                ADDITIONAL_CHECK_BODY.search(body) and
                ADDITIONAL_CHECK_CODE.search(body))

# V25: pantalla «Obtener una solicitud de inicio de sesión».
# Solo abre el menú de opciones oficiales. No envía la solicitud al móvil,
# no rellena OTP, no elige factores ni evade MFA, bloqueo o límites.
OTHER_METHOD_PROMPT = re.compile(
    r'(?:obtener\s+una\s+solicitud\s+de\s+inicio\s+de\s+sesi[oó]n|'
    r'get\s+a\s+sign[ -]?in\s+(?:request|notification))',re.I)
OTHER_METHOD_LINK = re.compile(
    r'^\s*(?:otras\s+formas\s+de\s+iniciar\s+sesi[oó]n|'
    r'other\s+ways\s+to\s+sign\s+in|'
    r'sign\s+in\s+another\s+way|'
    r'other\s+sign[ -]?in\s+options)\s*$',re.I)

def click_other_signin_methods(page):
    """Una pulsación acotada en la página oficial si está el aviso exacto.

    No toca el botón «Enviar solicitud» ni usa accesos de recuperación.
    """
    if not trusted_login_url(getattr(page,'url','')):
        return False
    try:
        body=(page.locator('body').inner_text(timeout=1500) or '')[:4500]
        if (RATE_LIMIT_TEXT.search(body) or BLOCKED_TEXT.search(body)
                or not OTHER_METHOD_PROMPT.search(body)):
            return False
        for role in ('link','button'):
            options=page.get_by_role(role,name=OTHER_METHOD_LINK)
            for i in range(min(options.count(),5)):
                choice=options.nth(i)
                if choice.is_visible() and choice.is_enabled():
                    choice.click(timeout=5500)
                    return True
    except Exception:
        pass
    return False

def is_microsoft_account_blocked(page):
    """No confundir CAPTCHA, MFA, contraseña incorrecta o 429 con bloqueo."""
    url=getattr(page,'url','')
    if not trusted_login_url(url):return False
    try:
        body=(page.locator('body').inner_text(timeout=1000) or '')[:4500]
    except Exception:return False
    if RATE_LIMIT_TEXT.search(body):return False
    # `account.live.com/Abuse` is the official locked-account page.
    return bool(BLOCKED_TEXT.search(body))

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


def inbox_ui_verified(page):
    """Confirmación conservadora: URL Outlook + carpeta de correo visible.

    Nunca dar la cuenta por lista por una URL que aún está cargando.
    """
    if not is_outlook_mail_url(getattr(page,'url','')):return False
    try:
        body=(page.locator('body').inner_text(timeout=1400) or '')[:4500]
        if RATE_LIMIT_TEXT.search(body) or CHALLENGE.search(body):return False
        if not re.search(r'(?i)\b(?:bandeja de entrada|inbox|correo no deseado|junk email|elementos enviados|sent items)\b',body):
            return False
        for css in ('[role="navigation"]','[role="main"]','[role="listbox"]',
                    '[data-app-section="Mail"]','[data-testid="folderPane"]'):
            try:
                x=page.locator(css)
                if x.count() and x.first.is_visible():return True
            except Exception:pass
    except Exception:pass
    return False


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
        self.blocked=False
        self.password_unavailable=False
        self.extra_verification=False
        self.phase='idle'
        self.last_error=''
        self.browser_opened=threading.Event()
        self.pending_code=None
        self._last_read_error=0.0
        # Snapshot of already-visible messages before each IMSS request.  The
        # browser is opened FIRST. The automated reader accepts new arrivals,
        # not simply the first OTP currently present in the inbox.
        self._prior_mail_keys=set()
        self._baseline_ready=False
        self._baseline_email=None

    def start(self, email, password):
        if self.running:
            raise RuntimeError('Ya hay una ventana de inicio abierta.')
        self.stop_event.clear()
        self.rate_limited=False
        self.blocked=False
        self.password_unavailable=False
        self.extra_verification=False
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
        self.manual_security_pending=False
        self._mailbox_verified_at=0
        self._mailbox_verified_email=None
        self._prior_mail_keys=set()
        self._baseline_ready=False
        self._baseline_email=None
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

    def _manual_security_wait(self,page):
        # Sticky pause: after a challenge only the human navigates until inbox is real.
        if is_microsoft_rate_limited(page):return False
        if is_microsoft_account_blocked(page):return False
        challenged=False
        if trusted_login_url(getattr(page,'url','')) and not is_passkey_enrollment_url(page.url):
            try:
                text=page.locator('body').inner_text(timeout=1000)[:12000]
                challenged=bool(CHALLENGE.search(text) or re.search(
                    r'captcha|not a robot|no soy un robot|security check|comprobaci[oó]n de seguridad|'
                    r'authenticator|fingerprint|huella|security key|llave de seguridad|'
                    r'use (?:your |a )?passkey|usa(?:r)? (?:tu |una )?clave de paso|'
                    r'c[oó]digo de seguridad|one.time code|approve (?:the )?sign.in',text,re.I))
                challenged=challenged or '/fido/' in urlparse(page.url).path.casefold()
                challenged=challenged or is_additional_verification_required(page) or is_mandatory_recovery_email_interrupt(page)
            except Exception:challenged=True
        paused=getattr(self,'manual_security_pending',False)
        if paused and not challenged and inbox_ui_verified(page):
            self.manual_security_pending=False
            self.extra_verification=False
            self._emit('Verificación manual terminada; comprobaré de nuevo cuenta y bandeja.')
            return False
        if challenged or paused:
            guard=getattr(self,'_optional_prompt_guard',None)
            if guard is not None:guard.disarm_passkey()
            self.manual_security_pending=True
            self.extra_verification=False
            self.phase='security_manual'
            self._mailbox_verified_at=0
            if not paused:
                self._emit('PAUSA: Microsoft requiere verificación manual. Completa sus instrucciones en Chrome; IMSS no comenzará. No se cambia de cuenta.')
            return True
        return False

    def _snapshot_before_request_v45(self,page,email):
        """Record visible IMSS mail identities when no IMSS request is active.
        Never open a message or extract any OTP in this phase.
        """
        if self._baseline_email!=email:
            self._prior_mail_keys=set()
            self._baseline_ready=False
            self._baseline_email=email
        if not is_outlook_mail_url(getattr(page,'url','')):
            return
        try:
            from lector_reciente_v40 import _candidate_rows
            for key,_,_ in _candidate_rows(page,self.sender):
                if key:self._prior_mail_keys.add(key)
            url=str(getattr(page,'url','') or '')
            if '/id/' in url.casefold():
                self._prior_mail_keys.add('seleccionado:'+url.split('?',1)[0])
            self._baseline_ready=True
        except Exception:
            pass

    def _scan_dated_new_only_v45(self,page,sender,started):
        """Fail closed if we did not see inbox before the new request.
        In this case only a message with a verifiable received date is accepted.
        """
        try:
            from lector_reciente_v40 import _candidate_rows
            from lector_reciente_v29 import _message_data,_correct_sender
            from datetime import timedelta
            for key,row,summary in _candidate_rows(page,sender):
                if key in self.scanned_ids:continue
                row.click(timeout=3000)
                if not _correct_sender(page,sender):continue
                received,body=_message_data(page,row)
                started_dt=iso_dt(started)
                received_dt=iso_dt(received)
                if not started_dt or not received_dt or received_dt<started_dt:
                    continue
                otp=imss_code_from_message(sender,received,summary,body,sender,started)
                if otp:
                    self.scanned_ids.add(key)
                    return otp
        except Exception:pass
        return None

    def _check_inbox(self, page, email):
        if not self.request_supplier or not self.deliver_code:
            return
        from lector_integrado import mailbox_identity_verified
        if not inbox_ui_verified(page) or not mailbox_identity_verified(page,email):
            self._mailbox_verified_at=0
            self.pending_code=None
            return
        self._mailbox_verified_email=email.casefold()
        self._mailbox_verified_at=time.monotonic()
        now=time.monotonic()
        if now-self.last_scan<0.8:return
        self.last_scan=now
        try: request=self.request_supplier()
        except Exception:return
        if not isinstance(request,dict) or request.get('status')!='ESPERANDO_CODIGO':
            self.pending_code=None
            self._snapshot_before_request_v45(page,email)
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
            self.scanned_ids=set(self._prior_mail_keys)
            self.last_scan_request=request_id
            self.pending_code=None
            self._emit('V45: solicitud nueva detectada; ignorando mensajes anteriores a esta solicitud.')
        result=self.pending_code or scan_visible_inbox(page,sender,request.get('started'),self.scanned_ids)
        if result=='fecha_no_verificable':
            self._emit('Encontré un posible correo IMSS, pero Outlook no mostró la fecha verificable. Usa el código manualmente.')
        elif result:
            self.pending_code=result
            try:
                self.deliver_code(request_id,result,email)
                self.pending_code=None
                self._emit('V45: CÓDIGO ENTREGADO AL ENLACE; IMSS debe confirmar su recepción y escritura.')
            except Exception as ex:
                self._emit('V40: ENLACE RECHAZÓ el envío ('+type(ex).__name__+'). Reintentaré el mismo folio sin copiar códigos en los registros.')

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
        from recarga_v33 import PageStallGuard
        recovery=PageStallGuard(seconds=5)
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
                if self._manual_security_wait(page):continue
                if recovery.consider(page):
                    self._emit('Pantalla de correo/aviso vacía 5 segundos: recarga controlada.')
                    continue
                if is_microsoft_rate_limited(page):
                    self.rate_limited=True
                    from guardia_v18 import marcar_limite
                    marcar_limite()
                    self.retry_requested.clear()
                    self.reopen_requested.clear()
                    self.open_mail_requested.clear()
                    self._emit('Microsoft respondió TOO MANY REQUESTS (429). Pausé el bot y mantengo la ventana abierta. Espera a que Microsoft retire el límite temporal.')
                    continue
                if is_outlook_mail_url(page.url):
                    if decline_optional_recovery(page):
                        self._emit('Elegí «Not now» en la oferta de recuperación de Outlook.')
                        continue
                    self.phase='mail' if inbox_ui_verified(page) else 'mail_loading'
                    self.last_error=''
                    if self.phase=='mail':
                        if previous!='mail':self._emit('Bandeja verificada. Mantengo la sesión mientras el bot IMSS espera el código.')
                        self._check_inbox_safely(page,email)
                    previous=self.phase
                elif trusted_login_url(page.url) and click_no_keep_session(page):
                    self._emit('Elegí «No» en la pregunta de Microsoft sobre mantener la sesión.')
                    previous='login'
                elif is_passkey_enrollment_url(page.url):
                    if decline_web_passkey_setup(page):
                        self._emit('Cancelé la creación opcional de una clave de paso de Microsoft.')
                        continue
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
                browser=launch_existing_session_v18(p,self._emit,email)
                context=None
                profile_guard=None
                optional_guard=None
                try:
                    # Each context is an isolated private session: no cookies/history are
                    # reused between accounts. On close the complete context is discarded.
                    context=browser.new_context(locale='es-MX',accept_downloads=False)
                    self._emit('Perfil separado de la cuenta: se reutiliza la sesión si Microsoft la mantiene válida.')
                    # No reescribir OAuth ni interceptar los formularios de Microsoft:
                    # esto interrumpía la carga en ciertas cuentas/tenants.
                    page=context.new_page()
                    try:page.bring_to_front()
                    except Exception:pass
                    self._emit('CHROME V36: navegador visible; sesión en ventana real, no en segundo plano.')
                    self.phase='login'
                    self.browser_opened.set()
                    from avisos_perfil import ProfilePromptGuard
                    from avisos_windows_v35 import OptionalWindowsPromptsV35
                    profile_guard=ProfilePromptGuard(self._emit)
                    optional_guard=OptionalWindowsPromptsV35(self._emit)
                    self._optional_prompt_guard=optional_guard
                    # In headless mode there are no native dialogs to control.
                    # Keep the optional guard for its harmless arm/stop methods.
                    if os.environ.get('GD_HEADLESS','0')!='1':
                        profile_guard.start()
                        optional_guard.start()
                    try:
                        page.goto(OUTLOOK_WEB_URL,wait_until='domcontentloaded',timeout=22000)
                    except Exception as exc:
                        # The Microsoft sign-in can keep redirecting while its form
                        # is already visible; a navigation timeout must not kill
                        # the private browser or abandon the login.
                        self._emit('Microsoft tardó en abrir Outlook ('+type(exc).__name__+'). Buscaré el formulario en la ventana abierta.')
                    self._emit('Abriendo Outlook en un perfil propio de Chrome; reutilizando sesión si está disponible…')
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
                    other_methods_clicked=False
                    other_methods_at=None
                    last_message=''
                    last_action=0
                    password_restart_count=0
                    from recarga_v33 import PageStallGuard
                    blank_guard=PageStallGuard(seconds=5)
                    while time.monotonic()<deadline and not self.stop_event.is_set():
                        if not browser.is_connected():
                            break
                        pages=[item for item in context.pages if not item.is_closed()]
                        if not pages:
                            try:context.wait_for_event('page',timeout=2000)
                            except Exception:pass
                            pages=[item for item in context.pages if not item.is_closed()]
                            if not pages:break
                        # La página blanca del aviso Microsoft puede estar en OTRA
                        # pestaña mientras queda un formulario de acceso abierto.
                        # Revisar SOLO ese aviso; nunca recargar el login/MFA.
                        for notice_tab in pages:
                            if (urlparse(getattr(notice_tab,'url','')).hostname or '').lower() == 'privacynotice.account.microsoft.com':
                                if blank_guard.consider(notice_tab):
                                    self._emit('Aviso de Microsoft en blanco: recargué esa pestaña tras 5 segundos.')
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
                        if self._manual_security_wait(page):
                            self.stop_event.wait(.5)
                            continue
                        optional_guard.arm_passkey(is_passkey_enrollment_url(url))
                        now=time.monotonic()
                        # Si Microsoft responde 429, no hacer más clics, envíos
                        # ni navegación. No buscar rutas alternativas ni recargar.
                        if is_microsoft_rate_limited(page):
                            self.rate_limited=True
                            from guardia_v18 import marcar_limite
                            marcar_limite()
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
                        # Únicamente páginas oficiales de Microsoft y texto inequívoco.
                        # Se bloquea la cuenta específica; no se interactúa con
                        # el formulario de desbloqueo ni se reintenta con ella.
                        if is_microsoft_account_blocked(page):
                            self.blocked=True
                            self.phase='blocked'
                            self._emit('Cuenta bloqueada por Microsoft. Se apartará de la lista activa para revisión del titular.')
                            self.stop_event.set()
                            break
                        # V41+hotfix: el formulario de "Agregar dirección de correo"
                        # obliga a registrar recuperación: no saltarlo ni esperar
                        # a que un Android quede detenido por esta cuenta.
                        if is_mandatory_recovery_email_interrupt(page):
                            self.extra_verification=True
                            self.phase='extra_verification'
                            self._emit('Cuenta requiere AGREGAR CORREO DE RECUPERACIÓN. '
                                       'Se apartó de Gestoría Díaz para revisión; '
                                       'no se modifica la seguridad de Microsoft.')
                            self.stop_event.set()
                            break
                        # V21: "Ya casi está" / se pide OTP a correo alternativo.
                        # No interactuar con el factor adicional; retirar la cuenta
                        # de la lista activa para este bot.
                        if is_additional_verification_required(page):
                            self.extra_verification=True
                            self.phase='extra_verification'
                            self._emit('Esta cuenta exige verificación adicional en Microsoft. '
                                       'Se apartará de las disponibles sin intentar eludirla.')
                            self.stop_event.set()
                            break
                        if blank_guard.consider(page):
                            self._emit('Pantalla vacía detectada: recarga controlada de esa pestaña tras 5 segundos.')
                            continue
                        if is_passkey_enrollment_url(url):
                            # Only an OFFER to create a new passkey, never a
                            # sign-in challenge using an existing passkey.
                            if decline_web_passkey_setup(page):
                                self._emit('Cancelé la oferta opcional de crear una clave de paso de Microsoft.')
                                time.sleep(.5)
                                continue
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
                        # V25: «Obtener una solicitud de inicio de sesión» permite
                        # abrir opciones alternativas. Solo un clic por intento,
                        # únicamente tras descartar 429/bloqueo/verificación adicional.
                        if not other_methods_clicked and click_other_signin_methods(page):
                            other_methods_clicked=True
                            other_methods_at=now
                            self.phase='other_signin_methods'
                            self._emit('Elegí «Otras formas de iniciar sesión» en Microsoft. '
                                       'Buscaré «Usar contraseña» si está disponible; '
                                       'no enviaré solicitudes al móvil ni códigos de verificación.')
                            continue
                        # Si el menú abierto no ofrece contraseña, no seguir esperando
                        # indefinidamente ni seleccionar un segundo factor por cuenta propia.
                        if other_methods_clicked and other_methods_at and now-other_methods_at>=25:
                            pwd_field,_=visible_control(page,PASSWORD_INPUT)
                            if pwd_field is None and not is_outlook_mail_url(url):
                                # Tras 25 s sin una contraseña disponible,
                                # no quedar indefinidamente en un menú de verificación.
                                # Nunca repetir la navegación a otro método.
                                if trusted_login_url(url):
                                    self.password_unavailable=True
                                    self.phase='password_unavailable'
                                    self._emit('No apareció un formulario de contraseña después de abrir '
                                               'las opciones. Se aparta para revisión del titular; '
                                               'no se completarán verificaciones automáticamente.')
                                    self.stop_event.set()
                                    break
                        # Mensaje explícito de Microsoft: esta cuenta requiere otro
                        # método. No hacer clic en verificaciones, no repetir contraseña,
                        # no reintentar la misma cuenta. Una pausa global 429 tiene prioridad.
                        if is_password_signin_unavailable(page):
                            self.password_unavailable=True
                            self.phase='password_unavailable'
                            self._emit('Microsoft no permite el inicio con contraseña para esta cuenta. '
                                       'Se apartará automáticamente como REQUIERE OTRO MÉTODO; '
                                       'no se repetirá el inicio.')
                            self.stop_event.set()
                            break
                        if trusted_login_url(url):
                            auth_page_seen=True
                            if not stay_dialog_handled and click_no_keep_session(page):
                                stay_dialog_handled=True
                                stage='password_sent'
                                self._emit('Respondí «No» a la oferta de mantener la sesión iniciada en Microsoft.')
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
                            if decline_optional_recovery(page):
                                self._emit('Elegí «Not now» en la oferta de recuperación de Outlook.')
                                continue
                            self.phase='mail' if inbox_ui_verified(page) else 'mail_loading'
                            if self.phase=='mail' and not mail_announced:
                                self._emit('Bandeja Outlook verificada. Buscando código nuevo para la solicitud IMSS…')
                                mail_announced=True
                            if self.phase=='mail':self._check_inbox_safely(page,email)
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
                    if optional_guard is not None:optional_guard.stop()
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


# V18 uses a dedicated persistent *per-email* Chrome profile instead of a new
# anonymous context on each start. It never reads or attaches to the user's
# ordinary Chrome profile or imports cookies from other applications.
def launch_existing_session_v18(p, on_status, email):
    from pathlib import Path
    import os
    from hashlib import sha256
    root=Path(os.environ.get('LOCALAPPDATA') or (Path.home()/'AppData'/'Local'))/'GestoriaDiaz'/'OutlookPerfilesV18'
    root.mkdir(parents=True,exist_ok=True)
    digest=sha256(email.strip().lower().encode('utf-8')).hexdigest()[:24]
    errors=[]
    for label,channel in [('Google Chrome','chrome'),('Microsoft Edge','msedge'),('Chromium',None)]:
        folder=root/(channel or 'chromium')/digest
        folder.mkdir(parents=True,exist_ok=True)
        try:
            # Only the bot-owned per-address Chrome profile; never the personal one.
            prepare_browser_preferences(folder)
            # V34: native visible Chrome windows, not a delayed screenshot preview.
            # Apply layout only when starting each session; users may freely move/resize.
            headless=False  # V36 DIAGNOSTICO: mostrar Chrome real siempre
            chrome_args=['--no-first-run','--no-default-browser-check',
                         '--disable-notifications','--disable-save-password-bubble',
                         '--disable-features=Translate']
            opts={'user_data_dir':str(folder),'headless':headless,'locale':'es-MX',
                  'accept_downloads':False,'timeout':25000,'args':chrome_args}
            if not headless:
                try:
                    from ventanas_v34 import tile_geometry, chrome_window_args
                    slot=int(os.environ.get('GD_WORKER_SLOT','1'))
                    geometry=tile_geometry(slot)
                    opts['no_viewport']=True
                    chrome_args.extend(chrome_window_args(geometry))
                except Exception:
                    chrome_args.extend(['--window-size=520,430'])

            if channel:opts['channel']=channel
            context=p.chromium.launch_persistent_context(**opts)
            if headless: raise AssertionError('V36 requiere Chrome visible')
            on_status('Usando perfil dedicado de '+label+' para esta cuenta. No es el Chrome personal ni incógnito.')
            return _BrowserPersistenteV18(context)
        except Exception as exc:
            errors.append(label+': '+type(exc).__name__)
    raise BrowserLaunchError('No se pudo abrir un perfil dedicado de Chrome, Edge ni Chromium. Cierra otras ventanas del bot. '+', '.join(errors))

class _BrowserPersistenteV18:
    def __init__(self, context):
        self.context=context
        self._closed=False
    def new_context(self, **kwargs):
        # Persistent contexts already own a browser profile; do not create
        # another anonymous context or cookies would be discarded.
        return self.context
    def is_connected(self):
        if self._closed:return False
        try:return any(not page.is_closed() for page in self.context.pages)
        except Exception:return False
    def close(self):
        if not self._closed:
            self._closed=True
            try:self.context.close()
            except Exception:pass
