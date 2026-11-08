# Verificación de transferencias, fusiones y división — 6 de noviembre de 2026

## Resultado y arquitectura

**VERIFIED — Implementación aplicada** en la app independiente `restaurant`, sitio `development`, Python 3.11.15 y puerto 8000. Se conserva la rama `feature/modulo-restaurante` y el último commit `dbc5a9c`. No se hicieron commits ni push; se preservó el trabajo local anterior.

**ANALYZED — Native Path Check:** ERPNext mantiene los documentos de facturación, pagos, impuestos, contabilidad e inventario. LEAF redistribuye productos entre sus órdenes antes de la factura y conserva su preparación. Se reutilizan los DocTypes actuales y sus validaciones, permisos, eventos y APIs ORM. Un Workflow o una configuración declarativa no representa el remapeo de cantidades y tickets; por ello se aplica Nivel 3 / categoría C dentro de `restaurant`, sin core, overrides, nuevos DocTypes ni campos.

## Comportamiento entregado

- Transferir toda la cuenta a una mesa disponible o fusionarla con una cuenta existente, con o sin mesa.
- Elegir explícitamente la cuenta de destino si una mesa tiene varias cuentas.
- Dividir cantidades de platillos y abrir la cuenta separada con nombre opcional.
- Abrir el cobro existente después de dividir una selección parcial; cobrar la cuenta original cuando se selecciona todo.
- Transferir sólo los productos seleccionados en una única operación, sin dejar una cuenta intermedia si falla.
- Conservar opciones, notas, descuentos, cantidades, propinas, filas restantes y trazabilidad entre origen/destino.
- Dividir/fusionar durante preparación, conservando etapas, marcas, tiempos y retiro en grupos KDS independientes.
- Mantener cantidades fraccionales válidas hasta la comanda y el payload de la factura nativa, sin truncarlas a dos decimales.

La interfaz mantiene el menú de Acciones y la paleta de LEAF. La vista Dividir usa productos a la izquierda, importe seleccionado destacado a la derecha y botones Pago, Dividir orden y Transferir. El selector de destino permite buscar mesas o cuentas. Se revisó el diseño en escritorio y móvil.

## Respaldo y preservación

**VERIFIED:** respaldo previo de esta tarea: `sites/development/private/backups/20261106_162708-development-database.sql.gz`. No se requirió migración de esquema, parches de datos ni recálculo de históricos.

El punto de partida de esta tarea tenía 5 órdenes, 4 tickets KDS, 2 Sales Invoice y 8 GL Entry; POS Invoice, Payment Entry y Stock Ledger Entry tenían cero registros. Las pruebas usan savepoints y rollback. La comparación final de contenido y conteos se registró mediante SHA-256 de documentos completos y filas hijas, sin imprimir datos personales.

**VERIFIED — Cierre:** todos los SHA-256 y conteos coinciden con ese punto de partida. Los documentos existentes conservaron exactamente su contenido.

## Pruebas ejecutadas

**VERIFIED:** 89 pruebas de esta tarea aprobadas:

| Suite | Resultado |
| --- | --- |
| `restaurant.tests.test_order_operations` | 35 / 35 |
| `restaurant.tests.test_kds` | 28 / 28 |
| `restaurant.tests.test_pos_startup` | 7 / 7 |
| `restaurant.restaurant.doctype.restaurant_command.test_restaurant_command` | 15 / 15 |
| `restaurant.restaurant.doctype.restaurant_preparation_display.test_restaurant_preparation_display` | 4 / 4 |

Ejecutadas mediante `bench --site development run-tests --module <módulo> --skip-test-records` dentro del Bench con su entorno Python 3.11. También se ejecutaron compilación Python, `node --check`, `git diff --check`, limpieza de caché y comprobación HTTP después de reiniciar la depuración existente. Un único proceso web de depuración y `/login` HTTP 200.

