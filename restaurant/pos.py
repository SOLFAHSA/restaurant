"""Backend services for the LEAF Restaurant POS, open accounts, pre-checks, SAR invoicing, and KDS."""

import json
import re

import frappe
from frappe import _
from frappe.utils import cint, cstr, flt, get_datetime, get_fullname, now_datetime, nowdate, nowtime

from restaurant.pos_auth import (
    employee_has_pin,
    get_linked_employee_for_user,
    get_supervisors_for_pos,
    is_cashier_only,
    is_direct_cashier,
    is_order_unlocked_for_session,
    is_supervisor,
    is_waiter_only,
    log_restaurant_audit,
    mark_order_unlocked_for_session,
    user_can_invoice,
    verify_employee_pin,
    verify_supervisor_authorization,
)

DEFAULT_CATEGORY_COLORS = (
    "#D9468F",
    "#16A34A",
    "#2563EB",
    "#EA580C",
    "#7C3AED",
    "#0891B2",
    "#CA8A04",
    "#DC2626",
)
DEFAULT_ITEM_COLORS = (
    "#EA580C",
    "#EC4899",
    "#EAB308",
    "#22C55E",
    "#3B82F6",
    "#A855F7",
    "#14B8A6",
    "#F97316",
)


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
    attempts = cint(cache.get_value(cache_key) or 0)
    if attempts >= max_attempts:
        frappe.throw(
            _("Demasiados intentos fallidos de PIN. Espera unos minutos antes de intentar de nuevo."),
            frappe.PermissionError,
        )
    return cache_key


def _record_pin_failure(cache_key, window_seconds=300):
    """Increment failed PIN attempt counter in Frappe cache."""
    cache = frappe.cache()
    attempts = cint(cache.get_value(cache_key) or 0) + 1
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


def _resolve_command_map():
    """Map Item Group names to configured Restaurant Command station names."""
    mapping = {}
    if not frappe.db.exists("DocType", "Restaurant Command"):
        return mapping
    commands = frappe.get_all(
        "Restaurant Command",
        filters={"enabled": 1},
        fields=["name", "command_name", "branch"],
        order_by="command_name asc",
    )
    for cmd in commands:
        rows = frappe.get_all(
            "Restaurant Command Group",
            filters={"parent": cmd.name, "parenttype": "Restaurant Command"},
            fields=["item_group"],
        )
        for row in rows:
            mapping.setdefault(row.item_group, []).append(cmd.command_name)
    return mapping


def _tax_rate_from_templates(template_names):
    for tpl in template_names:
        tpl_name = (tpl or "").upper()
        if "EXENTO" in tpl_name or "0%" in tpl_name:
            return 0.0
        if "18%" in tpl_name or "18" in tpl_name:
            return 18.0
        if "15%" in tpl_name or "15" in tpl_name:
            return 15.0
    return 15.0


def _resolve_item_tax_rate(item_code):
    """Return applicable Honduras ISV rate (15, 18, or 0) for an Item."""
    taxes = frappe.get_all(
        "Item Tax",
        filters={"parent": item_code, "parenttype": "Item"},
        fields=["item_tax_template"],
    )
    return _tax_rate_from_templates([row.item_tax_template for row in taxes])


def validate_order(doc):
    """Validate and compute server-side totals for a Restaurant Order."""
    doc.order_name = cstr(doc.order_name).strip()
    if not doc.order_name:
        frappe.throw(_("El nombre de la cuenta u orden es obligatorio."))
    if len(doc.order_name) > 140:
        frappe.throw(_("El nombre de la cuenta u orden no puede superar 140 caracteres."))

    doc.reference_note = cstr(doc.reference_note).strip()[:140]
    doc.customer_note = cstr(doc.customer_note).strip()[:500]
    doc.scheduled_time = cstr(doc.scheduled_time).strip()[:60]

    meta = frappe.get_meta("Restaurant Order")
    valid_statuses = [opt.strip() for opt in (meta.get_field("status").options or "").splitlines() if opt.strip()]
    doc.status = cstr(doc.status or "En curso").strip()
    if valid_statuses and doc.status not in valid_statuses:
        frappe.throw(_("El estado de la orden debe ser {0}.").format(", ".join(valid_statuses)))

    doc.service_type = cstr(doc.service_type or "Comer en el local").strip()
    if frappe.db.table_exists("Restaurant Order Preset"):
        valid_presets = frappe.get_all("Restaurant Order Preset", filters={"enabled": 1}, pluck="preset_name")
        if valid_presets and doc.service_type not in valid_presets:
            frappe.throw(_("La modalidad seleccionada '{0}' no es válida según los ajustes preestablecidos.").format(doc.service_type))

    valid_kds_statuses = [opt.strip() for opt in (meta.get_field("kds_status").options or "").splitlines() if opt.strip()]
    doc.kds_status = cstr(doc.kds_status or "Sin enviar").strip()
    if valid_kds_statuses and doc.kds_status not in valid_kds_statuses:
        doc.kds_status = "Sin enviar"

    doc.guests = max(1, cint(doc.guests or 1))

    if not doc.customer:
        doc.customer = _get_default_customer()
    if not doc.customer or not frappe.db.exists("Customer", doc.customer):
        frappe.throw(_("Selecciona un cliente válido para la cuenta u orden."))
    customer_info = frappe.db.get_value(
        "Customer", doc.customer, ["customer_name", "tax_id"], as_dict=True
    )
    doc.customer_name = (customer_info.customer_name if customer_info else doc.customer) or doc.customer
    if not doc.tax_id and customer_info and customer_info.tax_id:
        doc.tax_id = customer_info.tax_id
    doc.tax_id = cstr(doc.tax_id).strip()[:60]

    if doc.waiter:
        if not frappe.db.exists("Employee", doc.waiter):
            frappe.throw(_("El mesero seleccionado no existe."))
        doc.waiter_name = frappe.db.get_value("Employee", doc.waiter, "employee_name") or doc.waiter
    else:
        doc.waiter_name = ""

    if doc.restaurant_table:
        if not frappe.db.exists("Restaurant Table", doc.restaurant_table):
            frappe.throw(_("La mesa seleccionada no existe."))
        table_info = frappe.db.get_value(
            "Restaurant Table",
            doc.restaurant_table,
            ["table_number", "restaurant_area", "status"],
            as_dict=True,
        )
        if table_info and table_info.status == "Inactiva":
            frappe.throw(_("La mesa seleccionada está inactiva."))
        doc.table_label = table_info.table_number if table_info else doc.restaurant_table
        if table_info and table_info.restaurant_area:
            doc.restaurant_area = table_info.restaurant_area
    else:
        doc.table_label = ""

    if not doc.cashier:
        doc.cashier = frappe.session.user

    if not doc.company:
        doc.company = _get_default_company()
    if not doc.currency:
        doc.currency = (
            frappe.db.get_value("Company", doc.company, "default_currency")
            if doc.company
            else "HNL"
        ) or "HNL"

    if not doc.is_new() and not frappe.flags.get("in_restaurant_supervisor_cancel") and not frappe.flags.get("in_restaurant_order_operation"):
        before = doc.get_doc_before_save()
        if before:
            if before.status == "Facturada":
                frappe.throw(_("Una orden facturada no puede modificarse."), frappe.PermissionError)
            if doc.status == "Cancelada" and before.status != "Cancelada" and not is_supervisor():
                frappe.throw(
                    _("Solo un supervisor autorizado puede cancelar una orden."),
                    frappe.PermissionError,
                )
            new_by_name = {r.name: r for r in (doc.items or []) if getattr(r, "name", None)}
            for old_row in (before.items or []):
                old_kds = cstr(getattr(old_row, "kds_status", "") or "Pendiente")
                old_cancelled = cint(getattr(old_row, "is_cancelled", 0)) or old_kds == "Cancelado"
                if old_kds not in ("", "Pendiente") and not old_cancelled:
                    new_row = new_by_name.get(old_row.name)
                    if not new_row:
                        frappe.throw(
                            _("No puedes eliminar '{0}' porque ya fue enviado a cocina. Requiere autorización de supervisor.").format(
                                old_row.item_name or old_row.item_code
                            ),
                            frappe.PermissionError,
                        )
                    if flt(new_row.qty) < flt(old_row.qty) - 0.001:
                        frappe.throw(
                            _("No puedes reducir la cantidad de '{0}' porque ya fue enviado a cocina. Requiere autorización de supervisor.").format(
                                old_row.item_name or old_row.item_code
                            ),
                            frappe.PermissionError,
                        )
                    if cstr(new_row.kds_status or "Pendiente") == "Pendiente":
                        frappe.throw(
                            _("No puedes revertir el estado de cocina de un platillo ya enviado."),
                            frappe.PermissionError,
                        )

    command_map = _resolve_command_map()

    subtotal = 0.0
    taxed_15 = 0.0
    isv_15 = 0.0
    taxed_18 = 0.0
    isv_18 = 0.0
    exempt = 0.0

    item_meta = frappe.get_meta("Restaurant Order Item")
    valid_item_kds_statuses = [
        opt.strip() for opt in (item_meta.get_field("kds_status").options or "").splitlines() if opt.strip()
    ]

    item_codes = list({row.item_code for row in (doc.items or []) if row.item_code})
    items_by_code = {}
    taxes_by_item = {}
    catalog_price_by_item = {}
    option_price_by_item = {}
    if item_codes:
        for item_row in frappe.get_all(
            "Item",
            filters={"name": ["in", item_codes]},
            fields=["name", "item_name", "item_group", "stock_uom", "standard_rate"],
        ):
            items_by_code[item_row.name] = item_row
            if flt(item_row.standard_rate) > 0:
                catalog_price_by_item[item_row.name] = flt(item_row.standard_rate, 2)
        for tax_row in frappe.get_all(
            "Item Tax",
            filters={"parent": ["in", item_codes], "parenttype": "Item"},
            fields=["parent", "item_tax_template"],
        ):
            taxes_by_item.setdefault(tax_row.parent, []).append(tax_row.item_tax_template)
        selling_pl = cstr(getattr(doc, "selling_price_list", "") or "").strip()
        for price_row in frappe.get_all(
            "Item Price",
            filters={"item_code": ["in", item_codes], "selling": 1},
            fields=["item_code", "price_list", "price_list_rate"],
            order_by="modified desc",
        ):
            if selling_pl and price_row.price_list == selling_pl:
                catalog_price_by_item[price_row.item_code] = flt(price_row.price_list_rate, 2)
            elif price_row.item_code not in catalog_price_by_item or not selling_pl:
                catalog_price_by_item.setdefault(price_row.item_code, flt(price_row.price_list_rate, 2))
        if frappe.db.exists("DocType", "Restaurant Option Group"):
            opt_groups = frappe.get_all(
                "Restaurant Option Group",
                filters={"main_item": ["in", item_codes], "disabled": 0},
                fields=["name", "main_item"],
            )
            group_to_item = {g.name: g.main_item for g in opt_groups}
            if group_to_item:
                for opt_row in frappe.get_all(
                    "Restaurant Dish Option",
                    filters={"parent": ["in", list(group_to_item.keys())], "parenttype": "Restaurant Option Group"},
                    fields=["parent", "option_label", "additional_amount"],
                ):
                    main_item = group_to_item.get(opt_row.parent)
                    if main_item and opt_row.option_label:
                        option_price_by_item.setdefault(main_item, {})[cstr(opt_row.option_label).strip()] = flt(
                            opt_row.additional_amount, 2
                        )

    allow_rate_change = 0
    if getattr(doc, "pos_profile", None) and frappe.db.exists("POS Profile", doc.pos_profile):
        allow_rate_change = cint(frappe.db.get_value("POS Profile", doc.pos_profile, "allow_rate_change") or 0)
    can_override_rate = user_can_invoice() and bool(allow_rate_change)

    for row in (doc.items or []):
        if not row.item_code or row.item_code not in items_by_code:
            frappe.throw(_("Selecciona un producto o platillo válido en cada línea de la orden."))
        item_info = items_by_code[row.item_code]
        row.item_name = cstr(row.item_name or (item_info.item_name if item_info else row.item_code)).strip()
        row.item_group = (item_info.item_group if item_info and item_info.item_group else row.item_group)
        row.uom = row.uom or (item_info.stock_uom if item_info else None)

        row.qty = flt(row.qty)
        if row.qty <= 0:
            frappe.throw(_("La cantidad de cada platillo debe ser mayor que cero."))

        catalog_rate = flt(catalog_price_by_item.get(row.item_code, 0.0), 2)
        if catalog_rate > 0 and not can_override_rate:
            row.base_rate = catalog_rate
        elif is_waiter_only() and catalog_rate <= 0:
            row.base_rate = 0.0
        else:
            row.base_rate = max(0.0, flt(row.base_rate, 2))
            if row.base_rate == 0 and catalog_rate > 0:
                row.base_rate = catalog_rate

        # Recompute options_rate from authoritative Restaurant Dish Option records when available
        item_opt_map = option_price_by_item.get(row.item_code)
        raw_opts_json = cstr(getattr(row, "selected_options_json", "") or "").strip()
        if raw_opts_json:
            try:
                parsed_opts = json.loads(raw_opts_json)
            except Exception:
                parsed_opts = []
            if isinstance(parsed_opts, list) and item_opt_map is not None:
                row.options_rate = flt(
                    sum(
                        flt(item_opt_map.get(cstr(o.get("option_label") or "").strip(), 0.0), 2)
                        for o in parsed_opts
                        if isinstance(o, dict)
                    ),
                    2,
                )
            elif not parsed_opts:
                row.options_rate = 0.0
            else:
                row.options_rate = max(0.0, flt(row.options_rate, 2))
        else:
            row.options_rate = 0.0 if item_opt_map is not None else max(0.0, flt(row.options_rate, 2))

        row.discount_percentage = min(100.0, max(0.0, flt(row.discount_percentage, 2)))
        if is_waiter_only() and row.discount_percentage > 0:
            frappe.throw(_("Tu rol de mesero no tiene permiso para aplicar descuentos."), frappe.PermissionError)

        gross_unit = flt(row.base_rate + row.options_rate, 2)
        if gross_unit == 0 and flt(row.rate) > 0 and can_override_rate:
            row.base_rate = flt(row.rate, 2)
            gross_unit = row.base_rate

        row.rate = flt(gross_unit * (1.0 - (row.discount_percentage / 100.0)), 2)
        row.amount = flt(row.qty * row.rate, 2)

        row.tax_rate = _tax_rate_from_templates(taxes_by_item.get(row.item_code, []))

        row.note = cstr(row.note).strip()[:300]
        row.options_summary = cstr(row.options_summary).strip()[:500]
        stations = (command_map.get(row.item_group) or []) if row.item_group else []
        row.command_station = ", ".join(stations) if stations else "Cocina General"
        if valid_item_kds_statuses and row.kds_status not in valid_item_kds_statuses:
            row.kds_status = "Pendiente"

        is_row_cancelled = cint(getattr(row, "is_cancelled", 0)) or row.kds_status == "Cancelado"
        if is_row_cancelled:
            row.is_cancelled = 1
            row.kds_status = "Cancelado"
            row.amount = 0.0
            continue

        subtotal += row.amount
        if abs(row.tax_rate - 15.0) < 0.01:
            taxed_15 += row.amount
            isv_15 += flt(row.amount * 0.15, 2)
        elif abs(row.tax_rate - 18.0) < 0.01:
            taxed_18 += row.amount
            isv_18 += flt(row.amount * 0.18, 2)
        else:
            exempt += row.amount

    doc.subtotal = flt(subtotal, 2)
    doc.taxed_amount_15 = flt(taxed_15, 2)
    doc.isv_15 = flt(isv_15, 2)
    doc.taxed_amount_18 = flt(taxed_18, 2)
    doc.isv_18 = flt(isv_18, 2)
    doc.exempt_amount = flt(exempt, 2)
    doc.tax_amount = flt(doc.isv_15 + doc.isv_18, 2)

    doc.tip_percentage = max(0.0, min(100.0, flt(doc.tip_percentage, 2)))
    if doc.tip_percentage > 0:
        doc.tip_amount = flt(doc.subtotal * (doc.tip_percentage / 100.0), 2)
    else:
        doc.tip_amount = max(0.0, flt(doc.tip_amount, 2))

    doc.grand_total = flt(doc.subtotal + doc.tax_amount + doc.tip_amount, 2)


