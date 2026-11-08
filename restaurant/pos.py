"""Backend services for the LEAF Restaurant POS, open accounts, pre-checks, SAR invoicing, and KDS."""

import json
from datetime import datetime

import frappe
from frappe import _
from frappe.utils import cint, cstr, flt, get_datetime, get_fullname, now_datetime, nowdate, nowtime

ALLOWED_SERVICE_TYPES = ("Comer en el local", "Para llevar", "Entrega")
ALLOWED_ORDER_STATUSES = ("En curso", "Facturada", "Cancelada")
ALLOWED_KDS_STATUSES = ("Sin enviar", "En preparación", "Listo", "Entregado", "Cerrado")
ALLOWED_ITEM_KDS_STATUSES = ("Pendiente", "En preparación", "Listo", "Entregado", "Cerrado")

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
    if not {"System Manager", "Restaurant Manager", "Restaurant User"}.intersection(frappe.get_roles()):
        frappe.throw(
            _("No tienes permiso para acceder al Punto de Venta de Restaurante."),
            frappe.PermissionError,
        )


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
        fields=["name", "company", "currency", "selling_price_list", "warehouse", " customer"],
        limit=10,
    ) if False else frappe.get_all(
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


def _resolve_item_tax_rate(item_code):
    """Return applicable Honduras ISV rate (15, 18, or 0) for an Item."""
    taxes = frappe.get_all(
        "Item Tax",
        filters={"parent": item_code, "parenttype": "Item"},
        fields=["item_tax_template"],
    )
    for row in taxes:
        tpl_name = (row.item_tax_template or "").upper()
        if "EXENTO" in tpl_name or "0%" in tpl_name:
            return 0.0
        if "18%" in tpl_name or "18" in tpl_name:
            return 18.0
        if "15%" in tpl_name or "15" in tpl_name:
            return 15.0
    return 15.0


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

    doc.status = cstr(doc.status or "En curso").strip()
    if doc.status not in ALLOWED_ORDER_STATUSES:
        frappe.throw(_("El estado de la orden debe ser En curso, Facturada o Cancelada."))

    doc.service_type = cstr(doc.service_type or "Comer en el local").strip()
    if frappe.db.table_exists("Restaurant Order Preset"):
        valid_presets = frappe.get_all("Restaurant Order Preset", filters={"enabled": 1}, pluck="preset_name")
        if valid_presets and doc.service_type not in valid_presets:
            frappe.throw(_("La modalidad seleccionada '{0}' no es válida según los ajustes preestablecidos.").format(doc.service_type))
    elif doc.service_type not in ALLOWED_SERVICE_TYPES:
        frappe.throw(_("La modalidad debe ser Comer en el local, Para llevar o Entrega."))

    doc.kds_status = cstr(doc.kds_status or "Sin enviar").strip()
    if doc.kds_status not in ALLOWED_KDS_STATUSES:
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
            ["table_number", "restaurant_area"],
            as_dict=True,
        )
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

    command_map = _resolve_command_map()

    subtotal = 0.0
    taxed_15 = 0.0
    isv_15 = 0.0
    taxed_18 = 0.0
    isv_18 = 0.0
    exempt = 0.0

    for row in (doc.items or []):
        if not row.item_code or not frappe.db.exists("Item", row.item_code):
            frappe.throw(_("Selecciona un producto o platillo válido en cada línea de la orden."))
        item_info = frappe.db.get_value(
            "Item",
            row.item_code,
            ["item_name", "item_group", "stock_uom", "standard_rate"],
            as_dict=True,
        )
        row.item_name = cstr(row.item_name or (item_info.item_name if item_info else row.item_code)).strip()
        row.item_group = (item_info.item_group if item_info and item_info.item_group else row.item_group)
        row.uom = row.uom or (item_info.stock_uom if item_info else None)

        row.qty = flt(row.qty)
        if row.qty <= 0:
            frappe.throw(_("La cantidad de cada platillo debe ser mayor que cero."))

        row.base_rate = max(0.0, flt(row.base_rate, 2))
        row.options_rate = max(0.0, flt(row.options_rate, 2))
        row.discount_percentage = min(100.0, max(0.0, flt(row.discount_percentage, 2)))

        gross_unit = flt(row.base_rate + row.options_rate, 2)
        if gross_unit == 0 and flt(row.rate) > 0:
            row.base_rate = flt(row.rate, 2)
            gross_unit = row.base_rate

        row.rate = flt(gross_unit * (1.0 - (row.discount_percentage / 100.0)), 2)
        row.amount = flt(row.qty * row.rate, 2)

        if row.tax_rate is None or row.tax_rate == "":
            row.tax_rate = _resolve_item_tax_rate(row.item_code)
        else:
            row.tax_rate = flt(row.tax_rate, 2)

        row.note = cstr(row.note).strip()[:300]
        row.options_summary = cstr(row.options_summary).strip()[:500]
        stations = (command_map.get(row.item_group) or []) if row.item_group else []
        row.command_station = ", ".join(stations) if stations else "Cocina General"
        if row.kds_status not in ALLOWED_ITEM_KDS_STATUSES:
            row.kds_status = "Pendiente"

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
        })
    created_dt = get_datetime(doc.creation) if doc.creation else now_datetime()
    elapsed_mins = max(0, int((now_datetime() - created_dt).total_seconds() // 60))
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
        "kds_stage": (
            "Cerrado" if (doc.kds_status or "Sin enviar") == "Cerrado"
            else "Para Entregar" if (doc.kds_status or "Sin enviar") == "Listo"
            else "Completadas" if (doc.kds_status or "Sin enviar") == "Entregado"
            else "Por Preparar"
        ),
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
        "items": items,
    }


def _get_catalog_for_pos(selling_price_list=None):
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

    raw_items = frappe.get_all(
        "Item",
        filters={
            "disabled": 0,
            "is_sales_item": 1,
            "has_variants": 0,
            "is_fixed_asset": 0,
            "item_group": ["not in", ["Servicios", "Sub-ensambles", "Materia prima"]],
        },
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

    prof_fields = ["name", "company", "currency", "selling_price_list", "warehouse", "customer"]
    if frappe.get_meta("POS Profile").has_field("prefix"):
        prof_fields.append("prefix")
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
            "payments": payments,
        })

    active_price_list = (
        default_profile.selling_price_list if default_profile else "Venta estándar"
    )
    categories, items = _get_catalog_for_pos(active_price_list)
    areas = _get_areas_with_live_tables()

    waiters = frappe.get_all(
        "Employee",
        filters={"designation": "Mesero", "status": "Active"},
        fields=["name", "employee_name", "branch"],
        order_by="employee_name asc",
    )

    customers = frappe.get_all(
        "Customer",
        filters={"disabled": 0},
        fields=["name", "customer_name", "tax_id", "default_price_list"],
        order_by="customer_name asc",
        limit_page_length=200,
    )

    price_lists = frappe.get_all(
        "Price List",
        filters={"selling": 1, "enabled": 1},
        fields=["name", "currency"],
        order_by="name asc",
    )

    modes_of_payment = frappe.get_all(
        "Mode of Payment",
        filters={"enabled": 1},
        fields=["name", "type"],
        order_by="name asc",
    )

    order_docs = frappe.get_all(
        "Restaurant Order",
        fields=["name"],
        order_by="modified desc",
        limit_page_length=100,
    )
    orders = [_serialize_order(row.name) for row in order_docs]

    active_prof_name = (
        opening_shift["pos_profile"]
        if opening_shift and opening_shift.get("pos_profile")
        else (default_profile.name if default_profile else None)
    )
    fiscal_info = _resolve_sar_fiscal_info(pos_profile=active_prof_name, company=company)

    return {
        "cashier": {
            "user": frappe.session.user,
            "full_name": get_fullname(frappe.session.user),
        },
        "company": {
            "name": company or "Empresa Demostrativa",
            "tax_id": fiscal_info["company_tax_id"],
            "currency": "HNL",
        },
        "opening_shift": opening_shift,
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
        "presets": get_order_presets(),
        "fiscal_defaults": {
            "cai": fiscal_info["cai"],
            "due_date_cai": fiscal_info["due_date_cai"],
            "authorized_range": fiscal_info["authorized_range"],
            "prefix": fiscal_info["prefix"],
        },
    }


