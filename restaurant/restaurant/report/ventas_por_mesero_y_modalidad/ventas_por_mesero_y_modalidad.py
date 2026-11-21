import frappe
from frappe import _
from frappe.utils import getdate


def execute(filters=None):
    filters = frappe._dict(filters or {})
    if not all((filters.company, filters.from_date, filters.to_date)):
        frappe.throw(_("Selecciona una empresa y el rango de fechas."))
    from_date = getdate(filters.from_date)
    to_date = getdate(filters.to_date)
    if from_date > to_date:
        frappe.throw(_("La fecha inicial debe ser anterior o igual a la fecha final."))
    if not frappe.has_permission("Company", "read", doc=filters.company):
        frappe.throw(_("No tienes permiso para consultar esta empresa."), frappe.PermissionError)

    rows = frappe.get_list(
        "Sales Invoice",
        filters={
            "docstatus": 1,
            "is_return": 0,
            "company": filters.company,
            "posting_date": ["between", [from_date, to_date]],
            "restaurant_order": ["is", "set"],
        },
        fields=[
            "restaurant_waiter_name",
            "restaurant_service_type",
            "count(name) as invoice_count",
            "sum(base_net_total) as net_total",
            "sum(base_grand_total) as grand_total",
        ],
        group_by="restaurant_waiter_name, restaurant_service_type",
        order_by="restaurant_waiter_name asc, restaurant_service_type asc",
        limit_page_length=0,
    )
    currency = frappe.get_cached_value("Company", filters.company, "default_currency")
    for row in rows:
        row.restaurant_waiter_name = row.restaurant_waiter_name or _("Sin mesero")
        row.restaurant_service_type = row.restaurant_service_type or _("Sin modalidad")
        row.currency = currency

    columns = [
        {"fieldname": "restaurant_waiter_name", "label": _("Mesero"), "fieldtype": "Data", "width": 180},
        {"fieldname": "restaurant_service_type", "label": _("Modalidad"), "fieldtype": "Data", "width": 160},
        {"fieldname": "invoice_count", "label": _("Facturas"), "fieldtype": "Int", "width": 100},
        {"fieldname": "net_total", "label": _("Total neto"), "fieldtype": "Currency", "options": "currency", "width": 140},
        {"fieldname": "grand_total", "label": _("Total factura"), "fieldtype": "Currency", "options": "currency", "width": 140},
        {"fieldname": "currency", "label": _("Moneda"), "fieldtype": "Link", "options": "Currency", "width": 100},
    ]
    return columns, rows, _("Incluye facturas enviadas de Restaurante, sin notas de crédito. Importes en moneda de la empresa.")
