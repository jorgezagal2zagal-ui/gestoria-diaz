# Gestoría Díaz — Outlook V45 + IMSS V32 para LDPlayer

Esta entrega reutiliza los dos ZIP que proporcionaste. IMSS es la versión de
**LDPlayer por ADB local**, no la versión para teléfonos físicos. El archivo
`IMSS/gestoria_prueba_v7.py`, que localiza ADB, detecta transportes y abre IMSS,
se conserva exactamente igual al original.

## Instalar en Windows

1. Termina o cancela tus solicitudes anteriores y cierra los bots antiguos.
   Conserva sus carpetas. Extrae este ZIP en **una carpeta nueva**, fuera de
   OneDrive si bloquea archivos o bases de datos.
2. Instala Python **3.12 de 64 bits con Tcl/Tk**, preferentemente desde python.org.
   No necesitas compilar un `.exe`: los lanzadores de esta entrega son `.pyw`.
3. Ejecuta `INSTALAR_WINDOWS.bat`. Crea `.venv`, instala las dependencias con
   las versiones del paquete original, prepara Chromium si falta y ejecuta las
   pruebas locales. Chrome o Edge instalados pueden servir como alternativa.
4. En LDPlayer, inicia las instancias que vayas a utilizar y habilita su conexión
   ADB local. IMSS Digital debe estar instalado y en una sesión que puedas usar.
   Se conservan el descubrimiento ADB y los puertos locales originales; **no
   configures Wi-Fi ni conectes teléfonos**. Se admiten hasta cuatro instancias
   disponibles, sin contar dos veces los alias del mismo emulador.
5. Abre `GESTORIA_DIAZ.pyw`. También puedes usar `ABRIR_OUTLOOK.pyw` y después
   `ABRIR_IMSS_LDPLAYER.pyw`. No ejecutes los archivos antiguos de las subcarpetas.

El lanzador guarda copias SQLite coherentes de los datos compartidos existentes
antes de iniciar cada panel, en `%LOCALAPPDATA%\GestoriaDiaz\RespaldosIntegracion`.
Estos respaldos pertenecen a tu PC y pueden contener datos personales y
contraseñas cifradas con DPAPI: consérvalos allí; no los subas al repositorio.
Los dos ZIP originales proporcionados también están en `RESPALDOS_ORIGINALES`.

## Un trámite autorizado, hasta el código

1. En Outlook, importa tu TXT mediante la función existente. Ambos bots utilizan
   la misma lista SQLite bajo el mismo usuario Windows y equipo. No envíes tu
   TXT de contraseñas por chat ni lo copies dentro de este paquete.
2. Revisa el **remitente exacto** del mensaje real de verificación IMSS. Se
   conserva el valor predeterminado del programa original; corrígelo en la
   configuración si tu mensaje procede de otra dirección verificada.
3. En IMSS, pulsa **DETECTAR LDPLAYER POR ADB**. Este botón verifica la conexión
   sin abrir IMSS ni introducir datos todavía. Si no encuentra `adb.exe`, usa la
   opción original para elegir la carpeta de instalación de LDPlayer.
4. Agrega una CURP cuyo titular autorizó el trámite. Outlook prepara primero el
   correo reservado para ese canal. La reserva permanece asociada al mismo folio.
5. El programa exige una bandeja de entrada visible y que el control de perfil
   de Outlook muestre la cuenta esperada. Si la interfaz oculta la dirección,
   abre el perfil de Outlook para hacerla visible. Mientras no pueda comprobarla,
   IMSS espera y no empieza sobre otra cuenta.
6. Si Microsoft solicita MFA, CAPTCHA, PIN de acceso u otra comprobación,
   completa el paso **manualmente en Chrome**. Se conserva la ventana y el folio;
   el bot no cambia de cuenta para evitar la verificación. Los bloqueos y HTTP
   429 detienen los accesos automáticos. Las ofertas voluntarias de crear una
   llave de acceso y de mantener la sesión iniciada se rechazan con los
   controles existentes; no se cancela una autenticación obligatoria.
