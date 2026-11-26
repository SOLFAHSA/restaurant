"""Idempotent installation of restaurant-specific operational roles."""

import frappe
from frappe import _


def ensure_restaurant_roles():
    """Create the operational roles without changing existing users or business records."""
    for role_name in ("Restaurant Manager", "Restaurant Cashier", "Restaurant Direct Cashier", "Restaurant User"):
        if not frappe.db.exists("Role", role_name):
            frappe.get_doc({
                "doctype": "Role", "role_name": role_name, "desk_access": 1,
            }).insert()


def ensure_employee_pos_fields():
    """Ensure encrypted POS PIN custom field exists on Employee for waiters and supervisors."""
    if not frappe.db.exists("DocType", "Custom Field"):
        return
    custom_fields = [
        {
            "name": "Employee-restaurant_pos_section",
            "dt": "Employee",
            "fieldname": "restaurant_pos_section",
            "fieldtype": "Section Break",
            "label": "Acceso POS Restaurante",
            "insert_after": "user_id",
            "collapsible": 0,
        },
        {
            "name": "Employee-restaurant_pos_pin",
            "dt": "Employee",
            "fieldname": "restaurant_pos_pin",
            "fieldtype": "Password",
            "label": "PIN / Clave POS Restaurante",
            "description": "Clave numérica o PIN cifrado para desbloquear cuentas de mesero o autorizar acciones como supervisor.",
            "insert_after": "restaurant_pos_section",
        },
    ]
    for cf in custom_fields:
        if not frappe.db.exists("Custom Field", cf["name"]):
            doc = frappe.get_doc({"doctype": "Custom Field", **cf})
            doc.insert(ignore_permissions=True)
    frappe.clear_cache(doctype="Employee")


def ensure_link_permissions():
    """Install this app's select-only policy, preserving other roles' rules."""
    from frappe.permissions import add_permission, rights

    ensure_restaurant_roles()
    ensure_employee_pos_fields()
    for role_name in ("Restaurant Manager", "Restaurant User"):
        for doctype in ("Branch", "Employee", "Item Group"):
            filters = {
                "parent": doctype, "role": role_name, "permlevel": 0, "if_owner": 0,
            }
            permission_name = frappe.db.get_value("Custom DocPerm", filters, "name")
            if not permission_name:
                permission_name = add_permission(doctype, role_name, ptype="select")
            if permission_name:
                permission = frappe.get_doc("Custom DocPerm", permission_name)
                expected = {right: int(right == "select") for right in rights}
                if any(permission.get(right) != value for right, value in expected.items()):
                    # Custom DocPerm has permissive defaults; explicitly zero every other right.
                    permission.update(expected)
                    permission.save()
                frappe.clear_cache(doctype=doctype)
    ensure_cashier_permissions()
    ensure_restaurant_operational_permissions()
    ensure_pos_profile_branch_field()
    ensure_cash_denominations()
    ensure_sar_print_and_fields()
    backfill_historical_branches()
    ensure_restaurant_role_profiles()
    ensure_waiter_module_profile()


def ensure_pos_profile_branch_field():
    """Ensure POS Profile has an explicit Link field to Branch for multi-branch scoping."""
    if not frappe.db.exists("DocType", "Custom Field") or not frappe.db.exists("DocType", "POS Profile"):
        return
    if not frappe.db.exists("Custom Field", "POS Profile-branch"):
        frappe.get_doc({
            "doctype": "Custom Field",
            "name": "POS Profile-branch",
            "dt": "POS Profile",
            "fieldname": "branch",
            "fieldtype": "Link",
            "options": "Branch",
            "label": "Sucursal",
            "insert_after": "company",
            "search_index": 1,
        }).insert(ignore_permissions=True)
        frappe.clear_cache(doctype="POS Profile")


