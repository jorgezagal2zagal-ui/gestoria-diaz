"""Gestoría Díaz: prepara de 1 a 5 multiinstancias LDPlayer desde la plantilla.

1. Si una instancia GESTORIA_DIAZ_00X ya existe, NO se vuelve a crear.
2. Enciende las que estén apagadas.
3. Elige de 1 a 5 y pulsa PREPARAR / ENCENDER.
4. El bot introduce el PIN configurado, comprueba el desbloqueo y abre IMSS Digital.
"""
import csv
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from pathlib import Path
from html import unescape

DEFAULT = r'D:\LDPlayer\LDPlayer14\ldconsole.exe'
PACKAGE = 'st.android.imsspublico'
CANTIDAD = 3   # cantidad inicial; se elige de 1 a 5 desde la interfaz


def nombres_instancias(cantidad):
    """Nombres de la cantidad elegida, sin aceptar valores fuera de 1 a 5."""
    if isinstance(cantidad, str) and re.fullmatch(r'[1-5]', cantidad.strip()):
        cantidad = int(cantidad.strip())
    if type(cantidad) is not int or not 1 <= cantidad <= 5:
        raise ValueError('Elige una cantidad de instancias entre 1 y 5.')
    return [f'GESTORIA_DIAZ_00{i}' for i in range(1, cantidad + 1)]


NOMBRES = nombres_instancias(CANTIDAD)
TODOS_NOMBRES = nombres_instancias(5)
FLAGS = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
CARPETA_PROGRAMA = Path(__file__).resolve().parent


def directorio_datos():
    """Los datos de Windows sobreviven a la extracción temporal de un ZIP."""
    if sys.platform == 'win32':
        base = os.environ.get('LOCALAPPDATA') or os.environ.get('APPDATA')
        return (Path(base) if base else Path.home() / 'AppData' / 'Local') / 'GestoriaDiaz'
    return CARPETA_PROGRAMA / '.gestoria-datos'


CARPETA = directorio_datos()
USADOS = CARPETA / 'correos_usados.csv'


def preparar_datos():
    """Crear el almacén estable y conservar archivos de versiones anteriores."""
    CARPETA.mkdir(parents=True, exist_ok=True)
    for nombre in ('instancias.json', 'correos_usados.csv'):
        anterior, destino = CARPETA_PROGRAMA / nombre, CARPETA / nombre
        if anterior.is_file() and not destino.exists():
            try:
                with anterior.open('rb') as origen, destino.open('xb') as salida:
                    shutil.copyfileobj(origen, salida)
            except FileExistsError:
                pass             # otra ventana ya importó el historial; no sobrescribir

# Pantalla "Inicia sesión" de IMSS Digital (720x1280)
CHECK_AVISO = (75, 504)
PIN_EMULADOR = '1234'
TRAMITES = {   # solo estas 3 constancias
    'Constancia de semanas cotizadas': r'semanas\s*cotizadas',
    'Constancia de vigencia de derechos': r'vigencia\s*de\s*derechos',
    'Constancia de NSS (Número de Seguridad Social)': r'(asignaci[oó]n.*nss|consulta\s*nss|n[uú]mero de seguridad)',
}
CORTO = {'Constancia de semanas cotizadas': 'semanas', 'Constancia de vigencia de derechos': 'vigencia',
         'Constancia de NSS (Número de Seguridad Social)': 'nss'}

NEGRO, PANEL, DORADO, PLATA = '#121217', '#222229', '#d9b75b', '#c9c9c9'
VERDE, ROJO, AMARILLO = '#2ecc71', '#e74c3c', '#f1c40f'


# ---------------------------------------------------------------- ldconsole
def run(console, *args, timeout=60):
    """Sin pipes: la salida va a un archivo temporal para que nunca se congele."""
    with tempfile.TemporaryFile(mode='w+b') as f:
        try:
            subprocess.run([console, *args], cwd=str(Path(console).parent), stdout=f,
                           stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                           timeout=timeout, creationflags=FLAGS)
        except subprocess.TimeoutExpired:
            pass
        except Exception:
            return ''
        f.seek(0)
        return f.read().decode('utf-8', 'replace').strip()


MAPA = CARPETA / 'instancias.json'   # nombre -> índice de LDPlayer (por si LDPlayer le borra el nombre)


def leer_mapa():
    try:
        preparar_datos()
        return json.loads(MAPA.read_text(encoding='utf-8'))
    except Exception:
        return {}


def guardar_mapa(mapa):
    try:
        preparar_datos()
        MAPA.parent.mkdir(parents=True, exist_ok=True)
        MAPA.write_text(json.dumps(mapa, indent=2), encoding='utf-8')
    except Exception:
        pass


def olvidar_mapa(nombre):
    mapa = leer_mapa()
    if mapa.pop(nombre, None) is not None:
        guardar_mapa(mapa)


def listar(console):
    """list2: índice,nombre,top,bind,android_iniciado,pid,pid_vbox,...
    Si LDPlayer le quitó el nombre a una de las nuestras (sale como LDPlayer-N),
    la sigue reconociendo por su índice, sin apagarla."""
    filas = []
    for line in run(console, 'list2').splitlines():
        f = [x.strip() for x in line.split(',')]
        if len(f) > 5 and f[0].isdigit():
            filas.append(f)
    if not filas:
        return {}
    mapa = leer_mapa()
    por_indice = {v: k for k, v in mapa.items()}
    out, cambio = {}, False
    for f in filas:
        idx, real = f[0], f[1]
        nombre = real
        if real not in TODOS_NOMBRES and real == f'LDPlayer-{idx}' and idx in por_indice:
            nombre = por_indice[idx]
        if nombre in TODOS_NOMBRES and mapa.get(nombre) != idx:
            mapa[nombre] = idx
            cambio = True
        out[nombre] = {'index': idx, 'real': real, 'android': f[4] == '1', 'pid': f[5],
                       'running': f[5] not in ('', '-1', '0')}
    if cambio:
        guardar_mapa(mapa)
    return out


def celular(console, idx):
    """Resolución vertical de celular. Solo con la instancia APAGADA."""
    run(console, 'modify', '--index', str(idx), '--resolution', '720,1280,320',
        '--cpu', '2', '--memory', '3072')


def es_tablet(console, idx):
    """True si la instancia encendida está en horizontal/tablet (ancho > alto)."""
    out = adb(console, idx, 'shell', 'wm', 'size', timeout=10)
    m = re.findall(r'(\d+)x(\d+)', out)
    if not m:
        return False                      # sin ADB: no se puede saber, no se toca
    w, h = map(int, m[-1])
    return w > h


def reparar(console, emit, nombres=None):
    """Devuelve el nombre a las copias que LDPlayer dejó como LDPlayer-N.
    NUNCA apaga una instancia encendida: si está prendida solo la renombra."""
    nombres = tuple(NOMBRES if nombres is None else nombres)
    inst = listar(console)
    for n in nombres:                       # nuestras que perdieron el nombre (por índice)
        i = inst.get(n)
        if i and i['real'] != n:
            emit(f"🔧 {i['real']} es {n}; le regreso el nombre")
            run(console, 'rename', '--index', i['index'], '--title', n)
    faltan = [n for n in nombres if n not in inst]
    sueltas = sorted((v['index'], k) for k, v in inst.items()
                     if k == f"LDPlayer-{v['index']}")
    if faltan and sueltas:
        mapa = leer_mapa()
        for n, (idx, viejo) in zip(faltan, sueltas):
            emit(f'🔧 {viejo} perdió su nombre; la convierto en {n}')
            mapa[n] = idx
            run(console, 'rename', '--index', idx, '--title', n)
            if not inst[viejo]['running']:   # la resolución solo se puede cambiar apagada
                run(console, 'modify', '--index', idx, '--resolution', '720,1280,320',
                    '--cpu', '2', '--memory', '3072')
        guardar_mapa(mapa)
        time.sleep(2)
    inst = listar(console)
    for n in nombres:
        i = inst.get(n)
        if i and i['running'] and i['android'] and es_tablet(console, i['index']):
            emit(f'📱 {n} quedó en modo tablet; la reinicio una vez en modo celular')
            run(console, 'quit', '--index', i['index'])
            time.sleep(6)
            celular(console, i['index'])
            asegurar_adb(console, i['index'], n)
            run(console, 'launch', '--index', i['index'])
            time.sleep(3)
    inst = listar(console)
    for n in nombres:
        i = inst.get(n)
        if i and not i['running'] and asegurar_adb(console, i['index'], n):
            emit(f'🔧 {n}: activé la depuración ADB')
    return inst


