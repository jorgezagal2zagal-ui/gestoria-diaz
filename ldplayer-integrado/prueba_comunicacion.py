"""Cinco procesos reales: cuatro Outlook locales + cliente IMSS con ADB simulado."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parent
SETUP = r'''
from pool_v14 import SharedPool
from preparacion_v24 import PreparationV24
pool=SharedPool();prep=PreparationV24()
for n in range(1,5):
    email='autorizada'+str(n)+'@example.invalid';folio=('%032x'%n)
    pool.add([email])
    assert pool.reserve(folio)==email
    prep.create(folio,email,worker=n)
'''
SERVER = r'''
import json,sys,time
from pathlib import Path
from datetime import datetime,timezone
from types import SimpleNamespace
from enlace_integrado import State,Server
from outlook_integrado import IntegrationMixin
from lector_integrado import validate_message
from pool_v14 import SharedPool
from preparacion_v32 import PreparationV32
n=int(sys.argv[1]);email='autorizada'+str(n)+'@example.invalid';folio=('%032x'%n)
prep=PreparationV32(n);assert prep.set(folio,email,'LISTO')
app=SimpleNamespace(active_email=email,shared_pool=SharedPool(),preparacion=prep,
    browser=SimpleNamespace(running=True,phase='mail',manual_security_pending=False,rate_limited=False,
        _mailbox_verified_email=email,_mailbox_verified_at=time.monotonic()))
app._mailbox_ready=lambda:IntegrationMixin._mailbox_ready(app)
state=State();server=Server(state,port=0,mailbox_ready=app._mailbox_ready,
    can_begin=lambda email,folio,serial:IntegrationMixin._can_register(app,email,folio,serial))
server.start()
Path(sys.argv[2]).write_text(json.dumps({'port':server.server.server_address[1]}))
try:
    until=time.monotonic()+25
    delivered=False
    while time.monotonic()<until:
        app.browser._mailbox_verified_at=time.monotonic();prep.heartbeat()
        status=state.status()
        if status['status']=='ESPERANDO_CODIGO' and not delivered:
            code=validate_message('imss@example.invalid',datetime.now(timezone.utc).isoformat(),
                'Código de verificación','Código de verificación IMSS: '+('%06d'%n),
                'imss@example.invalid',status['started'])
            assert code
            state.put_code(folio,code,email);delivered=True
        if status['status']=='CODIGO_CONFIRMADO_FIN':
            assert status['code'] is None
            print('OUTLOOK '+str(n)+': código confirmado, secreto purgado; FIN.',flush=True)
            break
        time.sleep(.02)
    else:raise RuntimeError('No se completó el canal de prueba')
finally:server.close()
'''
CLIENT = r'''
import json,sys,threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from imss_paso1 import Node
import flujo_integrado as flow
from enlace_integrado import Client
ports=json.loads(sys.argv[1]);events={};opened={};written={};verified={}
def node(text='',clazz='android.widget.TextView',y=10,click=False):
    return Node(clazz,text,'','',(0,y,100,y+20),False,False,True,click)
def ui(adb,serial):
    n=int((int(serial.split('-')[1])-5554)/2)+1
    if verified.get(serial):return [node('Código verificado')]
    return [node('Ingresa tu código de verificación autorizada'+str(n)+'@example.invalid'),
        node('', 'android.widget.EditText',80),node('Verificar',y=120,click=True)]
def launch(adb,serial,logger):
    events[serial].append('abrir');opened[serial]=True;return 'ABIERTA',''
def form(adb,serial,curp,email,pin,**kwargs):
    kwargs['before_submit']()
    events[serial].append('formulario');return 'ESPERANDO CÓDIGO',''
def command(adb,serial,*args,**kwargs):
    n=int((int(serial.split('-')[1])-5554)/2)+1
    assert args==('shell','input','text','%06d'%n)
    assert not written.get(serial)
    events[serial].append('escribir');written[serial]=True;return 0,''
def tap(adb,serial,x,y):
    if y==130:
        assert written[serial];events[serial].append('verificar');verified[serial]=True
def run(n):
    serial='emulator-'+str(5552+2*n);events[serial]=[]
    result=flow.ejecutar('adb-simulado',serial,'A'*18,'autorizada'+str(n)+'@example.invalid',
        threading.Event(),Client(port=ports[str(n)]),folio=('%032x'%n),max_espera=10)
    assert result[0]=='CODIGO CONFIRMADO FIN',result
    assert events[serial]==['abrir','formulario','escribir','verificar'],events[serial]
with patch.object(flow,'foreground',side_effect=lambda adb,serial:bool(opened.get(serial))), \
     patch.object(flow,'launch_imss',side_effect=launch),patch.object(flow,'step_flow_v12',side_effect=form), \
     patch.object(flow,'quick_ui',side_effect=ui),patch.object(flow,'adb_run',side_effect=command), \
     patch.object(flow,'tap',side_effect=tap):
    with ThreadPoolExecutor(max_workers=4) as executor:list(executor.map(run,range(1,5)))
print('IMSS: cuatro folios/correos/LDPlayer aislados, escritura única, confirmación y FIN; ADB simulado.')
'''


def main():
    processes = []
    with tempfile.TemporaryDirectory() as temporary:
        env = dict(os.environ, LOCALAPPDATA=temporary)
        subprocess.run([sys.executable, '-c', SETUP], cwd=ROOT/'IMSS', env=env, check=True, timeout=15)
        try:
            ports = {}
            for n in range(1, 5):
                ready = Path(temporary)/('ready'+str(n)+'.json')
                process = subprocess.Popen([sys.executable, '-c', SERVER, str(n), str(ready), '--worker', str(n)],
                    cwd=ROOT/'OUTLOOK', env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                processes.append(process)
                deadline = time.monotonic()+10
                while not ready.exists() and process.poll() is None and time.monotonic() < deadline:time.sleep(.03)
                if not ready.exists():
                    raise RuntimeError('No inició el canal Outlook '+str(n))
                ports[str(n)] = json.loads(ready.read_text())['port']
            subprocess.run([sys.executable, '-c', CLIENT, json.dumps(ports)], cwd=ROOT/'IMSS', env=env, check=True, timeout=20)
            for process in processes:
                out, err = process.communicate(timeout=10)
                if process.returncode:raise RuntimeError('Falló el servidor de prueba: '+err[-1000:])
                print(out.strip())
        finally:
            for process in processes:
                if process.poll() is None:process.terminate()
                try:process.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill();process.communicate()
    print('COMUNICACIÓN ENTRE PROCESOS: SUPERADA. No se usaron Microsoft, Windows ni LDPlayer reales.')


if __name__ == '__main__':main()
