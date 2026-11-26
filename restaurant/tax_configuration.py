"""Resolve the native ERPNext sales tax configuration used by restaurant checkout.

The company keeps its own Sales Taxes and Charges Templates and Item Tax Templates. This
module only *reads* them: it detects whether prices are net (``included_in_print_rate = 0``)
or tax-inclusive (``included_in_print_rate = 1``) and which ISV accounts are in use, so the
pre-bill and the native Sales Invoice apply exactly the same rule.

``configure_company`` remains an optional helper that creates restaurant templates on new or
demo sites that have none; it never rewrites or rejects valid existing templates.
"""

import json

import frappe
from frappe import _
from frappe.utils import cint, cstr, flt

RATES = (0, 15, 18)
EXONERATED_CATEGORY = "Exonerado"
LEGACY_SALES_TEMPLATE_TITLE = "Restaurante ISV neto"
SALES_TEMPLATE = "Sales Taxes and Charges Template"
ITEM_TEMPLATE = "Item Tax Template"


def _account(company, rate):
    """Return the company's ISV account for a rate: the active sales template first, then legacy names."""
    for row in _active_sales_rows(company):
        if abs(flt(row.rate) - flt(rate)) < 0.01 and flt(row.rate):
            return row.account_head
    name = frappe.db.get_value("Account", {
        "company": company,
        "account_name": "Débito Fiscal ISV {0}%".format(rate),
        "root_type": "Liability", "is_group": 0, "disabled": 0,
    }, "name")
    if not name:
        frappe.throw(_("Configura la cuenta nativa de ISV {0}% para {1}.").format(rate, company))
    return name


def _active_sales_rows(company):
    """Rows of the template the restaurant would use, without failing when none is configured yet."""
    name = _find_sales_template(company)
    if not name:
        return []
    return frappe.get_all(
        "Sales Taxes and Charges", filters={"parent": name, "parenttype": SALES_TEMPLATE},
        fields=["account_head", "rate", "charge_type", "included_in_print_rate"], order_by="idx asc",
    )


def _settings_link(fieldname):
    if not frappe.db.exists("DocType", "Restaurant Settings"):
        return None
    if not frappe.get_meta("Restaurant Settings").has_field(fieldname):
        return None
    return frappe.db.get_single_value("Restaurant Settings", fieldname) or None


def _enabled_template_of_company(name, company):
    if not name:
        return None
    row = frappe.db.get_value(SALES_TEMPLATE, name, ["company", "disabled"], as_dict=True)
    if row and row.company == company and not cint(row.disabled):
        return name
    return None


def _find_sales_template(company, pos_profile=None):
    """Settings -> POS Profile -> restaurant template already in use -> company default.

    The restaurant template created by earlier versions ranks above the company default so sites
    that already bill with it keep exactly the same price rule after upgrading.
    """
    candidates = [_settings_link("sales_taxes_template")]
    if pos_profile and frappe.db.exists("POS Profile", pos_profile):
        candidates.append(frappe.db.get_value("POS Profile", pos_profile, "taxes_and_charges"))
    candidates.append(frappe.db.get_value(
        SALES_TEMPLATE, {"company": company, "title": LEGACY_SALES_TEMPLATE_TITLE, "disabled": 0}, "name",
    ))
    candidates.append(frappe.db.get_value(
        SALES_TEMPLATE, {"company": company, "is_default": 1, "disabled": 0}, "name",
    ))
    for candidate in candidates:
        name = _enabled_template_of_company(candidate, company)
        if name and _template_category(name) != EXONERATED_CATEGORY:
            return name
    return None


def _find_exonerated_template(company):
    name = _enabled_template_of_company(_settings_link("exonerated_taxes_template"), company)
    return name or frappe.db.get_value(
        SALES_TEMPLATE, {"company": company, "tax_category": EXONERATED_CATEGORY, "disabled": 0}, "name",
    )


def _template_category(name):
    return cstr(frappe.db.get_value(SALES_TEMPLATE, name, "tax_category")).strip()


