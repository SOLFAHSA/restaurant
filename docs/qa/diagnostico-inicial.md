# Informe de Auditoría General y Diagnóstico Inicial — Módulo Restaurante LEAF ERP

**Fecha de auditoría:** `2026-11-16`  
**Alcance evaluado:** Aplicación personalizada `restaurant` (`v0.0.1`, rama `feature/modulo-restaurante`, commit `3ef8544` + cambios locales pendientes SAR Ticket) integrada con Frappe `14.96.21`, ERPNext `14.74.4`, POS Awesome `6.3.0`, MariaDB `10.6.28` e infraestructura `frappe_docker14`.  
**Estado de gobernanza:** Auditoría ejecutada conforme a `AGENTS.md`, `00-orchestrator-global-rule.md`, `ARCHITECTURE_RULES.md` y la skill `leaf-qa-guardian` (solo lectura operativa, pruebas automatizadas en savepoint/rollback y documentación QA; sin mutación de lógica empresarial ni esquema sin autorización).

---

## 1. Inventario de Entorno y Versiones Reales (`VERIFIED`)

| Componente | Versión / Rama / Commit | Observaciones |
| :--- | :--- | :--- |
| **Frappe Framework** | `14.96.21` · rama `version-14` · `806e76d` | Limpio (`0` archivos modificados) |
| **ERPNext** | `14.74.4` · rama `version-14` · `45dd53f` | `4` archivos locales modificados (`ticket.json`, `sales_invoice.json`, `customer.json`, etc.) |
| **POS Awesome** | `6.3.0` · rama `version-14` · `0f0ad9c` | Limpio (`0` archivos modificados) |
| **Restaurante (`restaurant`)** | `0.0.1` · rama `feature/modulo-restaurante` · `3ef8544` | `8` archivos locales modificados/nuevos (formato SAR, `sar_format.py`, `test_sar_ticket.py`) + nuevo `test_qa_comprehensive_audit.py` |
| **Infraestructura (`frappe_docker14`)** | rama `main` · `ca7d961` | Python `3.11.18`, Node disponible, `16 vCPU`, `23,891 MB` RAM, `952 GB` disco libre |
| **Base de datos (`development`)** | `10.6.28-MariaDB-ubu2204` | `innodb_buffer_pool_size = 128 MB`, `max_connections = 151`, `slow_query_log = OFF` |
| **Herramientas QA ausentes** | `playwright`, `coverage`, `locust`, `k6`, `cypress` | No instalados en el entorno DevContainer (`BLOCKED` para E2E navegador real y `%` cobertura) |

### Registros existentes en el sitio `development` (`VERIFIED`)
- `Company`: `1` (`Empresa Demostrativa`) · `Branch`: `4` · `Warehouse`: `11` · `POS Profile`: `1` (`POS 01 HNL`, con `update_stock = 1`, `disable_rounded_total = 1`, `print_format = "Ticket"`) · `CAI`: `1`.
- `Customer`: `1` · `Item`: `40` · `Item Price`: `0` (todos los precios provienen de `Item.standard_rate` o `0`) · `Product Bundle`: `5` · `BOM`: `0`.
- `Sales Invoice`: `12` · `POS Invoice`: `0` · `GL Entry`: `57` (`0` comprobantes desbalanceados) · **`Stock Ledger Entry`: `0`**.
- `Restaurant Order`: `59` (`199` ítems hijos, `0` huérfanos, `0` facturas faltantes) · `Restaurant Area`: `26` · `Restaurant Table`: `19` · `Restaurant Command`: `2` · `Restaurant Preparation Display`: `1` (`3` stages, `26` tickets) · `Restaurant Cash Count`: `2` · `POS Opening Shift`: `8` · `POS Closing Shift`: `3` · `Retiro de efectivo`: `1` · `Restaurant Audit Log`: `5` · `Restaurant Gift Card`: `0`.

---

## 2. Arquitectura del Módulo `restaurant` (`ANALYZED`)

