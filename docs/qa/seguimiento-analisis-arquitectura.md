# Seguimiento de la revisión de arquitectura de Restaurante

Fecha de trabajo: 20/11/2026. Sitio: development. La aplicación orquesta las órdenes y conserva Sales Invoice, POS Profile, POS Opening Shift y POS Closing Shift como fuentes nativas. Las pruebas de facturación usan series transitorias de QA. Se ejecutan con `--app restaurant --skip-before-tests --skip-test-records` para evitar los preparativos globales de ERPNext.

| Hallazgo | Estado y decisión |
| --- | --- |
| R1. Cancelación | Se agregó un evento de Sales Invoice. ERPNext revierte la factura y sus movimientos. Restaurante desvincula y reabre la orden existente cuando la factura cancelada coincide con su vínculo, y sincroniza la mesa. |
| R2. Tarjetas de regalo | El cobro usa Certificado de Regalo y su pago a pasivo. El DocType anterior conserva el histórico y bloquea altas. Development carece de saldos anteriores. Revisar la conciliación de pasivos y códigos antes de migrar cualquier instalación que sí tenga saldos. Ver [canje nativo](canje-certificado-nativo.md). |
| R3. Pagos vacíos | Un total positivo requiere el importe recibido. Para un total cero, ERPNext necesita una fila de medio de pago con importe cero. |
| R4. Descuentos | El tope de POS Profile requiere aprobación de supervisor con motivo en el cobro. El máximo del Item se aplica también al descuento acumulado y respeta la validación nativa. |
| R5. Propina | BLOCKED. La cuenta y la base fiscal del servicio requieren decisión contable y validación tributaria local. |
| R6. Datos maestros | El cobro solo consulta las cuentas de cada medio de pago. Los medios se leen de POS Profile. Se retiró la API que generaba entradas de stock de demostración. |
| R7. Impuestos SAR | La precuenta usa tasas de las filas de Item Tax Template. Integración nativa aplicada. Se corrigió la premisa de precios inclusivos y se crearon plantillas nativas para precios netos. Se retiró la adaptación fiscal de validate. Las pruebas nuevas cubren ISV mixto, exoneración y descuentos. Ver [detalle fiscal](migracion-fiscal-nativa.md). |
| Cierre y arqueo | Se retiró la conciliación alternativa. El flujo exige el documento de cierre de POS Awesome. |
| Location | Se dejaron de exportar dos campos sin consumidores operativos. Las columnas de development estaban vacías y se preservaron. |
| Reportes | Ventas por Mesero y Modalidad consulta Sales Invoice respetando los permisos. Se comparó con las ventas históricas y se registró el reporte en Desk. El reporte por área necesita guardar ese dato en la factura para que un traslado posterior no cambie la clasificación histórica. Quedan pendientes propinas, cancelaciones y tiempos KDS. |
| Precios y promociones | PROPOSED. Verificar Pricing Rule con modificadores, precio inclusivo, clientes y descuentos antes de sustituir el cálculo del POS. El precio histórico de una orden no debe cambiar al consultarla o reimprimirla. |
| Refactor | Las reversiones y los certificados tienen módulos propios. Quedan pendientes la separación de los módulos grandes y la revisión individual de permisos elevados. Conviene mantener los contratos de endpoints mientras se mueven responsabilidades y comprobar sus consumidores. |
| Reglas LEAF | Sincronizadas las copias de exportación con 16 reglas y verificación en CI. El especialista adicional figura como auxiliar, en consonancia con el catálogo de 15 perfiles oficiales. |
| Rama e integración | La integración de la rama de ERPNext requiere confirmación del mantenedor de Grintsys. |
| Separación por empresa | La suite de aislamiento pasó sus 9 casos. En el navegador, el turno POS MOJITO HNL cargó la pestaña Órdenes y ORD-00087 no figuró en ese listado. |

## Camino nativo para la fase pendiente

Para activar Pricing Rule en Restaurante, ERPNext ofrece `get_item_details` y `apply_pricing_rule`. El piloto debe calcular con la empresa, cliente, lista, fecha, unidad y cantidades del pedido. Comparar los resultados de una orden normal, una con opciones pagadas, promociones por cantidad, un cupón y una cuenta dividida. Definir en qué momento se congela el precio y conservar el resultado en los documentos históricos. Facturación mantiene el cálculo nativo de Sales Invoice como fuente del total definitivo.

## Control de datos

VERIFIED en una conexión nueva: las huellas de 76 órdenes, 28 facturas del sitio, 11 turnos de apertura, 163 asientos y 20 movimientos de inventario coincidieron con la referencia anterior al cambio. La orden demostrativa citada conserva su empresa, estado y vínculo de factura. La serie de MOJITO seguía sin contador y sin documentos emitidos después de las pruebas de aislamiento, cocina y del primer ciclo de facturación QA.

## Superficie de cambios

- Restaurante: `restaurant/pos.py`, `restaurant/cash_count.py`, `restaurant/hooks.py`, `restaurant/invoice_events.py`, `restaurant/gift_certificates.py`, `restaurant/fixtures/custom_field.json` y el controlador de `Restaurant Gift Card`.
- Interfaz y reportes: página `restaurant_pos.js` y paquete `restaurant/restaurant/report/ventas_por_mesero_y_modalidad`.
- Pruebas: `test_checkout_acceptance.py`, `test_phase1_known_defects.py`, `test_item_configuration.py`, `test_kds.py`, `test_order_operations.py`, `test_qa_comprehensive_audit.py` y `tests/ui/precuenta_state.cjs`.
- Infraestructura: catálogo, manifiesto, orquestación, README y pares exportados del orquestador y perfil auxiliar. Verificador en `scripts/check_leaf_agent_export.py` y flujo en `.github/workflows/leaf-agent-export.yml`.

## Resultado de las pruebas

VERIFIED. 131 pruebas en Bench: aislamiento (9), arranque (8), configuración de artículos (29), cocina (28), operaciones de órdenes (35), aceptación de cobro (17) y cancelación y descuentos (5). También pasaron las cuatro pruebas JavaScript de precuenta y solicitud de autorización. La última comparación de huellas y serie se ejecutó tras finalizar las pruebas de facturación. El sitio respondió tras reiniciar Bench Web.
