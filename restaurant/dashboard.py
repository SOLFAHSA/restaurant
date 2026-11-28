"""Read-only restaurant dashboard metrics.

Sales come from submitted Sales Invoices (the source of truth, ADR 002);
operational counters come from Restaurant Order and Restaurant Table.
This module never writes business data.
"""

import frappe
from frappe import _
from frappe.utils import add_days, cint, flt, getdate, now_datetime, time_diff_in_seconds

DASHBOARD_ROLES = ("System Manager", "Restaurant Manager")
KITCHEN_STATES = ("En preparación", "Listo")
DELAYED_KITCHEN_MINUTES = 20
LIST_LIMIT = 8
TOP_ITEMS_LIMIT = 5


@frappe.whitelist()
def get_dashboard_data(company=None):
    """Return the metrics shown on the restaurant dashboard for today."""
    frappe.only_for(DASHBOARD_ROLES)
    company = _resolve_company(company)
    today = getdate()
    now = now_datetime()

    yesterday = add_days(today, -1)
    sales_today, invoices_today = _sales_summary(company, today)
    sales_yesterday, _invoices_yesterday = _sales_summary(company, yesterday)
    open_orders = _open_orders(company)
    kitchen_orders = _kitchen_orders(company, now)

    return {
        "company": company,
        "currency": frappe.get_cached_value("Company", company, "default_currency"),
        "date": str(today),
        "tables": _table_occupancy(),
        "open_orders": {
            "count": len(open_orders),
            "amount": sum(flt(row.grand_total) for row in open_orders),
        },
        "kitchen": {
            "count": len(kitchen_orders),
            "delayed": sum(1 for row in kitchen_orders if row["delayed"]),
            "delayed_minutes": DELAYED_KITCHEN_MINUTES,
            "orders": kitchen_orders[:LIST_LIMIT],
        },
        "sales": {
            "today": sales_today,
            "yesterday": sales_yesterday,
            "change_percent": _change_percent(sales_today, sales_yesterday),
            "invoices": invoices_today,
            "average_ticket": flt(sales_today / invoices_today, 2) if invoices_today else 0.0,
            "by_hour": _sales_by_hour(company, today),
            "by_hour_yesterday": _sales_by_hour(company, yesterday),
        },
        "top_items": _top_items(company, today),
        "pending_tables": _pending_tables(open_orders, now),
        "recent_activity": _recent_activity(company, now),
    }


def _resolve_company(company):
    company = company or frappe.defaults.get_user_default("Company")
    if not company:
        frappe.throw(_("Configura una compañía predeterminada para ver el dashboard."))
    if not frappe.db.exists("Company", company):
        frappe.throw(_("La compañía {0} no existe.").format(company))
    if not frappe.has_permission("Company", "read", company):
        frappe.throw(_("No tienes permiso para ver la compañía {0}.").format(company), frappe.PermissionError)
    return company


def _sales_summary(company, date):
    """Total (with ISV) and number of invoices issued that day from restaurant orders."""
    # Only invoices issued from a restaurant order count as restaurant sales.
    result = frappe.db.sql(
        """
        select coalesce(sum(si.grand_total), 0), count(si.name)
        from `tabSales Invoice` si
        inner join `tabRestaurant Order` ro on ro.sales_invoice = si.name
        where si.docstatus = 1 and si.is_return = 0
            and si.company = %(company)s and si.posting_date = %(date)s
        """,
        {"company": company, "date": date},
    )
    return (flt(result[0][0]), cint(result[0][1])) if result else (0.0, 0)


def _top_items(company, date):
    """Best sellers of the day by net amount; zero-priced combo components are left out."""
    rows = frappe.db.sql(
        """
        select sii.item_code, max(sii.item_name) as item_name,
            sum(sii.stock_qty) as qty, sum(sii.base_net_amount) as amount
        from `tabSales Invoice Item` sii
        inner join `tabSales Invoice` si on si.name = sii.parent
        inner join `tabRestaurant Order` ro on ro.sales_invoice = si.name
        where si.docstatus = 1 and si.is_return = 0
            and si.company = %(company)s and si.posting_date = %(date)s
            and sii.base_net_amount > 0
        group by sii.item_code
        order by amount desc
        limit %(limit)s
        """,
        {"company": company, "date": date, "limit": TOP_ITEMS_LIMIT},
        as_dict=True,
    )
    return [
        {"item_code": row.item_code, "item_name": row.item_name or row.item_code,
         "qty": flt(row.qty), "amount": flt(row.amount, 2)}
        for row in rows
    ]


