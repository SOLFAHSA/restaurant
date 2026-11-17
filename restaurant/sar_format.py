"""Honduras SAR fiscal receipt formatting helpers for LEAF Restaurant."""

import re
from decimal import Decimal, ROUND_HALF_UP

import frappe
from frappe.utils import cstr, flt, formatdate

_UNITS = (
    "",
    "UN",
    "DOS",
    "TRES",
    "CUATRO",
    "CINCO",
    "SEIS",
    "SIETE",
    "OCHO",
    "NUEVE",
    "DIEZ",
    "ONCE",
    "DOCE",
    "TRECE",
    "CATORCE",
    "QUINCE",
    "DIECISEIS",
    "DIECISIETE",
    "DIECIOCHO",
    "DIECINUEVE",
    "VEINTE",
    "VEINTIUN",
    "VEINTIDOS",
    "VEINTITRES",
    "VEINTICUATRO",
    "VEINTICINCO",
    "VEINTISEIS",
    "VEINTISIETE",
    "VEINTIOCHO",
    "VEINTINUEVE",
)

_TENS = (
    "",
    "",
    "",
    "TREINTA",
    "CUARENTA",
    "CINCUENTA",
    "SESENTA",
    "SETENTA",
    "OCHENTA",
    "NOVENTA",
)

_HUNDREDS = (
    "",
    "CIENTO",
    "DOSCIENTOS",
    "TRESCIENTOS",
    "CUATROCIENTOS",
    "QUINIENTOS",
    "SEISCIENTOS",
    "SETECIENTOS",
    "OCHOCIENTOS",
    "NOVECIENTOS",
)


def _group_to_words(n):
    """Convert an integer between 0 and 999 into uppercase Spanish words (apocopated for currency)."""
    if n == 0:
        return ""
    if n == 100:
        return "CIEN"
    parts = []
    hundreds = n // 100
    rem = n % 100
    if hundreds:
        parts.append(_HUNDREDS[hundreds])
    if rem:
        if rem < 30:
            parts.append(_UNITS[rem])
        else:
            tens = rem // 10
            ones = rem % 10
            if ones:
                parts.append(f"{_TENS[tens]} Y {_UNITS[ones]}")
            else:
                parts.append(_TENS[tens])
    return " ".join(parts)


def integer_to_spanish_words(n):
    """Convert a non-negative integer into uppercase Spanish words."""
    n = int(n)
    if n == 0:
        return "CERO"
    if n < 0:
        return f"MENOS {integer_to_spanish_words(abs(n))}"

    parts = []
    millions = n // 1_000_000
    rem = n % 1_000_000
    thousands = rem // 1_000
    units = rem % 1_000

    if millions:
        if millions == 1:
            parts.append("UN MILLON")
        else:
            parts.append(f"{integer_to_spanish_words(millions)} MILLONES")

    if thousands:
        if thousands == 1:
            parts.append("MIL")
        else:
            parts.append(f"{_group_to_words(thousands)} MIL")
    elif millions and not units:
        parts.append("DE")

    if units:
        parts.append(_group_to_words(units))

    return " ".join(part for part in parts if part).strip()


