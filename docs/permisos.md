# Matriz de permisos, roles y propiedad del dato — Módulo Restaurante (LEAF ERP v14)

**Proyecto:** Desarrollo del módulo Restaurante para LEAF ERP v14  
**Empresa receptora:** Grintsys  
**Institución:** CEUTEC — Proyecto de Graduación Fase 1  
**Módulo académico:** Semana 4 — Usuarios, cuentas y roles  
**Repositorio:** `https://github.com/SOLFAHSA/restaurant.git`  
**Entorno en línea (HTTPS):** `https://leaf-dev.hsjddhn.com/#login`

---

## 1. Propósito del documento

Este documento define el contrato de **autenticación**, **autorización basada en roles (RBAC)**, **menor privilegio** y **propiedad del dato** del módulo **Restaurante** sobre **Frappe / ERPNext v14**.

Siguiendo el principio de seguridad de ingeniería de software (*«la pantalla sugiere; el servidor y la base de datos deciden»*), cada regla descrita en esta matriz se valida obligatoriamente en el servidor (controladores Python, endpoints `@frappe.whitelist()`, `DocPerm`, `Custom DocPerm` y `User Permission` en MariaDB) antes de ejecutar cualquier acción o devolver datos.

---

## 2. Autenticación sin inventar la rueda

El módulo Restaurante delega el 100 % de la identidad y gestión de sesiones al motor nativo de **Frappe Framework v14**, evitando cualquier implementación casera de contraseñas o tokens:

| Componente de autenticación | Implementación en LEAF ERP v14 (Frappe Framework) | Regla de seguridad cumplida |
| :--- | :--- | :--- |
| **Inicio de sesión** | Ruta nativa `/login` (`#login`) y endpoint `/api/method/login` sobre **HTTPS** (`https://leaf-dev.hsjddhn.com/#login`). | Mensajes genéricos ante fallos de credenciales para no revelar qué correos tienen cuenta registrada; protección contra fuerza bruta. |
| **Almacenamiento de contraseñas** | Tabla interna `__Auth` de Frappe usando **hash criptográfico con sal (`PBKDF2-SHA256` vía `passlib`)**. | Ningún DocType del restaurante ni la tabla `tabUser` almacena contraseñas en texto plano ni reversibles. |
| **Sesiones y vencimiento** | Sesiones persistidas en servidor (`tabSessions`) con cookie `sid` (`HttpOnly`, `SameSite`, `Secure` en HTTPS) y expiración por inactividad. | Las terminales compartidas de caja o salón vencen su sesión tras inactividad; el estado de sesión reside en el servidor. |
| **Cierre de sesión real** | Endpoint nativo `/api/method/logout`. | Revoca y elimina la sesión activa en `tabSessions` dentro del servidor; cualquier intento posterior de usar la app o retroceder en el navegador es rechazado con `frappe.PermissionError`. |
| **Recuperación de contraseña** | Flujo nativo de restablecimiento de Frappe (`/login#forgot`). | Genera un enlace con token criptográfico de **un solo uso** y **vencimiento temporal corto**, invalidado inmediatamente después de utilizarse. |
| **Ingreso y registro de cuentas por rol** | **Alta e invitación administrativa cerrada** desde el panel de usuarios (`User`) por el `System Manager`. | **No existe registro abierto para roles operativos ni administrativos.** Ningún visitante puede auto-registrarse ni auto-asignarse un rol con permisos en el restaurante. |

---

## 3. Roles del sistema y principio de menor privilegio

Los roles viven en la base de datos (`tabRole` y `tabHas Role` asociados a `tabUser`) y se instalan de forma idempotente mediante el hook `before_migrate` en [`restaurant/setup.py`](../restaurant/setup.py). **Nunca** se codifican correos ni usuarios fijos en el código fuente.

### 3.1. Catálogo de roles del módulo Restaurante

