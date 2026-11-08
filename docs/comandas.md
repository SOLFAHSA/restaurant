# Configuración de comandas

Estado: implementación de configuración en Restaurant, nivel arquitectónico 3 / categoría C.

## Uso en Desk

1. Abre http://localhost:8000/app/restaurante y selecciona **Comandas**.
2. Pulsa **Nueva comanda**.
3. Escribe el nombre o descripción y selecciona la sucursal.
4. Marca los grupos nativos disponibles; el buscador filtra la lista sin perder selecciones.
5. Guarda para incorporar el registro a la tabla, o cancela para descartar la edición.

Se pueden registrar distintas comandas en una misma sucursal y asignar el mismo grupo a varias.
Ejemplo: una comanda de Barra y otra de Control pueden compartir Bebidas.
El nombre de cada comanda debe ser distinto dentro de su sucursal.
El estado **Activa** permite conservar una configuración sin utilizarla cuando se conecte el envío.

La asignación es **exacta**, sin herencia automática. Marcar ENTRADAS no marca ALITAS o NACHOS:
selecciona también los subgrupos necesarios. Los grupos corresponden a Item Group,
no a los grupos de opciones de lados o extras del platillo.

## Diseño del formato

Recomendación: diseñar el ticket mediante **Formato de impresión** de Frappe.
El acceso se muestra a quien tenga permiso de lectura de ese catálogo.
Reportes conserva las consultas analíticas de ventas.

No se agregó un diseñador paralelo ni una plantilla ligada al registro de configuración:
Print Format exige un DocType de origen. El documento operativo que llevará los platillos
debe definirse al implementar el envío desde POS, conservando su relación con la venta nativa.

**Límite actual:** guardar esta configuración no envía ni imprime pedidos desde POS Awesome.
Tampoco crea órdenes operativas, facturas, impuestos, pagos ni movimientos de inventario.
La tarjeta Cocina KDS continúa en su estado anterior.

## Arquitectura y fuente de verdad — ANALYZED

Native Path Check:
1. No se encontró configuración equivalente de destinos de cocina en las apps instaladas.
2. Branch e Item Group ya representan sucursales y categorías; se reutilizan.
3. POS Awesome filtra productos por Item Group; su impresión actual utiliza Sales Invoice.
4. La persistencia usa get_doc/save/get_list y permisos nativos.
5. validate aplica reglas también a formularios, API e importaciones.
6. El motor nativo de impresión y PrintFormat permanecen disponibles para el ticket futuro.
7. La relación destino/sucursal/múltiples grupos requiere una entidad de Restaurant.
8. Los enlaces apuntan a los catálogos nativos; una futura orden conservará el origen transaccional.
9. Restaurant coordina destinos; ERPNext conserva el motor financiero.
10. Solo se agregan configuración, tabla hija y página Desk, sin overrides de core.

El DocType principal Restaurant Command no es Custom, pertenece a Restaurant y admite importación.
System Manager tiene Read, Write, Create, Delete, Report, Import y Export.
Restaurant Manager administra configuraciones y dispone de selección de Branch e Item Group,
sin obtener permiso para modificar esos catálogos.

El servidor filtra por permisos de usuario/sucursal, valida los enlaces y evita grupos repetidos
dentro de una comanda. Un bloqueo por Branch serializa la comprobación de nombres duplicados.
La edición exige la marca modified; una sesión desactualizada no puede sobrescribir otra.

Los datos históricos permanecen congelados. No hay recálculo ni parche de datos.
La sincronización de metadatos es aditiva; el respaldo permite recuperación si falla el DDL.
Retirar la navegación o desactivar configuraciones permite dejar de usarlas sin borrar datos.

## Verificación

VERIFIED:
- Python del Bench: 3.11.15; app restaurant instalada en development, rama feature/modulo-restaurante.
- developer_mode = 1 y allow_tests = true; no se imprimieron secretos.
- Respaldo de base previo a sincronizar metadatos.
- Sincronización localizada de los dos DocTypes y de la Page, repetida sin duplicación.
- Huellas SHA-256 de filas nativas idénticas antes/después:
  Branch 4, Item Group 23, Item 40, Sales Invoice 2, POS Invoice 0, GL Entry 8, Stock Ledger Entry 0.
