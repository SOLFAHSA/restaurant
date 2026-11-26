"""Restaurant Order serialization for the POS and live table areas."""

import json

import frappe
from frappe.utils import cint, cstr, flt, get_datetime, get_fullname, now_datetime

from restaurant.pos_auth import (
    employee_has_pin,
    get_linked_employee_for_user,
    is_order_unlocked_for_session,
    is_waiter_only,
)
from restaurant.pos_context import _get_active_user_branch, _get_order_company


def build_order_serialization_context(docs):
    """Prefetch waiter/pin/cashier lookup maps once for a batch of Restaurant Orders."""
    doc_list = [d for d in (docs or []) if d]
    linked_emp = get_linked_employee_for_user()
    waiter_only = is_waiter_only()

    waiter_has_pin = set()
    if waiter_only and not linked_emp:
        waiter_ids = sorted({
            d.waiter for d in doc_list
            if getattr(d, "waiter", None) and getattr(d, "status", None) not in ("Facturada", "Cancelada")
        })
        if waiter_ids:
            try:
                auth_rows = frappe.db.sql(
                    """
                    SELECT DISTINCT name FROM `__Auth`
                    WHERE doctype = 'Employee' AND fieldname = 'restaurant_pos_pin'
                      AND name IN %s
                    """,
                    (tuple(waiter_ids),),
                )
                waiter_has_pin = {r[0] for r in (auth_rows or []) if r and r[0]}
            except Exception:
                waiter_has_pin = {wid for wid in waiter_ids if employee_has_pin(wid)}

    cashier_ids = sorted({d.cashier for d in doc_list if getattr(d, "cashier", None)})
    cashier_names = {}
    if cashier_ids:
        for urow in frappe.get_all("User", filters={"name": ["in", cashier_ids]}, fields=["name", "full_name"]):
            cashier_names[urow.name] = urow.full_name or urow.name

    return {
        "linked_emp": linked_emp,
        "waiter_only": waiter_only,
        "waiter_has_pin": waiter_has_pin,
        "cashier_names": cashier_names,
    }


class _BatchOrderObj:
    """Attribute-safe batch container for Restaurant Order without dict.items() collision."""

    def __init__(self, row, items):
        self.__dict__.update(row)
        self.items = list(items or [])

    def get(self, key, default=None):
        return self.__dict__.get(key, default)


def _load_orders_batch(filters=None, order_by="modified desc", limit_page_length=100, use_list_perms=True):
    """Fetch Restaurant Orders and their child items in exactly 2 batched SQL queries."""
    meta = frappe.get_meta("Restaurant Order")
    candidate_fields = [
        "name", "order_name", "reference_note", "status", "service_type",
        "restaurant_area", "restaurant_table", "table_label", "branch", "guests",
        "waiter", "waiter_name", "customer", "customer_name", "tax_id",
        "pos_profile", "pos_opening_shift", "cashier", "company", "currency",
        "selling_price_list", "kds_status", "sent_to_kitchen_at", "scheduled_time",
        "customer_note", "precuenta_printed", "subtotal", "taxed_amount_15",
        "isv_15", "taxed_amount_18", "isv_18", "exempt_amount", "tax_amount",
        "tip_percentage", "tip_amount", "grand_total", "sales_invoice", "cai",
        "due_date_cai", "creation", "modified", "docstatus",
    ]
    fields = [f for f in candidate_fields if f in ("name", "creation", "modified", "docstatus") or meta.has_field(f)]
    getter = frappe.get_list if use_list_perms else frappe.get_all
    rows = getter(
        "Restaurant Order",
        filters=filters or {},
        fields=fields,
        order_by=order_by,
        limit_page_length=limit_page_length,
    )
    if not rows:
        return []

    order_names = [r.name for r in rows]
    item_meta = frappe.get_meta("Restaurant Order Item")
    item_candidate_fields = [
        "name", "parent", "idx", "item_code", "item_name", "item_group", "qty", "uom",
        "base_rate", "options_rate", "discount_percentage", "rate", "amount", "tax_rate",
        "options_summary", "selected_options_json", "note", "command_station", "kds_status",
        "is_cancelled", "cancelled_qty", "cancellation_reason", "cancelled_by",
        "cancelled_by_supervisor", "cancelled_at",
    ]
    item_fields = [
        f for f in item_candidate_fields
        if f in ("name", "parent", "idx") or item_meta.has_field(f)
    ]
    item_rows = frappe.get_all(
        "Restaurant Order Item",
        filters={"parent": ["in", order_names], "parenttype": "Restaurant Order"},
        fields=item_fields,
        order_by="idx asc",
        limit_page_length=5000,
    )
    items_by_parent = {}
    for irow in item_rows:
        items_by_parent.setdefault(irow.parent, []).append(irow)
    return [_BatchOrderObj(row, items_by_parent.get(row.name, [])) for row in rows]


