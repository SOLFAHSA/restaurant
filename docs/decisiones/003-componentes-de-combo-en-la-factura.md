# 003 · Los componentes del combo viajan en la factura a precio 0 (23/11/2026)

**Estado:** Aceptada · **Issue:** #14

## Contexto

Al vender un combo (por ejemplo, "Menú combinado de hamburguesa"), solo la línea del combo llegaba a la factura. Las opciones elegidas por el cliente (la bebida) quedaban como texto, así que el inventario no bajaba. En la factura de prueba `000-002-01-00081510` la Coca-Cola siguió en 97 unidades después de venderla dentro del combo. El supervisor de práctica lo reportó como hallazgo grave en la semana 5 (S5-P1-01).

El combo no es una receta fija: cada cliente elige sus opciones (Coca-Cola, agua, batido…), y algunas tienen un recargo.

## Decisión

Al cobrar, cada opción "Incluir en combo" cuyo producto es **inventariable** se agrega a la factura de venta nativa como una línea más, **a precio 0**, con la cantidad del combo multiplicada por la cantidad configurada. ERPNext descuenta esas líneas del almacén del perfil de POS al emitir la factura y las devuelve al anularla. El producto, la cantidad y la unidad salen de la configuración del combo (`Restaurant Dish Option`), nunca del navegador. Los componentes que no son inventariables (platillos) no se agregan.

## Alternativas consideradas

- **Product Bundle nativo (paquete de productos).** Descartada por ahora: un paquete tiene componentes fijos, y el combo cambia según lo que elige cada cliente. Además, el módulo desactiva los paquetes de las recetas mientras los ingredientes no tengan existencia ni se permita existencia negativa. Se retomará para las recetas (parte B del #14).
- **Una entrada de inventario aparte (`Stock Entry`) al cobrar.** Descartada: separa el inventario de la venta. Anular la factura no revertiría la salida y habría que mantener la reversión a mano.
- **Dejar el inventario como estaba.** Descartada: el kárdex no cuadraría con lo vendido.

## Consecuencias

- La salida de inventario, su costo contable (costo de ventas contra inventario) y la reversión al anular los hace ERPNext, sin lógica paralela.
- La auditoría del 23/11/2026 confirmó 5 combos con su bebida descontada en las dos empresas.
- Si el componente no tiene existencia, la venta del combo se bloquea con "Existencia insuficiente", igual que un producto vendido solo.
- **Costo:** el ticket SAR muestra líneas a L 0.00 ("Incluido en el combo…"). **Requiere validación tributaria local.**
- **Costo:** las hamburguesas y otros platillos del combo todavía no descuentan sus ingredientes; eso llega con las recetas.
- **Costo:** cada factura con combo hace una consulta más, para leer la configuración de las opciones.

**Evidencia:** `restaurant/checkout/combos.py`, `restaurant/checkout/invoice.py`; pruebas `restaurant/tests/test_combo_stock.py` (5 casos: descuento y devolución al anular, cantidad multiplicada, el navegador no cambia el componente, rechazo sin existencia, opciones de solo indicación).
