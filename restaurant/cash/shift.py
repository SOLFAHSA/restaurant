"""Cash register shift: opening, cash movements, closing preview and closing."""

import frappe
from frappe import _
from frappe.utils import cint, cstr, flt, get_fullname, now_datetime, nowdate

from restaurant.pos_auth import is_supervisor, user_can_invoice
from restaurant.pos_context import (
    _get_active_opening_shift,
    _get_active_user_branch,
    _get_default_pos_profile,
    _require_pos_user,
)


@frappe.whitelist(methods=["POST"])
def open_pos_shift(pos_profile=None, opening_amount=0, balance_details=None, company=None):
    """Open or reuse a native POS Opening Shift for the logged-in cashier."""
    _require_pos_user()
    if not user_can_invoice():
        frappe.throw(
            _("Solo cajeros o supervisores pueden abrir turnos de caja."),
            frappe.PermissionError,
        )
    frappe.db.sql(
        "SELECT name FROM `tabPOS Opening Shift` WHERE user = %s AND docstatus = 1 AND status = 'Open' FOR UPDATE",
        (frappe.session.user,),
    )
    existing = _get_active_opening_shift(frappe.session.user)
    if existing:
        return existing

    if not pos_profile:
        default_prof = _get_default_pos_profile(company)
        pos_profile = default_prof.name if default_prof else None
    if not pos_profile or not frappe.db.exists("POS Profile", pos_profile):
        frappe.throw(_("Selecciona un perfil de Punto de Venta válido para abrir el turno."))

    prof_doc = frappe.get_doc("POS Profile", pos_profile)
    if company and prof_doc.company != company:
        frappe.throw(_("El perfil de Punto de Venta seleccionado no pertenece a la empresa indicada."))

    rows = []
    if balance_details:
        parsed = frappe.parse_json(balance_details) if isinstance(balance_details, str) else balance_details
        if isinstance(parsed, list):
            for entry in parsed:
                if isinstance(entry, dict) and entry.get("mode_of_payment"):
                    raw_amt = entry.get("amount") if entry.get("amount") is not None else entry.get("opening_amount")
                    rows.append({
                        "mode_of_payment": entry["mode_of_payment"],
                        "amount": max(0.0, flt(raw_amt, 2)),
                    })
    if not rows:
        if prof_doc.payments:
            for idx, pay_row in enumerate(prof_doc.payments):
                rows.append({
                    "mode_of_payment": pay_row.mode_of_payment,
                    "amount": max(0.0, flt(opening_amount, 2)) if idx == 0 else 0.0,
                })
        else:
            rows.append({
                "mode_of_payment": "Efectivo",
                "amount": max(0.0, flt(opening_amount, 2)),
            })

    shift_doc = frappe.get_doc({
        "doctype": "POS Opening Shift",
        "period_start_date": now_datetime(),
        "posting_date": nowdate(),
        "user": frappe.session.user,
        "pos_profile": prof_doc.name,
        "company": prof_doc.company,
        "balance_details": rows,
    })
    shift_doc.insert(ignore_permissions=True)
    shift_doc.submit()
    return _get_active_opening_shift(frappe.session.user)


@frappe.whitelist()
def get_shift_cash_movements(pos_opening_shift=None):
    """Return cash in/out movements (POS Awesome 'Retiro de efectivo') for the active shift."""
    _require_pos_user()
    if not pos_opening_shift:
        active = _get_active_opening_shift(frappe.session.user)
        pos_opening_shift = active["name"] if active else None
    if not pos_opening_shift or not frappe.db.exists("DocType", "Retiro de efectivo"):
        return {
            "pos_opening_shift": pos_opening_shift or "",
            "movements": [],
            "total_ingreso": 0.0,
            "total_retiro": 0.0,
            "net_cash_movement": 0.0,
        }

    rows = frappe.get_all(
        "Retiro de efectivo",
        filters={"pos_opening_shift": pos_opening_shift, "docstatus": 1},
        fields=["name", "type_transaction", "amount", "note", "posting_date", "cashier"],
        order_by="creation desc",
        limit_page_length=100,
    )
    total_ingreso = 0.0
    total_retiro = 0.0
    movements = []
    for row in rows:
        amt = flt(row.amount, 2)
        tx_type = cstr(row.type_transaction or "Retiro").strip()
        if tx_type == "Ingreso":
            total_ingreso += amt
        else:
            total_retiro += amt
        movements.append({
            "name": row.name,
            "type_transaction": tx_type,
            "amount": amt,
            "note": row.note or "",
            "posting_date": str(row.posting_date) if row.posting_date else "",
            "cashier": row.cashier or "",
        })

    return {
        "pos_opening_shift": pos_opening_shift,
        "movements": movements,
        "total_ingreso": flt(total_ingreso, 2),
        "total_retiro": flt(total_retiro, 2),
        "net_cash_movement": flt(total_ingreso - total_retiro, 2),
    }