def describe_sales_template(name):
    """Return the price mode and ISV accounts of a native Sales Taxes and Charges Template."""
    doc = frappe.get_cached_doc(SALES_TEMPLATE, name)
    rows = [row for row in doc.taxes if row.account_head]
    if any(row.charge_type != "On Net Total" for row in rows):
        frappe.throw(_(
            "La plantilla fiscal {0} solo puede tener filas 'Sobre el total neto' para el Restaurante."
        ).format(name))
    included_flags = {cint(row.included_in_print_rate) for row in rows}
    if len(included_flags) > 1:
        frappe.throw(_(
            "La plantilla fiscal {0} mezcla impuestos incluidos y no incluidos en el precio. "
            "Usa un mismo criterio en todas sus filas."
        ).format(name))
    return frappe._dict(
        name=name,
        included_in_print_rate=included_flags.pop() if included_flags else 0,
        rates={row.account_head: flt(row.rate) for row in rows},
    )


def resolve_tax_context(company, pos_profile=None, required=True):
    """Return the active sales template, its price mode, accounts and the exonerated template."""
    sales = _find_sales_template(company, pos_profile)
    if not sales:
        if not required:
            return None
        frappe.throw(_(
            "Configura la plantilla de impuestos de venta para {0} en Configuración del Restaurante, "
            "en el perfil de Punto de Venta o como plantilla predeterminada de la empresa."
        ).format(company))
    info = describe_sales_template(sales)
    exonerated = _find_exonerated_template(company)
    if exonerated:
        exo_doc = frappe.get_cached_doc(SALES_TEMPLATE, exonerated)
        if any(flt(row.rate) != 0 or row.charge_type != "On Net Total" for row in exo_doc.taxes):
            frappe.throw(_("La plantilla Exonerado {0} debe usar tasas de cero.").format(exonerated))
    info.update(company=company, exonerated=exonerated)
    return info


def taxes_included_in_price(company, pos_profile=None):
    """True when the active sales template prices already include ISV."""
    context = resolve_tax_context(company, pos_profile, required=False)
    return bool(context and context.included_in_print_rate)


def _item_template_rates(name):
    return {
        row.tax_type: flt(row.tax_rate)
        for row in frappe.get_all(
            "Item Tax Template Detail", filters={"parent": name, "parenttype": ITEM_TEMPLATE},
            fields=["tax_type", "tax_rate"],
        )
    }


def effective_rate(item_rates, context):
    """ISV rate ERPNext applies to a line: item rates override the sales template rates per account."""
    return flt(sum(item_rates.get(account, rate) for account, rate in context.rates.items()), 2)


def _company_item_templates(company):
    return frappe.get_all(
        ITEM_TEMPLATE, filters={"company": company, "disabled": 0}, fields=["name", "title"],
        order_by="creation asc",
    )


def resolve_line_item_tax_template(company, native_template, nominal_rate, context, exonerated=False):
    """Pick the Item Tax Template that makes the native invoice charge exactly the pre-bill rate.

    The item's own template is used whenever ERPNext would charge its nominal rate with the
    active sales template. Otherwise (for example a template that only lists the 15% account
    while the sales template also has an 18% row) another enabled template of the company that
    yields the same rate is used, so no ISV is charged twice.
    """
    target = 0.0 if exonerated else flt(nominal_rate, 2)
    if native_template and not exonerated:
        if abs(effective_rate(_item_template_rates(native_template), context) - target) < 0.01:
            return native_template
    candidates = []
    for row in _company_item_templates(company):
        rates = _item_template_rates(row.name)
        if abs(effective_rate(rates, context) - target) >= 0.01:
            continue
        if exonerated and any(flt(value) for value in rates.values()):
            continue
        candidates.append(row)
    if exonerated:
        # Grintsys' SAR adjustment recognizes exempt lines by the word EXENTO in the template name.
        candidates.sort(key=lambda row: "EXENTO" not in cstr(row.name).upper())
    if candidates:
        return candidates[0].name
    label = _("exonerado") if exonerated else "{0}%".format(int(target))
    frappe.throw(_(
        "No existe una plantilla de impuesto de artículo para ISV {0} compatible con la plantilla "
        "de venta {1} de {2}. Revisa las plantillas de la empresa o ejecuta el asistente de configuración."
    ).format(label, context.name, company))


