"""Idempotent installation of restaurant-specific operational roles."""

import frappe


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
    ensure_restaurant_role_profiles()
    ensure_waiter_module_profile()
    ensure_cash_denominations()
    sync_restaurant_dashboard_block()


def ensure_cashier_permissions():
    """Ensure Restaurant Cashier and Restaurant Direct Cashier have DB permissions for POS, customers, shifts, and reports."""
    from frappe.permissions import add_permission

    cashier_matrix = {
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
    """Seed default Honduras HNL bill denominations if Restaurant Cash Denomination is empty."""
    if not frappe.db.exists("DocType", "Restaurant Cash Denomination"):
        return
    if frappe.db.count("Restaurant Cash Denomination") > 0:
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
    )
    for label, dtype, val, order in defaults:
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
        for row in rows:
            block_name = row.get("name")
            if block_name and frappe.db.exists("Custom HTML Block", block_name):
                frappe.db.set_value(
                    "Custom HTML Block",
                    block_name,
                    {
                        "html": row.get("html") or "",
                        "script": row.get("script") or "",
                        "style": row.get("style") or "",
                    },
                    update_modified=False,
                )
        frappe.clear_cache(doctype="Custom HTML Block")
    except Exception:
        pass

