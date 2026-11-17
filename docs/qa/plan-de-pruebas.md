# Plan de Pruebas Integral en 7 Capas — Módulo Restaurante LEAF ERP

**Fecha:** `2026-11-16`  
**Entorno de ejecución:** Contenedor DevContainer `frappe_docker14_devcontainer-frappe-1`, sitio `development` (`http://127.0.0.1:8000`), MariaDB `10.6.28`, Redis Cache/Queue.  
**Política de seguridad de datos:** Toda prueba escrita en Python (`FrappeTestCase`) corre dentro de un `SAVEPOINT` transaccional (`frappe.db.savepoint` + `rollback`) garantizando **0 registros residuales** en la base `development`. Las pruebas de carga HTTP operan sobre consultas autenticadas de solo lectura y las pruebas de contención MariaDB ejecutan `ROLLBACK` explícito en ambas conexiones.

---

## 1. Estrategia en 7 Capas

| Capa | Objetivo | Suites / Scripts ejecutados | Estado en entorno |
| :--- | :--- | :--- | :--- |
| **1. Unit Testing** | Validadores puros, conversiones UOM, letras Lempira exactas, permisos estáticos, color/etapas, denominaciones | `test_sar_ticket.py`, `test_item_configuration.py`, `test_*` en `doctype/*/`, `test_qa_comprehensive_audit.py` | **Ejecutado (`VERIFIED`)** *(Cobertura `%` no determinada: falta `coverage`)* |
| **2. Integración Real** | `Restaurant Order` ↔ `Sales Invoice` (SAR/GL) ↔ `POS Opening/Closing Shift` ↔ `Retiro de efectivo` ↔ `Restaurant Cash Count` ↔ `KDS` | `test_qa_comprehensive_audit.py` (sin mocks en ERPNext/POS Awesome/MariaDB), `test_sar_ticket.py` | **Ejecutado (`VERIFIED`)** |
| **3. Funcional (Reglas A–J)** | Configuración, aperturas, cuentas/mesas, split/transfer/merge, precuenta, pagos mixtos, exoneraciones, PIN/auditoría | `test_order_operations.py`, `test_kds.py`, `test_pos_auth.py`, `test_restaurant_cash_count.py`, `test_qa_comprehensive_audit.py` | **Ejecutado (`VERIFIED`)** *(Impresión física TCP simulada con mock de `socket`)* |
| **4. Operación Multisucursal** | Simulación simultánea de **3 sucursales × 10 usuarios = 30 usuarios** (9 cajeros, 15 meseros, 6 cocina + 3 supervisores) y aislamiento `Branch` | `test_01_three_branch_thirty_user_full_operational_simulation`, `test_def_qa_06_*`, `test_multibranch_concurrency.py` | **Ejecutado (`VERIFIED`)** |
| **5. Seguridad, RBAC y Negativas** | Bypass HTTP directo, permisos por rol y página Desk, PIN rate-limit (Redis TTL/local cache), autoautorización, SQLi y `Guest` | `test_pos_auth.py`, `test_rbac_security_regression.py`, `test_qa_comprehensive_audit.py` + sondas HTTP en vivo | **Ejecutado (`VERIFIED`)** |
| **6. Carga, Rendimiento y Resistencia** | Benchmark progresivo **10, 30, 50 y 100 usuarios**, prueba sostenida (soak 20u/20s), RSS RAM, `SHOW GLOBAL STATUS` y perfilado SQL N+1 | `qa_load_and_concurrency.py` contra `127.0.0.1:8000` + `test_02_sql_query_count_and_n_plus_one_profile` + test `FOR UPDATE` 2 conexiones | **Ejecutado (`VERIFIED`)** *(En servidor dev single-process `frappe serve` + `debugpy`; staging multi-worker `BLOCKED`)* |
| **7. E2E Navegador (Playwright)** | Flujos visuales desktop/móvil/tablet de POS, KDS, Comandas e Ítems (`tests/ui/*.cjs`) | 7 scripts `.cjs` en `restaurant/tests/ui/` | **`BLOCKED`** (`playwright` y Chromium no instalados en `node_modules`) |

---

## 2. Criterios de Evaluación y Salida

- **Integridad contable:** `SUM(debit) - SUM(credit) = 0.00` en `GL Entry` para toda factura generada.
- **Tributación SAR:** Cálculo exacto en centavos (`disable_rounded_total = 1`), tasas ISV 15%/18%/Exento sin doble cobro, preservación de `Exonerado` y trazabilidad en formato térmico `Ticket`.
- **Rendimiento objetivo (referencia):** P95 < `2,000 ms` en operaciones interactivas, `< 1%` tasa de error bajo carga normal, `0` facturas duplicadas y estabilidad de memoria sin fugas en ejecución sostenida.
- **Criterio de veredicto:** Cualquier defecto **P0/P1 reproducible** en impuestos, inventario, permisos o aislamiento multisucursal impide otorgar aprobación incondicional a producción.
