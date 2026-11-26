"""Payment and invoicing of an order through the native Sales Invoice."""

import frappe
from frappe import _
from frappe.utils import cint, cstr, flt, nowdate, nowtime

from restaurant.checkout.accounts import _resolve_payment_account, _resolve_service_income_account
from restaurant.checkout.combos import get_combo_components
from restaurant.checkout.discounts import _approve_checkout_discounts
from restaurant.checkout.stock import _invoice_has_stock_items
from restaurant.orders.serialization import _get_areas_with_live_tables, _serialize_order
from restaurant.orders.validation import validate_order
from restaurant.pos_auth import user_can_invoice
from restaurant.pos_context import (
    _check_order_company,
    _get_active_opening_shift,
    _get_default_pos_profile,
    _require_pos_user,
)
from restaurant.pos_settings.config import _get_effective_rpos_config

RESTAURANT_TICKET = "Ticket Restaurant"


def _sync_order_totals_from_invoice(order, invoice):
    """The issued invoice is the source of truth: show its discounted totals on the order.

    The order total is what the customer paid in the transaction: the fiscal invoice total plus
    the voluntary tip, which is recorded outside the invoice.
    """
    isv_15 = flt(invoice.get("isv_15"), 2)
    isv_18 = flt(invoice.get("isv_18"), 2)
    order.db_set({
        "subtotal": flt(invoice.net_total, 2),
        "taxed_amount_15": flt(invoice.get("taxed_amount_15"), 2),
        "isv_15": isv_15,
        "taxed_amount_18": flt(invoice.get("taxed_amount_18"), 2),
        "isv_18": isv_18,
        "exempt_amount": flt(flt(invoice.get("exempt_amount")) + flt(invoice.get("exonerated_amount")), 2),
        "tax_amount": flt(isv_15 + isv_18, 2),
        "grand_total": flt(flt(invoice.grand_total) + flt(order.tip_amount), 2),
    })


def _check_change_is_paid_in_cash(payments, change_cents):
    """Change is handed back in cash, so a mixed payment may only exceed the total by its cash part."""
    if change_cents <= 0:
        return
    cash_modes = set(frappe.get_all(
        "Mode of Payment",
        filters={"name": ["in", list({row.mode_of_payment for row in payments})], "type": "Cash"},
        pluck="name",
    ))
    cash_cents = sum(round(flt(row.amount, 2) * 100) for row in payments if row.mode_of_payment in cash_modes)
    if change_cents > cash_cents:
        frappe.throw(_(
            "Solo el efectivo puede dar cambio. Cobra con tarjeta o transferencia solo el saldo pendiente "
            "y el resto en efectivo."
        ))


def _set_doc_field(doc, fieldname, value):
    setter = getattr(doc, "set", None)
    if callable(setter) and not isinstance(doc, dict):
        setter(fieldname, value)
    elif isinstance(doc, dict):
        doc[fieldname] = value
    else:
        setattr(doc, fieldname, value)


