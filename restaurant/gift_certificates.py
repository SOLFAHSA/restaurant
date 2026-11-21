"""Adapt Restaurant checkout to Grintsys gift certificates."""

import frappe
from frappe import _
from frappe.utils import cint, flt

from erpnext.accounts.doctype.certificado_de_regalo.certificado_de_regalo import (
    GIFT_CERT_ACCOUNT_BASE_NAME,
    GIFT_CERT_MOP_NAME,
    validar_codigo_para_canje,
    validate_sales_invoice_certificados,
)


def get_certificate_for_redemption(code, company):
    """Check the accounting setup before calling the native redemption API."""
    abbr = frappe.db.get_value("Company", company, "abbr")
    account = f"{GIFT_CERT_ACCOUNT_BASE_NAME} - {abbr}"
    if not frappe.db.exists("Account", account):
        account = frappe.db.get_value("Account", {
            "company": company, "account_name": GIFT_CERT_ACCOUNT_BASE_NAME, "is_group": 0,
        })
    configured_account = frappe.db.get_value(
        "Mode of Payment Account",
        {"parent": GIFT_CERT_MOP_NAME, "parenttype": "Mode of Payment", "company": company},
        "default_account",
    )
    if not (
        account
        and configured_account == account
        and cint(frappe.db.get_value("Mode of Payment", GIFT_CERT_MOP_NAME, "enabled"))
        and frappe.db.exists("Account", {
            "name": account, "company": company, "root_type": "Liability",
            "is_group": 0, "disabled": 0,
        })
    ):
        frappe.throw(_("Configura el método Certificado de Regalo y su cuenta de pasivo para esta empresa."))

    return validar_codigo_para_canje(code, company)


def apply_certificate(invoice, certificate, amount):
    """Add the native child row and let ERPNext synchronize its payment."""
    amount = flt(amount, 2)
    total = flt(invoice.grand_total if cint(invoice.disable_rounded_total) else invoice.rounded_total, 2)
    # ERPNext caps other payment rows during its validation, including cash tendered.
    remaining = flt(total - amount, 2)
    tendered = flt(sum(flt(row.amount) for row in invoice.payments), 2)
    if amount <= 0 or amount > total or amount > flt(certificate["saldo_disponible"], 2):
        frappe.throw(_("El monto del certificado debe ser mayor a cero y no superar el saldo ni el total por cobrar."))
    if tendered != remaining:
        frappe.throw(_("Con un certificado de regalo, registra el saldo restante exacto de {0:.2f}.").format(remaining))

    invoice.append("certificados_de_regalo", {
        "certificado_de_regalo": certificate["certificado_de_regalo"],
        "monto_aplicado": amount,
    })
    validate_sales_invoice_certificados(invoice)
