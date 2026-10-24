# -*- coding: utf-8 -*-
"""Arrange four separate, live, native Chrome windows once at launch.
No polling of pixels or capture/mirroring is used. Chrome windows stay movable.
"""
import os

def screen_dimensions():
    if os.name=='nt':
        try:
            import ctypes
            user32=ctypes.windll.user32
            width=int(user32.GetSystemMetrics(0))
            height=int(user32.GetSystemMetrics(1))
            if width>=800 and height>=600:return width,height
        except Exception:pass
    return 1366,768

def tile_geometry(slot, screen=None):
    slot=int(slot)
    if slot not in (1,2,3,4):raise ValueError('Slot de Outlook no válido')
    sw,sh=screen or screen_dimensions()
    gap=12
    # Reserve the taskbar and enough room for four windows on a typical monitor.
    w=max(385,min(550,(sw-3*gap)//2))
    h=max(310,min(495,(sh-80-3*gap)//2))
    col=(slot-1)%2
    row=(slot-1)//2
    x=gap+col*(w+gap)
    y=gap+row*(h+gap)
    return (x,y,w,h)

def chrome_window_args(geometry):
    x,y,w,h=geometry
    return [f'--window-size={w},{h}',f'--window-position={x},{y}']
