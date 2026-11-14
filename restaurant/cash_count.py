"""Cash audit (Arqueo de Caja) orchestration integrated with POS Awesome shifts."""

import frappe
from frappe import _
from frappe.utils import cint, cstr, flt, now_datetime

from restaurant.pos import (
    _get_active_opening_shift,
    _require_pos_user,
    close_pos_shift,
    create_cash_movement,
    get_shift_cash_movements,
)


DEFAULT_HNL_DENOMINATIONS = (
    ("Billete", 500.0, "Billetes L 500"),
    ("Billete", 200.0, "Billetes L 200"),
    ("Billete", 100.0, "Billetes L 100"),
    ("Billete", 50.0, "Billetes L 50"),
    ("Billete", 20.0, "Billetes L 20"),
    ("Billete", 10.0, "Billetes L 10"),
    ("Billete", 5.0, "Billetes L 5"),
    ("Billete", 2.0, "Billetes L 2"),
    ("Billete", 1.0, "Billetes L 1"),
)

PRINT_FORMAT_TICKET = "Arqueo de Caja - Ticket 80mm"
PRINT_FORMAT_LETTER = "Arqueo de Caja - Carta"

_ACCENT_MAP = str.maketrans("áéíóúüÁÉÍÓÚÜ", "aeiouuAEIOUU")
_DETAIL_KIND_LABELS = {
    "card": "Tarjeta",
    "transfer": "Transferencia",
    "other": "Otro",
}


def _normalize_label(value):
    """Lowercase and strip Spanish diacritics for resilient payment-method matching."""
    return cstr(value or "").strip().translate(_ACCENT_MAP).lower()


def _classify_payment_method(mode_of_payment, mop_type=None, cash_mop=None):
    """Classify a Mode of Payment into 'cash', 'card', 'transfer', or 'other'."""
    norm = _normalize_label(mode_of_payment)
    if (cash_mop and mode_of_payment == cash_mop) or mop_type == "Cash":
        return "cash"
    if any(tok in norm for tok in ("efectivo", "cash")):
        return "cash"
    if any(tok in norm for tok in ("tarjeta", "card", "credito", "debito", "visa", "mastercard", "pos")):
        return "card"
    if any(tok in norm for tok in ("transfer", "ach", "spei", "deposito", "sinpe")):
        return "transfer"
    return "other"


def _get_system_enabled_payment_methods():
    """Return active Mode of Payment records configured in the ERPNext site."""
    return frappe.get_all(
        "Mode of Payment",
        filters={"enabled": 1},
        fields=["name", "type"],
        order_by="name asc",
    )


def _get_active_banks():
    """Return bank names registered in ERPNext Bank master if available."""
    if not frappe.db.exists("DocType", "Bank"):
        return []
    return frappe.get_all("Bank", pluck="bank_name", order_by="bank_name asc") or []


def _resolve_cash_mode_of_payment(pos_profile, method_names=None):
    """Determine which Mode of Payment represents physical cash for a POS Profile."""
    configured = (
        frappe.db.get_value("POS Profile", pos_profile, "posa_cash_mode_of_payment")
        if frappe.get_meta("POS Profile").has_field("posa_cash_mode_of_payment")
        else None
    )
    candidates = [cstr(configured).strip(), "Efectivo", "Cash"]
    available = list(method_names or [])
    for candidate in candidates:
        if candidate and candidate in available:
            return candidate
    for name in available:
        lower = name.lower()
        if "efectivo" in lower or "cash" in lower:
            return name
    return cstr(configured).strip() or (available[0] if available else "Efectivo")


