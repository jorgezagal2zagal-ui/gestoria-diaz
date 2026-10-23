"""Local reproducible checks; isolated synthetic data, no real accounts or phone."""
import os, subprocess, sys, tempfile
from pathlib import Path
root=Path(__file__).resolve().parent
commands=[['-m','unittest','discover','-p','tests*.py','-v']]
commands += [[name] for name in ('PROBAR_V8.py','PROBAR_V9.py','PROBAR_V10.py','PROBAR_V11.py','PROBAR_V12.py','PROBAR_ENLACE.py')]

with tempfile.TemporaryDirectory() as temporary:
    environment=dict(os.environ,LOCALAPPDATA=temporary)
    for args in commands:
        result=subprocess.run([sys.executable,*args],cwd=root,env=environment)
        if result.returncode:sys.exit(result.returncode)
print('LOCAL CHECKS PASSED. Real Windows/HONOR/Microsoft integration remains unverified.')
