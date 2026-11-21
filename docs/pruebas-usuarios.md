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

### 5.3. Seguimiento posterior

Las verificaciones técnicas, el seguimiento de issues y la configuración fiscal realizados durante la semana 6 se registran en la [bitácora de la semana 6](bitacora/semana-6.md), para no mezclar el trabajo de esa semana con la evidencia de la semana 5.

---

## 6. Participantes del segmento — semana 5 (9 al 15 de noviembre de 2026)

Registro reconstruido el 20/11/2026 a partir de las sesiones y observaciones recibidas durante la semana 5. Las citas son paráfrasis del desarrollador a partir de la conversación, no transcripciones textuales: no se grabó audio. Los participantes se identifican sin nombre.

| Participante | Perfil | Fecha | Modalidad |
| :--- | :--- | :--- | :--- |
| **Participante 1** | Responsable de la empresa receptora; uso del POS como encargado de restaurante | 12 y 13 de noviembre | Uso directo del punto de venta y de Inventario, varias repeticiones |
| **Participante 2** | Dueño de restaurante interesado en adoptar el módulo | 11 de noviembre | Reunión y uso del sistema en facturación y configuración |

### 6.1. Hallazgos con la escala del curso

| Ref. | Participante | Hallazgo | Paráfrasis | Tipo | Severidad | Frecuencia | Estado |
| :--- | :---: | :--- | :--- | :--- | :--- | :--- | :--- |
| **S5-P1-01** | 1 | Al facturar un platillo configurado como combo ("Menú combinado de hamburguesa"), el Kardex no descuenta los componentes. | "Facturé el combo y en inventario no rebajó la existencia de lo que lleva." | Defecto | **Grave** | 1 de 2 participantes; reproducido en varias pruebas | Pendiente. Candidato a reutilizar *Product Bundle* nativo. |
| **S5-P1-02** | 1 | La pantalla de cocina (KDS) y la de estado de órdenes no se actualizan en tiempo real al pasar a *Listo* o *Completado*; hay que recargar con F5. | "Cuando pasa a listo no se actualiza, tengo que darle F5." | Defecto | **Grave** | 1 de 2; repetido en varias órdenes | Corrección de tiempo real en el commit `8c69600` (17/11, semana 6). Pendiente verificar en producción que el servicio de tiempo real esté activo. |
| **S5-P1-03** | 1 | Registrar una **cortesía de la casa**: orden que el restaurante absorbe, sin cobro al cliente, con descarga de inventario. | "Si hay un inconveniente con un cliente, que el restaurante lo pueda dar como cortesía y se rebaje el inventario." | Mejora (`mejora`) | — | 1 de 2 | Pendiente para una próxima fase. Requiere definición contable. |
| **S5-P2-01** | 2 | El mesero debe pedir el PIN del supervisor o gerente para eliminar una orden o un producto ya enviado a cocina. | "Que el mesero le pida el código al supervisor que está de turno." | Mejora (`mejora`) | — | 1 de 2 | Implementado en el commit `ebf96a8` (14/11). Pendiente confirmar si debe limitarse al supervisor del turno activo. |
| **S5-P2-02** | 2 | Cada rol debe ver solo las opciones que le corresponden. | "Que el mesero no tenga todos los accesos." | Mejora (`mejora`) | — | 1 de 2 | Implementado con perfiles de módulo por rol (ver H-02). |
| **S5-P2-03** | 2 | Propina con monto libre además del 10 % sugerido. | "Hay clientes que dejan un monto que no es el 10 %." | Mejora (`mejora`) | — | 1 de 2 | Implementado: porcentaje o monto fijo. |
| **S5-P2-04** | 2 | Seleccionar en la configuración los medios de pago (tarjeta de crédito, transferencia), no solo efectivo. | "Que salga tarjeta y transferencia, no solo efectivo." | Mejora (`mejora`) | — | 1 de 2 | Implementado en la configuración del POS (commit `5443ae1`, 14/11). |
| **S5-P2-05** | 2 | Arqueo de caja con denominaciones para cuadrar faltantes y sobrantes. | "Que el cajero pueda cuadrar su caja con lo que contó." | Mejora (`mejora`) | — | 1 de 2 | Implementado en el commit `1502ec2` (14/11). |
| **S5-P2-06** | 2 | Enviar facturas por WhatsApp. | "Mandar algunas facturas por WhatsApp." | Mejora (`mejora`) | — | 1 de 2 | Parcial: opción en la configuración y enlace para compartir la factura; sin envío automático. |
| **S5-P2-07** | 2 | Fondo de pantalla cuando el POS queda inactivo un tiempo configurable. | "Que aparezca un wallpaper si no se usa el punto de venta." | Mejora (`mejora`) | — | 1 de 2 | Implementado en Restaurant Settings. |

**Resumen de severidad:** 0 bloqueantes, 2 graves (S5-P1-01 y S5-P1-02), 0 menores, 0 cosméticos y 8 mejoras solicitadas.

### 6.2. Decisión sobre la hipótesis

**Decisión de Manuel (20/11/2026).** La muestra es de 2 participantes, por debajo de los 3 a 5 que pide el curso, y la visión inicial no fijó métrica ni umbral (ver sección 5.2). Con esa limitación, la decisión es:

- **H1 (coordinar salón, cocina y caja): se ajusta.** El problema existe y los dos participantes usaron el flujo completo, pero dos defectos graves afectan la operación (inventario de combos y actualización en tiempo real de cocina). Se mantiene el *qué* y se corrige el *cómo*.
- **H2 (integración sobre ERPNext): se sostiene con condiciones.** La facturación, el arqueo y los medios de pago operan sobre los documentos nativos; los combos deben pasar por el mecanismo nativo de inventario.

La siguiente ronda (issue #13) completará de 3 a 5 participantes con la métrica de la sección 5.2.
