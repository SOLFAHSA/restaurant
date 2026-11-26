"""Checkout extras: coupons, gift certificates, loyalty, email, WhatsApp and receipts."""

import re

import frappe
from frappe import _
from frappe.utils import cint, cstr, flt, nowdate

from restaurant.pos_auth import user_can_invoice
from restaurant.pos_context import (
    _get_active_opening_shift,
    _get_default_company,
    _get_order_company,
    _require_pos_user,
)
from restaurant.pos_settings.config import _get_effective_rpos_config


@frappe.whitelist()
def validate_coupon_code(coupon_code, order_total=0, customer=None):
    """Validate an ERPNext Coupon Code / Pricing Rule for POS discount application."""
    _require_pos_user()
    active_shift = _get_active_opening_shift(frappe.session.user)
    cfg = _get_effective_rpos_config(active_shift["pos_profile"] if active_shift else None)
    if not cint(cfg.get("enable_promotions_coupons")):
        frappe.throw(_("Las promociones y cupones están deshabilitados en la configuración del POS."))

    code = cstr(coupon_code or "").strip()
    if not code or not frappe.db.exists("Coupon Code", code):
        frappe.throw(_("El código de cupón '{0}' no es válido.").format(code))

    coupon = frappe.get_doc("Coupon Code", code)
    if coupon.valid_upto and frappe.utils.getdate(coupon.valid_upto) < frappe.utils.getdate(nowdate()):
        frappe.throw(_("El cupón '{0}' ha expirado.").format(code))
    if coupon.maximum_use and cint(coupon.used) >= cint(coupon.maximum_use):
        frappe.throw(_("El cupón '{0}' alcanzó su límite máximo de usos.").format(code))

    discount_pct = 0.0
    discount_amt = 0.0
    if coupon.pricing_rule and frappe.db.exists("Pricing Rule", coupon.pricing_rule):
        pr = frappe.get_doc("Pricing Rule", coupon.pricing_rule)
        if pr.rate_or_discount == "Discount Percentage":
            discount_pct = flt(pr.discount_percentage, 2)
        elif pr.rate_or_discount == "Discount Amount":
            discount_amt = flt(pr.discount_amount, 2)

    return {
        "coupon_code": coupon.name,
        "coupon_name": coupon.coupon_name,
        "discount_percentage": discount_pct,
        "discount_amount": discount_amt,
    }


@frappe.whitelist(methods=["POST"])
def validate_gift_card(card_code):
    """Validate a native gift certificate for the current company."""
    _require_pos_user()
    if not user_can_invoice():
        frappe.throw(_("Solo cajeros o supervisores pueden validar certificados de regalo."), frappe.PermissionError)

    active_shift = _get_active_opening_shift(frappe.session.user)
    cfg = _get_effective_rpos_config(active_shift["pos_profile"] if active_shift else None)
    if not cint(cfg.get("enable_gift_cards")):
        frappe.throw(_("Los certificados de regalo están deshabilitados en la configuración del POS."))

    from restaurant.gift_certificates import get_certificate_for_redemption

    company = active_shift["company"] if active_shift else _get_order_company()
    certificate = get_certificate_for_redemption(card_code, company)
    return {
        "masked_code": certificate["codigo_enmascarado"],
        "balance": flt(certificate["saldo_disponible"], 2),
    }


@frappe.whitelist()
def get_customer_loyalty_points(customer, company=None):
    """Return available ERPNext Loyalty Points for a customer when loyalty is enabled."""
    _require_pos_user()
    active_shift = _get_active_opening_shift(frappe.session.user)
    cfg = _get_effective_rpos_config(active_shift["pos_profile"] if active_shift else None)
    if not cint(cfg.get("enable_loyalty_program")):
        frappe.throw(_("El programa de lealtad está deshabilitado en la configuración del POS."))

    if not customer or not frappe.db.exists("Customer", customer):
        return {"loyalty_points": 0, "conversion_factor": 0.0, "loyalty_program": ""}

    loyalty_program = frappe.db.get_value("Customer", customer, "loyalty_program") or ""
    if not loyalty_program:
        return {"loyalty_points": 0, "conversion_factor": 0.0, "loyalty_program": ""}

    from erpnext.accounts.doctype.loyalty_program.loyalty_program import get_loyalty_program_details_with_points

    details = get_loyalty_program_details_with_points(
        customer,
        loyalty_program=loyalty_program,
        company=company or _get_default_company(),
        silent=True,
    ) or {}
    return {
        "loyalty_program": loyalty_program,
        "loyalty_points": cint(details.get("loyalty_points", 0)),
        "conversion_factor": flt(details.get("conversion_factor", 0.0)),
    }


