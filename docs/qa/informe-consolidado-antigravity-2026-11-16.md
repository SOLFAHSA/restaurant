# Informe consolidado del análisis de Antigravity — Restaurante LEAF ERP v14

**Fecha:** 16 de noviembre de 2026.

**Destinatario:** Manuel Padilla / Grintsys.

**Objeto:** explicar qué realizó Antigravity, qué encontró, qué permiten concluir sus resultados y cómo abordar las correcciones.

**Alcance de esta revisión:** documentación QA y lectura del código local. No se ejecutaron nuevamente Bench, pruebas HTTP, consultas a la base de datos ni migraciones. No se aplicaron correcciones funcionales.

## 1. Conclusión ejecutiva

**ANALYZED — El material revisado justifica mantener pendiente la salida a producción.** El registro formal contiene **16 grupos de defectos: 5 P0, 8 P1, 2 P2 y 1 P3**. Los principales riesgos afectan impuestos, inventario, permisos, pagos, separación de sucursales y caja. Un grupo puede contener varios problemas y combinar evidencia de ejecución con observaciones de código.

**ANALYZED — Antigravity amplió la auditoría y documentó problemas; ese trabajo no equivale a haberlos corregido.** La nueva suite contiene 16 pruebas: cuatro casos generales y doce reproducciones marcadas como `expectedFailure`. El reporte histórico de la suite completa indica 197 pruebas, 183 aprobadas y 14 fallos esperados, sin fallos inesperados. Los 14 fallos esperados siguen representando problemas abiertos.

**PROPOSED — La siguiente etapa debe ser una remediación por bloques verificables:** exactitud fiscal y pagos; seguridad y caja; aislamiento por sucursal e integridad de actualizaciones; inventario; rendimiento e infraestructura; certificación de los flujos completos. No conviene iniciar por aumentar trabajadores del servidor mientras persisten errores de negocio.

## 2. Fuentes y significado de la evidencia

**VERIFIED — Se comprobó la existencia de los diez documentos QA citados y del archivo `restaurant/tests/test_qa_comprehensive_audit.py`.** Se leyeron esos documentos, las reglas aplicables y fragmentos de implementación relacionados con los hallazgos principales.

Para interpretar correctamente este informe:

| Estado | Significado en esta revisión |
|---|---|
| VERIFIED | Comprobación realizada durante esta sesión, por ejemplo existencia de un archivo o consulta de Git. |
| ANALYZED | Lectura de documentos o inspección estática del código. No implica reproducción actual del defecto. |
| PROPOSED | Solución o prueba recomendada, todavía sin aplicar ni ejecutar en esta revisión. |
| BLOCKED | Validación que Antigravity dejó bloqueada; su disponibilidad actual no se volvió a comprobar. |

**ANALYZED — Los tiempos, conteos SQL, resultados Bench y conteos de base de datos que aparecen abajo son resultados históricos reportados por Antigravity.** Sus documentos los etiquetan como `VERIFIED`; aquí no se presentan como ejecuciones propias. No se localizaron los scripts `qa_load_and_concurrency.py` y `qa_db_inspect.py`, ni sus salidas crudas, dentro de la app revisada. Pueden estar fuera de ella o en el contenedor; deben incorporarse a una ubicación reproducible antes de repetir la auditoría.

Fuentes principales, relativas a `docs/qa/`:

| Documento | Qué aporta |
|---|---|
| [diagnostico-inicial.md](diagnostico-inicial.md) | Entorno, versiones, arquitectura, documentos existentes e inventario técnico. |
| [plan-de-pruebas.md](plan-de-pruebas.md) | Estrategia en siete capas y controles de aislamiento de pruebas. |
| [matriz-casos-prueba.md](matriz-casos-prueba.md) | Escenarios de configuración, caja, órdenes, KDS, facturas, seguridad y carga. |
| [reporte-ejecucion.md](reporte-ejecucion.md) | Totales Bench, carga HTTP, fallos esperados e integridad reportada. |
| [defectos-detectados.md](defectos-detectados.md) | Referencia canónica para IDs, severidades, ubicaciones y propuestas. |
| [informe-rendimiento.md](informe-rendimiento.md) | Consultas SQL, latencias, bloqueos y memoria. |
| [informe-multisucursal.md](informe-multisucursal.md) | Flujo de integración y brechas de separación de sucursales. |
| [informe-regresion.md](informe-regresion.md) | Comparación de cortes del 13, 14 y 16 de noviembre. |
| [plan-optimizacion.md](plan-optimizacion.md) | Propuesta original de corrección por fases. |
| [dictamen-final-produccion.md](dictamen-final-produccion.md) | Decisión histórica de no aprobación para producción. |

## 3. Qué realizó Antigravity

**ANALYZED — Secuencia reconstruida a partir del texto entregado, los documentos y la suite:**

