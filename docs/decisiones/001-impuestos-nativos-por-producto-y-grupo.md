# 001 · El impuesto de cada producto sale de las plantillas nativas de ERPNext (20/11/2026)

**Estado:** Aceptada

## Contexto

En las pruebas internas de la semana 6 se encontró que:

- Un producto sin plantilla de impuesto se cobraba al **15 % por defecto, sin avisar**. Un licor (18 %) o un artículo exento mal configurado se habría facturado con la tasa incorrecta.
- El menú del POS **deducía la tasa por el nombre** de la plantilla (si el nombre contenía "18", asumía 18 %).
- Solo se leía la plantilla del producto: la que ERPNext permite definir en el **Grupo de productos** se ignoraba, y tampoco se distinguía la empresa.

En Honduras conviven tres tratamientos: ISV 15 % (comidas y productos nuevos), ISV 18 % (bebidas alcohólicas) y exento (artículos usados). El ISV y la numeración SAR ya los calcula la factura nativa de ERPNext (Grintsys).

## Decisión

La tasa de cada producto se obtiene con la búsqueda nativa de ERPNext (`get_item_tax_template`): primero las plantillas del producto, luego las de su grupo y las de los grupos padre, siempre filtradas por la empresa. Si no hay plantilla, **la orden no se guarda** y el mensaje indica qué producto configurar. La factura se calcula con las plantillas nativas *Restaurante ISV 15 %*, *Restaurante ISV 18 %* y *Restaurante EXENTO*.

## Alternativas consideradas

- **Mantener un cálculo propio en el Restaurante.** Descartada: duplica el motor fiscal de ERPNext, que la regla LEAF prohíbe, y las dos versiones terminan dando resultados distintos.
- **Conservar el 15 % por defecto.** Descartada: un error fiscal silencioso es peor que una orden rechazada con un mensaje claro.
- **Exigir la plantilla en cada producto, sin herencia del grupo.** Descartada: obliga a configurar producto por producto y los nuevos se olvidan. La herencia por grupo ya existe en ERPNext.

## Consecuencias

- Hay una sola fuente de verdad para la tasa: la misma regla en el menú, en la orden y en la factura.
- Los productos nuevos de un grupo configurado (por ejemplo, *Bebidas alcohólicas*) heredan su tasa sin trabajo extra.
- **Costo:** antes de vender, cada empresa necesita sus plantillas (`restaurant.tax_configuration.configure_company`) y cada grupo o producto su plantilla asignada. Un producto sin configurar bloquea la orden hasta que alguien lo corrija.
- Dependemos del comportamiento de `get_item_tax_template` de ERPNext v14; un cambio en una actualización mayor requeriría revisar esta decisión.
- El tratamiento de cada tipo de producto requiere validación tributaria local.

**Evidencia:** `restaurant/pos.py` (`_get_item_tax_rates`, `validate_order`), pruebas `restaurant/tests/test_item_tax_resolution.py`.
