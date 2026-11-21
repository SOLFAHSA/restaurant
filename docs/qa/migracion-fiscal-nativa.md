# Evaluación de la facturación fiscal nativa de Restaurante

**VERIFIED en development.** Se comparó la propuesta del informe de arquitectura del 19/11/2026 con ERPNext Grintsys en la rama feat/sar-ticket-registro-sag, commit b7eb588, y con la configuración disponible. Se calcularon facturas en memoria. Las plantillas temporales del segundo escenario se revirtieron al terminar. La comprobación no inserta ni somete facturas y no solicita folios.

## Camino nativo de ERPNext y Grintsys

- `erpnext/accounts/doctype/sales_invoice/sales_invoice.py`, `SalesInvoice.before_validate` llama `set_missing_item_tax_templates` y `adjust_exonerated_rates_and_validate_sar`. La primera omite la búsqueda cuando la categoría es Exonerado. Cuando la segunda desconoce la plantilla, usa el divisor 1.15. Por eso, en una factura exonerada con precios incluidos en el catálogo, se necesita conocer la plantilla de cada artículo.
- En la misma clase, `SalesInvoice.validate` llama `get_itemised_tax_info` después del cálculo nativo. ERPNext calcula los impuestos desde Sales Taxes and Charges Template, Item Tax Template y los importes de factura. La autorización y numeración siguen en el flujo nativo de Sales Invoice.
- La app mantiene su orquestación de comanda y cobro. El adelanto de la comanda ahora lee las tasas de `Item Tax Template Detail.tax_rate`, conservando 15 % como valor predeterminado de este flujo cuando no hay una plantilla utilizable.

## Configuración observada

Los dos perfiles operativos carecían de `taxes_and_charges`. Las plantillas de venta normales tenían una sola fila de ISV 15 % y precio sin impuesto incluido, mientras que Restaurante muestra precios con ISV incluido. Las plantillas de artículo de ISV 18 % apuntaban a la cuenta Débito Fiscal ISV 15 % de su empresa. La búsqueda nativa de plantillas para «Contribuyente» encontró 1 de 27 productos en Empresa Demostrativa y 0 de 27 en MOJITO.

## Resultados en memoria

Precios de catálogo de L 115, L 118 y L 100 para artículo de ISV 15 %, artículo de ISV 18 % y artículo exento, respectivamente.

| Escenario | Total | Resultado |
| --- | ---: | --- |
| Plantilla de venta actual y plantillas explícitas de artículo | L 371.49 | ISV 17.25 y 21.24 calculado encima del precio. Ambas tasas en la cuenta del 15 %. |
| Exonerado sin plantillas explícitas | L 289.57 | Base incorrecta para la línea al 18 % y reducción indebida de la línea exenta. |
| Exonerado con plantillas explícitas | L 300.00 | Base exonerada correcta. |
| Una línea exonerada de L 118 al 18 %, con su plantilla y 10 % de descuento por línea | L 106.20 | La base esperada es L 90.00. La rama actual omite el ajuste del precio incluido si la línea ya tiene descuento. |
| Plantillas temporales con precios incluidos y cuentas separadas | L 333.00 | Bases L 100/L 100/L 100 e ISV L 15/L 18 en las cuentas correspondientes. |
| Configuración temporal y 10 % o L 33.30 de descuento global | L 299.70 | Bases L 90/L 90/L 90, ISV L 13.50/L 16.20. |
| Configuración temporal y 100 % de descuento global | L 0.00 | Bases, impuestos y filas contables de impuesto en cero. |

**BLOCKED para eliminar la adaptación fiscal de Restaurante en el entorno actual.** Antes del retiro, inventariar la clasificación de los productos en cada empresa y asignar plantillas nativas compatibles. La plantilla de factura debe incluir los impuestos en el precio y tener cuentas separadas para ISV 15 %/18 %. Probar también IVA cero, artículo exento y exonerado con sustento. Las pruebas de paridad deben cubrir la combinación exonerado y descuento por línea, cálculo en memoria y emisión con CAI de prueba, Ticket SAR, cuentas de GL y reversión. Este último grupo de pruebas sigue pendiente.

