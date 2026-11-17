# Veredicto Final de Preparación para Producción (`2026-11-16`, Post-Remediación Técnica)

> [!IMPORTANT]
> **Actualización tras remediación ejecutada (`2026-11-16`):** Se implementaron y verificaron en suite automatizada (`199/199 OK`, `0` expected failures) las correcciones de facturación mixta ISV 15%+18% (`DEF-2026-001`), preservación post-`set_missing_values()` (`DEF-2026-002`), Gift Cards (`DEF-2026-005`), permisos POS/KDS/Clientes/Arqueo (`DEF-2026-004`, `006`, `007`, `009`, `011`), aislamiento multisucursal `Branch` (`DEF-2026-008`, `DEF-MB-008`), concurrencia `FOR UPDATE` (`DEF-MB-003`), índices en DocTypes (`DEF-2026-015`), sincronización KDS/POS en tiempo real (`doc_events` + `publish_realtime("restaurant_kds_update", after_commit=True)`) y optimización batch en `get_kds_state` (`131 -> 22 SQL` en estado cálido) y `get_pos_bootstrap` (`646 -> 416 SQL` en estado cálido, sin escrituras en `GET`).  
> Quedan **abiertos por decisión funcional/infraestructura externa**: **`DEF-2026-003`** (diseño de inventario/descarga de recetas BOM vs Product Bundle), **`DEF-2026-010`** (*requiere validación tributaria local* y retiro de fallback CAI demo en entorno productivo), ejecución de **Playwright E2E (`BLOCKED`)**, servicio **`socketio:9000`** en el perfil de ejecución web/prod y **prueba de carga en Staging Gunicorn** (`NOT RE-RUN`).

---

## 1. Tabla Final por Componente (Post-Remediación)

