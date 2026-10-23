# Gestoría Díaz — Outlook automático V15.2

Esta versión corrige el bloqueo `PermissionError: [WinError 32]` al eliminar
`vault.sqlite3` durante las pruebas de instalación. El almacén de contraseñas,
la cola y las pruebas de migración cierran ahora sus conexiones SQLite al terminar,
también cuando hay errores. Las operaciones fallidas siguen revirtiendo sus cambios.

## Abrir el programa

1. Cierra las versiones anteriores y extrae este ZIP en una carpeta nueva.
2. Ejecuta `OUTLOOK/ABRIR_OUTLOOK.bat`. Si falta el entorno, prepara las dependencias.
3. Se prepara Chromium antes de abrir el panel. Si no se puede descargar, se intenta Chrome o Edge instalado.
4. Con una cuenta elegida y su contraseña guardada, el acceso comienza automáticamente.
   El botón **INICIAR** también ejecuta el flujo completo; no hace falta abrir la bandeja aparte.

Se necesita Windows y Python 3.12 o posterior de 64 bits. Se recomienda Python 3.12:
las 17 dependencias fijadas se resolvieron y descargaron para esa versión de Windows.
El BAT y DPAPI nativo no se ejecutaron en Linux.
Si el lanzador `py` encuentra Python 3.12 de 64 bits, el instalador lo prefiere.
De lo contrario usa el Python disponible de 64 bits, versión 3.12 o posterior.
El fallo de SQLite corregido también podía ocurrir con Python 3.12; la selección
de versión y la liberación del archivo son correcciones independientes.

## Pantalla principal

- **INICIAR:** abre el navegador privado, introduce el correo y la contraseña guardada y abre Outlook.
- **DETENER:** detiene el acceso y desactiva el arranque automático hasta volver a pulsar INICIAR.
- **IMPORTAR TXT:** importa y marca las cuentas del archivo; no abre todas simultáneamente.
- **CUENTAS:** elige qué cuenta o cuentas pueden utilizarse.
- **COPIAR CORREO** y **AJUSTES** son los únicos controles secundarios.

El estado del navegador, los errores y la pausa quedan siempre visibles.
Los controles de lectura opcional, remitente, envío manual y diagnóstico están en **AJUSTES**.

## Contraseña y cuentas

En **AJUSTES > Contraseña**, escribe una vez tu contraseña común y pulsa **GUARDAR PARA TODOS**.
Se guarda con DPAPI de tu usuario de Windows y se usa para los correos actuales y futuros.
No hay una contraseña incorporada en el ZIP. Las cuentas y claves guardadas anteriormente
se conservan en el mismo directorio de datos del usuario.

La primera ejecución de V15 activa el arranque automático. Una detención posterior se conserva
al volver a abrir el programa. Puedes reactivarlo con INICIAR o desde Ajustes.
Fuera de una solicitud IMSS se abre una sola cuenta elegida por inicio: no recorre la lista al
cerrar el navegador. Una solicitud IMSS solo utiliza su cuenta seleccionada correspondiente.

## Avisos del navegador y sesión abierta

Se usa primero Chromium para reducir las ofertas de perfil de Chrome/Edge. En Windows,
el programa busca las ofertas reconocidas de inicio de sesión o sincronización del navegador
y elige **No, gracias**, **Ahora no** o **Cancelar**, según el botón que ofrezcan.
Solo actúa sobre ventanas nativas del navegador abierto por este programa, con título y
contenido reconocidos. Si el aviso tiene otro diseño y no se reconoce, puedes rechazarlo manualmente.

El cuadro de **Seguridad de Windows > Guardar la clave de paso** es una operación diferente.
El programa conserva esa ventana para que decidas. Después de resolverla, el acceso puede continuar.
Los errores temporales de lectura y automatización conservan la pestaña y el lector del correo;
la sesión termina al pulsar DETENER, cerrar el programa o cerrar/perder el navegador.

## Entrega al otro bot

El enlace sigue activo en **127.0.0.1:8797**. El bot IMSS debe ejecutarse en el mismo equipo
y usuario, e implementar el protocolo de `enlace.py`. Este ZIP contiene el bot Outlook;
el otro bot no está incluido y no se comprobó su aplicación real en esta versión.

Una solicitud del bot IMSS puede reservar la cuenta seleccionada que ya tiene Outlook abierto,
sin abrir otra cuenta. En **AJUSTES**, configura una vez el remitente exacto del correo IMSS.
Con la solicitud activa, el lector exige remitente y fecha comprobables y un único código de seis dígitos.
El panel diferencia **código disponible** de **recepción confirmada por IMSS**. Si falla la entrega
local, el código permanece temporalmente en memoria para la misma solicitud; no se guarda en disco.

## Pausa y errores

El enfriamiento entre sesiones es de **30 segundos**. Un error antes de crear la pestaña
no marca la cuenta como usada ni impone una pausa ficticia. Los errores de arranque no se
ocultan con el mensaje de cierre. Edge, Chrome y Chromium se prueban con tiempos limitados.

Se conservan los dos reintentos (5 y 10 segundos) del aviso «inicio de sesión con contraseña
no disponible». No se repite indefinidamente. Microsoft 429 mantiene detenido el acceso;
la pausa de 30 segundos no levanta ese bloqueo. Las verificaciones de identidad que pida
Microsoft deben completarse en su propia página.

## Validación

- `python validar.py` / `PRUEBAS.bat`: 110 pruebas unittest más cola, migración y enlace HTTP local.
- `python -m unittest tests_recursos_sqlite -v`: cuatro regresiones con conexiones
  reales retenidas; comprueban cierre inmediato, eliminación del archivo y rollback.
- `python PROBAR_SESION_ENLACE.py`: navegador y enlace HTTP reales con páginas y código ficticios;
  comprueba conservación de sesión, recuperación de errores, entrega, confirmación y otra reserva.
- `python PROBAR_INTERFAZ_V15.py --mode auto`: panel Tk real, navegador visible y páginas ficticias.
- `python PROBAR_INTERFAZ_V15.py --mode button`: mismo recorrido mediante el botón INICIAR.
- En Linux con un escritorio y Chromium del sistema, agrega `--chromium /usr/bin/chromium`.

Se comprobaron ambos recorridos, el cierre/reintento, la contraseña común, la apertura
automática de la bandeja después del acceso y DETENER. Ninguna prueba utilizó cuentas reales.
Pendiente comprobar el BAT, DPAPI nativo, el botón nativo de Chrome/Edge y una cuenta Microsoft real.
El rechazo de avisos nativos se probó con controles simulados; necesita validación en Windows.
Los documentos V12/V13/V14 y el informe técnico incluido son antecedentes de versiones anteriores.
