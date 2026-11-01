## Restaurant

Módulo de gestión de restaurantes (**Custom App** independiente) para **LEAF ERP v14** sobre **Frappe / ERPNext v14**.

#### License

MIT

---

## Entrega académica: semana 1

- Participante: **Manuel Padilla**, Ingeniería en Sistemas, CEUTEC.
- Token de identificación de la entrega: **`LEARN-CAP-57D6DFA7`**.
- Repositorio principal (Upstream académico): `https://github.com/SOLFAHSA/restaurant.git`
- Rama activa de desarrollo: `feature/modulo-restaurante`
- [Visión, evidencia, Lean Canvas, hipótesis y alcance](docs/vision.md).
- [Bitácora de la semana 1](docs/bitacora/semana-1.md).

Este token identifica la entrega académica del participante; no modifica la
licencia ni la atribución del proyecto Grintsys.

**Estado:** repositorio de la Custom App estructurado bajo control del autor en
`SOLFAHSA/restaurant` para evaluación docente y preparado para integración vía
**Fork / Merge** hacia la organización **Grintsys**. La URL de demostración
pública por HTTPS continúa pendiente; la dirección `localhost` corresponde al
entorno local de desarrollo.

---

## Arquitectura del repositorio y modelo de integración (SOLFAHSA ➔ Grintsys)

Siguiendo la regla arquitectónica de **LEAF ERP v14** (*ERPNext como motor transaccional y principio Zero-Fork sobre el Core*), todo el desarrollo del módulo Restaurante reside en esta **Custom App independiente (`restaurant`, Nivel 3 / Categoría C)**, al mismo nivel modular que `frappe`, `erpnext`, `posawesome` y `hrms`.

```text
SOLFAHSA/restaurant (Upstream / Práctica Profesional CEUTEC)
   │
   ├──► Evaluación Docente (Control de versiones, bitácora, visión y releases)
   │
   └──► Fork & Pull Request / Sync Fork ──► Grintsys/restaurant (Repositorio Empresarial)
                                                │
                                                └──► bench get-app / install-app en entornos de prueba LEAF ERP v14
```

Este esquema garantiza:

1. **Autonomía académica:** el autor conserva control total del repositorio origen (`https://github.com/SOLFAHSA/restaurant.git`) para auditoría de commits, documentación y etiquetas de evaluación.
2. **Soberanía empresarial para Grintsys:** Grintsys puede realizar un **Fork** hacia `https://github.com/Grintsys/restaurant.git` (exactamente igual que el modelo utilizado en `Grintsys/POS-Awesome-14.git`), revisar cada avance y sincronizarlo en sus servidores de prueba sin afectar ni modificar los repositorios base (`frappe14` y `erpnext14`).

---

## Guía de instalación en Frappe Bench v14

### 1. Requisitos previos del entorno

- **Frappe Bench v14** ejecutándose con **Python 3.11.x** (obligatorio para compatibilidad con dependencias de Frappe v14).
- Aplicaciones base instaladas en el sitio:
  - `frappe` (`version-14`)
  - `erpnext` (`version-14`)
  - `posawesome` (`version-14`)

### 2. Instalación directa en un entorno de desarrollo

Desde el directorio del Bench (`/workspace/development/frappe-bench`):

```bash
# 1. Descargar la Custom App desde el repositorio principal
bench get-app --branch feature/modulo-restaurante https://github.com/SOLFAHSA/restaurant.git

# 2. Instalar la aplicación en el sitio (ejemplo: development)
bench --site development install-app restaurant

# 3. Ejecutar migraciones para sincronizar Workspace, Custom HTML Block y Fixtures
bench --site development migrate

# 4. Compilar recursos y limpiar caché
bench build --app restaurant
bench --site development clear-cache
```

### 3. Flujo de Fork, sincronización y despliegue para Grintsys

Para integrar y actualizar esta aplicación dentro de los entornos de prueba de **Grintsys**:

#### Paso A: Crear el Fork en la organización Grintsys
1. Iniciar sesión en GitHub con una cuenta con permisos en la organización `Grintsys`.
2. Abrir `https://github.com/SOLFAHSA/restaurant` y pulsar el botón **Fork**.
3. Seleccionar como propietario (**Owner**) a `Grintsys` y conservar el nombre `restaurant` (`https://github.com/Grintsys/restaurant.git`).
4. Desmarcar la opción *"Copy the default branch only"* si se desea copiar también la rama `feature/modulo-restaurante`.

