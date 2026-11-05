// Copyright (c) 2026, Grintsys and contributors
// For license information, please see license.txt

frappe.ui.form.on("Restaurant Table", {
	refresh(frm) {
		if (frm.doc.restaurant_area) {
			frm.add_custom_button(__("Abrir mapa de mesas"), () => {
				frappe.set_route("restaurant-table-map", frm.doc.restaurant_area);
			});
			frm.add_custom_button(__("Ver área"), () => {
				frappe.set_route("restaurant-location", frm.doc.restaurant_area);
			});
		}
	},

	restaurant_area(frm) {
		if (!frm.doc.restaurant_area) {
			frm.set_value("branch", "");
			return;
		}
		frappe.db.get_value("Restaurant Area", frm.doc.restaurant_area, "branch").then((res) => {
			if (res && res.message) {
				frm.set_value("branch", res.message.branch || "");
			}
		});
	},
});