| Dimensión | Evidencia |
| --- | --- |
| A — Estándar | VERIFIED: permisos nativos, unidades enteras/fraccionales, validación documental y carga del POS. |
| B — LEAF | VERIFIED: selección, división, movimiento completo/parcial, fusión, propinas, nombres y grupos KDS. |
| C — Integración | VERIFIED: separación seguida de invocación del emisor existente con `calculate_taxes_and_totals`, `insert` y `submit` simulados; el payload conserva cantidad `0.001`. No se emitieron facturas reales ni se registraron pagos reales. |
| D — Regresión | VERIFIED: KDS, arranque POS, comandas, cantidades y controlador de pantallas. |
| E — Históricos | VERIFIED: las órdenes/tickets existentes se preservan; una cuenta facturada, cancelada o con factura vinculada no se redistribuye. |
| F — Negativos | VERIFIED: cantidades inválidas/excesivas/duplicadas, perfiles incompatibles, falta de permisos, versiones desactualizadas, ticket ajeno y rollback tras fallo de remapeo. Los bloqueos están implementados y analizados; no se ejecutó una prueba de carga paralela. |
| G — Flujo | VERIFIED: operaciones reales de API con fixtures revertidos y navegación completa del POS con respuestas aisladas en navegador. |

**VERIFIED — Navegador:**

- `restaurant/tests/ui/order_operations.cjs`: menú de acciones, selección/cálculo/nombre, división, apertura del cobro parcial, cobro de todos sin división, transferencia parcial atómica, transferencia completa a mesa libre, fusión completa, cantidad fraccional y diseño móvil.
- `restaurant/tests/ui/kds.cjs`: dos tarjetas de la misma orden con distintos `ticket_id`, marcado y retiro independientes, dos rondas de preparación/entrega y vista móvil.

Los scripts leen el bootstrap/configuración real y aíslan las respuestas operativas; no mueven ni cobran cuentas reales. La prueba KDS guarda su configuración sin alterar valores para verificar persistencia.

## Perfiles activados

**ANALYZED:** los 15 perfiles se distribuyeron entre el orquestador y agentes especializados: orchestrator, functional-analyst-accountant, erpnext-logic-mapper, erpnext-core-behavior-researcher, upgrade-compatibility-reviewer, data-integrity-auditor, migration-patch-specialist, backend-implementer-frappe, frontend-wizard-js, frappe-test-engineer, qa-functional-accounting-auditor, docker-compose-platform-engineer, supply-chain-security-reviewer, ci-release-verification-engineer y repo-structure-git-guardian. No se requirieron cambios de infraestructura, dependencias ni CI.

## Observaciones

- El cálculo previo muestra diferencias de centavos cuando el redondeo existente de dos cuentas difiere del original; no se agregó un ajuste fiscal paralelo.
- Una fusión suma las propinas calculadas y deja la propina del destino como monto fijo, ajustable mediante el flujo existente.
- El retiro automático KDS mantiene su semántica de filtro reversible por tiempo; Listo registra el retiro persistente de cada grupo.
- No se ejecutaron cobros reales, una emisión fiscal real ni pruebas de carga. El emisor nativo continúa siendo la autoridad final al confirmar Pago.

**DICTAMEN FINAL: APROBADO CON OBSERVACIONES.** Auditoría sin hallazgos P1/P2 pendientes conocidos.

## Archivos de esta tarea

Rutas relativas al repositorio `development/frappe-bench/apps/restaurant/`. Los archivos que ya tenían trabajo local conservan esos cambios anteriores.

- `restaurant/order_operations.py`
- `restaurant/order_kds.py`
- `restaurant/pos.py`
- `restaurant/kds.py`
- `restaurant/restaurant/page/restaurant_pos/restaurant_pos.js`
- `restaurant/restaurant/page/restaurant_pos/restaurant_pos.css`
- `restaurant/restaurant/page/restaurant_kds/restaurant_kds.js`
- `restaurant/restaurant/doctype/restaurant_preparation_display/restaurant_preparation_display.py`
- `restaurant/restaurant/doctype/restaurant_preparation_display/test_restaurant_preparation_display.py`
- `restaurant/tests/test_order_operations.py`
- `restaurant/tests/test_kds.py`
- `restaurant/tests/ui/order_operations.cjs`
- `restaurant/tests/ui/kds.cjs`
- `docs/kitchen-display.md`
- `docs/kds-verificacion.md`
- `docs/transferir-dividir.md`
- `docs/transferir-dividir-verificacion.md`
