"""Ship two independently controlled bots in one window, preserving V4 exactly."""
import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
V4_SHA = '358346ec27f1687da97fc1ce53deeb0468b2e7f2819356991571262c8b6c74c7'
OUTLOOK = ('app.py','core.py','automation.py','history.py','requirements.txt')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build():
    previous = ROOT/'GESTORIA_DIAZ_PANEL_UNICO_SIMPLE_V4.zip'
    assert digest(previous) == V4_SHA
    backup = ROOT/'respaldos/GESTORIA_DIAZ_PANEL_UNICO_SIMPLE_V4_RESPALDO.zip'
    backup.write_bytes(previous.read_bytes())
    with zipfile.ZipFile(backup) as z:
        for name in OUTLOOK:
            assert (ROOT/'outlook_bot'/name).read_bytes() == z.read('GESTORIA_DIAZ_SIMPLE/outlook_bot/'+name)
    files = ['ABRIR_BOT.bat','INICIAR_TODO.bat','INICIAR_IMSS.bat',
             'INICIAR_OUTLOOK_CONECTADO.bat','panel_unificado.py',
             'gestoria_5_instancias.py','outlook_conectado.py','preparar_entorno.py',
             'diagnostico_conexion.py','LEEME_CONECTADOS.txt','VALIDACION_V5.txt',
             str(backup.relative_to(ROOT))]
    files += [str(p.relative_to(ROOT)) for p in sorted((ROOT/'conexion').glob('*.py'))]
    files += ['outlook_bot/'+n for n in OUTLOOK]
    manifest = {'version':'5-dos-bots','respaldo_v4_sha256':V4_SHA,
                'archivos':{n:digest(ROOT/n) for n in files}}
    (ROOT/'MANIFIESTO_V5.json').write_text(json.dumps(manifest,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    files.append('MANIFIESTO_V5.json')
    output = ROOT/'GESTORIA_DIAZ_DOS_BOTS_V5.zip'
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as z:
        for name in files:
            z.write(ROOT/name,'GESTORIA_DIAZ_V5/'+name)
    with zipfile.ZipFile(output) as z:
        assert z.testzip() is None
        for name in files:
            assert z.read('GESTORIA_DIAZ_V5/'+name) == (ROOT/name).read_bytes()
    print('ZIP V5:',len(files),'archivos;',output.stat().st_size,'bytes; SHA256',digest(output))


if __name__=='__main__':
    build()
