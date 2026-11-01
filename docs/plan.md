# Plan de desarrollo de diez semanas — Módulo Restaurante Leaf ERP

**Empresa receptora:** Grintsys

**Proyecto:** Módulo Restaurante para Leaf ERP

**Institución:** CEUTEC

**Asignatura:** Proyecto de Graduación Fase 1

**Metodología:** Desarrollo incremental, historias de usuario y MVP.

## 1. Objetivo general

Planificar el desarrollo progresivo de un módulo de gestión de restaurantes integrado con Leaf ERP, aprovechando las funcionalidades existentes de la plataforma y desarrollando componentes específicos para la operación gastronómica.

Se busca organizar el trabajo mediante entregas verificables, con historias priorizadas, criterios de aceptación y seguimiento del avance.

## 2. Contexto tecnológico

El módulo se desarrollará como una aplicación independiente dentro del entorno Leaf ERP, basado en Frappe Framework y ERPNext versión 14.

Tecnologías y componentes:

- Python para lógica de servidor.
- Frappe Framework para arquitectura y DocTypes.
- ERPNext para funcionalidades empresariales.
- MariaDB para almacenamiento de información.
- JavaScript, HTML y CSS para interfaces.
- Docker y Dev Containers para el entorno local de desarrollo.
- Git y GitHub para control de versiones.
- POS Awesome como componente existente que será evaluado para integración.

El trabajo deberá respetar la arquitectura del repositorio, los lineamientos de Grintsys y la reutilización de componentes disponibles.

## 3. Organización del trabajo

El proyecto se desarrollará mediante incrementos funcionales, procurando evitar la creación de procesos duplicados que ya existan en Leaf.

Cada nueva funcionalidad deberá analizarse, diseñarse, implementarse, validarse y documentarse conforme al alcance aprobado.

Las semanas 1, 2 y 3 reflejan actividades ya comunicadas. Las semanas 4 a 10 constituyen planificación propuesta, sujeta a revisión técnica y académica.

## 4. Cronograma de diez semanas

### Semana 1 — Inducción empresarial

**Actividades:**

- Conocer Grintsys, sus soluciones y su metodología.
- Familiarizarse con Leaf ERP y su finalidad.
- Observar dos reuniones con clientes.
- Comprender la importancia del levantamiento de información.
- Analizar tres alternativas iniciales de proyectos: Restaurantes, Encomiendas y Hospitales.

**Resultado:** conocimiento del contexto empresarial y evaluación conceptual de alternativas.

**Estado:** Actividad realizada. No se efectuó programación.

### Semana 2 — Análisis y preparación del entorno local

**Actividades:**

- Participar como observador en tres reuniones con clientes.
- Conocer cómo se realiza la presentación, el diagnóstico y el análisis de necesidades.
- Estudiar la documentación técnica proporcionada por Grintsys.
- Comenzar la preparación del entorno de desarrollo local.
- Recibir orientación sobre Frappe, ERPNext, Python, MariaDB y DocTypes.
- Estudiar la organización del código fuente.
- Trabajar académicamente los conceptos de mapa de historias, backlog, criterios de aceptación y MVP.

**Resultado:** conocimientos sobre análisis de clientes y preparación técnica inicial, además de artefactos de planificación académica.

**Estado:** Actividad realizada. No se desarrollaron funcionalidades nuevas durante esta semana.

### Semana 3 — Workspace Restaurante y Ubicaciones

**Actividades:**

- Incorporar la opción Restaurante al menú de Leaf.
- Diseñar la organización visual del Workspace.
- Vincular accesos a productos y platillos, categorías y subcategorías, y precios existentes.
- Crear el DocType Ubicaciones como componente específico del restaurante.
- Preparar la estructura visual para futuras funciones.

**Resultado:** estructura inicial del módulo, reutilización de funciones y primer componente desarrollado de forma independiente.

**Estado:** Desarrollo inicial realizado, según los avances documentados.

### Semana 4 — Gestión de mesas

**Actividades propuestas:**

- Analizar un DocType similar antes de implementar.
- Definir el modelo de mesas y su relación con ubicaciones.
- Establecer identificadores y estados de mesa.
- Implementar formulario, listado y validaciones.
- Realizar pruebas funcionales.

**Entregable esperado:** gestión básica de mesas persistente y verificable.

### Semana 5 — Producto mínimo viable

**Actividades propuestas:**

- Integrar mesas con cuentas abiertas.
- Implementar el registro mínimo de pedidos.
- Utilizar el catálogo existente de Leaf.
- Validar cantidades, productos y datos de la cuenta.
- Comprobar el flujo completo con datos reales.
- Publicar el avance en un entorno HTTPS autorizado.

**Entregable esperado:** MVP que permita demostrar, como mínimo, un flujo de atención persistente.

**Punto de control:** Validación con responsables y usuarios disponibles; reajuste del alcance si existen dependencias técnicas.

### Semana 6 — Atención y personal operativo

**Actividades propuestas:**

- Desarrollar o integrar la asignación de meseros.
- Organizar pedidos por mesa o modalidad de atención.
- Gestionar observaciones de productos.
- Revisar roles y permisos operativos.
- Validar cambios de estado.

