# Plan de Optimización y Remediación Priorizado (`2026-11-16`)

Todas las propuestas respetan los **5 Niveles de Prioridad Arquitectónica LEAF** y requieren revisión/autorización previa antes de modificar lógica de negocio o esquema.

---

## Fase 1 — Bloqueantes Inmediatos antes de Producción (P0: Fiscal, Seguridad, Integridad)

| Prioridad | Defecto(s) | Cambio Propuesto | Nivel LEAF | Impacto Esperado |
|---:|---|---|---|---|
| **1** | `DEF-2026-001` | Poblar todas las cuentas fiscales activas en `item_tax_rate` de `pay_and_invoice_order` (`0.0` explícito en tasas no aplicables por ítem) o usar plantillas nativas ERPNext por ítem para eliminar doble cobro 15%+18% (`33%`) y cobro sobre Exentos. (*Requiere validación tributaria local.*) | Nivel 1 / 3 | Exactitud fiscal 100% en órdenes mixtas ISV 15% + 18% + Exento. |
| **2** | `DEF-2026-002` | En `pay_and_invoice_order`, reasignar `si.tax_category`, campos de exoneración y `si.update_stock` **después** de `si.set_missing_values()` (y limpiar `si.taxes` si `Exonerado`). | Nivel 3 | Evita que `POS Profile` anule exoneraciones SAR o fuerce descuentos inesperados. |
| **3** | `DEF-2026-004`, `DEF-2026-011` | Corregir seguridad RBAC/PINs: exigir permiso `Customer` en `save_customer_with_rtn` sin `ignore_permissions=True`; añadir `_require_pos_user()` a `get_self_order_config`; pasar `expires=True` en todo `cache.get_value()` de rate-limit; corregir `result="Rechazado"` en `unlock_waiter_order`; retirar oráculo `check_password` en supervisores sin PIN; validar token único de supervisor en `send_order_to_kitchen(..., include_sent=1)`. | Nivel 3 | Cierra bypasses HTTP críticos de clientes, fuerza bruta de PIN y auditoría falsa. |
| **4** | `DEF-2026-005` | Integrar pago/contabilización nativa de `Restaurant Gift Card` y `Coupon Code` en `Sales Invoice` (o prohibir su activación en producción hasta integrarlo); impedir marcar `Restaurant Order = "Facturada"` si `si.docstatus != 1`. | Nivel 1 / 3 | Elimina descuadres caja vs `Sales Invoice` y bloqueos de cierre de turno. |
| **5** | `DEF-2026-003` | Decisión operativa Grintsys + implementación Nivel 1 sobre inventario/recetas (`BOM` o `Product Bundle` activo + `update_stock=1` por almacén y reversión en `on_cancel`). | Nivel 1 / 3 | Trazabilidad real de `Stock Ledger Entry` al vender platillos/bebidas. |

---

## Fase 2 — Estabilidad de Roles, Multisucursal y Arqueo de Caja (P1)

| Prioridad | Defecto(s) | Cambio Propuesto | Nivel LEAF | Impacto Esperado |
|---:|---|---|---|---|
| **6** | `DEF-2026-006`, `DEF-2026-007`, `DEF-2026-016` | Incluir `Restaurant Cashier` y `Restaurant Direct Cashier` en `restaurant_pos.json` y `restaurant_kds.json`; alinear `setup.py` con permisos de solo lectura en KDS; documentar/desactivar `create_user_permission` automático en `Employee` de cajeros para que vean órdenes de meseros. | Nivel 2 / 3 | Habilidad real de abrir POS/KDS para todos los perfiles definidos. |
| **7** | `DEF-2026-008`, `DEF-2026-013` | Añadir `branch` (`Link -> Branch`, indexado) en `Restaurant Order`, `POS Profile`, `Restaurant Preparation Display`, `Restaurant Cash Count` (+ patch idempotente para históricos); filtrar órdenes, comandas TCP, KDS, turnos, CAI y PIN de supervisores por sucursal; hacer obligatorio `expected_modified` + `FOR UPDATE` en `save_pos_order`, `send_order_to_kitchen` y `open_pos_shift`. | Nivel 2 / 3 | Aislamiento efectivo de 3+ sucursales y cero condiciones de carrera entre terminales. |
| **8** | `DEF-2026-009` | Endurecer `cash_count.py` y `pos.py`: exigir `user_can_invoice()` + validación de turno/sucursal en previews y `save_and_submit_cash_count`; ocultar `expected_*` en servidor cuando `hide_expected_amount=1`; sacar `submit_printed_invoices()` de las lecturas; habilitar cierre a `Restaurant Manager` de la misma sucursal; validar `unit_value` desde servidor y agregar monedas HNL; corregir filtro de `cash_mode_of_payment` distinto de `"Efectivo"`. | Nivel 3 | Control estricto de efectivo/arqueo y soporte a ciego real (`hide_expected_amount`). |
| **9** | `DEF-2026-010` | Eliminar fallbacks ficticios de RTN/CAI en `pos.py`; exigir `CAI` activo por empresa/establecimiento/serie y asignar `naming_series = fiscal_info["prefix"]`. (*Requiere validación tributaria local.*) | Nivel 1 / 3 | Cumplimiento estricto SAR Honduras sin comprobantes inválidos. |

---

## Fase 3 — Rendimiento, Índices MariaDB, Frontend e Infraestructura (P1 / P2)

| Prioridad | Defecto(s) | Cambio Propuesto | Nivel LEAF | Impacto Esperado |
|---:|---|---|---|---|
| **10** | `DEF-2026-012` | Sacar `sync_restaurant_dashboard_block()` y escrituras `GET` de `get_pos_bootstrap`; batching SQL (`IN (...)`) en `_serialize_orders_batch()`, `_resolve_command_map()` y `get_kds_state()` con paginación; evitar triple llamada a `make_closing_shift_from_opening()` en arqueos. | Nivel 3 | Baja `get_pos_bootstrap` de `646` SQL (`632 ms`) a `<30` SQL (`<120 ms`), eliminando bloqueos InnoDB en lectura. |
| **11** | `DEF-2026-015` | Agregar `"search_index": 1` e índices compuestos en `tabRestaurant Order`, `tabRestaurant Preparation Ticket`, `tabRestaurant Cash Count` y `tabRestaurant Audit Log`; subir `innodb_buffer_pool_size` en producción (`>= 50%` RAM DB) y desactivar `live_reload` en prod. | Nivel 2 / 4 | Escalabilidad lineal de consultas ante miles de órdenes/tickets históricos. |
| **12** | `DEF-2026-014` | Reparar selector Split (`[data-split-quantity]` / `preview_split_order`), precuenta de órdenes históricas, UI de pagos mixtos, cálculo exonerado en modal, doble diálogo de impresión, asset `background-light.svg`, `frappe.realtime` en KDS, locks en botones y responsive tablets. | Nivel 3 | UI sincronizada al 100% con reglas de backend y pruebas `.cjs`. |
| **13** | `DEF-2026-013`, `DEF-2026-015` | Incorporar `restaurant` en `deploy_production_native.sh` y `update_production.sh`, retirar contraseña sudo hardcoded, agregar healthchecks en `compose.yaml`, levantar `gunicorn` + `socketio` en staging multi-worker y ejecutar pruebas de carga + Playwright CI (`DEF-2026-015`). | Nivel 4 | Despliegue reproducible y certificación real bajo carga en staging. |
