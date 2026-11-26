# Reporte técnico: supuesto "ISV duplicado en el ticket"

- **Fecha:** 2026-11-24
- **Repositorio revisado:** `Grintsys/erpnext14` (`version-14`), sin cambios
- **Estado de evidencia:** VERIFIED (caso ejecutado en el sitio limpio `test_restaurant`, con rollback)
- **Conclusión:** no es un defecto de `sales_invoice.py` ni del formato `Ticket`. Es configuración: precio de lista **con ISV incluido** facturado con una plantilla de impuestos de **precio neto** (`included_in_print_rate = 0`). No se propone ningún cambio en `erpnext14`.

## Caso exacto y reproducible

Mismo producto, misma lista de precios, misma `Item Tax Template`; solo cambia `included_in_print_rate` de la `Sales Taxes and Charges Template`.

| Dato | Valor |
| :--- | :--- |
| Producto | `Hamburguesa clásica` (no inventariable) |
| Precio de lista | L 115.00 (el comercio lo publica con ISV incluido) |
| `Item Tax Template` | `Restaurante ISV 15%`: Débito Fiscal ISV 15% = 15, Débito Fiscal ISV 18% = 0 |
| Plantilla de venta | 2 filas `On Net Total`: ISV 15% (15) y ISV 18% (18) |
| Cliente | `Contribuyente`, sin descuentos, `disable_rounded_total = 1` |

### Resultado A: plantilla con `included_in_print_rate = 0` (precio neto)

```json
{
  "item_rate": 115.0, "item_net_rate": 115.0,
  "net_total": 115.0, "taxed_amount_15": 115.0, "isv_15": 17.25,
  "grand_total": 132.25
}
```

Ticket renderizado (extracto):

```
GRAVADO 15% L. 115.00   IMPTO. 15% L. 17.25   TOTAL FACTURA L. 132.25
**CIENTO TREINTA Y DOS LEMPIRAS CON 25/100**
```

El cliente esperaba pagar L 115.00 y ve L 132.25: el ISV se suma **encima** de un precio que ya lo incluía. Esto es lo que se percibía como "ISV duplicado".

### Resultado B: plantilla con `included_in_print_rate = 1` (precio con ISV incluido)

```json
{
  "item_rate": 115.0, "item_net_rate": 100.0,
  "net_total": 100.0, "taxed_amount_15": 100.0, "isv_15": 15.0,
  "grand_total": 115.0
}
```

Ticket renderizado (extracto):

```
GRAVADO 15% L. 100.00   IMPTO. 15% L. 15.00   TOTAL FACTURA L. 115.00
**CIENTO QUINCE LEMPIRAS EXACTOS**
```

Los dos cálculos son correctos según su configuración. ERPNext aplica exactamente la regla de la plantilla.

## Causa en el módulo Restaurante (corregida en la app `restaurant`)

Antes, `restaurant/tax_configuration.py` exigía la plantilla `Restaurante ISV neto` (siempre `included_in_print_rate = 0`). En sitios Grintsys, la plantilla predeterminada de la empresa (`Honduras Tax`) usa `included_in_print_rate = 1` y los precios se cargan con ISV incluido. Al forzar la plantilla neta, la factura sumaba el ISV otra vez.

Ahora la app Restaurante:

1. Resuelve la plantilla en este orden: `Restaurant Settings` → `POS Profile.taxes_and_charges` → `Restaurante ISV neto` si ya existe (sitios que ya facturaban con ella conservan su regla) → plantilla predeterminada de la empresa.
2. Detecta `included_in_print_rate` de sus filas y aplica la misma regla en la precuenta y en la `Sales Invoice`.
3. Pruebas: `restaurant.tests.test_fiscal_tip_isolation` (precio neto, precio incluido, una sola cuenta ISV estilo Grintsys, descuento por línea, exonerado).

## Recomendación operativa (no requiere código)

En cada sitio, confirmar si la lista de precios del restaurante publica precios **con** o **sin** ISV y elegir la plantilla correspondiente en **Configuración del Restaurante → Impuestos SAR y propinas**. Requiere validación tributaria local para la presentación del precio al consumidor.
