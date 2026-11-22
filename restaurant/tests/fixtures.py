"""Shared, idempotent baseline data so the Restaurant suite runs on a clean test site.

The suite was written against the `development` site and relied on records that only
exist there (a customer, a POS Profile with a SAR test series, a bank payment method and
preparation stages). This module creates ONLY what is missing and never edits existing
records, so on `development` it is a no-op.

It runs once per process and commits only when it created something, because test
classes roll back their own transactions.
"""

import frappe
from frappe.utils import add_days, nowdate

QA_CUSTOMER = "Consumidor Final"
QA_POS_PROFILE = "QA Restaurante"
QA_CASH_MOP = "Efectivo"
QA_BANK_MOP = "Transferencia bancaria"
QA_BANK_ACCOUNT_NAME = "Banco QA Restaurante"
QA_SAR_PREFIX = "000-099-01-.########"
QA_CAI = "QA-RESTAURANTE-BASELINE"
QA_STAGES = (
    ("Preparación", "#9CA3AF", 10),
    ("Entrega", "#3B82F6", 5),
    ("Completado", "#22C55E", 0),
)

_ensured = False


def ensure_restaurant_test_baseline():
    """Create the minimum baseline required by the Restaurant tests, only if missing."""
    global _ensured
    if _ensured:
        return
    original_user = frappe.session.user
    frappe.set_user("Administrator")
    created = []
    try:
        company = _get_company()
        if company:
            created += _ensure_customer()
            created += _ensure_cash_mode(company)
            created += _ensure_bank_mode(company)
            created += _ensure_pos_profile(company)
            created += _ensure_cai()
        created += _ensure_stages()
        if created:
            frappe.db.commit()
    finally:
        frappe.set_user(original_user)
    _ensured = True


def _get_company():
    company = frappe.defaults.get_global_default("company")
    if company and frappe.db.exists("Company", company):
        return company
    return frappe.db.get_value("Company", {}, "name")


def _leaf(doctype, **filters):
    return frappe.db.get_value(doctype, {"is_group": 0, **filters}, "name")


def _ensure_customer():
    if frappe.db.get_value("Customer", {"disabled": 0}, "name"):
        return []
    frappe.get_doc({
        "doctype": "Customer",
        "customer_name": QA_CUSTOMER,
        "customer_type": "Individual",
        "customer_group": _leaf("Customer Group") or "Individual",
        "territory": _leaf("Territory") or "All Territories",
    }).insert(ignore_permissions=True)
    return ["Customer"]


def _ensure_mode_account(mode, company, account):
    doc = frappe.get_doc("Mode of Payment", mode)
    if any(row.company == company for row in doc.accounts):
        return []
    doc.append("accounts", {"company": company, "default_account": account})
    doc.save(ignore_permissions=True)
    return ["Mode of Payment Account"]


def _ensure_cash_mode(company):
    created = []
    if not frappe.db.exists("Mode of Payment", QA_CASH_MOP):
        frappe.get_doc({
            "doctype": "Mode of Payment", "mode_of_payment": QA_CASH_MOP, "type": "Cash", "enabled": 1,
        }).insert(ignore_permissions=True)
        created.append("Mode of Payment")
    cash_account = frappe.get_cached_value("Company", company, "default_cash_account") or _leaf(
        "Account", company=company, account_type="Cash"
    )
    if cash_account:
        created += _ensure_mode_account(QA_CASH_MOP, company, cash_account)
    return created


def _ensure_bank_mode(company):
    # Skip when any Bank-type payment method already has an account for this company.
    for row in frappe.get_all(
        "Mode of Payment Account",
        filters={"company": company, "default_account": ["is", "set"]},
        fields=["parent"],
    ):
        if frappe.db.get_value("Mode of Payment", row.parent, "type") == "Bank":
            return []
    created = []
    bank_account = _leaf("Account", company=company, account_type="Bank")
    if not bank_account:
        parent = frappe.db.get_value(
            "Account", {"company": company, "is_group": 1, "account_type": "Bank"}, "name"
        ) or frappe.db.get_value("Account", {"company": company, "is_group": 1, "root_type": "Asset"}, "name")
        bank_account = frappe.get_doc({
            "doctype": "Account",
            "account_name": QA_BANK_ACCOUNT_NAME,
            "company": company,
            "parent_account": parent,
            "account_type": "Bank",
            "is_group": 0,
        }).insert(ignore_permissions=True).name
        created.append("Account")
    if not frappe.db.exists("Mode of Payment", QA_BANK_MOP):
        frappe.get_doc({
            "doctype": "Mode of Payment", "mode_of_payment": QA_BANK_MOP, "type": "Bank", "enabled": 1,
        }).insert(ignore_permissions=True)
        created.append("Mode of Payment")
    created += _ensure_mode_account(QA_BANK_MOP, company, bank_account)
    return created


