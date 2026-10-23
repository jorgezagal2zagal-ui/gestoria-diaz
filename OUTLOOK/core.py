# -*- coding: utf-8 -*-
"""Gestoría Díaz - núcleo de Outlook de prueba. No guarda contraseñas."""
from __future__ import annotations
import base64
from contextlib import contextmanager
import json
import os
import re
import secrets
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

DEFAULT_CLIENT_ID = os.environ.get('GESTORIA_DIAZ_MS_APP_ID', '').strip()
EMAIL_RE = re.compile(r'(?i)(?<![\w.+-])([\w.+-]+@[\w.-]+\.[a-z]{2,})(?![\w.-])')
OTP_RE = re.compile(r'(?i)(?:c[oó]digo(?:\s+de\s+(?:verificaci[oó]n|confirmaci[oó]n|acceso|seguridad))?|verification\s+code|security\s+code|clave\s+de\s+(?:acceso|verificaci[oó]n))\s*(?::|es|=|\-|\s){0,8}([0-9]{4,8})(?![0-9])')
GRAPH = 'https://graph.microsoft.com/v1.0'
SCOPES = ['User.Read', 'Mail.Read']
MAX_PDF = 15 * 1024 * 1024


def utcnow():
    return datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00','Z')


def parse_time(value):
    return datetime.fromisoformat(str(value).replace('Z', '+00:00')).astimezone(timezone.utc)


def data_dir():
    base = Path(os.environ.get('LOCALAPPDATA') or str(Path.home())) / 'GestoriaDiaz' / 'OutlookV1'
    base.mkdir(parents=True, exist_ok=True)
    return base


def parse_import(path):
    data = Path(path).read_bytes()
    if len(data) > 5_000_000:
        raise ValueError('Archivo mayor de 5 MB. Divide el archivo en partes.')
    for enc in ('utf-8-sig','utf-16','cp1252'):
        try:
            raw = data.decode(enc)
            if '\x00' not in raw:
                break
        except UnicodeError:
            continue
    else:
        raise ValueError('No se pudo leer el TXT/CSV.')
    unique = dict.fromkeys(m.lower() for m in EMAIL_RE.findall(raw))
    return list(unique)


def extract_code(text):
    found = OTP_RE.search(text or '')
    return found.group(1) if found else None


def eligible(message, sender, after):
    """Remitente EXACTO y mensaje recibido no antes del inicio de solicitud."""
    actual = ((message.get('from') or {}).get('emailAddress') or {}).get('address', '').lower()
    if not sender or actual != sender.strip().lower():
        return False
    try:
        return parse_time(message['receivedDateTime']) >= parse_time(after)
    except (ValueError, KeyError, TypeError):
        return False


def validate_pdf(content):
    return bool(content and len(content) <= MAX_PDF and content[:5] == b'%PDF-')


class AddressBook:
    def __init__(self, path=None):
        self.path = str(path or (data_dir() / 'correos.sqlite3'))
        self.lock = threading.RLock()
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS cuentas (email TEXT PRIMARY KEY, estado TEXT NOT NULL DEFAULT "PENDIENTE", ultimo_error TEXT DEFAULT "")')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def add(self, emails):
        count = 0
        with self.lock, self.connect() as db:
            for email in emails:
                e = email.lower().strip()
                if not EMAIL_RE.fullmatch(e):
                    continue
                c = db.execute('INSERT OR IGNORE INTO cuentas(email) VALUES (?)', (e,))
                count += c.rowcount
        return count

    def all(self):
        with self.lock, self.connect() as db:
            return [dict(x) for x in db.execute('SELECT email,estado,ultimo_error FROM cuentas ORDER BY email')]

    def set_status(self, email, status, error=''):
        if status not in ('PENDIENTE','AUTORIZADO','REAUTORIZAR','RETIRADO'):
            raise ValueError('Estado inválido')
        with self.lock, self.connect() as db:
            db.execute('UPDATE cuentas SET estado=?,ultimo_error=? WHERE email=?', (status,error[:180],email.lower().strip()))

    def counts(self):
        entries = self.all()
        return {'total':len(entries),'autorizados':sum(x['estado']=='AUTORIZADO' for x in entries),
                'pendientes':sum(x['estado']=='PENDIENTE' for x in entries),
                'reautorizacion':sum(x['estado']=='REAUTORIZAR' for x in entries)}


