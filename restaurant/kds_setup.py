"""Explicit, idempotent installation of the default preparation screen."""

import frappe
from frappe import _


def ensure_default_display():
    """Seed a first screen without changing existing configuration or orders."""
    from restaurant.kds import DISPLAY, STAGE, save_display, save_stage

    frappe.only_for("System Manager")
    if not frappe.db.get_value("DocType", DISPLAY, "name", for_update=True):
        frappe.throw(_("Sincroniza los DocTypes de preparación antes de crear la pantalla inicial."))
    # Serialize repeated setup calls without committing outside the caller transaction.
    existing = frappe.db.get_value(DISPLAY, {}, "name", for_update=True)
    if existing:
        return {"created": False, "display": existing}

    stages = []
    for label, color, minutes in (
        ("To cook", "#9CA3AF", 10),
        ("Ready", "#3B82F6", 5),
        ("Completed", "#22C55E", 0),
    ):
        name = frappe.db.get_value(STAGE, {"stage_name": label}, "name")
        if not name:
            name = save_stage({
                "stage_name": label, "color": color, "alert_minutes": minutes,
            })["name"]
        stages.append(name)
    display = save_display({
        "display_name": "Kitchen Display",
        "description": "Pantalla de preparación del restaurante: preparación, entrega y pedidos completados.",
        "enabled": 1, "auto_clear": 0, "auto_clear_minutes": 10,
        "pos_profiles": [], "item_groups": [], "stages": stages,
    })
    return {"created": True, "display": display["name"]}