1. **Inspección del entorno y del módulo.** Inventarió versiones, componentes, roles, endpoints y DocTypes; revisó la integración con Frappe, ERPNext y POS Awesome. El diagnóstico informa 25 DocTypes y 63 endpoints. Este último total necesita aclararse: su desglose suma 67 al incluir cuatro operaciones expuestas vía `pos.py`, por lo que debe distinguir funciones propias, envoltorios y rutas únicas.
2. **Línea base.** Reportó comprobaciones de sintaxis y una suite inicial de 181 pruebas: 179 aprobadas y dos fallos esperados.
3. **Nueva batería integral.** Creó `test_qa_comprehensive_audit.py` para ejercitar integración, permisos, impuestos, pagos, caché PIN y perfilado SQL.
4. **Ajustes de los datos de prueba.** Corrigió parámetros de perfiles POS, usuarios, comandas, apertura de turno, división y cancelación de ítems; estableció `Employee.create_user_permission=0` en los empleados de prueba y completó las tres etapas KDS. Estos ajustes permiten ejecutar los escenarios preparados, pero no corrigen por sí mismos el comportamiento del producto.
5. **Simulación multisucursal.** Preparó tres sucursales, 30 usuarios operativos y tres supervisores adicionales; el caso recorre apertura, orden, comanda, KDS, división, traslado, precuenta, cancelación, facturación, movimiento de efectivo, arqueo parcial y generación HTML del ticket.
6. **Reproducciones de defectos.** Añadió doce casos negativos marcados como `expectedFailure`, además de los dos existentes.
7. **Perfilado SQL.** Instrumentó `frappe.db.sql` para contar llamadas y medir operaciones contra datos del sitio de desarrollo.
8. **Carga HTTP y bloqueo de filas.** Reportó solicitudes concurrentes de lectura a 10, 30, 50 y 100 usuarios, una prueba breve de resistencia, siete sondas Guest y un experimento con dos conexiones MariaDB.
9. **Regresión e integridad.** Reportó la suite completa ampliada y comparaciones de conteos de tablas antes y después.
10. **Entrega documental.** Generó diez archivos QA y emitió el dictamen histórico **NO APTO PARA PRODUCCIÓN**.

**VERIFIED — Contexto local consultado:** infraestructura en commit `ca7d961`; app `restaurant` en rama `feature/modulo-restaurante`, commit `3ef8544`, con cambios locales previos. Entre ellos hay modificaciones en `pos.py`, `setup.py`, `hooks.py`, configuración y frontend, además de archivos SAR y QA sin versionar. No es posible atribuir todos esos cambios a Antigravity solo por el estado de Git; se conservaron intactos. `AGENTS.md` ya está excluido localmente en ambos repositorios consultados.

## 4. Resultados reportados y cómo interpretarlos

### 4.1 Suite y verificaciones

**ANALYZED — Resultados históricos extraídos de `reporte-ejecucion.md`:**

| Verificación | Resultado reportado | Interpretación |
|---|---|---|
| Sintaxis JavaScript | POS y KDS sin errores de sintaxis | Confirma que el parser acepta los archivos; no valida permisos ni comportamiento visual. |
| Sintaxis Python | Archivos `.py` de la raíz del paquete sin errores | No equivale a cobertura de todos los controladores ni a integración correcta. |
| Suite completa | 197 pruebas; 183 aprobadas; 14 fallos esperados; 263.202 s | Ejecución sin fallos inesperados, con problemas conocidos pendientes. |
| Nueva suite integral | 16 pruebas; ejecución aislada reportada de 116.899 s | Cuatro casos generales y doce reproducciones esperadas; no son 16 casos funcionales aprobados. |
| Sondas Guest | Siete endpoints devolvieron HTTP 403 | No demuestra que los roles autenticados tengan los permisos correctos. |
| Bloqueo MariaDB | Espera de 350.67 ms con dos conexiones y rollback | Comprueba el mecanismo de bloqueo en ese experimento; no certifica todos los endpoints concurrentes. |
| Playwright | Siete archivos `.cjs` sin ejecutar | BLOCKED en la auditoría original. |
| Cobertura Python | Porcentaje no medido | BLOCKED en la auditoría original. |
| Staging e impresora física | Sin certificación | BLOCKED en la auditoría original. |

**ANALYZED — Por qué un resultado `OK (expected failures=14)` admite defectos abiertos:** las pruebas decoradas con `@unittest.expectedFailure` esperan fallar. El ejecutor acepta ese resultado y termina en OK. Después de corregir cada problema hay que retirar ese decorador del caso correspondiente y exigir que pase de forma normal. También debe guardarse el traceback: un fallo esperado puede producirse por una excepción distinta del defecto que se intentaba reproducir.

### 4.2 Rendimiento

**ANALYZED — Perfilado histórico, con el volumen y configuración de esa ejecución:**

| Operación | Llamadas SQL reportadas | Tiempo aproximado |
|---|---:|---:|
| `get_locations` | 2 | 1.33 ms |
| `validate_order` | 22 | 11.11 ms |
| `get_commands` | 35 | 31.11 ms |
| `get_kds_state` | 131 | 115.27 ms |
| `get_cash_count_preview` | 167 | 232.84 ms |
| `save_pos_order` | 356 | 372.40 ms |
| `get_pos_bootstrap` | 646 | 631.83 ms |
| `pay_and_invoice_order` | 1,074 | 998.08 ms |