def ensure_restaurant_operational_permissions():
    """Keep Custom DocPerm in sync when custom rules exist for KDS and POS operational DocTypes."""
    if not frappe.db.exists("DocType", "Custom DocPerm"):
        return
    targets = [
        ("Restaurant Preparation Display", "Restaurant User", {"read": 1, "select": 1}),
        ("Restaurant Preparation Display", "Restaurant Cashier", {"read": 1, "select": 1}),
        ("Restaurant Preparation Stage", "Restaurant User", {"read": 1, "select": 1}),
        ("Restaurant Preparation Stage", "Restaurant Cashier", {"read": 1, "select": 1}),
        ("Restaurant Order", "Restaurant Cashier", {
            "read": 1, "write": 1, "create": 1, "delete": 0, "print": 1, "select": 1, "report": 1,
        }),
    ]
    for doctype, role_name, grants in targets:
        if not frappe.db.exists("DocType", doctype) or not frappe.db.exists("Role", role_name):
            continue
        if not frappe.db.exists("Custom DocPerm", {"parent": doctype}):
            continue
        existing = frappe.db.get_value(
            "Custom DocPerm",
            {"parent": doctype, "role": role_name, "permlevel": 0, "if_owner": 0},
            "name",
        )
        if existing:
            perm_doc = frappe.get_doc("Custom DocPerm", existing)
            changed = False
            for key, val in grants.items():
                if int(perm_doc.get(key) or 0) != int(val):
                    perm_doc.set(key, val)
                    changed = True
            if changed:
                perm_doc.save(ignore_permissions=True)
        else:
            frappe.get_doc({
                "doctype": "Custom DocPerm",
                "parent": doctype,
                "parenttype": "DocType",
                "parentfield": "permissions",
                "role": role_name,
                "permlevel": 0,
                **grants,
            }).insert(ignore_permissions=True)
        frappe.clear_cache(doctype=doctype)
    ensure_sar_print_and_fields()
    ensure_cash_denominations()
    sync_restaurant_dashboard_block()


