"""Preparation screens backed by native Frappe permissions and documents."""

import hashlib
import json

import frappe
from frappe import _
from frappe.permissions import get_doc_permissions, get_role_permissions
from frappe.utils import cint, cstr, get_datetime, now_datetime

from restaurant.pos import _require_pos_user, _row_stations, _serialize_order

DISPLAY = "Restaurant Preparation Display"
STAGE = "Restaurant Preparation Stage"
TICKET = "Restaurant Preparation Ticket"
ORDER = "Restaurant Order"


def _parse_data(data):
    if isinstance(data, str):
        data = frappe.parse_json(data)
    if not isinstance(data, dict):
        frappe.throw(_("Los datos de preparación no son válidos."))
    return data


def _parse_list(value):
    if not value:
        return []
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (ValueError, TypeError):
            return []
    return value if isinstance(value, list) else []


def _stage_data(doc):
    return {
        "name": doc.name,
        "stage_name": doc.stage_name,
        "color": doc.color,
        "alert_minutes": cint(doc.alert_minutes),
        "modified": str(doc.modified) if doc.modified else "",
    }


def _display_data(doc):
    stages = []
    for row in doc.get("stages", []):
        stage = frappe.get_doc(STAGE, row.stage)
        stage.check_permission("read")
        stages.append(_stage_data(stage))
    return {
        "name": doc.name,
        "display_name": doc.display_name,
        "description": doc.description or "",
        "enabled": cint(doc.enabled),
        "auto_clear": cint(doc.auto_clear),
        "auto_clear_minutes": cint(doc.auto_clear_minutes),
        "pos_profiles": [row.pos_profile for row in doc.get("pos_profiles", [])],
        "item_groups": [row.item_group for row in doc.get("item_groups", [])],
        "stages": stages,
        "modified": str(doc.modified) if doc.modified else "",
        "can_write": bool(get_doc_permissions(doc).get("write")),
    }


def _read_displays():
    names = frappe.get_list(
        DISPLAY, fields=["name"], order_by="display_name asc, name asc", limit_page_length=0
    )
    displays = []
    for row in names:
        doc = frappe.get_doc(DISPLAY, row.name)
        doc.check_permission("read")
        displays.append(_display_data(doc))
    return displays


def _eligible_items(doc, display, station=None):
    if (
        doc.status not in ("En curso", "Facturada")
        or cint(doc.docstatus) == 2
        or doc.kds_status == "Sin enviar"
        or (display["pos_profiles"] and doc.pos_profile not in display["pos_profiles"])
    ):
        return []
    groups = set(display["item_groups"])
    station = cstr(station).strip()
    if station in ("Todas las estaciones", "ALL", "Todas"):
        station = ""
    return [
        row for row in doc.items
        if row.kds_status not in (None, "", "Pendiente")
        and (not groups or row.item_group in groups)
        and (not station or station in _row_stations(row))
    ]


def ticket_name(display_name, order_name):
    """Use a deterministic primary key to enforce one ticket per screen/order."""
    value = json.dumps([display_name, order_name], ensure_ascii=False)
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _ticket_contexts(doc, display, for_update=False):
    """Assign each row to one persisted segment; new rows belong to the base."""
    eligible = _eligible_items(doc, display)
    if not eligible:
        return []
    base_name = ticket_name(display["name"], doc.name)
    records = frappe.db.get_values(
        TICKET, {"preparation_display": display["name"], "restaurant_order": doc.name},
        ["name"], as_dict=True, for_update=for_update,
    )
    tickets = [frappe.get_doc(TICKET, row.name, for_update=for_update) for row in records]
    imported = sorted((ticket for ticket in tickets if ticket.name != base_name), key=lambda ticket: ticket.name)
    contexts, assigned = [], set()
    for ticket in imported:
        known = set(_parse_list(ticket.included_item_names_json))
        rows = [row for row in eligible if row.name in known and row.name not in assigned]
        if rows:
            contexts.append((ticket, rows))
            assigned.update(row.name for row in rows)
    base = next((ticket for ticket in tickets if ticket.name == base_name), None)
    remaining = [row for row in eligible if row.name not in assigned]
    if remaining:
        contexts.insert(0, (base, remaining))
    return contexts


def _legacy_index(doc, stages):
    if doc.kds_status in ("Entregado", "Cerrado"):
        return len(stages) - 1
    if doc.kds_status == "Listo":
        return len(stages) - 2
    return 0


