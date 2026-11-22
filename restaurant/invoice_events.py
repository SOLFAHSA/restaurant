"""Synchronize restaurant order links with the native Sales Invoice lifecycle."""

import frappe


def reopen_order_after_invoice_cancel(invoice, method=None):
    """Reopen the matching account after ERPNext reverses its invoice."""
    order_name = invoice.get("restaurant_order")
    if not order_name:
        return

    order = frappe.db.get_value(
        "Restaurant Order", order_name, ["company", "sales_invoice", "status"],
        as_dict=True, for_update=True,
    )
    if not order or order.company != invoice.company or order.sales_invoice != invoice.name:
        return

    from restaurant.kds import publish_kds_realtime_update
    from restaurant.pos import sync_table_status_for_order

    updates = {"sales_invoice": None, "cai": None, "due_date_cai": None}
    if order.status == "Facturada":
        updates["status"] = "En curso"
    frappe.db.set_value("Restaurant Order", order_name, updates)
    reopened = frappe.get_doc("Restaurant Order", order_name)
    sync_table_status_for_order(reopened)
    publish_kds_realtime_update(reopened, method)