| Rol en base de datos | Perfil de negocio en el restaurante | Cómo obtiene su cuenta | Alcance general (Menor privilegio) |
| :--- | :--- | :--- | :--- |
| **`System Manager`** | **Administrador / Dueño del sistema** | Creado e invitado únicamente por administración central. | Control total de configuración, creación de usuarios, asignación de roles, restricciones por sucursal (`User Permission`) e importación/exportación de datos. |
| **`Restaurant Manager`** | **Gerente / Supervisor de restaurante y caja** | Invitado por `System Manager` con rol asignado en base de datos y sucursal asignada. | Administra la configuración operativa de su sucursal (áreas, plano de mesas, estaciones de comanda, pantallas/etapas KDS, opciones de platillos) y supervisa/factura cuentas en el POS. |
| **`Restaurant User`** | **Mesero / Operador de salón y cocina (KDS)** | Invitado por `System Manager` con permisos operativos acotados a salón, POS y cocina. | Consulta el mapa de mesas, áreas y catálogo; abre cuentas, toma pedidos, envía comandas a cocina, marca etapas en KDS y divide/transfiere cuentas en curso. **No puede eliminar cuentas ni modificar áreas, mesas, estaciones ni configuraciones.** |
| **`Guest`** | **Visitante no autenticado** | Sin sesión iniciada. | **Cero acceso** a rutas operativas, páginas de Desk y APIs del restaurante. Todo intento devuelve `403 Forbidden` / `frappe.PermissionError`. |

### 3.2. Aplicación estricta del menor privilegio sobre ERPNext

1. **Permiso `select` mínimo en vínculos corporativos (`restaurant/setup.py`):**
   - `ensure_link_permissions()` otorga a `Restaurant Manager` y `Restaurant User` únicamente el permiso `select = 1` (forzando `read = 0, write = 0, create = 0, delete = 0, report = 0, export = 0`) sobre `Branch`, `Employee` e `Item Group`.
   - **Efecto:** Un gerente o mesero puede seleccionar al mesero que atiende una mesa o filtrar por sucursal, pero **no puede abrir ni leer los expedientes confidenciales ni salarios de Recursos Humanos (`Employee`)**.
2. **Protección de tickets de cocina (`Restaurant Preparation Ticket`):**
   - El DocType `Restaurant Preparation Ticket` tiene `create = 0, write = 0, delete = 0, allow_import = 0` incluso para administradores en el formulario estándar, obligando a que toda transición de estado de cocina ocurra exclusivamente a través de las validaciones de integridad del servidor en `restaurant/kds.py`.
3. **Prohibición de eliminación de cuentas para operadores (`Restaurant Order`):**
   - El rol `Restaurant User` tiene `read = 1, create = 1, write = 1, delete = 0`. Un mesero no puede borrar registros de cuentas de la base de datos.

---

## 4. Matriz de permisos (`Acciones × Roles` y propiedad del dato)

**Convenciones de la matriz:**
- **✔ (Todas):** Permitido en todas las sucursales del sistema.
- **✔ (Su sucursal):** Permitido únicamente sobre registros pertenecientes a la sucursal (`Branch`) autorizada al usuario en `User Permission`.
- **✔ (En curso / Su turno):** Permitido únicamente sobre cuentas con estado `En curso` (no facturadas ni canceladas) dentro del turno o sucursal activa.
- **✘:** Denegado en el servidor (`frappe.PermissionError` / `frappe.ValidationError`) y oculto en la interfaz.

