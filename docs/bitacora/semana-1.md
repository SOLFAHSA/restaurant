# Bitácora de la semana 1

- Participante: Manuel Padilla, practicante de Ingeniería en Sistemas, CEUTEC.
- Proyecto: Custom App `restaurant` para LEAF ERP v14 / Grintsys.
- Período documentado: 29 y 30 de octubre de 2026.
- Estado: borrador local para revisión académica; publicación pendiente.
- Rama inspeccionada: `feature/modulo-restaurante`.
- Corte del historial: `0607fa5`.

## Objetivo de la semana

Establecer una app independiente para Restaurante y una portada integrada en
Frappe Desk que reutilice los catálogos y procesos existentes de LEAF ERP.
Documentar el avance real y distinguirlo de las funciones todavía propuestas.

## Actividades y evidencia del historial

Las fechas corresponden al campo de autor de los commits. El primer commit está
registrado en UTC; los cuatro siguientes tienen zona horaria UTC-06:00.

| Fecha | Commit | Trabajo registrado | Evidencia versionada |
| :--- | :--- | :--- | :--- |
| 2026-10-29 | `18ac1b0` | Inicialización de la app. | Estructura inicial del paquete y metadatos. |
| 2026-10-30 | `ff27ff4` | Renombrado a `restaurant` y conservación de la bienvenida. | Paquete `restaurant`, `migrate_app_name.py` y plantilla web. |
| 2026-10-30 | `9fb16c2` | Workspace Restaurante con accesos nativos e iconos. | Workspace e icono registrados dentro de la app. |
| 2026-10-30 | `31fe08b` | Configuración de accesos a meseros, sucursales y ubicaciones. | Fixtures de `Designation` y `Custom Field`, y configuración del Workspace. |
| 2026-10-30 | `0607fa5` | Rediseño de la interfaz del módulo Restaurante. | Bloque HTML/CSS/JavaScript, hook de exportación, Workspace y README. |

**VERIFIED:** el historial local contiene cinco commits al corte indicado. Su
existencia local no demuestra todavía que estén disponibles en un repositorio
público. No se han creado commits artificiales para completar el requisito.

## Levantamiento del contexto del proyecto

**Fuente:** explicación de Manuel Padilla durante la preparación de esta entrega.
Según Manuel, Grintsys le solicitó apoyar la creación de un módulo Restaurante
para ampliar la cobertura de LEAF ERP hacia ese rubro durante su práctica.
Este registro documenta su relato; no sustituye una entrevista directa con la
empresa ni una aprobación formal de alcance o de publicación.

Manuel planteó las siguientes necesidades:

- Facilitar a los comensales la separación de una cuenta y la reserva de mesas.
- Dar al propietario y al administrador mejor control del negocio y visibilidad
  de los movimientos de inventario.
- Coordinar el proceso entre la estación de meseros, la cocina y el cajero.

**ANALYZED:** este contexto fundamenta la motivación de la visión y del Lean
Canvas. No incluye ejemplos medidos de un restaurante específico ni entrevistas
con usuarios finales; la frecuencia, las causas y el impacto quedan por validar.
Las necesidades descritas no se registran como funcionalidades ya desarrolladas.

Se actualizó la documentación local con este contexto. Esta actividad aún no
forma parte de los cinco commits enumerados en el corte del historial.

## Decisiones de arquitectura

- Mantener `restaurant` como repositorio y aplicación independientes; no alojar
  su código dentro de `frappe` ni de `erpnext`.
- Usar `Item`, `Item Group`, `Item Price` y `UOM` para el catálogo gastronómico.
- Reutilizar `Employee` con el cargo `Mesero`, y `Branch` para sucursales.
- Reutilizar `Location` para salones y otras áreas. Los campos declarativos
  `restaurant_area` y `restaurant_branch` se exportan desde la app.
- Construir la portada mediante el Workspace y `Custom HTML Block` nativos.
- Reservar facturación, impuestos, cobros y movimientos contables a los
  documentos y procesos nativos de ERPNext; no construir un motor paralelo.

**ANALYZED:** estas decisiones están reflejadas en los archivos del repositorio.
La configuración de navegación no equivale a haber implementado todos los
procesos de un restaurante.

## Incidencia y aprendizaje técnico

Después del rediseño, la portada quedó sin contenido. La referencia del bloque
usaba `Restaurant Dashboard`, pero la etiqueta de la tabla `custom_blocks` del
Workspace estaba configurada como `Restaurante`. El renderizador nativo busca
el bloque por su etiqueta; la discrepancia impedía localizarlo.

Se unificó la etiqueta con la referencia. La corrección forma parte de `0607fa5`.
La regla de mantenimiento está documentada en el README.

La prueba local con clases reales de Frappe y EditorJS reprodujo cero tarjetas
con la etiqueta anterior y quince tarjetas en cuatro secciones con la etiqueta
corregida. También comprobó la navegación hacia productos, el aviso de opciones
pendientes y la ausencia de desbordamiento horizontal en tamaños de escritorio
y móvil. Esta prueba aislada no equivale a una certificación completa del flujo
operativo ni del despliegue público; sus artefactos no forman parte de este repo.

## Verificación reproducible del avance

Desde la raíz del repositorio de la app:

```bash
git status --short --branch
git log --format='%h | %aI | %s' -5
git rev-list --count HEAD
git rev-list --count --since='10 days ago' HEAD
git show --stat 0607fa5
git diff --check
git remote -v
git tag --list
```

**VERIFIED al corte:** cinco commits totales y cinco dentro de los diez días
anteriores a la revisión del 30 de octubre de 2026. Ese conteo es temporal y
debe comprobarse nuevamente el día de entrega. No había remoto ni etiquetas.

## Pendientes de la entrega

- Confirmar autorización de Grintsys para publicar este código y sincronizar su Fork empresarial (`Grintsys/restaurant`) desde el repositorio principal del participante (`https://github.com/SOLFAHSA/restaurant.git`).
- Revisar la [visión y el Lean Canvas](../vision.md), y aportar evidencia real
  del problema con observación o entrevistas.
- Verificar la publicación de la rama `feature/modulo-restaurante` en `https://github.com/SOLFAHSA/restaurant.git`.
- Preparar una instancia de demostración con dominio público y HTTPS, sin datos
  personales o de producción; verificar que ejecute la app real.
- Crear la etiqueta o release `semana-1` sobre el commit de entrega definitivo.
- Pegar las dos URL reales en la plataforma y ejecutar su validación.

No se ha declarado completada la entrega ni se ha sustituido la app por una
captura o una página estática.
