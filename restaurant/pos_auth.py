"""Role-based POS authorization, waiter PIN verification, supervisor approval, and audit logging."""

import hmac
import json
import uuid
import frappe
from frappe import _
from frappe.utils import cstr, flt, now_datetime
from frappe.utils.password import check_password, get_decrypted_password

MAX_SUPERVISOR_PIN_ATTEMPTS = 5
SUPERVISOR_PIN_LOCKOUT_SEC = 300
SUPERVISOR_TOKEN_TTL_SEC = 120


INVOICE_ALLOWED_ROLES = {
    "System Manager",
    "Restaurant Manager",
    "Restaurant Cashier",
    "Restaurant Direct Cashier",
    "Administrator",
}
SUPERVISOR_ROLES = {"System Manager", "Restaurant Manager", "Administrator"}
CASHIER_ROLES = {"Restaurant Cashier", "Restaurant Direct Cashier"}


def user_can_invoice(user=None):
    """Return True if the user is allowed to collect payment and emit SAR invoices."""
    target = user or frappe.session.user
    roles = set(frappe.get_roles(target))
    return bool(roles & INVOICE_ALLOWED_ROLES)


def is_supervisor(user=None):
    """Return True if the user holds a supervisor/manager role."""
    target = user or frappe.session.user
    roles = set(frappe.get_roles(target))
    return bool(roles & SUPERVISOR_ROLES)


def is_waiter_only(user=None):
    """Return True if the user operates strictly as a waiter (Restaurant User without manager/cashier)."""
    target = user or frappe.session.user
    roles = set(frappe.get_roles(target))
    return ("Restaurant User" in roles) and not bool(roles & INVOICE_ALLOWED_ROLES)


def is_cashier_only(user=None):
    """Return True if the user operates as a restaurant cashier without supervisor/manager role."""
    target = user or frappe.session.user
    roles = set(frappe.get_roles(target))
    return bool(roles & CASHIER_ROLES) and not bool(roles & SUPERVISOR_ROLES)


def is_direct_cashier(user=None):
    """Return True if the user is restricted to direct invoicing without tables or open accounts."""
    target = user or frappe.session.user
    roles = set(frappe.get_roles(target))
    return ("Restaurant Direct Cashier" in roles) and not bool(roles & SUPERVISOR_ROLES)


def get_linked_employee_for_user(user=None):
    """Return active Employee dict linked via Employee.user_id, or None."""
    target = user or frappe.session.user
    if not target or target in ("Guest", "Administrator"):
        return None
    row = frappe.db.get_value(
        "Employee",
        {"user_id": target, "status": "Active"},
        ["name", "employee_name", "designation", "branch"],
        as_dict=True,
    )
    return row


def get_supervisors_for_pos(branch=None):
    """Return active supervisor users (without secrets) for the authorization dropdown."""
    role_rows = frappe.get_all(
        "Has Role",
        filters={"role": ["in", list(SUPERVISOR_ROLES)], "parenttype": "User"},
        pluck="parent",
    )
    candidate_users = sorted({u for u in role_rows if u and u != "Guest"})
    if not candidate_users:
        return []

    users = frappe.get_all(
        "User",
        filters={"name": ["in", candidate_users], "enabled": 1},
        fields=["name", "full_name"],
        order_by="full_name asc",
    )
    if not branch:
        return [{"user": u.name, "full_name": u.full_name or u.name} for u in users]

    # Respect Branch User Permission if configured on a supervisor
    result = []
    for u in users:
        allowed_branches = frappe.get_all(
            "User Permission",
            filters={"user": u.name, "allow": "Branch"},
            pluck="for_value",
        )
        if not allowed_branches or branch in allowed_branches:
            result.append({"user": u.name, "full_name": u.full_name or u.name})
    return result


def verify_employee_pin(employee_name, pin):
    """Verify the encrypted restaurant_pos_pin stored on Employee without exposing it."""
    if not employee_name or not frappe.db.exists("Employee", employee_name):
        return False
    if not frappe.get_meta("Employee").has_field("restaurant_pos_pin"):
        return False
    stored_pin = get_decrypted_password("Employee", employee_name, "restaurant_pos_pin", raise_exception=False)
    if not stored_pin:
        return False
    return hmac.compare_digest(cstr(stored_pin).strip(), cstr(pin or "").strip())


def employee_has_pin(employee_name):
    """Return True if the Employee record has a restaurant_pos_pin configured."""
    if not employee_name or not frappe.get_meta("Employee").has_field("restaurant_pos_pin"):
        return False
    stored_pin = get_decrypted_password("Employee", employee_name, "restaurant_pos_pin", raise_exception=False)
    return bool(stored_pin)


