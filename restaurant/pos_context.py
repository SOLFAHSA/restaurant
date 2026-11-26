"""Shared POS context: user access, PIN throttling, company, branch, defaults and open shift."""

import frappe
from frappe import _
from frappe.utils import cint, cstr, flt, get_fullname

from restaurant.pos_auth import get_linked_employee_for_user, is_supervisor, verify_supervisor_authorization


def _require_pos_user():
    if frappe.session.user == "Guest":
        frappe.throw(
            _("Debes iniciar sesión para acceder al Punto de Venta de Restaurante."),
            frappe.PermissionError,
        )
    if not {"System Manager", "Restaurant Manager", "Restaurant Cashier", "Restaurant Direct Cashier", "Restaurant User"}.intersection(frappe.get_roles()):
        frappe.throw(
            _("No tienes permiso para acceder al Punto de Venta de Restaurante."),
            frappe.PermissionError,
        )


def _require_manager_user():
    """Ensure the current session user has manager-level administrative permissions."""
    _require_pos_user()
    if not {"System Manager", "Restaurant Manager"}.intersection(frappe.get_roles()):
        frappe.throw(
            _("Solo un Administrador o Gerente de Restaurante puede realizar esta operación."),
            frappe.PermissionError,
        )


def _enforce_pin_rate_limit(scope_key, max_attempts=5, window_seconds=300):
    """Block repeated failed PIN attempts for a user/target scope using Frappe cache."""
    cache = frappe.cache()
    cache_key = f"rpos_pin_fail:{frappe.session.user}:{scope_key}"
    attempts = cint(cache.get_value(cache_key, expires=True) or 0)
    if attempts >= max_attempts:
        frappe.throw(
            _("Demasiados intentos fallidos de PIN. Espera unos minutos antes de intentar de nuevo."),
            frappe.PermissionError,
        )
    return cache_key


def _record_pin_failure(cache_key, window_seconds=300):
    """Increment failed PIN attempt counter in Frappe cache."""
    cache = frappe.cache()
    attempts = cint(cache.get_value(cache_key, expires=True) or 0) + 1
    cache.set_value(cache_key, attempts, expires_in_sec=window_seconds)


def _clear_pin_failures(cache_key):
    """Clear failed PIN attempt counter after a successful verification."""
    frappe.cache().delete_value(cache_key)


def _get_active_user_branch(opening_shift=None, linked_waiter=None):
    """Resolve the active Branch for the current session user, if configured."""
    branch = frappe.defaults.get_user_default("Branch")
    if branch and frappe.db.exists("Branch", branch):
        return branch
    if linked_waiter is None:
        linked_waiter = get_linked_employee_for_user()
    if linked_waiter and linked_waiter.get("branch"):
        return linked_waiter["branch"]
    if opening_shift and opening_shift.get("pos_profile") and frappe.get_meta("POS Profile").has_field("branch"):
        prof_branch = frappe.db.get_value("POS Profile", opening_shift["pos_profile"], "branch")
        if prof_branch:
            return prof_branch
    return None


def _get_default_company():
    company = frappe.defaults.get_user_default("Company") or frappe.defaults.get_global_default("company")
    if company and frappe.db.exists("Company", company):
        return company
    companies = frappe.get_all("Company", pluck="name", limit=1)
    return companies[0] if companies else None


def _get_default_customer():
    for candidate in ("CONSUMIDOR FINAL", "Consumidor Final"):
        if frappe.db.exists("Customer", candidate):
            return candidate
    customers = frappe.get_all("Customer", filters={"disabled": 0}, pluck="name", limit=1)
    return customers[0] if customers else None


def _get_default_pos_profile(company=None):
    filters = {"disabled": 0}
    if company:
        filters["company"] = company
    profiles = frappe.get_all(
        "POS Profile",
        filters=filters,
        fields=["name", "company", "currency", "selling_price_list", "warehouse", "customer"],
        order_by="creation asc",
        limit=10,
    )
    if not profiles and company:
        profiles = frappe.get_all(
            "POS Profile",
            filters={"disabled": 0},
            fields=["name", "company", "currency", "selling_price_list", "warehouse", "customer"],
            order_by="creation asc",
            limit=10,
        )
    return profiles[0] if profiles else None


def _get_active_opening_shift(user=None):
    user = user or frappe.session.user
    if not frappe.db.exists("DocType", "POS Opening Shift"):
        return None
    shifts = frappe.get_all(
        "POS Opening Shift",
        filters={"user": user, "docstatus": 1, "status": "Open"},
        fields=["name", "pos_profile", "company", "user", "period_start_date", "posting_date"],
        order_by="creation desc",
        limit=1,
    )
    if not shifts:
        return None
    shift = shifts[0]
    doc = frappe.get_doc("POS Opening Shift", shift.name)
    opening_total = sum(flt(row.amount) for row in (doc.balance_details or []))
    return {
        "name": doc.name,
        "pos_profile": doc.pos_profile,
        "company": doc.company,
        "user": doc.user,
        "cashier_name": get_fullname(doc.user),
        "period_start_date": str(doc.period_start_date),
        "posting_date": str(doc.posting_date),
        "opening_amount": flt(opening_total, 2),
        "balance_details": [
            {"mode_of_payment": row.mode_of_payment, "opening_amount": flt(row.amount, 2)}
            for row in (doc.balance_details or [])
        ],
    }


def _get_order_company():
    shift = _get_active_opening_shift(frappe.session.user)
    return shift["company"] if shift else _get_default_company()


def _check_order_company(doc, company=None):
    if not doc.company or doc.company != (company or _get_order_company()):
        frappe.throw(_("La orden no pertenece a la empresa activa del punto de venta."), frappe.PermissionError)


def _authorize_sensitive_operation(action, order_name, supervisor_user=None, supervisor_pin=None, reason="", require_reason=True):
    """Authorize a sensitive POS operation via active supervisor session or supervisor PIN."""
    clean_reason = cstr(reason or "").strip()
    if is_supervisor():
        if require_reason and not clean_reason:
            frappe.throw(_("Debes ingresar el motivo obligatorio de la cancelación."), frappe.ValidationError)
        return {"authorized": True, "supervisor": frappe.session.user, "reason": clean_reason}

    auth = verify_supervisor_authorization(
        supervisor_user,
        supervisor_pin,
        action,
        order_name=order_name,
        reason=clean_reason,
        require_reason=require_reason,
        log_success=False,
    )
    if require_reason and not clean_reason:
        frappe.throw(_("Debes ingresar el motivo obligatorio de la cancelación."), frappe.ValidationError)
    return {"authorized": True, "supervisor": auth["supervisor"], "reason": clean_reason}
