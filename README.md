## Restaurant

Restaurant management module for LEAF ERP

#### License

MIT

## Página de bienvenida

La pantalla actual utiliza una plantilla Jinja de Frappe; todavía no contiene una aplicación Vue ni requiere compilar un bundle JavaScript.

- Plantilla: `restaurant/www/restaurant-welcome.html`.
- Ruta web: `/restaurant-welcome`.
- URL de desarrollo: `http://localhost:8000/restaurant-welcome`.

Los archivos de `www` se sirven mediante el enrutador web nativo de Frappe. Esta página no es una ruta de Desk bajo `/app`; registrar un módulo en `config/desktop.py` no crea una página de Desk.

### Después de instalar la app

Desde el directorio del Bench, verifica la instalación y el entorno Python:

```bash
bench --site development list-apps
env/bin/python -c "import restaurant; print(restaurant.__file__)"
bench --site development clear-cache
```

Si el servidor ya estaba iniciado al instalar la app y muestra `ModuleNotFoundError: No module named 'restaurant'`, detén y vuelve a iniciar el servidor web o la sesión **Bench Web** de VS Code. El proceso existente no incorpora automáticamente la nueva instalación editable de Python, especialmente con `--noreload`.

Usa el entorno virtual del Bench con Python 3.11.x. Ejecuta un solo servidor por puerto: detén el proceso web existente antes de iniciar otra sesión de depuración o `bench start`.

## Cambio de identificador de una instalación existente

El identificador de app, paquete Python y módulo es ahora `restaurant` / `Restaurant`.
Para un sitio que ya tenía instalada la app con el nombre anterior, respalda su base de datos antes de actualizar el código. No desinstales la app: la desinstalación puede eliminar datos.

1. Instala el paquete editable desde el directorio del Bench:
   `env/bin/python -m pip install --no-deps -e apps/restaurant`.
2. Retira la distribución anterior: `env/bin/python -m pip uninstall leaf_restaurant`.
3. En `sites/apps.txt` sustituye el identificador anterior por `restaurant`, conservando el resto de apps. Si existe `sites/apps.json`, cambia también su clave anterior a `restaurant`, preservando sus metadatos.
4. Ejecuta `env/bin/python -m restaurant.migrate_app_name --site development`.
5. Ejecuta `bench --site development migrate`, `bench build --app restaurant` y `bench --site development clear-cache`.
6. Reinicia el servidor web y los workers que estuvieran en ejecución.

El procedimiento de registro es idempotente, conserva el orden de las apps instaladas y renombra el módulo mediante la API nativa de Frappe. La ruta anterior de bienvenida redirige a `/restaurant-welcome`.

## Meseros y sucursales

El acceso **Meseros** del Workspace Restaurante utiliza el DocType nativo `Employee`
y filtra por el cargo (`Designation`) **Mesero**. No crea otro registro de personal
ni modifica los campos o permisos globales de Empleado.

1. En **Restaurante → Configuración → Sucursales**, registra las sucursales reales
   con el DocType nativo `Branch`. No es necesario crear otra empresa por sucursal.
2. En **Restaurante → Personal → Meseros**, pulsa **Nuevo**. Mientras el filtro del
   cargo siga aplicado, Frappe completa el cargo **Mesero** en la nueva ficha.
3. Completa los campos obligatorios nativos: nombre, empresa, género, fecha de
   nacimiento y fecha de ingreso. Selecciona la sucursal y el estado laboral.
   El nombre completo se construye a partir del nombre y los apellidos.
4. El teléfono (`cell_number`) es opcional. Una cuenta de usuario también es
   opcional; este cambio no crea cuentas ni asigna permisos de acceso.

La lista incluye los estados nativos Activo, Inactivo, Suspendido y Retirado.
El nombre traducido de cada estado depende del idioma de la sesión. El campo
Sucursal sigue siendo opcional en el esquema nativo: debe seleccionarse al
registrar un mesero para indicar dónde trabaja. Asociar una sucursal no impone
por sí solo restricciones de acceso por sucursal.

Los accesos respetan los permisos nativos: Administrator puede administrarlos;
los responsables de personal requieren los roles correspondientes, como
`HR User` o `HR Manager`. El filtro de Meseros organiza la vista y puede quitarse;
no reemplaza los permisos de seguridad.