def format_lempiras_in_words(amount):
    """Format an exact HNL amount in Honduran SAR uppercase wording without whole-unit rounding."""
    dec_val = Decimal(str(flt(amount, 2))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if dec_val < 0:
        dec_val = abs(dec_val)
    whole = int(dec_val)
    cents = int((dec_val - Decimal(whole)) * 100)

    words = integer_to_spanish_words(whole)
    currency_label = "LEMPIRA" if whole == 1 else "LEMPIRAS"
    if cents == 0:
        exact_label = "EXACTO" if whole == 1 else "EXACTOS"
        return f"**{words} {currency_label} {exact_label}**"
    return f"**{words} {currency_label} CON {cents:02d}/100**"


def _format_address_lines(addr_doc):
    """Return clean address display lines for a Frappe Address document."""
    if not addr_doc:
        return []
    lines = []
    for raw in (addr_doc.get("address_line1"), addr_doc.get("address_line2")):
        txt = cstr(raw or "").strip()
        if txt:
            lines.append(txt.upper())

    loc_parts = []
    city = cstr(addr_doc.get("city") or "").strip()
    state = cstr(addr_doc.get("state") or "").strip()
    if city:
        loc_parts.append(f"MUNICIPIO: {city.upper()}")
    if state:
        loc_parts.append(f"DEPARTAMENTO: {state.upper()}")
    if loc_parts:
        lines.append(", ".join(loc_parts))
    return lines


def _get_company_addresses(company_name):
    """Fetch Address records linked to the Company, prioritizing primary address first."""
    if not company_name:
        return []
    links = frappe.get_all(
        "Dynamic Link",
        filters={
            "link_doctype": "Company",
            "link_name": company_name,
            "parenttype": "Address",
        },
        pluck="parent",
    )
    if not links:
        return []
    return frappe.get_all(
        "Address",
        filters={"name": ["in", list(dict.fromkeys(links))], "disabled": 0},
        fields=[
            "name",
            "address_title",
            "address_type",
            "address_line1",
            "address_line2",
            "city",
            "county",
            "state",
            "phone",
            "email_id",
            "is_primary_address",
            "is_your_company_address",
        ],
        order_by="is_primary_address desc, creation asc",
    )


def _split_authorized_range(raw_range):
    """Split an authorized SAR range string into (from_number, to_number)."""
    txt = cstr(raw_range or "").strip()
    if not txt:
        return "", ""
    for sep in (" al ", " AL ", " a ", " A ", " / ", " ... ", "..."):
        if sep in txt:
            parts = [p.strip() for p in txt.split(sep, 1)]
            return parts[0], parts[1]
    match = re.match(
        r"(\d{3}-\d{3}-\d{2}-\d{6,10})\s*[-–]\s*(\d{3}-\d{3}-\d{2}-\d{6,10})",
        txt,
    )
    if match:
        return match.group(1), match.group(2)
    return txt, ""


def _parse_posa_notes(notes):
    """Extract legacy order_number, table_label, and waiter_name from posa_notes."""
    res = {"order_number": "", "table_label": "", "waiter_name": ""}
    txt = cstr(notes or "").strip()
    if not txt:
        return res
    for chunk in txt.split("|"):
        part = chunk.strip()
        lower = part.lower()
        if lower.startswith("orden:"):
            res["order_number"] = part.split(":", 1)[1].strip()
        elif lower.startswith("mesa:"):
            val = part.split(":", 1)[1].strip()
            if val and val.upper() != "N/A":
                res["table_label"] = val
        elif lower.startswith("mesero:"):
            val = part.split(":", 1)[1].strip()
            if val and val.upper() != "N/A":
                res["waiter_name"] = val
    return res


def _format_service_badge(service_type):
    """Map Restaurant Order service_type to SAR receipt uppercase service badge."""
    st = cstr(service_type or "").strip().lower()
    if not st:
        return ""
    if "llevar" in st or "pickup" in st or "takeout" in st:
        return "** LLEVAR **"
    if "domicilio" in st or "delivery" in st or "entrega" in st:
        return "** DOMICILIO **"
    if "comer" in st or "mesa" in st or "local" in st or "dine" in st:
        return "** COMER EN LOCAL **"
    return f"** {st.upper()} **"


def get_sar_ticket_context(doc):
    """Build normalized Honduras SAR thermal ticket context for a Sales Invoice document."""
    if isinstance(doc, str):
        doc = frappe.get_doc("Sales Invoice", doc)

    company_doc = frappe.get_doc("Company", doc.company) if doc.company and frappe.db.exists("Company", doc.company) else None
    company_legal_name = cstr((company_doc.company_name if company_doc else None) or doc.company or "EMPRESA").strip()
    company_rtn = cstr(doc.get("company_tax_id") or (company_doc.tax_id if company_doc else "") or "").strip()

    pos_profile_doc = None
    if doc.get("pos_profile") and frappe.db.exists("POS Profile", doc.pos_profile):
        pos_profile_doc = frappe.get_doc("POS Profile", doc.pos_profile)

    company_addresses = _get_company_addresses(doc.company)
    branch_addr_name = cstr(
        doc.get("company_address")
        or (pos_profile_doc.company_address if pos_profile_doc else "")
        or ""
    ).strip()

    branch_addr = None
    if branch_addr_name:
        branch_addr = next((a for a in company_addresses if a.name == branch_addr_name), None)
        if not branch_addr and frappe.db.exists("Address", branch_addr_name):
            branch_addr = frappe.get_doc("Address", branch_addr_name)

    primary_addr = next((a for a in company_addresses if a.get("is_primary_address")), None)
    if not primary_addr and company_addresses:
        primary_addr = company_addresses[0]
    if not branch_addr:
        branch_addr = primary_addr

    commercial_name = ""
    if branch_addr and cstr(branch_addr.get("address_title") or "").strip():
        cand = cstr(branch_addr.get("address_title")).strip()
        if cand.lower() != company_legal_name.lower():
            commercial_name = cand

    branch_lines = _format_address_lines(branch_addr)
    casa_matriz_addr = primary_addr if primary_addr else branch_addr
    casa_matriz_lines = _format_address_lines(casa_matriz_addr)

    company_phone = cstr(
        (branch_addr.get("phone") if branch_addr else "")
        or (casa_matriz_addr.get("phone") if casa_matriz_addr else "")
        or (company_doc.phone_no if company_doc else "")
        or ""
    ).strip()
    company_email = cstr(
        (branch_addr.get("email_id") if branch_addr else "")
        or (casa_matriz_addr.get("email_id") if casa_matriz_addr else "")
        or (company_doc.email if company_doc else "")
        or ""
    ).strip()

    posting_date_fmt = formatdate(doc.posting_date, "dd/MM/yyyy") if doc.posting_date else ""
    raw_time = cstr(doc.get("posting_time") or "").split(".")[0].strip()
    if raw_time and len(raw_time.split(":")) >= 2:
        parts = raw_time.split(":")
        posting_time_fmt = f"{int(parts[0]):02d}:{int(parts[1]):02d}:{int(parts[2]) if len(parts) > 2 else 0:02d}"
    else:
        posting_time_fmt = ""

    due_cai_raw = doc.get("due_date_cai")
    due_date_cai_fmt = formatdate(due_cai_raw, "dd/MM/yyyy") if due_cai_raw else ""

    auth_from, auth_to = _split_authorized_range(doc.get("authorized_range"))

    is_exonerated = cstr(doc.get("tax_category") or "").strip() == "Exonerado"
    oc_exenta = cstr(doc.get("custom_orden_compra_exenta") or "").strip() if is_exonerated else ""
    cr_exonerado = cstr(doc.get("custom_constancia_exonerado") or "").strip() if is_exonerated else ""
    reg_sag = cstr(doc.get("custom_registro_sag") or "").strip() if is_exonerated else ""

    legacy = _parse_posa_notes(doc.get("posa_notes"))
    order_number = cstr(doc.get("restaurant_order_number") or legacy["order_number"] or "").strip()
    table_label = cstr(doc.get("restaurant_table_label") or legacy["table_label"] or "").strip()
    service_type = cstr(doc.get("restaurant_service_type") or "").strip()

    if (not order_number or not service_type) and frappe.db.exists("DocType", "Restaurant Order"):
        linked_ord = frappe.db.get_value(
            "Restaurant Order",
            {"sales_invoice": doc.name},
            ["order_name", "table_label", "service_type"],
            as_dict=True,
        )
        if linked_ord:
            order_number = order_number or cstr(linked_ord.get("order_name") or "").strip()
            table_label = table_label or cstr(linked_ord.get("table_label") or "").strip()
            service_type = service_type or cstr(linked_ord.get("service_type") or "").strip()

    items = []
    for row in (doc.get("items") or []):
        sublines = []
        raw_desc = cstr(row.get("description") or "").strip()
        if " | " in raw_desc:
            segments = [s.strip() for s in raw_desc.split("|") if s.strip()]
            for seg in segments[1:]:
                clean_seg = re.sub(r"^(Opciones|Nota)\s*:\s*", "", seg, flags=re.IGNORECASE).strip()
                if clean_seg:
                    for piece in clean_seg.split(","):
                        p = piece.strip()
                        if p:
                            sublines.append(p.upper())
        qty_val = flt(row.get("qty"))
        qty_display = str(int(qty_val)) if qty_val == int(qty_val) else f"{qty_val:g}"
        items.append({
            "qty_display": qty_display,
            "item_name": cstr(row.get("item_name") or row.get("item_code") or "").strip().upper(),
            "rate": flt(row.get("rate"), 2),
            "amount": flt(row.get("amount"), 2),
            "sublines": sublines,
        })

    tip_amount = 0.0
    for tax_row in (doc.get("taxes") or []):
        desc = cstr(tax_row.get("description") or "").lower()
        if "propina" in desc or "servicio" in desc:
            tip_amount += flt(tax_row.get("tax_amount"), 2)

    customer_name = cstr(doc.get("customer_name") or doc.get("customer") or "CONSUMIDOR FINAL").strip()
    customer_rtn = cstr(doc.get("tax_id") or "").strip()

    payments = []
    total_paid_rows = 0.0
    for prow in (doc.get("payments") or []):
        amt = flt(prow.get("amount"), 2)
        total_paid_rows += amt
        payments.append({
            "mode_of_payment": cstr(prow.get("mode_of_payment") or "").upper(),
            "amount": amt,
        })
    paid_amount = flt(doc.get("paid_amount") or total_paid_rows or doc.get("grand_total"), 2)
    change_amount = flt(doc.get("change_amount"), 2)

    return {
        "company_legal_name": company_legal_name.upper(),
        "commercial_name": commercial_name.upper(),
        "branch_lines": branch_lines,
        "casa_matriz_lines": casa_matriz_lines,
        "company_phone": company_phone,
        "company_email": company_email,
        "company_rtn": company_rtn,
        "invoice_no": cstr(doc.name or ""),
        "posting_date_fmt": posting_date_fmt,
        "posting_time_fmt": posting_time_fmt,
        "cai": cstr(doc.get("cai") or ""),
        "customer_name": customer_name.upper(),
        "customer_rtn": customer_rtn,
        "oc_exenta": oc_exenta,
        "cr_exonerado": cr_exonerado,
        "reg_sag": reg_sag,
        "order_number": order_number,
        "table_label": table_label.upper() if table_label and table_label.upper() != "N/A" else "",
        "service_badge": _format_service_badge(service_type),
        "items": items,
        "discount_amount": flt(doc.get("discount_amount"), 2),
        "exempt_amount": flt(doc.get("exempt_amount"), 2),
        "exonerated_amount": flt(doc.get("exonerated_amount"), 2),
        "taxed_amount_15": flt(doc.get("taxed_amount_15"), 2),
        "taxed_amount_18": flt(doc.get("taxed_amount_18"), 2),
        "isv_15": flt(doc.get("isv_15"), 2),
        "isv_18": flt(doc.get("isv_18"), 2),
        "tip_amount": flt(tip_amount, 2),
        "grand_total": flt(doc.get("grand_total"), 2),
        "paid_amount": paid_amount,
        "change_amount": change_amount,
        "payments": payments,
        "amount_in_words": format_lempiras_in_words(doc.get("grand_total")),
        "authorized_range_from": auth_from,
        "authorized_range_to": auth_to,
        "due_date_cai_fmt": due_date_cai_fmt,
    }
