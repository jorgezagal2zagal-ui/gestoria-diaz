"""Cuentas y resultados en el mismo panel. Exportar no cambia el flujo IMSS."""
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
import tkinter as tk

try:
    from .accounts import Account, Catalog, export_addresses, parse_accounts, valid_address
    from .storage import MAIL_GROUPS
except ImportError:
    from accounts import Account, Catalog, export_addresses, parse_accounts, valid_address
    from storage import MAIL_GROUPS


EXPORTS = ("Lista de esta pestaña TXT", "Todos los correos cargados TXT", "Historial Outlook completo CSV", "Historial IMSS completo CSV")


class AccountsPanel:
    def __init__(self, app, parent):
        self.app, self.catalog = app, Catalog()
        self.groups = {category: [] for category in MAIL_GROUPS}
        self.count = tk.StringVar(value="Sin cuentas cargadas")
        self.export_mode = tk.StringVar(value=EXPORTS[0])
        self.frame = ttk.LabelFrame(parent, text="2 · CUENTAS Y RESULTADOS OUTLOOK", padding=10)
        self.frame.pack(fill="x", pady=8)
        actions = ttk.Frame(self.frame)
        actions.pack(fill="x", pady=(0, 8))
        for index, (label, command) in enumerate((("Cargar cuentas TXT", self.load), ("Añadir correo del formulario", self.add_current),
                               ("Usar seleccionado", self.use_selected), ("Siguiente correo", self.next_account),
                               ("Omitir seleccionado", self.omit), ("Quitar del catálogo", self.remove))):
            widget = ttk.Button(actions, text=label, command=command)
            widget.grid(row=index // 3, column=index % 3, sticky="ew", padx=(0, 5), pady=2)
            app.controls.append((widget, "normal"))
        self.notebook = ttk.Notebook(self.frame)
        self.notebook.pack(fill="x")
        self.tables = {}
        self.categories = ("Cargados",) + MAIL_GROUPS
        for category in self.categories:
            frame = ttk.Frame(self.notebook)
            self.notebook.add(frame, text=category)
            table = ttk.Treeview(frame, columns=("correo", "resultado", "detalle"), show="headings", height=5, selectmode="extended")
            for key, title, width in (("correo", "Correo", 290), ("resultado", "Resultado Outlook", 180), ("detalle", "Detalle", 380)):
                table.heading(key, text=title)
                table.column(key, width=width)
            scroll = ttk.Scrollbar(frame, orient="vertical", command=table.yview)
            table.configure(yscrollcommand=scroll.set)
            scroll.pack(side="right", fill="y")
            table.pack(fill="x", expand=True)
            table.bind("<Double-1>", lambda _event: self.use_selected())
            self.tables[category] = table
        export = ttk.Frame(self.frame)
        export.pack(fill="x", pady=(8, 0))
        ttk.Combobox(export, textvariable=self.export_mode, values=EXPORTS, state="readonly", width=34).pack(side="left")
        ttk.Button(export, text="EXPORTAR CORREOS / REGISTRO", command=self.export).pack(side="left", padx=8)
        ttk.Button(export, text="Actualizar listas", command=self.refresh).pack(side="left")
        ttk.Label(self.frame, textvariable=self.count, wraplength=930).pack(anchor="w", pady=(6, 0))
        self.refresh()

    def is_busy(self):
        return bool(self.app.worker and self.app.worker.is_alive())

    def editable(self):
        if self.is_busy():
            self.app.status.set("Espera o detén la solicitud antes de cambiar las cuentas. Las exportaciones siguen disponibles.")
            return False
        return True

    def import_file(self, path):
        if not self.editable():
            return 0
        source = Path(path)
        if source.stat().st_size > 16 * 1024 * 1024:
            raise ValueError("El TXT supera 16 MB.")
        incoming = parse_accounts(source.read_text(encoding="utf-8-sig"))
        added = self.catalog.merge(incoming)
        self.refresh()
        if not self.app.email.get().strip() and self.catalog.accounts:
            self.use(next(iter(self.catalog.accounts.values())).address)
        self.app.status.set(f"{added} cuentas nuevas cargadas. Las contraseñas quedan solo en memoria.")
        return added

    def load(self):
        if not self.editable():
            return
        path = filedialog.askopenfilename(parent=self.app.root, title="Cuentas correo:contraseña o solo correos", filetypes=(("TXT", "*.txt"),))
        if path:
            try:
                self.import_file(path)
            except ValueError as exc:
                messagebox.showerror("Importar cuentas", str(exc), parent=self.app.root)
            except (OSError, UnicodeError):
                messagebox.showerror("Importar cuentas", "No se pudo leer el TXT UTF-8. No se cambió el catálogo.", parent=self.app.root)

    def add_current(self):
        if not self.editable():
            return
        address, password = self.app.email.get().strip(), self.app.password.get()
        if not valid_address(address):
            messagebox.showerror("Añadir cuenta", "Escribe un correo válido en el formulario de solicitud.", parent=self.app.root)
            return
        self.catalog.merge([Account(address, password)])
        self.app.password.set("")
        self.refresh()
        self.app.status.set("Cuenta añadida al catálogo de esta sesión.")

    def selected(self):
        category = self.categories[self.notebook.index(self.notebook.select())]
        table = self.tables[category]
        return [str(table.item(ident, "values")[0]) for ident in table.selection()]

    def use(self, address):
        account = self.catalog.get(address)
        self.app.email.set(account.address if account else address)
        self.app.password.set("")
        self.app.status.set("Correo seleccionado para Outlook e IMSS: " + address)

    def use_selected(self):
        if not self.editable():
            return
        selected = self.selected()
        if selected:
            self.use(selected[0])
        else:
            self.app.status.set("Selecciona una fila de correos para usar esa cuenta.")

    def next_account(self):
        if not self.editable():
            return
        account = self.catalog.next(self.app.email.get().strip())
        if account:
            self.use(account.address)
        else:
            self.app.status.set("No hay otro correo disponible. Carga más cuentas o elige una de la lista.")

    def omit(self):
        if not self.editable():
            return
        selected = self.selected()
        if not selected:
            self.app.status.set("Selecciona los correos que quieres omitir.")
            return
        for address in selected:
            self.app.history.record_mail(address, "Omitido", "Omitido por el usuario desde la lista de correos.")
            self.catalog.omitted.add(address.casefold())
        current = self.app.email.get().strip()
        if current.casefold() in {a.casefold() for a in selected}:
            account = self.catalog.next(current)
            self.app.email.set(account.address if account else "")
            self.app.password.set("")
        self.refresh()
        self.app.status.set(f"{len(selected)} correos omitidos. El formulario usa el siguiente disponible si lo hay.")

    def remove(self):
        if not self.editable():
            return
        selected = self.selected()
        for address in selected:
            self.catalog.accounts.pop(address.casefold(), None)
        self.refresh()
        self.app.status.set("Cuentas seleccionadas retiradas de la memoria. El historial se conserva.")

    def refresh(self):
        self.groups = self.app.history.mail_groups()
        latest = {row[1].casefold(): row for group in self.groups.values() for row in group}
        loaded = []
        for key, account in self.catalog.accounts.items():
            previous = latest.get(key)
            state = "Omitido" if key in self.catalog.omitted else previous[2] if previous else "Disponible"
            loaded.append((account.address, state, "Contraseña cargada en memoria" if account.password else "Sin contraseña; modo manual o completar formulario"))
        for index, category in enumerate(self.categories):
            rows = loaded if category == "Cargados" else [(row[1], row[2], row[3]) for row in self.groups[category]]
            table = self.tables[category]
            children = table.get_children()
            if children:
                table.delete(*children)
            for row in rows[:500]:
                table.insert("", "end", values=row)
            self.notebook.tab(index, text=f"{category} ({len(rows)})")
        self.count.set(f"{len(loaded)} cuentas cargadas · " + " · ".join(f"{category}: {len(self.groups[category])}" for category in MAIL_GROUPS) + " · Hasta 500 filas visibles por lista; la exportación incluye todas.")

    def export_to(self, path, mode=None, category=None):
        mode = mode or self.export_mode.get()
        self.groups = self.app.history.mail_groups()
        if mode == EXPORTS[0]:
            category = category or self.categories[self.notebook.index(self.notebook.select())]
            addresses = [a.address for a in self.catalog.accounts.values()] if category == "Cargados" else [row[1] for row in self.groups[category]]
            export_addresses(path, addresses)
            return len(addresses)
        if mode == EXPORTS[1]:
            return self.catalog.export(path)
        if mode == EXPORTS[2]:
            self.app.history.export_mail(path)
            return None
        if mode == EXPORTS[3]:
            self.app.history.export(path)
            return None
        raise ValueError("Elige un formato de exportación válido.")

    def export(self):
        csv = self.export_mode.get() in EXPORTS[2:]
        path = filedialog.asksaveasfilename(parent=self.app.root, title="Exportar correos o historial", defaultextension=".csv" if csv else ".txt",
                                          initialfile="historial_completo.csv" if csv else "correos.txt", filetypes=(("CSV", "*.csv"),) if csv else (("Lista TXT", "*.txt"),))
        if path:
            try:
                count = self.export_to(path)
                self.app.status.set(f"Exportados {count} correos, sin contraseñas." if count is not None else "Historial completo exportado, sin contraseñas ni códigos.")
            except (OSError, ValueError) as exc:
                messagebox.showerror("Exportar", str(exc), parent=self.app.root)
