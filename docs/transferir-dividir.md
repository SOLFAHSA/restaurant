# Transferir, fusionar y dividir cuentas

## Uso en el punto de venta

Abre `/app/restaurant-pos`, selecciona una cuenta en curso y entra en **Acciones**. El menú mantiene su distribución y diseño de LEAF.

### Transferir / Fusionar

1. Selecciona **Transferir / Fusionar** para mover toda la cuenta.
2. Busca el destino por **Mesas** o **Cuentas / Órdenes**.
3. Una mesa disponible recibe la cuenta completa. Si la mesa tiene varias cuentas, elige la cuenta específica. Elegir una cuenta existente fusiona sus platillos con los de origen.
4. Confirma **Transferir** o **Fusionar cuentas**. El POS abre la cuenta resultante y actualiza las mesas.

Una fusión completa archiva el origen como cancelado, conservando sus datos y comentarios de trazabilidad. El movimiento no emite facturas ni pagos. No se admiten cuentas facturadas o canceladas, ni cuentas de distinta empresa, moneda, perfil POS, lista de precios o turno de caja.

### Dividir o transferir platillos seleccionados

1. En **Acciones → Dividir**, o **Transferir comida**, se abre la vista de dos columnas.
2. Haz clic en un platillo para seleccionar unidades; también puedes escribir la cantidad. Se conservan sus opciones, descuentos y notas.
3. El servidor calcula el importe seleccionado, el importe restante y la propina correspondiente. La pantalla muestra la cantidad seleccionada sobre la cantidad disponible.
4. Escribe opcionalmente el nombre de la persona o de la cuenta nueva.
5. Elige una acción:
   - **Dividir orden:** crea y abre la cuenta separada; la original conserva sus platillos restantes.
   - **Pago:** con una selección parcial, crea la cuenta separada y abre el formulario de cobro existente. Con todos los platillos seleccionados, abre el cobro de la cuenta completa. La factura y el pago se registran solamente al confirmar el formulario de cobro.
   - **Transferir:** mueve sólo la selección hacia una mesa o cuenta, en una única operación atómica.

La división requiere que ambas cuentas conserven productos. Para mover todos, utiliza Transferir; para cobrar todos, utiliza Pago. No se genera una cuenta vacía.

Las cantidades se validan en el servidor contra la línea de origen y la unidad de medida nativa. Una unidad configurada para números enteros rechaza fracciones; una unidad fraccional conserva sus cantidades sin reducirlas a dos decimales.

## Cocina y trazabilidad

**ANALYZED — Arquitectura de Nivel 3:** se reutilizan `Restaurant Order`, `Restaurant Order Item`, `Restaurant Preparation Ticket`, `Restaurant Table` y el motor nativo de facturación de ERPNext. No se agregaron DocTypes ni campos para estas operaciones.

Dividir o fusionar se permite mientras cocina prepara los platillos. Antes del movimiento, el servidor captura los tickets correspondientes; después remapea sus identificadores hacia las filas destino dentro de la misma transacción. Las filas restantes mantienen sus identificadores.

Una cuenta fusionada puede tener grupos en etapas distintas. El KDS muestra una tarjeta por grupo, con la misma cuenta y un indicador **Grupo X de Y**. Cada tarjeta conserva su etapa, marcas, tiempos y retiro. Marcar, restablecer o retirar una tarjeta no afecta las otras. La pantalla pública del estado de la orden agrupa estos tickets y muestra la etapa pendiente más temprana.

Si una división deja un grupo compuesto únicamente por platillos ya marcados, ese grupo avanza automáticamente a la etapa siguiente. Los segmentos que se vacían dejan de mostrarse y permanecen como historial. Los grupos entregados o retirados no vuelven a preparación por una fusión.

## Importes, propinas y concurrencia

- El cálculo previo reutiliza el cálculo de la orden existente en servidor. La interfaz no agrega un motor fiscal.
- Al dividir una propina porcentual se conserva el porcentaje en cada parte. Una propina fija se distribuye proporcionalmente, dejando el resto exacto en la cuenta original.
- Al fusionar se suman las propinas calculadas y se conserva el resultado como propina fija del destino, para no aplicar otra vez el porcentaje sobre los platillos recibidos. Puede ajustarse después mediante el flujo de propina existente.
- Al separar cantidades pueden aparecer diferencias de centavos por el redondeo de cada cuenta. La vista muestra la diferencia calculada por el servidor; la emisión final sigue los documentos y controladores nativos existentes.
- El servidor comprueba permisos, estado documental, cantidades, compatibilidad y versiones de ambas cuentas. Los bloqueos y savepoints evitan persistir una operación incompleta.
- Si otra persona cambió la cuenta, actualiza la información antes de repetir la operación. No se sobrescribe silenciosamente la versión recibida por la interfaz.

## Aplicación en otros entornos

No se requiere una migración de esquema ni un recálculo de históricos para esta función. Actualiza la app `restaurant`, reinicia la sesión web existente y ejecuta `bench --site development clear-cache` desde el Bench y su entorno Python 3.11. Verifica el nombre del sitio antes de usar esos comandos en otro entorno. En el navegador, vuelve a cargar el POS con Ctrl + F5.

Las pruebas y los archivos de implementación se detallan en `transferir-dividir-verificacion.md`.
