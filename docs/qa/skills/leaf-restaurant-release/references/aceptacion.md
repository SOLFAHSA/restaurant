# Matriz de aceptación de Restaurante

## 0. Preparar datos y ambientes

Registra rama, commit y estado de cada repositorio, sitio, puerto, empresa, sucursal, almacén, tipo de servicio, rol y perfil POS. Prepara en desarrollo o staging datos controlados de artículos, impuestos, facturación y turnos. Lleva un inventario de cuentas abiertas, facturas enviadas y anuladas, autorización fiscal, configuración de artículos y stock, pagos, histórico de impresión y enlaces. Registra totales agregados y compara antes y después si hay cambios. Usa en producción únicamente lecturas autorizadas y sin datos personales en la evidencia.

## 1. Facturación, dinero e inventario directo

| Caso | Criterio de aceptación |
|---|---|
| CAI y serie | `Sales Invoice` usa la serie autorizada para la empresa y punto de emisión configurados, el CAI, el rango y la fecha límite de la autorización aplicable. Probar primer y último folio, fuera de rango, vencido, agotado, ausente, renovación y dos cajas compitiendo por el último folio. Comprobar por separado lo que muestra la interfaz y lo que persiste e imprime la factura enviada. Sin autorización válida, conservar la orden y rechazar la emisión sin efectos parciales. |
| Precuenta y prefactura | Previsualizar o imprimir un documento identificado como informativo. Puede referenciar la orden y el consumo. Repetir la operación y comprobar que no cree factura fiscal, folio, cobro, GL ni SLE. Si existe borrador, validar cómo se recupera o descarta y bloquear impresión fiscal hasta el envío. Probar mesero y cajero desde Desk. |
| Factura enviada y reimpresión | Verificar emisor, RTN y dirección, serie/correlativo, fecha, autorización y vigencia, datos de cliente y referencias de exención o exoneración cuando apliquen, líneas, cantidades, precios, descuentos, bases, ISV, moneda y total según la modalidad aprobada. Conciliar el documento nativo, impresión web y térmica. Reimprimir una histórica con sus datos originales. |
| Impuestos y descuentos | Probar 15%, 18%, exento y exonerado con soporte aplicable. Usar una misma factura mixta y verificar cada base, tasa, impuesto y GL. Cubrir precios incluidos/excluidos si se ofrecen, descuento de línea y global, límites y aprobación, cambios del perfil POS y conciliación de ticket. Usar importes esperados fijados por el caso, independientes de la vista previa. |
| Propina | Partir de cero. El 10% es una sugerencia comercial voluntaria, con opción de cero o monto elegido si el procedimiento aprobado lo admite. Verificar aceptación afirmativa, separación del cargo fiscal, registro, liquidación en caja y reversión. Obtener validación tributaria local sobre base, soporte y tratamiento antes de habilitarlo. Con la función deshabilitada, verificar el rechazo en servidor y el tratamiento de órdenes abiertas con una propina registrada. |
| Cobro, saldo y ceros | Verificar efectivo exacto, cambio sin desajustes, pago múltiple, insuficiente, ausente y descuentos o tarjeta de regalo si están habilitados. Distinguir saldo por cobrar cero, vuelto cero, diferencia de arqueo cero, stock cero, cantidad de línea inválida y cortesía o cuenta de valor cero. Cero en saldo, efectivo o vuelto debe conservar su significado en factura, ticket y cierre. Acordar tratamiento y autorización de cortesías, incluida su salida de stock cuando corresponda. |
| Item inventariable y almacén | Con cantidad cero o insuficiente, rechazar facturación por el servidor en el almacén del perfil. Con existencia exacta, emitir y dejar saldo cero. Con dos cajas sobre la última unidad, confirmar a lo sumo una venta. Probar otro almacén con stock, UOM, restricciones globales y por artículo de inventario negativo y errores de configuración. |
| Item sin control y venta mixta | Admitir platillo o servicio no inventariable sin exigir saldo. En factura mixta únicamente las líneas o componentes inventariables generan SLE. Consultar el Kardex por fecha/hora, producto, almacén, cantidad y comprobante. Seguir el vínculo del comprobante a la orden. |
| Atomicidad y reversión | Folio, orden, pagos, GL y SLE deben conciliar tras éxito. Probar reintento, doble clic y recuperación tras error. Comparar efectos ante un fallo de stock, fiscal o contable. Probar anulación o devolución nativa según política y verificar efecto en mesa, turno, Kardex y caja sin duplicar movimientos. |