def _ensure_pos_profile(company):
    if frappe.db.get_value("POS Profile", {"disabled": 0, "company": company}, "name"):
        return []
    values = frappe.get_cached_value(
        "Company", company, ["default_currency", "write_off_account", "cost_center"], as_dict=True
    )
    profile = frappe.get_doc({
        "doctype": "POS Profile",
        "name": QA_POS_PROFILE,
        "company": company,
        "currency": values.default_currency,
        "warehouse": _leaf("Warehouse", company=company),
        "customer": frappe.db.get_value("Customer", {"disabled": 0}, "name"),
        "selling_price_list": frappe.db.get_value("Price List", {"selling": 1, "enabled": 1}, "name"),
        "select_doc_for_series": "Sales Invoice",
        "prefix": QA_SAR_PREFIX,
        "write_off_account": values.write_off_account,
        "write_off_cost_center": values.cost_center,
        "cost_center": values.cost_center,
        "write_off_limit": 1,
        "payments": [{"mode_of_payment": QA_CASH_MOP, "default": 1}],
    })
    profile.insert(ignore_permissions=True, set_name=QA_POS_PROFILE)
    return ["POS Profile"]


def _ensure_cai():
    if not frappe.db.exists("POS Profile", QA_POS_PROFILE) or frappe.db.exists("CAI", {"prefix": QA_SAR_PREFIX}):
        return []
    frappe.get_doc({
        "doctype": "CAI",
        "name_cai": QA_CAI,
        "no_declaration": QA_CAI,
        "cai": QA_CAI,
        "initial_number": "00000001",
        "final_number": "09999999",
        "reception_date": add_days(nowdate(), -1),
        "issue_deadline": add_days(nowdate(), 3650),
        "select_doc_for_series": "Sales Invoice",
        "prefix": QA_SAR_PREFIX,
        "expired_days": "1",
        "expired_amount": 1,
    }).insert(ignore_permissions=True)
    return ["CAI"]


def _ensure_stages():
    if frappe.db.count("Restaurant Preparation Stage") >= len(QA_STAGES):
        return []
    existing = set(frappe.get_all("Restaurant Preparation Stage", pluck="stage_name"))
    created = []
    for stage_name, color, minutes in QA_STAGES:
        if stage_name in existing:
            continue
        frappe.get_doc({
            "doctype": "Restaurant Preparation Stage",
            "stage_name": stage_name,
            "color": color,
            "alert_minutes": minutes,
        }).insert(ignore_permissions=True)
        created.append("Restaurant Preparation Stage")
    return created


def item_tax_rows(rate=15):
    """Item Tax rows that give a test item an explicit native template for every company."""
    from restaurant.tax_configuration import get_item_tax_template

    rows = []
    for company in frappe.get_all("Company", pluck="name"):
        try:
            rows.append({"item_tax_template": get_item_tax_template(company, rate, create=True)})
        except frappe.ValidationError:
            # Companies without Honduras ISV accounts cannot sell restaurant items.
            frappe.clear_messages()
    return rows


def ensure_item_tax(item_code, rate=15):
    """Attach a template to a reused test item only when neither it nor its group provides one."""
    from restaurant.pos import _get_item_tax_rates

    companies = frappe.get_all("Company", pluck="name")
    if all(_get_item_tax_rates([item_code], company).get(item_code) is not None for company in companies):
        return
    item = frappe.get_doc("Item", item_code)
    current = {row.item_tax_template for row in item.taxes}
    for row in item_tax_rows(rate):
        if row["item_tax_template"] not in current:
            item.append("taxes", row)
    item.save(ignore_permissions=True)


def existing_invoice_name():
    """Return a Sales Invoice to use as a link target, creating a draft on a clean test site."""
    name = frappe.db.get_value("Sales Invoice", {}, "name")
    if name:
        return name
    ensure_restaurant_test_baseline()
    company = _get_company()
    item = frappe.get_doc({
        "doctype": "Item",
        "item_code": f"QA-LINK-{frappe.generate_hash(length=8)}",
        "item_name": "Producto de enlace de prueba",
        "item_group": _leaf("Item Group"),
        "stock_uom": frappe.db.get_value("UOM", {}, "name"),
        "is_stock_item": 0,
        "is_sales_item": 1,
        "taxes": item_tax_rows(),
    }).insert(ignore_permissions=True)
    return frappe.get_doc({
        "doctype": "Sales Invoice",
        "company": company,
        "customer": frappe.db.get_value("Customer", {"disabled": 0}, "name"),
        "naming_series": QA_SAR_PREFIX,
        "items": [{"item_code": item.name, "qty": 1, "rate": 1}],
    }).insert(ignore_permissions=True).name
