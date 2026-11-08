# Configuración de platillos en Producto

## Alcance

La pestaña Restaurante amplía el formulario nativo Item. Esta entrega configura
recetas y selecciones del cliente; la interfaz de ventas y el consumo de inventario
se implementarán por separado. No depende de POS Awesome.

Native Path Check: Item identifica el producto, Product Bundle conserva los
componentes y las unidades pertenecen a UOM. Los grupos de opciones son entidades
especializadas de restaurant porque incluyen selección mínima/máxima, sustitución,
extras y adicionales por platillo. No se crea un motor de inventario ni se registran
facturas, pagos, GL Entry o Stock Ledger Entry desde esta configuración.

## Crear un producto y abrir su configuración

1. Abre Restaurante y selecciona Productos y platillos.
2. Pulsa Agregar producto. Este acceso abre el formulario completo de Item.
3. Completa los campos nativos obligatorios, como código, nombre, grupo y unidad.
4. Si el platillo se compone de ingredientes y no mantiene existencia propia,
   desmarca Mantener Stock antes de activar su receta. Los ingredientes deben
   existir como Item activos con control de inventario.
5. En Restaurante activa Activar receta y/o Activar opciones del platillo.
6. Guarda el producto. Después utiliza los botones de esta pestaña para guardar
   la composición o cada grupo de opciones.

Las dos casillas están desactivadas por defecto. No se convierten automáticamente
artículos existentes a no inventariables ni se crean recetas para todo el catálogo.

## Componentes de la receta

Agregar componentes o Editar componentes abre una tabla con búsqueda de Item,
cantidad y unidad. La cantidad corresponde a una unidad del platillo. Incluye
los ingredientes y empaques que quieras controlar.

La unidad puede quedar vacía para utilizar la unidad de inventario del ingrediente.
Si se elige otra unidad, debe existir una conversión válida. El servidor convierte
la cantidad a la unidad de inventario y guarda el origen de la captura. No acepta
conversiones proporcionadas por el navegador ni asume factor uno para unidades
distintas sin equivalencia. Tampoco permite ingredientes repetidos o el propio
platillo como componente.

La fuente de verdad de los componentes es Product Bundle. Los paquetes creados
por este editor se guardan deshabilitados y marcados como configuración de
Restaurante. No se activan para ventas ni consumen stock en esta entrega.
Los paquetes activos, ajenos o ya utilizados no se sobrescriben desde este editor.
Apagar Activar receta conserva la composición y no cambia el estado del paquete.
Un paquete existente conserva las protecciones nativas sobre cambios de stock
que ERPNext aplica al Item relacionado.

## Grupos de opciones

Agregar grupo de opciones permite definir nombre, mínimo/máximo de selecciones,
moneda y las alternativas. Un grupo puede quedar inactivo conservando sus datos.
La moneda del adicional se establece explícitamente si el sitio no tiene una
moneda predeterminada.

Cada alternativa incluye:

- Opción: nombre que verá el usuario, como Papas clásicas.
- Efecto: Solo indicación, Sustituir componente, Agregar componente o Incluir en combo.
- Adicional: cero si conserva el precio; un importe positivo si tiene suplemento.
- Ingrediente, extra o platillo, cantidad y unidad: para sustituciones, adiciones o secciones de un menú combinado.
- Componente que sustituye: debe pertenecer a la receta del mismo platillo.
- Seleccionada por defecto: sin exceder el máximo permitido del grupo.

En la tabla del diálogo se muestran nombre, efecto y adicional. Abre el detalle
de la fila para completar ingrediente o platillo, sustitución, cantidad, unidad y selección
predeterminada. Sin receta se permiten opciones de Solo indicación e Incluir en combo.
En la pestaña Restaurante cada grupo muestra sus opciones como tarjetas con su
etiqueta de selección (como `1 Incluido` u `Opcional`) y sus insignias de suplemento
(`+ L 3.00`), además del botón **Vista previa del modal** para simular la selección
interactiva y el cálculo del total antes de integrarlo al POS.

Los efectos y adicionales se guardan como configuración. Todavía no se eligen en
una venta ni alteran precios de facturas o inventario. La futura interfaz deberá
validar selecciones por línea y utilizar los motores nativos de precios e inventario.

## Seguridad y conservación

Los guardados comprueban permisos nativos sobre Item y sobre su configuración.
La receta también exige permisos sobre Product Bundle. La API verifica timestamps
para evitar sobrescribir cambios concurrentes y mantiene las operaciones atómicas.
No se exportan productos, recetas ni grupos de cada restaurante como fixtures.
Solo se versionan el esquema y los campos de la funcionalidad.

La instalación sincroniza los DocTypes de restaurant y los Custom Fields
versionados con bench --site development migrate. Después limpia caché y reinicia
la depuración si usa --noreload. La instalación no carga productos de demostración.

## Permisos de mantenimiento

Item Manager permite mantener el catálogo y los grupos de opciones. También se
requiere acceso nativo a Currency para seleccionar la moneda; por ejemplo Sales
User, Accounts User o Purchase User. Para recetas,
se necesitan además los permisos nativos sobre Product Bundle, por ejemplo el rol
Stock Manager o Sales User. No se amplían indiscriminadamente esos permisos.
System Manager y Administrator conservan sus facultades administrativas.

