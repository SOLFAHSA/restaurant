"""Restaurant POS entry point.

Endpoints keep their public path restaurant.pos.<name> (used by the POS JavaScript,
hooks and other apps); each one lives in its feature module and is re-exported here.
"""

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

from restaurant.pos_context import (  # noqa: F401
    _require_pos_user,
    _require_manager_user,
    _enforce_pin_rate_limit,
    _record_pin_failure,
    _clear_pin_failures,
    _get_active_user_branch,
    _get_default_company,
    _get_default_customer,
    _get_default_pos_profile,
    _get_active_opening_shift,
    _get_order_company,
    _check_order_company,
    _authorize_sensitive_operation,
)
from restaurant.cash.shift import (  # noqa: F401
    open_pos_shift,
    get_shift_cash_movements,
    create_cash_movement,
    get_closing_shift_preview,
    close_pos_shift,
)
from restaurant.pos_settings.config import (  # noqa: F401
    _get_effective_rpos_config,
    get_pos_idle_settings,
    save_pos_idle_settings,
    get_restaurant_pos_config,
    save_restaurant_pos_config,
    get_self_order_config,
)
from restaurant.pos_settings.stations import (  # noqa: F401
    _resolve_command_map,
    _row_stations,
    get_command_stations,
    get_command_configs,
    get_order_presets,
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


def _load_item_tax_template_rates(template_names):
    """Read configured rates for the order preview from enabled native Item Tax Templates."""
    if not template_names:
        return {}
    enabled_templates = frappe.get_all(
        "Item Tax Template",
        filters={"name": ["in", list(template_names)], "disabled": 0},
        pluck="name",
    )
    if not enabled_templates:
        return {}
    rates = {}
    for row in frappe.get_all(
        "Item Tax Template Detail",
        filters={"parent": ["in", enabled_templates], "parenttype": "Item Tax Template"},
        fields=["parent", "tax_rate"],
    ):
        rates[row.parent] = rates.get(row.parent, 0.0) + flt(row.tax_rate)
    return {template: rate for template, rate in rates.items() if rate in (0.0, 15.0, 18.0)}


def _sync_order_totals_from_invoice(order, invoice):
    """The issued invoice is the source of truth: show its discounted totals on the order."""
    isv_15 = flt(invoice.get("isv_15"), 2)
    isv_18 = flt(invoice.get("isv_18"), 2)
    order.db_set({
        "subtotal": flt(invoice.net_total, 2),
        "taxed_amount_15": flt(invoice.get("taxed_amount_15"), 2),
        "isv_15": isv_15,
        "taxed_amount_18": flt(invoice.get("taxed_amount_18"), 2),
        "isv_18": isv_18,
        "exempt_amount": flt(flt(invoice.get("exempt_amount")) + flt(invoice.get("exonerated_amount")), 2),
        "tax_amount": flt(isv_15 + isv_18, 2),
        "grand_total": flt(invoice.grand_total, 2),
    })


def _get_item_tax_rates(item_codes, company):
    """Resolve each item's rate with ERPNext's lookup: item templates first, then its item groups."""
    from erpnext.stock.get_item_details import get_item_tax_template

    args = frappe._dict(company=company, doctype="Sales Invoice", tax_category=None, transaction_date=nowdate())
    templates = {}
    for item_code in set(item_codes or []):
        out = {}
        get_item_tax_template(args, frappe.get_cached_doc("Item", item_code), out)
        templates[item_code] = out.get("item_tax_template")
    rates = _load_item_tax_template_rates({name for name in templates.values() if name})
    return {item_code: rates.get(template) for item_code, template in templates.items()}


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
        doc.company = _get_order_company()
    if not doc.currency:
        doc.currency = (
            frappe.db.get_value("Company", doc.company, "default_currency")
            if doc.company
            else "HNL"
        ) or "HNL"

    # Resolve and validate multi-branch ownership (Table -> Area -> POS Profile -> Shift -> User).
    table_branch = (
        frappe.db.get_value("Restaurant Table", doc.restaurant_table, "branch")
        if doc.restaurant_table and frappe.db.has_column("Restaurant Table", "branch")
        else ""
    ) or ""
    area_branch = (
        frappe.db.get_value("Restaurant Area", doc.restaurant_area, "branch")
        if doc.restaurant_area and frappe.db.has_column("Restaurant Area", "branch")
        else ""
    ) or ""
    prof_branch = (
        frappe.db.get_value("POS Profile", doc.pos_profile, "branch")
        if doc.pos_profile and frappe.db.has_column("POS Profile", "branch")
        else ""
    ) or ""
    if not prof_branch and doc.pos_opening_shift:
        shift_prof = frappe.db.get_value("POS Opening Shift", doc.pos_opening_shift, "pos_profile")
        if shift_prof and frappe.db.has_column("POS Profile", "branch"):
            prof_branch = frappe.db.get_value("POS Profile", shift_prof, "branch") or ""
    loc_branch = table_branch or area_branch
    if loc_branch and prof_branch and loc_branch != prof_branch:
        frappe.throw(
            _("La mesa o área seleccionada pertenece a la sucursal '{0}', distinta a la caja ({1}).").format(
                loc_branch, prof_branch
            ),
            frappe.ValidationError,
        )
    resolved_branch = loc_branch or prof_branch or _get_active_user_branch() or ""
    if meta.has_field("branch"):
        if resolved_branch:
            doc.branch = resolved_branch
        elif doc.get("branch"):
            doc.branch = cstr(doc.get("branch")).strip()

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
    taxed_18 = 0.0
    exempt = 0.0

    item_meta = frappe.get_meta("Restaurant Order Item")
    valid_item_kds_statuses = [
        opt.strip() for opt in (item_meta.get_field("kds_status").options or "").splitlines() if opt.strip()
    ]

    item_codes = list({row.item_code for row in (doc.items or []) if row.item_code})
    items_by_code = {}
    tax_rate_by_item = {}
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
        tax_rate_by_item = _get_item_tax_rates(item_codes, doc.company)
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

    missing_tax_items = []
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

        tax_rate = tax_rate_by_item.get(row.item_code)
        row.tax_rate = flt(tax_rate)

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
        if tax_rate is None:
            missing_tax_items.append(row.item_name or row.item_code)
            continue

        subtotal += row.amount
        if abs(row.tax_rate - 15.0) < 0.01:
            taxed_15 += row.amount
        elif abs(row.tax_rate - 18.0) < 0.01:
            taxed_18 += row.amount
        else:
            exempt += row.amount

    if missing_tax_items:
        frappe.throw(
            _("Estos productos no tienen una plantilla de impuesto para la empresa {0}: {1}. Asígnala en el producto o en su grupo de productos.").format(
                doc.company, ", ".join(sorted(set(missing_tax_items)))
            )
        )

    doc.subtotal = flt(subtotal, 2)
    doc.taxed_amount_15 = flt(taxed_15, 2)
    # Match ERPNext Sales Invoice taxes_and_totals: accumulate taxable net per rate before rounding once.
    doc.isv_15 = flt(doc.taxed_amount_15 * 0.15, 2)
    doc.taxed_amount_18 = flt(taxed_18, 2)
    doc.isv_18 = flt(doc.taxed_amount_18 * 0.18, 2)
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


def build_order_serialization_context(docs):
    """Prefetch waiter/pin/cashier lookup maps once for a batch of Restaurant Orders."""
    doc_list = [d for d in (docs or []) if d]
    linked_emp = get_linked_employee_for_user()
    waiter_only = is_waiter_only()

    waiter_has_pin = set()
    if waiter_only and not linked_emp:
        waiter_ids = sorted({
            d.waiter for d in doc_list
            if getattr(d, "waiter", None) and getattr(d, "status", None) not in ("Facturada", "Cancelada")
        })
        if waiter_ids:
            try:
                auth_rows = frappe.db.sql(
                    """
                    SELECT DISTINCT name FROM `__Auth`
                    WHERE doctype = 'Employee' AND fieldname = 'restaurant_pos_pin'
                      AND name IN %s
                    """,
                    (tuple(waiter_ids),),
                )
                waiter_has_pin = {r[0] for r in (auth_rows or []) if r and r[0]}
            except Exception:
                waiter_has_pin = {wid for wid in waiter_ids if employee_has_pin(wid)}

    cashier_ids = sorted({d.cashier for d in doc_list if getattr(d, "cashier", None)})
    cashier_names = {}
    if cashier_ids:
        for urow in frappe.get_all("User", filters={"name": ["in", cashier_ids]}, fields=["name", "full_name"]):
            cashier_names[urow.name] = urow.full_name or urow.name

    return {
        "linked_emp": linked_emp,
        "waiter_only": waiter_only,
        "waiter_has_pin": waiter_has_pin,
        "cashier_names": cashier_names,
    }


class _BatchOrderObj:
    """Attribute-safe batch container for Restaurant Order without dict.items() collision."""

    def __init__(self, row, items):
        self.__dict__.update(row)
        self.items = list(items or [])

    def get(self, key, default=None):
        return self.__dict__.get(key, default)


def _load_orders_batch(filters=None, order_by="modified desc", limit_page_length=100, use_list_perms=True):
    """Fetch Restaurant Orders and their child items in exactly 2 batched SQL queries."""
    meta = frappe.get_meta("Restaurant Order")
    candidate_fields = [
        "name", "order_name", "reference_note", "status", "service_type",
        "restaurant_area", "restaurant_table", "table_label", "branch", "guests",
        "waiter", "waiter_name", "customer", "customer_name", "tax_id",
        "pos_profile", "pos_opening_shift", "cashier", "company", "currency",
        "selling_price_list", "kds_status", "sent_to_kitchen_at", "scheduled_time",
        "customer_note", "precuenta_printed", "subtotal", "taxed_amount_15",
        "isv_15", "taxed_amount_18", "isv_18", "exempt_amount", "tax_amount",
        "tip_percentage", "tip_amount", "grand_total", "sales_invoice", "cai",
        "due_date_cai", "creation", "modified", "docstatus",
    ]
    fields = [f for f in candidate_fields if f in ("name", "creation", "modified", "docstatus") or meta.has_field(f)]
    getter = frappe.get_list if use_list_perms else frappe.get_all
    rows = getter(
        "Restaurant Order",
        filters=filters or {},
        fields=fields,
        order_by=order_by,
        limit_page_length=limit_page_length,
    )
    if not rows:
        return []

    order_names = [r.name for r in rows]
    item_meta = frappe.get_meta("Restaurant Order Item")
    item_candidate_fields = [
        "name", "parent", "idx", "item_code", "item_name", "item_group", "qty", "uom",
        "base_rate", "options_rate", "discount_percentage", "rate", "amount", "tax_rate",
        "options_summary", "selected_options_json", "note", "command_station", "kds_status",
        "is_cancelled", "cancelled_qty", "cancellation_reason", "cancelled_by",
        "cancelled_by_supervisor", "cancelled_at",
    ]
    item_fields = [
        f for f in item_candidate_fields
        if f in ("name", "parent", "idx") or item_meta.has_field(f)
    ]
    item_rows = frappe.get_all(
        "Restaurant Order Item",
        filters={"parent": ["in", order_names], "parenttype": "Restaurant Order"},
        fields=item_fields,
        order_by="idx asc",
        limit_page_length=5000,
    )
    items_by_parent = {}
    for irow in item_rows:
        items_by_parent.setdefault(irow.parent, []).append(irow)
    return [_BatchOrderObj(row, items_by_parent.get(row.name, [])) for row in rows]


def _serialize_order(doc, serial_ctx=None):
    if isinstance(doc, str):
        doc = frappe.get_doc("Restaurant Order", doc)
    items = []
    for row in (doc.get("items") if hasattr(doc, "get") else getattr(doc, "items", [])) or []:
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
    now_dt = now_datetime()
    created_dt = get_datetime(doc.creation) if doc.creation else now_dt
    elapsed_mins = max(0, int((now_dt - created_dt).total_seconds() // 60))
    if serial_ctx is not None:
        linked_emp = serial_ctx["linked_emp"]
        waiter_only = serial_ctx["waiter_only"]
        waiter_pin_ok = bool(doc.waiter and doc.waiter in serial_ctx["waiter_has_pin"])
        cashier_name = serial_ctx["cashier_names"].get(doc.cashier, "") if doc.cashier else ""
    else:
        linked_emp = get_linked_employee_for_user()
        waiter_only = is_waiter_only()
        waiter_pin_ok = bool(
            doc.waiter
            and waiter_only
            and not linked_emp
            and doc.status not in ("Facturada", "Cancelada")
            and employee_has_pin(doc.waiter)
        )
        cashier_name = get_fullname(doc.cashier) if doc.cashier else ""

    requires_pin_unlock = bool(
        doc.waiter
        and waiter_only
        and not linked_emp
        and doc.status not in ("Facturada", "Cancelada")
        and waiter_pin_ok
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
        "branch": getattr(doc, "branch", "") or "",
        "guests": cint(doc.guests or 1),
        "waiter": doc.waiter or "",
        "waiter_name": doc.waiter_name or "",
        "customer": doc.customer or "",
        "customer_name": doc.customer_name or doc.customer or "",
        "tax_id": doc.tax_id or "",
        "pos_profile": doc.pos_profile or "",
        "pos_opening_shift": doc.pos_opening_shift or "",
        "cashier": doc.cashier or "",
        "cashier_name": cashier_name,
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


def _get_catalog_for_pos(selling_price_list=None, allowed_categories=None, company=None):
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

    # Selling prices are menu data for every POS user; buying prices stay private.
    price_map = {}
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

    tax_rate_by_item = _get_item_tax_rates(
        [item.name for item in raw_items], company or _get_default_company()
    )

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
            "tax_rate": tax_rate_by_item.get(item.name),
            "restaurant_recipe_enabled": cint(item.restaurant_recipe_enabled),
            "restaurant_options_enabled": cint(item.restaurant_options_enabled),
            "is_combo": bool(is_combo),
            "command_station": ", ".join(stations) if stations else "Cocina General",
            "option_groups": opt_groups,
        })

    return categories, items


def _get_areas_with_live_tables(branch=None, company=None):
    """Return active Restaurant Areas with floor map elements and live table order status."""
    from restaurant.table_management import parse_area_layout

    if not frappe.has_permission("Restaurant Area", "read"):
        return []

    effective_branch = _get_active_user_branch() if branch is None else branch
    area_filters = {"status": "Activa"}
    if effective_branch:
        area_filters["branch"] = effective_branch

    areas = frappe.get_list(
        "Restaurant Area",
        filters=area_filters,
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

    open_order_filters = {"status": "En curso", "company": company or _get_order_company()}
    if effective_branch and frappe.get_meta("Restaurant Order").has_field("branch"):
        open_order_filters["branch"] = effective_branch

    open_orders = frappe.get_all(
        "Restaurant Order",
        filters=open_order_filters,
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
                "status": "Ocupada" if live else (row.status if row.status in ("Inactiva", "Reservada") else "Disponible"),
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
    """Read the configured series and its active authorization for the POS bootstrap."""
    company = company or _get_default_company()
    profile = frappe.db.get_value("POS Profile", pos_profile, ["company", "prefix"], as_dict=True) if pos_profile else None
    prefix = cstr(profile.prefix).strip() if profile and profile.company == company else ""
    fiscal_info = {
        "cai": "",
        "due_date_cai": "",
        "authorized_range": "",
        "prefix": prefix,
        "company_tax_id": cstr(frappe.db.get_value("Company", company, "tax_id")) if company else "",
    }
    if not prefix:
        return fiscal_info

    authorizations = frappe.get_all(
        "CAI",
        filters={"status": "Active", "prefix": prefix, "select_doc_for_series": "Sales Invoice"},
        fields=["cai", "issue_deadline", "initial_number", "final_number"],
        limit=2,
    )
    if len(authorizations) == 1:
        authorization = authorizations[0]
        series_key = prefix.rsplit(".", 1)[0]
        fiscal_info.update({
            "cai": cstr(authorization.cai),
            "due_date_cai": cstr(authorization.issue_deadline),
            "authorized_range": f"{series_key}{cint(authorization.initial_number):08d} al {series_key}{cint(authorization.final_number):08d}",
        })
    return fiscal_info


@frappe.whitelist()
def get_pos_bootstrap(area_name=None):
    """Return all operational context needed to launch the Restaurant POS."""
    _require_pos_user()
    opening_shift = _get_active_opening_shift(frappe.session.user)
    company = opening_shift["company"] if opening_shift else _get_default_company()
    default_profile = (
        frappe.get_cached_doc("POS Profile", opening_shift["pos_profile"])
        if opening_shift else _get_default_pos_profile(company)
    )

    prof_meta = frappe.get_meta("POS Profile")
    prof_fields = ["name", "company", "currency", "selling_price_list", "warehouse", "customer"]
    optional_prof_fields = (
        "branch",
        "prefix",
        "company_address",
        "print_format",
        "disable_rounded_total",
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
            "branch": prof.get("branch") or "",
            "currency": prof.currency or "HNL",
            "selling_price_list": prof.selling_price_list or "Venta estándar",
            "warehouse": prof.warehouse or "",
            "default_customer": prof.customer or default_customer_fallback,
            "prefix": prof.get("prefix") or "",
            "company_address": prof.get("company_address") or "",
            "print_format": prof.get("print_format") or "Ticket",
            "disable_rounded_total": cint(prof.get("disable_rounded_total") if prof.get("disable_rounded_total") is not None else 1),
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

    linked_waiter = get_linked_employee_for_user()
    active_branch = _get_active_user_branch(opening_shift=opening_shift, linked_waiter=linked_waiter)

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
    categories, items = _get_catalog_for_pos(active_price_list, allowed_categories=allowed_cats, company=company)
    areas = _get_areas_with_live_tables(branch=active_branch, company=company)

    waiter_filters = {"designation": "Mesero", "status": "Active"}
    if active_branch:
        waiter_filters["branch"] = ["in", [active_branch, "", None]]
    waiters = frappe.get_all(
        "Employee",
        filters=waiter_filters,
        fields=["name", "employee_name", "branch"],
        order_by="employee_name asc",
    )

    cust_meta = frappe.get_meta("Customer")
    cust_fields = ["name", "customer_name", "tax_id", "default_price_list"]
    for extra_cf in (
        "email_id",
        "mobile_no",
        "primary_address",
        "territory",
        "tax_category",
        "custom_subtipo_exonerado",
        "custom_constancia_exonerado",
        "custom_carnet_diplomatico",
        "custom_registro_sag",
    ):
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
            "tax_category": cstr(c.get("tax_category") or "Contribuyente"),
            "custom_subtipo_exonerado": cstr(c.get("custom_subtipo_exonerado") or ""),
            "custom_constancia_exonerado": cstr(c.get("custom_constancia_exonerado") or ""),
            "custom_carnet_diplomatico": cstr(c.get("custom_carnet_diplomatico") or ""),
            "custom_registro_sag": cstr(c.get("custom_registro_sag") or ""),
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


    waiter_only = is_waiter_only()
    can_invoice = user_can_invoice()
    supervisor_flag = is_supervisor()

    order_filters = {"company": company}
    if active_branch and frappe.get_meta("Restaurant Order").has_field("branch"):
        order_filters["branch"] = active_branch
    if not cint(rpos_config.get("share_open_orders", 1)):
        order_filters["owner"] = frappe.session.user
    if waiter_only and linked_waiter:
        order_filters["waiter"] = linked_waiter["name"]

    order_docs = _load_orders_batch(
        filters=order_filters,
        order_by="modified desc",
        limit_page_length=100,
        use_list_perms=True,
    )
    serial_ctx = build_order_serialization_context(order_docs)
    orders = [_serialize_order(row, serial_ctx=serial_ctx) for row in order_docs]

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
        "active_branch": active_branch or "",
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
        "rounding_method": frappe.get_system_settings("rounding_method") or "Banker's Rounding (legacy)",
        "rpos_config": rpos_config,
        "fiscal_defaults": {
            "cai": fiscal_info["cai"],
            "due_date_cai": fiscal_info["due_date_cai"],
            "authorized_range": fiscal_info["authorized_range"],
            "prefix": fiscal_info["prefix"],
        },
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

    active_shift = _get_active_opening_shift(frappe.session.user)
    company = active_shift["company"] if active_shift else _get_default_company()
    if not company or (payload.get("company") and payload["company"] != company):
        frappe.throw(_("La empresa indicada no coincide con la empresa activa."), frappe.PermissionError)
    for field, doctype in (("pos_profile", "POS Profile"), ("pos_opening_shift", "POS Opening Shift")):
        if payload.get(field) and frappe.db.get_value(doctype, payload[field], "company") != company:
            frappe.throw(_("El perfil o turno no pertenece a la empresa activa."), frappe.PermissionError)

    order_id = cstr(payload.get("name") or "").strip()
    if order_id:
        if not frappe.db.get_value("Restaurant Order", order_id, "name", for_update=True):
            frappe.throw(_("La cuenta u orden solicitada no existe."), frappe.DoesNotExistError)
        doc = frappe.get_doc("Restaurant Order", order_id, for_update=True)
        _check_order_company(doc, company)
        doc.check_permission("write")
        if doc.status == "Facturada":
            frappe.throw(_("Esta orden ya fue facturada y no puede modificarse."))
        token = cstr(payload.get("expected_modified") or payload.get("modified") or "").strip()
        if "expected_modified" in payload or "modified" in payload:
            try:
                token_matches = bool(token) and get_datetime(token) == get_datetime(doc.modified)
            except (TypeError, ValueError, OverflowError):
                token_matches = False
            if not token_matches:
                frappe.throw(
                    _("Esta orden fue modificada recientemente por otro usuario. Recarga la cuenta antes de guardar cambios."),
                    frappe.TimestampMismatchError,
                )
    else:
        if not frappe.has_permission("Restaurant Order", "create"):
            frappe.throw(_("No tienes permisos para abrir cuentas u órdenes."), frappe.PermissionError)
        doc = frappe.new_doc("Restaurant Order")

    doc.company = company
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

    if active_shift and (not order_id or not doc.pos_opening_shift):
        doc.pos_opening_shift = active_shift["name"]
        doc.pos_profile = active_shift["pos_profile"]

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
    _check_order_company(doc)
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
    _check_order_company(doc)
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

    company_name = doc.company or _get_default_company()
    company_rtn = cstr(frappe.db.get_value("Company", company_name, "tax_id")) if company_name else ""

    return {
        "company_name": company_name,
        "company_rtn": company_rtn,
        "printed_at": f"{nowdate()} {nowtime()[:8]}",
        "order": _serialize_order(doc),
    }


def _resolve_payment_account(mode_of_payment, company):
    """Read the payment account configured for this company's Mode of Payment."""
    account = frappe.db.get_value(
        "Mode of Payment Account",
        {"parent": mode_of_payment, "company": company},
        "default_account",
    )
    if not account:
        frappe.throw(_("Configura la cuenta de pago de {0} para {1}.").format(mode_of_payment, company))
    return account


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


def _set_doc_field(doc, fieldname, value):
    setter = getattr(doc, "set", None)
    if callable(setter) and not isinstance(doc, dict):
        setter(fieldname, value)
    elif isinstance(doc, dict):
        doc[fieldname] = value
    else:
        setattr(doc, fieldname, value)


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
    tax_category=None,
    custom_orden_compra_exenta=None,
    custom_constancia_exonerado=None,
    custom_carnet_diplomatico=None,
    custom_registro_sag=None,
    supervisor_user=None,
    supervisor_pin=None,
    reason=None,
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
    _check_order_company(doc)
    doc.check_permission("write")
    if doc.status == "Facturada" or doc.sales_invoice:
        frappe.throw(_("Esta cuenta ya fue facturada en el documento {0}.").format(doc.sales_invoice or doc.name))
    if doc.status == "Cancelada" or doc.docstatus == 2:
        frappe.throw(_("No se puede facturar una orden cancelada."))
    if not doc.items:
        frappe.throw(_("No puedes facturar una orden sin platillos ni productos."))

    company = doc.company
    active_shift_info = _get_active_opening_shift(frappe.session.user)
    pos_profile = active_shift_info.get("pos_profile") if active_shift_info else doc.pos_profile
    if not pos_profile:
        default_prof = _get_default_pos_profile(company)
        pos_profile = default_prof.name if default_prof else None
    prof_doc = frappe.get_doc("POS Profile", pos_profile) if pos_profile else None
    if not prof_doc or cint(prof_doc.disabled) or prof_doc.company != company or not prof_doc.prefix:
        frappe.throw(_("Configura una serie fiscal en un perfil POS activo de la empresa de esta orden."))
    if frappe.db.exists("POS Profile", {
        "prefix": prof_doc.prefix, "company": ["!=", company], "disabled": 0,
    }):
        frappe.throw(_("La serie fiscal del perfil POS está asignada a más de una empresa."))
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

    if (gift_card_code or flt(gift_card_amount)) and not cint(rpos_cfg.get("enable_gift_cards", 0)):
        frappe.throw(_("Las tarjetas de regalo están deshabilitadas en la configuración del POS."))

    if flt(loyalty_points) > 0 and not cint(rpos_cfg.get("enable_loyalty_program", 0)):
        frappe.throw(_("El programa de lealtad está deshabilitado en la configuración del POS."))

    if customer and frappe.db.exists("Customer", customer):
        doc.customer = customer
    if tax_id is not None:
        doc.tax_id = cstr(tax_id).strip()[:60]
        if (
            doc.customer
            and doc.tax_id
            and doc.customer.strip().upper() != "CONSUMIDOR FINAL"
            and frappe.has_permission("Customer", "write")
        ):
            frappe.db.set_value("Customer", doc.customer, "tax_id", doc.tax_id)

    if tip_percentage is not None:
        doc.tip_percentage = max(0.0, flt(tip_percentage, 2))
        if doc.tip_percentage == 0 and tip_amount is not None:
            doc.tip_amount = max(0.0, flt(tip_amount, 2))
    elif tip_amount is not None:
        doc.tip_percentage = 0.0
        doc.tip_amount = max(0.0, flt(tip_amount, 2))

    validate_order(doc)

    warehouse = prof_doc.warehouse
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

    from restaurant.tax_configuration import get_native_tax_configuration, get_item_tax_template

    invoice_items = []
    for row in doc.items:
        if cint(getattr(row, "is_cancelled", 0)) or row.kds_status == "Cancelado":
            continue
        desc_parts = [row.item_name or row.item_code]
        if row.options_summary:
            desc_parts.append(f"Opciones: {row.options_summary}")
        if row.note:
            desc_parts.append(f"Nota: {row.note}")
        item_entry = {
            "item_code": row.item_code,
            "item_name": row.item_name,
            "description": " | ".join(desc_parts),
            "qty": flt(row.qty),
            "uom": row.uom,
            "rate": flt(row.rate, 2),
            "price_list_rate": flt(row.base_rate + row.options_rate, 2),
            "discount_percentage": flt(row.discount_percentage, 2),
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

    update_stock = int(_invoice_has_stock_items(invoice_items))
    if update_stock and (not warehouse or prof_doc.company != company):
        frappe.throw(_("Configura un almacén en un perfil POS de la misma empresa para facturar productos inventariables."))

    service_taxes = []
    if doc.tip_amount > 0:
        service_acc = _resolve_service_income_account(company)
        if service_acc:
            service_taxes.append({
                "charge_type": "Actual",
                "account_head": service_acc,
                "description": "Servicio sugerido / Propina",
                "tax_amount": flt(doc.tip_amount, 2),
                "cost_center": cost_center,
            })

    from restaurant.gift_certificates import GIFT_CERT_MOP_NAME

    enabled_mops = {row.mode_of_payment for row in prof_doc.payments if row.mode_of_payment}
    parsed_payments = frappe.parse_json(payments) if isinstance(payments, str) else payments
    payment_rows = []
    if isinstance(parsed_payments, list):
        for p in parsed_payments:
            if isinstance(p, dict) and p.get("mode_of_payment") and flt(p.get("amount")) > 0:
                mop = p["mode_of_payment"]
                if mop == GIFT_CERT_MOP_NAME:
                    frappe.throw(_("Escanea el código para aplicar un Certificado de Regalo."))
                if mop not in enabled_mops:
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
    certificate = None
    if gift_card_code or flt(gift_card_amount):
        from restaurant.gift_certificates import get_certificate_for_redemption

        certificate = get_certificate_for_redemption(gift_card_code, company)


    # Prefer the billing cashier's active open shift so orders from prior closed shifts bill cleanly
    # and reconcile in the current cashier's shift/closing count.
    active_opening_shift = ""
    if active_shift_info:
        _check_order_company(doc, active_shift_info["company"])
        active_opening_shift = active_shift_info.get("name") or ""
    elif doc.pos_opening_shift:
        shift_row = frappe.db.get_value(
            "POS Opening Shift",
            doc.pos_opening_shift,
            ["name", "status", "docstatus", "company"],
            as_dict=True,
        )
        if shift_row and shift_row.company == company and shift_row.status == "Open" and cint(shift_row.docstatus) == 1:
            active_opening_shift = shift_row.name

    si_payload = {
        "doctype": "Sales Invoice",
        "company": company,
        "customer": doc.customer,
        "tax_id": doc.tax_id or "",
        "posting_date": nowdate(),
        "posting_time": nowtime(),
        "set_posting_time": 1,
        "due_date": nowdate(),
        "is_pos": 1,
        "pos_profile": pos_profile,
        "posa_pos_opening_shift": active_opening_shift or "",
        "currency": doc.currency or "HNL",
        "selling_price_list": doc.selling_price_list or (prof_doc.selling_price_list if prof_doc else "Venta estándar"),
        "update_stock": update_stock,
        "disable_rounded_total": 1 if not cint(rpos_cfg.get("enable_rounded_total", 0)) else 0,
        "naming_series": prof_doc.prefix,
        "posa_notes": f"Orden: {doc.order_name} | Mesa: {doc.table_label or 'N/A'} | Mesero: {doc.waiter_name or 'N/A'}",
        "items": invoice_items,
        "payments": payment_rows,
    }
    if update_stock:
        si_payload["set_warehouse"] = warehouse
    if prof_doc and getattr(prof_doc, "company_address", None):
        si_payload["company_address"] = prof_doc.company_address

    if flt(global_discount_percentage) > 0:
        si_payload["apply_discount_on"] = "Grand Total"
        si_payload["additional_discount_percentage"] = min(100.0, flt(global_discount_percentage, 2))
    elif flt(global_discount_amount) > 0:
        si_payload["apply_discount_on"] = "Grand Total"
        si_payload["discount_amount"] = flt(global_discount_amount, 2)

    if coupon_code and frappe.db.exists("Coupon Code", coupon_code):
        si_payload["coupon_code"] = coupon_code

    si_meta = frappe.get_meta("Sales Invoice")
    cust_meta = frappe.get_meta("Customer")
    cust_lookup_fields = ["tax_category"] if cust_meta.has_field("tax_category") else []
    for exo_f in (
        "custom_subtipo_exonerado",
        "custom_constancia_exonerado",
        "custom_carnet_diplomatico",
        "custom_registro_sag",
    ):
        if cust_meta.has_field(exo_f):
            cust_lookup_fields.append(exo_f)
    cust_info = (
        frappe.db.get_value("Customer", doc.customer, cust_lookup_fields, as_dict=True)
        if doc.customer and cust_lookup_fields
        else {}
    ) or {}
    resolved_tax_category = cstr(tax_category or cust_info.get("tax_category") or "Contribuyente").strip()
    if si_meta.has_field("tax_category"):
        si_payload["tax_category"] = resolved_tax_category

    is_exonerated = resolved_tax_category.upper() == "EXONERADO"
    native_taxes = get_native_tax_configuration(company)
    si_payload["taxes_and_charges"] = native_taxes[
        "exonerated_taxes_and_charges" if is_exonerated else "taxes_and_charges"
    ]
    for item_entry, order_row in zip(invoice_items, (
        row for row in doc.items if not cint(row.is_cancelled) and row.kds_status != "Cancelado"
    )):
        item_entry["item_tax_template"] = get_item_tax_template(
            company, 0 if is_exonerated else order_row.tax_rate,
        )
    exo_values = {
        "custom_subtipo_exonerado": cstr(cust_info.get("custom_subtipo_exonerado") or "").strip() if is_exonerated else "",
        "custom_orden_compra_exenta": cstr(custom_orden_compra_exenta or "").strip() if is_exonerated else "",
        "custom_constancia_exonerado": cstr(custom_constancia_exonerado or cust_info.get("custom_constancia_exonerado") or "").strip() if is_exonerated else "",
        "custom_carnet_diplomatico": cstr(custom_carnet_diplomatico or cust_info.get("custom_carnet_diplomatico") or "").strip() if is_exonerated else "",
        "custom_registro_sag": cstr(custom_registro_sag or cust_info.get("custom_registro_sag") or "").strip() if is_exonerated else "",
    }
    for exo_field, exo_val in exo_values.items():
        if si_meta.has_field(exo_field):
            si_payload[exo_field] = exo_val

    for r_field, r_val in (
        ("restaurant_order", doc.name),
        ("restaurant_order_number", cstr(doc.order_name or doc.name)),
        ("restaurant_table_label", cstr(doc.table_label or "")),
        ("restaurant_service_type", cstr(doc.service_type or "")),
        ("restaurant_waiter_name", cstr(doc.waiter_name or "")),
    ):
        if si_meta.has_field(r_field):
            si_payload[r_field] = r_val

    if si_meta.has_field("cashier"):
        si_payload["cashier"] = frappe.session.user
    if si_meta.has_field("redeem_loyalty_points") and flt(loyalty_points) > 0:
        si_payload["redeem_loyalty_points"] = 1
        si_payload["loyalty_points"] = cint(loyalty_points)

    si = frappe.get_doc(si_payload)
    si.set_missing_values()
    _set_doc_field(si, "payments", payment_rows)
    si.update_stock = update_stock
    si.disable_rounded_total = si_payload["disable_rounded_total"]
    si.tax_category = resolved_tax_category
    si.taxes_and_charges = si_payload["taxes_and_charges"]
    # Load the native tax master after POS defaults and preserve the service charge.
    from erpnext.controllers.accounts_controller import get_taxes_and_charges

    _set_doc_field(si, "taxes", get_taxes_and_charges(
        "Sales Taxes and Charges Template", si.taxes_and_charges,
    ) + service_taxes)
    si.calculate_taxes_and_totals()

    _approve_checkout_discounts(si, doc, prof_doc, supervisor_user, supervisor_pin, reason)
    grand_total = flt(si.grand_total, 2)
    if certificate:
        from restaurant.gift_certificates import apply_certificate

        apply_certificate(si, certificate, gift_card_amount)
    expected_paid_due = flt(si.rounded_total if not cint(si.disable_rounded_total) else grand_total, 2)
    total_paid = sum(flt(p.amount) for p in si.payments)
    total_paid_cents = round(flt(total_paid, 2) * 100)
    expected_due_cents = round(flt(expected_paid_due, 2) * 100)
    if total_paid_cents < expected_due_cents:
        frappe.throw(
            _("El monto total pagado ({0:.2f}) es menor al total por cobrar ({1:.2f}).").format(
                flt(total_paid, 2), flt(expected_paid_due, 2)
            )
        )

    if expected_due_cents == 0 and total_paid_cents > 0:
        frappe.throw(_("Una factura con total cero no admite un importe recibido."))
    if not si.payments and expected_due_cents == 0:
        # ERPNext requires a payment row even when the invoice has no amount due.
        zero_payment = next((row for row in prof_doc.payments if cint(row.default)), None)
        zero_payment = zero_payment or next(iter(prof_doc.payments), None)
        if not zero_payment:
            frappe.throw(_("Configura un método de pago en el perfil de Punto de Venta."))
        si.append("payments", {
            "mode_of_payment": zero_payment.mode_of_payment,
            "amount": 0,
            "account": _resolve_payment_account(zero_payment.mode_of_payment, company),
        })

    si.insert(ignore_permissions=True)
    auto_submit = bool(cint(rpos_cfg.get("auto_validate_orders", 1)))
    if auto_submit:
        si.submit()

    invoice_finalized = (cint(getattr(si, "docstatus", 0)) == 1) or auto_submit

    if active_opening_shift:
        doc.pos_opening_shift = active_opening_shift
    doc.sales_invoice = si.name
    doc.cai = si.cai
    doc.due_date_cai = si.due_date_cai
    doc.status = "Facturada" if invoice_finalized else "En curso"
    doc.save()
    if invoice_finalized:
        _sync_order_totals_from_invoice(doc, si)

    from restaurant.sar_format import format_lempiras_in_words

    return {
        "order": _serialize_order(doc),
        "invoice": {
            "name": si.name,
            "posting_date": str(si.posting_date),
            "posting_time": cstr(si.get("posting_time") or ""),
            "customer": si.customer,
            "customer_name": si.customer_name,
            "tax_id": si.tax_id or "",
            "tax_category": cstr(si.get("tax_category") or "Contribuyente"),
            "custom_orden_compra_exenta": cstr(si.get("custom_orden_compra_exenta") or ""),
            "custom_constancia_exonerado": cstr(si.get("custom_constancia_exonerado") or ""),
            "custom_carnet_diplomatico": cstr(si.get("custom_carnet_diplomatico") or ""),
            "custom_registro_sag": cstr(si.get("custom_registro_sag") or ""),
            "company": si.company,
            "company_tax_id": cstr(si.company_tax_id),
            "cai": cstr(si.cai),
            "due_date_cai": cstr(si.due_date_cai),
            "authorized_range": cstr(si.get("authorized_range")),
            "prefix": cstr(si.get("naming_series")) or prof_doc.prefix,
            "print_format": (prof_doc.print_format if prof_doc and prof_doc.print_format else "Ticket"),
            "net_total": flt(si.net_total, 2),
            "discount_amount": flt(si.get("discount_amount"), 2),
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
            "in_words": format_lempiras_in_words(si.grand_total),
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
    """Synchronize KDS tickets and publish a realtime update after item or order mutation."""
    try:
        from restaurant.kds import _sync_legacy_status, publish_kds_realtime_update
        _sync_legacy_status(doc)
        publish_kds_realtime_update(doc=doc, source="order_change")
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


@frappe.whitelist(methods=["POST"])
def authorize_reprint_command(order_name, supervisor_user=None, supervisor_pin=None, reason=""):
    """Verify supervisor authorization to reprint kitchen commands for an order."""
    _require_pos_user()
    if not order_name or not frappe.db.exists("Restaurant Order", order_name):
        frappe.throw(_("La cuenta u orden no existe."), frappe.DoesNotExistError)
    _check_order_company(frappe.get_doc("Restaurant Order", order_name))
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
    if not user_can_invoice():
        frappe.throw(
            _("Solo cajeros autorizados o supervisores pueden crear o editar clientes."),
            frappe.PermissionError,
        )
    clean_name = cstr(customer_name).strip()
    clean_rtn = cstr(tax_id).strip()[:60]
    clean_email = cstr(email_id).strip()[:140]
    clean_phone = cstr(mobile_no).strip()[:60]
    clean_addr = cstr(address).strip()[:200]
    if not clean_name:
        frappe.throw(_("El nombre o razón social del cliente es obligatorio."))

    cust_meta = frappe.get_meta("Customer")
    if customer_id and frappe.db.exists("Customer", customer_id):
        if customer_id.strip().upper() == "CONSUMIDOR FINAL":
            frappe.throw(_("No puedes sobrescribir el cliente genérico CONSUMIDOR FINAL."), frappe.PermissionError)
        doc = frappe.get_doc("Customer", customer_id)
        doc.check_permission("write")
        doc.customer_name = clean_name
        doc.tax_id = clean_rtn
        if email_id is not None and cust_meta.has_field("email_id"):
            doc.email_id = clean_email
        if mobile_no is not None and cust_meta.has_field("mobile_no"):
            doc.mobile_no = clean_phone
        if address is not None and cust_meta.has_field("primary_address"):
            doc.primary_address = clean_addr
        doc.save()
    else:
        if not frappe.has_permission("Customer", "create"):
            frappe.throw(_("No tienes permisos para registrar nuevos clientes."), frappe.PermissionError)
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
        doc.insert()

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
    cmd_filters = {"status": ["in", ["En curso", "Facturada"]], "company": _get_order_company()}
    active_branch = _get_active_user_branch()
    if active_branch and frappe.get_meta("Restaurant Order").has_field("branch"):
        cmd_filters["branch"] = active_branch
    order_docs = _load_orders_batch(
        filters=cmd_filters,
        order_by="sent_to_kitchen_at desc, modified desc",
        limit_page_length=max(10, min(100, cint(limit or 40))),
        use_list_perms=True,
    )
    serial_ctx = build_order_serialization_context(order_docs)
    emitted = []
    for row in order_docs:
        serialized = _serialize_order(row, serial_ctx=serial_ctx)
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


@frappe.whitelist(methods=["POST"])
def validate_gift_card(card_code):
    """Validate a native gift certificate for the current company."""
    _require_pos_user()
    if not user_can_invoice():
        frappe.throw(_("Solo cajeros o supervisores pueden validar certificados de regalo."), frappe.PermissionError)

    active_shift = _get_active_opening_shift(frappe.session.user)
    cfg = _get_effective_rpos_config(active_shift["pos_profile"] if active_shift else None)
    if not cint(cfg.get("enable_gift_cards")):
        frappe.throw(_("Los certificados de regalo están deshabilitados en la configuración del POS."))

    from restaurant.gift_certificates import get_certificate_for_redemption

    company = active_shift["company"] if active_shift else _get_order_company()
    certificate = get_certificate_for_redemption(card_code, company)
    return {
        "masked_code": certificate["codigo_enmascarado"],
        "balance": flt(certificate["saldo_disponible"], 2),
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

    attachment = frappe.attach_print(
        "Sales Invoice",
        si.name,
        file_name=f"{si.name}.pdf",
        print_format="Ticket",
    )
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
