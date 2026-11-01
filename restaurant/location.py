"""Restaurant area editor using native Frappe document persistence."""

from decimal import Decimal, InvalidOperation
from pathlib import PurePosixPath
import re
from urllib.parse import unquote, urlsplit

import frappe
from frappe import _
from frappe.utils import cstr

DOCTYPE = "Restaurant Area"
AREA_TYPES = ("Área interior", "Área abierta (Terraza)", "Barra", "Área privada")
AREA_STATUSES = ("Activa", "Inactiva")
AREA_ICONS = ("Terraza", "Salón", "Barra", "Jardín")
EDITABLE_FIELDS = (
    "area_name", "branch", "area_type", "display_order", "capacity", "status",
    "visible_in_pos", "description", "image", "icon", "printer", "waiter",
    "allow_open_accounts", "color", "notes",
)


@frappe.whitelist()
def get_editor_context(name=None, for_list=False):
    """Return only documents the current user can read or create."""
    if name:
        doc = frappe.get_doc(DOCTYPE, name)
        doc.check_permission("read")
        doc.apply_fieldlevel_read_permissions()
    else:
        if frappe.utils.cint(for_list):
            if not frappe.has_permission(DOCTYPE, "read"):
                frappe.throw(_("No tienes permiso para consultar ubicaciones del restaurante."), frappe.PermissionError)
        else:
            _require_create_permission()
        doc = frappe.new_doc(DOCTYPE)
    return {
        "doc": doc.as_dict(),
        "can_write": bool(doc.has_permission("write")) if name else False,
        "can_create": bool(frappe.has_permission(DOCTYPE, "create")),
        "kds_available": False,
        "tables_available": False,
    }


@frappe.whitelist()
def get_locations(search="", start=0, page_length=12):
    """Return a bounded page using native role and user permission filters."""
    if not frappe.has_permission(DOCTYPE, "read"):
        frappe.throw(_("No tienes permiso para consultar ubicaciones del restaurante."), frappe.PermissionError)
    if search is None:
        search = ""
    if not isinstance(search, str) or len(search) > 140:
        frappe.throw(_("La búsqueda debe ser un texto de hasta 140 caracteres."))
    search = search.strip()
    offset = _whole_number(start, _("Inicio de página"), 0)
    size = _whole_number(page_length, _("Tamaño de página"), 1)
    if size > 50:
        frappe.throw(_("El tamaño de página no puede superar 50 ubicaciones."))

    # Preserve native Frappe LIKE semantics; values are escaped by DatabaseQuery.
    pattern = "%" + search + "%"
    or_filters = {field: ["like", pattern] for field in ("area_name", "branch")} if search else None
    rows = frappe.get_list(
        DOCTYPE,
        fields=["name", "area_name", "branch", "capacity", "status", "icon", "color"],
        or_filters=or_filters,
        order_by="display_order asc, area_name asc, name asc",
        limit_start=offset,
        limit_page_length=size + 1,
    )
    return {
        "items": rows[:size],
        "has_next": len(rows) > size,
        "start": offset,
        "page_length": size,
    }


@frappe.whitelist(methods=["POST"])
def save_location(document):
    """Save an area without accepting permission flags or arbitrary fields."""
    if isinstance(document, str):
        document = frappe.parse_json(document)
    if not isinstance(document, dict):
        frappe.throw(_("Los datos de la ubicación no son válidos."))
    if document.get("doctype") not in (None, DOCTYPE):
        frappe.throw(_("El tipo de documento no corresponde a un área del restaurante."))

    name = document.get("name")
    is_new = bool(document.get("__islocal")) or not name
    if is_new:
        _require_create_permission()
        doc = frappe.new_doc(DOCTYPE)
    else:
        doc = frappe.get_doc(DOCTYPE, name)
        doc.check_permission("write")
        if not document.get("modified"):
            frappe.throw(_("Recarga la ubicación antes de guardar los cambios."))
        # Document.save compares this client timestamp with the current row.
        doc.modified = document["modified"]

    for fieldname in EDITABLE_FIELDS:
        if fieldname in document:
            doc.set(fieldname, document[fieldname])
    if is_new:
        doc.insert()
    else:
        doc.save()
    doc.apply_fieldlevel_read_permissions()
    return doc.as_dict()