**ANALYZED — Carga HTTP histórica contra el servidor de desarrollo bajo `debugpy`:**

| Usuarios concurrentes | Solicitudes | Errores | P95 reportado |
|---:|---:|---:|---:|
| 10 | 40 | 0% | 20.545 s |
| 30 | 90 | 0% | 29.025 s |
| 50 | 100 | 18% | 18.636 s |
| 100 | 100 | 20% | 27.720 s |
| 20, prueba breve de resistencia | 38 | 26.3% | No se informa un P95 global en la tabla principal |

**ANALYZED — Balance agregado:** 368 solicitudes, 320 exitosas y 48 errores. A 100 usuarios, el 100% de timeouts corresponde al endpoint bootstrap, no a todas las solicitudes. Los percentiles deben revisarse con los datos crudos para determinar cómo se trataron los timeouts; un P95 menor en un escenario con más errores no demuestra una mejora.

**ANALYZED — Memoria:** el reporte informa un aumento acumulado de RSS de 178.31 a 713.99 MB; aproximadamente 69.68 MB ocurrieron durante la prueba breve de resistencia. Esto es una señal de investigación, no prueba suficiente de una fuga de memoria ni de que `debugpy` sea su única causa. El ensayo duró 40.71 s incluyendo esperas; falta una prueba sostenida más larga en staging.

### 4.3 Datos existentes

**ANALYZED — Antigravity reportó conteos iguales antes y después:** 59 órdenes, 199 líneas, 12 facturas, 57 GL Entry, cero Stock Ledger Entry, ocho aperturas y dos arqueos; además, cero huérfanos y cero comprobantes contables desbalanceados en las verificaciones realizadas.

**ANALYZED — Límite:** conteos iguales no prueban que todos los valores de las filas sean idénticos, ni ausencia de efectos en Redis, archivos, impresoras o servicios externos. Un savepoint revierte operaciones SQL dentro de su transacción, pero no garantiza revertir esos efectos. El propio análisis identifica escrituras en endpoints considerados de lectura, por lo que la afirmación de carga totalmente inocua requiere validación adicional.

## 5. Hallazgos y solución propuesta para los 16 grupos

**ANALYZED — Las severidades siguientes son las del registro formal. PROPOSED — Todas las soluciones y criterios de cierre están pendientes de implementación y ejecución.** Las rutas son relativas a `development/frappe-bench/apps/restaurant/`, salvo donde se indica infraestructura. No se propone editar directamente Frappe o ERPNext.

### DEF-2026-001 · P0 · Impuestos mixtos incorrectos

**Hallazgo:** el registro describe aplicación de 15% y 18% a las mismas bases cuando una orden mezcla tasas. Se inspeccionó `restaurant/pos.py:2515`, donde cada línea solo declara su cuenta fiscal, y las filas de impuestos globales en `:2542`. El caso `test_def_qa_12` intenta reproducirlo.

**Impacto:** total de factura distinto al de la orden; cobro excesivo o rechazo de un pago correcto. En el ejemplo del reporte, L 120 al 15% y L 60 al 18% suman L 208.80 antes de propina; con L 18 de propina, L 226.80. La factura reportada asciende a L 257.40. Es aritmética del escenario de prueba, no una certificación tributaria.

**Solución:** reutilizar `Item Tax Template` y el cálculo nativo de `Sales Invoice`; revisar la representación de todas las cuentas aplicables por línea, incluyendo ceros donde corresponda. Resolver también la configuración donde ambas tasas utilizan una misma cuenta: añadir ceros sin resolver esa representación no basta. **Nivel 1/3; requiere validación tributaria local.**

**Cierre:** comparar orden, factura y ticket en casos 15%, 18%, exento, mixtos, descuentos, propina y cancelación; verificar cada base e impuesto, además del total.

### DEF-2026-002 · P0 · Valores sobrescritos por POS Profile

**Hallazgo:** `pay_and_invoice_order` prepara `update_stock` y categoría fiscal antes de `si.set_missing_values()`. Se inspeccionó que el controller local de ERPNext asigna valores desde POS Profile en `sales_invoice.py:940` y `:989`.

**Impacto:** pérdida de la categoría exonerada o movimiento de inventario contrario a la intención de la app.

**Solución:** definir qué configuración es la fuente de verdad y construir la factura respetando el ciclo nativo. Si se preservan valores tras `set_missing_values()`, comprobar que `insert`, `validate` y `submit` también los conservan. No forzar `update_stock=0` como solución permanente al flujo de inventario. Tratar exoneración mediante las reglas nativas/Grintsys pertinentes; no limpiar impuestos indiscriminadamente. **Nivel 1/3; requiere validación tributaria local.**

**Cierre:** probar POS Profile con stock activo/inactivo y clientes contribuyentes/exonerados; comprobar la factura persistida y enviada, no solo el objeto previo al guardado.

### DEF-2026-003 · P0 · Recetas sin consumo de inventario integrado

**Hallazgo:** se inspeccionó que la configuración administrada fuerza `Product Bundle.disabled=1`. El diagnóstico histórico informa BOM=0 y Stock Ledger Entry=0. Cero movimientos por sí solo no demuestra el defecto, pero es coherente con el flujo desconectado descrito.