7. Con Outlook listo, IMSS abre la aplicación usando el ADB original, comprueba
   CURP y correo y solicita el código. El enlace fija el inicio de la solicitud
   **justo antes del envío del formulario**, no al abrir Outlook. Después IMSS
   comprueba que está en la pantalla del código y notifica al canal Outlook.
8. Outlook admite sólo un mensaje del remitente exacto, con fecha real y zona
   horaria posterior al envío, contexto de verificación y un único código de seis
   dígitos. No inventa la fecha ni toma un correo antiguo por ser el primero.
   Si Outlook no expone remitente/fecha de manera comprobable, no se envía un
   código automáticamente; debes revisar el mensaje. El respaldo de entrega
   manual original sigue disponible con confirmación del operador.
9. IMSS escribe el código **una sola vez**, conservando ceros iniciales, sólo
   en campos vacíos identificados y en el correo/emulador del folio. Puede pulsar
   un único botón explícito `Verificar`. No utiliza posiciones estimadas para
   campos de código que Android no exponga.
10. Un texto positivo explícito de IMSS, como `Código verificado`, confirma la
    aceptación. Si la aplicación sólo cambia de pantalla, queda en `REVISAR`:
    no se afirma que el código fue aceptado. Una interfaz que use otro mensaje
    de aceptación necesitará adaptar el detector después de observarla en tu PC.

**FIN:** el emulador queda retenido al confirmar el código. No se pulsa
continuar/vincular, no se genera PDF, no se vuelve al inicio y no se repite el
trámite automáticamente. Los botones heredados de recuperación/finalización
no ejecutan esos pasos en el panel integrado. Los demás canales corresponden
a folios independientes. Empieza probando con una sola cuenta y un solo LDPlayer.

## Estados, registros y cierre

- Los paneles muestran `OCUPADO`, pausa manual, `REVISAR` y `CODIGO CONFIRMADO FIN`.
- El enlace es HTTP autenticado con clave local, exclusivamente en `127.0.0.1`,
  puertos 8797–8800. No expongas estos puertos en Internet ni desactives el firewall.
  Requiere el mismo usuario Windows; no pretende aislarse de programas maliciosos
  ejecutados como ese mismo usuario.
- No se registran contraseñas ni códigos; sólo eventos y tipos de fallo. El
  código se elimina del estado del enlace al confirmar recepción o cancelar y
  caduca al consultar una solicitud vencida.
- El diagnóstico Outlook está en `%LOCALAPPDATA%\GestoriaDiaz\DiagnosticosV36`.
  IMSS conserva su panel de registros y los mensajes omiten datos del trámite.
- Un reinicio, escritura parcial o falta de confirmación no provocan un nuevo
  envío automático. Revisa los folios y la pantalla antes de cerrar o cambiar de
  versión. Esta entrega no incluye un nuevo flujo de reutilización tras FIN.

## Verificación y límites

Ejecuta `PRUEBAS_WINDOWS.bat`, o `python ejecutar_pruebas.py` con las dependencias.
Las pruebas usan datos sintéticos y estado temporal. La comunicación se comprueba
con cuatro servidores Outlook en procesos separados y un cliente IMSS, usando
HTTP real y ADB simulado. `INFORME_PRUEBAS.md` detalla los resultados.

**No se ejecutaron Windows/Tk, DPAPI nativo, Microsoft real, LDPlayer ni IMSS
real en este entorno Linux.** Por eso se entrega una implementación comprobada
localmente para validación en tu PC, sin prometer un trámite real exitoso. La
disponibilidad de los paquetes Windows se comprobó por descarga, sin ejecutarlos.
No se generó ni firmó un `.exe`.

Las pruebas históricas V12 y V13 de IMSS se conservan sin alterarlas. Ya fallaban
en los originales por esperar tres instancias y por comparar transportes de
distintas versiones. Para verlas: `python ejecutar_pruebas.py --historicas`;
sus fallos se informan como fallos, no como pruebas superadas.
