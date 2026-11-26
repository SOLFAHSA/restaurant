"""Voluntary tips: a staff liability recorded with a native Journal Entry, never on the SAR invoice.

In Honduras the voluntary tip is collected on behalf of the staff: it is not restaurant income,
it is not part of the ISV base and it is not billed on the fiscal invoice. The cash or bank
movement is recorded as Debit Cash/Bank (Mode of Payment account) / Credit tip liability.
"""

import frappe
from frappe import _
from frappe.utils import cint, cstr, flt

TIP_ACCOUNT_FIELD = "tip_liability_account"


def validate_tip_liability_account(account, company=None):
    """The tip account must be a ledger Liability account without a party (not Payable)."""
    row = frappe.db.get_value(
        "Account", account, ["root_type", "is_group", "company", "account_type", "disabled"], as_dict=True,
    )
    if not row:
        frappe.throw(_("La cuenta de propinas {0} no existe.").format(account))
    if row.root_type != "Liability" or cint(row.is_group):
        frappe.throw(_(
            "La cuenta de propinas {0} debe ser una cuenta de pasivo de detalle (no de grupo)."
        ).format(account))
    if row.account_type in ("Payable", "Receivable"):
        frappe.throw(_(
            "La cuenta de propinas {0} no puede ser de tipo Por Pagar o Por Cobrar; usa una cuenta de pasivo sin tercero."
        ).format(account))
    if cint(row.disabled):
        frappe.throw(_("La cuenta de propinas {0} está deshabilitada.").format(account))
    if company and row.company != company:
        frappe.throw(_("La cuenta de propinas {0} no pertenece a la empresa {1}.").format(account, company))
    return account


def get_tip_liability_account(company):
    """Read the configured tip liability account for the company of the order."""
    account = None
    if frappe.get_meta("Restaurant Settings").has_field(TIP_ACCOUNT_FIELD):
        account = frappe.db.get_single_value("Restaurant Settings", TIP_ACCOUNT_FIELD)
    if not account or frappe.db.get_value("Account", account, "company") != company:
        frappe.throw(_(
            "Configura la cuenta de pasivo 'Propinas por pagar a empleados' de {0} en Configuración del Restaurante "
            "antes de cobrar propinas."
        ).format(company))
    return validate_tip_liability_account(account, company)


def split_tip_from_payments(payment_rows, tip_amount, tip_mode_of_payment=None):
    """Remove the tip from the tendered payments so the invoice only receives the consumption.

    The tip is taken from the requested Mode of Payment or, by default, from the first electronic
    payment (card / transfer) and otherwise from cash. Returns the Mode of Payment used.
    """
    tip_cents = round(flt(tip_amount, 2) * 100)
    if tip_cents <= 0:
        return None
    if not payment_rows:
        frappe.throw(_("Registra el pago de la propina junto con el cobro de la cuenta."))
    modes = [row["mode_of_payment"] for row in payment_rows]
    if tip_mode_of_payment:
        if tip_mode_of_payment not in modes:
            frappe.throw(_(
                "La propina debe cobrarse con uno de los métodos de pago de esta transacción ({0})."
            ).format(", ".join(modes)))
        chosen = tip_mode_of_payment
    else:
        cash_modes = set(frappe.get_all(
            "Mode of Payment", filters={"name": ["in", modes], "type": "Cash"}, pluck="name",
        ))
        chosen = next((mode for mode in modes if mode not in cash_modes), modes[0])
    row = next(row for row in payment_rows if row["mode_of_payment"] == chosen)
    if round(flt(row["amount"], 2) * 100) < tip_cents:
        frappe.throw(_(
            "El pago con {0} ({1:.2f}) no cubre la propina de {2:.2f}."
        ).format(chosen, flt(row["amount"], 2), flt(tip_amount, 2)))
    row["amount"] = flt((round(flt(row["amount"], 2) * 100) - tip_cents) / 100.0, 2)
    if row["amount"] <= 0:
        payment_rows.remove(row)
    return chosen


