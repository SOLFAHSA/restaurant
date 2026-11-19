# Pruebas con usuarios reales — Semana 5 (MVP)

**Proyecto:** Módulo Restaurante para LEAF ERP v14  
**Empresa receptora:** Grintsys  
**Entorno evaluado (HTTPS):** `https://leaf-dev.hsjddhn.com/#login`  
**Hipótesis evaluadas:** `H1` (coordinación operativa salón–cocina–caja) y `H2` (integración sobre el motor nativo de ERPNext v14), definidas en [`docs/vision.md`](vision.md).

---

## 1. Objetivo de la prueba

Comprobar si usuarios operando con roles reales de restaurante (**Mesero** y **Cajero**, más **Supervisor** para autorizaciones) pueden completar el ciclo diario sin asistencia técnica ni permisos de administrador: abrir turno, tomar cuentas en mesa, enviar comandas a cocina (KDS), imprimir pre-cuenta, aplicar descuentos permitidos, solicitar cancelaciones autorizadas y cerrar el arqueo de caja.

---

## 2. Guion de prueba aplicado

| Paso | Rol participante | Tarea solicitada | Criterio de éxito esperado |
| :-: | :--- | :--- | :--- |
| **1** | Mesero / Cajero | Iniciar sesión con su usuario operativo y navegar al módulo **Restaurante**. | Acceso directo al Workspace *Restaurante* sin ver módulos administrativos ajenos (Contabilidad, Build, Integraciones). |
| **2** | Cajero | Abrir turno de caja (`POS Opening Shift`) y consultar cuentas creadas por meseros. | El cajero visualiza las cuentas en curso de los meseros para poder cobrarlas. |
| **3** | Mesero | Seleccionar mesa, agregar platillos con opciones/notas y enviar comanda a cocina. | La orden aparece en Cocina KDS (`restaurant-kds`) y la mesa pasa a estado *Ocupada*. |
| **4** | Mesero | Generar la **Pre-cuenta** para el cliente desde el modal de acciones. | Puede imprimir o mostrar la pre-cuenta sin tener acceso al botón *Pasar a Facturar*. |
| **5** | Cajero | Aplicar un descuento en una línea o en el total y emitir el cobro/factura. | El descuento se aplica dentro de la configuración habilitada del POS y se registra la `Sales Invoice`. |
| **6** | Cajero / Mesero | Intentar cancelar una orden o eliminar un platillo enviado a cocina. | El sistema bloquea la acción directa y exige PIN de un **Supervisor** autorizado, registrando el motivo en bitácora. |
| **7** | Cajero | Consultar **Cocina KDS**, **Comandas** y registrar el **Arqueo de Caja**. | Acceso limpio sin alertas de permisos faltantes y cálculo esperado vs. contado correcto. |

---

## 3. Hallazgos registrados y severidad

| ID | Severidad | Hallazgo observado durante las pruebas | Causa raíz identificada | Acción aplicada |
| :-: | :---: | :--- | :--- | :--- |
| **H-01** | **Alta** | El usuario `cajero.prueba` no veía las cuentas abiertas por los meseros en el POS. | La configuración de perfiles y visibilidad compartida de cuentas abiertas no estaba alineada entre roles de salón y caja. | Se ajustaron los perfiles de módulo y visibilidad operativa para que el cajero consulte y cobre cuentas abiertas por meseros. |
| **H-02** | **Alta** | Al abrir **Cocina KDS**, **Comandas** o **Reportes** como cajero aparecían mensajes de *"No permitido / sin acceso a este documento"*. | Faltaban permisos `read`/`select` en `Restaurant Preparation Display`, `Restaurant Command` y `Custom Role` de reportes para `Restaurant Cashier`, además del `Module Profile` restringido. | Se configuraron los `Module Profile` (`Mesero (Salón)`, `Cajero (Completo)`, `Cajero (Facturación Directa)`) y la matriz de permisos en `setup.py`. |
| **H-03** | **Alta** | El cajero no tenía habilitada la opción de aplicar descuentos por línea o globales en el POS. | `allow_line_discount` y `allow_global_discount` en `Restaurant Settings` y `allow_discount_change` en `POS Profile` estaban desactivados. | Se habilitaron en configuración y se restringió el botón `%` del teclado numérico para que solo lo use un rol con permiso de facturación (`canInvoice()`). |
| **H-04** | **Alta** | En pruebas de seguridad sobre API, un payload manipulado podía enviar precios/tasas de impuesto propios o invocar endpoints de configuración. | `validate_order` aceptaba `base_rate`/`tax_rate` del cliente y varios endpoints usaban solo `_require_pos_user()`. | Se forzó el recálculo de precios, opciones e ISV desde base de datos en `validate_order`, se restringieron endpoints administrativos a `Restaurant Manager` y se agregó `FOR UPDATE` en Gift Cards. |
| **H-05** | **Media** | El mesero no podía abrir la **Pre-cuenta** porque el botón de acciones estaba oculto para su rol. | `openActionsModal` estaba bloqueado para roles sin permiso de facturación. | Se habilitó la pre-cuenta para meseros manteniendo oculto el botón *Pasar a Facturar*. |
| **H-06** | **Baja** | El loader de transición entre pantallas mostraba texto técnico sobre el ícono animado. | Estilos y plantilla de carga en `restaurant_theme.css` / `restaurant_pos.js`. | Se dejó únicamente el logotipo animado centrado (`leaf.gif`) de forma limpia. |

