"""Order changes: transfer, split, item cancellation, clearing, cancelling and unlocking."""

import frappe
from frappe import _
from frappe.utils import cint, cstr, flt, now_datetime

from restaurant.orders.serialization import _get_areas_with_live_tables, _serialize_order
from restaurant.pos_auth import (
    employee_has_pin,
    get_linked_employee_for_user,
    is_supervisor,
    log_restaurant_audit,
    mark_order_unlocked_for_session,
    verify_employee_pin,
)
from restaurant.pos_context import (
    _authorize_sensitive_operation,
    _check_order_company,
    _clear_pin_failures,
    _enforce_pin_rate_limit,
    _record_pin_failure,
    _require_pos_user,
)


@frappe.whitelist(methods=["POST"])
def transfer_order_table(order_name, target_table=None, target_order=None, expected_modified=None,
                         target_modified=None, split_items=None, new_order_name=None):
    """Transfer an open order to another table, merge into target order, or create a new order."""
    from restaurant.order_operations import transfer_account
    return transfer_account(
        order_name,
        target_table=target_table,
        target_order=target_order,
        expected_modified=expected_modified,
        target_modified=target_modified,
        split_items=split_items,
        new_order_name=new_order_name,
    )


@frappe.whitelist(methods=["POST"])
def split_order(order_name, split_items, new_order_name=None, expected_modified=None):
    """Split selected quantities from an open Restaurant Order into a second open account."""
    from restaurant.order_operations import split_account
    return split_account(
        order_name,
        split_items,
        new_order_name=new_order_name,
        expected_modified=expected_modified,
    )


@frappe.whitelist()
def get_order_operation_context(order_name):
    """Read permitted open destinations and split feasibility."""
    from restaurant.order_operations import get_order_operation_context as _get_ctx
    return _get_ctx(order_name)


@frappe.whitelist(methods=["POST"])
def preview_split_order(order_name, split_items, expected_modified=None):
    """Calculate the financial impact of a proposed account split."""
    from restaurant.order_operations import preview_split
    return preview_split(order_name, split_items, expected_modified=expected_modified)


def _sync_kds_after_order_change(doc):
    """Synchronize KDS tickets after an item or order mutation.

    The realtime notice is already published by the order's on_update hook after commit.
    """
    try:
        from restaurant.kds import _sync_legacy_status
        _sync_legacy_status(doc)
    except Exception:
        frappe.log_error(frappe.get_traceback(), "KDS Sync After Order Change")


