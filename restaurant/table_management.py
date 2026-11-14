"""Validation and persistence helpers for restaurant tables and floor maps."""

import json
import re

import frappe
from frappe import _
from frappe.utils import cint

HEX_COLOR_PATTERN = re.compile(r"^#[0-9A-Fa-f]{6}$")
ALLOWED_SHAPES = (
    "Cuadrada",
    "Rectangular",
    "Redonda",
    "Ovalada",
    "Cancha azul",
    "Cancha fútbol",
    "Cancha básquetbol",
)
ALLOWED_STATUSES = ("Disponible", "Ocupada", "Reservada", "Inactiva")
ALLOWED_BACKGROUNDS = ("Madera cálida", "Cerámica clara", "Madera gris", "Césped")
ALLOWED_ELEMENT_CATEGORIES = ("tables", "chairs", "decor")
ALLOWED_ELEMENT_SUBTYPES = {
    "tables": (
        "table_square_wood",
        "table_round_wood",
        "table_rect_wood",
        "table_oval_wood",
        "table_court_blue",
        "table_court_soccer",
        "table_court_basket",
    ),
    "chairs": (
        "chair_wood",
        "chair_armchair_red",
        "chair_stool_orange",
    ),
    "decor": (
        "decor_palm",
        "decor_fern",
        "decor_wall_h",
        "decor_wall_v",
        "decor_wall_corner",
        "decor_door",
        "decor_restroom",
        "decor_label",
    ),
}
SUBTYPE_TO_SHAPE = {
    "table_square_wood": "Cuadrada",
    "table_round_wood": "Redonda",
    "table_rect_wood": "Rectangular",
    "table_oval_wood": "Ovalada",
    "table_court_blue": "Cancha azul",
    "table_court_soccer": "Cancha fútbol",
    "table_court_basket": "Cancha básquetbol",
}
EDITABLE_TABLE_FIELDS = (
    "restaurant_area",
    "table_number",
    "seats",
    "shape",
    "status",
    "display_order",
    "color",
    "notes",
)


def _require_authenticated_user():
    if frappe.session.user == "Guest":
        frappe.throw(
            _("Debes iniciar sesión para administrar las mesas del restaurante."),
            frappe.PermissionError,
        )


def _parse_int(value, label, minimum=None, maximum=None):
    if isinstance(value, bool) or value in (None, ""):
        frappe.throw(_("El campo {0} debe ser un número entero.").format(label))
    try:
        if isinstance(value, float) and not value.is_integer():
            raise ValueError
        text = str(value).strip()
        if not text or "." in text:
            raise ValueError
        number = int(text)
    except ValueError:
        frappe.throw(_("El campo {0} debe ser un número entero.").format(label))
    if minimum is not None and number < minimum:
        frappe.throw(_("El campo {0} debe ser mayor o igual a {1}.").format(label, minimum))
    if maximum is not None and number > maximum:
        frappe.throw(_("El campo {0} no puede superar {1}.").format(label, maximum))
    return number


