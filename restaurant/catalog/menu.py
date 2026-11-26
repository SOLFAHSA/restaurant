"""POS menu: categories, items, selling prices and tax rates."""

import frappe
from frappe.utils import cint, cstr, flt

from restaurant.catalog.taxes import _get_item_tax_rates
from restaurant.pos_context import _get_default_company
from restaurant.pos_settings.stations import _resolve_command_map


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
