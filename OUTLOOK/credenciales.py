# -*- coding: utf-8 -*-
"""Lista de correos y claves guardadas con Windows DPAPI bajo el usuario actual.
No se transmiten contraseñas al puente local ni se imprimen en registros.
"""
from __future__ import annotations
import ctypes
from ctypes import wintypes
import os
import re
import sqlite3
from pathlib import Path
from core import EMAIL_RE, data_dir

class Blob(ctypes.Structure):
    _fields_ = [('cbData', wintypes.DWORD), ('pbData', ctypes.POINTER(ctypes.c_ubyte))]

class WindowsDPAPI:
    def __init__(self):
        if os.name != 'nt':
            raise RuntimeError('La caja fuerte de contraseñas solamente funciona en Windows.')
        self.crypt32 = ctypes.WinDLL('crypt32', use_last_error=True)
        self.kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
        self.crypt32.CryptProtectData.argtypes = [ctypes.POINTER(Blob), wintypes.LPCWSTR,
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
        self.crypt32.CryptProtectData.restype = wintypes.BOOL
        self.crypt32.CryptUnprotectData.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p,
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
        self.crypt32.CryptUnprotectData.restype = wintypes.BOOL
        self.kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        self.kernel32.LocalFree.restype = ctypes.c_void_p

    @staticmethod
    def _blob(raw):
        b = ctypes.create_string_buffer(raw)
        blob = Blob(len(raw), ctypes.cast(b, ctypes.POINTER(ctypes.c_ubyte)))
        return b, blob

    def _operate(self, raw, encrypt):
        buf, inp = self._blob(raw)
        out = Blob()
        fn = self.crypt32.CryptProtectData if encrypt else self.crypt32.CryptUnprotectData
        ok = (fn(ctypes.byref(inp), 'GestoriaDiaz Outlook', None, None, None, 0x1, ctypes.byref(out))
              if encrypt else fn(ctypes.byref(inp), None, None, None, None, 0x1, ctypes.byref(out)))
        if not ok: raise ctypes.WinError(ctypes.get_last_error())
        try: return ctypes.string_at(out.pbData, out.cbData)
        finally: self.kernel32.LocalFree(ctypes.cast(out.pbData, ctypes.c_void_p))

    def protect(self, plain):
        return self._operate(plain.encode('utf-8'), True)

    def unprotect(self, encrypted):
        return self._operate(encrypted, False).decode('utf-8')


def parse_list(text):
    """Parsea email | clave, email:clave, CSV y email solo. Mantiene las claves completas.
    No imprime contraseñas ni las escribe fuera del almacén cifrado.
    """
    output = {}
    for raw in text.splitlines():
        line = raw.strip().lstrip('\ufeff')
        if not line or line.startswith('#'): continue
        m = EMAIL_RE.search(line)
        if not m: continue
        address = m.group(0).lower()
        prefix = line[:m.start()].strip()
        # No aceptar la línea donde el correo está incrustado en otros campos complejos.
        if prefix and not re.fullmatch(r'(?i)(?:\d+[.)-]?|correo|email|cuenta|usuario|account|[\s,;:\-|])*', prefix):
            continue
        tail = line[m.end():].strip()
        tail = re.sub(r'^[|;,:\t\-\s]+', '', tail)
        tail = re.sub(r'(?i)^(?:(?:contraseñ?a|contra|password|passwd|clave|pass|pwd)\s*[:=]\s*)', '', tail).strip()
        # Una dirección sola NO borra una clave guardada anteriormente.
        password = tail if tail else None
        output[address] = password if password is not None else output.get(address)
    return list(output.items())


def decode_file(path):
    raw = Path(path).read_bytes()
    if len(raw) > 5_000_000: raise ValueError('Archivo mayor de 5 MB.')
    for enc in ('utf-8-sig', 'utf-16', 'cp1252'):
        try:
            data = raw.decode(enc)
            if '\x00' not in data: return parse_list(data)
        except UnicodeError: pass
    raise ValueError('No se puede leer este archivo.')

class Vault:
    def __init__(self, protector=None, path=None):
        self.protector = protector or WindowsDPAPI()
        self.path = str(path or (data_dir() / 'claves_dpapi.sqlite3'))
        with self._db() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS credenciales (
                email TEXT PRIMARY KEY, secreto BLOB, actualizado TEXT DEFAULT CURRENT_TIMESTAMP)""")
            db.execute("""CREATE TABLE IF NOT EXISTS preferencias_cifradas (
                nombre TEXT PRIMARY KEY, secreto BLOB NOT NULL)""")

    def _db(self):
        return sqlite3.connect(self.path, timeout=10)

    def save(self, accounts):
        """Guarda nuevas cuentas y contraseñas; un email sin clave conserva la previa."""
        with self._db() as db:
            for addr,password in accounts:
                addr = addr.strip().lower()
                if not EMAIL_RE.fullmatch(addr): continue
                if password is None:
                    db.execute('INSERT OR IGNORE INTO credenciales(email) VALUES (?)', (addr,))
                else:
                    if not password or len(password)>1024: raise ValueError('Contraseña vacía o demasiado larga')
                    encrypted=self.protector.protect(password)
                    db.execute("""INSERT INTO credenciales(email,secreto) VALUES(?,?)
                        ON CONFLICT(email) DO UPDATE SET secreto=excluded.secreto,actualizado=CURRENT_TIMESTAMP""",
                        (addr, encrypted))

    def set_common_password(self, password):
        """Contraseña única para todas las cuentas; solo se persiste el BLOB DPAPI."""
        if not isinstance(password, str) or not password or len(password)>1024:
            raise ValueError('Contraseña vacía o demasiado larga')
        encrypted = self.protector.protect(password)
        with self._db() as db:
            db.execute("""INSERT INTO preferencias_cifradas(nombre,secreto)
                VALUES ('password_comun',?) ON CONFLICT(nombre)
                DO UPDATE SET secreto=excluded.secreto""", (encrypted,))

    def has_common_password(self):
        with self._db() as db:
            return db.execute("SELECT 1 FROM preferencias_cifradas WHERE nombre='password_comun'").fetchone() is not None

    def clear_common_password(self):
        """Deja de usar la común y conserva las claves individuales anteriores."""
        with self._db() as db:
            db.execute("DELETE FROM preferencias_cifradas WHERE nombre='password_comun'")

    def _password_secret(self, email):
        address = email.strip().lower()
        if not EMAIL_RE.fullmatch(address):
            return None
        with self._db() as db:
            # La común tiene prioridad para TODOS los correos, actuales y futuros.
            r=db.execute("SELECT secreto FROM preferencias_cifradas WHERE nombre='password_comun'").fetchone()
            if r is None:
                r=db.execute('SELECT secreto FROM credenciales WHERE email=?',(address,)).fetchone()
        return r[0] if r else None

    def password(self, email):
        secret = self._password_secret(email)
        return self.protector.unprotect(secret) if secret is not None else None

    def has_password(self,email):
        return self._password_secret(email) is not None

    def remove(self,email):
        with self._db() as db: db.execute('DELETE FROM credenciales WHERE email=?',(email.lower(),))
