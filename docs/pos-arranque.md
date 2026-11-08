# Reparación de acceso y arranque del POS de Restaurante

DICTAMEN: APROBADO para acceso y arranque. La facturación, el cobro y el cumplimiento SAR no forman parte de este dictamen.

## Acceso

Desde Desk: Restaurante → Punto de venta.
Ruta directa: http://localhost:8000/app/restaurant-pos.
Roles permitidos: System Manager y Restaurant Manager.
Si el navegador conserva una página anterior, recarga con Ctrl+Shift+R.

## Diagnóstico y evidencia

VERIFIED:
- La tarjeta apuntaba a /app/posapp (POS Awesome), aunque ya existía restaurant-pos.
- Durante el diagnóstico, tanto POST /api/method/login como HEAD /login agotaron su tiempo de espera.
- El puerto aceptaba conexiones TCP; el mismo fallo HTTP ocurrió dentro del contenedor.
- El servidor volvió a responder sin intervención antes de la reparación. No hay evidencia suficiente para atribuir el bloqueo al depurador.
- En un proceso independiente, el bootstrap y el cargador nativo de Page funcionaban correctamente.
- Chrome confirmó posteriormente el arranque real con 23 productos y las tres pestañas, sin errores JavaScript.

ANALYZED:
- El constructor dejaba un panel fijo y oscuro vacío.
- onShow esperaba la carga sin mostrar progreso ni capturar fallos.
- El endpoint solo rechazaba Guest, mientras Page ya exigía un rol operativo.
- Frappe v14 no transmite una opción timeout de frappe.call hacia AJAX; se implementó un límite local con Promise.race y cancelación opcional.

## Cambios

- La tarjeta, su texto de ayuda y su ruta identifican el nuevo POS.
- Se conserva el diseño existente y se registra la ruta en el contexto visual de Restaurant.
- El arranque muestra progreso, verifica la respuesta y presenta Reintentar / Volver si falla.
- Una espera de más de 20 segundos produce un estado recuperable.
- Se preservan las opciones de navegación durante un reintento; se evita duplicar cargas simultáneas.
- Una respuesta tardía no reemplaza el estado tras agotar el tiempo.
- La autorización de los endpoints coincide con los roles de la página.
- Se agregó __init__.py por estructura del paquete; su ausencia no era la causa de la carga fallida.
- Se reinició únicamente el servidor web development para cargar Python, manteniendo un solo listener en 8000.

## Camino nativo y arquitectura

Nivel 3 / categoría C. Todo permanece dentro de Restaurant; no se editaron Frappe, ERPNext ni POS Awesome.

1. La página Desk ya existía: se reutiliza.
2. Los campos y catálogos nativos no cambian.
3. El arranque usa el bootstrap existente.
4. Se mantienen frappe.call y el cargador desk_page/Page.load_assets.
5. No se modifican eventos de documentos transaccionales.
6. Se reutilizan controles de acceso y rutas de Frappe.
7. La navegación se resuelve en la configuración del dashboard.
8. Las relaciones de órdenes y documentos ERPNext permanecen intactas.
9. Restaurant continúa como capa de interfaz/orquestación.
10. No se crearon nuevos DocTypes, campos ni motores.

La fuente de verdad de los productos sigue siendo Item; los perfiles y turnos mantienen sus documentos nativos.
No hay parche de datos, migración de esquema ni recálculo. Solo se actualizaron html/script del bloque de navegación correspondiente.

## Verificación ejecutada

VERIFIED:
- 75 pruebas backend aprobadas en 40.257 s.
- Cinco pruebas específicas: assets de Page, bootstrap real/serialización, rechazo de Guest,
  rechazo de un usuario sin rol operativo y aceptación de roles permitidos.
- Chrome real: tarjeta del Workspace → restaurant-pos, catálogo de 23 productos,
  pestañas Mesas / Caja / Órdenes y contexto visual.