**Impacto:** ventas sin trazabilidad de consumo de ingredientes o existencia terminada por almacén.

**Solución:** elegir el proceso operativo antes de programar: producción previa con BOM y movimientos estándar, o consumo de componentes mediante Product Bundle cuando su comportamiento nativo se ajuste al negocio. Definir cómo afectan opciones, sustituciones, merma y anulaciones; no habilitar todos los bundles sin esa decisión. **Nivel 1/3.**

**Cierre:** una venta debe generar los movimientos esperados en el almacén correcto; anulación/devolución debe revertirlos por documentos nativos, sin insertar GL Entry ni Stock Ledger Entry manualmente.

### DEF-2026-004 · P0 · Permisos insuficientes sobre clientes

**Hallazgo:** `save_customer_with_rtn` usa `ignore_permissions=True` en creación y actualización. La prueba negativa nueva verifica creación por mesero; la afirmación adicional sobre sobrescritura requiere su caso específico y evidencia.

**Impacto:** modificación no autorizada de datos maestros y riesgo de cambiar el RTN de un cliente genérico compartido.

**Solución:** validar rol y permiso de creación/escritura sobre `Customer` en servidor, restringir campos y evitar cambios globales del cliente genérico al emitir un comprobante. Conservar en la factura los datos transaccionales que permita el esquema nativo/Grintsys. **Nivel 1/3.**

**Cierre:** mesero rechazado por API directa; cajero autorizado dentro de sus permisos; cliente genérico intacto después de facturar.

### DEF-2026-005 · P0 · Gift Cards, descuentos y estado de facturación

**Hallazgo:** el código valida el pago contra el total completo y luego reduce el saldo de Gift Card. También asigna `Facturada` a la orden aunque `auto_validate_orders=0` deje la factura en borrador. El grupo incluye observaciones adicionales de interfaz sobre descuentos y exoneración, con evidencia distinta.

**Impacto:** pago complementario rechazado, posible saldo de tarjeta sin representación contable adecuada y orden cerrada contra una factura no enviada.

**Solución:** definir el tratamiento de Gift Card/anticipo y representarlo mediante documentos y cuentas nativas; conciliar efectivo más redención con la deuda liquidada. Separar factura borrador de factura enviada y ajustar la transición de la orden. Mostrar en UI los importes devueltos por el servidor. Mantener deshabilitada la función no integrada hasta completar ese flujo. **Nivel 1/3; tratamiento fiscal requiere validación tributaria local.**

**Cierre:** venta de L 115 con redención de L 50 requiere L 65 complementarios en el escenario preparado; comprobar saldo, cuentas, estado, reintento y reversión, además de descuentos/cupones por separado.

### DEF-2026-006 · P1 · Cajero directo sin acceso a la página POS

**Hallazgo:** `restaurant/restaurant/page/restaurant_pos/restaurant_pos.json` no incluye los roles de cajero identificados por la prueba; sus roles actuales son System Manager, Restaurant Manager y Restaurant User.

**Solución:** alinear los roles de la página con los perfiles realmente autorizados. No añadir roles indiscriminadamente ni confundir acceso a la página con permiso para cada operación. **Nivel 2/3.**

**Cierre:** iniciar sesión como cajero directo y completar sus acciones permitidas; comprobar denegación de operaciones administrativas.

### DEF-2026-007 · P1 · Permisos KDS contradictorios

**Hallazgo:** la página admite Restaurant User, mientras el registro informa falta de lectura sobre Stage/Display. Otros roles con lectura no figuran en la página.

**Solución:** definir qué puede consultar o modificar cocina, mesero y cajero; alinear página, DocTypes y endpoints en `restaurant/setup.py` y `restaurant_kds.json`. **Nivel 2/3.**

**Cierre:** matriz de roles en navegador y API; mesero con acceso de lectura, si así se decide, sin capacidad indebida para avanzar etapas.

### DEF-2026-008 · P1 · Separación de sucursales incompleta

**Hallazgo:** el registro reporta lectura y traslado cruzado de órdenes. Los JSON revisados de Order, Cash Count y Preparation Display no declaran `branch`; Order sí enlaza área y perfil POS. La ausencia de un campo directo no prueba por sí sola una fuga, pero los filtros y validaciones deben garantizar una relación inequívoca.

**Solución:** realizar Native Path Check para aprovechar Company, Branch, área, perfil y almacén existentes. Definir una sucursal autoritativa por operación y validarla en todas las APIs, sin confiar en el filtro del navegador. Solo añadir campos donde sean necesarios; cualquier extensión de POS Profile debe hacerse declarativamente desde la app, sin editar ERPNext. Revisar órdenes sin mesa, KDS, comandas TCP, turnos, supervisores y selección fiscal. **Nivel 1/2/3.**

**Datos históricos:** auditar asociaciones existentes y preparar un parche idempotente. Los documentos ambiguos no deben asignarse a una sucursal por defecto arbitraria; activar integridad de datos y especialista de migración antes de implementar cambios sobre históricos.

