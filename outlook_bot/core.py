"""Parsing and read-only Gmail OTP access. No credential persistence."""
import re
from dataclasses import dataclass

@dataclass
class Account:
    address: str
    password: str

def parse_accounts(text):
    accounts, seen = [], set()
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith('#') or re.fullmatch(r'[-_=*]{3,}', line):
            continue
        line = re.sub(r'^Account\s*:\s*', '', line, flags=re.I)
        match = re.match(r'^([^\s:;|]+@[^\s:;|]+)\s*[:;|\t](.*)$', line)
        if not match or not match.group(2):
            raise ValueError(f'Línea {n}: usa correo:contraseña. No se importó el archivo.')
        address, password = match.groups()
        if address.lower() in seen:
            raise ValueError(f'Línea {n}: correo duplicado. Elimina el duplicado.')
        seen.add(address.lower())
        accounts.append(Account(address, password))
    if not accounts:
        raise ValueError('El TXT no contiene cuentas.')
    return accounts


def merge_accounts(existing, incoming):
    result = list(existing)
    seen = {a.address.lower() for a in existing}
    added = 0
    for account in incoming:
        if account.address.lower() not in seen:
            result.append(account); seen.add(account.address.lower()); added += 1
    return result, added


def save_pending(path, accounts):
    from pathlib import Path
    path = Path(path)
    temp = path.with_suffix(path.suffix + '.tmp')
    text = ''.join('Account: ' + a.address + ':' + a.password + '\n' for a in accounts)
    temp.write_text(text, encoding='utf-8')
    temp.replace(path)


def load_pending(path):
    from pathlib import Path
    path = Path(path)
    if not path.exists(): return []
    text = path.read_text(encoding='utf-8-sig')
    return parse_accounts(text) if text.strip() else []
