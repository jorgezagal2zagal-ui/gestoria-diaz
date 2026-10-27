import json
import os
from pathlib import Path
import re
import shutil
import sys
import time
import uuid


def data_directory():
    if sys.platform == 'win32':
        base = os.environ.get('LOCALAPPDATA') or os.environ.get('APPDATA')
        return (Path(base) if base else Path.home() / 'AppData' / 'Local') / 'GestoriaDiazPuente'
    return Path(__file__).resolve().parents[1] / '.datos_conexion'


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        fd = os.open(str(temporary), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def read_json(path):
    try:
        path = Path(path)
        if path.stat().st_size > 65536:
            return None
        value = json.loads(path.read_text(encoding='utf-8'))
        return value if isinstance(value, dict) else None
    except (OSError, ValueError):
        return None


class Bridge:
    def __init__(self, root=None):
        self.root = Path(root) if root is not None else data_directory()

    def publish(self, emails, active):
        write_json(self.root / 'outlook.json', {'at': time.time(), 'emails': list(emails), 'active': active})

    def presence(self):
        info = read_json(self.root / 'outlook.json')
        return info if info and time.time() - info.get('at', 0) < 6 and info.get('active') else None

    def create(self, email, instance, sender, subject):
        if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', sender) or not subject.strip():
            raise ValueError('Configura el remitente completo y el asunto del mensaje del IMSS.')
        key = uuid.uuid4().hex
        job = self.job(key)
        write_json(job / 'request.json', {'id': key, 'email': email, 'instance': instance,
            'sender': sender.strip().casefold(), 'subject': subject.strip(),
            'created': time.time(), 'expires': time.time() + 540})
        return key

    def job(self, key):
        if not re.fullmatch(r'[a-f0-9]{32}', key):
            raise ValueError('Solicitud local inválida')
        return self.root / 'solicitudes' / key

    def pending(self):
        parent = self.root / 'solicitudes'
        if not parent.exists():
            return []
        result = []
        for directory in parent.iterdir():
            if not re.fullmatch(r'[a-f0-9]{32}', directory.name) or not directory.is_dir():
                continue
            request = read_json(directory / 'request.json')
            if not request:
                continue
            if request.get('expires', 0) < time.time() or (directory / 'finished.json').exists():
                shutil.rmtree(directory, ignore_errors=True)
            elif not (directory / 'response.json').exists():
                result.append(request)
        return sorted(result, key=lambda row: row['created'])

    def reply(self, key, status, **values):
        request = read_json(self.job(key) / 'request.json')
        if request and request.get('expires', 0) > time.time() and not self.cancelled(key):
            write_json(self.job(key) / 'response.json', {'id': key, 'email': request['email'],
                'instance': request['instance'], 'status': status, **values})
            if self.cancelled(key):
                (self.job(key) / 'response.json').unlink(missing_ok=True)

    def response(self, key):
        return read_json(self.job(key) / 'response.json')

    def started(self, key):
        write_json(self.job(key) / 'started.json', {'at': time.time()})

    def finish(self, key):
        try:
            descriptor = os.open(str(self.job(key) / 'finished.json'), os.O_CREAT | os.O_WRONLY, 0o600)
            os.close(descriptor)
            (self.job(key) / 'response.json').unlink(missing_ok=True)
        except FileNotFoundError:
            pass

    def cancelled(self, key):
        return (self.job(key) / 'finished.json').exists()
