"""Pruebas locales con estado temporal; fallos y pruebas antiguas separados."""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--historicas', action='store_true', help='Incluye las dos suites antiguas que ya fallaban en los ZIP originales')
    args = parser.parse_args()
    commands = [
        ('.', ['-m', 'unittest', 'tests_paquete', '-v']),
        ('IMSS', ['-m', 'unittest', 'tests_integracion', '-v']),
        ('IMSS', ['PRUEBAS_V11.py']),
        ('OUTLOOK', ['validar.py']),
        ('OUTLOOK', ['PRUEBAS_INTEGRADO_GUI.py']),
        ('.', ['prueba_comunicacion.py']),
    ]
    if args.historicas:
        commands += [('IMSS', ['PRUEBAS_V12.py']), ('IMSS', ['PRUEBAS_V13.py'])]
    failures = 0
    with tempfile.TemporaryDirectory() as temp:
        env = dict(os.environ, LOCALAPPDATA=temp, PYTHONDONTWRITEBYTECODE='1')
        for folder, command in commands:
            print('\nEJECUTANDO '+folder+': '+' '.join(command), flush=True)
            result = subprocess.run([sys.executable, *command], cwd=ROOT/folder, env=env, timeout=180)
            if result.returncode:failures += 1
    if failures:
        print(str(failures)+' comandos fallaron; consulta sus resultados. No se declaran superados.')
        return 1
    print('PRUEBAS LOCALES SUPERADAS. ADB, Microsoft, DPAPI y ventanas Windows reales no fueron validados por estas pruebas.')
    return 0


if __name__ == '__main__':raise SystemExit(main())