### Módulos Python y superficie API (63 endpoints `@frappe.whitelist()`)
- **`restaurant/pos.py` (37 endpoints):** bootstrap, turnos `POS Opening/Closing Shift`, movimientos `Retiro de efectivo`, órdenes/validación, pre-cuenta, comandas e impresión TCP ESC/POS, facturación SAR `Sales Invoice`, stock administrativo, cupones, gift cards, lealtad, correo/WhatsApp.
- **`restaurant/cash_count.py` (3 endpoints):** snapshot/arqueo de caja por denominaciones, métodos y movimientos (`Restaurant Cash Count`, único DocType submittable del módulo).
- **`restaurant/kds.py` (7 endpoints) + `order_kds.py` + `kds_setup.py`:** estado KDS, pantallas, etapas, avance/retroceso/descarte de tickets y remapeo atómico en divisiones/fusiones.
- **`restaurant/order_operations.py` (4 endpoints vía `pos.py`):** división (`split`), traslado y fusión (`transfer/merge`) con savepoint transaccional y bloqueo ordenado (`for_update=True`).
- **`restaurant/commands.py` (3 endpoints):** destinos de impresión/comandas por sucursal y `Item Group`.
- **`restaurant/location.py` (3 endpoints):** áreas de salón por sucursal (`Branch`).
- **`restaurant/table_management.py` (6 endpoints):** mesas y plano visual (`layout_json`).
- **`restaurant/item_configuration.py` (3 endpoints):** recetas en `Product Bundle` inactivo (`disabled=1`, `restaurant_managed=1`) y `Restaurant Option Group`.
- **`restaurant/pos_auth.py`:** RBAC, verificación criptográfica (`hmac.compare_digest`) de PIN de mesero/supervisor y bitácora (`Restaurant Audit Log` + `Activity Log` + timeline).
- **`restaurant/sar_format.py`:** conversión exacta a letras en Lempiras (`Decimal`) y helpers Jinja SAR.
- **`restaurant/restaurant/doctype/restaurant_settings/restaurant_settings.py` (1 endpoint):** configuración operativa y sincronización en `tabDefaultValue`.

### DocTypes (`25` DocTypes JSON en `restaurant/restaurant/doctype/`) (`ANALYZED`)
- **13 regulares:** `Restaurant Area`, `Restaurant Table`, `Restaurant Order`, `Restaurant Order Preset`, `Restaurant Command`, `Restaurant Option Group`, `Restaurant Preparation Display`, `Restaurant Preparation Stage`, `Restaurant Preparation Ticket`, `Restaurant Cash Count` (único `is_submittable: 1`), `Restaurant Cash Denomination`, `Restaurant Gift Card`, `Restaurant Audit Log`.
- **1 Single:** `Restaurant Settings`.
- **11 tablas hijas (`istable: 1`).**
- **Hallazgo transversal:** **0 campos** en los 25 DocTypes declaran `"search_index": 1`; verificado con `SHOW INDEX` que `tabRestaurant Order`, `tabRestaurant Preparation Ticket`, `tabRestaurant Cash Count` y `tabRestaurant Audit Log` únicamente poseen índices `PRIMARY (name)` y `modified`.

---

## 3. Evaluación Arquitectónica y Cumplimiento "ERPNext como Motor" (`ANALYZED` / `VERIFIED`)

| Eje de evaluación | Estado | Evidencia real |
| :--- | :--- | :--- |
| **Contabilidad (`GL Entry`) y Facturación SAR (`Sales Invoice`)** | **FUNCIONAL CON DEFECTOS P0/P1** | Las 12 facturas existentes y las 6 generadas en simulación multisucursal tienen `SUM(debit) - SUM(credit) = 0.00` (`VERIFIED`). **Brecha P0:** `pay_and_invoice_order` aplica doble tributación (15% + 18% = 33%) cuando coexisten ítems de tasas distintas (`DEF-QA-12`, `VERIFIED`); `si.set_missing_values()` sobrescribe `update_stock` y `tax_category="Exonerado"` desde `POS Profile` (`DEF-QA-05`, `VERIFIED`); existen fallbacks CAI/RTN ficticios hardcodeados (*requiere validación tributaria local*). |
| **Inventario y Recetas** | **NO INTEGRADO EN VENTAS (BRECHA CRÍTICA)** | `Product Bundle` permanece forzosamente `disabled=1` (`item_configuration.py:173-174`) y no existe integración `BOM`. En `POS 01 HNL` (`update_stock=1`), `set_missing_values()` anula `update_stock=0` en `Sales Invoice`, causando `NegativeStockError` si se facturan artículos inventariables sin stock (`Stock Ledger Entry = 0`). |
| **Turnos y Arqueo (`POS Awesome`)** | **PARCIAL CON RIESGOS ALTOS** | Recálculo en servidor sólido en `cash_count.py`, pero `POS Closing Shift` en POS Awesome hardcodea `"Efectivo"`, las vistas previas disparan `submit_printed_invoices()` en `GET`, y `Restaurant Manager` queda bloqueado al intentar cerrar turno ajeno desde `Arqueo de Cierre` (`DEF-QA-04`, `VERIFIED`). |
| **Capacidad Multisucursal (3 sucursales)** | **NO GARANTIZADA / INCOMPLETA** | `Restaurant Order`, `Restaurant Cash Count`, `POS Profile` y `Restaurant Preparation Display` carecen de campo `branch`. El filtro `if has_field("branch")` en `pos.py:1312, 3320` nunca se activa (`DEF-QA-06`, `VERIFIED`), ni `transfer_account` bloquea traslados entre sucursales (`DEF-MB-008`, `VERIFIED`). |
| **Convención de idiomas (Código EN / UI ES)** | **MAYORMENTE CONFORME** | Código principalmente en inglés (excepciones menores: `total_ingreso`, `precuenta_printed`); etapas sembradas en `kds_setup.py` están en inglés (`"To cook"`, `"Ready"`, `"Completed"`) y mensajes internos de `erpnext`/`posawesome` salen en inglés al usuario. |