def sync_table_status_for_order(doc, deleted=False):
    """Synchronize Restaurant Table status (Ocupada / Disponible) with active orders."""
    tables_to_check = set()
    if getattr(doc, "restaurant_table", None):
        tables_to_check.add(doc.restaurant_table)
    before = doc.get_doc_before_save() if hasattr(doc, "get_doc_before_save") else None
    if before and getattr(before, "restaurant_table", None):
        tables_to_check.add(before.restaurant_table)

    for table_name in tables_to_check:
        if not table_name or not frappe.db.exists("Restaurant Table", table_name):
            continue
        current_status = frappe.db.get_value("Restaurant Table", table_name, "status")
        if current_status == "Inactiva":
            continue
        active_filters = {
            "restaurant_table": table_name,
            "status": "En curso",
        }
        if deleted and doc.name:
            active_filters["name"] = ["!=", doc.name]
        has_active_order = bool(frappe.db.exists("Restaurant Order", active_filters))
        target_status = "Ocupada" if has_active_order else "Disponible"
        if current_status != target_status:
            frappe.db.set_value("Restaurant Table", table_name, "status", target_status)


def _serialize_order(doc):
    if isinstance(doc, str):
        doc = frappe.get_doc("Restaurant Order", doc)
    items = []
    for row in (doc.items or []):
        selected_options = []
        if row.selected_options_json:
            try:
                selected_options = json.loads(row.selected_options_json)
            except Exception:
                selected_options = []
        items.append({
            "name": row.name,
            "idx": row.idx,
            "item_code": row.item_code,
            "item_name": row.item_name,
            "item_group": row.item_group,
            "qty": flt(row.qty),
            "uom": row.uom,
            "base_rate": flt(row.base_rate, 2),
            "options_rate": flt(row.options_rate, 2),
            "discount_percentage": flt(row.discount_percentage, 2),
            "rate": flt(row.rate, 2),
            "amount": flt(row.amount, 2),
            "tax_rate": flt(row.tax_rate, 2),
            "options_summary": row.options_summary or "",
            "selected_options": selected_options,
            "note": row.note or "",
            "command_station": row.command_station or "Cocina General",
            "kds_status": row.kds_status or "Pendiente",
            "is_cancelled": cint(getattr(row, "is_cancelled", 0)) or row.kds_status == "Cancelado",
            "cancelled_qty": flt(getattr(row, "cancelled_qty", 0)),
            "cancellation_reason": cstr(getattr(row, "cancellation_reason", "") or ""),
            "cancelled_by": cstr(getattr(row, "cancelled_by", "") or ""),
            "cancelled_by_supervisor": cstr(getattr(row, "cancelled_by_supervisor", "") or ""),
            "cancelled_at": cstr(getattr(row, "cancelled_at", "") or ""),
        })
    created_dt = get_datetime(doc.creation) if doc.creation else now_datetime()
    elapsed_mins = max(0, int((now_datetime() - created_dt).total_seconds() // 60))
    linked_emp = get_linked_employee_for_user()
    requires_pin_unlock = bool(
        doc.waiter
        and is_waiter_only()
        and not linked_emp
        and doc.status not in ("Facturada", "Cancelada")
        and employee_has_pin(doc.waiter)
        and not is_order_unlocked_for_session(doc.name)
    )
    return {
        "name": doc.name,
        "order_name": doc.order_name,
        "reference_note": doc.reference_note or "",
        "status": doc.status,
        "service_type": doc.service_type,
        "restaurant_area": doc.restaurant_area or "",
        "restaurant_table": doc.restaurant_table or "",
        "table_label": doc.table_label or "",
        "guests": cint(doc.guests or 1),
        "waiter": doc.waiter or "",
        "waiter_name": doc.waiter_name or "",
        "customer": doc.customer or "",
        "customer_name": doc.customer_name or doc.customer or "",
        "tax_id": doc.tax_id or "",
        "pos_profile": doc.pos_profile or "",
        "pos_opening_shift": doc.pos_opening_shift or "",
        "cashier": doc.cashier or "",
        "cashier_name": get_fullname(doc.cashier) if doc.cashier else "",
        "company": doc.company or "",
        "currency": doc.currency or "HNL",
        "selling_price_list": doc.selling_price_list or "",
        "kds_status": doc.kds_status or "Sin enviar",
        "sent_to_kitchen_at": str(doc.sent_to_kitchen_at) if doc.sent_to_kitchen_at else "",
        "scheduled_time": doc.scheduled_time or "",
        "customer_note": doc.customer_note or "",
        "precuenta_printed": cint(doc.precuenta_printed),
        "subtotal": flt(doc.subtotal, 2),
        "taxed_amount_15": flt(doc.taxed_amount_15, 2),
        "isv_15": flt(doc.isv_15, 2),
        "taxed_amount_18": flt(doc.taxed_amount_18, 2),
        "isv_18": flt(doc.isv_18, 2),
        "exempt_amount": flt(doc.exempt_amount, 2),
        "tax_amount": flt(doc.tax_amount, 2),
        "tip_percentage": flt(doc.tip_percentage, 2),
        "tip_amount": flt(doc.tip_amount, 2),
        "grand_total": flt(doc.grand_total, 2),
        "sales_invoice": doc.sales_invoice or "",
        "cai": doc.cai or "",
        "due_date_cai": str(doc.due_date_cai) if doc.due_date_cai else "",
        "creation": str(doc.creation),
        "modified": str(doc.modified),
        "elapsed_minutes": elapsed_mins,
        "elapsed_label": f"{elapsed_mins // 60:02d}:{elapsed_mins % 60:02d}",
        "requires_pin_unlock": requires_pin_unlock,
        "items": items,
    }


def _expand_item_groups(group_names):
    """Expand selected Item Groups to include their descendant sub-categories via lft/rgt."""
    if not group_names:
        return []
    expanded = set()
    rows = frappe.get_all(
        "Item Group",
        filters={"name": ["in", list(group_names)]},
        fields=["name", "lft", "rgt"],
    )
    for row in rows:
        expanded.add(row.name)
        children = frappe.get_all(
            "Item Group",
            filters={"lft": [">=", row.lft], "rgt": ["<=", row.rgt]},
            pluck="name",
        )
        for ch in children:
            expanded.add(ch)
    return list(expanded)


def _get_effective_rpos_config(pos_profile=None):
    """Merge Restaurant Settings single doc with per-profile defaults."""
    cfg = {
        "pos_profile": pos_profile or "",
        "default_preset": "Comer en el local",
        "enable_self_order": 0,
        "self_order_channels": "Ambos canales",
        "enable_mobile_self_order": 0,
        "enable_kiosk_self_order": 0,
        "enabled_payments": [],
        "auto_validate_orders": 1,
        "tips_enabled": 1,
        "enable_rounded_total": 1,
        "show_product_images": 1,
        "show_category_images": 1,
        "group_by_category": 0,
        "large_scrollbars": 0,
        "share_open_orders": 1,
        "restrict_categories": 0,
        "allowed_categories": [],
        "allow_category_search": 1,
        "allow_line_discount": 1,
        "price_display_mode": "Precio con impuesto incluido",
        "allow_global_discount": 1,
        "enable_promotions_coupons": 0,
        "enable_gift_cards": 0,
        "enable_loyalty_program": 0,
        "allow_whatsapp_invoice": 0,
        "allow_email_invoice": 1,
        "enable_self_invoicing": 0,
        "idle_wallpaper_enabled": 1,
        "idle_wallpaper_show_clock": 1,
        "idle_wallpaper_timeout": 120,
        "idle_wallpaper_background_url": "/assets/restaurant/images/background-light.svg",
        "idle_wallpaper_logo_url": "",
    }

    if frappe.db.exists("DocType", "Restaurant Settings"):
        try:
            rs = frappe.get_single("Restaurant Settings")
            for key in (
                "default_preset", "enable_self_order", "self_order_channels",
                "enable_mobile_self_order", "enable_kiosk_self_order",
                "auto_validate_orders", "tips_enabled", "enable_rounded_total",
                "show_product_images", "show_category_images", "group_by_category",
                "large_scrollbars", "share_open_orders", "restrict_categories",
                "allow_category_search", "allow_line_discount", "price_display_mode",
                "allow_global_discount", "enable_promotions_coupons",
                "enable_gift_cards", "enable_loyalty_program",
                "allow_whatsapp_invoice", "allow_email_invoice", "enable_self_invoicing",
                "idle_wallpaper_enabled", "idle_wallpaper_show_clock",
            ):
                if hasattr(rs, key) and rs.get(key) is not None:
                    cfg[key] = rs.get(key)
            if hasattr(rs, "idle_wallpaper_minutes") and rs.idle_wallpaper_minutes:
                cfg["idle_wallpaper_timeout"] = int(round(max(0.1, flt(rs.idle_wallpaper_minutes)) * 60))
            if getattr(rs, "idle_wallpaper_background", None):
                cfg["idle_wallpaper_background_url"] = rs.idle_wallpaper_background
            if getattr(rs, "idle_wallpaper_logo", None):
                cfg["idle_wallpaper_logo_url"] = rs.idle_wallpaper_logo
            if getattr(rs, "payment_methods", None):
                cfg["enabled_payments"] = [
                    r.mode_of_payment for r in rs.payment_methods if cint(r.enabled) and r.mode_of_payment
                ]
            if cint(cfg.get("restrict_categories")) and getattr(rs, "allowed_categories", None):
                cfg["allowed_categories"] = [
                    r.item_group for r in rs.allowed_categories if r.item_group
                ]
        except Exception:
            pass

    if pos_profile:
        raw_pref = frappe.db.get_default(f"rpos_cfg_{pos_profile}")
        if raw_pref:
            try:
                pref = json.loads(raw_pref) if isinstance(raw_pref, str) else dict(raw_pref)
                for k, v in pref.items():
                    if v is not None:
                        cfg[k] = v
            except Exception:
                pass
        if frappe.db.exists("POS Profile", pos_profile):
            prof_doc = frappe.get_doc("POS Profile", pos_profile)
            cfg["show_product_images"] = 0 if cint(prof_doc.hide_images) else cint(cfg.get("show_product_images", 1))
            cfg["enable_rounded_total"] = 0 if cint(prof_doc.disable_rounded_total) else 1
            if prof_doc.payments:
                cfg["enabled_payments"] = [row.mode_of_payment for row in prof_doc.payments if row.mode_of_payment]

    return cfg


def _get_catalog_for_pos(selling_price_list=None, allowed_categories=None):
    """Return categories (Item Group) and products (Item) with photos, colors, prices, and options."""
    has_item_color = frappe.get_meta("Item").has_field("restaurant_color")
    has_group_color = frappe.get_meta("Item Group").has_field("restaurant_color")

    item_fields = [
        "name",
        "item_name",
        "description",
        "item_group",
        "stock_uom",
        "image",
        "standard_rate",
        "is_stock_item",
        "restaurant_recipe_enabled",
        "restaurant_options_enabled",
    ]
    if has_item_color:
        item_fields.append("restaurant_color")

    item_filters = {
        "disabled": 0,
        "is_sales_item": 1,
        "has_variants": 0,
        "is_fixed_asset": 0,
        "item_group": ["not in", ["Servicios", "Sub-ensambles", "Materia prima"]],
    }
    if allowed_categories:
        expanded_groups = _expand_item_groups(allowed_categories)
        if expanded_groups:
            item_filters["item_group"] = ["in", expanded_groups]

    raw_items = frappe.get_all(
        "Item",
        filters=item_filters,
        fields=item_fields,
        order_by="item_name asc",
        limit_page_length=300,
    )

    price_map = {}
    if frappe.has_permission("Item Price", "read"):
        price_rows = frappe.get_all(
            "Item Price",
            filters={"selling": 1},
            fields=["item_code", "price_list", "price_list_rate"],
            order_by="modified desc",
        )
        for row in price_rows:
            if selling_price_list and row.price_list == selling_price_list:
                price_map[row.item_code] = flt(row.price_list_rate, 2)
            elif row.item_code not in price_map:
                price_map[row.item_code] = flt(row.price_list_rate, 2)

    option_groups_by_item = {}
    if frappe.db.exists("DocType", "Restaurant Option Group"):
        groups = frappe.get_all(
            "Restaurant Option Group",
            filters={"disabled": 0},
            fields=["name", "main_item", "group_name", "min_selections", "max_selections", "currency"],
            order_by="creation asc",
        )
        group_names = [grp.name for grp in groups]
        opts_by_parent = {}
        if group_names:
            all_opts = frappe.get_all(
                "Restaurant Dish Option",
                filters={"parent": ["in", group_names], "parenttype": "Restaurant Option Group"},
                fields=[
                    "parent",
                    "option_label",
                    "effect",
                    "item_code",
                    "replaces_item",
                    "qty",
                    "uom",
                    "additional_amount",
                    "is_default",
                ],
                order_by="idx asc",
                limit_page_length=1000,
            )
            for opt in all_opts:
                opts_by_parent.setdefault(opt.parent, []).append(opt)
        for grp in groups:
            opts = opts_by_parent.get(grp.name, [])
            option_groups_by_item.setdefault(grp.main_item, []).append({
                "name": grp.name,
                "group_name": grp.group_name,
                "min_selections": cint(grp.min_selections),
                "max_selections": cint(grp.max_selections),
                "currency": grp.currency or "HNL",
                "options": [
                    {
                        "option_label": o.option_label,
                        "effect": o.effect,
                        "item_code": o.item_code or "",
                        "replaces_item": o.replaces_item or "",
                        "qty": flt(o.qty or 1),
                        "uom": o.uom or "",
                        "additional_amount": flt(o.additional_amount, 2),
                        "is_default": cint(o.is_default),
                    }
                    for o in opts
                ],
            })

    command_map = _resolve_command_map()

    tax_rate_by_item = {}
    item_codes = [item.name for item in raw_items]
    if item_codes:
        tax_rows = frappe.get_all(
            "Item Tax",
            filters={"parent": ["in", item_codes], "parenttype": "Item"},
            fields=["parent", "item_tax_template"],
            order_by="idx asc",
            limit_page_length=1000,
        )
        for row in tax_rows:
            if row.parent in tax_rate_by_item:
                continue
            tpl_name = (row.item_tax_template or "").upper()
            if "EXENTO" in tpl_name or "0%" in tpl_name:
                tax_rate_by_item[row.parent] = 0.0
            elif "18%" in tpl_name or "18" in tpl_name:
                tax_rate_by_item[row.parent] = 18.0
            elif "15%" in tpl_name or "15" in tpl_name:
                tax_rate_by_item[row.parent] = 15.0

    used_group_names = []
    for item in raw_items:
        if item.item_group and item.item_group not in used_group_names:
            used_group_names.append(item.item_group)

    group_fields = ["name", "item_group_name", "parent_item_group", "image"]
    if has_group_color:
        group_fields.append("restaurant_color")

    group_docs = (
        frappe.get_all(
            "Item Group",
            filters={"name": ["in", used_group_names]},
            fields=group_fields,
            order_by="lft asc",
        )
        if used_group_names
        else []
    )
    categories = []
    category_color_map = {}
    for idx, grp in enumerate(group_docs):
        color = (
            grp.get("restaurant_color")
            if has_group_color and grp.get("restaurant_color")
            else DEFAULT_CATEGORY_COLORS[idx % len(DEFAULT_CATEGORY_COLORS)]
        )
        category_color_map[grp.name] = color
        categories.append({
            "name": grp.name,
            "label": grp.item_group_name or grp.name,
            "image": grp.image or "",
            "color": color,
        })

    items = []
    for idx, item in enumerate(raw_items):
        base_price = price_map.get(item.name, flt(item.standard_rate, 2))
        item_color = (
            item.get("restaurant_color")
            if has_item_color and item.get("restaurant_color")
            else category_color_map.get(
                item.item_group, DEFAULT_ITEM_COLORS[idx % len(DEFAULT_ITEM_COLORS)]
            )
        )
        stations = command_map.get(item.item_group) or []
        opt_groups = option_groups_by_item.get(item.name, [])
        is_combo = any(
            any(opt.get("effect") == "Incluir en combo" for opt in grp.get("options", []))
            for grp in opt_groups
        )
        items.append({
            "item_code": item.name,
            "item_name": item.item_name or item.name,
            "description": cstr(item.description or item.item_name or item.name).strip(),
            "item_group": item.item_group,
            "uom": item.stock_uom or "Unidad",
            "image": item.image or "",
            "color": item_color,
            "price": flt(base_price, 2),
            "tax_rate": tax_rate_by_item.get(item.name, 15.0),
            "restaurant_recipe_enabled": cint(item.restaurant_recipe_enabled),
            "restaurant_options_enabled": cint(item.restaurant_options_enabled),
            "is_combo": bool(is_combo),
            "command_station": ", ".join(stations) if stations else "Cocina General",
            "option_groups": opt_groups,
        })

    return categories, items


def _get_areas_with_live_tables():
    """Return active Restaurant Areas with floor map elements and live table order status."""
    from restaurant.table_management import parse_area_layout

    if not frappe.has_permission("Restaurant Area", "read"):
        return []

    areas = frappe.get_list(
        "Restaurant Area",
        filters={"status": "Activa"},
        fields=[
            "name",
            "area_name",
            "branch",
            "capacity",
            "color",
            "icon",
            "floor_background",
            "layout_json",
            "display_order",
        ],
        order_by="display_order asc, area_name asc",
        limit_page_length=200,
    )
    if not areas:
        return []

    open_orders = frappe.get_all(
        "Restaurant Order",
        filters={"status": "En curso"},
        fields=[
            "name",
            "order_name",
            "restaurant_table",
            "waiter_name",
            "customer_name",
            "grand_total",
            "guests",
            "creation",
        ],
        order_by="creation asc",
    )
    active_by_table = {}
    for order in open_orders:
        if order.restaurant_table and order.restaurant_table not in active_by_table:
            created_dt = get_datetime(order.creation) if order.creation else now_datetime()
            mins = max(0, int((now_datetime() - created_dt).total_seconds() // 60))
            active_by_table[order.restaurant_table] = {
                "order_id": order.name,
                "order_name": order.order_name,
                "waiter_name": order.waiter_name or "",
                "customer_name": order.customer_name or "",
                "grand_total": flt(order.grand_total, 2),
                "guests": cint(order.guests or 1),
                "elapsed_label": f"{mins // 60:02d}:{mins % 60:02d}'",
            }

    tables_by_area = {}
    area_names = [area.name for area in areas]
    if area_names and frappe.has_permission("Restaurant Table", "read"):
        raw_tables = frappe.get_list(
            "Restaurant Table",
            filters={"restaurant_area": ["in", area_names]},
            fields=[
                "name",
                "restaurant_area",
                "branch",
                "table_number",
                "seats",
                "shape",
                "status",
                "display_order",
                "color",
                "notes",
                "modified",
            ],
            order_by="display_order asc, table_number asc",
            limit_page_length=1000,
        )
        for row in raw_tables:
            live = active_by_table.get(row.name)
            tables_by_area.setdefault(row.restaurant_area, []).append({
                "name": row.name,
                "restaurant_area": row.restaurant_area,
                "branch": row.branch,
                "table_number": row.table_number,
                "seats": row.seats,
                "shape": row.shape,
                "status": "Ocupada" if live else (row.status or "Disponible"),
                "display_order": row.display_order,
                "color": row.color,
                "notes": row.notes,
                "modified": row.modified,
                "active_order": live,
            })

    result = []
    for area in areas:
        result.append({
            "name": area.name,
            "area_name": area.area_name,
            "branch": area.branch,
            "capacity": cint(area.capacity),
            "color": area.color or "#22C55E",
            "icon": area.icon or "utensils",
            "floor_background": area.floor_background or "Madera cálida",
            "elements": parse_area_layout(area.layout_json),
            "tables": tables_by_area.get(area.name, []),
        })
    return result


def _resolve_sar_fiscal_info(pos_profile=None, company=None):
    """Resolve active SAR Honduras CAI, deadline, authorized range, prefix, and company RTN."""
    company = company or _get_default_company()
    company_tax_id = (
        frappe.db.get_value("Company", company, "tax_id") if company else ""
    ) or "05019000123456"

    prefix = ""
    if pos_profile and frappe.db.exists("POS Profile", pos_profile):
        if frappe.get_meta("POS Profile").has_field("prefix"):
            prefix = cstr(frappe.db.get_value("POS Profile", pos_profile, "prefix") or "").strip()

    cai_val = ""
    due_date_val = ""
    authorized_range_val = ""
    initial_num = ""
    final_num = ""

    if frappe.db.exists("DocType", "CAI"):
        cai_filters = {"status": "Active"}
        if prefix:
            cai_filters["prefix"] = prefix
        cai_rows = frappe.get_all(
            "CAI",
            filters=cai_filters,
            fields=["cai", "issue_deadline", "initial_number", "final_number", "prefix"],
            order_by="creation desc",
            limit=1,
        )
        if not cai_rows and prefix:
            cai_rows = frappe.get_all(
                "CAI",
                filters={"status": "Active"},
                fields=["cai", "issue_deadline", "initial_number", "final_number", "prefix"],
                order_by="creation desc",
                limit=1,
            )
        if cai_rows:
            row = cai_rows[0]
            cai_val = cstr(row.cai or "").strip()
            due_date_val = str(row.issue_deadline) if row.issue_deadline else ""
            prefix = prefix or cstr(row.prefix or "").strip()
            initial_num = cstr(row.initial_number or "").strip()
            final_num = cstr(row.final_number or "").strip()
            clean_pre = prefix.split(".")[0] if prefix else "000-001-01-"
            if initial_num and final_num:
                try:
                    authorized_range_val = (
                        f"{clean_pre}{int(initial_num):08d} al {clean_pre}{int(final_num):08d}"
                    )
                except Exception:
                    authorized_range_val = f"{clean_pre}{initial_num} al {clean_pre}{final_num}"

    if not cai_val:
        si_fields = ["cai", "due_date_cai"]
        if frappe.get_meta("Sales Invoice").has_field("authorized_range"):
            si_fields.append("authorized_range")
        last_cai = frappe.db.get_value(
            "Sales Invoice",
            {"cai": ["is", "set"]},
            si_fields,
            order_by="creation desc",
            as_dict=True,
        )
        if last_cai:
            cai_val = cstr(last_cai.get("cai") or "").strip()
            due_date_val = str(last_cai.get("due_date_cai")) if last_cai.get("due_date_cai") else ""
            authorized_range_val = cstr(last_cai.get("authorized_range") or "").strip()

    clean_prefix = (prefix.split(".")[0] if prefix else "000-001-01-") or "000-001-01-"
    return {
        "cai": cai_val or "3A8F9E-12B4C6-78D0E2-9F1A3B-45C6D8-01",
        "due_date_cai": due_date_val or "2026-12-31",
        "authorized_range": authorized_range_val or f"{clean_prefix}00000001 al {clean_prefix}00050000",
        "prefix": prefix or "000-001-01-.########",
        "company_tax_id": company_tax_id,
    }


@frappe.whitelist()
def get_pos_bootstrap(area_name=None):
    """Return all operational context needed to launch the Restaurant POS."""
    _require_pos_user()
    company = _get_default_company()
    default_profile = _get_default_pos_profile(company)
    opening_shift = _get_active_opening_shift(frappe.session.user)

    prof_meta = frappe.get_meta("POS Profile")
    prof_fields = ["name", "company", "currency", "selling_price_list", "warehouse", "customer"]
    optional_prof_fields = (
        "prefix",
        "hide_expected_amount",
        "close_pos_format",
        "cash_movements_format",
        "print_format_for_online",
        "letter_head",
    )
    for opt_field in optional_prof_fields:
        if prof_meta.has_field(opt_field):
            prof_fields.append(opt_field)
    raw_profiles = frappe.get_all(
        "POS Profile",
        filters={"disabled": 0},
        fields=prof_fields,
        order_by="creation asc",
    )
    payments_by_profile = {}
    profile_names = [prof.name for prof in raw_profiles]
    if profile_names:
        payment_rows = frappe.get_all(
            "POS Payment Method",
            filters={"parent": ["in", profile_names], "parenttype": "POS Profile"},
            fields=["parent", "mode_of_payment", "default"],
            order_by="idx asc",
            limit_page_length=500,
        )
        for prow in payment_rows:
            payments_by_profile.setdefault(prow.parent, []).append({
                "mode_of_payment": prow.mode_of_payment,
                "default": cint(prow.default),
            })

    default_customer_fallback = _get_default_customer()
    pos_profiles = []
    for prof in raw_profiles:
        payments = payments_by_profile.get(prof.name) or [
            {"mode_of_payment": "Efectivo", "default": 1}
        ]
        pos_profiles.append({
            "name": prof.name,
            "company": prof.company,
            "currency": prof.currency or "HNL",
            "selling_price_list": prof.selling_price_list or "Venta estándar",
            "warehouse": prof.warehouse or "",
            "default_customer": prof.customer or default_customer_fallback,
            "prefix": prof.get("prefix") or "",
            "hide_expected_amount": cint(prof.get("hide_expected_amount") or 0),
            "close_pos_format": prof.get("close_pos_format") or "",
            "cash_movements_format": prof.get("cash_movements_format") or "",
            "print_format_for_online": prof.get("print_format_for_online") or "",
            "letter_head": prof.get("letter_head") or "",
            "payments": payments,
        })

    companies_list = sorted({prof["company"] for prof in pos_profiles if prof.get("company")})
    if not companies_list and company:
        companies_list = [company]

    active_prof_name = (
        opening_shift["pos_profile"]
        if opening_shift and opening_shift.get("pos_profile")
        else (default_profile.name if default_profile else None)
    )
    rpos_config = _get_effective_rpos_config(active_prof_name)
    allowed_cats = (
        rpos_config.get("allowed_categories")
        if cint(rpos_config.get("restrict_categories")) and rpos_config.get("allowed_categories")
        else None
    )

    active_price_list = (
        default_profile.selling_price_list if default_profile else "Venta estándar"
    )
    categories, items = _get_catalog_for_pos(active_price_list, allowed_categories=allowed_cats)
    areas = _get_areas_with_live_tables()

    waiters = frappe.get_all(
        "Employee",
        filters={"designation": "Mesero", "status": "Active"},
        fields=["name", "employee_name", "branch"],
        order_by="employee_name asc",
    )

    cust_meta = frappe.get_meta("Customer")
    cust_fields = ["name", "customer_name", "tax_id", "default_price_list"]
    for extra_cf in ("email_id", "mobile_no", "primary_address", "territory"):
        if cust_meta.has_field(extra_cf):
            cust_fields.append(extra_cf)

    raw_customers = frappe.get_all(
        "Customer",
        filters={"disabled": 0},
        fields=cust_fields,
        order_by="customer_name asc",
        limit_page_length=200,
    )
    customers = []
    for c in raw_customers:
        addr_clean = cstr(c.get("primary_address") or c.get("territory") or "").replace("<br>", ", ").replace("\n", ", ").strip(" ,")
        customers.append({
            "name": c.name,
            "customer_name": c.customer_name,
            "tax_id": c.tax_id or "",
            "default_price_list": c.default_price_list or "",
            "email_id": cstr(c.get("email_id") or ""),
            "mobile_no": cstr(c.get("mobile_no") or ""),
            "address": addr_clean,
        })

    price_lists = frappe.get_all(
        "Price List",
        filters={"selling": 1, "enabled": 1},
        fields=["name", "currency"],
        order_by="name asc",
    )

    mop_filters = {"enabled": 1}
    if rpos_config.get("enabled_payments"):
        mop_filters["name"] = ["in", rpos_config["enabled_payments"]]
    modes_of_payment = frappe.get_all(
        "Mode of Payment",
        filters=mop_filters,
        fields=["name", "type"],
        order_by="name asc",
    )


    linked_waiter = get_linked_employee_for_user()
    active_branch = _get_active_user_branch(opening_shift=opening_shift, linked_waiter=linked_waiter)
    waiter_only = is_waiter_only()
    can_invoice = user_can_invoice()
    supervisor_flag = is_supervisor()

    order_filters = {}
    if company and frappe.get_meta("Restaurant Order").has_field("company"):
        order_filters["company"] = company
    if active_branch and frappe.get_meta("Restaurant Order").has_field("branch"):
        order_filters["branch"] = active_branch
    if not cint(rpos_config.get("share_open_orders", 1)):
        order_filters["owner"] = frappe.session.user
    if waiter_only and linked_waiter:
        order_filters["waiter"] = linked_waiter["name"]

    order_docs = frappe.get_all(
        "Restaurant Order",
        filters=order_filters,
        fields=["name", "order_name"],
        order_by="modified desc",
        limit_page_length=100,
    )
    for row in order_docs:
        raw_oname = cstr(row.order_name or "").strip()
        if re.match(r"^orden\s+\d+", raw_oname, flags=re.IGNORECASE):
            m_seq = re.search(r"(\d+)$", cstr(row.name or ""))
            if m_seq:
                clean_seq = str(1000 + cint(m_seq.group(1)))
                frappe.db.set_value("Restaurant Order", row.name, "order_name", clean_seq, update_modified=False)
    orders = [_serialize_order(row.name) for row in order_docs]

    fiscal_info = _resolve_sar_fiscal_info(pos_profile=active_prof_name, company=company)

    if active_prof_name:
        try:
            profile_cfg = get_restaurant_pos_config(pos_profile=active_prof_name)
            for k, v in profile_cfg.items():
                if k not in rpos_config or rpos_config[k] is None:
                    rpos_config[k] = v
        except Exception:
            frappe.log_error("Failed to load restaurant POS config in bootstrap", "Restaurant POS")

    return {
        "cashier": {
            "user": frappe.session.user,
            "full_name": get_fullname(frappe.session.user),
        },
        "permissions": {
            "can_invoice": can_invoice,
            "is_waiter_only": waiter_only,
            "is_cashier_only": is_cashier_only(),
            "is_direct_cashier": is_direct_cashier(),
            "can_manage_tables": not is_direct_cashier(),
            "can_create_accounts": not is_direct_cashier(),
            "can_access_backend": supervisor_flag,
            "is_supervisor": supervisor_flag,
            "requires_supervisor_auth": not supervisor_flag,
            "linked_waiter": linked_waiter,
        },
        "supervisors": get_supervisors_for_pos(branch=active_branch),
        "company": {
            "name": company or "Empresa Demostrativa",
            "tax_id": fiscal_info["company_tax_id"],
            "currency": "HNL",
        },
        "opening_shift": opening_shift,
        "companies": companies_list,
        "pos_profiles": pos_profiles,
        "areas": areas,
        "categories": categories,
        "items": items,
        "waiters": waiters,
        "customers": customers,
        "price_lists": price_lists,
        "modes_of_payment": modes_of_payment,
        "orders": orders,
        "command_stations": get_command_stations(),
        "command_configs": get_command_configs(),
        "presets": get_order_presets(),
        "idle_wallpaper": get_pos_idle_settings(),
        "rpos_config": rpos_config,
        "fiscal_defaults": {
            "cai": fiscal_info["cai"],
            "due_date_cai": fiscal_info["due_date_cai"],
            "authorized_range": fiscal_info["authorized_range"],
            "prefix": fiscal_info["prefix"],
        },
    }


@frappe.whitelist(methods=["POST"])
def open_pos_shift(pos_profile=None, opening_amount=0, balance_details=None, company=None):
    """Open or reuse a native POS Opening Shift for the logged-in cashier."""
    _require_pos_user()
    if not user_can_invoice():
        frappe.throw(
            _("Solo cajeros o supervisores pueden abrir turnos de caja."),
            frappe.PermissionError,
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

    if frappe.db.exists("DocType", "POS Closing Shift"):
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

    invoices = frappe.get_all(
        "Sales Invoice",
        filters={"posa_pos_opening_shift": opening_doc.name, "docstatus": 1},
        fields=["name", "customer", "customer_name", "grand_total", "paid_amount", "change_amount", "posting_date"],
        order_by="creation desc",
    )
    invoice_names = [inv.name for inv in invoices]
    paid_by_mop = {}
    if invoice_names:
        payment_rows = frappe.get_all(
            "Sales Invoice Payment",
            filters={"parent": ["in", invoice_names], "parenttype": "Sales Invoice"},
            fields=["parent", "mode_of_payment", "amount"],
        )
        change_by_inv = {inv.name: flt(inv.change_amount, 2) for inv in invoices}
        for prow in payment_rows:
            mop = prow.mode_of_payment
            amt = flt(prow.amount, 2)
            if "efectivo" in mop.lower() or "cash" in mop.lower():
                amt -= flt(change_by_inv.get(prow.parent, 0.0), 2)
                change_by_inv[prow.parent] = 0.0
            paid_by_mop[mop] = flt(paid_by_mop.get(mop, 0.0) + amt, 2)

    payment_reconciliation = []
    seen_mops = set()
    cash_mop_applied = False
    for b_row in (opening_doc.balance_details or []):
        mop = b_row.mode_of_payment
        seen_mops.add(mop)
        opening_amt = flt(b_row.amount, 2)
        sales_amt = flt(paid_by_mop.get(mop, 0.0), 2)
        is_cash = "efectivo" in mop.lower() or "cash" in mop.lower() or not cash_mop_applied
        cash_net = cash_movements["net_cash_movement"] if is_cash and not cash_mop_applied else 0.0
        if is_cash and not cash_mop_applied:
            cash_mop_applied = True
        expected_amt = flt(opening_amt + sales_amt + cash_net, 2)
        payment_reconciliation.append({
            "mode_of_payment": mop,
            "is_cash": cint(is_cash),
            "opening_amount": opening_amt,
            "sales_amount": sales_amt,
            "cash_movement_net": flt(cash_net, 2),
            "expected_amount": expected_amt,
            "closing_amount": expected_amt,
            "difference": 0.0,
        })

    for mop, sales_amt in paid_by_mop.items():
        if mop in seen_mops:
            continue
        is_cash = "efectivo" in mop.lower() or "cash" in mop.lower()
        payment_reconciliation.append({
            "mode_of_payment": mop,
            "is_cash": cint(is_cash),
            "opening_amount": 0.0,
            "sales_amount": flt(sales_amt, 2),
            "cash_movement_net": 0.0,
            "expected_amount": flt(sales_amt, 2),
            "closing_amount": flt(sales_amt, 2),
            "difference": 0.0,
        })

    total_sales = sum(flt(inv.grand_total, 2) for inv in invoices)
    return {
        "pos_opening_shift": opening_doc.name,
        "pos_profile": opening_doc.pos_profile,
        "company": opening_doc.company,
        "currency": currency,
        "hide_expected_amount": hide_expected_amount,
        "user": opening_doc.user,
        "cashier_name": get_fullname(opening_doc.user),
        "period_start_date": str(opening_doc.period_start_date),
        "invoice_count": len(invoices),
        "total_sales": flt(total_sales, 2),
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
    if doc.user != frappe.session.user and "System Manager" not in frappe.get_roles():
        frappe.throw(_("Solo el cajero titular o un administrador puede cerrar este turno."), frappe.PermissionError)

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

    closing_shift_name = ""
    if frappe.db.exists("DocType", "POS Closing Shift"):
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
    else:
        frappe.db.set_value("POS Opening Shift", doc.name, {
            "status": "Closed",
            "period_end_date": nowdate(),
        })

    if frappe.db.get_value("POS Opening Shift", doc.name, "status") != "Closed":
        frappe.db.set_value("POS Opening Shift", doc.name, {
            "status": "Closed",
            "period_end_date": nowdate(),
        })

    return {
        "closed": doc.name,
        "pos_closing_shift": closing_shift_name,
    }


def _get_next_order_sequence_number():
    """Compute the next strict +1 sequential account number from the database."""
    rows = frappe.db.sql(
        "SELECT name, order_name FROM `tabRestaurant Order` ORDER BY creation DESC LIMIT 200 FOR UPDATE",
        as_dict=True,
    )
    max_seq = 1000
    for r in rows:
        m_id = re.search(r"(\d+)$", cstr(r.name or ""))
        if m_id:
            seq_from_id = 1000 + cint(m_id.group(1))
            if seq_from_id > max_seq:
                max_seq = seq_from_id
        raw_oname = cstr(r.order_name or "").strip()
        if re.match(r"^\d{4}$", raw_oname):
            num_val = cint(raw_oname)
            if 1000 <= num_val < 3000 and num_val > max_seq:
                max_seq = num_val
    return str(max_seq + 1)


@frappe.whitelist(methods=["POST"])
def save_pos_order(order):
    """Create or update a Restaurant Order and return its updated state."""
    _require_pos_user()
    payload = frappe.parse_json(order) if isinstance(order, str) else order
    if not isinstance(payload, dict):
        frappe.throw(_("Los datos de la orden no tienen un formato válido."))
    if is_direct_cashier() and payload.get("restaurant_table"):
        frappe.throw(
            _("Tu perfil de facturación directa no permite asignar mesas."),
            frappe.PermissionError,
        )

    order_id = cstr(payload.get("name") or "").strip()
    if order_id:
        if not frappe.db.exists("Restaurant Order", order_id):
            frappe.throw(_("La cuenta u orden solicitada no existe."), frappe.DoesNotExistError)
        doc = frappe.get_doc("Restaurant Order", order_id)
        doc.check_permission("write")
        if doc.status == "Facturada":
            frappe.throw(_("Esta orden ya fue facturada y no puede modificarse."))
        expected_modified = cstr(payload.get("expected_modified") or "").strip()
        if expected_modified and cstr(doc.modified) != expected_modified:
            frappe.throw(
                _("Esta orden fue modificada recientemente por otro usuario. Recarga la cuenta antes de guardar cambios.")
            )
    else:
        if not frappe.has_permission("Restaurant Order", "create"):
            frappe.throw(_("No tienes permisos para abrir cuentas u órdenes."), frappe.PermissionError)
        doc = frappe.new_doc("Restaurant Order")

    active_shift = _get_active_opening_shift(frappe.session.user)
    effective_profile = (
        payload.get("pos_profile")
        or doc.pos_profile
        or (active_shift["pos_profile"] if active_shift else None)
    )
    rpos_cfg = _get_effective_rpos_config(effective_profile)

    if order_id and not cint(rpos_cfg.get("share_open_orders", 1)) and doc.owner != frappe.session.user:
        user_roles = set(frappe.get_roles(frappe.session.user))
        if not (user_roles & {"System Manager", "Restaurant Manager", "Administrator"}):
            frappe.throw(_("No tienes autorización para modificar órdenes abiertas de otro usuario."), frappe.PermissionError)


    linked_waiter = get_linked_employee_for_user()
    if is_waiter_only():
        if linked_waiter:
            if order_id and doc.waiter and doc.waiter != linked_waiter["name"]:
                frappe.throw(
                    _("Esta cuenta pertenece a otro mesero y no puedes modificarla."),
                    frappe.PermissionError,
                )
        elif order_id and doc.waiter and employee_has_pin(doc.waiter):
            if not is_order_unlocked_for_session(doc.name):
                waiter_pin = payload.get("waiter_pin")
                pin_cache_key = _enforce_pin_rate_limit(f"waiter:{doc.waiter}")
                if waiter_pin and verify_employee_pin(doc.waiter, waiter_pin):
                    _clear_pin_failures(pin_cache_key)
                    mark_order_unlocked_for_session(doc.name)
                else:
                    _record_pin_failure(pin_cache_key)
                    frappe.throw(
                        _("Código incorrecto. Solo el mesero asignado ({0}) o un supervisor puede abrir esta cuenta.").format(
                            doc.waiter_name or doc.waiter
                        ),
                        frappe.PermissionError,
                    )

    if not cint(rpos_cfg.get("tips_enabled", 1)):
        if flt(payload.get("tip_amount")) > 0 or flt(payload.get("tip_percentage")) > 0:
            frappe.throw(_("Las propinas están deshabilitadas en la configuración del POS."))

    if not cint(rpos_cfg.get("allow_line_discount", 1)):
        for row in (payload.get("items") or []):
            if isinstance(row, dict) and flt(row.get("discount_percentage")) > 0:
                frappe.throw(_("Los descuentos por línea están deshabilitados en la configuración del POS."), frappe.PermissionError)

    if is_waiter_only() and "selling_price_list" in payload:
        incoming_pl = cstr(payload.get("selling_price_list") or "").strip()
        current_pl = cstr(doc.selling_price_list or "").strip()
        if order_id and incoming_pl and current_pl and incoming_pl != current_pl:
            frappe.throw(_("Tu rol de mesero no tiene permiso para cambiar la lista de precios."), frappe.PermissionError)

    editable_fields = (
        "order_name",
        "reference_note",
        "service_type",
        "restaurant_area",
        "restaurant_table",
        "guests",
        "waiter",
        "customer",
        "tax_id",
        "pos_profile",
        "pos_opening_shift",
        "selling_price_list",
        "scheduled_time",
        "customer_note",
        "tip_percentage",
        "tip_amount",
    )
    for field in editable_fields:
        if field in payload:
            doc.set(field, payload.get(field))

    if is_waiter_only() and linked_waiter and not order_id:
        doc.waiter = linked_waiter["name"]

    raw_order_name = cstr(doc.order_name or "").strip()
    if not raw_order_name or re.match(r"^orden\s+\d{4}$", raw_order_name, flags=re.IGNORECASE):
        if doc.restaurant_table:
            tbl_num = frappe.db.get_value("Restaurant Table", doc.restaurant_table, "table_number") or doc.restaurant_table
            doc.order_name = f"Mesa {tbl_num}"
        else:
            doc.order_name = _get_next_order_sequence_number()

    if not doc.pos_opening_shift:
        active_shift = _get_active_opening_shift(frappe.session.user)
        if active_shift:
            doc.pos_opening_shift = active_shift["name"]
            doc.pos_profile = doc.pos_profile or active_shift["pos_profile"]
            doc.company = doc.company or active_shift["company"]

    if "items" in payload and isinstance(payload.get("items"), list):
        existing_rows = {r.name: r for r in (doc.items or []) if getattr(r, "name", None)}
        incoming_names = {
            cstr(r.get("name") or "").strip()
            for r in payload["items"]
            if isinstance(r, dict) and r.get("item_code") and cstr(r.get("name") or "").strip()
        }
        for old_name, old_row in existing_rows.items():
            old_kds = cstr(getattr(old_row, "kds_status", "") or "Pendiente")
            old_cancelled = cint(getattr(old_row, "is_cancelled", 0)) or old_kds == "Cancelado"
            if old_kds not in ("", "Pendiente") and not old_cancelled and old_name not in incoming_names:
                log_restaurant_audit(
                    "Intento de eliminar producto enviado a cocina",
                    f"Usuario {frappe.session.user} intentó eliminar {old_row.item_name or old_row.item_code} sin autorización.",
                    order_name=doc.name,
                    result="Bloqueado",
                    item_code=old_row.item_code,
                    item_name=old_row.item_name,
                    affected_qty=old_row.qty,
                    previous_state=old_kds,
                    resulting_state=old_kds,
                )
                frappe.throw(
                    _("No puedes eliminar '{0}' porque ya fue enviado a cocina. Solicita autorización de un supervisor.").format(
                        old_row.item_name or old_row.item_code
                    ),
                    frappe.PermissionError,
                )

        item_rows = []
        for raw_row in payload["items"]:
            if not isinstance(raw_row, dict) or not raw_row.get("item_code"):
                continue
            row_name = cstr(raw_row.get("name") or "").strip()
            old_row = existing_rows.get(row_name)
            if old_row and (cint(getattr(old_row, "is_cancelled", 0)) or old_row.kds_status == "Cancelado"):
                item_rows.append(old_row)
                continue

            selected_options = raw_row.get("selected_options") or []
            if isinstance(selected_options, str):
                try:
                    selected_options = json.loads(selected_options)
                except Exception:
                    selected_options = []
            options_rate = 0.0
            summary_parts = []
            for opt in selected_options:
                if isinstance(opt, dict):
                    label = cstr(opt.get("option_label") or "").strip()
                    add_amt = flt(opt.get("additional_amount"), 2)
                    options_rate += add_amt
                    if label:
                        summary_parts.append(
                            f"{label} (+L {add_amt:.2f})" if add_amt > 0 else label
                        )
            if raw_row.get("options_rate") is not None and not selected_options:
                options_rate = flt(raw_row.get("options_rate"), 2)

            qty = flt(raw_row.get("qty") or 1)
            kds_status = raw_row.get("kds_status") or "Pendiente"
            if old_row:
                if old_row.kds_status not in (None, "", "Pendiente"):
                    if abs(flt(old_row.qty) - qty) > 0.001:
                        frappe.throw(_("No se puede modificar la cantidad de un platillo que ya fue enviado a cocina."), frappe.ValidationError)
                    kds_status = old_row.kds_status

            row_data = {
                "item_code": raw_row.get("item_code"),
                "item_name": raw_row.get("item_name"),
                "item_group": raw_row.get("item_group"),
                "qty": qty,
                "uom": raw_row.get("uom"),
                "base_rate": flt(raw_row.get("base_rate") if raw_row.get("base_rate") is not None else raw_row.get("rate") or 0),
                "options_rate": flt(options_rate, 2),
                "discount_percentage": flt(raw_row.get("discount_percentage") or 0),
                "tax_rate": raw_row.get("tax_rate"),
                "options_summary": raw_row.get("options_summary") or ", ".join(summary_parts),
                "selected_options_json": json.dumps(selected_options, ensure_ascii=False),
                "note": cstr(raw_row.get("note") or "").strip(),
                "command_station": raw_row.get("command_station"),
                "kds_status": kds_status,
            }
            if old_row:
                row_data["name"] = old_row.name
            item_rows.append(row_data)

        for old_name, old_row in existing_rows.items():
            if (cint(getattr(old_row, "is_cancelled", 0)) or old_row.kds_status == "Cancelado") and old_name not in incoming_names:
                item_rows.append(old_row)

        doc.set("items", item_rows)

    if doc.is_new():
        doc.insert()
        if doc.waiter:
            mark_order_unlocked_for_session(doc.name)
    else:
        doc.save()

    return {
        "order": _serialize_order(doc),
        "areas": _get_areas_with_live_tables(),
    }


def _row_stations(row):
    """Split the comma-separated station list stored on an order line."""
    names = [part.strip() for part in cstr(row.command_station or "").split(",") if part.strip()]
    return names or ["Cocina General"]


def get_command_stations():
    """Return enabled Restaurant Command station names plus the general fallback."""
    names = []
    if frappe.db.exists("DocType", "Restaurant Command"):
        names = frappe.get_all(
            "Restaurant Command",
            filters={"enabled": 1},
            pluck="command_name",
            order_by="command_name asc",
        )
    if "Cocina General" not in names:
        names.append("Cocina General")
    return names


def get_command_configs():
    """Return enabled Restaurant Command documents with their category mappings and printer configuration."""
    if not frappe.db.exists("DocType", "Restaurant Command"):
        return []
    cmd_meta = frappe.get_meta("Restaurant Command")
    cmd_fields = ["name", "command_name", "branch", "enabled"]
    for extra_f in ("print_mode", "network_printer", "printer_ip", "printer_port", "paper_width_mm", "auto_print_on_send"):
        if cmd_meta.has_field(extra_f):
            cmd_fields.append(extra_f)
    rows = frappe.get_all(
        "Restaurant Command",
        filters={"enabled": 1},
        fields=cmd_fields,
        order_by="command_name asc",
    )
    configs = []
    for row in rows:
        groups = frappe.get_all(
            "Restaurant Command Group",
            filters={"parent": row.name, "parenttype": "Restaurant Command"},
            pluck="item_group",
        )
        configs.append({
            "name": row.name,
            "command_name": row.command_name,
            "branch": row.branch or "",
            "print_mode": row.get("print_mode") or "Impresora del navegador (Ticket térmico)",
            "network_printer": row.get("network_printer") or "",
            "printer_ip": row.get("printer_ip") or "",
            "printer_port": cint(row.get("printer_port") or 9100),
            "paper_width_mm": row.get("paper_width_mm") or "80mm",
            "auto_print_on_send": cint(row.get("auto_print_on_send") if row.get("auto_print_on_send") is not None else 1),
            "groups": groups,
        })
    return configs


def get_order_presets():
    """Return active order presets (Comer en el local, Para llevar, Entrega) with scheduling and customer rules."""
    default_presets = [
        {
            "preset_name": "Comer en el local",
            "color_bg": "#cce3fd",
            "color_border": "#3b82f6",
            "is_default": 1,
            "require_customer": 0,
            "enable_scheduling": 0,
            "slot_interval_minutes": 20,
            "schedule_start_time": "12:00",
            "schedule_end_time": "22:00",
        },
        {
            "preset_name": "Para llevar",
            "color_bg": "#fef0a6",
            "color_border": "#eab308",
            "is_default": 0,
            "require_customer": 0,
            "enable_scheduling": 1,
            "slot_interval_minutes": 20,
            "schedule_start_time": "12:00",
            "schedule_end_time": "22:00",
        },
        {
            "preset_name": "Entrega",
            "color_bg": "#fcd5b5",
            "color_border": "#f97316",
            "is_default": 0,
            "require_customer": 1,
            "enable_scheduling": 1,
            "slot_interval_minutes": 20,
            "schedule_start_time": "12:00",
            "schedule_end_time": "22:00",
        },
    ]
    if frappe.db.table_exists("Restaurant Order Preset"):
        preset_meta = frappe.get_meta("Restaurant Order Preset")
        preset_fields = ["name", "preset_name", "color_bg", "color_border", "is_default"]
        for extra_pf in ("require_customer", "enable_scheduling", "slot_interval_minutes", "schedule_start_time", "schedule_end_time"):
            if preset_meta.has_field(extra_pf):
                preset_fields.append(extra_pf)
        records = frappe.get_all(
            "Restaurant Order Preset",
            filters={"enabled": 1},
            fields=preset_fields,
            order_by="idx asc, creation asc",
        )
        if records:
            for rec in records:
                if rec.preset_name in ("Para llevar", "Entrega") and not rec.get("enable_scheduling"):
                    rec["enable_scheduling"] = 1
                if rec.preset_name == "Entrega" and not rec.get("require_customer"):
                    rec["require_customer"] = 1
                rec["slot_interval_minutes"] = cint(rec.get("slot_interval_minutes") or 20)
                rec["schedule_start_time"] = cstr(rec.get("schedule_start_time") or "12:00")
                rec["schedule_end_time"] = cstr(rec.get("schedule_end_time") or "22:00")
            return records
        for p in default_presets:
            if not frappe.db.exists("Restaurant Order Preset", p["preset_name"]):
                doc_data = {
                    "doctype": "Restaurant Order Preset",
                    "preset_name": p["preset_name"],
                    "color_bg": p["color_bg"],
                    "color_border": p["color_border"],
                    "is_default": p["is_default"],
                    "enabled": 1,
                }
                if preset_meta.has_field("require_customer"):
                    doc_data["require_customer"] = p["require_customer"]
                    doc_data["enable_scheduling"] = p["enable_scheduling"]
                    doc_data["slot_interval_minutes"] = p["slot_interval_minutes"]
                    doc_data["schedule_start_time"] = p["schedule_start_time"]
                    doc_data["schedule_end_time"] = p["schedule_end_time"]
                doc = frappe.get_doc(doc_data)
                doc.insert(ignore_permissions=True)
        return frappe.get_all(
            "Restaurant Order Preset",
            filters={"enabled": 1},
            fields=preset_fields,
            order_by="idx asc, creation asc",
        )
    return default_presets


def _dispatch_station_print_jobs(doc, stations, sent_at):
    """Non-blocking dispatch of station tickets to configured network/ESC-POS printers."""
    import socket

    configs = {cfg["command_name"]: cfg for cfg in get_command_configs()}
    results = {}
    for station_name, lines in (stations or {}).items():
        cfg = configs.get(station_name) or {
            "command_name": station_name,
            "print_mode": "Impresora del navegador (Ticket térmico)",
            "auto_print_on_send": 1,
            "paper_width_mm": "80mm",
        }
        mode = cfg.get("print_mode") or "Impresora del navegador (Ticket térmico)"
        auto_print = cint(cfg.get("auto_print_on_send", 1))
        entry = {
            "station": station_name,
            "print_mode": mode,
            "auto_print_on_send": auto_print,
            "paper_width_mm": cfg.get("paper_width_mm") or "80mm",
            "dispatched_to_hardware": False,
            "browser_print": bool(auto_print and mode == "Impresora del navegador (Ticket térmico)"),
            "warning": "",
        }
        if not auto_print or mode == "Solo KDS (Sin impresión automática)":
            results[station_name] = entry
            continue

        ip_addr = cstr(cfg.get("printer_ip") or "").strip()
        port_num = cint(cfg.get("printer_port") or 9100)
        if mode == "Network Printer Settings (Frappe Nativo)" and cfg.get("network_printer"):
            if frappe.db.exists("Network Printer Settings", cfg["network_printer"]):
                np_doc = frappe.db.get_value(
                    "Network Printer Settings",
                    cfg["network_printer"],
                    ["server_ip", "port"],
                    as_dict=True,
                )
                if np_doc and np_doc.server_ip:
                    ip_addr = cstr(np_doc.server_ip).strip()
                    port_num = cint(np_doc.port or 9100)

        if ip_addr and mode in (
            "Impresora de red directa (ESC/POS IP:Puerto)",
            "Network Printer Settings (Frappe Nativo)",
        ):
            try:
                header = (
                    f"\x1b@\x1ba\x01COMANDA - {station_name.upper()}\n"
                    f"\x1ba\x00Cuenta: {doc.order_name}\n"
                    f"Mesa/Servicio: {doc.table_label or doc.service_type}\n"
                    f"Hora: {sent_at}\n"
                    + ("-" * 32) + "\n"
                )
                body = ""
                for l in lines:
                    body += f"{l['qty']:g} x {l['item_name']}\n"
                    if l.get("options_summary"):
                        body += f"  - {l['options_summary']}\n"
                    if l.get("note"):
                        body += f"  ** {l['note']} **\n"
                footer = ("-" * 32) + "\n\n\n\x1dV\x00"
                raw_bytes = (header + body + footer).encode("cp850", errors="replace")
                with socket.create_connection((ip_addr, port_num), timeout=1.5) as sock:
                    sock.sendall(raw_bytes)
                entry["dispatched_to_hardware"] = True
            except Exception as exc:
                entry["warning"] = cstr(exc)[:140]
                entry["browser_print"] = True
        results[station_name] = entry
    return results


@frappe.whitelist(methods=["POST"])
def send_order_to_kitchen(order_name, station=None, include_sent=0):
    """Send pending lines of an order to one station (or all) and return printable station tickets.

    Only lines still in "Pendiente" are sent unless include_sent is set (reprint).
    """
    _require_pos_user()
    if not order_name or not frappe.db.exists("Restaurant Order", order_name):
        frappe.throw(_("Guarda la cuenta u orden antes de enviarla a cocina."))
    doc = frappe.get_doc("Restaurant Order", order_name)
    doc.check_permission("write")
    if not doc.items:
        frappe.throw(_("Agrega al menos un platillo o bebida antes de enviar la comanda a cocina."))

    target_station = cstr(station).strip()
    if target_station in ("", "ALL", "Todas"):
        target_station = ""
    reprint = cint(include_sent)

    stations = {}
    for row in doc.items:
        row_stations = _row_stations(row)
        if target_station and target_station not in row_stations:
            continue
        if not reprint and row.kds_status != "Pendiente":
            continue
        if row.kds_status == "Pendiente":
            row.kds_status = "En preparación"
        for station_name in row_stations:
            if target_station and station_name != target_station:
                continue
            stations.setdefault(station_name, []).append({
                "item_name": row.item_name,
                "qty": flt(row.qty),
                "options_summary": row.options_summary or "",
                "note": row.note or "",
            })

    if not stations:
        frappe.throw(
            _("No hay platillos pendientes de comandar para {0}.").format(
                target_station or _("ninguna estación")
            )
        )

    doc.sent_to_kitchen_at = now_datetime()
    if doc.kds_status == "Sin enviar":
        doc.kds_status = "En preparación"
    doc.save()
    sent_at_str = f"{nowdate()} {nowtime()[:8]}"
    print_jobs = _dispatch_station_print_jobs(doc, stations, sent_at_str)
    return {
        "order": _serialize_order(doc),
        "areas": _get_areas_with_live_tables(),
        "stations": stations,
        "print_jobs": print_jobs,
        "sent_at": sent_at_str,
    }


@frappe.whitelist(methods=["POST"])
def get_precuenta_data(order_name, tip_percentage=None, tip_amount=None):
    """Return formatted non-fiscal Pre-cuenta data for customer review before invoicing."""
    _require_pos_user()
    if not order_name or not frappe.db.exists("Restaurant Order", order_name):
        frappe.throw(_("La cuenta u orden solicitada no existe."), frappe.DoesNotExistError)
    doc = frappe.get_doc("Restaurant Order", order_name)
    doc.check_permission("read")

    if doc.status == "En curso" and doc.has_permission("write"):
        if tip_percentage is not None:
            doc.tip_percentage = max(0.0, flt(tip_percentage, 2))
            if doc.tip_percentage == 0 and tip_amount is not None:
                doc.tip_amount = max(0.0, flt(tip_amount, 2))
        elif tip_amount is not None:
            doc.tip_percentage = 0.0
            doc.tip_amount = max(0.0, flt(tip_amount, 2))
        doc.precuenta_printed = 1
        doc.save()

    company_name = doc.company or _get_default_company() or "Empresa Demostrativa"
    company_rtn = frappe.db.get_value("Company", company_name, "tax_id") or "05019000123456"

    return {
        "company_name": company_name,
        "company_rtn": company_rtn,
        "printed_at": f"{nowdate()} {nowtime()[:8]}",
        "order": _serialize_order(doc),
    }


def _resolve_payment_account(mode_of_payment, company):
    """Ensure the chosen Mode of Payment has a valid ledger account for the company."""
    account = frappe.db.get_value(
        "Mode of Payment Account",
        {"parent": mode_of_payment, "company": company},
        "default_account",
    )
    if account:
        return account
    fallback = frappe.db.get_value(
        "Account",
        {"company": company, "account_type": ["in", ["Cash", "Bank"]], "is_group": 0},
        "name",
    )
    if fallback and frappe.db.exists("Mode of Payment", mode_of_payment):
        mop_doc = frappe.get_doc("Mode of Payment", mode_of_payment)
        mop_doc.append("accounts", {"company": company, "default_account": fallback})
        mop_doc.save(ignore_permissions=True)
        return fallback
    return fallback


def _resolve_tax_account(company, rate=15.0):
    """Return the native Honduras ISV tax account head for the company."""
    search_token = "18%" if abs(rate - 18.0) < 0.01 else "15%"
    acc = frappe.db.get_value(
        "Account",
        {"company": company, "name": ["like", f"%{search_token}%"], "is_group": 0},
        "name",
    )
    if acc:
        return acc
    tpl = frappe.db.get_value(
        "Sales Taxes and Charges Template",
        {"company": company, "is_default": 1},
        "name",
    )
    if tpl:
        row_acc = frappe.db.get_value(
            "Sales Taxes and Charges",
            {"parent": tpl, "parenttype": "Sales Taxes and Charges Template"},
            "account_head",
        )
        if row_acc:
            return row_acc
    return frappe.db.get_value(
        "Account",
        {"company": company, "account_type": "Tax", "is_group": 0},
        "name",
    )


def _resolve_service_income_account(company):
    """Return the income account used to record suggested service / tips."""
    for candidate in ("Servicios", "Ventas"):
        acc = frappe.db.get_value(
            "Account",
            {"company": company, "name": ["like", f"%{candidate}%"], "root_type": "Income", "is_group": 0},
            "name",
        )
        if acc:
            return acc
    return frappe.db.get_value(
        "Account",
        {"company": company, "root_type": "Income", "is_group": 0},
        "name",
    )


@frappe.whitelist(methods=["POST"])
def pay_and_invoice_order(
    order_name,
    payments=None,
    customer=None,
    tax_id=None,
    cai=None,
    due_date_cai=None,
    authorized_range=None,
    tip_percentage=None,
    tip_amount=None,
    global_discount_percentage=None,
    global_discount_amount=None,
    coupon_code=None,
    gift_card_code=None,
    gift_card_amount=None,
    loyalty_points=None,
):
    """Emit and submit a native SAR Sales Invoice for a Restaurant Order and free its table."""
    _require_pos_user()
    if not user_can_invoice():
        frappe.throw(
            _("No tienes permiso para cobrar ni emitir facturas SAR. Solicita al cajero o supervisor."),
            frappe.PermissionError,
        )
    if not order_name or not frappe.db.exists("Restaurant Order", order_name):
        frappe.throw(_("La cuenta u orden seleccionada no existe."), frappe.DoesNotExistError)

    frappe.db.get_value("Restaurant Order", order_name, "name", for_update=True)
    doc = frappe.get_doc("Restaurant Order", order_name)
    doc.check_permission("write")
    if doc.status == "Facturada" or doc.sales_invoice:
        frappe.throw(_("Esta cuenta ya fue facturada en el documento {0}.").format(doc.sales_invoice or doc.name))
    if doc.status == "Cancelada" or doc.docstatus == 2:
        frappe.throw(_("No se puede facturar una orden cancelada."))
    if not doc.items:
        frappe.throw(_("No puedes facturar una orden sin platillos ni productos."))

    company = doc.company or _get_default_company()
    pos_profile = doc.pos_profile
    if not pos_profile:
        default_prof = _get_default_pos_profile(company)
        pos_profile = default_prof.name if default_prof else None
    rpos_cfg = _get_effective_rpos_config(pos_profile)

    if not cint(rpos_cfg.get("tips_enabled", 1)):
        if flt(tip_amount) > 0 or flt(tip_percentage) > 0 or flt(doc.tip_amount) > 0:
            frappe.throw(_("Las propinas están deshabilitadas en la configuración del POS."))

    if not cint(rpos_cfg.get("allow_line_discount", 1)):
        for row in doc.items:
            if cint(getattr(row, "is_cancelled", 0)) or row.kds_status == "Cancelado":
                continue
            if flt(row.discount_percentage) > 0:
                frappe.throw(_("Los descuentos por línea están deshabilitados en la configuración del POS."), frappe.PermissionError)

    if (flt(global_discount_percentage) > 0 or flt(global_discount_amount) > 0) and not cint(rpos_cfg.get("allow_global_discount", 1)):
        frappe.throw(_("Los descuentos globales están deshabilitados en la configuración del POS."), frappe.PermissionError)

    if coupon_code and not cint(rpos_cfg.get("enable_promotions_coupons", 0)):
        frappe.throw(_("Las promociones y cupones están deshabilitados en la configuración del POS."))

    if gift_card_code and not cint(rpos_cfg.get("enable_gift_cards", 0)):
        frappe.throw(_("Las tarjetas de regalo están deshabilitadas en la configuración del POS."))

    if flt(loyalty_points) > 0 and not cint(rpos_cfg.get("enable_loyalty_program", 0)):
        frappe.throw(_("El programa de lealtad está deshabilitado en la configuración del POS."))

    if customer and frappe.db.exists("Customer", customer):
        doc.customer = customer
    if tax_id is not None:
        doc.tax_id = cstr(tax_id).strip()[:60]
        if doc.customer and doc.tax_id:
            frappe.db.set_value("Customer", doc.customer, "tax_id", doc.tax_id)

    if tip_percentage is not None:
        doc.tip_percentage = max(0.0, flt(tip_percentage, 2))
        if doc.tip_percentage == 0 and tip_amount is not None:
            doc.tip_amount = max(0.0, flt(tip_amount, 2))
    elif tip_amount is not None:
        doc.tip_percentage = 0.0
        doc.tip_amount = max(0.0, flt(tip_amount, 2))

    validate_order(doc)

    prof_doc = frappe.get_doc("POS Profile", pos_profile) if pos_profile else None
    warehouse = prof_doc.warehouse if prof_doc else None
    income_account = (
        prof_doc.income_account
        if prof_doc and getattr(prof_doc, "income_account", None)
        else _resolve_service_income_account(company)
    )
    cost_center = (
        prof_doc.cost_center
        if prof_doc and getattr(prof_doc, "cost_center", None)
        else frappe.db.get_value("Company", company, "cost_center")
    )

    invoice_items = []
    for row in doc.items:
        if cint(getattr(row, "is_cancelled", 0)) or row.kds_status == "Cancelado":
            continue
        desc_parts = [row.item_name or row.item_code]
        if row.options_summary:
            desc_parts.append(f"Opciones: {row.options_summary}")
        if row.note:
            desc_parts.append(f"Nota: {row.note}")
        item_tax_rate_json = "{}"
        tax_acc = _resolve_tax_account(company, row.tax_rate)
        if tax_acc:
            item_tax_rate_json = json.dumps({tax_acc: flt(row.tax_rate, 2)})

        item_entry = {
            "item_code": row.item_code,
            "item_name": row.item_name,
            "description": " | ".join(desc_parts),
            "qty": flt(row.qty),
            "uom": row.uom,
            "rate": flt(row.rate, 2),
            "price_list_rate": flt(row.base_rate + row.options_rate, 2),
            "discount_percentage": flt(row.discount_percentage, 2),
            "item_tax_rate": item_tax_rate_json,
        }
        if warehouse:
            item_entry["warehouse"] = warehouse
        if income_account:
            item_entry["income_account"] = income_account
        if cost_center:
            item_entry["cost_center"] = cost_center
        invoice_items.append(item_entry)

    if not invoice_items:
        frappe.throw(_("No hay productos activos por facturar en esta cuenta."))

    taxes = []
    tax_acc_15 = _resolve_tax_account(company, 15.0)
    if tax_acc_15 and doc.isv_15 > 0:
        taxes.append({
            "charge_type": "On Net Total",
            "account_head": tax_acc_15,
            "description": "ISV 15%",
            "rate": 15.0,
            "cost_center": cost_center,
        })
    tax_acc_18 = _resolve_tax_account(company, 18.0)
    if tax_acc_18 and doc.isv_18 > 0 and tax_acc_18 != tax_acc_15:
        taxes.append({
            "charge_type": "On Net Total",
            "account_head": tax_acc_18,
            "description": "ISV 18%",
            "rate": 18.0,
            "cost_center": cost_center,
        })
    if doc.tip_amount > 0:
        service_acc = _resolve_service_income_account(company)
        if service_acc:
            taxes.append({
                "charge_type": "Actual",
                "account_head": service_acc,
                "description": "Servicio sugerido / Propina",
                "tax_amount": flt(doc.tip_amount, 2),
                "cost_center": cost_center,
            })

    enabled_mops = set(rpos_cfg.get("enabled_payments") or [])
    parsed_payments = frappe.parse_json(payments) if isinstance(payments, str) else payments
    payment_rows = []
    if isinstance(parsed_payments, list):
        for p in parsed_payments:
            if isinstance(p, dict) and p.get("mode_of_payment") and flt(p.get("amount")) > 0:
                mop = p["mode_of_payment"]
                if enabled_mops and mop not in enabled_mops:
                    frappe.throw(
                        _("El método de pago '{0}' no está habilitado para este Punto de Venta.").format(mop),
                        frappe.PermissionError,
                    )
                acc = _resolve_payment_account(mop, company)
                payment_rows.append({
                    "mode_of_payment": mop,
                    "amount": flt(p["amount"], 2),
                    "account": acc,
                })
    if not payment_rows:
        default_mop = "Efectivo"
        if prof_doc and prof_doc.payments:
            default_mop = prof_doc.payments[0].mode_of_payment
        acc = _resolve_payment_account(default_mop, company)
        payment_rows.append({
            "mode_of_payment": default_mop,
            "amount": flt(doc.grand_total, 2),
            "account": acc,
        })

    gift_card_doc = None
    redeemed_gift_amount = 0.0
    if gift_card_code and flt(gift_card_amount) > 0:
        clean_gc_code = cstr(gift_card_code).strip().upper()
        if not frappe.db.exists("Restaurant Gift Card", clean_gc_code):
            frappe.throw(_("La tarjeta de regalo '{0}' no existe.").format(clean_gc_code))
        frappe.db.sql(
            "SELECT name FROM `tabRestaurant Gift Card` WHERE name = %s FOR UPDATE",
            (clean_gc_code,),
        )
        gift_card_doc = frappe.get_doc("Restaurant Gift Card", clean_gc_code)
        if not cint(gift_card_doc.enabled):
            frappe.throw(_("La tarjeta de regalo '{0}' está inactiva o vencida.").format(clean_gc_code))
        if flt(gift_card_amount) > flt(gift_card_doc.balance):
            frappe.throw(_("Saldo insuficiente en la tarjeta de regalo (disponible: {0}).").format(flt(gift_card_doc.balance, 2)))
        redeemed_gift_amount = flt(gift_card_amount, 2)

    fiscal_info = _resolve_sar_fiscal_info(pos_profile=pos_profile, company=company)
    cai_value = cstr(fiscal_info["cai"] or doc.cai).strip()
    due_cai_value = cstr(fiscal_info["due_date_cai"] or doc.due_date_cai).strip()
    auth_range_value = cstr(fiscal_info["authorized_range"]).strip()

    active_opening_shift = doc.pos_opening_shift
    if not active_opening_shift:
        active_shift_info = _get_active_opening_shift(frappe.session.user)
        if active_shift_info:
            active_opening_shift = active_shift_info.get("name") or ""

    si_payload = {
        "doctype": "Sales Invoice",
        "company": company,
        "customer": doc.customer,
        "tax_id": doc.tax_id or "",
        "posting_date": nowdate(),
        "due_date": nowdate(),
        "is_pos": 1,
        "pos_profile": pos_profile,
        "posa_pos_opening_shift": active_opening_shift or "",
        "currency": doc.currency or "HNL",
        "selling_price_list": doc.selling_price_list or (prof_doc.selling_price_list if prof_doc else "Venta estándar"),
        "update_stock": 0,
        "cai": cai_value,
        "due_date_cai": due_cai_value,
        "posa_notes": f"Orden: {doc.order_name} | Mesa: {doc.table_label or 'N/A'} | Mesero: {doc.waiter_name or 'N/A'}",
        "items": invoice_items,
        "taxes": taxes,
        "payments": payment_rows,
    }
    if flt(global_discount_percentage) > 0:
        si_payload["apply_discount_on"] = "Grand Total"
        si_payload["additional_discount_percentage"] = min(100.0, flt(global_discount_percentage, 2))
    elif flt(global_discount_amount) > 0:
        si_payload["apply_discount_on"] = "Grand Total"
        si_payload["discount_amount"] = flt(global_discount_amount, 2)

    if coupon_code and frappe.db.exists("Coupon Code", coupon_code):
        si_payload["coupon_code"] = coupon_code

    si_meta = frappe.get_meta("Sales Invoice")
    if si_meta.has_field("authorized_range"):
        si_payload["authorized_range"] = auth_range_value
    if si_meta.has_field("cashier"):
        si_payload["cashier"] = frappe.session.user
    if si_meta.has_field("redeem_loyalty_points") and flt(loyalty_points) > 0:
        si_payload["redeem_loyalty_points"] = 1
        si_payload["loyalty_points"] = cint(loyalty_points)

    si = frappe.get_doc(si_payload)
    si.set_missing_values()
    si.calculate_taxes_and_totals()

    total_paid = sum(flt(p.amount) for p in si.payments)
    grand_total = flt(si.grand_total, 2)
    if flt(total_paid, 2) + 0.01 < grand_total:
        frappe.throw(
            _("El monto total pagado ({0}) es menor al total de la factura ({1}).").format(
                flt(total_paid, 2), grand_total
            )
        )
    if total_paid < grand_total and si.payments:
        si.payments[0].amount = flt(si.payments[0].amount + (grand_total - total_paid), 2)

    si.insert(ignore_permissions=True)
    if cint(rpos_cfg.get("auto_validate_orders", 1)):
        si.submit()

    if gift_card_doc and redeemed_gift_amount > 0:
        gift_card_doc.balance = flt(gift_card_doc.balance - redeemed_gift_amount, 2)
        gift_card_doc.save(ignore_permissions=True)

    if not doc.pos_opening_shift and active_opening_shift:
        doc.pos_opening_shift = active_opening_shift
    doc.sales_invoice = si.name
    doc.cai = si.cai or cai_value
    doc.due_date_cai = si.due_date_cai or due_cai_value
    doc.status = "Facturada"
    doc.save()

    return {
        "order": _serialize_order(doc),
        "invoice": {
            "name": si.name,
            "posting_date": str(si.posting_date),
            "customer": si.customer,
            "customer_name": si.customer_name,
            "tax_id": si.tax_id or "",
            "company": si.company,
            "company_tax_id": si.company_tax_id or fiscal_info["company_tax_id"],
            "cai": si.cai or cai_value,
            "due_date_cai": str(si.due_date_cai or due_cai_value),
            "authorized_range": getattr(si, "authorized_range", None) or auth_range_value,
            "prefix": getattr(si, "naming_series", None) or fiscal_info["prefix"],
            "net_total": flt(si.net_total, 2),
            "taxed_amount_15": flt(si.get("taxed_amount_15"), 2),
            "isv_15": flt(si.get("isv_15"), 2),
            "taxed_amount_18": flt(si.get("taxed_amount_18"), 2),
            "isv_18": flt(si.get("isv_18"), 2),
            "exempt_amount": flt(si.get("exempt_amount"), 2),
            "exonerated_amount": flt(si.get("exonerated_amount"), 2),
            "tip_amount": flt(doc.tip_amount, 2),
            "grand_total": flt(si.grand_total, 2),
            "paid_amount": flt(si.paid_amount, 2),
            "change_amount": flt(si.change_amount, 2),
        },
        "areas": _get_areas_with_live_tables(),
    }


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
    """Synchronize KDS tickets and publish a realtime update after item or order cancellation."""
    try:
        from restaurant.kds import _sync_legacy_status
        _sync_legacy_status(doc)
    except Exception:
        frappe.log_error(frappe.get_traceback(), "KDS Sync After Cancellation")
    try:
        frappe.publish_realtime(
            "restaurant_kds_update",
            {"order_name": doc.name, "status": doc.status, "kds_status": doc.kds_status},
            after_commit=True,
        )
    except Exception:
        pass


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


@frappe.whitelist(methods=["POST"])
def authorize_clear_order(order_name=None, supervisor_user=None, supervisor_pin=None, reason=""):
    """Verify supervisor authorization to empty/clear an active order in the POS."""
    _require_pos_user()
    if is_supervisor():
        log_restaurant_audit(
            "Vaciar orden",
            f"Supervisor {frappe.session.user} vació la orden directamente.",
            order_name=order_name,
            supervisor_user=frappe.session.user,
        )
        return {"authorized": True, "supervisor": frappe.session.user}
    return verify_supervisor_authorization(
        supervisor_user,
        supervisor_pin,
        "Vaciar orden",
        order_name=order_name,
        reason=reason,
    )


@frappe.whitelist(methods=["POST"])
def authorize_reprint_command(order_name, supervisor_user=None, supervisor_pin=None, reason=""):
    """Verify supervisor authorization to reprint kitchen commands for an order."""
    _require_pos_user()
    if not order_name or not frappe.db.exists("Restaurant Order", order_name):
        frappe.throw(_("La cuenta u orden no existe."), frappe.DoesNotExistError)
    if is_supervisor():
        log_restaurant_audit(
            "Reimprimir comandas",
            f"Supervisor {frappe.session.user} autorizó reimpresión de comandas.",
            order_name=order_name,
            supervisor_user=frappe.session.user,
        )
        return {"authorized": True, "supervisor": frappe.session.user}
    return verify_supervisor_authorization(
        supervisor_user,
        supervisor_pin,
        "Reimprimir comandas",
        order_name=order_name,
        reason=reason,
    )


@frappe.whitelist(methods=["POST"])
def save_customer_with_rtn(customer_name, tax_id=None, customer_id=None, email_id=None, mobile_no=None, address=None):
    """Create or update a Customer with their fiscal RTN, email, phone, and address directly from the Restaurant POS."""
    _require_pos_user()
    clean_name = cstr(customer_name).strip()
    clean_rtn = cstr(tax_id).strip()[:60]
    clean_email = cstr(email_id).strip()[:140]
    clean_phone = cstr(mobile_no).strip()[:60]
    clean_addr = cstr(address).strip()[:200]
    if not clean_name:
        frappe.throw(_("El nombre o razón social del cliente es obligatorio."))

    cust_meta = frappe.get_meta("Customer")
    if customer_id and frappe.db.exists("Customer", customer_id):
        doc = frappe.get_doc("Customer", customer_id)
        doc.customer_name = clean_name
        doc.tax_id = clean_rtn
        if email_id is not None and cust_meta.has_field("email_id"):
            doc.email_id = clean_email
        if mobile_no is not None and cust_meta.has_field("mobile_no"):
            doc.mobile_no = clean_phone
        if address is not None and cust_meta.has_field("primary_address"):
            doc.primary_address = clean_addr
        doc.save(ignore_permissions=True)
    else:
        group = (
            frappe.db.get_single_value("Selling Settings", "customer_group")
            or frappe.db.get_value("Customer Group", {"is_group": 0}, "name")
            or "All Customer Groups"
        )
        territory = (
            frappe.db.get_single_value("Selling Settings", "territory")
            or frappe.db.get_value("Territory", {"is_group": 0}, "name")
            or "All Territories"
        )
        payload = {
            "doctype": "Customer",
            "customer_name": clean_name,
            "customer_type": "Individual",
            "customer_group": group,
            "territory": territory,
            "tax_id": clean_rtn,
        }
        if clean_email and cust_meta.has_field("email_id"):
            payload["email_id"] = clean_email
        if clean_phone and cust_meta.has_field("mobile_no"):
            payload["mobile_no"] = clean_phone
        if clean_addr and cust_meta.has_field("primary_address"):
            payload["primary_address"] = clean_addr
        doc = frappe.get_doc(payload)
        doc.insert(ignore_permissions=True)

    return {
        "name": doc.name,
        "customer_name": doc.customer_name,
        "tax_id": doc.tax_id or "",
        "email_id": cstr(getattr(doc, "email_id", "") or clean_email),
        "mobile_no": cstr(getattr(doc, "mobile_no", "") or clean_phone),
        "address": cstr(getattr(doc, "primary_address", "") or clean_addr),
    }


@frappe.whitelist()
def get_emitted_commands(limit=40):
    """Return orders that already have emitted kitchen commands for reprinting."""
    _require_pos_user()
    cmd_filters = {"status": ["in", ["En curso", "Facturada"]]}
    active_branch = _get_active_user_branch()
    if active_branch and frappe.get_meta("Restaurant Order").has_field("branch"):
        cmd_filters["branch"] = active_branch
    rows = frappe.get_all(
        "Restaurant Order",
        filters=cmd_filters,
        fields=["name"],
        order_by="sent_to_kitchen_at desc, modified desc",
        limit_page_length=max(10, min(100, cint(limit or 40))),
    )
    emitted = []
    for row in rows:
        serialized = _serialize_order(row.name)
        emitted_lines = [
            it for it in (serialized.get("items") or [])
            if (it.get("kds_status") and it.get("kds_status") != "Pendiente") or serialized.get("sent_to_kitchen_at")
        ]
        if not emitted_lines:
            continue
        stations = sorted({
            st.strip()
            for it in emitted_lines
            for st in cstr(it.get("command_station") or "Cocina General").split(",")
            if st.strip()
        })
        emitted.append({
            "name": serialized["name"],
            "order_name": serialized["order_name"],
            "table_label": serialized["table_label"],
            "service_type": serialized["service_type"],
            "waiter_name": serialized["waiter_name"],
            "status": serialized["status"],
            "kds_status": serialized["kds_status"],
            "sent_to_kitchen_at": serialized["sent_to_kitchen_at"] or serialized["modified"],
            "stations": stations or ["Cocina General"],
            "items": emitted_lines,
        })
    return {
        "commands": emitted,
        "command_stations": get_command_stations(),
    }


@frappe.whitelist(methods=["POST"])
def create_pos_product(product):
    """Create a product/dish using native Item, Item Price, and Restaurant Item Configuration."""
    _require_manager_user()
    payload = frappe.parse_json(product) if isinstance(product, str) else product
    if not isinstance(payload, dict):
        frappe.throw(_("Los datos del producto no tienen un formato válido."))

    item_name = cstr(payload.get("item_name") or "").strip()
    if not item_name:
        frappe.throw(_("El nombre del producto o platillo es obligatorio."))

    item_code = cstr(payload.get("item_code") or "").strip() or item_name
    item_group = cstr(payload.get("item_group") or "").strip()
    if not item_group or not frappe.db.exists("Item Group", item_group):
        fallback_grp = frappe.db.get_value(
            "Item Group",
            {"is_group": 0, "name": ["not in", ["Servicios", "Sub-ensambles", "Materia prima"]]},
            "name",
        ) or frappe.db.get_value("Item Group", {"is_group": 0}, "name") or "All Item Groups"
        item_group = fallback_grp

    stock_uom = cstr(payload.get("stock_uom") or "Nos").strip()
    if not frappe.db.exists("UOM", stock_uom):
        stock_uom = frappe.db.get_value("UOM", {}, "name") or "Nos"

    price = max(0.0, flt(payload.get("price"), 2))
    recipe_enabled = cint(payload.get("restaurant_recipe_enabled"))
    options_enabled = cint(payload.get("restaurant_options_enabled"))
    is_stock_item = 0 if recipe_enabled else cint(payload.get("is_stock_item", 0))
    color = cstr(payload.get("restaurant_color") or "#1898e8").strip()

    if frappe.db.exists("Item", item_code):
        item_doc = frappe.get_doc("Item", item_code)
    else:
        item_doc = frappe.new_doc("Item")
        item_doc.item_code = item_code

    item_doc.item_name = item_name
    item_doc.item_group = item_group
    item_doc.stock_uom = stock_uom
    item_doc.is_sales_item = 1
    item_doc.is_stock_item = is_stock_item
    item_doc.standard_rate = price
    item_doc.description = cstr(payload.get("description") or item_name).strip()

    item_meta = frappe.get_meta("Item")
    if item_meta.has_field("restaurant_color") and color:
        item_doc.set("restaurant_color", color)
    if item_meta.has_field("restaurant_recipe_enabled"):
        item_doc.set("restaurant_recipe_enabled", recipe_enabled)
    if item_meta.has_field("restaurant_options_enabled"):
        item_doc.set("restaurant_options_enabled", options_enabled)

    if item_doc.is_new():
        item_doc.insert(ignore_permissions=True)
    else:
        item_doc.save(ignore_permissions=True)

    selling_price_list = cstr(payload.get("selling_price_list") or "").strip()
    if not selling_price_list:
        default_prof = _get_default_pos_profile()
        selling_price_list = (
            default_prof.selling_price_list
            if default_prof and default_prof.selling_price_list
            else (frappe.db.get_value("Price List", {"selling": 1, "enabled": 1}, "name") or "Standard Selling")
        )

    if selling_price_list and frappe.db.exists("Price List", selling_price_list):
        existing_price = frappe.db.get_value(
            "Item Price",
            {"item_code": item_doc.name, "price_list": selling_price_list, "selling": 1},
            "name",
        )
        if existing_price:
            frappe.db.set_value("Item Price", existing_price, "price_list_rate", price)
        else:
            ip_doc = frappe.get_doc({
                "doctype": "Item Price",
                "item_code": item_doc.name,
                "price_list": selling_price_list,
                "selling": 1,
                "price_list_rate": price,
            })
            ip_doc.insert(ignore_permissions=True)

    option_group = payload.get("option_group")
    if options_enabled and isinstance(option_group, dict) and option_group.get("group_name") and option_group.get("options"):
        from restaurant.item_configuration import save_option_group

        item_doc.reload()
        save_option_group(item_doc.name, option_group, str(item_doc.modified))

    categories, items = _get_catalog_for_pos(selling_price_list)
    created_entry = next((it for it in items if it["item_code"] == item_doc.name), None)
    return {
        "item_code": item_doc.name,
        "item": created_entry,
        "categories": categories,
        "items": items,
    }


@frappe.whitelist()
def get_pos_idle_settings():
    """Return configured POS inactivity wallpaper settings."""
    _require_pos_user()
    if frappe.db.exists("DocType", "Restaurant Settings"):
        try:
            settings = frappe.get_single("Restaurant Settings")
            return {
                "enabled": cint(bool(settings.idle_wallpaper_enabled)),
                "timeout_seconds": max(5, int(round(flt(settings.idle_wallpaper_minutes or 2) * 60))),
                "background_url": settings.idle_wallpaper_background or "/assets/restaurant/images/background-light.svg",
                "logo_url": settings.idle_wallpaper_logo or "",
                "show_clock": cint(bool(settings.idle_wallpaper_show_clock)),
            }
        except Exception:
            pass

    raw_enabled = frappe.db.get_default("rpos_idle_wallpaper_enabled")
    raw_timeout = frappe.db.get_default("rpos_idle_wallpaper_timeout_seconds")
    raw_show_clock = frappe.db.get_default("rpos_idle_wallpaper_show_clock")
    bg_url = frappe.db.get_default("rpos_idle_wallpaper_background_url") or "/assets/restaurant/images/background-light.svg"
    logo_url = frappe.db.get_default("rpos_idle_wallpaper_logo_url") or ""
    enabled = 1 if raw_enabled is None else cint(raw_enabled)
    show_clock = 1 if raw_show_clock is None else cint(raw_show_clock)
    timeout_seconds = cint(raw_timeout) if raw_timeout is not None else 120
    if timeout_seconds < 5:
        timeout_seconds = 120
    return {
        "enabled": cint(bool(enabled)),
        "timeout_seconds": timeout_seconds,
        "background_url": bg_url,
        "logo_url": logo_url,
        "show_clock": cint(bool(show_clock)),
    }


@frappe.whitelist(methods=["POST"])
def save_pos_idle_settings(enabled=1, timeout_seconds=120, background_url=None, logo_url=None, show_clock=1):
    """Persist POS inactivity wallpaper settings in global defaults."""
    _require_manager_user()
    clean_enabled = 1 if cint(enabled) else 0
    clean_show_clock = 1 if cint(show_clock) else 0
    clean_timeout = max(5, min(7200, cint(timeout_seconds or 120)))
    frappe.db.set_default("rpos_idle_wallpaper_enabled", str(clean_enabled))
    frappe.db.set_default("rpos_idle_wallpaper_timeout_seconds", str(clean_timeout))
    frappe.db.set_default("rpos_idle_wallpaper_show_clock", str(clean_show_clock))
    if background_url is not None:
        frappe.db.set_default("rpos_idle_wallpaper_background_url", str(background_url or ""))
    if logo_url is not None:
        frappe.db.set_default("rpos_idle_wallpaper_logo_url", str(logo_url or ""))
    frappe.clear_cache()
    return {
        "enabled": clean_enabled,
        "timeout_seconds": clean_timeout,
        "background_url": background_url or "",
        "logo_url": logo_url or "",
        "show_clock": clean_show_clock,
    }


@frappe.whitelist()
def get_restaurant_pos_config(pos_profile=None):
    """Retrieve full configuration matching the Odoo-style restaurant POS settings screen."""
    _require_pos_user()
    try:
        from restaurant.setup import sync_restaurant_dashboard_block
        sync_restaurant_dashboard_block()
    except Exception:
        pass
    company = _get_default_company()
    all_profiles = frappe.get_all(
        "POS Profile",
        filters={"disabled": 0},
        fields=["name", "company", "currency", "customer"],
        order_by="name asc",
    )
    if not pos_profile or not frappe.db.exists("POS Profile", pos_profile):
        default_p = _get_default_pos_profile(company)
        pos_profile = default_p.name if default_p else (all_profiles[0].name if all_profiles else None)

    if not pos_profile:
        return {
            "pos_profiles": [],
            "selected_profile": "",
            "company": company,
            "currency": "HNL",
            "has_active_shift": False,
            "active_shift": None,
            "is_bar_restaurant": 1,
            "areas": [],
            "enabled_areas": [],
            "presets": [],
            "enabled_presets": [],
            "default_preset": "Comer en el local",
            "payments": [],
            "all_payment_methods": [],
            "enable_rounded_total": 0,
            "max_difference_enabled": 0,
            "write_off_limit": 0.0,
            "auto_validate_orders": 1,
            "one_click_pay": 0,
            "tips_enabled": 1,
            "tip_after_payment": 0,
            "employee_login_required": 0,
            "show_product_images": 1,
            "show_category_images": 1,
            "group_by_category": 0,
            "large_scrollbars": 0,
            "online_reservation": 0,
            "default_screen": "Caja",
            "idle_wallpaper_enabled": 1,
            "idle_wallpaper_timeout": 60,
        }

    prof_doc = frappe.get_doc("POS Profile", pos_profile)

    shifts = frappe.get_all(
        "POS Opening Shift",
        filters={"pos_profile": pos_profile, "docstatus": 1, "status": "Open"},
        fields=["name", "user", "period_start_date"],
        limit=1,
    )
    active_shift = shifts[0] if shifts else None

    payments = [
        {"mode_of_payment": row.mode_of_payment, "default": cint(row.default)}
        for row in (prof_doc.payments or [])
    ]
    all_payment_methods = frappe.get_all(
        "Mode of Payment", filters={"enabled": 1}, pluck="name", order_by="name asc"
    )

    area_fields = ["name", "area_name"]
    if frappe.db.table_exists("Restaurant Area"):
        area_meta = frappe.get_meta("Restaurant Area")
        if area_meta.has_field("status"):
            area_fields.append("status")
        areas = frappe.get_all("Restaurant Area", fields=area_fields, order_by="area_name asc")
    else:
        areas = []
    for a in areas:
        a["disabled"] = 1 if a.get("status") == "Inactiva" else 0

    preset_fields = ["name", "preset_name", "color_bg", "color_border"]
    if frappe.db.table_exists("Restaurant Order Preset"):
        preset_meta = frappe.get_meta("Restaurant Order Preset")
        if preset_meta.has_field("enabled"):
            preset_fields.append("enabled")
        if preset_meta.has_field("enable_scheduling"):
            preset_fields.append("enable_scheduling")
        presets = frappe.get_all(
            "Restaurant Order Preset",
            fields=preset_fields,
            order_by="idx asc, creation asc" if preset_meta.has_field("idx") else "creation asc",
        )
    else:
        presets = []
    for p in presets:
        p["disabled"] = 0 if cint(p.get("enabled", 1)) else 1

    pref_key = f"rpos_cfg_{pos_profile}"
    raw_pref = frappe.db.get_default(pref_key)
    pref = {}
    if raw_pref:
        try:
            pref = json.loads(raw_pref) if isinstance(raw_pref, str) else raw_pref
        except Exception:
            pref = {}

    idle_settings = get_pos_idle_settings()

    return {
        "pos_profiles": [p.name for p in all_profiles],
        "selected_profile": pos_profile,
        "company": prof_doc.company,
        "currency": prof_doc.currency or "HNL",
        "has_active_shift": bool(active_shift),
        "active_shift": active_shift,
        "is_bar_restaurant": cint(pref.get("is_bar_restaurant", 1)),
        "areas": areas,
        "enabled_areas": pref.get("enabled_areas", [a.name for a in areas if not a.get("disabled")]),
        "presets": presets,
        "enabled_presets": pref.get("enabled_presets", [p.preset_name for p in presets if not p.get("disabled")]),
        "default_preset": pref.get("default_preset", "Comer en el local"),
        "payments": payments,
        "all_payment_methods": all_payment_methods,
        "enable_rounded_total": 0 if cint(prof_doc.disable_rounded_total) else 1,
        "max_difference_enabled": 1 if flt(prof_doc.write_off_limit) > 0 else cint(pref.get("max_difference_enabled", 0)),
        "write_off_limit": flt(prof_doc.write_off_limit or 0),
        "auto_validate_orders": cint(pref.get("auto_validate_orders", 1)),
        "one_click_pay": cint(pref.get("one_click_pay", 0)),
        "tips_enabled": cint(pref.get("tips_enabled", 1)),
        "tip_after_payment": cint(pref.get("tip_after_payment", 0)),
        "employee_login_required": cint(pref.get("employee_login_required", 0)),
        "show_product_images": 0 if cint(prof_doc.hide_images) else cint(pref.get("show_product_images", 1)),
        "show_category_images": cint(pref.get("show_category_images", 1)),
        "group_by_category": cint(pref.get("group_by_category", 0)),
        "large_scrollbars": cint(pref.get("large_scrollbars", 0)),
        "online_reservation": cint(pref.get("online_reservation", 0)),
        "default_screen": pref.get("default_screen", "Caja"),
        "idle_wallpaper_enabled": cint(pref.get("idle_wallpaper_enabled", idle_settings["enabled"])),
        "idle_wallpaper_timeout": cint(pref.get("idle_wallpaper_timeout", idle_settings["timeout_seconds"])),
        "idle_wallpaper_background_url": pref.get("idle_wallpaper_background_url", idle_settings.get("background_url", "/assets/restaurant/images/background-light.svg")),
        "idle_wallpaper_logo_url": pref.get("idle_wallpaper_logo_url", idle_settings.get("logo_url", "")),
        "idle_wallpaper_show_clock": cint(pref.get("idle_wallpaper_show_clock", idle_settings.get("show_clock", 1))),
    }


@frappe.whitelist(methods=["POST"])
def save_restaurant_pos_config(pos_profile, config):
    """Save full configuration matching the Odoo-style restaurant POS settings screen."""
    _require_manager_user()
    if isinstance(config, str):
        config = json.loads(config)

    if not pos_profile or not frappe.db.exists("POS Profile", pos_profile):
        frappe.throw(_("El Perfil de Punto de Venta especificado no existe."))

    prof_doc = frappe.get_doc("POS Profile", pos_profile)

    # 1. Update native POS Profile fields
    show_prod_imgs = cint(config.get("show_product_images", 1))
    prof_doc.hide_images = 0 if show_prod_imgs else 1
    prof_doc.disable_rounded_total = 0 if cint(config.get("enable_rounded_total", 0)) else 1

    if cint(config.get("max_difference_enabled", 0)):
        prof_doc.write_off_limit = max(0.0, flt(config.get("write_off_limit") or 0))
    else:
        prof_doc.write_off_limit = 0.0

    # Payments table
    incoming_payments = config.get("payments") or []
    if incoming_payments:
        clean_methods = []
        for p in incoming_payments:
            m = p if isinstance(p, str) else p.get("mode_of_payment")
            if m and frappe.db.exists("Mode of Payment", m) and m not in clean_methods:
                clean_methods.append(m)

        if clean_methods:
            prof_doc.set("payments", [])
            for idx, m in enumerate(clean_methods):
                prof_doc.append("payments", {
                    "mode_of_payment": m,
                    "default": 1 if idx == 0 else 0,
                })

    prof_doc.save(ignore_permissions=True)

    # 2. Persist extended profile configuration
    pref_key = f"rpos_cfg_{pos_profile}"
    frappe.db.set_default(pref_key, json.dumps(config))

    # 3. Synchronize global wallpaper settings if provided
    if "idle_wallpaper_enabled" in config and "idle_wallpaper_timeout" in config:
        save_pos_idle_settings(
            enabled=config.get("idle_wallpaper_enabled"),
            timeout_seconds=config.get("idle_wallpaper_timeout"),
            background_url=config.get("idle_wallpaper_background_url"),
            logo_url=config.get("idle_wallpaper_logo_url"),
            show_clock=config.get("idle_wallpaper_show_clock", 1),
        )

    frappe.clear_cache()
    return get_restaurant_pos_config(pos_profile)


def _get_default_warehouse(company=None):
    """Resolve default active warehouse for restaurant operations."""
    if not company:
        company = _get_default_company()
    pos_p = _get_default_pos_profile(company)
    if pos_p and getattr(pos_p, "warehouse", None):
        return pos_p.warehouse
    wh = frappe.db.get_value("Warehouse", {"company": company, "is_group": 0, "disabled": 0}, "name")
    if not wh:
        wh = frappe.db.get_value("Warehouse", {"is_group": 0, "disabled": 0}, "name")
    return wh


@frappe.whitelist(methods=["GET", "POST"])
def get_restaurant_stock_status(warehouse=None):
    """Analyze stock status for all restaurant sales items.

    Returns the item list, whether each item is a stock item, its bin quantity in the warehouse,
    and whether restaurant billing can proceed without stock (which is always true in LEAF because
    Sales Invoices are issued with update_stock=0).
    """
    _require_pos_user()
    company = _get_default_company()
    target_wh = warehouse or _get_default_warehouse(company)

    items = frappe.get_all(
        "Item",
        filters={
            "disabled": 0,
            "is_sales_item": 1,
            "has_variants": 0,
            "is_fixed_asset": 0,
            "item_group": ["not in", ["Servicios", "Sub-ensambles", "Materia prima"]],
        },
        fields=["name", "item_name", "item_group", "stock_uom", "is_stock_item", "standard_rate"],
        order_by="item_name asc",
        limit_page_length=500,
    )

    bin_map = {}
    if target_wh and frappe.db.table_exists("Bin"):
        bins = frappe.get_all(
            "Bin",
            filters={"warehouse": target_wh},
            fields=["item_code", "actual_qty"],
        )
        for b in bins:
            bin_map[b.item_code] = flt(b.actual_qty)

    report = []
    stock_items_count = 0
    non_stock_items_count = 0
    total_stock_units = 0.0

    for it in items:
        is_stock = cint(it.is_stock_item)
        qty = bin_map.get(it.name, 0.0) if is_stock else 0.0
        if is_stock:
            stock_items_count += 1
            total_stock_units += qty
        else:
            non_stock_items_count += 1

        report.append({
            "item_code": it.name,
            "item_name": it.item_name,
            "item_group": it.item_group,
            "stock_uom": it.stock_uom,
            "is_stock_item": is_stock,
            "actual_qty": qty,
            "billing_allowed": True,
            "note": "Inventariable en almacén" if is_stock else "Platillo / No inventariable (Facturación libre)",
        })

    return {
        "company": company,
        "warehouse": target_wh,
        "total_items": len(items),
        "stock_items_count": stock_items_count,
        "non_stock_items_count": non_stock_items_count,
        "total_stock_units": total_stock_units,
        "billing_requires_stock": False,
        "items": report,
    }


@frappe.whitelist(methods=["POST"])
def ensure_restaurant_stock(target_qty=100, make_inventoriable=0, warehouse=None):
    """Seed or replenish stock to target_qty (default 100) via a native Stock Entry.

    If make_inventoriable=1, items without recipes will be updated to is_stock_item=1.
    For all is_stock_item=1 items having less than target_qty, creates and submits a native
    Stock Entry (Material Receipt).
    """
    _require_manager_user()
    company = _get_default_company()
    target_wh = warehouse or _get_default_warehouse(company)
    target_qty = max(1.0, flt(target_qty or 100))
    make_inv = cint(make_inventoriable)

    if not target_wh or not frappe.db.exists("Warehouse", target_wh):
        frappe.throw(_("No se encontró un almacén válido para registrar la entrada de stock."))

    items = frappe.get_all(
        "Item",
        filters={
            "disabled": 0,
            "is_sales_item": 1,
            "has_variants": 0,
            "is_fixed_asset": 0,
            "item_group": ["not in", ["Servicios", "Sub-ensambles", "Materia prima"]],
        },
        fields=["name", "item_name", "stock_uom", "is_stock_item", "standard_rate", "restaurant_recipe_enabled"],
        limit_page_length=500,
    )

    items_to_receipt = []

    for it in items:
        if make_inv and not cint(it.is_stock_item) and not cint(it.get("restaurant_recipe_enabled")):
            frappe.db.set_value("Item", it.name, "is_stock_item", 1, update_modified=False)
            it.is_stock_item = 1

        if not cint(it.is_stock_item):
            continue

        curr_qty = flt(frappe.db.get_value("Bin", {"item_code": it.name, "warehouse": target_wh}, "actual_qty") or 0)
        needed = target_qty - curr_qty
        if needed > 0:
            rate = flt(it.standard_rate or 10.0)
            if rate <= 0:
                rate = 10.0
            items_to_receipt.append({
                "item_code": it.name,
                "item_name": it.item_name,
                "qty": needed,
                "t_warehouse": target_wh,
                "uom": it.stock_uom or "Nos",
                "stock_uom": it.stock_uom or "Nos",
                "conversion_factor": 1.0,
                "basic_rate": rate,
            })

    if not items_to_receipt:
        return {
            "status": "up_to_date",
            "message": _("Todos los productos inventariables ya cuentan con {0} o más unidades.").format(target_qty),
            "warehouse": target_wh,
            "stock_entry": None,
        }

    se = frappe.get_doc({
        "doctype": "Stock Entry",
        "stock_entry_type": "Material Receipt",
        "purpose": "Material Receipt",
        "company": company,
        "posting_date": nowdate(),
        "posting_time": nowtime(),
        "to_warehouse": target_wh,
        "items": items_to_receipt,
    })
    se.insert(ignore_permissions=True)
    se.submit()

    frappe.clear_cache(doctype="Item")
    frappe.clear_cache(doctype="Bin")

    return {
        "status": "success",
        "message": _("Se generó la Entrada de Stock {0} con {1} productos actualizados a {2} unidades.").format(
            se.name, len(items_to_receipt), target_qty
        ),
        "stock_entry": se.name,
        "warehouse": target_wh,
        "items_updated": len(items_to_receipt),
    }


@frappe.whitelist()
def get_self_order_config(pos_profile=None):
    """Return active self-order channels and status for mobile/kiosk clients."""
    cfg = _get_effective_rpos_config(pos_profile)
    enabled = bool(cint(cfg.get("enable_self_order")))
    mobile_ok = enabled and bool(cint(cfg.get("enable_mobile_self_order")))
    kiosk_ok = enabled and bool(cint(cfg.get("enable_kiosk_self_order")))
    return {
        "enabled": enabled,
        "channels": cfg.get("self_order_channels") or "Ambos canales",
        "mobile_enabled": mobile_ok,
        "kiosk_enabled": kiosk_ok,
        "default_preset": cfg.get("default_preset") or "Comer en el local",
    }


@frappe.whitelist(methods=["POST"])
def submit_self_order(order, channel="mobile", table=None):
    """Create a Restaurant Order from an authorized self-order channel (mobile or kiosk)."""
    _require_pos_user()
    payload = frappe.parse_json(order) if isinstance(order, str) else dict(order or {})
    pos_profile = payload.get("pos_profile")
    cfg = _get_effective_rpos_config(pos_profile)

    if not cint(cfg.get("enable_self_order")):
        frappe.throw(_("El autopedido está deshabilitado en la configuración del restaurante."), frappe.PermissionError)

    ch = cstr(channel or "mobile").strip().lower()
    if ch == "mobile" and not cint(cfg.get("enable_mobile_self_order")):
        frappe.throw(_("El canal de autopedido por celular no está habilitado."), frappe.PermissionError)
    if ch == "kiosk" and not cint(cfg.get("enable_kiosk_self_order")):
        frappe.throw(_("El canal de autopedido mediante kiosco no está habilitado."), frappe.PermissionError)
    if ch not in ("mobile", "kiosk"):
        frappe.throw(_("Canal de autopedido no válido."))

    if table and not payload.get("restaurant_table"):
        payload["restaurant_table"] = table
    if not payload.get("reference_note"):
        payload["reference_note"] = "Autopedido Celular" if ch == "mobile" else "Autopedido Kiosco"

    return save_pos_order(payload)


@frappe.whitelist()
def validate_coupon_code(coupon_code, order_total=0, customer=None):
    """Validate an ERPNext Coupon Code / Pricing Rule for POS discount application."""
    _require_pos_user()
    active_shift = _get_active_opening_shift(frappe.session.user)
    cfg = _get_effective_rpos_config(active_shift["pos_profile"] if active_shift else None)
    if not cint(cfg.get("enable_promotions_coupons")):
        frappe.throw(_("Las promociones y cupones están deshabilitados en la configuración del POS."))

    code = cstr(coupon_code or "").strip()
    if not code or not frappe.db.exists("Coupon Code", code):
        frappe.throw(_("El código de cupón '{0}' no es válido.").format(code))

    coupon = frappe.get_doc("Coupon Code", code)
    if coupon.valid_upto and frappe.utils.getdate(coupon.valid_upto) < frappe.utils.getdate(nowdate()):
        frappe.throw(_("El cupón '{0}' ha expirado.").format(code))
    if coupon.maximum_use and cint(coupon.used) >= cint(coupon.maximum_use):
        frappe.throw(_("El cupón '{0}' alcanzó su límite máximo de usos.").format(code))

    discount_pct = 0.0
    discount_amt = 0.0
    if coupon.pricing_rule and frappe.db.exists("Pricing Rule", coupon.pricing_rule):
        pr = frappe.get_doc("Pricing Rule", coupon.pricing_rule)
        if pr.rate_or_discount == "Discount Percentage":
            discount_pct = flt(pr.discount_percentage, 2)
        elif pr.rate_or_discount == "Discount Amount":
            discount_amt = flt(pr.discount_amount, 2)

    return {
        "coupon_code": coupon.name,
        "coupon_name": coupon.coupon_name,
        "discount_percentage": discount_pct,
        "discount_amount": discount_amt,
    }


@frappe.whitelist()
def validate_gift_card(card_code):
    """Validate a Restaurant Gift Card and return its available balance."""
    _require_pos_user()
    active_shift = _get_active_opening_shift(frappe.session.user)
    cfg = _get_effective_rpos_config(active_shift["pos_profile"] if active_shift else None)
    if not cint(cfg.get("enable_gift_cards")):
        frappe.throw(_("Las tarjetas de regalo están deshabilitadas en la configuración del POS."))

    code = cstr(card_code or "").strip().upper()
    if not code or not frappe.db.exists("Restaurant Gift Card", code):
        frappe.throw(_("La tarjeta de regalo '{0}' no existe.").format(code))

    gc = frappe.get_doc("Restaurant Gift Card", code)
    if not cint(gc.enabled):
        frappe.throw(_("La tarjeta de regalo '{0}' se encuentra inactiva.").format(code))
    if gc.expiry_date and frappe.utils.getdate(gc.expiry_date) < frappe.utils.getdate(nowdate()):
        frappe.throw(_("La tarjeta de regalo '{0}' está vencida.").format(code))
    if flt(gc.balance) <= 0:
        frappe.throw(_("La tarjeta de regalo '{0}' no tiene saldo disponible.").format(code))

    return {
        "card_code": gc.card_code,
        "balance": flt(gc.balance, 2),
        "customer": gc.customer or "",
    }


@frappe.whitelist()
def get_customer_loyalty_points(customer, company=None):
    """Return available ERPNext Loyalty Points for a customer when loyalty is enabled."""
    _require_pos_user()
    active_shift = _get_active_opening_shift(frappe.session.user)
    cfg = _get_effective_rpos_config(active_shift["pos_profile"] if active_shift else None)
    if not cint(cfg.get("enable_loyalty_program")):
        frappe.throw(_("El programa de lealtad está deshabilitado en la configuración del POS."))

    if not customer or not frappe.db.exists("Customer", customer):
        return {"loyalty_points": 0, "conversion_factor": 0.0, "loyalty_program": ""}

    loyalty_program = frappe.db.get_value("Customer", customer, "loyalty_program") or ""
    if not loyalty_program:
        return {"loyalty_points": 0, "conversion_factor": 0.0, "loyalty_program": ""}

    from erpnext.accounts.doctype.loyalty_program.loyalty_program import get_loyalty_program_details_with_points

    details = get_loyalty_program_details_with_points(
        customer,
        loyalty_program=loyalty_program,
        company=company or _get_default_company(),
        silent=True,
    ) or {}
    return {
        "loyalty_program": loyalty_program,
        "loyalty_points": cint(details.get("loyalty_points", 0)),
        "conversion_factor": flt(details.get("conversion_factor", 0.0)),
    }


@frappe.whitelist(methods=["POST"])
def send_invoice_email(invoice_name, recipient_email=None):
    """Send Sales Invoice PDF via Frappe native email configuration."""
    _require_pos_user()
    active_shift = _get_active_opening_shift(frappe.session.user)
    cfg = _get_effective_rpos_config(active_shift["pos_profile"] if active_shift else None)
    if not cint(cfg.get("allow_email_invoice", 1)):
        frappe.throw(_("El envío de facturas por correo electrónico está deshabilitado en la configuración del POS."))

    if not invoice_name or not frappe.db.exists("Sales Invoice", invoice_name):
        frappe.throw(_("La factura solicitada no existe."))

    si = frappe.get_doc("Sales Invoice", invoice_name)
    si.check_permission("read")
    target_email = cstr(recipient_email or frappe.db.get_value("Customer", si.customer, "email_id") or "").strip()
    if not target_email:
        frappe.throw(_("El cliente no tiene un correo electrónico configurado."))

    attachment = frappe.attach_print("Sales Invoice", si.name, file_name=f"{si.name}.pdf")
    frappe.sendmail(
        recipients=[target_email],
        subject=_("Factura {0} - {1}").format(si.name, si.company),
        message=_("Adjunto enviamos su comprobante fiscal {0} por un total de {1} {2}.").format(
            si.name, si.currency, flt(si.grand_total, 2)
        ),
        attachments=[attachment],
        now=True,
    )
    return {"status": "sent", "recipient": target_email, "invoice": si.name}


@frappe.whitelist()
def get_whatsapp_invoice_share_link(invoice_name, phone=None):
    """Generate a safe WhatsApp share URL for a Sales Invoice without sending automatically."""
    _require_pos_user()
    active_shift = _get_active_opening_shift(frappe.session.user)
    cfg = _get_effective_rpos_config(active_shift["pos_profile"] if active_shift else None)
    if not cint(cfg.get("allow_whatsapp_invoice")):
        frappe.throw(_("El envío de facturas por WhatsApp está deshabilitado en la configuración del POS."))

    if not invoice_name or not frappe.db.exists("Sales Invoice", invoice_name):
        frappe.throw(_("La factura solicitada no existe."))

    si = frappe.get_doc("Sales Invoice", invoice_name)
    si.check_permission("read")
    clean_phone = re.sub(r"[^\d]", "", cstr(phone or frappe.db.get_value("Customer", si.customer, "mobile_no") or ""))
    text = (
        f"Comprobante {si.name} - {si.company}\n"
        f"Cliente: {si.customer_name}\n"
        f"Total: {si.currency} {flt(si.grand_total, 2):,.2f}\n"
        f"CAI: {si.get('cai') or 'N/A'}"
    )
    from urllib.parse import quote

    base_url = f"https://wa.me/{clean_phone}" if clean_phone else "https://wa.me/"
    return {"url": f"{base_url}?text={quote(text)}", "invoice": si.name}


@frappe.whitelist()
def get_self_invoicing_receipt_data(invoice_name):
    """Return SAR Honduras fiscal receipt metadata and self-invoicing URL when enabled."""
    _require_pos_user()
    active_shift = _get_active_opening_shift(frappe.session.user)
    cfg = _get_effective_rpos_config(active_shift["pos_profile"] if active_shift else None)
    if not cint(cfg.get("enable_self_invoicing")):
        frappe.throw(_("La autofacturación está deshabilitada en la configuración del POS."))

    if not invoice_name or not frappe.db.exists("Sales Invoice", invoice_name):
        frappe.throw(_("La factura solicitada no existe."))

    si = frappe.get_doc("Sales Invoice", invoice_name)
    si.check_permission("read")
    return {
        "invoice": si.name,
        "company": si.company,
        "customer": si.customer_name,
        "tax_id": si.tax_id or "",
        "cai": si.get("cai") or "",
        "due_date_cai": cstr(si.get("due_date_cai") or ""),
        "grand_total": flt(si.grand_total, 2),
        "currency": si.currency,
        "portal_url": frappe.utils.get_url(f"/app/sales-invoice/{si.name}"),
    }