def ensure_cashier_permissions():
    """Ensure Restaurant Cashier and Restaurant Direct Cashier have DB permissions for POS, customers, shifts, and reports."""
    from frappe.permissions import add_permission

    # SAR series control records are created by Grintsys ERPNext itself; their permission fix
    # belongs to erpnext14 (docs/qa/reporte-grintsys-permisos-serie-sar.md), not to this app.
    cashier_matrix = {
        "Restaurant Manager": {
            "POS Opening Shift": {"read": 1, "write": 1, "create": 1, "submit": 1},
            "POS Closing Shift": {"read": 1, "write": 1, "create": 1, "submit": 1},
            "Sales Invoice": {"read": 1, "write": 1, "create": 1, "submit": 1, "cancel": 1, "report": 1, "print": 1},
            "Restaurant Cash Count": {"read": 1, "write": 1, "create": 1, "submit": 1, "cancel": 1, "print": 1},
        },
        "Restaurant User": {
            "Customer": {"read": 1, "select": 1},
            "Restaurant Order": {"read": 1, "write": 1, "create": 1, "print": 1, "select": 1, "report": 1, "delete": 0},
            "Restaurant Table": {"read": 1, "select": 1},
            "Restaurant Area": {"read": 1, "select": 1},
        },
        "Restaurant Cashier": {
            "Customer": {"read": 1, "write": 1, "create": 1, "select": 1, "report": 1},
            "Sales Invoice": {"read": 1, "report": 1, "print": 1},
            "Restaurant Order": {"read": 1, "write": 1, "create": 1, "select": 1, "report": 1, "print": 1},
            "Restaurant Table": {"read": 1, "select": 1},
            "Restaurant Area": {"read": 1, "select": 1},
            "Restaurant Command": {"read": 1, "select": 1},
            "Restaurant Command Group": {"read": 1, "select": 1},
            "Restaurant Preparation Display": {"read": 1, "select": 1},
            "Restaurant Preparation Ticket": {"read": 1, "write": 0, "select": 1},
            "Restaurant Preparation Stage": {"read": 1, "select": 1},
            "Restaurant Cash Count": {"read": 1, "write": 1, "create": 1, "submit": 1, "print": 1},
            "POS Opening Shift": {"read": 1, "write": 1, "create": 1, "submit": 1},
            "POS Closing Shift": {"read": 1, "write": 1, "create": 1, "submit": 1},
        },
        "Restaurant Direct Cashier": {
            "Customer": {"read": 1, "write": 1, "create": 1, "select": 1, "report": 1},
            "Sales Invoice": {"read": 1, "report": 1, "print": 1},
            "Restaurant Order": {"read": 1, "write": 1, "create": 1, "select": 1, "report": 1, "print": 1},
            "Restaurant Cash Count": {"read": 1, "write": 1, "create": 1, "submit": 1, "print": 1},
            "POS Opening Shift": {"read": 1, "write": 1, "create": 1, "submit": 1},
            "POS Closing Shift": {"read": 1, "write": 1, "create": 1, "submit": 1},
        },
    }
    for role_name, doctypes in cashier_matrix.items():
        if not frappe.db.exists("Role", role_name):
            continue
        for doctype, expected in doctypes.items():
            if not frappe.db.exists("DocType", doctype):
                continue
            filters = {"parent": doctype, "role": role_name, "permlevel": 0, "if_owner": 0}
            perm_name = frappe.db.get_value("Custom DocPerm", filters, "name")
            if not perm_name:
                perm_name = add_permission(doctype, role_name, ptype="read")
            if perm_name:
                perm_doc = frappe.get_doc("Custom DocPerm", perm_name)
                changed = False
                for right, val in expected.items():
                    if perm_doc.get(right) != val:
                        perm_doc.set(right, val)
                        changed = True
                if changed:
                    perm_doc.save()
                frappe.clear_cache(doctype=doctype)

    if frappe.db.exists("Page", "restaurant-commands") and frappe.db.exists("Role", "Restaurant Cashier"):
        cmd_page = frappe.get_doc("Page", "restaurant-commands")
        if "Restaurant Cashier" not in {r.role for r in (cmd_page.roles or [])}:
            cmd_page.append("roles", {"role": "Restaurant Cashier"})
            cmd_page.save(ignore_permissions=True)

    if frappe.db.exists("DocType", "Custom Role") and frappe.db.exists("Role", "Restaurant Cashier"):
        for rpt_name in ("Sales Analytics", "Sales Register", "Item-wise Sales Register"):
            if not frappe.db.exists("Report", rpt_name):
                continue
            cr_name = frappe.db.get_value("Custom Role", {"report": rpt_name}, "name")
            if cr_name:
                cr_doc = frappe.get_doc("Custom Role", cr_name)
                if "Restaurant Cashier" not in {r.role for r in (cr_doc.roles or [])}:
                    cr_doc.append("roles", {"role": "Restaurant Cashier"})
                    cr_doc.save(ignore_permissions=True)
            else:
                rpt_doc = frappe.get_doc("Report", rpt_name)
                roles_list = [{"role": r.role} for r in (rpt_doc.roles or [])]
                if "Restaurant Cashier" not in {r["role"] for r in roles_list}:
                    roles_list.append({"role": "Restaurant Cashier"})
                frappe.get_doc({
                    "doctype": "Custom Role",
                    "report": rpt_name,
                    "roles": roles_list,
                }).insert(ignore_permissions=True)


def ensure_restaurant_role_profiles():
    """Create ready-to-assign Spanish Role Profiles for Restaurant staff."""
    if not frappe.db.exists("DocType", "Role Profile"):
        return
    profiles = {
        "Mesero (Salón)": ["Restaurant User"],
        "Cajero (Completo)": ["Restaurant User", "Restaurant Cashier"],
        "Cajero (Facturación Directa)": ["Restaurant Cashier", "Restaurant Direct Cashier"],
        "Supervisor de Restaurante": ["Restaurant Manager", "Restaurant User"],
    }
    for profile_name, role_list in profiles.items():
        if frappe.db.exists("Role Profile", profile_name):
            continue
        valid_roles = [{"role": r} for r in role_list if frappe.db.exists("Role", r)]
        if not valid_roles:
            continue
        frappe.get_doc({
            "doctype": "Role Profile",
            "role_profile": profile_name,
            "roles": valid_roles,
        }).insert(ignore_permissions=True)