def asegurar_adb(console, idx, nombre=None):
    """Con la instancia APAGADA: deja ADB activado y el nombre puesto en su config,
    en una sola escritura (así LDPlayer no los vuelve a borrar al arrancar)."""
    cfg = Path(console).parent / 'vms' / 'config' / f'leidian{idx}.config'
    try:
        data = json.loads(cfg.read_text(encoding='utf-8'))
        cambio = False
        if data.get('basicSettings.adbDebug') != 1:
            data['basicSettings.adbDebug'] = 1
            cambio = True
        if nombre and data.get('statusSettings.playerName', nombre) != nombre:
            data['statusSettings.playerName'] = nombre
            cambio = True
        if cambio:
            cfg.write_text(json.dumps(data, indent=4, ensure_ascii=False), encoding='utf-8')
        return cambio
    except Exception:
        return False


def _sin_pipes(args, timeout=40):
    with tempfile.TemporaryFile(mode='w+b') as f:
        try:
            subprocess.run(args, stdout=f, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                           timeout=timeout, creationflags=FLAGS)
        except Exception:
            return ''
        f.seek(0)
        return f.read().decode('utf-8', 'replace').strip()


def adb(console, idx, *args, timeout=40):
    exe = str(Path(console).parent / 'adb.exe')
    return _sin_pipes([exe, '-s', f'emulator-{5554 + 2 * int(idx)}', *args], timeout)


def estado_bloqueo_android(salida):
    """True/False solo con evidencia de keyguard; None si ADB no permite saberlo."""
    if not salida or re.search(r'(?im)^\s*(?:adb:\s*)?error\b|device\s+(?:offline|unauthorized)', salida):
        return None
    flags = re.findall(
        r'\b(?:isKeyguardShowing|mKeyguardShowing|mIsKeyguardShowing|keyguardShowing|'
        r'isStatusBarKeyguard|mShowingLockscreen|mDreamingLockscreen)'
        r'\s*(?:\(\))?\s*[:=]\s*(true|false)\b', salida, re.I)
    # Algunas versiones de Android usan showing/inputRestricted dentro del delegado.
    lineas = salida.splitlines()
    for pos, linea in enumerate(lineas):
        if not re.search(r'\b(?:KeyguardServiceDelegate|mKeyguardDelegate)\b', linea, re.I):
            continue
        margen = len(linea) - len(linea.lstrip())
        bloque = [linea]
        for siguiente in lineas[pos + 1:]:
            if siguiente.strip() and len(siguiente) - len(siguiente.lstrip()) <= margen:
                break
            bloque.append(siguiente)
        flags.extend(re.findall(
            r'\b(?:showing|inputRestricted)\s*[:=]\s*(true|false)\b', '\n'.join(bloque), re.I))
    if any(valor.lower() == 'true' for valor in flags):
        return True
    return False if flags else None


def introducir_pin_android(console, idx, pin):
    """Introduce un PIN configurado con eventos del teclado numérico de Android."""
    if not isinstance(pin, str) or not re.fullmatch(r'[0-9]{4,12}', pin):
        return False
    adb(console, idx, 'shell', 'input', 'keyevent', 'KEYCODE_MOVE_END')
    adb(console, idx, 'shell', 'input', 'keyevent', *(['KEYCODE_DEL'] * 12))
    for digito in pin:
        adb(console, idx, 'shell', 'input', 'keyevent', 'KEYCODE_' + digito)
    adb(console, idx, 'shell', 'input', 'keyevent', 'KEYCODE_ENTER')
    return True


