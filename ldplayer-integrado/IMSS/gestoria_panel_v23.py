# -*- coding: utf-8 -*-
"""IMSS V23: cuarta ranura de LDPlayer; base ADB V7 y puente V22 intactos."""
import tkinter as tk
from gestoria_panel_v22 import PanelV22

class PanelV23(PanelV22):
    def __init__(self, root):
        super().__init__(root)
        root.title('GESTORÍA DÍAZ · IMSS V23 · 4 EMULADORES LDPLAYER')
        root.geometry('1240x930')
        root.minsize(1050, 790)
        self.connect_btn.configure(text='1. CONECTAR Y ABRIR 4 EMULADORES (ADB V7)')
        self.add_btn.configure(text='2. AGREGAR CURP A LA COLA · 4 ANDROID')
        self.log('V23: 4 ranuras ADB; núcleo V7 sin modificaciones. Outlook V24 mantiene cada sesión separada por Android.')
        self.log('El código se entrega solo al emulador que solicitó esa verificación.')

def main():
    root=tk.Tk(); PanelV23(root); root.mainloop()
if __name__=='__main__':main()
