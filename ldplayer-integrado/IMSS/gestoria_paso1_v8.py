# -*- coding: utf-8 -*-
"""Gestoría Díaz · Paso 1 · Tres instancias Android.

Solo ingresar CURP/correo, marcar aviso y pulsar Iniciar sesión.
NO lee ni automatiza códigos, PIN, verificaciones, PDFs o WhatsApp.
La conexión y apertura se importan sin cambios de la V7 probada.
"""
from __future__ import annotations

from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import pathlib
import queue
import re
import threading
import tkinter as tk
from tkinter import filedialog, messagebox

from gestoria_prueba_v7 import (process, devices_from_output,
                                 adb_run, locate_adb, launch_imss, foreground, short)
from gestoria_prueba_v23 import select_serials, MAX_ANDROID
from imss_paso1 import check_login, do_login, ui_dump, validation_detected

BG = '#111215'; PANEL = '#1d1f25'; GOLD = '#e2b44c'; FG = '#f8f5ed'
MUTED = '#bcbab3'; RED = '#ff8f88'; GREEN = '#80daa3'; BLUE = '#9ac7f5'


class Panel:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title('GESTORÍA DÍAZ · IMSS DIGITAL · PASO 1 V8')
        root.geometry('1240x830'); root.minsize(1050, 700); root.configure(bg=BG)
        self.messages = queue.Queue()
        self.adb = None
        self.serials = [None] * MAX_ANDROID
        self.states = ['SIN CONEXIÓN'] * MAX_ANDROID
        self.allow_manual = [False] * MAX_ANDROID
        self.pending = deque()
        self.executor = ThreadPoolExecutor(max_workers=MAX_ANDROID)
        self.working = False
        self.sequence = 0
        self.count_sent = 0

        header = tk.Frame(root, bg=BG, padx=18, pady=15); header.pack(fill='x')
        tk.Label(header, text='GESTORÍA DÍAZ', bg=BG, fg=GOLD,
                 font=('Segoe UI', 25, 'bold')).pack(anchor='w')
        tk.Label(header, text='IMSS DIGITAL · 4 LDPLAYER · PRUEBA PASO 1 V8', bg=BG,
                 fg=FG, font=('Segoe UI', 10, 'bold')).pack(anchor='w')
        tk.Label(header, text='Conexión/apertura tomadas de V7 sin modificaciones. '
                 'El trámite se detiene en la verificación de identidad.',
                 bg=BG, fg=MUTED).pack(anchor='w', pady=(6, 0))

        bar = tk.Frame(root, bg=BG, padx=16, pady=7); bar.pack(fill='x')
        self.connect_btn = self.button(bar, '1. CONECTAR 4 POR ADB', self.connect, GOLD, '#111215')
        self.connect_btn.pack(side='left', expand=True, fill='x', padx=4)
        self.open_btn = self.button(bar, '2. ABRIR IMSS (V7)', self.open_imss, '#343842', FG)
        self.open_btn.pack(side='left', expand=True, fill='x', padx=4)

        tk.Label(root, text='ESTADO DE LAS INSTANCIAS', bg=BG, fg=GOLD,
                 font=('Segoe UI', 10, 'bold')).pack(anchor='w', padx=18, pady=(10, 5))
        cells = tk.Frame(root, bg=BG, padx=12); cells.pack(fill='x')
        self.status_labels, self.detail_labels = [], []
        for i in range(MAX_ANDROID):
            card = tk.Frame(cells, bg=PANEL, padx=9, pady=11)
            card.pack(side='left', fill='both', expand=True, padx=6)
            tk.Label(card, text=f'ANDROID {i+1}', fg=GOLD, bg=PANEL,
                     font=('Segoe UI', 13, 'bold')).pack()
            s = tk.Label(card, text='SIN CONEXIÓN', fg=RED, bg=PANEL,
                         font=('Segoe UI', 10, 'bold'))
            s.pack(pady=(9, 3)); self.status_labels.append(s)
            d = tk.Label(card, text='Inicia LDPlayer', fg=MUTED, bg=PANEL,
                         font=('Segoe UI', 9), wraplength=215, justify='center')
            d.pack(pady=(0, 8)); self.detail_labels.append(d)
            tk.Button(card, text='COMPROBAR SI ESTÁ LIBRE', command=lambda j=i: self.mark_ready(j),
                      bg='#343842', fg=FG, activebackground=GOLD, bd=0,
                      font=('Segoe UI', 8, 'bold'), padx=8, pady=6).pack(fill='x')

        form = tk.Frame(root, bg=PANEL, padx=18, pady=13); form.pack(fill='x', padx=18, pady=(15, 5))
        tk.Label(form, text='NUEVA SOLICITUD · UN SOLO FORMULARIO', bg=PANEL,
                 fg=GOLD, font=('Segoe UI', 10, 'bold')).pack(anchor='w')
        inputs = tk.Frame(form, bg=PANEL); inputs.pack(fill='x', pady=(10, 7))
        curp_col = tk.Frame(inputs, bg=PANEL); curp_col.pack(side='left', fill='x', expand=True, padx=(0, 8))
        email_col = tk.Frame(inputs, bg=PANEL); email_col.pack(side='left', fill='x', expand=True, padx=(8, 0))
        tk.Label(curp_col, text='CURP (18 caracteres)', bg=PANEL, fg=FG).pack(anchor='w')
        self.curp_var = tk.StringVar()
        self.curp_var.trace_add('write', self.upper_curp)
        self.curp_entry = tk.Entry(curp_col, textvariable=self.curp_var, bg='#eae9e5', fg='#181818',
                                   font=('Segoe UI', 12), bd=0)
        self.curp_entry.pack(fill='x', ipady=8, pady=(4, 0))
        tk.Label(email_col, text='Correo autorizado de verificación', bg=PANEL, fg=FG).pack(anchor='w')
        self.email_var = tk.StringVar()
        self.email_entry = tk.Entry(email_col, textvariable=self.email_var, bg='#eae9e5',
                                    fg='#181818', font=('Segoe UI', 12), bd=0)
        self.email_entry.pack(fill='x', ipady=8, pady=(4, 0))
        self.permission = tk.BooleanVar(value=False)
        tk.Checkbutton(form, text='Confirmo que el titular autorizó este trámite y el uso de su correo.',
                       variable=self.permission, bg=PANEL, fg=FG, selectcolor=PANEL,
                       activebackground=PANEL, activeforeground=FG, bd=0).pack(anchor='w', pady=7)
        self.add_btn = self.button(form, '3. ENVIAR AL ANDROID LIBRE / PONER EN COLA', self.enqueue, GOLD, '#111215')
        self.add_btn.pack(fill='x', pady=(2, 2))
        self.queue_label = tk.Label(form, text='Solicitudes en espera: 0  ·  Inicios enviados: 0',
                                    bg=PANEL, fg=MUTED, font=('Segoe UI', 9))
        self.queue_label.pack(anchor='w', pady=(7, 0))

        tk.Label(root, text='REGISTRO SIN CURP, EMAIL NI CONTRASEÑAS', bg=BG, fg=GOLD,
                 font=('Segoe UI', 10, 'bold')).pack(anchor='w', padx=18, pady=(12, 5))
        logframe = tk.Frame(root, bg=BG, padx=18); logframe.pack(fill='both', expand=True)
        self.logtext = tk.Text(logframe, bg=PANEL, fg=FG, font=('Consolas', 9),
                               padx=10, pady=8, bd=0, state='disabled', wrap='word')
        self.logtext.pack(side='left', fill='both', expand=True)
        scrollbar = tk.Scrollbar(logframe, command=self.logtext.yview)
        scrollbar.pack(side='right', fill='y'); self.logtext.configure(yscrollcommand=scrollbar.set)
        tk.Label(root, text='No automatiza códigos, PIN ni WhatsApp · Datos solo en memoria · Uso autorizado',
                 bg=BG, fg=MUTED, font=('Segoe UI', 9)).pack(pady=7)
        menu = tk.Menu(root); opts = tk.Menu(menu, tearoff=False)
        opts.add_command(label='Guardar diagnóstico sin datos personales', command=self.save_log)
        opts.add_command(label='Vaciar solicitudes pendientes', command=self.clear_pending)
        menu.add_cascade(label='Opciones', menu=opts); root.configure(menu=menu)
        root.protocol('WM_DELETE_WINDOW', self.close)
        self.log('V8 inicializada. La base de conexión y apertura es V7 original.')
        root.after(140, self.pump)

    @staticmethod
    def button(parent, name, fn, bg, fg):
        return tk.Button(parent, text=name, command=fn, bg=bg, fg=fg,
                         font=('Segoe UI', 10, 'bold'), bd=0, pady=12)

    def upper_curp(self, *_):
        val = self.curp_var.get()
        clean = re.sub('[^A-Z0-9]', '', val.upper())[:18]
        if clean != val:
            self.curp_var.set(clean)

    def log(self, info):
        self.logtext.configure(state='normal')
        self.logtext.insert('end', f'[{datetime.now():%H:%M:%S}] {info}\n')
        self.logtext.see('end'); self.logtext.configure(state='disabled')

    def send(self, *msg):
        self.messages.put(msg)

    def set_status(self, i, status, detail):
        self.states[i] = status
        self.status_labels[i].configure(text=status, fg=GREEN if status == 'LIBRE' else
                                        BLUE if status in ('OCUPADO', 'ESPERANDO CÓDIGO', 'CONECTADO') else
                                        MUTED if status in ('REVISAR', 'ABRIENDO', 'BUSCANDO') else RED)
        self.detail_labels[i].configure(text=detail)

    def update_count(self):
        self.queue_label.configure(text=f'Solicitudes en espera: {len(self.pending)}  ·  Inicios enviados: {self.count_sent}')

    def pump(self):
        try:
            while True:
                action, *args = self.messages.get_nowait()
                if action == 'log': self.log(args[0])
                elif action == 'status': self.set_status(*args)
                elif action == 'attached':
                    self.adb, self.serials, assessments = args
                    for i, info in enumerate(assessments):
                        self.set_status(i, info[0], info[1])
                    self.working = False
                elif action == 'opened':
                    for i, status, detail in args[0]:
                        self.set_status(i, status, detail)
                    self.working = False
                elif action == 'work_result':
                    slot, status, detail = args
                    self.set_status(slot, status, detail)
                    if status == 'ESPERANDO CÓDIGO': self.count_sent += 1
                    self.update_count()
                elif action == 'ready':
                    slot, ok, detail = args
                    self.allow_manual[slot] = False
                    self.set_status(slot, 'LIBRE' if ok else 'REVISAR', detail)
                elif action == 'manual_check':
                    i, serial = args
                    if foreground(self.adb, serial) is True:
                        yes = messagebox.askyesno('Confirmar pantalla inicial',
                            f'Android {i+1}: no pude leer los controles.\n\n'
                            '¿Estás viendo AHORA MISMO la pantalla inicial de IMSS Digital '
                            'con los campos CURP y correo?')
                        if yes:
                            self.allow_manual[i] = True
                            self.set_status(i, 'LIBRE', 'Confirmación visual del operador')
                    else:
                        messagebox.showwarning('No disponible', 'IMSS Digital no está en primer plano.')
                elif action == 'finish':
                    self.working = False
        except queue.Empty:
            pass
        self.dispatch()
        self.root.after(140, self.pump)

    def connect(self):
        if self.working or any(x == 'OCUPADO' for x in self.states): return
        self.working = True
        for i in range(MAX_ANDROID): self.set_status(i, 'BUSCANDO', 'Detectando por ADB')
        threading.Thread(target=self.connect_worker, daemon=True).start()

    def connect_worker(self):
        try:
            adb = locate_adb()
            if not adb:
                raise RuntimeError('No se encontró adb.exe de LDPlayer 9.')
            rc, out = process([adb, 'start-server'], timeout=18)
            if rc: raise RuntimeError('No se pudo iniciar ADB.')
            rc, out = process([adb, 'devices', '-l'], timeout=18)
            if rc: raise RuntimeError('ADB no pudo listar dispositivos.')
            found = devices_from_output(out)
            selected = select_serials(found)
            if len(selected) < MAX_ANDROID:
                for idx in range(MAX_ANDROID):
                    if idx not in [n for n, _ in selected]:
                        try:
                            process([adb, 'connect', f'127.0.0.1:{5555 + idx * 2}'], timeout=8)
                        except Exception: pass
                rc, out = process([adb, 'devices', '-l'], timeout=15)
                if rc == 0: selected = select_serials(devices_from_output(out))
            serials = [None] * MAX_ANDROID
            assessed = [('SIN CONEXIÓN', 'No se detectó otro emulador') for _ in range(MAX_ANDROID)]
            for slot, (idx, serial) in enumerate(selected):
                rc, out = adb_run(adb, serial, 'shell', 'echo', 'GESTORIA_OK', timeout=12)
                if rc == 0 and 'GESTORIA_OK' in out:
                    serials[slot] = serial
                    ok, why = check_login(adb, serial)
                    assessed[slot] = ('LIBRE' if ok else 'REVISAR', f'{serial} · {why}')
            self.send('attached', adb, serials, assessed)
            self.send('log', f'ADB: {sum(bool(x) for x in serials)} de {MAX_ANDROID} emuladores conectados.')
            self.send('log', 'Solo se asignan solicitudes a Android marcados LIBRE.')
        except Exception as exc:
            self.send('log', 'Error de conexión: ' + str(exc)[:180])
            self.send('finish')
            for i in range(MAX_ANDROID): self.send('status', i, 'REVISAR', 'Comprueba ADB y vuelve a conectar')

    def open_imss(self):
        if self.working: return
        if not self.adb or not any(self.serials):
            messagebox.showinfo('Conecta primero', 'Presiona primero el botón 1.'); return
        if any(s in ('OCUPADO', 'ESPERANDO CÓDIGO') for s in self.states):
            messagebox.showwarning('Hay trámites activos', 'No abras de nuevo IMSS mientras algún Android esté en verificación.')
            return
        self.working = True
        threading.Thread(target=self.open_worker, daemon=True).start()

    def open_worker(self):
        result = []
        with ThreadPoolExecutor(max_workers=MAX_ANDROID) as pool:
            ftrs = {pool.submit(launch_imss, self.adb, serial,
                                lambda txt: None): i
                    for i, serial in enumerate(self.serials) if serial}
            for f in as_completed(ftrs):
                i = ftrs[f]
                try:
                    label, detail = f.result()
                    if label == 'ABIERTA':
                        ready, why = check_login(self.adb, self.serials[i])
                        result.append((i, 'LIBRE' if ready else 'REVISAR', why))
                    else:
                        result.append((i, 'REVISAR', detail))
                except Exception:
                    result.append((i, 'REVISAR', 'No se pudo abrir IMSS Digital'))
        self.send('opened', result)
        self.send('log', 'Se comprobó la apertura IMSS mediante el núcleo V7.')

    def mark_ready(self, i):
        serial = self.serials[i]
        if not serial:
            messagebox.showinfo('Sin ADB', f'Android {i+1} no está conectado.'); return
        if self.states[i] == 'OCUPADO':
            messagebox.showinfo('En proceso', 'No interrumpas una escritura en curso.'); return
        if self.states[i] == 'ESPERANDO CÓDIGO':
            if not messagebox.askyesno('Confirmar término',
                    '¿Ya terminó la verificación y regresaste MANUALMENTE a la pantalla inicial de IMSS Digital?'):
                return
        threading.Thread(target=self.ready_worker, args=(i, serial), daemon=True).start()

    def ready_worker(self, i, serial):
        ok, detail = check_login(self.adb, serial)
        if ok:
            self.send('ready', i, True, 'Pantalla inicial comprobada')
            self.send('log', f'Android {i+1}: pantalla inicial comprobada; disponible.')
            return
        # Si Android no expone texto accesible, permitir confirmación visual en GUI.
        self.send('status', i, 'REVISAR', detail)
        self.send('log', f'Android {i+1}: no confirmó inicio por accesibilidad.')
        self.send('manual_check', i, serial)

    def enqueue(self):
        curp = self.curp_var.get().strip().upper()
        email = self.email_var.get().strip()
        if not re.fullmatch(r'[A-Z0-9]{18}', curp):
            messagebox.showerror('CURP', 'Introduce exactamente 18 caracteres alfanuméricos.'); return
        if not re.fullmatch(r'[A-Za-z0-9._+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}', email):
            messagebox.showerror('Correo', 'Introduce un correo válido (sin espacios).'); return
        if not self.permission.get():
            messagebox.showwarning('Autorización', 'Confirma primero la autorización del titular.'); return
        if not self.adb or not any(self.serials):
            messagebox.showwarning('Conectar', 'Primero conecta los emuladores por ADB.'); return
        if len(self.pending) >= 100:
            messagebox.showwarning('Cola llena', 'Esta prueba limita la cola a 100 solicitudes.'); return
        self.sequence += 1
        self.pending.append((self.sequence, curp, email))
        self.curp_var.set('')
        self.email_var.set('')  # evita dejar datos privados visibles en pantalla
        self.permission.set(False)
        self.update_count()
        self.log('Nueva solicitud recibida (datos privados omitidos del diagnóstico).')

    def dispatch(self):
        # El hilo de Tkinter es dueño exclusivo de cola, estados y asignación.
        if self.working:
            return
        while self.pending:
            slot = next((i for i, state in enumerate(self.states)
                         if state == 'LIBRE' and self.serials[i]), None)
            if slot is None: break
            reqid, curp, email = self.pending.popleft()
            self.set_status(slot, 'OCUPADO', 'Ingresando CURP, correo y aviso')
            allow_override = self.allow_manual[slot]
            self.allow_manual[slot] = False
            self.log(f'Solicitud #{reqid} asignada a Android {slot+1}.')
            self.update_count()
            self.executor.submit(self.login_worker, slot, reqid, curp, email, allow_override)

    def login_worker(self, slot, reqid, curp, email, override):
        try:
            state, detail = do_login(self.adb, self.serials[slot], curp, email,
                                     ready_confirmed_by_operator=override,
                                     update=lambda txt: self.send('status', slot, 'OCUPADO', txt))
        except Exception:
            state, detail = 'REVISAR', 'Falló la automatización; revisa la pantalla del emulador.'
        self.send('work_result', slot, state, detail)
        self.send('log', f'Android {slot+1} · solicitud #{reqid}: {state}. No se registran datos personales.')

    def clear_pending(self):
        if self.pending and messagebox.askyesno('Vaciar cola', '¿Eliminar las solicitudes que aún no comenzaron?'):
            self.pending.clear(); self.update_count(); self.log('Cola pendiente borrada.')

    def save_log(self):
        path = filedialog.asksaveasfilename(defaultextension='.txt',
                                            filetypes=[('Texto', '*.txt')])
        if path:
            pathlib.Path(path).write_text(self.logtext.get('1.0','end'), encoding='utf-8')

    def close(self):
        if any(s == 'OCUPADO' for s in self.states):
            if not messagebox.askyesno('Trabajo en curso', 'Hay un Android escribiendo. ¿Cerrar de todos modos?'):
                return
        self.pending.clear(); self.executor.shutdown(wait=False, cancel_futures=True)
        self.root.destroy()


def main():
    win = tk.Tk()
    Panel(win)
    win.mainloop()


if __name__ == '__main__':
    main()
