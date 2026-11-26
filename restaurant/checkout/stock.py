"""Stock checks before submitting a restaurant Sales Invoice."""

import frappe
from frappe import _
from frappe.utils import flt


def _invoice_has_stock_items(items):
    return bool(frappe.db.exists("Item", {
        "name": ["in", [item.get("item_code") for item in items]],
        "is_stock_item": 1,
    }))


def validate_restaurant_invoice_stock(doc, method=None):
    """Validate the warehouse and lock stock when creating or submitting a Restaurant sale."""
    if not doc.get("restaurant_order") or doc.is_return:
        return

    previous_invoice = doc.get_doc_before_save()
    if not doc.update_stock:
        if previous_invoice and previous_invoice.update_stock:
            frappe.throw(_("No se puede desactivar la actualización de inventario de esta factura de Restaurante."))
        if doc.docstatus == 1 and _invoice_has_stock_items(doc.items):
            frappe.throw(_("Activa la actualización de inventario antes de enviar esta factura de Restaurante."))
        return

    warehouse = doc.set_warehouse
    if previous_invoice:
        warehouse = previous_invoice.set_warehouse or frappe.db.get_value(
            "POS Profile", previous_invoice.pos_profile or doc.pos_profile or "", "warehouse",
        )
    if not warehouse:
        frappe.throw(_("Configura un almacén en el perfil POS de esta factura de Restaurante."))
    if warehouse != doc.set_warehouse:
        frappe.throw(_("No se puede cambiar el almacén de la factura de Restaurante."))

    quantities = {}
    for row in doc.get_item_list():
        if row.qty <= 0 or not frappe.get_cached_value("Item", row.item_code, "is_stock_item"):
            continue
        if warehouse and row.warehouse != warehouse:
            frappe.throw(_("El producto {0} debe usar el almacén {1} de la factura de Restaurante.").format(
                row.item_code, warehouse,
            ))
        key = (row.item_code, row.warehouse)
        quantities[key] = quantities.get(key, 0) + row.qty

    if not doc.is_new() and doc.docstatus != 1:
        return

    precision = doc.precision("stock_qty", "items")
    # Lock in a stable order and let ERPNext post the movements in the same transaction.
    for (item_code, warehouse), requested in sorted(quantities.items()):
        available = flt(frappe.db.get_value(
            "Bin", {"item_code": item_code, "warehouse": warehouse}, "actual_qty", for_update=True,
        ))
        if flt(available - requested, precision) < 0:
            frappe.throw(_("Existencia insuficiente para {0} en el almacén {1}. Disponible: {2}. Requerido: {3}.").format(
                item_code, warehouse, flt(available, precision), flt(requested, precision),
            ))
