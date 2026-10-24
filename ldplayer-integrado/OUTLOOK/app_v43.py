# -*- coding: utf-8 -*-
"""Outlook V41 restaurado; único cambio: apartar recuperación obligatoria."""
import os,sys
if '--worker' in sys.argv:
    os.environ['GD_WORKER_SLOT']=sys.argv[sys.argv.index('--worker')+1]
else:os.environ['GD_WORKER_SLOT']='1'
os.environ['GD_HEADLESS']='0'
from app_v41 import OutlookV41, OutlookWorkerV36

def main():
    if '--worker' in sys.argv:
        slot=int(sys.argv[sys.argv.index('--worker')+1])
        if slot not in (2,3,4):raise ValueError('Canal inválido')
        app=OutlookWorkerV36();app.withdraw()
    else:
        app=OutlookV41()
        app.title('GESTORÍA DÍAZ · OUTLOOK V41 RESTAURADO · RECUPERACIÓN CONTROLADA')
    app.mainloop()
if __name__=='__main__':main()
