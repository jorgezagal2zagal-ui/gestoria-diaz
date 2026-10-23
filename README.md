# Gestoría Díaz — Outlook V15.1

[Descargar ZIP](https://github.com/jorgezagal2zagal-ui/gestoria-diaz/raw/refs/heads/outlook-v15.1-descarga/GESTORIA_DIAZ_OUTLOOK_V15_1_SESION_ENLACE.zip)

Cierra la versión anterior, extrae el ZIP en una carpeta nueva y abre `OUTLOOK/ABRIR_OUTLOOK.bat`.
Requiere Windows y Python 3.12 o posterior de 64 bits; se recomienda 3.12.

Esta actualización rechaza las ofertas reconocidas de perfil o sincronización de Chrome/Edge mediante No, gracias/Cancelar. Prioriza Chromium, conserva la pestaña ante errores temporales y permite que el enlace IMSS reserve la cuenta que ya tiene Outlook abierto. Mantiene la interfaz simple y el enfriamiento de 30 segundos.

El código pasa por el enlace local compatible del mismo equipo y usuario. Configura el remitente exacto en AJUSTES. El panel distingue código disponible de recepción confirmada. El otro bot IMSS no está incluido.

Pasaron 106 pruebas locales, las pruebas con Tk y Chromium visibles y el intercambio HTTP con lectura de un mensaje ficticio en el navegador. La operación nativa de Windows (BAT, DPAPI y botón de Chrome/Edge), una cuenta Microsoft real y la aplicación IMSS/dispositivo real siguen pendientes de comprobación.

La contraseña común se configura una vez en AJUSTES y se cifra con DPAPI del usuario. Este paquete no incluye contraseñas, cuentas ni códigos reales. Los cuadros de Seguridad de Windows para guardar claves de paso requieren la decisión del usuario.

Código fuente y evidencia: [OUTLOOK/README_PRIMERO.md](OUTLOOK/README_PRIMERO.md), [RESULTADOS_PRUEBAS.json](OUTLOOK/RESULTADOS_PRUEBAS.json).
