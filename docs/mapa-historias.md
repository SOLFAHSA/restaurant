# Mapa de historias de usuario — Módulo Restaurante Leaf ERP

**Empresa:** Grintsys

**Proyecto:** Módulo Restaurante para Leaf ERP

**Institución:** CEUTEC

**Asignatura:** Proyecto de Graduación Fase 1

**Actividad académica:** Módulo 2 — Del cliente al backlog

## 1. Objetivo

Definir y organizar las historias de usuario del módulo Restaurante, identificar las actividades principales de los distintos usuarios, priorizar las funcionalidades y delimitar un producto mínimo viable (MVP).

Este documento es un artefacto de análisis y planificación. Las historias propuestas no deben interpretarse como funciones desarrolladas o requerimientos validados con clientes del sector gastronómico.

## 2. Contexto del proyecto

Grintsys desarrolla Leaf ERP, una solución empresarial basada en Frappe y ERPNext. El proyecto propone ampliar Leaf mediante un módulo especializado para restaurantes, reutilizando componentes existentes para productos, categorías, precios, clientes y otras operaciones administrativas.

El módulo contempla áreas, mesas, atención de clientes, cuentas, pedidos, comandas, cocina, inventario y reportes.

## 3. Usuarios y actores

- **Administrador:** configura sucursales, áreas, mesas, menús y permisos.
- **Mesero:** atiende mesas, abre cuentas y registra pedidos.
- **Cajero:** gestiona ventas, pagos y cierre de cuentas.
- **Cocina:** recibe y actualiza el estado de los pedidos.
- **Gerente:** supervisa la operación y consulta reportes.
- **Cliente:** recibe el servicio y los comprobantes correspondientes.

## 4. Mapa de actividades

| Actividad | Historias | Resultado esperado |
|---|---|---|
| Configurar restaurante | HU-01, HU-02 | Acceso al módulo y registro de áreas |
| Preparar catálogo | HU-03, HU-04 | Menú organizado con productos y precios |
| Organizar atención | HU-05, HU-06 | Mesas disponibles y personal asignado |
| Tomar pedidos | HU-07, HU-08 | Cuenta abierta y productos registrados |
| Coordinar cocina | HU-09, HU-10 | Comandas y seguimiento de preparación |
| Cobrar | HU-11, HU-12 | Cuenta cerrada y comprobante generado |
| Controlar inventario | HU-13 | Consumo de insumos según receta |
| Supervisar operación | HU-14 | Información y reportes |

## 5. Historias y criterios de aceptación

### HU-01 — Acceder al módulo Restaurante

**Como** administrador, **quiero** acceder al módulo Restaurante desde el menú principal de Leaf **para** encontrar sus funciones en un solo espacio.

**Criterios:**

- Existe un acceso visible denominado Restaurante.
- El acceso abre el Workspace correspondiente.
- El Workspace muestra las funcionalidades agrupadas.
- Las opciones no implementadas no deben simular operaciones exitosas.

**Prioridad:** Alta. **MVP:** Sí.

### HU-02 — Configurar ubicaciones

**Como** administrador, **quiero** registrar áreas como salón y terraza **para** organizar la distribución física del restaurante.

**Criterios:**

- Se puede registrar el nombre de una ubicación.
- El formulario valida los campos obligatorios.
- El registro se guarda y puede consultarse posteriormente.
- No se permiten registros inválidos.
- La ubicación no debe crear mesas automáticamente sin una integración implementada.

**Prioridad:** Alta. **MVP:** Sí.

### HU-03 — Administrar categorías y subcategorías

**Como** administrador, **quiero** organizar los platos en categorías y subcategorías **para** facilitar la navegación del menú.

**Criterios:**

- Se pueden consultar grupos de productos existentes.
- La organización contempla grupos y subgrupos.
- Se respetan las validaciones del proceso nativo reutilizado.
- No se duplican innecesariamente los catálogos del ERP.

**Prioridad:** Alta. **MVP:** Sí.

### HU-04 — Administrar productos y precios

**Como** administrador, **quiero** registrar y consultar productos y precios **para** mantener actualizado el menú.

**Criterios:**

- El acceso conduce al catálogo existente de Leaf.
- Se pueden consultar los datos y precios según permisos.
- Se utiliza la funcionalidad nativa del ERP.
- No se presenta la reutilización como un nuevo motor de ventas.

**Prioridad:** Alta. **MVP:** Sí.

### HU-05 — Configurar mesas

**Como** administrador, **quiero** registrar mesas asociadas a una ubicación **para** controlar su disponibilidad.

**Criterios:**

- Cada mesa posee un identificador.
- Cada mesa está asociada a un área.
- Se puede consultar su estado.
- No se permiten identificadores duplicados dentro del alcance definido.

**Prioridad:** Alta. **MVP:** Sí.

### HU-06 — Gestionar meseros

**Como** administrador, **quiero** identificar los meseros **para** organizar la atención.

**Criterios:**

- Se aprovecha el catálogo existente de empleados cuando corresponda.
- Los registros pueden identificarse por el cargo de mesero.
- Se respetan los permisos de acceso.
- No se duplican empleados innecesariamente.

**Prioridad:** Media. **MVP:** Según validación.

### HU-07 — Abrir una cuenta

**Como** mesero, **quiero** abrir una cuenta para una mesa o cliente **para** registrar su consumo.

**Criterios:**

- La cuenta tiene un identificador.
- Se registra la mesa o el tipo de atención.
- La cuenta inicia en estado abierto.
- No se crean cuentas incompletas o inconsistentes.

**Prioridad:** Alta. **MVP:** Sí.