def _legacy_item_template_title(rate):
    return "Restaurante EXENTO" if rate == 0 else "Restaurante ISV {0}%".format(int(rate))


def get_item_tax_template(company, rate, create=False):
    """Return (or create in the optional wizard) a restaurant Item Tax Template for a rate."""
    rate = flt(rate)
    if rate not in RATES:
        frappe.throw(_("La tasa fiscal debe ser 0%, 15% o 18%."))
    title = _legacy_item_template_title(rate)
    name = frappe.db.get_value(ITEM_TEMPLATE, {"company": company, "title": title}, "name")
    accounts = {value: _account(company, value) for value in (15, 18)}
    expected = {account: (value if value == rate else 0) for value, account in accounts.items()}
    if not name and create:
        doc = frappe.get_doc({
            "doctype": ITEM_TEMPLATE, "title": title, "company": company,
            "taxes": [{"tax_type": account, "tax_rate": value} for account, value in expected.items()],
        })
        doc.insert()
        name = doc.name
    if not name:
        frappe.throw(_("Configura la plantilla de artículo ISV {0}% para {1}.").format(int(rate), company))
    return name


def _create_legacy_sales_template(company):
    accounts = {rate: _account(company, rate) for rate in (15, 18)}
    doc = frappe.get_doc({
        "doctype": SALES_TEMPLATE,
        "title": LEGACY_SALES_TEMPLATE_TITLE, "company": company, "is_default": 0,
        "taxes": [{
            "charge_type": "On Net Total", "account_head": accounts[rate],
            "description": "ISV {0}%".format(rate), "rate": rate,
            "included_in_print_rate": 0,
        } for rate in (15, 18)],
    })
    doc.insert()
    return doc.name


def get_native_tax_configuration(company, create=False, pos_profile=None):
    """Resolve the native templates used by restaurant checkout.

    With ``create=True`` (optional wizard) missing restaurant templates are created; existing
    valid company templates are always preferred and never modified.
    """
    if create and not _find_sales_template(company, pos_profile):
        _create_legacy_sales_template(company)
    context = resolve_tax_context(company, pos_profile)
    if not context.exonerated:
        frappe.throw(_("Configura una plantilla nativa Exonerado para {0}.").format(company))
    item_templates = {}
    for rate in RATES:
        if create:
            get_item_tax_template(company, rate, create=True)
        legacy = frappe.db.get_value(
            ITEM_TEMPLATE, {"company": company, "title": _legacy_item_template_title(rate), "disabled": 0}, "name",
        )
        if legacy and abs(effective_rate(_item_template_rates(legacy), context) - rate) < 0.01:
            item_templates[rate] = legacy
        else:
            item_templates[rate] = resolve_line_item_tax_template(
                company, None, rate, context, exonerated=not rate,
            )
    return {
        "taxes_and_charges": context.name,
        "exonerated_taxes_and_charges": context.exonerated,
        "included_in_print_rate": cint(context.included_in_print_rate),
        "item_tax_templates": item_templates,
    }


@frappe.whitelist()
def configure_company(company):
    """Optional wizard for new/demo sites: create restaurant templates only when missing."""
    frappe.only_for("System Manager")
    return get_native_tax_configuration(company, create=True)


def tax_context_as_json(context):
    """Serializable summary for the POS bootstrap."""
    if not context:
        return {}
    return json.loads(frappe.as_json({
        "sales_taxes_template": context.name,
        "exonerated_taxes_template": context.exonerated or "",
        "included_in_print_rate": cint(context.included_in_print_rate),
    }))