def local_secret():
    path = data_dir() / 'llave_puente_local.txt'
    if not path.exists():
        path.write_text(secrets.token_urlsafe(36), encoding='utf-8')
        try: os.chmod(path, 0o600)
        except OSError: pass
    return path.read_text(encoding='utf-8').strip()


class OutlookService:
    """OAuth delegado. Tokens cifrados con DPAPI y disponibles solo en el usuario Windows."""
    def __init__(self, client_id=DEFAULT_CLIENT_ID):
        try:
            import msal
            import requests
            from msal_extensions import FilePersistenceWithDataProtection, PersistedTokenCache
        except ImportError as exc:
            raise RuntimeError('Faltan dependencias: ejecuta INSTALAR.bat.') from exc
        if os.name != 'nt':
            raise RuntimeError('El acceso real requiere Windows por cifrado DPAPI.')
        if not re.fullmatch('[0-9a-fA-F-]{36}', client_id):
            raise ValueError('Client ID inválido')
        self.requests = requests
        self.lock = threading.RLock()
        self.persistence = FilePersistenceWithDataProtection(str(data_dir() / ('msal_'+client_id+'.bin')))
        self.cache = PersistedTokenCache(self.persistence)
        self.app = msal.PublicClientApplication(client_id,authority='https://login.microsoftonline.com/consumers',token_cache=self.cache)

    def account(self,email):
        email=email.strip().lower()
        return next((a for a in self.app.get_accounts() if a.get('username','').lower()==email),None)

    def authorize(self,email,on_device_code,cancel=None):
        # Mantener el flujo de Microsoft: el titular confirma acceso y permisos.
        with self.lock:
            flow=self.app.initiate_device_flow(scopes=SCOPES)
        if not flow.get('user_code'):
            raise RuntimeError('Microsoft no entregó código: '+str(flow.get('error_description') or flow))
        on_device_code(flow.get('verification_uri','https://microsoft.com/devicelogin'),flow['user_code'])
        def stop(f):
            return bool(cancel and cancel.is_set()) or time.time() >= f.get('expires_at',0)
        result=self.app.acquire_token_by_device_flow(flow,exit_condition=stop)
        if cancel and cancel.is_set():
            raise RuntimeError('Secuencia detenida por el usuario.')
        if 'access_token' not in result:
            raise RuntimeError('Microsoft no autorizó el acceso: '+str(result.get('error_description') or result.get('error','Sin detalles'))[:250])
        actual=self._request(result['access_token'],'/me',{'$select':'mail,userPrincipalName'})
        known={str(v).lower() for v in (actual.get('mail'),actual.get('userPrincipalName'),(result.get('id_token_claims') or {}).get('preferred_username')) if v}
        if email.strip().lower() not in known or not self.account(email):
            # No asociar una sesión de otra cuenta al correo solicitado.
            for acc in self.app.get_accounts():
                if acc.get('username','').lower() != email.strip().lower():
                    self.app.remove_account(acc)
            raise RuntimeError('Cuenta diferente: Microsoft autorizó otra dirección. Repite con '+email)
        return actual

    def token(self,email):
        with self.lock:
            account=self.account(email)
            if account is None:
                raise RuntimeError('Cuenta sin autorización inicial.')
            token=self.app.acquire_token_silent(SCOPES,account=account)
        if not token or not token.get('access_token'):
            raise RuntimeError('Autorización vencida o revocada. Autoriza de nuevo.')
        return token['access_token']

    def _request(self,token,path,params=None):
        if not path.startswith('/'):
            raise ValueError('Ruta inválida')
        for retry in range(3):
            resp=self.requests.get(GRAPH+path,headers={'Authorization':'Bearer '+token,
                                   'Accept':'application/json','Prefer':'outlook.body-content-type="text"'},
                                   params=params,timeout=30)
            if resp.status_code in (429,503,504):
                try: delay=min(20,max(1,int(resp.headers.get('Retry-After','3'))))
                except ValueError: delay=3
                time.sleep(delay)
                continue
            if resp.status_code==401:
                raise RuntimeError('Microsoft rechazó el token. Reautoriza la cuenta.')
            if not resp.ok:
                raise RuntimeError('Microsoft Graph HTTP '+str(resp.status_code)+': '+resp.text[:250])
            return resp.json()
        raise RuntimeError('Microsoft está limitando las consultas temporalmente (429/503).')

    def messages(self,email,limit=35):
        return self._request(self.token(email),'/me/mailFolders/inbox/messages',
                            {'$top':max(1,min(50,int(limit))),
                             '$select':'id,subject,bodyPreview,from,receivedDateTime,hasAttachments',
                             '$orderby':'receivedDateTime desc'}).get('value',[])

    def code(self,email,sender,after):
        if not EMAIL_RE.fullmatch(sender.strip()):
            raise ValueError('Configura primero el remitente EXACTO de los códigos.')
        token=self.token(email)
        for m in self.messages(email):
            if not eligible(m,sender,after):
                continue
            data=self._request(token,'/me/messages/'+quote(m['id'],safe=''),
                {'$select':'subject,body,from,receivedDateTime'})
            msg=(data.get('subject') or '')+'\n'+((data.get('body') or {}).get('content') or '')
            code=extract_code(msg)
            if code:
                return {'code':code,'subject':data.get('subject',''),'received':data.get('receivedDateTime'),
                        'message_id':m['id']}
        return None

    def pdf_candidates(self,email,sender,after):
        if not EMAIL_RE.fullmatch(sender.strip()):
            raise ValueError('Configura primero el remitente EXACTO del documento.')
        token=self.token(email)
        out=[]
        for m in self.messages(email):
            if not eligible(m,sender,after) or not m.get('hasAttachments'): continue
            attachments=self._request(token,'/me/messages/'+quote(m['id'],safe='')+'/attachments',{'$top':25}).get('value',[])
            for item in attachments:
                if item.get('@odata.type')=='#microsoft.graph.fileAttachment' and str(item.get('name','')).lower().endswith('.pdf'):
                    out.append({'email':email, 'message_id':m['id'],'attachment_id':item['id'],
                                'name':item['name'],'subject':m.get('subject',''), 'received':m.get('receivedDateTime')})
        return out

    def get_pdf(self,email,sender,after,message_id,attachment_id):
        token=self.token(email)
        # Verificar nuevamente el mensaje que pertenece a la cuenta y remitente, y que es nuevo.
        m=self._request(token,'/me/messages/'+quote(message_id,safe=''),
                        {'$select':'id,from,receivedDateTime'})
        if not eligible(m,sender,after):
            raise PermissionError('PDF bloqueado: remitente o fecha no coinciden con la solicitud.')
        attachment=self._request(token,'/me/messages/'+quote(message_id,safe='')+'/attachments/'+quote(attachment_id,safe=''))
        if attachment.get('@odata.type') != '#microsoft.graph.fileAttachment' or not str(attachment.get('name','')).lower().endswith('.pdf'):
            raise ValueError('No es un PDF adjunto de Microsoft Graph.')
        body=base64.b64decode(attachment.get('contentBytes',''),validate=True)
        if not validate_pdf(body):
            raise ValueError('Archivo inválido o mayor de 15 MB.')
        return body

    def forget(self,email):
        with self.lock:
            ac=self.account(email)
            if ac: self.app.remove_account(ac)
