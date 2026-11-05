"""Isolated configuration tests; no restaurant sales or stock transactions."""

from copy import deepcopy
from uuid import uuid4

import frappe
from frappe.tests.utils import FrappeTestCase

from restaurant.item_configuration import (
    get_configuration,
    save_option_group,
    save_recipe,
)


class TestItemConfiguration(FrappeTestCase):
    transaction_doctypes = (
        "Sales Invoice", "POS Invoice", "Payment Entry", "Stock Entry",
        "Stock Ledger Entry", "GL Entry",
    )
    ounce_factor = 0.028349523125

    def setUp(self):
        self.original_user = frappe.session.user
        frappe.set_user("Administrator")
        self.savepoint = "restaurant_item_configuration_test"
        frappe.db.savepoint(self.savepoint)
        self.suffix = uuid4().hex[:10]
        self.item_index = 0
        self.transaction_counts = {
            dt: frappe.db.count(dt) for dt in self.transaction_doctypes
        }
        parent_group = frappe.db.get_value(
            "Item Group", {"is_group": 1, "parent_item_group": ["is", "not set"]}, "name"
        )
        self.group = frappe.get_doc({
            "doctype": "Item Group",
            "item_group_name": "_Test Restaurant Menu " + self.suffix,
            "parent_item_group": parent_group,
            "is_group": 0,
        }).insert().name
        self.unit = self.make_uom("Unit", whole=True)
        self.weight = self.make_uom("Kg")
        self.ounce = self.make_uom("Ounce")
        self.unsupported_uom = self.make_uom("Unconverted")

    def tearDown(self):
        frappe.set_user("Administrator")
        try:
            self.assertEqual(
                {dt: frappe.db.count(dt) for dt in self.transaction_doctypes},
                self.transaction_counts,
                "Configuring a menu must not create financial or stock transactions",
            )
        finally:
            frappe.db.rollback(save_point=self.savepoint)
            frappe.clear_cache()
            frappe.set_user(self.original_user)

    def make_uom(self, label, whole=False):
        return frappe.get_doc({
            "doctype": "UOM",
            "uom_name": "_Test Restaurant " + label + " " + self.suffix,
            "must_be_whole_number": int(whole),
            "enabled": 1,
        }).insert().name

    def make_item(self, label="Dish", **values):
        self.item_index += 1
        item_code = "_Test Restaurant {} {} {}".format(label, self.suffix, self.item_index)
        payload = {
            "doctype": "Item", "item_code": item_code, "item_name": item_code,
            "item_group": self.group, "stock_uom": self.unit,
            "is_stock_item": 0, "is_sales_item": 1, "is_purchase_item": 0,
            "include_item_in_manufacturing": 0,
            "restaurant_recipe_enabled": 0, "restaurant_options_enabled": 0,
        }
        payload.update(values)
        return frappe.get_doc(payload).insert()

    def make_ingredient(self, label="Ingredient", with_ounces=True, **values):
        conversions = [{"uom": self.weight, "conversion_factor": 1}]
        if with_ounces:
            conversions.append({"uom": self.ounce, "conversion_factor": self.ounce_factor})
        payload = {
            "is_stock_item": 1, "stock_uom": self.weight,
            "uoms": conversions, "is_purchase_item": 1,
        }
        payload.update(values)
        return self.make_item(label, **payload)

    def item_modified(self, item):
        return str(frappe.db.get_value("Item", item.name, "modified"))

    def recipe_rows(self, ingredient, qty=1, uom=None):
        return [{"item_code": ingredient.name, "qty": qty, "uom": uom or self.weight}]

    def bundle_for(self, item):
        return frappe.get_doc("Product Bundle", {"new_item_code": item.name})

    def option_group(self, **values):
        group = {
            "group_name": "Acompañamiento " + self.suffix,
            "min_selections": 1, "max_selections": 1,
            "currency": "HNL", "disabled": 0,
            "options": [
                {"option_label": "Clásicas", "effect": "Solo indicación",
                 "additional_amount": 0, "is_default": 1},
                {"option_label": "Gourmet", "effect": "Solo indicación",
                 "additional_amount": 15, "is_default": 0},
            ],
        }
        group.update(values)
        return group

    def test_generic_item_remains_usable_without_restaurant_configuration(self):
        item = self.make_item("Generic")
        before = frappe.get_doc("Item", item.name).as_dict()
        configuration = get_configuration(item.name)
        self.assertFalse(configuration["item"]["restaurant_recipe_enabled"])
        self.assertFalse(configuration["item"]["restaurant_options_enabled"])
        self.assertFalse(configuration["recipe"]["exists"])
        self.assertFalse(configuration["groups"])
        self.assertEqual(frappe.get_doc("Item", item.name).as_dict(), before)
        self.assertFalse(frappe.db.exists("Product Bundle", {"new_item_code": item.name}))

    def test_recipe_normalizes_explicit_ounce_conversion_and_stays_disabled(self):
        item = self.make_item(restaurant_recipe_enabled=1)
        ingredient = self.make_ingredient()
        save_recipe(item.name, self.recipe_rows(ingredient, 8, self.ounce), self.item_modified(item))
        bundle = self.bundle_for(item)
        self.assertTrue(bundle.disabled)
        self.assertTrue(bundle.restaurant_managed)
        self.assertEqual(len(bundle.items), 1)
        row = bundle.items[0]
        self.assertEqual(row.item_code, ingredient.name)
        self.assertEqual(row.uom, self.weight)
        self.assertAlmostEqual(row.qty, 8 * self.ounce_factor, places=6)
        self.assertEqual(row.restaurant_input_uom, self.ounce)
        self.assertAlmostEqual(row.restaurant_input_factor, self.ounce_factor, places=6)
        self.assertFalse(frappe.db.get_value("Item", item.name, "is_stock_item"))
        loaded = get_configuration(item.name)["recipe"]["rows"][0]
        self.assertEqual(loaded["uom"], self.ounce)
        self.assertAlmostEqual(loaded["qty"], 8, places=5)

    def test_recipe_accepts_stock_unit_without_guessing_another_conversion(self):
        item = self.make_item(restaurant_recipe_enabled=1)
        ingredient = self.make_ingredient(with_ounces=False)
        save_recipe(item.name, self.recipe_rows(ingredient, 0.25), self.item_modified(item))
        row = self.bundle_for(item).items[0]
        self.assertEqual(row.uom, self.weight)
        self.assertAlmostEqual(row.qty, 0.25)
        self.assertAlmostEqual(row.restaurant_input_factor, 1)

    def test_missing_conversion_is_rejected_without_creating_bundle(self):
        item = self.make_item(restaurant_recipe_enabled=1)
        ingredient = self.make_ingredient(with_ounces=False)
        with self.assertRaises(frappe.ValidationError):
            save_recipe(
                item.name, self.recipe_rows(ingredient, 8, self.unsupported_uom),
                self.item_modified(item),
            )
        self.assertFalse(frappe.db.exists("Product Bundle", {"new_item_code": item.name}))

    def test_nonpositive_component_quantities_are_rejected(self):
        item = self.make_item(restaurant_recipe_enabled=1)
        ingredient = self.make_ingredient()
        for quantity in (0, -1):
            with self.subTest(quantity=quantity):
                with self.assertRaises(frappe.ValidationError):
                    save_recipe(
                        item.name, self.recipe_rows(ingredient, quantity), self.item_modified(item),
                    )
        self.assertFalse(frappe.db.exists("Product Bundle", {"new_item_code": item.name}))

    def test_stock_item_cannot_enable_restaurant_recipe(self):
        item = self.make_ingredient("Stock Parent")
        item.restaurant_recipe_enabled = 1
        with self.assertRaises(frappe.ValidationError):
            item.save()
        self.assertFalse(frappe.db.get_value("Item", item.name, "restaurant_recipe_enabled"))

    def test_recipe_requires_feature_and_stock_components(self):
        generic = self.make_item("Generic")
        ingredient = self.make_ingredient()
        with self.assertRaises(frappe.ValidationError):
            save_recipe(generic.name, self.recipe_rows(ingredient), self.item_modified(generic))
        dish = self.make_item(restaurant_recipe_enabled=1)
        nonstock_component = self.make_item("Nonstock Component")
        with self.assertRaises(frappe.ValidationError):
            save_recipe(dish.name, self.recipe_rows(nonstock_component, uom=self.unit), self.item_modified(dish))
        ingredient.disabled = 1
        ingredient.save()
        with self.assertRaises(frappe.ValidationError):
            save_recipe(dish.name, self.recipe_rows(ingredient), self.item_modified(dish))

    def test_stale_item_timestamp_cannot_overwrite_recipe(self):
        item = self.make_item(restaurant_recipe_enabled=1)
        ingredient = self.make_ingredient()
        previous = self.item_modified(item)
        item.description = "Descripción actualizada"
        item.save()
        with self.assertRaises(frappe.TimestampMismatchError):
            save_recipe(item.name, self.recipe_rows(ingredient), previous)
        self.assertFalse(frappe.db.exists("Product Bundle", {"new_item_code": item.name}))

    def test_stale_bundle_timestamp_cannot_overwrite_components(self):
        item = self.make_item(restaurant_recipe_enabled=1)
        ingredient = self.make_ingredient()
        save_recipe(item.name, self.recipe_rows(ingredient), self.item_modified(item))
        bundle = self.bundle_for(item)
        previous = str(bundle.modified)
        bundle.items[0].qty = 2
        bundle.save()
        with self.assertRaises(frappe.TimestampMismatchError):
            save_recipe(item.name, self.recipe_rows(ingredient, 3), self.item_modified(item), previous)
        self.assertEqual(self.bundle_for(item).items[0].qty, 2)

    def test_unmanaged_native_bundle_is_not_overwritten(self):
        item = self.make_item(restaurant_recipe_enabled=1)
        ingredient = self.make_ingredient()
        native = frappe.get_doc({
            "doctype": "Product Bundle", "new_item_code": item.name,
            "disabled": 1, "restaurant_managed": 0,
            "items": [{"item_code": ingredient.name, "qty": 1, "uom": self.weight}],
        }).insert()
        with self.assertRaises(frappe.ValidationError):
            save_recipe(item.name, self.recipe_rows(ingredient, 2), self.item_modified(item), str(native.modified))
        self.assertEqual(self.bundle_for(item).items[0].qty, 1)
        self.assertFalse(self.bundle_for(item).restaurant_managed)

    def test_options_can_be_configured_without_recipe_and_keep_price_choices(self):
        item = self.make_item(restaurant_options_enabled=1)
        group = self.option_group()
        save_option_group(item.name, group, self.item_modified(item))
        stored = frappe.get_doc("Restaurant Option Group", {"main_item": item.name})
        self.assertEqual(stored.min_selections, 1)
        self.assertEqual(stored.max_selections, 1)
        self.assertEqual(stored.currency, "HNL")
        self.assertEqual([row.additional_amount for row in stored.options], [0, 15])
        self.assertEqual([row.is_default for row in stored.options], [1, 0])
        self.assertFalse(frappe.db.exists("Product Bundle", {"new_item_code": item.name}))

    def test_option_selection_bounds_and_default_limits_are_enforced(self):
        item = self.make_item(restaurant_options_enabled=1)
        cases = [
            {"min_selections": -1},
            {"min_selections": 2, "max_selections": 1},
            {"min_selections": 1, "max_selections": 3},
            {"options": [
                {"option_label": "Clásicas", "effect": "Solo indicación", "is_default": 1},
                {"option_label": "Gourmet", "effect": "Solo indicación", "is_default": 1},
            ]},
        ]
        for values in cases:
            with self.subTest(values=values):
                with self.assertRaises(frappe.ValidationError):
                    save_option_group(item.name, self.option_group(**values), self.item_modified(item))
        self.assertFalse(frappe.db.exists("Restaurant Option Group", {"main_item": item.name}))

    def test_substitution_requires_a_base_recipe_component(self):
        item = self.make_item(restaurant_recipe_enabled=1, restaurant_options_enabled=1)
        original = self.make_ingredient("Original")
        replacement = self.make_ingredient("Replacement")
        unrelated = self.make_ingredient("Unrelated")
        save_recipe(item.name, self.recipe_rows(original), self.item_modified(item))
        group = self.option_group(options=[{
            "option_label": "Gourmet", "effect": "Sustituir componente",
            "item_code": replacement.name, "replaces_item": unrelated.name,
            "qty": 0.25, "uom": self.weight, "additional_amount": 15,
            "is_default": 1,
        }])
        with self.assertRaises(frappe.ValidationError):
            save_option_group(item.name, group, self.item_modified(item))
        self.assertFalse(frappe.db.exists("Restaurant Option Group", {"main_item": item.name}))
        group["options"][0]["replaces_item"] = original.name
        save_option_group(item.name, group, self.item_modified(item))
        stored = frappe.get_doc("Restaurant Option Group", {"main_item": item.name})
        self.assertEqual(stored.options[0].replaces_item, original.name)
        self.assertEqual(stored.options[0].item_code, replacement.name)
        self.assertEqual(self.bundle_for(item).items[0].item_code, original.name)
        self.assertEqual(self.bundle_for(item).items[0].qty, 1)

    def test_stale_group_timestamp_cannot_overwrite_options(self):
        item = self.make_item(restaurant_options_enabled=1)
        payload = self.option_group()
        save_option_group(item.name, payload, self.item_modified(item))
        stored = frappe.get_doc("Restaurant Option Group", {"main_item": item.name})
        stale = deepcopy(payload)
        stale.update({"name": stored.name, "modified": str(stored.modified)})
        stored.group_name = "Acompañamiento actualizado " + self.suffix
        stored.save()
        with self.assertRaises(frappe.TimestampMismatchError):
            save_option_group(item.name, stale, self.item_modified(item))
        self.assertEqual(
            frappe.db.get_value("Restaurant Option Group", stored.name, "group_name"),
            stored.group_name,
        )

    def test_option_group_cannot_be_moved_to_another_item(self):
        first = self.make_item("First Dish", restaurant_options_enabled=1)
        second = self.make_item("Second Dish", restaurant_options_enabled=1)
        payload = self.option_group()
        save_option_group(first.name, payload, self.item_modified(first))
        stored = frappe.get_doc("Restaurant Option Group", {"main_item": first.name})
        payload.update({"name": stored.name, "modified": str(stored.modified)})
        with self.assertRaises(frappe.PermissionError):
            save_option_group(second.name, payload, self.item_modified(second))
        self.assertEqual(frappe.db.get_value("Restaurant Option Group", stored.name, "main_item"), first.name)

    def test_guest_cannot_save_recipe_or_options(self):
        item = self.make_item(restaurant_recipe_enabled=1, restaurant_options_enabled=1)
        ingredient = self.make_ingredient()
        modified = self.item_modified(item)
        frappe.set_user("Guest")
        with self.assertRaises(frappe.PermissionError):
            save_recipe(item.name, self.recipe_rows(ingredient), modified)
        with self.assertRaises(frappe.PermissionError):
            save_option_group(item.name, self.option_group(), modified)

    def test_read_only_item_user_cannot_save_recipe_or_options(self):
        item = self.make_item(restaurant_recipe_enabled=1, restaurant_options_enabled=1)
        ingredient = self.make_ingredient()
        role = "_Test Restaurant Item Reader " + self.suffix
        frappe.get_doc({"doctype": "Role", "role_name": role, "desk_access": 1}).insert()
        from frappe.permissions import add_permission
        add_permission("Item", role, ptype="read")
        user_name = "restaurant-item-reader-" + self.suffix + "@example.invalid"
        frappe.get_doc({
            "doctype": "User", "email": user_name, "first_name": "Prueba",
            "send_welcome_email": 0, "roles": [{"role": role}],
        }).insert()
        modified = self.item_modified(item)
        frappe.clear_cache(doctype="Item")
        frappe.set_user(user_name)
        self.assertTrue(frappe.has_permission("Item", "read", doc=item))
        self.assertFalse(frappe.has_permission("Item", "write", doc=item))
        with self.assertRaises(frappe.PermissionError):
            save_recipe(item.name, self.recipe_rows(ingredient), modified)
        with self.assertRaises(frappe.PermissionError):
            save_option_group(item.name, self.option_group(), modified)

    def test_empty_component_unit_uses_the_stock_unit(self):
        item = self.make_item(restaurant_recipe_enabled=1)
        ingredient = self.make_ingredient()
        save_recipe(item.name, [{"item_code": ingredient.name, "qty": 2}], self.item_modified(item))
        row = self.bundle_for(item).items[0]
        self.assertEqual(row.restaurant_input_uom, self.weight)
        self.assertEqual(row.qty, 2)

    def test_turning_off_flags_preserves_saved_configuration(self):
        item = self.make_item(restaurant_recipe_enabled=1, restaurant_options_enabled=1)
        ingredient = self.make_ingredient()
        save_recipe(item.name, self.recipe_rows(ingredient), self.item_modified(item))
        save_option_group(item.name, self.option_group(), self.item_modified(item))
        bundle_before = self.bundle_for(item).as_dict()
        groups_before = frappe.get_all("Restaurant Option Group", filters={"main_item": item.name}, pluck="name")
        item.reload()
        item.restaurant_recipe_enabled = 0
        item.restaurant_options_enabled = 0
        item.save()
        self.assertEqual(self.bundle_for(item).as_dict(), bundle_before)
        self.assertEqual(frappe.get_all("Restaurant Option Group", filters={"main_item": item.name}, pluck="name"), groups_before)

    def test_referenced_component_cannot_be_removed_from_recipe(self):
        item = self.make_item(restaurant_recipe_enabled=1, restaurant_options_enabled=1)
        original = self.make_ingredient("Original")
        replacement = self.make_ingredient("Replacement")
        save_recipe(item.name, self.recipe_rows(original), self.item_modified(item))
        group = self.option_group(options=[{
            "option_label": "Alternativa", "effect": "Sustituir componente",
            "item_code": replacement.name, "replaces_item": original.name,
            "qty": 1, "uom": self.weight, "additional_amount": 0,
        }])
        save_option_group(item.name, group, self.item_modified(item))
        bundle = self.bundle_for(item)
        with self.assertRaises(frappe.ValidationError):
            save_recipe(item.name, self.recipe_rows(replacement), self.item_modified(item), str(bundle.modified))
        self.assertEqual(self.bundle_for(item).items[0].item_code, original.name)

    def test_managed_bundle_cannot_be_activated_natively(self):
        item = self.make_item(restaurant_recipe_enabled=1)
        ingredient = self.make_ingredient()
        save_recipe(item.name, self.recipe_rows(ingredient), self.item_modified(item))
        bundle = self.bundle_for(item)
        bundle.disabled = 0
        with self.assertRaises(frappe.ValidationError):
            bundle.save()
        self.assertTrue(frappe.db.get_value("Product Bundle", bundle.name, "disabled"))
        self.assertTrue(get_configuration(item.name)["recipe"]["editable"])
        self.assertEqual(self.bundle_for(item).items[0].qty, 1)

    def test_native_bundle_edit_cannot_orphan_a_substitution(self):
        item = self.make_item(restaurant_recipe_enabled=1, restaurant_options_enabled=1)
        original = self.make_ingredient("Native Original")
        replacement = self.make_ingredient("Native Replacement")
        save_recipe(item.name, self.recipe_rows(original), self.item_modified(item))
        save_option_group(item.name, self.option_group(options=[{
            "option_label": "Alternativa", "effect": "Sustituir componente",
            "item_code": replacement.name, "replaces_item": original.name,
            "qty": 1, "uom": self.weight, "additional_amount": 0,
        }]), self.item_modified(item))
        bundle = self.bundle_for(item)
        bundle.items[0].item_code = replacement.name
        with self.assertRaises(frappe.ValidationError):
            bundle.save()
        self.assertEqual(self.bundle_for(item).items[0].item_code, original.name)

    def test_catalogue_manager_with_currency_access_can_configure_options(self):
        item = self.make_item(restaurant_options_enabled=1)
        email = "item-manager-" + self.suffix + "@example.invalid"
        frappe.get_doc({"doctype": "User", "email": email, "first_name": "Prueba",
                        "send_welcome_email": 0, "roles": [{"role": "Item Manager"}, {"role": "Accounts User"}]}).insert()
        frappe.set_user(email)
        context = get_configuration(item.name)
        self.assertTrue(context["can_create_option_group"])
        context = save_option_group(item.name, self.option_group(), self.item_modified(item))
        self.assertTrue(context["groups"][0]["_can_write"])

    def test_item_manager_without_currency_access_has_no_group_write_action(self):
        item = self.make_item(restaurant_options_enabled=1)
        email = "item-only-" + self.suffix + "@example.invalid"
        frappe.get_doc({"doctype": "User", "email": email, "first_name": "Prueba",
                        "send_welcome_email": 0, "roles": [{"role": "Item Manager"}]}).insert()
        frappe.set_user(email)
        context = get_configuration(item.name)
        self.assertTrue(context["can_write"])
        self.assertFalse(context["can_create_option_group"])

    def test_native_deletion_preserves_managed_recipe(self):
        item = self.make_item(restaurant_recipe_enabled=1)
        ingredient = self.make_ingredient()
        save_recipe(item.name, self.recipe_rows(ingredient), self.item_modified(item))
        with self.assertRaises(frappe.ValidationError):
            frappe.delete_doc("Product Bundle", item.name)
        self.assertTrue(frappe.db.exists("Product Bundle", item.name))

    def test_material_options_require_native_recipe_read_permission(self):
        item = self.make_item(restaurant_recipe_enabled=1, restaurant_options_enabled=1)
        original = self.make_ingredient("Protected Original")
        replacement = self.make_ingredient("Protected Replacement")
        save_recipe(item.name, self.recipe_rows(original), self.item_modified(item))
        email = "options-only-" + self.suffix + "@example.invalid"
        frappe.get_doc({"doctype": "User", "email": email, "first_name": "Prueba",
                        "send_welcome_email": 0, "roles": [{"role": "Item Manager"}, {"role": "Accounts User"}]}).insert()
        group = self.option_group(options=[{
            "option_label": "Alternativa", "effect": "Sustituir componente",
            "item_code": replacement.name, "replaces_item": original.name,
            "qty": 1, "uom": self.weight, "additional_amount": 0,
        }])
        frappe.set_user(email)
        context = get_configuration(item.name)
        self.assertFalse(context["recipe"]["rows"])
        self.assertTrue(context["can_create_option_group"])
        with self.assertRaises(frappe.PermissionError):
            save_option_group(item.name, group, self.item_modified(item))

    def test_combo_option_group_supports_dishes_and_drinks_with_surcharges(self):
        combo = self.make_item("Burger Combo Menu", restaurant_options_enabled=1, standard_rate=10)
        cheese_burger = self.make_item("Cheese Burger", restaurant_recipe_enabled=1)
        bacon_burger = self.make_item("Bacon Burger", restaurant_recipe_enabled=1)
        water = self.make_ingredient("Water Bottle", with_ounces=False, stock_uom=self.unit, uoms=[{"uom": self.unit, "conversion_factor": 1}])
        smoothie = self.make_ingredient("Banana Smoothie", with_ounces=False, stock_uom=self.unit, uoms=[{"uom": self.unit, "conversion_factor": 1}])

        burgers_group = {
            "group_name": "Hamburguesas",
            "min_selections": 1, "max_selections": 1, "currency": "HNL", "disabled": 0,
            "options": [
                {"option_label": "Hamburguesa con queso", "effect": "Incluir en combo",
                 "item_code": cheese_burger.name, "additional_amount": 0, "is_default": 1},
                {"option_label": "Hamburguesa con tocino", "effect": "Incluir en combo",
                 "item_code": bacon_burger.name, "additional_amount": 0, "is_default": 0},
            ],
        }
        drinks_group = {
            "group_name": "Bebidas",
            "min_selections": 1, "max_selections": 1, "currency": "HNL", "disabled": 0,
            "options": [
                {"option_label": "Agua", "effect": "Incluir en combo",
                 "item_code": water.name, "qty": 1, "uom": self.unit, "additional_amount": 0, "is_default": 1},
                {"option_label": "Batido de plátano", "effect": "Incluir en combo",
                 "item_code": smoothie.name, "qty": 1, "uom": self.unit, "additional_amount": 2, "is_default": 0},
            ],
        }
        save_option_group(combo.name, burgers_group, self.item_modified(combo))
        context = save_option_group(combo.name, drinks_group, self.item_modified(combo))
        self.assertEqual(context["item"]["base_price"], 10.0)
        self.assertEqual(len(context["groups"]), 2)
        self.assertEqual(context["groups"][0]["options"][0]["item_code"], cheese_burger.name)
        self.assertEqual(context["groups"][0]["options"][0]["qty"], 1.0)
        self.assertEqual(context["groups"][1]["options"][1]["additional_amount"], 2.0)

    def test_combo_option_rejects_self_reference_or_replaces_item(self):
        combo = self.make_item("Invalid Combo", restaurant_options_enabled=1)
        dish = self.make_item("Included Dish")
        for bad_option in (
            {"option_label": "Mismo combo", "effect": "Incluir en combo", "item_code": combo.name, "additional_amount": 0},
            {"option_label": "Con reemplazo", "effect": "Incluir en combo", "item_code": dish.name, "replaces_item": dish.name, "additional_amount": 0},
            {"option_label": "Cantidad cero", "effect": "Incluir en combo", "item_code": dish.name, "qty": 0, "additional_amount": 0},
        ):
            with self.subTest(bad_option=bad_option["option_label"]):
                with self.assertRaises(frappe.ValidationError):
                    save_option_group(combo.name, self.option_group(options=[bad_option]), self.item_modified(combo))
