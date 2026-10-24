# -*- coding: utf-8 -*-
"""Outlook V45: visible V44 with pre-request inbox baseline; no old codes."""
import os,sys
if '--worker' in sys.argv:
    os.environ['GD_WORKER_SLOT']=sys.argv[sys.argv.index('--worker')+1]
else: os.environ['GD_WORKER_SLOT']='1'
os.environ['GD_HEADLESS']='0'
from app_v41 import OutlookV41,OutlookWorkerV36

def main():
    if '--worker' in sys.argv:
        n=int(sys.argv[sys.argv.index('--worker')+1])
        if n not in (2,3,4):raise ValueError('Canal inválido')
        app=OutlookWorkerV36();app.withdraw()
    else:
        app=OutlookV41()
        app.title('GESTORÍA DÍAZ · OUTLOOK V45 · ESPERA CÓDIGOS NUEVOS')
        app.info.set('Outlook V45: bandeja primero; ignora mensajes antiguos y espera el correo nuevo del IMSS.')
    app.mainloop()
if __name__=='__main__':main()
