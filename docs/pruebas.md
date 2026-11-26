# Estrategia de pruebas — Módulo Restaurante (semana 7)

**Proyecto:** Módulo Restaurante para LEAF ERP (Frappe v14 + ERPNext Grintsys + POS Awesome)
**Autor:** Manuel Padilla · **Fecha:** 25/11/2026

## 1. Principio

No se prueba todo: se prueba primero **donde más duele fallar**. En un restaurante, un error en el color de un botón molesta; un error en el ISV, en el cobro o en el inventario le cuesta dinero al negocio y problemas con el SAR. Por eso las pruebas se ordenan por los **cuatro focos de riesgo** del curso: reglas del negocio, permisos, dinero y flujo central.

## 2. Los cuatro focos de riesgo del Restaurante

### 2.1 Dinero (el foco más crítico)

| Qué no puede fallar | Nivel | Pruebas |
| :--- | :--- | :--- |
| ISV 15 % / 18 % / exento por producto con las plantillas nativas de ERPNext | Integración | `test_item_tax_resolution` (5), `test_native_fiscal_parity` (4) |
| La precuenta, la orden y la factura muestran los mismos totales, con y sin descuento; el vuelto se descuenta del efectivo esperado | Integración | `test_checkout_acceptance` (16), `test_order_invoice_totals` (2) |
| Descuentos dentro del límite del perfil; por encima, solo con supervisor y motivo | Integración | `test_phase1_known_defects` (5) |
| Pago mixto: varios métodos en una factura; **solo el efectivo da cambio** | Integración | `test_mixed_payment` (2) |
| Numeración fiscal SAR: CAI vigente, folio y serie | Integración | `test_fiscal_numbering` (11), `test_sar_ticket` (7) |
| El inventario sale al facturar y regresa al anular; los combos descuentan sus componentes | Integración | `test_invoice_stock` (7), `test_combo_stock` (5) |
| Arqueo y cierre de caja: faltantes y sobrantes, totales que no se pueden manipular y cierre del turno nativo | Integración | `test_restaurant_cash_count` (6), `test_restaurant_cash_denomination` (2) |

### 2.2 Permisos y propiedad del dato

| Qué no puede fallar | Nivel | Pruebas |
| :--- | :--- | :--- |
| El mesero no cobra, no da descuentos y no ve funciones administrativas | Integración | `test_rbac_security_regression` (6), `test_waiter_permissions_and_cancellations` (5) |
| Desbloqueo con PIN del mesero; autorización de supervisor con bitácora; el cajero necesita supervisor para anular | Integración | `test_pos_auth` (6) |
| Una empresa o sucursal no ve ni modifica las órdenes de otra; dos usuarios no se pisan los cambios de una misma cuenta | Integración | `test_order_company_isolation` (9)*, `test_multibranch_concurrency` (4) |
| El mesero ve precios de venta del menú, nunca precios de compra | Integración | `test_pos_catalog_prices` (2) |
| El tablero solo lo abren administradores y gerentes; el ticket promedio se calcula bien | Integración | `test_dashboard` (4) |

\* Hoy se omite en el sitio de pruebas porque necesita dos empresas con perfil de POS (ver brechas, sección 6).

### 2.3 Reglas del negocio

| Qué no puede fallar | Nivel | Pruebas |
| :--- | :--- | :--- |
| Estados de cocina: pendiente → en preparación → listo → entregado, por estación | Integración | `test_kds` (28), `test_restaurant_preparation_display` (4) |
| Configuración de platillos, opciones y combos | Integración | `test_item_configuration` (29) |
| Áreas, mesas y comandas | Integración | `test_restaurant_area` (11), `test_restaurant_area_list` (7), `test_restaurant_table` (4), `test_restaurant_command` (15) |
| Arranque del POS con perfil, turno y configuración correctos | Integración | `test_pos_startup` (8) |
| Datos de demostración solo en entornos de prueba | Integración | `test_demo_data` (5) |

### 2.4 Flujo central

**Abrir cuenta → agregar productos → enviar a cocina → precuenta → cobrar → factura SAR.**

| Qué no puede fallar | Nivel | Pruebas |
| :--- | :--- | :--- |
| Dividir, transferir y fusionar cuentas sin perder productos ni importes | Integración | `test_order_operations` (35) |
| Simulación operativa completa: 3 sucursales y 30 usuarios, más controles de seguridad y presupuesto de consultas | Integración | `test_qa_comprehensive_audit` (18) |
| La pantalla continúa al cobro después de la precuenta sin recargar | Unitaria (JavaScript) | `restaurant/tests/ui/precuenta_state.cjs` (4) |
| El cajero cobra una cuenta y obtiene su factura SAR **desde el navegador** | **Extremo a extremo** | Por crear (Playwright), sección 6 |
| El mesero **no ve** el botón de cobrar **desde el navegador** | **Extremo a extremo** | Por crear (Playwright), sección 6 |

