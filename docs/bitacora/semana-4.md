# Bitácora de actividades — Semana 4

**Proyecto:** Desarrollo del módulo Restaurante para Leaf ERP

**Empresa receptora:** Grintsys

**Institución:** CEUTEC

**Asignatura:** Proyecto de Graduación Fase 1

**Etapa:** Semana 4 — Usuarios, cuentas, roles y flujo operativo integral del restaurante

**Tecnologías:** Frappe Framework, ERPNext v14, Python 3.11, JavaScript y MariaDB

**Entorno en línea (HTTPS):** `https://leaf-dev.hsjddhn.com/#login`

## 1. Introducción

Durante la cuarta semana de práctica profesional en Grintsys, el trabajo técnico se enfocó en dos ejes complementarios: por un lado, consolidar el modelo de **autenticación, autorización basada en roles (RBAC), menor privilegio y propiedad del dato** del módulo Restaurante; y por otro, completar la integración de los procesos operativos de piso (mesas y plano del salón, configuración de platillos y combos, estaciones de comanda, punto de venta de restaurante, gestión de cuentas y órdenes, división y transferencia de cuentas, y pantalla de cocina KDS).

Asimismo, se verificó la publicación del entorno bajo **HTTPS** en dominio público (`https://leaf-dev.hsjddhn.com/#login`), se documentó la matriz formal de permisos en [`docs/permisos.md`](../permisos.md) y se ejecutaron pruebas exhaustivas en servidor para comprobar que cada restricción se cumpla en el backend y en la base de datos, independientemente de la interfaz gráfica.

## 2. Objetivo de la semana

Implementar y verificar el control de acceso por roles (`System Manager`, `Restaurant Manager`, `Restaurant User` y bloqueo a `Guest`) junto con las reglas de propiedad del dato en el servidor, integrando el recorrido operativo completo del restaurante y documentando la matriz de permisos (`docs/permisos.md`) y las lecciones del caso de estudio de la semana.

## 3. Actividades realizadas

### 3.1. Autenticación nativa, sesiones y recuperación de contraseña en producción

Siguiendo la primera regla de seguridad estudiada en el módulo (*«no programar la autenticación desde cero»*), se utilizó el motor de identidad nativo de **Frappe Framework v14** publicado bajo HTTPS en `https://leaf-dev.hsjddhn.com/#login`:

- **Almacenamiento seguro de contraseñas:** las contraseñas nunca se guardan en texto plano ni en tablas propias del módulo; residen en la tabla interna `__Auth` cifradas mediante hash criptográfico con sal (`PBKDF2-SHA256`).
- **Inicio y cierre real de sesión:** el inicio de sesión genera una sesión de servidor en `tabSessions` con expiración por inactividad, mientras que el cierre de sesión (`/api/method/logout`) revoca el token en el servidor e invalida el acceso inmediatamente.
- **Recuperación de contraseña:** utiliza enlaces con tokens de un solo uso y vencimiento temporal.
- **Modelo de ingreso por rol:** el personal del restaurante no se auto-registra con privilegios; las cuentas son creadas o invitadas desde el panel administrativo por el `System Manager`, evitando que un usuario externo se auto-asigne un rol superior.

**Resultado:** flujo de registro por invitación, inicio de sesión, cierre de sesión y recuperación de contraseña operativo sobre HTTPS.

### 3.2. Definición de roles en base de datos y principio de menor privilegio

Se estructuró en [`restaurant/setup.py`](../../restaurant/setup.py) y en los esquemas JSON de los DocTypes del módulo una jerarquía de tres roles autenticados más el perfil anónimo:

1. **`System Manager` (Administrador / Dueño):** administra usuarios, asigna roles y permisos por sucursal (`User Permission`), e importa/exporta catálogos.
2. **`Restaurant Manager` (Gerente / Supervisor de sucursal):** configura áreas, mesas, estaciones de comanda, opciones de platillos, ajustes preestablecidos y pantallas KDS de su sucursal, además de operar y supervisar cuentas y facturación SAR.
3. **`Restaurant User` (Mesero / Operador de salón y cocina):** consulta áreas, mesas y catálogo; abre cuentas, comanda a cocina, actualiza etapas en el KDS y divide o transfiere cuentas en curso, pero **no tiene permiso para eliminar órdenes (`delete: 0`) ni modificar catálogos o configuraciones**.
4. **`Guest` (Visitante sin sesión):** bloqueado en todas las páginas, DocTypes y endpoints del módulo.

Adicionalmente, mediante `ensure_link_permissions()` en `setup.py`, se aplicó el principio de **menor privilegio** sobre los DocTypes corporativos de ERPNext (`Employee`, `Branch`, `Item Group`), otorgando únicamente el permiso `select = 1` (y poniendo en `0` los permisos `read`, `write`, `create` y `delete`). De esta manera, el personal del restaurante puede asociar un mesero a una cuenta sin acceder a los expedientes privados ni salarios de Recursos Humanos.

**Resultado:** roles persistidos en base de datos y política de menor privilegio aplicada automáticamente en cada migración.

### 3.3. Elaboración de la matriz de permisos y propiedad del dato (`docs/permisos.md`)

Se redactó el documento [`docs/permisos.md`](../permisos.md) cruzando las 20 acciones principales de las historias de usuario del módulo contra los roles del sistema y especificando las reglas de **propiedad del dato**:

- **Aislamiento por sucursal (`Branch` / `User Permission`):** cada gerente u operador con restricción de sucursal solo puede consultar o modificar áreas, mesas y estaciones de su propia sucursal.
- **Autoría y turno de caja (`owner`, `cashier`, `POS Opening Shift`):** el servidor sella la identidad del cajero y propietario a partir de `frappe.session.user`, ignorando atributos manipulados en el cliente.
- **Inmutabilidad fiscal SAR (`Sales Invoice`):** ninguna cuenta en estado `Facturada` o `Cancelada`, ni vinculada a una factura emitida, puede ser editada, dividida, transferida o cancelada desde el POS.

**Resultado:** contrato de autorización documentado en `docs/permisos.md`.

### 3.4. Integración de procesos operativos del restaurante (Mesas, Comandas, POS, Cuentas y KDS)

Durante este ciclo se consolidaron y verificaron los componentes funcionales que conforman el recorrido completo del restaurante:

- **Mesas y mapa interactivo del salón (`Restaurant Table` y `restaurant-table-map`):** creación de mesas vinculadas a áreas y sucursales, diseño visual del plano y sincronización automática del estado (`Disponible` / `Ocupada`).
- **Configuración de platillos, recetas y grupos de opciones (`Item`, `Product Bundle` y `Restaurant Option Group`):** extensión declarativa sobre `Item` para definir insumos y modificadores de preparación.
- **Estaciones de comanda (`Restaurant Command`) y ajustes preestablecidos (`Restaurant Order Preset`):** enrutamiento de categorías de productos hacia estaciones de cocina/barra y parametrización de modalidades (*Comer en el local*, *Para llevar*, *Entrega*) mediante DocTypes propios, sin listas fijas en código.
- **Gestión de Cuentas y Órdenes (`Restaurant Order`):** habilitación del acceso **Cuentas** y **Nueva cuenta** en el Workspace de *Operación diaria*, vista de lista con indicadores de estado (`En curso`, `Facturada`, `Cancelada`) y vista de formulario estructurada en pestañas (`Productos`, `Pagos`, `Información adicional`, `Nota para el cliente`) con acciones rápidas hacia el Punto de Venta y la Factura SAR.
- **División, transferencia y fusión atómica de cuentas (`order_operations.py`) y Cocina KDS (`restaurant_kds`):** separación parcial o total de platillos entre cuentas o mesas conservando el avance exacto de preparación en las pantallas de cocina (`To cook`, `Ready`, `Completed`).

**Resultado:** recorrido operativo de punta a punta integrado sobre ERPNext v14.

