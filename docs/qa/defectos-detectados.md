# Registro Formal de Defectos Detectados (`2026-11-16`)

> **Nota de actualización post-remediación (`2026-11-16`):** Se resolvieron y validaron en verde (`199/199 OK`, `0 expected failures`) los defectos **`DEF-2026-001`, `002`, `004`, `005` (Gift Card / modal Exonerado / estado Borrador), `006`, `007`, `008` (+ `DEF-MB-008`), `009` (propiedad de turno/sucursal, cierre Gerente, ocultamiento `expected_amount` en preview, validación de denominaciones), `011` (`get_self_order_config`, `expires=True`, auditoría `Rechazado`), `012` (batching `get_kds_state` `131 -> 22 SQL` cálido y eliminación de escrituras `GET` en `get_restaurant_pos_config`), `013` (`DEF-MB-003` + `FOR UPDATE` en `open_pos_shift`), `014` (sync realtime `restaurant_kds_update`, precuenta en `Órdenes`, `persistCurrentOrderSilently`, guardas doble clic)** y **`015` (índices `search_index: 1` en DocTypes clave)**. Permanecen abiertos por alcance/gobernanza: **`DEF-2026-003`** (inventario/BOM), **`DEF-2026-010`** (*requiere validación tributaria local* para bloquear CAI demo en prod) y puntos de despliegue/Playwright/socket `9000`.

---

## 1. Defectos Críticos (P0)

### `DEF-2026-001` — Doble tributación (33% ISV) al facturar órdenes con tasas mixtas (15% + 18% o Exento)
- **Estado:** Confirmado en ejecución real (`VERIFIED` vía `test_def_qa_12_mixed_isv15_isv18_order_does_not_double_tax_on_invoice`).
- **Archivo y líneas:** `apps/restaurant/restaurant/pos.py:2515-2560` (`pay_and_invoice_order`).
- **Descripción técnica:** Al mezclar un platillo gravado al 15% y una bebida al 18% (o un ítem Exento), `pos.py:2518` rellena `item_tax_rate` solo con `{tax_acc: row.tax_rate}` sin poner en `0.0` las demás cuentas de impuesto incluidas en `taxes` (`Charge Type: On Net Total`, 15% y 18%). ERPNext aplica entonces **ambas filas (15% + 18% = 33%)** a todos los ítems; análogamente, los ítems Exentos reciben 15%/18%, y si 15% y 18% comparten cuenta contable, `pos.py:2553` (`tax_acc_18 != tax_acc_15`) omite la fila de 18%.
- **Evidencia real:** En la simulación de 3 sucursales (`L 120` @ 15% + `L 60` @ 18% + `L 18` propina), `Restaurant Order` calculó `L 226.80`, mientras `Sales Invoice` calculó **`L 257.40`** (`+L 30.60` de doble ISV), lanzando `ValidationError: El monto total pagado (226.8) es menor al total de la factura (257.4)`. Reproducido también en `test_def_qa_12` (`L 120` + `L 60`: esperado `L 208.80`).
- **Propuesta (`PROPOSED`):** Resolver `tax_acc_15` y `tax_acc_18` antes del loop de ítems y poblar explícitamente en cada línea `item_tax_rate` todas las cuentas fiscales presentes en `taxes` (`{tax_acc_15: 15/0, tax_acc_18: 0/18}`), usando `Item Tax Template` nativos de ERPNext cuando aplique (Nivel 1/3; *requiere validación tributaria local*).

