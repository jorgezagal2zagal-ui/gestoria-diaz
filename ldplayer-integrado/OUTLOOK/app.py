# -*- coding: utf-8 -*-
"""Gestoría Díaz - Outlook Incógnito: panel reducido y enlace IMSS local.

- Inicio en Microsoft mediante Chromium temporal (sin cookies persistentes).
- Lectura automática OPCIONAL mediante OAuth delegado de Microsoft Graph.
- Envío manual de código al bot IMSS como respaldo.
- No omite MFA ni CAPTCHA de Microsoft.
"""
from __future__ import annotations
import json, re, threading, time, tkinter as tk
import queue as ui_queue
from diagnostico import record
from pathlib import Path
from tkinter import messagebox,ttk,scrolledtext,filedialog
from core import EMAIL_RE, data_dir
from credenciales import Vault, decode_file
from navegador import BrowserLogin
from mail_service import MailService
from enlace import State,Server
from queue_store import QueueStore
from cooldown import Cooldown
BG='#101419';BOX='#1B232C';GOLD='#E8BB62';WHITE='#F0F1F4';GRAY='#ACB6C1';GREEN='#93E4C1'
SETTINGS=data_dir()/'panel_simple.json'

def get_settings():
    try:
        value=json.loads(SETTINGS.read_text(encoding='utf-8'))
        return value if isinstance(value,dict) else {}
    except (ValueError,OSError):return {}