| # | Historia / Módulo | Acción de negocio | `System Manager` (Dueño / Admin) | `Restaurant Manager` (Gerente / Supervisor) | `Restaurant User` (Mesero / Cocina) | `Guest` (No autenticado) | Regla de propiedad del dato y validación en servidor |
| :-: | :--- | :--- | :---: | :---: | :---: | :---: | :--- |
| **1** | **Autenticación y Usuarios** | Iniciar sesión, cerrar sesión y recuperar contraseña | ✔ | ✔ | ✔ | ✔ *(solo `/login`)* | Validado por Frappe en `__Auth` y `tabSessions`. |
| **2** | **Autenticación y Usuarios** | Invitar usuarios, asignar roles y definir `User Permission` por sucursal | ✔ (Todas) | ✘ | ✘ | ✘ | Solo `System Manager` modifica `User`, `Role` y `User Permission`. Evita auto-escalación de privilegios. |
| **3** | **Ubicaciones (`Restaurant Area`)** | Ver listado y detalle de áreas / salones del restaurante | ✔ (Todas) | ✔ (Su sucursal) | ✔ (Su sucursal) | ✘ | `frappe.has_permission("Restaurant Area", "read")` + filtro nativo por `Branch` en `restaurant/location.py`. |
| **4** | **Ubicaciones (`Restaurant Area`)** | Crear, editar o desactivar áreas del restaurante | ✔ (Todas) | ✔ (Su sucursal) | ✘ | ✘ | Validado en `save_location()` con `doc.check_permission("write" / "create")` y control de concurrencia por `modified`. |
| **5** | **Mesas y Plano (`Restaurant Table`)** | Consultar mapa de mesas y disponibilidad en vivo | ✔ (Todas) | ✔ (Su sucursal) | ✔ (Su sucursal) | ✘ | Lectura validada por rol y sucursal del área padre. |
| **6** | **Mesas y Plano (`Restaurant Table`)** | Crear mesas, eliminar mesas o diseñar el plano del salón (`save_area_map`) | ✔ (Todas) | ✔ (Su sucursal) | ✘ | ✘ | Requiere permiso `write`/`create`/`delete` en `Restaurant Table` y `Restaurant Area`. |
| **7** | **Catálogo y Menú (`Item`, `Restaurant Option Group`)** | Consultar platillos, precios y grupos de opciones en el POS | ✔ (Todas) | ✔ (Su sucursal) | ✔ (Su sucursal) | ✘ | validado por `_require_pos_user()` en `restaurant/pos.py`. |
| **8** | **Catálogo y Menú (`Item`, `Restaurant Option Group`)** | Configurar recetas (`Product Bundle`), grupos de opciones y adicionales de platillos | ✔ (Todas) | ✔ (Su sucursal) | ✘ | ✘ | Validado en `restaurant/item_configuration.py` (`save_recipe`, `save_option_group`). |
| **9** | **Comandas (`Restaurant Command`)** | Consultar estaciones de comanda (Cocina, Barra, Parrilla) | ✔ (Todas) | ✔ (Su sucursal) | ✔ (Su sucursal) | ✘ | Filtrado por `Branch` y permisos nativos en `restaurant/commands.py`. |
| **10** | **Comandas (`Restaurant Command`)** | Crear o modificar estaciones de comanda y sus categorías asociadas | ✔ (Todas) | ✔ (Su sucursal) | ✘ | ✘ | `save_command()` verifica `check_permission` y rechaza sobrescritura de `owner` o `doctype`. |
| **11** | **Ajustes (`Restaurant Order Preset`)** | Consultar modalidades de servicio (*Comer en el local*, *Para llevar*, *Entrega*) | ✔ (Todas) | ✔ | ✔ | ✘ | `Restaurant User` tiene `read: 1, write: 0, create: 0, delete: 0`. |
| **12** | **Ajustes (`Restaurant Order Preset`)** | Crear, editar o eliminar ajustes preestablecidos de orden | ✔ (Todas) | ✔ | ✘ | ✘ | Restringido a `System Manager` y `Restaurant Manager` en `DocPerm`. |
| **13** | **Cuentas y POS (`Restaurant Order`)** | Abrir cuenta en mesa o venta directa, agregar platillos y guardar comanda | ✔ (Todas) | ✔ (En curso) | ✔ (En curso) | ✘ | `_require_pos_user()` + `doc.check_permission("write")`. Sella `cashier = frappe.session.user`. |
| **14** | **Cuentas y POS (`Restaurant Order`)** | Enviar comanda a cocina (`send_order_to_kitchen`) e imprimir precuenta | ✔ (Todas) | ✔ (En curso) | ✔ (En curso) | ✘ | Solo envía líneas en estado `Pendiente`; impide reabrir platillos ya entregados. |
| **15** | **Operaciones de Cuenta (`order_operations.py`)** | Dividir cuenta (`split_order`), transferir de mesa o fusionar cuentas activas (`transfer_order`) | ✔ (En curso) | ✔ (En curso) | ✔ (En curso) | ✘ | Verifica `check_permission("write")` en origen y destino; **rechaza cuentas `Facturadas` o `Canceladas`** y verifica versión `expected_modified`. |
| **16** | **Facturación Fiscal SAR (`Sales Invoice`)** | Cobrar cuenta y emitir Factura SAR con CAI e ISV 15 % / 18 % (`pay_and_invoice_order`) | ✔ (En curso) | ✔ (En curso) | ✔ (En curso / Su turno) | ✘ | Genera `Sales Invoice` nativa de ERPNext vinculada al `POS Opening Shift` activo del usuario en sesión y bloquea la cuenta como `Facturada`. |
| **17** | **Cuentas y POS (`Restaurant Order`)** | Cancelar una orden abierta (`cancel_pos_order`) | ✔ (En curso) | ✔ (En curso) | ✔ (En curso) | ✘ | Si `status == "Facturada"` o existe `sales_invoice`, el servidor **rechaza la cancelación**. |
| **18** | **Cuentas y POS (`Restaurant Order`)** | Eliminar físicamente un registro de `Restaurant Order` en base de datos | ✔ | ✔ | ✘ | ✘ | `Restaurant User` tiene `delete: 0` en `restaurant_order.json`. |
| **19** | **Cocina KDS (`Restaurant Preparation Display` / `Stage`)** | Crear o reordenar pantallas de cocina y etapas de preparación (`save_display`, `save_stage`) | ✔ (Todas) | ✔ (Su sucursal) | ✘ | ✘ | Requiere permisos de escritura/creación en `Restaurant Preparation Display` y `Stage`; `ensure_default_display` exige `frappe.only_for("System Manager")`. |
| **20** | **Cocina KDS (`restaurant_kds`)** | Ver comandas en pantalla KDS, marcar platillos listos y avanzar o retirar tickets (`toggle_item`, `dismiss_ticket`) | ✔ (Todas) | ✔ (Su sucursal) | ✔ (Su sucursal) | ✘ | Verifica `_require_pos_user()` y `frappe.has_permission("Restaurant Order", "write", order)` antes de mutar cualquier estado de preparación. |

