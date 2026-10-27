"""Bounded Outlook login attempts. Credentials remain in memory."""
import os
from pathlib import Path
import shutil
import time
import unicodedata
from urllib.parse import urlsplit


class LoginFailure(Exception):
    pass


class SkipRequested(Exception):
    pass


class RateLimited(LoginFailure):
    pass


class VerificationRequired(LoginFailure):
    pass


def normalized(text):
    return ''.join(c for c in unicodedata.normalize('NFD', text.casefold())
                   if not unicodedata.combining(c))


def password_unavailable(text):
    text = normalized(text).replace('’', "'")
    return any(message in text for message in (
        'password sign-in is not available', 'password sign in is not available',
        "password sign-in isn't available", "password sign in isn't available",
        "password isn't available", 'password is not available',
        "can't sign in with a password", 'cannot sign in with a password',
        'no puedes iniciar sesion con contrasena',
        'no puede iniciar sesion con contrasena',
        'no esta disponible el inicio de sesion con contrasena',
        'el inicio de sesion con contrasena no esta disponible',
        'esta cuenta no tiene una contrasena',
        'la contrasena no esta disponible para iniciar sesion',
        'la contrasena no esta disponible para inicio de sesion',
    ))


def browser_binary(browser):
    commands = {'chrome': ('chrome', 'google-chrome', 'chromium', 'chromium-browser'),
                'edge': ('msedge', 'microsoft-edge'), 'firefox': ('firefox',)}
    for command in commands[browser]:
        found = shutil.which(command)
        if found:
            return found
    relative = {'chrome': 'Google/Chrome/Application/chrome.exe',
                'edge': 'Microsoft/Edge/Application/msedge.exe',
                'firefox': 'Mozilla Firefox/firefox.exe'}[browser]
    for variable in ('PROGRAMFILES', 'PROGRAMFILES(X86)', 'LOCALAPPDATA'):
        base = os.environ.get(variable)
        if base and (Path(base) / relative).is_file():
            return str(Path(base) / relative)
    return None


def available_browsers():
    return [name for name in ('chrome', 'edge', 'firefox') if browser_binary(name)][:2]


def create_driver(browser, headless=False):
    from selenium import webdriver
    os.environ.setdefault('SE_TIMEOUT', '30')
    if browser == 'chrome':
        options = webdriver.ChromeOptions()
        options.add_argument('--incognito')
        constructor = webdriver.Chrome
    elif browser == 'edge':
        options = webdriver.EdgeOptions()
        options.add_argument('--inprivate')
        constructor = webdriver.Edge
    else:
        options = webdriver.FirefoxOptions()
        options.add_argument('-private')
        constructor = webdriver.Firefox
    binary = browser_binary(browser)
    if binary:
        options.binary_location = binary
    if headless:
        options.add_argument('-headless' if browser == 'firefox' else '--headless=new')
    options.page_load_strategy = 'eager'
    driver = constructor(options=options)
    driver.set_page_load_timeout(30)
    driver.set_script_timeout(15)
    return driver


def close_driver(driver):
    if driver is not None:
        try:
            driver.quit()
        except Exception:
            pass


def first_visible(driver, by, selector):
    for element in driver.find_elements(by, selector):
        try:
            if element.is_displayed() and element.is_enabled():
                return element
        except Exception:
            continue
    return None


EMAIL = 'input[type="email"], input[name="loginfmt"], input#i0116'
PASSWORD = 'input#i0118, input[name="passwd"], input[type="password"]'
NEXT = 'input#idSIButton9, button[type="submit"], input[type="submit"]'
OTHER = "//*[self::a or self::button or @role='button'][contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'other ways to sign in') or contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'otras formas de iniciar sesión') or contains(normalize-space(.), 'Opciones de inicio de sesión')]"
USE_PASSWORD = "//*[text()[normalize-space()='Use your password'] or text()[normalize-space()='Usar tu contraseña'] or text()[normalize-space()='Usar la contraseña']]"
STAY_NO = "//input[@id='idBtn_Back' or translate(@value, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz')='no'] | //button[translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz')='no'] | //*[@role='button' and translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz')='no']"
NOTICE_OK = "//button[translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz')='ok'] | //input[translate(@value, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz')='ok'] | //*[@role='button' and translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz')='ok']"


class SpecialPages:
    """Handle the supplied Microsoft screens without retrying a throttle in another browser."""
    def __init__(self, driver, cancelled, report, cooldown=60, clock=None, sleep=None):
        self.driver, self.cancelled, self.report = driver, cancelled, report
        self.cooldown = cooldown
        self.clock = clock or time.monotonic
        self.sleep = sleep or time.sleep
        self.refreshed = False
        self.notice_clicked = False

    def handle(self):
        if self.cancelled():
            raise SkipRequested()
        body = first_visible(self.driver, 'tag name', 'body')
        text = ' '.join(normalized(body.text).split()) if body else ''
        verification_text = text.replace('’', "'")
        if ('almost there' in verification_text
                and urlsplit(self.driver.current_url).hostname in (
                    'login.live.com', 'account.live.com', 'login.microsoftonline.com')
                and any(marker in verification_text for marker in (
                    "just one more step to verify it's you", 'send a code to', 'already have a code'))):
            self.report('Verificación adicional: omitiendo esta cuenta y pasando a la siguiente.')
            raise VerificationRequired('Microsoft solicita verificación adicional')
        if 'too many requests' in text:
            if self.refreshed:
                raise RateLimited('Microsoft sigue limitando solicitudes. Intenta más tarde.')
            self.report('Microsoft limita solicitudes. Espero 60 segundos antes de recargar una vez.')
            started = self.clock()
            end = started + self.cooldown
            while self.clock() < end:
                if self.cancelled():
                    raise RateLimited('Pausa por límite de solicitudes cancelada.')
                self.sleep(min(.25, max(0, end - self.clock())))
            if self.cancelled():
                raise RateLimited('Pausa por límite de solicitudes cancelada.')
            self.refreshed = True
            try:
                self.driver.refresh()
            except Exception:
                raise RateLimited('No se pudo recargar la página limitada por Microsoft.') from None
            return self.clock() - started
        if password_unavailable(text):
            raise LoginFailure('Inicio con contraseña no disponible')
        host = urlsplit(self.driver.current_url).hostname
        if host == 'privacynotice.account.microsoft.com' and not self.notice_clicked:
            button = first_visible(self.driver, 'xpath', NOTICE_OK)
            if button:
                button.click()
                self.notice_clicked = True
                self.report('Aviso de Microsoft: pulsé OK; continuando.')
                return 0
        return None


