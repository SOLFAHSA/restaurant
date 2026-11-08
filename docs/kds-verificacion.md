# Verificación del monitor de cocina — 6 de noviembre de 2026

> Este informe corresponde a la implementación inicial del KDS. La ampliación posterior de transferencias y divisiones conserva la preparación mediante grupos independientes y reemplaza el bloqueo anterior de dividir/fusionar. Consulta `transferir-dividir.md` y `transferir-dividir-verificacion.md` para el comportamiento vigente.

## Resultado

**VERIFIED — Implementado y migrado** en el sitio local `development`, Python 3.11.15, app independiente `restaurant`, rama conservada `feature/modulo-restaurante`. Acceso: http://localhost:8000/app/restaurant-kds.

**ANALYZED — Arquitectura:** Nivel 3 / categoría C. `POS Profile`, `Item Group`, `Item`, `Restaurant Order` y documentos fiscales nativos siguen siendo las fuentes de sus respectivos datos. Pantallas, etapas y tickets representan únicamente la preparación. No se modificaron repositorios core en esta tarea.

## Funcionalidad

- Pantallas persistentes con nombre, descripción, múltiples perfiles POS, categorías exactas y etapas ordenadas.
- Etapas reutilizables con color y alerta por minutos. Se requieren al menos tres etapas; las adicionales anteriores a entrega son de preparación.
- Marcado independiente por platillo y por pantalla. Completar todos avanza y reinicia las marcas de la siguiente etapa.
- Última etapa con Restablecer/Listo; retiro automático opcional desde la hora de completado del servidor. Nunca borra pedidos o facturas.
- Identidades estables de filas enviadas; productos adicionales forman lotes nuevos. La reimpresión no reabre ni cambia temporizadores.
- Facturar conserva el progreso de cocina. Dividir y fusionar requieren preparación terminada; traslado sin fusión continúa disponible.
- Solicitudes POST, permisos nativos, bloqueo del pedido y tickets, etapa esperada y control de versiones de configuración.

## Respaldo y datos

**VERIFIED:** respaldo previo `sites/development/private/backups/20261106_111228-development-database.sql.gz`; migración aditiva completada. Configuración inicial idempotente: una pantalla Kitchen Display y tres etapas. No se hizo backfill de pedidos históricos ni se emitieron facturas reales durante estas pruebas.

**VERIFIED:** conteos preservados después de las pruebas: Restaurant Order 5, Sales Invoice 2, GL Entry 8, POS Invoice 0, Payment Entry 0 y Stock Ledger Entry 0. Las pruebas KDS comparan también importes operativos y cuentan documentos nativos; fixtures revertidos por savepoints.

## Pruebas ejecutadas

Desde el Bench del contenedor, con su entorno Python 3.11 activo:

```bash
bench --site development backup
bench --site development migrate
bench --site development execute restaurant.kds_setup.ensure_default_display
bench --site development clear-cache
bench --site development run-tests --app restaurant --module restaurant.tests.test_kds --skip-test-records
bench --site development run-tests --app restaurant --module restaurant.tests.test_pos_startup --skip-test-records
bench --site development run-tests --app restaurant --module restaurant.restaurant.doctype.restaurant_command.test_restaurant_command --skip-test-records
bench --site development run-tests --app restaurant --module restaurant.restaurant.doctype.restaurant_preparation_display.test_restaurant_preparation_display --skip-test-records
bench --site development run-tests --app restaurant --module restaurant.restaurant.doctype.restaurant_preparation_stage.test_restaurant_preparation_stage --skip-test-records
bench --site development run-tests --app restaurant --module restaurant.restaurant.doctype.restaurant_preparation_ticket.test_restaurant_preparation_ticket --skip-test-records
```

**VERIFIED:** 55 pruebas aprobadas: KDS 28, arranque 7, comandas 15, pantalla 3, etapa 1 y ticket 1. Se ejecutaron además `py_compile` con el Python del Bench, `node --check` y `git diff --check`.

| Dimensión | Evidencia |
| --- | --- |
| A — Estándar | VERIFIED: permisos, controladores y carga nativa de páginas. |
| B — LEAF | VERIFIED: configuración, dos rondas, colores/temporizadores, retiro y nuevos lotes. |
| C — Integración | VERIFIED: perfiles/categorías nativos y preservación de estados al invocar la facturación; emisor nativo simulado para no emitir facturas reales. |
| D — Regresión | VERIFIED: comandas, arranque, reimpresión, edición POS y traslados/división. |
| E — Históricos | VERIFIED: lectura sin escrituras, estado legado, orden facturada e invariantes de datos. |
| F — Negativos | VERIFIED: permisos, valores inválidos, solicitudes desactualizadas, identidad manipulada y aislamiento entre pantallas. Las carreras se protegen por bloqueos nativos; no se ejecutó prueba de carga concurrente. |
| G — Flujo | VERIFIED: API transaccional de preparación y navegador con pedidos simulados; no se modificaron pedidos reales desde la UI. |

