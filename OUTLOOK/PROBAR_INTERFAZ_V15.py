"""Panel Tk real + navegador real, con cuentas y páginas totalmente ficticias.

Requiere un escritorio (en Linux, DISPLAY) y Playwright/Chromium.
No usa DPAPI real, datos existentes, cuentas Microsoft ni el servidor IMSS.
"""
import argparse
import json
import os
from pathlib import Path
import secrets
import tempfile
import threading
import time
from unittest.mock import Mock,patch


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--chromium')
    parser.add_argument('--mode',choices=('auto','button'),default='auto')
    parser.add_argument('--screenshot')
    args=parser.parse_args()
    with tempfile.TemporaryDirectory() as temporary,patch.dict(os.environ,LOCALAPPDATA=temporary):
        import tkinter as tk
        import app
        import navegador as n
        from credenciales import Vault
        from queue_store import QueueStore

        class Protector:
            def __init__(self):self.values={}
            def protect(self,value):
                token=secrets.token_bytes(32);self.values[token]=value;return token
            def unprotect(self,token):return self.values[token]

        email='synthetic@example.invalid';password='synthetic-test-password'
        vault=Vault(protector=Protector(),path=Path(temporary)/'synthetic.sqlite3')
        vault.set_common_password(password)
        queue=QueueStore();queue.add([email]);queue.select_all()
        app.save_settings({'email':email,'auto_queue':False,
                           'automation_version':14 if args.mode=='auto' else 15})
        seen=threading.Event();requests=[];pages=[];auth_pages=[0]

        def route(request_route):
            url=request_route.request.url;requests.append(url)
            if url==n.OUTLOOK_LOGIN_LANDING:
                auth_pages[0]+=1
                html='''<!doctype html><meta charset="utf-8"><h1>Iniciar sesión</h1>
                <form><input id="i0116" name="loginfmt" autocomplete="username">
                <button id="idSIButton9" type="submit">Siguiente</button></form>
                <script>
                document.querySelector('form').onsubmit=event=>{
                  event.preventDefault();
                  if(document.querySelector('input').value!==EMAIL)return;
                  if(FAIL){document.body.textContent='El inicio de sesión con contraseña no está disponible en este momento.';return;}
                  document.body.innerHTML='<form><input id="i0118" name="passwd" type="password">'
                    +'<button id="idSIButton9" type="submit">Iniciar sesión</button></form>';
                  document.querySelector('form').onsubmit=event=>{
                    event.preventDefault();
                    if(document.querySelector('input').value===PASSWORD)location.href='https://account.microsoft.com/';
                  };
                };
                </script>'''
                html=html.replace('EMAIL',json.dumps(email)).replace('PASSWORD',json.dumps(password))
                html=html.replace('FAIL','true' if auth_pages[0]==1 else 'false')
            elif url=='https://account.microsoft.com/':html='<h1>Cuenta Microsoft</h1>'
            elif n.is_outlook_mail_url(url):html='<h1 id="test-inbox">Bandeja sintética</h1>'
            else:
                request_route.fulfill(status=404,body='No external network');return
            request_route.fulfill(status=200,content_type='text/html; charset=utf-8',body=html)

        class Browser:
            def __init__(self,browser):self.browser=browser
            def new_context(self,**kwargs):
                context=self.browser.new_context(**kwargs)
                context.route('**/*',route);context.on('page',lambda page:pages.append(page))
                return context
            def is_connected(self):return self.browser.is_connected()
            def close(self):self.browser.close()

        def launch(playwright,emit):
            options={'headless':False}
            if args.chromium:options['executable_path']=args.chromium
            return Browser(playwright.chromium.launch(**options))

        def inbox(page,account):
            assert account==email
            assert page.locator('#test-inbox').inner_text()=='Bandeja sintética'
            seen.set()

        with patch.object(app,'Vault',return_value=vault),patch.object(app,'Server',return_value=Mock()), \
             patch.object(n,'launch_private_browser',side_effect=launch), \
             patch.object(n,'PASSWORD_RETRY_DELAYS',(0,0)), \
             patch.object(n.BrowserLogin,'_check_inbox',side_effect=inbox):
            root=app.App()
            try:
                root.update()
                def buttons(widget):
                    result=[]
                    for child in widget.winfo_children():
                        if isinstance(child,tk.Button):result.append(child)
                        result.extend(buttons(child))
                    return result
                main_buttons={button.cget('text'):button for button in buttons(root)}
                assert set(main_buttons)=={'INICIAR','DETENER','IMPORTAR TXT','CUENTAS','COPIAR CORREO','AJUSTES'}
                if args.mode=='button':
                    assert not root.auto_queue.get()
                    main_buttons['INICIAR'].invoke()
                else:assert root.auto_queue.get()
                deadline=time.monotonic()+30
                while not seen.is_set() and time.monotonic()<deadline:
                    root.update();time.sleep(.02)
                assert seen.is_set(),root.browser_status.get()
                root._tick_once();root.update()
                # Los eventos del hilo se procesan en el temporizador de Tk.
                deadline=time.monotonic()+3
                while root.info.get()!='Acceso completado. Outlook está abierto.' and time.monotonic()<deadline:
                    root.update();time.sleep(.02)
                assert root.info.get()=='Acceso completado. Outlook está abierto.'
                assert root.cooldown.seconds==30
                assert queue.entries()[0]['estado']=='USADO'
                assert auth_pages[0]==2
                assert len(pages)==2 and pages[0].is_closed()
                assert 'https://account.microsoft.com/' in requests
                assert n.OUTLOOK_WEB_URL in requests
                assert root.browser.phase=='mail'
                root.lift();root.focus_force();root.update()
                if args.screenshot:
                    from PIL import ImageGrab
                    x=root.winfo_rootx();y=root.winfo_rooty()
                    ImageGrab.grab(bbox=(x,y,x+root.winfo_width(),y+root.winfo_height()),
                                   xdisplay=os.environ.get('DISPLAY')).save(args.screenshot)
                main_buttons['AJUSTES'].invoke();root.update()
                assert root.settings_window.winfo_exists()
                root.settings_window.destroy()
                main_buttons['DETENER'].invoke()
                assert not root.auto_queue.get()
                deadline=time.monotonic()+5
                while root.browser.running and time.monotonic()<deadline:
                    root.update();time.sleep(.02)
                assert not root.browser.running
                assert not app.get_settings()['auto_queue']
                print('PASS: Tk '+args.mode+' -> navegador visible -> mismo correo/clave -> reintento -> bandeja automática -> detener.')
            finally:
                root.close()


if __name__=='__main__':main()