def save_settings(info):
    SETTINGS.parent.mkdir(parents=True,exist_ok=True)
    temp=SETTINGS.with_suffix('.tmp')
    merged=get_settings()
    merged.update(info)
    temp.write_text(json.dumps(merged,ensure_ascii=False,indent=2),encoding='utf-8')
    temp.replace(SETTINGS)

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('Gestoría Díaz · Outlook automático V15.2')
        self._closed=False
        self._ui_events=ui_queue.Queue()
        self._auto_queue_enabled=threading.Event()
        self.geometry('760x610');self.minsize(680,540);self.configure(bg=BG)
        cfg=get_settings()
        if cfg.get('automation_version')!=15:
            cfg.update(auto_queue=True,automation_version=15)
            save_settings(cfg)
        self.email=tk.StringVar(value=cfg.get('email',''))
        self.password=tk.StringVar()
        self.save_pw=tk.BooleanVar(value=False)
        self.common_password_status=tk.StringVar(value='Contraseña común: sin configurar.')
        self.sender=tk.StringVar(value=cfg.get('sender',''))
        self.client_id=tk.StringVar(value=cfg.get('client_id',''))
        self.last_auto_check=0.0
        self.code=tk.StringVar()
        self.link_status=tk.StringVar(value='Iniciando enlace con IMSS…')
        self.browser_status=tk.StringVar(value='Outlook aún no se ha abierto.')
        self.info=tk.StringVar(value='Las contraseñas se utilizan solo en el inicio de sesión oficial de Microsoft.')
        self.browser_events=[]
        self.queue = QueueStore()
        self.cooldown = Cooldown(seconds=5)
        self.cooldown_label=tk.StringVar(value='ENFRIAMIENTO · Listo para iniciar')
        self.accounts_label=tk.StringVar(value='Cuentas importadas: 0')
        self.auto_queue=tk.BooleanVar(value=bool(cfg.get('auto_queue',True)))
        if self.auto_queue.get():self._auto_queue_enabled.set()
        self._auto_started_request=None
        self._last_auto_status=None
        self._auto_start_attempted=False
        self._launch_recorded=False
        self.active_email=None
        self.active_email_label=tk.StringVar(value="Ninguna cuenta en uso")
        self._previous_browser_running=False
        self.state=State();self.server=None
        self.browser=BrowserLogin(self._receive_browser_event,
                                  request_supplier=self.state.status,
                                  deliver_code=self._deliver_browser_code)
        self.browser.set_sender(self.sender.get())
        self.vault=None;self.service=None;self.auto_busy=False
        try:
            self.server=Server(self.state,resolver=self._reserve_email,available=self._reservation_available,can_begin=self._can_begin);self.server.start()
            self.link_status.set('Enlace activo en esta computadora (127.0.0.1:8797)')
        except Exception as e:
            self.link_status.set('No se pudo activar el enlace. Cierra otras versiones de Outlook. '+str(e)[:65])
        self._build()
        self._update_common_password_status()
        self.after(1000,self.tick)
        self.protocol('WM_DELETE_WINDOW',self.close)

    def report_callback_exception(self,error_type,error,trace):
        record('outlook_callback_failed',error.with_traceback(trace))
        try:self.info.set('Error de interfaz; revisa el diagnóstico técnico antes de repetir la operación.')
        except Exception:pass

    def post_ui(self,callback):
        if not self._closed:self._ui_events.put(callback)

    def _can_begin(self,email):
        return (not self.browser.rate_limited and
                ((self.browser.running and self.active_email==email.strip().lower()) or
                 (not self.browser.running and not self.cooldown.remaining())))

    def _reservation_available(self):
        if not self._auto_queue_enabled.is_set() or self.browser.rate_limited or self.cooldown.remaining():return False
        if not self.browser.running:return True
        return bool(self._active_session_email() and self.state.status()['status'] in
                    ('SIN_SOLICITUD','CADUCADA','SOLICITUD_IMSS_ENVIADA','CANCELADA'))

    def _active_session_email(self):
        if not self.browser.running or getattr(self.browser,'phase','')!='mail' or self.browser.rate_limited:return None
        email=self.active_email
        return email if any(row['email']==email and row['seleccionado'] for row in self.queue.entries()) else None

    def _reserve_email(self):
        # HTTP worker: use storage only, never Tk variables.
        active=self._active_session_email()
        if active:return active
        if self.browser.running:return None
        vault=Vault()
        return next((item['email'] for item in self.queue.entries()
                     if item['estado']=='NUEVO' and item['seleccionado']
                     and vault.has_password(item['email'])),None)

    def _receive_browser_event(self, message):
        # La contraseña nunca se guarda ni se imprime en el diagnóstico.
        try:self.post_ui(lambda m=message:self._show_browser_event(m))
        except Exception:pass

    def _show_browser_event(self, message):
        self.browser_status.set(self.browser.last_error or message)
        if getattr(self.browser,'phase','')=='mail':
            self.info.set('Acceso completado. Outlook está abierto.')
        self.browser_events.append(message)
        self.browser_events=self.browser_events[-50:]

    def show_diagnostics(self):
        win=tk.Toplevel(self)
        win.title('Diagnóstico · Inicio de Outlook')
        win.geometry('740x400')
        win.configure(bg=BG)
        tk.Label(win,text='PASOS DEL NAVEGADOR (sin contraseñas ni códigos)',
                 bg=BG,fg=GOLD,font=('Segoe UI',11,'bold')).pack(anchor='w',padx=12,pady=(12,4))
        box=scrolledtext.ScrolledText(win,wrap='word',height=16,
                     bg=BOX,fg=WHITE,insertbackground=WHITE,font=('Consolas',10))
        box.pack(fill='both',expand=True,padx=12,pady=8)
        box.insert('1.0','\n'.join(self.browser_events) or 'Todavía no hay eventos del navegador.')
        box.configure(state='disabled')

    def _vault(self):
        if self.vault is None:self.vault=Vault()
        return self.vault

    def _update_common_password_status(self):
        try:
            enabled=self._vault().has_common_password()
            text=('Contraseña común guardada: se usará en todos los correos.' if enabled
                  else 'Contraseña común: sin configurar.')
        except Exception:
            text='No se pudo comprobar la contraseña común guardada.'
        self.common_password_status.set(text)

    def save_password_for_all(self):
        password=self.password.get()
        if not password:
            messagebox.showerror('Contraseña común','Escribe arriba la contraseña que usarán todos los correos.')
            return
        try:
            self._vault().set_common_password(password)
        except Exception as exc:
            messagebox.showerror('Contraseña común','No se pudo guardar la contraseña cifrada ('+type(exc).__name__+').')
            return
        self.password.set('')
        self.save_pw.set(False)
        self._update_common_password_status()
        self.info.set('Contraseña común guardada para todos los correos actuales y futuros. Se conserva al cerrar el programa.')

    def forget_common_password(self):
        try:
            self._vault().clear_common_password()
        except Exception as exc:
            messagebox.showerror('Contraseña común','No se pudo quitar la contraseña común ('+type(exc).__name__+').')
            return
        self.password.set('')
        self._update_common_password_status()
        self.info.set('Contraseña común eliminada. Se usarán las claves individuales que ya estuvieran guardadas.')

    def _mail(self):
        if self.service is None:
            cid=self.client_id.get().strip()
            if not re.fullmatch(r'[0-9a-fA-F-]{36}',cid):
                raise RuntimeError('Para leer correo automáticamente necesitas un ID de aplicación Microsoft autorizado. El inicio en incógnito funciona sin ese ID.')
            self.service=MailService(client_id=cid)
        return self.service

    def label(self,parent,text,color=GRAY,size=10,bold=False):
        return tk.Label(parent,text=text,bg=parent.cget('bg'),fg=color,
                 font=('Segoe UI',size,'bold' if bold else 'normal'),anchor='w',justify='left')

    def button(self,parent,text,fn,accent=False):
        return tk.Button(parent,text=text,command=fn,bg=GOLD if accent else '#343E49',
              fg=BG if accent else WHITE,activebackground='#EED18C',relief='flat',bd=0,
              padx=14,pady=10,font=('Segoe UI',10,'bold'))

    def _build(self):
        main=tk.Frame(self,bg=BG,padx=22,pady=20);main.pack(fill='both',expand=True)
        self.label(main,'GESTORÍA DÍAZ · OUTLOOK',GOLD,19,True).pack(anchor='w')
        self.label(main,'Enfriamiento entre cuentas: 5 s · protecciones de Microsoft intactas',GRAY,10).pack(anchor='w',pady=(3,17))
        self.label(main,'Correo elegido',WHITE,10,True).pack(anchor='w')
        self.account_picker=ttk.Combobox(main,textvariable=self.email,state='readonly')
        self.account_picker.pack(fill='x',ipady=5,pady=(5,12))
        self.account_picker.bind('<<ComboboxSelected>>',self._select_from_dropdown)
        actions=tk.Frame(main,bg=BG);actions.pack(fill='x',pady=(0,16))
        for text,command,accent in (('INICIAR',self.start_automation,True),
                ('DETENER',self.stop_automation,False),('IMPORTAR TXT',self.import_txt,False),
                ('CUENTAS',self.manage_accounts,False)):
            self.button(actions,text,command,accent).pack(side='left',padx=(0,8))
        status=tk.Frame(main,bg=BOX,padx=16,pady=14);status.pack(fill='x')
        self.label(status,'ESTADO DEL ACCESO',GOLD,10,True).pack(anchor='w')
        tk.Label(status,textvariable=self.browser_status,bg=BOX,fg=WHITE,font=('Segoe UI',11),
                 wraplength=625,justify='left',anchor='w').pack(fill='x',pady=(8,10))
        tk.Label(status,textvariable=self.active_email_label,bg=BOX,fg=GRAY,
                 font=('Segoe UI',10),anchor='w').pack(fill='x')
        tk.Label(status,textvariable=self.cooldown_label,bg=BOX,fg=GOLD,
                 font=('Segoe UI',10),anchor='w').pack(fill='x',pady=(6,0))
        tk.Label(main,textvariable=self.accounts_label,bg=BG,fg=GRAY,
                 font=('Segoe UI',9),anchor='w').pack(fill='x',pady=(12,4))
        tk.Label(main,textvariable=self.link_status,bg=BG,fg=GRAY,font=('Segoe UI',9),
                 wraplength=650,justify='left',anchor='w').pack(fill='x',pady=(0,6))
        tools=tk.Frame(main,bg=BG);tools.pack(fill='x',pady=(4,8))
        self.button(tools,'COPIAR CORREO',self.copy_current_email).pack(side='left',padx=(0,8))
        self.button(tools,'AJUSTES',self.show_settings).pack(side='left')
        tk.Label(main,textvariable=self.info,bg=BG,fg=GOLD,font=('Segoe UI',10),
                 wraplength=650,justify='left',anchor='w').pack(fill='x',pady=(4,0))
        self._update_counts()

    def _select_from_dropdown(self,event=None):
        if self.browser.running:
            if self.active_email:self.email.set(self.active_email)
            self.info.set('Detén el acceso actual antes de elegir otra cuenta.')
            return
        self._choose_account(self.email.get())

    def show_settings(self):
        previous=getattr(self,'settings_window',None)
        if previous is not None and previous.winfo_exists():
            previous.lift();return
        win=tk.Toplevel(self);self.settings_window=win
        win.title('Ajustes de Outlook');win.geometry('710x550');win.configure(bg=BG)
        tabs=ttk.Notebook(win);tabs.pack(fill='both',expand=True,padx=15,pady=15)
        access=tk.Frame(tabs,bg=BOX,padx=16,pady=16)
        imss=tk.Frame(tabs,bg=BOX,padx=16,pady=16)
        advanced=tk.Frame(tabs,bg=BOX,padx=16,pady=16)
        tabs.add(access,text='Contraseña');tabs.add(imss,text='Código IMSS');tabs.add(advanced,text='Avanzado')
        self.label(access,'Contraseña común para todos los correos',GOLD,12,True).pack(anchor='w')
        ttk.Entry(access,textvariable=self.password,show='●').pack(fill='x',ipady=5,pady=12)
        row=tk.Frame(access,bg=BOX);row.pack(anchor='w')
        self.button(row,'GUARDAR PARA TODOS',self.save_password_for_all,True).pack(side='left',padx=(0,8))
        self.button(row,'OLVIDAR COMÚN',self.forget_common_password).pack(side='left')
        tk.Label(access,textvariable=self.common_password_status,bg=BOX,fg=GRAY,
                 wraplength=600,justify='left',anchor='w').pack(fill='x',pady=12)
        self.label(access,'Se conserva cifrada para este usuario de Windows.',GRAY,9).pack(anchor='w')
        tk.Checkbutton(access,text='Iniciar automáticamente con una cuenta preparada',
            variable=self.auto_queue,bg=BOX,fg=WHITE,activebackground=BOX,
            selectcolor='#273544',command=self.save_auto_queue).pack(anchor='w',pady=20)
        self.label(imss,'Remitente exacto del código IMSS',GOLD,11,True).pack(anchor='w')
        ttk.Entry(imss,textvariable=self.sender).pack(fill='x',ipady=5,pady=9)
        self.button(imss,'GUARDAR AJUSTES',self.save_preferences).pack(anchor='w')
        self.label(imss,'El lector de la bandeja trabaja al abrir Outlook. '
                   'Si falta un dato verificable, puedes enviar el código manualmente.',GRAY,9).pack(anchor='w',pady=12)
        row=tk.Frame(imss,bg=BOX);row.pack(fill='x')
        ttk.Entry(row,textvariable=self.code,width=12).pack(side='left',ipady=5,padx=(0,8))
        self.button(row,'ENVIAR CÓDIGO',self.send_manual_code).pack(side='left')
        self.button(advanced,'VER DIAGNÓSTICO',self.show_diagnostics).pack(anchor='w')
        self.label(advanced,'Lectura opcional con Microsoft Graph',GOLD,11,True).pack(anchor='w',pady=(20,6))
        self.label(advanced,'ID de aplicación Microsoft',GRAY,9).pack(anchor='w')
        ttk.Entry(advanced,textvariable=self.client_id).pack(fill='x',ipady=5,pady=8)
        self.button(advanced,'AUTORIZAR LECTURA',self.authorize_microsoft).pack(anchor='w')
        self.label(advanced,'Esta opción es independiente del inicio automático en el navegador.',GRAY,9).pack(anchor='w',pady=12)

    def save_preferences(self):
        save_settings({'email':self.email.get().strip().lower(),
                       'sender':self.sender.get().strip().lower(),
                       'client_id':self.client_id.get().strip(),
                       'auto_queue':bool(self.auto_queue.get())})
        self.browser.set_sender(self.sender.get())
        self.info.set('Ajustes guardados.')

    def copy_current_email(self):
        email=(self.active_email if self.browser.running else None) or self.email.get().strip().lower()
        if not email or not EMAIL_RE.fullmatch(email):
            self.info.set('No hay correo válido para copiar.');return
        try:
            self.clipboard_clear();self.clipboard_append(email);self.update_idletasks()
            self.info.set('Correo copiado al portapapeles: '+email)
        except Exception as exc:
            self.info.set('No se pudo copiar el correo ('+type(exc).__name__+').')

    def close_private(self):
        """Cierra una sesión privada; 5 s antes de abrir otra cuenta."""
        if self.browser.running:
            self.cooldown.begin()
            self.info.set('Cerrando incógnito. La siguiente cuenta estará disponible tras el enfriamiento.')
        self.browser.stop()

    def _guard_new_login(self):
        if self.browser.rate_limited:
            messagebox.showwarning('Microsoft 429',
                'Microsoft aplicó Too Many Requests. Se pausaron TODAS las cuentas. No se intentará otra hasta que Microsoft retire el límite. Cierra este bot.')
            return False
        if self.browser.running:
            self.info.set('Primero cierra la sesión privada anterior.');return False
        left=self.cooldown.remaining()
        if left:
            self.info.set(f'Enfriamiento activo. Espera {left} segundos antes de iniciar otra cuenta.')
            return False
        return True

    def start_automation(self):
        """Única acción de arranque: navegador privado, correo, contraseña y bandeja."""
        if self.browser.running:
            self.info.set('El acceso ya está en marcha. Revisa el estado del navegador.')
            return
        if not self._guard_new_login():return
        self.auto_queue.set(True)
        self._auto_queue_enabled.set()
        self._auto_start_attempted=False
        self._auto_started_request=None
        self.save_preferences()
        state=self.state.status()
        if state.get('status')=='ESPERANDO_CODIGO':
            self._maybe_start_request_account(state,explicit=True)
        else:self._maybe_auto_start(state)

    def stop_automation(self):
        self.auto_queue.set(False)
        self._auto_queue_enabled.clear()
        self._auto_start_attempted=True
        save_settings({'auto_queue':False})
        self.close_private()
        self.browser_status.set('Automatización detenida. Pulsa INICIAR para continuar.')

    def _maybe_auto_start(self,state):
        if not self.auto_queue.get() or self.browser.running or self.browser.rate_limited:
            return
        if self.cooldown.remaining():return
        if state.get('status')=='ESPERANDO_CODIGO':
            self._maybe_start_request_account(state)
            return
        # Fuera de una solicitud IMSS se abre una sola cuenta elegida; no se
        # recorren ni se cambian cuentas al cerrar el navegador.
        if state.get('status')!='SIN_SOLICITUD' or self._auto_start_attempted:return
        email=self.email.get().strip().lower() or self.queue.choose()
        if not email or not EMAIL_RE.fullmatch(email):
            self.info.set('Importa un TXT y elige una cuenta para comenzar.')
            return
        try:password=self._vault().password(email)
        except Exception as exc:
            self._auto_start_attempted=True
            self.browser_status.set('No se pudo leer la contraseña cifrada ('+type(exc).__name__+'). Abre AJUSTES.')
            return
        if not password:
            self.info.set('Abre AJUSTES, escribe la contraseña y pulsa GUARDAR PARA TODOS.')
            return
        self.email.set(email)
        self._auto_start_attempted=True
        self._start_browser(email,password)

    def import_txt(self):
        filename=filedialog.askopenfilename(title='Selecciona TXT con correos y contraseñas',
                                              filetypes=[('Archivos de texto','*.txt'),('Todos','*.*')])
        if not filename:return
        try:
            accounts=decode_file(filename)
            if not accounts:raise ValueError('No encontré direcciones válidas. Usa correo | CONTRA: contraseña')
            with_password=sum(1 for _e,pw in accounts if pw)
            if not messagebox.askyesno('Importar cuentas',
                f'Se encontraron {len(accounts)} correos y {with_password} contraseñas.\n'
                'Las contraseñas se cifrarán con Windows DPAPI.\n'
                'El TXT ORIGINAL seguirá sin cifrar hasta que lo borres tú. ¿Importar?'):
                return
            self._vault().save(accounts)
            added=self.queue.add([e for e,_ in accounts])
            selected=[row['email'] for row in self.queue.entries() if row['seleccionado']]
            self.queue.set_selected(selected+[email for email,_ in accounts])
            if not self.email.get().strip():self.email.set(accounts[0][0])
            if not self.browser.running:self._auto_start_attempted=False
            self._update_counts()
            self.info.set(f'TXT importado: {len(accounts)} correos ({added} nuevos). Las claves están cifradas para este usuario de Windows.')
        except Exception as ex:
            messagebox.showerror('Importación TXT',str(ex)[:220])

    def _update_counts(self):
        try:
            c=self.queue.counts()
            self.accounts_label.set(f'Cuentas: {c["total"]} · Nuevo: {c["nuevos"]} · Usado: {c["usados"]} · Seleccionados: {c["seleccionados"]}')
            picker=getattr(self,'account_picker',None)
            if picker is not None:
                emails=[row['email'] for row in self.queue.entries()]
                current=self.email.get().strip().lower()
                if current and current not in emails:emails.insert(0,current)
                picker.configure(values=emails)
        except Exception:self.accounts_label.set('No se pudo leer la lista de cuentas.')

    def _choose_account(self,email):
        if self.browser.running:
            messagebox.showinfo('Sesión activa','Cierra la ventana privada antes de seleccionar otra cuenta.')
            return
        if not self.queue.activate(email):
            messagebox.showwarning('Cuenta','La cuenta no está disponible.');return
        self.email.set(email)
        self.password.set('')
        self._auto_start_attempted=False
        self.info.set('Seleccionada '+email+'. Todavía figura como NUEVO hasta iniciar el acceso.')
        self._update_counts()

    def next_account(self):
        if self.browser.running:
            messagebox.showinfo('Sesión activa','Cierra primero la ventana privada.');return
        if self.browser.rate_limited:
            messagebox.showwarning('Microsoft 429','Acceso en pausa por límite de Microsoft. No cambiaré de cuenta.');return
        address=self.queue.choose(exclude=self.email.get().strip().lower()) or self.queue.choose()
        if not address:
            self.info.set('No hay cuentas NUEVAS seleccionadas. Marca cuentas desde VER / ELEGIR CUENTA.');return
        self._choose_account(address)

    def manage_accounts(self):
        win=tk.Toplevel(self);win.title('Cuentas Outlook · Nuevo / Usado')
        win.geometry('760x570');win.configure(bg=BG)
        style=ttk.Style(win)
        style.configure('GD.Treeview',background=BOX,foreground=WHITE,fieldbackground=BOX,rowheight=26)
        style.map('GD.Treeview',background=[('selected','#705C34')],foreground=[('selected',WHITE)])
        self.label(win,'LISTADO DE CUENTAS',GOLD,13,True).pack(anchor='w',padx=15,pady=(15,6))
        self.label(win,'NUEVO = aún no se inició un acceso con este bot. USADO = ya se intentó acceder.',GRAY,9).pack(anchor='w',padx=15)
        self.label(win,'Selecciona varias filas con Ctrl o Mayús, o pulsa SELECCIONAR TODOS.',GRAY,9).pack(anchor='w',padx=15,pady=(0,6))
        outer=tk.Frame(win,bg=BG);outer.pack(fill='both',expand=True,padx=15,pady=8)
        sc=tk.Scrollbar(outer);sc.pack(side='right',fill='y')
        tree=ttk.Treeview(outer,columns=('correo','estado','sel'),show='headings',selectmode='extended',yscrollcommand=sc.set,style='GD.Treeview')
        tree.heading('correo',text='CORREO');tree.heading('estado',text='ESTADO');tree.heading('sel',text='EN LISTA')
        tree.column('correo',width=415,anchor='w');tree.column('estado',width=105,anchor='center');tree.column('sel',width=105,anchor='center')
        tree.pack(side='left',fill='both',expand=True);sc.configure(command=tree.yview)
        entries=self.queue.entries()
        for n,row in enumerate(entries):
            tree.insert('', 'end', iid=str(n),values=(row['email'],row['estado'],'Sí' if row['seleccionado'] else 'No'))
        # El resaltado inicial reproduce las cuentas previamente seleccionadas.
        already=[str(n) for n,row in enumerate(entries) if row['seleccionado']]
        if already:tree.selection_set(already)
        def refresh():
            for n,row in enumerate(self.queue.entries()):
                tree.item(str(n),values=(row['email'],row['estado'],'Sí' if row['seleccionado'] else 'No'))
            self._update_counts()
        def apply():
            picked=[entries[int(i)]['email'] for i in tree.selection()]
            self.queue.set_selected(picked);refresh()
            self.info.set(f'Se seleccionaron {len(picked)} cuentas. Solo NUEVO se procesa automáticamente.')
        def all_accounts():
            tree.selection_set(tree.get_children());self.queue.select_all();refresh()
        def none():
            tree.selection_remove(tree.selection());self.queue.deselect_all();refresh()
        def choose_one():
            selected=tree.selection()
            if not selected:
                messagebox.showinfo('Seleccionar cuenta','Selecciona una fila.');return
            self._choose_account(entries[int(selected[0])]['email'])
            refresh()
        bar=tk.Frame(win,bg=BG);bar.pack(fill='x',padx=15,pady=(5,12))
        self.button(bar,'SELECCIONAR TODOS',all_accounts,True).pack(side='left',padx=(0,6))
        self.button(bar,'QUITAR TODOS',none).pack(side='left',padx=(0,6))
        self.button(bar,'GUARDAR SELECCIÓN',apply).pack(side='left',padx=(0,6))
        self.button(bar,'ELEGIR UNA',choose_one).pack(side='left')
        self.label(win,'Importar o seleccionar no marca un correo como USADO. Los estados se conservan al cerrar.',GRAY,9).pack(anchor='w',padx=15,pady=(0,10))

    def save_auto_queue(self):
        if self.auto_queue.get():
            self._auto_queue_enabled.set()
            self._auto_start_attempted=False
        else:self._auto_queue_enabled.clear()
        settings=get_settings()
        settings['auto_queue']=bool(self.auto_queue.get())
        save_settings(settings)
        self.info.set('Entrada automática por solicitud IMSS '+('activada.' if self.auto_queue.get() else 'desactivada.'))

    def _maybe_start_request_account(self, state, explicit=False):
        """Un único inicio por solicitud y cuenta, solo tras la pausa y con autorización."""
        if not self.auto_queue.get() or state.get('status')!='ESPERANDO_CODIGO':return
        req_id=state.get('request_id')
        email=str(state.get('email') or '').strip().lower()
        if not req_id or not EMAIL_RE.fullmatch(email):return
        if req_id==self._auto_started_request:return
        if self.browser.running or self.browser.rate_limited or self.cooldown.remaining():return
        if not self.queue.is_selected_new(email):
            if not explicit:return
            if not any(row['email']==email and row['seleccionado'] for row in self.queue.entries()):
                self.info.set('Selecciona en CUENTAS el correo que solicita IMSS.')
                return
        try: pw=self._vault().password(email)
        except Exception as exc:
            self.info.set('Cuenta seleccionada sin contraseña accesible: '+email)
            return
        if not pw:return
        self.email.set(email);self.password.set('')
        if self._start_browser(email,pw):self._auto_started_request=req_id

    def _start_browser(self,email,pw):
        if not self._guard_new_login():return False
        self.browser_events=[]
        self.browser_status.set('Abriendo Microsoft en incógnito…')
        self.browser.set_sender(self.sender.get())
        try:self.browser.start(email,pw)
        except Exception as exc:
            reason=self.browser.last_error or ('No se pudo abrir Outlook ('+type(exc).__name__+'). Revisa AJUSTES > Diagnóstico.')
            self.browser_status.set(reason);self.info.set(reason)
            return False
        # No marcar USADO hasta confirmar que se creó la pestaña real.
        self._launch_recorded=False
        self.active_email=email
        self.active_email_label.set(email)
        self._previous_browser_running=True
        self.password.set('')
        self._update_counts()
        self.info.set('Iniciando acceso automático para '+email+'…')
        return True

    def open_incognito(self):
        email=self.email.get().strip().lower()
        if not EMAIL_RE.fullmatch(email):messagebox.showerror('Correo','Escribe un correo válido.');return
        pw=self.password.get()
        try:
            vault=self._vault()
            common_enabled=vault.has_common_password()
            if common_enabled or not pw:
                pw=vault.password(email) or ''
        except Exception as exc:
            messagebox.showerror('Contraseña','No se pudo leer la contraseña cifrada ('+type(exc).__name__+').')
            return
        if not pw:
            messagebox.showerror('Contraseña','Escribe la contraseña o guarda una antes.');return
        if not self._guard_new_login():return
        if self.save_pw.get() and not common_enabled:
            try:self._vault().save([(email,pw)])
            except Exception as e:messagebox.showerror('Guardado',str(e)[:160]);return
        save_settings({'email':email,'sender':self.sender.get().strip().lower(),'client_id':self.client_id.get().strip(),'auto_queue':bool(self.auto_queue.get())})
        self._start_browser(email,pw)

    def _deliver_browser_code(self, request_id, code, email):
        # Callback del hilo Playwright: no tocar Tk aquí.
        self.state.put_code(request_id,code,email=email)
        self.post_ui(lambda:self.info.set('Código verificado del correo reciente y enviado a IMSS por el enlace local.'))

    def send_manual_code(self):
        code=self.code.get().strip()
        if not re.fullmatch('[0-9]{6}',code):
            messagebox.showerror('Código','Introduce seis dígitos.');return
        data=self.state.status()
        if data['status'] not in ('ESPERANDO_CODIGO','CODIGO_DISPONIBLE'):
            messagebox.showerror('IMSS','No hay una solicitud IMSS pendiente. Inicia el trámite en el otro programa.');return
        actual=self.email.get().strip().lower()
        try:self.state.put_code(data['request_id'],code,email=actual)
        except Exception as e:messagebox.showerror('No se envió',str(e));return
        self.code.set('')
        self.info.set('Código enviado a IMSS por el enlace local. No se guardó en disco.')

    def authorize_microsoft(self):
        email=self.email.get().strip().lower()
        if not EMAIL_RE.fullmatch(email):messagebox.showerror('Correo','Introduce un correo válido.');return
        sender=self.sender.get().strip().lower()
        if not EMAIL_RE.fullmatch(sender):messagebox.showerror('Remitente','Indica el remitente real y exacto del código recibido.');return
        save_settings({'email':email,'sender':sender,'client_id':self.client_id.get().strip(),'auto_queue':bool(self.auto_queue.get())})
        try:self._mail()
        except Exception as exc:
            self.info.set('No se pudo preparar Microsoft: '+type(exc).__name__);return
        self.info.set('Abriendo autorización oficial de Microsoft para leer solo el correo de esta cuenta…')
        def worker():
            try:
                self._mail().connect_interactive(email)
                self.post_ui(lambda:self.info.set('Lectura de Microsoft autorizada. El bot buscará códigos nuevos del remitente configurado.'))
            except Exception as e:
                msg=str(e)[:200]
                self.post_ui(lambda:self.info.set('Autorización no completada: '+msg))
        threading.Thread(target=worker,daemon=True).start()

    def tick(self):
        try:
            for _ in range(100):
                try:callback=self._ui_events.get_nowait()
                except ui_queue.Empty:break
                try:callback()
                except Exception as exc:record('outlook_ui_callback_failed',exc)
            self._tick_once()
        except Exception as exc:
            record('outlook_tick_failed',exc)
        finally:
            if not self._closed:self.after(1000,self.tick)

    def _tick_once(self):
        if self.browser.browser_opened.is_set() and not self._launch_recorded:
            if self.active_email:self.queue.mark_started(self.active_email)
            self._launch_recorded=True
        # El cierre inesperado del navegador también inicia la pausa.
        if self._previous_browser_running and not self.browser.running:
            self.active_email_label.set('Ninguna sesión abierta')
            if self.browser.browser_opened.is_set():self.cooldown.begin()
            if self.browser.last_error:
                self.browser_status.set(self.browser.last_error)
                self.info.set('Corrige el problema indicado y pulsa INICIAR para volver a intentar.')
            self._previous_browser_running=False
        elif self.browser.running:
            self._previous_browser_running=True
            if self.active_email:self.active_email_label.set(self.active_email)
        remain=self.cooldown.remaining()
        if self.browser.rate_limited:
            self.cooldown_label.set('MICROSOFT 429 · Acceso detenido. No cambiar de cuenta.')
        elif remain:
            self.cooldown_label.set(f'ENFRIAMIENTO · {remain:02d} segundos antes de otra cuenta')
        elif self.browser.running:
            self.cooldown_label.set('SESIÓN PRIVADA ACTIVA')
        else:
            self.cooldown_label.set('ENFRIAMIENTO · Listo para iniciar')
        self._update_counts()
        self.browser.set_sender(self.sender.get())
        state=self.state.status()
        self._maybe_auto_start(state)
        if state['status']=='SIN_SOLICITUD':
            self.link_status.set('Enlace listo. Esperando que IMSS inicie un trámite…' if self.server else 'Puerto ocupado; cierra el Outlook anterior.')
        elif state['status']=='SOLICITUD_IMSS_ENVIADA':
            self.link_status.set('IMSS terminó la solicitud. Espera el mensaje de Historia Laboral y revisa el enlace al PDF.')
        elif state['status']=='CADUCADA':
            self.link_status.set('Solicitud IMSS caducada; inicia una nueva en IMSS.')
        elif state['status']=='CODIGO_DISPONIBLE':
            self.link_status.set('Código listo en el enlace. Esperando que el bot IMSS lo recoja.')
        elif state['status']=='CODIGO_ENVIADO_AL_CELULAR':
            self.link_status.set('El bot IMSS confirmó la recepción del código. La sesión permanece abierta.')
        else:
            self.link_status.set('Solicitud IMSS para '+str(state['email'])+' · '+str(state['status']))
            if state['status']=='ESPERANDO_CODIGO' and not self.auto_busy and (time.monotonic()-self.last_auto_check)>5:
                sender=self.sender.get().strip().lower()
                if (EMAIL_RE.fullmatch(sender) and self.client_id.get().strip() and
                    self.email.get().strip().lower()==state['email']):
                    self._mail()  # create the service on the Tk thread
                    self.auto_busy=True;self.last_auto_check=time.monotonic()
                    threading.Thread(target=self._try_auto_code,args=(state,sender),daemon=True).start()


    def _try_auto_code(self,request,sender):
        try:
            found=self._mail().code(request['email'],sender,request['started'])
            if found and found.get('code'):
                self.state.put_code(request['request_id'],found['code'],email=request['email'])
                self.post_ui(lambda:self.info.set('Código disponible en el enlace. Esperando confirmación del bot IMSS.'))
        except Exception as e:
            # No imprimir tokens/códigos de mensajes. Evita afirmaciones de éxito.
            short=str(e)[:130]
            if ('sin autorización' in short.lower() or 'faltan dependencias' in short.lower()):
                self.post_ui(lambda:self.info.set('Lectura automática inactiva: '+short))
        finally:self.auto_busy=False

    def close(self):
        self._closed=True
        self.close_private()
        if self.server:
            try:self.server.close()
            except Exception:pass
        self.destroy()

if __name__=='__main__':
    from ejecutar import main
    main()