@frappe.whitelist(methods=["POST"])
def send_invoice_email(invoice_name, recipient_email=None):
    """Send Sales Invoice PDF via Frappe native email configuration."""
    _require_pos_user()
    active_shift = _get_active_opening_shift(frappe.session.user)
    cfg = _get_effective_rpos_config(active_shift["pos_profile"] if active_shift else None)
    if not cint(cfg.get("allow_email_invoice", 1)):
        frappe.throw(_("El envío de facturas por correo electrónico está deshabilitado en la configuración del POS."))

    if not invoice_name or not frappe.db.exists("Sales Invoice", invoice_name):
        frappe.throw(_("La factura solicitada no existe."))

    si = frappe.get_doc("Sales Invoice", invoice_name)
    si.check_permission("read")
    target_email = cstr(recipient_email or frappe.db.get_value("Customer", si.customer, "email_id") or "").strip()
    if not target_email:
        frappe.throw(_("El cliente no tiene un correo electrónico configurado."))

    attachment = frappe.attach_print(
        "Sales Invoice",
        si.name,
        file_name=f"{si.name}.pdf",
        print_format=(
            frappe.db.get_value("POS Profile", si.pos_profile, "print_format") if si.get("pos_profile") else None
        ) or "Ticket Restaurant",
    )
    frappe.sendmail(
        recipients=[target_email],
        subject=_("Factura {0} - {1}").format(si.name, si.company),
        message=_("Adjunto enviamos su comprobante fiscal {0} por un total de {1} {2}.").format(
            si.name, si.currency, flt(si.grand_total, 2)
        ),
        attachments=[attachment],
        now=True,
    )
    return {"status": "sent", "recipient": target_email, "invoice": si.name}


@frappe.whitelist()
def get_whatsapp_invoice_share_link(invoice_name, phone=None):
    """Generate a safe WhatsApp share URL for a Sales Invoice without sending automatically."""
    _require_pos_user()
    active_shift = _get_active_opening_shift(frappe.session.user)
    cfg = _get_effective_rpos_config(active_shift["pos_profile"] if active_shift else None)
    if not cint(cfg.get("allow_whatsapp_invoice")):
        frappe.throw(_("El envío de facturas por WhatsApp está deshabilitado en la configuración del POS."))

    if not invoice_name or not frappe.db.exists("Sales Invoice", invoice_name):
        frappe.throw(_("La factura solicitada no existe."))

    si = frappe.get_doc("Sales Invoice", invoice_name)
    si.check_permission("read")
    clean_phone = re.sub(r"[^\d]", "", cstr(phone or frappe.db.get_value("Customer", si.customer, "mobile_no") or ""))
    text = (
        f"Comprobante {si.name} - {si.company}\n"
        f"Cliente: {si.customer_name}\n"
        f"Total: {si.currency} {flt(si.grand_total, 2):,.2f}\n"
        f"CAI: {si.get('cai') or 'N/A'}"
    )
    from urllib.parse import quote

    base_url = f"https://wa.me/{clean_phone}" if clean_phone else "https://wa.me/"
    return {"url": f"{base_url}?text={quote(text)}", "invoice": si.name}


@frappe.whitelist()
def get_self_invoicing_receipt_data(invoice_name):
    """Return SAR Honduras fiscal receipt metadata and self-invoicing URL when enabled."""
    _require_pos_user()
    active_shift = _get_active_opening_shift(frappe.session.user)
    cfg = _get_effective_rpos_config(active_shift["pos_profile"] if active_shift else None)
    if not cint(cfg.get("enable_self_invoicing")):
        frappe.throw(_("La autofacturación está deshabilitada en la configuración del POS."))

    if not invoice_name or not frappe.db.exists("Sales Invoice", invoice_name):
        frappe.throw(_("La factura solicitada no existe."))

    si = frappe.get_doc("Sales Invoice", invoice_name)
    si.check_permission("read")
    return {
        "invoice": si.name,
        "company": si.company,
        "customer": si.customer_name,
        "tax_id": si.tax_id or "",
        "cai": si.get("cai") or "",
        "due_date_cai": cstr(si.get("due_date_cai") or ""),
        "grand_total": flt(si.grand_total, 2),
        "currency": si.currency,
        "portal_url": frappe.utils.get_url(f"/app/sales-invoice/{si.name}"),
    }
