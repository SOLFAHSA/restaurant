"""Configure native ERPNext tax templates for net restaurant prices."""

import frappe
from frappe import _
from frappe.utils import flt

RATES = (0, 15, 18)


def _account(company, rate):
    """Use the Honduras tax accounts already maintained by Grintsys."""
    name = frappe.db.get_value("Account", {
        "company": company,
        "account_name": "Débito Fiscal ISV {0}%".format(rate),
        "root_type": "Liability", "is_group": 0, "disabled": 0,
    }, "name")
    if not name:
        frappe.throw(_("Configura la cuenta nativa Débito Fiscal ISV {0}% para {1}.").format(rate, company))
    return name


def _template_name(doctype, company, title):
    return frappe.db.get_value(doctype, {"company": company, "title": title}, "name")


def _get_sales_tax_template(company, create=False):
    """Return a native Sales Taxes and Charges Template for net prices."""
    title = "Restaurante ISV neto"
    name = _template_name("Sales Taxes and Charges Template", company, title)
    if not name and create:
        accounts = {rate: _account(company, rate) for rate in (15, 18)}
        doc = frappe.get_doc({
            "doctype": "Sales Taxes and Charges Template",
            "title": title, "company": company, "is_default": 0,
            "taxes": [{
                "charge_type": "On Net Total", "account_head": accounts[rate],
                "description": "ISV {0}%".format(rate), "rate": rate,
                "included_in_print_rate": 0,
            } for rate in (15, 18)],
        })
        doc.insert()
        name = doc.name
    if not name:
        frappe.throw(_("Configura la plantilla nativa de impuestos netos para {0}.").format(company))
    doc = frappe.get_doc("Sales Taxes and Charges Template", name)
    expected = {_account(company, rate): rate for rate in (15, 18)}
    actual = {row.account_head: flt(row.rate) for row in doc.taxes}
    if doc.disabled or actual != expected or len(doc.taxes) != 2 or any(
        row.charge_type != "On Net Total" or row.included_in_print_rate for row in doc.taxes
    ):
        frappe.throw(_("La plantilla fiscal de {0} debe calcular ISV 15% y 18% sobre el precio neto.").format(company))
    return name


def get_item_tax_template(company, rate, create=False):
    """Return a native Item Tax Template with explicit rates for both ISV accounts."""
    rate = flt(rate)
    if rate not in RATES:
        frappe.throw(_("La tasa fiscal debe ser 0%, 15% o 18%."))
    title = "Restaurante EXENTO" if rate == 0 else "Restaurante ISV {0}%".format(int(rate))
    name = _template_name("Item Tax Template", company, title)
    accounts = {value: _account(company, value) for value in (15, 18)}
    expected = {account: (value if value == rate else 0) for value, account in accounts.items()}
    if not name and create:
        doc = frappe.get_doc({
            "doctype": "Item Tax Template", "title": title, "company": company,
            "taxes": [{"tax_type": account, "tax_rate": value} for account, value in expected.items()],
        })
        doc.insert()
        name = doc.name
    if not name:
        frappe.throw(_("Configura la plantilla de artículo ISV {0}% para {1}.").format(int(rate), company))
    doc = frappe.get_doc("Item Tax Template", name)
    if doc.disabled or len(doc.taxes) != 2 or {
        row.tax_type: flt(row.tax_rate) for row in doc.taxes
    } != expected:
        frappe.throw(_("La plantilla de artículo de {0} tiene cuentas o tasas inconsistentes.").format(company))
    return name


def get_native_tax_configuration(company, create=False):
    """Resolve the native sales and item templates used by restaurant checkout."""
    normal = _get_sales_tax_template(company, create=create)
    zero = frappe.db.get_value(
        "Sales Taxes and Charges Template",
        {"company": company, "tax_category": "Exonerado", "disabled": 0}, "name",
    )
    if not zero:
        frappe.throw(_("Configura una plantilla nativa Exonerado para {0}.").format(company))
    doc = frappe.get_doc("Sales Taxes and Charges Template", zero)
    if any(flt(row.rate) != 0 or row.charge_type != "On Net Total" for row in doc.taxes):
        frappe.throw(_("La plantilla Exonerado debe usar tasas de cero."))
    return {
        "taxes_and_charges": normal,
        "exonerated_taxes_and_charges": zero,
        "item_tax_templates": {rate: get_item_tax_template(company, rate, create=create) for rate in RATES},
    }


def configure_company(company):
    """Create native configuration without rewriting existing tax templates."""
    frappe.only_for("System Manager")
    return get_native_tax_configuration(company, create=True)
