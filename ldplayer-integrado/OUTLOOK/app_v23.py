# -*- coding: utf-8 -*-
"""Outlook V23 DIAGNÓSTICO: sin modificar el flujo V22 ni mecanismos de login."""
import threading,time,tempfile,re,tkinter as tk
from app_v22 import OutlookV22
from diagnostico_v23 import clean,window_state,classify

class OutlookV23(OutlookV22):
    def __init__(self):
        self._diagnostic_started=None
        self._last_window_check=0.0
        self._last_window={'supported':False,'processes':None,'visible':None}
        self._browser_test_busy=False
        super().__init__()
        self.title('GESTORÍA DÍAZ · OUTLOOK V23 · DIAGNÓSTICO DE APERTURA')
        main=self.winfo_children()[0]
        self.diagnostic_label=tk.StringVar(value='Diagnóstico: esperando navegador.')
        tk.Label(main,textvariable=self.diagnostic_label,bg='#101419',fg='#E8BB62',
            wraplength=740,justify='left',font=('Segoe UI',10,'bold')).pack(anchor='w',pady=5)
        tk.Label(main,text='La V23 NO intenta otras cuentas para superar bloqueos de Microsoft.',
            bg='#101419',fg='#ACB6C1',font=('Segoe UI',9)).pack(anchor='w',pady=3)
        row=tk.Frame(main,bg='#101419');row.pack(fill='x',pady=2)
        self.button(row,'COPIAR DIAGNÓSTICO',self.copy_diagnostic).pack(side='left',padx=(0,8))
        self.button(row,'PROBAR CHROME SIN CORREO',self.browser_blank_test).pack(side='left')

    def _start_browser(self,email,pw):
        ok=super()._start_browser(email,pw)
        if ok:
            self._diagnostic_started=time.monotonic()
            self.diagnostic_label.set('SOLICITUD ENVIADA AL PROCESO · Aún no confirma una ventana.')
        return ok

    def _tick_once(self):
        super()._tick_once()
        now=time.monotonic()
        if now-self._last_window_check>=3:
            self._last_window=window_state()
            self._last_window_check=now
        age=(now-self._diagnostic_started if self._diagnostic_started is not None else None)
        status=classify(self.browser,age,self._last_window)
        if hasattr(self,'diagnostic_label'):
            self.diagnostic_label.set(status)
        if self.browser.running and age is not None and age>20 and not self.browser.browser_opened.is_set():
            self.browser_status.set('SIN VENTANA CONFIRMADA. No se ha iniciado sesión. Abre Diagnóstico.')
        if self.browser.running and age is not None and age>12 and self.browser.browser_opened.is_set() and self._last_window['supported'] and self._last_window['visible']==0:
            self.browser_status.set('PLAYWRIGHT ABRIÓ LA PESTAÑA, PERO WINDOWS AÚN NO DETECTA CHROME VISIBLE. Revisa si está minimizado. Esto no indica por sí solo un fallo de inicio de sesión.')

    def copy_diagnostic(self):
        b=self.browser
        win=window_state()
        age=(round(time.monotonic()-self._diagnostic_started) if self._diagnostic_started else 0)
        text='\n'.join([
            'GESTORIA DIAZ OUTLOOK V23 - DIAGNOSTICO SIN DATOS PERSONALES',
            'Estado: '+classify(b,age,win),
            'running='+str(bool(b.running)),
            'playwright_page='+str(bool(b.browser_opened.is_set())),
            'phase='+clean(getattr(b,'phase','')),
            'segundos_desde_intento='+str(age),
            'procesos_chrome_bot='+str(win['processes']),
            'ventanas_visibles_bot='+str(win['visible']),
            'windows_diagnostics_supported='+str(win['supported']),
            'rate_limited='+str(bool(getattr(b,'rate_limited',False))),
            'error='+clean(getattr(b,'last_error','')),
            'EVENTOS:',
            *(clean(x) for x in self.browser_events[-12:])
        ])
        try:
            self.clipboard_clear();self.clipboard_append(text);self.update_idletasks()
            self.info.set('Diagnóstico sin contraseñas copiado. Pégalo en el chat para localizar el fallo.')
        except Exception as exc:self.info.set('No se pudo copiar diagnóstico ('+type(exc).__name__+').')

    def browser_blank_test(self):
        if self._browser_test_busy:return
        if self.browser.running:
            self.info.set('Primero finaliza la sesión activa; no probaré Chrome durante un inicio de sesión.')
            return
        self._browser_test_busy=True
        self.info.set('Probando una ventana Chrome en blanco, sin introducir correos ni acceder a Microsoft.')
        def worker():
            answer=''
            try:
                from playwright.sync_api import sync_playwright
                with sync_playwright() as p:
                    with tempfile.TemporaryDirectory(prefix='gestoria_chrome_test_') as folder:
                        context=p.chromium.launch_persistent_context(folder,channel='chrome',headless=False,
                            args=['--no-first-run','--no-default-browser-check'],timeout=18000)
                        try:
                            page=context.new_page();page.goto('about:blank',wait_until='commit',timeout=7000)
                            answer='CHROME SÍ ABRE una ventana en blanco. La falla puede estar en el perfil individual o estado de sesión.'
                            time.sleep(2)
                        finally:context.close()
            except Exception as ex:
                answer='CHROME NO ABRIÓ la prueba sin correo ('+type(ex).__name__+'). Verifica Playwright e instalaciones.'
            def complete():
                self._browser_test_busy=False
                self.info.set(answer)
                self.diagnostic_label.set(answer)
            self.post_ui(complete)
        threading.Thread(target=worker,daemon=True).start()

if __name__=='__main__':OutlookV23().mainloop()
