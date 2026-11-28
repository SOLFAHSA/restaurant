# Cómo ejecutar las pruebas del módulo Restaurante

Guía paso a paso para correr la suite automática de `restaurant` en un **sitio exclusivo de pruebas**, sin tocar el sitio de trabajo `development`.

> Resultado de referencia (2026-11-19): 246 pruebas, 226 aprobadas, 4 fallos, 6 errores, 10 omitidas. Detalle en [linea-base-2026-11-19.md](linea-base-2026-11-19.md).

## ¿Por qué un sitio aparte?

Las pruebas crean y borran clientes, órdenes, facturas y turnos de caja. Si se corren en `development`, mezclan datos de prueba con los datos de trabajo. Un sitio separado (`test_restaurant`) se puede borrar y volver a crear cuando sea necesario.

## Requisitos

- Entorno Docker de `frappe_docker14` levantado (contenedor `frappe_docker14_devcontainer-frappe-1` en ejecución).
- Terminal de WSL (o la terminal de VS Code dentro del DevContainer).
- La contraseña root de MariaDB: está en `.devcontainer/docker-compose.yml`, variable `MYSQL_ROOT_PASSWORD`. **No la copies en documentos ni en commits.**

Para comprobar que el contenedor está corriendo:

```bash
docker ps --filter name=frappe_docker14_devcontainer-frappe-1
```

## Paso 1. Arreglo de SSL de MariaDB (una vez por reinicio del contenedor)

El cliente `mysql` del contenedor (MariaDB 11.8) exige conexión SSL, pero el servidor no la ofrece. Síntoma: `ERROR 2026 (HY000): TLS/SSL error: SSL is required, but the server does not support it`.

Solución sin tocar la configuración del usuario: un archivo temporal en `/tmp` del contenedor, que se activa con la variable `MYSQL_HOME`.

```bash
docker exec frappe_docker14_devcontainer-frappe-1 bash -lc 'mkdir -p /tmp/leaf_mycnf && printf "[client]\nskip-ssl\n" > /tmp/leaf_mycnf/my.cnf'
```

Todos los comandos siguientes llevan `-e MYSQL_HOME=/tmp/leaf_mycnf`.

## Paso 2. Crear el sitio de pruebas (solo la primera vez)

Entra al contenedor:

```bash
docker exec -it -e MYSQL_HOME=/tmp/leaf_mycnf -w /workspace/development/frappe-bench frappe_docker14_devcontainer-frappe-1 bash
```

Dentro del contenedor, crea el sitio. Reemplaza `<ROOT_DB>` por la contraseña root de MariaDB y `<ADMIN>` por cualquier contraseña para Administrator:

```bash
bench new-site test_restaurant --mariadb-root-password '<ROOT_DB>' --admin-password '<ADMIN>' --no-mariadb-socket
```

Instala las apps **en este orden**. Restaurante usa código de POS Awesome, así que también hay que instalarla:

```bash
bench --site test_restaurant install-app erpnext
bench --site test_restaurant install-app posawesome
bench --site test_restaurant install-app restaurant
```

Activa las pruebas y ejecuta la preparación nativa de ERPNext, que completa el asistente de configuración y crea la empresa "Wind Power LLC":

```bash
bench --site test_restaurant set-config allow_tests true
bench --site test_restaurant execute erpnext.setup.utils.before_tests
```

Verificación: `bench --site test_restaurant list-apps` debe mostrar `frappe`, `erpnext`, `posawesome` y `restaurant`.

> `bench new-site` **no** cambia el sitio por defecto. `development` sigue siendo el sitio que abre el navegador.

## Paso 3. Ejecutar las pruebas

Desde WSL (fuera del contenedor). Tarda unos 6 minutos:

```bash
docker exec -e MYSQL_HOME=/tmp/leaf_mycnf -w /workspace/development/frappe-bench frappe_docker14_devcontainer-frappe-1 bash -lc 'bench --site test_restaurant run-tests --app restaurant --skip-before-tests --skip-test-records'
```

Para correr un solo archivo de pruebas, por ejemplo `test_kds`:

```bash
docker exec -e MYSQL_HOME=/tmp/leaf_mycnf -w /workspace/development/frappe-bench frappe_docker14_devcontainer-frappe-1 bash -lc 'bench --site test_restaurant run-tests --module restaurant.tests.test_kds --skip-before-tests --skip-test-records'
```

### ¿Por qué `--skip-test-records`?

Sin esa opción la suite se detiene antes de empezar, con `TypeError: sequence item 1: expected str instance, NoneType found` en `erpnext/accounts/utils.py`. La causa es un ciclo de dependencias de prueba: **Company → POS Offer → Brand → Account**. POS Awesome agrega a `Company` los campos `posa_customer_offer` y `posa_primary_offer`, que enlazan a `POS Offer`. No es un defecto del módulo Restaurante.

Con `--skip-test-records`, Frappe no crea los registros `_Test …` de ERPNext. Los datos que necesita la suite los crea `restaurant/tests/fixtures.py`.

## Cómo funcionan los datos base (`restaurant/tests/fixtures.py`)

La función `ensure_restaurant_test_baseline()` se llama al inicio de `setUp` en `test_invoice_stock`, `test_kds`, `test_pos_auth`, `test_pos_startup` y `test_qa_comprehensive_audit`. **Solo crea lo que falta y nunca modifica registros existentes.** En `development` no hace nada.

En un sitio limpio crea:

| Registro | Valor |
| :--- | :--- |
| Cliente | Consumidor Final |
| Medios de pago | Efectivo (Cash), Transferencia bancaria (Bank), con sus cuentas |
| Cuenta bancaria | Banco QA Restaurante |
| POS Profile | QA Restaurante, serie SAR de prueba `000-099-01-.########` |
| CAI | QA-RESTAURANTE-BASELINE (solo de prueba, sin validez fiscal) |
| Etapas de preparación | Preparación, Entrega, Completado |

Si una prueba nueva necesita otro dato base, agrégalo en este archivo en lugar de depender de los datos de `development`.

## Cómo leer el resultado

Al final de la ejecución aparece algo como:

```
Ran 246 tests in 369.384s
FAILED (failures=4, errors=6, skipped=10)
```

| Término | Significado |
| :--- | :--- |
| `failures` | La prueba corrió, pero el resultado no fue el esperado |
| `errors` | La prueba se interrumpió por una excepción |
| `skipped` | La prueba se saltó a propósito porque falta una condición |

Compara siempre contra la línea base vigente. Una prueba que pasaba y ahora falla después de tu cambio es una **regresión** y hay que revisarla antes de hacer commit.

## Problemas frecuentes

| Síntoma | Solución |
| :--- | :--- |
| `TLS/SSL error: SSL is required` | Repetir el Paso 1 y usar `-e MYSQL_HOME=/tmp/leaf_mycnf` |
| `TypeError: sequence item 1 … NoneType` al iniciar | Falta `--skip-test-records` |
| `Company _Test Company not found` | Falta `--skip-test-records` |
| `Testing only allowed if allow_tests is set` | `bench --site test_restaurant set-config allow_tests true` |
| No hay empresa en el sitio | `bench --site test_restaurant execute erpnext.setup.utils.before_tests` |
| El sitio quedó dañado | Borrarlo y repetir el Paso 2: `bench drop-site test_restaurant --root-password '<ROOT_DB>' --no-backup` |
