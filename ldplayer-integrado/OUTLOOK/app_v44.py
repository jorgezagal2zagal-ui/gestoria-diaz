# -*- coding: utf-8 -*-
"""Outlook V44 - Base V41R con lector del mensaje abierto y 5 s enfriamiento."""
import os,sys
if '--worker' in sys.argv:
    os.environ['GD_WORKER_SLOT']=sys.argv[sys.argv.index('--worker')+1]
else:os.environ['GD_WORKER_SLOT']='1'
os.environ['GD_HEADLESS']='0'
from app_v41 import OutlookV41,OutlookWorkerV36

def main():
    if '--worker' in sys.argv:
        slot=int(sys.argv[sys.argv.index('--worker')+1])
        if slot not in (2,3,4):raise ValueError('Canal inválido')
        app=OutlookWorkerV36();app.withdraw()
    else:
        app=OutlookV41()
        app.title('GESTORÍA DÍAZ · OUTLOOK V44 · LECTURA DIRECTA Y ENFRIAMIENTO 5 s')
        app.info.set('Outlook V44: Chrome visible; lectura de código seleccionado; 5 s enfriamiento.')
    app.mainloop()
if __name__=='__main__':main()
