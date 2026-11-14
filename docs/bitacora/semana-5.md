# Bitácora de actividades — Semana 5

**Proyecto:** Desarrollo del módulo Restaurante para Leaf ERP

**Empresa receptora:** Grintsys

**Institución:** CEUTEC

**Asignatura:** Proyecto de Graduación Fase 1

**Etapa:** Semana 5 — MVP con usuarios reales, perfiles operativos, arqueo de caja y endurecimiento en servidor

**Tecnologías:** Frappe Framework v14, ERPNext v14, Python 3.11, JavaScript, MariaDB y Redis

**Entorno en línea (HTTPS):** `https://leaf-dev.hsjddhn.com/#login`

## 1. Introducción

Durante la quinta semana de práctica profesional en Grintsys, el enfoque pasó de la construcción de funcionalidades aisladas a la **validación operativa con usuarios de prueba reales** (`Mesero` y `Cajero`), el refinamiento de la experiencia diaria en el Punto de Venta y el **endurecimiento de seguridad, concurrencia y permisos en el servidor**.

A partir de las sesiones de prueba documentadas en [`docs/pruebas-usuarios.md`](../pruebas-usuarios.md), se detectaron y corrigieron fricciones reales de operación (visibilidad de cuentas entre meseros y cajeros, acceso limpio a Cocina KDS y Comandas, habilitación de pre-cuenta para meseros, descuentos para cajeros y cancelación protegida por PIN de supervisor) junto con el cierre completo de brechas de validación en el backend.

## 2. Objetivo de la semana

Ejecutar pruebas del MVP con perfiles operativos reales, resolver los hallazgos de usabilidad y permisos sin exponer módulos administrativos ajenos, completar el flujo de arqueo de caja y tarjetas de regalo, y verificar la estabilidad del módulo mediante la suite completa de pruebas automatizadas.

## 3. Actividades realizadas

### 3.1. Pruebas con usuarios reales y ajuste de perfiles (`Module Profile` y roles)

- Se configuraron perfiles de módulo específicos (`Mesero (Salón)`, `Cajero (Completo)` y `Cajero (Facturación Directa)`) para que el personal operativo ingrese únicamente al Workspace **Restaurante**, bloqueando el acceso a módulos como Contabilidad, Build, Calidad o Integraciones.
- Se ajustaron los permisos de `Restaurant Cashier` en [`restaurant/setup.py`](../../restaurant/setup.py) y [`restaurant_commands.json`](../../restaurant/restaurant/page/restaurant_commands/restaurant_commands.json) para eliminar alertas falsas de permisos al abrir **Cocina KDS**, **Comandas** y **Reportes**.
- Se habilitó la emisión de **Pre-cuenta** para meseros manteniendo el cobro y la facturación SAR restringidos exclusivamente a cajeros y supervisores.

### 3.2. Descuentos en POS, autorización por PIN y bitácora de auditoría

- Se habilitaron los descuentos por línea y globales en `Restaurant Settings` y en el `POS Profile`, restringiendo el uso del teclado de descuento (`%`) a usuarios con capacidad de facturación (`canInvoice()`).
- Se consolidó la verificación por PIN de supervisor (`pos_auth.py`) para cancelar órdenes completas o líneas ya enviadas a cocina, exigiendo motivo obligatorio y registrando usuario, supervisor, fecha, estado previo/posterior en `Restaurant Audit Log`.
- Se añadió limitación de intentos fallidos (`rate limiting` en `frappe.cache()`) tanto para PIN de supervisor como para PIN de desbloqueo de cuentas de mesero.

### 3.3. Arqueo de caja, tarjetas de regalo y endurecimiento en servidor

- Se integró el flujo de **Arqueo de Caja (`Restaurant Cash Count`)** con denominaciones, movimientos de caja (`Ingreso`/`Retiro`), validación de propiedad de turno en `create_cash_movement` y formatos de impresión Carta y Ticket 80mm, restringiendo `create`/`write`/`submit` a roles de caja y gerencia.
- Se reforzó [`restaurant/pos.py`](../../restaurant/pos.py) (`validate_order`) para recalcular en servidor precios base (`Item Price` / `Item.standard_rate`), adicionales (`Restaurant Dish Option`) e ISV (`Item Tax`), evitando manipulación desde el cliente.
- Se agregaron bloqueos transaccionales `SELECT ... FOR UPDATE` en la redención de `Restaurant Gift Card` y en la numeración secuencial de órdenes, además de filtrado por sucursal (`Branch`) en `get_pos_bootstrap` y `get_emitted_commands`.

## 4. Pruebas ejecutadas y verificación

- Se ejecutó la suite completa de pruebas automatizadas del módulo (`bench --site development run-tests --app restaurant --skip-test-records`) tras los ajustes finales: **177 pruebas ejecutadas, 0 fallos y 0 errores** (`OK`, con 2 `expected failures` documentados).
- Se validaron manualmente en navegador los flujos de **Cajero de Prueba** y **Mesero de Prueba** sobre el entorno conectado al backend de Frappe v14.

## 5. Dificultades identificadas

- Equilibrar el aislamiento estricto de `Module Profile` con los permisos internos que requieren las pantallas personalizadas (`restaurant-kds`, `restaurant-commands`) y los enlaces a DocTypes estándar (`Employee`, `Branch`, `Item`).
- Asegurar que las pruebas de operaciones atómicas (`split_account`, `transfer_account`) convivan con la regla que impide a un usuario editar o reducir cantidades de platillos ya enviados a cocina sin autorización de supervisor.

## 6. Aprendizajes de la semana

Probar el sistema con perfiles reales (`Mesero` y `Cajero`) evidenció fallos que no aparecen al trabajar únicamente como `Administrator`: desde botones ocultos por exceso de restricción hasta permisos indirectos faltantes en pantallas de cocina y reportes. Además, quedó claro que toda regla crítica (precios, impuestos, descuentos, PIN y concurrencia de saldo) debe aplicarse y verificarse en el servidor.

## 7. Próximas actividades

- Definir con el equipo de Grintsys la estrategia contable/operativa para la descarga automática de inventario y recetas (`update_stock`) al emitir facturas.
- Cargar la configuración **CAI** productiva y ejecutar pruebas de carga multi-sucursal en un entorno staging previo a producción.

## 8. Conclusión

Al cierre de la semana 5, el MVP del módulo Restaurante cuenta con un flujo operativo probado con perfiles reales, documentación de hallazgos en [`docs/pruebas-usuarios.md`](../pruebas-usuarios.md), controles de seguridad y concurrencia reforzados en servidor, y una suite de **177 pruebas automatizadas** aprobada, publicado bajo la etiqueta `semana-5`.