def _ticket_projection(doc, display, ticket, eligible):
    """Project legacy data without inserting or modifying historical records."""
    stages = _parse_list(ticket.stages_json) if ticket else []
    stages = stages or display["stages"]
    if not stages:
        frappe.throw(_("La pantalla no tiene etapas de preparación configuradas."))
    item_names = {row.name for row in eligible}
    old_names = set(_parse_list(ticket.get("included_item_names_json"))) if ticket else set()
    new_names = {
        row.name for row in eligible
        if row.name not in old_names and row.kds_status not in ("Entregado", "Cerrado", "Cancelado")
    }
    added_items = bool(ticket and old_names and new_names)
    active_names = set(_parse_list(ticket.get("active_item_names_json"))) if ticket else item_names
    active_names = active_names.intersection(item_names) if active_names else item_names
    index = max(0, min(cint(ticket.stage_index), len(stages) - 1)) if ticket else _legacy_index(doc, stages)
    completed = set(_parse_list(ticket.completed_items_json)) if ticket else set()
    if not ticket and index == 0:
        completed = {row.name for row in eligible if row.kds_status in ("Listo", "Entregado", "Cerrado", "Cancelado")}
    started_at = ticket.stage_started_at if ticket else doc.sent_to_kitchen_at or doc.creation
    completed_at = ticket.completed_at if ticket else (
        doc.modified if doc.kds_status in ("Entregado", "Cerrado") else None
    )
    cleared_at = ticket.cleared_at if ticket else (doc.modified if doc.kds_status == "Cerrado" else None)
    if not ticket and doc.kds_status == "En preparación":
        current_names = {row.name for row in eligible if row.kds_status not in ("Entregado", "Cerrado")}
        if current_names:
            active_names = current_names
    if added_items:
        finished_batch = index == len(stages) - 1 or cleared_at
        active_names = new_names if finished_batch else active_names | new_names
        if finished_batch:
            stages = display["stages"]
        index, completed = 0, set()
        started_at, completed_at, cleared_at = doc.sent_to_kitchen_at or doc.modified, None, None
    return {
        "stages": stages,
        "stage_index": index,
        "completed_item_names": sorted(completed.intersection(active_names)),
        "active_item_names": sorted(active_names),
        "stage_started_at": started_at or now_datetime(),
        "completed_at": completed_at,
        "cleared_at": cleared_at,
        "added_items": added_items,
    }


def _is_retired(projection, display, current_time):
    if projection["cleared_at"]:
        return True
    return bool(
        display["auto_clear"] and projection["completed_at"]
        and projection["stage_index"] == len(projection["stages"]) - 1
        and (current_time - get_datetime(projection["completed_at"])).total_seconds()
        >= cint(display["auto_clear_minutes"]) * 60
    )


