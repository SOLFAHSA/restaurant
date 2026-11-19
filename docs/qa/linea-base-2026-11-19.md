# Línea base de pruebas — 2026-11-19

- **Rama:** `feature/modulo-restaurante`
- **Commit:** `73e92da` (HEAD tras los 3 commits de la Fase 0)
- **Sitio:** `test_restaurant`, exclusivo para pruebas (frappe, erpnext, posawesome, restaurant; `allow_tests` activo; preparación nativa `erpnext.setup.utils.before_tests` ejecutada). El sitio `development` no se tocó.
- **Comando:**

```bash
docker exec -e MYSQL_HOME=/tmp/leaf_mycnf -w /workspace/development/frappe-bench frappe_docker14_devcontainer-frappe-1 bash -lc 'bench --site test_restaurant run-tests --app restaurant --skip-test-records'
```

`MYSQL_HOME=/tmp/leaf_mycnf` apunta a un `my.cnf` temporal con `[client] skip-ssl`: el cliente MariaDB 11.8 del contenedor exige SSL y el servidor no lo ofrece.

## Resultado (VERIFIED)

| Ejecutadas | Aprobadas | Fallos | Errores | Omitidas | Duración |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 246 | 119 | 40 | 74 | 13 | 160,2 s |

## Por qué se usó `--skip-test-records` (VERIFIED)

Sin esa opción la suite aborta antes de ejecutar ninguna prueba, tanto en `development` como en `test_restaurant`. La cadena de dependencias de prueba es **Restaurant Area → Employee → Company → POS Offer → Brand → Account**. El enlace Company → POS Offer viene de dos Custom Fields de **POS Awesome** (`Company-posa_customer_offer`, `Company-posa_primary_offer`). Frappe marca `Company` como "en proceso", baja hasta `Account` y esta intenta nombrarse con `_Test Company`, que aún no existe:

```
erpnext/accounts/utils.py:1306 get_autoname_with_number
TypeError: sequence item 1: expected str instance, NoneType found
```

No es un defecto del código del Restaurante. Afecta a cualquier suite de este bench que tenga POS Awesome instalado.

## Lectura de los fallos (ANALYZED)

| Causa | Cantidad aprox. | Tipo |
| :--- | :--- | :--- |
| `Selecciona un cliente válido para la cuenta u orden.` (`pos.py:278`): las pruebas usan un cliente que existe en `development` y no en un sitio limpio | 60 | Entorno |
| `Development requires a POS Profile with a test SAR series` y similares: las pruebas exigen un POS Profile con serie SAR propio de `development` | 39 | Entorno |
| `POS Profile None not found`: consecuencia de lo anterior | 11 | Entorno |
| `Los datos semilla solo pueden ejecutarse en development con modo desarrollador activo.`: protección intencional de `test_demo_data` | 3 | Entorno (por diseño) |
| `test_pos_startup.test_kds_page_loader_and_orders_api_return_stage_metadata`: `0 not greater than or equal to 3` (probablemente faltan etapas KDS configuradas) | 1 | Por confirmar |

**Conclusión:** en un sitio limpio, prácticamente todos los fallos vienen de que las pruebas **dependen de los datos del sitio `development`** (cliente, POS Profile con serie SAR de prueba y etapas KDS), no de defectos confirmados de la lógica. Esta línea base mide la **autonomía de la suite**, no la corrección del módulo. Los resultados se registran, no se corrigen.

## Hallazgos para las siguientes fases (PROPOSED)

1. Hacer la suite autosuficiente: que cada prueba cree su propio cliente, POS Profile con serie SAR de prueba y etapas KDS (fixtures en `setUpClass` o un `before_tests` del Restaurante), en lugar de depender de `development`.
2. Resolver el ciclo Company → POS Offer de POS Awesome: `test_ignore` en los módulos de prueba del Restaurante o un `before_tests` que cree primero las dependencias de ERPNext. Requiere Native Path Check y aprobación.
3. Antes de la Fase 1 (hook `on_cancel`, pagos vacíos, límites de descuento), volver a correr esta línea base para comparar.

