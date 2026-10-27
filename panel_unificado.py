"""Single-window entry point for Outlook, IMSS, emulator preparation and batches."""

import tkinter as tk
import gestoria_5_instancias as imss
from conexion.unified import OutlookSection


def main():
    root = tk.Tk()
    imss.App(root, outlook_factory=OutlookSection)
    root.title("GESTORÍA DÍAZ V3 | OUTLOOK + IMSS · PANEL ÚNICO")
    root.mainloop()


if __name__ == "__main__":
    main()