def validate_table(doc):
    """Enforce restaurant table business rules during every save path."""
    area_name = (doc.restaurant_area or "").strip()
    if not area_name or not frappe.db.exists("Restaurant Area", area_name):
        frappe.throw(_("Selecciona un área de restaurante válida."))
    area_doc = frappe.get_doc("Restaurant Area", area_name)
    area_doc.check_permission("read")
    doc.restaurant_area = area_doc.name
    doc.branch = area_doc.branch

    doc.table_number = (doc.table_number or "").strip()
    if not doc.table_number:
        frappe.throw(_("El número o código de mesa es obligatorio."))
    if len(doc.table_number) > 60:
        frappe.throw(_("El número o código de mesa no puede superar 60 caracteres."))

    duplicate = frappe.db.sql(
        """
        SELECT name
        FROM `tabRestaurant Table`
        WHERE restaurant_area = %s
          AND LOWER(TRIM(table_number)) = LOWER(%s)
          AND name != %s
        LIMIT 1
        """,
        (doc.restaurant_area, doc.table_number, doc.name or ""),
    )
    if duplicate:
        frappe.throw(
            _("Ya existe la mesa {0} dentro del área {1}.").format(
                doc.table_number, doc.restaurant_area
            )
        )

    doc.seats = _parse_int(
        doc.seats if doc.seats not in (None, "") else 4,
        _("Asientos"),
        minimum=1,
        maximum=500,
    )
    doc.display_order = _parse_int(
        0 if doc.display_order in (None, "") else doc.display_order,
        _("Orden de visualización"),
        minimum=0,
    )
    doc.shape = (doc.shape or "Cuadrada").strip()
    if doc.shape not in ALLOWED_SHAPES:
        frappe.throw(_("La forma seleccionada para la mesa no es válida."))

    doc.status = (doc.status or "Disponible").strip()
    if doc.status not in ALLOWED_STATUSES:
        frappe.throw(_("El estado de la mesa debe ser Disponible, Ocupada, Reservada o Inactiva."))

    doc.color = (doc.color or "#22C55E").strip().upper()
    if not HEX_COLOR_PATTERN.match(doc.color):
        frappe.throw(_("El color de la mesa debe usar formato hexadecimal #RRGGBB."))

    doc.notes = (doc.notes or "").strip()
    if len(doc.notes) > 300:
        frappe.throw(_("Las observaciones de la mesa no pueden superar 300 caracteres."))


def parse_area_layout(raw_layout):
    """Parse and sanitize the floor plan JSON stored on Restaurant Area."""
    if not raw_layout:
        return []
    if isinstance(raw_layout, list):
        items = raw_layout
    else:
        try:
            items = json.loads(raw_layout)
        except Exception:
            return []
    if not isinstance(items, list):
        return []
    cleaned = []
    for index, item in enumerate(items[:250]):
        if not isinstance(item, dict):
            continue
        category = str(item.get("category") or "").strip()
        subtype = str(item.get("subtype") or "").strip()
        if category not in ALLOWED_ELEMENT_CATEGORIES:
            continue
        if subtype not in ALLOWED_ELEMENT_SUBTYPES.get(category, ()):
            continue
        element_id = str(item.get("id") or f"el_{index + 1}").strip()[:60]
        try:
            x = max(0, min(1400, int(round(float(item.get("x", 40))))))
            y = max(0, min(900, int(round(float(item.get("y", 40))))))
            width = max(24, min(600, int(round(float(item.get("width", 90))))))
            height = max(24, min(600, int(round(float(item.get("height", 90))))))
            rotation = int(round(float(item.get("rotation", 0)))) % 360
        except (TypeError, ValueError):
            continue
        entry = {
            "id": element_id,
            "category": category,
            "subtype": subtype,
            "x": x,
            "y": y,
            "width": width,
            "height": height,
            "rotation": rotation,
        }
        if category == "tables":
            table_name = str(item.get("table_name") or "").strip()
            if table_name:
                entry["table_name"] = table_name
        if subtype == "decor_label":
            entry["label"] = str(item.get("label") or "Zona").strip()[:60]
        cleaned.append(entry)
    return cleaned


def get_area_tables_list(area_name):
    """Return ordered tables belonging to a Restaurant Area."""
    if not area_name or not frappe.db.exists("Restaurant Area", area_name):
        return []
    area_doc = frappe.get_doc("Restaurant Area", area_name)
    area_doc.check_permission("read")
    if not frappe.has_permission("Restaurant Table", "read"):
        return []
    return frappe.get_List(
        "Restaurant Table",
        filters={"restaurant_area": area_name},
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
        limit_page_length=200,
    ) if hasattr(frappe, "get_List") else frappe.get_list(
        "Restaurant Table",
        filters={"restaurant_area": area_name},
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
        limit_page_length=200,
    )


@frappe.whitelist()
def get_area_tables(area_name):
    """Return the linked tables for a Restaurant Area."""
    _require_authenticated_user()
    return get_area_tables_list(area_name)