def log_restaurant_audit(
    action,
    detail,
    order_name=None,
    supervisor_user=None,
    result="Autorizado",
    item_code=None,
    item_name=None,
    affected_qty=None,
    reason="",
    previous_state=None,
    resulting_state=None,
    operation_id=None,
):
    """Record an immutable audit entry in Restaurant Audit Log, Activity Log, and Order timeline."""
    op_id = cstr(operation_id or uuid.uuid4().hex[:12]).strip()
    subject = f"[POS Restaurante] {action}: {detail}"
    if supervisor_user:
        subject += f" (Autorizado por: {supervisor_user})"

    if frappe.db.exists("DocType", "Restaurant Audit Log"):
        try:
            frappe.get_doc({
                "doctype": "Restaurant Audit Log",
                "event_time": now_datetime(),
                "operation_id": op_id,
                "action": cstr(action)[:140],
                "result": result if result in ("Autorizado", "Rechazado", "Bloqueado") else "Autorizado",
                "requested_by": frappe.session.user,
                "supervisor_user": supervisor_user if supervisor_user and frappe.db.exists("User", supervisor_user) else None,
                "restaurant_order": order_name if order_name and frappe.db.exists("Restaurant Order", order_name) else None,
                "item_code": item_code if item_code and frappe.db.exists("Item", item_code) else None,
                "item_name": cstr(item_name or "")[:140] or None,
                "affected_qty": flt(affected_qty) if affected_qty is not None else 0,
                "reason": cstr(reason or "")[:500] or None,
                "previous_state": cstr(previous_state or "")[:140] or None,
                "resulting_state": cstr(resulting_state or "")[:140] or None,
                "detail": cstr(detail or "")[:500],
            }).insert(ignore_permissions=True)
        except Exception:
            frappe.log_error(frappe.get_traceback(), "Restaurant Audit Log DocType")

    try:
        frappe.get_doc({
            "doctype": "Activity Log",
            "subject": subject[:140],
            "content": subject,
            "user": frappe.session.user,
            "reference_doctype": "Restaurant Order" if order_name else None,
            "reference_name": order_name,
            "status": "Success" if result == "Autorizado" else "Failed",
        }).insert(ignore_permissions=True)
    except Exception:
        frappe.log_error(frappe.get_traceback(), "Restaurant Audit Log")

    if order_name and frappe.db.exists("Restaurant Order", order_name):
        try:
            doc = frappe.get_doc("Restaurant Order", order_name)
            doc.add_comment("Info", subject)
        except Exception:
            pass
    return op_id


def _supervisor_fail_key(supervisor_user):
    return f"rpos_sup_fail:{frappe.session.user}:{supervisor_user}"


def _supervisor_token_key(token):
    return f"rpos_sup_tok:{token}"


def issue_supervisor_auth_token(supervisor_user, action, order_name=None, target="", reason=""):
    """Issue a short-lived, single-use authorization token bound to a specific operation."""
    token = uuid.uuid4().hex
    payload = {
        "user": frappe.session.user,
        "supervisor": cstr(supervisor_user).strip(),
        "action": cstr(action).strip(),
        "order_name": cstr(order_name or "").strip(),
        "target": cstr(target or "").strip(),
        "reason": cstr(reason or "").strip(),
    }
    frappe.cache().set_value(
        _supervisor_token_key(token),
        json.dumps(payload, ensure_ascii=False),
        expires_in_sec=SUPERVISOR_TOKEN_TTL_SEC,
    )
    return token


def consume_supervisor_auth_token(token, action, order_name=None, target=""):
    """Consume and validate a single-use supervisor authorization token for the exact operation."""
    clean_token = cstr(token or "").strip()
    if not clean_token:
        return None
    cache = frappe.cache()
    key = _supervisor_token_key(clean_token)
    raw = cache.get_value(key)
    if not raw:
        return None
    cache.delete_value(key)
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except Exception:
        return None
    if (
        data.get("user") != frappe.session.user
        or data.get("action") != cstr(action).strip()
        or data.get("order_name") != cstr(order_name or "").strip()
        or data.get("target") != cstr(target or "").strip()
    ):
        return None
    return data


def _resolve_supervisor_by_pin(raw_secret):
    """Find the active supervisor User whose linked Employee PIN matches raw_secret."""
    for sup in get_supervisors_for_pos():
        sup_name = sup["user"]
        linked_emp = get_linked_employee_for_user(sup_name)
        if linked_emp and employee_has_pin(linked_emp["name"]) and verify_employee_pin(linked_emp["name"], raw_secret):
            return sup_name
    return None


