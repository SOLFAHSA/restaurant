// Copyright (c) 2026, Grintsys and contributors
// For license information, please see license.txt

frappe.ui.form.on("Restaurant Cash Count", {
	setup(frm) {
		frm.set_query("pos_opening_shift", () => ({
			filters: {
				docstatus: 1,
			},
		}));
	},

	refresh(frm) {
		if (frm.doc.docstatus === 0 && frm.doc.pos_opening_shift) {
			frm.add_custom_button(__("Cargar datos del turno"), () => {
				frm.trigger("load_shift_preview");
			});
		}

		if (!frm.is_new()) {
			frm.add_custom_button(
				__("Imprimir Ticket (80mm)"),
				() => frm.events.open_print_format(frm, "Arqueo de Caja - Ticket 80mm"),
				__("Imprimir")
			);
			frm.add_custom_button(
				__("Imprimir Tamaño Carta"),
				() => frm.events.open_print_format(frm, "Arqueo de Caja - Carta"),
				__("Imprimir")
			);
		}
	},

	pos_opening_shift(frm) {
		if (frm.doc.docstatus === 0 && frm.doc.pos_opening_shift) {
			frm.trigger("load_shift_preview");
		}
	},

	load_shift_preview(frm) {
		if (!frm.doc.pos_opening_shift) return;
		frappe.call({
			method: "restaurant.cash_count.get_cash_count_preview",
			args: { pos_opening_shift: frm.doc.pos_opening_shift },
			freeze: true,
			freeze_message: __("Consultando datos del turno..."),
			callback(r) {
				const data = r.message;
				if (!data) return;

				frm.set_value("pos_profile", data.pos_profile);
				frm.set_value("company", data.company);
				frm.set_value("currency", data.currency);
				frm.set_value("cashier", data.cashier);
				frm.set_value("cashier_name", data.cashier_name);
				frm.set_value("invoice_count", data.invoice_count);
				frm.set_value("total_sales", data.total_sales);
				frm.set_value("total_income", data.total_income);
				frm.set_value("total_expense", data.total_expense);
				frm.set_value("net_cash_movement", data.net_cash_movement);
				frm.set_value("total_expected", data.total_expected);

				if (!(frm.doc.denominations || []).length) {
					(data.denominations || []).forEach((row) => {
						const child = frm.add_child("denominations");
						child.denomination_type = row.denomination_type;
						child.unit_value = row.unit_value;
						child.denomination_label = row.denomination_label;
						child.quantity = 0;
						child.subtotal = 0;
					});
					frm.refresh_field("denominations");
				}

				const existingByMop = {};
				(frm.doc.payment_methods || []).forEach((row) => {
					if (row.mode_of_payment) {
						existingByMop[row.mode_of_payment] = {
							counted_amount: row.counted_amount,
							reference_note: row.reference_note,
						};
					}
				});

				frm.clear_table("payment_methods");
				(data.payment_methods || []).forEach((row) => {
					const prev = existingByMop[row.mode_of_payment] || {};
					const child = frm.add_child("payment_methods");
					child.mode_of_payment = row.mode_of_payment;
					child.opening_amount = row.opening_amount;
					child.sales_amount = row.sales_amount;
					child.income_amount = row.income_amount;
					child.expense_amount = row.expense_amount;
					child.expected_amount = row.expected_amount;
					child.counted_amount = flt(prev.counted_amount || 0);
					child.difference = flt(child.counted_amount - child.expected_amount);
					child.reference_note = prev.reference_note || "";
				});
				frm.refresh_field("payment_methods");

				frm.clear_table("cash_movements");
				(data.movements || []).forEach((mv) => {
					const child = frm.add_child("cash_movements");
					child.cash_movement_ref = mv.name;
					child.movement_type = mv.type_transaction;
					child.amount = mv.amount;
					child.note = mv.note;
					child.posting_time = mv.posting_date;
				});
				frm.refresh_field("cash_movements");
			},
		});
	},

	open_print_format(frm, formatName) {
		const url = frappe.urllib.get_full_url(
			`/printview?doctype=${encodeURIComponent(frm.doctype)}` +
				`&name=${encodeURIComponent(frm.docname)}` +
				`&format=${encodeURIComponent(formatName)}` +
				`&trigger_print=1`
		);
		window.open(url, "_blank");
	},
});

