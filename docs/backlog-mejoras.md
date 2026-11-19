# Backlog de mejoras del MVP y seguimiento de usuarios

**Proyecto** Módulo Restaurante de LEAF ERP v14  
**Corte** 18 de noviembre de 2026, miércoles de semana 6, según el calendario comunicado por Manuel.  
**Estado** PROPOSED para prioridad, clasificación académica y programación. Los resultados técnicos previos conservan su alcance y fecha.  
**Responsable propuesto** Manuel Padilla, con revisión funcional de Grintsys.

## 1. Interpretación del Módulo 5

El PDF aportado contiene 15 páginas. En las páginas 1 y 2 presenta los entregables y desarrolla desde la clase 3, correspondiente a la sesión 2. Las conclusiones y el repaso recuperan el guion de observación de la sesión 1. Esta revisión utiliza el contenido incluido en el archivo.

El módulo exige probar el MVP publicado con 3 a 5 personas reales del segmento. Cada participante realiza tareas con una meta operativa, piensa en voz alta y recibe observación sin instrucciones sobre qué botones pulsar. El documento de pruebas registra guion, hallazgos, severidad, participantes afectados y cita textual. Se vuelve a la hipótesis inicial con su métrica y umbral para decidir si se sostiene, se ajusta o se cae. Los hallazgos alimentan issues priorizados para las semanas 6 a 9. También se pide el hito semana-5 y la realización de los retos académicos.

El archivo incluye actividades de evaluación individuales. Esta entrega documenta el trabajo del proyecto y su seguimiento.

### Severidad y prioridad

| Severidad del curso | Criterio |
|---|---|
| Bloqueante | Impide completar una tarea del MVP. Se atiende primero. |
| Grave | Permite completar la tarea con mucho esfuerzo, errores o ayuda. Se atiende en semana 6. |
| Menor | Provoca una duda o demora breve que la persona resuelve sola. Se compara con el resto del backlog. |
| Cosmético | Afecta la presentación y permite completar la tarea. Se revisa para semana 9. |

La severidad se asigna por el efecto observado y la frecuencia se registra como personas afectadas sobre personas expuestas a la tarea. Una incidencia repetida por una misma persona conserva un solo participante en el numerador. Se ordena por severidad y luego por frecuencia. La dependencia y el riesgo transaccional se documentan cuando cambien el orden. Las propuestas nuevas se evalúan antes de asignar severidad.

## 2. Fuentes y alcance de evidencia

- ANALYZED. Registro histórico de semana 5 en [pruebas de usuarios](pruebas-usuarios.md), con hallazgos H-01 a H-06 y correcciones declaradas.
- ANALYZED. [Visión inicial](vision.md), [plan de diez semanas](plan.md) y [bitácora de semana 5](bitacora/semana-5.md).
- VERIFIED en las comprobaciones previas de esta sesión del 18/11/2026. Inventario directo, CAI, desglose de descuentos, corrección de sincronización de precuenta y consultas de facturación en development. Se referencia el resultado previo y sus pruebas, conservando las verificaciones operativas pendientes.
- ANALYZED. Los documentos disponibles carecen de un padrón anónimo de 3 a 5 participantes, frecuencia por hallazgo y citas individuales de las pruebas históricas. El registro disponible de Manuel permite atribuirle su reporte de precuenta como prueba del desarrollador. La pertenencia de participantes al segmento y su independencia se deben acreditar.
- VERIFIED. Consulta GitHub del 18/11/2026 mediante la conexión JEMM6192. El remoto local es SOLFAHSA/restaurant, público, con Issues habilitado. La búsqueda de issues devolvió cero resultados. La cuenta conectada tiene lectura y carece de push y triage según la respuesta del repositorio. La publicación posterior se completó mediante la sesión del navegador SOLFAHSA, después de que la integración devolviera 403 al intentar crear el primer issue.
- VERIFIED. Existe el tag remoto semana-5. La consulta de una GitHub Release con ese tag devolvió 404. Conviene confirmar con el docente si requiere además una Release y acreditar la versión en línea.

## 3. Backlog inicial

Los identificadores locales están enlazados a los 13 issues publicados con autorización de Manuel. Las fichas conservan el contenido aprobado y los estados de aceptación pendientes. Frecuencia y cita se completarán desde evidencia real. Los hallazgos técnicos conservan su fuente técnica.

