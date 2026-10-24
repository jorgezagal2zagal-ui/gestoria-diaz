# -*- coding: utf-8 -*-
"""Gestoría Díaz: diagnóstico de tres emuladores LDPlayer e IMSS Digital.

Solo ADB y apertura. No accede a datos personales ni a verificaciones del IMSS.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import queue
import re
import shutil
import subprocess
import threading
import time
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor, as_completed
from tkinter import filedialog, messagebox

HERE = pathlib.Path(__file__).resolve().parent
SETTINGS = HERE / 'config_ldplayer.json'
PACKAGE = 'st.android.imsspublico'  # Aplicación oficial en Google Play
BG = '#111215'; PANEL = '#1d1f25'; GOLD = '#e2b44c'; FG = '#f8f5ed'
MUTED = '#bbb9b3'; RED = '#ff8f88'; GREEN = '#80daa3'


def process(parts, timeout=15):
    command = [str(p) for p in parts]
    try:
        p = subprocess.run(command, capture_output=True, text=True,
                           encoding='utf-8', errors='replace', timeout=timeout,
                           creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except FileNotFoundError as e:
        raise RuntimeError(f'No existe: {command[0]}') from e
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f'Tiempo agotado ({timeout} s): {" ".join(command[1:5])}') from e
    return p.returncode, ((p.stdout or '') + '\n' + (p.stderr or '')).strip()


def adb_run(adb, serial, *args, timeout=15):
    return process([adb, '-s', serial, *args], timeout=timeout)


def devices_from_output(output):
    """ADB output includes one row per transport; do not mistake debug lines for devices."""
    found = {}
    for line in output.splitlines():
        match = re.match(r'^([^\s]+)\s+(device|offline|unauthorized)(?:\s|$)', line.strip())
        if match:
            found[match.group(1)] = match.group(2)
    return found


def index_of_serial(serial):
    """Canonical LDPlayer index for both emulator and loopback aliases."""
    m = re.fullmatch(r'emulator-(\d+)', serial)
    if m:
        n = int(m.group(1)) - 5554
    else:
        m = re.fullmatch(r'(?:127\.0\.0\.1|localhost):(\d+)', serial)
        if not m:
            return None
        n = int(m.group(1)) - 5555
    return n // 2 if n >= 0 and n % 2 == 0 and n <= 200 else None


def select_serials(devices):
    """Use only reachable devices, prioritize emulator-5554 over its tcp alias."""
    grouped = {}
    for serial, state in devices.items():
        idx = index_of_serial(serial)
        if idx is not None and state == 'device':
            grouped.setdefault(idx, []).append(serial)
    return [(idx, sorted(names, key=lambda s: (not s.startswith('emulator-'), s))[0])
            for idx, names in sorted(grouped.items())][:3]


def locate_adb():
    saved = None
    try:
        saved = json.loads(SETTINGS.read_text(encoding='utf-8')).get('folder')
    except (OSError, ValueError, AttributeError):
        pass
    folders = ([pathlib.Path(saved)] if saved else [])
    path_adb = shutil.which('adb')
    if path_adb: folders.append(pathlib.Path(path_adb).parent)
    for disk in 'CDEFGH':
        r = pathlib.Path(disk + ':\\')
        folders += [r / 'LDPlayer' / 'LDPlayer9', r / 'LDPlayer9',
                    r / 'leidian' / 'LDPlayer9', r / 'Program Files' / 'LDPlayer' / 'LDPlayer9',
                    r / 'Program Files (x86)' / 'LDPlayer' / 'LDPlayer9']
    for folder in folders:
        exe = folder / 'adb.exe'
        if exe.is_file():
            return str(exe)
    return None


def short(text, max_chars=240):
    return ' '.join(text.replace('\r', ' ').split())[:max_chars]


def main_package_in_focus(output):
    """Return True, False, or None when the Android version hides focus info."""
    candidates = []
    for line in output.splitlines():
        if any(token in line for token in ('mResumedActivity', 'topResumedActivity',
                                           'ResumedActivity', 'mCurrentFocus', 'mFocusedApp')):
            candidates.append(line)
    if not candidates:
        return None
    # Multiple last-resumed fields can coexist with stale history: prioritize newest top.
    return any(PACKAGE in line for line in candidates)


def foreground(adb, serial):
    readings = []
    for command in [('shell', 'dumpsys', 'activity', 'activities'),
                    ('shell', 'dumpsys', 'window', 'windows')]:
        try:
            rc, output = adb_run(adb, serial, *command, timeout=12)
            if rc == 0:
                result = main_package_in_focus(output)
                if result is not None:
                    readings.append(result)
        except RuntimeError:
            pass
    if True in readings:
        return True
    if False in readings:
        return False
    return None


def verify_focus(adb, serial, attempts=3):
    current = None
    for step in range(attempts):
        current = foreground(adb, serial)
        if current is True:
            return True
        if step < attempts - 1:
            time.sleep(0.7)
    return current


def launch_imss(adb, serial, logger):
    """Check installed package, launch by normal Android intents, confirm foreground."""
    rc, out = adb_run(adb, serial, 'shell', 'pm', 'path', PACKAGE, timeout=18)
    logger(f'{serial}: pm path {PACKAGE}: {short(out, 180) or "sin resultado"}')
    if rc != 0 or 'package:' not in out:
        return 'NO INSTALADA', ('Android no encuentra el paquete oficial ' + PACKAGE
                                + '. Abre Play Store e instala IMSS Digital aquí.')

    # Try the normal Launcher intent via monkey first.
    try:
        rc, out = adb_run(adb, serial, 'shell', 'monkey', '-p', PACKAGE,
                          '-c', 'android.intent.category.LAUNCHER', '1', timeout=22)
        logger(f'{serial}: monkey rc={rc}: {short(out)}')
        if verify_focus(adb, serial, 3) is True:
            return 'ABIERTA', 'IMSS Digital aparece como aplicación activa.'
    except Exception as exc:
        logger(f'{serial}: monkey falló: {exc}')

    # Fallback: package-specific MAIN/LAUNCHER intent.
    try:
        rc, out = adb_run(adb, serial, 'shell', 'am', 'start', '-W', '-a',
                          'android.intent.action.MAIN', '-c',
                          'android.intent.category.LAUNCHER', '-p', PACKAGE, timeout=23)
        logger(f'{serial}: am start rc={rc}: {short(out)}')
        if verify_focus(adb, serial, 3) is True:
            return 'ABIERTA', 'IMSS Digital aparece como aplicación activa.'
    except Exception as exc:
        logger(f'{serial}: am start falló: {exc}')

    # Last attempt: resolve actual launch Activity instead of guessing its class.
    try:
        rc, result = adb_run(adb, serial, 'shell', 'cmd', 'package', 'resolve-activity',
                             '--brief', '-a', 'android.intent.action.MAIN',
                             '-c', 'android.intent.category.LAUNCHER', '-p', PACKAGE, timeout=14)
        logger(f'{serial}: resolve-activity rc={rc}: {short(result)}')
        components = re.findall(r'(?m)^([\w.]+/[\w.$]+)$', result)
        components = [x for x in components if x.startswith(PACKAGE + '/')]
        if components:
            rc, result = adb_run(adb, serial, 'shell', 'am', 'start', '-W', '-n', components[-1], timeout=22)
            logger(f'{serial}: am start -n rc={rc}: {short(result)}')
            if verify_focus(adb, serial, 3) is True:
                return 'ABIERTA', 'IMSS Digital aparece como aplicación activa.'
    except Exception as exc:
        logger(f'{serial}: resolución de actividad falló: {exc}')

    state = foreground(adb, serial)
    if state is False:
        return 'NO SE ABRIÓ', 'La aplicación está instalada, pero otra pantalla sigue activa. Revisa el diagnóstico.'
    return 'SIN CONFIRMAR', ('ADB envió comandos, pero Android no confirmó IMSS Digital '
                            'en primer plano. Revisa los tres emuladores y el registro.')


class GUI:
    def __init__(self, window):
        self.root = window
        window.title('GESTORÍA DÍAZ - PRUEBA V7 - 3 ANDROID')
        window.geometry('1010x730'); window.minsize(870, 625); window.configure(bg=BG)
        self.adb = None; self.serials = [None] * 3
        self.tasks = queue.Queue(); self.is_busy = False
        heading = tk.Frame(window, bg=BG, padx=18, pady=16)
        heading.pack(fill='x')
        tk.Label(heading, text='GESTORÍA DÍAZ', font=('Segoe UI', 26, 'bold'),
                 bg=BG, fg=GOLD).pack(anchor='w')
        tk.Label(heading, text='PRUEBA V7  ·  LDPLAYER 9  ·  IMSS DIGITAL',
                 bg=BG, fg=FG, font=('Segoe UI', 11, 'bold')).pack(anchor='w')
        tk.Label(heading, text='Solo conexión ADB y apertura; sin CURP, correo ni trámites.',
                 bg=BG, fg=MUTED).pack(anchor='w', pady=(8, 0))
        buttons = tk.Frame(window, bg=BG, padx=18, pady=14); buttons.pack(fill='x')
        self.b1 = tk.Button(buttons, text='1. CONECTAR LOS 3 POR ADB', command=self.connect,
                            bg=GOLD, fg='#171717', font=('Segoe UI', 12, 'bold'), pady=15, bd=0)
        self.b1.pack(side='left', fill='x', expand=True, padx=(0, 8))
        self.b2 = tk.Button(buttons, text='2. ABRIR IMSS DIGITAL', command=self.open_apps,
                            bg='#383b43', fg=FG, font=('Segoe UI', 12, 'bold'), pady=15, bd=0)
        self.b2.pack(side='left', fill='x', expand=True, padx=(8, 0))
        tk.Label(window, text='ESTADO DE LAS 3 INSTANCIAS', bg=BG, fg=GOLD,
                 font=('Segoe UI', 10, 'bold')).pack(anchor='w', padx=18, pady=(10, 5))
        row = tk.Frame(window, bg=BG, padx=12); row.pack(fill='x')
        self.statuses, self.details = [], []
        for j in range(3):
            cell = tk.Frame(row, bg=PANEL, padx=10, pady=17)
            cell.pack(side='left', fill='both', expand=True, padx=6)
            tk.Label(cell, text=f'ANDROID {j+1}', bg=PANEL, fg=GOLD,
                     font=('Segoe UI', 16, 'bold')).pack()
            s = tk.Label(cell, text='SIN PROBAR', bg=PANEL, fg=MUTED,
                         font=('Segoe UI', 12, 'bold'))
            s.pack(pady=(12, 5))
            d = tk.Label(cell, text='Emulador pendiente', bg=PANEL, fg=FG,
                         font=('Segoe UI', 9), wraplength=230, justify='center')
            d.pack(pady=(0, 5))
            self.statuses.append(s); self.details.append(d)
        tk.Label(window, text='REGISTRO ADB Y APERTURA REAL', bg=BG, fg=GOLD,
                 font=('Segoe UI', 10, 'bold')).pack(anchor='w', padx=18, pady=(18, 6))
        block = tk.Frame(window, bg=BG, padx=18); block.pack(fill='both', expand=True)
        self.log_box = tk.Text(block, bg=PANEL, fg=FG, font=('Consolas', 9),
                               state='disabled', wrap='word', borderwidth=0, padx=8, pady=8)
        self.log_box.pack(side='left', fill='both', expand=True)
        sb = tk.Scrollbar(block, command=self.log_box.yview); sb.pack(side='right', fill='y')
        self.log_box.configure(yscrollcommand=sb.set)
        tk.Label(window, text='Versión de diagnóstico local · No oficial · No almacena datos personales',
                 bg=BG, fg=MUTED, font=('Segoe UI', 9)).pack(pady=10)
        menu = tk.Menu(window); options = tk.Menu(menu, tearoff=0)
        options.add_command(label='Elegir carpeta LDPlayer (adb.exe)', command=self.pick_folder)
        options.add_command(label='Guardar diagnóstico TXT', command=self.save_log)
        menu.add_cascade(label='Opciones', menu=options); window.configure(menu=menu)
        self.log('V7 iniciada. Abre las tres ventanas de LDPlayer antes de conectar.')
        self.log('Esta V7 NO necesita que ldconsole list2 detecte emuladores.')
        window.after(130, self.pump)

    def log(self, string):
        self.log_box.configure(state='normal')
        self.log_box.insert('end', f'[{dt.datetime.now():%H:%M:%S}] {string}\n')
        self.log_box.see('end'); self.log_box.configure(state='disabled')

    def signal(self, kind, *values):
        self.tasks.put((kind, *values))

    def pump(self):
        try:
            while True:
                kind, *values = self.tasks.get_nowait()
                if kind == 'log': self.log(values[0])
                elif kind == 'state':
                    idx, state, detail = values
                    color = GREEN if state in ('CONECTADO', 'ABIERTA') else (
                        RED if state in ('NO SE ABRIÓ', 'NO INSTALADA', 'ERROR', 'SIN CONEXIÓN') else MUTED)
                    self.statuses[idx].configure(text=state, fg=color)
                    self.details[idx].configure(text=detail)
                elif kind == 'serials': self.serials = values[0]
                elif kind == 'adb': self.adb = values[0]
                elif kind == 'finish': self.busy(False)
        except queue.Empty:
            pass
        self.root.after(130, self.pump)

    def busy(self, active):
        self.is_busy = active
        self.b1.configure(state='disabled' if active else 'normal')
        self.b2.configure(state='disabled' if active else 'normal')

    def pick_folder(self):
        if self.is_busy: return
        folder = filedialog.askdirectory(title='Elige la carpeta con adb.exe de LDPlayer 9')
        if not folder: return
        if not (pathlib.Path(folder) / 'adb.exe').is_file():
            messagebox.showerror('Carpeta incorrecta', 'Esta carpeta no contiene adb.exe.')
            return
        SETTINGS.write_text(json.dumps({'folder': folder}, indent=2), encoding='utf-8')
        self.log('Se guardó la carpeta ADB: ' + folder)
        self.log('Ahora presiona el botón 1.')

    def save_log(self):
        filepath = filedialog.asksaveasfilename(defaultextension='.txt',
                                                 filetypes=[('Diagnóstico TXT', '*.txt')])
        if filepath:
            pathlib.Path(filepath).write_text(self.log_box.get('1.0', 'end'), encoding='utf-8')
            self.log('Registro guardado en ' + filepath)

    def connect(self):
        if self.is_busy: return
        self.serials = [None] * 3
        for i in range(3): self.signal('state', i, 'BUSCANDO', 'Consultando ADB')
        self.busy(True)
        threading.Thread(target=self._connect_worker, daemon=True).start()

    def _connect_worker(self):
        try:
            adb = locate_adb()
            if not adb:
                raise RuntimeError('No encontré adb.exe. Ve a Opciones y elige D:\\LDPlayer\\LDPlayer9.')
            self.signal('adb', adb)
            self.signal('log', 'ADB seleccionado: ' + adb)
            rc, output = process([adb, 'start-server'], timeout=18)
            if rc != 0: raise RuntimeError('No se pudo iniciar ADB: ' + short(output))
            rc, output = process([adb, 'devices', '-l'], timeout=14)
            if rc != 0: raise RuntimeError('Error adb devices: ' + short(output))
            available = devices_from_output(output)
            self.signal('log', 'Transporte ADB: ' + (', '.join(f'{k}={v}' for k,v in available.items()) or 'NINGUNO'))
            selected = select_serials(available)
            if len(selected) < 3:
                for idx in range(3):
                    if idx not in [j for j,_ in selected]:
                        try:
                            process([adb, 'connect', f'127.0.0.1:{5555 + 2*idx}'], timeout=8)
                        except RuntimeError:
                            pass
                rc, output = process([adb, 'devices', '-l'], timeout=14)
                if rc == 0: selected = select_serials(devices_from_output(output))
            self.signal('log', 'Tres transportes elegidos: ' + str(selected))
            connected = [None, None, None]
            for slot in range(3):
                if slot >= len(selected):
                    self.signal('state', slot, 'SIN CONEXIÓN', 'No se detectó otro emulador ADB')
                    continue
                idx, serial = selected[slot]
                rc, output = adb_run(adb, serial, 'shell', 'echo', 'GESTORIA_OK', timeout=12)
                if rc == 0 and 'GESTORIA_OK' in output:
                    connected[slot] = serial
                    self.signal('state', slot, 'CONECTADO', f'Instancia {idx} · {serial}')
                    self.signal('log', f'Android {slot + 1}: shell confirmado en {serial}')
                else:
                    self.signal('state', slot, 'ERROR', f'ADB shell falló: {short(output)}')
            self.signal('serials', connected)
            self.signal('log', f'RESULTADO: {sum(bool(x) for x in connected)}/3 conectados.')
        except Exception as exc:
            self.signal('log', 'ERROR: ' + str(exc))
            for idx in range(3): self.signal('state', idx, 'ERROR', 'Revisa registro ADB')
        finally:
            self.signal('finish')

    def open_apps(self):
        if self.is_busy: return
        if not self.adb or not any(self.serials):
            messagebox.showinfo('Primero conectar', 'Pulsa primero el botón 1 y comprueba las conexiones.')
            return
        self.busy(True)
        threading.Thread(target=self._open_worker, daemon=True).start()

    def _open_worker(self):
        try:
            work = [(idx, serial) for idx, serial in enumerate(self.serials) if serial]
            with ThreadPoolExecutor(max_workers=3) as pool:
                futures = {pool.submit(launch_imss, self.adb, serial,
                                       lambda msg: self.signal('log', msg)): (idx, serial)
                           for idx, serial in work}
                for future in as_completed(futures):
                    idx, serial = futures[future]
                    try:
                        status, detail = future.result()
                    except Exception as exc:
                        status, detail = 'ERROR', str(exc)[:180]
                    self.signal('state', idx, status, detail)
                    self.signal('log', f'ANDROID {idx + 1} ({serial}): {status}: {detail}')
            self.signal('log', 'FIN de prueba de apertura. Verde solo si IMSS está confirmado en primer plano.')
        finally:
            self.signal('finish')


def main():
    root = tk.Tk(); GUI(root); root.mainloop()


if __name__ == '__main__':
    main()
