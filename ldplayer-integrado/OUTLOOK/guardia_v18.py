"""Rate-limit circuit breaker. No retries or account rotation on HTTP 429."""
from pathlib import Path
import os,time,json
STORE=Path(os.environ.get('LOCALAPPDATA') or (Path.home()/'AppData'/'Local'))/'GestoriaDiaz'/'OutlookLimiteV18.json'
PAUSA=1800

def marcar_limite(now=None):
    now=time.time() if now is None else now
    STORE.parent.mkdir(parents=True,exist_ok=True)
    tmp=STORE.with_suffix('.tmp')
    tmp.write_text(json.dumps({'hasta':now+PAUSA}),encoding='utf-8')
    os.replace(tmp,STORE)

def faltan_segundos(now=None):
    now=time.time() if now is None else now
    try:return max(0,int(json.loads(STORE.read_text(encoding='utf-8'))['hasta']-now))
    except (OSError,KeyError,ValueError,TypeError):return 0
