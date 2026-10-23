# Gestoría Díaz — Outlook V14.2

[Descargar el ZIP de Outlook V14.2](https://github.com/jorgezagal2zagal-ui/gestoria-diaz/raw/refs/heads/outlook-v14.2-descarga/GESTORIA_DIAZ_OUTLOOK_V14_2_CONTRASENA_COMUN.zip)

Extrae el ZIP en una carpeta nueva. En Windows ejecuta `OUTLOOK/INSTALAR.bat` y
luego `OUTLOOK/ABRIR_OUTLOOK.bat`.

Para guardar una contraseña común, escríbela una vez en el panel y pulsa
**GUARDAR PARA TODOS**. Se conserva con DPAPI del usuario de Windows y se usa para
los correos actuales y futuros. El paquete no contiene contraseñas incorporadas.

Incluye dos reintentos automáticos (5 y 10 segundos) cuando Microsoft muestra que
el inicio con contraseña no está disponible, con la misma cuenta y contexto.

Validación: 72 pruebas locales, además de comprobaciones de cola, migración y enlace
HTTP local. El reintento de navegador se comprobó con HTML sintético en Chromium.
Pendiente verificar el panel, DPAPI nativo y cuentas reales en Windows.

SHA-256 del ZIP: `46c661f503187a1bed139c3bf2d2b07bb6a21f116b4beb06599e5f00f0210c29`.