@frappe.whitelist(methods=["POST"])
def save_table(document):
    """Create or update a Restaurant Table using native Frappe permissions."""
    _require_authenticated_user()
    payload = frappe.parse_json(document) if isinstance(document, str) else document
    if not isinstance(payload, dict):
        frappe.throw(_("Los datos de la mesa no tienen un formato válido."))
    if payload.get("doctype") and payload.get("doctype") != "Restaurant Table":
        frappe.throw(_("El documento recibido no corresponde a una mesa de restaurante."))

    values = {field: payload.get(field) for field in EDITABLE_TABLE_FIELDS if field in payload}
    if payload.get("name"):
        if not frappe.db.exists("Restaurant Table", payload["name"]):
            frappe.throw(_("La mesa solicitada no existe."), frappe.DoesNotExistError)
        doc = frappe.get_doc("Restaurant Table", payload["name"])
        doc.check_permission("write")
        if payload.get("modified") and str(doc.modified) != str(payload.get("modified")):
            frappe.throw(
                _("La mesa fue modificada por otro usuario. Recarga antes de guardar."),
                frappe.TimestampMismatchError,
            )
        doc.update(values)
        doc.save()
    else:
        if not frappe.has_permission("Restaurant Table", "create"):
            frappe.throw(
                _("No tienes permisos para crear mesas de restaurante."),
                frappe.PermissionError,
            )
        doc = frappe.get_doc({"doctype": "Restaurant Table", **values})
        doc.check_permission("create")
        doc.insert()

    return {
        "table": doc.as_dict(),
        "tables": get_area_tables_list(doc.restaurant_area),
    }


@frappe.whitelist(methods=["POST"])
def delete_table(name):
    """Delete a Restaurant Table and detach it from its area floor map if present."""
    _require_authenticated_user()
    if not name or not frappe.db.exists("Restaurant Table", name):
        frappe.throw(_("La mesa solicitada no existe."), frappe.DoesNotExistError)
    doc = frappe.get_doc("Restaurant Table", name)
    doc.check_permission("delete")
    area_name = doc.restaurant_area
    frappe.delete_doc("Restaurant Table", doc.name)

    if area_name and frappe.db.exists("Restaurant Area", area_name):
        area_doc = frappe.get_doc("Restaurant Area", area_name)
        if area_doc.has_permission("write") and area_doc.layout_json:
            elements = parse_area_layout(area_doc.layout_json)
            changed = False
            for item in elements:
                if item.get("table_name") == name:
                    item.pop("table_name", None)
                    changed = True
            if changed:
                area_doc.layout_json = json.dumps(elements, ensure_ascii=False)
                area_doc.save()

    return {
        "deleted": name,
        "tables": get_area_tables_list(area_name),
    }


@frappe.whitelist(methods=["POST"])
def update_table_status(table_name, status):
    """Update operational status of a table from the floor map."""
    _require_authenticated_user()
    if not table_name or not frappe.db.exists("Restaurant Table", table_name):
        frappe.throw(_("La mesa seleccionada no existe."), frappe.DoesNotExistError)
    doc = frappe.get_doc("Restaurant Table", table_name)
    doc.check_permission("write")
    doc.status = status
    doc.save()
    return {
        "table": doc.as_dict(),
        "tables": get_area_tables_list(doc.restaurant_area),
    }