**Cierre:** usuarios A/B/C no pueden leer, modificar, imprimir, cobrar ni arquear documentos ajenos mediante IDs manipulados; probar también traslados, cambios de área y operaciones sin mesa.

### DEF-2026-009 · P1 · Arqueo y cierre sin controles suficientes

**Hallazgo:** el registro informa consultas de turnos ajenos, exposición de esperados en modo ciego, envío de facturas durante vistas previas GET, cierre bloqueado al gerente y confianza en denominaciones recibidas del cliente.

**Solución:** validar permiso, dueño y sucursal en servidor; definir la excepción del gerente autorizado. Omitir los esperados de la respuesta en modo ciego, resolver denominaciones y valores desde el maestro y separar lectura de envío contable. Usar configuración del método de efectivo en lugar de su nombre literal. **Nivel 1/3.**

**Cierre:** una vista previa no cambia documentos; cajero B recibe rechazo sobre turno A; el payload ciego no contiene esperados; valores de denominación manipulados son rechazados; cierre autorizado crea los documentos correctos.

### DEF-2026-010 · P1 · Información SAR de respaldo no confiable

**Hallazgo:** el registro identifica selección de datos fiscales globales y constantes de demostración como respaldo cuando falta configuración válida. Este grupo figura como análisis de código, no reproducción fiscal productiva.

**Solución:** resolver CAI, establecimiento y serie mediante configuración nativa/Grintsys válida; impedir emisión fiscal cuando falten datos en lugar de sustituirlos con valores de ejemplo. Validar vigencia, rango y correspondencia de empresa/establecimiento. **Nivel 1/3; requiere validación tributaria local.**

**Cierre:** casos de CAI ausente, vencido, agotado o de establecimiento distinto no generan una factura fiscal inválida; escenario válido usa la serie y autorización correctas.

### DEF-2026-011 · P1 · PIN, caché, auditoría y endpoint sin guardia

**Hallazgo:** se inspeccionaron lecturas TTL sin `expires=True` y el respaldo a `check_password` en `pos_auth.py:348`. El registro agrega acceso de usuarios no POS a configuración, registro de PIN fallido como autorizado y reimpresión sin el token previsto.

**Solución:** exigir guardias y alcance de sucursal; utilizar PIN dedicado; registrar rechazo explícito; validar token de reimpresión ligado a acción, orden, usuario y vencimiento. Corregir la caché TTL y hacer atómico el contador Redis para evitar incrementos perdidos entre peticiones concurrentes. **Nivel 3.**

**Límite de evidencia:** el caso nuevo de caché repite intentos en una misma sesión local de prueba; no demuestra por sí solo un bypass entre peticiones HTTP o entre trabajadores.

**Cierre:** probar bloqueo en la misma petición, en peticiones independientes y en varios trabajadores; rechazo auditado como rechazo; token vencido, reutilizado o de otra orden no autoriza.

### DEF-2026-012 · P1 · Demasiadas consultas y escrituras durante lecturas

**Hallazgo:** se inspeccionó que bootstrap serializa órdenes individualmente y puede renombrarlas. `get_restaurant_pos_config` llama a `sync_restaurant_dashboard_block`, que escribe y limpia caché. El perfilado histórico informa 646 SQL en bootstrap y 1,074 al facturar.

**Solución:** mover sincronización y saneamiento de datos fuera de lecturas, al ciclo adecuado de instalación/configuración o a un parche. Agrupar consultas, paginar y evitar resolver repetidamente catálogos. Optimizar la app sin omitir validaciones fiscales, contables ni permisos del motor nativo. **Nivel 3.**

**Cierre:** comprobar ausencia de DML y envíos en GET; guardar perfil antes/después y ejecutar carga equivalente en staging. La prueba actual de perfilado solo exige conteos mayores que cero: no impone un presupuesto de rendimiento.

### DEF-2026-013 · P1 · Concurrencia y despliegue incompletos

**Hallazgo:** se inspeccionó que `expected_modified` es opcional al guardar una orden. El registro agrega falta de coordinación en apertura de turno y envío de comanda, ausencia de restaurant en scripts de producción y una credencial embebida en infraestructura.

**Solución:** exigir versión al actualizar, volver a comprobarla bajo el bloqueo apropiado y coordinar también la mesa o el turno para impedir carreras de creación. Incorporar idempotencia para reintentos de negocio. Para impresión física, diseñar estado de despacho y recuperación: un fallo de red puede dejar incierto si ya se imprimió. Incluir la app en instalación/actualización y retirar la credencial embebida sin reproducirla en reportes. **Nivel 3 en la app; revisión de plataforma para infraestructura.**

**Cierre:** dos conexiones/peticiones reales sobre la misma orden, mesa y turno; reintento tras pérdida de respuesta; despliegue reproducible en un entorno limpio con la app instalada. No asumir que el experimento genérico FOR UPDATE ya verifica estos escenarios.

### DEF-2026-014 · P2 · Interfaz, sincronización e impresión

**Hallazgo:** observaciones de código sobre Split, propina de la orden seleccionada, pagos mixtos, errores de red silenciados, doble impresión, activo faltante, KDS y adaptación a tablet. No se ejecutó Playwright en la auditoría original.

