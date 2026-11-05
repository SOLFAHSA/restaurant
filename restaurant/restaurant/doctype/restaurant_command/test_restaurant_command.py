"""Isolated command configuration, native permissions and pagination tests."""

from copy import deepcopy
from uuid import uuid4

import frappe
from frappe.tests.utils import FrappeTestCase

from restaurant.commands import get_commands, get_editor_context, save_command


class TestRestaurantCommand(FrappeTestCase):
    transaction_doctypes = (
        "Sales Invoice", "POS Invoice", "Payment Entry", "Stock Entry",
        "Stock Ledger Entry", "GL Entry",
    )

    def setUp(self):
        self.original_user = frappe.session.user
        frappe.set_user("Administrator")
        self.savepoint = "restaurant_command_test"
        frappe.db.savepoint(self.savepoint)
        self.suffix = uuid4().hex[:10]
        self.transaction_counts = {
            doctype: frappe.db.count(doctype) for doctype in self.transaction_doctypes
        }
        self.branch = self.make_branch("Centro")
        self.other_branch = self.make_branch("Norte")
        root = frappe.db.get_value(
            "Item Group", {"is_group": 1, "parent_item_group": ["is", "not set"]}, "name"
        )
        self.parent_group = self.make_group("Menú", root, is_group=1)
        self.first_group = self.make_group("Cocina", self.parent_group)
        self.second_group = self.make_group("Bebidas", self.parent_group)

    def tearDown(self):
        frappe.set_user("Administrator")
        try:
            self.assertEqual(
                {doctype: frappe.db.count(doctype) for doctype in self.transaction_doctypes},
                self.transaction_counts,
                "Command configuration must not create financial or stock transactions",
            )
        finally:
            frappe.db.rollback(save_point=self.savepoint)
            frappe.clear_cache()
            frappe.set_user(self.original_user)

    def make_branch(self, label):
        return frappe.get_doc({
            "doctype": "Branch", "branch": "_Test Comandas " + label + " " + self.suffix,
        }).insert().name

    def make_group(self, label, parent, is_group=0):
        return frappe.get_doc({
            "doctype": "Item Group", "item_group_name": "_Test Comandas " + label + " " + self.suffix,
            "parent_item_group": parent, "is_group": is_group,
        }).insert().name

    def payload(self, label="Cocina", **values):
        document = {
            "command_name": label + " " + self.suffix,
            "branch": self.branch, "enabled": 1,
            "groups": [{"item_group": self.first_group}],
        }
        document.update(values)
        return document

    def make_manager(self):
        email = "restaurant-command-manager-" + self.suffix + "@example.invalid"
        frappe.get_doc({
            "doctype": "User", "email": email, "first_name": "Prueba",
            "send_welcome_email": 0,
            "roles": [{"role": "Restaurant Manager"}],
        }).insert()
        frappe.get_doc({
            "doctype": "User Permission", "user": email, "allow": "Branch",
            "for_value": self.branch, "apply_to_all_doctypes": 1,
        }).insert()
        return email

    def test_create_and_edit_preserve_selected_native_groups(self):
        created = save_command(self.payload(command_name="  Cocina " + self.suffix + "  "))
        self.assertEqual(created["command_name"], "Cocina " + self.suffix)
        self.assertEqual(created["branch"], self.branch)
        self.assertEqual(created["docstatus"], 0)
        context = get_editor_context(created["name"])
        self.assertTrue(context["can_write"])
        self.assertEqual(context["doc"]["groups"][0]["item_group"], self.first_group)
        names = {row.name for row in context["groups"]}
        self.assertTrue({self.parent_group, self.first_group, self.second_group}.issubset(names))
        changes = self.payload(
            name=created["name"], modified=str(created["modified"]),
            command_name="Barra " + self.suffix, enabled=0,
            groups=[{"item_group": self.second_group}],
        )
        updated = save_command(changes)
        self.assertEqual(updated["name"], created["name"])
        self.assertEqual(updated["enabled"], 0)
        self.assertEqual([row["item_group"] for row in updated["groups"]], [self.second_group])
        self.assertEqual(frappe.db.count("Restaurant Command", {"branch": self.branch}), 1)

    def test_opening_new_editor_does_not_save_any_document(self):
        before = frappe.db.count("Restaurant Command")
        context = get_editor_context()
        self.assertTrue(context["can_write"])
        self.assertTrue(context["doc"].get("__islocal"))
        self.assertEqual(frappe.db.count("Restaurant Command"), before)

    def test_same_group_can_be_assigned_to_multiple_commands_in_same_branch(self):
        first = save_command(self.payload("Cocina principal"))
        second = save_command(self.payload("Cocina de apoyo"))
        self.assertNotEqual(first["name"], second["name"])
        self.assertEqual(first["branch"], second["branch"])
        for document in (first, second):
            self.assertEqual(document["groups"][0]["item_group"], self.first_group)

    def test_group_assignment_is_exact_without_adding_descendants(self):
        created = save_command(self.payload(groups=[{"item_group": self.parent_group}]))
        self.assertEqual([row["item_group"] for row in created["groups"]], [self.parent_group])
        result = get_commands(search=self.suffix)
        row = next(row for row in result["items"] if row["name"] == created["name"])
        self.assertEqual(row["groups"], [self.parent_group])

    def test_duplicate_name_in_same_branch_is_rejected_but_other_branch_is_allowed(self):
        first = save_command(self.payload())
        with self.assertRaises(frappe.ValidationError):
            save_command(self.payload())
        second = save_command(self.payload(branch=self.other_branch))
        self.assertNotEqual(first["name"], second["name"])
        unchanged = save_command(self.payload(name=first["name"], modified=str(first["modified"])))
        self.assertEqual(unchanged["name"], first["name"])

    def test_stale_timestamp_cannot_overwrite_another_edit(self):
        created = save_command(self.payload())
        stale = deepcopy(created)
        current = frappe.get_doc("Restaurant Command", created["name"])
        current.command_name = "Cocina actualizada " + self.suffix
        current.save()
        stale["command_name"] = "Edición anterior " + self.suffix
        with self.assertRaises(frappe.TimestampMismatchError):
            save_command(stale)
        self.assertEqual(
            frappe.db.get_value("Restaurant Command", current.name, "command_name"),
            current.command_name,
        )

    def test_edit_requires_the_saved_timestamp(self):
        created = save_command(self.payload())
        with self.assertRaises(frappe.ValidationError):
            save_command(self.payload(name=created["name"], command_name="Sin marca de tiempo"))
        self.assertEqual(
            frappe.db.get_value("Restaurant Command", created["name"], "command_name"),
            created["command_name"],
        )

    def test_missing_repeated_or_unknown_groups_are_rejected(self):
        for groups in (
            [], None, "Cocina", [{}], [None], [{"item_group": ""}],
            [{"item_group": self.first_group}, {"item_group": self.first_group}],
            [{"item_group": "_Test Grupo inexistente " + self.suffix}],
        ):
            with self.subTest(groups=groups):
                with self.assertRaises(frappe.ValidationError):
                    save_command(self.payload(groups=groups))
        self.assertEqual(frappe.db.count("Restaurant Command", {"branch": self.branch}), 0)

    def test_name_branch_and_state_are_validated_on_server(self):
        for values in (
            {"command_name": " "}, {"command_name": "a" * 141}, {"branch": ""},
            {"branch": "_Test Sucursal inexistente " + self.suffix}, {"enabled": 2},
        ):
            with self.subTest(values=values):
                with self.assertRaises(frappe.ValidationError):
                    save_command(self.payload(**values))
        self.assertEqual(frappe.db.count("Restaurant Command", {"branch": self.branch}), 0)

    def test_native_form_cannot_bypass_duplicate_group_validation(self):
        document = frappe.get_doc({"doctype": "Restaurant Command", **self.payload(
            groups=[{"item_group": self.first_group}, {"item_group": self.first_group}],
        )})
        with self.assertRaises(frappe.ValidationError):
            document.insert()

    def test_payload_cannot_change_document_type_or_protected_fields(self):
        with self.assertRaises(frappe.ValidationError):
            save_command(self.payload(doctype="Sales Invoice"))
        for value in (None, [], "[]"):
            with self.subTest(value=value):
                with self.assertRaises(frappe.ValidationError):
                    save_command(value)
        created = save_command(self.payload(owner="Guest", docstatus=1))
        self.assertEqual(created["owner"], "Administrator")
        self.assertEqual(created["docstatus"], 0)

    def test_pages_are_stable_disjoint_and_search_matches_branch_and_name(self):
        created = [save_command(self.payload("Destino %02d" % index)) for index in range(7)]
        names = []
        for offset, expected_length, has_next in ((0, 3, True), (3, 3, True), (6, 1, False)):
            result = get_commands(search=self.suffix, start=offset, page_length=3)
            self.assertEqual(result["start"], offset)
            self.assertEqual(len(result["items"]), expected_length)
            self.assertEqual(result["has_next"], has_next)
            names.extend(row["name"] for row in result["items"])
        self.assertEqual(names, [document["name"] for document in created])
        self.assertEqual(len(set(names)), 7)
        exact = get_commands(search="Destino 04 " + self.suffix)
        self.assertEqual([row["name"] for row in exact["items"]], [created[4]["name"]])
        self.assertEqual(len(get_commands(search=self.branch, page_length=50)["items"]), 7)
        self.assertEqual(get_commands(search=self.suffix, start=100)["items"], [])
        self.assertEqual(get_commands(search="Sin coincidencias " + self.suffix)["items"], [])
        self.assertEqual(get_commands(search="%' OR 1=1 -- " + self.suffix)["items"], [])

    def test_invalid_search_and_paging_are_rejected(self):
        for arguments in (
            {"start": -1}, {"start": True}, {"start": 1.5}, {"start": "bad"},
            {"page_length": 0}, {"page_length": 51}, {"page_length": False},
            {"page_length": 2.5}, {"search": "a" * 141}, {"search": None},
            {"search": {"unexpected": "value"}},
        ):
            with self.subTest(arguments=arguments):
                with self.assertRaises(frappe.ValidationError):
                    get_commands(**arguments)

    def test_guest_cannot_list_open_create_or_edit_commands(self):
        created = save_command(self.payload())
        frappe.set_user("Guest")
        for action in (
            lambda: get_commands(search=self.suffix), lambda: get_editor_context(),
            lambda: get_editor_context(created["name"]), lambda: save_command(self.payload()),
            lambda: save_command(created),
        ):
            with self.subTest(action=action):
                with self.assertRaises(frappe.PermissionError):
                    action()

    def test_manager_branch_permission_limits_read_create_and_edit(self):
        allowed = save_command(self.payload())
        restricted = save_command(self.payload("Cocina norte", branch=self.other_branch))
        user = self.make_manager()
        frappe.set_user(user)
        self.assertTrue(frappe.has_permission("Restaurant Command", "create"))
        self.assertTrue(get_editor_context(allowed["name"])["can_write"])
        result = get_commands(search=self.suffix, page_length=50)
        self.assertEqual([row["name"] for row in result["items"]], [allowed["name"]])
        self.assertFalse(get_commands(search=self.other_branch)["items"])
        with self.assertRaises(frappe.PermissionError):
            get_editor_context(restricted["name"])
        with self.assertRaises(frappe.PermissionError):
            save_command(restricted)
        with self.assertRaises(frappe.PermissionError):
            save_command(self.payload("No permitida", branch=self.other_branch))
        saved = save_command(self.payload("Permitida"))
        self.assertEqual(saved["branch"], self.branch)
        update = self.payload(name=allowed["name"], modified=str(allowed["modified"]), enabled=0)
        self.assertEqual(save_command(update)["enabled"], 0)