**Entregable esperado:** flujo de atención organizado para mesero y caja.

### Semana 7 — Comandas y cocina

**Actividades propuestas:**

- Crear la representación de comandas.
- Evaluar estaciones de preparación.
- Implementar seguimiento de estados.
- Desarrollar una primera vista de monitor de cocina.
- Evaluar impresión térmica cuando exista configuración compatible.

**Entregable esperado:** flujo demostrable de pedido hacia cocina.

### Semana 8 — Cuentas, pagos e inventario

**Actividades propuestas:**

- Ampliar operaciones de cuentas.
- Evaluar separación de consumos y precuentas.
- Integrar cobros con los componentes autorizados de Leaf.
- Analizar recetas, componentes e inventario mediante recursos de ERPNext.
- Comprobar que no existan registros o movimientos duplicados.

**Entregable esperado:** integración progresiva de atención y procesos empresariales.

### Semana 9 — Reportes y pruebas

**Actividades propuestas:**

- Evaluar reportes operativos y ventas.
- Incorporar filtros y búsquedas.
- Revisar exportaciones según permisos.
- Ejecutar pruebas funcionales, de seguridad y de integridad.
- Documentar incidencias y correcciones.
- Evaluar requisitos académicos adicionales.

**Entregable esperado:** versión candidata a entrega, con evidencia de pruebas.

### Semana 10 — Validación y entrega

**Actividades propuestas:**

- Ejecutar pruebas integrales de los flujos disponibles.
- Verificar la instalación en el entorno autorizado.
- Revisar documentación y repositorio.
- Preparar demostración funcional.
- Registrar limitaciones y funcionalidades futuras.
- Presentar resultados y aprendizajes.

**Entregable esperado:** versión final académica del módulo dentro del alcance validado.

## 5. MVP

El MVP tendrá como objetivo evaluar si los procesos esenciales del restaurante pueden ejecutarse dentro de Leaf aprovechando su estructura actual.

**Alcance inicial propuesto:**

- Workspace Restaurante.
- Configuración de ubicaciones.
- Gestión básica de mesas.
- Catálogo de productos y precios reutilizado.
- Apertura de cuenta.
- Registro de pedidos con persistencia.

El cobro completo y la integración avanzada con cocina e inventario deberán incorporarse según su viabilidad y prioridad.

**Validación esperada:** lograr que un usuario ejecute el flujo previsto con datos reales sin depender de pantallas simuladas.

## 6. Historias y entregables

| Etapa | Historias principales |
|---|---|
| Configuración inicial | HU-01, HU-02, HU-03, HU-04 |
| Mesas y personal | HU-05, HU-06 |
| Atención y pedidos | HU-07, HU-08 |
| Comandas y cocina | HU-09, HU-10 |
| Cobro | HU-11, HU-12 |
| Inventario y reportes | HU-13, HU-14 |

## 7. Requisitos adicionales del curso

El material académico establece como referencia para la aplicación completa:

- Más de 20 tablas de negocio.
- Al menos 3 roles.
- Al menos 6 flujos completos.
- Panel con reportes y exportación.
- Búsquedas y filtros.
- Carga de archivos.
- Notificaciones.
- Bitácora de auditoría.
- Al menos una integración externa.
- PWA instalable.

Estos elementos deberán incluirse en una matriz de cobertura y evaluarse con Grintsys. Se contabilizarán los componentes nativos de ERPNext únicamente cuando su uso real dentro del módulo esté comprobado. No se presupone que estén implementados ni que se requiera crear veinte tablas nuevas.

La compatibilidad y viabilidad de una PWA, de las notificaciones y de otras integraciones requieren evaluación adicional.

## 8. Riesgos y medidas de mitigación

| Riesgo | Medida |
|---|---|
| Curva de aprendizaje de Frappe y ERPNext | Estudiar componentes y DocTypes similares |
| Duplicación de funciones existentes | Aplicar reutilización de procesos nativos |
| Problemas de integración | Implementar y probar cambios pequeños |
| Falta de disponibilidad de usuarios | Coordinar validaciones con responsables |
| Problemas con publicación HTTPS | Preparar y verificar un entorno autorizado |
| Alcance amplio | Priorizar MVP e iteraciones posteriores |
| Incompatibilidad con código empresarial | Respetar reglas y arquitectura del repositorio |

## 9. Control de calidad y seguimiento

Cada historia deberá contener descripción funcional, criterios de aceptación y evidencia de prueba.

Se utilizarán commits pequeños y descriptivos para registrar los cambios. Las funcionalidades solo se considerarán terminadas cuando estén probadas, documentadas y disponibles en el entorno requerido para su evaluación.

La bitácora semanal registrará las actividades reales, los resultados y los obstáculos, diferenciando el trabajo ejecutado de las actividades futuras.

## 10. Consideración académica

El curso propone una primera historia publicada durante la semana 2 y un MVP en la semana 5. Sin embargo, en la práctica profesional documentada la semana 2 se dedicó a reuniones, análisis y preparación del entorno local.

Por tanto, el hito técnico correspondiente a la primera historia en línea deberá reportarse con su fecha real de implementación y publicación, sin atribuir desarrollo a una semana en la cual no se realizó programación.