### HU-08 — Agregar productos a una cuenta

**Como** mesero, **quiero** agregar platos y observaciones **para** registrar correctamente los pedidos.

**Criterios:**

- Se seleccionan productos del catálogo.
- Se registran cantidades.
- Se pueden añadir observaciones.
- El sistema calcula los importes.
- Se validan cantidades y productos antes de guardar.

**Prioridad:** Alta. **MVP:** Sí.

### HU-09 — Generar comandas

**Como** mesero, **quiero** enviar pedidos a cocina **para** iniciar su preparación.

**Criterios:**

- La comanda se vincula a una cuenta.
- Incluye productos, cantidades y observaciones.
- No se envía una comanda vacía.
- Se conserva su relación con el pedido original.

**Prioridad:** Alta. **MVP:** Posterior al flujo básico.

### HU-10 — Gestionar cocina KDS

**Como** personal de cocina, **quiero** visualizar pedidos pendientes y actualizar sus estados **para** coordinar la preparación.

**Criterios:**

- Se muestran los pedidos recibidos.
- Se identifican estados pendiente, en preparación y listo.
- Los cambios quedan asociados a la comanda.
- Un pedido entregado no se modifica sin autorización.

**Prioridad:** Media. **MVP:** No.

### HU-11 — Consultar precuenta

**Como** cajero o mesero, **quiero** consultar una precuenta **para** verificar los consumos antes del cobro.

**Criterios:**

- Se muestran los productos y cantidades registrados.
- Se calculan los importes correspondientes.
- La precuenta no representa por sí misma una factura fiscal.
- No se realizan cobros duplicados.

**Prioridad:** Alta. **MVP:** Según alcance de cobro.

### HU-12 — Cerrar cuenta y registrar pago

**Como** cajero, **quiero** finalizar el consumo **para** completar la venta.

**Criterios:**

- Se muestra el total pendiente.
- Se registra el pago mediante el proceso autorizado.
- Se evita cerrar dos veces la misma cuenta.
- Se conserva la trazabilidad de la operación.

**Prioridad:** Alta. **MVP:** Sí, sujeto a integración validada.

### HU-13 — Controlar recetas e inventario

**Como** administrador, **quiero** asociar ingredientes a los platos **para** controlar el consumo de insumos.

**Criterios:**

- Se definen componentes y cantidades por receta.
- Se utilizan unidades de medida válidas.
- Los movimientos de inventario respetan los mecanismos de ERPNext.
- No se descuentan insumos dos veces por la misma venta.

**Prioridad:** Media. **MVP:** No.

### HU-14 — Consultar reportes

**Como** gerente, **quiero** consultar reportes de operación **para** evaluar ventas y desempeño.

**Criterios:**

- Se muestran datos provenientes de operaciones reales.
- Existen filtros por períodos cuando corresponda.
- Se respetan permisos.
- Los reportes no incluyen datos simulados presentados como transacciones reales.

**Prioridad:** Media. **MVP:** No.

## 6. Priorización por valor y riesgo

Se priorizan primero las historias que permiten validar la configuración y el flujo de atención, considerando tanto su valor como la incertidumbre técnica.

| Historia | Valor | Riesgo | Decisión |
|---|---|---|---|
| HU-01 Acceso al módulo | Alto | Bajo | Temprana |
| HU-02 Ubicaciones | Alto | Medio | Temprana |
| HU-03 y HU-04 Catálogo | Alto | Bajo | Reutilizar |
| HU-05 Mesas | Alto | Medio | Temprana |
| HU-07 y HU-08 Cuenta y pedido | Alto | Alto | Validar en MVP |
| HU-09 Comandas | Alto | Alto | Validar después del flujo inicial |
| HU-10 Cocina KDS | Medio | Alto | Iteración posterior |
| HU-12 Cobro | Alto | Alto | Validar integración |
| HU-13 Inventario | Alto | Alto | Iteración posterior |
| HU-14 Reportes | Medio | Medio | Iteración posterior |

## 7. MVP propuesto para la semana 5

El MVP busca validar un flujo mínimo y verificable:

1. Acceder al Workspace Restaurante.
2. Configurar ubicaciones y mesas.
3. Consultar el catálogo reutilizado de Leaf.
4. Abrir una cuenta.
5. Agregar productos y guardar un pedido.
6. Consultar el estado de la cuenta.
7. Completar el cierre o documentar la integración pendiente, según la viabilidad técnica validada.

El MVP debe guardar información real y comprobarse de extremo a extremo. Su disponibilidad en línea queda sujeta al despliegue y las pruebas.

## 8. Definición de Hecho

Una historia puede marcarse como terminada únicamente cuando:

- Cumple sus criterios de aceptación.
- Ha sido probada con datos persistentes.
- Respeta los permisos y validaciones.
- Está documentada.
- Su código está registrado en GitHub.
- Se ha verificado en el entorno de entrega requerido.
- No se presentan enlaces o pantallas provisionales como funcionalidades terminadas.

## 9. GitHub Backlog

Cada historia puede registrarse como un Issue identificado con HU-XX, su rol, acción, beneficio, criterios de aceptación, prioridad y etiqueta MVP cuando aplique.

Tablero recomendado: **Backlog → En curso → Hecho**.

La creación efectiva de Issues y etiquetas debe comprobarse directamente en GitHub.

## 10. Estado académico y técnico

**Semana 1:** inducción, sin programación.

**Semana 2:** observación de tres reuniones, análisis y preparación del entorno local. Este mapa es un artefacto de planificación.

**Semana 3:** inicio de programación; Workspace Restaurante, accesos reutilizados y DocType de Ubicaciones.
