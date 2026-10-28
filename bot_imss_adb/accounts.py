"""Catálogo de cuentas en memoria y exportaciones de direcciones sin contraseñas."""
from dataclasses import dataclass, field
import re

try:
    from .storage import atomic_text
except ImportError:
    from storage import atomic_text


@dataclass(frozen=True)
class Account:
    address: str
    password: str = field(default="", repr=False)


def valid_address(address):
    return bool(len(address) <= 254 and re.fullmatch(r"[A-Za-z0-9._+\-]{1,64}@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", address))


def parse_accounts(text):
    accounts, seen = [], set()
    for number, raw in enumerate(text.lstrip("\ufeff").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#") or re.fullmatch(r"[-_=*]{3,}", line):
            continue
        line = re.sub(r"^Account\s*:\s*", "", line, flags=re.I)
        match = re.fullmatch(r"([^\s:;|]+@[^\s:;|]+)\s*[:;|\t](.*)", line)
        address, password = match.groups() if match else (line, "")
        address = address.strip()
        if not valid_address(address) or (match and not password):
            raise ValueError(f"Línea {number}: usa correo:contraseña, o solo correo para el modo manual.")
        if address.casefold() in seen:
            raise ValueError(f"Línea {number}: hay un correo duplicado. No se importó el archivo.")
        seen.add(address.casefold())
        accounts.append(Account(address, password))
        if len(accounts) > 50000:
            raise ValueError("Importa como máximo 50 000 cuentas.")
    if not accounts:
        raise ValueError("El archivo no contiene correos válidos.")
    return accounts


class Catalog:
    def __init__(self):
        self.accounts = {}
        self.omitted = set()

    def merge(self, accounts):
        merged = dict(self.accounts)
        for account in accounts:
            previous = merged.get(account.address.casefold())
            if previous is None or account.password:
                merged[account.address.casefold()] = account
        if len(merged) > 50000:
            raise ValueError("El catálogo admite hasta 50 000 cuentas.")
        added = len(merged) - len(self.accounts)
        self.accounts = merged
        return added

    def get(self, address):
        return self.accounts.get(address.strip().casefold())

    def next(self, current=""):
        keys = list(self.accounts)
        if current.casefold() in keys:
            offset = keys.index(current.casefold()) + 1
            keys = keys[offset:] + keys[:offset]
        return next((self.accounts[k] for k in keys if k not in self.omitted and k != current.casefold()), None)

    def export(self, path, selected=None):
        wanted = None if selected is None else {value.casefold() for value in selected}
        rows = [account.address for key, account in self.accounts.items() if wanted is None or key in wanted]
        export_addresses(path, rows)
        return len(rows)


def export_addresses(path, addresses):
    # One address per line. TXT files never contain password/PIN/OTP values.
    rows, seen = [], set()
    for address in addresses:
        if not valid_address(address):
            raise ValueError("La lista contiene un correo inválido; no se exportó.")
        if address.casefold() not in seen:
            seen.add(address.casefold())
            rows.append(address)
    with atomic_text(path, "utf-8") as stream:
        stream.write("".join(address + "\n" for address in rows))