### `DEF-2026-002` — `si.set_missing_values()` sobrescribe `update_stock = 0` y `tax_category = "Exonerado"` desde `POS Profile`
- **Estado:** Confirmado en ejecución real (`VERIFIED` vía `test_def_qa_05`).
- **Archivo y líneas:** `apps/restaurant/restaurant/pos.py:2655, 2700, 2728` ↔ `apps/erpnext/erpnext/accounts/doctype/sales_invoice/sales_invoice.py:821-822, 939-940, 988-989, 1006-1007`.
- **Descripción técnica:** `pay_and_invoice_order` arma `si_payload` con `update_stock = 0` y `tax_category = "Exonerado"`, pero inmediatamente llama a `si.set_missing_values()` (`pos.py:2728`, con `for_validate=False`). En ERPNext, `set_pos_fields(for_validate=False)` sobrescribe `self.update_stock = cint(pos.get("update_stock"))` y `self.tax_category = pos.get("tax_category")`, anulando ambos valores en la factura. En `POS 01 HNL` activo hoy en `development`, `update_stock = 1`, provocando `NegativeStockError` al facturar artículos inventariables sin stock (`Stock Ledger Entry = 0`).
- **Propuesta (`PROPOSED`):** Reafirmar `si.update_stock` (conforme política de inventario acordada) y `si.tax_category` + exoneraciones **después** de `si.set_missing_values()`, y limpiar filas `taxes` cuando `tax_category == "Exonerado"`.

### `DEF-2026-003` — Inventario y recetas (`Product Bundle` / `BOM`) desconectados de la facturación
- **Estado:** Confirmado en código y BD (`VERIFIED`: `Stock Ledger Entry = 0`, `BOM = 0`, `Product Bundle disabled = 1`).
- **Archivo y líneas:** `apps/restaurant/restaurant/item_configuration.py:103-106, 173-174`; `apps/restaurant/restaurant/pos.py:2655`.
- **Descripción técnica:** Las recetas se almacenan como `Product Bundle` forzadamente `disabled = 1` (`validate_managed_bundle` impide activarlos), las opciones de platillo que sustituyen o agregan ingredientes solo suman precio en texto, y la facturación POS intenta omitir stock (`update_stock = 0`). Vender un platillo no descuenta ingredientes ni producto terminado del almacén correspondiente.
- **Propuesta (`PROPOSED`):** Definir contable y operativamente con Grintsys el camino estándar ERPNext (Nivel 1): `BOM` / `Stock Entry` de consumo o `Product Bundle` habilitado + `update_stock = 1` controlado por sucursal/almacén, respetando devoluciones en `on_cancel`.

### `DEF-2026-004` — Meseros pueden crear y sobrescribir clientes maestros vía `ignore_permissions=True`
- **Estado:** Confirmado en ejecución real (`VERIFIED` vía `test_def_qa_02`).
- **Archivo y líneas:** `apps/restaurant/restaurant/pos.py:3252-3311` (`save_customer_with_rtn`, `L3275, L3302`) y `pos.py:2481` (`pay_and_invoice_order`).
- **Descripción técnica:** `save_customer_with_rtn` solo exige `_require_pos_user()` y ejecuta `insert`/`save` con `ignore_permissions=True`. Un mesero (`Restaurant User`, sin permiso de escritura en `Customer`) puede alterar cualquier cliente existente (por ejemplo cambiar nombre/RTN de `CONSUMIDOR FINAL`). Además `pos.py:2481` modifica globalmente `Customer.tax_id` al facturar.
- **Propuesta (`PROPOSED`):** Exigir `user_can_invoice()` + `frappe.has_permission("Customer", "create"/"write")` eliminando `ignore_permissions=True`; no mutar el `tax_id` maestro de clientes genéricos como `CONSUMIDOR FINAL`.