def ensure_waiter_module_profile():
    """Keep Desk sidebar minimal per staff profile (waiters: Inicio/Restaurante/Sitio Web; cashiers: Restaurante only)."""
    if not frappe.db.exists("DocType", "Module Profile"):
        return
    all_modules = frappe.get_all("Module Def", pluck="name")
    profile_allowed_map = {
        "Mesero (Salón)": {"Restaurant", "Website", "Setup"},
        "Cajero (Completo)": {"Restaurant"},
        "Cajero (Facturación Directa)": {"Restaurant"},
    }

    for profile_name, allowed_modules in profile_allowed_map.items():
        blocked_rows = [{"module": m} for m in sorted(all_modules) if m not in allowed_modules]
        if frappe.db.exists("Module Profile", profile_name):
            mp = frappe.get_doc("Module Profile", profile_name)
            existing = {r.module for r in (mp.block_modules or [])}
            target = {r["module"] for r in blocked_rows}
            if existing != target:
                mp.set("block_modules", blocked_rows)
                mp.save(ignore_permissions=True)
        else:
            frappe.get_doc({
                "doctype": "Module Profile",
                "module_profile_name": profile_name,
                "block_modules": blocked_rows,
            }).insert(ignore_permissions=True)

    # ERPNext Settings shares module 'Setup' with Home (Inicio); restrict it to System Manager.
    if frappe.db.exists("Workspace", "ERPNext Settings"):
        ws = frappe.get_doc("Workspace", "ERPNext Settings")
        if not ws.roles and frappe.db.exists("Role", "System Manager"):
            ws.append("roles", {"role": "System Manager"})
            ws.save(ignore_permissions=True)

    for profile_name in profile_allowed_map:
        staff_users = frappe.get_all(
            "User",
            filters={"role_profile_name": profile_name, "enabled": 1},
            fields=["name", "module_profile"],
        )
        for row in staff_users:
            if row.module_profile != profile_name:
                u = frappe.get_doc("User", row.name)
                u.module_profile = profile_name
                u.save(ignore_permissions=True)
                frappe.clear_cache(user=row.name)


def ensure_cash_denominations():
    """Seed default Honduras HNL bill and coin denominations idempotently."""
    if not frappe.db.exists("DocType", "Restaurant Cash Denomination"):
        return
    defaults = (
        ("Billetes L 500", "Billete", 500.0, 10),
        ("Billetes L 200", "Billete", 200.0, 20),
        ("Billetes L 100", "Billete", 100.0, 30),
        ("Billetes L 50", "Billete", 50.0, 40),
        ("Billetes L 20", "Billete", 20.0, 50),
        ("Billetes L 10", "Billete", 10.0, 60),
        ("Billetes L 5", "Billete", 5.0, 70),
        ("Billetes L 2", "Billete", 2.0, 80),
        ("Billetes L 1", "Billete", 1.0, 90),
        ("Moneda L 0.50", "Moneda", 0.50, 100),
        ("Moneda L 0.20", "Moneda", 0.20, 110),
        ("Moneda L 0.10", "Moneda", 0.10, 120),
        ("Moneda L 0.05", "Moneda", 0.05, 130),
    )
    for label, dtype, val, order in defaults:
        if frappe.db.exists("Restaurant Cash Denomination", {"denomination_label": label}):
            continue
        frappe.get_doc({
            "doctype": "Restaurant Cash Denomination",
            "denomination_label": label,
            "currency": "HNL",
            "denomination_type": dtype,
            "unit_value": val,
            "sort_order": order,
            "enabled": 1,
        }).insert(ignore_permissions=True)