def desbloquear_android(console, idx, pin):
    """True si se desbloqueó, False si falló, None si no llegó a enviar el PIN."""
    if not isinstance(pin, str) or not re.fullmatch(r'[0-9]{4,12}', pin):
        return False
    antes = adb(console, idx, 'shell', 'dumpsys', 'window', 'policy', timeout=10)
    if estado_bloqueo_android(antes) is not True:
        return None
    adb(console, idx, 'shell', 'input', 'keyevent', 'KEYCODE_WAKEUP')
    dimensiones = adb(console, idx, 'shell', 'wm', 'size', timeout=10)
    medidas = re.findall(r'(\d+)x(\d+)', dimensiones)
    ancho, alto = map(int, medidas[-1]) if medidas else (720, 1280)
    x = str(ancho // 2)
    adb(console, idx, 'shell', 'input', 'swipe', x, str(int(alto * .8)),
        x, str(int(alto * .25)), '300')
    time.sleep(.5)
    introducir_pin_android(console, idx, pin)
    for _ in range(3):
        time.sleep(1)
        despues = adb(console, idx, 'shell', 'dumpsys', 'window', 'policy', timeout=10)
        if estado_bloqueo_android(despues) is False:
            return True
    return False


def enviar_pin_identidad(console, idx, nodos, pin):
    """Enfoca el campo de identidad o usa su teclado visible antes de enviar el PIN."""
    if not isinstance(pin, str) or not re.fullmatch(r'[0-9]{4,12}', pin):
        return False
    pantalla_visible = [n for n in nodos if n.get('visible', True) and n.get('area', 0) > 0]
    texto = todo_texto(pantalla_visible)
    if re.search(r'c[oó]digo de validaci[oó]n', texto):
        return False
    if not re.search(r'(?:validaci[oó]n|verificaci[oó]n) de identidad|confirma tu identidad|'
                     r'(?:ingresa|introduce) (?:tu |el )?pin', texto):
        return False

    visibles = [n for n in pantalla_visible if n.get('enabled')]
    campos = [n for n in visibles if re.sub(r'[^a-z0-9]', '',
              n.get('rid', '').rsplit('/', 1)[-1].lower()) in
              ('passwordentry', 'pinentry', 'password', 'passwordinput', 'pininput',
               'passwordfield', 'pinfield', 'edittextpin', 'inputpin')]
    if not campos:
        campos = [n for n in visibles if n.get('clase', '').endswith('EditText')]
        enfocados = [n for n in campos if n.get('focused')]
        if len(enfocados) == 1:
            campos = enfocados
    if len(campos) == 1:
        tocar(console, idx, campos[0]['xy'])
        return introducir_pin_android(console, idx, pin)

    teclado = {}
    for nodo in visibles:
        clave = nodo.get('rid', '').rsplit('/', 1)[-1]
        identificador = re.fullmatch(r'key([0-9])', clave, re.I)
        if identificador:
            teclado.setdefault(identificador.group(1), nodo)
    for nodo in visibles:
        if re.fullmatch(r'key[0-9]', nodo.get('rid', '').rsplit('/', 1)[-1], re.I):
            continue
        etiqueta = nodo.get('texto', '').strip()
        inicial = re.match(r'^([0-9])(?:\s|$)', etiqueta)
        if inicial:
            digito = inicial.group(1)
            # UIAutomator puede unir texto y descripción: "1 1" o "2 ABC".
            # Un segundo número distinto o un valor multidígito es ambiguo.
            sufijos = etiqueta[1:].split()
            if all(parte == digito or not re.search(r'\d', parte) for parte in sufijos):
                teclado.setdefault(digito, nodo)
    if len(teclado) != 10:
        return False
    # La propia pantalla de identidad ofrece los diez botones numéricos.
    adb(console, idx, 'shell', 'input', 'keyevent', *(['KEYCODE_DEL'] * 12))
    for digito in pin:
        tocar(console, idx, teclado[digito]['xy'])
    adb(console, idx, 'shell', 'input', 'keyevent', 'KEYCODE_ENTER')
    return True


def en_imss(console, idx):
    """True si IMSS Digital ya está al frente en esa instancia."""
    return PACKAGE in adb(console, idx, 'shell', 'dumpsys window | grep mCurrentFocus', timeout=10)


def abrir_app(console, nombre, idx):
    """Trae IMSS Digital al frente SIN reiniciar la instancia ni la app.
    Si ya está al frente, no toca nada. Solo si no hay ADB usa ldconsole runapp."""
    if en_imss(console, idx):
        return 'ya estaba abierta'
    out = adb(console, idx, 'shell', 'monkey', '-p', PACKAGE, '-c',
              'android.intent.category.LAUNCHER', '1', timeout=20)
    if 'Events injected' in out:
        return 'traída al frente'
    run(console, 'runapp', '--index', str(idx), '--packagename', PACKAGE, timeout=40)
    return 'abierta con ldconsole (sin ADB)'


def pantalla(console, idx):
    """Nodos visibles: dict con rid, texto (text o content-desc), enabled, centro, clase."""
    adb(console, idx, 'shell', 'uiautomator', 'dump', '/sdcard/u.xml')
    xml = adb(console, idx, 'shell', 'cat', '/sdcard/u.xml')
    nodos = []
    for m in re.finditer(r'<node [^>]*>', xml):
        t = m.group(0)
        g = lambda k: unescape((re.search(k + r'="([^"]*)"', t) or [None, ''])[1])
        b = list(map(int, re.findall(r'-?\d+', g('bounds'))))
        if len(b) != 4:
            b = [0, 0, 0, 0]
        valor, descripcion = g('text'), g('content-desc')
        texto = ' '.join((valor + ' ' + descripcion).split())
        nodos.append({'rid': g('resource-id'), 'texto': texto,
                      'valor': valor, 'descripcion': descripcion, 'bounds': tuple(b),
                      'visible': g('visible-to-user') != 'false',
                      'focused': g('focused') == 'true',
                      'enabled': g('enabled') == 'true',
                      'xy': ((b[0] + b[2]) // 2, (b[1] + b[3]) // 2), 'clase': g('class'),
                      'area': max(0, b[2] - b[0]) * max(0, b[3] - b[1])})
    return nodos


def cajas_codigo_validacion(nodos):
    """Selecciona la fila de seis casillas; excluye los campos CURP/correo."""
    campos = [n for n in nodos if n.get('clase', '').endswith('EditText')
              and n.get('visible', True) and n.get('enabled') and n.get('area', 0) > 0
              and min(n['xy']) >= 0]
    medidas = []
    for campo in campos:
        limites = campo.get('bounds')
        if limites and len(limites) == 4:
            ancho, alto = limites[2] - limites[0], limites[3] - limites[1]
        else:
            ancho = alto = campo['area'] ** .5
        if ancho > 0 and alto > 0 and .3 <= ancho / alto <= 2:
            medidas.append((campo, ancho, alto))
    filas = {}
    for referencia, _, alto in medidas:
        fila = [(n, w, h) for n, w, h in medidas
                if abs(n['xy'][1] - referencia['xy'][1]) <= min(alto, h) * .25]
        if len(fila) != 6:
            continue
        fila.sort(key=lambda item: item[0]['xy'][0])
        anchos, altos = [item[1] for item in fila], [item[2] for item in fila]
        distancias = [fila[i + 1][0]['xy'][0] - fila[i][0]['xy'][0] for i in range(5)]
        if (max(anchos) > min(anchos) * 1.8 or max(altos) > min(altos) * 1.5
                or min(distancias) < min(anchos) * .6
                or max(distancias) > max(anchos) * 2.2):
            continue
        clave = tuple(n['xy'] for n, _, _ in fila)
        filas[clave] = [n for n, _, _ in fila]
    if len(filas) == 1:
        return next(iter(filas.values()))
    if filas:
        return []                # varias filas posibles: no escribir en una al azar
    unicas = []
    for campo in campos:
        rid = re.sub(r'[^a-z0-9]', '', campo.get('rid', '').rsplit('/', 1)[-1].lower())
        if rid in ('otp', 'otpinput', 'codeinput', 'verificationcode', 'validationcode',
                   'codigovalidacion', 'codigoverificacion', 'txtcodigo', 'inputcodigo'):
            unicas.append(campo)
    return unicas if len(unicas) == 1 else []


def codigo_escrito(cajas):
    """Lee el valor real; los números de las descripciones no son dígitos escritos."""
    valores = [n.get('valor', n.get('texto', '')).strip() for n in cajas]
    if len(cajas) == 6 and all(re.fullmatch(r'[0-9]?', valor) for valor in valores):
        return ''.join(valores)
    if len(cajas) == 1 and re.fullmatch(r'[0-9]{0,6}', valores[0]):
        return valores[0]
    return ''


def todo_texto(nodos):
    return ' | '.join(n['texto'] for n in nodos if n['texto']).lower()


def buscar(nodos, rid):
    for n in nodos:
        if n['rid'].endswith(rid):
            return n
    return None


def buscar_texto(nodos, patron):
    """Nodo más chico cuyo texto coincide (regex, sin mayúsculas)."""
    hits = [n for n in nodos if n['texto'] and re.search(patron, n['texto'], re.I)]
    return min(hits, key=lambda n: n['area']) if hits else None


def tocar(console, idx, xy):
    adb(console, idx, 'shell', 'input', 'tap', str(xy[0]), str(xy[1]))
    time.sleep(1)


def escribir(console, idx, xy, texto):
    tocar(console, idx, xy)
    adb(console, idx, 'shell', 'input', 'keyevent', 'KEYCODE_MOVE_END')
    adb(console, idx, 'shell', 'input', 'keyevent', *(['KEYCODE_DEL'] * 60))
    adb(console, idx, 'shell', 'input', 'text', texto)
    time.sleep(0.8)


def tocar_texto(console, idx, patron, bajar=4):
    """Busca un botón/mosaico por su texto (haciendo scroll si hace falta) y lo toca."""
    for intento in range(bajar + 1):
        n = buscar_texto(pantalla(console, idx), patron)
        if n:
            tocar(console, idx, n['xy'])
            return True
        adb(console, idx, 'shell', 'input', 'swipe', '360', '1000', '360', '450', '400')
        time.sleep(1.2)
    return False


def leer_correos(ruta):
    """TXT: un correo por línea (si trae ':contraseña' se ignora)."""
    lista = []
    for linea in Path(ruta).read_text(encoding='utf-8', errors='replace').splitlines():
        correo = linea.strip().split(':', 1)[0].strip()
        if re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', correo):
            lista.append(correo)
    return lista


def correos_usados():
    preparar_datos()
    if not USADOS.is_file():
        return set()
    with USADOS.open(encoding='utf-8') as f:
        return {r['correo'].lower() for r in csv.DictReader(f)}


def marcar_usado(curp, correo, instancia, tramite):
    preparar_datos()
    USADOS.parent.mkdir(parents=True, exist_ok=True)
    nuevo = not USADOS.is_file()
    with USADOS.open('a', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=['fecha', 'curp', 'correo', 'instancia', 'tramite'])
        if nuevo:
            w.writeheader()
        w.writerow({'fecha': time.strftime('%Y-%m-%d %H:%M'), 'curp': curp, 'correo': correo,
                    'instancia': instancia, 'tramite': tramite})


# ---------------------------------------------------------------- interfaz
class App:
    def __init__(self, root):
        self.root = root
        root.title('GESTORÍA DÍAZ | 1 A 5 MULTIINSTANCIAS')
        root.geometry(f'{min(1000, root.winfo_screenwidth() - 60)}x'
                      f'{min(980, root.winfo_screenheight() - 100)}')
        root.configure(bg=NEGRO)
        self.events = queue.Queue()
        self.usados_sesion = set()
        self.correos_pendientes = []
        self.bloqueo_correos = threading.RLock()
        self.ultimo_guardado_correos = 0.0
        self.aviso_guardado_pendiente = False
        try:
            preparar_datos()
        except OSError:
            self.emit('⚠ No pude preparar la carpeta de datos. Los correos se conservarán en esta sesión hasta poder guardarlos.')
        self.busy = False
        self.desbloqueando = False
        self.nombres = tuple(NOMBRES)
        self.iniciado = False     # esperar a que se elija cantidad y se pulse preparar
        self.cantidad_var = tk.StringVar(value=str(CANTIDAD))
        self.intentos_pin = {}
        self.console = tk.StringVar(value=DEFAULT)
        self.arranque = {}        # nombre -> momento en que Android quedó listo
        self.enviados = {}        # nombre -> cuántas veces se mandó IMSS
        self.auto_on = True       # reponer instancias borradas
        self.ultimo_auto = 0
        self.bloqueada = {}       # nombre -> último estado de bloqueo visto
        self.sesion = {}          # nombre -> (índice, pid): identifica la instancia REAL
        self.ultimo_abrir = {}    # nombre -> cuándo se abrió IMSS por última vez

        tk.Label(root, text='GESTORÍA DÍAZ', bg=NEGRO, fg=DORADO,
                 font=('Segoe UI', 26, 'bold')).pack(pady=(18, 2))
        tk.Label(root, text='PREPARADOR DE 1 A 5 MULTIINSTANCIAS · IMSS DIGITAL',
                 bg=NEGRO, fg='white', font=('Segoe UI', 10, 'bold')).pack(pady=(0, 12))

        fr = tk.Frame(root, bg=PANEL, padx=12, pady=10)
        fr.pack(fill='x', padx=24)
        tk.Label(fr, text='Ruta de ldconsole.exe', bg=PANEL, fg='white').pack(anchor='w')
        row = tk.Frame(fr, bg=PANEL)
        row.pack(fill='x', pady=(6, 0))
        tk.Entry(row, textvariable=self.console).pack(side='left', fill='x', expand=True, ipady=5)
        tk.Button(row, text='Examinar', command=self.browse).pack(side='left', padx=(8, 0))

        cantidades = tk.Frame(fr, bg=PANEL)
        cantidades.pack(fill='x', pady=(10, 0))
        tk.Label(cantidades, text='¿Cuántas instancias quieres abrir?',
                 bg=PANEL, fg='white').pack(side='left')
        self.selector_cantidad = ttk.Combobox(
            cantidades, textvariable=self.cantidad_var, values=(1, 2, 3, 4, 5),
            width=4, state='readonly')
        self.selector_cantidad.pack(side='left', padx=10)
        self.selector_cantidad.bind('<<ComboboxSelected>>', self.aplicar_cantidad)
        tk.Label(cantidades, text='Elige de 1 a 5 y pulsa PREPARAR / ENCENDER.',
                 bg=PANEL, fg=PLATA).pack(side='left')

        caja = tk.Frame(root, bg=NEGRO)
        caja.pack(fill='x', padx=24, pady=12)
        self.filas = {}
        self.marcos_filas = {}
        for n in TODOS_NOMBRES:
            f = tk.Frame(caja, bg=PANEL, highlightbackground=DORADO, highlightthickness=1)
            f.pack(fill='x', pady=3)
            c = tk.Canvas(f, width=20, height=20, bg=PANEL, highlightthickness=0)
            c.pack(side='left', padx=10, pady=6)
            foco = c.create_oval(3, 3, 17, 17, fill=ROJO, outline='')
            tk.Label(f, text=n, bg=PANEL, fg=PLATA, font=('Consolas', 11),
                     width=24, anchor='w').pack(side='left')
            est = tk.Label(f, text='Sin revisar', bg=PANEL, fg=ROJO,
                           font=('Segoe UI', 10, 'bold'), anchor='w')
            est.pack(side='left', fill='x', expand=True)
            tk.Button(f, text='🗑 Eliminar y reemplazar', command=lambda nom=n: self.eliminar(nom),
                      bg='#5a1a1a', fg='white', activebackground=ROJO, relief='flat',
                      font=('Segoe UI', 9, 'bold'), padx=8).pack(side='right', padx=8, pady=4)
            self.filas[n] = (c, foco, est)
            self.marcos_filas[n] = f
            if n not in self.nombres:
                f.pack_forget()

        self.aviso = tk.Label(root, text='', bg=NEGRO, fg=DORADO, font=('Segoe UI', 11, 'bold'))
        self.aviso.pack(pady=(0, 6))

        bf = tk.Frame(root, bg=NEGRO)
        bf.pack()
        self.btn = tk.Button(bf, text='▶  PREPARAR / ENCENDER', command=self.start,
                             bg=DORADO, fg='#111', font=('Segoe UI', 12, 'bold'),
                             padx=18, pady=10, relief='flat')
        self.btn.pack(side='left', padx=6)
        self.btn_imss = tk.Button(bf, text='📱 REABRIR IMSS DIGITAL', command=self.imss,
                                  bg=PLATA, fg='#111', font=('Segoe UI', 12, 'bold'),
                                  padx=18, pady=10, relief='flat')
        self.btn_imss.pack(side='left', padx=6)
        self.auto_var = tk.BooleanVar(value=True)
        tk.Checkbutton(bf, text='Reponer automáticamente si borro una instancia', variable=self.auto_var,
                       command=lambda: setattr(self, 'auto_on', self.auto_var.get()),
                       bg=NEGRO, fg='white', selectcolor=PANEL, activebackground=NEGRO,
                       activeforeground=DORADO).pack(side='left', padx=10)

        # ---- consulta IMSS
        cf = tk.Frame(root, bg=PANEL, padx=12, pady=10, highlightbackground=DORADO,
                      highlightthickness=1)
        cf.pack(fill='x', padx=24, pady=(14, 0))
        tk.Label(cf, text='CONSULTA IMSS DIGITAL', bg=PANEL, fg=DORADO,
                 font=('Segoe UI', 11, 'bold')).grid(row=0, column=0, columnspan=4, sticky='w')
        tk.Label(cf, text='CURP del cliente', bg=PANEL, fg='white').grid(row=1, column=0, sticky='w', pady=5)
        self.curp = tk.StringVar()
        tk.Entry(cf, textvariable=self.curp, width=24, font=('Consolas', 12)).grid(
            row=1, column=1, sticky='w', padx=6)
        tk.Label(cf, text='Instancia', bg=PANEL, fg='white').grid(row=1, column=2, sticky='e')
        self.inst_sel = tk.StringVar(value=self.nombres[0])
        self.selector_instancia = ttk.Combobox(
            cf, textvariable=self.inst_sel, values=self.nombres, width=20,
            state='readonly')
        self.selector_instancia.grid(row=1, column=3, padx=6)
        tk.Label(cf, text='Trámite', bg=PANEL, fg='white').grid(row=2, column=0, sticky='w', pady=5)
        self.tramite = tk.StringVar(value='Constancia de semanas cotizadas')
        ttk.Combobox(cf, textvariable=self.tramite, values=list(TRAMITES), width=44,
                     state='readonly').grid(row=2, column=1, columnspan=2, sticky='w', padx=6)
        tk.Button(cf, text='📄 Cargar correos (TXT)', command=self.cargar_txt).grid(
            row=3, column=0, sticky='w', pady=4)
        self.info_correos = tk.Label(cf, text='Sin archivo de correos', bg=PANEL, fg=PLATA)
        self.info_correos.grid(row=3, column=1, columnspan=2, sticky='w', padx=6)
        self.btn_consulta = tk.Button(cf, text='🔎 1. INICIAR', command=self.consulta,
                                      bg=DORADO, fg='#111', font=('Segoe UI', 11, 'bold'),
                                      relief='flat', padx=14, pady=5)
        self.btn_consulta.grid(row=3, column=3, pady=4)
        tk.Label(cf, text='Código del correo', bg=PANEL, fg='white').grid(row=4, column=0, sticky='w', pady=5)
        self.codigo = tk.StringVar()
        tk.Entry(cf, textvariable=self.codigo, width=10, font=('Consolas', 14)).grid(
            row=4, column=1, sticky='w', padx=6)
        self.btn_codigo = tk.Button(cf, text='✅ 2. ENVIAR CÓDIGO', command=self.enviar_codigo,
                                    bg=VERDE, fg='#111', font=('Segoe UI', 11, 'bold'),
                                    relief='flat', padx=14, pady=5, state='disabled')
        self.btn_codigo.grid(row=4, column=3, pady=4)
        tk.Button(cf, text='🚪 Cerrar sesión IMSS', command=self.cerrar_sesion).grid(
            row=4, column=2, sticky='e')
        self.correos = []
        self.pendiente = None        # (path, idx, nombre, curp, correo, tramite)

        self.log = tk.Text(root, bg='#1d1d24', fg='#eeeeee', font=('Consolas', 9),
                           state='disabled', relief='flat')
        self.log.pack(fill='both', expand=True, padx=24, pady=(12, 18))

        root.after(100, self.poll)
        threading.Thread(target=self.monitor, daemon=True).start()
        self.aviso.configure(text='Elige de 1 a 5 instancias y pulsa PREPARAR / ENCENDER.')

    # ---------- utilidades GUI
    def aplicar_cantidad(self, event=None):
        """Actualizar la selección sin apagar ni borrar las instancias sobrantes."""
        if self.busy or getattr(self, 'desbloqueando', False):
            self.cantidad_var.set(str(len(self.nombres)))
            return False
        try:
            nombres = tuple(nombres_instancias(self.cantidad_var.get()))
        except ValueError as exc:
            self.cantidad_var.set(str(len(self.nombres)))
            messagebox.showerror('Gestoría Díaz', str(exc))
            return False
        if nombres != self.nombres:
            self.iniciado = False
            self.nombres = nombres
            self.aviso.configure(text='Cantidad elegida. Pulsa PREPARAR / ENCENDER para continuar.')
        for nombre, marco in self.marcos_filas.items():
            if nombre in self.nombres:
                marco.pack(fill='x', pady=3)
            else:
                marco.pack_forget()
        self.selector_instancia.configure(values=self.nombres)
        if self.inst_sel.get() not in self.nombres:
            self.inst_sel.set(self.nombres[0])
        return True

    def browse(self):
        p = filedialog.askopenfilename(filetypes=[('ldconsole.exe', 'ldconsole.exe'), ('EXE', '*.exe')])
        if p:
            self.console.set(p)

    def emit(self, msg):
        self.events.put(('log', time.strftime('[%H:%M:%S] ') + msg))

    def estado(self, n, texto, color):
        self.events.put(('estado', (n, texto, color)))

    def ruta(self):
        p = self.console.get().strip().strip('"')
        return p if Path(p).is_file() else None

    def poll(self):
        try:
            while True:
                ev, data = self.events.get_nowait()
                if ev == 'log':
                    self.log.configure(state='normal')
                    self.log.insert('end', data + '\n')
                    self.log.see('end')
                    self.log.configure(state='disabled')
                elif ev == 'estado':
                    n, t, col = data
                    c, foco, est = self.filas[n]
                    c.itemconfig(foco, fill=col)
                    est.configure(text=t, fg=col)
                elif ev == 'aviso':
                    self.aviso.configure(text=data)
                elif ev == 'done':
                    self.busy = False
                    self.btn.configure(state='normal')
                    self.selector_cantidad.configure(state='readonly')
        except queue.Empty:
            pass
        if (getattr(self, 'correos_pendientes', [])
                and time.monotonic() - self.ultimo_guardado_correos >= 5):
            self.guardar_correos_pendientes()
        self.root.after(100, self.poll)

    # ---------- preparar
    def start(self):
        if self.busy:
            return
        if not self.aplicar_cantidad():
            return
        path = self.ruta()
        if not path:
            messagebox.showerror('Gestoría Díaz', 'No se encontró ldconsole.exe. Comprueba la ruta.')
            return
        self.busy = True
        self.iniciado = True
        self.btn.configure(state='disabled')
        self.selector_cantidad.configure(state='disabled')
        threading.Thread(target=self.work, args=(path,), daemon=True).start()

    def work(self, path):
        nombres = tuple(self.nombres)
        try:
            inst = reparar(path, self.emit, nombres)
            faltan = [n for n in nombres if n not in inst]
            for n in nombres:
                if n in inst:
                    self.emit(f'✔ {n} ya existe, no se vuelve a crear')

            # 1) crear solo las que falten
            if faltan:
                plantillas = sorted(n for n in inst if 'PLANTILLA' in n.upper())
                if not plantillas:
                    self.emit('ERROR: no encontré ninguna instancia con "PLANTILLA" en el nombre.')
                    return
                plantilla = plantillas[0]
                self.emit(f'Plantilla: {plantilla}')
                if inst[plantilla]['running']:
                    self.emit('La plantilla está encendida; la apago para poder copiarla...')
                    run(path, 'quit', '--name', plantilla)
                    time.sleep(8)
                for n in faltan:
                    for intento in (1, 2):
                        self.estado(n, 'Copiando plantilla...', AMARILLO)
                        self.emit(f'➕ Creando {n} desde {plantilla} (intento {intento})')
                        run(path, 'copy', '--name', n, '--from', inst[plantilla]['index'], timeout=1800)
                        time.sleep(3)
                        if n in listar(path):
                            self.emit(f'   {n} creada')
                            break
                    else:
                        self.estado(n, 'No se pudo crear', ROJO)
                        self.emit(f'ERROR: {n} no se pudo crear')
                time.sleep(15)        # dejar que LDPlayer termine de guardar las copias
                inst = reparar(path, self.emit, nombres)

            # 2) encender las apagadas (una por una, después de terminar TODAS las copias)
            for n in nombres:
                if n in inst and not inst[n]['running']:
                    self.estado(n, 'Encendiendo...', AMARILLO)
                    self.emit(f'▶ Encendiendo {n} (modo celular 720x1280)')
                    celular(path, inst[n]['index'])
                    run(path, 'launch', '--index', inst[n]['index'])
                    time.sleep(15)
            # 3) revisar: reparar nombres perdidos y reintentar las que no prendieron
            time.sleep(20)
            inst = listar(path)
            for n in nombres:
                if n in inst and not inst[n]['running']:
                    self.emit(f'↻ {n} no prendió, lo intento otra vez')
                    celular(path, inst[n]['index'])
                    run(path, 'launch', '--index', inst[n]['index'])
                    time.sleep(15)
            self.events.put(('aviso', '🔑 Android se desbloquea con el PIN configurado y después se abre IMSS Digital.'))
            self.emit('Preparación terminada. El monitor comprobará el PIN y abrirá IMSS Digital.')
        except Exception as exc:
            self.emit(f'ERROR: {exc}')
        finally:
            self.events.put(('done', None))

    # ---------- eliminar y reemplazar
    def eliminar(self, nombre):
        path = self.ruta()
        if not path:
            return
        if self.busy:
            messagebox.showinfo('Gestoría Díaz', 'Espera a que el bot termine lo que está haciendo.')
            return
        if not messagebox.askyesno('Gestoría Díaz',
                                   f'¿Eliminar {nombre} y crear una nueva desde la plantilla?\n\n'
                                   'Se borra para siempre lo que tenga esa instancia.'):
            return
        self.busy = True
        self.btn.configure(state='disabled')
        self.selector_cantidad.configure(state='disabled')
        threading.Thread(target=self._eliminar, args=(path, nombre), daemon=True).start()

    def _eliminar(self, path, nombre):
        try:
            self.ultimo_auto = time.time()          # que el monitor no la reponga al mismo tiempo
            self.olvidar(nombre)                    # nada de la instancia vieja se queda guardado
            self.estado(nombre, 'Eliminando...', ROJO)
            self.emit(f'🗑 Apagando y eliminando {nombre}')
            info = listar(path).get(nombre)
            if info:
                run(path, 'quit', '--index', info['index'])
                time.sleep(6)
                run(path, 'remove', '--index', info['index'], timeout=120)
                time.sleep(3)
            if nombre in listar(path):
                self.emit(f'✖ No se pudo eliminar {nombre}; ciérrala en LDMultiPlayer e intenta otra vez')
                self.events.put(('done', None))
                return
            olvidar_mapa(nombre)
            self.emit(f'   {nombre} eliminada. Creo una nueva desde la plantilla...')
            self.work(path)          # crea la que falta, le activa ADB y la prende
        except Exception as exc:
            self.emit(f'ERROR al eliminar: {exc}')
            self.events.put(('done', None))

    # ---------- abrir IMSS
    def imss(self):
        path = self.ruta()
        if path:
            threading.Thread(target=self._imss, args=(path,), daemon=True).start()

    def _imss(self, path):
        inst = listar(path)
        for n in tuple(self.nombres):
            i = inst.get(n)
            if not i or not i['running'] or not i['android']:
                self.emit(f'⚠ {n}: no está encendida o Android no ha terminado de arrancar (no la toco)')
                continue
            if self.bloqueada.get(n):
                self.emit(f'🔒 {n}: está bloqueada; al meter tu PIN se abre IMSS sola')
                continue
            res = abrir_app(path, n, i['index'])
            self.ultimo_abrir[n] = time.time()
            self.estado(n, '📱 IMSS Digital abierto', VERDE)
            self.emit(f'📱 {n}: IMSS Digital {res}')
        self.events.put(('aviso', '✅ IMSS Digital al frente en las instancias encendidas'))

    # ---------- consulta IMSS
    def cargar_txt(self):
        p = filedialog.askopenfilename(filetypes=[('Texto', '*.txt')])
        if not p:
            return
        self.correos = leer_correos(p)
        self.refrescar_correos()
        self.emit(f'📄 Cargados {len(self.correos)} correos de {Path(p).name}')

    def disponibles(self):
        usados = correos_usados() | getattr(self, 'usados_sesion', set()).copy()
        return [c for c in self.correos if c.lower() not in usados]

    def registrar_correo(self, curp, correo, nombre, tramite):
        """Reservar primero en memoria: un fallo de disco no debe cancelar el PIN."""
        if not hasattr(self, 'bloqueo_correos'):
            self.bloqueo_correos = threading.RLock()
            self.usados_sesion = set()
            self.correos_pendientes = []
            self.ultimo_guardado_correos = 0.0
            self.aviso_guardado_pendiente = False
        with self.bloqueo_correos:
            self.usados_sesion.add(correo.lower())
            self.correos_pendientes.append((curp, correo, nombre, tramite))
        return self.guardar_correos_pendientes()

    def guardar_correos_pendientes(self):
        if not getattr(self, 'correos_pendientes', []):
            return True
        with self.bloqueo_correos:
            self.ultimo_guardado_correos = time.monotonic()
            while self.correos_pendientes:
                try:
                    marcar_usado(*self.correos_pendientes[0])
                except OSError:
                    if not self.aviso_guardado_pendiente:
                        self.emit('⚠ No pude guardar el historial de correos. El correo queda reservado '
                                  'en esta sesión; continuaré con el PIN y reintentaré guardar.')
                        self.aviso_guardado_pendiente = True
                    return False
                self.correos_pendientes.pop(0)
            if self.aviso_guardado_pendiente:
                self.emit('✔ Historial de correos guardado. Ya no hay registros pendientes.')
                self.aviso_guardado_pendiente = False
        return True

    def refrescar_correos(self):
        d = len(self.disponibles())
        self.info_correos.configure(text=f'{len(self.correos)} cargados · {d} disponibles')

    def foto(self, path, idx, nombre_archivo):
        adb(path, idx, 'shell', 'screencap', '-p', '/sdcard/c.png')
        destino = CARPETA / 'capturas'
        destino.mkdir(parents=True, exist_ok=True)
        adb(path, idx, 'pull', '/sdcard/c.png', str(destino / nombre_archivo))
        return destino / nombre_archivo

    def consulta(self):
        path = self.ruta()
        curp = self.curp.get().strip().upper()
        if not path:
            return
        if not re.fullmatch(r'[A-Z]{4}\d{6}[HM][A-Z]{5}[A-Z0-9]\d', curp):
            messagebox.showerror('Gestoría Díaz', 'La CURP no tiene un formato válido (18 caracteres).')
            return
        libres = self.disponibles()
        if not libres:
            messagebox.showerror('Gestoría Díaz', 'No hay correos disponibles. Carga un TXT con un correo por línea.')
            return
        self.btn_consulta.configure(state='disabled')
        self.btn_codigo.configure(state='disabled')
        threading.Thread(target=self._consulta,
                         args=(path, curp, libres[0], self.inst_sel.get(), self.tramite.get()),
                         daemon=True).start()

    def _consulta(self, path, curp, correo, nombre, tramite):
        try:
            info = listar(path).get(nombre)
            if not info or not info['android']:
                self.emit(f'⚠ {nombre} no está encendida')
                return
            idx = info['index']
            if 'OK' not in adb(path, idx, 'shell', 'echo', 'OK', timeout=15):
                self.emit(f'✖ {nombre}: sin conexión ADB (reiníciala para que tome la depuración ADB)')
                return
            self.emit(f'🔎 {nombre}: {tramite} · {curp} · {correo}')
            abrir_app(path, nombre, idx)
            nodos = []
            for _ in range(12):
                time.sleep(2)
                nodos = pantalla(path, idx)
                txt = todo_texto(nodos)
                if 'permiso de ubicaci' in txt:
                    tocar_texto(path, idx, r'^cancelar$', 0)
                    continue
                if buscar(nodos, 'txtCURP'):
                    break
                if 'cerrar sesión' in txt or 'tramita' in txt:
                    self.emit(f'⚠ {nombre}: ya hay una sesión abierta en IMSS. Usa "Cerrar sesión IMSS" primero.')
                    return
            else:
                self.emit(f'⚠ {nombre}: no encontré la pantalla "Inicia sesión" (¿está desbloqueada?)')
                return
            escribir(path, idx, buscar(nodos, 'txtCURP')['xy'], curp)
            escribir(path, idx, buscar(nodos, 'txtCorreo')['xy'], correo)
            adb(path, idx, 'shell', 'input', 'keyevent', 'KEYCODE_BACK')   # cerrar teclado
            time.sleep(1)
            nodos = pantalla(path, idx)
            if not buscar(nodos, 'txtCURP'):
                self.emit(f'⚠ {nombre}: se salió de la pantalla al cerrar el teclado; intenta de nuevo')
                return
            btn = buscar(nodos, 'btnIniciar')
            if btn and not btn['enabled']:
                tocar(path, idx, CHECK_AVISO)                 # "He leído y acepto"
                nodos = pantalla(path, idx)
                btn = buscar(nodos, 'btnIniciar')
            if not btn or not btn['enabled']:
                self.emit(f'⚠ {nombre}: INICIAR SESIÓN sigue desactivado; revisa CURP/correo')
                return
            tocar(path, idx, btn['xy'])                       # INICIAR SESIÓN
            self.registrar_correo(curp, correo, nombre, tramite)
            self.root.after(0, self.refrescar_correos)

            # Validación de identidad (PIN) -> confirmar correo -> pantalla de código
            pin_enviado = False
            aviso_pin_manual = False
            for _ in range(30):
                time.sleep(2)
                nodos = pantalla(path, idx)
                txt = todo_texto([n for n in nodos if n.get('visible', True) and n.get('area', 0) > 0])
                if 'código de validación' in txt or 'codigo de validacion' in txt:
                    self.pendiente = (path, idx, nombre, curp, correo, tramite)
                    self.events.put(('aviso', f'📧 {nombre}: pega el código que llegó a {correo}'))
                    self.emit(f'📧 Esperando código. IMSS lo mandó a {correo}')
                    self.root.after(0, lambda: self.btn_codigo.configure(state='normal'))
                    return
                if re.search(r'(?:validaci[oó]n|verificaci[oó]n) de identidad|confirma tu identidad|'
                             r'(?:ingresa|introduce) (?:tu |el )?pin', txt):
                    if 'incorrect' in txt or 'demasiados intentos' in txt:
                        self.emit('⚠ Android no aceptó el PIN. Revísalo en la instancia; no lo volveré a enviar.')
                        return
                    if not pin_enviado:
                        pin_enviado = enviar_pin_identidad(path, idx, nodos, PIN_EMULADOR)
                        if pin_enviado:
                            self.emit('🔑 Validación de identidad: PIN enviado')
                            time.sleep(2)
                        elif not aviso_pin_manual:
                            self.emit('⚠ No encontré un campo o teclado de PIN visible. '
                                      'Introduce el PIN en la instancia; seguiré esperando el código.')
                            aviso_pin_manual = True
                    continue
                if 'confirmado tu correo' in txt:
                    tocar_texto(path, idx, r'^confirmar$', 0)
                    continue
                if 'error' in txt or 'no existe' in txt or 'incorrect' in txt:
                    foto = self.foto(path, idx, f'error_{curp}.png')
                    self.emit(f'✖ IMSS respondió: {txt[:160]}  (captura: {foto.name})')
                    return
            foto = self.foto(path, idx, f'atorado_{curp}.png')
            self.emit(f'⚠ No llegué a la pantalla del código. Captura: {foto.name}')
        except Exception as exc:
            self.emit(f'ERROR en consulta: {exc}')
        finally:
            self.root.after(0, lambda: self.btn_consulta.configure(state='normal'))

    def enviar_codigo(self):
        codigo = re.sub(r'\D', '', self.codigo.get())
        if len(codigo) != 6:
            messagebox.showerror('Gestoría Díaz', 'El código debe tener 6 dígitos.')
            return
        if not self.pendiente:
            messagebox.showerror('Gestoría Díaz', 'Primero presiona 1. INICIAR.')
            return
        self.btn_codigo.configure(state='disabled')
        threading.Thread(target=self._codigo, args=(codigo, *self.pendiente), daemon=True).start()

    def meter_codigo(self, path, idx, codigo):
        """Escribe solo en las casillas de validación y confirma los seis dígitos."""
        if not isinstance(codigo, str) or not re.fullmatch(r'[0-9]{6}', codigo):
            return False
        for intento in (1, 2):
            nodos = pantalla(path, idx)
            cajas = cajas_codigo_validacion(nodos)
            if not cajas:
                self.emit('⚠ No identifiqué las casillas del código de validación.')
                break
            if codigo_escrito(cajas) == codigo:
                return True
            cantidad = len(cajas)
            # Borrar desde la derecha, SOLO si hay contenido. DEL sobre una casilla
            # vacía puede retroceder a la anterior y borrar otro dígito.
            for pos in reversed(range(cantidad)):
                if not cajas[pos].get('valor', cajas[pos].get('texto', '')):
                    continue
                cajas = cajas_codigo_validacion(pantalla(path, idx))
                if len(cajas) != cantidad:
                    return False
                caja = cajas[pos]
                valor = caja.get('valor', caja.get('texto', ''))
                if not valor:
                    continue
                tocar(path, idx, caja['xy'])
                adb(path, idx, 'shell', 'input', 'keyevent', 'KEYCODE_MOVE_END')
                adb(path, idx, 'shell', 'input', 'keyevent',
                    *(['KEYCODE_DEL'] * min(len(valor), 6 if cantidad == 1 else 1)))
            for pos, digito in enumerate(codigo):
                cajas = cajas_codigo_validacion(pantalla(path, idx))
                if len(cajas) != cantidad:
                    return False
                if cantidad == 6 or pos == 0:
                    tocar(path, idx, cajas[pos if cantidad == 6 else 0]['xy'])
                adb(path, idx, 'shell', 'input', 'keyevent', 'KEYCODE_' + digito)
                time.sleep(.3)
            time.sleep(.6)
            cajas = cajas_codigo_validacion(pantalla(path, idx))
            if len(cajas) == cantidad and codigo_escrito(cajas) == codigo:
                return True
            if intento == 1:
                self.emit('⚠ El código no quedó completo. Voy a limpiar las casillas y repetirlo una vez.')
        self.foto(path, idx, 'codigo_incompleto.png')
        return False

    def _codigo(self, codigo, path, idx, nombre, curp, correo, tramite):
        try:
            if not self.meter_codigo(path, idx, codigo):
                self.emit('✖ No pude escribir los 6 dígitos. Revisa la captura y vuelve a enviarlo.')
                return
            nodos = [n for n in pantalla(path, idx) if n.get('visible', True) and n.get('area', 0) > 0]
            botones = [n for n in nodos if n.get('enabled') and any(
                re.fullmatch(r'(?i)(verificar|validar)', etiqueta.strip())
                for etiqueta in (n.get('valor', ''), n.get('descripcion', ''), n.get('texto', '')))]
            if not botones:
                self.emit('⚠ Verificar sigue desactivado o no está visible. Revisa las seis casillas y vuelve a enviar.')
                return
            boton = min(botones, key=lambda n: n['area'])
            tocar(path, idx, boton['xy'])
            self.emit('➡ Seis dígitos comprobados; pulsé Verificar')
            confirmado = False
            for _ in range(10):
                time.sleep(2)
                nodos = [n for n in pantalla(path, idx) if n.get('visible', True) and n.get('area', 0) > 0]
                txt = todo_texto(nodos)
                if re.search(r'error al validar|c[oó]digo (?:incorrecto|inv[aá]lido|expirado|vencido)', txt):
                    self.emit('✖ Error al validar el código. Usa el correo MÁS RECIENTE y vuelve a enviarlo.')
                    return
                if 'ha sido confirmado' in txt:
                    aceptar = buscar_texto(nodos, r'^aceptar$')
                    if aceptar and aceptar.get('enabled'):
                        tocar(path, idx, aceptar['xy'])
                    self.emit('✅ Correo confirmado')
                    confirmado = True
                    break
                en_codigo = bool(re.search(r'c[oó]digo de (?:validaci[oó]n|verificaci[oó]n)', txt)
                                 or cajas_codigo_validacion(nodos))
                if not en_codigo and ('tramita' in txt or 'cita médica' in txt or 'vigencia' in txt):
                    confirmado = True
                    break
            if not confirmado:
                self.emit('⚠ IMSS todavía no confirma el código. Revisa la pantalla antes de volver a enviarlo.')
                return
            time.sleep(2)
            self.pendiente = None
            self.events.put(('aviso', f'⚙ {nombre}: haciendo {tramite}...'))
            self.hacer_tramite(path, idx, nombre, curp, tramite)
        except Exception as exc:
            self.emit(f'ERROR con el código: {exc}')
        finally:
            if self.pendiente is not None:
                self.root.after(0, lambda: self.btn_codigo.configure(state='normal'))

    def hacer_tramite(self, path, idx, nombre, curp, tramite):
        encontrado = tocar_texto(path, idx, TRAMITES[tramite], 5)
        if not encontrado:                       # p. ej. NSS está dentro del menú > Tramita
            nodos = pantalla(path, idx)
            menu = buscar_texto(nodos, r'(men[uú]|navigate|abrir)')
            tocar(path, idx, menu['xy'] if menu else (45, 70))
            if tocar_texto(path, idx, r'^tramita$', 0):
                time.sleep(2)
                encontrado = tocar_texto(path, idx, TRAMITES[tramite], 4)
        if not encontrado:
            foto = self.foto(path, idx, f'sin_tramite_{curp}.png')
            self.emit(f'⚠ No encontré el botón de "{tramite}". Captura: {foto.name}')
            return
        # seguir dando CONTINUAR / ENVIAR A TU CORREO hasta que IMSS confirme
        for _ in range(6):
            time.sleep(3)
            nodos = pantalla(path, idx)
            txt = todo_texto(nodos)
            if txt:
                self.emit(f'   IMSS: {txt[:180]}')
            boton = (buscar_texto(nodos, r'enviar a tu correo') or buscar_texto(nodos, r'^continuar$')
                     or buscar_texto(nodos, r'^aceptar$'))
            if boton:
                tocar(path, idx, boton['xy'])
                continue
            break
        time.sleep(2)
        txt = todo_texto(pantalla(path, idx))
        foto = self.foto(path, idx, f'{curp}_{CORTO.get(tramite, "tramite")}.png')
        self.emit(f'📨 {tramite} terminado para {curp}. IMSS lo manda al correo. Captura: {foto.name}')
        self.emit(f'   Pantalla: {txt[:200]}')
        self.events.put(('aviso', f'📨 Listo: revisa el correo para descargar {tramite}'))

    def cerrar_sesion(self):
        path = self.ruta()
        if path:
            threading.Thread(target=self._cerrar, args=(path, self.inst_sel.get()), daemon=True).start()

    def _cerrar(self, path, nombre):
        info = listar(path).get(nombre)
        if not info:
            return
        idx = info['index']
        adb(path, idx, 'shell', 'input', 'keyevent', 'KEYCODE_BACK')
        time.sleep(1)
        abrir_app(path, nombre, idx)
        time.sleep(3)
        nodos = pantalla(path, idx)
        menu = buscar_texto(nodos, r'(men[uú]|navigate|abrir)')
        tocar(path, idx, menu['xy'] if menu else (45, 70))
        time.sleep(1)
        if tocar_texto(path, idx, r'cerrar sesi[oó]n', 1):
            time.sleep(1.5)
            tocar_texto(path, idx, r'^(aceptar|s[ií]|cerrar sesi[oó]n)$', 0)
            self.emit(f'🚪 {nombre}: sesión de IMSS cerrada')
        else:
            foto = self.foto(path, idx, 'cerrar_sesion.png')
            self.emit(f'⚠ {nombre}: no encontré "Cerrar sesión". Captura: {foto.name}')

    # ---------- monitor
    def olvidar(self, n):
        """Borra todo lo que el bot recordaba de una instancia (se eliminó, se apagó o es nueva)."""
        for d in (self.bloqueada, self.arranque, self.enviados, self.sesion,
                  self.ultimo_abrir, self.intentos_pin):
            d.pop(n, None)

    def abrir_imss(self, path, n, idx, motivo=''):
        abrir_app(path, n, idx)
        self.ultimo_abrir[n] = time.time()
        self.estado(n, '📱 IMSS Digital abierto', VERDE)
        if motivo:
            self.emit(f'📱 {n}: {motivo} → abrí IMSS Digital')

    def monitor(self):
        """Tras pulsar preparar, vigila solo las instancias elegidas, desbloquea
        Android con el PIN configurado y abre IMSS Digital al confirmar el desbloqueo."""
        while True:
            time.sleep(2)
            if not self.iniciado:
                continue
            nombres = self.nombres
            path = self.ruta()
            if not path:
                continue
            try:
                inst = listar(path)
            except Exception:
                continue
            if not inst:
                continue                       # ldconsole no respondió; no asumir que se borraron
            if not self.iniciado or nombres != self.nombres:
                continue
            faltan = [n for n in nombres if n not in inst]
            for n in faltan:
                self.olvidar(n)
            if faltan and self.auto_on and not self.busy and time.time() - self.ultimo_auto > 90:
                self.ultimo_auto = time.time()
                self.emit('♻ Faltan ' + ', '.join(faltan) + ': las creo de nuevo desde la plantilla')
                self.root.after(0, self.start)
                continue
            for n in nombres:
                if not self.iniciado or nombres != self.nombres:
                    break
                try:
                    self.vigilar(path, n, inst.get(n))
                except Exception as exc:
                    self.emit(f'⚠ monitor {n}: {exc}')

    def ocupada(self, n):
        """True si el bot está haciendo algo con esa instancia (no pisar su etiqueta)."""
        texto = self.filas[n][2].cget('text')
        return self.busy and texto in ('Copiando plantilla...', 'Encendiendo...', 'Eliminando...')

    def vigilar(self, path, n, i):
        if not i:
            if not self.ocupada(n):
                self.estado(n, 'No existe', ROJO)
            return
        if not i['running'] or not i['android']:
            if not self.ocupada(n):
                self.estado(n, 'Apagada' if not i['running'] else 'Arrancando...',
                            ROJO if not i['running'] else AMARILLO)
            self.olvidar(n)
            return
        idx = i['index']
        # (índice, pid) cambia si la instancia se reemplazó o se reinició, aunque LDPlayer
        # reutilice el mismo índice. Entonces se vigila como si fuera la primera vez.
        clave = (idx, i['pid'])
        if self.sesion.get(n) != clave:
            self.olvidar(n)
            self.sesion[n] = clave
        t0 = self.arranque.setdefault(n, time.time())
        out = adb(path, idx, 'shell', 'dumpsys', 'window', timeout=10)
        if not out or 'not found' in out or 'offline' in out or out.lower().startswith('error'):
            # sin ADB: mandar IMSS a los 15, 45, 90 y 150 s de arrancar
            hechos = self.enviados.get(n, 0)
            if hechos < 4 and time.time() - t0 >= (15, 45, 90, 150)[hechos]:
                run(path, 'runapp', '--index', idx, '--packagename', PACKAGE, timeout=40)
                self.enviados[n] = hechos + 1
            self.estado(n, 'Encendida (sin ADB)', AMARILLO)
            return
        ahora = estado_bloqueo_android(out)
        if ahora is None:
            self.estado(n, 'Comprobando bloqueo de Android...', AMARILLO)
            return
        antes = self.bloqueada.get(n)
        self.bloqueada[n] = ahora
        if ahora:
            if n in self.intentos_pin:
                self.estado(n, '🔒 Revisa el PIN o desbloquea manualmente', AMARILLO)
                return
            self.desbloqueando = True
            try:
                # La selección pudo cambiar mientras respondía dumpsys.
                if not self.iniciado or n not in self.nombres:
                    return
                # Registrar ANTES de escribir para no repetir el PIN cada dos segundos.
                self.intentos_pin[n] = clave
                self.estado(n, '🔑 Desbloqueando con el PIN configurado...', AMARILLO)
                resultado = desbloquear_android(path, idx, PIN_EMULADOR)
                if resultado is None:
                    # ADB cambió de estado antes de escribir: aún no se gastó un intento.
                    self.intentos_pin.pop(n, None)
                    self.estado(n, 'Esperando confirmar el bloqueo de Android...', AMARILLO)
                    return
                if not resultado:
                    self.estado(n, '🔒 Revisa el PIN o desbloquea manualmente', AMARILLO)
                    self.emit(f'⚠ {n}: no pude confirmar el desbloqueo; no repetiré el PIN automáticamente.')
                    return
                self.bloqueada[n] = False
                self.intentos_pin.pop(n, None)
                self.emit(f'🔓 {n}: Android desbloqueado')
                self.abrir_imss(path, n, idx, 'PIN aceptado')
            finally:
                self.desbloqueando = False
            return
        self.intentos_pin.pop(n, None)
        foco = re.search(r'mCurrentFocus=.*', out)
        foco = foco.group(0).lower() if foco else ''
        if antes is None or antes:
            # se acaba de desbloquear, o es la primera vez que el bot la ve desbloqueada
            self.abrir_imss(path, n, idx, 'desbloqueada' if antes else 'instancia lista')
        elif 'launcher' in foco and time.time() - self.ultimo_abrir.get(n, 0) > 8:
            # quedó en la pantalla de inicio (sin ninguna app): IMSS de vuelta
            self.abrir_imss(path, n, idx, 'quedó en la pantalla de inicio')
        else:
            c, f, est = self.filas[n]
            if 'IMSS' not in est.cget('text'):
                self.estado(n, '📱 IMSS Digital abierto', VERDE)


if __name__ == '__main__':
    root = tk.Tk()
    App(root)
    root.mainloop()
