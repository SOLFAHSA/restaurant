# Áreas del restaurante

## Decisión de arquitectura

**ANALYZED:** el Native Path Check identificó `Location` como alternativa nativa. El usuario solicitó expresamente un DocType independiente para áreas exclusivas del restaurante. La entidad `Restaurant Area`, módulo `Restaurant`, conserva por separado la configuración operativa solicitada y reutiliza `Branch`, `Employee` y `Network Printer Settings` mediante campos Link. No modifica ni migra los registros de `Location`, ni introduce transacciones contables o de inventario.

## Persistencia y permisos

El esquema se versiona en `restaurant/restaurant/doctype/restaurant_area/restaurant_area.json`. Se instala mediante `bench --site development migrate`; no es un DocType Custom de base de datos. `System Manager` dispone de lectura, escritura, creación, eliminación, reportes, importación y exportación. `Restaurant Manager` dispone de CRUD y reportes; la configuración concede únicamente selección sobre sucursales y empleados, conservando las reglas previas y respetando User Permissions. La regla instalada por esta app no concede lectura ni exportación de Recursos Humanos; no revoca los accesos nativos o asignados mediante otros roles. La lectura de impresoras conserva los permisos nativos existentes.

`restaurant.setup.ensure_restaurant_roles` es idempotente y puede registrarse en `before_migrate` y `after_install`. Solo crea el rol operativo cuando falta; no asigna roles a usuarios ni modifica registros existentes. `restaurant.setup.ensure_link_permissions`, ejecutado después de migrar, instala los permisos mínimos de selección de forma idempotente sin borrar reglas previas.

Las APIs del editor comprueban permisos sobre el documento y sus enlaces. Las actualizaciones exigen la fecha `modified` para utilizar el control nativo de concurrencia. Las validaciones del controller también se aplican al formulario estándar y a la importación. No se aceptan flags de permisos desde el cliente.

## Límites funcionales

La referencia de KDS y la vinculación de mesas permanecen deshabilitadas porque aún no existe una fuente de datos para esos módulos. Los atributos de visibilidad y apertura de cuentas son configuración; el guardado no implica que POS Awesome ya los consuma. Seleccionar una impresora tampoco despacha comandas.

## Verificación

**VERIFIED — 1 de noviembre de 2026:** suite `restaurant.restaurant.doctype.restaurant_area.test_restaurant_area`, ejecutada en el sitio `development` con Python 3.11.15: **10 pruebas, 0 fallos, 0 errores**, duración 5.047 segundos.

Cobertura ejecutada: guardado y reapertura; preservación de Location; rangos, enteros y longitudes; imágenes remotas/inexistentes; acceso denegado a Guest; concurrencia mediante `modified`; rechazo de actualizaciones sin timestamp y de flags de permisos; DocType incorrecto; User Permissions de sucursal; acceso al listado de un usuario de solo lectura. La prueba de selección comprueba la regla específica añadida para Restaurant Manager, sin atribuirle los permisos de otros roles.

| DocType | Antes | Después |
| --- | ---: | ---: |
| User | 2 | 2 |
| Branch | 0 | 0 |
| Restaurant Area | 0 | 0 |
| Location | 0 | 0 |
| Role | 50 | 50 |
| User Permission | 0 | 0 |
| Custom DocPerm | 7 | 7 |

Los registros temporales se revirtieron. El ajuste de los permisos mínimos de selección pertenece a la configuración instalada por la app, no a los datos temporales de las pruebas.

Comando reproducible desde la raíz del Bench, con el esquema previamente migrado y sin una transacción pendiente. Ejecutar únicamente sobre el sitio de desarrollo o de pruebas autorizado; `FrappeTestCase` confirma la transacción inicial antes de empezar y cada caso utiliza un savepoint para sus datos temporales.

```bash
cd sites
../env/bin/python - <<'PY'
import json
import unittest
import frappe

frappe.init(site="development")
frappe.connect()
frappe.set_user("Administrator")
tables = ["User", "Branch", "Restaurant Area", "Location", "Role", "User Permission", "Custom DocPerm"]
before = {dt: frappe.db.count(dt) for dt in tables}
try:
    suite = unittest.defaultTestLoader.loadTestsFromName(
        "restaurant.restaurant.doctype.restaurant_area.test_restaurant_area"
    )
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    frappe.db.rollback()
    after = {dt: frappe.db.count(dt) for dt in tables}
    print("Counts before:", json.dumps(before, sort_keys=True))
    print("Counts after: ", json.dumps(after, sort_keys=True))
    print("Tests run:", result.testsRun, "failures:", len(result.failures), "errors:", len(result.errors))
    if before != after:
        raise SystemExit("Data counts changed unexpectedly")
    if not result.wasSuccessful():
        raise SystemExit(1)
finally:
    frappe.db.rollback()
    frappe.destroy()
PY
```

Estas pruebas no certifican integraciones KDS, mesas, POS, contabilidad ni inventario. La verificación visual y funcional del editor se registra por separado.