def _serialize_ticket(doc, display, ticket, eligible, current_time):
    projection = _ticket_projection(doc, display, ticket, eligible)
    if not projection["active_item_names"] or _is_retired(projection, display, current_time):
        return None
    serialized = _serialize_order(doc)
    names = set(projection["active_item_names"])
    serialized["items"] = [row for row in serialized["items"] if row["name"] in names]
    serialized.update({
        "ticket_name": ticket.name if ticket else ticket_name(display["name"], doc.name),
        "stage_index": projection["stage_index"],
        "stages": projection["stages"],
        "kds_stage": projection["stages"][projection["stage_index"]]["name"],
        "completed_item_names": projection["completed_item_names"],
        "kds_timer_start": str(projection["stage_started_at"]),
        "kds_wait_minutes": max(0, int((current_time - get_datetime(projection["stage_started_at"])).total_seconds() // 60)),
        "completed_at": str(projection["completed_at"]) if projection["completed_at"] else "",
    })
    return serialized


@frappe.whitelist()
def get_kds_state(display_name=None, station=None):
    """Read persisted preparation configuration and permitted active orders."""
    _require_pos_user()
    displays = _read_displays()
    selected = next((row for row in displays if row["name"] == display_name), None)
    if display_name and not selected:
        frappe.throw(_("No tienes acceso a la pantalla seleccionada."), frappe.PermissionError)
    if not selected:
        selected = next((row for row in displays if row["enabled"]), None)
    now = now_datetime()
    rows = frappe.get_list(
        ORDER,
        filters={
            "status": ["in", ["En curso", "Facturada"]],
            "docstatus": ["!=", 2],
            "kds_status": ["in", ["En preparación", "Listo", "Entregado"]],
        },
        fields=["name"], order_by="sent_to_kitchen_at asc, creation asc", limit_page_length=0,
    )
    documents = []
    for row in rows:
        doc = frappe.get_doc(ORDER, row.name)
        doc.check_permission("read")
        documents.append(doc)
    orders = []
    stations = {"Todas las estaciones", "Cocina General"}
    for display in displays:
        display["in_progress_count"] = 0
        display["avg_wait_minutes"] = 0
        total_wait = 0
        if not display["enabled"]:
            continue
        for doc in documents:
            eligible = _eligible_items(doc, display)
            if not eligible:
                continue
            for item in eligible:
                stations.update(_row_stations(item))
            contexts = _ticket_contexts(doc, display)
            for batch_index, (ticket, batch_items) in enumerate(contexts, 1):
                serialized = _serialize_ticket(doc, display, ticket, batch_items, now)
                if not serialized:
                    continue
                serialized.update({"batch_index": batch_index, "batch_count": len(contexts)})
                if serialized["stage_index"] < len(serialized["stages"]) - 1:
                    display["in_progress_count"] += 1
                    total_wait += serialized["kds_wait_minutes"]
                if selected and selected["name"] == display["name"]:
                    filtered = _eligible_items(doc, display, station)
                    names = {item.name for item in filtered}
                    serialized["items"] = [item for item in serialized["items"] if item["name"] in names]
                    if serialized["items"]:
                        orders.append(serialized)
        if display["in_progress_count"]:
            display["avg_wait_minutes"] = round(total_wait / display["in_progress_count"])
    stage_rows = frappe.get_list(STAGE, fields=["name"], order_by="stage_name asc", limit_page_length=0)
    return {
        "displays": displays,
        "selected_display": selected["name"] if selected else None,
        "orders": orders,
        "stations": sorted(stations),
        "stages_catalog": [_stage_data(frappe.get_doc(STAGE, row.name)) for row in stage_rows],
        "server_now": str(now),
        "has_more": False,
        "can_create_display": bool(get_role_permissions(DISPLAY).get("create")),
        "can_create_stage": bool(get_role_permissions(STAGE).get("create")),
    }


def _editable_doc(doctype, data):
    if data.get("name"):
        doc = frappe.get_doc(doctype, data["name"])
        doc.check_permission("write")
        if not data.get("modified"):
            frappe.throw(_("Recarga la configuración antes de guardar los cambios."))
        doc.modified = data["modified"]
    else:
        if not frappe.has_permission(doctype, "create"):
            frappe.throw(_("No tienes permiso para crear esta configuración."), frappe.PermissionError)
        doc = frappe.new_doc(doctype)
    return doc


@frappe.whitelist(methods=["POST"])
def save_display(data):
    """Save only the declared configuration fields through the native controller."""
    _require_pos_user()
    data = _parse_data(data)
    doc = _editable_doc(DISPLAY, data)
    for field in ("display_name", "description", "enabled", "auto_clear", "auto_clear_minutes"):
        if field in data:
            doc.set(field, data[field])
    for field, link_field in (("pos_profiles", "pos_profile"), ("item_groups", "item_group"), ("stages", "stage")):
        if field not in data:
            continue
        if not isinstance(data[field], list):
            frappe.throw(_("Las selecciones de la pantalla deben ser listas válidas."))
        names = [row.get(link_field) if isinstance(row, dict) else row for row in data[field]]
        if any(not isinstance(name, str) or not name.strip() for name in names):
            frappe.throw(_("Selecciona valores válidos para la pantalla."))
        doc.set(field, [{link_field: name} for name in names])
    doc.save()
    return _display_data(doc)


@frappe.whitelist(methods=["POST"])
def save_stage(data):
    """Persist stage colors and alerts; the controller validates every entry path."""
    _require_pos_user()
    data = _parse_data(data)
    doc = _editable_doc(STAGE, data)
    for field in ("stage_name", "color", "alert_minutes"):
        if field in data:
            doc.set(field, data[field])
    doc.save()
    return _stage_data(doc)


def _locked_context(display_name, order_name, ticket_id=None):
    _require_pos_user()
    if any(not isinstance(name, str) or not name.strip() or len(name) > 140 for name in (display_name, order_name)):
        frappe.throw(_("Selecciona una pantalla y una orden válidas."))
    display_name, order_name = display_name.strip(), order_name.strip()
    display_doc = frappe.get_doc(DISPLAY, display_name)
    display_doc.check_permission("read")
    if not display_doc.enabled:
        frappe.throw(_("Esta pantalla de preparación está desactivada."))
    display = _display_data(display_doc)
    # The parent lock serializes ticket creation, kitchen updates and POS edits.
    if not frappe.db.get_value(ORDER, order_name, "name", for_update=True):
        frappe.throw(_("La orden seleccionada no existe."), frappe.DoesNotExistError)
    doc = frappe.get_doc(ORDER, order_name, for_update=True)
    doc.check_permission("read")
    doc.check_permission("write")
    eligible = _eligible_items(doc, display)
    if not eligible:
        frappe.throw(_("La orden no tiene productos enviados a esta pantalla."))
    contexts = _ticket_contexts(doc, display, for_update=True)
    if ticket_id:
        if not isinstance(ticket_id, str) or len(ticket_id) > 140:
            frappe.throw(_("El identificador del ticket no es válido."))
        match = next((context for context in contexts if (
            context[0].name if context[0] else ticket_name(display["name"], doc.name)
        ) == ticket_id), None)
        if not match:
            frappe.throw(_("El ticket no pertenece a esta orden y pantalla."), frappe.PermissionError)
        ticket, eligible = match
    elif len(contexts) == 1:
        ticket, eligible = contexts[0]
    else:
        frappe.throw(_("Selecciona el ticket de preparación que deseas actualizar."))
    projection = _ticket_projection(doc, display, ticket, eligible)
    return doc, display, ticket, eligible, projection


def _check_expected_stage(projection, expected_stage):
    actual = projection["stages"][projection["stage_index"]]["name"]
    if not expected_stage or cstr(expected_stage) != actual:
        frappe.throw(_("La orden cambió de etapa. Actualiza la pantalla antes de continuar."), frappe.TimestampMismatchError)


def _materialize_ticket(doc, display, ticket, eligible, projection):
    if not ticket:
        ticket = frappe.new_doc(TICKET)
        ticket.name = ticket_name(display["name"], doc.name)
        ticket.preparation_display = display["name"]
        ticket.restaurant_order = doc.name
    ticket.stages_json = json.dumps(projection["stages"], ensure_ascii=False)
    ticket.stage_index = projection["stage_index"]
    ticket.completed_items_json = json.dumps(projection["completed_item_names"])
    ticket.stage_started_at = projection["stage_started_at"]
    ticket.completed_at = projection["completed_at"]
    ticket.cleared_at = projection["cleared_at"]
    ticket.included_item_names_json = json.dumps([row.name for row in eligible])
    ticket.active_item_names_json = json.dumps(projection["active_item_names"])
    return ticket


def _persist_ticket(ticket):
    # Ticket permissions prohibit direct Desk/API writes; operational access was
    # checked on both linked documents before this private persistence step.
    ticket.save(ignore_permissions=True)


def _operational_display(doc):
    """Read configuration privately after operational order access was checked."""
    return {
        "name": doc.name,
        "pos_profiles": [entry.pos_profile for entry in doc.get("pos_profiles", [])],
        "item_groups": [entry.item_group for entry in doc.get("item_groups", [])],
        "stages": [_stage_data(frappe.get_doc(STAGE, entry.stage)) for entry in doc.get("stages", [])],
    }


def _capture_enabled_screen_tickets(doc):
    """Freeze peer screens before changing the shared legacy order status.

    The caller holds the order lock and has verified write access. Capturing
    these operational snapshots only during POST keeps reads side-effect free
    and lets an untouched screen resume after being disabled temporarily.
    """
    for row in frappe.get_all(DISPLAY, filters={"enabled": 1}, fields=["name"]):
        display = _operational_display(frappe.get_doc(DISPLAY, row.name))
        for ticket, eligible in _ticket_contexts(doc, display, for_update=True):
            if ticket:
                continue
            projection = _ticket_projection(doc, display, None, eligible)
            ticket = _materialize_ticket(doc, display, None, eligible, projection)
            _persist_ticket(ticket)


def _sync_legacy_status(doc):
    """Update only operational fields after all relevant screens agree."""
    phases = []
    item_phases = {}
    for row in frappe.get_all(DISPLAY, filters={"enabled": 1}, fields=["name"]):
        display = _operational_display(frappe.get_doc(DISPLAY, row.name))
        eligible = _eligible_items(doc, display)
        if not eligible:
            continue
        for ticket, batch_items in _ticket_contexts(doc, display, for_update=True):
            projection = _ticket_projection(doc, display, ticket, batch_items)
            index, count = projection["stage_index"], len(projection["stages"])
            phase = 3 if projection["cleared_at"] else 2 if index == count - 1 else 1 if index == count - 2 else 0
            active_names = set(projection["active_item_names"])
            if not active_names:
                phase = 2
            phases.append(phase)
            for item in batch_items:
                previous_phase = 3 if item.kds_status == "Cerrado" else 2
                item_phases.setdefault(item.name, []).append(phase if item.name in active_names else previous_phase)
    if not phases:
        return
    # Retirement belongs to each screen's ticket. A global closed order would
    # hide unfinished tickets when another screen is disabled and later resumed.
    status = ("En preparación", "Listo", "Entregado", "Entregado")[min(phases)]
    if doc.kds_status != status:
        frappe.db.set_value(ORDER, doc.name, "kds_status", status, update_modified=False)
        doc.kds_status = status
    for row in doc.items:
        if cint(getattr(row, "is_cancelled", 0)) or row.kds_status == "Cancelado":
            continue
        row_phases = item_phases.get(row.name)
        if row_phases:
            row_status = ("En preparación", "Listo", "Entregado", "Entregado")[min(row_phases)]
            if row.kds_status != row_status:
                frappe.db.set_value("Restaurant Order Item", row.name, "kds_status", row_status, update_modified=False)
                row.kds_status = row_status


def _mutation_result(doc, display, ticket, eligible):
    _persist_ticket(ticket)
    _capture_enabled_screen_tickets(doc)
    _sync_legacy_status(doc)
    return {
        "ticket_name": ticket.name,
        "order": _serialize_ticket(doc, display, ticket, eligible, now_datetime()),
    }


@frappe.whitelist(methods=["POST"])
def toggle_item(display_name, order_name, item_name, expected_stage, completed=1, ticket_id=None):
    """Set a dish mark once, advancing only when every eligible dish is marked."""
    doc, display, ticket, eligible, projection = _locked_context(display_name, order_name, ticket_id)
    _check_expected_stage(projection, expected_stage)
    if _is_retired(projection, display, now_datetime()) or projection["stage_index"] == len(projection["stages"]) - 1:
        frappe.throw(_("Esta orden ya terminó su preparación en esta pantalla."))
    if completed not in (0, 1, "0", "1", False, True):
        frappe.throw(_("La marca del producto no es válida."))
    if item_name not in set(projection["active_item_names"]):
        frappe.throw(_("El producto no pertenece a esta orden y pantalla."))
    ticket = _materialize_ticket(doc, display, ticket, eligible, projection)
    marked = set(projection["completed_item_names"])
    if cint(completed):
        marked.add(item_name)
    else:
        marked.discard(item_name)
    if marked == set(projection["active_item_names"]):
        ticket.stage_index += 1
        ticket.stage_started_at = now_datetime()
        ticket.completed_items_json = "[]"
        if ticket.stage_index == len(projection["stages"]) - 1:
            ticket.completed_at = ticket.stage_started_at
    else:
        ticket.completed_items_json = json.dumps(sorted(marked))
    return _mutation_result(doc, display, ticket, eligible)


@frappe.whitelist(methods=["POST"])
def dismiss_ticket(display_name, order_name, expected_stage=None, ticket_id=None):
    """Retire a completed ticket without deleting the order or its history."""
    doc, display, ticket, eligible, projection = _locked_context(display_name, order_name, ticket_id)
    if expected_stage is not None:
        _check_expected_stage(projection, expected_stage)
    if projection["stage_index"] != len(projection["stages"]) - 1:
        frappe.throw(_("Solo puedes retirar órdenes de la etapa completada."))
    ticket = _materialize_ticket(doc, display, ticket, eligible, projection)
    ticket.cleared_at = ticket.cleared_at or now_datetime()
    return _mutation_result(doc, display, ticket, eligible)


def _rewind_ticket(display_name, order_name, expected_stage, first=False, ticket_id=None):
    doc, display, ticket, eligible, projection = _locked_context(display_name, order_name, ticket_id)
    _check_expected_stage(projection, expected_stage)
    ticket = _materialize_ticket(doc, display, ticket, eligible, projection)
    ticket.stage_index = 0 if first else max(0, ticket.stage_index - 1)
    ticket.completed_items_json = "[]"
    ticket.completed_at = None
    ticket.cleared_at = None
    ticket.stage_started_at = now_datetime()
    return _mutation_result(doc, display, ticket, eligible)


@frappe.whitelist(methods=["POST"])
def reset_ticket(display_name, order_name, expected_stage, ticket_id=None):
    """Return a ticket to its initial stage with a new server-side timer."""
    return _rewind_ticket(display_name, order_name, expected_stage, first=True, ticket_id=ticket_id)


@frappe.whitelist(methods=["POST"])
def move_previous_stage(display_name, order_name, expected_stage, ticket_id=None):
    """Undo a preparation-stage transition without altering financial documents."""
    return _rewind_ticket(display_name, order_name, expected_stage, ticket_id=ticket_id)
