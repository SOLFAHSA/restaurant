# Colores exclusivos de Restaurante

Fecha: 5 de noviembre de 2026. Cambio visual en la Custom App `restaurant`.

## Decisión y camino nativo

ANALYZED — Frappe ya proporciona Workspace, listas, formularios, diálogos y eventos del router. Se reutilizan esos componentes y el catálogo nativo `Item`; la app añade CSS y contexto de navegación. No se modifican Frappe, ERPNext, POS Awesome ni sus DocTypes.

La estructura, dimensiones, textos, rutas y comportamiento transaccional existentes se conservan. El único cambio de navegación es registrar el origen para elegir la paleta visual.

## Paleta

| Uso | Color |
| --- | --- |
| Botones principales y enlaces | `#2f8500` |
| Botón al pasar el cursor | `#246700` |
| Íconos del menú | `#369900` |
| Fondos verdes claros | `#effbe9` |
| Bordes de acento | `#a4ce87` |
| Restaurante seleccionado y Create Workspace | `#002456` |

## Alcance

El Workspace Restaurante y las pantallas propias de áreas y mesas activan el contexto. Los catálogos compartidos lo reciben al abrirse desde las tarjetas del menú de Restaurante. La navegación entre lista y formulario conserva el contexto; una recarga de esa misma URL también lo conserva en la pestaña actual.

Al abrir otro Workspace, una transacción ajena o seleccionar un resultado de la búsqueda general, se retira la paleta. Abrir Productos directamente desde Almacén mantiene su aspecto nativo. No se aplica una paleta global a Desk.

Los estilos del dashboard se mantienen dentro de su Shadow DOM. Los demás requieren `body.restaurant-theme-context`; el azul del Workspace requiere además `body.restaurant-theme-workspace`. Los diálogos se identifican por el origen de la interacción, incluidas las tarjetas dentro del Shadow DOM.

El estado Habilitado se colorea mediante el atributo nativo `disabled,=,0`, exclusivamente en la lista de Item del contexto. Otros estados azules, estados de alerta y acciones de borrado conservan su significado.

## Archivos de este cambio

- `restaurant/public/css/restaurant_theme.css`: reglas acotadas y paleta.
- `restaurant/public/js/restaurant_theme.js`: activación, limpieza y persistencia del contexto visual.
- `restaurant/hooks.py`: registro directo y versionado del CSS y JavaScript del tema, independiente del sprite de íconos.
- `restaurant/public/js/restaurant_icons.js`: queda dedicado al sprite; se retira su carga indirecta del tema.
- `restaurant/fixtures/custom_html_block.json`: colores locales del dashboard y registro del origen al abrir una tarjeta.
- `restaurant/tests/ui/restaurant_theme.cjs`: prueba de navegador con cuenta dedicada y cobertura de catálogos, configuración y reportes.
- `restaurant/tests/ui/restaurant_theme_cached_session.cjs`: regresión de sesión con Desk anterior y carga lenta de assets.
- `docs/colores-restaurante.md`: esta documentación.

## Aplicación y verificación

En `development` se respalda el bloque Custom HTML Block `Restaurant Dashboard` y se actualizan únicamente sus campos `style` y `script` mediante el documento nativo. No se cambia su HTML. La fixture conserva el cambio para otras instalaciones. No requiere migración de esquema. Al introducir el registro directo en hooks.py, reiniciar el servidor si utiliza --noreload. El Workspace también carga los dos assets mediante etiquetas nativas versionadas y espera su finalización antes de navegar, para recuperar sesiones con un sprite anterior en caché. No se utiliza frappe.require con querystrings porque ese formato no está soportado por su cargador en esta versión. En el navegador, usar **Ctrl+F5** para obtener el bloque actualizado.

VERIFIED — Prueba Playwright en Chrome con sesión aislada y una cuenta temporal propia. Comprueba colores del Workspace, tarjetas, botón Agregar Producto, filtro, enlaces, estado Habilitado, recarga, formulario nuevo, áreas y mapa; compara los colores originales de Item antes y después de visitar Restaurante. También verifica salida mediante Almacén, búsqueda general y Sales Invoice, origen de diálogos, dimensiones del botón y preservación de indicadores rojos. No guarda productos ni transacciones.

La prueba exige `LEAF_UI_CREDENTIALS_FILE` con credenciales de una cuenta dedicada y permisos de lectura apropiados. No se deben reutilizar sesiones personales ni versionar ese archivo. Requiere un sitio de desarrollo con al menos un Item habilitado y funciones de Desk activadas para la cuenta de prueba. Variables opcionales: `LEAF_PLAYWRIGHT_MODULE`, `LEAF_UI_BROWSER`, `LEAF_UI_BASE_URL`, `LEAF_UI_OUTPUT`.

```bash
node restaurant/tests/ui/restaurant_theme.cjs
```

En Windows, ejecutar una copia temporal del script desde una carpeta local si Node no resuelve paquetes desde una ruta UNC de WSL. La prueba genera capturas y `restaurant-theme-result.json` en el directorio de salida.

Riesgo de mantenimiento: comprobar selectores y eventos al actualizar Frappe. La integración no reemplaza controladores ni reglas de inventario, contabilidad o impuestos.

## Corrección de carga en sesiones existentes

VERIFIED — Se reprodujo el defecto informado: tarjetas verdes y selección/botones nativos, con el objeto del tema ausente. La prueba mantuvo el mismo contexto del navegador, aplicó el script actualizado del bloque y recargó sin vaciar la caché. Se verificaron los colores de selección, Create Workspace, Editar y Productos con el sprite anterior, incluso al hacer clic antes de finalizar la carga del JavaScript. La prueba anterior con una sesión nueva no cubría esta condición.

La paleta se registra ahora directamente en los hooks nativos de Desk con URL versionada. El sprite queda dedicado a los íconos. El bloque tiene una recuperación independiente que espera CSS y JavaScript, comparte una sola promesa y puede reintentar si falla la carga. Se preservan el HTML y el CSS del dashboard.

```bash
node restaurant/tests/ui/restaurant_theme_cached_session.cjs
```

VERIFIED — Después del reinicio confirmado se verificó que el HTML de Desk entrega ambos hooks versionados. Pasaron la prueba general ampliada y la regresión de assets inicialmente ausentes con carga demorada y clic inmediato: cero errores JavaScript. La cuenta de prueba utilizó roles nativos de catálogo y reportes; no se alteraron los permisos de usuarios existentes. El Workspace reutiliza una sola hoja de estilos, tanto si su URL original es absoluta como relativa.
VERIFIED — La regresión final también aborta la descarga CSS: el catálogo continúa abriendo con su interfaz nativa; al restablecer la descarga, el siguiente intento recupera el verde y conserva una sola hoja de estilos. La revisión de fuente cerró esa observación. La cuenta temporal y sus sesiones se eliminaron al finalizar.