#### Paso B: Instalar desde el Fork de Grintsys en servidores de prueba
```bash
cd /workspace/development/frappe-bench
bench get-app --branch feature/modulo-restaurante https://github.com/Grintsys/restaurant.git
bench --site development install-app restaurant
bench --site development migrate
bench --site development clear-cache
```

#### Paso C: Actualizar el Fork de Grintsys cuando existan nuevos commits en `SOLFAHSA/restaurant`
Puede realizarse desde la interfaz web de GitHub pulsando **Sync fork ➔ Update branch**, o desde la terminal del repositorio clonado:

```bash
cd /workspace/development/frappe-bench/apps/restaurant

# Registrar el repositorio del practicante como upstream (solo la primera vez)
git remote add upstream https://github.com/SOLFAHSA/restaurant.git

# Descargar y fusionar los nuevos avances verificados
git fetch upstream
git checkout feature/modulo-restaurante
git merge upstream/feature/modulo-restaurante

# Subir los cambios revisados al Fork oficial de Grintsys
git push origin feature/modulo-restaurante

# Aplicar cambios en el sitio de pruebas de Frappe
cd /workspace/development/frappe-bench
bench --site development migrate
bench --site development clear-cache
```

---

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

## Ubicaciones y áreas del restaurante

El acceso **Restaurante → Configuración → Ubicaciones** abre una pantalla Desk
propia en `/app/restaurant-location`, respaldada por el nuevo DocType independiente
`Restaurant Area`, módulo `Restaurant`. La pantalla reproduce la estructura y
los colores del mockup, con información general, vista previa, configuración
operativa y una sección para futuras mesas vinculadas.

Esta decisión responde a la solicitud explícita de mantener las áreas operativas
exclusivas del restaurante. `Location` y sus campos previos se conservan para
compatibilidad; no se copian ni eliminan sus registros. La fuente de verdad de
las nuevas áreas es `Restaurant Area`. Esta funcionalidad corresponde a una etapa
posterior a la inducción documentada en la semana 1.

Para registrar un área:

1. Registra primero la sucursal real desde **Sucursales**, si aún no existe.
2. Abre **Ubicaciones** y pulsa **Nueva ubicación**.
3. Completa nombre, sucursal, tipo de área y capacidad; el nombre es único en el
   sitio. Usa nombres como **Centro - Terraza** y **Norte - Terraza** si corresponde.
4. Selecciona estado, visibilidad, orden, color e icono o imagen. La impresora y el
   mesero son opcionales; el mesero debe estar activo, tener cargo **Mesero** y
   pertenecer a la sucursal elegida.
5. Pulsa **Guardar ubicación**. El registro se puede reabrir desde el listado.

El formulario nativo sigue disponible en `/app/restaurant-area`; su botón
**Abrir diseño de ubicaciones** permite regresar al editor visual. Los controles
se adaptan a móvil. Los roles autorizados son `System Manager` y
`Restaurant Manager`, respetando las restricciones por sucursal.

KDS y vinculación de mesas permanecen deshabilitados hasta contar con sus
catálogos e integración. Las opciones de POS, cuentas e impresora guardan
configuración y no ejecutan facturación, cobros ni impresión de comandas.

Para instalar esta versión en un sitio autorizado, ejecuta desde el Bench:

```bash
bench --site development migrate
bench --site development clear-cache
```

Reinicia el servidor si se ejecutaba sin recarga automática. No se necesita
compilar un bundle para los archivos de esta Page. Consulta la
[decisión de arquitectura y evidencia de pruebas](docs/ubicaciones.md).

## Pantalla de inicio de Restaurante

El Workspace `/app/restaurante` utiliza el bloque nativo `Custom HTML Block`
**Restaurant Dashboard**, versionado en `restaurant/fixtures/custom_html_block.json`.
El HTML, CSS y JavaScript del bloque reproducen las cuatro secciones del mockup:
Operación diaria, Catálogo, Clientes y reportes, y Configuración. Los estilos están
aislados en el Shadow DOM del bloque; la barra lateral y los demás Workspaces
conservan su presentación nativa. Los iconos provienen del sprite SVG de Frappe,
del conjunto Font Awesome incluido en LEAF y del icono de restaurante existente.

Los accesos de productos, grupos, precios, meseros y clientes abren los
documentos nativos. Ubicaciones abre el editor de `Restaurant Area`. **Punto de venta** abre el POS Awesome ya instalado; no
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