### `DEF-2026-005` — Desfase contable en redención de Gift Cards, descuentos/cupones, exoneración UI y facturas Borrador
- **Estado:** Confirmado (`VERIFIED` vía `test_def_qa_10`; `ANALYZED` en código).
- **Archivo y líneas:** `pos.py:2601-2616, 2674-2675, 2735-2759`; `restaurant_pos.js:3443-3447, 3671, 3896-3904, 3937`.
- **Descripción técnica:**
  1. `test_def_qa_10` demostró que redimir una `Restaurant Gift Card` rebaja su saldo (`L2750-2752`) pero **no descuenta el monto de `si.payments` (`L2735-2742`)**, fallando si el efectivo recibido es `total - gift_card` o provocando sobrepago sin asiento contable.
  2. Cuando `auto_validate_orders == 0`, `Sales Invoice` queda en Borrador (`docstatus = 0`), pero la orden pasa a `"Facturada"` (`pos.py:2759`), bloqueando luego el cierre de caja en `POS Closing Shift`.
  3. En `openFiscalPaymentModal()` (`restaurant_pos.js:3896-3904`), marcar el checkbox `"Factura Exonerada"` no recalcula ISV a `0` ni en `payments` ni en `pos.py:2543-2560`. En pantalla de pago tampoco se descuentan visualmente cupón/lealtad/gift card ni hay UI de pagos mixtos.
- **Propuesta (`PROPOSED`):** Integrar pagos de Gift Card/anticipos y cupones mediante asientos/reglas nativas ERPNext, impedir marcar `"Facturada"` si `si.docstatus != 1`, y sincronizar cálculo exonerado/descuentos entre modal y servidor.

---

## 2. Defectos Altos (P1)

### `DEF-2026-006` — `Cajero (Facturación Directa)` bloqueado de abrir `/app/restaurant-pos` en Desk
- **Estado:** Confirmado en ejecución (`VERIFIED` vía `test_def_qa_01`).
- **Archivo y líneas:** `apps/restaurant/restaurant/restaurant/page/restaurant_pos/restaurant_pos.json:4-18` vs `restaurant/setup.py:167`.
- **Descripción técnica:** `restaurant_pos.json` solo lista `System Manager`, `Restaurant Manager` y `Restaurant User`. El perfil `Cajero (Facturación Directa)` solo posee `Restaurant Cashier` y `Restaurant Direct Cashier`, recibiendo `PermissionError` al abrir la página POS.
- **Propuesta (`PROPOSED`):** Agregar `Restaurant Cashier` y `Restaurant Direct Cashier` en `restaurant_pos.json` (`roles`).

### `DEF-2026-007` — Desajuste de permisos en `restaurant-kds` para Meseros y Cajeros
- **Estado:** Confirmado en ejecución (`VERIFIED` vía `test_def_qa_09`).
- **Archivo y líneas:** `apps/restaurant/restaurant/restaurant/page/restaurant_kds/restaurant_kds.json:4-18` vs `restaurant/setup.py:80-97` y `kds.py:275`.
- **Descripción técnica:** `restaurant_kds.json` da acceso a `Restaurant User`, pero `setup.py` no le otorga lectura a `Restaurant Preparation Stage`/`Display`, causando error al llamar `get_kds_state()`. A la inversa, `Restaurant Cashier` sí recibe permisos de lectura en `setup.py:95-97`, pero falta en `restaurant_kds.json`. Además `open-stages-list` (`restaurant_kds.js:708`) es código muerto sin botón en DOM.
- **Propuesta (`PROPOSED`):** Alinear roles en `restaurant_kds.json` con `setup.py` y definir si `Restaurant User` debe consultar KDS en solo lectura o separarse por rol de cocina.

### `DEF-2026-008` — Aislamiento multisucursal (`Branch`) roto en órdenes, KDS, comandas TCP, traslados, PIN y CAI
- **Estado:** Confirmado en ejecución (`VERIFIED` vía `test_def_qa_06`, `test_def_qa_07` y `DEF-MB-008` en `test_multibranch_concurrency.py`).
- **Archivo y líneas:** `restaurant_order.json`, `restaurant_cash_count.json`, `pos.py:96-109, 187-201, 1094-1122, 1312-1313, 2056, 2170, 3320`, `order_operations.py:16, 355`, `kds.py:70, 230, 421`, `pos_auth.py:247`.
- **Descripción técnica:** Al faltar `branch` en `Restaurant Order`, `Restaurant Cash Count`, `POS Profile` y `Restaurant Preparation Display`, las órdenes de Sucursal B se filtran a Sucursal A (`test_def_qa_06`), se pueden mover órdenes entre sucursales (`DEF-MB-008`), imprimir comandas TCP hacia IPs de otras sucursales, validar PINs de supervisores de otra sucursal y tomar `CAI`/`Sales Invoice` globales en `_resolve_sar_fiscal_info`.
- **Propuesta (`PROPOSED`):** Agregar campo `branch` (`Link -> Branch`, `search_index: 1`) en `Restaurant Order`, `POS Profile`, `Restaurant Preparation Display`, `Restaurant Cash Count`, validar coincidencia de sucursal en todas las operaciones (`save_pos_order`, `transfer_account`, `send_order_to_kitchen`, `get_kds_state`, `pay_and_invoice_order`, `cash_count.py`, `_resolve_supervisor_by_pin`), y pasar un patches idempotente para poblar datos históricos (`Compuerta de Datos Existentes`).