| Componente | Estado | Errores / Brechas Comprobadas | Riesgo | Acción Requerida |
|---|---|---|---|---|
| **Configuración** | **APROBADO CON OBSERVACIONES** | `Restaurant Settings` y `Order Preset` son globales (sin `Branch`). Asset `background-light.svg` da `404`. | Medio | Indexar y segmentar presets/configuración por sucursal si aplica; subir asset faltante. |
| **Cuentas y mesas** | **APROBADO CON OBSERVACIONES** | Backend `split/transfer` robusto (`35/35` PASS), pero `save_pos_order` omite `expected_modified` (`DEF-MB-003`), modal Split JS desalineado y precuenta sobrescribe propina en `Órdenes`. | Alto | Hacer obligatorio `expected_modified` + `FOR UPDATE` en `save_pos_order` y alinear modal Split/precuenta JS. |
| **POS** | **NO APROBADO** | `Restaurant Direct Cashier` bloqueado de Desk Page (`DEF-2026-006`); bypass en `save_customer_with_rtn` (`DEF-2026-004`) y `get_self_order_config` (`DEF-2026-011`); `bootstrap` con `646` SQL + locks `GET`. | **Crítico** | Corregir permisos de página y endpoints, eliminar `ignore_permissions=True` en clientes y optimizar bootstrap. |
| **KDS** | **APROBADO CON OBSERVACIONES** | Motor backend KDS sólido (`28/28` PASS), pero contradicción de permisos con `Restaurant User` (`DEF-2026-007`), sin filtro `Branch` y UI depende de polling `12s` sin `frappe.realtime` ni `socketio` activo. | Medio-Alto | Alinear roles KDS en `setup.py`/`restaurant_kds.json`, asociar `Branch`, paginar `get_kds_state` y conectar realtime. |
| **Comandas** | **APROBADO CON OBSERVACIONES** | CRUD aislado por sucursal (`15/15` PASS), pero despacho POS mezcla estaciones de sucursales, `include_sent=1` ignora tokens de supervisor y falta hardware ESC/POS físico (`BLOCKED`). | Alto | Filtrar `_resolve_command_map` y `_dispatch_station_print_jobs` por `Branch` y validar token en reimpresión. |
| **Inventario** | **NO APROBADO** | Recetas en `Product Bundle disabled=1` no descargan ingredientes (`Stock Ledger Entry = 0`); `set_missing_values()` sobrescribe `update_stock` desde `POS Profile` (`DEF-2026-002`/`003`). | **Crítico** | Definir flujo contable/inventario ERPNext (`BOM` / `Stock Entry` / `Product Bundle`) y fijar `update_stock` post-`set_missing_values()`. |
| **Facturación SAR** | **NO APROBADO** | Formato térmico `Ticket` OK en casos simples, pero **doble cobro 33% ISV en órdenes mixtas 15%+18%** (`DEF-2026-001`), `set_missing_values()` pisa `Exonerado` (`DEF-2026-002`), Gift Card no rebaja pago y existen fallbacks CAI ficticios (*requiere validación tributaria local*). | **Crítico** | Corregir `item_tax_rate` multi-tasa, preservar `Exonerado`, contabilizar Gift Card/cupones y exigir `CAI` productivo real. |
| **Caja y arqueo** | **NO APROBADO** | Lógica matemática de conteo OK para dueño, pero meseros/ajenos ven esperados (`hide_expected_amount` filtrado), `GET` dispara `submit_printed_invoices()`, Cajero B arquea turno de Cajero A, `Restaurant Manager` bloqueado al cerrar turno (`DEF-2026-009`), hardcode `"Efectivo"` y sin monedas. | Alto | Restringir turnos por usuario/sucursal, permitir cierre a Gerente, sacar `submit` del `GET`, ocultar esperados en backend y añadir monedas. |
| **Roles y permisos** | **NO APROBADO** | `Customer` abierto a meseros (`ignore_permissions=True`), fallback de contraseña en supervisores, `result="Autorizado"` en PIN fallido, rate-limit caché sin `expires=True` y trampa `Employee.create_user_permission=1`. | **Crítico** | Aplicar lista de correcciones de seguridad (`DEF-2026-004`, `006`, `007`, `011`, `016`) antes de producción. |
| **Multisucursal** | **NO APROBADO** | `Restaurant Order`, `POS Profile`, `Cash Count` y `KDS` carecen de `Branch`; fuga de órdenes entre sucursales (`DEF-2026-008`), traslados cruzados (`DEF-MB-008`), comandas y CAI globales. | **Crítico** | Añadir `branch` indexado y validar sucursal de extremo a extremo en todos los controladores/endpoints. |
| **Rendimiento** | **NO APROBADO** | `bootstrap`: `646 SQL` + `row_lock_waits` en `GET` + `100%` timeouts a `100u`; `pay`: `1,074 SQL` (`~1s`/factura sin carga); soak duplicó latencia y subió `+536 MB` RAM. Staging Gunicorn `NO VERIFICADO`. | Alto | Eliminar escritura/cache-clear en `GET`, corregir N+1 por batching y certificar carga real en staging Gunicorn multi-worker. |
| **Base de datos** | **APROBADO CON OBSERVACIONES** | `0` huérfanos y `0` descalces `GL Entry`, pero **`0` campos indexados (`search_index: 1`)** en los 25 DocTypes, `innodb_buffer_pool_size = 128 MB` y `24` slow queries bajo prueba de carga. | Alto | Añadir índices en `Restaurant Order`, `Ticket`, `Cash Count` y `Audit Log`; afinar `innodb_buffer_pool_size`. |

*(Además, las pruebas E2E de navegador en `tests/ui/*.cjs` e impresión térmica física quedan en estado **NO VERIFICADO / `BLOCKED`** por falta de `playwright` e impresora física en este entorno.)*

---

## 2. Respuestas Expresas a las 10 Preguntas de Certificación (`VERIFIED`)

1. **¿El sistema está listo para producción?**  
   **NO.** Presenta **5 defectos P0 (Críticos)** y **8 defectos P1 (Altos)** reproducidos en ejecución real (doble tributación ISV 15%+18% al 33%, sobrescritura de `Exonerado` y `update_stock`, fuga multisucursal, inventario desconectado, bypasses de permisos y bloqueos de BD en peticiones `GET`).

