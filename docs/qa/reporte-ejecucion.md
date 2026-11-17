# Reporte de Ejecución QA (`2026-11-16`)

---

## 1. Resumen Global de Pruebas Ejecutadas tras la Última Edición (`VERIFIED`)

| Verificación | Comando / Fuente | Ejecutadas | Aprobadas | Expected Failures (Defectos Reproducidos) | Fallos / Errores Inesperados | Tiempo | Estado Final |
|---|---|---:|---:|---:|---:|---:|---|
| **Sintaxis JS POS & KDS** | `node -c restaurant_pos.js && node -c restaurant_kds.js` | 2 archivos | 2 | 0 | 0 | <1s | **`VERIFIED` PASS** |
| **Sintaxis Python** | `env/bin/python -m py_compile apps/restaurant/restaurant/*.py apps/restaurant/restaurant/tests/*.py` | Todos `.py` | Todos | 0 | 0 | <2s | **`VERIFIED` PASS** |
| **Migración esquema e índices** | `bench --site development migrate && bench --site development clear-cache` | 25+ DocTypes | Todos | — | 0 | ~30s | **`VERIFIED` PASS** |
| **Suite completa `restaurant` (Post-remediación P0/P1 + Realtime KDS)** | `bench --site development run-tests --app restaurant --skip-test-records` | **199** | **199** | **0** *(14 defectos previos + 2 nuevos tests de realtime/SQL pasan)* | **0** | **266.266s** | **`VERIFIED` OK** |
| **Perfil SQL (Post-optimización)** | `test_02` + consola cálida | 8 APIs | — | — | 0 | — | **`get_kds_state`: `131 -> 22 SQL` (cálido) / `85 SQL` (tras `clear_cache`); `get_pos_bootstrap`: `646 -> 416 SQL` (cálido) / `496 SQL` (tras `clear_cache`) sin escrituras `GET`** |
| **Sondas HTTP RBAC (`Guest`) (Línea base previa)** | `qa_load_and_concurrency.py` contra `127.0.0.1:8000` | 7 endpoints | 7 (`HTTP 403`) | — | 0 | 0.24s | **`VERIFIED` PASS (pre-remediación)** |
| **Contención MariaDB `FOR UPDATE` (Línea base previa)** | `qa_load_and_concurrency.py` (2 conexiones PyMySQL reales) | 1 carrera controlada | 1 (`350.67 ms` bloqueo, rollback limpio) | — | 0 | 0.36s | **`VERIFIED` PASS (pre-remediación)** |
| **Benchmark Carga HTTP (`10u`..`100u` + `Soak`) (Línea base previa)** | `qa_load_and_concurrency.py` contra `127.0.0.1:8000` (`frappe serve` + `debugpy`) | **368** solicitudes | **320** | — | **48 timeouts (`ReadTimeout`)** *(requiere re-benchmark en Gunicorn tras optimización)* | ~167s | **`VERIFIED` FAIL en dev single-process (pre-remediación)** |
| **Pruebas UI Playwright (`tests/ui/*.cjs`)** | `playwright` / Chromium | 7 archivos `.cjs` | 0 | — | 0 | — | **`BLOCKED`** |
| **Cobertura de código (%)** | `env/bin/python -c "import coverage"` | — | — | — | — | — | **`BLOCKED`** |
| **Carga Staging Gunicorn + Impresora Física + SocketIO 9000 activo** | Entorno multi-worker + hardware ESC/POS + `bench socketio` | — | — | — | — | — | **`BLOCKED` (sin servicio `socketio:9000` en sesión `Bench Web`)** |

---

## 2. Integridad de la Base de Datos `development` Antes vs. Después de Toda la Batería (`VERIFIED`)

- `Restaurant Order`: `59` antes → **`59` después** · `Restaurant Order Item`: `199` → **`199`** (`0` huérfanos).
- `Sales Invoice`: `12` → **`12`** · `GL Entry`: `57` → **`57`** (`0` comprobantes desbalanceados).
- `Stock Ledger Entry`: `0` → **`0`** · `POS Opening Shift`: `8` → **`8`** · `Restaurant Cash Count`: `2` → **`2`**.
- `User`: `7` → **`7`** · `Employee`: `6` → **`6`** · `Restaurant Audit Log`: `5` → **`5`**.

---

