import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path
import subprocess
import os
import shutil
import threading
import queue
import csv
from automation import available_browsers, try_account, close_driver, LoginFailure, SkipRequested, RateLimited, VerificationRequired
from core import parse_accounts, merge_accounts, Account
from history import HistoryStore, FIELDS, GROUPS, group_results

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('Gestoría Díaz | Panel de cuentas')
        self.geometry('1000x720'); self.minsize(800, 550)
        self.configure(bg='#111318')
        self.accounts = []
        self.states = {}
        self.history = HistoryStore()
        self._events = queue.Queue()
        self._skip_event = threading.Event()
        self._stop_event = threading.Event()
        self._running = False
        self.manage_buttons = []
        self.after(100, self._drain_events)
        self.protocol('WM_DELETE_WINDOW', self.close_panel)
        style = ttk.Style(self); style.theme_use('clam')
        style.configure('TFrame', background='#111318')
        style.configure('TLabel', background='#111318', foreground='#eeeeee', font=('Segoe UI', 10))
        style.configure('TButton', font=('Segoe UI', 10), padding=6)
        style.configure('Title.TLabel', foreground='#d8b66b', font=('Segoe UI', 22, 'bold'))
        outer = ttk.Frame(self, padding=20); outer.pack(fill='both', expand=True)
        ttk.Label(outer, text='GESTORÍA DÍAZ', style='Title.TLabel').pack(anchor='w')
        ttk.Label(outer, text='Outlook: omitir correo y recuperación con otro navegador').pack(anchor='w', pady=(3, 12))
        self.stats = tk.StringVar(value='Cuentas leídas: 0')
        ttk.Label(outer, textvariable=self.stats).pack(anchor='w', pady=4)
        manage = ttk.Frame(outer); manage.pack(fill='x', pady=8)
        for title, command in [('Importar TXT', self.load), ('Añadir por escrito', self.add_dialog), ('Seleccionar todos', self.select_all), ('Quitar seleccionados', self.remove), ('Limpiar lista', self.clear)]:
            button = ttk.Button(manage, text=title, command=command)
            button.pack(side='left', padx=(0, 5))
            self.manage_buttons.append(button)
        actions = ttk.Frame(outer)
        actions.pack(fill='x', pady=(2, 8))
        self.start_button = ttk.Button(actions, text='INICIAR', command=self.open_private_login)
        self.start_button.pack(side='left', padx=(0, 8))
        self.skip_button = ttk.Button(actions, text='OMITIR CORREO / SIGUIENTE', command=self.skip_account, state='disabled')
        self.skip_button.pack(side='left', padx=(0, 8))
        self.stop_button = ttk.Button(actions, text='DETENER', command=self.stop_accounts, state='disabled')
        self.stop_button.pack(side='left')
        ttk.Button(actions, text='VER REGISTRO', command=self.show_history).pack(side='left', padx=8)
        table_frame = ttk.Frame(outer); table_frame.pack(fill='both', expand=True)
        self.table = ttk.Treeview(table_frame, columns=('email', 'password', 'state'), show='headings', selectmode='extended')
        self.table.heading('email', text='Correo'); self.table.heading('password', text='Contraseña leída')
        self.table.heading('state', text='Estado')
        self.table.column('email', width=390); self.table.column('password', width=200)
        self.table.column('state', width=260)
        scroll = ttk.Scrollbar(table_frame, orient='vertical', command=self.table.yview)
        self.table.configure(yscrollcommand=scroll.set)
        self.table.pack(side='left', fill='both', expand=True); scroll.pack(side='right', fill='y')
        self.show_password = tk.BooleanVar(value=False)
        ttk.Checkbutton(outer, text='Mostrar contraseñas (solo en esta pantalla)', variable=self.show_password, command=self.refresh).pack(anchor='w', pady=8)
        self.status = tk.StringVar(value='Importa un TXT con una cuenta por línea: correo:contraseña')
        ttk.Label(outer, textvariable=self.status).pack(anchor='w', pady=6)
        ttk.Label(outer, text='Las contraseñas solo quedan en memoria. El registro guarda correo, fecha y resultado.').pack(anchor='w')
        self.history_status = tk.StringVar(value=f'Registro: {self.history.path}')
        ttk.Label(outer, textvariable=self.history_status, wraplength=900).pack(anchor='w')

    def _record_result(self, address, result, detail):
        store = self.__dict__.get('history')
        if store is None:
            return
        try:
            store.append(address, result, detail)
        except (OSError, UnicodeError, csv.Error):
            self._post(lambda: self.history_status.set(
                'No pude guardar el registro. Revisa el permiso de escritura de la carpeta de datos.'))

    def show_history(self):
        window = tk.Toplevel(self)
        window.title('Correos por resultado')
        window.geometry('1000x560')
        ttk.Label(window, text='Último resultado por correo. El historial completo se conserva en CSV.').pack(anchor='w', padx=10, pady=8)
        notebook = ttk.Notebook(window)
        notebook.pack(fill='both', expand=True, padx=10)
        tables = {}
        grouped = {name: [] for name in GROUPS}
        for category in GROUPS:
            frame = ttk.Frame(notebook)
            notebook.add(frame, text=category)
            table = ttk.Treeview(frame, columns=FIELDS, show='headings')
            for field, width in zip(FIELDS, (200, 300, 180, 300)):
                table.heading(field, text=field.capitalize())
                table.column(field, width=width)
            scroll = ttk.Scrollbar(frame, orient='vertical', command=table.yview)
            table.configure(yscrollcommand=scroll.set)
            scroll.pack(side='right', fill='y')
            table.pack(fill='both', expand=True)
            tables[category] = table
        summary = tk.StringVar()
        ttk.Label(window, textvariable=summary).pack(anchor='w', padx=10, pady=5)

        def refresh():
            nonlocal grouped
            try:
                rows = self.history.read()
            except (OSError, UnicodeError, csv.Error):
                messagebox.showerror('Registro', 'No se pudo leer el registro.', parent=window)
                return False
            grouped = group_results(rows)
            for index, category in enumerate(GROUPS):
                table = tables[category]
                table.delete(*table.get_children())
                for row in grouped[category]:
                    table.insert('', 'end', values=tuple(row.get(field, '') for field in FIELDS))
                notebook.tab(index, text=f'{category} ({len(grouped[category])})')
            summary.set(' | '.join(f'{name}: {len(grouped[name])}' for name in GROUPS))
            return True

        def export_list():
            if not refresh():
                return
            index = notebook.index(notebook.select())
            category = GROUPS[index]
            filename = ('correos_entraron.txt', 'correos_con_inconvenientes.txt', 'correos_omitidos.txt')[index]
            path = filedialog.asksaveasfilename(parent=window, defaultextension='.txt',
                initialfile=filename, filetypes=[('Lista de correos TXT', '*.txt')])
            if path:
                try:
                    Path(path).write_text(''.join(row['correo'].strip() + '\n' for row in grouped[category]), encoding='utf-8')
                except OSError:
                    messagebox.showerror('Registro', 'No se pudo guardar la lista.', parent=window)

        def export():
            path = filedialog.asksaveasfilename(parent=window, defaultextension='.csv',
                initialfile='registro_correos.csv', filetypes=[('Registro CSV', '*.csv')])
            if path:
                try:
                    self.history.export(path)
                except OSError:
                    messagebox.showerror('Registro', 'No se pudo exportar el registro.', parent=window)

        buttons = ttk.Frame(window)
        buttons.pack(pady=8)
        ttk.Button(buttons, text='Actualizar', command=refresh).pack(side='left', padx=5)
        ttk.Button(buttons, text='Guardar lista TXT', command=export_list).pack(side='left', padx=5)
        ttk.Button(buttons, text='Historial completo CSV', command=export).pack(side='left', padx=5)
        refresh()

    def _post(self, callback):
        self._events.put(callback)

    def _drain_events(self):
        try:
            while True:
                self._events.get_nowait()()
        except queue.Empty:
            pass
        self.after(100, self._drain_events)

    def _account_status(self, address, state):
        self.states[address.lower()] = state
        self.refresh()

    def open_private_login(self):
        if self._running:
            self.status.set('Ya hay una cuenta en curso. Usa Omitir correo o Detener.')
            return
        if not self.accounts:
            messagebox.showwarning('Sin cuentas', 'Primero importa un correo en el panel.')
            return
        browsers = available_browsers()
        if not browsers:
            messagebox.showwarning('Navegador', 'Instala Chrome, Edge o Firefox antes de iniciar.')
            return
        self._running = True
        self._stop_event.clear()
        self._skip_event.clear()
        for button in self.manage_buttons:
            button.configure(state='disabled')
        self.start_button.configure(state='disabled')
        self.skip_button.configure(state='normal')
        self.stop_button.configure(state='normal')
        self.status.set('Iniciando cola de cuentas…')
        threading.Thread(target=self._run_accounts,
                         args=(list(self.accounts), browsers), daemon=True).start()

    def skip_account(self):
        if self._running:
            self._skip_event.set()
            self.status.set('Omitiendo correo; cerrando el navegador de este intento…')

    def stop_accounts(self):
        self._stop_event.set()
        self._skip_event.set()
        self.status.set('Deteniendo…')

    def _finish_run(self):
        self._running = False
        for button in self.manage_buttons:
            button.configure(state='normal')
        self.start_button.configure(state='normal')
        self.skip_button.configure(state='disabled')
        self.stop_button.configure(state='disabled')

    def _run_accounts(self, accounts, browsers):
        limited = False
        try:
            for account in accounts:
                if self._stop_event.is_set():
                    break
                self._skip_event.clear()
                address = account.address
                def report(text, address=address):
                    self._post(lambda: self.status.set(f'{address} | {text}'))
                self._post(lambda address=address: self._account_status(address, 'Intentando'))
                driver = None
                try:
                    driver = try_account(account, browsers,
                        lambda: self._skip_event.is_set() or self._stop_event.is_set(), report)
                    self._record_result(address, 'Entró a la bandeja', 'Bandeja de Outlook abierta')
                    self._post(lambda address=address: self._account_status(address, 'Bandeja abierta'))
                    report('Bandeja abierta. Usa Omitir / siguiente para avanzar.')
                    # Keep this inbox usable until the user explicitly moves on.
                    while not self._skip_event.wait(.2):
                        if self._stop_event.is_set():
                            break
                    self._post(lambda address=address: self._account_status(address, 'Finalizado'))
                except SkipRequested:
                    stopped = self._stop_event.is_set()
                    self._record_result(address, 'Interrumpido' if stopped else 'Omitido',
                                        'Detenido por usuario' if stopped else 'Omitido manualmente')
                    self._post(lambda address=address: self._account_status(address, 'Omitido manualmente'))
                except VerificationRequired:
                    self._record_result(address, 'No logró entrar', 'Verificación adicional: Almost there')
                    self._post(lambda address=address: self._account_status(address, 'Omitido: verificación adicional'))
                except RateLimited:
                    self._record_result(address, 'Interrumpido', 'Microsoft limita solicitudes: Too Many Requests')
                    limited = True
                    self._post(lambda address=address: self._account_status(address, 'Microsoft limita solicitudes'))
                    break
                except LoginFailure:
                    self._record_result(address, 'No logró entrar', 'No se completó el acceso en los navegadores disponibles')
                    self._post(lambda address=address: self._account_status(address, 'Omitido: acceso no disponible'))
                except Exception:
                    self._record_result(address, 'No logró entrar', 'Error de navegador')
                    self._post(lambda address=address: self._account_status(address, 'Omitido: error de navegador'))
                finally:
                    close_driver(driver)
            if self._stop_event.is_set():
                text = 'Proceso detenido.'
            elif limited:
                text = 'Microsoft sigue mostrando Too Many Requests. Cola detenida; vuelve a intentar más tarde.'
            else:
                text = 'Cola terminada. Revisa los estados de las cuentas.'
            self._post(lambda text=text: self.status.set(text))
        finally:
            self._post(self._finish_run)

    def close_panel(self):
        self._stop_event.set()
        self._skip_event.set()
        self.destroy()

    def refresh(self):
        self.table.delete(*self.table.get_children())
        for i, account in enumerate(self.accounts):
            password = account.password if self.show_password.get() else '●' * min(len(account.password), 12)
            self.table.insert('', 'end', iid=str(i), values=(account.address, password, self.states.get(account.address.lower(), 'Pendiente')))
        self.stats.set(f'Cuentas leídas: {len(self.accounts)}')

    def add_text(self, content):
        incoming = parse_accounts(content)
        self.accounts, added = merge_accounts(self.accounts, incoming)
        self.refresh()
        self.status.set(f'Leídas: {len(incoming)} | Añadidas: {added} | Duplicadas omitidas: {len(incoming)-added}')

    def load(self):
        path = filedialog.askopenfilename(filetypes=[('Cuentas TXT', '*.txt')])
        if not path: return
        try: self.add_text(Path(path).read_text(encoding='utf-8-sig'))
        except (ValueError, OSError, UnicodeError) as exc: messagebox.showerror('Importación', str(exc))

    def add_dialog(self):
        dialog = tk.Toplevel(self); dialog.title('Añadir cuentas por escrito'); dialog.geometry('640x340')
        ttk.Label(dialog, text='Una cuenta por línea: correo:contraseña').pack(anchor='w', padx=12, pady=12)
        entry = tk.Text(dialog, height=10); entry.pack(fill='both', expand=True, padx=12)
        def add():
            try: self.add_text(entry.get('1.0', 'end'))
            except ValueError as exc: messagebox.showerror('Añadir cuentas', str(exc), parent=dialog); return
            dialog.destroy()
        ttk.Button(dialog, text='Añadir a la lista', command=add).pack(pady=12)
        dialog.transient(self); dialog.grab_set(); entry.focus_set()

    def select_all(self): self.table.selection_set(self.table.get_children())
    def remove(self):
        indices = {int(i) for i in self.table.selection()}
        self.accounts = [a for i, a in enumerate(self.accounts) if i not in indices]
        self.refresh()
    def clear(self):
        self.accounts = []; self.refresh(); self.status.set('Lista vacía.')

if __name__ == '__main__': App().mainloop()
