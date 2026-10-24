# Reporte de la entrega — Gestoría Díaz LDPlayer

Fecha: 24 de octubre de 2026. Plataforma de pruebas: Linux, Python 3.12.14.
Origen: los ZIP `BOT_IMSS_V32_ESTABLE.zip` y `BOT_OUTLOOK_V45_CORREOS_NUEVOS.zip`
aportados en este chat. No se tomó la aplicación IMSS de teléfonos físicos del
repositorio anterior.

## Problemas encontrados

1. El puente original consideraba superada la verificación simplemente cuando
   desaparecía la pantalla del código. Una lectura vacía, un error o un cambio
   a otra aplicación podían confundirse con aceptación.
2. El lector original incluía rutas que inventaban la fecha de recepción usando
   la hora de la solicitud y una lectura de mensaje abierto sin fecha técnica.
   Una lista previa de mensajes no basta para demostrar que todos los demás
   mensajes son nuevos.
3. El panel heredaba recuperación automática, reapertura de IMSS y reintentos;
   esas funciones entraban en conflicto con detenerse después del código.
4. La preparación registrada en SQLite no probaba que la cuenta siguiera
   visible y lista. Los transportes anteriores tampoco vinculaban el código al
   serial del emulador ni distinguían una solicitud duplicada de una nueva.
5. Ante algunas verificaciones Microsoft, el código anterior apartaba la cuenta
   y cerraba la ventana, en lugar de conservarla para intervención manual.

## Cambios realizados

- Extensiones de Outlook V45 y del panel IMSS V32 existentes; se conservan los
  módulos anteriores y sus funciones de administración de correos.
- Protocolo local nuevo e idéntico en ambos componentes, con clave local,
  rechazo de `Origin`, folio/correo/serial asignados, fases explícitas y rechazo
  de códigos cruzados, reemplazos y reenvíos sobre registros existentes.
- Señal de bandeja reciente, con dirección de la cuenta comprobada en el perfil
  de Outlook, y validación de la reserva/worker en SQLite antes de comenzar.
- Hora de solicitud fijada mediante un callback inmediatamente antes de pulsar
  el envío del formulario IMSS. Se exige que Outlook siga listo en ese momento.
- Lector del mensaje abierto con remitente estructurado, fecha real con zona
  horaria, asunto y código únicos. Se elimina la inferencia de fecha del flujo
  integrado. La ruta OAuth antigua no entrega códigos en este modo.
- Pausa manual persistente ante desafíos Microsoft, sin cambiar de cuenta.
  El control de ofertas voluntarias se desarma ante autenticación obligatoria.
- Escritura ADB única y confirmación positiva explícita; emulador retenido en
  FIN o REVISAR, sin continuación, generación de PDF ni recuperación automática.
- Lanzadores `.pyw`, instalador, pruebas reproducibles, respaldos de los ZIP
  originales y respaldos SQLite locales antes de abrir los paneles.

El núcleo **`IMSS/gestoria_prueba_v7.py` no se modificó**. Se comparó byte a byte
con el contenido del ZIP interno de IMSS V32, verificando antes su SHA-256.
SHA-256 del núcleo ADB conservado:

`c651a967a9b782346699eae02984f2d22502b7630c3ad3e20c23a78705bc625f`

## Resultados locales

| Comprobación ejecutada | Resultado |
| --- | --- |
| Respaldo SQLite y contratos de lanzadores (`tests_paquete`) | 4/4 superadas |
| Flujo IMSS integrado y límites ADB (`IMSS/tests_integracion`) | 22/22 superadas |
| Suite existente IMSS V11 | 10/10 superadas |
| Descubrimiento Outlook, originales y nuevas regresiones | 162/162 superadas |
| Outlook PROBAR_V8 | 10/10 superadas |
| Outlook PROBAR_V9 | 15/15 superadas |
| Outlook PROBAR_V10 | 5/5 superadas |
| Contratos de panel integrado, sin abrir Tk | 7/7 superadas |
| Scripts de aserciones Outlook V11, V12 y enlace | Completados con salida 0 |
| Comunicación HTTP entre procesos | Cuatro canales completados en cinco procesos |
| Paquetes específicos de Windows uiautomation/comtypes | Descarga de versiones fijadas comprobada; no ejecutados |

**Total: 235 casos unittest superados**, además de los scripts de aserciones y
la prueba entre procesos. No hubo casos omitidos ni expected failures en esas
suites. Los respaldos SQLite se ejercitaron con una base real en modo WAL y
se comprobó la integridad y conservación del contenido del respaldo.

La prueba entre procesos utiliza las clases reales de protocolo, la lista
SQLite compartida y las comprobaciones de preparación del panel. Cada canal
espera a IMSS, entrega su código sintético y verifica el ACK y FIN. El cliente
ejecuta el nuevo flujo con funciones ADB y pantallas simuladas: sólo permite
abrir, enviar formulario, escribir una vez y verificar. No simula una prueba
exitosa con un dispositivo real.

Se comprobaron la identidad de cuenta, rechazo de códigos de otros folios y
direcciones, mensajes viejos/sin fecha/ambiguos, expiración y cancelación,
ceros iniciales, fallo parcial de ADB, ausencia de campos, rechazo de clave
incorrecta y `Origin` en HTTP, pausa MFA/llave existente, redacción de registros,
ausencia de acciones Android antes de Outlook y ausencia de reenvío tras FIN.

## Dos fallos históricos, sin ocultarlos

Las suites antiguas IMSS V12 y V13 también se ejecutaron sobre los originales
y se volvieron a comprobar en la entrega:

- V12: 10 superadas y 1 fallida. Espera una lista de tres emuladores aunque el
  panel entregado por el usuario utiliza cuatro posiciones, una eventualmente vacía.
- V13: 7 superadas y 1 fallida. Espera que los archivos `enlace.py` antiguos sean
  idénticos, pero el original Outlook usa un puerto por worker y el original
  IMSS conserva un puerto predeterminado fijo. Los nuevos `enlace_integrado.py`
  sí son idénticos y su igualdad tiene una regresión propia.

No se modificaron estas pruebas para convertirlas en éxitos. Se pueden repetir
con `python ejecutar_pruebas.py --historicas`, que devuelve error ante esos fallos.
No validan por sí solas la nueva coordinación.

## No comprobado en esta máquina

- Ventanas Tk de Windows, doble clic `.pyw`, BAT y mutex de Windows reales.
- Cifrado y lectura DPAPI en el perfil Windows del usuario.
- Inicio de sesión Microsoft real, interfaz actual de su bandeja, avisos nativos,
  exposición real del remitente y la fecha en su DOM.
- ADB de su instalación LDPlayer, pantallas reales IMSS ni aceptación real de un código.
- Pasos posteriores al código: están deliberadamente fuera del flujo.
- No se produjo ni firmó un `.exe`.

Si Outlook no expone los datos exigidos o IMSS usa un mensaje de aceptación
distinto, el programa se detiene para revisión. Es necesario validar primero
una cuenta y un trámite autorizados en Windows; una prueba sintética superada
no garantiza compatibilidad con una interfaz real que todavía no fue observada.

Los archivos `LEEME*.txt`, versiones y pruebas anteriores conservados en las
subcarpetas son documentación histórica. Para esta entrega, utiliza
`LEEME_PRIMERO.md` en la carpeta principal.