## 4. Prueba de permisos de la semana (Servidor vs. Usuario curioso)

Siguiendo la metodología de la Clase 4 del Módulo 4, se verificó cada regla tanto con cuentas por rol como mediante llamadas directas al servidor simulando a un usuario curioso que intenta saltarse la interfaz. Las credenciales de demostración se entregaron al docente por el canal privado del curso (nunca dentro del repositorio).

| # | Escenario probado (incluyendo intentos prohibidos) | Rol utilizado | Resultado en servidor y base de datos | Estado |
| :-: | :--- | :--- | :--- | :---: |
| **1** | Abrir el Punto de Venta (`get_pos_bootstrap`), listar áreas (`get_locations`) o listar comandas (`get_commands`) sin haber iniciado sesión o tras cerrar sesión | `Guest` | El servidor rechaza la petición con `frappe.PermissionError` (HTTP 403) antes de consultar datos. | ✅ Cumple |
| **2** | Enviar un payload con `flags={"ignore_permissions": True}` o `owner="Guest"` al guardar un área o estación de comanda | `Guest` / `Restaurant Manager` | El servidor ignora los campos inyectados, exige permiso real y conserva `owner` del usuario autenticado en sesión (`test_payload_cannot_escalate_permissions`, `test_payload_cannot_change_document_type_or_protected_fields`). | ✅ Cumple |
| **3** | Gerente asignado a *Sucursal Centro* cambia el identificador en la petición para leer o editar un área o comanda de *Sucursal Norte* | `Restaurant Manager` (con `User Permission` en `Branch`) | El servidor bloquea la lectura y escritura sobre la otra sucursal lanzando `frappe.PermissionError` (`test_branch_user_permission_is_enforced`, `test_manager_branch_permission_limits_read_create_and_edit`). | ✅ Cumple |
| **4** | Operador de piso crea y actualiza una cuenta en curso en el POS, pero intenta eliminar el documento `Restaurant Order` o crear/editar un `Restaurant Area` | `Restaurant User` | La creación y actualización de la orden en curso proceden; el intento de eliminar la orden (`delete: 0`) o modificar áreas/configuraciones es rechazado por el servidor (`test_role_matrix_enforces_least_privilege_on_restaurant_order`, `test_read_only_user_can_open_list_but_not_create`). | ✅ Cumple |
| **5** | Usuario autenticado pero con un rol ajeno al restaurante (ej. `Sales User` sin rol de restaurante) invoca las APIs del POS | Usuario sin rol del módulo | `_require_pos_user()` rechaza la llamada en el servidor con `frappe.PermissionError` (`test_authenticated_user_without_page_roles_is_rejected`). | ✅ Cumple |
| **6** | Intentar dividir, transferir, fusionar o cancelar una cuenta que ya tiene estado `Facturada` o vínculo a `Sales Invoice` SAR | `Restaurant Manager` / `Restaurant User` | El servidor bloquea la operación con `ValidationError` manteniendo intacta la factura y la cuenta (`test_billed_and_cancelled_accounts_cannot_be_split_or_transferred`). | ✅ Cumple |
| **7** | Manipular desde el navegador el estado KDS de un platillo o la estación de comanda al guardar la orden en el POS | `Restaurant User` / `Restaurant Manager` | El servidor ignora el estado forjado y recalcula la estación y el grupo desde MariaDB (`test_pos_save_preserves_sent_row_identity_and_ignores_forged_kitchen_state`, `test_pos_cannot_forge_native_item_group_or_kitchen_routing`). | ✅ Cumple |

## 5. Aplicación de las lecciones del caso real (`HealthCare.gov`) al proyecto

El análisis del lanzamiento fallido de *HealthCare.gov* estudiado en la Clase 3 dejó cuatro lecciones directas que aplicamos en esta entrega:

1. **Probar el recorrido completo, temprano y seguido:** en lugar de probar DocTypes aislados, verificamos la cadena completa desde el alta de sucursal, área y mesa, pasando por la apertura de cuenta en el POS, envío a cocina KDS, división/transferencia de platillos y cierre con generación de `Sales Invoice` nativa de ERPNext.
2. **La autenticación y los permisos son parte del camino crítico:** validamos el inicio de sesión en el dominio HTTPS (`https://leaf-dev.hsjddhn.com/#login`) y comprobamos que los roles (`System Manager`, `Restaurant Manager`, `Restaurant User`) tengan los permisos de enlace (`select` en `Branch`, `Employee`, `Item Group`) necesarios para que la operación no falle al cambiar de una cuenta de administrador a una cuenta operativa.
3. **Un cambio tardío de requisitos tiene costo de diseño:** reemplazar valores fijos en código por DocTypes parametrizables (`Restaurant Order Preset`, `Restaurant Preparation Stage`) de forma oportuna evitó arrastrar deuda técnica hacia las siguientes etapas.
4. **Publicar en pequeño antes de publicar en grande:** dejamos preparado y verificado el incremento funcional para que en la **Semana 5** pueda probarse de forma controlada con los primeros usuarios reales.

## 6. Resultados obtenidos

1. Autenticación, manejo de sesiones y recuperación de contraseña verificados sobre HTTPS (`https://leaf-dev.hsjddhn.com/#login`).
2. Roles operativos (`System Manager`, `Restaurant Manager`, `Restaurant User`) y política de menor privilegio (`select` en vínculos) configurados en `restaurant/setup.py` y en los DocTypes del módulo.
3. Matriz completa de permisos (`Acciones × Roles` y propiedad del dato) documentada en [`docs/permisos.md`](../permisos.md).
4. Vistas de **Cuentas (`Restaurant Order`)**, **Punto de Venta**, **Transferir / Dividir cuentas** y **Cocina KDS** integradas y respaldadas por pruebas automatizadas en servidor (más de 100 pruebas unitarias aprobadas en la suite de la aplicación).
5. Publicación del release y etiqueta `semana-4` en el repositorio oficial `https://github.com/SOLFAHSA/restaurant.git`.

## 7. Dificultades identificadas

Uno de los retos más importantes fue equilibrar el principio de **menor privilegio** con las dependencias internas de un ERP empresarial como ERPNext: al restringir un rol operativo para que no lea información sensible de otras áreas (como `Employee` en Recursos Humanos), los campos `Link` en los formularios pueden fallar si no se otorga explícitamente el permiso `select`. La solución mediante `Custom DocPerm` en `ensure_link_permissions()` permitió mantener la seguridad sin romper la experiencia de uso.

## 8. Aprendizajes de la semana

Durante esta cuarta semana comprendí en la práctica la diferencia entre **autenticación** (*quién sos*) y **autorización** (*qué podés hacer y sobre qué datos*), así como el peligro de confiar en validaciones puramente visuales en JavaScript. Aprendí a diseñar una matriz de permisos formal, a implementar reglas de propiedad del dato por sucursal y estado transaccional en el servidor, y a comprobarlas intentando deliberadamente realizar acciones no permitidas con cada rol.

## 9. Próximas actividades (Semana 5)

- Ejecutar pruebas de uso del MVP con usuarios reales aplicando la lección de lanzamiento gradual (*publicar en pequeño*).
- Recopilar observaciones de usabilidad en los flujos de toma de pedido, KDS, división de cuentas y facturación SAR.
- Continuar el refinamiento de reportes operativos y trazabilidad en el repositorio.

## 10. Conclusión

La cuarta semana permitió dotar al módulo Restaurante de un esquema de seguridad, cuentas y roles profesional sobre Frappe / ERPNext v14, garantizando que cada operación de salón, caja y cocina esté respaldada por permisos verificados en el servidor y reglas claras de propiedad del dato. Con la documentación de `docs/permisos.md`, la bitácora `docs/bitacora/semana-4.md` y el release `semana-4`, el proyecto queda listo para iniciar las pruebas con usuarios reales en la siguiente etapa.