@frappe.whitelist(methods=["POST"])
def cancel_sent_order_item(
    order_name,
    item_row_name,
    cancel_qty=None,
    supervisor_user=None,
    supervisor_pin=None,
    reason="",
    expected_modified=None,
):
    """Cancel a full or partial quantity of a sent-to-kitchen item with supervisor authorization."""
    _require_pos_user()
    if not order_name or not frappe.db.exists("Restaurant Order", order_name):
        frappe.throw(_("La cuenta u orden no existe."), frappe.DoesNotExistError)

    frappe.db.sql("SELECT name FROM `tabRestaurant Order` WHERE name=%s FOR UPDATE", order_name)
    doc = frappe.get_doc("Restaurant Order", order_name)
    _check_order_company(doc)
    doc.check_permission("write")

    if doc.status == "Facturada":
        frappe.throw(_("Esta cuenta ya fue facturada y no puede modificarse. Realiza una nota de crédito o devolución formal."))
    if doc.status == "Cancelada":
        frappe.throw(_("Esta cuenta ya se encuentra cancelada."))
    if expected_modified and cstr(doc.modified) != cstr(expected_modified).strip():
        frappe.throw(_("Esta orden fue modificada recientemente por otro usuario. Recarga la cuenta antes de cancelar."))

    target_row = next((r for r in (doc.items or []) if r.name == item_row_name), None)
    if not target_row:
        frappe.throw(_("El producto seleccionado no pertenece a esta orden."), frappe.DoesNotExistError)

    prev_kds = cstr(getattr(target_row, "kds_status", "") or "Pendiente")
    if cint(getattr(target_row, "is_cancelled", 0)) or prev_kds == "Cancelado":
        frappe.throw(_("Este producto ya fue cancelado anteriormente."))
    if prev_kds == "Pendiente":
        frappe.throw(_("Este producto aún está en borrador y puede retirarse directamente sin autorización."))

    req_qty = flt(target_row.qty)
    qty_to_cancel = req_qty if cancel_qty in (None, "") else flt(cancel_qty)
    if qty_to_cancel <= 0 or qty_to_cancel > req_qty + 0.001:
        frappe.throw(_("La cantidad a cancelar debe ser mayor que 0 y no mayor a {0}.").format(req_qty))

    auth = _authorize_sensitive_operation(
        "Cancelar producto enviado a cocina",
        doc.name,
        supervisor_user=supervisor_user,
        supervisor_pin=supervisor_pin,
        reason=reason,
        require_reason=True,
    )
    sup_user = auth["supervisor"]
    clean_reason = auth["reason"]
    cancel_ts = now_datetime()

    frappe.flags.in_restaurant_supervisor_cancel = True
    try:
        if qty_to_cancel < req_qty - 0.001:
            target_row.qty = flt(req_qty - qty_to_cancel, 3)
            doc.append("items", {
                "item_code": target_row.item_code,
                "item_name": target_row.item_name,
                "item_group": target_row.item_group,
                "qty": qty_to_cancel,
                "uom": target_row.uom,
                "base_rate": 0.0,
                "options_rate": 0.0,
                "discount_percentage": 0.0,
                "rate": 0.0,
                "amount": 0.0,
                "tax_rate": target_row.tax_rate,
                "options_summary": target_row.options_summary,
                "selected_options_json": target_row.selected_options_json,
                "note": target_row.note,
                "command_station": target_row.command_station,
                "kds_status": "Cancelado",
                "is_cancelled": 1,
                "cancelled_qty": qty_to_cancel,
                "cancellation_reason": clean_reason,
                "cancelled_by": frappe.session.user,
                "cancelled_by_supervisor": sup_user,
                "cancelled_at": cancel_ts,
            })
        else:
            target_row.is_cancelled = 1
            target_row.cancelled_qty = req_qty
            target_row.kds_status = "Cancelado"
            target_row.cancellation_reason = clean_reason
            target_row.cancelled_by = frappe.session.user
            target_row.cancelled_by_supervisor = sup_user
            target_row.cancelled_at = cancel_ts
            target_row.amount = 0.0

        doc.save()
    finally:
        frappe.flags.in_restaurant_supervisor_cancel = False

    _sync_kds_after_order_change(doc)
    log_restaurant_audit(
        "Cancelar producto enviado a cocina",
        f"Producto: {target_row.item_name or target_row.item_code} (Cant: {qty_to_cancel}) | Motivo: {clean_reason}",
        order_name=doc.name,
        supervisor_user=sup_user,
        result="Autorizado",
        item_code=target_row.item_code,
        item_name=target_row.item_name,
        affected_qty=qty_to_cancel,
        reason=clean_reason,
        previous_state=prev_kds,
        resulting_state="Cancelado",
    )
    return {
        "order": _serialize_order(doc),
        "areas": _get_areas_with_live_tables(),
    }