### `DEF-2026-009` — Brechas de autorización, lectura ciegas y mutación GET en Arqueo y Cierre de Caja
- **Estado:** Confirmado en ejecución (`VERIFIED` vía `test_def_qa_04`, `test_def_qa_07`) y análisis (`ANALYZED`).
- **Archivo y líneas:** `cash_count.py:234, 302, 337, 374, 497-583`, `pos.py:1455, 1533, 1562-1583, 1724`, `posawesome/.../pos_closing_shift.py:196, 275-283, 328-348`, `setup.py:237-247`.
- **Descripción técnica:**
  1. `get_cash_count_preview` (`cash_count.py:497`), `get_closing_shift_preview` (`pos.py:1562`) y `get_shift_cash_movements` (`pos.py:1455`) solo validan `_require_pos_user()`: un mesero o Cajero B consulta y opera sobre turnos ajenos (`test_def_qa_07`), exponiendo `expected_amount` aunque `hide_expected_amount=1`.
  2. Las vistas previas disparan `make_closing_shift_from_opening()` → `submit_printed_invoices()` durante peticiones `GET`.
  3. `close_pos_shift` (`pos.py:1724`) bloquea a `Restaurant Manager` para cerrar un turno vía `Arqueo de Cierre` (`test_def_qa_04`).
  4. `cash_count.py:374` confía en `unit_value` enviado en el payload en vez de consultarlo desde `Restaurant Cash Denomination`, `setup.py:237-247` omite denominaciones de monedas (centavos), y `pos_closing_shift.py:328-348` hardcodea `"Efectivo"` rompiendo cálculos si el método de efectivo tiene otro nombre.
- **Propuesta (`PROPOSED`):** Exigir `user_can_invoice()` + propiedad de turno/sucursal (permitiendo cierre a `Restaurant Manager` de la misma sucursal), ocultar `expected_*` en servidor cuando `hide_expected_amount=1`, evitar `submit_printed_invoices()` en previews `GET`, y añadir denominaciones de monedas HNL en `setup.py`.

### `DEF-2026-010` — Fallbacks SAR ficticios hardcodeados (`RTN 05019000123456` / `CAI 3A8F9E-...`) *(requiere validación tributaria local)*
- **Estado:** Confirmado en código (`ANALYZED`).
- **Archivo y líneas:** `pos.py:1065-1141, 2324, 2409-2411`.
- **Descripción técnica:** Si no existe `CAI` activo para la serie del perfil POS, `_resolve_sar_fiscal_info` cae a otro `CAI`, otra `Sales Invoice` o constantes ficticias. Además `si_payload` no fuerza `naming_series = fiscal_info["prefix"]` y puede emitir comprobantes sin rango autorizado vigente.
- **Propuesta (`PROPOSED`):** Bloquear facturación fiscal SAR si no hay `CAI` activo vigente vinculado a la empresa/establecimiento/serie (`naming_series`), eliminar fallbacks ficticios de producción (*requiere validación tributaria local*).

