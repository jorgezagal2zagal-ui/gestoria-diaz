"""Extensión de IMSS V32 LDPlayer. Núcleo ADB original sin modificaciones."""
import threading
import time
import tkinter as tk
from tkinter import messagebox
from gestoria_panel_v32 import PanelV32
from enlace_integrado import Client
from flujo_integrado import ejecutar
from gestoria_prueba_v7 import adb_run


class PanelIntegrado(PanelV32):
    def __init__(self, root):
        super().__init__(root)
        root.title('Gestoría Díaz · IMSS LDPlayer · FIN DESPUÉS DEL CÓDIGO')
        self.connect_btn.configure(text='1. DETECTAR LDPLAYER POR ADB (SIN ABRIR IMSS TODAVÍA)')
        self.add_btn.configure(text='2. AGREGAR CURP AUTORIZADA · OUTLOOK PRIMERO')
        self.use_pin.set(False)
        self.log('Integración: sin Wi-Fi, sin rotación de cuentas ante verificaciones y sin reinicios automáticos.')
        tk.Label(root, text='MODO ACTIVO: OUTLOOK → IMSS → CÓDIGO → FIN. NO CONTINÚA CON TRÁMITES NI PDF.',
                 bg='#111215', fg='#e2b44c', font=('Segoe UI', 10, 'bold')).pack(anchor='w', padx=20)

    @staticmethod
    def start_and_assess(adb, serial, update=lambda text: None):
        # El botón de conexión conserva la detección original, pero no inicia IMSS antes de Outlook.
        rc, output = adb_run(adb, serial, 'shell', 'echo', 'GESTORIA_OK', timeout=10)
        return ('LIBRE', 'LDPlayer conectado; IMSS espera bandeja Outlook.') if not rc and 'GESTORIA_OK' in output else (
            'REVISAR', 'LDPlayer no respondió a ADB.')

    def connect(self):
        if any(self.folios):
            messagebox.showinfo('Folios retenidos', 'Hay folios en FIN o revisión. No se reasignarán emuladores sobre esas pantallas.')
            return
        return super().connect()

    def login_worker(self, slot, reqid, curp, email, override, pin, stop, folio):
        done = threading.Event()
        self._worker_done[slot] = done
        client = Client(port=8797 + slot, timeout=2)
        try:
            self.send('status', slot, 'OCUPADO', 'Esperando bandeja Outlook comprobada; Android sin tocar')
            deadline = time.monotonic() + 180
            while not stop.is_set():
                prep = self.preparacion.status(folio)
                if not prep or prep['email'] != email:
                    raise RuntimeError('Preparación ajena o inexistente')
                try:ready = client.ready()
                except Exception:ready = {}
                if ready.get('protocol') == 2 and ready.get('ready') and ready.get('email') == email:
                    break
                phase = ready.get('phase')
                if phase == 'security_manual':
                    # La intervención manual no provoca rotación, timeout ni comandos Android.
                    deadline = time.monotonic() + 180
                    self.send('status', slot, 'OCUPADO', 'PAUSA: resuelve manualmente la verificación de Microsoft en Chrome')
                elif prep['estado'] in ('BLOQUEADA', 'REVISAR', 'LIMITE_MICROSOFT', 'METODO_NO_DISPONIBLE'):
                    self.send('bridge_result', slot, reqid, 'REVISAR',
                              'Outlook requiere intervención; no se cambió de cuenta ni se inició IMSS.', folio, False)
                    return
                if time.monotonic() >= deadline:
                    self.send('bridge_result', slot, reqid, 'REVISAR',
                              'No se confirmó la bandeja de Outlook. Android sin tocar.', folio, False)
                    return
                stop.wait(.6)
            if stop.is_set():
                self.send('bridge_result', slot, reqid, 'REVISAR', 'Espera detenida; no se inició otro trámite.', folio, False)
                return
            result = ejecutar(self.adb, self.serials[slot], curp, email, stop, client,
                update=lambda text: self.send('status', slot, 'OCUPADO', text),
                pin=pin, override=override, folio=folio)
            self.send('bridge_result', slot, reqid, *result)
        except Exception as exc:
            self.send('bridge_result', slot, reqid, 'REVISAR',
                      'Proceso retenido (' + type(exc).__name__ + '); no se repite automáticamente.', folio, False)
        finally:
            done.set()
            self._queued_inputs.pop(reqid, None)
            del pin

    def _stall_tick(self):
        # Desactivar recuperación y reintentos heredados: podrían tocar Android tras el OTP.
        return

    def watch_loop(self):
        # El vigilante antiguo reabría IMSS incluso después del resultado del trabajador.
        return

    def ask_to_reset(self, slot):
        messagebox.showinfo('Límite del flujo', 'Esta versión termina después del código. No vuelve al inicio, no genera PDF ni pulsa pasos posteriores.')

    def recover_manual(self):
        messagebox.showinfo('Revisión manual', 'Revisa el emulador y el folio. Esta versión no reinicia ni repite el trámite automáticamente.')

    def _finish_manually(self, done):
        messagebox.showinfo('Confirmación verificable', 'La aceptación se confirma sólo por un mensaje explícito de IMSS. Un cambio de pantalla o una confirmación manual no se registra como éxito automático.')


def main():
    root = tk.Tk()
    PanelIntegrado(root)
    root.mainloop()


if __name__ == '__main__':main()