@frappe.whitelist(methods=["POST"])
def pay_and_invoice_order(
    order_name,
    payments=None,
    customer=None,
    tax_id=None,
    cai=None,
    due_date_cai=None,
    authorized_range=None,
    tip_percentage=None,
    tip_amount=None,
    global_discount_percentage=None,
    global_discount_amount=None,
    coupon_code=None,
    gift_card_code=None,
    gift_card_amount=None,
    loyalty_points=None,
    tax_category=None,
    custom_orden_compra_exenta=None,
    custom_constancia_exonerado=None,
    custom_carnet_diplomatico=None,
    custom_registro_sag=None,
    supervisor_user=None,
    supervisor_pin=None,
    reason=None,
    tip_mode_of_payment=None,
):
    """Emit and submit a native SAR Sales Invoice for a Restaurant Order and free its table."""
    _require_pos_user()
    if not user_can_invoice():
        frappe.throw(
            _("No tienes permiso para cobrar ni emitir facturas SAR. Solicita al cajero o supervisor."),
            frappe.PermissionError,
        )
    if not order_name or not frappe.db.exists("Restaurant Order", order_name):
        frappe.throw(_("La cuenta u orden seleccionada no existe."), frappe.DoesNotExistError)

    frappe.db.get_value("Restaurant Order", order_name, "name", for_update=True)
    doc = frappe.get_doc("Restaurant Order", order_name)
    _check_order_company(doc)
    doc.check_permission("write")
    if doc.status == "Facturada" or doc.sales_invoice:
        frappe.throw(_("Esta cuenta ya fue facturada en el documento {0}.").format(doc.sales_invoice or doc.name))
    if doc.status == "Cancelada" or doc.docstatus == 2:
        frappe.throw(_("No se puede facturar una orden cancelada."))
    if not doc.items:
        frappe.throw(_("No puedes facturar una orden sin platillos ni productos."))

    company = doc.company
    active_shift_info = _get_active_opening_shift(frappe.session.user)
    pos_profile = active_shift_info.get("pos_profile") if active_shift_info else doc.pos_profile
    if not pos_profile:
        default_prof = _get_default_pos_profile(company)
        pos_profile = default_prof.name if default_prof else None
    prof_doc = frappe.get_doc("POS Profile", pos_profile) if pos_profile else None
    if not prof_doc or cint(prof_doc.disabled) or prof_doc.company != company or not prof_doc.prefix:
        frappe.throw(_("Configura una serie fiscal en un perfil POS activo de la empresa de esta orden."))
    if frappe.db.exists("POS Profile", {
        "prefix": prof_doc.prefix, "company": ["!=", company], "disabled": 0,
    }):
        frappe.throw(_("La serie fiscal del perfil POS está asignada a más de una empresa."))
    rpos_cfg = _get_effective_rpos_config(pos_profile)

    if not cint(rpos_cfg.get("tips_enabled", 1)):
        if flt(tip_amount) > 0 or flt(tip_percentage) > 0 or flt(doc.tip_amount) > 0:
            frappe.throw(_("Las propinas están deshabilitadas en la configuración del POS."))

    if not cint(rpos_cfg.get("allow_line_discount", 1)):
        for row in doc.items:
            if cint(getattr(row, "is_cancelled", 0)) or row.kds_status == "Cancelado":
                continue
            if flt(row.discount_percentage) > 0:
                frappe.throw(_("Los descuentos por línea están deshabilitados en la configuración del POS."), frappe.PermissionError)

    if (flt(global_discount_percentage) > 0 or flt(global_discount_amount) > 0) and not cint(rpos_cfg.get("allow_global_discount", 1)):
        frappe.throw(_("Los descuentos globales están deshabilitados en la configuración del POS."), frappe.PermissionError)

    if coupon_code and not cint(rpos_cfg.get("enable_promotions_coupons", 0)):
        frappe.throw(_("Las promociones y cupones están deshabilitados en la configuración del POS."))

    if (gift_card_code or flt(gift_card_amount)) and not cint(rpos_cfg.get("enable_gift_cards", 0)):
        frappe.throw(_("Las tarjetas de regalo están deshabilitadas en la configuración del POS."))

    if flt(loyalty_points) > 0 and not cint(rpos_cfg.get("enable_loyalty_program", 0)):
        frappe.throw(_("El programa de lealtad está deshabilitado en la configuración del POS."))

    if customer and frappe.db.exists("Customer", customer):
        doc.customer = customer
    if tax_id is not None:
        doc.tax_id = cstr(tax_id).strip()[:60]
        if (
            doc.customer
            and doc.tax_id
            and doc.customer.strip().upper() != "CONSUMIDOR FINAL"
            and frappe.has_permission("Customer", "write")
        ):
            frappe.db.set_value("Customer", doc.customer, "tax_id", doc.tax_id)

    if tip_percentage is not None:
        doc.tip_percentage = max(0.0, flt(tip_percentage, 2))
        if doc.tip_percentage == 0 and tip_amount is not None:
            doc.tip_amount = max(0.0, flt(tip_amount, 2))
    elif tip_amount is not None:
        doc.tip_percentage = 0.0
        doc.tip_amount = max(0.0, flt(tip_amount, 2))

    si_meta = frappe.get_meta("Sales Invoice")
    cust_meta = frappe.get_meta("Customer")
    cust_lookup_fields = ["tax_category"] if cust_meta.has_field("tax_category") else []
    for exo_f in (
        "custom_subtipo_exonerado",
        "custom_constancia_exonerado",
        "custom_carnet_diplomatico",
        "custom_registro_sag",
    ):
        if cust_meta.has_field(exo_f):
            cust_lookup_fields.append(exo_f)
    cust_info = (
        frappe.db.get_value("Customer", doc.customer, cust_lookup_fields, as_dict=True)
        if doc.customer and cust_lookup_fields
        else {}
    ) or {}
    resolved_tax_category = cstr(tax_category or cust_info.get("tax_category") or "Contribuyente").strip()
    is_exonerated = resolved_tax_category.upper() == "EXONERADO"
    # The pre-bill and the invoice must apply the same exoneration rule.
    doc.flags.restaurant_tax_category = resolved_tax_category

    validate_order(doc)

    warehouse = prof_doc.warehouse
    income_account = (
        prof_doc.income_account
        if prof_doc and getattr(prof_doc, "income_account", None)
        else _resolve_service_income_account(company)
    )
    cost_center = (
        prof_doc.cost_center
        if prof_doc and getattr(prof_doc, "cost_center", None)
        else frappe.db.get_value("Company", company, "cost_center")
    )

    from restaurant.catalog.taxes import _get_item_tax_templates
    from restaurant.tax_configuration import resolve_line_item_tax_template, resolve_tax_context

    tax_context = resolve_tax_context(company, pos_profile)
    if is_exonerated and not tax_context.exonerated:
        frappe.throw(_("Configura una plantilla de impuestos de venta Exonerado para {0}.").format(company))
    prices_include_tax = bool(cint(tax_context.included_in_print_rate))

    billable_rows = [
        row for row in doc.items
        if not cint(getattr(row, "is_cancelled", 0)) and row.kds_status != "Cancelado"
    ]
    native_templates = _get_item_tax_templates([row.item_code for row in billable_rows], company)
    invoice_items = []
    line_tax_templates = []
    line_defaults = {
        key: value
        for key, value in (("warehouse", warehouse), ("income_account", income_account), ("cost_center", cost_center))
        if value
    }
    for row, components in zip(billable_rows, get_combo_components(billable_rows)):
        desc_parts = [row.item_name or row.item_code]
        if row.options_summary:
            desc_parts.append(f"Opciones: {row.options_summary}")
        if row.note:
            desc_parts.append(f"Nota: {row.note}")
        line_template = resolve_line_item_tax_template(
            company, native_templates.get(row.item_code), row.tax_rate, tax_context, exonerated=is_exonerated,
        )
        line_rate = flt(row.rate, 2)
        list_rate = flt(row.base_rate + row.options_rate, 2)
        if is_exonerated and prices_include_tax and flt(row.tax_rate):
            # Tax-inclusive price lists: an exonerated customer pays the price without its ISV.
            divisor = 1 + flt(row.tax_rate) / 100.0
            line_rate = flt(line_rate / divisor, 2)
            list_rate = flt(list_rate / divisor, 2)
        if is_exonerated and "EXENTO" not in cstr(line_template).upper():
            # Without a list price Grintsys' SAR adjustment keeps the exonerated net rate untouched.
            list_rate = 0
        item_entry = {
            "item_code": row.item_code,
            "item_name": row.item_name,
            "description": " | ".join(desc_parts),
            "qty": flt(row.qty),
            "uom": row.uom,
            "rate": line_rate,
            "price_list_rate": list_rate,
            "discount_percentage": flt(row.discount_percentage, 2),
            **line_defaults,
        }
        invoice_items.append(item_entry)
        line_tax_templates.append(line_template)
        # Combo components go at zero so the native invoice moves (and reverts) their stock.
        for component in components:
            invoice_items.append({
                "item_code": component.item_code,
                "item_name": component.item_name,
                "description": _("Incluido en el combo {0}").format(row.item_name or row.item_code),
                "qty": component.qty,
                "uom": component.uom,
                "rate": 0,
                "price_list_rate": 0,
                "discount_percentage": 0,
                **line_defaults,
            })
            line_tax_templates.append(line_template)

    if not invoice_items:
        frappe.throw(_("No hay productos activos por facturar en esta cuenta."))

    update_stock = int(_invoice_has_stock_items(invoice_items))
    if update_stock and (not warehouse or prof_doc.company != company):
        frappe.throw(_("Configura un almacén en un perfil POS de la misma empresa para facturar productos inventariables."))

    from restaurant.gift_certificates import GIFT_CERT_MOP_NAME

    enabled_mops = {row.mode_of_payment for row in prof_doc.payments if row.mode_of_payment}
    parsed_payments = frappe.parse_json(payments) if isinstance(payments, str) else payments
    payment_rows = []
    if isinstance(parsed_payments, list):
        for p in parsed_payments:
            if isinstance(p, dict) and p.get("mode_of_payment") and flt(p.get("amount")) > 0:
                mop = p["mode_of_payment"]
                if mop == GIFT_CERT_MOP_NAME:
                    frappe.throw(_("Escanea el código para aplicar un Certificado de Regalo."))
                if mop not in enabled_mops:
                    frappe.throw(
                        _("El método de pago '{0}' no está habilitado para este Punto de Venta.").format(mop),
                        frappe.PermissionError,
                    )
                acc = _resolve_payment_account(mop, company)
                payment_rows.append({
                    "mode_of_payment": mop,
                    "amount": flt(p["amount"], 2),
                    "account": acc,
                })
    # The tip never enters the SAR invoice: it is taken out of the tendered payments and
    # recorded as a staff liability with a native Journal Entry after the invoice is submitted.
    from restaurant.checkout.tips import get_tip_liability_account, split_tip_from_payments

    tip_total = flt(doc.tip_amount, 2)
    resolved_tip_mop = None
    if tip_total > 0:
        get_tip_liability_account(company)
        resolved_tip_mop = split_tip_from_payments(payment_rows, tip_total, tip_mode_of_payment)

    certificate = None
    if gift_card_code or flt(gift_card_amount):
        from restaurant.gift_certificates import get_certificate_for_redemption

        certificate = get_certificate_for_redemption(gift_card_code, company)


    # Prefer the billing cashier's active open shift so orders from prior closed shifts bill cleanly
    # and reconcile in the current cashier's shift/closing count.
    active_opening_shift = ""
    if active_shift_info:
        _check_order_company(doc, active_shift_info["company"])
        active_opening_shift = active_shift_info.get("name") or ""
    elif doc.pos_opening_shift:
        shift_row = frappe.db.get_value(
            "POS Opening Shift",
            doc.pos_opening_shift,
            ["name", "status", "docstatus", "company"],
            as_dict=True,
        )
        if shift_row and shift_row.company == company and shift_row.status == "Open" and cint(shift_row.docstatus) == 1:
            active_opening_shift = shift_row.name

    si_payload = {
        "doctype": "Sales Invoice",
        "company": company,
        "customer": doc.customer,
        "tax_id": doc.tax_id or "",
        "posting_date": nowdate(),
        "posting_time": nowtime(),
        "set_posting_time": 1,
        "due_date": nowdate(),
        "is_pos": 1,
        "pos_profile": pos_profile,
        "posa_pos_opening_shift": active_opening_shift or "",
        "currency": doc.currency or "HNL",
        "selling_price_list": doc.selling_price_list or (prof_doc.selling_price_list if prof_doc else "Venta estándar"),
        "update_stock": update_stock,
        "disable_rounded_total": 1 if not cint(rpos_cfg.get("enable_rounded_total", 0)) else 0,
        "naming_series": prof_doc.prefix,
        "posa_notes": f"Orden: {doc.order_name} | Mesa: {doc.table_label or 'N/A'} | Mesero: {doc.waiter_name or 'N/A'}",
        "items": invoice_items,
        "payments": payment_rows,
    }
    if update_stock:
        si_payload["set_warehouse"] = warehouse
    if prof_doc and getattr(prof_doc, "company_address", None):
        si_payload["company_address"] = prof_doc.company_address

    if flt(global_discount_percentage) > 0:
        si_payload["apply_discount_on"] = "Grand Total"
        si_payload["additional_discount_percentage"] = min(100.0, flt(global_discount_percentage, 2))
    elif flt(global_discount_amount) > 0:
        si_payload["apply_discount_on"] = "Grand Total"
        si_payload["discount_amount"] = flt(global_discount_amount, 2)

    if coupon_code and frappe.db.exists("Coupon Code", coupon_code):
        si_payload["coupon_code"] = coupon_code

    if si_meta.has_field("tax_category"):
        si_payload["tax_category"] = resolved_tax_category

    si_payload["taxes_and_charges"] = tax_context.exonerated if is_exonerated else tax_context.name
    for item_entry, line_template in zip(invoice_items, line_tax_templates):
        item_entry["item_tax_template"] = line_template
    exo_values = {
        "custom_subtipo_exonerado": cstr(cust_info.get("custom_subtipo_exonerado") or "").strip() if is_exonerated else "",
        "custom_orden_compra_exenta": cstr(custom_orden_compra_exenta or "").strip() if is_exonerated else "",
        "custom_constancia_exonerado": cstr(custom_constancia_exonerado or cust_info.get("custom_constancia_exonerado") or "").strip() if is_exonerated else "",
        "custom_carnet_diplomatico": cstr(custom_carnet_diplomatico or cust_info.get("custom_carnet_diplomatico") or "").strip() if is_exonerated else "",
        "custom_registro_sag": cstr(custom_registro_sag or cust_info.get("custom_registro_sag") or "").strip() if is_exonerated else "",
    }
    for exo_field, exo_val in exo_values.items():
        if si_meta.has_field(exo_field):
            si_payload[exo_field] = exo_val

    for r_field, r_val in (
        ("restaurant_order", doc.name),
        ("restaurant_order_number", cstr(doc.order_name or doc.name)),
        ("restaurant_table_label", cstr(doc.table_label or "")),
        ("restaurant_service_type", cstr(doc.service_type or "")),
        ("restaurant_waiter_name", cstr(doc.waiter_name or "")),
    ):
        if si_meta.has_field(r_field):
            si_payload[r_field] = r_val

    if si_meta.has_field("cashier"):
        si_payload["cashier"] = frappe.session.user
    if si_meta.has_field("redeem_loyalty_points") and flt(loyalty_points) > 0:
        si_payload["redeem_loyalty_points"] = 1
        si_payload["loyalty_points"] = cint(loyalty_points)

    si = frappe.get_doc(si_payload)
    si.set_missing_values()
    _set_doc_field(si, "payments", payment_rows)
    si.update_stock = update_stock
    si.disable_rounded_total = si_payload["disable_rounded_total"]
    si.tax_category = resolved_tax_category
    si.taxes_and_charges = si_payload["taxes_and_charges"]
    # Load the native tax master after POS defaults; the invoice carries consumption and ISV only.
    from erpnext.controllers.accounts_controller import get_taxes_and_charges

    _set_doc_field(si, "taxes", get_taxes_and_charges(
        "Sales Taxes and Charges Template", si.taxes_and_charges,
    ))
    si.calculate_taxes_and_totals()

    _approve_checkout_discounts(si, doc, prof_doc, supervisor_user, supervisor_pin, reason)
    grand_total = flt(si.grand_total, 2)
    if certificate:
        from restaurant.gift_certificates import apply_certificate

        apply_certificate(si, certificate, gift_card_amount)
    expected_paid_due = flt(si.rounded_total if not cint(si.disable_rounded_total) else grand_total, 2)
    total_paid = sum(flt(p.amount) for p in si.payments)
    total_paid_cents = round(flt(total_paid, 2) * 100)
    expected_due_cents = round(flt(expected_paid_due, 2) * 100)
    if total_paid_cents < expected_due_cents:
        frappe.throw(
            _("El monto total pagado ({0:.2f}) es menor al total por cobrar ({1:.2f}).").format(
                flt(total_paid, 2), flt(expected_paid_due, 2)
            )
        )

    _check_change_is_paid_in_cash(si.payments, total_paid_cents - expected_due_cents)

    if expected_due_cents == 0 and total_paid_cents > 0:
        frappe.throw(_("Una factura con total cero no admite un importe recibido."))
    if not si.payments and expected_due_cents == 0:
        # ERPNext requires a payment row even when the invoice has no amount due.
        zero_payment = next((row for row in prof_doc.payments if cint(row.default)), None)
        zero_payment = zero_payment or next(iter(prof_doc.payments), None)
        if not zero_payment:
            frappe.throw(_("Configura un método de pago en el perfil de Punto de Venta."))
        si.append("payments", {
            "mode_of_payment": zero_payment.mode_of_payment,
            "amount": 0,
            "account": _resolve_payment_account(zero_payment.mode_of_payment, company),
        })

    si.insert(ignore_permissions=True)
    auto_submit = bool(cint(rpos_cfg.get("auto_validate_orders", 1)))
    if auto_submit:
        if getattr(si, "flags", None) is not None:
            # The tip Journal Entry is created right below; the on_submit hook must not repeat it.
            si.flags.restaurant_tip_handled = True
        si.submit()

    invoice_finalized = (cint(getattr(si, "docstatus", 0)) == 1) or auto_submit

    if active_opening_shift:
        doc.pos_opening_shift = active_opening_shift
    has_tip_fields = frappe.get_meta("Restaurant Order").has_field("tip_journal_entry")
    if has_tip_fields:
        doc.tip_mode_of_payment = resolved_tip_mop
        doc.tip_journal_entry = None
        if invoice_finalized and resolved_tip_mop:
            from restaurant.checkout.tips import create_tip_journal_entry

            doc.tip_journal_entry = create_tip_journal_entry(doc, si, tip_total, resolved_tip_mop)
    doc.sales_invoice = si.name
    doc.cai = si.cai
    doc.due_date_cai = si.due_date_cai
    doc.status = "Facturada" if invoice_finalized else "En curso"
    doc.save()
    if invoice_finalized:
        _sync_order_totals_from_invoice(doc, si)

    from restaurant.sar_format import format_lempiras_in_words

    return {
        "order": _serialize_order(doc),
        "invoice": {
            "name": si.name,
            "posting_date": str(si.posting_date),
            "posting_time": cstr(si.get("posting_time") or ""),
            "customer": si.customer,
            "customer_name": si.customer_name,
            "tax_id": si.tax_id or "",
            "tax_category": cstr(si.get("tax_category") or "Contribuyente"),
            "custom_orden_compra_exenta": cstr(si.get("custom_orden_compra_exenta") or ""),
            "custom_constancia_exonerado": cstr(si.get("custom_constancia_exonerado") or ""),
            "custom_carnet_diplomatico": cstr(si.get("custom_carnet_diplomatico") or ""),
            "custom_registro_sag": cstr(si.get("custom_registro_sag") or ""),
            "company": si.company,
            "company_tax_id": cstr(si.company_tax_id),
            "cai": cstr(si.cai),
            "due_date_cai": cstr(si.due_date_cai),
            "authorized_range": cstr(si.get("authorized_range")),
            "prefix": cstr(si.get("naming_series")) or prof_doc.prefix,
            "print_format": (prof_doc.print_format if prof_doc and prof_doc.print_format else RESTAURANT_TICKET),
            "net_total": flt(si.net_total, 2),
            "discount_amount": flt(si.get("discount_amount"), 2),
            "taxed_amount_15": flt(si.get("taxed_amount_15"), 2),
            "isv_15": flt(si.get("isv_15"), 2),
            "taxed_amount_18": flt(si.get("taxed_amount_18"), 2),
            "isv_18": flt(si.get("isv_18"), 2),
            "exempt_amount": flt(si.get("exempt_amount"), 2),
            "exonerated_amount": flt(si.get("exonerated_amount"), 2),
            "tip_amount": flt(tip_total, 2),
            "tip_mode_of_payment": cstr(resolved_tip_mop or ""),
            "tip_journal_entry": cstr(doc.get("tip_journal_entry") or ""),
            "total_collected": flt(flt(si.grand_total) + tip_total, 2),
            "grand_total": flt(si.grand_total, 2),
            "paid_amount": flt(si.paid_amount, 2),
            "change_amount": flt(si.change_amount, 2),
            "in_words": format_lempiras_in_words(si.grand_total),
        },
        "areas": _get_areas_with_live_tables(),
    }
