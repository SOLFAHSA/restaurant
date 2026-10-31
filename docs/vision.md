# Visión del proyecto Restaurant

- Participante: Manuel Padilla, Ingeniería en Sistemas, CEUTEC.
- Contexto: Custom App independiente para LEAF ERP v14 / Grintsys.
- Fecha de corte: 30 de octubre de 2026.
- Estado: **borrador académico para revisión**. Publicación pendiente de
  autorización de Grintsys; no hay validación de mercado declarada.

## 1. Visión y problema

**Origen del proyecto — requerimiento empresarial relatado por Manuel:** durante
su práctica profesional, Grintsys le solicitó apoyar la creación de un módulo
Restaurante para ampliar la cobertura de su producto LEAF ERP hacia ese rubro.
La fuente de esta información es la explicación de Manuel en la sesión de
levantamiento de contexto; no se presenta como una entrevista directa con
Grintsys ni como una validación independiente de su estrategia comercial.

**Necesidades planteadas por Manuel:** facilitar la separación de cuentas y la
reserva de mesas para los clientes; ofrecer al propietario y al administrador
mejor visibilidad de los movimientos de inventario y del funcionamiento del
negocio; y coordinar el proceso entre meseros, cocina y caja.

**Problema a validar:** los restaurantes destinatarios podrían tener dificultades
para coordinar esos procesos y mantener la trazabilidad de los consumos y sus
movimientos de inventario. La frecuencia de los inconvenientes, sus causas y
su impacto todavía requieren observación de operaciones reales o entrevistas.
El relato no identifica un establecimiento concreto ni aporta mediciones;
por ello no se afirma que todos los restaurantes tengan ese problema.

**PROPOSED — visión del producto:** ampliar LEAF ERP con una experiencia de
restaurante que conecte la atención de mesas, las cuentas de servicio y la
coordinación entre meseros, cocina y caja con los procesos nativos de facturación,
cobros e inventario de ERPNext. La separación de cuentas y las reservas se
analizarán como necesidades del flujo, antes de decidir su implementación.

**Personas involucradas:** Grintsys como solicitante del módulo; propietarios y
administradores como responsables del control; meseros, cocina y cajeros como
usuarios operativos; y comensales como beneficiarios de la atención. No se ha
definido que los comensales vayan a utilizar directamente la aplicación.

La primera versión implementada organiza el espacio de trabajo y el acceso a
catálogos. Esta visión describe un objetivo futuro más amplio y no implica que
ya se hayan desarrollado las cuentas, reservas, comandas o el control integral
del servicio.

## 2. Evidencia disponible y límites