## 3. Desglose de las 14 `expected failures` Previas — TODAS REMEDIADAS Y EN VERDE (`VERIFIED`) + 2 Nuevos Tests (`199/199 OK`)

1. `DEF-MB-003` (`test_multibranch_concurrency.py`): `save_pos_order` ahora usa `for_update=True` y exige `expected_modified`/`modified` actualizados (`TimestampMismatchError`). — **PASS (`VERIFIED`)**.
2. `DEF-MB-008` (`test_multibranch_concurrency.py`): `transfer_account` y `get_context` bloquean traslados y fusiones entre sucursales distintas. — **PASS (`VERIFIED`)**.
3. `DEF-QA-01` (`test_qa_comprehensive_audit.py`): `restaurant_pos.json` incluye `Restaurant Cashier` y `Restaurant Direct Cashier`. — **PASS (`VERIFIED`)**.
4. `DEF-QA-02` (`test_qa_comprehensive_audit.py`): `save_customer_with_rtn` exige `user_can_invoice()` y permisos nativos de `Customer` sin `ignore_permissions=True`; protege `CONSUMIDOR FINAL`. — **PASS (`VERIFIED`)**.
5. `DEF-QA-03` (`test_qa_comprehensive_audit.py`): `get_self_order_config` exige `_require_pos_user()`. — **PASS (`VERIFIED`)**.
6. `DEF-QA-04` (`test_qa_comprehensive_audit.py`): `close_pos_shift` + `setup.py` habilitan a `Restaurant Manager` para cerrar turnos mediante `Arqueo de Cierre` en su sucursal. — **PASS (`VERIFIED`)**.
7. `DEF-QA-05` (`test_qa_comprehensive_audit.py`): `preserve_restaurant_invoice_taxes` y `pay_and_invoice_order` preservan `update_stock=0`, `tax_category="Exonerado"` y exoneraciones tras `set_missing_values()`. — **PASS (`VERIFIED`)**.
8. `DEF-QA-06` (`test_qa_comprehensive_audit.py`): `Restaurant Order`, `POS Profile` y `get_pos_bootstrap` / `get_kds_state` / `get_emitted_commands` aíslan por `branch`. — **PASS (`VERIFIED`)**.
9. `DEF-QA-07` (`test_qa_comprehensive_audit.py`): `cash_count.py` restringe vista previa y registro de arqueos al cajero dueño del turno o supervisor en su sucursal. — **PASS (`VERIFIED`)**.
10. `DEF-QA-08` (`test_qa_comprehensive_audit.py`): `unlock_waiter_order` registra `result="Rechazado"` al fallar PIN. — **PASS (`VERIFIED`)**.
11. `DEF-QA-09` (`test_qa_comprehensive_audit.py`): `Restaurant Preparation Display`/`Stage` y `restaurant_kds.json` alineados para `Restaurant User` y `Restaurant Cashier`. — **PASS (`VERIFIED`)**.
12. `DEF-QA-10` (`test_qa_comprehensive_audit.py`): `pay_and_invoice_order` acredita `Restaurant Gift Card` (`Tarjeta de Regalo` MOP o `write_off_amount`) rebajando el saldo debido en efectivo. — **PASS (`VERIFIED`)**.
13. `DEF-QA-11` (`test_qa_comprehensive_audit.py`): Rate limit y tokens de PIN usan `cache.get_value(..., expires=True)`. — **PASS (`VERIFIED`)**.
14. `DEF-QA-12` (`test_qa_comprehensive_audit.py`): `pay_and_invoice_order` + hook `validate` fijan `rate=0` por fila de impuesto y `0.0` explícito en `item_tax_rate`, eliminando la doble tributación (33%) en tasas mixtas 15%+18%+Exento. — **PASS (`VERIFIED`)**.
15. `test_kds_realtime_event_emitted_on_order_and_ticket_mutations`: Verifica emisión de `frappe.publish_realtime("restaurant_kds_update", ..., after_commit=True)` al crear/editar órdenes (`doc_events`), enviar a cocina, mover etapa KDS (`kds._mutation_result`) y facturar. — **PASS (`VERIFIED`)**.
16. `test_kds_state_and_pos_config_sql_budget`: Verifica presupuesto SQL en lote (`get_kds_state` `<= 25 SQL` en estado cálido) y cero escrituras `GET` en `get_restaurant_pos_config`. — **PASS (`VERIFIED`)**.
