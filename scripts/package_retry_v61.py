"""Ship bounded automatic recovery and keep the V6 backup unchanged."""
import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
V6_SHA = '3ee05579ca6158d227dd536b1871f24b4f4abe5d3a0adf836473b6999f149beb'
OUTLOOK = ('app.py','core.py','automation.py','history.py','requirements.txt')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build():
    previous = ROOT/'GESTORIA_DIAZ_PARALELO_V6.zip'
    assert digest(previous) == V6_SHA
    backup = ROOT/'respaldos/GESTORIA_DIAZ_PARALELO_V6_RESPALDO.zip'
    backup.write_bytes(previous.read_bytes())
    with zipfile.ZipFile(backup) as z:
        for name in OUTLOOK:
            assert (ROOT/'outlook_bot'/name).read_bytes() == z.read('GESTORIA_DIAZ_V6/outlook_bot/'+name)
    files = ['ABRIR_BOT.bat','INICIAR_TODO.bat','INICIAR_IMSS.bat',
             'INICIAR_OUTLOOK_CONECTADO.bat','panel_unificado.py',
             'gestoria_5_instancias.py','outlook_conectado.py','preparar_entorno.py',
             'diagnostico_conexion.py','LEEME_CONECTADOS.txt','VALIDACION_V61.txt',
             str(backup.relative_to(ROOT))]
    files += [str(p.relative_to(ROOT)) for p in sorted((ROOT/'conexion').glob('*.py'))]
    files += ['outlook_bot/'+n for n in OUTLOOK]
    manifest = {'version':'6.1-reintentos','respaldo_v6_sha256':V6_SHA,
                'archivos':{n:digest(ROOT/n) for n in files}}
    (ROOT/'MANIFIESTO_V61.json').write_text(json.dumps(manifest,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    files.append('MANIFIESTO_V61.json')
    output = ROOT/'GESTORIA_DIAZ_REINTENTOS_V6_1.zip'
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as z:
        for name in files:
            z.write(ROOT/name,'GESTORIA_DIAZ_V6_1/'+name)
    with zipfile.ZipFile(output) as z:
        assert z.testzip() is None
        for name in files:
            assert z.read('GESTORIA_DIAZ_V6_1/'+name) == (ROOT/name).read_bytes()
    print('ZIP V6.1:',len(files),'archivos;',output.stat().st_size,'bytes; SHA256',digest(output))


if __name__=='__main__':
    build()
