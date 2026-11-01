# Datos semilla del restaurante

El módulo `restaurant.demo_data` prepara datos ficticios coherentes para probar
la configuración del restaurante. Solo permite el sitio `development` con
`developer_mode = 1` y usuario Administrator o System Manager, con los permisos
nativos de lectura y creación de los DocTypes utilizados. No es una API web,
no se ejecuta mediante hooks y no se instala automáticamente al migrar.

## Camino nativo e integridad

Reutiliza las APIs `frappe.get_doc(...).insert()` de los DocTypes UOM, Item Group,
Price List, Branch, Item e Item Price, junto con Restaurant Area. No crea tablas,
campos ni documentos fiscales, contables o de inventario. Los artículos tienen
`is_stock_item = 0`, `standard_rate = 0` y `opening_stock = 0`; sus precios están
separados en una lista de demostración HNL. Los precios son ilustrativos y no
constituyen configuración fiscal ni un catálogo comercial real.

Todos los registros creados utilizan el prefijo **DEMO-REST** en su nombre o
referencias. No se modifican registros ya existentes. Si un registro del conjunto
ya existe con valores diferentes, el proceso informa el conflicto y revierte las
inserciones de esa ejecución. La inserción del grupo utiliza el mantenimiento
nativo del árbol de Item Group, incluidos sus índices jerárquicos derivados.

## Contenido reproducible

| DocType | Registros |
| --- | ---: |
| UOM | 1 |
| Item Group | 1 |
| Price List | 1 |
| Branch | 4 |
| Restaurant Area | 24 |
| Item | 12 |
| Item Price | 12 |
| Total | 55 |

Las sucursales ficticias Centro, Norte, Sur y Mirador contienen seis áreas cada
una: salón principal, terraza, barra, salón privado, jardín y salón familiar.
El catálogo incluye platos y bebidas con precios de ejemplo en HNL. Cada precio
se relaciona con un artículo, la unidad propia y la lista de precios del conjunto.
Su fecha inicial de vigencia es fija: 2026-01-01. No se crean empleados ni usuarios.

## Ejecución en desarrollo

Desde la terminal del DevContainer, en la raíz del Bench con Python 3.11.x:

```bash
bench --site development execute restaurant.demo_data.seed
```

La función devuelve un resumen de registros creados y existentes por DocType.
El comando nativo `bench execute` confirma la transacción cuando termina bien;
la función no ejecuta commits internos. Ante un error se revierte al savepoint
propio y se propaga la excepción. No lo ejecutes con transacciones previas sin
confirmar en una consola compartida.

Una segunda ejecución con los mismos datos debe indicar `total_created = 0` y
`total_existing = 55`. No repara ni sobrescribe modificaciones manuales del conjunto.
Si existe un conflicto, revisa el registro antes de decidir qué conservar.

## Recuperación y límites

Este script no elimina datos. Para volver al estado anterior se puede restaurar
una copia del sitio de desarrollo tomada antes de la carga o eliminar mediante
Frappe únicamente los registros de demostración, en orden inverso de dependencia,
si no han sido utilizados por otros documentos. No se deben borrar registros de
producción ni aplicar eliminaciones masivas por parecido de nombre.

Las ubicaciones y el catálogo no implementan pedidos, cobros, reservas o KDS.
Los datos semilla permiten pruebas realistas de navegación, búsqueda y relaciones;
no sustituyen la verificación del flujo central ni el despliegue HTTPS.

## Verificación

**VERIFIED — 1 de noviembre de 2026:** cinco pruebas aprobadas, cero fallos y
cero errores, ejecutadas con Python 3.11.15 en `development` (1.750 segundos).
Cubren doble ejecución, enlaces nativos, conservación exacta de los artículos y
precios preexistentes, rechazo de modificaciones ajenas, rollback ante fallo
inyectado, bloqueo de otros sitios, modo desarrollador desactivado y usuario Guest.

Cada caso utiliza un prefijo único y rollback a un savepoint. La suite también
puede ejecutarse cuando el conjunto de demostración ya está cargado. La ejecución
verificada conservó estos conteos antes y después: UOM 239, Item Group 6,
Price List 2, Branch 0, Restaurant Area 0, Item 3 e Item Price 2.

Comando reproducible desde la raíz del Bench, únicamente en desarrollo autorizado
y sin una transacción previa pendiente. `FrappeTestCase` confirma la transacción
inicial antes de comenzar; cada prueba revierte sus propias inserciones.

```bash
cd sites
../env/bin/python - <<'PY'
import unittest
import frappe

frappe.init(site="development")
frappe.connect()
frappe.set_user("Administrator")
try:
    suite = unittest.defaultTestLoader.loadTestsFromName("restaurant.tests.test_demo_data")
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise SystemExit(1)
finally:
    frappe.db.rollback()
    frappe.destroy()
PY
```

## Carga verificada en development

**VERIFIED — 1 de noviembre de 2026:** se cargaron los 55 registros del conjunto.
La primera ejecución creó 55 y la segunda creó 0, reconociendo los 55 existentes.
Se compararon los campos de negocio de los registros previos y permanecieron
sin cambios. Los conteos de documentos contables y movimientos de inventario
se conservaron. El árbol de Item Group conserva su mantenimiento nativo.

La regresión combinada de semilla, controlador de áreas y listado ejecutó
22 pruebas sobre el sitio ya poblado: 0 fallos y 0 errores. Los datos temporales
se revirtieron y el conjunto de demostración permaneció disponible.
