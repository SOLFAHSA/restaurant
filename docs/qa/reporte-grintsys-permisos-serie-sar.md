# Reporte para Grintsys: un usuario sin rol de administrador no puede emitir la primera factura de una serie SAR nueva

- **Fecha:** 2026-11-19
- **Reportado por:** Manuel Padilla (práctica profesional, módulo Restaurante LEAF)
- **Repositorio afectado:** `Grintsys/erpnext14`, rama `version-14`
- **Archivo:** `erpnext/accounts/doctype/sales_invoice/sales_invoice.py`
- **Severidad propuesta:** Alta. Bloquea la facturación en caja al habilitar una serie fiscal nueva.
- **Estado de evidencia:** VERIFIED (reproducido con pruebas automáticas)

## Resumen

Al emitir la **primera** Sales Invoice de una serie fiscal (`naming_series`) nueva, `before_naming` crea dos registros auxiliares: `Prefix sales for days` y `Daily summary series`. Los crea con `doc.insert()` **sin** `ignore_permissions`. Ambos DocTypes solo permiten crear al rol **System Manager**, así que cualquier otro usuario (cajero, Accounts User, usuario POS) recibe `frappe.exceptions.PermissionError` y **la factura no se emite**.

Las series ya usadas no fallan, porque los registros ya existen y el `insert` no se ejecuta. Por eso el problema queda oculto en sitios con historial y aparece al habilitar una serie nueva.

## Código involucrado

`sales_invoice.py` (líneas 550-575 aprox.):

```python
def before_naming(self):
    if self.amended_from:
        return
    if self.docstatus == 0 or (self.status == "Draft" and not self.cai):
        self.assign_cai()
        self.create_prefix_for_days()
        self.create_daily_summary_series()

def create_prefix_for_days(self):
    prefix = frappe.get_all("Prefix sales for days", ["name_prefix"], filters={"name_prefix": self.naming_series})
    if len(prefix) == 0:
        doc = frappe.new_doc('Prefix sales for days')
        doc.name_prefix = self.naming_series
        doc.insert(ignore_if_duplicate=True)          # <- checks the current user's permissions

def create_daily_summary_series(self):
    ...
    if len(prefix) == 0:
        doc = frappe.new_doc('Daily summary series')
        doc.name_serie = serie
        doc.insert(ignore_if_duplicate=True)          # <- same issue
```

Permisos estándar de ambos DocTypes (`prefix_sales_for_days.json`, `daily_summary_series.json`): solo `System Manager` con `create = 1`.

## Cuándo ocurre en operación real

- Se habilita una **sucursal o punto de emisión nuevo** con su propio prefijo SAR.
- Se registra un **CAI nuevo** con un prefijo que todavía no tiene facturas.
- Se instala un **sitio nuevo** (cliente nuevo de LEAF).

En todos esos casos, si el primer usuario que factura no es administrador, la caja queda bloqueada hasta que un administrador emita una factura con esa serie o cree los registros a mano.

No es exclusivo del módulo Restaurante. Afecta cualquier flujo que cree una Sales Invoice como usuario sin rol System Manager: POS Awesome, Accounts User o integraciones.

## Cómo reproducirlo

1. En un sitio sin registros en `Prefix sales for days` ni `Daily summary series` para la serie `000-099-01-.########`, crear un POS Profile con esa serie y un CAI vigente.
2. Crear un usuario **sin** rol System Manager, con permiso para crear Sales Invoice (por ejemplo, con `ignore_permissions` en el flujo POS o con el rol Accounts User).
3. Emitir una Sales Invoice con esa serie como ese usuario.
4. **Resultado:** `frappe.exceptions.PermissionError` en `create_prefix_for_days` → `Document.insert` → `check_permission`.
5. **Resultado esperado:** la factura se emite y los registros auxiliares se crean automáticamente.

Traza obtenida:

```
restaurant/pos.py, line 3259, in pay_and_invoice_order   -> si.insert(ignore_permissions=True)
frappe/model/naming.py, line 140, in set_new_name
erpnext/accounts/doctype/sales_invoice/sales_invoice.py, line 556, in before_naming
erpnext/accounts/doctype/sales_invoice/sales_invoice.py, line 565, in create_prefix_for_days
frappe/model/document.py, line 207, in check_permission
frappe.exceptions.PermissionError
```

Observa que la factura se inserta con `ignore_permissions=True`, pero esa bandera **no se propaga** a los documentos auxiliares que se crean dentro de `before_naming`.

## Evidencia

- Sitio de pruebas limpio `test_restaurant` (frappe, erpnext Grintsys, posawesome, restaurant).
- Pruebas `test_03b_pure_cashier_can_submit_invoice_via_pos_api` y `test_kds_realtime_event_emitted_on_order_and_ticket_mutations` (módulo `restaurant.tests.test_qa_comprehensive_audit`): **fallan** con `PermissionError`.
- Al crear manualmente, como Administrator, `Prefix sales for days` = `000-099-01-.########` y `Daily summary series` = `000-099`, las dos pruebas **pasan** (`Ran 1 test … OK`). Esto confirma la causa.

## Corrección propuesta (para el fork Grintsys)

Los registros auxiliares son un efecto interno del sistema, no una acción del usuario. Lo correcto es crearlos ignorando los permisos del usuario actual:

```python
doc.insert(ignore_permissions=True, ignore_if_duplicate=True)
```

en `create_prefix_for_days` y en `create_daily_summary_series`.

- **Impacto:** mínimo. No cambia datos existentes ni la numeración fiscal; solo permite crear dos registros de control que el sistema ya crea hoy para administradores.
- **Riesgo de upgrade:** bajo. Es código propio de Grintsys, no del ERPNext original.
- **Requiere validación tributaria local:** no, porque no altera la numeración ni el CAI.

## Mitigación temporal en LEAF Restaurante

Mientras se corrige el fork, la app Restaurante puede otorgar al rol de caja permiso de **lectura y creación** sobre esos dos DocTypes, mediante su matriz de permisos (`restaurant/setup.py`, `ensure_cashier_permissions`, que se aplica en cada `bench migrate`). Es un cambio declarativo (Nivel 2) y reversible, y deja de ser necesario cuando Grintsys publique la corrección.
