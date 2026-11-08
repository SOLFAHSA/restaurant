# Pantallas de preparación y monitor de cocina

## Configuración en Frappe Desk

La ruta `/app/restaurant-kds` conserva el monitor del módulo Restaurante. Como administrador o con el rol Restaurant Manager, crea una pantalla con nombre, descripción y las etapas ordenadas del proceso. La configuración se guarda en la app independiente `restaurant`.

- **Puntos de venta:** referencias al `POS Profile` nativo; sin selección se incluyen todos los permitidos.
- **Categorías:** referencias al `Item Group` nativo; sin selección se incluyen todas. La selección es exacta: agrega los subgrupos necesarios.
- **Etapas:** crea sus nombres, colores y temporizadores en **Restaurant Preparation Stage** y selecciónalas en la pantalla. Se requieren al menos tres etapas.
- **Eliminación automática:** opcional, con minutos enteros mayores que cero. Retira del monitor los tickets completados; conserva pedidos, facturas e historial.

El flujo recomendado tiene tres etapas: **Por preparar → Para entregar → Completadas**. En las etapas de trabajo, cada clic marca o desmarca un platillo y lo muestra tachado. Al marcar todos los platillos del ticket, el servidor avanza a la siguiente etapa y comienza una lista de marcado nueva. En la última etapa se usa **Listo** para retirar el ticket; **Restablecer** permite volver al proceso.

El temporizador de alerta se expresa en minutos por etapa. Cero desactiva la alerta. La hora del servidor y el inicio persistido de la etapa permiten conservar el tiempo al recargar el navegador.

## Arquitectura y preservación

**ANALYZED — Native Path Check:** ERPNext aporta `Item`, `Item Group`, `POS Profile` y los documentos transaccionales. Las pantallas, sus etapas y el progreso de preparación son orquestación de Nivel 3 dentro de `restaurant`; no sustituyen facturas, pagos, contabilidad ni inventario.

Se reutilizan las órdenes existentes y las comandas de impresión permanecen independientes. `Restaurant Preparation Display` guarda la configuración; `Restaurant Preparation Stage` guarda etapas reutilizables; `Restaurant Preparation Ticket` guarda progreso por pantalla y orden. Los tickets sólo se modifican mediante los endpoints del monitor, con permisos y validaciones del servidor.

**ANALYZED — División y fusión durante la preparación:** el servidor conserva segmentos de preparación separados cuando los platillos que llegan a una cuenta tienen etapas o marcas distintas de los existentes. Una misma orden puede mostrar varias tarjetas, identificadas por su ticket y número de lote. Cada segmento mantiene sus etapas, marcas, temporizador y retiro; mover productos entre cuentas no vuelve a prepararlos. Al dividir una cantidad, ambas porciones conservan el avance del producto original. Si una porción contiene únicamente platillos ya marcados, avanza automáticamente a la siguiente etapa. Las filas no trasladadas conservan su identidad y los segmentos vacíos permanecen como historial, sin aparecer en el monitor. Esta extensión no requiere nuevos DocTypes ni actualización masiva de pedidos históricos; la evidencia ejecutada se registra con las pruebas de operaciones de cuentas.

Cada ticket conserva una instantánea de sus etapas y los identificadores de los platillos incluidos. Cambiar nombres, colores o alertas no debe reinterpretar el progreso histórico. No se permite reordenar o quitar etapas de una pantalla mientras existan tickets activos. Los completados que ya vencieron bajo la política automática guardada se consideran retirados para esta validación; no se modifica su historial. Las órdenes canceladas y los segmentos que ya no contienen platillos en su cuenta de origen tampoco bloquean la configuración.

El retiro automático es un filtro de visibilidad calculado con `completed_at`; no escribe `cleared_at`. Si posteriormente se desactiva o amplía ese plazo, los tickets completados que sólo estaban ocultos por tiempo pueden volver a mostrarse. El botón **Listo** sí registra el retiro manual persistente. La validación de cambios en la secuencia de etapas utiliza la política anterior a la edición, para no cambiar retroactivamente qué tickets bloquean esa edición.

La correspondencia con los estados anteriores se basa en posición: etapa inicial de preparación, etapa previa a la final para entrega y etapa final completada. Las etapas intermedias adicionales pertenecen al proceso de preparación. Las etiquetas pueden cambiar sin alterar los documentos financieros.

**PROPOSED — Migración:** sincronizar los DocTypes nuevos mediante `bench --site development migrate` utilizando Python 3.11 del bench. No requiere recalcular órdenes históricas ni transformar facturas. Antes de ejecutar en otro entorno, verificar sitio, apps instaladas y respaldo.

**PROPOSED — Configuración inicial explícita:** desde `/workspace/development/frappe-bench`, ejecutar `bench --site development execute restaurant.kds_setup.ensure_default_display`. La función está en `restaurant/kds_setup.py`; no se ejecuta automáticamente en migraciones. Si ya existe alguna pantalla, devuelve su identificador sin modificar ni duplicar configuraciones. En una instalación sin pantallas, crea **Kitchen Display** con las etapas **Por preparar** (gris, 10 minutos), **Para entregar** (azul, 5 minutos) y **Completadas** (verde, sin alerta), reutilizando etapas de igual nombre si ya existen. Los filtros iniciales vacíos incluyen todos los perfiles y categorías permitidos; el retiro automático comienza desactivado. La función no modifica pedidos, no altera datos financieros y deja la confirmación transaccional a su invocador.

## Verificación funcional

1. Crear una pantalla con tres etapas y filtros de punto de venta y categoría; recargar y comprobar persistencia.
2. Enviar una orden de dos platillos desde POS. Un pedido no enviado no debe aparecer.
3. Marcar un platillo: sólo esa línea queda tachada. Marcar el segundo: el ticket avanza y reinicia el marcado de la nueva etapa.
4. Repetir en la etapa de entrega: ambos deben marcarse antes de pasar a completadas.
5. Recargar y abrir el mismo monitor en otra sesión: etapa, marcas y temporizador deben coincidir.
6. Retirar con **Listo** y comprobar que el pedido y la factura permanecen intactos.
7. Activar retiro automático, completar un ticket y comprobar que desaparezca al vencer el plazo. Desactivarlo y comprobar que permanezca.
8. Verificar una misma orden en dos pantallas: el progreso y retiro de una no deben ocultar la otra.
9. Intentar minutos negativos o fraccionarios, colores inválidos, etapas duplicadas, registros sin permisos y clics de una etapa desactualizada: el servidor debe rechazarlos.
10. Comparar cantidad e importes de facturas, asientos y movimientos de inventario antes y después: los cambios de cocina no deben modificarlos.
11. Dividir parcialmente un platillo marcado y fusionar cuentas con etapas diferentes: comprobar cantidad total conservada, marcas y avance por segmento, identidad de los platillos restantes y ausencia de preparaciones duplicadas.

Estos pasos son criterios de aceptación **PROPOSED**; su ejecución y resultados se registran por separado, sin presentarlos como pruebas ya verificadas.