---

## 4. Decisión sobre las hipótesis

- **Hipótesis `H1` (Necesidad operativa de coordinar salón, cocina y caja):** **VALIDADA CON ITERACIÓN.**  
  La operación de extremo a extremo funcionó con los usuarios de prueba una vez corregidos los hallazgos `H-01` a `H-05`. Se confirma que el restaurante necesita separación estricta entre **Mesero**, **Cajero** y **Supervisor** mediante `Module Profile` y autorización por PIN en servidor, no solo ocultando botones en pantalla.
- **Hipótesis `H2` (Integración sobre el motor nativo de LEAF ERP / ERPNext v14):** **VALIDADA PARCIALMENTE (condicionada para salida a producción).**  
  La facturación con `Sales Invoice`, turnos de caja (`POS Opening Shift`), métodos de pago y cálculo de ISV operan correctamente sobre ERPNext. Sin embargo, para liberar el sistema en producción real queda pendiente:
  1. Definir con Grintsys la descarga automática de inventario y explosión de recetas (`update_stock`) al facturar.
  2. Cargar los rangos y documentos **CAI** reales de producción antes de desactivar el respaldo de demostración.


---

## 5. Revisión frente al Módulo 5 realizada el 18/11/2026

**Estado de revisión** ANALYZED. Este complemento registra la revisión realizada en semana 6 y conserva el texto histórico de semana 5. La fuente académica es el PDF del Módulo 5 entregado por Manuel, páginas 1 a 4, 8 a 9 y 12 a 13.

### 5.1. Correspondencia de requisitos y evidencias

| Requisito del módulo | Evidencia disponible | Pendiente de acreditar |
|---|---|---|
| MVP publicado y usado por 3 a 5 personas del segmento | URL histórica y descripciones de perfiles operativos en este documento | Fecha de cada sesión, versión utilizada, participantes únicos y vínculo con el segmento. |
| Tareas con metas, observación sin ayudar y pensamiento en voz alta | Guion operativo de siete tareas | Resultado individual, asistencia, duración cuando se mida y citas reales. |
| Hallazgos con severidad y frecuencia | H-01 a H-06 con severidades históricas Alta, Media y Baja | Clasificación del curso Bloqueante, Grave, Menor y Cosmético, sustentada en el efecto observado. Frecuencia por participantes expuestos. |
| Decidir si la hipótesis se sostiene, se ajusta o se cae | Conclusiones históricas H1/H2 en sección 4 | Métrica, umbral y evidencia por persona para fundamentar el dictamen. |
| Issues priorizados para semanas 6 a 9 | Issues M5-01 a M5-06 y M6-01 a M6-07 publicados y enlazados en el backlog | Responsables confirmados y aceptación. Publicación y enlaces verificados. |
| Hito semana-5 | VERIFIED. Tag remoto semana-5 encontrado el 18/11/2026 | La consulta de GitHub Release devolvió 404. Confirmar el formato de entrega requerido y acreditar la versión desplegada. |
| Retos académicos | Su realización se controla en la plataforma del curso | Registro del propio estudiante. |

### 5.2. Precisión sobre las hipótesis

La [visión inicial](vision.md), sección 6, dejó las métricas por definir. Sus hipótesis H1, H2 y H3 son cualitativas. Las conclusiones de la sección 4 de este documento se conservan como interpretación histórica. La decisión académica con métrica y umbral queda pendiente de completar.

**PROPOSED para la siguiente ronda de pruebas.** Registrar antes de ejecutar las sesiones el alcance y estos criterios de trabajo con revisión del tutor o responsable.

- H1. Medir la proporción de participantes del segmento que terminan las tareas operativas asignadas a su rol sin ayuda. Umbral propuesto del 80% por tarea, con una muestra total de 3 a 5 personas únicas. Registrar el numerador y denominador de cada tarea.
- H2. Medir la conciliación de cada transacción válida de la ronda. Umbral propuesto del 100% entre orden, factura, impuestos, cobro y registros nativos aplicables, con cero duplicados. Los rechazos esperados se registran como casos negativos.
- H3. Revisar con los responsables si el alcance efectivamente probado permite demostrar el objetivo del MVP dentro del tiempo disponible.