---

## 5. Reglas de propiedad del dato e invariantes de servidor

Además del rol del usuario, el servidor aplica cuatro reglas de **propiedad del dato** que ningún parámetro del navegador puede saltar:

### 5.1. Aislamiento por sucursal (`Branch` via `User Permission`)
Cuando un usuario (`Restaurant Manager` o `Restaurant User`) tiene asignado un registro de `User Permission` sobre una sucursal específica (por ejemplo, `Branch = Sucursal Centro`), el motor de permisos de Frappe y los controladores del módulo (`location.py`, `commands.py`, `table_management.py`) filtran todas las consultas y validan cada escritura:
- Un gerente de **Sucursal Centro** no puede ver, editar ni crear áreas, mesas o estaciones de comanda en **Sucursal Norte**.
- Si intenta enviar por API el identificador de un registro de otra sucursal (cambiando el ID en la petición o URL), el servidor responde con `frappe.PermissionError`.

### 5.2. Propiedad de autoría y sesión (`owner` y `cashier`)
- Al crear o modificar registros mediante las APIs del módulo (`save_location`, `save_command`, `save_pos_order`), el servidor ignora campos protegidos enviados por el cliente como `owner`, `docstatus` o `flags={"ignore_permissions": True}`.
- El campo `cashier` de `Restaurant Order` y el turno `POS Opening Shift` se obtienen en el servidor a partir de `frappe.session.user`.