## Línea base v2: con datos base propios (VERIFIED)

Se agregó `restaurant/tests/fixtures.py` con `ensure_restaurant_test_baseline()`, que crea **solo lo que falta** y nunca modifica registros existentes (en `development` no hace nada): cliente "Consumidor Final", medios de pago "Efectivo" (Cash) y "Transferencia bancaria" (Bank) con sus cuentas, la cuenta "Banco QA Restaurante", el POS Profile "QA Restaurante" con serie SAR de prueba `000-099-01-.########`, el CAI de prueba `QA-RESTAURANTE-BASELINE` y 3 etapas de preparación. Se llama al inicio de `setUp` en `test_invoice_stock`, `test_kds`, `test_pos_auth`, `test_pos_startup` y `test_qa_comprehensive_audit`. No se tocó lógica del módulo.

| Corrida | Ejecutadas | Aprobadas | Fallos | Errores | Omitidas | Duración |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| v1 (sin datos base) | 246 | 119 | 40 | 74 | 13 | 160,2 s |
| **v2 (con datos base)** | 246 | **226** | 4 | 6 | 10 | 369,4 s |
| **v3 (con permiso de series SAR)** | 246 | **228** | 4 | 4 | 10 | 414,3 s |

### Fallos restantes (10)

| Módulo | Prueba | Mensaje | Lectura |
| :--- | :--- | :--- | :--- |
| test_demo_data | `test_existing_modified_demo_record_is_not_overwritten` | Los datos semilla solo pueden ejecutarse en development… | Entorno, por diseño |
| test_demo_data | `test_failed_run_rolls_back_new_records` | Ídem | Entorno, por diseño |
| test_demo_data | `test_repeat_execution_preserves_records_and_native_links` | Ídem | Entorno, por diseño |
| test_kds | `test_invoicing_preserves_virtual_and_materialized_kitchen_progress` | Development must provide an existing invoice link for the mock | Entorno: exige una Sales Invoice previa en el sitio |
| test_order_operations | `test_invoice_link_is_rejected_even_if_account_status_still_says_open` | Development must provide an existing invoice link | Entorno: ídem |
| test_order_operations | `test_split_then_pay_calls_native_invoice_lifecycle_with_exact_fractional_quantity` | Development must provide an existing invoice link for the mock | Entorno: ídem |
| test_order_operations | `test_merge_with_different_currency_is_rejected_without_mutation` | `'USD' == 'USD'` | Entorno: la prueba asume que la empresa no usa USD (en `development` es HNL) |
| test_qa_comprehensive_audit | `test_01_three_branch_thirty_user_full_operational_simulation` | El método de pago 'Transferencia bancaria' no está habilitado para este Punto de Venta. | Entorno: la prueba espera que el POS Profile habilite ese medio de pago |
| test_qa_comprehensive_audit | `test_03b_pure_cashier_can_submit_invoice_via_pos_api` | `PermissionError` en `si.insert` de `pay_and_invoice_order` (`pos.py:3259`) | **Por confirmar**: permisos de un rol de caja en el sitio limpio, o defecto real |
| test_qa_comprehensive_audit | `test_kds_realtime_event_emitted_on_order_and_ticket_mutations` | `PermissionError` en el mismo punto | **Por confirmar**: misma causa que la anterior |

**Conclusión v2 (ANALYZED):** 8 de los 10 fallos restantes son de entorno. Los 2 `PermissionError` al facturar como cajero deben investigarse antes de la Fase 1, porque tocan el flujo de cobro.

## v3: corrección de los 2 `PermissionError` del cajero (VERIFIED)

**Causa:** en ERPNext Grintsys, `SalesInvoice.before_naming` crea `Prefix sales for days` y `Daily summary series` con `doc.insert()` sin `ignore_permissions`, y solo System Manager puede crearlos. La primera factura de una serie SAR nueva emitida por un cajero falla. Detalle en [reporte-grintsys-permisos-serie-sar.md](reporte-grintsys-permisos-serie-sar.md).

