"""Accounts and SAR fiscal data resolved from native configuration."""

import frappe
from frappe import _
from frappe.utils import cint, cstr

from restaurant.pos_context import _get_default_company


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
