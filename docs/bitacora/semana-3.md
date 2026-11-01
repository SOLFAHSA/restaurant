# Bitácora de actividades — Semana 3

**Proyecto:** Desarrollo del módulo Restaurante para Leaf ERP

**Empresa receptora:** Grintsys

**Institución:** CEUTEC

**Asignatura:** Proyecto de Graduación Fase 1

**Etapa:** Semana 3 — Diseño, integración y desarrollo inicial

**Tecnologías:** Frappe Framework, ERPNext v14, Python y MariaDB

## 1. Introducción

Durante la tercera semana de práctica profesional en Grintsys, comenzaron las primeras actividades de programación y adaptación del módulo Restaurante dentro de Leaf ERP.

Después de las etapas iniciales de inducción, observación de reuniones con clientes, análisis de procesos y preparación del entorno local, se inició el trabajo técnico relacionado con la estructura y la interfaz del módulo.

Las actividades se concentraron principalmente en la creación del acceso Restaurante dentro del menú principal del sistema, el rediseño de su Workspace, la integración de funcionalidades existentes de Leaf y el desarrollo de un nuevo DocType denominado Restaurant Area, utilizado para gestionar las ubicaciones físicas de un restaurante.

Esta etapa permitió aplicar los conocimientos adquiridos sobre Frappe, ERPNext, DocTypes y la organización del código fuente de la plataforma.

## 2. Objetivo de la semana

Iniciar el desarrollo del módulo Restaurante mediante la creación de una estructura de navegación integrada con Leaf ERP, la reutilización de procesos ya existentes y la implementación de un primer componente de gestión propio del restaurante.

## 3. Actividades realizadas

### 3.1. Creación de la opción Restaurante en el menú principal

Se incorporó una nueva opción denominada Restaurante dentro de la navegación principal de Leaf ERP.

Esta opción permite identificar el módulo y acceder a un espacio de trabajo específico para la operación gastronómica.

Se procuró mantener el diseño general y la estructura de navegación establecidos por Grintsys, garantizando consistencia visual con los demás módulos.

**Resultado:** acceso Restaurante incorporado a la navegación del sistema.

### 3.2. Rediseño del Workspace Restaurante

Se realizó el rediseño y la organización del Workspace correspondiente al módulo Restaurante.

El propósito fue establecer una estructura visual que permitiera identificar los procesos que integrarán la solución.

Se organizaron accesos relacionados con:

- Punto de venta.
- Cuentas y nuevas cuentas.
- Mesas y mapa de mesas.
- Meseros.
- Ubicaciones.
- Comandas.
- Cocina KDS.
- Productos y platillos.
- Categorías y subcategorías.
- Precios de productos.
- Clientes y reportes.
- Configuración general.

Este diseño representa la estructura funcional prevista del módulo. La presencia de una opción en el Workspace no significa necesariamente que su desarrollo esté terminado.

**Resultado:** Workspace organizado para facilitar la navegación actual y el desarrollo progresivo de los procesos pendientes.

### 3.3. Integración de funcionalidades existentes de Leaf ERP

Se analizaron funcionalidades que Leaf ERP ya proporcionaba y que podían aprovecharse dentro del módulo Restaurante.

Se incorporaron accesos para:

**Productos y platillos:** utilizando el DocType nativo Item para administrar artículos y productos.

**Categorías y subcategorías:** mediante Item Group, aprovechando la estructura de clasificación existente.

**Precios de productos:** mediante Item Price, conservando el funcionamiento del catálogo de precios.

El trabajo consistió en vincular estos procesos al Workspace Restaurante, respetando su lógica y sus mecanismos existentes.

No se programaron nuevamente esos procesos ni se duplicaron sus estructuras de datos.

**Resultado:** reutilización de componentes nativos de Leaf ERP desde la nueva interfaz del restaurante.

### 3.4. Análisis y desarrollo del DocType Ubicaciones

Una de las principales actividades de programación fue el desarrollo de un nuevo DocType denominado Restaurant Area.

Su finalidad es administrar las áreas o espacios físicos de un restaurante, como salones, terrazas, barras y áreas privadas.

Se analizó la necesidad de disponer de un componente específico para este proceso y se desarrolló dentro de la Custom App Restaurant, manteniendo la independencia del código principal de ERPNext.

El componente contempla campos como nombre del área, sucursal, capacidad, tipo de área, estado y orden de visualización.

También incorpora opciones de configuración y referencias a elementos existentes, como empleados e impresoras.

**Resultado:** DocType Restaurant Area desarrollado como primera estructura especializada de información del módulo Restaurante.

### 3.5. Desarrollo de la interfaz de Ubicaciones

Se trabajó en una pantalla para consultar y administrar ubicaciones dentro del entorno de Leaf.

El desarrollo incorpora una interfaz de gestión relacionada con el nuevo DocType, permitiendo trabajar con los datos de las áreas del restaurante.

El diseño busca mantener consistencia con el entorno visual existente y facilitar la futura integración de las mesas y cuentas.

**Resultado:** estructura de gestión de ubicaciones disponible en el entorno local de desarrollo.

### 3.6. Validación y pruebas del componente

Se realizaron actividades de validación para comprobar el comportamiento del DocType Restaurant Area.

La documentación técnica del repositorio registra una suite de 10 pruebas ejecutadas satisfactoriamente, con 0 fallos y 0 errores.

Entre los aspectos verificados se encuentran:

- Guardado y recuperación de registros.
- Validación de campos.
- Asociación con sucursales.
- Comprobación de permisos.
- Control de concurrencia.
- Protección frente a valores inválidos.
- Conservación de información existente.

Estas pruebas corresponden específicamente al componente Ubicaciones en el entorno de desarrollo.

**Resultado:** evidencia técnica del funcionamiento y persistencia del DocType Restaurant Area.

### 3.7. Control de versiones y documentación

Se utilizaron Git y GitHub para registrar los avances del módulo Restaurante.

Los cambios técnicos se organizaron en el repositorio correspondiente a la Custom App Restaurant.

También se documentaron aspectos relacionados con la instalación, arquitectura, funcionamiento de Ubicaciones y decisiones de integración con los componentes existentes.

**Resultado:** avances de código y documentación registrados en el repositorio del proyecto.

### 3.8. Relación con los contenidos académicos del módulo 3

Durante el curso universitario se estudiaron los conceptos de:

- Entidades y relaciones.
- Llaves primarias y foráneas.
- Normalización.
- Integridad de datos.
- Restricciones de unicidad y obligatoriedad.
- Migraciones versionadas.
- Datos de prueba.
- Persistencia de información.
- Validación en pantalla, servidor y base de datos.

Estos conocimientos permitieron relacionar la implementación del DocType Ubicaciones con la importancia de diseñar estructuras de datos confiables.

Se preparó un modelo conceptual del módulo completo, distinguiendo las entidades existentes, la estructura desarrollada durante la semana y los componentes pendientes.

## 4. Resultados obtenidos

Los principales resultados de la semana fueron:

1. Incorporación del módulo Restaurante a la navegación principal de Leaf.
2. Rediseño y organización del Workspace.
3. Integración de los accesos a productos, categorías y precios existentes.
4. Desarrollo del nuevo DocType Restaurant Area.
5. Desarrollo de la interfaz de administración de Ubicaciones.
6. Validaciones y pruebas documentadas del componente.
7. Registro de los avances mediante Git y GitHub.
8. Mayor comprensión de la arquitectura de Frappe y la persistencia de información en MariaDB.

## 5. Dificultades identificadas

Entre los principales desafíos se encontraron la comprensión de la arquitectura existente de Leaf ERP, la necesidad de respetar los lineamientos del código fuente y la diferenciación entre funcionalidades nativas y desarrollos nuevos.

También fue necesario analizar los componentes antes de modificarlos, con el objetivo de evitar duplicaciones y mantener la compatibilidad con el sistema.

Esta experiencia permitió comprender que el desarrollo sobre una plataforma empresarial existente requiere tanto conocimiento de programación como análisis de arquitectura, procesos y dependencias.

## 6. Funcionalidades pendientes

Al cierre de esta etapa se mantienen en desarrollo o planificación:

- Gestión de mesas.
- Apertura y administración de cuentas.
- Registro de pedidos.
- Generación de comandas.
- Monitor de cocina KDS.
- Integración de recetas con inventario.
- Operaciones especializadas de cobro.
- Reportes operativos específicos.

La representación visual de estas opciones en el Workspace no constituye evidencia de que ya funcionen.

## 7. Alcance de la persistencia y la publicación

El desarrollo de Restaurant Area utiliza la persistencia de Frappe y MariaDB en el entorno local de desarrollo.

La documentación técnica registra pruebas de almacenamiento y recuperación de datos reales de prueba.

Sin embargo, estas pruebas no constituyen por sí solas una verificación de la publicación del flujo gastronómico completo en un servidor HTTPS.

La comprobación del despliegue público y de los procesos operativos completos permanece como actividad pendiente de validación.

## 8. Aprendizajes de la semana

Durante esta semana fortalecí mis conocimientos relacionados con el desarrollo de aplicaciones sobre Frappe y ERPNext, el manejo de DocTypes y la integración de funcionalidades existentes.

Uno de los aprendizajes más importantes fue comprender que no siempre es necesario programar nuevamente un proceso para incorporarlo a un módulo. En muchos casos, es más conveniente reutilizar los componentes que ya proporciona el sistema, respetando su estructura y funcionamiento.

También comprendí la importancia de diseñar correctamente los datos, definir validaciones y desarrollar componentes que puedan integrarse progresivamente con otras funcionalidades.

## 9. Próximas actividades

Para las siguientes etapas se contempla:

- Continuar el desarrollo del módulo Restaurante.
- Analizar e implementar la gestión de mesas.
- Relacionar las mesas con las ubicaciones.
- Definir el modelo de cuentas abiertas.
- Preparar el flujo de pedidos.
- Evaluar la integración con POS Awesome.
- Extender las pruebas de persistencia.
- Continuar la documentación y el control de versiones.

## 10. Conclusión

La tercera semana de práctica profesional representó el inicio del desarrollo técnico del módulo Restaurante para Leaf ERP.

El trabajo se concentró principalmente en el rediseño del Workspace, la creación de una estructura de navegación para los futuros procesos del restaurante y la reutilización de funcionalidades ya disponibles dentro del sistema.

El avance más importante de desarrollo propio fue la creación del DocType Restaurant Area, destinado a administrar las ubicaciones y áreas físicas del restaurante.

Las actividades realizadas permitieron poner en práctica los conocimientos adquiridos en las primeras semanas y establecer una base funcional y técnica para continuar con el desarrollo de mesas, cuentas, pedidos y demás procesos previstos.

Aunque todavía existen funcionalidades pendientes, los avances representan el primer incremento del módulo Restaurante dentro de la arquitectura de Leaf ERP.
