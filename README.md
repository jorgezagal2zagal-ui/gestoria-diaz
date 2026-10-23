# Gestoría Díaz — Outlook V15.2

[Descargar ZIP corregido](https://github.com/jorgezagal2zagal-ui/gestoria-diaz/raw/refs/heads/outlook-v15.2-descarga/GESTORIA_DIAZ_OUTLOOK_V15_2_SQLITE_CORREGIDO.zip)

Cierra la versión anterior, extrae el ZIP en una carpeta nueva y ejecuta `OUTLOOK/ABRIR_OUTLOOK.bat`.
Requiere Windows y Python de 64 bits, versión 3.12 o posterior. El instalador prefiere Python 3.12 si ya está instalado.

V15.2 corrige el `PermissionError: [WinError 32]` sobre `vault.sqlite3` que impedía completar las pruebas de instalación. Las conexiones del almacén de contraseñas, la cola y los ejemplos de migración se cierran al terminar, también tras errores. Las transacciones fallidas revierten sus cambios. La selección de Python 3.15 observada en la captura y la fuga de conexiones son cuestiones independientes.

Cuatro pruebas de regresión con conexiones SQLite reales retenidas fallaban antes de la corrección y pasan después. Pasaron las 110 pruebas locales y la prueba de Chromium/enlace HTTP con mensajes ficticios desde la extracción del ZIP. La ejecución nativa del BAT, DPAPI, los avisos de Chrome/Edge, una cuenta Microsoft real y el bot IMSS/dispositivo real siguen pendientes de comprobación en Windows.

Se conservan los cambios de V15.1: No, gracias/Cancelar en ofertas reconocidas de perfil del navegador, Chromium preferente, conservación de sesión ante errores temporales, reserva de la sesión abierta por el enlace local, interfaz simple y enfriamiento de 30 segundos.

La contraseña común se configura una vez en AJUSTES y se cifra con DPAPI del usuario. Este paquete no incluye contraseñas, cuentas ni códigos reales. El otro bot IMSS no está incluido: debe implementar el enlace local en el mismo equipo y usuario; configura el remitente exacto en AJUSTES.

Detalles y evidencia: [README_PRIMERO.md](OUTLOOK/README_PRIMERO.md), [RESULTADOS_PRUEBAS.json](OUTLOOK/RESULTADOS_PRUEBAS.json).