def _serialize_order(doc, serial_ctx=None):
    if isinstance(doc, str):
        doc = frappe.get_doc("Restaurant Order", doc)
    items = []
    for row in (doc.get("items") if hasattr(doc, "get") else getattr(doc, "items", [])) or []:
        selected_options = []
        if row.selected_options_json:
            try:
                selected_options = json.loads(row.selected_options_json)
            except Exception:
                selected_options = []
        items.append({
            "name": row.name,
            "idx": row.idx,
            "item_code": row.item_code,
            "item_name": row.item_name,
            "item_group": row.item_group,
            "qty": flt(row.qty),
            "uom": row.uom,
            "base_rate": flt(row.base_rate, 2),
            "options_rate": flt(row.options_rate, 2),
            "discount_percentage": flt(row.discount_percentage, 2),
            "rate": flt(row.rate, 2),
            "amount": flt(row.amount, 2),
            "tax_rate": flt(row.tax_rate, 2),
            "options_summary": row.options_summary or "",
            "selected_options": selected_options,
            "note": row.note or "",
            "command_station": row.command_station or "Cocina General",
            "kds_status": row.kds_status or "Pendiente",
            "is_cancelled": cint(getattr(row, "is_cancelled", 0)) or row.kds_status == "Cancelado",
            "cancelled_qty": flt(getattr(row, "cancelled_qty", 0)),
            "cancellation_reason": cstr(getattr(row, "cancellation_reason", "") or ""),
            "cancelled_by": cstr(getattr(row, "cancelled_by", "") or ""),
            "cancelled_by_supervisor": cstr(getattr(row, "cancelled_by_supervisor", "") or ""),
            "cancelled_at": cstr(getattr(row, "cancelled_at", "") or ""),
        })
    now_dt = now_datetime()
    created_dt = get_datetime(doc.creation) if doc.creation else now_dt
    elapsed_mins = max(0, int((now_dt - created_dt).total_seconds() // 60))
    if serial_ctx is not None:
        linked_emp = serial_ctx["linked_emp"]
        waiter_only = serial_ctx["waiter_only"]
        waiter_pin_ok = bool(doc.waiter and doc.waiter in serial_ctx["waiter_has_pin"])
        cashier_name = serial_ctx["cashier_names"].get(doc.cashier, "") if doc.cashier else ""
    else:
        linked_emp = get_linked_employee_for_user()
        waiter_only = is_waiter_only()
        waiter_pin_ok = bool(
            doc.waiter
            and waiter_only
            and not linked_emp
            and doc.status not in ("Facturada", "Cancelada")
            and employee_has_pin(doc.waiter)
        )
        cashier_name = get_fullname(doc.cashier) if doc.cashier else ""

    requires_pin_unlock = bool(
        doc.waiter
        and waiter_only
        and not linked_emp
        and doc.status not in ("Facturada", "Cancelada")
        and waiter_pin_ok
        and not is_order_unlocked_for_session(doc.name)
    )
    return {
        "name": doc.name,
        "order_name": doc.order_name,
        "reference_note": doc.reference_note or "",
        "status": doc.status,
        "service_type": doc.service_type,
        "restaurant_area": doc.restaurant_area or "",
        "restaurant_table": doc.restaurant_table or "",
        "table_label": doc.table_label or "",
        "branch": getattr(doc, "branch", "") or "",
        "guests": cint(doc.guests or 1),
        "waiter": doc.waiter or "",
        "waiter_name": doc.waiter_name or "",
        "customer": doc.customer or "",
        "customer_name": doc.customer_name or doc.customer or "",
        "tax_id": doc.tax_id or "",
        "pos_profile": doc.pos_profile or "",
        "pos_opening_shift": doc.pos_opening_shift or "",
        "cashier": doc.cashier or "",
        "cashier_name": cashier_name,
        "company": doc.company or "",
        "currency": doc.currency or "HNL",
        "selling_price_list": doc.selling_price_list or "",
        "kds_status": doc.kds_status or "Sin enviar",
        "sent_to_kitchen_at": str(doc.sent_to_kitchen_at) if doc.sent_to_kitchen_at else "",
        "scheduled_time": doc.scheduled_time or "",
        "customer_note": doc.customer_note or "",
        "precuenta_printed": cint(doc.precuenta_printed),
        "subtotal": flt(doc.subtotal, 2),
        "taxed_amount_15": flt(doc.taxed_amount_15, 2),
        "isv_15": flt(doc.isv_15, 2),
        "taxed_amount_18": flt(doc.taxed_amount_18, 2),
        "isv_18": flt(doc.isv_18, 2),
        "exempt_amount": flt(doc.exempt_amount, 2),
        "tax_amount": flt(doc.tax_amount, 2),
        "tip_percentage": flt(doc.tip_percentage, 2),
        "tip_amount": flt(doc.tip_amount, 2),
        "grand_total": flt(doc.grand_total, 2),
        "sales_invoice": doc.sales_invoice or "",
        "cai": doc.cai or "",
        "due_date_cai": str(doc.due_date_cai) if doc.due_date_cai else "",
        "creation": str(doc.creation),
        "modified": str(doc.modified),
        "elapsed_minutes": elapsed_mins,
        "elapsed_label": f"{elapsed_mins // 60:02d}:{elapsed_mins % 60:02d}",
        "requires_pin_unlock": requires_pin_unlock,
        "items": items,
    }


def _get_areas_with_live_tables(branch=None, company=None):
    """Return active Restaurant Areas with floor map elements and live table order status."""
    from restaurant.table_management import parse_area_layout

    if not frappe.has_permission("Restaurant Area", "read"):
        return []

    effective_branch = _get_active_user_branch() if branch is None else branch
    area_filters = {"status": "Activa"}
    if effective_branch:
        area_filters["branch"] = effective_branch

    areas = frappe.get_list(
        "Restaurant Area",
        filters=area_filters,
        fields=[
            "name",
            "area_name",
            "branch",
            "capacity",
            "color",
            "icon",
            "floor_background",
            "layout_json",
            "display_order",
        ],
        order_by="display_order asc, area_name asc",
        limit_page_length=200,
    )
    if not areas:
        return []

    open_order_filters = {"status": "En curso", "company": company or _get_order_company()}
    if effective_branch and frappe.get_meta("Restaurant Order").has_field("branch"):
        open_order_filters["branch"] = effective_branch

    open_orders = frappe.get_all(
        "Restaurant Order",
        filters=open_order_filters,
        fields=[
            "name",
            "order_name",
            "restaurant_table",
            "waiter_name",
            "customer_name",
            "grand_total",
            "guests",
            "creation",
        ],
        order_by="creation asc",
    )
    active_by_table = {}
    for order in open_orders:
        if order.restaurant_table and order.restaurant_table not in active_by_table:
            created_dt = get_datetime(order.creation) if order.creation else now_datetime()
            mins = max(0, int((now_datetime() - created_dt).total_seconds() // 60))
            active_by_table[order.restaurant_table] = {
                "order_id": order.name,
                "order_name": order.order_name,
                "waiter_name": order.waiter_name or "",
                "customer_name": order.customer_name or "",
                "grand_total": flt(order.grand_total, 2),
                "guests": cint(order.guests or 1),
                "elapsed_label": f"{mins // 60:02d}:{mins % 60:02d}'",
            }

    tables_by_area = {}
    area_names = [area.name for area in areas]
    if area_names and frappe.has_permission("Restaurant Table", "read"):
        raw_tables = frappe.get_list(
            "Restaurant Table",
            filters={"restaurant_area": ["in", area_names]},
            fields=[
                "name",
                "restaurant_area",
                "branch",
                "table_number",
                "seats",
                "shape",
                "status",
                "display_order",
                "color",
                "notes",
                "modified",
            ],
            order_by="display_order asc, table_number asc",
            limit_page_length=1000,
        )
        for row in raw_tables:
            live = active_by_table.get(row.name)
            tables_by_area.setdefault(row.restaurant_area, []).append({
                "name": row.name,
                "restaurant_area": row.restaurant_area,
                "branch": row.branch,
                "table_number": row.table_number,
                "seats": row.seats,
                "shape": row.shape,
                "status": "Ocupada" if live else (row.status if row.status in ("Inactiva", "Reservada") else "Disponible"),
                "display_order": row.display_order,
                "color": row.color,
                "notes": row.notes,
                "modified": row.modified,
                "active_order": live,
            })

    result = []
    for area in areas:
        result.append({
            "name": area.name,
            "area_name": area.area_name,
            "branch": area.branch,
            "capacity": cint(area.capacity),
            "color": area.color or "#22C55E",
            "icon": area.icon or "utensils",
            "floor_background": area.floor_background or "Madera cálida",
            "elements": parse_area_layout(area.layout_json),
            "tables": tables_by_area.get(area.name, []),
        })
    return result
