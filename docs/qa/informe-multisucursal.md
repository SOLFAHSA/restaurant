# Informe de Operación Multisucursal (3 Sucursales / 30 Usuarios) y Concurrencia (`2026-11-16`)

---

## 1. Simulación Real Ejecutada: 3 Sucursales y 30 Usuarios Operativos (`VERIFIED`)

Ejecutada mediante la prueba de integración sin mocks financieros [`test_01_three_branch_thirty_user_full_operational_simulation`](file:////wsl.localhost/Ubuntu-24.04/home/jmp/proyectos/leaf/frappe_docker14/development/frappe-bench/apps/restaurant/restaurant/tests/test_qa_comprehensive_audit.py) (en savepoint transaccional sobre BD `development`):

| Sucursal simulada | Cajeros | Meseros | Cocina | Supervisores | Turnos | Órdenes / Split / Facturas |
|---|---:|---:|---:|---:|---:|---|
| **Sucursal A** | 3 | 5 | 2 | 1 | `1` abierto (`L 500`) | Orden en mesa A-M1 → Comanda → KDS 3 etapas → Split → Traslado A-M2 → Precuenta → Cancelación ítem con PIN → `2` Facturas SAR (mixto + efectivo) → Retiro `L 20` → Arqueo → Ticket SAR |
| **Sucursal B** | 3 | 5 | 2 | 1 | `1` abierto (`L 500`) | Flujo completo paralelo sobre B-M1 / B-M2, almacén B, impresora TCP B simulada, KDS B |
| **Sucursal C** | 3 | 5 | 2 | 1 | `1` abierto (`L 500`) | Flujo completo paralelo sobre C-M1 / C-M2, almacén C, impresora TCP C simulada, KDS C |
| **Totales** | **9** | **15** | **6** | **3** | **3** | **6 Facturas SAR emitidas, 0 descalces `GL Entry`, 0 huérfanos (`65.5s`, PASS)** |

**Importante:** El flujo operativo completó correctamente en el escenario feliz **cuando** cada usuario solo operó sobre sus propios IDs y las tasas de una orden no mezclaron `15% + 18%`. Sin embargo, las pruebas negativas multisucursal y de concurrencia demostraron que **el aislamiento entre sucursales NO está garantizado todavía**.

---

## 2. Problemas Reales Detectados en Aislamiento Multisucursal (`VERIFIED` / `ANALYZED`)

| Área | ¿Aislado hoy? | Evidencia comprobada |
| :--- | :--- | :--- |
| **Áreas (`Restaurant Area`) y Mesas (`Restaurant Table`)** | **SÍ (CRUD)** | Tienen campo `branch`, validan `User Permission(Branch)` en `location.py` y `table_management.py`. *Brecha:* cambiar `branch` del área desincroniza la mesa si no se re-guarda; mover mesa entre áreas de distinta sucursal no bloquea si tiene órdenes activas. |
| **Comandas en maestro (`Restaurant Command`)** | **SÍ (CRUD)** | Tienen `branch` obligatorio y unicidad `(branch, command_name)` (`commands.py:134, 146`). |
| **Comandas en tiempo real (`pos.py` / Impresión TCP)** | **NO** | `_resolve_command_map` (`pos.py:187`), `get_command_configs` (`2056`) y `_dispatch_station_print_jobs` (`2170`) leen **todas** las comandas sin filtrar `branch`, mezclando estaciones entre sucursales y pudiendo imprimir en impresoras TCP de otra sucursal. |
| **Órdenes en POS (`get_pos_bootstrap` / `get_emitted_commands`)** | **NO (`DEF-QA-06` VERIFIED)** | `Restaurant Order` **no tiene campo `branch`**. Las líneas `pos.py:1312` y `pos.py:3320` (`if has_field("branch")`) son código muerto; probado en `test_def_qa_06` que un usuario de Sucursal A **ve la orden creada por Sucursal B**. |
| **Traslado / Fusión de mesas (`transfer_account`)** | **NO (`DEF-MB-008` VERIFIED)** | Probado en `test_transfer_account_blocks_cross_branch_table` (`@expectedFailure`): `order_operations.py:355` permite trasladar una cuenta desde una mesa de Sucursal A hacia una mesa de Sucursal B. |
| **KDS (`Restaurant Preparation Display`)** | **NO** | No posee campo `branch` ni `Restaurant Order` posee `branch`; si no se restringe manualmente por `pos_profiles` exactos, cualquier pantalla KDS recibe órdenes de todas las sucursales. |
| **Turnos, Movimientos de Caja y Arqueo (`cash_count.py`)** | **NO (`DEF-QA-07` VERIFIED)** | `Restaurant Cash Count`, `POS Opening Shift` y `Retiro de efectivo` carecen de `branch`. Probado en `test_def_qa_07` que **Cajero B (e incluso meseros) puede consultar esperados e insertar arqueos en el turno abierto de Cajero A**. |
| **Facturación SAR y CAI (`_resolve_sar_fiscal_info`)** | **NO** | `pos.py:1094, 1122` hace fallback global al primer `CAI` activo o última `Sales Invoice` del sitio sin filtrar `Company`/`Branch`, arriesgando emitir facturas de Sucursal B con rango CAI de Sucursal A. |
| **Supervisores por PIN (`_resolve_supervisor_by_pin`)** | **NO** | Si el frontend omite `supervisor_user`, `pos_auth.py:247` valida PIN contra supervisores de **todas las sucursales**. |
| **Trampa ERPNext `Employee.create_user_permission = 1`** | **BLOQUEO OPERATIVO** | Comprobado en ejecución (`test_03` antes de poner `0`): si en Desk se crea un `Employee` ligado al `user_id` de un **cajero** dejando activo el check por defecto `create_user_permission = 1`, ERPNext crea `User Permission(Employee)` y **bloquea al cajero de abrir/desbloquear órdenes de los meseros** (`Not allowed for Employee: HR-EMP-XXXXX. Restricted field: waiter`). |

---

## 3. Evaluación de Escenarios de Concurrencia y Resistencia (Sección 7) (`VERIFIED` / `ANALYZED`)

| Escenario | Estado real comprobado | Evidencia |
|---|---|---|
| **1. Dos cajeros facturan la misma cuenta** | **PROTEGIDO (`VERIFIED`)** | `pay_and_invoice_order` (`pos.py:2436`) bloquea la fila con `for_update=True` y rechaza si `status == "Facturada" or sales_invoice`. Verificado lock real en MariaDB (`350.67 ms` espera serializada). |
| **2. Dos meseros modifican simultáneamente una orden** | **RIESGO (`DEF-MB-003` VERIFIED)** | `save_pos_order` (`pos.py:1817`) no usa `FOR UPDATE` y vuelve opcional `expected_modified`, sobrescribiendo cambios concurrentes si se omite el timestamp. Además permite crear 2 órdenes simultáneas para la misma mesa `"Disponible"`. |
| **3. Varios usuarios venden el último producto disponible** | **DESCONECTADO (`ANALYZED`)** | `update_stock = 0` en POS (salvo sobrescritura accidental por `POS Profile.update_stock=1`); además los platillos compuestos usan `Product Bundle disabled=1` que no descuenta ingredientes en `Bin`/`Stock Ledger Entry`. |
| **4. Recibir una orden mientras otra se está cerrando / dividiendo** | **PARCIAL (`VERIFIED` / `ANALYZED`)** | `split`/`transfer` bloquean por `FOR UPDATE` + `savepoint` y remapean tickets KDS atómicamente (`test_order_operations.py`), pero `save_pos_order` no usa `FOR UPDATE` y `pos.py:1720` (`close_pos_shift`) bloquea el cierre si quedaron borradores (`POS Closing Shift` check). |
| **5. Sucursal A vende mientras Sucursal B actualiza inventario** | **PARCIAL (`ANALYZED`)** | Almacenes están separados por `POS Profile.warehouse`, pero `ensure_restaurant_stock` y `get_restaurant_stock_status` no restringen almacén por sucursal del gerente ni usan `FOR UPDATE`. |
| **6. Pérdida de conexión después de confirmar pago / reintento** | **PARCIAL (`ANALYZED`)** | No existe `idempotency_key` en `pay_and_invoice_order` ni en `save_and_submit_cash_count` (`Arqueo Parcial`). Para facturación, el segundo intento queda bloqueado porque la orden ya pasó a `Facturada`; para `Arqueo Parcial`, un reintento puede crear un arqueo duplicado y en frontend `persistCurrentOrderSilently` (`catch {}`) oculta fallos de red. |
| **7. KDS pierde conexión / dos operadores actualizan la misma orden** | **PARCIAL (`VERIFIED` / `ANALYZED`)** | Concurrencia backend entre dos operadores KDS está **protegida** (`FOR UPDATE` + `_check_expected_stage` verificado en `test_kds.py`). Pero al no existir `socketio` en puerto `9000` en dev y no suscribirse `restaurant_kds.js` a `frappe.realtime.on("restaurant_kds_update")`, la sincronización depende solo de polling cada `12s`. |
| **8. Impresora falla durante envío / reinicio de servicio** | **SIN REINTENTO (`ANALYZED`)** | `_dispatch_station_print_jobs` (`pos.py:2233`) conecta por TCP síncrono sin cola de reintentos ni `FOR UPDATE`; dos envíos simultáneos duplican tickets físicos. |
| **9. Prueba de resistencia sostenida (`soak_20u_20s`)** | **DEGRADACIÓN MEDIDA (`VERIFIED`)** | En `40.71s` continuos con `20` usuarios en `frappe serve` (`debugpy`), la latencia subió de `7.5s` → `14.88s`, hubo `10` timeouts (`26.3%`) y RSS creció `+69.7 MB` en ese intervalo. |
