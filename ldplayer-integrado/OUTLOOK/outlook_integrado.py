"""Outlook V45 conservado, con preparación comprobada y lector estricto."""
import os
import sys
import time
import subprocess
from pathlib import Path

if '--worker' in sys.argv:
    os.environ['GD_WORKER_SLOT'] = sys.argv[sys.argv.index('--worker') + 1]
else:
    os.environ['GD_WORKER_SLOT'] = '1'
os.environ['GD_HEADLESS'] = '0'

from app_v41 import OutlookV41, OutlookWorkerV36
import app as baseapp
import navegador_v28 as browser
from enlace_integrado import State, Server
from lector_integrado import scan_visible_inbox, inbox_verified

browser.scan_visible_inbox = scan_visible_inbox
browser.inbox_ui_verified = inbox_verified
baseapp.State = State


def integrated_server(state, **kwargs):
    owner = kwargs['can_begin'].__self__
    kwargs['can_begin'] = owner._can_register
    return Server(state, mailbox_ready=owner._mailbox_ready, **kwargs)


baseapp.Server = integrated_server


class IntegrationMixin:
    def _mailbox_ready(self):
        b = self.browser
        email = str(self.active_email or '').casefold()
        valid = bool(b.running and b.phase == 'mail' and email and
            not getattr(b, 'manual_security_pending', False) and
            not b.rate_limited and not getattr(b, 'blocked', False) and
            getattr(b, '_mailbox_verified_email', None) == email and
            0 <= time.monotonic() - getattr(b, '_mailbox_verified_at', 0) < 5)
        return {'ready': valid, 'email': email if valid else None,
                'phase': b.phase, 'worker': int(os.environ.get('GD_WORKER_SLOT', '1'))}

    def _can_register(self, email, folio, serial):
        ready = self._mailbox_ready()
        row = self.shared_pool.by_folio(folio)
        prep = self.preparacion.status(folio)
        with self.preparacion.db() as db:
            assigned = db.execute('SELECT worker FROM tareas WHERE folio=?', (folio,)).fetchone()
        worker = int(os.environ.get('GD_WORKER_SLOT', '1'))
        return bool(ready['ready'] and ready['email'] == email.strip().casefold() and
                    row and row['email'] == email.strip().casefold() and row['estado'] == 'OCUPADO' and
                    prep and prep['email'] == row['email'] and prep['estado'] == 'LISTO' and
                    assigned and assigned['worker'] == worker)

    def _tick_once(self):
        if getattr(self.browser, 'manual_security_pending', False):
            self.preparacion.heartbeat()
            self.prep_started = time.monotonic()
            self.info.set('PAUSA: completa manualmente la verificación de Microsoft en Chrome. IMSS espera; no se cambia de cuenta.')
            self.browser_status.set('INTERVENCIÓN MANUAL · ventana de Microsoft abierta')
            self._security_was_paused = True
            return
        if getattr(self, '_security_was_paused', False):
            self.prep_started = time.monotonic()
            self._security_was_paused = False
        super()._tick_once()
        current = self.state.status()
        if current['status'] == 'CODIGO_CONFIRMADO_FIN':
            self.link_status.set('FIN: IMSS confirmó el código. No continuar con trámites ni PDF.')
            self.info.set('Código confirmado; LDPlayer retenido. No se inicia otra solicitud sobre ese emulador.')
        elif self.browser.phase == 'mail' and not self._mailbox_ready()['ready']:
            self.info.set('Bandeja visible, pero falta verificar la cuenta en el control de perfil de Outlook. Abre el perfil para revisar la dirección; IMSS sigue esperando.')

    def _try_auto_code(self, request, sender):
        # Evitar la ruta OAuth antigua con ventana temporal permisiva. Se usa
        # sólo el lector de mensajes estrictos del navegador en esta integración.
        self.auto_busy = False

    def _offer_cleanup_v39(self):
        # No ofrecer vaciar la lista al arrancar una integración.
        return

    def recover_previous_session(self):
        from tkinter import messagebox
        messagebox.showinfo('Folio retenido', 'Revisa o cancela explícitamente el folio antes de reutilizar la sesión. No se marca el código como aceptado manualmente.', parent=self)


class OutlookIntegradoWorker(IntegrationMixin, OutlookWorkerV36):
    pass


class OutlookIntegrado(IntegrationMixin, OutlookV41):
    def start_worker(self, n):
        if n not in (2, 3, 4):return
        old = self.children.get(n)
        if old and old.poll() is None:return
        env = dict(os.environ, GD_WORKER_SLOT=str(n), GD_HEADLESS='0', GD_BG_WORKER='1')
        self.children[n] = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), '--worker', str(n)],
            env=env, cwd=str(Path(__file__).resolve().parent), close_fds=True)

    def __init__(self):
        super().__init__()
        self.title('Gestoría Díaz · Outlook V45 integrado · LDPlayer · FIN EN CÓDIGO')
        self.info.set('Importa cuentas autorizadas. IMSS esperará la bandeja y la cuenta verificadas. Los desafíos Microsoft requieren intervención manual.')


def main():
    if sys.platform != 'win32':
        raise SystemExit('Las ventanas requieren Windows, Tk y DPAPI. En Linux ejecuta las pruebas locales.')
    if '--worker' in sys.argv:
        n = int(sys.argv[sys.argv.index('--worker') + 1])
        if n not in (2, 3, 4):raise ValueError('Canal inválido')
        instance = OutlookIntegradoWorker()
        instance.withdraw()
    else:
        instance = OutlookIntegrado()
    instance.mainloop()


if __name__ == '__main__':main()
