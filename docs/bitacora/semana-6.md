# Bitácora de actividades — Semana 6

**Proyecto:** Desarrollo del módulo Restaurante para Leaf ERP

**Empresa receptora:** Grintsys

**Institución:** CEUTEC

**Asignatura:** Proyecto de Graduación Fase 1

**Etapa:** Semana 6 (16 al 22 de noviembre de 2026) — Arquitectura y oficio diario: estructura, decisiones registradas, corrección de los hallazgos de la semana 5 y segundo flujo completo (fiscal)

**Tecnologías:** Frappe Framework v14, ERPNext v14 (Grintsys), POS Awesome, Python 3.11, JavaScript, MariaDB, Redis y Socket.IO

## 1. Introducción

La semana 6 partió de los hallazgos de la semana 5, que confirmaron el problema pero obligaron a ajustar la solución (H1 se ajusta). El trabajo se concentró en tres frentes: corregir los defectos que afectan el cobro y los impuestos, ordenar la arquitectura para que cada regla viva una sola vez en su capa, y dejar registradas las decisiones que costaría cambiar.

## 2. Objetivo de la semana

Documentar la arquitectura del sistema y sus decisiones principales, corregir los defectos de cobro, impuestos y permisos encontrados en las pruebas, eliminar código sin uso, y completar el **flujo fiscal** de punta a punta (producto con su ISV, orden, factura, ticket SAR y anulación) como segundo flujo del negocio.

## 3. Actividades realizadas

### 3.1. Por fecha

| Fecha | Actividad | Evidencia |
| :--- | :--- | :--- |
| 17/11 | Ticket SAR sin redondeo y actualización en tiempo real de la pantalla de cocina (hallazgo S5-P1-02); auditoría QA integral | Commits `8c69600` y `30cef59` |
| 18/11 | Revisión de la entrega frente al Módulo 5, publicación de los issues #1 a #13 y aceptación de la matriz de cobro y caja | Sección 4 de esta bitácora; `docs/qa/aceptacion-cobro-caja-2026-11-18.md` |
| 19/11 | Línea base de pruebas en un sitio limpio (de 119 a 228 de 246 aprobadas); corrección del permiso del cajero para la primera factura de una serie SAR nueva; pruebas que reproducen los defectos de cobro; configuración fiscal de la empresa | Commits `263b6ae` a `38eaa6b`; `docs/qa/linea-base-2026-11-19.md` |
| 20/11 | Impuestos con plantillas nativas por producto y grupo; anulación que reabre la orden; descuentos con autorización de supervisor; la orden igual a la factura; precios del menú para mesero y cajero; limpieza de código sin uso; pruebas autosuficientes; pruebas manuales con usuarios mesero y cajero; arquitectura y decisiones registradas | `docs/arquitectura.md`, `docs/decisiones/001` y `002`; suite de 263 pruebas aprobada |

### 3.2. Arquitectura y decisiones

- Se documentó el sistema en [`docs/arquitectura.md`](../arquitectura.md): diagramas de contexto y de contenedores en Mermaid, las tres capas del stack y la estructura de carpetas actual y meta.
- Se registraron dos decisiones: [001 · impuestos nativos por producto y grupo](../decisiones/001-impuestos-nativos-por-producto-y-grupo.md) y [002 · la factura como fuente de verdad](../decisiones/002-factura-como-fuente-de-verdad.md).
- Se movieron dos reglas a la capa de negocio: la tasa de impuesto, que el menú deducía por el nombre de la plantilla, y los totales de la orden facturada.

### 3.3. Hallazgos de las pruebas internas de la semana 6

Pruebas del desarrollador con los usuarios de prueba Mesero y Cajero, y auditoría técnica del código. No son pruebas con participantes del segmento.

