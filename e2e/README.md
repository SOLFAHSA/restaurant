# Pruebas de extremo a extremo (Playwright)

Dos pruebas con un navegador real, como las define `docs/pruebas.md`:

| Prueba | Criterio |
| :--- | :--- |
| `tests/flujo-central.spec.js` | Dado un cajero con turno abierto, cuando cobra una cuenta en efectivo, entonces ve la factura SAR emitida |
| `tests/permiso-mesero.spec.js` | Dado un mesero, cuando agrega un producto a una cuenta, entonces no ve la opción de cobrar |

Corren contra el sitio de **desarrollo o de prueba** con datos semilla, **nunca contra producción**. La prueba del cajero emite una factura real en ese sitio.

## Requisitos (una sola vez, dentro del contenedor)

```bash
cd /workspace/development/frappe-bench/apps/restaurant/e2e
npm ci
npx playwright install chromium
```

En Debian 13 el navegador necesita además `libatk-bridge2.0-0t64` y `libcups2t64` (`sudo apt-get install`).

## Ejecutar

Las contraseñas se pasan al ejecutar; nunca se guardan en el código.

```bash
E2E_CASHIER_USER=cajero.prueba@leaf.local E2E_CASHIER_PASSWORD='...' \
E2E_WAITER_USER=mesero.prueba@leaf.local E2E_WAITER_PASSWORD='...' \
npx playwright test
```

Variables opcionales: `E2E_BASE_URL` (por defecto `http://localhost:8000`) y `E2E_ITEM` (producto sin opciones; por defecto `BALEADA`). El cajero necesita un turno de caja abierto. El informe queda en `playwright-report/`.
