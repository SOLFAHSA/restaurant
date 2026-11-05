"""Kitchen destination configuration backed by native Frappe documents."""

import frappe
from frappe import _
from frappe.utils import cint, cstr

from restaurant.location import _check_readable_link, _whole_number

DOCTYPE = "Restaurant Command"


def _require_permission(permission):
    if not frappe.has_permission(DOCTYPE, permission):
        frappe.throw(_("No tienes permiso para administrar comandas."), frappe.PermissionError)


@frappe.whitelist()
def get_commands(search="", start=0, page_length=20):
    """List destinations with native user permissions and bounded pagination."""
    _require_permission("read")
    if not isinstance(search, str) or len(search) > 140:
        frappe.throw(_("La búsqueda debe ser un texto de hasta 140 caracteres."))
    offset = _whole_number(start, _("Inicio de página"), 0)
    size = _whole_number(page_length, _("Tamaño de página"), 1)
    if size > 50:
        frappe.throw(_("El tamaño de página no puede superar 50 comandas."))
    pattern = "%" + search.strip() + "%"
    rows = frappe.get_list(
        DOCTYPE, fields=["name", "command_name", "branch", "enabled"],
        or_filters={field: ["like", pattern] for field in ("command_name", "branch")} if search.strip() else None,
        order_by="command_name asc, name asc", limit_start=offset, limit_page_length=size + 1,
    )
    items = []
    for row in rows[:size]:
        doc = frappe.get_doc(DOCTYPE, row.name)
        doc.check_permission("read")
        doc.apply_fieldlevel_read_permissions()
        items.append({
            **row, "groups": [entry.item_group for entry in doc.get("groups", [])],
            "can_write": bool(doc.has_permission("write")),
        })
    return {
        "items": items, "has_next": len(rows) > size, "start": offset,
        "can_create": bool(frappe.has_permission(DOCTYPE, "create")),
        "can_view_formats": bool(frappe.has_permission("Print Format", "read")),
    }


@frappe.whitelist()
def get_editor_context(name=None):
    """Expose the saved selection and every readable native item group."""
    if name:
        doc = frappe.get_doc(DOCTYPE, name)
        doc.check_permission("read")
        doc.apply_fieldlevel_read_permissions()
    else:
        _require_permission("create")
        doc = frappe.new_doc(DOCTYPE)
    groups = frappe.get_list(
        "Item Group", fields=["name", "parent_item_group", "is_group"],
        order_by="lft asc", limit_page_length=0,
    )
    return {
        "doc": doc.as_dict(), "groups": groups,
        "can_write": bool(doc.has_permission("write")) if name else True,
    }


@frappe.whitelist(methods=["POST"])
def save_command(document):
    """Accept editable fields only; preserve permission and timestamp checks."""
    if isinstance(document, str):
        document = frappe.parse_json(document)
    if not isinstance(document, dict) or document.get("doctype") not in (None, DOCTYPE):
        frappe.throw(_("Los datos de la comanda no son válidos."))
    name = document.get("name")
    if name:
        doc = frappe.get_doc(DOCTYPE, name)
        doc.check_permission("write")
        if not document.get("modified"):
            frappe.throw(_("Recarga la comanda antes de guardar los cambios."))
        doc.modified = document["modified"]
    else:
        _require_permission("create")
        doc = frappe.new_doc(DOCTYPE)
    for fieldname in ("command_name", "branch", "enabled"):
        if fieldname in document:
            doc.set(fieldname, document[fieldname])
    groups = document.get("groups")
    if not isinstance(groups, list) or any(
        not isinstance(row, dict) or not isinstance(row.get("item_group"), str) for row in groups
    ):
        frappe.throw(_("Selecciona los grupos de la comanda."))
    doc.set("groups", [{"item_group": row["item_group"]} for row in groups])
    doc.save()
    doc.apply_fieldlevel_read_permissions()
    return doc.as_dict()


def validate_command(doc):
    """Apply the same business rules to modal, native form, API and imports."""
    doc.command_name = cstr(doc.command_name).strip()
    if not doc.command_name or len(doc.command_name) > 140:
        frappe.throw(_("Ingresa un nombre de comanda de hasta 140 caracteres."))
    if not doc.branch:
        frappe.throw(_("Selecciona la sucursal de la comanda."))
    _check_readable_link("Branch", doc.branch)
    if doc.enabled not in (0, 1, "0", "1", False, True):
        frappe.throw(_("El estado de la comanda no es válido."))
    doc.enabled = cint(doc.enabled)
    if not doc.get("groups"):
        frappe.throw(_("Selecciona al menos un grupo para la comanda."))
    selected = set()
    for row in doc.groups:
        if not row.item_group or row.item_group in selected:
            frappe.throw(_("Selecciona grupos válidos sin repetirlos dentro de la comanda."))
        _check_selectable_group(row.item_group)
        selected.add(row.item_group)
    # Serialize duplicate-name checks while allowing groups at multiple destinations.
    frappe.db.get_value("Branch", doc.branch, "name", for_update=True)
    duplicates = frappe.db.sql(
        """select name from `tabRestaurant Command`
        where branch = %s and command_name = %s and name != %s for update""",
        (doc.branch, doc.command_name, doc.name or ""),
    )
    if duplicates:
        frappe.throw(_("Ya existe una comanda con ese nombre en la sucursal."))


def _check_selectable_group(name):
    group = frappe.get_doc("Item Group", name)
    allowed = group.has_permission("read") or group.has_permission("select")
    if not allowed or not frappe.permissions.has_user_permission(group):
        frappe.throw(_("No tienes permiso para seleccionar ese grupo."), frappe.PermissionError)
