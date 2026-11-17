# Informe de Rendimiento, Perfilado SQL y Diagnóstico de Lentitud (`2026-11-16`)

**Entorno medido (`VERIFIED`):**
- Contenedor `frappe_docker14_devcontainer-frappe-1` (`16 vCPU`, `23,891 MB` RAM, `MariaDB 10.6.28`).
- **Advertencia metodológica obligatoria:** El servidor web activo en el puerto `8000` durante las pruebas HTTP es el servidor de desarrollo de proceso único (`frappe serve --port 8000 --noreload` bajo `debugpy`, PID `2908`), **no** un clúster Nginx + Gunicorn (`gunicorn_workers: 33` no estaba activo en `8000`) y `innodb_buffer_pool_size` está en su mínimo por defecto (`128 MB`). Por ello se realizaron tanto **mediciones aisladas en Python (sin Werkzeug/debugpy)** como **pruebas HTTP concurrentes (10, 30, 50 y 100 usuarios)**.

---

## 1. Perfilado Exacto de Consultas SQL por Operación (En Python, 1 usuario, BD real con 59 órdenes y 40 ítems) (`VERIFIED`)

Medido instrumentando `frappe.db.sql` dentro de `test_02_sql_query_count_and_n_plus_one_profile`:

| Operación / Endpoint | Consultas SQL | Latencia (ms) | Diagnóstico |
| :--- |---:|---:| :--- |
| `get_locations(page_length=20)` | **2** | **1.33 ms** | **Referencia óptima** (paginado sin N+1) |
| `validate_order(doc)` | **22** | **11.11 ms** | Moderado; repite `_resolve_command_map()` en cada validación |
| `get_commands(page_length=20)` | **35** | **31.11 ms** | Patrón N+1 (`frappe.get_doc` por comanda tras `get_list`) |
| `get_kds_state()` | **131** | **115.27 ms** | N+1 severo: carga todas las órdenes sin límite + ticket/etapa en bucle |
| `get_cash_count_preview()` | **167** | **232.84 ms** | Llama `make_closing_shift_from_opening` leyendo facturas y retiros en bucle |
| `save_pos_order()` (1 ítem) | **356** | **372.40 ms** | Dispara carga de maestro, recálculo N+1 y sincronización completa |
| **`get_pos_bootstrap()`** | **646** | **631.83 ms** | **Cuello de botella crítico**: `59` llamadas `_serialize_order` + `sync_restaurant_dashboard_block()` (muta BD en GET) + `clear_cache()` |
| **`pay_and_invoice_order()`** (1 ítem) | **1,074** | **998.08 ms** | **~1 segundo por factura incluso sin carga concurrente**, invocando múltiples `validate_order`, resolución repetida de cuentas y cálculo ERPNext |

---

## 2. Benchmark HTTP Progresivo en Vivo (`10`, `30`, `50`, `100` usuarios + Soak `20u/20s`) (`VERIFIED`)

Tráfico autenticado contra `http://127.0.0.1:8000` mezclando operaciones reales (`get_pos_bootstrap`, `get_kds_state`, `get_commands`, `get_locations`, `get_restaurant_stock_status`, timeout HTTP = `30s`):

| Escenario | Concurrencia | Solicitudes | Éxitos | Error % | RPS | Ops/min | Avg (ms) | P50 (ms) | P95 (ms) | P99 (ms) | Max (ms) | `get_pos_bootstrap` Avg (ms) | RSS inicio → fin (MB) | Row Lock Waits Δ | Slow Queries Δ |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|---:|
| **10 usuarios** | 10 | 40 | 40 | **0.0%** | 1.52 | 91.4 | 5,583 | 2,035 | **20,545** | 24,148 | 24,322 | 20,157 ms | 178.3 → 228.2 | **7** | 0 |
| **30 usuarios** | 30 | 90 | 90 | **0.0%** | 2.79 | 167.4 | 6,897 | 1,233 | **29,025** | 29,676 | 29,707 | 27,137 ms | 228.2 → 325.1 | **17** | 0 |
| **50 usuarios** | 50 | 100 | 82 | **18.0%** | 2.20 | 132.0 | 6,016 | 5,965 | **18,636** | 27,723 | 29,173 | 28,278 ms | 325.1 → 442.4 | **19** | 0 |
| **100 usuarios** | 100 | 100 | 80 | **20.0%** | 2.65 | 158.9 | 13,793 | 10,468 | **27,720** | 27,897 | 27,990 | **Timeout (`>30s`, 100% fallo)** | 442.4 → 644.3 | 0 *(abortado)* | **6** |

### Prueba de Resistencia Sostenida (`soak_20u_20s`: 20 usuarios continuos durante ~20–40s) (`VERIFIED`)
- **Solicitudes exitosas:** `28` · **Errores (`ReadTimeout`):** `10` (`26.3%` fallo) · **Duración real incluyendo colas:** `40.71s` · **RPS:** `0.69`.
- **Degradación progresiva detectada:**
  - *Primera mitad:* Avg `7,508.8 ms` · P95 `8,457.6 ms`.
  - *Segunda mitad:* Avg **`14,880.8 ms`** (casi **2× más lento**) · P95 **`24,417.7 ms`**.
- **Consumo RAM del proceso Python (`PID 2908`):** Subió de `178.31 MB` al inicio del benchmark hasta **`713.99 MB`** al final del soak (**`+535.68 MB` acumulados**; **`+69.68 MB`** solo durante el soak), y se dispararon **`24` slow queries (>10s)** acumuladas entre el nivel 100u y el soak.

---

## 3. Prueba Real de Contención de Bloqueos en MariaDB (`FOR UPDATE`) (`VERIFIED`)