def sync_restaurant_dashboard_block(bootinfo=None):
    """Keep the Restaurant Dashboard Custom HTML Block in sync with the versioned fixture."""
    import json
    import os

    if not frappe.db.exists("DocType", "Custom HTML Block"):
        return
    fixture_path = os.path.join(
        os.path.dirname(__file__), "fixtures", "custom_html_block.json"
    )
    if not os.path.exists(fixture_path):
        return
    try:
        with open(fixture_path, encoding="utf-8") as f:
            rows = json.load(f)
        updated_any = False
        for row in rows:
            block_name = row.get("name")
            if not block_name or not frappe.db.exists("Custom HTML Block", block_name):
                continue
            target_html = row.get("html") or ""
            target_script = row.get("script") or ""
            target_style = row.get("style") or ""
            current = frappe.db.get_value(
                "Custom HTML Block",
                block_name,
                ["html", "script", "style"],
                as_dict=True,
            ) or {}
            if (
                (current.get("html") or "") == target_html
                and (current.get("script") or "") == target_script
                and (current.get("style") or "") == target_style
            ):
                continue
            frappe.db.set_value(
                "Custom HTML Block",
                block_name,
                {
                    "html": target_html,
                    "script": target_script,
                    "style": target_style,
                },
                update_modified=False,
            )
            updated_any = True
        if updated_any:
            frappe.clear_cache(doctype="Custom HTML Block")
    except Exception:
        pass


def ensure_sar_print_and_fields():
    """Ensure Sales Invoice restaurant traceability fields and exact SAR centavos defaults exist."""
    if frappe.db.exists("DocType", "Custom Field") and frappe.db.exists("DocType", "Sales Invoice"):
        si_meta = frappe.get_meta("Sales Invoice")
        anchor = "posa_notes" if si_meta.has_field("posa_notes") else "remarks"
        cf_defs = [
            {
                "name": "Sales Invoice-restaurant_section",
                "dt": "Sales Invoice",
                "fieldname": "restaurant_section",
                "fieldtype": "Section Break",
                "label": "Restaurante LEAF",
                "insert_after": anchor,
                "collapsible": 1,
            },
            {
                "name": "Sales Invoice-restaurant_order",
                "dt": "Sales Invoice",
                "fieldname": "restaurant_order",
                "fieldtype": "Link",
                "label": "Orden de Restaurante",
                "options": "Restaurant Order",
                "insert_after": "restaurant_section",
                "read_only": 1,
                "no_copy": 1,
            },
            {
                "name": "Sales Invoice-restaurant_order_number",
                "dt": "Sales Invoice",
                "fieldname": "restaurant_order_number",
                "fieldtype": "Data",
                "label": "Número de Orden",
                "insert_after": "restaurant_order",
                "read_only": 1,
                "no_copy": 1,
            },
            {
                "name": "Sales Invoice-restaurant_table_label",
                "dt": "Sales Invoice",
                "fieldname": "restaurant_table_label",
                "fieldtype": "Data",
                "label": "Mesa",
                "insert_after": "restaurant_order_number",
                "read_only": 1,
                "no_copy": 1,
            },
            {
                "name": "Sales Invoice-restaurant_service_type",
                "dt": "Sales Invoice",
                "fieldname": "restaurant_service_type",
                "fieldtype": "Data",
                "label": "Modalidad de Servicio",
                "insert_after": "restaurant_table_label",
                "read_only": 1,
                "no_copy": 1,
            },
            {
                "name": "Sales Invoice-restaurant_waiter_name",
                "dt": "Sales Invoice",
                "fieldname": "restaurant_waiter_name",
                "fieldtype": "Data",
                "label": "Atendido por",
                "insert_after": "restaurant_service_type",
                "read_only": 1,
                "no_copy": 1,
            },
        ]
        changed = False
        for cf in cf_defs:
            if not frappe.db.exists("Custom Field", cf["name"]):
                frappe.get_doc({"doctype": "Custom Field", **cf}).insert(ignore_permissions=True)
                changed = True
        if changed:
            frappe.clear_cache(doctype="Sales Invoice")

    # Disable automatic whole-unit rounding for exact Honduras SAR Lempiras with centavos.
    if frappe.db.exists("DocType", "Restaurant Settings"):
        try:
            current_val = frappe.db.get_single_value("Restaurant Settings", "enable_rounded_total")
            if current_val in (1, "1"):
                frappe.db.set_value("Restaurant Settings", None, "enable_rounded_total", 0)
        except Exception:
            pass

    # POS Profiles are never touched by a migration: other modules (POS Awesome retail, hospital...)
    # share them. Restaurant defaults are applied only by apply_restaurant_pos_profile_defaults().