### `DEF-2026-011` — Vulnerabilidades de PIN, caché Redis, auditoría engañosa y endpoints sin guardia
- **Estado:** Confirmado en ejecución (`VERIFIED` vía `test_def_qa_03`, `test_def_qa_08`, `test_def_qa_11`).
- **Archivo y líneas:** `pos.py:75, 87, 2243, 3175, 3191, 3910`; `pos_auth.py:201-242, 247, 278, 332, 348-356`.
- **Descripción técnica:**
  1. `get_self_order_config` (`pos.py:3910`) carece de `_require_pos_user()`, quedando abierto a cualquier usuario autenticado no-restaurante (`test_def_qa_03`).
  2. `pos.py:75, 87` y `pos_auth.py:278, 332` llaman `frappe.cache().get_value(key)` **sin `expires=True`**: en `frappe/utils/redis_wrapper.py:43-85`, `get_value` cachea `None` en `frappe.local.cache` y `set_value(..., expires_in_sec=300)` no lo actualiza, permitiendo bypass en múltiples intentos dentro de la misma petición/worker (`test_def_qa_11`).
  3. `unlock_waiter_order` (`pos.py:3175, 3191`) registra intentos fallidos sin `result="Rechazado"`, guardándose como `"Autorizado"` en `Restaurant Audit Log` (`test_def_qa_08`).
  4. `pos_auth.py:348-356` hace fallback a `check_password` cuando un supervisor no tiene PIN, creando un oráculo de contraseña de `Administrator`/gerentes; `send_order_to_kitchen(..., include_sent=1)` omite los tokens de un solo uso (`pos_auth.py:201-242` muertos).
- **Propuesta (`PROPOSED`):** Agregar `_require_pos_user()` a `get_self_order_config`, pasar `expires=True` en todo `get_value` con TTL, corregir `result="Rechazado"`, exigir PIN dedicado sin fallback a password de cuenta, y validar token supervisor de un solo uso en `include_sent=1`.

### `DEF-2026-012` — Degradación severa de rendimiento por N+1 (`646`/`1,074` SQL) y escritura en `GET get_pos_bootstrap`
- **Estado:** Confirmado en ejecución (`VERIFIED` en `test_02` y benchmark HTTP `qa_load_and_concurrency.py`).
- **Archivo y líneas:** `pos.py:187-201, 1319-1339, 3530-3531`; `setup.py:259-289`; `kds.py:237-281`; `cash_count.py:581-582`.
- **Descripción técnica:** `get_pos_bootstrap` dispara `646 SQL` + escribe en `tabCustom HTML Block` + limpia caché en `GET` (causando `43` `Innodb_row_lock_waits` en `10u-50u` y 100% `ReadTimeout` a `100u`). `pay_and_invoice_order` ejecuta `1,074 SQL` (`998 ms`). RSS del proceso creció de `178 MB` a `714 MB` y `Slow_queries` subió `+24`.
- **Propuesta (`PROPOSED`):** Ver plan detallado en `docs/qa/plan-optimizacion.md`.

### `DEF-2026-013` — Concurrencia incompleta (`save_pos_order`, `open_pos_shift`, impresión) y scripts de despliegue incompletos
- **Estado:** Confirmado (`VERIFIED` en `DEF-MB-003`; `ANALYZED` en despliegue).
- **Archivo y líneas:** `pos.py:1403-1452, 1817, 2252`; `scripts/deploy_production_native.sh:161-204`; `scripts/update_production.sh:85-115`; `compose.yaml`.
- **Descripción técnica:** `save_pos_order` no exige `expected_modified` ni bloquea orden/mesa con `FOR UPDATE` (`DEF-MB-003`); `open_pos_shift` permite doble turno simultáneo sin lock; `send_order_to_kitchen` carece de lock e idempotencia. En infraestructura, los scripts de producción no clonan ni actualizan `apps/restaurant`, `update_production.sh:115` expone contraseña sudo `"123456"` y `compose.yaml` no define healthchecks en servicios Python/Nginx/Websocket.
- **Propuesta (`PROPOSED`):** Bloqueo optimista/pesimista obligatorio en `save_pos_order`, lock en apertura/cierre de turno e idempotencia en comandas/pagos; incluir `restaurant` en despliegue, retirar credenciales hardcoded y añadir healthchecks en Compose.

