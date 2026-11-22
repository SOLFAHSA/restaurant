"""Comprehensive 2026-11-16 QA Audit: 3-Branch 30-User Simulation, RBAC Probes, SAR/Accounting/Inventory Integrity, and SQL N+1 Profiler."""

import json
import time
import unittest
from unittest.mock import MagicMock, patch
from uuid import uuid4

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt, now_datetime, nowdate
from frappe.utils.password import set_encrypted_password

from restaurant import cash_count, commands, kds, location, order_operations, pos, table_management
from restaurant.setup import (
    ensure_link_permissions,
    ensure_restaurant_roles,
    ensure_restaurant_role_profiles,
    ensure_waiter_module_profile,
)
from restaurant.tests.fixtures import ensure_restaurant_test_baseline


class TestQAComprehensiveAudit2026(FrappeTestCase):
    """Real transactional QA, multi-branch, security, accounting, and SQL profiling tests."""

    def setUp(self):
        super().setUp()
        ensure_restaurant_test_baseline()
        self.original_user = frappe.session.user
        frappe.set_user("Administrator")
        self.savepoint = f"qa_audit_{uuid4().hex[:8]}"
        frappe.db.savepoint(self.savepoint)
        ensure_restaurant_roles()
        ensure_link_permissions()
        self.suffix = uuid4().hex[:6]
        self.company = frappe.db.get_default("company") or frappe.db.get_value("Company", {}, "name")
        if not self.company:
            self.skipTest("Site missing default Company")
        self.currency = frappe.db.get_value("Company", self.company, "default_currency") or "HNL"
        self.uom = frappe.db.get_value("UOM", {"must_be_whole_number": 1}, "name") or frappe.db.get_value("UOM", {}, "name") or "Unidad"
        self.customer = self._ensure_customer()
        self._ensure_base_accounts_and_modes()

    def tearDown(self):
        frappe.set_user("Administrator")
        frappe.db.rollback(save_point=self.savepoint)
        frappe.clear_cache()
        frappe.set_user(self.original_user)

    def _ensure_customer(self):
        existing = frappe.db.get_value("Customer", {"disabled": 0}, "name")
        if existing:
            return existing
        return frappe.get_doc({
            "doctype": "Customer",
            "customer_name": f"Cliente QA {self.suffix}",
            "tax_category": "Contribuyente",
        }).insert(ignore_permissions=True).name

    def _ensure_base_accounts_and_modes(self):
        self.cash_mop = "Efectivo"
        bank_modes = [
            row.parent for row in frappe.get_all(
                "Mode of Payment Account",
                filters={"company": self.company, "default_account": ["is", "set"]},
                fields=["parent"],
            )
            if frappe.db.get_value("Mode of Payment", row.parent, "type") == "Bank"
        ]
        self.card_mop = bank_modes[0] if bank_modes else "Tarjetas de credito"
        self.transfer_mop = "Transferencia bancaria"
        if not frappe.db.exists("Mode of Payment", self.transfer_mop):
            self.transfer_mop = self.card_mop

    def _make_branch(self, label):
        return frappe.get_doc({
            "doctype": "Branch",
            "branch": f"{label}-{self.suffix}",
        }).insert(ignore_permissions=True).name

    def _make_warehouse(self, label):
        parent_wh = frappe.db.get_value("Warehouse", {"company": self.company, "is_group": 1}, "name")
        return frappe.get_doc({
            "doctype": "Warehouse",
            "warehouse_name": f"{label}-{self.suffix}",
            "company": self.company,
            "parent_warehouse": parent_wh,
        }).insert(ignore_permissions=True).name

    def _make_pos_profile(self, label, warehouse, update_stock=0, tax_category="Contribuyente"):
        src_name = frappe.db.get_value("POS Profile", {"disabled": 0, "company": self.company}, "name")
        src = frappe.get_doc("POS Profile", src_name)
        doc = frappe.copy_doc(src)
        new_name = f"{label}-{self.suffix}"
        doc.name = new_name
        doc.__newname = new_name
        doc.warehouse = warehouse
        doc.update_stock = update_stock
        doc.disable_rounded_total = 1
        doc.tax_category = tax_category
        doc.applicable_for_users = []
        enabled = {row.mode_of_payment for row in doc.payments}
        for mop in (self.cash_mop, self.card_mop, self.transfer_mop):
            if mop not in enabled and frappe.db.exists("Mode of Payment", mop):
                doc.append("payments", {"mode_of_payment": mop})
                enabled.add(mop)
        if hasattr(doc, "posa_allow_user_to_edit_rate"):
            doc.allow_rate_change = 1
        doc.insert(ignore_permissions=True, set_name=new_name)
        return doc.name

    def _make_user_and_employee(self, idx, role_profile_name, roles, branch, pin=None, create_employee=True):
        prev_user = frappe.session.user
        frappe.set_user("Administrator")
        try:
            email = f"qa.{idx}.{self.suffix}@leaf.local"
            user = frappe.get_doc({
                "doctype": "User",
                "email": email,
                "first_name": f"QA-{idx}",
                "last_name": self.suffix,
                "enabled": 1,
                "user_type": "System User",
                "send_welcome_email": 0,
                "role_profile_name": role_profile_name,
                "roles": [{"role": r} for r in roles],
            }).insert(ignore_permissions=True)
            emp_name = None
            if create_employee:
                emp = frappe.get_doc({
                    "doctype": "Employee",
                    "first_name": f"Emp-{idx}",
                    "last_name": self.suffix,
                    "gender": frappe.db.get_value("Gender", {}, "name") or "Male",
                    "date_of_birth": "1995-01-01",
                    "date_of_joining": "2024-01-01",
                    "company": self.company,
                    "status": "Active",
                    "user_id": user.name,
                    "branch": branch,
                    "create_user_permission": 0,
                    "designation": "Mesero" if frappe.db.exists("Designation", "Mesero") and "Restaurant User" in roles else None,
                }).insert(ignore_permissions=True)
                emp_name = emp.name
                if pin:
                    set_encrypted_password("Employee", emp.name, pin, fieldname="restaurant_pos_pin")
            frappe.get_doc({
                "doctype": "User Permission",
                "user": user.name,
                "allow": "Branch",
                "for_value": branch,
                "apply_to_all_doctypes": 1,
            }).insert(ignore_permissions=True)
            return {"user": user.name, "employee": emp_name, "branch": branch, "pin": pin}
        finally:
            frappe.set_user(prev_user)

    def _make_item(self, code, rate=100.0, tax_pct=15.0, is_stock=0, item_group=None):
        grp = item_group or frappe.db.get_value("Item Group", {"is_group": 0}, "name") or "All Item Groups"
        taxes = []
        if tax_pct == 15.0 and frappe.db.exists("Item Tax Template", {"name": ["like", "%15%"]}):
            itt = frappe.db.get_value("Item Tax Template", {"name": ["like", "%15%"]}, "name")
            taxes.append({"item_tax_template": itt})
        elif tax_pct == 18.0 and frappe.db.exists("Item Tax Template", {"name": ["like", "%18%"]}):
            itt = frappe.db.get_value("Item Tax Template", {"name": ["like", "%18%"]}, "name")
            taxes.append({"item_tax_template": itt})
        elif tax_pct == 0.0 and frappe.db.exists("Item Tax Template", {"name": ["like", "%EXENT%"]}):
            itt = frappe.db.get_value("Item Tax Template", {"name": ["like", "%EXENT%"]}, "name")
            taxes.append({"item_tax_template": itt})
        return frappe.get_doc({
            "doctype": "Item",
            "item_code": f"{code}-{self.suffix}",
            "item_name": f"{code} QA {self.suffix}",
            "item_group": grp,
            "stock_uom": self.uom,
            "is_stock_item": is_stock,
            "is_sales_item": 1,
            "standard_rate": rate,
            "taxes": taxes,
        }).insert(ignore_permissions=True).name

    def test_01_three_branch_thirty_user_full_operational_simulation(self):
        """Simulate 3 branches simultaneously (9 cashiers, 15 waiters, 6 kitchen = 30 users + 3 supervisors)."""
        root_grp = frappe.db.get_value("Item Group", {"is_group": 1, "parent_item_group": ["is", "not set"]}, "name") or "All Item Groups"
        grp_food = frappe.get_doc({
            "doctype": "Item Group",
            "item_group_name": f"QA Cocina {self.suffix}",
            "parent_item_group": root_grp,
            "is_group": 0,
        }).insert(ignore_permissions=True).name
        grp_drink = frappe.get_doc({
            "doctype": "Item Group",
            "item_group_name": f"QA Bebidas {self.suffix}",
            "parent_item_group": root_grp,
            "is_group": 0,
        }).insert(ignore_permissions=True).name

        dish = self._make_item("PLATILLO", rate=120.0, tax_pct=15.0, item_group=grp_food)
        beer = self._make_item("BEBIDA15", rate=60.0, tax_pct=15.0, item_group=grp_drink)
        water = self._make_item("EXTRA15", rate=25.0, tax_pct=15.0, item_group=grp_drink)

        stages = [
            kds.save_stage({"stage_name": f"{lbl}-{self.suffix}", "color": clr, "alert_minutes": mins})["name"]
            for lbl, clr, mins in (("En Preparación", "#F59E0B", 10), ("Listo", "#22C55E", 5), ("Entregado", "#3B82F6", 0))
        ]

        branches_ctx = {}
        total_sim_users = 0
        user_seq = 0
        for code in ("A", "B", "C"):
            frappe.set_user("Administrator")
            branch = self._make_branch(f"Sucursal-{code}")
            wh = self._make_warehouse(f"Alm-{code}")
            prof = self._make_pos_profile(f"POS-{code}", wh, update_stock=0)
            area_res = location.save_location({
                "area_name": f"Salon-{code}-{self.suffix}",
                "branch": branch,
                "capacity": 40,
                "display_order": 1,
                "enabled": 1,
                "floor_background": "Madera cálida",
            })
            area = area_res["name"]
            t1 = table_management.save_table({"table_number": f"{code}-M1", "restaurant_area": area, "seats": 4, "status": "Disponible"})["table"]["name"]
            t2 = table_management.save_table({"table_number": f"{code}-M2", "restaurant_area": area, "seats": 4, "status": "Disponible"})["table"]["name"]

            cmd_name = commands.save_command({
                "command_name": f"Comanda-{code}-{self.suffix}",
                "branch": branch,
                "print_mode": "Impresora de red directa (ESC/POS IP:Puerto)",
                "printer_ip": f"127.0.0.{len(branches_ctx) + 10}",
                "printer_port": 9100,
                "auto_print_on_send": 1,
                "enabled": 1,
                "groups": [{"item_group": grp_food}, {"item_group": grp_drink}],
            })["name"]

            display = kds.save_display({
                "display_name": f"KDS-{code}-{self.suffix}",
                "enabled": 1,
                "auto_clear": 0,
                "auto_clear_minutes": 10,
                "stages": stages,
                "pos_profiles": [prof],
                "item_groups": [grp_food, grp_drink],
            })["name"]

            cashiers = []
            for i in range(3):
                user_seq += 1
                is_direct = i == 2
                rp = "Cajero (Facturación Directa)" if is_direct else "Cajero (Completo)"
                roles = ["Restaurant Cashier", "Restaurant Direct Cashier"] if is_direct else ["Restaurant User", "Restaurant Cashier"]
                # Grant Accounts User/Sales User in this operational simulation so native ERPNext invoice submit works cleanly;
                # pure-role without Accounts User is tested separately in DEF-QA-03!
                cashiers.append(self._make_user_and_employee(f"caj-{code}-{user_seq}", None, roles + ["Sales User", "Accounts User"], branch))
                total_sim_users += 1

            waiters = []
            for i in range(5):
                user_seq += 1
                waiters.append(self._make_user_and_employee(f"mes-{code}-{user_seq}", "Mesero (Salón)", ["Restaurant User"], branch, pin=f"1{code}{i}9" if False else f"40{user_seq:02d}"))
                total_sim_users += 1

            kitchen = []
            for i in range(2):
                user_seq += 1
                kitchen.append(self._make_user_and_employee(f"coc-{code}-{user_seq}", None, ["Restaurant User", "Restaurant Cashier"], branch))
                total_sim_users += 1

            sup = self._make_user_and_employee(f"sup-{code}-{user_seq}", None, ["Restaurant Manager", "Restaurant User", "Accounts User", "Sales User"], branch, pin=f"990{len(branches_ctx) + 1}")

            # Cashier 0 opens POS shift
            frappe.set_user(cashiers[0]["user"])
            shift_res = pos.open_pos_shift(
                pos_profile=prof,
                balance_details=[{"mode_of_payment": self.cash_mop, "opening_amount": 500.0}],
            )
            shift_name = shift_res["name"]

            branches_ctx[code] = {
                "branch": branch,
                "warehouse": wh,
                "pos_profile": prof,
                "area": area,
                "tables": [t1, t2],
                "command": cmd_name,
                "display": display,
                "cashiers": cashiers,
                "waiters": waiters,
                "kitchen": kitchen,
                "supervisor": sup,
                "shift": shift_name,
            }

        self.assertEqual(total_sim_users, 30)

        # Run full operational flow per branch concurrently in logic (serial DB session inside savepoint)
        created_invoices = []
        mock_socket = MagicMock()
        with patch("socket.create_connection", return_value=mock_socket):
            for code, ctx in branches_ctx.items():
                # 1. Waiter opens dine-in order on M1
                frappe.set_user(ctx["waiters"][0]["user"])
                ord_res = pos.save_pos_order({
                    "order_name": f"5{code}01",
                    "service_type": "Comer en el local",
                    "restaurant_table": ctx["tables"][0],
                    "pos_profile": ctx["pos_profile"],
                    "waiter": ctx["waiters"][0]["employee"],
                    "customer": self.customer,
                    "items": [
                        {"item_code": dish, "qty": 2, "note": "Sin sal"},
                        {"item_code": beer, "qty": 1},
                        {"item_code": water, "qty": 1},
                    ],
                })
                order_doc = ord_res["order"]
                self.assertEqual(frappe.db.get_value("Restaurant Table", ctx["tables"][0], "status"), "Ocupada")

                # 2. Send order to kitchen / commands
                cmd_res = pos.send_order_to_kitchen(order_doc["name"])
                self.assertTrue(len(cmd_res["print_jobs"]) >= 1)

                # 3. Kitchen advances items in KDS
                frappe.set_user(ctx["kitchen"][0]["user"])
                kds_state = kds.get_kds_state(display_name=ctx["display"])
                kds_order = next((o for o in kds_state["orders"] if o["name"] == order_doc["name"]), None)
                self.assertIsNotNone(kds_order)
                for line in kds_order["items"]:
                    kds.toggle_item(display_name=ctx["display"], order_name=order_doc["name"], item_name=line["name"], expected_stage=stages[0], completed=1)
                for line in kds_order["items"]:
                    kds.toggle_item(display_name=ctx["display"], order_name=order_doc["name"], item_name=line["name"], expected_stage=stages[1], completed=1)
                kds.dismiss_ticket(display_name=ctx["display"], order_name=order_doc["name"], expected_stage=stages[2])

                # 4. Cashier splits 1 item to M2, prints precuenta, cancels an item with Supervisor PIN, and invoices remaining with mixed payments
                frappe.set_user(ctx["cashiers"][0]["user"])
                fresh_mod = frappe.db.get_value("Restaurant Order", order_doc["name"], "modified")
                split_res = pos.split_order(
                    order_name=order_doc["name"],
                    split_items=[{"item_name": order_doc["items"][0]["name"], "qty": 1}],
                    expected_modified=str(fresh_mod),
                )
                split_child = split_res["new_order"]
                self.assertEqual(flt(split_child["items"][0]["qty"]), 1.0)
                pos.transfer_order_table(
                    order_name=split_child["name"],
                    target_table=ctx["tables"][1],
                    expected_modified=str(split_child["modified"]),
                )

                # Precuenta non-fiscal
                prec = pos.get_precuenta_data(order_doc["name"], tip_percentage=10)
                self.assertEqual(prec["order"]["precuenta_printed"], 1)

                # Cancel water item via Supervisor PIN
                frappe.set_user(ctx["cashiers"][0]["user"])
                parent_reloaded = frappe.get_doc("Restaurant Order", order_doc["name"])
                cancel_item = next(it for it in parent_reloaded.items if it.item_code == water and not it.is_cancelled)
                pos.cancel_sent_order_item(
                    order_name=order_doc["name"],
                    item_row_name=cancel_item.name,
                    cancel_qty=1,
                    supervisor_user=ctx["supervisor"]["user"],
                    supervisor_pin=ctx["supervisor"]["pin"],
                    reason="Cliente cambió de opinión QA",
                    expected_modified=str(parent_reloaded.modified),
                )
                self.assertGreaterEqual(
                    frappe.db.count("Restaurant Audit Log", {"restaurant_order": order_doc["name"]}),
                    1,
                )

                # Mixed payment on parent order (50% Cash + remainder Card)
                frappe.set_user(ctx["cashiers"][0]["user"])
                refreshed = frappe.get_doc("Restaurant Order", order_doc["name"])
                grand = flt(refreshed.grand_total, 2)
                cash_part = flt(grand / 2.0, 2)
                card_part = flt(grand - cash_part, 2)
                inv_res = pos.pay_and_invoice_order(
                    order_name=order_doc["name"],
                    payments=[
                        {"mode_of_payment": self.cash_mop, "amount": cash_part},
                        {"mode_of_payment": self.card_mop, "amount": card_part},
                    ],
                    customer=self.customer,
                )
                si_name = inv_res["invoice"]["name"]
                created_invoices.append(si_name)
                self.assertEqual(flt(inv_res["invoice"]["grand_total"], 2), grand)

                # GL Entry balance verification per invoice
                gl_diff = frappe.db.sql(
                    "SELECT IFNULL(SUM(debit) - SUM(credit), 0) FROM `tabGL Entry` WHERE voucher_type='Sales Invoice' AND voucher_no=%s AND is_cancelled=0",
                    (si_name,),
                )[0][0]
                self.assertAlmostEqual(flt(gl_diff), 0.0, places=2)

                # Pay split child order in Cash too so shift has no pending invoiced gap & M2 releases
                frappe.set_user(ctx["cashiers"][0]["user"])
                child_doc = frappe.get_doc("Restaurant Order", split_child["name"])
                inv_child = pos.pay_and_invoice_order(
                    order_name=child_doc.name,
                    payments=[{"mode_of_payment": self.cash_mop, "amount": flt(child_doc.grand_total, 2)}],
                    customer=self.customer,
                )
                created_invoices.append(inv_child["invoice"]["name"])

                # Cash movement (Retiro de efectivo)
                if frappe.has_permission("Retiro de efectivo", "create"):
                    mov = cash_count.register_cash_count_movement("Retiro", 20.0, "Hielo QA", pos_opening_shift=ctx["shift"])
                    self.assertAlmostEqual(flt(mov["total_expense"], 2), 20.0, places=2)

                # Cash Count & Shift Closing (exact expected match -> Cuadrado)
                frappe.set_user("Administrator")  # Ensure Retiro + Closing Shift rights cleanly complete flow
                snap = cash_count.get_cash_count_preview(pos_opening_shift=ctx["shift"])
                cash_method = next((m for m in snap["payment_methods"] if m["is_cash"]), None)
                self.assertIsNotNone(cash_method)
                expected_cash = flt(cash_method["expected_amount"], 2)

                # Submit partial or closing count matching expected
                denom_rows = []
                rem = int(expected_cash)
                frac = flt(expected_cash - rem, 2)
                for d in snap["denominations"]:
                    uv = flt(d["unit_value"])
                    qty = int(rem // uv) if uv >= 1 and rem >= uv else 0
                    rem -= int(qty * uv)
                    denom_rows.append({**d, "quantity": qty, "subtotal": flt(qty * uv, 2)})
                method_rows = []
                for m in snap["payment_methods"]:
                    if m["is_cash"]:
                        method_rows.append({**m, "counted_amount": flt(expected_cash - frac, 2)})
                    else:
                        method_rows.append({**m, "counted_amount": flt(m["expected_amount"], 2)})

                cc_res = cash_count.save_and_submit_cash_count({
                    "pos_opening_shift": ctx["shift"],
                    "count_type": "Arqueo Parcial",
                    "denominations": denom_rows,
                    "payment_methods": method_rows,
                    "notes": f"Arqueo Branch {code}",
                })
                self.assertEqual(cc_res["cash_count"]["pos_opening_shift"], ctx["shift"])

                # Also verify SAR Ticket prints cleanly for branch invoice
                ticket_html = frappe.get_print("Sales Invoice", si_name, "Ticket", no_letterhead=1)
                self.assertIn(f"FACTURA No. {si_name}", ticket_html)
                self.assertIn("Original: Cliente", ticket_html)

        self.assertEqual(len(created_invoices), 6)

    def test_02_sql_query_count_and_n_plus_one_profile(self):
        """Measure exact SQL query counts and latency on real site data to prove N+1 bottlenecks."""
        counters = {"calls": 0}
        orig_sql = frappe.db.sql

        def counted_sql(query, *args, **kwargs):
            counters["calls"] += 1
            return orig_sql(query, *args, **kwargs)

        profile_results = {}
        sample_order = frappe.db.get_value("Restaurant Order", {"status": "En curso"}, "name")
        try:
            frappe.db.sql = counted_sql
            for label, fn in (
                ("get_pos_bootstrap", lambda: pos.get_pos_bootstrap()),
                ("get_kds_state", lambda: kds.get_kds_state()),
                ("get_commands", lambda: commands.get_commands(page_length=20)),
                ("get_locations", lambda: location.get_locations(page_length=20)),
            ):
                counters["calls"] = 0
                t0 = time.perf_counter()
                fn()
                elapsed_ms = (time.perf_counter() - t0) * 1000.0
                profile_results[label] = {"sql_queries": counters["calls"], "ms": round(elapsed_ms, 2)}

            if sample_order:
                doc = frappe.get_doc("Restaurant Order", sample_order)
                counters["calls"] = 0
                t0 = time.perf_counter()
                pos.validate_order(doc)
                profile_results["validate_order"] = {
                    "sql_queries": counters["calls"],
                    "ms": round((time.perf_counter() - t0) * 1000.0, 2),
                }

            prof = frappe.db.get_value("POS Profile", {"disabled": 0, "company": self.company}, "name")
            item_p = self._make_item("PROFITEM", rate=90.0, tax_pct=15.0)
            wh_p = self._make_warehouse("ProfWh")
            prof_p = self._make_pos_profile("ProfPOS", wh_p, update_stock=0)
            frappe.get_doc({
                "doctype": "POS Opening Shift",
                "period_start_date": now_datetime(),
                "company": self.company,
                "user": "Administrator",
                "pos_profile": prof_p,
                "balance_details": [{"mode_of_payment": self.cash_mop, "opening_amount": 0.0}],
            }).insert(ignore_permissions=True).submit()

            counters["calls"] = 0
            t0 = time.perf_counter()
            saved = pos.save_pos_order({
                "order_name": f"PRF-{self.suffix}",
                "pos_profile": prof_p,
                "customer": self.customer,
                "items": [{"item_code": item_p, "qty": 1}],
            })
            profile_results["save_pos_order"] = {
                "sql_queries": counters["calls"],
                "ms": round((time.perf_counter() - t0) * 1000.0, 2),
            }

            counters["calls"] = 0
            t0 = time.perf_counter()
            pos.pay_and_invoice_order(
                order_name=saved["order"]["name"],
                payments=[{"mode_of_payment": self.cash_mop, "amount": saved["order"]["grand_total"]}],
            )
            profile_results["pay_and_invoice_order"] = {
                "sql_queries": counters["calls"],
                "ms": round((time.perf_counter() - t0) * 1000.0, 2),
            }

            shift_p = frappe.db.get_value("POS Opening Shift", {"pos_profile": prof_p, "status": "Open", "docstatus": 1}, "name")
            if shift_p:
                counters["calls"] = 0
                t0 = time.perf_counter()
                cash_count.get_cash_count_preview(pos_opening_shift=shift_p)
                profile_results["get_cash_count_preview"] = {
                    "sql_queries": counters["calls"],
                    "ms": round((time.perf_counter() - t0) * 1000.0, 2),
                }
        finally:
            frappe.db.sql = orig_sql

        print("\n[QA_SQL_PROFILE]", json.dumps(profile_results))
        # Verify real measurements were collected (>0 queries for non-trivial endpoints)
        self.assertGreater(profile_results["get_pos_bootstrap"]["sql_queries"], 0)
        self.assertGreater(profile_results["get_kds_state"]["sql_queries"], 0)

    def test_03_negative_and_security_controls_passing(self):
        """Verify security controls that ALREADY hold in backend."""
        # Waiter cannot call save_restaurant_pos_config; removed helper endpoints must stay absent
        waiter = self._make_user_and_employee("secw", "Mesero (Salón)", ["Restaurant User"], self._make_branch("SecBr"))
        frappe.set_user(waiter["user"])
        with self.assertRaises(frappe.PermissionError):
            pos.save_restaurant_pos_config(frappe.db.get_value("POS Profile", {"company": self.company}, "name"), {})
        for removed in ("ensure_restaurant_stock", "create_pos_product", "get_restaurant_stock_status", "authorize_clear_order"):
            self.assertFalse(hasattr(pos, removed), removed)

        # Rate limit locks waiter PIN after 5 wrong attempts
        target_emp = self._make_user_and_employee("pinw", "Mesero (Salón)", ["Restaurant User"], self._make_branch("PinBr"), pin="7788")
        frappe.set_user("Administrator")
        item = self._make_item("PINITEM", rate=50.0)
        ord_doc = frappe.get_doc({
            "doctype": "Restaurant Order",
            "order_name": f"PIN-{self.suffix}",
            "customer": self.customer,
            "waiter": target_emp["employee"],
            "items": [{"item_code": item, "qty": 1, "base_rate": 50.0}],
        }).insert(ignore_permissions=True)

        cashier = self._make_user_and_employee("pinc", "Cajero (Completo)", ["Restaurant User", "Restaurant Cashier"], target_emp["branch"], create_employee=False)
        frappe.set_user(cashier["user"])
        cache_key = f"rpos_pin_fail:{cashier['user']}:waiter:{target_emp['employee']}"
        frappe.cache().delete_value(cache_key)
        for _ in range(5):
            frappe.local.cache = {}
            with self.assertRaises(frappe.PermissionError):
                pos.unlock_waiter_order(ord_doc.name, "0000")
        frappe.clear_messages()
        frappe.local.cache = {}
        with self.assertRaises(frappe.PermissionError) as ctx:
            pos.unlock_waiter_order(ord_doc.name, "7788")
        msg_dump = str(ctx.exception) + " " + json.dumps(frappe.local.message_log or [], ensure_ascii=False)
        self.assertIn("Demasiados intentos", msg_dump)
        frappe.clear_messages()
        frappe.cache().delete_value(cache_key)

    def test_03b_pure_cashier_can_submit_invoice_via_pos_api(self):
        """PASS: si.insert(ignore_permissions=True) propagates ignore_permissions flag to si.submit()."""
        branch = self._make_branch("PureCash")
        wh = self._make_warehouse("PureWh")
        prof = self._make_pos_profile("PurePOS", wh, update_stock=0)
        cashier = self._make_user_and_employee("pc1", "Cajero (Completo)", ["Restaurant User", "Restaurant Cashier"], branch)
        item = self._make_item("PCITEM", rate=100.0)
        frappe.set_user("Administrator")
        frappe.get_doc({
            "doctype": "POS Opening Shift",
            "period_start_date": now_datetime(),
            "company": self.company,
            "user": cashier["user"],
            "pos_profile": prof,
            "balance_details": [{"mode_of_payment": self.cash_mop, "opening_amount": 100.0}],
        }).insert(ignore_permissions=True).submit()
        frappe.set_user(cashier["user"])
        ord_res = pos.save_pos_order({
            "order_name": f"PC-{self.suffix}",
            "pos_profile": prof,
            "customer": self.customer,
            "items": [{"item_code": item, "qty": 1}],
        })
        inv_res = pos.pay_and_invoice_order(
            order_name=ord_res["order"]["name"],
            payments=[{"mode_of_payment": self.cash_mop, "amount": ord_res["order"]["grand_total"]}],
        )
        self.assertTrue(inv_res["invoice"]["name"])
        self.assertEqual(int(frappe.db.get_value("Sales Invoice", inv_res["invoice"]["name"], "docstatus")), 1)

    # --- VERIFIED REMEDIATED DEFECT TESTS ---

    def test_def_qa_01_direct_cashier_can_access_pos_desk_page(self):
        """DEF-QA-01: Restaurant Direct Cashier lacks Page Role on restaurant-pos Desk Page."""
        branch = self._make_branch("DC")
        dc = self._make_user_and_employee("dc1", "Cajero (Facturación Directa)", ["Restaurant Cashier", "Restaurant Direct Cashier"], branch)
        frappe.set_user(dc["user"])
        from frappe.desk.desk_page import get as get_page
        res = get_page("restaurant-pos")
        self.assertTrue(res)

    def test_def_qa_02_waiter_cannot_overwrite_customer_via_save_customer_with_rtn(self):
        """DEF-QA-02: Waiter (Restaurant User) can create/modify Customers via ignore_permissions=True."""
        branch = self._make_branch("CustSec")
        waiter = self._make_user_and_employee("w_cust", "Mesero (Salón)", ["Restaurant User"], branch)
        frappe.set_user(waiter["user"])
        with self.assertRaises(frappe.PermissionError):
            pos.save_customer_with_rtn(customer_name="Cliente Creado Por Mesero", tax_id="08011990123456")

    def test_def_qa_03_non_restaurant_user_blocked_from_get_self_order_config(self):
        """DEF-QA-03: get_self_order_config lacks _require_pos_user() and allows any non-restaurant authenticated user."""
        plain_user = frappe.get_doc({
            "doctype": "User",
            "email": f"plain.{self.suffix}@leaf.local",
            "first_name": "Plain",
            "last_name": self.suffix,
            "enabled": 1,
            "user_type": "System User",
            "send_welcome_email": 0,
            "roles": [{"role": "Desk User"}],
        }).insert(ignore_permissions=True)
        frappe.set_user(plain_user.name)
        with self.assertRaises(frappe.PermissionError):
            pos.get_self_order_config()

    def test_def_qa_04_manager_can_close_cashier_shift_via_cash_count(self):
        """DEF-QA-04: Restaurant Manager is blocked by close_pos_shift from closing another cashier's shift."""
        branch = self._make_branch("MgrClose")
        wh = self._make_warehouse("MgrWh")
        prof = self._make_pos_profile("MgrPOS", wh, update_stock=0)
        cashier = self._make_user_and_employee("mc1", "Cajero (Completo)", ["Restaurant User", "Restaurant Cashier"], branch)
        manager = self._make_user_and_employee("mg1", None, ["Restaurant User", "Restaurant Manager"], branch)
        frappe.set_user("Administrator")
        shift = frappe.get_doc({
            "doctype": "POS Opening Shift",
            "period_start_date": now_datetime(),
            "company": self.company,
            "user": cashier["user"],
            "pos_profile": prof,
            "balance_details": [{"mode_of_payment": self.cash_mop, "opening_amount": 200.0}],
        }).insert(ignore_permissions=True)
        shift.submit()
        frappe.set_user(manager["user"])
        snap = cash_count.get_cash_count_preview(pos_opening_shift=shift.name)
        denom_rows = []
        rem = 200
        for d in snap["denominations"]:
            uv = flt(d["unit_value"])
            qty = int(rem // uv) if uv >= 1 and rem >= uv else 0
            rem -= int(qty * uv)
            denom_rows.append({**d, "quantity": qty, "subtotal": flt(qty * uv, 2)})
        method_rows = [{**m, "counted_amount": flt(m["expected_amount"], 2)} for m in snap["payment_methods"]]
        res = cash_count.save_and_submit_cash_count({
            "pos_opening_shift": shift.name,
            "count_type": "Arqueo de Cierre",
            "denominations": denom_rows,
            "payment_methods": method_rows,
        })
        self.assertTrue(res["cash_count"]["pos_closing_shift"])

    def test_def_qa_09_waiter_can_call_kds_state_matching_page_role(self):
        """DEF-QA-09: restaurant_kds.json grants Page access to Restaurant User, but setup.py omits Display/Stage perms."""
        branch = self._make_branch("KdsWaiter")
        waiter = self._make_user_and_employee("kw1", "Mesero (Salón)", ["Restaurant User"], branch)
        frappe.set_user(waiter["user"])
        state = kds.get_kds_state()
        self.assertIn("displays", state)

    def test_def_qa_10_gift_card_redemption_deducts_from_invoice_cash_due(self):
        """DEF-QA-10: A native certificate reduces the required cash payment."""
        branch = self._make_branch("GC")
        wh = self._make_warehouse("GCWh")
        prof = self._make_pos_profile("GCPOS", wh, update_stock=0)
        item = self._make_item("GCITEM", rate=100.0, tax_pct=15.0)
        frappe.set_user("Administrator")
        frappe.db.set_value("Restaurant Settings", None, "enable_gift_cards", 1)
        from frappe.utils.password import decrypt

        gc = frappe.get_doc({
            "doctype": "Certificado de Regalo",
            "company": self.company,
            "comprador": self.customer,
            "monto_inicial": 50.0,
            "es_saldo_inicial": 1,
        }).insert(ignore_permissions=True)
        gc.submit()
        code = decrypt(gc.codigo_cifrado)
        frappe.get_doc({
            "doctype": "POS Opening Shift",
            "period_start_date": now_datetime(),
            "company": self.company,
            "user": "Administrator",
            "pos_profile": prof,
            "balance_details": [{"mode_of_payment": self.cash_mop, "opening_amount": 0.0}],
        }).insert(ignore_permissions=True).submit()
        ord_res = pos.save_pos_order({
            "order_name": f"GC-{self.suffix}",
            "pos_profile": prof,
            "customer": self.customer,
            "items": [{"item_code": item, "qty": 1}],
        })
        grand = flt(ord_res["order"]["grand_total"], 2)
        res = pos.pay_and_invoice_order(
            order_name=ord_res["order"]["name"],
            payments=[{"mode_of_payment": self.cash_mop, "amount": flt(grand - 50.0, 2)}],
            gift_card_code=code,
            gift_card_amount=50.0,
        )
        self.assertTrue(res["invoice"]["name"])

    def test_def_qa_11_waiter_pin_rate_limit_works_without_clearing_local_cache(self):
        """DEF-QA-11: cache.get_value(key) without expires=True caches None in frappe.local.cache and hides TTL increments."""
        target_emp = self._make_user_and_employee("pinlocw", "Mesero (Salón)", ["Restaurant User"], self._make_branch("PinLoc"), pin="7788")
        frappe.set_user("Administrator")
        item = self._make_item("PINLOC", rate=50.0)
        ord_doc = frappe.get_doc({
            "doctype": "Restaurant Order",
            "order_name": f"PINL-{self.suffix}",
            "customer": self.customer,
            "waiter": target_emp["employee"],
            "items": [{"item_code": item, "qty": 1, "base_rate": 50.0}],
        }).insert(ignore_permissions=True)
        cashier = self._make_user_and_employee("pinlocc", "Cajero (Completo)", ["Restaurant User", "Restaurant Cashier"], target_emp["branch"], create_employee=False)
        frappe.set_user(cashier["user"])
        cache_key = f"rpos_pin_fail:{cashier['user']}:waiter:{target_emp['employee']}"
        frappe.cache().delete_value(cache_key)
        for _ in range(5):
            with self.assertRaises(frappe.PermissionError):
                pos.unlock_waiter_order(ord_doc.name, "0000")
        with self.assertRaises(frappe.PermissionError):
            pos.unlock_waiter_order(ord_doc.name, "7788")

    def test_def_qa_12_mixed_isv15_isv18_order_does_not_double_tax_on_invoice(self):
        """DEF-QA-12 (P0): pay_and_invoice_order double-taxes mixed 15% + 18% items (both rates apply to every item -> 33% ISV)."""
        branch = self._make_branch("MixTax")
        wh = self._make_warehouse("MixWh")
        prof = self._make_pos_profile("MixPOS", wh, update_stock=0)
        dish15 = self._make_item("D15", rate=120.0, tax_pct=15.0)
        drink18 = self._make_item("B18", rate=60.0, tax_pct=18.0)
        frappe.set_user("Administrator")
        frappe.get_doc({
            "doctype": "POS Opening Shift",
            "period_start_date": now_datetime(),
            "company": self.company,
            "user": "Administrator",
            "pos_profile": prof,
            "balance_details": [{"mode_of_payment": self.cash_mop, "opening_amount": 0.0}],
        }).insert(ignore_permissions=True).submit()
        ord_res = pos.save_pos_order({
            "order_name": f"MIX-{self.suffix}",
            "pos_profile": prof,
            "customer": self.customer,
            "items": [
                {"item_code": dish15, "qty": 1},
                {"item_code": drink18, "qty": 1},
            ],
        })
        expected_total = flt(ord_res["order"]["grand_total"], 2)  # 120*1.15 + 60*1.18 = 208.80
        inv_res = pos.pay_and_invoice_order(
            order_name=ord_res["order"]["name"],
            payments=[{"mode_of_payment": self.cash_mop, "amount": expected_total}],
        )
        self.assertAlmostEqual(flt(inv_res["invoice"]["grand_total"], 2), expected_total, places=2)

    def test_def_qa_05_exonerated_and_update_stock_not_overwritten_by_set_missing_values(self):
        """DEF-QA-05: si.set_missing_values() overwrites si_payload update_stock=0 and tax_category='Exonerado' from POS Profile."""
        branch = self._make_branch("Exo")
        wh = self._make_warehouse("ExoWh")
        prof = self._make_pos_profile("ExoPOS", wh, update_stock=1, tax_category="Contribuyente")
        exo_cust = frappe.get_doc({
            "doctype": "Customer",
            "customer_name": f"Cliente Exonerado {self.suffix}",
            "tax_category": "Exonerado",
            "custom_subtipo_exonerado": "Constancia SAR / SAG / SEFIN",
            "custom_constancia_exonerado": "CR-2026-001",
            "custom_registro_sag": "SAG-2026-009",
        }).insert(ignore_permissions=True).name
        item = self._make_item("EXOITEM", rate=100.0, tax_pct=15.0)
        frappe.get_doc({
            "doctype": "POS Opening Shift",
            "period_start_date": now_datetime(),
            "company": self.company,
            "user": "Administrator",
            "pos_profile": prof,
            "balance_details": [{"mode_of_payment": self.cash_mop, "opening_amount": 0.0}],
        }).insert(ignore_permissions=True).submit()
        ord_res = pos.save_pos_order({
            "order_name": f"EXO-{self.suffix}",
            "pos_profile": prof,
            "customer": exo_cust,
            "items": [{"item_code": item, "qty": 1}],
        })
        inv_res = pos.pay_and_invoice_order(
            order_name=ord_res["order"]["name"],
            payments=[{"mode_of_payment": self.cash_mop, "amount": ord_res["order"]["grand_total"]}],
            customer=exo_cust,
            tax_category="Exonerado",
            custom_orden_compra_exenta="OC-777",
        )
        si = frappe.get_doc("Sales Invoice", inv_res["invoice"]["name"])
        self.assertEqual(int(si.update_stock), 0)
        self.assertEqual(si.tax_category, "Exonerado")

    def test_def_qa_06_branch_isolation_in_bootstrap_orders(self):
        """DEF-QA-06: Branch A user still sees Branch B orders in get_pos_bootstrap because Restaurant Order lacks 'branch' field."""
        br_a = self._make_branch("IsoA")
        br_b = self._make_branch("IsoB")
        wh_b = self._make_warehouse("IsoWhB")
        prof_b = self._make_pos_profile("IsoProfB", wh_b, update_stock=0)
        user_a = self._make_user_and_employee("iso_a", "Cajero (Completo)", ["Restaurant User", "Restaurant Cashier"], br_a)
        user_b = self._make_user_and_employee("iso_b", "Cajero (Completo)", ["Restaurant User", "Restaurant Cashier"], br_b)
        area_b = frappe.get_doc({
            "doctype": "Restaurant Area",
            "area_name": f"AreaB-{self.suffix}",
            "branch": br_b,
            "capacity": 10,
            "status": "Activa",
            "visible_in_pos": 1,
        }).insert(ignore_permissions=True).name
        tbl_b = frappe.get_doc({
            "doctype": "Restaurant Table",
            "table_number": f"TB-{self.suffix}",
            "restaurant_area": area_b,
            "branch": br_b,
            "seats": 4,
            "status": "Disponible",
        }).insert(ignore_permissions=True).name
        item = self._make_item("ISOITEM", rate=80.0)

        frappe.set_user(user_b["user"])
        ord_b = pos.save_pos_order({
            "order_name": f"BRB-{self.suffix}",
            "pos_profile": prof_b,
            "restaurant_table": tbl_b,
            "customer": self.customer,
            "items": [{"item_code": item, "qty": 1}],
        })["order"]["name"]

        frappe.set_user(user_a["user"])
        boot_a = pos.get_pos_bootstrap()
        visible_names = {o["name"] for o in boot_a.get("orders", [])}
        self.assertNotIn(ord_b, visible_names)

    def test_def_qa_07_other_cashier_blocked_from_reading_or_counting_foreign_shift(self):
        """DEF-QA-07: Cashier B can preview/submit Cash Count against Cashier A's open shift."""
        br = self._make_branch("CCSec")
        wh = self._make_warehouse("CCWh")
        prof = self._make_pos_profile("CCProf", wh, update_stock=0)
        caj_a = self._make_user_and_employee("cca", "Cajero (Completo)", ["Restaurant User", "Restaurant Cashier"], br)
        caj_b = self._make_user_and_employee("ccb", "Cajero (Completo)", ["Restaurant User", "Restaurant Cashier"], br)

        frappe.set_user("Administrator")
        shift_a = frappe.get_doc({
            "doctype": "POS Opening Shift",
            "period_start_date": now_datetime(),
            "company": self.company,
            "user": caj_a["user"],
            "pos_profile": prof,
            "balance_details": [{"mode_of_payment": self.cash_mop, "opening_amount": 500.0}],
        }).insert(ignore_permissions=True)
        shift_a.submit()

        frappe.set_user(caj_b["user"])
        with self.assertRaises(frappe.PermissionError):
            cash_count.get_cash_count_preview(pos_opening_shift=shift_a.name)

    def test_def_qa_08_wrong_waiter_pin_logs_rejected_not_authorized(self):
        """DEF-QA-08: Failed waiter PIN in unlock_waiter_order logs result='Autorizado' by default."""
        br = self._make_branch("Aud")
        emp_w = self._make_user_and_employee("audw", "Mesero (Salón)", ["Restaurant User"], br, pin="1234")
        audu = self._make_user_and_employee("audu", "Mesero (Salón)", ["Restaurant User"], br, create_employee=False)
        item = self._make_item("AUDITEM", rate=50.0)
        ord_doc = frappe.get_doc({
            "doctype": "Restaurant Order",
            "order_name": f"AUD-{self.suffix}",
            "customer": self.customer,
            "waiter": emp_w["employee"],
            "items": [{"item_code": item, "qty": 1, "base_rate": 50.0}],
        }).insert(ignore_permissions=True)

        frappe.set_user(audu["user"])
        with self.assertRaises(frappe.PermissionError):
            pos.unlock_waiter_order(ord_doc.name, "9999")
        log_row = frappe.db.get_value(
            "Restaurant Audit Log",
            {"restaurant_order": ord_doc.name, "action": "PIN de mesero incorrecto"},
            "result",
        )
        self.assertEqual(log_row, "Rechazado")

    def test_kds_realtime_event_emitted_on_order_and_ticket_mutations(self):
        """Verify doc_events + kds._mutation_result push restaurant_kds_update with after_commit=True."""
        from unittest.mock import patch

        branch = self._make_branch("RT")
        wh = self._make_warehouse("RTWh")
        prof = self._make_pos_profile("RTPOS", wh, update_stock=0)
        frappe.db.set_value("POS Profile", prof, "branch", branch)
        area = frappe.get_doc({
            "doctype": "Restaurant Area",
            "area_name": f"SalonRT-{self.suffix}",
            "branch": branch,
            "capacity": 10,
            "status": "Activa",
            "visible_in_pos": 1,
        }).insert(ignore_permissions=True).name
        table = frappe.get_doc({
            "doctype": "Restaurant Table",
            "restaurant_area": area,
            "branch": branch,
            "table_number": f"RT1-{self.suffix}",
            "seats": 4,
            "status": "Disponible",
        }).insert(ignore_permissions=True).name
        item = self._make_item("RTITEM", rate=80.0, tax_pct=15.0)
        caj = self._make_user_and_employee("rtcaj", "Cajero (Completo)", ["Restaurant User", "Restaurant Cashier"], branch)

        frappe.set_user("Administrator")
        stages = [
            kds.save_stage({"stage_name": f"{lbl}-{self.suffix}", "color": "#22C55E", "alert_minutes": 10})["name"]
            for lbl in ("Preparar", "Listo", "Servido")
        ]
        disp_name = kds.save_display({
            "display_name": f"KdsRT-{self.suffix}",
            "enabled": 1,
            "branch": branch,
            "pos_profiles": [prof],
            "stages": stages,
        })["name"]
        shift = frappe.get_doc({
            "doctype": "POS Opening Shift",
            "period_start_date": now_datetime(),
            "company": self.company,
            "user": caj["user"],
            "pos_profile": prof,
            "balance_details": [{"mode_of_payment": self.cash_mop, "opening_amount": 0.0}],
        }).insert(ignore_permissions=True).submit()

        frappe.set_user(caj["user"])
        with patch("frappe.publish_realtime") as rt_mock:
            saved = pos.save_pos_order({
                "order_name": f"RT-{self.suffix}",
                "pos_profile": prof,
                "pos_opening_shift": shift.name,
                "restaurant_area": area,
                "restaurant_table": table,
                "customer": self.customer,
                "items": [{"item_code": item, "qty": 1}],
            })
            order_name = saved["order"]["name"]
            self.assertEqual(saved["order"].get("branch"), branch)
            rt_calls = [c for c in rt_mock.call_args_list if c.args and c.args[0] == "restaurant_kds_update"]
            self.assertTrue(rt_calls, "save_pos_order debe emitir evento restaurant_kds_update")
            self.assertTrue(rt_calls[-1].kwargs.get("after_commit"))
            self.assertEqual(set(rt_calls[-1].args[1]), {"source", "ts"})

            rt_mock.reset_mock()
            pos.send_order_to_kitchen(order_name)
            send_calls = [c for c in rt_mock.call_args_list if c.args and c.args[0] == "restaurant_kds_update"]
            self.assertTrue(send_calls, "send_order_to_kitchen debe emitir restaurant_kds_update")

            rt_mock.reset_mock()
            state = kds.get_kds_state(display_name=disp_name)
            card = next(o for o in state["orders"] if o["name"] == order_name)
            kds.toggle_item(
                display_name=disp_name,
                order_name=order_name,
                item_name=card["items"][0]["name"],
                expected_stage=card["kds_stage"],
                completed=1,
                ticket_id=card["ticket_name"],
            )
            ticket_calls = [c for c in rt_mock.call_args_list if c.args and c.args[0] == "restaurant_kds_update"]
            self.assertTrue(ticket_calls, "kds.toggle_item debe emitir restaurant_kds_update")
            self.assertEqual(ticket_calls[-1].args[1].get("source"), "kds_ticket")

            rt_mock.reset_mock()
            pos.pay_and_invoice_order(
                order_name=order_name,
                payments=[{"mode_of_payment": self.cash_mop, "amount": flt(saved["order"]["grand_total"], 2)}],
            )
            pay_calls = [c for c in rt_mock.call_args_list if c.args and c.args[0] == "restaurant_kds_update"]
            self.assertTrue(pay_calls, "pay_and_invoice_order debe emitir restaurant_kds_update")
            self.assertEqual(set(pay_calls[-1].args[1]), {"source", "ts"})

    def test_kds_state_and_pos_config_sql_budget(self):
        """Verify get_kds_state batching cuts N+1 queries and get_restaurant_pos_config is read-only."""
        branch = self._make_branch("SqlB")
        wh = self._make_warehouse("SqlWh")
        prof = self._make_pos_profile("SqlPOS", wh, update_stock=0)
        frappe.db.set_value("POS Profile", prof, "branch", branch)
        area = frappe.get_doc({
            "doctype": "Restaurant Area",
            "area_name": f"SalonSql-{self.suffix}",
            "branch": branch,
            "capacity": 10,
            "status": "Activa",
            "visible_in_pos": 1,
        }).insert(ignore_permissions=True).name
        table = frappe.get_doc({
            "doctype": "Restaurant Table",
            "restaurant_area": area,
            "branch": branch,
            "table_number": f"S1-{self.suffix}",
            "seats": 4,
            "status": "Disponible",
        }).insert(ignore_permissions=True).name
        item = self._make_item("SQLITEM", rate=65.0, tax_pct=15.0)
        stages = [
            kds.save_stage({"stage_name": f"{lbl}Sql-{self.suffix}", "color": "#3B82F6", "alert_minutes": 10})["name"]
            for lbl in ("Preparar", "Listo", "Servido")
        ]
        disp_name = kds.save_display({
            "display_name": f"KdsSql-{self.suffix}",
            "enabled": 1,
            "branch": branch,
            "pos_profiles": [prof],
            "stages": stages,
        })["name"]
        caj = self._make_user_and_employee("sqlc", "Cajero (Completo)", ["Restaurant User", "Restaurant Cashier"], branch)

        frappe.set_user(caj["user"])
        for idx in range(5):
            o = pos.save_pos_order({
                "order_name": f"SQL-{idx}-{self.suffix}",
                "pos_profile": prof,
                "restaurant_area": area,
                "restaurant_table": table if idx == 0 else None,
                "customer": self.customer,
                "items": [{"item_code": item, "qty": idx + 1}],
            })
            pos.send_order_to_kitchen(o["order"]["name"])

        # Warm DocType metadata cache once to measure steady-state runtime SQL budget cleanly.
        kds.get_kds_state(display_name=disp_name)

        orig_sql = frappe.db.sql
        queries = []

        def tracked_sql(query, *args, **kwargs):
            queries.append(str(query))
            return orig_sql(query, *args, **kwargs)

        try:
            frappe.db.sql = tracked_sql
            kds.get_kds_state(display_name=disp_name)
            kds_sql_count = len(queries)
            self.assertLessEqual(kds_sql_count, 25, f"get_kds_state ejecutó {kds_sql_count} SQL queries")

            queries.clear()
            pos.get_restaurant_pos_config(pos_profile=prof)
            writes = [
                q for q in queries
                if any(k in q.upper() for k in ("UPDATE `TABCUSTOM HTML BLOCK", "INSERT INTO", "DELETE FROM"))
            ]
            self.assertFalse(writes, f"get_restaurant_pos_config ejecutó escrituras en GET: {writes}")
        finally:
            frappe.db.sql = orig_sql