Un paquete gestionado por este editor no se puede activar desde su formulario
nativo durante esta entrega de configuración. Si el producto ya participa en
cualquier documento comercial histórico, la creación o edición de su receta se
rechaza antes de guardar. Esto preserva la configuración de artículos ya usados.

Los paquetes gestionados se conservan al apagar la casilla y no se eliminan desde
el formulario nativo, para evitar referencias de sustitución huérfanas. La
configuración de artículos genéricos sin receta no recibe estas restricciones.

## Verificación ejecutada

VERIFIED — 4 de noviembre de 2026, development, Python 3.11.15:

- 49 casos distintos comprobados mediante unittest: 26 de configuración de
  platillos y 23 de regresión de áreas, listado y datos semilla. Las ejecuciones
  finales no tuvieron fallos ni errores. Los datos temporales se revirtieron.
- Se conservaron los 16 Item originales y todos los campos originales de las dos
  Sales Invoice, cuatro Sales Invoice Item y ocho GL Entry existentes.
- Después de las pruebas: 0 Product Bundle, 0 Restaurant Option Group,
  0 Stock Ledger Entry, 0 Stock Entry y 0 POS Invoice. No se dejó carga de ejemplo.
- Frappe FormMeta entrega los scripts del editor y del acceso al formulario
  completo; Item.quick_entry continúa en 1 para los demás accesos.
- Sintaxis Python 3.11 y JavaScript verificada, incluidos los assets de Item
  concatenados por Frappe. La revisión visual en la sesión del usuario requiere
  recargar el navegador después de reiniciar la depuración sin recarga automática.

Las pruebas de configuración cubren unidades válidas y desconocidas, componentes
inválidos, guardados concurrentes, paquetes ajenos o activos, permisos, precios
cero/positivos, límites de selección, referencias de sustitución y conservación
al desactivar las casillas. También verifican validaciones desde el formulario
nativo y que no se pueda activar ni eliminar una receta gestionada en esta etapa.

## Archivos de esta entrega

Rutas desde la raíz de la app restaurant:

- README.md
- docs/configuracion-platillos.md
- restaurant/fixtures/custom_field.json
- restaurant/fixtures/custom_html_block.json
- restaurant/hooks.py
- restaurant/item_configuration.py
- restaurant/public/js/item_restaurant.js
- restaurant/public/js/item_restaurant_list.js
- restaurant/translations/es.csv
- restaurant/tests/test_item_configuration.py
- restaurant/restaurant/doctype/restaurant_option_group/__init__.py
- restaurant/restaurant/doctype/restaurant_option_group/restaurant_option_group.json
- restaurant/restaurant/doctype/restaurant_option_group/restaurant_option_group.py
- restaurant/restaurant/doctype/restaurant_option_group/restaurant_option_group.js
- restaurant/restaurant/doctype/restaurant_option_group/test_restaurant_option_group.py
- restaurant/restaurant/doctype/restaurant_dish_option/__init__.py
- restaurant/restaurant/doctype/restaurant_dish_option/restaurant_dish_option.json
- restaurant/restaurant/doctype/restaurant_dish_option/restaurant_dish_option.py
- restaurant/restaurant/doctype/restaurant_dish_option/restaurant_dish_option.js

## Corrección de carga y edición del formulario

VERIFIED — 4 de noviembre de 2026: se reprodujo en un navegador aislado que el
proceso web activo entregaba las casillas pero no el hook JavaScript del editor.
Un proceso Python nuevo sí encontraba el código, por lo que esa comprobación por
sí sola no validaba la sesión web. Detener e iniciar efectivamente Frappe renovó
los hooks servidos; limpiar caché sin renovar el proceso no era suficiente.

Se corrigió también el ancho de las columnas de los diálogos: el límite nativo
de la tabla ocultaba Unidad y Adicional. Cada tabla utiliza ahora diez unidades
de ancho para sus tres columnas. Las opciones permiten abrir el detalle con el
lápiz de la fila para configurar ingrediente, sustitución, cantidad y unidad.
El refresco del formulario espera la carga del editor antes de continuar.

La prueba real de navegador restaurant/tests/ui/item_configuration.cjs verificó:

- Panel y botones de componentes y grupos visibles y habilitados.
- Añadir fila, búsqueda nativa de ingredientes con respuesta HTTP 200, cantidad
  y unidad accesibles.
- Grupo con selección de efecto, adicional y detalle de ingrediente/sustitución.
- Ningún error JavaScript y ningún cambio guardado en el producto del usuario.

Se utilizó una cuenta temporal nueva de pruebas, sin leer credenciales o sesiones
existentes. Al finalizar se eliminó esa cuenta y sus archivos de credenciales.
No se crearon recetas ni grupos. ARTICULO PRUEBA conservó su fecha de modificación.

El test de navegador requiere Playwright y un navegador de pruebas. Recibe
LEAF_UI_BASE_URL, LEAF_UI_ITEM, LEAF_UI_CREDENTIALS_FILE y, si el entorno lo necesita,
LEAF_PLAYWRIGHT_MODULE, LEAF_UI_BROWSER y LEAF_UI_OUTPUT. El archivo de credenciales
pertenece a una cuenta dedicada de desarrollo y nunca debe versionarse.

Archivos de esta corrección:

- restaurant/public/js/item_restaurant.js
- restaurant/tests/ui/item_configuration.cjs
- docs/configuracion-platillos.md
