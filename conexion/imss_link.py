import json
from pathlib import Path
import re
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox

from .bridge import Bridge, read_json, write_json
from .reader import normalized


class ImssConnection:
    def __init__(self, app):
        self.app = app
        self.bridge = Bridge()
        self.active = False
        self.cancel = threading.Event()
        self.job = None
        self.rejected = False
        self.reset_ready = False
        self.auto = tk.BooleanVar(value=True)
        saved = read_json(self.bridge.root / 'preferencias.json') or {}
        self.sender = tk.StringVar(value=saved.get('sender', ''))
        self.subject = tk.StringVar(value=saved.get('subject', ''))
        self.app.root.protocol('WM_DELETE_WINDOW', self.close_window)

    def close_window(self):
        self.cancel.set()
        if self.job:
            self.bridge.finish(self.job)
        self.app.root.destroy()

    def controls(self, parent):
        frame = tk.Frame(parent, bg='#222229', padx=10, pady=8)
        frame.pack(fill='x', padx=24, pady=8)
        tk.Checkbutton(frame, text='Outlook → IMSS → código automático', variable=self.auto,
                       bg='#222229', fg='white', selectcolor='#121217', activebackground='#222229').pack(side='left')
        tk.Button(frame, text='Configurar lector', command=self.settings).pack(side='left', padx=8)
        tk.Button(frame, text='Detener solicitud', command=self.stop, bg='#862e35', fg='white').pack(side='right')

    def settings(self):
        window = tk.Toplevel(self.app.root)
        window.title('Correo del IMSS que contiene el código')
        window.geometry('620x240')
        for label, variable in [('Remitente completo del correo del IMSS', self.sender),
                                ('Texto del asunto que identifica ese correo', self.subject)]:
            ttk.Label(window, text=label).pack(anchor='w', padx=16, pady=(12, 3))
            ttk.Entry(window, textvariable=variable, width=75).pack(padx=16, fill='x')
        def save():
            if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', self.sender.get().strip()) or not self.subject.get().strip():
                messagebox.showerror('Lector', 'Escribe el remitente y el asunto reales del mensaje del IMSS.', parent=window)
                return
            try:
                write_json(self.bridge.root / 'preferencias.json',
                           {'sender': self.sender.get().strip(), 'subject': self.subject.get().strip()})
            except OSError:
                messagebox.showerror('Lector', 'No se pudo guardar la configuración local.', parent=window)
                return
            window.destroy()
        ttk.Button(window, text='Guardar configuración', command=save).pack(pady=16)

    def start(self, path, curp, instance, procedure):
        if self.active or self.app.busy:
            self.app.emit('Espera a que termine la operación actual.')
            return
        sender, subject = self.sender.get().strip(), self.subject.get().strip()
        if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', sender) or not subject:
            self.settings()
            self.app.emit('Configura remitente y asunto antes de activar el lector automático.')
            return
        if not self.bridge.presence():
            self.app.emit('Abre INICIAR_OUTLOOK_CONECTADO, importa las cuentas y pulsa ACTIVAR CONEXIÓN IMSS.')
            return
        self.active = True
        self.app.busy = True
        self.cancel.clear()
        self.app.btn_consulta.configure(state='disabled')
        self.app.btn_codigo.configure(state='disabled')
        self.app.selector_cantidad.configure(state='disabled')
        threading.Thread(target=self.run, args=(path, curp, instance, procedure, sender, subject), daemon=True).start()

    def stop(self):
        self.cancel.set()
        if self.job:
            self.bridge.finish(self.job)
        self.app.emit('Deteniendo la solicitud conectada; la entrada manual queda disponible al terminar.')

    def response(self, key, email, instance, statuses, timeout):
        end = time.monotonic() + timeout
        while time.monotonic() < end and not self.cancel.is_set():
            response = self.bridge.response(key)
            if response and response.get('id') == key and response.get('email', '').casefold() == email.casefold() and response.get('instance') == instance:
                if response.get('status') in statuses:
                    return response
            if not self.bridge.presence():
                return {'status': 'stopped', 'reason': 'Se desconectó el bot de Outlook.'}
            self.cancel.wait(.5)
        return {'status': 'error', 'reason': 'Tiempo de espera agotado o solicitud detenida.'}

    def return_to_login(self, path, idx, nodes=None):
        # Navigation helpers are imported from the actual bot instance's module.
        import sys
        module = sys.modules[type(self.app).__module__]
        cancelled = False
        accepted = False
        for _ in range(12):
            if self.cancel.is_set():
                return False
            if nodes is None:
                nodes = module.pantalla(path, idx)
            visible = [n for n in nodes if n.get('visible', True) and n.get('area', 0) > 0]
            words = module.texto_normalizado(module.todo_texto(visible))
            code_screen = 'codigo de validacion' in words or bool(module.cajas_codigo_validacion(visible))
            fields = [n for n in visible if n.get('enabled')]
            validation_error = self.is_validation_error(visible)
            if not code_screen and not validation_error and module.buscar(fields, 'txtCURP') and module.buscar(fields, 'txtCorreo'):
                return True
            target = 'aceptar' if validation_error and not accepted else 'cancelar' if code_screen and not cancelled else None
            if target:
                buttons = [n for n in fields if any(module.texto_normalizado(label) == target
                    for label in (n.get('valor', ''), n.get('descripcion', ''), n.get('texto', '')))]
                if buttons:
                    module.tocar(path, idx, min(buttons, key=lambda n: n['area'])['xy'])
                    if target == 'aceptar': accepted = True
                    else: cancelled = True
            nodes = None
            self.cancel.wait(.5)
        return False

    def is_validation_error(self, nodes):
        text = normalized(' '.join(n.get('texto', '') for n in nodes
                          if n.get('visible', True) and n.get('area', 0) > 0))
        return bool(re.search(r'error al validar|codigo (?:incorrecto|invalido|vencido|expirado|no es valido)', text))

    def code_rejected(self, path, idx, instance, curp, email, procedure, nodes):
        self.rejected = True
        self.app.pendiente = None
        self.reset_ready = self.return_to_login(path, idx, nodes)
        return self.reset_ready

    def run(self, path, curp, instance, procedure, sender, subject):
        attempted = set()
        reason = 'No se completó la solicitud.'
        try:
            self.app.pendiente = None
            for number in range(1, 4):
                if self.cancel.is_set():
                    return
                presence = self.bridge.presence()
                if not presence:
                    reason = 'Outlook no está conectado.'
                    break
                import sys
                module = sys.modules[type(self.app).__module__]
                excluded = module.correos_usados() | self.app.usados_sesion | attempted
                email = next((value for value in presence['emails'] if value.casefold() not in {v.casefold() for v in excluded}), None)
                if email is None:
                    reason = 'No quedan correos importados y disponibles en Outlook.'
                    break
                attempted.add(email.casefold())
                self.app.emit(f'Intento conectado {number}/3: abriendo la bandeja de {email}')
                self.job = self.bridge.create(email, instance, sender, subject)
                try:
                    ready = self.response(self.job, email, instance, {'ready', 'error', 'limited', 'stopped'}, 330)
                    if ready['status'] != 'ready':
                        reason = ready.get('reason', 'No se pudo abrir la bandeja.')
                        if ready['status'] in ('limited', 'stopped'):
                            break
                        continue
                    self.bridge.started(self.job)
                    self.rejected = False
                    self.reset_ready = False
                    self.app.resultado_tramite = False
                    self.app.pendiente = None
                    self.app.root.after(0, lambda: self.app.codigo.set(''))
                    self.app._consulta(path, curp, email, instance, procedure)
                    pending = self.app.pendiente
                    if not pending or pending[2:5] != (instance, curp, email):
                        reason = 'IMSS no llegó a solicitar el código; revisa la pantalla de la instancia.'
                        break
                    response = self.response(self.job, email, instance, {'code', 'error', 'limited', 'stopped'}, 185)
                    if response['status'] != 'code':
                        reason = response.get('reason', 'No llegó un código verificable.')
                        self.app.pendiente = None
                        if response['status'] in ('limited', 'stopped') or not self.return_to_login(path, pending[1]):
                            break
                        continue
                    code = response.get('code', '')
                    if not re.fullmatch(r'[0-9]{6}', code) or self.app.pendiente != pending or self.cancel.is_set():
                        reason = 'La respuesta ya no corresponde a la solicitud activa.'
                        break
                    self.app.root.after(0, lambda value=code: self.app.codigo.set(value))
                    self.app._codigo(code, *pending)
                    if self.app.resultado_tramite:
                        self.app.emit('✔ Solicitud completada y envío de la constancia confirmado por IMSS.')
                        self.app.events.put(('aviso', '✔ Solicitud completada. Revisa el correo de la constancia.'))
                        return
                    reason = 'El código fue rechazado o IMSS no confirmó el trámite.'
                    if not self.rejected or not self.reset_ready:
                        break             # no repetir un trámite que puede haberse completado
                finally:
                    if self.job:
                        self.bridge.finish(self.job)
                    self.job = None
            if not self.cancel.is_set():
                self.app.emit(f'No se logró completar la solicitud. Correos intentados: {len(attempted)}/3. {reason}')
                self.app.events.put(('aviso', 'No se logró completar la solicitud; revisa el registro.'))
        except Exception:
            self.app.emit('No se logró completar la solicitud conectada. Revisa la conexión y la instancia; puedes usar el modo manual.')
        finally:
            self.active = False
            self.app.busy = False
            def restore():
                self.app.btn_consulta.configure(state='normal')
                self.app.selector_cantidad.configure(state='readonly')
                self.app.btn_codigo.configure(state='normal' if self.app.pendiente else 'disabled')
            try:
                self.app.root.after(0, restore)
            except (RuntimeError, tk.TclError):
                pass