def inbox_ready(driver):
    url = urlsplit(driver.current_url)
    if url.hostname != 'outlook.live.com' or not url.path.startswith('/mail'):
        return False
    if first_visible(driver, 'css selector', EMAIL + ', ' + PASSWORD):
        return False
    return bool(first_visible(driver, 'css selector',
        '[role="main"], [role="navigation"], [role="tree"], button[aria-label="New mail"], button[aria-label="Correo nuevo"]'))


def open_inbox(account, browser, cancelled, report, driver_factory=create_driver,
               timeout=150, stage_timeout=25):
    """One browser attempt; never interact with MFA or CAPTCHA challenges."""
    driver = None
    deadline = time.monotonic() + timeout
    special = None

    def wait(probe, label):
        nonlocal deadline
        end = min(deadline, time.monotonic() + stage_timeout)
        while time.monotonic() < end:
            if cancelled():
                raise SkipRequested()
            paused = special.handle()
            if paused is not None:
                deadline += paused
                end = min(deadline, end + paused)
                continue
            try:
                result = probe()
            except Exception as error:
                # Stale elements are expected during redirects; real transport
                # errors must remain bounded by the same deadline.
                if isinstance(error, (SkipRequested, LoginFailure)):
                    raise
                result = None
            if result:
                return result
            time.sleep(.25)
        raise LoginFailure('Pantalla no reconocida o tiempo agotado: ' + label)

    try:
        if cancelled():
            raise SkipRequested()
        driver = driver_factory(browser)
        special = SpecialPages(driver, cancelled, report)
        if cancelled():
            raise SkipRequested()
        report('Escribiendo correo')
        driver.get('https://login.live.com/')
        field = wait(lambda: first_visible(driver, 'css selector', EMAIL), 'correo')
        field.clear()
        field.send_keys(account.address)
        wait(lambda: first_visible(driver, 'css selector', NEXT), 'siguiente').click()
        other_clicked = False
        password_clicked = False

        def password_step():
            nonlocal other_clicked, password_clicked
            field = first_visible(driver, 'css selector', PASSWORD)
            if field:
                return field
            option = first_visible(driver, 'xpath', USE_PASSWORD)
            if option and not password_clicked:
                try:
                    option.click()
                except Exception:
                    driver.execute_script("const el=arguments[0]; (el.closest('button,a,[role=button],[tabindex]') || el).click();", option)
                password_clicked = True
            elif not other_clicked:
                other = first_visible(driver, 'xpath', OTHER)
                if other:
                    other.click()
                    other_clicked = True
            return None

        report('Esperando inicio con contraseña')
        field = wait(password_step, 'contraseña')
        field.clear()
        field.send_keys(account.password)
        wait(lambda: first_visible(driver, 'css selector', NEXT), 'iniciar sesión').click()
        report('Esperando respuesta de Microsoft')

        def signed_in():
            if inbox_ready(driver):
                return 'inbox'
            no = first_visible(driver, 'xpath', STAY_NO)
            if no:
                return no
            if urlsplit(driver.current_url).hostname == 'outlook.live.com':
                return 'redirect'
            return None

        result = wait(signed_in, 'confirmación de acceso')
        if result not in ('inbox', 'redirect'):
            result.click()
            def left_prompt():
                try:
                    return not result.is_displayed()
                except Exception:
                    return True
            wait(left_prompt, 'salida de mantener sesión')
        if not inbox_ready(driver):
            driver.get('https://outlook.live.com/mail/0/inbox')
        wait(lambda: inbox_ready(driver), 'bandeja de entrada')
        if cancelled():
            raise SkipRequested()
        return driver
    except BaseException:
        close_driver(driver)
        raise


def try_account(account, browsers, cancelled, report, attempt=None):
    """Try each selected browser once; caller decides when to advance accounts."""
    attempt = open_inbox if attempt is None else attempt
    for index, browser in enumerate(browsers[:2]):
        if cancelled():
            raise SkipRequested()
        report('Probando ' + browser)
        try:
            return attempt(account, browser, cancelled, report)
        except SkipRequested:
            raise
        except RateLimited:
            raise
        except VerificationRequired:
            raise
        except Exception:
            # Do not log Selenium exception strings: they can contain credentials.
            suffix = '; probando alternativa' if index + 1 < min(2, len(browsers)) else '; intentos agotados'
            report(browser + ': no se completó el acceso' + suffix)
    raise LoginFailure('No se pudo iniciar sesión en los navegadores disponibles')
