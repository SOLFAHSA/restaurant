"""Deterministic demonstration data using native, non-transactional documents."""

from decimal import Decimal
from uuid import uuid4

import frappe
from frappe import _
from frappe.utils import cint

PREFIX = "DEMO-REST"
UNIT = PREFIX + " Unidad"
GROUP = PREFIX + " Menú de demostración"
PRICE_LIST = PREFIX + " Precios HNL"
PRICE_DATE = "2026-01-01"
DOCTYPES = ("UOM", "Item Group", "Price List", "Branch", "Restaurant Area", "Item", "Item Price")
BRANCHES = ("Centro", "Norte", "Sur", "Mirador")
AREAS = (
    ("Salón principal", 48, "Salón", "#3B78FF"),
    ("Terraza", 24, "Terraza", "#22C55E"),
    ("Barra", 12, "Barra", "#F59E0B"),
    ("Salón privado", 16, "Salón", "#8B5CF6"),
    ("Jardín", 32, "Jardín", "#16A34A"),
    ("Salón familiar", 36, "Salón", "#0EA5E9"),
)
PRODUCTS = (
    ("001", "Baleada sencilla", 35),
    ("002", "Baleada especial", 65),
    ("003", "Sopa de pollo", 125),
    ("004", "Pollo a la plancha", 175),
    ("005", "Carne asada", 245),
    ("006", "Filete de pescado", 225),
    ("007", "Ensalada de la casa", 115),
    ("008", "Hamburguesa artesanal", 165),
    ("009", "Flan de la casa", 65),
    ("010", "Limonada natural", 45),
    ("011", "Café americano", 35),
    ("012", "Agua embotellada", 30),
)


def sync_workspace_block():
    """Sync the Restaurant Dashboard Custom HTML Block from fixtures into the database."""
    import json
    path = frappe.get_app_path("restaurant", "fixtures", "custom_html_block.json")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)[0]
    if frappe.db.exists("Custom HTML Block", "Restaurant Dashboard"):
        doc = frappe.get_doc("Custom HTML Block", "Restaurant Dashboard")
        doc.html = data["html"]
        doc.script = data["script"]
        doc.style = data["style"]
        doc.save(ignore_permissions=True)
        frappe.db.commit()
        return "Synced Restaurant Dashboard Custom HTML Block"
    return "Restaurant Dashboard not found"


def seed():
    """Create missing demo records atomically; the caller owns the commit."""
    _check_environment()
    if frappe.db.get_default("item_naming_by") == "Naming Series":
        frappe.throw(_("Los datos semilla requieren nomenclatura de artículos por código; no se cambiará la configuración del sitio."))
    root_group = frappe.db.get_value("Item Group", {"is_group": 1, "parent_item_group": ["is", "not set"]}, "name")
    if not root_group:
        frappe.throw(_("No se encontró el grupo raíz nativo de artículos."))
    if not frappe.db.exists("Currency", "HNL"):
        frappe.throw(_("La moneda HNL debe estar disponible antes de cargar la demostración."))
    summary = {
        "created": {dt: 0 for dt in DOCTYPES},
        "existing": {dt: 0 for dt in DOCTYPES},
        "records": {dt: [] for dt in DOCTYPES},
    }
    savepoint = "restaurant_demo_" + uuid4().hex[:12]
    frappe.db.savepoint(savepoint)
    try:
        _seed_records(root_group, summary)
    except Exception:
        frappe.db.rollback(save_point=savepoint)
        raise
    summary["total_created"] = sum(summary["created"].values())
    summary["total_existing"] = sum(summary["existing"].values())
    return summary


def _check_environment():
    if frappe.local.site != "development" or not cint(frappe.conf.get("developer_mode")):
        frappe.throw(_("Los datos semilla solo pueden ejecutarse en development con modo desarrollador activo."), frappe.PermissionError)
    if frappe.session.user != "Administrator" and "System Manager" not in frappe.get_roles():
        frappe.throw(_("Solo un administrador puede cargar los datos de demostración."), frappe.PermissionError)


def _seed_records(root_group, summary):
    _ensure("UOM", {"name": UNIT}, {"uom_name": UNIT, "must_be_whole_number": 1, "enabled": 1}, summary)
    _ensure("Item Group", {"name": GROUP}, {"item_group_name": GROUP, "parent_item_group": root_group, "is_group": 0}, summary)
    _ensure("Price List", {"name": PRICE_LIST}, {"price_list_name": PRICE_LIST, "currency": "HNL", "selling": 1, "buying": 0, "enabled": 1}, summary)
    for branch_index, branch_label in enumerate(BRANCHES):
        branch_name = PREFIX + " Sucursal " + branch_label
        _ensure("Branch", {"name": branch_name}, {"branch": branch_name}, summary)
        for area_index, (label, capacity, icon, color) in enumerate(AREAS):
            area_name = PREFIX + " " + branch_label + " - " + label
            _ensure("Restaurant Area", {"name": area_name}, {
                "area_name": area_name, "branch": branch_name,
                "display_order": branch_index * len(AREAS) + area_index + 1,
                "capacity": capacity, "status": "Activa", "visible_in_pos": 1,
                "description": "Área ficticia para pruebas de navegación y configuración del restaurante.",
                "icon": icon, "allow_open_accounts": 1, "color": color,
                "notes": "Datos de demostración; no corresponden a un establecimiento real.",
            }, summary)
    for code, label, rate in PRODUCTS:
        item_code = PREFIX + "-" + code
        _ensure("Item", {"name": item_code}, {
            "item_code": item_code, "item_name": label + " (demostración)",
            "item_group": GROUP, "stock_uom": UNIT, "is_stock_item": 0,
            "is_sales_item": 1, "is_purchase_item": 0, "disabled": 0,
            "standard_rate": 0, "opening_stock": 0,
            "description": "Producto ficticio del catálogo de demostración del restaurante.",
        }, summary)
        _ensure("Item Price", {
            "item_code": item_code, "price_list": PRICE_LIST, "uom": UNIT,
            "valid_from": PRICE_DATE,
        }, {
            "item_code": item_code, "price_list": PRICE_LIST, "uom": UNIT,
            "valid_from": PRICE_DATE, "currency": "HNL", "price_list_rate": rate,
            "selling": 1, "buying": 0,
        }, summary)


def _ensure(doctype, identity, values, summary):
    matches = frappe.get_all(doctype, filters=identity, pluck="name", limit_page_length=2)
    if len(matches) > 1:
        frappe.throw(_("Se encontraron registros duplicados de demostración en {0}; no se modificarán.").format(doctype))
    if matches:
        doc = frappe.get_doc(doctype, matches[0])
        doc.check_permission("read")
        if any(not _same_value(doc.get(key), value) for key, value in values.items()):
            frappe.throw(_("El registro {0} de {1} ya existe con datos diferentes; no se sobrescribirá.").format(doc.name, doctype))
        summary["existing"][doctype] += 1
    else:
        doc = frappe.get_doc({"doctype": doctype, **values}).insert()
        summary["created"][doctype] += 1
    summary["records"][doctype].append(doc.name)
    return doc


def _same_value(actual, expected):
    if isinstance(expected, (int, float, Decimal)):
        try:
            return actual is not None and Decimal(str(actual)) == Decimal(str(expected))
        except (ValueError, ArithmeticError):
            return False
    return str(actual or "") == str(expected or "")