### 5.3. Integridad del enrutamiento y precios en servidor
- En `validate_order()` (`restaurant/pos.py`), el servidor consulta directamente en MariaDB el `item_group`, la estación de comanda (`Restaurant Command`) y la tasa de impuesto ISV (`15%`, `18%` o `Exento`), recalculando subtotales, impuestos y total general. Si un cliente manipula en el navegador el grupo de producto, la estación de cocina o el estado KDS de una línea ya enviada, el servidor descarta el valor falsificado y conserva el dato real de la base de datos.

### 5.4. Inmutabilidad de cuentas facturadas o canceladas
- En `order_operations.py` (`_check_open_order`) y `pos.py` (`cancel_pos_order`), toda cuenta que tenga `status != "En curso"` o que ya posea un enlace a `sales_invoice` (`Sales Invoice` emitida bajo normativa SAR) queda bloqueada en el servidor contra edición, división, transferencia, fusión o cancelación desde el POS.

---

## 6. Verificación automatizada de permisos en el repositorio

Las reglas de esta matriz están respaldadas por pruebas automatizadas ejecutadas sobre MariaDB en la suite del módulo:

| Archivo de prueba | Reglas de autorización y propiedad verificadas en servidor |
| :--- | :--- |
| [`test_restaurant_area.py`](../restaurant/restaurant/doctype/restaurant_area/test_restaurant_area.py) | Rechazo a `Guest` (`test_guest_cannot_create_or_read`), bloqueo de escalación por payload (`test_payload_cannot_escalate_permissions`), cumplimiento de propiedad por sucursal (`test_branch_user_permission_is_enforced`), menor privilegio `select` en `Employee` y bloqueo de escritura a rol de solo lectura (`test_read_only_user_can_open_list_but_not_create`). |
| [`test_restaurant_area_list.py`](../restaurant/restaurant/doctype/restaurant_area/test_restaurant_area_list.py) | Paginación respetando permisos de sucursal (`test_search_and_paging_respect_branch_user_permission`), rechazo a `Guest` y prevención de inyección SQL en búsquedas. |
| [`test_restaurant_command.py`](../restaurant/restaurant/doctype/restaurant_command/test_restaurant_command.py) | Aislamiento entre sucursales para `Restaurant Manager` (`test_manager_branch_permission_limits_read_create_and_edit`), rechazo de suplantación de `owner="Guest"` o cambio de `doctype` (`test_payload_cannot_change_document_type_or_protected_fields`) y bloqueo total a `Guest`. |
| [`test_pos_startup.py`](../restaurant/tests/test_pos_startup.py) | Guardias de acceso `_require_pos_user()` contra `Guest` incluso con roles simulados (`test_guest_guard_rejects_access_even_with_a_mocked_operational_role`), rechazo a usuarios autenticados sin rol de restaurante (`test_authenticated_user_without_page_roles_is_rejected`) y verificación de matriz de menor privilegio en `Restaurant Order` (`test_role_matrix_enforces_least_privilege_on_restaurant_order`). |
| [`test_kds.py`](../restaurant/tests/test_kds.py) | Verificación de permiso `write` en `Restaurant Order` antes de permitir cambios en KDS (`test_order_write_permission_is_required_before_kitchen_mutation`) e inmunidad ante falsificación de estado KDS o estación de cocina desde el cliente (`test_pos_save_preserves_sent_row_identity_and_ignores_forged_kitchen_state`). |
| [`test_order_operations.py`](../restaurant/tests/test_order_operations.py) | Bloqueo en servidor de división, transferencia o fusión sobre cuentas facturadas o canceladas (`test_billed_and_cancelled_accounts_cannot_be_split_or_transferred`, `test_invoice_link_is_rejected_even_if_account_status_still_says_open`). |

> **Nota sobre credenciales de demostración:** Siguiendo las buenas prácticas de seguridad del Módulo 4, las credenciales de las cuentas de demostración por rol para el entorno `https://leaf-dev.hsjddhn.com/#login` **nunca** se almacenan ni publican en este repositorio; se comparten exclusivamente con el docente a través del canal privado del curso.