- 15 pruebas backend aprobadas; repetidas con Restaurant Manager como único rol operativo.
- Suite completa de Restaurant: 70 pruebas aprobadas (39.391 s), sin regresiones detectadas.
- Sintaxis JavaScript, compileall Python y git diff --check sin errores.
- Huellas protegidas nuevamente idénticas después de ejecutar las 70 pruebas.
- La revisión independiente comprobó ORM, permisos y ausencia de un motor financiero paralelo.

Comando de pruebas, dentro del DevContainer, desde /workspace/development/frappe-bench:

```bash
bench --site development run-tests --app restaurant \
  --module restaurant.restaurant.doctype.restaurant_command.test_restaurant_command \
  --skip-test-records
```

Las pruebas usan savepoint/rollback y comparan los conteos de documentos financieros e inventario.
Cubren grupos compartidos, selección exacta, apertura sin guardar, creación, edición, datos inválidos,
permisos por sucursal, Guest, campos protegidos, búsqueda, paginación y marcas de tiempo.

Prueba visual reproducible: restaurant/tests/ui/commands.cjs. Requiere una cuenta temporal
expresamente autorizada y las variables LEAF_UI_CREDENTIALS_FILE, LEAF_PLAYWRIGHT_MODULE,
LEAF_UI_BROWSER y LEAF_UI_OUTPUT. No se deben reutilizar sesiones personales.
La creación de una cuenta System Manager fue rechazada por revisión automática; se solicitó
autorización para una cuenta temporal limitada a Restaurant Manager.
La verificación visual autenticada queda pendiente hasta recibir esa autorización.

Matriz de cobertura:
- A / nativo: catálogos y metadatos enlazados; sin cambios de core.
- B / LEAF: las 15 pruebas de configuración.
- C / integración: enlaces y permisos nativos; envío POS pendiente.
- D / regresión: comandos y comprobación de datos existentes.
- E / históricos: huellas conservadas; sin tocar estados enviados/cancelados.
- F / negativos: permisos, datos inválidos, duplicados y edición desactualizada.
- G / completo: prueba UI reproducible preparada; autenticación pendiente de autorización.

## Archivos de esta implementación

Rutas desde development/frappe-bench/apps/restaurant:

- restaurant/commands.py
- restaurant/setup.py
- restaurant/hooks.py
- restaurant/public/js/restaurant_theme.js
- restaurant/translations/es.csv
- restaurant/fixtures/custom_html_block.json
- restaurant/restaurant/workspace/restaurante/restaurante.json
- restaurant/restaurant/doctype/restaurant_command/__init__.py
- restaurant/restaurant/doctype/restaurant_command/restaurant_command.json
- restaurant/restaurant/doctype/restaurant_command/restaurant_command.py
- restaurant/restaurant/doctype/restaurant_command/restaurant_command.js
- restaurant/restaurant/doctype/restaurant_command/test_restaurant_command.py
- restaurant/restaurant/doctype/restaurant_command_group/__init__.py
- restaurant/restaurant/doctype/restaurant_command_group/restaurant_command_group.json
- restaurant/restaurant/doctype/restaurant_command_group/restaurant_command_group.py
- restaurant/restaurant/page/restaurant_commands/__init__.py
- restaurant/restaurant/page/restaurant_commands/restaurant_commands.json
- restaurant/restaurant/page/restaurant_commands/restaurant_commands.js
- restaurant/restaurant/page/restaurant_commands/restaurant_commands.css
- restaurant/tests/ui/commands.cjs
- docs/comandas.md

Se conservaron los cambios locales previos de README.md, docs/modelo-datos.md,
docs/ubicaciones.md, docs/colores-restaurante.md, docs/configuracion-platillos.md y otras pruebas UI.