@frappe.whitelist(methods=["POST"])
def clear_pos_order(
    order_name=None,
    supervisor_user=None,
    supervisor_pin=None,
    reason="",
    expected_modified=None,
):
    """Clear draft items freely or cancel all sent-to-kitchen items with supervisor authorization."""
    _require_pos_user()
    if not order_name:
        return {"cleared": True}
    if not frappe.db.exists("Restaurant Order", order_name):
        frappe.throw(_("La cuenta u orden no existe."), frappe.DoesNotExistError)

    frappe.db.sql("SELECT name FROM `tabRestaurant Order` WHERE name=%s FOR UPDATE", order_name)
    doc = frappe.get_doc("Restaurant Order", order_name)
    _check_order_company(doc)
    doc.check_permission("write")
    if doc.status == "Facturada":
        frappe.throw(_("No puedes vaciar una cuenta que ya fue facturada."))
    if doc.status == "Cancelada":
        frappe.throw(_("Esta cuenta ya está cancelada."))
    if expected_modified and cstr(doc.modified) != cstr(expected_modified).strip():
        frappe.throw(_("Esta orden fue modificada recientemente por otro usuario. Recarga la cuenta antes de vaciarla."))

    sent_active = [
        r for r in (doc.items or [])
        if cstr(getattr(r, "kds_status", "") or "Pendiente") not in ("", "Pendiente", "Cancelado")
        and not cint(getattr(r, "is_cancelled", 0))
    ]
    if sent_active:
        auth = _authorize_sensitive_operation(
            "Vaciar orden confirmada",
            doc.name,
            supervisor_user=supervisor_user,
            supervisor_pin=supervisor_pin,
            reason=reason,
            require_reason=True,
        )
        sup_user = auth["supervisor"]
        clean_reason = auth["reason"]
        cancel_ts = now_datetime()

        frappe.flags.in_restaurant_supervisor_cancel = True
        try:
            kept_rows = []
            for r in (doc.items or []):
                kds = cstr(getattr(r, "kds_status", "") or "Pendiente")
                if cint(getattr(r, "is_cancelled", 0)) or kds == "Cancelado":
                    kept_rows.append(r)
                elif kds not in ("", "Pendiente"):
                    r.is_cancelled = 1
                    r.cancelled_qty = flt(r.qty)
                    r.kds_status = "Cancelado"
                    r.cancellation_reason = clean_reason
                    r.cancelled_by = frappe.session.user
                    r.cancelled_by_supervisor = sup_user
                    r.cancelled_at = cancel_ts
                    r.amount = 0.0
                    kept_rows.append(r)
            doc.set("items", kept_rows)
            doc.tip_percentage = 0
            doc.tip_amount = 0
            doc.save()
        finally:
            frappe.flags.in_restaurant_supervisor_cancel = False

        _sync_kds_after_order_change(doc)
        log_restaurant_audit(
            "Vaciar orden confirmada",
            f"Se cancelaron {len(sent_active)} línea(s) enviadas a cocina | Motivo: {clean_reason}",
            order_name=doc.name,
            supervisor_user=sup_user,
            result="Autorizado",
            affected_qty=sum(flt(r.qty) for r in sent_active),
            reason=clean_reason,
            previous_state=doc.kds_status,
            resulting_state="Vaciada / Cancelado",
        )
    else:
        kept_rows = [
            r for r in (doc.items or [])
            if cint(getattr(r, "is_cancelled", 0)) or cstr(getattr(r, "kds_status", "") or "Pendiente") == "Cancelado"
        ]
        doc.set("items", kept_rows)
        doc.tip_percentage = 0
        doc.tip_amount = 0
        doc.save()

    return {
        "order": _serialize_order(doc),
        "areas": _get_areas_with_live_tables(),
    }