Ejecutado con **dos conexiones TCP PyMySQL reales e independientes** contra la tabla `tabRestaurant Order` (`ORD-00005`):
1. Conexión 1 abrió `BEGIN`, ejecutó `SELECT name FROM tabRestaurant Order WHERE name='ORD-00005' FOR UPDATE`, retuvo el bloqueo `0.35s` y ejecutó `ROLLBACK`.
2. Conexión 2 ejecutó simultáneamente el mismo `FOR UPDATE`: quedó bloqueada exactamente **`350.67 ms`** esperando a Conexión 1 y adquirió la fila limpiamente inmediatamente tras el `ROLLBACK` (`acquired_after_rollback=ORD-00005`), confirmando que los row-locks InnoDB operan correctamente cuando existen (`VERIFIED`).

---

## 4. Diagnóstico Formal de Lentitud y Consumo (Síntoma → Causa Comprobada → Evidencia → Solución) (`VERIFIED`)

### Hallazgo de Rendimiento 1 — Escritura y `clear_cache()` dentro de `GET get_pos_bootstrap`
- **Síntoma:** Con apenas `10` usuarios concurrentes, `get_pos_bootstrap` promedia **`20.16s`** (`P95 = 20.5s`) y genera **`7` a `19` esperas de bloqueo InnoDB (`Innodb_row_lock_waits`)** siendo una petición `GET`. A `100` usuarios sufre **100% de timeouts (`>30s`)**.
- **Causa comprobada:** `get_pos_bootstrap()` (`pos.py:1339`) llama a `get_restaurant_pos_config()` (`pos.py:3530`), que llama a **`sync_restaurant_dashboard_block()` (`setup.py:259-288`)**. Esta función lee un JSON del disco, ejecuta **`frappe.db.set_value("Custom HTML Block", "Restaurant Dashboard", ...)`** (bloqueando esa fila en MariaDB en cada petición `GET`) y llama a **`frappe.clear_cache(doctype="Custom HTML Block")`**, invalidando la caché compartida mientras los demás hilos consultan. Además `pos.py:1328-1332` dispara escrituras en bucle si existen nombres con prefijo `"Orden "`.
- **Evidencia:** `db_row_lock_waits_delta = 7 (10u), 17 (30u), 19 (50u)` y `646` queries por bootstrap (`test_02` + `qa_load_and_concurrency.py`).
- **Solución propuesta:** Mover `sync_restaurant_dashboard_block()` únicamente a `after_migrate` / hash-check en Redis (nunca en `GET` ni `clear_cache` en lectura) e idempotente solo en migración.
- **Impacto esperado:** Eliminación total de bloqueos InnoDB y `clear_cache` en lectura POS (`>80%` reducción de contención).

### Hallazgo de Rendimiento 2 — N+1 Masivo en Bootstrap (`646` SQL), Facturación (`1,074` SQL), Arqueo (`167` SQL) y KDS (`131` SQL)
- **Síntoma:** Un solo `get_pos_bootstrap` tarda `631–751 ms` sin carga y `pay_and_invoice_order` tarda `998 ms` (`~1s` por factura). En un servidor con `debugpy`/1 proceso la cola satura con `1.5–2.8 RPS`, superando ampliamente el objetivo `P95 < 2,000 ms` desde `10` usuarios.
- **Causa comprobada:**
  - `pos.py:1319-1333`: descarga órdenes y llama `_serialize_order(row.name)` en bucle (`frappe.get_doc`, `get_linked_employee_for_user`, `employee_has_pin` descifrado SQL, acceso caché) sumando `646` queries con solo 59 órdenes.
  - `pos.py:187-201` y `2056-2080`: `_resolve_command_map()` y `get_command_configs()` hacen `1 + N` queries en **cada** `validate_order`.
  - `kds.py:237-281`: carga todas las órdenes KDS sin límite (`limit_page_length=0`) con `frappe.get_doc` uno por uno y doble bucle `displays × orders`.
  - `cash_count.py:581-582` + `pos.py:1744`: reconstruye `make_closing_shift_from_opening()` hasta 3 veces seguidas por arqueo de cierre.
- **Solución propuesta:** Consultas batch (`IN (...)`) en `_serialize_orders_batch()`, caché TTL corto para `_resolve_command_map()`, paginación/filtro por ventana activa y sucursal en KDS (`limit_page_length`), y evitar múltiples recomputaciones en `cash_count.py`.
- **Impacto esperado:** Reducción de `646` a `<30` queries en bootstrap (`<120 ms`) y de `131` a `<15` queries en KDS.

### Hallazgo de Rendimiento 3 — Ausencia Total de Índices en MariaDB, `debugpy` y Crecimiento de RAM
- **Síntoma:** Latencia del soak se duplicó (`7.5s` → `14.8s`), `Slow_queries` subió `+24`, y el RSS del proceso Python subió de `178 MB` a `714 MB` (`+536 MB`).
- **Causa comprobada:** `0` campos con `search_index: 1` en los 25 DocTypes (`SHOW INDEX` verificado), `innodb_buffer_pool_size = 128 MB`, entorno ejecutando `bench serve` single-process bajo `debugpy` (que retiene referencias/objetos en memoria durante trazas y serializa peticiones).
- **Solución propuesta:** Agregar `search_index: 1` e índices compuestos en `tabRestaurant Order` (`(status, branch)`, `restaurant_table`, `sales_invoice`), `tabRestaurant Preparation Ticket` (`(restaurant_order, preparation_display)`), `tabRestaurant Cash Count` (`pos_opening_shift`) y `tabRestaurant Audit Log` (`restaurant_order`, `event_time`); probar rendimiento real sobre **Gunicorn multi-worker (`gunicorn -w 4..8`) + Redis separado + `innodb_buffer_pool_size >= 2 GB`** en staging.
