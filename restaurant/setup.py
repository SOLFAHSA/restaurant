"""Idempotent installation of restaurant-specific operational roles."""

import frappe


def ensure_restaurant_roles():
    """Create the role without changing existing users or business records."""
    if not frappe.db.exists("Role", "Restaurant Manager"):
        frappe.get_doc({
            "doctype": "Role", "role_name": "Restaurant Manager", "desk_access": 1,
        }).insert()


def ensure_link_permissions():
    """Install this app's select-only policy, preserving other roles' rules."""
    from frappe.permissions import add_permission, rights

    ensure_restaurant_roles()
    for doctype in ("Branch", "Employee"):
        filters = {
            "parent": doctype, "role": "Restaurant Manager", "permlevel": 0, "if_owner": 0,
        }
        permission_name = frappe.db.get_value("Custom DocPerm", filters, "name")
        if not permission_name:
            permission_name = add_permission(doctype, "Restaurant Manager", ptype="select")
        if permission_name:
            permission = frappe.get_doc("Custom DocPerm", permission_name)
            expected = {right: int(right == "select") for right in rights}
            if any(permission.get(right) != value for right, value in expected.items()):
                # Custom DocPerm has permissive defaults; explicitly zero every other right.
                permission.update(expected)
                permission.save()
            frappe.clear_cache(doctype=doctype)