| Hallazgo | Severidad | Estado |
| :--- | :--- | :--- |
| El cajero no podía emitir la primera factura de una serie SAR nueva | Bloqueante | Corregido el 19/11 (commit `9a30f0e`); corrección de fondo reportada a Grintsys |
| El resumen SAR del ticket duplicaba el ISV cuando un producto aparecía en dos líneas | Grave | Corregido en ERPNext de Grintsys; pendiente de aprobación del responsable |
| El mesero y el cajero veían el menú sin precios | Grave | Corregido |
| Un producto sin plantilla de impuesto se cobraba al 15 % sin aviso | Grave | Corregido (decisión 001) |
| Tarjeta y transferencia se contabilizaban en la cuenta de efectivo | Grave | Corregido en la configuración |
| El total de la orden no coincidía con la factura cuando había descuento global | Menor | Corregido (decisión 002) |
| El botón "+" de Productos no respondía fuera del espacio del Restaurante | Menor | Corregido |

### 3.4. Limpieza de código

Se eliminaron funciones y endpoints sin consumidores, verificados uno por uno: el mecanismo de token de supervisor sin uso, la creación de productos desde el POS, la consulta de existencias que duplicaba el reporte nativo *Balance de existencias*, una autorización duplicada y una consulta de mesas reemplazada. También se eliminaron funciones del POS y de la pantalla de cocina que no se llamaban desde ningún lugar. Se conservó el autopedido, que será la base del kiosco solicitado por la empresa.

## 4. Seguimiento de los issues de la semana 5

### 4.1. Verificaciones de los issues de la semana 5 (M6-01 a M6-07)

| Referencia | Origen | Evidencia disponible | Aceptación pendiente |
|---|---|---|---|
| M6-01 | Auditoría técnica de stock directo | VERIFIED en pruebas previas de esta sesión. Integración y restricciones al facturar, con suite test_invoice_stock. | Revalidación operativa del alcance habilitado. El consumo de recetas se evalúa por separado según alcance. |
| M6-02 | Auditoría técnica de CAI | VERIFIED en pruebas previas de esta sesión. Suite test_fiscal_numbering, 11 casos, y revisión de facturas. | Aceptación y configuración del entorno que se vaya a publicar. |
| M6-03 | Desglose de descuentos del Ticket SAR | VERIFIED en comprobaciones previas de tickets renderizados. Descuentos de línea de L 0.26 y L 0.77 conciliados con facturas. | Descuento global y salida física en los escenarios aplicables. |
| M6-04 | Reporte de Manuel sobre la precuenta | VERIFIED en comprobaciones previas. Tres pruebas de interfaz, guardas de versiones y flujo temporal en Frappe. Posterior orden ORD-00097 terminó en una sola factura. | VERIFIED. Manuel confirmó “Sí, terminé sin actualizar”. Quedan la revalidación desde Órdenes y con mesero, y el enlace al commit o PR, según el issue. |
| M6-05 | RTN del emisor vacío | VERIFIED en revisión previa de tickets. | Revisión de configuración por responsable autorizado y comprobación posterior. |
| M6-06 | Cobertura pendiente de cobro y cierre | ANALYZED a partir de la última ronda manual. | Casos faltantes y nuevos issues por defectos confirmados. |
| M6-07 | Integridad del registro académico | ANALYZED en esta revisión documental. | Fichas de 3 a 5 personas, frecuencia y citas reales. |

La prueba comunicada por Manuel se registra como actividad del desarrollador. Los participantes reales del segmento se identificarán como Participante 1, Participante 2 y sucesivos, con rol y fecha de sesión.

### 4.2. Seguimiento, publicación de issues y configuración fiscal

El [backlog de mejoras](../backlog-mejoras.md) contiene las fichas y enlaces de los 13 issues publicados con origen, severidad propuesta, estado, procedimiento y criterio de cierre, junto con el plan de semanas 6 a 9 y la plantilla de nuevas incidencias.

Para cada issue se conservará la relación con el hallazgo, el cambio real, la evidencia de prueba y la aceptación de la persona usuaria o responsable. Se registrarán tanto los defectos ya corregidos como las mejoras pendientes con su fecha real.

