# -*- coding: utf-8 -*-
"""Enlace LOCAL IMSS <-> Outlook. Solo escucha en 127.0.0.1. Sin nube.

No guarda los códigos ni contraseñas en disco. Clave compartida restringida
al perfil del usuario actual de Windows. Se requiere mismo usuario y equipo.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler
from urllib.error import URLError, HTTPError
import json, os, re, secrets, threading, time

EMAIL = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
BASE = Path(os.environ.get('LOCALAPPDATA') or str(Path.home()))/'GestoriaDiaz'/'EnlaceIMSS_Outlook'
KEYFILE = BASE/'clave_local.txt'
HOST, PORT = '127.0.0.1', 8797

def shared_key():
    BASE.mkdir(parents=True, exist_ok=True)
    try:
        descriptor=os.open(KEYFILE,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    except FileExistsError:
        descriptor=None
    if descriptor is not None:
        with os.fdopen(descriptor,'w',encoding='utf-8') as f:
            f.write(secrets.token_urlsafe(48));f.flush();os.fsync(f.fileno())
    for attempt in range(30):
        value=KEYFILE.read_text(encoding='utf-8').strip()
        if len(value)>=40:return value
        time.sleep(.01)
    raise RuntimeError('La clave local no es válida; no se reemplazó el archivo existente.')

class LinkError(RuntimeError): pass

class LocalOnlyRedirect(HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        raise HTTPError(req.full_url,code,'El enlace local no permite redirecciones',headers,fp)

class State:
    def __init__(self):
        self.lock=threading.RLock(); self.job=None

    def start(self, email, request_id):
        email=email.strip().lower()
        if not EMAIL.fullmatch(email): raise ValueError('Correo inválido')
        if not re.fullmatch('[0-9a-f]{32}',request_id): raise ValueError('Solicitud inválida')
        with self.lock:
            if self.job and self.job['id']==request_id:
                if self.job['email']!=email:raise ValueError('El folio ya tiene otro correo')
                return self.status(request_id)
            if self.job and self.status()['status'] not in ('CADUCADA','SOLICITUD_IMSS_ENVIADA','CANCELADA'):
                raise ValueError('Hay otra solicitud activa; revisa el trámite antes de sustituirla')
            self.job={'email':email,'id':request_id,'started':datetime.now(timezone.utc).isoformat(),
                      'code':None,'status':'ESPERANDO_CODIGO','created':time.monotonic(),
                      'sent_at':0, 'document_ready':False}
            return self.status(request_id)

    def status(self,request_id=None):
        with self.lock:
            j=self.job
            if not j: return {'status':'SIN_SOLICITUD','email':None,'code':None}
            if request_id and request_id!=j['id']: raise ValueError('Solicitud diferente')
            expired = time.monotonic()-j['created']>900
            if expired and j['status'] not in ('SOLICITUD_IMSS_ENVIADA','CANCELADA'):
                j['code']=None;j['status']='CADUCADA'
            return {'status':j['status'],'email':j['email'],'request_id':j['id'],
                    'started':j['started'],'code':j['code'],
                    'document_ready':j['document_ready']}

    def put_code(self,request_id,code,email=None):
        code=str(code).strip()
        if not re.fullmatch('[0-9]{6}',code): raise ValueError('Se requieren seis dígitos')
        with self.lock:
            j=self.job
            if not j or j['id']!=request_id: raise ValueError('Solicitud no encontrada')
            if not email or j['email']!=email.strip().lower(): raise ValueError('La cuenta no coincide con la solicitud IMSS')
            if time.monotonic()-j['created']>900: raise ValueError('Solicitud caducada; inicia un nuevo trámite')
            if j['status'] not in ('ESPERANDO_CODIGO','CODIGO_DISPONIBLE'):
                raise ValueError('La solicitud ya no espera un código')
            j['code']=code;j['status']='CODIGO_DISPONIBLE';j['sent_at']=time.monotonic()
            return {'ok':True}

    def acknowledge(self,request_id):
        with self.lock:
            j=self.job
            if not j or j['id']!=request_id:raise ValueError('Solicitud distinta')
            if j['status'] not in ('CODIGO_DISPONIBLE','CODIGO_ENVIADO_AL_CELULAR'):
                raise ValueError('No hay código pendiente de confirmación')
            if j['status']=='CODIGO_DISPONIBLE':
                j['status']='CODIGO_ENVIADO_AL_CELULAR'
                j['code']=None
            return {'ok':True}

    def imss_done(self,request_id):
        with self.lock:
            j=self.job
            if not j or j['id']!=request_id:raise ValueError('Solicitud distinta')
            if self.status(request_id)['status'] in ('CADUCADA','CANCELADA'):
                raise ValueError('Solicitud inactiva')
            j['status']='SOLICITUD_IMSS_ENVIADA';j['code']=None;j['document_ready']=False
            return {'ok':True}

    def register(self,email,request_id,can_begin):
        with self.lock:
            if self.job and self.job['id']==request_id:return self.start(email,request_id)
            if not can_begin(email):raise ValueError('La sesión Outlook no está disponible para ese correo')
            return self.start(email,request_id)

    def reserve(self,request_id,resolver,available):
        if not re.fullmatch('[0-9a-f]{32}',request_id):raise ValueError('Solicitud inválida')
        with self.lock:
            if self.job and self.job['id']==request_id:return self.status(request_id)
            if self.job and self.status()['status'] not in ('CADUCADA','SOLICITUD_IMSS_ENVIADA','CANCELADA'):
                raise ValueError('Hay otra solicitud activa')
            if not resolver or not available():raise ValueError('Outlook ocupado, limitado o automático desactivado')
            email=resolver()
            if not email:raise ValueError('No hay cuenta NUEVA seleccionada con contraseña cifrada')
            return self.start(email,request_id)

    def cancel(self,request_id):
        with self.lock:
            if not self.job or self.job['id']!=request_id:raise ValueError('Solicitud distinta')
            self.job['status']='CANCELADA';self.job['code']=None
            return {'ok':True}

class Server:
    def __init__(self,state:State,port=PORT,resolver=None,available=lambda:True,can_begin=lambda email:True):
        key=shared_key()
        class Handler(BaseHTTPRequestHandler):
            def setup(self):
                super().setup();self.connection.settimeout(3)
            def log_message(self,*args): return
            def reply(self,status,obj):
                payload=json.dumps(obj,ensure_ascii=False).encode('utf-8')
                self.send_response(status)
                self.send_header('Content-Type','application/json; charset=utf-8')
                self.send_header('Cache-Control','no-store')
                self.send_header('X-Content-Type-Options','nosniff')
                self.send_header('Content-Length',str(len(payload)))
                self.end_headers();self.wfile.write(payload)
            def authorized(self):
                return not self.headers.get('Origin') and secrets.compare_digest(self.headers.get('X-GD-Link-Key','').encode('utf-8'),key.encode('utf-8'))
            def body(self):
                if self.headers.get('Transfer-Encoding'):raise ValueError('Formato de transporte no permitido')
                n=int(self.headers.get('Content-Length','0'))
                if not (1<=n<=2048):raise ValueError('Tamaño inválido')
                x=json.loads(self.rfile.read(n))
                if not isinstance(x,dict):raise ValueError('Formato inválido')
                return x
            def do_GET(self):
                if not self.authorized():return self.reply(401,{'error':'Sin autorización'})
                try:
                    p=urlparse(self.path)
                    if p.path=='/v1/ping':return self.reply(200,{'ok':True,'version':1,'available':bool(available())})
                    if p.path=='/v1/estado':
                        req=parse_qs(p.query).get('id',[None])[0]
                        return self.reply(200,state.status(req))
                    return self.reply(404,{'error':'No existe'})
                except ValueError as e:return self.reply(400,{'error':str(e)})
            def do_POST(self):
                if not self.authorized():return self.reply(401,{'error':'Sin autorización'})
                try:
                    p=self.body()
                    if self.path=='/v1/reservar':return self.reply(200,state.reserve(str(p.get('id','')),resolver,available))
                    if self.path=='/v1/cancelar':return self.reply(200,state.cancel(str(p.get('id',''))))
                    if self.path=='/v1/iniciar':return self.reply(200,state.register(str(p.get('email','')),str(p.get('id','')),can_begin))
                    if self.path=='/v1/codigo':return self.reply(200,state.put_code(str(p.get('id','')),str(p.get('code','')),str(p.get('email',''))))
                    if self.path=='/v1/recibido':return self.reply(200,state.acknowledge(str(p.get('id',''))))
                    if self.path=='/v1/imss_enviado':return self.reply(200,state.imss_done(str(p.get('id',''))))
                    return self.reply(404,{'error':'No existe'})
                except (ValueError, UnicodeError) as e:return self.reply(400,{'error':str(e)[:150]})
                except Exception:return self.reply(500,{'error':'Error local'})
        self.server=ThreadingHTTPServer((HOST,port),Handler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
    def start(self):
        try:self.thread.start()
        except Exception:
            self.server.server_close();raise
    def close(self):
        if self.thread.is_alive():self.server.shutdown()
        self.server.server_close()

class Client:
    def __init__(self,port=PORT,timeout=1.4):self.port=port;self.timeout=timeout
    def call(self,endpoint,body=None):
        url=f'http://{HOST}:{self.port}'+endpoint
        data=json.dumps(body).encode('utf-8') if body is not None else None
        req=Request(url,data=data,headers={'X-GD-Link-Key':shared_key(),
                           'Content-Type':'application/json'},method='POST' if data is not None else 'GET')
        try:
            with build_opener(ProxyHandler({}),LocalOnlyRedirect()).open(req,timeout=self.timeout) as r: return json.loads(r.read(8192))
        except HTTPError as e:
            try: error=json.loads(e.read(1024)).get('error','HTTP '+str(e.code))
            except Exception: error='HTTP '+str(e.code)
            raise LinkError(error) from e
        except (URLError,TimeoutError,OSError) as e:
            raise LinkError('El bot Outlook no está abierto o el enlace local está ocupado.') from e
    def ping(self):return self.call('/v1/ping')
    def begin(self,email,request_id):return self.call('/v1/iniciar',{'email':email,'id':request_id})
    def status(self,request_id):return self.call('/v1/estado?id='+request_id)
    def ack(self,request_id):return self.call('/v1/recibido',{'id':request_id})
    def reserve(self,request_id):return self.call('/v1/reservar',{'id':request_id})
    def cancel(self,request_id):return self.call('/v1/cancelar',{'id':request_id})
    def done(self,request_id):return self.call('/v1/imss_enviado',{'id':request_id})