Ejemplo controlado con precios excluidos y sin descuento ni propina. Tres renglones de L 100 gravados al 15%, gravados al 18% y exentos deben producir L 33 de ISV distribuido en dos tasas y L 333 de total. Fija resultados independientes para el descuento, el precio incluido y un caso integrado con las tres bases, descuentos de línea y global, propina voluntaria separada según política, efectivo, vuelto y arqueo. Registra el orden de cálculo aprobado y concilia factura, soporte de propina, GL y caja.

## 2. Operación, perfiles y sucursales

| Perfil o flujo | Criterio de aceptación |
|---|---|
| Mesero | Abre y trabaja cuentas autorizadas, agrega productos y envía comandas. Puede generar precuenta. Verificar que factura, arqueo, configuración, descuentos excepcionales y cancelaciones de partidas enviadas queden reservados a los permisos aprobados. |
| Cajero completo y directo | Cobra con su turno y perfil. El directo usa el circuito de venta sin asignar mesas ni administrar cuentas ajenas. Ambos deben tener independientes las acciones de emisión, reimpresión y cancelación. |
| Turno, arqueo y cierre | Probar apertura y apertura duplicada, turno propio, ajeno, anterior o cerrado, cobro sin turno, ingresos y retiros, arqueo ciego, diferencias positivas, negativas y cero, cierre con pendientes, concurrencia y reintentos. Conciliar por medio de pago y comprobar que el cierre procesa cada factura una sola vez. |
| Supervisor y administrador | Supervisor autoriza excepciones con motivo, identidad y sucursal. Administrador fiscal mantiene perfiles, series y cuentas con permisos separados de caja. Verificar trazabilidad del intento y de la resolución, incluidos rechazos. |
| Cocina | Ve comandas autorizadas por estación y sucursal y actualiza sus etapas conforme al permiso operativo. Verificar que cocina pueda operar con el mínimo de datos del cliente, sin permisos de caja ni configuración fiscal. |
| Salón y cuentas | Crear área y mesa con el rol autorizado. Probar mesa inactiva, dos cuentas en una mesa, dividir cantidades y montos, transferir o fusionar conservando progreso de cocina, total, descuentos y autorizaciones. La mesa se libera de acuerdo con las cuentas que siguen abiertas. |
| Para llevar y entrega | Abrir, guardar, enviar a cocina y cobrar sin mesa cuando corresponda. Probar cliente explícito, contacto, destino y horario cuando sean requisitos de entrega. Verificar persistencia y control en servidor. |
| KDS, comandas y sucursal | Enviar solo partidas correspondientes, conservar etapas al pagar o dividir, impedir duplicados y exigir autorización de reimpresión según política. Aislar listado, acciones, pantalla, eventos, impresora, turno y caja entre sucursales. Probar estaciones homónimas en el equipo térmico del ambiente. |

## 3. Recetas y liberación

- Distingue el platillo no inventariable, el inventariable directo, el fabricado con BOM y Stock Entry y el combo que descarga componentes por un mecanismo nativo comprobado. Verifica unidades, extras, sustituciones, mermas, faltantes y reversión. Elige un solo momento de descarga por componente y conserva configuraciones e históricos.
- Orden de corrección recomendado. Primero CAI, ticket, impuestos, descuentos y pagos junto al stock directo obligatorio. Después roles, caja y circuitos de salón/cocina de la salida. Evalúa recetas, entrega o multisucursal adicional según su criticidad y si se habilitarán. Los prerrequisitos críticos de una fase deben estar aprobados antes de habilitarla.
- En staging, repite los casos críticos con el artefacto de salida y configuración representativa. Adjunta un plan de reversión de código, configuración y datos, con responsables y una prueba de recuperación. Si falta evidencia fiscal, de caja, de inventario o de permisos para un camino habilitado, emite dictamen RECHAZADO para ese alcance e identifica los casos inaccesibles como BLOCKED.

## Referencias oficiales

- [SAR, régimen de facturación](https://www.sar.gob.hn/facturacion/).
- [SAR, Ley del Impuesto Sobre Ventas y documentación](https://www.sar.gob.hn/impuesto-sobre-ventas-isv/).
- [SDE, Reglamento de Protección al Consumidor, artículo 78.4](https://sde.gob.hn/wp-content/uploads/2022/03/Acuerdo-084-2021_ley-de-proteccion-al-consumidor_27-de-dicimbre-del-2021-4.pdf).
