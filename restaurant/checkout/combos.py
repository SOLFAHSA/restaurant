"""Combo components billed at zero on the native Sales Invoice, so ERPNext moves and reverts their stock."""

import json

import frappe
from frappe import _
from frappe.utils import cstr, flt

COMBO_EFFECT = "Incluir en combo"


def get_combo_components(rows):
    """Return, for each order row, the stock items its chosen combo options take from the warehouse.

    The order only says which option the customer chose (group and label). The item, quantity and
    unit always come from the configured Restaurant Dish Option, never from the browser.
    """
    options = _load_combo_options({row.item_code for row in rows})
    if not options:
        return [[] for _row in rows]

    component_items = {option.item_code for candidates in options.values() for option in candidates}
    stock_items = {
        item.name: item
        for item in frappe.get_all(
            "Item",
            filters={"name": ["in", list(component_items)], "is_stock_item": 1},
            fields=["name", "item_name", "stock_uom"],
        )
    }

    components = []
    for row in rows:
        row_components = []
        for chosen in _chosen_options(row):
            option = _match_option(options.get((row.item_code, chosen["label"]), []), chosen["group"])
            if not option or option.item_code not in stock_items:
                continue  # Non-stock components (dishes, services) do not move inventory.
            item = stock_items[option.item_code]
            uom = option.uom or item.stock_uom
            _check_uom_conversion(item, uom)
            row_components.append(frappe._dict({
                "item_code": item.name,
                "item_name": item.item_name,
                "qty": flt(row.qty) * flt(option.qty or 1),
                "uom": uom,
            }))
        components.append(row_components)
    return components


def _load_combo_options(main_items):
    """Map (combo item, option label) to its configured combo options, tagged with the group name."""
    if not main_items:
        return {}
    groups = {
        group.name: group
        for group in frappe.get_all(
            "Restaurant Option Group",
            filters={"main_item": ["in", list(main_items)], "disabled": 0},
            fields=["name", "main_item", "group_name"],
        )
    }
    if not groups:
        return {}
    options = {}
    for option in frappe.get_all(
        "Restaurant Dish Option",
        filters={"parenttype": "Restaurant Option Group", "parent": ["in", list(groups)], "effect": COMBO_EFFECT},
        fields=["parent", "option_label", "item_code", "qty", "uom"],
    ):
        if not option.item_code:
            continue
        group = groups[option.parent]
        option.group_name = cstr(group.group_name).strip()
        options.setdefault((group.main_item, cstr(option.option_label).strip()), []).append(option)
    return options


def _chosen_options(row):
    try:
        chosen = json.loads(cstr(row.get("selected_options_json")) or "[]")
    except ValueError:
        return []
    return [
        {"label": cstr(option.get("option_label")).strip(), "group": cstr(option.get("group_name")).strip()}
        for option in (chosen if isinstance(chosen, list) else [])
        if isinstance(option, dict) and cstr(option.get("option_label")).strip()
    ]


def _match_option(candidates, group_name):
    """Prefer the option of the chosen group; without a group, accept only an unambiguous label."""
    in_group = [option for option in candidates if option.group_name == group_name]
    if in_group:
        return in_group[0]
    return candidates[0] if len(candidates) == 1 else None


def _check_uom_conversion(item, uom):
    if uom == item.stock_uom:
        return
    if not frappe.db.exists("UOM Conversion Detail", {"parent": item.name, "parenttype": "Item", "uom": uom}):
        frappe.throw(
            _("El componente de combo {0} usa la unidad {1}, que no tiene conversión a {2}. Agrégala en el producto.").format(
                item.item_name or item.name, uom, item.stock_uom
            )
        )