RESTAURANT_TICKET = "Ticket Restaurant"


@frappe.whitelist(methods=["POST"])
def apply_restaurant_pos_profile_defaults(pos_profile):
    """Explicit administrator action: prepare one POS Profile for restaurant SAR tickets.

    Sets exact centavos (no whole-unit rounding) and the restaurant thermal ticket only on the
    requested profile, never on the other POS Profiles of the site.
    """
    frappe.only_for(("System Manager", "Restaurant Manager"))
    return set_restaurant_pos_profile_defaults(pos_profile)


def set_restaurant_pos_profile_defaults(pos_profile):
    if not pos_profile or not frappe.db.exists("POS Profile", pos_profile):
        frappe.throw(_("El perfil de Punto de Venta {0} no existe.").format(pos_profile))
    updates = {"disable_rounded_total": 1}
    if frappe.db.exists("Print Format", RESTAURANT_TICKET):
        updates["print_format"] = RESTAURANT_TICKET
    frappe.db.set_value("POS Profile", pos_profile, updates)
    return updates


def backfill_historical_branches():
    """Backfill Branch on historical Restaurant Orders and Cash Counts after schema migration."""
    try:
        if frappe.db.has_column("Restaurant Order", "branch"):
            if frappe.db.has_column("Restaurant Table", "branch"):
                frappe.db.sql(
                    """
                    UPDATE `tabRestaurant Order` ord
                    INNER JOIN `tabRestaurant Table` tbl ON tbl.name = ord.restaurant_table
                    SET ord.branch = tbl.branch
                    WHERE (ord.branch IS NULL OR ord.branch = '')
                      AND tbl.branch IS NOT NULL AND tbl.branch != ''
                    """
                )
            if frappe.db.has_column("Restaurant Area", "branch"):
                frappe.db.sql(
                    """
                    UPDATE `tabRestaurant Order` ord
                    INNER JOIN `tabRestaurant Area` area ON area.name = ord.restaurant_area
                    SET ord.branch = area.branch
                    WHERE (ord.branch IS NULL OR ord.branch = '')
                      AND area.branch IS NOT NULL AND area.branch != ''
                    """
                )
            if frappe.db.has_column("POS Profile", "branch"):
                frappe.db.sql(
                    """
                    UPDATE `tabRestaurant Order` ord
                    INNER JOIN `tabPOS Profile` prof ON prof.name = ord.pos_profile
                    SET ord.branch = prof.branch
                    WHERE (ord.branch IS NULL OR ord.branch = '')
                      AND prof.branch IS NOT NULL AND prof.branch != ''
                    """
                )
        if frappe.db.has_column("Restaurant Cash Count", "branch") and frappe.db.has_column("POS Profile", "branch"):
            frappe.db.sql(
                """
                UPDATE `tabRestaurant Cash Count` rcc
                INNER JOIN `tabPOS Profile` prof ON prof.name = rcc.pos_profile
                SET rcc.branch = prof.branch
                WHERE (rcc.branch IS NULL OR rcc.branch = '')
                  AND prof.branch IS NOT NULL AND prof.branch != ''
                """
            )
    except Exception:
        pass