@frappe.whitelist()
def get_map_context(area_name=None):
    """Return areas, selected area layout, and linked tables for the floor map designer."""
    _require_authenticated_user()
    if not frappe.has_permission("Restaurant Area", "read"):
        frappe.throw(
            _("No tienes permisos para consultar las áreas del restaurante."),
            frappe.PermissionError,
        )

    areas = frappe.get_list(
        "Restaurant Area",
        fields=[
            "name",
            "area_name",
            "branch",
            "status",
            "capacity",
            "color",
            "icon",
            "floor_background",
            "display_order",
        ],
        order_by="display_order asc, area_name asc",
        limit_page_length=100,
    )

    selected_name = (area_name or "").strip()
    if not selected_name and areas:
        selected_name = areas[0]["name"]

    area_doc = None
    elements = []
    tables = []
    can_write_area = False
    if selected_name:
        if not frappe.db.exists("Restaurant Area", selected_name):
            frappe.throw(_("El área seleccionada no existe."), frappe.DoesNotExistError)
        doc = frappe.get_doc("Restaurant Area", selected_name)
        doc.check_permission("read")
        can_write_area = bool(doc.has_permission("write"))
        tables = get_area_tables_list(doc.name)
        table_names = {row["name"] for row in tables}
        elements = parse_area_layout(doc.layout_json)
        for item in elements:
            if item.get("table_name") and item["table_name"] not in table_names:
                item.pop("table_name", None)
        area_doc = {
            "name": doc.name,
            "area_name": doc.area_name,
            "branch": doc.branch,
            "status": doc.status,
            "capacity": cint(doc.capacity),
            "color": doc.color or "#22C55E",
            "floor_background": doc.floor_background or "Madera cálida",
            "modified": str(doc.modified),
        }

    return {
        "areas": areas,
        "area": area_doc,
        "elements": elements,
        "tables": tables,
        "permissions": {
            "can_write_area": can_write_area,
            "can_create_area": bool(frappe.has_permission("Restaurant Area", "create")),
            "can_create_table": bool(frappe.has_permission("Restaurant Table", "create")),
            "can_write_table": bool(frappe.has_permission("Restaurant Table", "write")),
            "can_delete_table": bool(frappe.has_permission("Restaurant Table", "delete")),
        },
    }


@frappe.whitelist(methods=["POST"])
def save_area_map(area_name, floor_background=None, elements=None, area_modified=None):
    """Validate and persist the visual floor map of a Restaurant Area."""
    _require_authenticated_user()
    if not area_name or not frappe.db.exists("Restaurant Area", area_name):
        frappe.throw(_("Selecciona un área de restaurante válida."))
    doc = frappe.get_doc("Restaurant Area", area_name)
    doc.check_permission("write")

    if area_modified and str(doc.modified) != str(area_modified):
        frappe.throw(
            _("El mapa de esta área fue modificado por otro usuario. Recarga antes de guardar."),
            frappe.TimestampMismatchError,
        )

    bg = (floor_background or doc.floor_background or "Madera cálida").strip()
    if bg not in ALLOWED_BACKGROUNDS:
        frappe.throw(_("El fondo seleccionado para el piso no es válido."))

    raw_elements = frappe.parse_json(elements) if isinstance(elements, str) else (elements or [])
    if not isinstance(raw_elements, list):
        frappe.throw(_("Los elementos del mapa no tienen un formato válido."))

    cleaned = parse_area_layout(raw_elements)
    valid_tables = {
        row["name"]: row
        for row in get_area_tables_list(doc.name)
    }
    assigned_tables = set()
    for item in cleaned:
        table_name = item.get("table_name")
        if not table_name:
            continue
        if table_name not in valid_tables:
            frappe.throw(
                _("La mesa asignada ({0}) no pertenece al área {1}.").format(
                    table_name, doc.area_name
                )
            )
        if table_name in assigned_tables:
            frappe.throw(
                _("La mesa {0} está asignada más de una vez en el mismo mapa.").format(
                    valid_tables[table_name]["table_number"]
                )
            )
        assigned_tables.add(table_name)
        mapped_shape = SUBTYPE_TO_SHAPE.get(item.get("subtype"))
        if mapped_shape and valid_tables[table_name].get("shape") != mapped_shape:
            table_doc = frappe.get_doc("Restaurant Table", table_name)
            if table_doc.has_permission("write"):
                table_doc.shape = mapped_shape
                table_doc.save()

    doc.floor_background = bg
    doc.layout_json = json.dumps(cleaned, ensure_ascii=False)
    doc.save()
    return get_map_context(doc.name)