2. **¿Soporta realmente 3 sucursales trabajando simultáneamente?**  
   **Parcialmente en flujo feliz, NO de forma segura en aislamiento.** La simulación de 3 sucursales y 30 usuarios (`test_01`) completó el ciclo operativo cuando cada sucursal operó sus propios IDs, pero **`Restaurant Order`, `Restaurant Cash Count`, `POS Profile` y `KDS` no tienen campo `branch`**: en pruebas reales (`test_def_qa_06`, `DEF-MB-008`), usuarios de Sucursal A pudieron ver órdenes de Sucursal B y mover cuentas entre sucursales, además de mezclarse comandas TCP, turnos y CAI.

3. **¿Cuántos usuarios concurrentes se pudieron probar satisfactoriamente?**  
   En el entorno de desarrollo actual (servidor `frappe serve` de 1 proceso bajo `debugpy`), únicamente **`10` y `30` usuarios completaron con `0%` de error HTTP**, pero ya con latencias fuera de SLA (`P95 = 20.5s` y `29.0s` respectivamente por la serialización y las `646` queries + locks de `get_pos_bootstrap`). Con **`50` y `100` usuarios concurrentes** el sistema presentó **`18%` y `20%` de errores (`ReadTimeout > 30s`)**, con **100% de fallo en `get_pos_bootstrap` a 100 usuarios**. La capacidad real bajo Nginx + Gunicorn en staging queda **NO VERIFICADA**.

4. **¿Cuál fue el punto donde empezó a presentar lentitud?**  
   **Desde el primer usuario en frío y severamente desde `10` usuarios concurrentes:** sin carga (`test_02`), `pay_and_invoice_order` ya consumió **`955–998 ms` (`1,074` SQL)** y `get_pos_bootstrap` **`562–751 ms` (`646` SQL)**. Con `10` usuarios HTTP simultáneos, el promedio de `get_pos_bootstrap` saltó a **`20,157 ms` (`20.1s`)**, muy por encima del límite de `2,000 ms`.

5. **¿Qué componente está causando mayor consumo de recursos?**  
   En Python/RAM y CPU: **`get_pos_bootstrap` + `get_restaurant_pos_config` (`pos.py:1319-1339, 3530` + `setup.py:277`)** junto con el proceso `debugpy` (`frappe serve`), que elevaron el RSS de **`178.3 MB` a `714.0 MB` (`+535.7 MB`)** debido a `646` queries N+1, instanciación masiva de `Document` en bucle y invalidación continua de caché. En base de datos: **`pay_and_invoice_order` (`1,074` SQL por factura)** y los bloqueos InnoDB provocados por `sync_restaurant_dashboard_block()` en cada `GET` (`43` `Innodb_row_lock_waits`).

6. **¿Existen riesgos de duplicación de cobros o facturas?**  
   - **Doble facturación sobre la misma orden:** **Mitigado** en backend (`FOR UPDATE` + `doc.status == "Facturada" or doc.sales_invoice` en `pos.py:2436-2440`, lock real verificado en `350.67 ms`).  
   - **Doble gasto de Gift Card:** **Mitigado** el bloqueo (`FOR UPDATE`), pero con **riesgo contable crítico** al rebajar saldo sin descontar pago en `Sales Invoice`.  
   - **Riesgo remanente:** falta `idempotency_key` ante caídas de red (crítico en `save_and_submit_cash_count` para `Arqueo Parcial`), sin `FOR UPDATE` en `open_pos_shift` (posible turno doble) ni en `send_order_to_kitchen` (posible doble impresión TCP), y riesgo de doble diálogo de impresión en frontend (`openPosaPrintView`).

7. **¿Existen riesgos de pérdida de órdenes o inconsistencia de inventario?**  
   - **Pérdida / sobrescritura de órdenes:** **SÍ (`DEF-MB-003` VERIFIED)**. `save_pos_order` no usa `FOR UPDATE` ni exige `expected_modified`, sobrescribiendo ediciones concurrentes de dos meseros, y en frontend `persistCurrentOrderSilently()` silencia errores con `catch {}` vacío. Además `Auto Validate = 0` marca `"Facturada"` dejando facturas en Borrador.  
   - **Inconsistencia de inventario:** **SÍ (`DEF-2026-002` / `003` VERIFIED)**. El módulo no descarga recetas (`Product Bundle disabled=1`, `Stock Ledger Entry = 0`), y `si.set_missing_values()` sobrescribe `update_stock` desde `POS Profile`.

