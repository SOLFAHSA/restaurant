"""Checkout discount limits and supervisor approval."""

import frappe
from frappe import _
from frappe.utils import cint, cstr, flt

from restaurant.pos_auth import is_supervisor, log_restaurant_audit
from restaurant.pos_context import _authorize_sensitive_operation


class DiscountApprovalRequired(frappe.PermissionError):
    pass


def _approve_checkout_discounts(invoice, order, profile, supervisor_user=None, supervisor_pin=None, reason=""):
    """Apply the POS Profile and Item discount limits before issuing an invoice."""
    profile_limit = flt(profile.get("posa_max_discount_allowed"))
    discount_base = flt(invoice.grand_total) + flt(invoice.discount_amount)
    global_pct = (100 * flt(invoice.discount_amount) / discount_base) if discount_base > 0 else 0
    item_codes = {row.item_code for row in order.items if not cint(row.is_cancelled)}
    item_limits = {
        row.name: flt(row.max_discount)
        for row in frappe.get_all("Item", filters={"name": ["in", list(item_codes)]},
                                   fields=["name", "max_discount"])
    }
    exceeds_limit = bool(profile_limit > 0 and flt(global_pct, 4) > profile_limit)
    for row in order.items:
        if cint(row.is_cancelled) or row.kds_status == "Cancelado":
            continue
        line_pct = flt(row.discount_percentage)
        combined_pct = flt(line_pct + (100 - line_pct) * global_pct / 100, 4)
        item_limit = item_limits.get(row.item_code, 0)
        if item_limit > 0 and combined_pct > item_limit:
            frappe.throw(_("El descuento de {0} supera el máximo configurado de {1}%.").format(
                row.item_name or row.item_code, item_limit,
            ))
        if profile_limit > 0 and combined_pct > profile_limit:
            exceeds_limit = True

    if not exceeds_limit:
        return
    if not cstr(reason).strip() or (not is_supervisor() and not supervisor_pin):
        frappe.throw(_("El descuento supera el límite configurado. Solicita autorización de un supervisor e indica el motivo."),
                     DiscountApprovalRequired)
    approval = _authorize_sensitive_operation(
        "Descuento sobre el límite", order.name, supervisor_user, supervisor_pin, reason,
    )
    log_restaurant_audit(
        "Descuento sobre el límite", _("Descuento autorizado para facturar la orden."),
        order_name=order.name, supervisor_user=approval["supervisor"], reason=approval["reason"],
    )
