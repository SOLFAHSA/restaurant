# Paginación y búsqueda de ubicaciones

## Decisión técnica

**ANALYZED:** se reutiliza `frappe.get_list` para conservar los permisos de rol y las restricciones por sucursal. La mejora no modifica el esquema ni los registros de `Restaurant Area`. La aplicación agrega una API acotada y controles de navegación en su página Desk; no modifica el framework ni ERPNext.

## API

`restaurant.location.get_locations(search="", start=0, page_length=12)` devuelve `items`, `has_next`, `start` y `page_length`. Consulta como máximo una fila adicional para determinar si hay otra página, sin calcular un total separado ni consultar registros ignorando permisos.

- `start`: entero igual o mayor que cero.
- `page_length`: entero entre 1 y 50.
- `search`: texto de hasta 140 caracteres; busca por nombre de área o sucursal.
- Se conserva la semántica nativa `LIKE` de Frappe: `%` representa cualquier secuencia y `_` un carácter. El framework escapa los valores, incluidas las comillas; no se construyen consultas SQL manuales. Los comodines no omiten los permisos.
- Orden estable: `display_order`, `area_name` y `name`, todos ascendentes.
- No admite campos, filtros u órdenes arbitrarios desde el cliente.

## Interfaz

El listado muestra 12 registros por defecto, con opciones de 24 y 48. Los controles **Anterior** y **Siguiente** navegan entre páginas; el rango indica lo que se está mostrando, sin afirmar un total global.

La búsqueda se ejecuta en el servidor después de 300 ms sin escribir o al pulsar Enter. Un cambio de búsqueda o tamaño vuelve a la primera página. Los identificadores de solicitud impiden que una respuesta anterior reemplace resultados de una búsqueda más reciente o modifique otra pantalla. El campo de búsqueda conserva el foco. Mientras carga se inhabilita la navegación; si falla la consulta se muestran un error y la acción **Reintentar**, sin conservar resultados anteriores como si correspondieran a la búsqueda actual.

El orden usa desplazamiento (`start`), por lo que una alta o eliminación concurrente puede cambiar la composición de páginas entre consultas. No se promete una instantánea transaccional del listado.

## Pruebas

**VERIFIED — 1 de noviembre de 2026:** suite `restaurant.restaurant.doctype.restaurant_area.test_restaurant_area_list`, ejecutada en `development` con el Python 3.11 del Bench: **7 pruebas, 0 fallos y 0 errores**, duración 3.786 segundos. Comprueba páginas consecutivas, orden y ausencia de duplicados, límites, búsquedas por nombre/sucursal, comodines nativos y comillas sin inyección SQL, página vacía, permisos de lectura y restricciones por sucursal. Crea datos temporales y los revierte por savepoint. La suite base de validaciones del DocType se conserva.

No se requiere `bench migrate` ni compilación de assets para esta mejora. Al actualizar el código, limpiar caché y reiniciar el servidor si utiliza `--noreload`.

Los conteos antes y después de la suite fueron iguales: Branch 0, Restaurant Area 0, User 2, Role 50, User Permission 0 y Custom DocPerm 7. La ejecución fue mediante `unittest.TextTestRunner` sobre una conexión Frappe al sitio, con rollback por caso y al cerrar. La prueba de comodines incluye una consulta `%` con User Permissions para demostrar que no amplía el acceso a sucursales restringidas.

Para repetir la suite en un sitio de pruebas autorizado, desde la raíz del Bench:

```bash
cd sites
../env/bin/python - <<'PY'
import unittest
import frappe

frappe.init(site="development")
frappe.connect()
frappe.set_user("Administrator")
try:
    suite = unittest.defaultTestLoader.loadTestsFromName(
        "restaurant.restaurant.doctype.restaurant_area.test_restaurant_area_list"
    )
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise SystemExit(1)
finally:
    frappe.db.rollback()
    frappe.destroy()
PY
```

`FrappeTestCase` confirma la transacción inicial al comenzar la clase: no debe ejecutarse con cambios de datos pendientes ni sobre producción. Los casos utilizan savepoints para revertir sus propios datos.

**VERIFIED:** `node --check` del archivo JavaScript de la página y análisis AST de los archivos Python modificados. La revisión visual y las interacciones reales de navegación se registran por separado cuando se ejecuten.

## Verificación del navegador

**VERIFIED — 1 de noviembre de 2026:** con las 24 áreas de demostración se
comprobaron páginas de 12 y 24, Anterior/Siguiente, última página sin siguiente,
orden y ausencia de solapamientos. La búsqueda por Terraza devolvió cuatro áreas
y la búsqueda por sucursal Norte devolvió seis. Se retrasó una respuesta anterior
para comprobar que no reemplazara la búsqueda reciente y se verificó la
conservación del foco, resultado vacío, apertura del editor y retorno al listado.

Chromium verificó 1365 px y 390 px sin desbordamiento horizontal ni excepciones
JavaScript. La suite combinada ejecutó 22 pruebas con 0 fallos y 0 errores sobre
el conjunto demo persistido, conservando los conteos antes y después.