def create_tip_journal_entry(order, invoice, tip_amount, mode_of_payment):
    """Submit a native Journal Entry: Debit Cash/Bank of the Mode of Payment, Credit tip liability."""
    from restaurant.checkout.accounts import _resolve_payment_account

    tip_amount = flt(tip_amount, 2)
    if tip_amount <= 0:
        return None
    company = invoice.company
    cash_account = _resolve_payment_account(mode_of_payment, company)
    liability_account = get_tip_liability_account(company)
    cost_center = invoice.get("cost_center") or frappe.get_cached_value("Company", company, "cost_center")
    shift = cstr(invoice.get("posa_pos_opening_shift") or order.get("pos_opening_shift") or "")
    remark = _(
        "Propina voluntaria recaudada a favor del personal (no forma parte de la factura SAR). "
        "Orden: {0} | Factura: {1} | Turno: {2} | Mesero: {3} | Medio de pago: {4}"
    ).format(order.name, invoice.name, shift or "N/A", order.get("waiter_name") or order.get("waiter") or "N/A", mode_of_payment)
    journal = frappe.get_doc({
        "doctype": "Journal Entry",
        "voucher_type": "Journal Entry",
        "company": company,
        "posting_date": invoice.posting_date,
        "user_remark": remark,
        "accounts": [
            {
                "account": cash_account,
                "debit_in_account_currency": tip_amount,
                "credit_in_account_currency": 0,
                "cost_center": cost_center,
                "user_remark": remark,
            },
            {
                "account": liability_account,
                "debit_in_account_currency": 0,
                "credit_in_account_currency": tip_amount,
                "cost_center": cost_center,
                "user_remark": remark,
            },
        ],
    })
    journal.flags.ignore_permissions = True
    journal.insert()
    journal.submit()
    return journal.name


def cancel_tip_journal_entry(journal_entry):
    """Reverse the tip liability when its invoice is cancelled."""
    if not journal_entry or not frappe.db.exists("Journal Entry", journal_entry):
        return
    journal = frappe.get_doc("Journal Entry", journal_entry)
    if journal.docstatus != 1:
        return
    journal.flags.ignore_permissions = True
    journal.cancel()


def create_pending_tip_journal_entry(invoice, method=None):
    """Sales Invoice on_submit: record the tip of a draft restaurant invoice submitted later."""
    if invoice.flags.get("restaurant_tip_handled"):
        return
    order_name = invoice.get("restaurant_order")
    if not order_name or not frappe.db.exists("Restaurant Order", order_name):
        return
    order = frappe.get_doc("Restaurant Order", order_name)
    if order.sales_invoice != invoice.name or order.get("tip_journal_entry") or flt(order.tip_amount) <= 0:
        return
    if not order.get("tip_mode_of_payment"):
        return
    journal = create_tip_journal_entry(order, invoice, order.tip_amount, order.tip_mode_of_payment)
    frappe.db.set_value("Restaurant Order", order.name, "tip_journal_entry", journal, update_modified=False)


def get_shift_tips_by_mode(pos_opening_shift):
    """Tips received during a POS shift, per Mode of Payment, from submitted tip Journal Entries."""
    if not pos_opening_shift or not frappe.get_meta("Restaurant Order").has_field("tip_journal_entry"):
        return {}
    rows = frappe.db.sql(
        """
        SELECT ord.tip_mode_of_payment AS mode_of_payment, SUM(je.total_debit) AS amount
        FROM `tabRestaurant Order` ord
        INNER JOIN `tabJournal Entry` je ON je.name = ord.tip_journal_entry
        WHERE ord.pos_opening_shift = %s AND je.docstatus = 1
        GROUP BY ord.tip_mode_of_payment
        """,
        (pos_opening_shift,),
        as_dict=True,
    )
    return {row.mode_of_payment: flt(row.amount, 2) for row in rows if row.mode_of_payment}