@frappe.whitelist(methods=["POST"])
def create_cash_movement(type_transaction, amount, note="", pos_opening_shift=None):
    """Create and submit a native POS Awesome 'Retiro de efectivo' (Ingreso or Retiro)."""
    _require_pos_user()
    if not user_can_invoice():
        frappe.throw(
            _("Solo cajeros o supervisores pueden registrar entradas o salidas de efectivo."),
            frappe.PermissionError,
        )
    tx_type = cstr(type_transaction or "Retiro").strip()
    if tx_type not in ("Ingreso", "Retiro"):
        frappe.throw(_("El tipo de movimiento debe ser Ingreso o Retiro."))

    amt = flt(amount, 2)
    if amt <= 0:
        frappe.throw(_("El monto de entrada o salida de efectivo debe ser mayor que cero."))

    clean_note = cstr(note or "").strip()
    if not clean_note:
        frappe.throw(_("Ingresa el motivo o descripción del movimiento de efectivo."))

    if not pos_opening_shift:
        active = _get_active_opening_shift(frappe.session.user)
        pos_opening_shift = active["name"] if active else None
    if not pos_opening_shift or not frappe.db.exists("POS Opening Shift", pos_opening_shift):
        frappe.throw(_("Debes tener un turno de Punto de Venta abierto para registrar entradas o salidas de efectivo."))

    shift_doc = frappe.get_doc("POS Opening Shift", pos_opening_shift)
    if shift_doc.user != frappe.session.user and not is_supervisor():
        frappe.throw(
            _("Solo el usuario del turno abierto o un supervisor pueden registrar movimientos en esta caja."),
            frappe.PermissionError,
        )
    doc = frappe.get_doc({
        "doctype": "Retiro de efectivo",
        "type_transaction": tx_type,
        "pos_opening_shift": shift_doc.name,
        "pos_profile": shift_doc.pos_profile,
        "cashier": frappe.session.user,
        "posting_date": now_datetime(),
        "amount": amt,
        "note": clean_note,
    })
    doc.insert(ignore_permissions=True)
    doc.submit()

    summary = get_shift_cash_movements(shift_doc.name)
    summary["created"] = {
        "name": doc.name,
        "type_transaction": doc.type_transaction,
        "amount": flt(doc.amount, 2),
        "note": doc.note,
    }
    return summary


@frappe.whitelist()
def get_closing_shift_preview(pos_opening_shift=None):
    """Build a POS Awesome closing shift reconciliation preview for the active shift."""
    _require_pos_user()
    if not pos_opening_shift:
        active = _get_active_opening_shift(frappe.session.user)
        pos_opening_shift = active["name"] if active else None
    if not pos_opening_shift or not frappe.db.exists("POS Opening Shift", pos_opening_shift):
        frappe.throw(_("No se encontró un turno de Punto de Venta activo para cerrar."))

    opening_doc = frappe.get_doc("POS Opening Shift", pos_opening_shift)
    cash_movements = get_shift_cash_movements(opening_doc.name)
    prof_doc = frappe.get_cached_doc("POS Profile", opening_doc.pos_profile)
    hide_expected_amount = cint(getattr(prof_doc, "hide_expected_amount", 0))
    currency = getattr(prof_doc, "currency", None) or frappe.get_cached_value("Company", opening_doc.company, "default_currency") or "HNL"

    if not frappe.db.exists("DocType", "POS Closing Shift"):
        frappe.throw(_("Instala POS Awesome para conciliar y cerrar el turno."))

    from posawesome.posawesome.doctype.pos_closing_shift.pos_closing_shift import (
        make_closing_shift_from_opening,
    )

    closing_doc = make_closing_shift_from_opening(frappe.as_json(opening_doc.as_dict()))
    configured_cash_mop = (
        frappe.db.get_value("POS Profile", opening_doc.pos_profile, "posa_cash_mode_of_payment")
        if frappe.get_meta("POS Profile").has_field("posa_cash_mode_of_payment")
        else None
    )
    cash_net_total = flt(cash_movements.get("net_cash_movement"), 2)
    cash_applied = False
    payment_reconciliation = []
    for row in (closing_doc.payment_reconciliation or []):
        mop = row.mode_of_payment or ""
        expected_amt = flt(row.expected_amount, 2)
        opening_amt = flt(row.opening_amount, 2)
        is_cash = (
            (configured_cash_mop and mop == configured_cash_mop)
            or "efectivo" in mop.lower()
            or "cash" in mop.lower()
        )
        cash_net = cash_net_total if (is_cash and not cash_applied) else 0.0
        if is_cash and not cash_applied:
            cash_applied = True
        payment_reconciliation.append({
            "mode_of_payment": mop,
            "is_cash": cint(is_cash),
            "opening_amount": opening_amt,
            "sales_amount": flt(expected_amt - opening_amt - cash_net, 2),
            "cash_movement_net": cash_net,
            "expected_amount": expected_amt,
            "closing_amount": expected_amt,
            "difference": 0.0,
        })

    return {
        "pos_opening_shift": opening_doc.name,
        "pos_profile": opening_doc.pos_profile,
        "company": opening_doc.company,
        "currency": currency,
        "hide_expected_amount": hide_expected_amount,
        "user": opening_doc.user,
        "cashier_name": get_fullname(opening_doc.user),
        "period_start_date": str(opening_doc.period_start_date),
        "invoice_count": len(closing_doc.pos_transactions or []),
        "total_sales": flt(closing_doc.grand_total, 2),
        "cash_movements": cash_movements,
        "payment_reconciliation": payment_reconciliation,
    }