def _get_default_denominations(currency="HNL"):
    """Return enabled cash denominations from Restaurant Cash Denomination, with Honduras HNL fallback."""
    if frappe.db.exists("DocType", "Restaurant Cash Denomination"):
        rows = frappe.get_all(
            "Restaurant Cash Denomination",
            filters={"enabled": 1, "currency": currency or "HNL"},
            fields=["denomination_type", "unit_value", "denomination_label"],
            order_by="sort_order asc, unit_value desc",
        )
        if not rows and currency:
            rows = frappe.get_all(
                "Restaurant Cash Denomination",
                filters={"enabled": 1},
                fields=["denomination_type", "unit_value", "denomination_label"],
                order_by="sort_order asc, unit_value desc",
            )
        if rows:
            return [
                {
                    "denomination_type": row.denomination_type or "Billete",
                    "unit_value": flt(row.unit_value, 2),
                    "denomination_label": row.denomination_label,
                    "quantity": 0,
                    "subtotal": 0.0,
                }
                for row in rows
            ]

    return [
        {
            "denomination_type": dtype,
            "unit_value": flt(unit_val, 2),
            "denomination_label": label,
            "quantity": 0,
            "subtotal": 0.0,
        }
        for dtype, unit_val, label in DEFAULT_HNL_DENOMINATIONS
    ]


def _get_profile_payment_methods(pos_profile):
    """Return ordered Mode of Payment names configured on a POS Profile."""
    rows = frappe.get_all(
        "POS Payment Method",
        filters={"parent": pos_profile, "parenttype": "POS Profile"},
        fields=["mode_of_payment"],
        order_by="idx asc",
    )
    return [row.mode_of_payment for row in rows if row.mode_of_payment]


def _compute_fallback_shift_reconciliation(opening_doc, cash_movements):
    """Fallback reconciliation when POS Closing Shift DocType is unavailable."""
    invoices = frappe.get_all(
        "Sales Invoice",
        filters={"posa_pos_opening_shift": opening_doc.name, "docstatus": 1},
        fields=["name", "grand_total", "change_amount"],
    )
    invoice_names = [inv.name for inv in invoices]
    paid_by_mop = {}
    if invoice_names:
        payment_rows = frappe.get_all(
            "Sales Invoice Payment",
            filters={"parent": ["in", invoice_names], "parenttype": "Sales Invoice"},
            fields=["parent", "mode_of_payment", "amount"],
        )
        change_by_inv = {inv.name: flt(inv.change_amount, 2) for inv in invoices}
        for prow in payment_rows:
            amt = flt(prow.amount, 2)
            if "efectivo" in prow.mode_of_payment.lower() or "cash" in prow.mode_of_payment.lower():
                amt -= flt(change_by_inv.get(prow.parent, 0.0), 2)
                change_by_inv[prow.parent] = 0.0
            paid_by_mop[prow.mode_of_payment] = flt(
                paid_by_mop.get(prow.mode_of_payment, 0.0) + amt, 2
            )

    rows = []
    seen = set()
    for detail in (opening_doc.balance_details or []):
        mop = detail.mode_of_payment
        seen.add(mop)
        opening_amt = flt(detail.amount, 2)
        sales_amt = flt(paid_by_mop.get(mop, 0.0), 2)
        rows.append({
            "mode_of_payment": mop,
            "opening_amount": opening_amt,
            "expected_amount": flt(opening_amt + sales_amt, 2),
        })

    for mop, sales_amt in paid_by_mop.items():
        if mop not in seen:
            rows.append({
                "mode_of_payment": mop,
                "opening_amount": 0.0,
                "expected_amount": flt(sales_amt, 2),
            })

    cash_mop = _resolve_cash_mode_of_payment(opening_doc.pos_profile, [r["mode_of_payment"] for r in rows])
    for row in rows:
        if row["mode_of_payment"] == cash_mop:
            row["expected_amount"] = flt(
                row["expected_amount"] + flt(cash_movements.get("net_cash_movement"), 2), 2
            )
            break

    return {
        "invoice_count": len(invoices),
        "total_sales": flt(sum(flt(inv.grand_total, 2) for inv in invoices), 2),
        "rows": rows,
    }