**Mitigación (Nivel 2):** `restaurant/setup.py`, `ensure_cashier_permissions()`, otorga `read` y `create` sobre esos dos DocTypes a Restaurant Manager, Restaurant Cashier y Restaurant Direct Cashier (sin `write` ni `delete`). Se aplica en cada `bench migrate`.

**Verificación:** con los dos registros borrados (condición original del defecto) y tras `migrate`, `test_03b_pure_cashier_can_submit_invoice_via_pos_api` y `test_kds_realtime_event_emitted_on_order_and_ticket_mutations` pasan. Suite completa: 228/246, sin regresiones. Los 8 fallos restantes son los de entorno ya descritos en v2.

## Pruebas de reproducción de la Fase 1 (VERIFIED)

`restaurant/tests/test_phase1_known_defects.py` documenta 4 defectos con `@unittest.expectedFailure`. Resultado: `Ran 4 tests … OK (expected failures=4)`. Se verificó, sin la marca, que cada una falla por el defecto y no por la preparación:

| Prueba | Defecto | Evidencia sin la marca |
| :--- | :--- | :--- |
| `test_cancelled_invoice_does_not_leave_the_order_billed` | 1a: al anular la factura, la orden queda "Facturada" y enlazada | La orden sigue apuntando a la factura anulada |
| `test_cancelled_invoice_restores_the_gift_card_balance` | 1a: no se devuelve el saldo de la tarjeta de regalo | Saldo 0, se esperaba 50 |
| `test_cashier_cannot_exceed_the_pos_profile_discount_limit_alone` | 1c: el cajero supera `posa_max_discount_allowed` sin supervisor | Se guardó 50% con límite 10% (5% sí pasa) |
| `test_item_max_discount_is_enforced_when_the_order_is_saved` | 1c: `Item.max_discount` no se valida al guardar la orden | Se guardó 50% con máximo 10% |

Cuando la Fase 1 corrija un defecto, unittest reportará *unexpected success*: en ese momento hay que quitar la marca de esa prueba. El cobro sin pagos (1b) no tiene prueba porque está pendiente la decisión de negocio.

## Detalle v1: pruebas con fallo o error (114)