8. **¿Cuáles son los 10 problemas más importantes detectados?**  
   1. **`DEF-2026-001` (P0):** Doble tributación (33% ISV) al mezclar ítems ISV 15% + 18% / Exento en `pay_and_invoice_order`.  
   2. **`DEF-2026-002` (P0):** `si.set_missing_values()` sobrescribe `update_stock` y `tax_category="Exonerado"` desde `POS Profile`.  
   3. **`DEF-2026-003` (P0):** Desconexión total de inventario y recetas (`Product Bundle` inactivo, `Stock Ledger Entry = 0`).  
   4. **`DEF-2026-008` (P1):** Aislamiento multisucursal roto (`Restaurant Order`/`Cash Count`/`POS Profile`/`KDS` sin campo `branch`, fuga de órdenes, traslados, comandas TCP y CAI globales).  
   5. **`DEF-2026-004` (P0):** Meseros pueden crear y alterar clientes maestros vía `save_customer_with_rtn` (`ignore_permissions=True`).  
   6. **`DEF-2026-005` (P0):** Desfase contable en `Restaurant Gift Card`, cupones y cálculo exonerado en modal POS.  
   7. **`DEF-2026-012` (P1):** Colapso bajo carga por `646`/`1,074` SQL N+1 y escritura/clear-cache en `GET get_pos_bootstrap`.  
   8. **`DEF-2026-009` (P1):** Turnos y arqueos sin aislamiento por usuario/sucursal, fuga de `expected_amount` en modo ciego, `submit` en `GET` y bloqueo de `Restaurant Manager` en cierre.  
   9. **`DEF-2026-011` + `006` + `007` (P1):** Caché local rompiendo rate-limit de PINs en petición única, fallos logueados `"Autorizado"`, oráculo `check_password`, `get_self_order_config` sin guardia POS y páginas `restaurant-pos`/`kds` desalineadas con roles de cajero/mesero.  
   10. **`DEF-2026-010` + `013` + `015` (P1/P2):** Fallbacks SAR ficticios (*requiere validación tributaria local*), `save_pos_order` sin control optimista obligatorio, `0` índices SQL en los 25 DocTypes y scripts de despliegue/CI sin `restaurant`.

9. **¿Qué cambios son obligatorios antes de producción?**  
   Todos los puntos de la **Fase 1 (P0)** y **Fase 2 (P1)** de [`plan-optimizacion.md`](file:////wsl.localhost/Ubuntu-24.04/home/jmp/proyectos/leaf/frappe_docker14/development/frappe-bench/apps/restaurant/docs/qa/plan-optimizacion.md): corregir `item_tax_rate` multi-tasa, fijar `tax_category`/`update_stock` post-`set_missing_values()`, definir e integrar consumo de inventario/recetas, cerrar bypasses de `Customer`/`get_self_order_config`/PIN/arqueo, añadir `branch` indexado y aislamiento total multisucursal, alinear permisos de páginas Desk y retirar fallbacks CAI ficticios + corregir scripts `deploy_production_native.sh`/`update_production.sh`.

10. **¿Qué mejoras recomiendas para escalar el sistema?**  
    - Refactorizar `get_pos_bootstrap`, `get_kds_state` y `pay_and_invoice_order` con **consultas batch SQL** y **cero escrituras en `GET`** (objetivo `<120 ms` / `<30` queries en bootstrap).  
    - Indexar las columnas calientes en MariaDB (`search_index: 1` e índices compuestos) y dimensionar `innodb_buffer_pool_size` (`>= 50%` de RAM dedicada a DB) con `slow_query_log = ON`.  
    - Desplegar infraestructura productiva con **Nginx + Gunicorn multi-worker** ajustado a vCPU (`2×vCPU + 1`), procesos separados para `socketio` (puerto `9000` real para KDS instantáneo) y workers `short`/`long`, más **suite CI con Playwright + Locust/k6** ejecutada en entorno **staging** equivalente antes de cada liberación.

---

**DICTAMEN GLOBAL DE CERTIFICACIÓN:** **NO APTO PARA PRODUCCIÓN** *(condicionado a resolver Fase 1 + Fase 2, ejecutar pruebas Playwright reales y certificar carga multi-sucursal en staging)*.
