"""Synchronize restaurant order links with the native Sales Invoice lifecycle."""

import frappe


def reopen_order_after_invoice_cancel(invoice, method=None):
    """Reopen the matching account after ERPNext reverses its invoice."""
    order_name = invoice.get("restaurant_order")
    if not order_name:
        return

    has_tip_fields = frappe.get_meta("Restaurant Order").has_field("tip_journal_entry")
    fields = ["company", "sales_invoice", "status"] + (["tip_journal_entry"] if has_tip_fields else [])
    order = frappe.db.get_value("Restaurant Order", order_name, fields, as_dict=True, for_update=True)
    if not order or order.company != invoice.company or order.sales_invoice != invoice.name:
        return

    from restaurant.checkout.tips import cancel_tip_journal_entry
    from restaurant.kds import publish_kds_realtime_update
    from restaurant.orders.validation import sync_table_status_for_order

    updates = {"sales_invoice": None, "cai": None, "due_date_cai": None}
    if has_tip_fields:
        # Reverse the staff tip liability together with the invoice: no orphan balances remain.
        cancel_tip_journal_entry(order.tip_journal_entry)
        updates.update({"tip_journal_entry": None, "tip_mode_of_payment": None})
    if order.status == "Facturada":
        updates["status"] = "En curso"
    frappe.db.set_value("Restaurant Order", order_name, updates)
    reopened = frappe.get_doc("Restaurant Order", order_name)
    _restore_order_totals(reopened)
    sync_table_status_for_order(reopened)
    publish_kds_realtime_update(reopened, method)


def _restore_order_totals(order):
    """Drop the cancelled invoice's discounted totals by recomputing them from the order lines."""
    from restaurant.orders.validation import validate_order

    try:
        validate_order(order)
    except frappe.ValidationError:
        # Never block the native cancellation; the next save of the order reports the problem.
        frappe.clear_messages()
        return
    order.db_update()