| ID local | Origen | Título | Severidad propuesta | Estado actual | Semana propuesta |
|---|---|---|---|---|---|
| [M5-01 · #1](https://github.com/SOLFAHSA/restaurant/issues/1) | Semana 5, H-01 | Permitir a caja consultar las cuentas abiertas por meseros | Bloqueante | Corrección registrada, pendiente de revalidación | 6 |
| [M5-02 · #2](https://github.com/SOLFAHSA/restaurant/issues/2) | Semana 5, H-02 | Validar el acceso de caja a Cocina KDS, Comandas y Reportes | Grave | Corrección registrada, pendiente de revalidación | 6 |
| [M5-03 · #3](https://github.com/SOLFAHSA/restaurant/issues/3) | Semana 5, H-03 | Verificar descuentos autorizados por rol y configuración | Grave | Corrección registrada, pendiente de revalidación | 6 |
| [M5-04 · #4](https://github.com/SOLFAHSA/restaurant/issues/4) | Semana 5, H-04 | Revalidar la protección de precios, impuestos y funciones administrativas | Bloqueante | Corrección registrada, pendiente de revalidación | 6 |
| [M5-05 · #5](https://github.com/SOLFAHSA/restaurant/issues/5) | Semana 5, H-05 | Permitir al mesero generar la precuenta de su cuenta | Bloqueante | Corrección registrada, pendiente de revalidación | 6 |
| [M5-06 · #6](https://github.com/SOLFAHSA/restaurant/issues/6) | Semana 5, H-06 | Revalidar la presentación del indicador de carga | Cosmético | Corrección registrada, pendiente de revalidación | 9 |
| [M6-01 · #7](https://github.com/SOLFAHSA/restaurant/issues/7) | Semana 6, auditoría y corrección del 18/11/2026 | Completar la aceptación del inventario directo al facturar | Bloqueante | Verificado técnicamente en development, pendiente de aceptación operativa | 6 |
| [M6-02 · #8](https://github.com/SOLFAHSA/restaurant/issues/8) | Semana 6, auditoría y corrección del 18/11/2026 | Completar la aceptación de CAI y numeración fiscal | Bloqueante | Verificado técnicamente en development, pendiente de aceptación operativa | 6 |
| [M6-03 · #9](https://github.com/SOLFAHSA/restaurant/issues/9) | Semana 6, corrección y reimpresiones del 18/11/2026 | Completar la aceptación del desglose de descuentos en Ticket SAR | Grave | Verificado en ticket renderizado, pendiente de aceptación operativa | 6 |
| [M6-04 · #10](https://github.com/SOLFAHSA/restaurant/issues/10) | Semana 6, reporte de Manuel del 18/11/2026 | Continuar al cobro después de una precuenta sin recargar el POS | Grave | Corrección verificada técnicamente y uso sin F5 confirmado por Manuel, en validación final | 6 |
| [M6-05 · #11](https://github.com/SOLFAHSA/restaurant/issues/11) | Semana 6, revisión de ticket del 18/11/2026 | Completar y verificar el RTN del emisor en el ticket | Grave | CAI y perfil propio configurados y verificados, pendiente aceptación operativa | 6 |
| [M6-06 · #12](https://github.com/SOLFAHSA/restaurant/issues/12) | Semana 6, cobertura pendiente al 18/11/2026 | Completar la matriz de cobro y cierre de caja pendiente | Por evaluar en cada hallazgo | DEF-2026-017 corregido, 17 casos de aceptación aprobados, pendiente aceptación de interfaz | 7-8 |
| [M6-07 · #13](https://github.com/SOLFAHSA/restaurant/issues/13) | Revisión documental de semana 5 realizada en semana 6 | Completar la evidencia de validación con 3 a 5 participantes del segmento | Por evaluar en cada hallazgo | Pendiente | 6 |

## 4. Fichas de issues publicados

Cada bloque sirve como cuerpo de un issue y conserva su ID para enlazarlo con pruebas y bitácora. Para los registros históricos, la fecha de detección se conserva como semana 5, pendiente del día exacto. La fecha de publicación será la real.

### M5-01 - Permitir a caja consultar las cuentas abiertas por meseros

**Tipo** Error de usuario  
**Origen** Semana 5, H-01  
**Severidad propuesta** Bloqueante  
**Estado** Corrección registrada, pendiente de revalidación  
**Semana propuesta** 6  
**Responsable propuesto** Manuel Padilla  
**Issue GitHub** [#1](https://github.com/SOLFAHSA/restaurant/issues/1)

**Descripción**

El registro histórico indica que caja no visualizaba las cuentas de salón.

**Evidencia disponible**

docs/pruebas-usuarios.md, H-01.

**Participantes y frecuencia**

Pendiente de completar con los participantes realmente expuestos a esta tarea. En los hallazgos técnicos, registrar los escenarios ejecutados por separado.

**Cita textual**

Pendiente de evidencia de la persona participante. Para tareas técnicas o académicas, indicar que provienen de auditoría.

**Procedimiento de aceptación**

Abrir una cuenta con mesero y consultar/cobrar esa misma cuenta con cajero autorizado.

**Criterio de cierre**

La cuenta aparece con su importe y detalle correctos. Se preservan los límites de sucursal y las autorizaciones.

Registrar fecha de revalidación, participante anónimo, resultado esperado y obtenido, evidencia anonimizada y commit o PR correspondiente. La corrección con evidencia técnica queda En validación hasta completar la aceptación aplicable.

### M5-02 - Validar el acceso de caja a Cocina KDS, Comandas y Reportes

**Tipo** Error de usuario  
**Origen** Semana 5, H-02  
**Severidad propuesta** Grave  
**Estado** Corrección registrada, pendiente de revalidación  
**Semana propuesta** 6  
**Responsable propuesto** Manuel Padilla  
**Issue GitHub** [#2](https://github.com/SOLFAHSA/restaurant/issues/2)

**Descripción**

El registro histórico describe alertas de permisos en pantallas operativas.

**Evidencia disponible**

docs/pruebas-usuarios.md, H-02.

**Participantes y frecuencia**

Pendiente de completar con los participantes realmente expuestos a esta tarea. En los hallazgos técnicos, registrar los escenarios ejecutados por separado.

**Cita textual**

Pendiente de evidencia de la persona participante. Para tareas técnicas o académicas, indicar que provienen de auditoría.

**Procedimiento de aceptación**

Entrar con cajero operativo y ejecutar las tareas de cocina, comandas y reportes autorizadas.

**Criterio de cierre**

Las tareas autorizadas finalizan sin ayuda ni alertas de permisos. Las operaciones reservadas requieren su autorización.

Registrar fecha de revalidación, participante anónimo, resultado esperado y obtenido, evidencia anonimizada y commit o PR correspondiente. La corrección con evidencia técnica queda En validación hasta completar la aceptación aplicable.

### M5-03 - Verificar descuentos autorizados por rol y configuración

**Tipo** Error de usuario  
**Origen** Semana 5, H-03  
**Severidad propuesta** Grave  
**Estado** Corrección registrada, pendiente de revalidación  
**Semana propuesta** 6  
**Responsable propuesto** Manuel Padilla  
**Issue GitHub** [#3](https://github.com/SOLFAHSA/restaurant/issues/3)

**Descripción**

El registro histórico indica que caja tenía deshabilitados los descuentos.

**Evidencia disponible**

docs/pruebas-usuarios.md, H-03.

**Participantes y frecuencia**

Pendiente de completar con los participantes realmente expuestos a esta tarea. En los hallazgos técnicos, registrar los escenarios ejecutados por separado.

**Cita textual**

Pendiente de evidencia de la persona participante. Para tareas técnicas o académicas, indicar que provienen de auditoría.

**Procedimiento de aceptación**

Aplicar un descuento de línea y uno global con un cajero autorizado en pruebas independientes.

**Criterio de cierre**

Orden, factura, impuestos y ticket coinciden con resultados calculados previamente. Se exige autorización cuando corresponda.

Registrar fecha de revalidación, participante anónimo, resultado esperado y obtenido, evidencia anonimizada y commit o PR correspondiente. La corrección con evidencia técnica queda En validación hasta completar la aceptación aplicable.

### M5-04 - Revalidar la protección de precios, impuestos y funciones administrativas

**Tipo** Hallazgo técnico  
**Origen** Semana 5, H-04  
**Severidad propuesta** Bloqueante  
**Estado** Corrección registrada, pendiente de revalidación  
**Semana propuesta** 6  
**Responsable propuesto** Manuel Padilla  
**Issue GitHub** [#4](https://github.com/SOLFAHSA/restaurant/issues/4)

**Descripción**

La revisión técnica histórica registró validaciones de servidor insuficientes.

**Evidencia disponible**

docs/pruebas-usuarios.md, H-04.

**Participantes y frecuencia**

Pendiente de completar con los participantes realmente expuestos a esta tarea. En los hallazgos técnicos, registrar los escenarios ejecutados por separado.

**Cita textual**

Pendiente de evidencia de la persona participante. Para tareas técnicas o académicas, indicar que provienen de auditoría.

**Procedimiento de aceptación**

Ejecutar regresión de servidor y permisos con datos de prueba y roles operativos.

**Criterio de cierre**

Los importes se obtienen de la configuración autorizada y las acciones administrativas exigen el rol correspondiente. Adjuntar resultados de pruebas.

Registrar fecha de revalidación, participante anónimo, resultado esperado y obtenido, evidencia anonimizada y commit o PR correspondiente. La corrección con evidencia técnica queda En validación hasta completar la aceptación aplicable.

### M5-05 - Permitir al mesero generar la precuenta de su cuenta

**Tipo** Error de usuario  
**Origen** Semana 5, H-05  
**Severidad propuesta** Bloqueante  
**Estado** Corrección registrada, pendiente de revalidación  
**Semana propuesta** 6  
**Responsable propuesto** Manuel Padilla  
**Issue GitHub** [#5](https://github.com/SOLFAHSA/restaurant/issues/5)

**Descripción**

El registro histórico indica que el botón de acciones ocultaba la precuenta al mesero.

**Evidencia disponible**

docs/pruebas-usuarios.md, H-05.

**Participantes y frecuencia**

Pendiente de completar con los participantes realmente expuestos a esta tarea. En los hallazgos técnicos, registrar los escenarios ejecutados por separado.

**Cita textual**

Pendiente de evidencia de la persona participante. Para tareas técnicas o académicas, indicar que provienen de auditoría.

**Procedimiento de aceptación**

Abrir una cuenta con mesero y solicitar la precuenta.

**Criterio de cierre**

La precuenta muestra el detalle correcto. Cobrar y emitir factura requieren permiso de caja o supervisión.

Registrar fecha de revalidación, participante anónimo, resultado esperado y obtenido, evidencia anonimizada y commit o PR correspondiente. La corrección con evidencia técnica queda En validación hasta completar la aceptación aplicable.

### M5-06 - Revalidar la presentación del indicador de carga

**Tipo** Detalle visual  
**Origen** Semana 5, H-06  
**Severidad propuesta** Cosmético  
**Estado** Corrección registrada, pendiente de revalidación  
**Semana propuesta** 9  
**Responsable propuesto** Manuel Padilla  
**Issue GitHub** [#6](https://github.com/SOLFAHSA/restaurant/issues/6)

**Descripción**

El registro histórico describe texto técnico sobre el indicador de carga.

**Evidencia disponible**

docs/pruebas-usuarios.md, H-06.

**Participantes y frecuencia**

Pendiente de completar con los participantes realmente expuestos a esta tarea. En los hallazgos técnicos, registrar los escenarios ejecutados por separado.

**Cita textual**

Pendiente de evidencia de la persona participante. Para tareas técnicas o académicas, indicar que provienen de auditoría.

**Procedimiento de aceptación**

Navegar entre pantallas en los dispositivos de la prueba.

**Criterio de cierre**

El indicador se presenta legible y sin superposiciones durante la navegación.

Registrar fecha de revalidación, participante anónimo, resultado esperado y obtenido, evidencia anonimizada y commit o PR correspondiente. La corrección con evidencia técnica queda En validación hasta completar la aceptación aplicable.

### M6-01 - Completar la aceptación del inventario directo al facturar

**Tipo** Hallazgo técnico  
**Origen** Semana 6, auditoría y corrección del 18/11/2026  
**Severidad propuesta** Bloqueante  
**Estado** Verificado técnicamente en development, pendiente de aceptación operativa  
**Semana propuesta** 6  
**Responsable propuesto** Manuel Padilla  
**Issue GitHub** [#7](https://github.com/SOLFAHSA/restaurant/issues/7)

**Descripción**

La auditoría identificó facturación sin descarga de inventario. Se implementó y probó el circuito de stock directo.

**Evidencia disponible**

restaurant/tests/test_invoice_stock.py y auditorías de esta sesión del 18/11/2026.

**Participantes y frecuencia**

Pendiente de completar con los participantes realmente expuestos a esta tarea. En los hallazgos técnicos, registrar los escenarios ejecutados por separado.

**Cita textual**

Pendiente de evidencia de la persona participante. Para tareas técnicas o académicas, indicar que provienen de auditoría.

**Procedimiento de aceptación**

Probar existencia cero, insuficiente, exacta y artículo sin control, y revisar Kardex y reversión.

**Criterio de cierre**

Se bloquea inventario insuficiente. La venta válida descuenta una sola vez en el almacén efectivo. La cancelación restaura el saldo. Los artículos sin control completan la venta.

Registrar fecha de revalidación, participante anónimo, resultado esperado y obtenido, evidencia anonimizada y commit o PR correspondiente. La corrección con evidencia técnica queda En validación hasta completar la aceptación aplicable.

### M6-02 - Completar la aceptación de CAI y numeración fiscal

**Tipo** Hallazgo técnico  
**Origen** Semana 6, auditoría y corrección del 18/11/2026  
**Severidad propuesta** Bloqueante  
**Estado** Verificado técnicamente en development, pendiente de aceptación operativa  
**Semana propuesta** 6  
**Responsable propuesto** Manuel Padilla  
**Issue GitHub** [#8](https://github.com/SOLFAHSA/restaurant/issues/8)

**Descripción**

Se corrigieron la selección de autorización y las validaciones de numeración fiscal.

**Evidencia disponible**

restaurant/tests/test_fiscal_numbering.py y auditorías de esta sesión del 18/11/2026.

**Participantes y frecuencia**

Pendiente de completar con los participantes realmente expuestos a esta tarea. En los hallazgos técnicos, registrar los escenarios ejecutados por separado.

**Cita textual**

Pendiente de evidencia de la persona participante. Para tareas técnicas o académicas, indicar que provienen de auditoría.

**Procedimiento de aceptación**

Generar precuentas y emitir facturas con una serie de prueba, incluyendo vencimiento, agotamiento y renovación.

**Criterio de cierre**

La precuenta conserva la numeración fiscal. La factura usa el CAI y folio autorizados. Se rechazan autorizaciones inválidas. La reimpresión conserva los datos originales.

Registrar fecha de revalidación, participante anónimo, resultado esperado y obtenido, evidencia anonimizada y commit o PR correspondiente. La corrección con evidencia técnica queda En validación hasta completar la aceptación aplicable.

### M6-03 - Completar la aceptación del desglose de descuentos en Ticket SAR

**Tipo** Error de impresión  
**Origen** Semana 6, corrección y reimpresiones del 18/11/2026  
**Severidad propuesta** Grave  
**Estado** Verificado en ticket renderizado, pendiente de aceptación operativa  
**Semana propuesta** 6  
**Responsable propuesto** Manuel Padilla  
**Issue GitHub** [#9](https://github.com/SOLFAHSA/restaurant/issues/9)

**Descripción**

Se corrigió el desglose de descuentos y se contrastó con los importes persistidos.

**Evidencia disponible**

restaurant/tests/test_sar_ticket.py y auditorías de esta sesión del 18/11/2026.

**Participantes y frecuencia**

Pendiente de completar con los participantes realmente expuestos a esta tarea. En los hallazgos técnicos, registrar los escenarios ejecutados por separado.

**Cita textual**

Pendiente de evidencia de la persona participante. Para tareas técnicas o académicas, indicar que provienen de auditoría.

**Procedimiento de aceptación**

Emitir y reimprimir un ticket con descuento de línea y otro con descuento global.

**Criterio de cierre**

Cada descuento aparece una sola vez. Base, impuestos, total y pago coinciden con la factura. Adjuntar salida de impresora de prueba cuando esté disponible.

Registrar fecha de revalidación, participante anónimo, resultado esperado y obtenido, evidencia anonimizada y commit o PR correspondiente. La corrección con evidencia técnica queda En validación hasta completar la aceptación aplicable.

### M6-04 - Continuar al cobro después de una precuenta sin recargar el POS

**Tipo** Error de usuario  
**Origen** Semana 6, reporte de Manuel del 18/11/2026  
**Severidad propuesta** Grave  
**Estado** Corrección verificada técnicamente y uso sin F5 confirmado por Manuel, en validación final  
**Semana propuesta** 6  
**Responsable propuesto** Manuel Padilla  
**Issue GitHub** [#10](https://github.com/SOLFAHSA/restaurant/issues/10)

**Descripción**

Después de generar una precuenta, el POS usaba una versión anterior de la orden y mostraba una alerta al intentar continuar.

**Evidencia disponible**

restaurant/tests/ui/precuenta_state.cjs, restaurant/restaurant/page/restaurant_pos/restaurant_pos.js y reporte de esta sesión.

**Participantes y frecuencia**

Pendiente de completar con los participantes realmente expuestos a esta tarea. En los hallazgos técnicos, registrar los escenarios ejecutados por separado.

**Cita textual**

Reporte de Manuel en esta sesión del 18/11/2026, como desarrollador que realiza la prueba. “tengo que estar prácticamente como actualizando, dándole actualizar a la página o F5 para que funcione”.

**Procedimiento de aceptación**

Abrir una cuenta, generar precuenta, ajustar propina, volver a precuenta y pasar al cobro. Repetir desde Órdenes y con mesero.

**Criterio de cierre**

El POS usa la versión devuelta por el servidor. El cobro opera sobre la cuenta visualizada. Un cambio real en otra sesión mantiene su protección de concurrencia. Registrar confirmación de que el participante terminó sin F5.

Registrar fecha de revalidación, participante anónimo, resultado esperado y obtenido, evidencia anonimizada y commit o PR correspondiente. La corrección con evidencia técnica queda En validación hasta completar la aceptación aplicable.

**Aceptación de uso comunicada por Manuel**

VERIFIED. En el seguimiento de esta sesión se preguntó si, después de generar la precuenta, pudo continuar y facturar sin actualizar la página ni presionar F5. Manuel respondió “Sí, terminé sin actualizar”.

Esta confirmación completa la aceptación del recorrido precuenta a factura sin recarga por parte del desarrollador que realizó la prueba. Se conservan las validaciones técnicas previas. Para cerrar el conjunto de criterios del issue quedan documentar la revalidación desde Órdenes y con mesero, y vincular el commit o PR de la corrección.

### M6-05 - Completar y verificar el RTN del emisor en el ticket

**Tipo** Configuración  
**Origen** Semana 6, revisión de ticket del 18/11/2026  
**Severidad propuesta** Grave  
**Estado** CAI y perfil propio configurados y verificados, pendiente aceptación operativa  
**Semana propuesta** 6  
**Responsable propuesto** Manuel Padilla  
**Issue GitHub** [#11](https://github.com/SOLFAHSA/restaurant/issues/11)

**Descripción**

La revisión de los tickets encontró vacío el RTN del emisor.

**Evidencia disponible**

Auditorías de facturas de esta sesión del 18/11/2026.

**Participantes y frecuencia**

Pendiente de completar con los participantes realmente expuestos a esta tarea. En los hallazgos técnicos, registrar los escenarios ejecutados por separado.

**Cita textual**

Pendiente de evidencia de la persona participante. Para tareas técnicas o académicas, indicar que provienen de auditoría.

**Procedimiento de aceptación**

Con el responsable autorizado, revisar los datos del emisor en Company y renderizar el Ticket SAR.

**Criterio de cierre**

El RTN autorizado aparece en el ticket conforme a la configuración aprobada. Adjuntar evidencia anonimizada y confirmación del responsable fiscal. Requiere validación tributaria local.

Registrar fecha de revalidación, participante anónimo, resultado esperado y obtenido, evidencia anonimizada y commit o PR correspondiente. La corrección con evidencia técnica queda En validación hasta completar la aceptación aplicable.

**VERIFIED. Configuración del emisor recibida del responsable.** Se creó una Company independiente y una Address principal vinculada mediante Dynamic Link en development. Se guardaron los datos proporcionados por el usuario y se conservaron los ceros iniciales del RTN. Una vista previa sin emisión del Ticket verificó razón social, RTN, dirección, ciudad y teléfono. La nueva empresa tiene cuentas, almacenes, centros de costos y cuenta de efectivo nativos. El aviso del generador de departamentos por diferencia de idioma se resolvió ejecutando el generador nativo con la traducción existente.

La huella de las 17 facturas existentes y sus GL/SLE coincidió antes y después. El perfil y los turnos de demostración continúan asociados a su empresa histórica.

**Pendiente en la etapa previa** Recibir el CAI, prefijo fiscal, número inicial, número final y fecha límite de emisión para completar un perfil POS propio. El campo prefix es obligatorio en POS Profile. Después corresponde comprobar la factura emitida y su ticket desde ese perfil.

**Tratamiento de evidencia** Los datos concretos del emisor están guardados en development. El seguimiento público conserva esta verificación sin reproducir esos datos.

**VERIFIED. Configuración fiscal completada el 19/11/2026.** El responsable proporcionó los datos complementarios de declaración y recepción. Se guardó el CAI nativo y se comprobó estado Active, fechas y rango contra los datos recibidos. Se registró la serie en Document Naming Settings y se creó el perfil POS propio de la empresa con cuentas, centro de costos, almacén y dirección de esa empresa.

La verificación en una conexión nueva confirmó que el perfil está activo y aparece en get_pos_bootstrap. Se habilitó Efectivo como medio inicial con cuenta propia. Se configuraron alertas preventivas a 30 días y 100 folios disponibles. La vista previa del Ticket mostró emisor, CAI, rango y vencimiento correctos.

La lógica nativa confirmó el primer folio esperado. La serie sigue sin contador ni facturas y conserva su rango completo de 2,000 folios en development. Las 17 facturas existentes y sus GL/SLE conservaron la huella previa.

**Pendiente de aceptación operativa** Abrir un turno del perfil de la nueva empresa y comprobar la factura emitida y su impresión en el flujo operativo. Los turnos abiertos actuales pertenecen a la empresa demostrativa.

Los valores concretos de la autorización fiscal están almacenados en development. El seguimiento público contiene esta evidencia técnica.

### M6-06 - Completar la matriz de cobro y cierre de caja pendiente

**Tipo** Tarea de QA  
**Origen** Semana 6, cobertura pendiente al 18/11/2026  
**Severidad propuesta** Por evaluar en cada hallazgo  
**Estado** DEF-2026-017 corregido y 17 casos de aceptación aprobados, en validación operativa  
**Semana propuesta** 7-8  
**Responsable propuesto** Manuel Padilla  
**Issue GitHub** [#12](https://github.com/SOLFAHSA/restaurant/issues/12)

**Descripción**

La última ronda manual cubrió ISV 15%, efectivo, tarjeta, transferencia, propina fija y descuentos de línea. Faltó completar otros escenarios.

**Evidencia disponible**

docs/qa/auditoria-salida-restaurante-2026-11-18.md y auditorías de esta sesión.

**Participantes y frecuencia**

Pendiente de completar con los participantes realmente expuestos a esta tarea. En los hallazgos técnicos, registrar los escenarios ejecutados por separado.

**Cita textual**

Pendiente de evidencia de la persona participante. Para tareas técnicas o académicas, indicar que provienen de auditoría.

**Procedimiento de aceptación**

Ejecutar casos separados de mezcla 15%/18%/exento, descuento global, cortesía autorizada, pago mixto, vuelto y cierre de caja.

**Criterio de cierre**

Adjuntar resultado esperado y obtenido por caso, factura, pago, GL y stock aplicables. Abrir un issue específico por cada defecto confirmado y asignar severidad.

Registrar fecha de revalidación, participante anónimo, resultado esperado y obtenido, evidencia anonimizada y commit o PR correspondiente. La corrección con evidencia técnica queda En validación hasta completar la aceptación aplicable.

**Avance VERIFIED del 18/11/2026** Se aprobaron impuestos mixtos, descuento global por porcentaje y monto, descuento del 100% por línea, vuelto y pago mixto con arqueo de cierre temporal. Falló el descuento global del 100%, DEF-2026-017. [Informe de ejecución](qa/aceptacion-cobro-caja-2026-11-18.md).

**Corrección posterior VERIFIED** Manuel autorizó el ajuste de DEF-2026-017. Se respetan net_amount=0 y el total final nativo para el pago predeterminado. La regresión ampliada aprobó 17 casos, con un total de 51 entre las suites ejecutadas. Las 17 facturas existentes y sus ledgers conservaron su huella. Pendiente aceptación de interfaz y salida de impresora según el alcance del issue. [Informe actualizado](qa/aceptacion-cobro-caja-2026-11-18.md).

### M6-07 - Completar la evidencia de validación con 3 a 5 participantes del segmento

**Tipo** Tarea académica  
**Origen** Revisión documental de semana 5 realizada en semana 6  
**Severidad propuesta** Por evaluar en cada hallazgo  
**Estado** Pendiente  
**Semana propuesta** 6  
**Responsable propuesto** Manuel Padilla  
**Issue GitHub** [#13](https://github.com/SOLFAHSA/restaurant/issues/13)

**Descripción**

La documentación disponible carece de padrón anónimo, frecuencia por hallazgo, citas de participantes y métrica con umbral previamente registrados.

**Evidencia disponible**

docs/pruebas-usuarios.md, docs/vision.md y Módulo 5 entregado por el estudiante.

**Participantes y frecuencia**

Pendiente de completar con los participantes realmente expuestos a esta tarea. En los hallazgos técnicos, registrar los escenarios ejecutados por separado.

**Cita textual**

Pendiente de evidencia de la persona participante. Para tareas técnicas o académicas, indicar que provienen de auditoría.

**Procedimiento de aceptación**

Recuperar la evidencia disponible y realizar las sesiones faltantes. Registrar fecha real, rol y tareas sin asistencia. Definir la métrica antes de la siguiente ronda.

**Criterio de cierre**

Documentar entre 3 y 5 personas del segmento con identificadores anónimos, resultados por tarea, ayudas, frecuencia y citas reales. Contrastar H1/H2 con métrica y umbral y emitir una decisión fundamentada.

Registrar fecha de revalidación, participante anónimo, resultado esperado y obtenido, evidencia anonimizada y commit o PR correspondiente. La corrección con evidencia técnica queda En validación hasta completar la aceptación aplicable.


## 5. Secuencia propuesta para semanas 6 a 9

| Semana | Trabajo | Evidencia de salida |
|---|---|---|
| 6 | Completar fichas y frecuencia. Priorizar bloqueantes y graves. Revalidar stock directo, CAI, permisos, descuentos y precuenta. Revisar RTN con responsable autorizado. | Issues trazados a hallazgos, resultados por tarea, conciliaciones y aceptación de correcciones. |
| 7 | Completar pruebas operativas con roles, cuentas compartidas, comandas y cocina. Ejecutar los casos de impuestos y descuentos pendientes en M6-06. | Casos individuales con resultado, frecuencia real y nuevos issues para defectos encontrados. |
| 8 | Completar cobro, vuelto y cierre. Evaluar recetas o modalidades adicionales según demanda confirmada y alcance aprobado. | Conciliación de caja y definición de alcance para ampliaciones con sus criterios de aceptación. |
| 9 | Revalidar correcciones, resolver menores priorizados y revisar cosméticos, incluyendo M5-06. | Evidencia de aceptación y backlog pendiente justificado para la entrega. |

Esta secuencia reordena el [plan previo](plan.md) a partir de la evidencia. Cada nuevo bloqueante cambia el orden de trabajo. Los casos ya completados se registran con sus fechas reales.

## 6. Registro de próximas sesiones

Una persona puede evaluar varias tareas con un mismo identificador. El rol y la condición de pertenencia al segmento se documentan sin publicar nombres, correos o teléfonos.

| Participante anónimo | Fecha real | Perfil del segmento | Tarea | Resultado sin ayuda | Ayuda necesaria | Duración observada | Hallazgo | Cita textual |
|---|---|---|---|---|---|---|---|---|
| Por registrar | Por registrar | Por acreditar | Por ejecutar o recuperar | Por registrar | Por registrar | Por registrar | ID local y issue | Por transcribir |

Las cuentas de prueba con distintos roles pueden corresponder a una misma persona. Contar personas únicas al calcular la muestra.

### Plantilla para nuevas incidencias

Copiar este bloque por hallazgo y completar la información disponible.

```markdown
## Hallazgo
Describir lo que ocurrió y cómo afecta la tarea.

## Origen
Fecha real, participante anónimo o auditoría técnica, rol y entorno.

## Frecuencia y cita
Personas afectadas / personas expuestas a la tarea.
Transcripción real o indicación de que falta evidencia.

## Reproducción
Precondiciones, datos de prueba y acciones que produjeron el resultado.

## Esperado y obtenido
Describir ambos resultados con importes o estados concretos cuando corresponda.

## Clasificación
Error, duda, sugerencia, mejora o tarea técnica.
Severidad según efecto observado, prioridad y semana propuesta.
Estado de evidencia VERIFIED, ANALYZED, PROPOSED o BLOCKED.

## Aceptación
Condiciones observables para dar el trabajo por terminado.

## Seguimiento
Responsable, dependencias, enlace al hallazgo, commit o PR, prueba y aceptación.
```

## 7. Operación del seguimiento en GitHub

El product backlog es la lista ordenada de trabajo del producto. Un issue representa un trabajo concreto con su evidencia y aceptación. GitHub Projects permite mostrar esos issues como tabla o tablero. Las relaciones permiten seguir el flujo hallazgo, issue, cambio, prueba y aceptación.

**Estados propuestos** Pendiente, Priorizado, En curso, En validación y Terminado. Los trabajos corregidos antes de crear el issue conservan la fecha histórica y su aceptación pendiente. Al cerrar, adjuntar el resultado de la revalidación y el commit o PR real.

**Campos propuestos** ID local, tipo, severidad, participantes afectados/expuestos, semana, responsable, estado, evidencia y criterio de aceptación. Las etiquetas o un tablero se configuran con una cuenta que tenga los permisos correspondientes.

Los borradores están preparados para un repositorio público. Las capturas y anexos se revisan para anonimizar datos de participantes, clientes y documentos de prueba antes de publicarlos.

Referencias oficiales de la herramienta consultadas el 18/11/2026.

- [GitHub Issues](https://docs.github.com/en/issues/tracking-your-work-with-issues/learning-about-issues/about-issues).
- [GitHub Projects](https://docs.github.com/en/issues/planning-and-tracking-with-projects/learning-about-projects/about-projects).

## 8. Dictamen de la revisión documental

ANALYZED. La documentación histórica aporta un guion, seis hallazgos y decisiones sobre hipótesis. El cierre académico sigue pendiente de participantes, frecuencia, citas y contraste con métricas. Los 13 issues ya están publicados y enlazados. La verificación técnica en development aporta evidencia para la iteración de semana 6. La publicación del MVP, las sesiones con personas del segmento y los requisitos de entrega se acreditarán con sus registros específicos.

## 9. Registro de publicación

**Estado de evidencia** VERIFIED. Manuel autorizó publicar los 13 borradores en SOLFAHSA/restaurant.

La integración GitHub devolvió 403 Resource not accessible by integration al crear el primer issue. Se utilizó la sesión autenticada del navegador SOLFAHSA y se publicaron los issues #1 a #13. La API de lectura confirmó 13 URLs únicas, estado Open y coincidencia exacta de título y descripción con cada borrador aprobado.

GitHub registró la creación entre 2026-11-19T03:08:31Z y 2026-11-19T03:10:55Z, equivalentes al 18/11/2026 entre 21:08:31 y 21:10:55 en America/Guatemala. Los hallazgos conservan su origen en semana 5 o semana 6.

La severidad, semana y responsabilidad propuestas están registradas en el cuerpo de cada issue. Las aceptaciones, citas y frecuencias pendientes se completarán con sus evidencias.

[Consultar los 13 issues](https://github.com/SOLFAHSA/restaurant/issues).

**Dictamen de publicación** APROBADO. Se publicaron y verificaron los 13 registros autorizados.
