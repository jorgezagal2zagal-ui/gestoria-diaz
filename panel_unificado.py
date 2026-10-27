"""Single-window entry point for Outlook, IMSS, emulator preparation and batches."""

import tkinter as tk
import gestoria_5_instancias as imss
from conexion.unified import OutlookSection


def main():
    root = tk.Tk()
    app = imss.App(root, outlook_factory=OutlookSection)
    from conexion.parallel_ui import ParallelPanel
    ParallelPanel(app)
    root.title("GESTORÍA DÍAZ V6.1 | 3 SOLICITUDES · REINTENTOS AUTOMÁTICOS")
    root.mainloop()


if __name__ == "__main__":
    main()
