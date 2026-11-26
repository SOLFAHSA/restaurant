# Reporte para Grintsys: formato `Ticket` estándar y campo `custom_registro_sag`

- **Fecha:** 2026-11-24
- **Repositorio afectado:** `Grintsys/erpnext14` (rama `version-14`)
- **Origen:** rama local `feat/sar-ticket-registro-sag` (commit `b7eb588`)
- **Estado de evidencia:** ANALYZED

## 1. Formato `Ticket` estándar: se retira la sobreescritura

La rama `feat/sar-ticket-registro-sag` modificaba `erpnext/accounts/print_format/ticket/ticket.json`, un formato estándar que usan todos los clientes de LEAF ERP. Por acuerdo de la revisión técnica, **ese cambio no se propone a `version-14`**.

El módulo Restaurante ahora tiene su propio formato térmico de 80 mm dentro de su app:

- Nombre: `Ticket Restaurant`
- Ruta: `restaurant/restaurant/print_format/ticket_restaurant/ticket_restaurant.json`
- `doc_type = "Sales Invoice"`, `module = "Restaurant"`, `standard = "Yes"`
- Usa el contexto `restaurant.sar_format.get_sar_ticket_context` (registrado en `hooks.py → jinja.methods`).

Acción sugerida a Grintsys: cerrar o descartar el cambio de `ticket.json` de esa rama. El `Ticket` estándar de `version-14` queda intacto.

## 2. Campo `custom_registro_sag` (No. Registro SAG en facturas exoneradas)

- Hoy existe solo en la rama `feat/sar-ticket-registro-sag`: `erpnext/selling/custom/customer.json` y `erpnext/accounts/custom/sales_invoice.json`.
- El módulo Restaurante lo lee de forma defensiva y **no falla** si el campo no existe en un sitio:
  - `checkout/invoice.py`: solo lo copia a la factura si `frappe.get_meta("Sales Invoice").has_field("custom_registro_sag")`.
  - `pos.py`: solo lo lee del cliente si `Customer` tiene el campo.
  - `sar_format.py` y `Ticket Restaurant`: `doc.get("custom_registro_sag")`, con valor vacío si no existe.

Solicitud a Grintsys (PR independiente, sin mezclar con formatos de impresión): si el SAR exige imprimir el No. de Registro SAG en facturas exoneradas, incluir en `version-14` los dos `Custom Field` (`Customer-custom_registro_sag` y `Sales Invoice-custom_registro_sag`). Requiere validación tributaria local sobre la obligatoriedad del dato.

## Pasos para comprobar el aislamiento

1. En un sitio con `version-14` sin el campo, instalar la app Restaurante y ejecutar `bench --site <sitio> migrate`.
2. Facturar una orden con un cliente `Exonerado` desde el POS de Restaurante.
3. Resultado esperado: la factura se emite y `Ticket Restaurant` imprime la línea `No.Reg.Sec.Agro` vacía, sin errores.