def build_cash_count_snapshot(pos_opening_shift=None):
    """Build a server-verified snapshot of shift totals, payment methods, and cash movements."""
    if not pos_opening_shift:
        active = _get_active_opening_shift(frappe.session.user)
        pos_opening_shift = active["name"] if active else None

    if not pos_opening_shift or not frappe.db.exists("POS Opening Shift", pos_opening_shift):
        frappe.throw(_("No se encontró un turno de Punto de Venta activo para realizar el arqueo."))

    opening_doc = frappe.get_doc("POS Opening Shift", pos_opening_shift)
    cash_movements = get_shift_cash_movements(opening_doc.name)
    total_income = flt(cash_movements.get("total_ingreso"), 2)
    total_expense = flt(cash_movements.get("total_retiro"), 2)
    net_cash_movement = flt(cash_movements.get("net_cash_movement"), 2)

    prof_doc = frappe.get_cached_doc("POS Profile", opening_doc.pos_profile)
    currency = (
        getattr(prof_doc, "currency", None)
        or frappe.get_cached_value("Company", opening_doc.company, "default_currency")
        or "HNL"
    )
    hide_expected_amount = cint(getattr(prof_doc, "hide_expected_amount", 0))

    if frappe.db.exists("DocType", "POS Closing Shift"):
        from posawesome.posawesome.doctype.pos_closing_shift.pos_closing_shift import (
            make_closing_shift_from_opening,
        )

        closing_doc = make_closing_shift_from_opening(frappe.as_json(opening_doc.as_dict()))
        invoice_count = len(closing_doc.pos_transactions or [])
        total_sales = flt(closing_doc.grand_total, 2)
        reconciliation_rows = [
            {
                "mode_of_payment": row.mode_of_payment,
                "opening_amount": flt(row.opening_amount, 2),
                "expected_amount": flt(row.expected_amount, 2),
            }
            for row in (closing_doc.payment_reconciliation or [])
        ]
    else:
        fallback = _compute_fallback_shift_reconciliation(opening_doc, cash_movements)
        invoice_count = fallback["invoice_count"]
        total_sales = fallback["total_sales"]
        reconciliation_rows = fallback["rows"]

    profile_methods = _get_profile_payment_methods(opening_doc.pos_profile)
    system_methods = _get_system_enabled_payment_methods()
    mop_type_map = {m["name"]: m.get("type") for m in system_methods}

    by_mop = {row["mode_of_payment"]: row for row in reconciliation_rows}
    combined_mops = []
    for mop in profile_methods:
        if mop and mop not in combined_mops:
            combined_mops.append(mop)
    for row in reconciliation_rows:
        mop = row.get("mode_of_payment")
        if mop and mop not in combined_mops:
            combined_mops.append(mop)
    for sys_m in system_methods:
        mop = sys_m.get("name")
        if mop and mop not in combined_mops:
            combined_mops.append(mop)
    if not combined_mops:
        combined_mops = ["Efectivo"]

    cash_mop = _resolve_cash_mode_of_payment(opening_doc.pos_profile, combined_mops)
    kind_order = {"cash": 0, "card": 1, "transfer": 2, "other": 3}
    ordered_mops = sorted(
        combined_mops,
        key=lambda mop: kind_order.get(
            _classify_payment_method(mop, mop_type=mop_type_map.get(mop), cash_mop=cash_mop),
            3,
        ),
    )

    payment_methods = []
    for mop in ordered_mops:
        base = by_mop.get(mop, {"opening_amount": 0.0, "expected_amount": 0.0})
        opening_amt = flt(base["opening_amount"], 2)
        expected_amt = flt(base["expected_amount"], 2)
        is_cash = mop == cash_mop
        detail_kind = _classify_payment_method(mop, mop_type=mop_type_map.get(mop), cash_mop=cash_mop)
        income_amt = total_income if is_cash else 0.0
        expense_amt = total_expense if is_cash else 0.0
        # For cash, make_closing_shift_from_opening already adds income and subtracts withdrawals
        # when the mode matches "Efectivo". Keep sales_amount consistent with expected_amount.
        sales_amt = flt(expected_amt - opening_amt - income_amt + expense_amt, 2)
        payment_methods.append({
            "mode_of_payment": mop,
            "is_cash": cint(is_cash),
            "method_type": mop_type_map.get(mop) or ("Cash" if is_cash else "Bank"),
            "detail_kind": detail_kind,
            "opening_amount": opening_amt,
            "sales_amount": sales_amt,
            "income_amount": income_amt,
            "expense_amount": expense_amt,
            "expected_amount": expected_amt,
            "counted_amount": 0.0,
            "difference": flt(-expected_amt, 2),
            "reference_note": "",
        })

    recent_counts = []
    if frappe.db.exists("DocType", "Restaurant Cash Count"):
        recent_counts = frappe.get_all(
            "Restaurant Cash Count",
            filters={"pos_opening_shift": opening_doc.name, "docstatus": 1},
            fields=[
                "name", "count_type", "status", "posting_date",
                "total_expected", "total_counted", "total_difference", "pos_closing_shift",
            ],
            order_by="creation desc",
            limit=10,
        )

    return {
        "pos_opening_shift": opening_doc.name,
        "shift_status": opening_doc.status,
        "pos_profile": opening_doc.pos_profile,
        "company": opening_doc.company,
        "currency": currency,
        "hide_expected_amount": hide_expected_amount,
        "cash_mode_of_payment": cash_mop,
        "cashier": opening_doc.user,
        "cashier_name": frappe.utils.get_fullname(opening_doc.user),
        "period_start_date": str(opening_doc.period_start_date),
        "invoice_count": invoice_count,
        "total_sales": total_sales,
        "total_income": total_income,
        "total_expense": total_expense,
        "net_cash_movement": net_cash_movement,
        "total_expected": flt(sum(m["expected_amount"] for m in payment_methods), 2),
        "denominations": _get_default_denominations(),
        "payment_methods": payment_methods,
        "banks": _get_active_banks(),
        "movements": cash_movements.get("movements") or [],
        "recent_counts": recent_counts,
        "print_formats": {
            "ticket": PRINT_FORMAT_TICKET,
            "letter": PRINT_FORMAT_LETTER,
        },
    }


