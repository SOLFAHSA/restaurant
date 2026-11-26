"""Kitchen/bar stations, command routing and print configuration, and order presets."""

import frappe
from frappe.utils import cint, cstr


def _resolve_command_map():
    """Map Item Group names to configured Restaurant Command station names in 2 batch queries."""
    cached = getattr(frappe.local, "_restaurant_command_map_cache", None)
    if cached is not None:
        return {k: list(v) for k, v in cached.items()}
    mapping = {}
    if not frappe.db.exists("DocType", "Restaurant Command"):
        return mapping
    commands = frappe.get_all(
        "Restaurant Command",
        filters={"enabled": 1},
        fields=["name", "command_name", "branch"],
        order_by="command_name asc",
    )
    if commands:
        cmd_by_name = {cmd.name: cmd.command_name for cmd in commands}
        rows = frappe.get_all(
            "Restaurant Command Group",
            filters={"parent": ["in", list(cmd_by_name.keys())], "parenttype": "Restaurant Command"},
            fields=["parent", "item_group"],
            limit_page_length=1000,
        )
        for row in rows:
            station_name = cmd_by_name.get(row.parent)
            if station_name and row.item_group:
                mapping.setdefault(row.item_group, []).append(station_name)
    frappe.local._restaurant_command_map_cache = mapping
    return {k: list(v) for k, v in mapping.items()}


def _row_stations(row):
    """Split the comma-separated station list stored on an order line."""
    names = [part.strip() for part in cstr(row.command_station or "").split(",") if part.strip()]
    return names or ["Cocina General"]


def get_command_stations():
    """Return enabled Restaurant Command station names plus the general fallback."""
    names = []
    if frappe.db.exists("DocType", "Restaurant Command"):
        names = frappe.get_all(
            "Restaurant Command",
            filters={"enabled": 1},
            pluck="command_name",
            order_by="command_name asc",
        )
    if "Cocina General" not in names:
        names.append("Cocina General")
    return names


def get_command_configs():
    """Return enabled Restaurant Command documents with their category mappings and printer configuration."""
    if not frappe.db.exists("DocType", "Restaurant Command"):
        return []
    cmd_meta = frappe.get_meta("Restaurant Command")
    cmd_fields = ["name", "command_name", "branch", "enabled"]
    for extra_f in ("print_mode", "network_printer", "printer_ip", "printer_port", "paper_width_mm", "auto_print_on_send"):
        if cmd_meta.has_field(extra_f):
            cmd_fields.append(extra_f)
    rows = frappe.get_all(
        "Restaurant Command",
        filters={"enabled": 1},
        fields=cmd_fields,
        order_by="command_name asc",
    )
    groups_by_cmd = {}
    if rows:
        cmd_names = [r.name for r in rows]
        group_rows = frappe.get_all(
            "Restaurant Command Group",
            filters={"parent": ["in", cmd_names], "parenttype": "Restaurant Command"},
            fields=["parent", "item_group"],
            order_by="idx asc",
            limit_page_length=1000,
        )
        for g in group_rows:
            if g.item_group:
                groups_by_cmd.setdefault(g.parent, []).append(g.item_group)
    configs = []
    for row in rows:
        groups = groups_by_cmd.get(row.name, [])
        configs.append({
            "name": row.name,
            "command_name": row.command_name,
            "branch": row.branch or "",
            "print_mode": row.get("print_mode") or "Impresora del navegador (Ticket térmico)",
            "network_printer": row.get("network_printer") or "",
            "printer_ip": row.get("printer_ip") or "",
            "printer_port": cint(row.get("printer_port") or 9100),
            "paper_width_mm": row.get("paper_width_mm") or "80mm",
            "auto_print_on_send": cint(row.get("auto_print_on_send") if row.get("auto_print_on_send") is not None else 1),
            "groups": groups,
        })
    return configs


def get_order_presets():
    """Return active order presets (Comer en el local, Para llevar, Entrega) with scheduling and customer rules."""
    default_presets = [
        {
            "preset_name": "Comer en el local",
            "color_bg": "#cce3fd",
            "color_border": "#3b82f6",
            "is_default": 1,
            "require_customer": 0,
            "enable_scheduling": 0,
            "slot_interval_minutes": 20,
            "schedule_start_time": "12:00",
            "schedule_end_time": "22:00",
        },
        {
            "preset_name": "Para llevar",
            "color_bg": "#fef0a6",
            "color_border": "#eab308",
            "is_default": 0,
            "require_customer": 0,
            "enable_scheduling": 1,
            "slot_interval_minutes": 20,
            "schedule_start_time": "12:00",
            "schedule_end_time": "22:00",
        },
        {
            "preset_name": "Entrega",
            "color_bg": "#fcd5b5",
            "color_border": "#f97316",
            "is_default": 0,
            "require_customer": 1,
            "enable_scheduling": 1,
            "slot_interval_minutes": 20,
            "schedule_start_time": "12:00",
            "schedule_end_time": "22:00",
        },
    ]
    if frappe.db.table_exists("Restaurant Order Preset"):
        preset_meta = frappe.get_meta("Restaurant Order Preset")
        preset_fields = ["name", "preset_name", "color_bg", "color_border", "is_default"]
        for extra_pf in ("require_customer", "enable_scheduling", "slot_interval_minutes", "schedule_start_time", "schedule_end_time"):
            if preset_meta.has_field(extra_pf):
                preset_fields.append(extra_pf)
        records = frappe.get_all(
            "Restaurant Order Preset",
            filters={"enabled": 1},
            fields=preset_fields,
            order_by="idx asc, creation asc",
        )
        if records:
            for rec in records:
                if rec.preset_name in ("Para llevar", "Entrega") and not rec.get("enable_scheduling"):
                    rec["enable_scheduling"] = 1
                if rec.preset_name == "Entrega" and not rec.get("require_customer"):
                    rec["require_customer"] = 1
                rec["slot_interval_minutes"] = cint(rec.get("slot_interval_minutes") or 20)
                rec["schedule_start_time"] = cstr(rec.get("schedule_start_time") or "12:00")
                rec["schedule_end_time"] = cstr(rec.get("schedule_end_time") or "22:00")
            return records
        for p in default_presets:
            if not frappe.db.exists("Restaurant Order Preset", p["preset_name"]):
                doc_data = {
                    "doctype": "Restaurant Order Preset",
                    "preset_name": p["preset_name"],
                    "color_bg": p["color_bg"],
                    "color_border": p["color_border"],
                    "is_default": p["is_default"],
                    "enabled": 1,
                }
                if preset_meta.has_field("require_customer"):
                    doc_data["require_customer"] = p["require_customer"]
                    doc_data["enable_scheduling"] = p["enable_scheduling"]
                    doc_data["slot_interval_minutes"] = p["slot_interval_minutes"]
                    doc_data["schedule_start_time"] = p["schedule_start_time"]
                    doc_data["schedule_end_time"] = p["schedule_end_time"]
                doc = frappe.get_doc(doc_data)
                doc.insert(ignore_permissions=True)
        return frappe.get_all(
            "Restaurant Order Preset",
            filters={"enabled": 1},
            fields=preset_fields,
            order_by="idx asc, creation asc",
        )
    return default_presets