@frappe.whitelist(methods=["POST"])
def cancel_pos_order(order_name, supervisor_user=None, supervisor_pin=None, reason=""):
    """Cancel an unbilled Restaurant Order with supervisor authorization and release its table."""
    _require_pos_user()
    if not order_name or not frappe.db.exists("Restaurant Order", order_name):
        frappe.throw(_("La cuenta u orden no existe."))
    frappe.db.sql("SELECT name FROM `tabRestaurant Order` WHERE name=%s FOR UPDATE", order_name)
    doc = frappe.get_doc("Restaurant Order", order_name)
    _check_order_company(doc)
    doc.check_permission("write")
    if doc.status == "Facturada":
        frappe.throw(_("No puedes cancelar desde el POS una cuenta que ya tiene factura emitida."))
    if doc.status == "Cancelada":
        frappe.throw(_("Esta cuenta ya se encuentra cancelada."))

    prev_status = doc.status
    auth = _authorize_sensitive_operation(
        "Cancelar orden completa",
        doc.name,
        supervisor_user=supervisor_user,
        supervisor_pin=supervisor_pin,
        reason=reason,
        require_reason=True,
    )
    sup_user = auth["supervisor"]
    clean_reason = auth["reason"]
    cancel_ts = now_datetime()

    frappe.flags.in_restaurant_supervisor_cancel = True
    try:
        for r in (doc.items or []):
            kds = cstr(getattr(r, "kds_status", "") or "Pendiente")
            if kds not in ("", "Pendiente", "Cancelado") and not cint(getattr(r, "is_cancelled", 0)):
                r.is_cancelled = 1
                r.cancelled_qty = flt(r.qty)
                r.kds_status = "Cancelado"
                r.cancellation_reason = clean_reason
                r.cancelled_by = frappe.session.user
                r.cancelled_by_supervisor = sup_user
                r.cancelled_at = cancel_ts
                r.amount = 0.0
        doc.status = "Cancelada"
        doc.save()
    finally:
        frappe.flags.in_restaurant_supervisor_cancel = False

    _sync_kds_after_order_change(doc)
    log_restaurant_audit(
        "Cancelar orden completa",
        f"Orden cancelada | Motivo: {clean_reason}",
        order_name=doc.name,
        supervisor_user=sup_user,
        result="Autorizado",
        reason=clean_reason,
        previous_state=prev_status,
        resulting_state="Cancelada",
    )
    return {
        "order": _serialize_order(doc),
        "areas": _get_areas_with_live_tables(),
    }


@frappe.whitelist(methods=["POST"])
def unlock_waiter_order(order_name, pin):
    """Verify the assigned waiter's PIN and unlock the order for the current session."""
    _require_pos_user()
    if not order_name or not frappe.db.exists("Restaurant Order", order_name):
        frappe.throw(_("La cuenta u orden solicitada no existe."), frappe.DoesNotExistError)
    doc = frappe.get_doc("Restaurant Order", order_name)
    _check_order_company(doc)
    doc.check_permission("read")
    if not doc.waiter:
        mark_order_unlocked_for_session(doc.name)
        return {"unlocked": True, "order": _serialize_order(doc)}

    if is_supervisor():
        mark_order_unlocked_for_session(doc.name)
        return {"unlocked": True, "order": _serialize_order(doc)}

    linked_emp = get_linked_employee_for_user()
    if linked_emp:
        if doc.waiter != linked_emp["name"]:
            log_restaurant_audit(
                "Acceso denegado a cuenta de otro mesero",
                f"Usuario {frappe.session.user} ({linked_emp['name']}) intentó abrir la orden de {doc.waiter}",
                order_name=doc.name,
                result="Rechazado",
            )
            frappe.throw(_("Esta cuenta pertenece a otro mesero y no puedes abrirla."), frappe.PermissionError)
        mark_order_unlocked_for_session(doc.name)
        return {"unlocked": True, "order": _serialize_order(doc)}

    if not employee_has_pin(doc.waiter):
        mark_order_unlocked_for_session(doc.name)
        return {"unlocked": True, "order": _serialize_order(doc)}

    pin_cache_key = _enforce_pin_rate_limit(f"waiter:{doc.waiter}")
    if not verify_employee_pin(doc.waiter, pin):
        _record_pin_failure(pin_cache_key)
        log_restaurant_audit(
            "PIN de mesero incorrecto",
            f"Intento fallido de desbloquear cuenta asignada a {doc.waiter_name or doc.waiter}",
            order_name=doc.name,
            result="Rechazado",
        )
        frappe.throw(
            _("Código incorrecto. Solo el mesero asignado ({0}) o un supervisor puede abrir esta cuenta.").format(
                doc.waiter_name or doc.waiter
            ),
            frappe.PermissionError,
        )

    _clear_pin_failures(pin_cache_key)
    mark_order_unlocked_for_session(doc.name)
    return {"unlocked": True, "order": _serialize_order(doc)}