**Solución:** usar la vista previa del servidor para división y pagos, conservar el contexto de la orden seleccionada, mostrar errores recuperables y bloquear acciones mientras estén pendientes. Restaurar activos, conectar KDS a eventos con resincronización y verificar tamaños de pantalla. **Nivel 3.**

**Cierre:** siete suites de navegador y casos específicos de doble clic, desconexión, reconexión, selección de otra orden y presentación en tablet; impresión física aparte.

### DEF-2026-015 · P2 · Índices, configuración de recursos y CI

**Hallazgo:** el diagnóstico reporta cero declaraciones `search_index: 1`, pero también reconoce índices PRIMARY y modified. Por tanto, “ausencia total de índices” es una formulación incorrecta. Faltan índices de negocio evaluados para las consultas observadas. Los recursos MariaDB y el despliegue requieren medición en un entorno representativo.

**Solución:** usar consultas reales y EXPLAIN para diseñar índices simples/compuestos; verificar los existentes antes de añadirlos. Dimensionar memoria de MariaDB, conexiones y trabajadores según recursos asignados y medición, sin aplicar automáticamente 33 trabajadores ni un porcentaje fijo de la RAM del host. Incorporar pruebas de restaurant en CI. **Nivel 2/3 para esquema de la app; revisión de plataforma para recursos y CI.**

**Cierre:** planes de ejecución y carga antes/después; ausencia de agotamiento de memoria o conexiones; pipeline reproducible con pruebas backend y navegador. Metas como bootstrap <30 consultas o <120 ms son objetivos propuestos, no mejoras obtenidas.

### DEF-2026-016 · P3 · Restricciones Employee e idioma

**Hallazgo:** la suite prepara empleados con `create_user_permission=0` para evitar la restricción descrita sobre órdenes de otros meseros. El registro también lista textos visibles en inglés e inconsistencias de redacción.

**Solución:** documentar el modelo de User Permission por rol y evaluar las restricciones necesarias; no desactivar globalmente una protección para resolver el acceso de los cajeros. Traducir los textos visibles manteniendo código y comentarios técnicos en inglés. **Nivel 1/2/3.**

**Cierre:** cajero autorizado puede operar las cuentas de su ámbito sin ver otras sucursales; restricciones de empleados siguen protegiendo los demás flujos; UI en español neutro.

## 6. Precisiones necesarias sobre el análisis original

**ANALYZED — Estas precisiones mejoran el informe sin descartar sus alertas principales:**

| Afirmación del material original | Interpretación sustentada por la revisión |
|---|---|
| “Simulación simultánea/paralela de 30 usuarios” | El caso usa `frappe.set_user` y un bucle secuencial por sucursal dentro de una sola sesión de BD (`test_qa_comprehensive_audit.py:284`). Prepara 30 usuarios y tres supervisores, pero no ejecuta 30 sesiones concurrentes. |
| “Flujo completo certificado” | El flujo principal usa productos al 15%, perfil con `update_stock=0`, socket simulado y arqueo parcial como Administrator. No certifica impuestos mixtos, inventario, hardware ni cierre completo por cajero. |
| “Cierre de caja probado en la simulación” | El código crea `Arqueo Parcial`; no llama al cierre completo en ese tramo. Se necesita un caso de cierre efectivo por cada rol autorizado. |
| “Facturas mixtas” | En el flujo principal se refiere a medios de pago. No significa mezcla de tasas fiscales; esa mezcla falla en otro caso. |
| “Sin índices” | Existen PRIMARY y modified según el diagnóstico; falta evaluar índices adicionales para consultas de negocio. |
| “+536 MB en el soak” | Es el aumento acumulado del benchmark; durante el ensayo breve se reportan +69.68 MB. No demuestra una fuga por sí solo. |
| “Lecturas sin efectos / cero contaminación” | Los conteos reportados son iguales, pero los propios documentos identifican escrituras en GET. Falta comparar valores y efectos externos. |
| “Bloqueo probado, doble facturación certificada” | El bloqueo genérico con dos conexiones no sustituye una carrera real de dos solicitudes de facturación y revisión de sus documentos finales. |
| “Todos los P0/P1 reproducidos” | El registro mezcla ejecución y lectura estática; por ejemplo DEF-2026-010 se clasifica ANALYZED. Cada subhallazgo necesita evidencia propia. |
| IDs del resumen pegado | DEF-2026-006 es acceso del cajero directo; DEF-2026-008 es multisucursal; DEF-2026-011 reúne PIN y guardias. La auditoría falsa de PIN es un subhallazgo de 011 y la prueba DEF-QA-08. No intercambiar numeración de pruebas con IDs de defectos. |
| Tiempo de simulación | Los documentos citan 65.5 s y 67.9 s. Pueden ser ejecuciones diferentes; asociar cada cifra a su log antes de compararlas. |

**ANALYZED — Comprobación contable insuficiente por sí sola:** un saldo débito menos crédito igual a cero no prueba que las cuentas, impuestos o importes sean correctos. Además, la consulta del caso principal convierte una suma sin filas a cero; conviene exigir existencia de GL Entry cuando el documento enviado deba generarlas, y revisar cuentas e importes esperados.