---

## 3. Defectos Medios y Bajos (P2 / P3)

### `DEF-2026-014` — Defectos de Frontend, Sync KDS, Split Bill y Responsividad (`P2`)
- **Archivo y líneas:** `restaurant_pos.js`, `restaurant_kds.js`, `restaurant_table_map.js`, `restaurant_pos.css`, `restaurant_kds.css`.
- **Detalle comprobado (`ANALYZED`):**
  1. **Modal Split desalineado (`restaurant_pos.js:4352-4401` vs `order_operations.cjs:154`):** `renderSplitView` omite `[data-split-quantity]`, no llama `preview_split_order` y calcula cuotas pre-impuestos mientras la prueba UI espera total con impuesto.
  2. **Precuenta histórica (`restaurant_pos.js:3273-3280`):** Al abrir precuenta desde `Órdenes`, envía al servidor la propina de `this.currentOrder` sobrescribiendo la orden seleccionada.
  3. **Sin UI de pagos mixtos (`restaurant_pos.js:3469, 3671`)** y descuento/cupón/gift card/lealtad no recalculan el vuelto ni el pago en `renderPaymentScreenView`.
  4. **Impresión y popups (`3342, 4224, 5464-5474, 2070`):** `createModal()` borra el modal padre de Cierre al abrir resumen diario; `openPosaPrintView` combina `trigger_print=1` + `print()` doble; `/assets/restaurant/images/background-light.svg` da `404`; `persistCurrentOrderSilently` (`2038`) tiene `catch {}` vacío; falta bloqueo de botón contra doble clic en Pago / KDS / Arqueo.
  5. **KDS & Table Map:** `restaurant_kds.js` no escucha `frappe.realtime.on("restaurant_kds_update")` (y `socketio:9000` está apagado en sesión dev debugpy); `restaurant_table_map.js:81-85` ignora `frappe.route_options?.area_name`; grillas fijas desbordan por `overflow: hidden` en tablets (`restaurant_pos.css:12, 982, 1139, 1574`).

### `DEF-2026-015` — Ausencia total de índices SQL y afinamiento MariaDB/Gunicorn (`P2`)
- **Archivo y líneas:** Los 25 DocTypes `*.json` (`0` con `search_index: 1`), `common_site_config.json` (`gunicorn_workers: 33` vs `background_workers: 1`, `live_reload: true`, `redis_socketio == redis_queue`), MariaDB (`innodb_buffer_pool_size = 128 MB`), `.github/workflows/` (sin CI para `restaurant`).
- **Propuesta (`PROPOSED`):** Agregar índices en `tabRestaurant Order`, `tabRestaurant Preparation Ticket`, `tabRestaurant Cash Count`, `tabRestaurant Audit Log`, ajustar `innodb_buffer_pool_size`, separar colas/workers y agregar workflow CI + Playwright/coverage.

### `DEF-2026-016` — Trampa `Employee.create_user_permission = 1` e inconsistencias menores de idioma/copy (`P3`)
- **Archivo y líneas:** `kds_setup.py:21-23, 32` (`"To cook"`, `"Ready"`, `"Completed"`), `migrate_app_name.py:18-26` (sin `_()`), `restaurant_pos.js:1529, 4934` (`"escaneé"`, `"Backend"`), `restaurant_kds.js:445-446` (`"← Kitchen Display"`), `setup.py` / creación de `Employee` en Desk.
- **Detalle comprobado (`VERIFIED`):** Si un usuario cajero tiene un `Employee` con `create_user_permission = 1`, ERPNext restringe sus consultas a `waiter == propio empleado`, bloqueando cuentas de meseros. En `test_qa_comprehensive_audit.py` se comprobó que `create_user_permission = 0` evita dicho bloqueo.