| Clasificación | Evidencia | Qué permite concluir |
| :--- | :--- | :--- |
| ANALYZED | Relato de Manuel sobre la solicitud de Grintsys y las necesidades del restaurante, recogido en la [bitácora](bitacora/semana-1.md#levantamiento-del-contexto-del-proyecto). | Sustenta el origen y la motivación del proyecto; no demuestra frecuencia de problemas ni validación con usuarios finales. |
| VERIFIED | Cinco commits locales hasta `0607fa5`, enumerados en la [bitácora](bitacora/semana-1.md). | Hay una evolución versionada de la app; no demuestra publicación ni adopción. |
| ANALYZED | [Workspace Restaurante](../restaurant/restaurant/workspace/restaurante/restaurante.json). | Existe una portada con referencia al bloque y accesos nativos conservados. |
| ANALYZED | [Bloque de interfaz](../restaurant/fixtures/custom_html_block.json). | Hay quince tarjetas en cuatro secciones; algunas anuncian funciones pendientes. |
| ANALYZED | [Fixtures de campos](../restaurant/fixtures/custom_field.json) y [cargo Mesero](../restaurant/fixtures/designation.json). | La app extiende y reutiliza catálogos existentes, sin crear fichas duplicadas. |
| PROPOSED | Observaciones de servicio y entrevistas con usuarios. | Falta evidencia de campo para confirmar el problema y priorizar el producto. |

Las referencias visuales aportadas durante el diseño orientaron la interfaz;
no constituyen entrevistas, métricas de ventas ni resultados de usabilidad.
El relato de Manuel se atribuye expresamente a su fuente. No se han incorporado
entrevistas con usuarios finales, porcentajes de mejora o cifras de negocio
que no estén sustentados. Una demostración local tampoco prueba que exista un
despliegue público por HTTPS.

## 3. Lean Canvas inicial

Todos los bloques siguientes son **PROPOSED** y requieren validación con
usuarios y con Grintsys. No representan compromisos comerciales aprobados.

| Bloque | Hipótesis inicial |
| :--- | :--- |
| Problema | Dificultades planteadas para separar cuentas y reservar mesas, necesidad de visibilidad del inventario y de coordinación entre meseros, cocina y caja. Frecuencia e impacto pendientes de validar. |
| Segmentos | Restaurantes como rubro que Grintsys desea atender con LEAF ERP, según Manuel; propietarios y administradores, cajeros, meseros y cocina. Comensales como beneficiarios. |
| Propuesta de valor | Atención y control administrativo del restaurante integrados con LEAF, con trazabilidad hacia el motor transaccional nativo de ERPNext. |
| Solución | Portada y catálogos reutilizados como primera etapa; evaluar después mesas, reservas, separación de cuentas y comandas conectadas con facturación e inventario nativos. |
| Canales | Demostraciones y sesiones de validación coordinadas con Grintsys; acceso a usuarios aún por confirmar. |
| Fuentes de ingresos | Por definir con Grintsys; evaluar si encaja en su oferta de implementación, soporte o servicio. No hay precios acordados. |
| Estructura de costos | Desarrollo, pruebas, alojamiento de una instancia Frappe, mantenimiento y capacitación. Importes pendientes. |
| Métricas clave | Éxito y tiempo por tarea; posteriormente, errores al separar consumos, conflictos de reservas, errores de coordinación y diferencias entre movimientos esperados y registrados de inventario. Sin línea base medida. |
| Ventaja diferencial | Posible integración con la arquitectura y los procesos de LEAF; no se ha demostrado una ventaja comercial exclusiva. |

## 4. Hipótesis y plan de validación

Los criterios siguientes son metas propuestas para un experimento futuro, no
resultados obtenidos ni requisitos confirmados del curso.

| Hipótesis | Experimento propuesto | Criterio inicial de decisión |
| :--- | :--- | :--- |
| H1: existen dificultades de coordinación del servicio, separación de cuentas, reservas o visibilidad del inventario que justifican el módulo. | Observar tareas y entrevistar al menos a tres usuarios de funciones distintas; documentar ejemplos concretos, el procedimiento actual y su efecto sin datos personales innecesarios. | Identificar al menos un problema recurrente respaldado por dos participantes; si no aparece, revisar la hipótesis y la prioridad de desarrollo. |
| H2: la portada facilita encontrar catálogos. | Pedir a cinco usuarios que encuentren productos, categorías, precios, meseros y ubicaciones; registrar éxito, tiempo y ayuda requerida. | Al menos cuatro de cinco completan las tareas sin ayuda. Comparar tiempos solo si se mide una línea base equivalente. |
| H3: los catálogos nativos representan los datos necesarios. | Revisar ejemplos reales con el responsable funcional y mapear cada dato a los DocTypes existentes. | No crear otro catálogo cuando exista equivalencia nativa; documentar las brechas antes de desarrollar. |

Antes de medir mejoras se deben acordar las tareas, el contexto y la línea base.
El desempeño durante un servicio, la facturación y el uso táctil completo
requieren pruebas adicionales cuando esos flujos estén implementados.

## 5. Alcance real de la semana 1

**ANALYZED en los archivos de la app:**

- App y paquete `restaurant`, separados de `frappe` y `erpnext`.
- Portada `/app/restaurante` mediante Workspace y Custom HTML Block nativos.
- Bienvenida web `/restaurant-welcome`, mediante plantilla Jinja.
- Accesos a productos, categorías, precios, personal y áreas; reportes y
  configuración mediante navegación a funciones existentes.
- Uso de `Employee` con `Designation = Mesero`, `Branch` y `Location` con dos
  campos declarativos para identificar áreas y relacionar sucursales.
- Punto de venta enlazado al POS Awesome existente; no es un POS gastronómico
  nuevo desarrollado dentro de esta app.

**Fuera del alcance implementado:** cuentas de servicio, creación de mesas,
mapa de mesas, comandas y cocina KDS. Sus tarjetas son referencias visuales que
informan que aún no están habilitadas. Tampoco están implementados por esta app
el traslado de cuentas, la división de consumos, las reservas ni la impresión
de comandas.
No se declara un POS táctil funcional completo.

## 6. Decisiones de arquitectura

La respuesta al Native Path Check es reutilizar primero las entidades y flujos
estándar. LEAF organiza la experiencia; ERPNext conserva la fuente de verdad
transaccional.

| Necesidad | Camino nativo que se reutiliza o debe evaluarse |
| :--- | :--- |
| Productos y platillos | `Item` |
| Categorías y subcategorías | Árbol de `Item Group` |
| Precios y unidades | `Item Price`, `Price List` y `UOM` |
| Meseros y sucursales | `Employee`, `Designation` y `Branch` |
| Salones, terrazas y otras áreas | `Location` y campos declarativos de la app |
| Facturación y cobro futuros | Evaluar `Sales Invoice` o `POS Invoice` y `Payment Entry` según el flujo aprobado |
| Recetas e inventario futuros | Evaluar `BOM` y `Stock Entry` antes de crear lógica propia |

No se crearán motores paralelos de impuestos, facturas, `GL Entry` o
`Stock Ledger Entry`. Las entidades operativas nuevas requieren análisis previo;
este documento no autoriza su implementación. Se mantiene Python 3.11.x y el
código propio dentro de `restaurant`.

## 7. Entrega y publicación pendientes

La app depende de un entorno Frappe/ERPNext; publicar únicamente HTML estático
no demuestra que la Custom App esté funcionando en internet.

Antes de cerrar la entrega se debe confirmar la autorización de publicación en
`https://github.com/SOLFAHSA/restaurant.git` (con soporte de integración vía Fork
hacia `Grintsys`), preparar una instancia de demostración con un dominio HTTPS,
verificar su funcionamiento y fijar la versión definitiva con la etiqueta o
release `semana-1`. La URL de demostración pública aún está pendiente de definir.

La instancia académica debe usar datos de demostración. No se deben exportar
bases de datos, credenciales o datos personales de los sitios de Grintsys.

## 8. Preguntas pendientes para Manuel y el responsable del proyecto

1. ¿En qué restaurantes se validarán las necesidades relatadas por Manuel y qué casos concretos pueden documentarse?
2. ¿Quiénes podrán participar en la validación y qué tareas realizan actualmente?
3. ¿Qué alcance de publicación autoriza Grintsys y quién alojará la demostración?
4. ¿El evaluador necesita credenciales de demostración para acceder al Desk?
5. ¿Qué parte de la operación se priorizará después de validar esta primera entrega?