**PROPOSED — Fortalecer las reproducciones:** separar casos que intentan verificar varios síntomas a la vez, comprobar el tipo y motivo exacto del fallo y añadir pruebas concretas para afirmaciones no cubiertas por el caso citado. Por ejemplo, crear un cliente como mesero y sobrescribir uno existente son escenarios distintos.

## 7. Camino nativo y fuentes de verdad

**ANALYZED — Native Path Check:** ERPNext ya aporta documentos y procesos para facturar, calcular impuestos, contabilizar y mover inventario. La app debe incorporar la operación del restaurante a esos caminos. No se justifica construir libros contables, motores fiscales o movimientos de stock paralelos.

**PROPOSED — Mapeo previo a cada implementación:**

| Necesidad | Fuente de verdad / camino a reutilizar | Nivel preferido |
|---|---|---|
| Productos y precios | Item, Item Price, listas y configuración existente | 1/2 |
| Tasas y totales de factura | Plantillas/configuración fiscal nativa y controller de Sales Invoice | 1; orquestación 3 |
| Venta y estado contable | Sales Invoice enlazada, `docstatus`, envío y cancelación | 1/3 |
| Pagos y redenciones | Documentos y cuentas nativos según diseño contable validado | 1/3 |
| Ingredientes y existencias | BOM, Product Bundle y documentos estándar de inventario según proceso elegido | 1/3 |
| Turnos y cierre | POS Opening Shift / POS Closing Shift existentes y su integración comprobada | 1/3 |
| Sucursal | Relaciones Company/Branch/perfil/área/almacén; extensión solo donde falte | 1/2/3 |
| Autorización | Roles, permisos y validación de servidor sobre cada recurso | 1/2/3 |
| Mesa, orden y cocina | DocTypes de restaurant enlazados al motor nativo | 3 |

**PROPOSED — Antes de introducir campos:** responder las diez preguntas del Native Path Check, consultar la metadata instalada y documentar por qué los vínculos existentes no bastan. Para datos históricos, definir respaldo, mapeo, excepciones y parche idempotente antes de migrar. Las facturas enviadas no se recalculan retroactivamente como efecto de una corrección de código.

## 8. Plan de solución y verificación

**PROPOSED — Orden recomendado; cada bloque termina con evidencia y revisión antes de avanzar a producción:**

| Bloque | Trabajo | Dónde / herramienta | Condición para darlo por cerrado |
|---|---|---|---|
| 0. Reproducibilidad | Guardar commit + diff, scripts, logs, datos mínimos y resultados estructurados; conservar cambios locales | Terminal/editor, repositorios de app e infraestructura | Otro desarrollador puede repetir cada caso en desarrollo aislado. |
| 1. Fiscal y pagos | 001, 002, 005 y 010; decisión de integración de stock de 003 | Frappe Desk para configuración; editor en la app | Totales correctos, CAI válido, estado y pagos conciliados; aprobación tributaria local donde corresponda. |
| 2. Seguridad y caja | 004, 006, 007, 009 y 011; modelo de permisos de 016 | Desk para roles; editor para controles de servidor | API y navegador respetan rol, recurso, turno y sucursal; PIN y modo ciego funcionan. |
| 3. Sucursal y concurrencia | 008 y 013; estrategia de datos históricos | App, pruebas con conexiones independientes y revisión de migración | No hay lectura/escritura cruzada, actualizaciones perdidas ni duplicados en reintentos. |
| 4. Inventario completo | 003 y política definitiva de 002 | Configuración nativa y orquestación en la app | Venta, consumo y reversión generan los movimientos correctos por almacén. |
| 5. Rendimiento y entrega | 012 y 015; despliegue de 013 | App, MariaDB y repositorio de infraestructura | GET sin mutación; carga dentro de objetivos en staging; instalación y actualización reproducibles. |
| 6. Experiencia y certificación | 014, textos de 016 y regresión de todos los bloques | Navegador, Playwright, impresora y staging | Flujos completos por rol, hardware y resistencia sostenida con evidencias archivadas. |

**PROPOSED — Archivos candidatos a revisión, no lista de cambios autorizados:**

| Área | Rutas existentes relativas a la app |
|---|---|
| Facturación, órdenes y acceso POS | `restaurant/pos.py`, `restaurant/pos_auth.py` |
| Caja y movimientos | `restaurant/cash_count.py` |
| Separación de sucursal y operaciones | `restaurant/order_operations.py`, `restaurant/location.py`, `restaurant/table_management.py`, `restaurant/commands.py` |
| Cocina | `restaurant/kds.py`, `restaurant/order_kds.py`, `restaurant/kds_setup.py` |
| Recetas | `restaurant/item_configuration.py` |
| Roles y extensión | `restaurant/setup.py`, `restaurant/hooks.py` |
| Acceso a páginas | `restaurant/restaurant/page/restaurant_pos/restaurant_pos.json`, `restaurant/restaurant/page/restaurant_kds/restaurant_kds.json` |
| Frontend | `restaurant/restaurant/page/restaurant_pos/restaurant_pos.js`, `restaurant/restaurant/page/restaurant_pos/restaurant_pos.css`, `restaurant/restaurant/page/restaurant_kds/restaurant_kds.js`, `restaurant/restaurant/page/restaurant_kds/restaurant_kds.css`, `restaurant/restaurant/page/restaurant_table_map/restaurant_table_map.js` |
| Esquema, solo tras decidir el diseño | `restaurant/restaurant/doctype/restaurant_order/restaurant_order.json`, `restaurant/restaurant/doctype/restaurant_cash_count/restaurant_cash_count.json`, `restaurant/restaurant/doctype/restaurant_preparation_display/restaurant_preparation_display.json` |
| Regresión | `restaurant/tests/test_qa_comprehensive_audit.py`, `restaurant/tests/test_multibranch_concurrency.py`, suites existentes de órdenes/KDS/permisos/caja/SAR y `restaurant/tests/ui/*.cjs` |