La app versiona únicamente el cargo **Mesero** en `restaurant/fixtures/designation.json`.
Los empleados, teléfonos y sucursales de cada sitio no se exportan como fixtures.
Frappe importa esta configuración al instalar o migrar la app por el flujo nativo.

## Ubicaciones del restaurante

El acceso **Restaurante → Configuración → Ubicaciones** utiliza el DocType nativo
`Location`. Sus nombres y su jerarquía representan espacios como salones, terrazas
y áreas VIP. La app no crea un segundo catálogo de ubicaciones.

La extensión declarativa agrega únicamente estos campos a `Location`:

- `restaurant_area`: **Área de restaurante**, identifica las ubicaciones de esta opción.
  Su valor predeterminado es cero; las ubicaciones generales de otros módulos no
  se clasifican automáticamente como áreas del restaurante.
- `restaurant_branch`: **Sucursal**, vínculo al DocType nativo `Branch`. Se muestra
  cuando la ubicación está marcada como área de restaurante. Es opcional en esta
  primera versión; selecciónala para identificar a qué sucursal pertenece el espacio.

Para registrar un espacio:

1. Registra primero la sucursal real desde **Sucursales**, si aún no existe.
2. Abre **Ubicaciones** y pulsa **Nuevo**. Mientras siga aplicado el filtro, Frappe
   completa la marca **Área de restaurante**.
3. Escribe un nombre único, por ejemplo **Centro - Salón 1**, y selecciona la sucursal.
4. Guarda. El mapa y los datos geográficos nativos no son obligatorios.

`Location.location_name` es único en todo el sitio, no por sucursal. Usa nombres
como **Centro - Terraza** y **Norte - Terraza** cuando dos sucursales tengan espacios
con el mismo nombre. La jerarquía nativa es opcional: una ubicación padre debe
estar marcada como grupo para seleccionarse en el formulario.

El filtro organiza la vista y puede quitarse; no constituye aislamiento de permisos.
Se conservan los permisos nativos de `Location`, incluidos los de `System Manager`.
Los campos se versionan en `restaurant/fixtures/custom_field.json`; las ubicaciones
y sucursales reales no se exportan como fixtures. Frappe sincroniza la extensión
al instalar o migrar la app mediante su flujo nativo.

## Pantalla de inicio de Restaurante

El Workspace `/app/restaurante` utiliza el bloque nativo `Custom HTML Block`
**Restaurant Dashboard**, versionado en `restaurant/fixtures/custom_html_block.json`.
El HTML, CSS y JavaScript del bloque reproducen las cuatro secciones del mockup:
Operación diaria, Catálogo, Clientes y reportes, y Configuración. Los estilos están
aislados en el Shadow DOM del bloque; la barra lateral y los demás Workspaces
conservan su presentación nativa. Los iconos provienen del sprite SVG de Frappe,
del conjunto Font Awesome incluido en LEAF y del icono de restaurante existente.

Los accesos de productos, grupos, precios, meseros, ubicaciones y clientes abren
los documentos nativos. **Punto de venta** abre el POS Awesome ya instalado; no
representa la implementación del nuevo POS táctil gastronómico. **Reportes**
ofrece los reportes nativos de ventas. **Configuración** conserva los accesos a
sucursales, listas de precios, unidades de medida y bienvenida. Los filtros y
permisos existentes se mantienen.

Las tarjetas de Cuentas, Nueva cuenta, Mesas, Mapa de mesas, Comandas y Cocina KDS
son referencias visuales pendientes de desarrollo. Su título indica el estado
y al pulsarlas se informa que todavía no están habilitadas; no crean cuentas
ni documentos. La tarjeta Mapa de mesas se incluye para reproducir el último
mockup y no agrega un mapa ni modifica el alcance del POS gastronómico.

Para editar esta portada desde Desk, utiliza el registro **Custom HTML Block →
Restaurant Dashboard**, modifica sus campos HTML/CSS/JavaScript y exporta los
fixtures de `restaurant`. Conserva el nombre del bloque porque el Workspace
lo referencia. En la tabla **Custom Blocks** del Workspace, conserva también
`label = Restaurant Dashboard`: el renderizador de Frappe v14 busca el bloque
por esa etiqueta. Cambiarla por «Restaurante» deja la portada sin contenido; los
títulos visibles en español se definen dentro del HTML, no en esa referencia.
Después de actualizar la configuración local, recarga el navegador
con `Ctrl + Shift + R`.