- Fallo de conexión simulado → error visible → Reintentar → catálogo.
- Respuesta incompleta simulada → error visible → recuperación.
- Petición retenida solo en el navegador → límite de 20 segundos → recuperación.
- Ausencia de turno simulada únicamente en la respuesta → diálogo → Salir →
  ruta nativa /app/Workspaces/Restaurante; el panel fijo ya no es visible.
- La prueba bloquea toda API operativa restaurant.pos.* distinta del bootstrap.
- Cero errores JavaScript no capturados y ninguna llamada de escritura operativa.
- Sintaxis Python/JavaScript y git diff --check correctos.
- Un único listener en 8000; HEAD /login devuelve 200.
- Ninguna cuenta nueva. Se usó una sesión separada con el acceso de desarrollo documentado,
  sin guardar credenciales en el código; la prueba cierra su sesión al terminar.

La primera ejecución de la prueba visual esperaba la ruta abreviada del Workspace.
La navegación era correcta: Frappe utiliza la ruta completa. Se ajustó esa expectativa y la ejecución completa pasó.

Comandos dentro del DevContainer, desde /workspace/development/frappe-bench:

```bash
bench --site development run-tests --app restaurant \
  --module restaurant.tests.test_pos_startup --skip-test-records
bench --site development run-tests --app restaurant --skip-test-records
```

Prueba visual: restaurant/tests/ui/pos_startup.cjs.
Requiere LEAF_UI_USER y LEAF_UI_PASSWORD suministrados explícitamente en el entorno;
no escribirlos en archivos versionados.
Opcionales: LEAF_PLAYWRIGHT_MODULE, LEAF_UI_BROWSER, LEAF_UI_BASE_URL, LEAF_UI_OUTPUT.

## Integridad y alcance de datos

VERIFIED: las huellas SHA-256 completas permanecen iguales antes y después de las pruebas:

| DocType | Registros |
| --- | ---: |
| Sales Invoice | 2 |
| POS Invoice | 0 |
| Payment Entry | 0 |
| Stock Entry | 0 |
| GL Entry | 8 |
| Stock Ledger Entry | 0 |
| Restaurant Order | 0 |
| Restaurant Order Item | 0 |
| POS Opening Shift | 1 |
| Restaurant Area | 26 |
| Restaurant Table | 19 |

No se abrieron ni cerraron turnos, ni se guardaron órdenes o emitieron facturas.
Las pruebas backend usan savepoint/rollback. No se cambiaron ramas ni se hicieron commits.

## Alcance pendiente

La causa puntual del bloqueo HTTP transitorio no quedó determinada.
El servidor anterior ejecutaba debugpy y --nothreading; eso no demuestra que el depurador causara el bloqueo.
El reinicio controlado terminó esa sesión de depuración y dejó el servicio web normal.
Para volver a depurar, detén primero el servidor que ocupa 8000 y luego inicia la configuración de VS Code.

Esta reparación no audita integralmente la lógica financiera preexistente.
El bootstrap incluye valores de ejemplo de identificación fiscal y la resolución de tasas usa nombres
de plantillas; antes de certificar el cobro/SAR se necesita revisar ese flujo contra la configuración
nativa de ERPNext y Grintsys. La aplicabilidad fiscal requiere validación tributaria local.

## Archivos de esta reparación

Rutas desde development/frappe-bench/apps/restaurant:

- restaurant/pos.py
- restaurant/restaurant/page/restaurant_pos/__init__.py
- restaurant/restaurant/page/restaurant_pos/restaurant_pos.js
- restaurant/restaurant/page/restaurant_pos/restaurant_pos.css
- restaurant/fixtures/custom_html_block.json
- restaurant/public/js/restaurant_theme.js
- restaurant/hooks.py
- restaurant/tests/test_pos_startup.py
- restaurant/tests/ui/pos_startup.cjs
- docs/pos-arranque.md

Se conservaron los demás cambios locales previos, incluidos el POS y DocTypes en desarrollo.