def _sales_by_hour(company, date):
    rows = frappe.db.sql(
        """
        select hour(si.posting_time) as hour, sum(si.grand_total) as total
        from `tabSales Invoice` si
        inner join `tabRestaurant Order` ro on ro.sales_invoice = si.name
        where si.docstatus = 1 and si.is_return = 0
            and si.company = %(company)s and si.posting_date = %(date)s
        group by hour(si.posting_time)
        order by hour
        """,
        {"company": company, "date": date},
        as_dict=True,
    )
    return [{"hour": cint(row.hour), "total": flt(row.total)} for row in rows]


def _change_percent(current, previous):
    if not previous:
        return None
    return round((current - previous) / previous * 100, 1)


def _table_occupancy():
    counts = dict(
        frappe.db.sql(
            """select status, count(*) from `tabRestaurant Table`
            where status != 'Inactiva' group by status"""
        )
    )
    total = sum(counts.values())
    occupied = cint(counts.get("Ocupada"))
    return {
        "total": total,
        "occupied": occupied,
        "available": cint(counts.get("Disponible")),
        "reserved": cint(counts.get("Reservada")),
        "occupied_percent": round(occupied / total * 100) if total else 0,
    }


def _open_orders(company):
    return frappe.get_all(
        "Restaurant Order",
        filters={"company": company, "status": "En curso", "docstatus": ["<", 2]},
        fields=["name", "restaurant_table", "table_label", "guests", "grand_total", "creation"],
        order_by="creation asc",
    )


def _kitchen_orders(company, now):
    orders = frappe.get_all(
        "Restaurant Order",
        filters={"company": company, "status": "En curso", "kds_status": ["in", KITCHEN_STATES]},
        fields=[
            "name", "service_type", "table_label", "customer_name",
            "kds_status", "sent_to_kitchen_at", "creation",
        ],
        order_by="sent_to_kitchen_at asc",
    )
    if not orders:
        return []

    item_counts = dict(
        frappe.db.sql(
            """select parent, sum(qty - coalesce(cancelled_qty, 0))
            from `tabRestaurant Order Item`
            where parenttype = 'Restaurant Order' and parent in %(names)s and is_cancelled = 0
            group by parent""",
            {"names": tuple(row.name for row in orders)},
        )
    )
    result = []
    for row in orders:
        minutes = _minutes_since(row.sent_to_kitchen_at or row.creation, now)
        result.append({
            "name": row.name,
            "service_type": row.service_type,
            "reference": row.table_label or row.customer_name or "",
            "items": flt(item_counts.get(row.name)),
            "minutes": minutes,
            "kds_status": row.kds_status,
            "delayed": row.kds_status == "En preparación" and minutes >= DELAYED_KITCHEN_MINUTES,
        })
    return result


def _pending_tables(open_orders, now):
    rows = [
        {
            "order": row.name,
            "table": row.table_label or row.restaurant_table,
            "guests": cint(row.guests),
            "minutes": _minutes_since(row.creation, now),
            "amount": flt(row.grand_total),
        }
        for row in open_orders
        if row.restaurant_table
    ]
    rows.sort(key=lambda row: row["minutes"], reverse=True)
    return rows[:LIST_LIMIT]


def _recent_activity(company, now):
    rows = frappe.get_all(
        "Restaurant Order",
        filters={"company": company},
        fields=["name", "status", "kds_status", "service_type", "table_label", "customer_name",
                "grand_total", "modified"],
        order_by="modified desc",
        limit_page_length=5,
    )
    return [
        {
            "order": row.name,
            "event": _activity_label(row),
            "kind": _activity_kind(row),
            "reference": row.table_label or row.customer_name or row.service_type or "",
            "amount": flt(row.grand_total),
            "minutes": _minutes_since(row.modified, now),
        }
        for row in rows
    ]


def _activity_kind(row):
    """Short key the dashboard uses to color each activity."""
    if row.status == "Facturada":
        return "closed"
    if row.status == "Cancelada":
        return "cancelled"
    if row.kds_status == "Listo":
        return "ready"
    if row.kds_status == "En preparación":
        return "kitchen"
    return "open"


def _activity_label(row):
    if row.status == "Facturada":
        return _("Cuenta cerrada")
    if row.status == "Cancelada":
        return _("Cuenta cancelada")
    if row.kds_status == "Listo":
        return _("Pedido listo")
    if row.kds_status == "En preparación":
        return _("Pedido en cocina")
    return _("Cuenta abierta")


def _minutes_since(moment, now):
    if not moment:
        return 0
    return max(0, cint(time_diff_in_seconds(now, moment) // 60))