| Tipo | Módulo | Prueba | Mensaje |
| :--- | :--- | :--- | :--- |
| FAIL | test_checkout_acceptance | `test_cash_change_is_deducted_from_expected_closing_cash` | AssertionError: None is not true : Development requires a POS Profile with a test SAR series |
| FAIL | test_checkout_acceptance | `test_default_payment_includes_native_discounted_tip_total` | AssertionError: None is not true : Development requires a POS Profile with a test SAR series |
| FAIL | test_checkout_acceptance | `test_default_payment_uses_discounted_total_for_omitted_empty_and_zero_rows` | AssertionError: None is not true : Development requires a POS Profile with a test SAR series |
| FAIL | test_checkout_acceptance | `test_explicit_cash_tender_is_preserved_with_global_discount` | AssertionError: None is not true : Development requires a POS Profile with a test SAR series |
| FAIL | test_checkout_acceptance | `test_full_global_discount_has_zero_tax_base_and_no_cash_tendered` | AssertionError: None is not true : Development requires a POS Profile with a test SAR series |
| FAIL | test_checkout_acceptance | `test_full_global_discount_zeroes_mixed_tax_bases` | AssertionError: None is not true : Development requires a POS Profile with a test SAR series |
| FAIL | test_checkout_acceptance | `test_full_global_fixed_discount_has_zero_total_and_payment` | AssertionError: None is not true : Development requires a POS Profile with a test SAR series |
| FAIL | test_checkout_acceptance | `test_full_line_discount_has_zero_total_and_no_cash_tendered` | AssertionError: None is not true : Development requires a POS Profile with a test SAR series |
| FAIL | test_checkout_acceptance | `test_gift_card_reduces_default_payment_after_discount` | AssertionError: None is not true : Development requires a POS Profile with a test SAR series |
| FAIL | test_checkout_acceptance | `test_gift_card_with_payment_account_uses_discounted_cash_remainder` | AssertionError: None is not true : Development requires a POS Profile with a test SAR series |
| FAIL | test_checkout_acceptance | `test_global_fixed_discount_recalculates_tax_and_ticket` | AssertionError: None is not true : Development requires a POS Profile with a test SAR series |
| FAIL | test_checkout_acceptance | `test_global_percentage_discount_recalculates_tax_and_ticket` | AssertionError: None is not true : Development requires a POS Profile with a test SAR series |
| FAIL | test_checkout_acceptance | `test_mixed_payment_reconciles_and_cash_count_closes_only_temporary_shift` | AssertionError: None is not true : Development requires a POS Profile with a test SAR series |
| FAIL | test_checkout_acceptance | `test_mixed_tax_bases_and_ticket_match_independent_expected_amounts` | AssertionError: None is not true : Development requires a POS Profile with a test SAR series |
| FAIL | test_checkout_acceptance | `test_sar_summary_preserves_zero_and_legacy_missing_net_amount` | AssertionError: None is not true : Development requires a POS Profile with a test SAR series |
| FAIL | test_checkout_acceptance | `test_zero_price_invoice_posts_and_reverses_native_stock` | AssertionError: None is not true : Development requires a POS Profile with a test SAR series |
| FAIL | test_checkout_acceptance | `test_zero_total_does_not_redeem_gift_card` | AssertionError: None is not true : Development requires a POS Profile with a test SAR series |
| ERROR | test_demo_data | `test_existing_modified_demo_record_is_not_overwritten` | frappe.exceptions.PermissionError: Los datos semilla solo pueden ejecutarse en development con modo desarrollador activo. |
| ERROR | test_demo_data | `test_failed_run_rolls_back_new_records` | frappe.exceptions.PermissionError: Los datos semilla solo pueden ejecutarse en development con modo desarrollador activo. |
| ERROR | test_demo_data | `test_repeat_execution_preserves_records_and_native_links` | frappe.exceptions.PermissionError: Los datos semilla solo pueden ejecutarse en development con modo desarrollador activo. |
| FAIL | test_fiscal_numbering | `test_draft_with_expired_cai_cannot_be_submitted` | AssertionError: None is not true : Development requires a POS Profile with a test SAR series |
| FAIL | test_fiscal_numbering | `test_duplicate_active_authorizations_are_rejected` | AssertionError: None is not true : Development requires a POS Profile with a test SAR series |
| FAIL | test_fiscal_numbering | `test_expired_authorization_is_rejected` | AssertionError: None is not true : Development requires a POS Profile with a test SAR series |
| FAIL | test_fiscal_numbering | `test_expired_pending_authorization_does_not_replace_the_active_cai` | AssertionError: None is not true : Development requires a POS Profile with a test SAR series |
| FAIL | test_fiscal_numbering | `test_fractional_authorized_number_is_rejected` | AssertionError: None is not true : Development requires a POS Profile with a test SAR series |
| FAIL | test_fiscal_numbering | `test_last_folio_is_valid_then_series_is_exhausted` | AssertionError: None is not true : Development requires a POS Profile with a test SAR series |
| FAIL | test_fiscal_numbering | `test_missing_authorization_does_not_use_another_series` | AssertionError: None is not true : Development requires a POS Profile with a test SAR series |
| FAIL | test_fiscal_numbering | `test_pending_authorization_can_start_without_an_active_cai` | AssertionError: None is not true : Development requires a POS Profile with a test SAR series |
| FAIL | test_fiscal_numbering | `test_precheck_repeated_then_first_folio_starts_at_authorized_number` | AssertionError: None is not true : Development requires a POS Profile with a test SAR series |
| FAIL | test_fiscal_numbering | `test_renewal_does_not_reuse_an_overlapping_folio` | AssertionError: None is not true : Development requires a POS Profile with a test SAR series |
| FAIL | test_fiscal_numbering | `test_stock_rejection_rolls_back_cai_activation_and_folio` | AssertionError: None is not true : Development requires a POS Profile with a test SAR series |
| FAIL | test_invoice_stock | `test_draft_invoice_rechecks_stock_on_later_submission` | AssertionError: None is not true : Development requires a POS Profile with a test SAR series |
| FAIL | test_invoice_stock | `test_exact_stock_in_mixed_invoice_posts_once_and_cancel_restores_stock` | AssertionError: None is not true : Development requires a POS Profile with a test SAR series |
| FAIL | test_invoice_stock | `test_legacy_stock_draft_cannot_submit_without_tracking` | AssertionError: None is not true : Development requires a POS Profile with a test SAR series |
| FAIL | test_invoice_stock | `test_nonstock_item_can_be_invoiced_without_stock_movement` | AssertionError: None is not true : Development requires a POS Profile with a test SAR series |
| FAIL | test_invoice_stock | `test_repeated_lines_use_converted_quantity_even_if_item_allows_negative_stock` | AssertionError: None is not true : Development requires a POS Profile with a test SAR series |
| FAIL | test_invoice_stock | `test_stock_item_requires_a_warehouse_on_the_pos_profile` | AssertionError: None is not true : Development requires a POS Profile with a test SAR series |
| FAIL | test_invoice_stock | `test_stock_report_distinguishes_available_empty_and_nonstock` | AssertionError: None is not true : Development requires a POS Profile with a test SAR series |
| FAIL | test_invoice_stock | `test_zero_stock_in_pos_warehouse_blocks_even_when_another_warehouse_has_stock` | AssertionError: None is not true : Development requires a POS Profile with a test SAR series |
| ERROR | test_kds | `test_active_ticket_keeps_stage_snapshot_after_configuration_edit` | frappe.exceptions.ValidationError: Selecciona un cliente válido para la cuenta u orden. |
| ERROR | test_kds | `test_automatic_retirement_uses_completion_time_and_preserves_orders` | frappe.exceptions.ValidationError: Selecciona un cliente válido para la cuenta u orden. |
| ERROR | test_kds | `test_cannot_dismiss_incomplete_ticket_and_reset_restores_first_stage` | frappe.exceptions.ValidationError: Selecciona un cliente válido para la cuenta u orden. |
| ERROR | test_kds | `test_category_filter_hides_other_lines_and_prevents_toggling_them` | frappe.exceptions.ValidationError: Selecciona un cliente válido para la cuenta u orden. |
| ERROR | test_kds | `test_completed_split_keeps_remaining_line_identity_without_reopening_kitchen` | frappe.exceptions.ValidationError: Selecciona un cliente válido para la cuenta u orden. |
| ERROR | test_kds | `test_disabled_automatic_retirement_keeps_completed_ticket_visible` | frappe.exceptions.ValidationError: Selecciona un cliente válido para la cuenta u orden. |
| ERROR | test_kds | `test_each_stage_requires_all_lines_and_clears_strikes_for_next_stage` | frappe.exceptions.ValidationError: Selecciona un cliente válido para la cuenta u orden. |
| ERROR | test_kds | `test_existing_financial_order_is_not_rewritten_by_reading_display` | frappe.exceptions.ValidationError: Selecciona un cliente válido para la cuenta u orden. |
| ERROR | test_kds | `test_get_is_read_only_and_excludes_unsent_or_cancelled_orders` | frappe.exceptions.ValidationError: Selecciona un cliente válido para la cuenta u orden. |
| ERROR | test_kds | `test_legacy_order_with_new_sent_batch_does_not_reprepare_old_delivered_lines` | frappe.exceptions.ValidationError: Selecciona un cliente válido para la cuenta u orden. |
| ERROR | test_kds | `test_marks_and_stage_timer_persist_across_reloads_and_repeat_is_idempotent` | frappe.exceptions.ValidationError: Selecciona un cliente válido para la cuenta u orden. |
| ERROR | test_kds | `test_new_sent_line_reopens_only_new_batch_after_completed_ticket_was_cleared` | frappe.exceptions.ValidationError: Selecciona un cliente válido para la cuenta u orden. |
| ERROR | test_kds | `test_order_write_permission_is_required_before_kitchen_mutation` | frappe.exceptions.ValidationError: Selecciona un cliente válido para la cuenta u orden. |
| ERROR | test_kds | `test_pending_lines_of_partially_sent_order_are_not_visible_or_mutable` | frappe.exceptions.ValidationError: Selecciona un cliente válido para la cuenta u orden. |
| ERROR | test_kds | `test_pos_cannot_forge_native_item_group_or_kitchen_routing` | frappe.exceptions.ValidationError: Selecciona un cliente válido para la cuenta u orden. |
| ERROR | test_kds | `test_pos_save_preserves_sent_row_identity_and_ignores_forged_kitchen_state` | frappe.exceptions.ValidationError: Selecciona un cliente válido para la cuenta u orden. |
| ERROR | test_kds | `test_reenabled_display_recovers_its_unfinished_ticket_after_other_display_retires` | frappe.exceptions.ValidationError: Selecciona un cliente válido para la cuenta u orden. |
| ERROR | test_kds | `test_reprinting_does_not_reopen_completed_preparation` | frappe.exceptions.ValidationError: Selecciona un cliente válido para la cuenta u orden. |
| ERROR | test_kds | `test_same_order_on_two_displays_has_independent_progress` | frappe.exceptions.ValidationError: Selecciona un cliente válido para la cuenta u orden. |
| ERROR | test_kds | `test_simple_table_transfer_and_active_merge_preserve_independent_kitchen_tickets` | frappe.exceptions.ValidationError: Selecciona un cliente válido para la cuenta u orden. |
| ERROR | test_kds | `test_split_preserves_active_kitchen_progress_with_or_without_ticket` | frappe.exceptions.ValidationError: Selecciona un cliente válido para la cuenta u orden. |
| ERROR | test_kds | `test_stale_stage_is_rejected_before_mutation` | frappe.exceptions.ValidationError: Selecciona un cliente válido para la cuenta u orden. |
| ERROR | test_kds | `test_untouched_enabled_display_is_captured_before_peer_changes_global_state` | frappe.exceptions.ValidationError: Selecciona un cliente válido para la cuenta u orden. |
| FAIL | test_kds | `test_invoicing_preserves_virtual_and_materialized_kitchen_progress` | AssertionError: None is not true : Development must provide an existing invoice link for the mock |
| FAIL | test_kds | `test_pos_profile_filter_is_applied_on_server` | AssertionError: None is not true : Development must provide a native POS Profile |
| ERROR | test_order_operations | `test_billed_and_cancelled_accounts_cannot_be_split_or_transferred` | frappe.exceptions.ValidationError: Selecciona un cliente válido para la cuenta u orden. |
| ERROR | test_order_operations | `test_context_and_split_preview_are_read_only` | frappe.exceptions.ValidationError: Selecciona un cliente válido para la cuenta u orden. |
| ERROR | test_order_operations | `test_duplicate_foreign_and_missing_lines_are_rejected` | frappe.exceptions.ValidationError: Selecciona un cliente válido para la cuenta u orden. |
| ERROR | test_order_operations | `test_empty_open_target_account_can_receive_food_and_its_kitchen_progress` | frappe.exceptions.ValidationError: Selecciona un cliente válido para la cuenta u orden. |
| ERROR | test_order_operations | `test_fixed_tip_is_partitioned_without_duplication` | frappe.exceptions.ValidationError: Selecciona un cliente válido para la cuenta u orden. |
| ERROR | test_order_operations | `test_fractional_native_quantity_survives_split_response_and_pos_save_roundtrip` | frappe.exceptions.ValidationError: Selecciona un cliente válido para la cuenta u orden. |
| ERROR | test_order_operations | `test_full_merge_to_occupied_table_preserves_amounts_and_target_line_ids` | frappe.exceptions.ValidationError: Selecciona un cliente válido para la cuenta u orden. |
| ERROR | test_order_operations | `test_guest_and_order_write_denied_cannot_split` | frappe.exceptions.ValidationError: Selecciona un cliente válido para la cuenta u orden. |
| ERROR | test_order_operations | `test_invalid_split_quantities_are_rejected_without_mutation` | frappe.exceptions.ValidationError: Selecciona un cliente válido para la cuenta u orden. |
| ERROR | test_order_operations | `test_merge_preserves_independent_segments_at_different_preparation_stages` | frappe.exceptions.ValidationError: Selecciona un cliente válido para la cuenta u orden. |
| ERROR | test_order_operations | `test_merge_with_different_currency_is_rejected_without_mutation` | frappe.exceptions.ValidationError: Selecciona un cliente válido para la cuenta u orden. |
| ERROR | test_order_operations | `test_moving_current_batch_does_not_reopen_older_delivered_rows_remaining_at_source` | frappe.exceptions.ValidationError: Selecciona un cliente válido para la cuenta u orden. |
| ERROR | test_order_operations | `test_native_whole_number_uom_rejects_fractional_selection` | frappe.exceptions.ValidationError: Selecciona un cliente válido para la cuenta u orden. |
| ERROR | test_order_operations | `test_partial_merge_rolls_back_both_accounts_and_tables_if_kitchen_remap_fails` | frappe.exceptions.ValidationError: Selecciona un cliente válido para la cuenta u orden. |
| ERROR | test_order_operations | `test_partial_split_normalizes_already_marked_subset_without_repreparation` | frappe.exceptions.ValidationError: Selecciona un cliente válido para la cuenta u orden. |
| ERROR | test_order_operations | `test_partial_split_preserves_quantities_options_taxes_tips_and_remaining_row_identity` | frappe.exceptions.ValidationError: Selecciona un cliente válido para la cuenta u orden. |
| ERROR | test_order_operations | `test_partial_transfer_to_empty_table_creates_only_one_new_account` | frappe.exceptions.ValidationError: Selecciona un cliente válido para la cuenta u orden. |
| ERROR | test_order_operations | `test_partial_transfer_to_existing_account_does_not_create_an_orphan_order` | frappe.exceptions.ValidationError: Selecciona un cliente válido para la cuenta u orden. |
| ERROR | test_order_operations | `test_retired_ticket_stays_retired_when_quantities_are_split` | frappe.exceptions.ValidationError: Selecciona un cliente válido para la cuenta u orden. |
| ERROR | test_order_operations | `test_selecting_every_quantity_cannot_leave_an_empty_split_account` | frappe.exceptions.ValidationError: Selecciona un cliente válido para la cuenta u orden. |
| ERROR | test_order_operations | `test_sent_food_remains_visible_when_merged_into_an_unsent_account` | frappe.exceptions.ValidationError: Selecciona un cliente válido para la cuenta u orden. |
| ERROR | test_order_operations | `test_source_cannot_be_its_own_target` | frappe.exceptions.ValidationError: Selecciona un cliente válido para la cuenta u orden. |
| ERROR | test_order_operations | `test_split_preserves_distinct_stages_and_native_category_filters_on_multiple_displays` | frappe.exceptions.ValidationError: Selecciona un cliente válido para la cuenta u orden. |
| ERROR | test_order_operations | `test_split_preview_matches_persisted_totals_and_exposes_rounding_difference` | frappe.exceptions.ValidationError: Selecciona un cliente válido para la cuenta u orden. |
| ERROR | test_order_operations | `test_split_rolls_back_order_creation_and_tickets_if_kitchen_remap_fails` | frappe.exceptions.ValidationError: Selecciona un cliente válido para la cuenta u orden. |
| ERROR | test_order_operations | `test_split_then_pay_calls_native_invoice_lifecycle_with_exact_fractional_quantity` | frappe.exceptions.ValidationError: Selecciona un cliente válido para la cuenta u orden. |
| ERROR | test_order_operations | `test_splitting_completed_ticket_does_not_reopen_delivered_food` | frappe.exceptions.ValidationError: Selecciona un cliente válido para la cuenta u orden. |
| ERROR | test_order_operations | `test_stale_or_closed_target_is_rejected_before_changing_source` | frappe.exceptions.ValidationError: Selecciona un cliente válido para la cuenta u orden. |
| ERROR | test_order_operations | `test_stale_source_version_is_rejected_for_preview_split_and_transfer` | frappe.exceptions.ValidationError: Selecciona un cliente válido para la cuenta u orden. |
| ERROR | test_order_operations | `test_target_account_without_table_can_receive_a_full_transfer` | frappe.exceptions.ValidationError: Selecciona un cliente válido para la cuenta u orden. |
| ERROR | test_order_operations | `test_target_write_permission_is_required_before_merging` | frappe.exceptions.ValidationError: Selecciona un cliente válido para la cuenta u orden. |
| ERROR | test_order_operations | `test_ticket_identifier_from_another_order_or_display_is_rejected_without_writes` | frappe.exceptions.ValidationError: Selecciona un cliente válido para la cuenta u orden. |
| ERROR | test_order_operations | `test_transfer_to_empty_table_preserves_order_lines_and_kitchen_progress` | frappe.exceptions.ValidationError: Selecciona un cliente válido para la cuenta u orden. |
| ERROR | test_order_operations | `test_unsent_food_does_not_enter_kitchen_when_merged_into_a_sent_account` | frappe.exceptions.ValidationError: Selecciona un cliente válido para la cuenta u orden. |
| FAIL | test_order_operations | `test_invoice_link_is_rejected_even_if_account_status_still_says_open` | AssertionError: None is not true : Development must provide an existing invoice link |
| ERROR | test_pos_auth | `test_cashier_bypasses_waiter_pin_and_needs_supervisor_for_cancel` | frappe.exceptions.ValidationError: Selecciona un cliente válido para la cuenta u orden. |
| ERROR | test_pos_auth | `test_linked_employee_waiter_isolation` | frappe.exceptions.ValidationError: Selecciona un cliente válido para la cuenta u orden. |
| ERROR | test_pos_auth | `test_shared_terminal_waiter_pin_unlock` | frappe.exceptions.ValidationError: Selecciona un cliente válido para la cuenta u orden. |
| FAIL | test_pos_startup | `test_kds_page_loader_and_orders_api_return_stage_metadata` | AssertionError: 0 not greater than or equal to 3 |
| ERROR | test_qa_comprehensive_audit | `test_01_three_branch_thirty_user_full_operational_simulation` | frappe.exceptions.DoesNotExistError: POS Profile None not found |
| ERROR | test_qa_comprehensive_audit | `test_02_sql_query_count_and_n_plus_one_profile` | frappe.exceptions.DoesNotExistError: POS Profile None not found |
| ERROR | test_qa_comprehensive_audit | `test_03b_pure_cashier_can_submit_invoice_via_pos_api` | frappe.exceptions.DoesNotExistError: POS Profile None not found |
| ERROR | test_qa_comprehensive_audit | `test_def_qa_04_manager_can_close_cashier_shift_via_cash_count` | frappe.exceptions.DoesNotExistError: POS Profile None not found |
| ERROR | test_qa_comprehensive_audit | `test_def_qa_05_exonerated_and_update_stock_not_overwritten_by_set_missing_values` | frappe.exceptions.DoesNotExistError: POS Profile None not found |
| ERROR | test_qa_comprehensive_audit | `test_def_qa_06_branch_isolation_in_bootstrap_orders` | frappe.exceptions.DoesNotExistError: POS Profile None not found |
| ERROR | test_qa_comprehensive_audit | `test_def_qa_07_other_cashier_blocked_from_reading_or_counting_foreign_shift` | frappe.exceptions.DoesNotExistError: POS Profile None not found |
| ERROR | test_qa_comprehensive_audit | `test_def_qa_10_gift_card_redemption_deducts_from_invoice_cash_due` | frappe.exceptions.DoesNotExistError: POS Profile None not found |
| ERROR | test_qa_comprehensive_audit | `test_def_qa_12_mixed_isv15_isv18_order_does_not_double_tax_on_invoice` | frappe.exceptions.DoesNotExistError: POS Profile None not found |
| ERROR | test_qa_comprehensive_audit | `test_kds_realtime_event_emitted_on_order_and_ticket_mutations` | frappe.exceptions.DoesNotExistError: POS Profile None not found |
| ERROR | test_qa_comprehensive_audit | `test_kds_state_and_pos_config_sql_budget` | frappe.exceptions.DoesNotExistError: POS Profile None not found |