def recalculate_cash_count_doc(doc, use_denomination_cash_total=False):
    """Recalculate all cash denominations, shift expectations, movements, and totals on server."""
    if not doc.pos_opening_shift:
        frappe.throw(_("Debes seleccionar un turno de Punto de Venta abierto."))

    snapshot = build_cash_count_snapshot(doc.pos_opening_shift)
    doc.company = snapshot["company"]
    doc.pos_profile = snapshot["pos_profile"]
    doc.currency = snapshot["currency"]
    doc.cashier = snapshot["cashier"]
    doc.cashier_name = snapshot["cashier_name"]
    if not doc.posting_date:
        doc.posting_date = now_datetime()

    # 1. Recalculate cash denominations strictly on server.
    if not doc.denominations:
        for row in snapshot["denominations"]:
            doc.append("denominations", row)

    bills_total = 0.0
    coins_total = 0.0
    has_nonzero_qty = False
    for row in doc.denominations:
        qty = max(0, cint(row.quantity))
        unit_val = max(0.0, flt(row.unit_value, 2))
        row.quantity = qty
        row.unit_value = unit_val
        row.subtotal = flt(qty * unit_val, 2)
        if qty > 0:
            has_nonzero_qty = True
        if row.denomination_type == "Moneda":
            coins_total += row.subtotal
        else:
            bills_total += row.subtotal

    doc.cash_bills_total = flt(bills_total, 2)
    doc.cash_coins_total = flt(coins_total, 2)
    doc.cash_counted_total = flt(bills_total + coins_total, 2)

    # 2. Validate payment method detail lines (Card POS / Bank transfers / etc.).
    cash_mop = snapshot["cash_mode_of_payment"]
    snap_kind_map = {
        row["mode_of_payment"]: row.get("detail_kind")
        or _classify_payment_method(row["mode_of_payment"], cash_mop=cash_mop)
        for row in snapshot["payment_methods"]
    }
    valid_details = []
    detail_totals = {}
    for row in (getattr(doc, "payment_details", None) or []):
        mop = cstr(getattr(row, "mode_of_payment", "") or "").strip()
        if not mop or mop == cash_mop:
            continue
        amt = max(0.0, flt(getattr(row, "amount", 0), 2))
        pos_term = cstr(getattr(row, "pos_terminal", "") or "").strip()[:100]
        bank = cstr(getattr(row, "bank_name", "") or "").strip()[:100]
        ref = cstr(getattr(row, "reference", "") or "").strip()[:100]
        if amt <= 0 and not pos_term and not bank and not ref:
            continue
        kind_key = snap_kind_map.get(mop) or _classify_payment_method(mop, cash_mop=cash_mop)
        if kind_key == "card":
            bank = ""
        else:
            pos_term = ""
        valid_details.append({
            "mode_of_payment": mop,
            "detail_kind": _DETAIL_KIND_LABELS.get(kind_key, "Otro"),
            "pos_terminal": pos_term,
            "bank_name": bank,
            "reference": ref,
            "amount": amt,
        })
        detail_totals[mop] = flt(detail_totals.get(mop, 0.0) + amt, 2)

    if hasattr(doc, "payment_details"):
        doc.set("payment_details", [])
        for detail in valid_details:
            doc.append("payment_details", detail)

    # 3. Merge user-entered counted amounts with MariaDB expectations and detail sums.
    submitted_by_mop = {}
    for row in (doc.payment_methods or []):
        if row.mode_of_payment:
            submitted_by_mop[row.mode_of_payment] = {
                "counted_amount": max(0.0, flt(row.counted_amount, 2)),
                "reference_note": cstr(row.reference_note or "").strip()[:140],
            }

    doc.set("payment_methods", [])
    total_expected = 0.0
    total_counted = 0.0
    for snap_row in snapshot["payment_methods"]:
        mop = snap_row["mode_of_payment"]
        entered = submitted_by_mop.get(mop, {})
        if mop == cash_mop and (use_denomination_cash_total or has_nonzero_qty):
            counted_amt = doc.cash_counted_total
        elif mop in detail_totals:
            counted_amt = flt(detail_totals[mop], 2)
        else:
            counted_amt = max(0.0, flt(entered.get("counted_amount"), 2))

        expected_amt = flt(snap_row["expected_amount"], 2)
        diff_amt = flt(counted_amt - expected_amt, 2)
        total_expected += expected_amt
        total_counted += counted_amt
        doc.append("payment_methods", {
            "mode_of_payment": mop,
            "opening_amount": flt(snap_row["opening_amount"], 2),
            "sales_amount": flt(snap_row["sales_amount"], 2),
            "income_amount": flt(snap_row["income_amount"], 2),
            "expense_amount": flt(snap_row["expense_amount"], 2),
            "expected_amount": expected_amt,
            "counted_amount": counted_amt,
            "difference": diff_amt,
            "reference_note": entered.get("reference_note") or "",
        })

    # 3. Sync official shift cash movements (Ingresos / Retiros) from MariaDB.
    doc.set("cash_movements", [])
    for mv in (snapshot["movements"] or []):
        doc.append("cash_movements", {
            "cash_movement_ref": mv.get("name"),
            "movement_type": mv.get("type_transaction"),
            "amount": flt(mv.get("amount"), 2),
            "note": cstr(mv.get("note") or "").strip(),
            "posting_time": mv.get("posting_date"),
        })

    doc.total_income = flt(snapshot["total_income"], 2)
    doc.total_expense = flt(snapshot["total_expense"], 2)
    doc.net_cash_movement = flt(snapshot["net_cash_movement"], 2)
    doc.invoice_count = cint(snapshot["invoice_count"])
    doc.total_sales = flt(snapshot["total_sales"], 2)
    doc.total_expected = flt(total_expected, 2)
    doc.total_counted = flt(total_counted, 2)
    doc.total_difference = flt(doc.total_counted - doc.total_expected, 2)

    if abs(doc.total_difference) < 0.01:
        doc.total_difference = 0.0
        doc.status = "Cuadrado"
    elif doc.total_difference > 0:
        doc.status = "Sobrante"
    else:
        doc.status = "Faltante"

    return snapshot


