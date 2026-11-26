"""Item tax rates resolved with ERPNext's native Item Tax Template lookup."""

import frappe
from frappe.utils import flt, nowdate


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


def _get_item_tax_templates(item_codes, company):
    """Resolve each item's template with ERPNext's lookup: item templates first, then its item groups."""
    from erpnext.stock.get_item_details import get_item_tax_template

    args = frappe._dict(company=company, doctype="Sales Invoice", tax_category=None, transaction_date=nowdate())
    templates = {}
    for item_code in set(item_codes or []):
        out = {}
        get_item_tax_template(args, frappe.get_cached_doc("Item", item_code), out)
        templates[item_code] = out.get("item_tax_template")
    return templates


def _get_item_tax_rates(item_codes, company):
    """Resolve each item's nominal ISV rate from its native Item Tax Template."""
    templates = _get_item_tax_templates(item_codes, company)
    rates = _load_item_tax_template_rates({name for name in templates.values() if name})
    return {item_code: rates.get(template) for item_code, template in templates.items()}