## Editor y verificación visual

**VERIFIED — 1 de noviembre de 2026:** Page `/app/restaurant-location` instalada en
`development` mediante la migración nativa. El acceso Ubicaciones del Workspace
abre el listado; `/app/restaurant-location/new` abre una ubicación nueva.

Chromium probó el guardado mediante controles reales, el enlace nativo de sucursal,
la selección de icono, el interruptor de visibilidad, el guardado de descripción y
observaciones, la recarga desde servidor y la presencia en el listado. El formulario
nativo de `Restaurant Area` abre el mismo registro mediante su botón de diseño.
Se verificó la vista a 1365 px y 390 px, sin desbordamiento horizontal. La pasada
final de estos flujos no produjo excepciones JavaScript. Los registros temporales
se eliminaron y la sesión temporal de prueba se revocó.

Los controles de orden y capacidad del editor utilizan entrada con teclado numérico
y validación de enteros; el esquema persiste campos `Int`. Esto evita el temporizador
de foco del control numérico de esta versión de Frappe, que podía alterar el campo
activo al cambiar rápidamente de foco. No se modifica el código del framework.

La vista previa es una ilustración SVG de referencia. No representa registros reales
de mesas ni acredita una integración con POS/KDS. El cambio queda instalado en el
sitio de desarrollo; no publica ni modifica la demostración ni el release semana-1.

## Archivos de esta implementación

Rutas relativas a la raíz de la app `restaurant`:

- `README.md`
- `docs/ubicaciones.md`
- `restaurant/hooks.py`
- `restaurant/location.py`
- `restaurant/setup.py`
- `restaurant/translations/es.csv`
- `restaurant/fixtures/custom_html_block.json`
- `restaurant/restaurant/workspace/restaurante/restaurante.json`
- `restaurant/restaurant/doctype/__init__.py`
- `restaurant/restaurant/doctype/restaurant_area/__init__.py`
- `restaurant/restaurant/doctype/restaurant_area/restaurant_area.json`
- `restaurant/restaurant/doctype/restaurant_area/restaurant_area.py`
- `restaurant/restaurant/doctype/restaurant_area/restaurant_area.js`
- `restaurant/restaurant/doctype/restaurant_area/test_restaurant_area.py`
- `restaurant/restaurant/page/restaurant_location/__init__.py`
- `restaurant/restaurant/page/restaurant_location/restaurant_location.json`
- `restaurant/restaurant/page/restaurant_location/restaurant_location.html`
- `restaurant/restaurant/page/restaurant_location/restaurant_location.css`
- `restaurant/restaurant/page/restaurant_location/restaurant_location.js`

## Simplificación del formulario de áreas

**ANALYZED — 4 de noviembre de 2026:** la interfaz utiliza Áreas, Nueva área y
Nombre del área. Se retira Tipo de área del esquema activo, del editor y de las
validaciones. Cada restaurante define sus espacios mediante un nombre libre.
Se conservan Restaurant Area, area_name y la ruta /app/restaurant-location para
mantener los registros y enlaces existentes.

La sincronización nativa de Frappe conserva la columna histórica area_type;
no se ejecuta un borrado de columnas ni una actualización de las áreas existentes.
No se necesita un parche de datos. El orden de visualización se conserva:
los números menores aparecen primero en el listado; no identifica mesas.
Las demás opciones conservan su alcance actual.

### Verificación de la simplificación

**VERIFIED — 4 de noviembre de 2026:** sincronización nativa del DocType y de la
Page en development con Python 3.11.15. Las 24 áreas existentes conservaron
exactamente todos sus valores e identificadores, incluida la columna histórica
area_type. La interfaz y los accesos usan Áreas y Nombre del área.

Se ejecutaron 23 pruebas de las suites test_restaurant_area,
test_restaurant_area_list y restaurant.tests.test_demo_data: 0 fallos y 0 errores.
Incluyen crear y editar sin tipo de área, clientes antiguos, permisos, concurrencia,
paginación y repetición segura de datos semilla. Se revirtieron los registros
temporales y se comprobaron los conteos de 13 tablas antes y después.

Archivos modificados en esta simplificación, desde la raíz de la app:

- README.md
- docs/modelo-datos.md
- docs/ubicaciones.md
- restaurant/demo_data.py
- restaurant/fixtures/custom_html_block.json
- restaurant/location.py
- restaurant/restaurant/doctype/restaurant_area/restaurant_area.js
- restaurant/restaurant/doctype/restaurant_area/restaurant_area.json
- restaurant/restaurant/doctype/restaurant_area/test_restaurant_area.py
- restaurant/restaurant/page/restaurant_location/restaurant_location.html
- restaurant/restaurant/page/restaurant_location/restaurant_location.js
- restaurant/restaurant/page/restaurant_location/restaurant_location.json
- restaurant/restaurant/workspace/restaurante/restaurante.json
