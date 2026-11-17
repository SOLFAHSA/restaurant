# Informe de Regresión (`2026-11-16` vs. Línea Base `2026-11-13`)

---

## 1. Evolución Verificada de la Suite Automatizada (`VERIFIED`)

| Corte | Fecha | Comando | Total Tests | OK | Expected Failures | FAIL / ERROR inesperados | Duración |
|---|---|---|---:|---:|---:|---:|---:|
| **Auditoría QA inicial** | `2026-11-13` | `bench --site development run-tests --app restaurant --skip-test-records` | 177 | 129 | 2 | `1 FAIL`, `45 ERROR` | 166.61s |
| **Post-remediación P0/P1** | `2026-11-13` | `bench --site development run-tests --app restaurant --skip-test-records` | 177 | 175 | 2 | `0` | 139.56s |
| **Post-actualización SAR Ticket** | `2026-11-14` | `bench --site development run-tests --app restaurant --skip-test-records` | 181 | 179 | 2 | `0` | 164.80s |
| **Auditoría integral hoy (línea base + SAR)** | `2026-11-16` | `bench --site development run-tests --app restaurant --skip-test-records` | 181 | 179 | 2 | `0` | 146.04s |
| **Auditoría integral ampliada (`+ test_qa_comprehensive_audit.py`)** | `2026-11-16` | `bench --site development run-tests --app restaurant --skip-test-records` | **197** | **183** | **14** | **0** | **263.20s** |
| **Post-remediación P0/P1 + Realtime KDS + Batching SQL** | `2026-11-16` | `bench --site development run-tests --app restaurant --skip-test-records` | **199** | **199** | **0** | **0** | **266.27s** |

---

## 2. Verificación de Módulos Tras Cambios Recientes (Arqueo + Formato SAR Ticket) (`VERIFIED`)

1. **Pruebas existentes conservadas en verde (`179/179` sin regresiones inesperadas):**
   - `test_pos_startup.py`, `test_order_operations.py` (`35` tests), `test_kds.py` (`28` tests), `test_item_configuration.py` (`28` tests), `test_pos_auth.py` (`6` tests), `test_demo_data.py` (`5` tests), `test_restaurant_cash_count.py` (`6` tests), `test_restaurant_area*.py` (`18` tests), `test_restaurant_command.py` (`15` tests), `test_restaurant_table.py` (`4` tests), `test_sar_ticket.py` (`4` tests).
2. **Regresiones funcionales e integraciones descubiertas al eliminar mocks en `test_qa_comprehensive_audit.py`:**
   - **Facturación con tasas mixtas (`DEF-QA-12` / `DEF-2026-001`):** No había aparecido antes porque `test_order_operations.py` y `test_kds.py` mockeaban `Sales Invoice`, y `test_sar_ticket.py` probó un único ítem al 15%.
   - **Sobrescritura de `set_missing_values()` (`DEF-QA-05` / `DEF-2026-002`):** No se había detectado con `update_stock=0` en un perfil o sin combinar `Exonerado` + `POS Profile(Contribuyente)`.
   - **Desalineación de permisos en Pages y caché local (`DEF-QA-01`, `DEF-QA-09`, `DEF-QA-11`):** Expuestos al ejecutar la matriz real de usuarios `Direct Cashier`, `Restaurant User` en KDS e intentos repetidos de PIN en memoria sin limpiar `frappe.local.cache`.
