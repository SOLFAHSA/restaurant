# Bitácora de actividades — Semana 7

**Proyecto:** Desarrollo del módulo Restaurante para Leaf ERP

**Empresa receptora:** Grintsys

**Institución:** CEUTEC

**Asignatura:** Proyecto de Graduación Fase 1

**Etapa:** Semana 7 (23 al 29 de noviembre de 2026) — Calidad comprobable: estrategia de pruebas, pruebas de extremo a extremo, pipeline de integración continua y tercer flujo completo

**Tecnologías:** Frappe Framework v14, ERPNext v14 (Grintsys), POS Awesome, Python 3.11, JavaScript, MariaDB, Redis, Socket.IO, Playwright y GitHub Actions

## 1. Introducción

La semana 7 se dedicó a que la calidad del módulo se pueda **comprobar**, no solo afirmar. Se escribió la estrategia de pruebas por foco de riesgo, se agregaron las primeras pruebas con un navegador real, se creó el pipeline que revisa cada cambio y se terminó el tercer flujo del negocio: el cobro con varios métodos de pago. A mitad de semana también se ordenó el flujo de trabajo en GitHub, que se había vuelto difícil de revisar.

## 2. Objetivo de la semana

Definir qué se prueba y en qué nivel, automatizar las pruebas de reglas, permisos y dinero, agregar al menos una prueba de extremo a extremo del flujo central y una de un permiso crítico, crear el pipeline de integración continua y completar el **cobro con pagos mixtos** como tercer flujo.

## 3. Actividades realizadas

### 3.1. Por fecha

| Fecha | Actividad | Evidencia |
| :--- | :--- | :--- |
| 23/11 | `pos.py` separado por funcionalidad (`cash/`, `catalog/`, `orders/`, `checkout/`, `pos_settings/`); combos que descuentan del inventario sus componentes; tablero del restaurante; primeros pagos mixtos | PR #41; ramas de combos, tablero y pagos |
| 25/11 | Estrategia de pruebas (`docs/pruebas.md`), arquitectura real por funcionalidad, decisión 003 de combos; corrección del tiempo real en la pantalla de cocina | Commits de documentación; issue #15 |
| 26/11 | Revisión de la directiva de impuestos de Grintsys; actualización de ERPNext a la rama oficial `version-14`; informe de 13 fallas del núcleo de ERPNext para Grintsys | `docs/qa/` (informe para el supervisor) |
| 27/11 | Rediseño del cobro: líneas por método de pago, cambio y restante; corrección del teclado de cobro que cambiaba la cantidad del producto; cliente con el formulario nativo de ERPNext | PR #45; issues #38 y #46 |
| 28/11 | Pantalla de cocina con filtros, limpiar todo, zoom y modo oscuro nativo; reordenamiento de ramas desde la principal; pull requests #48 a #51 mezclados; pruebas de extremo a extremo con Playwright; limpieza de código sin uso; pipeline de integración continua | PR #48 a #51, #53 y #55; issues #47, #52 y #54 |

### 3.2. Estrategia de pruebas

Se documentó en [`docs/pruebas.md`](../pruebas.md), por los cuatro focos de riesgo del curso:

| Foco | Ejemplos de lo que se prueba | Nivel |
| :--- | :--- | :--- |
| Reglas del negocio | Combos que descuentan componentes, cocina que avanza por etapas, orden igual a la factura | Integración |
| Permisos | El mesero no cobra ni crea clientes; solo el gerente limpia órdenes en preparación | Integración y extremo a extremo |
| Dinero | Pagos mixtos, cambio solo en efectivo, descuentos, ISV por producto, arqueo | Integración |
| Flujo central | Abrir cuenta, agregar producto, cobrar y obtener la factura SAR | Extremo a extremo |

Los valores esperados se calcularon a mano (por ejemplo, tarjeta L 65 + efectivo L 100 para L 115 da cambio L 50) y las pruebas corren en el sitio `test_restaurant`, nunca en producción, con `--skip-before-tests --skip-test-records`.

### 3.3. Pruebas de extremo a extremo

Se agregó la carpeta `e2e/` con **Playwright 1.49.1** (versión fija) y dos pruebas cuyo nombre es el criterio:

- *Dado un cajero con turno abierto, cuando cobra una cuenta en efectivo, entonces ve la factura SAR emitida.* La prueba también comprueba en ERPNext que la factura existe y está emitida.
- *Dado un mesero, cuando agrega un producto a una cuenta, entonces no ve la opción de cobrar.*

Resultado contra el sitio de desarrollo: **2 de 2 aprobadas**. La primera ejecución del cajero se detuvo porque ese usuario no tenía turno de caja abierto; se abrió el turno y la prueba ahora lo indica con un mensaje claro.

### 3.4. Pipeline de integración continua

Se creó `.github/workflows/ci.yml`, que corre en cada push y pull request a la rama principal con los cinco pasos del curso:

1. Descargar el código.
2. Instalar con versiones fijas (Python 3.11, Node 18, ruff 0.8.4, Bench 5.31.1, Playwright del `package-lock`).
3. Revisar estilo: errores y código sin uso en Python, sintaxis de JavaScript y carga de las pruebas de Playwright.
4. Correr las pruebas del módulo en un sitio de pruebas nuevo.
5. Construir los recursos del módulo.

Antes de activarlo, la revisión de estilo encontró 9 importaciones y 6 variables sin uso y una prueba definida dos veces; se eliminaron. El trabajo de pruebas completas necesita dos secretos de GitHub (el token de lectura del ERPNext privado de Grintsys y la contraseña de la base de pruebas), que nunca van en el archivo.

