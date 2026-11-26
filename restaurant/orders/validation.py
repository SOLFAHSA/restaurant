"""Restaurant Order validation and table status synchronization."""

import json

import frappe
from frappe import _
from frappe.utils import cint, cstr, flt

from restaurant.catalog.taxes import _get_item_tax_rates
from restaurant.pos_auth import is_supervisor, is_waiter_only, user_can_invoice
from restaurant.pos_context import _get_active_user_branch, _get_default_customer, _get_order_company
from restaurant.pos_settings.stations import _resolve_command_map
from restaurant.tax_configuration import taxes_included_in_price


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
    prices_include_tax = taxes_included_in_price(doc.company, doc.pos_profile) if doc.company else False
    exonerated = is_exonerated_order(doc)

    gross_by_rate = {15.0: 0.0, 18.0: 0.0}
    net_by_rate = {15.0: 0.0, 18.0: 0.0}
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

        line_rate = 0.0 if exonerated else row.tax_rate
        rate_key = next((key for key in gross_by_rate if abs(line_rate - key) < 0.01), None)
        if rate_key is not None:
            gross_by_rate[rate_key] += row.amount
            # ERPNext rounds the net amount of each tax-inclusive invoice line before taxing it.
            net_by_rate[rate_key] += flt(row.amount / (1 + rate_key / 100.0), 2)
        elif exonerated and prices_include_tax:
            # The exonerated invoice line is billed at the price without its ISV.
            exempt += net_exonerated_line_amount(row.qty, row.rate, row.tax_rate)
        else:
            exempt += row.amount

    if missing_tax_items:
        frappe.throw(
            _("Estos productos no tienen una plantilla de impuesto para la empresa {0}: {1}. Asígnala en el producto o en su grupo de productos.").format(
                doc.company, ", ".join(sorted(set(missing_tax_items)))
            )
        )

    # Match ERPNext taxes_and_totals: accumulate the taxable amount per rate and round once.
    taxable = {}
    isv = {}
    for rate, gross in gross_by_rate.items():
        if prices_include_tax:
            net = net_by_rate[rate]
            taxable[rate] = flt(net, 2)
            isv[rate] = flt(net * rate / 100.0, 2)
        else:
            taxable[rate] = flt(gross, 2)
            isv[rate] = flt(taxable[rate] * rate / 100.0, 2)

    doc.taxed_amount_15 = taxable[15.0]
    doc.isv_15 = isv[15.0]
    doc.taxed_amount_18 = taxable[18.0]
    doc.isv_18 = isv[18.0]
    doc.exempt_amount = flt(exempt, 2)
    doc.subtotal = flt(doc.taxed_amount_15 + doc.taxed_amount_18 + doc.exempt_amount, 2)
    doc.tax_amount = flt(doc.isv_15 + doc.isv_18, 2)
    if prices_include_tax:
        # Tax-inclusive prices: the invoice total is the sum of the prices, ISV is not added again.
        fiscal_total = flt(sum(gross_by_rate.values()) + exempt, 2)
    else:
        fiscal_total = flt(doc.subtotal + doc.tax_amount, 2)

    doc.tip_percentage = max(0.0, min(100.0, flt(doc.tip_percentage, 2)))
    if doc.tip_percentage > 0:
        doc.tip_amount = flt(doc.subtotal * (doc.tip_percentage / 100.0), 2)
    else:
        doc.tip_amount = max(0.0, flt(doc.tip_amount, 2))

    # The voluntary tip is collected for the staff: it is never part of the fiscal invoice total.
    doc.flags.fiscal_total = fiscal_total
    doc.grand_total = flt(fiscal_total + doc.tip_amount, 2)


def net_exonerated_line_amount(qty, rate, tax_rate):
    """Amount of an exonerated line when list prices include ISV (same rounding as the invoice line)."""
    net_rate = flt(flt(rate) / (1 + flt(tax_rate) / 100.0), 2)
    return flt(flt(qty) * net_rate, 2)


def is_exonerated_order(doc):
    """An order is exonerated when the checkout forces it or its customer has the Exonerado category."""
    forced = doc.flags.get("restaurant_tax_category")
    if forced:
        return cstr(forced).strip().upper() == "EXONERADO"
    if not doc.customer or not frappe.get_meta("Customer").has_field("tax_category"):
        return False
    category = frappe.db.get_value("Customer", doc.customer, "tax_category")
    return cstr(category).strip().upper() == "EXONERADO"


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
