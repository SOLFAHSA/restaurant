"""Idempotent installation of restaurant-specific operational roles."""

import frappe


def ensure_restaurant_roles():
    """Create the operational roles without changing existing users or business records."""
    for role_name in ("Restaurant Manager", "Restaurant User"):
        if not frappe.db.exists("Role", role_name):
            frappe.get_doc({
                "doctype": "Role", "role_name": role_name, "desk_access": 1,
            }).insert()


def ensure_link_permissions():
    """Install this app's select-only policy, preserving other roles' rules."""
    from frappe.permissions import add_permission, rights

    ensure_restaurant_roles()
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