### 3.5. Tercer flujo: cobro con pagos mixtos

El cajero cobra una cuenta con efectivo, tarjeta y transferencia en **una sola factura nativa**, y el cambio solo sale de la parte en efectivo; el servidor rechaza cualquier otro caso. Se verificó con pruebas automáticas y con tres facturas reales en desarrollo, cuyo libro mayor cuadra. Entra a la rama principal por el PR #45 **con el pipeline en verde**.

### 3.6. Orden del flujo de trabajo en GitHub

A mitad de semana había seis ramas apiladas una sobre otra, y un pull request (#42) se mezcló por error en la rama equivocada. Se respaldó cada rama, se reconstruyó cada una desde la rama principal con solo sus propios commits, se probó cada una por separado y todas juntas, y se publicaron de nuevo. Desde entonces cada rama sale de la principal y cada cambio no planeado tiene su propio issue.

## 4. Issues y pull requests de la semana

| Issue | Tema | Pull request | Estado |
| :--- | :--- | :--- | :--- |
| #14 | Combos que no descontaban sus componentes | #48 | Cerrado |
| #15 | La pantalla de cocina no se actualizaba en tiempo real | #50 | Cerrado |
| #38 | Cobrar con varios métodos de pago (tercer flujo) | #45 | Abierto, se mezcla con el pipeline en verde |
| #39 | Tablero del restaurante | #49 | Cerrado |
| #40 | Aviso falso de "orden modificada por otro usuario" | — | Abierto; una de sus causas (el teclado de cobro) se corrigió en #45 |
| #43 | Propina como pasivo y plantillas de impuestos | #44 | Abierto, en revisión con el supervisor y Grintsys |
| #46 | Crear cliente con el formulario nativo | #45 | Abierto |
| #47 | Filtros, limpiar todo, zoom y modo oscuro en la cocina | #50 | Cerrado |
| #52 | Pruebas de extremo a extremo | #53 | Abierto |
| #54 | Pipeline de integración continua y rama protegida | #55 | Abierto |

## 5. Pruebas ejecutadas y verificación

| Comprobación | Resultado |
| :--- | :--- |
| Suite completa con combos, tablero, pagos, cocina y documentación juntos | 276 pruebas: 263 aprobadas, 10 omitidas y 13 fallas, todas del núcleo de ERPNext `version-14` |
| Pruebas de cocina (`test_kds`) | 30 de 30 aprobadas, incluidas 2 nuevas de limpiar órdenes |
| Pruebas de pagos mixtos (`test_mixed_payment`) | 2 de 2 aprobadas |
| Pruebas de extremo a extremo (Playwright) | 2 de 2 aprobadas |
| Revisión de estilo (`ruff --select E9,F`) | Sin errores |
| Revisión de sintaxis de JavaScript | 25 archivos sin errores |

Las **13 fallas** no son del módulo Restaurante: 11 corresponden a la numeración CAI y 2 al ISV duplicado cuando un producto aparece en dos líneas, ambos en el ERPNext de Grintsys. **No se desactivó ninguna prueba**; se reportaron al supervisor con su evidencia.

## 6. Uso de inteligencia artificial

Se usó Claude Code como asistente de desarrollo. Propuso diseños, escribió código y pruebas, revisó el código sin uso, analizó facturas y registros de cambios en la base de datos y redactó documentación. Manuel definió el diseño de cada pantalla con sus referencias, probó cada cambio en pantalla, emitió las facturas de prueba, ejecutó las pruebas de navegador, revisó cada pull request con su lista de autorrevisión y tomó las decisiones de negocio. Las decisiones fiscales se dejaron para el supervisor.

## 7. Dificultades identificadas

- El ERPNext oficial de Grintsys (`version-14`) tiene 13 fallas que el pipeline detecta; mientras no se resuelvan, el trabajo de pruebas completas no puede quedar en verde sin desactivar pruebas, y eso no se hará.
- `Grintsys/erpnext14` es privado: el pipeline necesita un token de lectura que debe proporcionar la empresa.
- Las ramas apiladas complicaron la revisión y provocaron que un pull request se mezclara en la rama equivocada.
- El teclado de cobro compartía su marca con el teclado de la orden y cambiaba la cantidad del producto; se encontró revisando el historial de cambios de una orden real.
- El servicio de tiempo real (puerto 9000) no estaba encendido en el entorno de desarrollo, por eso la cocina no se actualizaba sola.

## 8. Aprendizajes de la semana

1. Se prueba primero donde más duele fallar: reglas, permisos, dinero y flujo central.
2. Una prueba de extremo a extremo encuentra lo que no ve una de integración: el cajero sin turno abierto no puede cobrar, aunque el servidor esté bien.
3. El pipeline no reemplaza las pruebas; las ejecuta en cada cambio y no deja pasar lo que falla.
4. Cada rama sale de la principal y se mezcla pronto; si aparece un cambio no planeado, primero se crea su issue.
5. Antes de escribir algo nuevo se busca lo nativo: el formulario de clientes, el tema oscuro y el cierre de caja ya existían en Frappe, ERPNext y POS Awesome.

## 9. Próximas actividades

- Configurar los secretos del pipeline y la protección de la rama principal cuando el supervisor entregue el token de lectura.
- Mezclar el PR #45 (pagos mixtos) con el pipeline en verde.
- Revisar con el supervisor y Grintsys los impuestos (PR #44) y las 13 fallas del núcleo.
- Unificar las denominaciones de billetes y monedas del arqueo en su configuración, sin listas repetidas en el código.
- Publicar la versión actual del módulo en el servidor del entorno en línea.