**PROPOSED — Infraestructura:** revisar `scripts/deploy_production_native.sh`, `scripts/update_production.sh`, `compose.yaml` y la configuración efectiva de staging en el repositorio raíz. La ruta exacta de cualquier parche nuevo, fixture, índice o workflow se debe definir después de elegir la solución. No se propone cambiar controllers del core para estos defectos.

**PROPOSED — Ejecución segura de la verificación posterior:** en la terminal de VS Code dentro del DevContainer, desde `/workspace/development/frappe-bench`, verificar primero `env/bin/python --version` (3.11.x), `bench --site development list-apps`, sitio destino y puerto activo. La auditoría histórica usó 8000; no asumir que sigue siendo el puerto actual. Con un entorno de pruebas preparado y respaldo verificado, ejecutar las suites relevantes y luego:

```bash
bench --site development run-tests --app restaurant --skip-test-records
```

**PROPOSED — Evidencia a conservar:** comando, versión/diff, fecha, sitio, salida completa, motivo de cualquier fallo, casos pendientes y documentos generados. Las pruebas que escriben deben ejecutarse con el aislamiento definido; un comando Bench sobre un sitio poblado no garantiza inocuidad por sí solo. Ningún comando de este apartado se ejecutó durante esta revisión.

## 9. Criterios de aprobación de producción

**PROPOSED — Condiciones mínimas de salida:**

1. Cerrar los P0/P1 aplicables al alcance liberado con pruebas normales aprobadas y trazabilidad al defecto; no conservar `expectedFailure` sobre errores declarados resueltos.
2. Verificar impuestos y pagos desde la orden hasta la factura enviada, ticket, cuentas y cancelación. Validar fiscalmente CAI/exoneración según el caso.
3. Demostrar permisos y separación de sucursales con pruebas negativas por API y navegador, incluidos turnos, arqueos, comandas y supervisores.
4. Demostrar que no se pierden actualizaciones ni se duplican operaciones ante concurrencia y reintentos; comprobar resultados finales de negocio.
5. Certificar inventario con el proceso operativo acordado y sus reversas.
6. Ejecutar Playwright, impresión física y un cierre completo por rol autorizado.
7. Medir carga en staging representativo, sin depurador, con volumen de datos y mezcla de lecturas/escrituras acordados. Usar como referencia inicial el P95 <2 s y errores <1% del plan original; ajustarlos explícitamente por operación. No extrapolar capacidad de producción a partir del servidor de desarrollo.
8. Revisar datos históricos y efectos externos, además de conteos; conservar evidencias y procedimiento de recuperación.

## 10. Cierre del orquestador

**CAMBIOS REALIZADOS — VERIFIED:** creado este informe consolidado, con inventario de actividades, resultados históricos, 16 grupos de hallazgos, limitaciones y propuestas de cierre. La skill [leaf-qa-guardian](../../../../../../.agents/skills/leaf-qa-guardian/SKILL.md) se utilizó para la revisión documental QA.

**ARCHIVOS MODIFICADOS — VERIFIED:** únicamente `development/frappe-bench/apps/restaurant/docs/qa/informe-consolidado-antigravity-2026-11-16.md` por esta tarea. Se preservaron los documentos originales y cambios locales previos.

**DATOS AFECTADOS — VERIFIED:** no se ejecutaron operaciones de base de datos, migraciones ni correcciones funcionales en esta sesión.

**PRUEBAS EJECUTADAS Y EVIDENCIA:** VERIFIED: lectura de archivos y consulta de estado, rama y último commit de Git. ANALYZED: inspección de la suite, informes e implementación relacionada. No se reejecutó la batería histórica; sus resultados siguen atribuidos a Antigravity.

**RIESGOS PENDIENTES — ANALYZED:** defectos abiertos, evidencia de ejecución sin repetir, scripts y logs originales por localizar, validaciones de navegador/hardware/staging pendientes y decisiones de negocio sobre inventario, permisos y Gift Cards.

**DICTAMEN FINAL — ANALYZED: RECHAZADO PARA PRODUCCIÓN con la evidencia revisada.** Este dictamen conserva la decisión preventiva de la auditoría original; no constituye una nueva certificación ejecutada. Las soluciones descritas son PROPOSED y requieren su implementación y verificación correspondiente.