La decisión se emitirá con los resultados observados y la métrica acordada antes de las siguientes pruebas. Para las sesiones históricas, recuperar la evidencia disponible con su fecha real.

### 5.3. Nuevos hallazgos y verificaciones de semana 6

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

### 5.4. Seguimiento y programación

El [backlog de mejoras](backlog-mejoras.md) contiene las fichas y enlaces de los 13 issues publicados con origen, severidad propuesta, estado, procedimiento y criterio de cierre, junto con el plan de semanas 6 a 9 y la plantilla de nuevas incidencias.

Para cada issue se conservará la relación con el hallazgo, el cambio real, la evidencia de prueba y la aceptación de la persona usuaria o responsable. Se registrarán tanto los defectos ya corregidos como las mejoras pendientes con su fecha real.

**VERIFIED. Publicación autorizada por Manuel.** Se crearon y comprobaron los [issues #1 a #13](https://github.com/SOLFAHSA/restaurant/issues), con coincidencia exacta frente a los borradores aprobados. El registro de publicación y los enlaces individuales están en el backlog. Todos continúan abiertos con su aceptación pendiente.

**VERIFIED. Aceptación del recorrido sin recarga.** Manuel confirmó en el seguimiento de esta sesión que pudo generar la precuenta, continuar y facturar sin actualizar la página ni presionar F5. La confirmación está registrada en el [issue #10](https://github.com/SOLFAHSA/restaurant/issues/10), que continúa en validación final por los demás criterios de cierre.

**VERIFIED. Avance técnico del issue #12.** La matriz de cobro y cierre temporal aprobó seis casos y detectó un fallo en descuento global del 100%, DEF-2026-017. Los resultados y la restauración del entorno están en el [informe de aceptación](qa/aceptacion-cobro-caja-2026-11-18.md). La aceptación con participantes operativos sigue pendiente.

**VERIFIED. Corrección posterior del issue #12.** Tras la autorización de Manuel, DEF-2026-017 se corrigió en development. Se aprobaron 17 casos de aceptación y 51 pruebas distintas entre las suites ejecutadas. Se comprobó la preservación de las 17 facturas existentes y sus GL/SLE. El [informe actualizado](qa/aceptacion-cobro-caja-2026-11-18.md) conserva la evidencia inicial y la posterior. La aceptación con perfiles operativos y la impresión física continúan pendientes.

**VERIFIED. Configuración del emisor recibida del responsable.** Se creó una Company independiente y una Address principal vinculada mediante Dynamic Link en development. Se guardaron los datos proporcionados por el usuario y se conservaron los ceros iniciales del RTN. Una vista previa sin emisión del Ticket verificó razón social, RTN, dirección, ciudad y teléfono. La nueva empresa tiene cuentas, almacenes, centros de costos y cuenta de efectivo nativos. El aviso del generador de departamentos por diferencia de idioma se resolvió ejecutando el generador nativo con la traducción existente.

La huella de las 17 facturas existentes y sus GL/SLE coincidió antes y después. El perfil y los turnos de demostración continúan asociados a su empresa histórica.

**Pendiente** Recibir el CAI, prefijo fiscal, número inicial, número final y fecha límite de emisión para completar un perfil POS propio. El campo prefix es obligatorio en POS Profile. Después corresponde comprobar la factura emitida y su ticket desde ese perfil.

**Tratamiento de evidencia** Los datos concretos del emisor están guardados en development. El seguimiento público conserva esta verificación sin reproducir esos datos.

**VERIFIED. Configuración fiscal completada el 19/11/2026.** El responsable proporcionó los datos complementarios de declaración y recepción. Se guardó el CAI nativo y se comprobó estado Active, fechas y rango contra los datos recibidos. Se registró la serie en Document Naming Settings y se creó el perfil POS propio de la empresa con cuentas, centro de costos, almacén y dirección de esa empresa.

La verificación en una conexión nueva confirmó que el perfil está activo y aparece en get_pos_bootstrap. Se habilitó Efectivo como medio inicial con cuenta propia. Se configuraron alertas preventivas a 30 días y 100 folios disponibles. La vista previa del Ticket mostró emisor, CAI, rango y vencimiento correctos.

La lógica nativa confirmó el primer folio esperado. La serie sigue sin contador ni facturas y conserva su rango completo de 2,000 folios en development. Las 17 facturas existentes y sus GL/SLE conservaron la huella previa.

**Pendiente de aceptación operativa** Abrir un turno del perfil de la nueva empresa y comprobar la factura emitida y su impresión en el flujo operativo. Los turnos abiertos actuales pertenecen a la empresa demostrativa.

Los valores concretos de la autorización fiscal están almacenados en development. El seguimiento público contiene esta evidencia técnica.
