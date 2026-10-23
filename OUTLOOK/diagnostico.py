"""Technical events only; no CURP, email, PIN, OTP or exception messages."""
import json, logging, os, traceback
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path

def _record(event, exc=None):
    logger=logging.getLogger('gestoria.OUTLOOK.diagnostics')
    if not logger.handlers:
        root=Path(os.environ.get('LOCALAPPDATA') or str(Path.home()))/'GestoriaDiaz'/'Diagnostico'
        root.mkdir(parents=True,exist_ok=True)
        handler=RotatingFileHandler(root/'outlook_events.jsonl',maxBytes=262144,backupCount=3,encoding='utf-8')
        handler.setFormatter(logging.Formatter('%(message)s'))
        logger.addHandler(handler);logger.setLevel(logging.INFO);logger.propagate=False
    data={'event':event,'time':datetime.now(timezone.utc).isoformat()}
    if exc is not None:
        data['type']=type(exc).__name__
        data['frames']=[{'file':Path(f.filename).name,'line':f.lineno,'function':f.name}
                        for f in traceback.extract_tb(exc.__traceback__)]
    logger.info(json.dumps(data))


def record(event, exc=None):
    try:
        _record(event,exc)
    except OSError:
        # Disk-full/read-only diagnostics must not halt the scheduler.
        pass
