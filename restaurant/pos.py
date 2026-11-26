"""Restaurant POS entry point.

Endpoints keep their public path restaurant.pos.<name> (used by the POS JavaScript,
hooks and other apps); each one lives in its feature module and is re-exported here.

Feature map:
    pos_context.py          user access, PIN throttling, company, branch, defaults, open shift
    cash/shift.py           cash register shift: open, cash movements, closing preview, close
    pos_settings/           POS configuration per profile (config.py) and kitchen/bar stations (stations.py)
    catalog/                POS menu and prices (menu.py) and item tax rates (taxes.py)
    orders/                 validation, serialization, lifecycle (service.py) and changes (changes.py)
    checkout/               payment and Sales Invoice (invoice.py), discounts, stock, accounts, extras
    pos.py (this file)      get_pos_bootstrap: everything the POS screen needs to start
"""

import frappe
from frappe.utils import cint, cstr, get_fullname

from restaurant.pos_auth import (
    get_linked_employee_for_user,
    get_supervisors_for_pos,
    is_cashier_only,
    is_direct_cashier,
    is_supervisor,
    is_waiter_only,
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
from restaurant.checkout.accounts import (  # noqa: F401
    _resolve_sar_fiscal_info,
    _resolve_payment_account,
    _resolve_service_income_account,
)
from restaurant.checkout.stock import (  # noqa: F401
    _invoice_has_stock_items,
    validate_restaurant_invoice_stock,
)
from restaurant.checkout.discounts import (  # noqa: F401
    DiscountApprovalRequired,
    _approve_checkout_discounts,
)
from restaurant.checkout.invoice import (  # noqa: F401
    _sync_order_totals_from_invoice,
    _set_doc_field,
    pay_and_invoice_order,
)
from restaurant.checkout.extras import (  # noqa: F401
    validate_coupon_code,
    validate_gift_card,
    get_customer_loyalty_points,
    send_invoice_email,
    get_whatsapp_invoice_share_link,
    get_self_invoicing_receipt_data,
)


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