def validate_area(doc, method=None):
    """Validate both the designed editor and native form/import writes."""
    doc.area_name = cstr(doc.area_name).strip()
    if not doc.area_name:
        frappe.throw(_("Ingresa el nombre de la ubicación."))
    if len(doc.area_name) > 140:
        frappe.throw(_("El nombre de la ubicación no puede superar 140 caracteres."))
    if not doc.branch:
        frappe.throw(_("Selecciona la sucursal de la ubicación."))
    if doc.area_type not in AREA_TYPES:
        frappe.throw(_("Selecciona un tipo de área válido."))
    if doc.status not in AREA_STATUSES:
        frappe.throw(_("Selecciona un estado válido."))
    if doc.icon not in AREA_ICONS:
        frappe.throw(_("Selecciona un icono válido."))

    doc.display_order = _whole_number(doc.display_order, _("Orden de visualización"), 0)
    doc.capacity = _whole_number(doc.capacity, _("Capacidad estimada"), 1)
    doc.visible_in_pos = _check_value(doc.visible_in_pos, _("Visible en POS"))
    doc.allow_open_accounts = _check_value(doc.allow_open_accounts, _("Permite apertura de cuentas"))
    for fieldname, maximum, label in (
        ("description", 500, _("Descripción")),
        ("notes", 300, _("Observaciones")),
    ):
        if len(cstr(doc.get(fieldname))) > maximum:
            frappe.throw(_("{0} no puede superar {1} caracteres.").format(label, maximum))
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", cstr(doc.color)):
        frappe.throw(_("El color de referencia debe tener el formato #22C55E."))

    _check_readable_link("Branch", doc.branch)
    if doc.printer:
        _check_readable_link("Network Printer Settings", doc.printer)
    if doc.waiter:
        waiter = _check_readable_link("Employee", doc.waiter)
        if waiter.status != "Active" or waiter.designation != "Mesero":
            frappe.throw(_("El mesero responsable debe ser un empleado activo con cargo Mesero."))
        if waiter.branch != doc.branch:
            frappe.throw(_("El mesero responsable debe pertenecer a la sucursal seleccionada."))
    if doc.image:
        _validate_image(doc.image)


def _require_create_permission():
    if not frappe.has_permission(DOCTYPE, "create"):
        frappe.throw(_("No tienes permiso para crear ubicaciones del restaurante."), frappe.PermissionError)


def _whole_number(value, label, minimum):
    try:
        number = Decimal(str(value))
        if isinstance(value, bool) or not number.is_finite() or number != number.to_integral_value():
            raise InvalidOperation
        if number < minimum or number > 2147483647:
            raise InvalidOperation
    except (InvalidOperation, TypeError, ValueError):
        frappe.throw(_("{0} debe ser un número entero mayor o igual a {1}.").format(label, minimum))
    return int(number)


def _check_value(value, label):
    if value not in (0, 1, "0", "1", False, True):
        frappe.throw(_("El valor de {0} no es válido.").format(label))
    return int(value)


def _check_readable_link(doctype, name):
    doc = frappe.get_doc(doctype, name)
    allowed = frappe.has_permission(doctype, "read", doc=doc)
    if doctype in ("Branch", "Employee"):
        allowed = allowed or frappe.has_permission(doctype, "select", doc=doc)
    if not allowed or not frappe.permissions.has_user_permission(doc):
        frappe.throw(_("No tienes permiso para seleccionar ese registro."), frappe.PermissionError)
    return doc


def _validate_image(file_url):
    parsed = urlsplit(cstr(file_url))
    path = unquote(parsed.path)
    if (
        parsed.scheme or parsed.netloc or parsed.query or parsed.fragment
        or not path.startswith(("/files/", "/private/files/"))
        or ".." in PurePosixPath(path).parts
    ):
        frappe.throw(_("Selecciona una imagen cargada en este sitio."))
    file_name = frappe.db.get_value("File", {"file_url": file_url}, "name")
    if not file_name:
        frappe.throw(_("La imagen seleccionada no existe en los archivos del sitio."))
    image_file = _check_readable_link("File", file_name)
    extension = PurePosixPath(cstr(image_file.file_name)).suffix.lower()
    if extension not in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".avif"):
        frappe.throw(_("Selecciona una imagen JPG, PNG, GIF, WEBP o AVIF."))
