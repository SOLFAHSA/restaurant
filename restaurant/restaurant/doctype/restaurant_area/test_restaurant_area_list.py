"""Permission-aware server paging and native-LIKE-search regression tests."""

from uuid import uuid4

import frappe
from frappe.tests.utils import FrappeTestCase

from restaurant.location import get_locations


class TestRestaurantAreaList(FrappeTestCase):
    def setUp(self):
        self.original_user = frappe.session.user
        frappe.set_user("Administrator")
        self.savepoint = "restaurant_area_list_test"
        frappe.db.savepoint(self.savepoint)
        self.suffix = uuid4().hex[:10]
        self.branch = frappe.get_doc({
            "doctype": "Branch", "branch": "Lista Centro " + self.suffix,
        }).insert().name
        self.areas = []
        for index in range(25):
            self.areas.append(self.make_area("Área %02d %s" % (index, self.suffix), display_order=index % 3))

    def tearDown(self):
        frappe.set_user("Administrator")
        frappe.db.rollback(save_point=self.savepoint)
        frappe.clear_cache(doctype="Restaurant Area")
        frappe.set_user(self.original_user)

    def make_area(self, area_name, **values):
        doc = frappe.new_doc("Restaurant Area")
        doc.update({"area_name": area_name, "branch": self.branch, "capacity": 24})
        doc.update(values)
        return doc.insert()

    def make_reader(self, restricted_branch=None):
        role = "Restaurant List Reader " + self.suffix
        frappe.get_doc({"doctype": "Role", "role_name": role, "desk_access": 1}).insert()
        from frappe.permissions import add_permission
        add_permission("Restaurant Area", role, ptype="read")
        frappe.clear_cache(doctype="Restaurant Area")
        user = "restaurant-list-" + self.suffix + "@example.invalid"
        frappe.get_doc({
            "doctype": "User", "email": user, "first_name": "Prueba",
            "send_welcome_email": 0, "roles": [{"role": role}],
        }).insert()
        if restricted_branch:
            frappe.get_doc({
                "doctype": "User Permission", "user": user, "allow": "Branch",
                "for_value": restricted_branch, "apply_to_all_doctypes": 1,
            }).insert()
        return user

    def test_pages_are_stable_disjoint_and_bounded(self):
        names = []
        for offset, expected_length, has_next in [(0, 7, True), (7, 7, True), (14, 7, True), (21, 4, False)]:
            result = get_locations(search=self.suffix, start=offset, page_length=7)
            self.assertEqual(result["start"], offset)
            self.assertEqual(result["page_length"], 7)
            self.assertEqual(len(result["items"]), expected_length)
            self.assertEqual(result["has_next"], has_next)
            names.extend(row.name for row in result["items"])
        expected = [doc.name for doc in sorted(self.areas, key=lambda doc: (doc.display_order, doc.area_name, doc.name))]
        self.assertEqual(names, expected)
        self.assertEqual(len(set(names)), 25)
        self.assertEqual([row.name for row in get_locations(self.suffix, 0, 7)["items"]], names[:7])

    def test_name_branch_and_empty_search(self):
        result = get_locations(search="Área 17 " + self.suffix, page_length=12)
        self.assertEqual([row.name for row in result["items"]], [self.areas[17].name])
        branch_page = get_locations(search=self.branch, page_length=50)
        self.assertEqual(len(branch_page["items"]), 25)
        self.assertFalse(branch_page["has_next"])
        empty = get_locations(search="Sin coincidencias " + self.suffix)
        self.assertEqual(empty["items"], [])
        self.assertFalse(empty["has_next"])
        past_end = get_locations(search=self.suffix, start=100)
        self.assertEqual(past_end["items"], [])
        self.assertFalse(past_end["has_next"])

    def test_special_search_values_use_safe_native_like_semantics(self):
        percent = self.make_area("100%" + self.suffix)
        percent_alternate = self.make_area("100x" + self.suffix)
        result = get_locations(search="100%" + self.suffix)
        self.assertEqual({row.name for row in result["items"]}, {percent.name, percent_alternate.name})
        underscore = self.make_area("Patio_1" + self.suffix)
        underscore_alternate = self.make_area("PatioX1" + self.suffix)
        result = get_locations(search="Patio_1" + self.suffix)
        self.assertEqual({row.name for row in result["items"]}, {underscore.name, underscore_alternate.name})
        quote = self.make_area("O'Hara " + self.suffix)
        self.assertEqual([row.name for row in get_locations(search="O'Hara " + self.suffix)["items"]], [quote.name])
        injection = get_locations(search="%' OR 1=1 -- " + self.suffix)
        self.assertEqual(injection["items"], [])

    def test_invalid_paging_parameters_are_rejected(self):
        for arguments in (
            {"start": -1}, {"start": 1.5}, {"start": True}, {"start": "bad"},
            {"page_length": 0}, {"page_length": 51}, {"page_length": 2.5},
            {"page_length": False}, {"search": "a" * 141}, {"search": {"unexpected": "value"}},
        ):
            with self.subTest(arguments=arguments):
                with self.assertRaises(frappe.ValidationError):
                    get_locations(**arguments)

    def test_guest_cannot_list(self):
        frappe.set_user("Guest")
        with self.assertRaises(frappe.PermissionError):
            get_locations(search=self.suffix)

    def test_read_only_user_can_list(self):
        user = self.make_reader()
        frappe.set_user(user)
        self.assertFalse(frappe.has_permission("Restaurant Area", "create"))
        self.assertEqual(len(get_locations(search=self.suffix, page_length=50)["items"]), 25)

    def test_search_and_paging_respect_branch_user_permission(self):
        other_branch = frappe.get_doc({
            "doctype": "Branch", "branch": "Lista Restringida " + self.suffix,
        }).insert().name
        restricted = self.make_area("Área restringida " + self.suffix, branch=other_branch)
        user = self.make_reader(restricted_branch=self.branch)
        frappe.set_user(user)
        result = get_locations(search=self.suffix, page_length=50)
        self.assertEqual(len(result["items"]), 25)
        self.assertFalse(result["has_next"])
        self.assertNotIn(restricted.name, [row.name for row in result["items"]])
        wildcard_page = get_locations(search="%", page_length=50)
        self.assertEqual(len(wildcard_page["items"]), 25)
        self.assertNotIn(restricted.name, [row.name for row in wildcard_page["items"]])
        forbidden_search = get_locations(search=other_branch)
        self.assertEqual(forbidden_search["items"], [])
        self.assertFalse(forbidden_search["has_next"])
