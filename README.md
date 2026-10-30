## Restaurant

Restaurant management module for LEAF ERP

#### License

MIT

## Página de bienvenida

La pantalla actual utiliza una plantilla Jinja de Frappe; todavía no contiene una aplicación Vue ni requiere compilar un bundle JavaScript.

- Plantilla: `restaurant/www/restaurant-welcome.html`.
- Ruta web: `/restaurant-welcome`.
- URL de desarrollo: `http://localhost:8000/restaurant-welcome`.

Los archivos de `www` se sirven mediante el enrutador web nativo de Frappe. Esta página no es una ruta de Desk bajo `/app`; registrar un módulo en `config/desktop.py` no crea una página de Desk.

### Después de instalar la app

Desde el directorio del Bench, verifica la instalación y el entorno Python:

```bash
bench --site development list-apps
env/bin/python -c "import restaurant; print(restaurant.__file__)"
bench --site development clear-cache
```

Si el servidor ya estaba iniciado al instalar la app y muestra `ModuleNotFoundError: No module named 'restaurant'`, detén y vuelve a iniciar el servidor web o la sesión **Bench Web** de VS Code. El proceso existente no incorpora automáticamente la nueva instalación editable de Python, especialmente con `--noreload`.

Usa el entorno virtual del Bench con Python 3.11.x. Ejecuta un solo servidor por puerto: detén el proceso web existente antes de iniciar otra sesión de depuración o `bench start`.

## Cambio de identificador de una instalación existente

El identificador de app, paquete Python y módulo es ahora `restaurant` / `Restaurant`.
Para un sitio que ya tenía instalada la app con el nombre anterior, respalda su base de datos antes de actualizar el código. No desinstales la app: la desinstalación puede eliminar datos.

1. Instala el paquete editable desde el directorio del Bench:
   `env/bin/python -m pip install --no-deps -e apps/restaurant`.
2. Retira la distribución anterior: `env/bin/python -m pip uninstall leaf_restaurant`.
3. En `sites/apps.txt` sustituye el identificador anterior por `restaurant`, conservando el resto de apps. Si existe `sites/apps.json`, cambia también su clave anterior a `restaurant`, preservando sus metadatos.
4. Ejecuta `env/bin/python -m restaurant.migrate_app_name --site development`.
5. Ejecuta `bench --site development migrate`, `bench build --app restaurant` y `bench --site development clear-cache`.
6. Reinicia el servidor web y los workers que estuvieran en ejecución.

El procedimiento de registro es idempotente, conserva el orden de las apps instaladas y renombra el módulo mediante la API nativa de Frappe. La ruta anterior de bienvenida redirige a `/restaurant-welcome`.
