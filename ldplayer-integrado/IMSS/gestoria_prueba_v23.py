# -*- coding: utf-8 -*-
"""Selector para cuatro LDPlayer. Importa el núcleo ADB V7 SIN modificarlo."""
from gestoria_prueba_v7 import index_of_serial

MAX_ANDROID = 4

def select_serials(devices):
    """Prioriza serial emulator-*; evita contar alias del mismo emulador dos veces."""
    grouped = {}
    for serial, state in devices.items():
        idx = index_of_serial(serial)
        if idx is not None and state == 'device':
            grouped.setdefault(idx, []).append(serial)
    return [(idx, sorted(names, key=lambda s: (not s.startswith('emulator-'), s))[0])
            for idx, names in sorted(grouped.items())][:MAX_ANDROID]