## 3. Niveles de prueba y pirámide

| Nivel | Qué prueba | Herramienta | Cantidad hoy |
| :--- | :--- | :--- | :--- |
| Unitaria | Una regla aislada, en milisegundos | Node (`node:test`) para la lógica de pantalla | 4 |
| Integración | El caso de uso con la base de datos de prueba: orden, factura nativa, contabilidad e inventario | `FrappeTestCase` | 274 |
| Extremo a extremo | La app completa en un navegador, como un usuario | Playwright | 0 en ejecución |

**Lectura honesta:** la pirámide del proyecto está cargada hacia la integración. Es esperable en un módulo de ERP, porque casi cada regla depende de documentos nativos (factura, impuestos, inventario) que solo existen en la base de datos. Las reglas de cálculo que no tocan la base se irán separando en pruebas unitarias. Las de extremo a extremo serán **pocas**: solo el flujo central y el permiso crítico.

## 4. Cómo se escriben las pruebas

1. **Cada criterio es una prueba:** *Dado* (preparar), *Cuando* (una sola acción), *Entonces* (comprobar el resultado visible).
2. **El nombre de la prueba es la frase del criterio**, para que el reporte diga qué regla se rompió. Ejemplos:
   - `test_chosen_drink_leaves_the_warehouse_and_returns_on_cancel` — *la bebida elegida en el combo sale de bodega y regresa al anular.*
   - `test_card_cannot_pay_more_than_the_amount_due` — *la tarjeta no puede pagar más que el saldo pendiente.*
   - `test_cashier_cannot_invoice_above_the_pos_profile_discount_limit_alone` — *el cajero no factura un descuento sobre el límite sin supervisor.*
3. **También lo que NO debe pasar:** cajero sin permiso, tarjeta que paga de más, combo sin existencia, producto sin plantilla de impuesto, orden de otra empresa.
4. **Valores esperados fijos y calculados a mano** (por ejemplo, total L 115.00 = L 100.00 + ISV 15 %), nunca con la misma fórmula del código.
5. **Pruebas independientes:** cada una crea sus datos con un punto de guardado (`savepoint`) y los deshace al terminar. Ninguna depende del orden ni de datos de otra prueba.
6. **Nunca contra producción.** Se usa un sitio aparte, `test_restaurant`, con datos semilla propios (`restaurant/tests/fixtures.py`).

## 5. Cómo se ejecutan

Desde la terminal del contenedor de desarrollo, en la carpeta `frappe-bench`:

```bash
bench --site test_restaurant run-tests --app restaurant --skip-before-tests --skip-test-records
```

| Parte | Por qué |
| :--- | :--- |
| `--site test_restaurant` | Sitio exclusivo de pruebas, nunca el de desarrollo ni el de producción |
| `--skip-before-tests` | Evita el gancho `before_tests` de ERPNext, que **borra todos los precios de venta** (`tabItem Price`) |
| `--skip-test-records` | Evita los registros de prueba automáticos, que fallan por un ciclo de dependencias de POS Awesome; las pruebas crean sus propios datos |

Para un solo archivo: agregar `--module restaurant.tests.test_combo_stock`.

Prueba unitaria de pantalla: `node restaurant/tests/ui/precuenta_state.cjs`.

## 6. Brechas conocidas y plan de la semana 7

| Brecha | Plan |
| :--- | :--- |
| Las pruebas de navegador no corren: Playwright no está instalado | Instalarlo y escribir 2 pruebas de extremo a extremo: el flujo central del cajero y el permiso del mesero |
| No hay pipeline de integración continua | Crear `.github/workflows/` con los 5 pasos (descargar, instalar, estilo, pruebas, construir) y proteger la rama principal |
| `test_order_company_isolation` se omite | Agregar una segunda empresa con perfil de POS a los datos semilla del sitio de pruebas |
| Varias instrucciones antiguas mandaban correr las pruebas contra `development` sin `--skip-before-tests` | ✅ Corregido el 25/11/2026 en `comandas.md`, `kds-verificacion.md`, `pos-arranque.md` y `qa/como-ejecutar-pruebas.md` |
| La prueba del ticket promedio del tablero calculaba el valor esperado con la misma fórmula del código | ✅ Corregido el 25/11/2026: ahora usa L 345.00 en 3 facturas = L 115.00 |
| `test_fiscal_numbering` depende de cambios en el ERPNext de Grintsys que aún no están aprobados | Reportarlos a Grintsys y ajustar las pruebas según su decisión |

## 7. Regla del pipeline

Si el pipeline queda en rojo, **se arregla antes que cualquier otra cosa**. Una prueba que falla **nunca se desactiva ni se borra** para "pasar": si la prueba está mal, se corrige con su motivo en el pull request.