def verify_supervisor_authorization(
    supervisor_user,
    secret,
    action,
    order_name=None,
    reason="",
    require_reason=False,
    issue_token=False,
    token_target="",
    log_success=True,
):
    """Validate supervisor role + encrypted PIN (resolving supervisor by PIN if omitted), rate-limit failures, and log audit."""
    sup_user = cstr(supervisor_user or "").strip()
    raw_secret = cstr(secret or "").strip()
    clean_reason = cstr(reason or "").strip()
    if not raw_secret:
        frappe.throw(_("Debes ingresar el PIN o código de autorización del supervisor."), frappe.PermissionError)

    if require_reason and not clean_reason:
        frappe.throw(_("Debes ingresar el motivo obligatorio de la cancelación."), frappe.ValidationError)

    if not sup_user:
        fail_key = _supervisor_fail_key("_pin_")
        attempts = int(frappe.cache().get_value(fail_key) or 0)
        if attempts >= MAX_SUPERVISOR_PIN_ATTEMPTS:
            log_restaurant_audit(
                f"Bloqueo por intentos fallidos ({action})",
                f"Usuario {frappe.session.user} excedió el límite de intentos de PIN de supervisor.",
                order_name=order_name,
                result="Bloqueado",
                reason=clean_reason,
            )
            frappe.throw(
                _("Demasiados intentos de PIN incorrecto. Espera 5 minutos antes de volver a intentar."),
                frappe.PermissionError,
            )

        sup_user = _resolve_supervisor_by_pin(raw_secret)
        if not sup_user:
            frappe.cache().set_value(fail_key, attempts + 1, expires_in_sec=SUPERVISOR_PIN_LOCKOUT_SEC)
            log_restaurant_audit(
                f"Intento fallido de {action}",
                f"Usuario: {frappe.session.user} ingresó un PIN de supervisor inválido.",
                order_name=order_name,
                result="Rechazado",
                reason=clean_reason,
            )
            frappe.throw(_("PIN o código de supervisor incorrecto."), frappe.PermissionError)

        frappe.cache().delete_value(fail_key)
    else:
        if sup_user == frappe.session.user and not is_supervisor():
            log_restaurant_audit(
                f"Autoautorización bloqueada ({action})",
                f"Usuario {frappe.session.user} intentó autoautorizarse.",
                order_name=order_name,
                result="Bloqueado",
                reason=clean_reason,
            )
            frappe.throw(_("Un mesero o cajero no puede autoautorizarse con sus propias credenciales."), frappe.PermissionError)

        if not frappe.db.exists("User", {"name": sup_user, "enabled": 1}):
            frappe.throw(_("El usuario supervisor seleccionado no existe o está deshabilitado."), frappe.PermissionError)

        sup_roles = set(frappe.get_roles(sup_user))
        if not (sup_roles & SUPERVISOR_ROLES):
            log_restaurant_audit(
                f"Autorización rechazada ({action})",
                f"Usuario {sup_user} no posee rol de supervisor.",
                order_name=order_name,
                supervisor_user=sup_user,
                result="Rechazado",
                reason=clean_reason,
            )
            frappe.throw(_("El usuario seleccionado no tiene rol de Supervisor o Gerente."), frappe.PermissionError)

        fail_key = _supervisor_fail_key(sup_user)
        attempts = int(frappe.cache().get_value(fail_key) or 0)
        if attempts >= MAX_SUPERVISOR_PIN_ATTEMPTS:
            log_restaurant_audit(
                f"Bloqueo por intentos fallidos ({action})",
                f"Usuario {frappe.session.user} excedió el límite de intentos para supervisor {sup_user}.",
                order_name=order_name,
                supervisor_user=sup_user,
                result="Bloqueado",
                reason=clean_reason,
            )
            frappe.throw(
                _("Demasiados intentos de PIN incorrecto. Espera 5 minutos antes de volver a intentar."),
                frappe.PermissionError,
            )

        authorized = False
        linked_emp = get_linked_employee_for_user(sup_user)
        if linked_emp and employee_has_pin(linked_emp["name"]):
            authorized = verify_employee_pin(linked_emp["name"], raw_secret)
        else:
            try:
                check_password(sup_user, raw_secret)
                authorized = True
            except frappe.AuthenticationError:
                authorized = False

        if not authorized:
            frappe.cache().set_value(fail_key, attempts + 1, expires_in_sec=SUPERVISOR_PIN_LOCKOUT_SEC)
            log_restaurant_audit(
                f"Intento fallido de {action}",
                f"Usuario: {frappe.session.user}, Supervisor intentado: {sup_user}",
                order_name=order_name,
                supervisor_user=sup_user,
                result="Rechazado",
                reason=clean_reason,
            )
            frappe.throw(_("PIN o clave de supervisor incorrecta."), frappe.PermissionError)

        frappe.cache().delete_value(fail_key)

    op_id = None
    if log_success:
        reason_txt = f" | Motivo: {clean_reason}" if clean_reason else ""
        op_id = log_restaurant_audit(
            action,
            f"Solicitado por {frappe.session.user}{reason_txt}",
            order_name=order_name,
            supervisor_user=sup_user,
            result="Autorizado",
            reason=clean_reason,
        )

    result = {"authorized": True, "supervisor": sup_user, "operation_id": op_id}
    if issue_token:
        result["auth_token"] = issue_supervisor_auth_token(
            sup_user, action, order_name=order_name, target=token_target, reason=clean_reason
        )
    return result


def is_order_unlocked_for_session(order_name):
    """Check if the current user session has unlocked the waiter-owned order."""
    if not order_name:
        return True
    key = f"rpos_unlocked:{frappe.session.user}:{order_name}"
    return bool(frappe.cache().get_value(key))


def mark_order_unlocked_for_session(order_name):
    """Mark a waiter-owned order as unlocked for the current user session (1 hour TTL)."""
    if order_name:
        key = f"rpos_unlocked:{frappe.session.user}:{order_name}"
        frappe.cache().set_value(key, 1, expires_in_sec=3600)