**VERIFIED. Publicación autorizada por Manuel.** Se crearon y comprobaron los [issues #1 a #13](https://github.com/SOLFAHSA/restaurant/issues), con coincidencia exacta frente a los borradores aprobados. El registro de publicación y los enlaces individuales están en el backlog. Todos continúan abiertos con su aceptación pendiente.

**VERIFIED. Aceptación del recorrido sin recarga.** Manuel confirmó en el seguimiento de esta sesión que pudo generar la precuenta, continuar y facturar sin actualizar la página ni presionar F5. La confirmación está registrada en el [issue #10](https://github.com/SOLFAHSA/restaurant/issues/10), que continúa en validación final por los demás criterios de cierre.

**VERIFIED. Avance técnico del issue #12.** La matriz de cobro y cierre temporal aprobó seis casos y detectó un fallo en descuento global del 100%, DEF-2026-017. Los resultados y la restauración del entorno están en el [informe de aceptación](../qa/aceptacion-cobro-caja-2026-11-18.md). La aceptación con participantes operativos sigue pendiente.

**VERIFIED. Corrección posterior del issue #12.** Tras la autorización de Manuel, DEF-2026-017 se corrigió en development. Se aprobaron 17 casos de aceptación y 51 pruebas distintas entre las suites ejecutadas. Se comprobó la preservación de las 17 facturas existentes y sus GL/SLE. El [informe actualizado](../qa/aceptacion-cobro-caja-2026-11-18.md) conserva la evidencia inicial y la posterior. La aceptación con perfiles operativos y la impresión física continúan pendientes.

**VERIFIED. Configuración del emisor recibida del responsable.** Se creó una Company independiente y una Address principal vinculada mediante Dynamic Link en development. Se guardaron los datos proporcionados por el usuario y se conservaron los ceros iniciales del RTN. Una vista previa sin emisión del Ticket verificó razón social, RTN, dirección, ciudad y teléfono. La nueva empresa tiene cuentas, almacenes, centros de costos y cuenta de efectivo nativos. El aviso del generador de departamentos por diferencia de idioma se resolvió ejecutando el generador nativo con la traducción existente.

La huella de las 17 facturas existentes y sus GL/SLE coincidió antes y después. El perfil y los turnos de demostración continúan asociados a su empresa histórica.

**Pendiente** Recibir el CAI, prefijo fiscal, número inicial, número final y fecha límite de emisión para completar un perfil POS propio. El campo prefix es obligatorio en POS Profile. Después corresponde comprobar la factura emitida y su ticket desde ese perfil.

**Tratamiento de evidencia** Los datos concretos del emisor están guardados en development. El seguimiento público conserva esta verificación sin reproducir esos datos.

**VERIFIED. Configuración fiscal completada el 19/11/2026.** El responsable proporcionó los datos complementarios de declaración y recepción. Se guardó el CAI nativo y se comprobó estado Active, fechas y rango contra los datos recibidos. Se registró la serie en Document Naming Settings y se creó el perfil POS propio de la empresa con cuentas, centro de costos, almacén y dirección de esa empresa.

La verificación en una conexión nueva confirmó que el perfil está activo y aparece en get_pos_bootstrap. Se habilitó Efectivo como medio inicial con cuenta propia. Se configuraron alertas preventivas a 30 días y 100 folios disponibles. La vista previa del Ticket mostró emisor, CAI, rango y vencimiento correctos.

La lógica nativa confirmó el primer folio esperado. La serie sigue sin contador ni facturas y conserva su rango completo de 2,000 folios en development. Las 17 facturas existentes y sus GL/SLE conservaron la huella previa.

**Pendiente de aceptación operativa** Abrir un turno del perfil de la nueva empresa y comprobar la factura emitida y su impresión en el flujo operativo. Los turnos abiertos actuales pertenecen a la empresa demostrativa.

Los valores concretos de la autorización fiscal están almacenados en development. El seguimiento público contiene esta evidencia técnica.

## 5. Pruebas ejecutadas y verificación

- **Pruebas automatizadas (unitarias y de integración):** ejecuté la suite completa en un sitio de pruebas limpio (`bench --site test_restaurant run-tests --app restaurant --skip-test-records`): **263 pruebas, 0 fallos y 0 errores** (`OK`, 10 omitidas por diseño). Las unitarias comprueban funciones aisladas, como la tasa de impuesto de un producto; las de integración recorren la orden, la factura nativa, la contabilidad y el inventario. Procedimiento en [`docs/qa/como-ejecutar-pruebas.md`](../qa/como-ejecutar-pruebas.md).
- **Pruebas manuales:** antes de entregar cada versión a mi supervisor de práctica para que él haga sus propias pruebas, recorrí manualmente el módulo completo en el entorno de desarrollo: mesas y mapa del salón, toma de órdenes, envío a cocina y pantalla de preparación, precuenta, cobro con efectivo, tarjeta y transferencia, descuentos, propina, anulaciones con PIN de supervisor, arqueo y cierre de caja, con los usuarios Mesero, Cajero y Supervisor, en las dos empresas. De esas pruebas salieron los hallazgos de la sección 3.3.
- **Auditoría de las pruebas manuales del 20/11:** revisé una por una las 5 facturas de Empresa Demostrativa y las 9 de MOJITO: ISV 15 % y 18 %, contabilidad cuadrada, inventario, numeración consecutiva y dos cierres de caja con diferencia 0.00.

## 6. Uso de inteligencia artificial

Se usaron dos asistentes: **Claude Code** (Anthropic) y **Codex** (OpenAI). Las cinco reglas del módulo 6 se aplicaron así:

| Uso | Qué se pidió | Qué se aceptó | Qué cambié o decidí yo | Qué se descartó | Cómo se verificó |
| :--- | :--- | :--- | :--- | :--- | :--- |
| Auditoría y corrección de cobro e impuestos (Codex) | Evaluar el análisis de arquitectura y corregir los riesgos | Plantillas fiscales nativas, anulación que reabre la orden, descuento con supervisor | Revisé el resultado con una auditoría independiente antes de aceptarlo | — | Suite completa y facturas reales de prueba |
| Diagnóstico de defectos (Claude Code) | Revisar mis facturas de prueba y explicar cada error | Causas y correcciones del ISV duplicado, precios ocultos y cuenta de tarjeta | Decidí qué corregir ahora y qué dejar para otra fase | Topar la propina: no aplica al negocio en Honduras | Pruebas automáticas nuevas y repetición manual con mesero y cajero |
| Limpieza de código (Claude Code) | Encontrar código sin uso o duplicado | Las eliminaciones con evidencia de que nadie las usaba | Elegí qué eliminar y qué conservar | Eliminar los certificados de regalo y el autopedido: se conservan para el kiosco y las cortesías | Búsqueda de referencias y suite completa |
| Documentación (Claude Code) | Borradores de arquitectura, decisiones y bitácora | La estructura de los documentos | Confirmé las fechas, la decisión sobre la hipótesis y el segundo flujo | — | Revisión propia de cada documento |

No se compartieron con los asistentes contraseñas ni datos reales de clientes.

## 7. Dificultades identificadas

- Separar lo que corresponde al módulo Restaurante de lo que corresponde al ERPNext de Grintsys: dos defectos (permiso de series SAR e ISV duplicado en el ticket) estaban en el código de la empresa y requieren su aprobación.
- Mantener un sitio de pruebas limpio: el entorno exigió configurar SSL del cliente de base de datos y evitar un ciclo de datos de prueba causado por POS Awesome.

## 8. Aprendizajes de la semana

Una regla de negocio repetida en dos lugares termina dando dos resultados: el impuesto se deducía en el menú y se calculaba en la factura, y la orden y la factura calculaban su total por separado. Dejar cada regla en un solo lugar, y reutilizar el mecanismo que ERPNext ya tiene, eliminó defectos en vez de agregar código.

## 9. Próximas actividades

- Pasar los cambios por el ciclo issue → rama → commits pequeños → pull request → revisión → merge, publicar y verificar en producción; release `semana-6`.
- Verificar en producción el servicio de tiempo real de la pantalla de cocina (S5-P1-02).
- Corregir el inventario de los combos con el mecanismo nativo de paquetes de productos (S5-P1-01), semana 7.
- Completar la ronda de 3 a 5 participantes del segmento (issue #13).
