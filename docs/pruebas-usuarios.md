# Pruebas con usuarios reales — Semana 5 (MVP)

**Proyecto:** Módulo Restaurante para LEAF ERP v14  
**Empresa receptora:** Grintsys  
**Entorno evaluado (HTTPS):** `https://leaf-dev.hsjddhn.com/#login`  
**Hipótesis evaluadas:** `H1` (coordinación operativa salón–cocina–caja) y `H2` (integración sobre el motor nativo de ERPNext v14), definidas en [`docs/vision.md`](vision.md).

---

## 1. Objetivo de la prueba

Comprobar si usuarios operando con roles reales de restaurante (**Mesero** y **Cajero**, más **Supervisor** para autorizaciones) pueden completar el ciclo diario sin asistencia técnica ni permisos de administrador: abrir turno, tomar cuentas en mesa, enviar comandas a cocina (KDS), imprimir pre-cuenta, aplicar descuentos permitidos, solicitar cancelaciones autorizadas y cerrar el arqueo de caja.

---

## 2. Guion de prueba aplicado

| Paso | Rol participante | Tarea solicitada | Criterio de éxito esperado |
| :-: | :--- | :--- | :--- |
| **1** | Mesero / Cajero | Iniciar sesión con su usuario operativo y navegar al módulo **Restaurante**. | Acceso directo al Workspace *Restaurante* sin ver módulos administrativos ajenos (Contabilidad, Build, Integraciones). |
| **2** | Cajero | Abrir turno de caja (`POS Opening Shift`) y consultar cuentas creadas por meseros. | El cajero visualiza las cuentas en curso de los meseros para poder cobrarlas. |
| **3** | Mesero | Seleccionar mesa, agregar platillos con opciones/notas y enviar comanda a cocina. | La orden aparece en Cocina KDS (`restaurant-kds`) y la mesa pasa a estado *Ocupada*. |
| **4** | Mesero | Generar la **Pre-cuenta** para el cliente desde el modal de acciones. | Puede imprimir o mostrar la pre-cuenta sin tener acceso al botón *Pasar a Facturar*. |
| **5** | Cajero | Aplicar un descuento en una línea o en el total y emitir el cobro/factura. | El descuento se aplica dentro de la configuración habilitada del POS y se registra la `Sales Invoice`. |
| **6** | Cajero / Mesero | Intentar cancelar una orden o eliminar un platillo enviado a cocina. | El sistema bloquea la acción directa y exige PIN de un **Supervisor** autorizado, registrando el motivo en bitácora. |
| **7** | Cajero | Consultar **Cocina KDS**, **Comandas** y registrar el **Arqueo de Caja**. | Acceso limpio sin alertas de permisos faltantes y cálculo esperado vs. contado correcto. |

---

## 3. Hallazgos registrados y severidad

| ID | Severidad | Hallazgo observado durante las pruebas | Causa raíz identificada | Acción aplicada |
| :-: | :---: | :--- | :--- | :--- |
| **H-01** | **Alta** | El usuario `cajero.prueba` no veía las cuentas abiertas por los meseros en el POS. | La configuración de perfiles y visibilidad compartida de cuentas abiertas no estaba alineada entre roles de salón y caja. | Se ajustaron los perfiles de módulo y visibilidad operativa para que el cajero consulte y cobre cuentas abiertas por meseros. |
| **H-02** | **Alta** | Al abrir **Cocina KDS**, **Comandas** o **Reportes** como cajero aparecían mensajes de *"No permitido / sin acceso a este documento"*. | Faltaban permisos `read`/`select` en `Restaurant Preparation Display`, `Restaurant Command` y `Custom Role` de reportes para `Restaurant Cashier`, además del `Module Profile` restringido. | Se configuraron los `Module Profile` (`Mesero (Salón)`, `Cajero (Completo)`, `Cajero (Facturación Directa)`) y la matriz de permisos en `setup.py`. |
| **H-03** | **Alta** | El cajero no tenía habilitada la opción de aplicar descuentos por línea o globales en el POS. | `allow_line_discount` y `allow_global_discount` en `Restaurant Settings` y `allow_discount_change` en `POS Profile` estaban desactivados. | Se habilitaron en configuración y se restringió el botón `%` del teclado numérico para que solo lo use un rol con permiso de facturación (`canInvoice()`). |
| **H-04** | **Alta** | En pruebas de seguridad sobre API, un payload manipulado podía enviar precios/tasas de impuesto propios o invocar endpoints de configuración. | `validate_order` aceptaba `base_rate`/`tax_rate` del cliente y varios endpoints usaban solo `_require_pos_user()`. | Se forzó el recálculo de precios, opciones e ISV desde base de datos en `validate_order`, se restringieron endpoints administrativos a `Restaurant Manager` y se agregó `FOR UPDATE` en Gift Cards. |
| **H-05** | **Media** | El mesero no podía abrir la **Pre-cuenta** porque el botón de acciones estaba oculto para su rol. | `openActionsModal` estaba bloqueado para roles sin permiso de facturación. | Se habilitó la pre-cuenta para meseros manteniendo oculto el botón *Pasar a Facturar*. |
| **H-06** | **Baja** | El loader de transición entre pantallas mostraba texto técnico sobre el ícono animado. | Estilos y plantilla de carga en `restaurant_theme.css` / `restaurant_pos.js`. | Se dejó únicamente el logotipo animado centrado (`leaf.gif`) de forma limpia. |

---

## 4. Decisión sobre las hipótesis

- **Hipótesis `H1` (Necesidad operativa de coordinar salón, cocina y caja):** **VALIDADA CON ITERACIÓN.**  
  La operación de extremo a extremo funcionó con los usuarios de prueba una vez corregidos los hallazgos `H-01` a `H-05`. Se confirma que el restaurante necesita separación estricta entre **Mesero**, **Cajero** y **Supervisor** mediante `Module Profile` y autorización por PIN en servidor, no solo ocultando botones en pantalla.
- **Hipótesis `H2` (Integración sobre el motor nativo de LEAF ERP / ERPNext v14):** **VALIDADA PARCIALMENTE (condicionada para salida a producción).**  
  La facturación con `Sales Invoice`, turnos de caja (`POS Opening Shift`), métodos de pago y cálculo de ISV operan correctamente sobre ERPNext. Sin embargo, para liberar el sistema en producción real queda pendiente:
  1. Definir con Grintsys la descarga automática de inventario y explosión de recetas (`update_stock`) al facturar.
  2. Cargar los rangos y documentos **CAI** reales de producción antes de desactivar el respaldo de demostración.
