# 002 · La factura es la fuente de verdad de los totales de una orden facturada (20/11/2026)

**Estado:** Aceptada

## Contexto

El descuento global se aplica en el momento del cobro y ERPNext lo calcula sobre el total de la factura. La orden del restaurante, en cambio, recalculaba sus totales sin ese descuento. En la factura `000-002-01-00081505`, con 5 % de descuento, la factura decía **L 16.94** y la orden seguía en **L 17.83**. Cualquier pantalla o reporte que leyera la orden mostraba un monto que nunca se cobró.

## Decisión

Cuando la factura queda emitida, la orden copia sus totales: base gravada, ISV 15 %, ISV 18 %, exento y total. Si la factura se anula, la orden vuelve a calcular sus totales desde sus propias líneas, sin el descuento de la factura anulada. No se agregan campos nuevos.

## Alternativas consideradas

- **Replicar en la orden el cálculo del descuento de ERPNext.** Descartada: el descuento sobre el total, con impuesto incluido, reparte montos entre bases e ISV. Repetir esa lógica sería un segundo motor de cálculo.
- **Agregar campos de descuento a la orden y recalcular en cada guardado.** Descartada por ahora: duplica la lógica y exige cambio de esquema sin aportar más que copiar el resultado de la factura.
- **Dejar la diferencia.** Descartada: confunde al personal y a los reportes.

## Consecuencias

- La orden facturada y su factura siempre muestran el mismo total, sin un cálculo duplicado.
- **Costo:** después de facturar, el subtotal de la orden pasa a ser la base con descuento; el monto del descuento global se consulta en la factura.
- Antes de cobrar, la precuenta aún no refleja un descuento global, porque este se aplica en el cobro. Mostrarlo en la precuenta queda como mejora para una próxima fase.
- Si recalcular la orden al anular falla (por ejemplo, un producto quedó sin plantilla de impuesto), la anulación nativa no se bloquea: el problema se reporta en el siguiente guardado de la orden.

**Evidencia:** `restaurant/pos.py` (`_sync_order_totals_from_invoice`), `restaurant/invoice_events.py` (`_restore_order_totals`), pruebas `restaurant/tests/test_order_invoice_totals.py`.
