"""Append-only results. Never receives account objects or passwords."""
import csv
from datetime import datetime
import os
from pathlib import Path
import sys
import threading


FIELDS = ('fecha', 'correo', 'resultado', 'detalle')
RESULTS = ('Entró a la bandeja', 'No logró entrar', 'Omitido', 'Interrumpido')
GROUPS = ('Entraron a la bandeja', 'Con inconvenientes', 'Omitidos')


def group_results(rows):
    """One entry per address, using its latest recorded attempt."""
    latest = {}
    for row in rows:
        address = (row.get('correo') or '').strip()
        if address:
            key = address.casefold()
            latest.pop(key, None)
            latest[key] = row
    grouped = {name: [] for name in GROUPS}
    for row in reversed(list(latest.values())):
        result = row.get('resultado', '')
        detail = (row.get('detalle') or '').casefold()
        verification = 'almost there' in detail or ('verificaci' in detail and 'adicional' in detail)
        if result == 'Entró a la bandeja':
            category = GROUPS[0]
        elif result == 'Omitido' or (result == 'No logró entrar' and verification):
            category = GROUPS[2]
        else:
            category = GROUPS[1]
        grouped[category].append(row)
    return grouped


def history_path():
    if sys.platform == 'win32':
        base = os.environ.get('LOCALAPPDATA') or os.environ.get('APPDATA')
        root = Path(base) if base else Path.home() / 'AppData' / 'Local'
        return root / 'GestoriaDiazOutlook' / 'registro_correos.csv'
    return Path(__file__).resolve().parent / 'registros' / 'registro_correos.csv'


def spreadsheet_value(value):
    return "'" + value if value.startswith(('=', '+', '-', '@', '\t', '\r')) else value


class HistoryStore:
    def __init__(self, path=None):
        self.path = Path(path) if path is not None else history_path()
        self._lock = threading.Lock()

    def append(self, address, result, detail):
        if result not in RESULTS:
            raise ValueError('Resultado desconocido')
        # Exact allowlist: credential data is never accepted as a record dict.
        row = dict(zip(FIELDS, (datetime.now().astimezone().isoformat(timespec='seconds'),
                               address, result, detail)))
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            new = not self.path.exists() or self.path.stat().st_size == 0
            with self.path.open('a', newline='', encoding='utf-8-sig') as output:
                writer = csv.DictWriter(output, fieldnames=FIELDS)
                if new:
                    writer.writeheader()
                writer.writerow({key: spreadsheet_value(value) for key, value in row.items()})

    def read(self):
        with self._lock:
            if not self.path.exists():
                return []
            with self.path.open(newline='', encoding='utf-8-sig') as source:
                rows = list(csv.DictReader(source))
            # Restore formula-protected addresses only for on-screen display;
            # export copies the protected CSV unchanged.
            for row in rows:
                email = row.get('correo', '')
                if email.startswith("'") and email[1:].startswith(('=', '+', '-', '@', '\t', '\r')):
                    row['correo'] = email[1:]
            return rows

    def export(self, destination):
        target = Path(destination)
        with self._lock:
            if target.resolve() == self.path.resolve():
                return
            if self.path.exists():
                data = self.path.read_bytes()
            else:
                data = ('\ufeff' + ','.join(FIELDS) + '\r\n').encode('utf-8')
            target.write_bytes(data)
