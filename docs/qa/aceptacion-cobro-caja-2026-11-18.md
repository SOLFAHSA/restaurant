# Aceptación de cobro y caja del 18/11/2026

**Issue de seguimiento** [#12](https://github.com/SOLFAHSA/restaurant/issues/12)

**Entorno** development, Python 3.11, Frappe y ERPNext v14.

**Fuente transaccional** Sales Invoice, GL Entry, POS Opening Shift y POS Closing Shift nativos.

**Alcance** QA de impuestos mixtos, descuentos, pagos, vuelto y arqueo temporal.

**Estado actual** VERIFIED. Corrección autorizada de DEF-2026-017 aplicada y verificada. Se aprobaron 51 pruebas distintas. La evidencia de detección inicial se conserva a continuación.

## Resultados de la detección inicial

| Caso | Datos y resultado esperado | Resultado observado |
|---|---|---|
| Mezcla 15%, 18% y exento | Tres artículos de L 100. Bases de L 100 por categoría, ISV de L 15 y L 18, total L 333. | VERIFIED. Factura, ticket y conciliación comprobados. |
| Descuento global del 10% | Base inicial L 100 e ISV 15%. Descuento sobre total L 11.50, base final L 90, ISV L 13.50, total L 103.50. | VERIFIED. Importes persistidos y ticket coinciden. |
| Descuento global de L 10 | Venta original L 115. Base final L 91.30, ISV L 13.70, total L 105. | VERIFIED. Importes persistidos y descuento del ticket coinciden. |
| Descuento de línea del 100% | Total, base gravada, pago y cambio iguales a cero. | VERIFIED. Caso aprobado. |
| Pago mixto y cierre | Venta L 115, efectivo L 50 y medio bancario L 65. Arqueo esperado y contado L 115, diferencia cero. | VERIFIED. Factura enviada, arqueo enviado y POS Closing Shift enviado. Se cerró el turno temporal. |
| Vuelto | Venta L 115 y efectivo entregado L 200. Cambio L 85 y efectivo esperado de caja L 115. | VERIFIED. Factura, ticket y vista previa de arqueo coinciden. |
| Descuento global del 100% | Total, base gravada, ISV, pago y cambio iguales a cero cuando se indica pago cero. | VERIFIED. Fallo DEF-2026-017. El total queda en cero, pero la base gravada, el ISV y los importes de cobro conservan valores anteriores al descuento. |

## Ejecución reproducible

Desde el Bench del DevContainer, con el sitio development.

~~~bash
bench --site development run-tests --module restaurant.tests.test_sar_ticket --skip-test-records --skip-before-tests
bench --site development run-tests --module restaurant.tests.test_checkout_acceptance --skip-test-records --skip-before-tests
~~~

La primera suite ejecutó 7 casos y terminó OK. La última ejecución de test_checkout_acceptance ejecutó 7 casos, con 6 aprobados y 1 fallo en test_full_global_discount_has_zero_tax_base_and_no_cash_tendered. El detalle de la aserción fue 100.0 != 0 para taxed_amount_15.

Se reutilizaron fixtures de inventario y CAI para configurar un perfil, almacén, turno, serie fiscal y artículos de prueba. La primera ejecución requirió completar denomination_label en los datos del arqueo. También se cambió la importación del fixture por una importación del módulo para limitar la selección a los casos de aceptación.

## DEF-2026-017

**Estado** Confirmado, VERIFIED.

**Severidad** Alta en el escenario de descuento global del 100%. Requiere corrección antes de aceptar ese escenario.

**Origen** Matriz técnica del issue #12.

**Participantes** Auditoría automatizada y comprobación puntual del desarrollador asistida en esta sesión. Frecuencia de usuarios del segmento pendiente.

### Reproducción

1. Configurar una serie y un turno temporales con descuento global permitido.
2. Crear un artículo de L 100 con ISV 15% y generar una orden de L 115.
3. Ejecutar pay_and_invoice_order con global_discount_percentage=100 y una fila de pago en efectivo con amount=0.
4. Consultar la factura confirmada y renderizar el Ticket.

### Evidencia previa a la corrección

| Campo | Esperado | Obtenido |
|---|---|---|
| net_total | L 0 | L 0 |
| grand_total | L 0 | L 0 |
| taxed_amount_15 | L 0 | L 100 |
| isv_15 | L 0 | L 15 |
| paid_amount | L 0 | L 115 |
| change_amount | L 0 | L 115 |

El Ticket renderizado mostró los mismos valores incorrectos de base, ISV, pago y cambio.

### Causa analizada

ANALYZED. En restaurant/pos.py, _sync_sar_tax_summary trata net_amount=0 como ausencia y recupera amount, que conserva el valor anterior al descuento. En pay_and_invoice_order, la fila de pago cero se descarta y el pago predeterminado toma doc.grand_total de la orden antes del descuento global. La factura nativa calcula correctamente grand_total=0, mientras los campos SAR y la fila de pago quedan inconsistentes.

### Propuesta inicial y alcance autorizado

PROPOSED. En restaurant/pos.py, respetar net_amount=0 al sincronizar el resumen fiscal y resolver el pago predeterminado a partir del total final calculado por ERPNext, conservando el tratamiento correcto de pagos explícitos y Gift Cards. Reutilizar calculate_taxes_and_totals y el ciclo nativo de Sales Invoice. La regresión está preparada en restaurant/tests/test_checkout_acceptance.py.

Verificar los siete casos de esta matriz y las suites SAR, inventario y CAI después del cambio. Para el uso operativo de cortesías, confirmar la política y la autorización de roles. El tratamiento tributario aplicable requiere validación tributaria local.

## Integridad de la prueba

VERIFIED. Las ejecuciones con Bench revirtieron los datos temporales mediante sus fixtures.

La comprobación puntual posterior, realizada fuera del runner de Bench para inspeccionar los campos del fallo, dejó persistidos sus documentos sintéticos. Se identificaron por perfil, serie, artículos y vínculos exactos. Se canceló su factura por la vía nativa y se retiraron exclusivamente los registros de esa comprobación. Se utilizó la operación interna de Restaurant para liberar el vínculo de su orden sintética después de cancelar la factura.

La verificación en una conexión independiente confirmó cero perfiles, artículos, CAI y plantillas de impuestos de prueba, y ausencia de la factura, orden y turno temporales identificados. El turno original POSA-OS-26-0000010 permanece abierto. Las seis facturas originales 22 a 27 siguen enviadas.

## Alcance pendiente

La matriz se ejecutó en backend con Administrator y datos sintéticos. La aceptación de interfaz, perfiles operativos y salida física de impresora se documentará con sus pruebas específicas. El issue #12 permanece en validación por DEF-2026-017 y por esa aceptación operativa.

**Dictamen de la detección inicial** Se aprobaron seis casos y se rechazó el descuento global del 100%. El dictamen actualizado figura en la sección siguiente.

## Corrección autorizada y verificada el 18/11/2026

Manuel autorizó corregir y probar los importes en development.

### Camino nativo y decisión arquitectónica

ANALYZED. ERPNext ya proporciona calculate_taxes_and_totals de Sales Invoice, el descuento global y el cálculo de pagos, cambio y saldo. Restaurant consume el total y las bases finales de ese controller. El cambio es de nivel arquitectónico 3, categoría C, dentro de la Custom App.

La revisión independiente de lógica y compatibilidad aprobó el delta. La revisión de integridad y migración determinó que la solución es prospectiva y no requiere parche ni migración para este alcance. La consulta encontró 17 facturas vinculadas a Restaurant y ninguna con additional_discount_percentage=100.

### Cambios aplicados

- restaurant/pos.py, _sync_sar_tax_summary. El valor net_amount=0 se conserva. El respaldo amount se utiliza cuando net_amount es None.
- restaurant/pos.py, pay_and_invoice_order. Se identifica la fila predeterminada de pago. Después del cálculo nativo se ajusta esa fila al grand_total final y se vuelve a invocar el cálculo nativo.
- El mismo indicador se usa para descontar la redención de Gift Card del remanente de pago predeterminado, incluyendo solicitudes con lista de importes cero.
- Los importes positivos explícitos se conservan como efectivo recibido.
- restaurant/tests/test_checkout_acceptance.py amplía las regresiones de cero, pagos, propina, Gift Cards y reversión nativa de inventario.

### Resultados de regresión

| Suite | Resultado comprobado |
|---|---|
| test_checkout_acceptance | VERIFIED. 17 casos distintos aprobados, ejecutados como grupo de 16 y un caso adicional de Gift Card con cuenta contable. |
| test_sar_ticket | VERIFIED. 7 de 7 aprobados. |
| test_invoice_stock | VERIFIED. 8 de 8 aprobados. |
| test_fiscal_numbering | VERIFIED. 11 de 11 aprobados. |
| test_pos_startup | VERIFIED. 8 de 8 aprobados. |
| Total | VERIFIED. 51 casos distintos aprobados. |

La regresión del descuento global del 100% comprueba grand_total=0, taxed_amount_15=0, isv_15=0, paid_amount=0 y change_amount=0, además del resumen del Ticket. Se comprobaron descuento total por monto, mezcla 15%/18%/exento, pagos omitidos o en cero, descuentos parciales, efectivo explícito con cambio, propina según cálculo nativo, Gift Card con y sin medio contable específico y saldo de tarjeta intacto cuando el total es cero. Una factura de total cero con artículo inventariable descontó una unidad y su cancelación nativa la restauró.

### Integridad y disponibilidad

VERIFIED. Las 17 facturas existentes, sus GL Entry y Stock Ledger Entry conservaron la huella SHA256 86e5d2e498c7d9922122cca168c62d313470a7b0e3be9ac23420afba406b9bd5 antes y después de las pruebas.

Una conexión independiente comprobó cero perfiles, artículos, plantillas fiscales, CAI, Gift Cards y cuentas de prueba remanentes. El turno original permanece abierto.

Bench Web se ejecutaba con noreload. Se reinició su sesión de depuración en VS Code para cargar el cambio y se comprobó respuesta HTTP 200 de development.

### Seguimiento y dictamen actual

VERIFIED. DEF-2026-017 queda corregido técnicamente en development. El issue #12 conserva pendiente la aceptación de interfaz con los perfiles operativos y la salida física de impresora, junto con el enlace al commit o PR de entrega. La política operativa de cortesías y su tratamiento tributario requieren validación tributaria local.

**Dictamen actual** APROBADO CON OBSERVACIONES para la corrección y las regresiones ejecutadas.
