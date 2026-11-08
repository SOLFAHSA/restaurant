"""Preserve preparation segments during atomic account splits and merges."""

import hashlib
import json

import frappe
from frappe import _
from frappe.utils import cint, now_datetime


def capture_order_kds(doc):
    """Freeze virtual screen state while the caller holds the order lock."""
    from restaurant import kds

    doc.check_permission("read")
    doc.check_permission("write")
    kds._capture_enabled_screen_tickets(doc)
    display_names = set(frappe.get_all(
        kds.TICKET, filters={"restaurant_order": doc.name}, pluck="preparation_display",
    ))
    snapshots = []
    for display_name in sorted(display_names):
        display = kds._operational_display(frappe.get_doc(kds.DISPLAY, display_name))
        for ticket, eligible in kds._ticket_contexts(doc, display, for_update=True):
            if not ticket:
                continue
            projection = kds._ticket_projection(doc, display, ticket, eligible)
            snapshots.append({
                "ticket_name": ticket.name,
                "preparation_display": display_name,
                "stages": projection["stages"],
                "stage_index": projection["stage_index"],
                "included_item_names": [row.name for row in eligible],
                "active_item_names": projection["active_item_names"],
                "completed_item_names": projection["completed_item_names"],
                "stage_started_at": projection["stage_started_at"],
                "completed_at": projection["completed_at"],
                "cleared_at": projection["cleared_at"],
            })
    return {"order_name": doc.name, "tickets": snapshots}


def _normalize_subset(ticket, active_names, marked_names):
    """Advance a partition that now contains only already-marked dishes."""
    from restaurant.kds import _parse_list

    stages = _parse_list(ticket.stages_json)
    if (
        active_names and marked_names == active_names and stages
        and cint(ticket.stage_index) < len(stages) - 1 and not ticket.cleared_at
    ):
        ticket.stage_index += 1
        ticket.stage_started_at = now_datetime()
        marked_names = set()
        if ticket.stage_index == len(stages) - 1:
            ticket.completed_at = ticket.stage_started_at
    ticket.active_item_names_json = json.dumps(sorted(active_names))
    ticket.completed_items_json = json.dumps(sorted(marked_names))


def _normalize_source(doc):
    """Normalize remaining batches without deleting moved-row history."""
    from restaurant import kds

    records = frappe.db.get_values(
        kds.TICKET, {"restaurant_order": doc.name}, ["name"], as_dict=True, for_update=True,
    )
    actual_names = {row.name for row in doc.items}
    for record in records:
        ticket = frappe.get_doc(kds.TICKET, record.name, for_update=True)
        active = set(kds._parse_list(ticket.active_item_names_json)).intersection(actual_names)
        marked = set(kds._parse_list(ticket.completed_items_json)).intersection(active)
        if not active:
            # Empty segments remain audit records and never become visible again.
            continue
        before = (ticket.stage_index, ticket.active_item_names_json, ticket.completed_items_json)
        _normalize_subset(ticket, active, marked)
        if before != (ticket.stage_index, ticket.active_item_names_json, ticket.completed_items_json):
            kds._persist_ticket(ticket)


def remap_order_kds(snapshot, target_doc, row_mapping):
    """Clone moved preparation partitions using a server-built child-ID mapping.

    The caller locks both orders, captures both sides before their changes,
    saves their rows, and commits the complete operation as one transaction.
    """
    from restaurant import kds

    target_doc.check_permission("read")
    target_doc.check_permission("write")
    if not isinstance(row_mapping, dict) or any(
        not isinstance(old, str) or not isinstance(new, str)
        for old, new in row_mapping.items()
    ):
        frappe.throw(_("La relación de platillos trasladados no es válida."))
    target_names = {row.name for row in target_doc.items}
    if not set(row_mapping.values()).issubset(target_names) or len(set(row_mapping.values())) != len(row_mapping):
        frappe.throw(_("Los platillos trasladados no corresponden a la cuenta de destino."))
    created = []
    for state in snapshot["tickets"]:
        moved = set(state["included_item_names"]).intersection(row_mapping)
        if not moved:
            continue
        identity = json.dumps([
            state["ticket_name"], target_doc.name,
            sorted((old, row_mapping[old]) for old in moved),
        ])
        name = hashlib.sha256(identity.encode("utf-8")).hexdigest()
        if frappe.db.get_value(kds.TICKET, name, "name", for_update=True):
            continue
        ticket = frappe.new_doc(kds.TICKET)
        ticket.name = name
        ticket.preparation_display = state["preparation_display"]
        ticket.restaurant_order = target_doc.name
        ticket.stages_json = json.dumps(state["stages"], ensure_ascii=False)
        ticket.stage_index = state["stage_index"]
        ticket.stage_started_at = state["stage_started_at"]
        ticket.completed_at = state["completed_at"]
        ticket.cleared_at = state["cleared_at"]
        ticket.included_item_names_json = json.dumps(sorted(row_mapping[old] for old in moved))
        active = {row_mapping[old] for old in moved.intersection(state["active_item_names"])}
        marked = {row_mapping[old] for old in moved.intersection(state["completed_item_names"])}
        if not active:
            # Rows from an older finished batch must not re-enter its newer batch.
            ticket.stage_index = len(state["stages"]) - 1
            ticket.cleared_at = ticket.cleared_at or now_datetime()
        _normalize_subset(ticket, active, marked)
        kds._persist_ticket(ticket)
        created.append(ticket.name)
    source_doc = frappe.get_doc(kds.ORDER, snapshot["order_name"], for_update=True)
    _normalize_source(source_doc)
    for doc in (source_doc, target_doc):
        if doc.status == "En curso":
            kds._sync_legacy_status(doc)
    return {"created_tickets": created}
