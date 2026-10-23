"""Chromium y HTTP local reales; acceso, buzón y código ficticios.

Todas las peticiones del navegador se interceptan. No accede a cuentas Microsoft,
IMSS ni dispositivos. Comprueba el protocolo que debe implementar el otro bot.
python PROBAR_SESION_ENLACE.py [--chromium /ruta/al/ejecutable]
"""
import argparse
import json
import os
import tempfile
import threading
import time
from types import SimpleNamespace
from unittest.mock import patch


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--chromium')
    args=parser.parse_args()
    with tempfile.TemporaryDirectory() as temporary,patch.dict(os.environ,LOCALAPPDATA=temporary):
        from app import App
        from enlace import State,Server,Client
        import navegador as n

        email='synthetic@example.invalid';password='synthetic-test-password'
        sender='sender@example.invalid';code='012345'
        passkey_url='https://login.microsoft.com/consumers/fido/create?mkt=es-MX'
        state=State();logs=[]
        observed={'contexts':0,'pages':0,'closed':0,'loop_failure':False,
                  'read_failure':False,'delivery_failure':False}

        def deliver(request_id,value,account):
            if not observed['delivery_failure']:
                observed['delivery_failure']=True
                raise RuntimeError('synthetic temporary delivery failure')
            state.put_code(request_id,value,email=account)

        engine=n.BrowserLogin(logs.append,request_supplier=state.status,deliver_code=deliver)
        engine.set_sender(sender)
        enabled=threading.Event();enabled.set()
        app=SimpleNamespace(browser=engine,active_email=email,_auto_queue_enabled=enabled,
            cooldown=SimpleNamespace(remaining=lambda:0),state=state,
            queue=SimpleNamespace(entries=lambda:[{'email':email,'estado':'USADO','seleccionado':1}]))
        app._active_session_email=lambda:App._active_session_email(app)
        server=Server(state,port=0,resolver=lambda:App._reserve_email(app),
                      available=lambda:App._reservation_available(app))
        client=Client(port=server.server.server_port)

        def route(request_route):
            url=request_route.request.url
            if url==n.OUTLOOK_LOGIN_LANDING:
                html='''<!doctype html><meta charset="utf-8"><h1>Iniciar sesión</h1>
                <form><input id="i0116" name="loginfmt" autocomplete="username">
                <button id="idSIButton9" type="submit">Siguiente</button></form>
                <script>
                document.querySelector('form').onsubmit=event=>{
                  event.preventDefault();
                  if(document.querySelector('input').value!==EMAIL)return;
                  document.body.innerHTML='<form><input id="i0118" name="passwd" type="password">'
                    +'<button id="idSIButton9" type="submit">Iniciar sesión</button></form>';
                  document.querySelector('form').onsubmit=event=>{
                    event.preventDefault();
                    if(document.querySelector('input').value===PASSWORD)location.href=PASSKEY;
                  };
                };
                </script>'''
                for name,value in (('EMAIL',email),('PASSWORD',password),('PASSKEY',passkey_url)):
                    html=html.replace(name,json.dumps(value))
            elif url==passkey_url:
                html=('<h1>Guardar la clave de paso</h1><p>El inicio de sesión con contraseña no está disponible.</p>'
                      '<script>setTimeout(()=>location.href='+json.dumps(n.OUTLOOK_WEB_URL)+',1800)</script>')
            elif n.is_outlook_mail_url(url):
                html='''<!doctype html><meta charset="utf-8"><h1>Buzón simulado</h1>
                <div role="option" data-item-id="synthetic-message" tabindex="0">IMSS: código de validación</div>
                <article role="article" hidden></article>
                <script>
                document.querySelector('[role=option]').onclick=()=>{
                  const pane=document.querySelector('article');pane.hidden=false;
                  pane.innerHTML='<span>'+SENDER+'</span><time datetime="'+new Date().toISOString()+'">Hoy</time>'
                    +'<p>IMSS. Código de validación: '+CODE+'</p>';
                };
                </script>'''.replace('SENDER',json.dumps(sender)).replace('CODE',json.dumps(code))
            else:
                request_route.fulfill(status=404,body='No external requests');return
            request_route.fulfill(status=200,content_type='text/html; charset=utf-8',body=html)

        class Browser:
            def __init__(self,browser):self.browser=browser
            def new_context(self,**kwargs):
                observed['contexts']+=1
                context=self.browser.new_context(**kwargs)
                context.route('**/*',route)
                def page_opened(page):
                    observed['pages']+=1
                    def closed():observed['closed']+=1
                    page.on('close',closed)
                context.on('page',page_opened)
                return context
            def is_connected(self):return self.browser.is_connected()
            def close(self):self.browser.close()

        def launch(playwright,emit):
            options={'headless':True}
            if args.chromium:options['executable_path']=args.chromium
            return Browser(playwright.chromium.launch(**options))

        original_limit=n.is_microsoft_rate_limited
        def transient_loop_failure(page):
            if n.is_outlook_mail_url(page.url) and not observed['loop_failure']:
                observed['loop_failure']=True
                raise RuntimeError('synthetic temporary loop failure')
            return original_limit(page)

        original_scan=n.scan_visible_inbox
        def transient_read_failure(*values):
            if not observed['read_failure']:
                observed['read_failure']=True
                raise RuntimeError('synthetic temporary reader failure')
            return original_scan(*values)

        def wait_for(predicate,seconds=45):
            deadline=time.monotonic()+seconds
            while time.monotonic()<deadline:
                if predicate():return
                if engine.last_error and not engine.running:break
                time.sleep(.1)
            raise AssertionError('No se completó el recorrido sintético: '+repr(logs))

        server.start()
        try:
            with patch.object(n,'launch_private_browser',side_effect=launch), \
                 patch.object(n,'is_microsoft_rate_limited',side_effect=transient_loop_failure), \
                 patch.object(n,'scan_visible_inbox',side_effect=transient_read_failure):
                engine.start(email,password)
                wait_for(lambda:engine.phase=='mail')
                assert any('clave de paso' in message for message in logs)
                assert client.ping()['available']
                request_id='a'*32
                reserved=client.reserve(request_id)
                assert reserved['email']==email and reserved['status']=='ESPERANDO_CODIGO'
                assert not client.ping()['available']
                wait_for(lambda:client.status(request_id)['status']=='CODIGO_DISPONIBLE')
                assert client.status(request_id)['code']==code
                assert all(observed[key] for key in ('loop_failure','read_failure','delivery_failure'))
                assert observed['pages']==1 and observed['contexts']==1 and observed['closed']==0
                assert engine.running and engine.phase=='mail'
                client.ack(request_id)
                assert client.status(request_id)['status']=='CODIGO_ENVIADO_AL_CELULAR'
                assert client.status(request_id)['code'] is None
                client.done(request_id)
                assert client.status(request_id)['status']=='SOLICITUD_IMSS_ENVIADA'
                assert engine.running and observed['closed']==0 and client.ping()['available']
                second=client.reserve('b'*32)
                assert second['email']==email and second['status']=='ESPERANDO_CODIGO'
                client.cancel('b'*32)
                engine.stop()
                wait_for(lambda:not engine.running,seconds=6)
                assert observed['closed']==1
        finally:
            engine.stop()
            deadline=time.monotonic()+6
            while engine.running and time.monotonic()<deadline:time.sleep(.1)
            server.close()
        print('PASS: Chromium -> clave de paso conservada -> sesión abierta tras errores -> lectura DOM verificada -> HTTP local -> confirmación IMSS -> nueva reserva -> DETENER.')


if __name__=='__main__':main()