@frappe.whitelist(methods=["POST"])
def close_pos_shift(pos_opening_shift, closing_amounts=None, note=None):
    """Close the active POS Opening Shift using POS Awesome's native POS Closing Shift process."""
    _require_pos_user()
    if not user_can_invoice():
        frappe.throw(
            _("Solo cajeros o supervisores pueden cerrar turnos de caja."),
            frappe.PermissionError,
        )
    if not pos_opening_shift or not frappe.db.exists("POS Opening Shift", pos_opening_shift):
        frappe.throw(_("No se encontró el turno de caja activo."))
    frappe.db.get_value("POS Opening Shift", pos_opening_shift, "name", for_update=True)
    doc = frappe.get_doc("POS Opening Shift", pos_opening_shift)
    if doc.docstatus != 1 or doc.status == "Closed":
        frappe.throw(_("Este turno de caja ya se encuentra cerrado."))
    if doc.user != frappe.session.user and not is_supervisor():
        frappe.throw(_("Solo el cajero titular o un supervisor puede cerrar este turno."), frappe.PermissionError)
    if doc.user != frappe.session.user and "System Manager" not in frappe.get_roles():
        user_branch = _get_active_user_branch()
        prof_branch = (
            frappe.db.get_value("POS Profile", doc.pos_profile, "branch")
            if doc.pos_profile and frappe.db.has_column("POS Profile", "branch")
            else None
        )
        if user_branch and prof_branch and user_branch != prof_branch:
            frappe.throw(_("No puedes cerrar un turno de caja perteneciente a otra sucursal."), frappe.PermissionError)

    parsed_amounts = {}
    if closing_amounts:
        raw_closing = frappe.parse_json(closing_amounts) if isinstance(closing_amounts, str) else closing_amounts
        if isinstance(raw_closing, list):
            for entry in raw_closing:
                if isinstance(entry, dict) and entry.get("mode_of_payment"):
                    parsed_amounts[entry["mode_of_payment"]] = flt(entry.get("closing_amount"), 2)
        elif isinstance(raw_closing, dict):
            for k, v in raw_closing.items():
                parsed_amounts[k] = flt(v, 2)

    if not frappe.db.exists("DocType", "POS Closing Shift"):
        frappe.throw(_("Instala POS Awesome para cerrar el turno."))

    from posawesome.posawesome.doctype.pos_closing_shift.pos_closing_shift import (
        make_closing_shift_from_opening,
    )

    closing_doc = make_closing_shift_from_opening(frappe.as_json(doc.as_dict()))
    for row in (closing_doc.payment_reconciliation or []):
        if row.mode_of_payment in parsed_amounts:
            row.closing_amount = flt(parsed_amounts[row.mode_of_payment], 2)
        else:
            row.closing_amount = flt(row.expected_amount, 2)
        row.difference = flt(row.closing_amount - flt(row.expected_amount, 2), 2)
    closing_doc.insert(ignore_permissions=True)
    closing_doc.submit()
    closing_shift_name = closing_doc.name
    clean_note = cstr(note or "").strip()
    if clean_note:
        closing_doc.add_comment("Comment", text=_("Nota de cierre: {0}").format(clean_note))

    return {
        "closed": doc.name,
        "pos_closing_shift": closing_shift_name,
    }
