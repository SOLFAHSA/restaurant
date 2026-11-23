"""Restaurant POS entry point.

Endpoints keep their public path restaurant.pos.<name> (used by the POS JavaScript,
hooks and other apps); each one lives in its feature module and is re-exported here.
"""

import re

import frappe
from frappe import _
from frappe.utils import cint, cstr, flt, get_fullname, nowdate, nowtime

from restaurant.pos_auth import (
    get_linked_employee_for_user,
    get_supervisors_for_pos,
    is_cashier_only,
    is_direct_cashier,
    is_supervisor,
    is_waiter_only,
    log_restaurant_audit,
    user_can_invoice,
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
from restaurant.catalog.taxes import (  # noqa: F401
    _load_item_tax_template_rates,
    _get_item_tax_rates,
)
from restaurant.catalog.menu import (  # noqa: F401
    DEFAULT_CATEGORY_COLORS,
    DEFAULT_ITEM_COLORS,
    _expand_item_groups,
    _get_catalog_for_pos,
)
from restaurant.orders.validation import (  # noqa: F401
    validate_order,
    sync_table_status_for_order,
)
from restaurant.orders.serialization import (  # noqa: F401
    build_order_serialization_context,
    _BatchOrderObj,
    _load_orders_batch,
    _serialize_order,
    _get_areas_with_live_tables,
)
from restaurant.orders.service import (  # noqa: F401
    _get_next_order_sequence_number,
    save_pos_order,
    _dispatch_station_print_jobs,
    send_order_to_kitchen,
    get_precuenta_data,
    authorize_reprint_command,
    save_customer_with_rtn,
    get_emitted_commands,
    submit_self_order,
)
from restaurant.orders.changes import (  # noqa: F401
    transfer_order_table,
    split_order,
    get_order_operation_context,
    preview_split_order,
    _sync_kds_after_order_change,
    cancel_sent_order_item,
    clear_pos_order,
    cancel_pos_order,
    unlock_waiter_order,
)


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