**VERIFIED — Navegador:** `restaurant/tests/ui/kds.cjs` abrió la página y formularios reales, guardó configuración sin alterar sus valores y verificó persistencia; un fixture de respuesta aislado probó dos rondas por platillo, completado y Listo. Capturas revisadas en escritorio y móvil; se corrigió el recorte móvil y se añadió una aserción de límites de pantalla. Las pruebas requieren credenciales locales explícitas por entorno, Playwright y Chromium ya instalados.

## Perfiles revisores

**ANALYZED:** participaron los 15 perfiles, distribuidos entre el orquestador y agentes por especialidad: orchestrator; functional-analyst-accountant; erpnext-logic-mapper; erpnext-core-behavior-researcher; upgrade-compatibility-reviewer; data-integrity-auditor; migration-patch-specialist; backend-implementer-frappe; frontend-wizard-js; frappe-test-engineer; qa-functional-accounting-auditor; docker-compose-platform-engineer; supply-chain-security-reviewer; ci-release-verification-engineer; repo-structure-git-guardian. No equivalen a 15 procesos simultáneos.

## Observaciones

- El retiro automático es un filtro reversible: desactivarlo o ampliar su plazo puede mostrar otra vez tarjetas completadas. Listo registra un retiro persistente por pantalla.
- No se reordenan etapas con tickets activos; los tickets guardan sus etapas/alertas originales. Los vencidos bajo la política automática anterior no bloquean la configuración.
- Dividir o fusionar cuentas en preparación está bloqueado para conservar trazabilidad. Se permite facturar o trasladar sin fusionar.
- El monitor consulta el historial candidato completo: conviene medir/paginar antes de usar grandes volúmenes. No se ejecutaron pruebas de carga ni una facturación fiscal real.
- Se preservaron cambios locales anteriores, rama y commits; esta tarea no hizo commit ni push.

**DICTAMEN FINAL: APROBADO CON OBSERVACIONES.**

## Archivos creados o modificados en esta tarea

Rutas relativas al repositorio independiente `development/frappe-bench/apps/restaurant/`. Los archivos con cambios previos conservan ese trabajo; esta lista no atribuye cambios ajenos a la tarea.
- `docs/kds-verificacion.md`
- `docs/kitchen-display.md`
- `restaurant/kds_setup.py`
- `restaurant/kds.py`
- `restaurant/pos.py`
- `restaurant/restaurant/doctype/restaurant_preparation_display_stage/__init__.py`
- `restaurant/restaurant/doctype/restaurant_preparation_display_stage/restaurant_preparation_display_stage.json`
- `restaurant/restaurant/doctype/restaurant_preparation_display_stage/restaurant_preparation_display_stage.py`
- `restaurant/restaurant/doctype/restaurant_preparation_display/__init__.py`
- `restaurant/restaurant/doctype/restaurant_preparation_display/restaurant_preparation_display.js`
- `restaurant/restaurant/doctype/restaurant_preparation_display/restaurant_preparation_display.json`
- `restaurant/restaurant/doctype/restaurant_preparation_display/restaurant_preparation_display.py`
- `restaurant/restaurant/doctype/restaurant_preparation_display/test_restaurant_preparation_display.py`
- `restaurant/restaurant/doctype/restaurant_preparation_pos/__init__.py`
- `restaurant/restaurant/doctype/restaurant_preparation_pos/restaurant_preparation_pos.json`
- `restaurant/restaurant/doctype/restaurant_preparation_pos/restaurant_preparation_pos.py`
- `restaurant/restaurant/doctype/restaurant_preparation_stage/__init__.py`
- `restaurant/restaurant/doctype/restaurant_preparation_stage/restaurant_preparation_stage.js`
- `restaurant/restaurant/doctype/restaurant_preparation_stage/restaurant_preparation_stage.json`
- `restaurant/restaurant/doctype/restaurant_preparation_stage/restaurant_preparation_stage.py`
- `restaurant/restaurant/doctype/restaurant_preparation_stage/test_restaurant_preparation_stage.py`
- `restaurant/restaurant/doctype/restaurant_preparation_ticket/__init__.py`
- `restaurant/restaurant/doctype/restaurant_preparation_ticket/restaurant_preparation_ticket.js`
- `restaurant/restaurant/doctype/restaurant_preparation_ticket/restaurant_preparation_ticket.json`
- `restaurant/restaurant/doctype/restaurant_preparation_ticket/restaurant_preparation_ticket.py`
- `restaurant/restaurant/doctype/restaurant_preparation_ticket/test_restaurant_preparation_ticket.py`
- `restaurant/restaurant/page/restaurant_kds/restaurant_kds.css`
- `restaurant/restaurant/page/restaurant_kds/restaurant_kds.js`
- `restaurant/restaurant/page/restaurant_pos/restaurant_pos.js`
- `restaurant/tests/test_kds.py`
- `restaurant/tests/test_pos_startup.py`
- `restaurant/tests/ui/kds.cjs`