@frappe.whitelist(methods=["POST"])
def open_pos_shift(pos_profile=None, opening_amount=0, balance_details=None):
    """Open or reuse a native POS Opening Shift for the logged-in cashier."""
    _require_pos_user()
    existing = _get_active_opening_shift(frappe.session.user)
    if existing:
        return existing

    if not pos_profile:
        default_prof = _get_default_pos_profile()
        pos_profile = default_prof.name if default_prof else None
    if not pos_profile or not frappe.db.exists("POS Profile", pos_profile):
        frappe.throw(_("Selecciona un perfil de Punto de Venta válido para abrir el turno."))

    prof_doc = frappe.get_doc("POS Profile", pos_profile)
    rows = []
    if balance_details:
        parsed = frappe.parse_json(balance_details) if isinstance(balance_details, str) else balance_details
        if isinstance(parsed, list):
            for entry in parsed:
                if isinstance(entry, dict) and entry.get("mode_of_payment"):
                    rows.append({
                        "mode_of_payment": entry["mode_of_payment"],
                        "amount": max(0.0, flt(entry.get("opening_amount"), 2)),
                    })
    if not rows:
        default_mop = "Efectivo"
        if prof_doc.payments:
            default_mop = prof_doc.payments[0].mode_of_payment
        rows.append({
            "mode_of_payment": default_mop,
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
            "opening_amount": opening_amt,
            "sales_amount": sales_amt,
            "cash_movement_net": flt(cash_net, 2),
            "expected_amount": expected_amt,
            "closing_amount": expected_amt,
        })

    for mop, sales_amt in paid_by_mop.items():
        if mop in seen_mops:
            continue
        payment_reconciliation.append({
            "mode_of_payment": mop,
            "opening_amount": 0.0,
            "sales_amount": flt(sales_amt, 2),
            "cash_movement_net": 0.0,
            "expected_amount": flt(sales_amt, 2),
            "closing_amount": flt(sales_amt, 2),
        })

    total_sales = sum(flt(inv.grand_total, 2) for inv in invoices)
    return {
        "pos_opening_shift": opening_doc.name,
        "pos_profile": opening_doc.pos_profile,
        "company": opening_doc.company,
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
    if not pos_opening_shift or not frappe.db.exists("POS Opening Shift", pos_opening_shift):
        frappe.throw(_("No se encontró el turno de caja activo."))
    doc = frappe.get_doc("POS Opening Shift", pos_opening_shift)
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
        try:
            from posawesome.posawesome.doctype.pos_closing_shift.pos_closing_shift import (
                make_closing_shift_from_opening,
            )

            closing_doc = make_closing_shift_from_opening(doc)
            for row in (closing_doc.payment_reconciliation or []):
                if row.mode_of_payment in parsed_amounts:
                    row.closing_amount = flt(parsed_amounts[row.mode_of_payment], 2)
                else:
                    row.closing_amount = flt(row.expected_amount, 2)
                row.difference = flt(row.closing_amount - flt(row.expected_amount, 2), 2)
            closing_doc.insert(ignore_permissions=True)
            closing_doc.submit()
            closing_shift_name = closing_doc.name
        except Exception:
            frappe.db.set_value("POS Opening Shift", doc.name, {
                "status": "Closed",
                "period_end_date": nowdate(),
            })
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


@frappe.whitelist(methods=["POST"])
def save_pos_order(order):
    """Create or update a Restaurant Order and return its updated state."""
    _require_pos_user()
    payload = frappe.parse_json(order) if isinstance(order, str) else order
    if not isinstance(payload, dict):
        frappe.throw(_("Los datos de la orden no tienen un formato válido."))

    order_id = cstr(payload.get("name") or "").strip()
    if order_id:
        if not frappe.db.exists("Restaurant Order", order_id):
            frappe.throw(_("La cuenta u orden solicitada no existe."), frappe.DoesNotExistError)
        doc = frappe.get_doc("Restaurant Order", order_id)
        doc.check_permission("write")
        if doc.status == "Facturada":
            frappe.throw(_("Esta orden ya fue facturada y no puede modificarse."))
    else:
        if not frappe.has_permission("Restaurant Order", "create"):
            frappe.throw(_("No tienes permisos para abrir cuentas u órdenes."), frappe.PermissionError)
        doc = frappe.new_doc("Restaurant Order")

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

    if not doc.pos_opening_shift:
        active_shift = _get_active_opening_shift(frappe.session.user)
        if active_shift:
            doc.pos_opening_shift = active_shift["name"]
            doc.pos_profile = doc.pos_profile or active_shift["pos_profile"]
            doc.company = doc.company or active_shift["company"]

    if "items" in payload and isinstance(payload.get("items"), list):
        existing_rows = {r.name: r for r in (doc.items or []) if getattr(r, "name", None)}
        item_rows = []
        for raw_row in payload["items"]:
            if not isinstance(raw_row, dict) or not raw_row.get("item_code"):
                continue
            row_name = cstr(raw_row.get("name") or "").strip()
            old_row = existing_rows.get(row_name)

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
        doc.set("items", item_rows)

    if doc.is_new():
        doc.insert()
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


def get_order_presets():
    """Return active order presets (Comer en el local, Para llevar, Entrega)."""
    default_presets = [
        {"preset_name": "Comer en el local", "color_bg": "#cce3fd", "color_border": "#3b82f6", "is_default": 1},
        {"preset_name": "Para llevar", "color_bg": "#fef0a6", "color_border": "#eab308", "is_default": 0},
        {"preset_name": "Entrega", "color_bg": "#fcd5b5", "color_border": "#f97316", "is_default": 0},
    ]
    if frappe.db.table_exists("Restaurant Order Preset"):
        records = frappe.get_all(
            "Restaurant Order Preset",
            filters={"enabled": 1},
            fields=["name", "preset_name", "color_bg", "color_border", "is_default"],
            order_by="idx asc, creation asc",
        )
        if records:
            return records
        for p in default_presets:
            if not frappe.db.exists("Restaurant Order Preset", p["preset_name"]):
                doc = frappe.get_doc({
                    "doctype": "Restaurant Order Preset",
                    "preset_name": p["preset_name"],
                    "color_bg": p["color_bg"],
                    "color_border": p["color_border"],
                    "is_default": p["is_default"],
                    "enabled": 1,
                })
                doc.insert(ignore_permissions=True)
        return frappe.get_all(
            "Restaurant Order Preset",
            filters={"enabled": 1},
            fields=["name", "preset_name", "color_bg", "color_border", "is_default"],
            order_by="idx asc, creation asc",
        )
    return default_presets


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
    return {
        "order": _serialize_order(doc),
        "stations": stations,
        "sent_at": f"{nowdate()} {nowtime()[:8]}",
    }


@frappe.whitelist()
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
):
    """Emit and submit a native SAR Sales Invoice for a Restaurant Order and free its table."""
    _require_pos_user()
    if not order_name or not frappe.db.exists("Restaurant Order", order_name):
        frappe.throw(_("La cuenta u orden seleccionada no existe."), frappe.DoesNotExistError)

    doc = frappe.get_doc("Restaurant Order", order_name)
    doc.check_permission("write")
    if doc.status == "Facturada" and doc.sales_invoice:
        frappe.throw(_("Esta cuenta ya fue facturada en el documento {0}.").format(doc.sales_invoice))
    if not doc.items:
        frappe.throw(_("No puedes facturar una orden sin platillos ni productos."))

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

    company = doc.company or _get_default_company()
    pos_profile = doc.pos_profile
    if not pos_profile:
        default_prof = _get_default_pos_profile(company)
        pos_profile = default_prof.name if default_prof else None
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

    parsed_payments = frappe.parse_json(payments) if isinstance(payments, str) else payments
    payment_rows = []
    if isinstance(parsed_payments, list):
        for p in parsed_payments:
            if isinstance(p, dict) and p.get("mode_of_payment") and flt(p.get("amount")) > 0:
                mop = p["mode_of_payment"]
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

    fiscal_info = _resolve_sar_fiscal_info(pos_profile=pos_profile, company=company)
    cai_value = cstr(cai or doc.cai or fiscal_info["cai"]).strip()
    due_cai_value = cstr(due_date_cai or doc.due_date_cai or fiscal_info["due_date_cai"]).strip()
    auth_range_value = cstr(authorized_range or fiscal_info["authorized_range"]).strip()

    si_payload = {
        "doctype": "Sales Invoice",
        "company": company,
        "customer": doc.customer,
        "tax_id": doc.tax_id or "",
        "posting_date": nowdate(),
        "due_date": nowdate(),
        "is_pos": 1,
        "pos_profile": pos_profile,
        "posa_pos_opening_shift": doc.pos_opening_shift or "",
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
    si_meta = frappe.get_meta("Sales Invoice")
    if si_meta.has_field("authorized_range"):
        si_payload["authorized_range"] = auth_range_value
    if si_meta.has_field("cashier"):
        si_payload["cashier"] = frappe.session.user

    si = frappe.get_doc(si_payload)
    si.set_missing_values()
    si.calculate_taxes_and_totals()

    total_paid = sum(flt(p.amount) for p in si.payments)
    if total_paid < flt(si.grand_total, 2):
        si.payments[0].amount = flt(si.payments[0].amount + (flt(si.grand_total, 2) - total_paid), 2)

    si.insert(ignore_permissions=True)
    si.submit()

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


@frappe.whitelist(methods=["POST"])
def cancel_pos_order(order_name):
    """Cancel an unbilled Restaurant Order and release its table."""
    _require_pos_user()
    if not order_name or not frappe.db.exists("Restaurant Order", order_name):
        frappe.throw(_("La cuenta u orden no existe."))
    doc = frappe.get_doc("Restaurant Order", order_name)
    doc.check_permission("write")
    if doc.status == "Facturada":
        frappe.throw(_("No puedes cancelar desde el POS una cuenta que ya tiene factura emitida."))
    doc.status = "Cancelada"
    doc.save()
    return {
        "order": _serialize_order(doc),
        "areas": _get_areas_with_live_tables(),
    }


@frappe.whitelist(methods=["POST"])
def save_customer_with_rtn(customer_name, tax_id=None, customer_id=None):
    """Create or update a Customer with their fiscal RTN directly from the Restaurant POS."""
    _require_pos_user()
    clean_name = cstr(customer_name).strip()
    clean_rtn = cstr(tax_id).strip()[:60]
    if not clean_name:
        frappe.throw(_("El nombre o razón social del cliente es obligatorio."))

    if customer_id and frappe.db.exists("Customer", customer_id):
        doc = frappe.get_doc("Customer", customer_id)
        doc.customer_name = clean_name
        doc.tax_id = clean_rtn
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
        doc = frappe.get_doc({
            "doctype": "Customer",
            "customer_name": clean_name,
            "customer_type": "Individual",
            "customer_group": group,
            "territory": territory,
            "tax_id": clean_rtn,
        })
        doc.insert(ignore_permissions=True)

    return {
        "name": doc.name,
        "customer_name": doc.customer_name,
        "tax_id": doc.tax_id or "",
    }


@frappe.whitelist()
def get_kds_orders(station=None, status_filter=None):
    """Return active kitchen orders and station filters for the Kitchen Display System (KDS)."""
    _require_pos_user()
    filters = {
        "status": ["in", ["En curso", "Facturada"]],
        "kds_status": ["in", ["Sin enviar", "En preparación", "Listo", "Entregado"]],
    }
    if status_filter and status_filter in ALLOWED_KDS_STATUSES:
        filters["kds_status"] = status_filter

    rows = frappe.get_all(
        "Restaurant Order",
        filters=filters,
        fields=["name"],
        order_by="sent_to_kitchen_at asc, creation asc",
        limit_page_length=150,
    )
    orders = []
    stations_set = {"Todas las estaciones", "Cocina General"}
    command_displays = []
    if frappe.db.exists("DocType", "Restaurant Command"):
        for cmd_name in frappe.get_all("Restaurant Command", filters={"enabled": 1}, pluck="command_name"):
            stations_set.add(cmd_name)
        cmd_docs = frappe.get_all(
            "Restaurant Command",
            filters={"enabled": 1},
            fields=["name", "command_name", "branch", "enabled"],
            order_by="command_name asc",
        )
        for cmd in cmd_docs:
            stations_set.add(cmd.command_name)
            groups = frappe.get_all(
                "Restaurant Command Group",
                filters={"parent": cmd.name, "parenttype": "Restaurant Command"},
                pluck="item_group",
            )
            command_displays.append({
                "name": cmd.name,
                "command_name": cmd.command_name,
                "branch": cmd.branch or "Restaurante",
                "enabled": cint(cmd.enabled),
                "groups": groups,
            })

    counts = {
        "Todas": 0,
        "Por Preparar": 0,
        "Para Entregar": 0,
        "Completadas": 0,
    }
    now_dt = now_datetime()

    for r in rows:
        serialized = _serialize_order(r.name)
        if not serialized["items"]:
            continue
        for item in serialized["items"]:
            if item.get("command_station"):
                for st in item["command_station"].split(","):
                    if st.strip():
                        stations_set.add(st.strip())
        if station and station not in ("Todas las estaciones", "ALL", "Todas"):
            filtered_items = [
                it for it in serialized["items"]
                if station.lower() in (it.get("command_station") or "").lower()
            ]
            if not filtered_items:
                continue
            serialized["items"] = filtered_items

        raw_kds = serialized.get("kds_status") or "Sin enviar"
        if raw_kds == "Cerrado":
            continue
        if raw_kds == "Listo":
            stage = "Para Entregar"
        elif raw_kds == "Entregado":
            stage = "Completadas"
        else:
            stage = "Por Preparar"

        timer_ref = serialized.get("sent_to_kitchen_at") or serialized.get("creation")
        ref_dt = get_datetime(timer_ref) if timer_ref else now_dt
        wait_mins = max(0, int((now_dt - ref_dt).total_seconds() // 60))

        serialized["kds_stage"] = stage
        serialized["kds_timer_start"] = str(timer_ref or now_dt)
        serialized["kds_wait_minutes"] = wait_mins

        counts["Todas"] += 1
        counts[stage] = counts.get(stage, 0) + 1
        orders.append(serialized)

    in_progress_orders = [o for o in orders if o.get("kds_stage") == "Por Preparar"]
    in_progress_count = len(in_progress_orders)
    avg_wait_minutes = (
        int(round(sum(int(o.get("kds_wait_minutes") or 0) for o in in_progress_orders) / in_progress_count))
        if in_progress_count
        else 0
    )

    return {
        "stations": sorted(stations_set),
        "command_displays": command_displays,
        "orders": orders,
        "counts": counts,
        "in_progress_count": in_progress_count,
        "avg_wait_minutes": avg_wait_minutes,
        "server_now": str(now_dt),
    }


@frappe.whitelist()
def update_kds_status(order_name, kds_status, item_idx=None):
    """Advance or update the Kitchen KDS status of an order or individual dish line."""
    _require_pos_user()
    if not order_name or not frappe.db.exists("Restaurant Order", order_name):
        frappe.throw(_("La comanda seleccionada no existe."))
    doc = frappe.get_doc("Restaurant Order", order_name)
    doc.check_permission("write")

    stage_aliases = {
        "Por Preparar": "En preparación",
        "Para Entregar": "Listo",
        "Completadas": "Entregado",
    }
    target_status = stage_aliases.get(cstr(kds_status).strip(), cstr(kds_status).strip())

    if item_idx is not None and item_idx != "":
        target_idx = cint(item_idx)
        for row in doc.items:
            if cint(row.idx) == target_idx and target_status in ALLOWED_ITEM_KDS_STATUSES:
                row.kds_status = target_status
        statuses = {row.kds_status for row in doc.items}
        if statuses == {"Cerrado"}:
            doc.kds_status = "Cerrado"
        elif statuses == {"Entregado"}:
            doc.kds_status = "Entregado"
        elif statuses <= {"Listo", "Entregado"}:
            doc.kds_status = "Listo"
        else:
            doc.kds_status = "En preparación"
    else:
        if target_status not in ALLOWED_KDS_STATUSES:
            frappe.throw(_("El estado de cocina no es válido."))
        doc.kds_status = target_status
        if target_status == "En preparación" and not doc.sent_to_kitchen_at:
            doc.sent_to_kitchen_at = now_datetime()
        mapped_item_status = (
            "Pendiente" if target_status == "Sin enviar" else target_status
        )
        for row in doc.items:
            row.kds_status = mapped_item_status

    doc.save()
    serialized = _serialize_order(doc)
    return {
        "order": serialized,
        "kds_status": serialized["kds_status"],
        "kds_stage": serialized["kds_stage"],
    }


@frappe.whitelist()
def clear_completed_kds_orders(order_names=None):
    """Close completed ('Entregado') KDS tickets so they disappear from the active KDS monitor."""
    _require_pos_user()
    names = []
    if order_names:
        parsed = frappe.parse_json(order_names) if isinstance(order_names, str) else order_names
        if isinstance(parsed, list):
            names = [cstr(n).strip() for n in parsed if cstr(n).strip()]
    if not names:
        names = frappe.get_all(
            "Restaurant Order",
            filters={
                "status": ["in", ["En curso", "Facturada"]],
                "kds_status": "Entregado",
            },
            pluck="name",
            limit_page_length=200,
        )
    closed = []
    for name in names:
        if not frappe.db.exists("Restaurant Order", name):
            continue
        doc = frappe.get_doc("Restaurant Order", name)
        if not doc.has_permission("write"):
            continue
        doc.kds_status = "Cerrado"
        for row in doc.items:
            row.kds_status = "Cerrado"
        doc.save()
        closed.append(doc.name)
    return {"closed": closed, "closed_orders": closed}


@frappe.whitelist()
def get_emitted_commands(limit=40):
    """Return orders that already have emitted kitchen commands for reprinting."""
    _require_pos_user()
    rows = frappe.get_all(
        "Restaurant Order",
        filters={"status": ["in", ["En curso", "Facturada"]]},
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
    _require_pos_user()
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
