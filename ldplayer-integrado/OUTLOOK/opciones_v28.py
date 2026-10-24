# -*- coding: utf-8 -*-
"""Responde solo a invitaciones OPCIONALES visibles en páginas oficiales.

Nunca entra en MFA, contraseña olvidada, CAPTCHA, bloqueo ni cambio de datos
sensibles de Microsoft. No crea ni acepta claves de paso.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
import re
from urllib.parse import urlparse

AUTH_HOSTS = {'login.microsoft.com', 'login.live.com', 'account.microsoft.com'}
OUTLOOK_HOSTS = {'outlook.live.com', 'outlook.office.com'}
PASSKEY_CREATE = re.compile(r'/fido/create/?$', re.I)
PASSKEY_SETUP = re.compile(
    r'configurando la clave de paso|configurar(?: una| la)? clave de paso|'
    r'setting up (?:your|a) passkey|create(?: a| your) passkey', re.I)
RECOVERY_OFFER = re.compile(r'keep access to your account with a recovery method|'
                            r'mant[eé]n el acceso a tu cuenta con un m[eé]todo de recuperaci[oó]n', re.I)
NOT_NOW = re.compile(r'^\s*(?:not now|ahora no|en otro momento)\s*$', re.I)
CANCEL = re.compile(r'^\s*(?:cancelar|cancel|no|not now|ahora no)\s*$', re.I)


def _on_create_page(page):
    url=urlparse(getattr(page, 'url', ''))
    return (url.scheme == 'https' and (url.hostname or '').lower() in AUTH_HOSTS
            and bool(PASSKEY_CREATE.search(url.path)))


def _on_outlook_page(page):
    url=urlparse(getattr(page, 'url', ''))
    return (url.scheme == 'https' and (url.hostname or '').lower() in OUTLOOK_HOSTS
            and url.path.lower().startswith('/mail'))


def _click_visible_button(page, expected):
    """Never click unless a button has exact intended text, not any arbitrary No."""
    for role in ('button',):
        loc=page.get_by_role(role,name=expected)
        for i in range(min(loc.count(),5)):
            button=loc.nth(i)
            if button.is_visible() and button.is_enabled():
                button.click(timeout=2500)
                return True
    return False


def decline_web_passkey_setup(page):
    """Only CANCEL *creating* a new passkey on Microsoft's official create URL."""
    if not _on_create_page(page):return False
    try:
        text=(page.locator('body').inner_text(timeout=1000) or '')[:5500]
        if not PASSKEY_SETUP.search(text):return False
        if _click_visible_button(page,CANCEL):return True
        # Some Microsoft forms expose an input or div role=button instead of
        # a semantic <button>. Verify its exact label and official create URL.
        locator=page.locator('button, input[type="button"], input[type="submit"], [role="button"]')
        for i in range(min(locator.count(),15)):
            element=locator.nth(i)
            if not element.is_visible() or not element.is_enabled():continue
            label=(element.inner_text(timeout=600) or '').strip()
            if not label:
                label=(element.get_attribute('value',timeout=600) or '').strip()
            if CANCEL.fullmatch(label):
                element.click(timeout=2500)
                return True
        return False
    except Exception:return False


def decline_optional_recovery(page):
    """Rechaza únicamente el ofrecimiento opcional de recuperación de Outlook.

    Outlook puede renderizar "Not now" como enlace, texto clicable o dentro
    de un iframe. La comprobación se hace en el mismo marco y sólo en una
    página oficial del buzón. Jamás se responden desafíos MFA de Microsoft.
    """
    if not _on_outlook_page(page):
        return False
    try:
        frames=[page]
        for frame in (getattr(page,'frames',None) or []):
            if frame is not page:
                frames.append(frame)
        for frame in frames[:12]:
            try:
                body=(frame.locator('body').inner_text(timeout=850) or '')[:7500]
                if not RECOVERY_OFFER.search(body):
                    continue
                # May be a button, a link, or a semantically unmarked text node.
                for role in ('button','link'):
                    loc=frame.get_by_role(role,name=NOT_NOW)
                    for i in range(min(loc.count(),6)):
                        target=loc.nth(i)
                        if target.is_visible() and target.is_enabled():
                            target.click(timeout=2200)
                            return True
                loc=frame.get_by_text(NOT_NOW,exact=True)
                for i in range(min(loc.count(),6)):
                    target=loc.nth(i)
                    if target.is_visible() and target.is_enabled():
                        target.click(timeout=2200)
                        return True
            except Exception:
                continue
        return False
    except Exception:
        return False


def prepare_browser_preferences(folder):
    """Bot-owned profile only; block password prompts and external-handler offers.

    This does not change the user's normal Chrome, shared IMSS pool, saved
    Microsoft cookies, or stored bot credentials. Preferences are local.
    """
    path=Path(folder)
    prefs=path/'Default'/'Preferences'
    prefs.parent.mkdir(parents=True,exist_ok=True)
    try:
        with prefs.open(encoding='utf-8') as f:data=json.load(f)
        if not isinstance(data,dict):return False
    except FileNotFoundError:
        data={}
    except (ValueError, OSError):
        # Never overwrite an existing profile if its preferences are damaged.
        return False
    data['credentials_enable_service']=False
    data['translate']={'enabled':False, **{k:v for k,v in data.get('translate',{}).items() if k!='enabled'}} if isinstance(data.get('translate'),dict) else {'enabled':False}
    profile=data.setdefault('profile',{})
    if not isinstance(profile,dict):return False
    profile['password_manager_enabled']=False
    content=profile.setdefault('default_content_setting_values',{})
    if not isinstance(content,dict):return False
    # Notifications and registerProtocolHandler prompts are not needed to read an Inbox.
    content['notifications']=2
    content['protocol_handlers']=2
    temp=prefs.with_name('Preferences.bot_v28.tmp')
    try:
        temp.write_text(json.dumps(data,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
        os.replace(temp,prefs)
        return True
    finally:
        try:temp.unlink(missing_ok=True)
        except OSError:pass
