"""Comprobar SHA-256 de todos los archivos distribuidos, sin ejecutar su contenido."""
import hashlib
import json
from pathlib import Path


def main():
    root = Path(__file__).resolve().parent
    entries = json.loads((root/'MANIFIESTO_ENTREGA_SHA256.json').read_text(encoding='utf-8'))
    for name, expected in entries.items():
        path = root/name
        if not path.resolve().is_relative_to(root) or not path.is_file():
            raise SystemExit('Ruta ausente o insegura: '+name)
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise SystemExit('Archivo distinto al distribuido: '+name)
    print('Integridad de la entrega comprobada: '+str(len(entries))+' archivos.')


if __name__ == '__main__':main()