## Integración aplicada y verificada en desarrollo

La comparación posterior del contrato real de la orden corrigió una premisa de la primera evaluación. Restaurant Order guarda `base_rate` y `rate` netos y suma el ISV a su total. La prueba inicial entregó precios brutos directamente a Sales Invoice. Sus resultados describían esa entrada, pero no el contrato de entrada real del módulo.

Se reutilizan los DocTypes nativos Sales Taxes and Charges Template e Item Tax Template. Las plantillas nuevas usan precios netos, cuentas existentes separadas del 15% y 18%, y las dos tasas explícitas por artículo para que una línea no herede la otra tasa. La exoneración recibe una plantilla de artículo EXENTO de tasa cero y la categoría fiscal Exonerado, conservando los precios netos y los descuentos. Grintsys interpreta esa plantilla como precio que no necesita otra división. El resumen exonerado lo determina Sales Invoice desde la categoría fiscal. Los documentos de sustento se configuran en Customer y la orden de compra exenta se proporciona en el cobro.

Se retiraron de Restaurante `_resolve_tax_account`, `_sync_sar_tax_summary`, `preserve_restaurant_invoice_taxes`, el hook fiscal de validate y las tasas y filas ISV construidas a mano. El checkout selecciona las plantillas y deja que ERPNext calcule, asigne CAI, registre GL/SLE y revierta el documento. Se conserva el cargo Actual de propina, cuyo tratamiento contable sigue pendiente de la decisión de contabilidad.

La configuración se crea de manera idempotente mediante `restaurant.tax_configuration.configure_company(company)`. Se comprobó por huellas que los documentos históricos conservaron sus datos durante la configuración. El helper reutiliza las cuentas nativas y no altera las plantillas fiscales anteriores. Otro sitio debe preparar esa configuración antes de habilitar el checkout actualizado.

VERIFIED. Las pruebas nativas con series transitorias de QA validaron impuestos mixtos y descuento global, dos cuentas separadas en GL, Ticket, cancelación y reapertura de orden, exoneración con descuento por línea y global, y descuento del 100%. Los datos fiscales de MOJITO no se usan para emitir estas pruebas.

### Cierre de verificación de integración

VERIFIED. Se aprobaron 94 casos distintos durante esta integración: aceptación de cobro (16), paridad fiscal nativa (4), numeración fiscal (11), cocina (28) y operaciones de cuentas (35). Las dos primeras ejecuciones de exoneración identificaron la falta de sustento del cliente de QA; se configuró en el maestro de prueba y la prueba final pasó con las validaciones SAR activas.

VERIFIED. Se repitió configure_company por empresa con el mismo resultado, sin crear duplicados. Las huellas finales de 76 órdenes, 28 facturas, 11 turnos, 163 GL Entry y 20 Stock Ledger Entry coinciden con la referencia anterior. La serie de MOJITO conserva cero facturas y carece de contador. Bench Web se reinició desde VS Code, se limpió la caché y el servidor respondió pong. El core ERPNext conserva su diff previo a esta integración.

Archivos de esta integración: restaurant/pos.py, restaurant/hooks.py, restaurant/tax_configuration.py, restaurant/tests/test_native_fiscal_parity.py, restaurant/tests/test_checkout_acceptance.py, restaurant/tests/test_item_configuration.py, restaurant/tests/test_kds.py y restaurant/tests/test_order_operations.py. Se actualizaron este informe y seguimiento-analisis-arquitectura.md.

DICTAMEN: APROBADO CON OBSERVACIONES para la integración en development. En instalaciones adicionales se debe preparar la configuración nativa por empresa y validar el catálogo de tasas y el sustento de clientes exonerados. La clasificación tributaria de los productos y el tratamiento de la propina requieren validación tributaria local.
