# Diagnóstico y alcance de los cambios

> Informe histórico recibido con V14. Incluye referencias a un paquete IMSS separado
> que no forma parte de esta descarga. Para el alcance y la evidencia de V15.2,
> consulta README_PRIMERO.md y RESULTADOS_PRUEBAS.json.

## Bases y preservación

IMSS parte de GESTORIA_DIAZ_IMSS_WIFI_IDENTIDAD_CORREGIDA_V9.zip, cuyo respaldo
privado conserva SHA-256 db11f9fdef3f3c3e24e379b49b170bd22df026f5adbcceb474eeb6573abbaf32.
Outlook parte del V13 del primer adjunto, no del motor IMSS anterior del coordinador.
El respaldo del primer adjunto conserva SHA-256
f55d10d4560ba843edc6ffb8b237acb31136a32bf4b5d6d6d1458a6da7bf4f98.
Los respaldos originales no se incluyen en las distribuciones.

La navegación y los selectores originales de Outlook se conservan. En IMSS se
conserva la detección de identidad, los flujos de privacidad, el ingreso de datos,
el código, ADB y la navegación; el cambio deliberado en el motor exige autorización
explícita antes de pulsar el cambio de dispositivo. No se reescribió el motor de V9.
Las versiones V10/V14 identifican estos cambios; no equivalen a certificación del servicio.

## Hallazgos y correcciones

- V9 incluía un PIN fijo y lo restablecía al pulsar OLVIDAR/RESTABLECER. Ahora no
  existe PIN distribuido y eliminarlo realmente llama a pin_vault.forget. La carga
  privada nunca inventa un PIN cuando DPAPI falla ni guarda nada durante el arranque.
  La captura de un PIN en memoria ya no implica guardarlo permanentemente.
- V9 pulsaba automáticamente el cambio de dispositivo. El flujo ahora se detiene;
  el panel pide confirmación expresa, lee de nuevo la pantalla y llama al cambio
  autorizado con un bloqueo de repetición independiente de last_action/Reanudar.
- Los temporizadores de IMSS/Outlook podían dejar de programarse tras una excepción.
  Ambos se reprograman en finally; un error de IMSS detiene las acciones del flujo.
- Outlook invocaba funciones Tk desde los hilos de Microsoft/Playwright. Ahora
  publica callbacks en una cola que consume exclusivamente el hilo de interfaz.
  La creación del servicio OAuth y la captura de opciones Tk se realizan en ese hilo.
- Un error al crear el hilo de navegador dejaba running=True. Se restaura el estado
  si el hilo no pudo arrancar. Se conservó la limpieza defensiva del contexto.
- Un código manual podía llegar mientras se producía la vista previa y borrarse su
  señal antes de entrar a espera. Se limpia la señal antes de leer Android; una
  prueba reproduce la respuesta durante la captura y verifica el avance siguiente.
- La configuración Outlook se valida como objeto y se reemplaza atómicamente;
  JSON dañado o con forma incorrecta no causa una caída al abrir.
- El instalador ADB comprueba integridad ZIP, rutas, duplicados, enlaces y límites;
  extrae temporalmente y publica el directorio solo al terminar. No sobrescribe una
  instalación existente. Conserva HTTPS con verificación de certificados. CRC ZIP
  no se presenta como firma criptográfica; no se ejecutaron binarios descargados.
- Los errores ADB dejan de propagar texto bruto de stdout/stderr, que podría
  incluir datos enviados al comando. Los diagnósticos persistentes no incluyen
  mensajes de excepción ni valores de variables.

## Contrato del enlace

Ambos paquetes contienen una copia idéntica y autónoma de enlace.py. Se conserva la
API /v1 para compatibilidad, con reserva y cancelación añadidas. El servidor Outlook
solo se enlaza a 127.0.0.1:8797; usa una clave aleatoria del perfil privado, valida
folios/cuentas, limita cuerpos y tiempo de lectura, y rechaza peticiones con Origin.
La ruta HTTP local evita proxies de Internet del proceso; esto no modifica las rutas
de Microsoft, Git ni otros destinos. No se incluyen códigos ni contraseñas en disco.

El inicio con un mismo identificador es idempotente y no borra códigos ni reinicia
su fecha. Una reserva no sustituye un trámite activo. La asignación de cuentas se
realiza bajo el bloqueo del estado, y exige modo automático autorizado, una sesión
libre, selección y una contraseña guardada. No se reasigna ante un límite Microsoft.
Una cuenta explícita también se verifica contra la sesión Outlook existente.

El cliente IMSS valida folio y correo antes de enviar. Marca el único intento de
escritura antes de ADB: ante un error parcial exige revisión. Si se pierde la respuesta
a la confirmación, repite solo la confirmación y nunca vuelve a introducir el código.
Una entrada manual desactiva la recepción automática para ese intento.

## Cola y recuperación

Los datos se guardan en el perfil, en GestoriaDiaz/IMSSV10. La CURP usa DPAPI y el
identificador de enlace se conserva como metadato. Incluso un folio todavía PENDIENTE
pero con reserva hecha requiere atención tras reiniciar. No se reproduce un trámite
incierto ni se libera el teléfono por suposición. Se conserva el historial cancelado.

La revisión de un folio comprueba su reserva y la cancela únicamente si coincide;
solo entonces permite otro intento. El cambio de correo está restringido a una lectura
reciente de ACCESO. Los folios/CURP nunca se recrean para ese cambio.
DETENER desactiva la cola e invalida preparaciones en curso mediante su generación.

## Evidencia y límites

Las pruebas originales de seguridad, identidad, privacidad y Wi-Fi se mantuvieron.
Se actualizaron las pruebas que exigían el PIN incrustado o el cambio automático:
son requisitos incompatibles con la instrucción actual del usuario, no fallos omitidos.
Los antiguos valores personales usados en fixtures se sustituyeron por ejemplos ficticios.

El informe de ejecución adjunto detalla los conteos actuales. Se ejecutaron pruebas
unitarias, HTTP real en loopback, reservas concurrentes, pérdida de confirmación,
fallo parcial de ADB, cola, reinicios, detención, mensajes de interfaz y ZIP malicioso.
Además, Outlook servidor e IMSS cliente se probaron en procesos separados.
La parte ADB/Windows/Microsoft se simuló; no existe evidencia de integración física.

No se afirma haber corregido la causa real del cierre de Outlook del usuario:
no había un registro del fallo real ni sesión Microsoft/dispositivo disponibles.
La espera de 900 segundos del motor original mantiene la ventana abierta y por sí
misma no explica ese cierre. Los nuevos registros ayudan a aislar su excepción real.

Pendientes: instalación y ventanas Windows, DPAPI nativo, HONOR y cambios de puerto
reales, Microsoft/429 reales, remitente real, finalización IMSS, PDF real e identidad
del documento. Tampoco se ha validado la restauración de una nueva tarea en la nube.

Resultado final: **77 pruebas IMSS + 39 Outlook = 116 pruebas automatizadas superadas**,
más los scripts con aserciones V11/V12/enlace y el intercambio entre procesos separados.
Los paquetes incluyen el JSON de resultados y un manifiesto SHA-256 de sus archivos.
El borrador de nube conserva install_script/start_skill actualizados, sin publicación.
El cliente local rechaza redirecciones para no reenviar la clave a otro destino;
las cabeceras no ASCII fallan con 401 y un servidor sin hilo iniciado se cierra sin bloquear.
