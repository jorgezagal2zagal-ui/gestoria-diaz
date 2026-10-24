"""Windows entry point with clear prerequisites and private technical diagnostics."""
import sys
import struct

def main():
    if sys.version_info<(3,12) or struct.calcsize('P')!=8:
        raise SystemExit('Requiere Python 3.12 o superior de 64 bits.')
    if sys.platform!='win32':raise SystemExit('Este panel requiere Windows, Tk y DPAPI. Para pruebas locales ejecuta validar.py.')
    from diagnostico import record
    try:
        from preparar import ensure_browser
        if ensure_browser():
            raise SystemExit('No se pudo preparar el navegador. Revisa el mensaje anterior.')
        from app import App
        App().mainloop()
    except Exception as exc:
        record('startup_failed',exc)
        raise SystemExit('No se pudo abrir el panel. Revisa dependencias y el diagnóstico técnico en LOCALAPPDATA/GestoriaDiaz/Diagnostico.') from None

if __name__=='__main__':main()