@frappe.whitelist()
def get_cash_count_preview(pos_opening_shift=None):
    """Return live shift expectations, Honduras denominations, and movements for the POS UI."""
    _require_pos_user()
    return build_cash_count_snapshot(pos_opening_shift)


@frappe.whitelist(methods=["POST"])
def register_cash_count_movement(type_transaction, amount, note, pos_opening_shift=None):
    """Create a native Retiro de efectivo movement and return refreshed cash count preview."""
    create_cash_movement(
        type_transaction=type_transaction,
        amount=amount,
        note=note,
        pos_opening_shift=pos_opening_shift,
    )
    return build_cash_count_snapshot(pos_opening_shift)


@frappe.whitelist(methods=["POST"])
def save_and_submit_cash_count(payload):
    """Create, server-validate, submit a Restaurant Cash Count, and optionally close the shift."""
    _require_pos_user()
    if not frappe.has_permission("Restaurant Cash Count", "create"):
        frappe.throw(_("No tienes permisos para registrar arqueos de caja."), frappe.PermissionError)

    data = frappe.parse_json(payload) if isinstance(payload, str) else payload
    if not isinstance(data, dict):
        frappe.throw(_("Los datos del arqueo no tienen un formato válido."))

    pos_opening_shift = cstr(data.get("pos_opening_shift") or "").strip()
    if not pos_opening_shift:
        active = _get_active_opening_shift(frappe.session.user)
        pos_opening_shift = active["name"] if active else ""
    if not pos_opening_shift or not frappe.db.exists("POS Opening Shift", pos_opening_shift):
        frappe.throw(_("No se encontró un turno de caja activo para registrar el arqueo."))

    count_type = cstr(data.get("count_type") or "Arqueo de Cierre").strip()
    if count_type not in ("Arqueo Parcial", "Arqueo de Cierre"):
        frappe.throw(_("El tipo de arqueo debe ser Arqueo Parcial o Arqueo de Cierre."))

    doc = frappe.new_doc("Restaurant Cash Count")
    doc.count_type = count_type
    doc.pos_opening_shift = pos_opening_shift
    doc.posting_date = now_datetime()
    doc.notes = cstr(data.get("notes") or "").strip()
    doc.flags.use_denomination_cash_total = True

    raw_denoms = data.get("denominations") or []
    if isinstance(raw_denoms, list) and raw_denoms:
        for d in raw_denoms:
            if not isinstance(d, dict):
                continue
            doc.append("denominations", {
                "denomination_type": cstr(d.get("denomination_type") or "Billete"),
                "unit_value": max(0.0, flt(d.get("unit_value"), 2)),
                "denomination_label": cstr(d.get("denomination_label") or ""),
                "quantity": max(0, cint(d.get("quantity"))),
            })

    raw_methods = data.get("payment_methods") or []
    if isinstance(raw_methods, list):
        for m in raw_methods:
            if not isinstance(m, dict) or not m.get("mode_of_payment"):
                continue
            doc.append("payment_methods", {
                "mode_of_payment": cstr(m.get("mode_of_payment")),
                "counted_amount": max(0.0, flt(m.get("counted_amount"), 2)),
                "reference_note": cstr(m.get("reference_note") or "").strip()[:140],
            })

    raw_details = data.get("payment_details") or []
    if isinstance(raw_details, list):
        for d in raw_details:
            if not isinstance(d, dict) or not d.get("mode_of_payment"):
                continue
            doc.append("payment_details", {
                "mode_of_payment": cstr(d.get("mode_of_payment")),
                "pos_terminal": cstr(d.get("pos_terminal") or "").strip()[:100],
                "bank_name": cstr(d.get("bank_name") or "").strip()[:100],
                "reference": cstr(d.get("reference") or "").strip()[:100],
                "amount": max(0.0, flt(d.get("amount"), 2)),
            })

    doc.insert()
    doc.submit()
    doc.reload()

    return {
        "cash_count": {
            "name": doc.name,
            "count_type": doc.count_type,
            "status": doc.status,
            "pos_opening_shift": doc.pos_opening_shift,
            "pos_closing_shift": doc.pos_closing_shift or "",
            "cash_counted_total": flt(doc.cash_counted_total, 2),
            "total_expected": flt(doc.total_expected, 2),
            "total_counted": flt(doc.total_counted, 2),
            "total_difference": flt(doc.total_difference, 2),
            "currency": doc.currency,
        },
        "print_formats": {
            "ticket": PRINT_FORMAT_TICKET,
            "letter": PRINT_FORMAT_LETTER,
        },
    }


def close_linked_pos_shift_from_count(doc):
    """Close the active POS Opening Shift using the verified counted amounts of a cash count."""
    closing_amounts = [
        {
            "mode_of_payment": row.mode_of_payment,
            "closing_amount": flt(row.counted_amount, 2),
        }
        for row in (doc.payment_methods or [])
    ]
    return close_pos_shift(doc.pos_opening_shift, closing_amounts=closing_amounts)

