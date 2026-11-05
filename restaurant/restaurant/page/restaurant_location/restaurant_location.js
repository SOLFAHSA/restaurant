frappe.pages["restaurant-location"].on_page_load = function (wrapper) {
    wrapper.restaurant_location = new RestaurantLocationPage(wrapper);
};

frappe.pages["restaurant-location"].on_page_show = function (wrapper) {
    wrapper.restaurant_location.show();
};

class RestaurantLocationPage {
    constructor(wrapper) {
        this.wrapper = wrapper;
        $(wrapper).addClass("restaurant-location-page");
        this.page = frappe.ui.make_app_page({ parent: wrapper, title: "Áreas", single_column: true });
        this.root = $(frappe.render_template("restaurant_location")).appendTo(this.page.body)[0];
        this.controls = {};
        this.dirty = false;
        this.requestId = 0;
        this.searchRequestId = 0;
        this.searchTimer = null;
        window.addEventListener("beforeunload", (event) => {
            if (this.dirty && this.wrapper.style.display !== "none") {
                event.preventDefault();
                event.returnValue = "";
            }
        });
        this.root.addEventListener("click", (event) => this.handleClick(event));
    }

    escape(value) {
        return frappe.utils.escape_html(String(value == null ? "" : value));
    }

    symbol(kind) {
        const paths = {
            back: '<path d="M19 12H5m6-6-6 6 6 6"/>',
            check: '<path d="m5 12 4 4L19 6"/>',
            plus: '<path d="M12 5v14M5 12h14"/>',
            image: '<rect x="3" y="3" width="18" height="18" rx="3"/><circle cx="8" cy="8" r="1.5"/><path d="m3 17 5-5 4 4 4-6 5 7"/>',
            icon: '<rect x="4" y="4" width="16" height="16" rx="3"/><path d="M8 8h8M8 12h8M8 16h4"/>',
            people: '<circle cx="9" cy="7" r="3"/><path d="M3 20v-3a6 6 0 0 1 12 0v3M16 4a3 3 0 0 1 0 6m2 4a5 5 0 0 1 3 4v2"/>',
            terrace: '<path d="M3 9 12 3l9 6H3Zm9-6v14M6 21l1-6m10 6-1-6M4 15h16M5 11v4m14-4v4M9 21v-4h6v4"/>',
            dining: '<path d="M4 8h16v9H4zM7 4v4m10-4v4M7 17v4m10-4v4M1 11h3m16 0h3M1 15h3m16 0h3"/>',
            bar: '<path d="M3 4h18l-9 9-9-9Zm9 9v7m-5 1h10M7 8h10"/>',
            garden: '<path d="M12 21V10m0 6C5 17 2 12 3 7c6-1 10 3 9 9Zm0-3C12 6 16 2 22 3c1 6-3 10-10 10Z"/>',
            map: '<polygon points="3 6 9 3 15 6 21 3 21 18 15 21 9 18 3 21"/><line x1="9" y1="3" x2="9" y2="18"/><line x1="15" y1="6" x2="15" y2="21"/>',
            edit: '<path d="M12 20h9"/><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4Z"/>',
            trash: '<path d="M3 6h18"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/>',
        };
        return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths[kind] || paths.terrace}</svg>`;
    }

    iconKey(value) {
        return { "Terraza": "terrace", "Salón": "dining", "Barra": "bar", "Jardín": "garden" }[value] || "terrace";
    }
    floorPlan() {
        return `<svg viewBox="0 0 600 310" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Ilustración de referencia de un área de restaurante">
          <defs><pattern id="ra-floor" width="32" height="32" patternUnits="userSpaceOnUse"><rect width="32" height="32" fill="#dfcba5"/><path d="M0 0H32V32" fill="none" stroke="#cbb68e" stroke-width="1"/><path d="M4 7h22M5 23h15" stroke="#ead8b8" opacity=".5"/></pattern><filter id="ra-shadow"><feDropShadow dx="0" dy="3" stdDeviation="3" flood-color="#4e412e" flood-opacity=".22"/></filter><g id="ra-chair"><rect x="-11" y="-9" width="22" height="18" rx="4" fill="#696552"/><path d="M-8-6H8" stroke="#91876b" stroke-width="2"/></g><g id="ra-round"><use href="#ra-chair" x="0" y="-43"/><use href="#ra-chair" x="0" y="43"/><use href="#ra-chair" transform="translate(-43 0) rotate(90)"/><use href="#ra-chair" transform="translate(43 0) rotate(90)"/><circle r="36" fill="#c89e57"/><circle r="32" fill="#ddb875"/><circle r="28" fill="none" stroke="#e7c892" opacity=".7"/></g><g id="ra-square"><use href="#ra-chair" x="-18" y="-40"/><use href="#ra-chair" x="18" y="-40"/><use href="#ra-chair" x="-18" y="40"/><use href="#ra-chair" x="18" y="40"/><use href="#ra-chair" transform="translate(-42 0) rotate(90)"/><use href="#ra-chair" transform="translate(42 0) rotate(90)"/><rect x="-35" y="-31" width="70" height="62" rx="4" fill="#d1a55f"/><rect x="-31" y="-27" width="62" height="54" rx="2" fill="#debb7e"/></g><g id="ra-plant"><rect x="-10" y="-8" width="20" height="24" rx="3" fill="#a18a57"/><g fill="#7c9a3c" stroke="#617d31" stroke-width="1.4"><ellipse rx="8" ry="17" transform="rotate(0)"/><ellipse rx="8" ry="17" transform="rotate(60)"/><ellipse rx="8" ry="17" transform="rotate(120)"/></g><circle r="6" fill="#9eb447"/></g></defs>
          <rect width="600" height="310" fill="url(#ra-floor)"/><rect x="8" y="8" width="584" height="294" rx="3" fill="none" stroke="#ad9369" stroke-width="8"/>
          <g filter="url(#ra-shadow)"><use href="#ra-round" x="162" y="84"/><use href="#ra-round" transform="translate(453 79) scale(.82)"/><use href="#ra-square" x="103" y="210"/><use href="#ra-square" x="506" y="210"/><g transform="translate(300 246)"><use href="#ra-chair" x="-37" y="-43"/><use href="#ra-chair" x="0" y="-43"/><use href="#ra-chair" x="37" y="-43"/><use href="#ra-chair" x="-37" y="43"/><use href="#ra-chair" x="0" y="43"/><use href="#ra-chair" x="37" y="43"/><rect x="-65" y="-32" width="130" height="64" rx="4" fill="#d1a15b"/><rect x="-60" y="-27" width="120" height="54" rx="3" fill="#ddb577"/></g><rect x="267" y="12" width="100" height="33" rx="3" fill="#ac8d54"/><use href="#ra-plant" x="283" y="25"/><use href="#ra-plant" x="315" y="25"/><use href="#ra-plant" x="347" y="25"/><use href="#ra-plant" x="30" y="31"/><use href="#ra-plant" x="30" y="90"/><use href="#ra-plant" x="30" y="147"/><use href="#ra-plant" x="32" y="277"/><use href="#ra-plant" x="565" y="30"/><use href="#ra-plant" x="570" y="215"/><use href="#ra-plant" x="570" y="275"/><use href="#ra-plant" x="421" y="278"/></g>
        </svg>`;
    }

    async show() {
        const currentId = ++this.requestId;
        clearTimeout(this.searchTimer);
        this.searchRequestId++;
        this.dirty = false;
        this.loading = true;
        this.root.innerHTML = '<div class="ra-loading" role="status">Cargando áreas…</div>';
        const route = frappe.get_route();
        const name = route[1] && route[1] !== "new" ? route[1] : null;
        try {
            const response = await frappe.call({ method: "restaurant.location.get_editor_context", args: { name, for_list: route[1] ? 0 : 1 } });
            if (currentId !== this.requestId) return;
            this.context = response.message;
            this.doc = { ...this.context.doc };
            if (!route[1]) await this.renderList(currentId);
            else await this.renderEditor();
        } catch (error) {
            if (currentId === this.requestId) this.root.innerHTML = '<div class="ra-error" role="alert">No fue posible cargar esta área. Comprueba tus permisos e inténtalo nuevamente.</div>';
        } finally {
            if (currentId === this.requestId) this.loading = false;
        }
    }

    async renderList(requestId) {
        this.listSearch = "";
        this.pageStart = 0;
        this.pageLength = 12;
        this.hasNext = false;
        this.root.innerHTML = `<header class="ra-toolbar"><div class="ra-heading"><button class="ra-button ra-back" data-action="workspace" aria-label="Volver al restaurante">${this.symbol("back")}</button><div><h1>Áreas</h1><p>Organiza los espacios de atención de tu restaurante.</p></div></div>${this.context.can_create ? `<button class="ra-button ra-button-primary" data-action="new">${this.symbol("plus")} Nueva área</button>` : ""}</header><div class="ra-list-tools"><input class="form-control ra-list-search" type="search" maxlength="140" placeholder="Buscar área o sucursal" aria-label="Buscar área o sucursal"/><label class="ra-page-size">Por página <select class="form-control" aria-label="Áreas por página"><option value="12">12</option><option value="24">24</option><option value="48">48</option></select></label></div><div class="ra-location-grid" aria-busy="true"></div><nav class="ra-pagination" aria-label="Paginación de áreas"><span data-page-range role="status" aria-live="polite"></span><div class="ra-pagination-actions"><button class="ra-button" data-action="previous-page" disabled>Anterior</button><button class="ra-button" data-action="next-page" disabled>Siguiente</button></div></nav>`;
        const searchInput = this.root.querySelector(".ra-list-search");
        searchInput.addEventListener("input", () => {
            this.listSearch = searchInput.value.trim();
            this.queueListPage(0, 300);
        });
        searchInput.addEventListener("keydown", (event) => {
            if (event.key === "Enter") {
                event.preventDefault();
                this.listSearch = searchInput.value.trim();
                this.queueListPage(0);
            }
        });
        this.root.querySelector(".ra-page-size select").addEventListener("change", (event) => {
            this.pageLength = Number(event.target.value);
            this.queueListPage(0);
        });
        await this.loadListPage(0, requestId, ++this.searchRequestId);
    }

    isCurrentList(requestId, searchRequestId) {
        const route = frappe.get_route();
        return requestId === this.requestId && searchRequestId === this.searchRequestId && route[0] === "restaurant-location" && !route[1] && Boolean(this.root.querySelector(".ra-location-grid"));
    }

    queueListPage(start, delay = 0) {
        clearTimeout(this.searchTimer);
        const requestId = this.requestId;
        const searchRequestId = ++this.searchRequestId;
        this.pageStart = start;
        this.setListLoading();
        if (delay) this.searchTimer = setTimeout(() => this.loadListPage(start, requestId, searchRequestId), delay);
        else this.loadListPage(start, requestId, searchRequestId);
    }

    setListLoading() {
        this.listLoading = true;
        this.hasNext = false;
        const target = this.root.querySelector(".ra-location-grid");
        if (!target) return;
        target.setAttribute("aria-busy", "true");
        target.innerHTML = '<div class="ra-loading" role="status">Cargando áreas…</div>';
        this.root.querySelector("[data-page-range]").textContent = "Cargando…";
        this.updateListNavigation();
    }

    async loadListPage(start, requestId, searchRequestId) {
        if (!this.isCurrentList(requestId, searchRequestId)) return;
        const search = this.listSearch;
        const pageLength = this.pageLength;
        this.pageStart = start;
        this.setListLoading();
        try {
            const result = await frappe.call({ method: "restaurant.location.get_locations", args: { search, start, page_length: pageLength } });
            if (!this.isCurrentList(requestId, searchRequestId)) return;
            this.locations = result.message.items;
            this.hasNext = Boolean(result.message.has_next);
            this.pageStart = result.message.start;
            this.pageLength = result.message.page_length;
            this.drawList();
            this.root.querySelector("[data-page-range]").textContent = this.locations.length
                ? `Mostrando ${this.pageStart + 1}–${this.pageStart + this.locations.length}`
                : (this.pageStart ? "Sin resultados en esta página" : "No hay resultados");
        } catch (error) {
            if (!this.isCurrentList(requestId, searchRequestId)) return;
            this.locations = [];
            this.hasNext = false;
            this.root.querySelector(".ra-location-grid").innerHTML = '<div class="ra-error" role="alert">No fue posible cargar las áreas. Comprueba tu conexión o tus permisos.<p><button class="ra-button" data-action="retry-list">Reintentar</button></p></div>';
            this.root.querySelector("[data-page-range]").textContent = "No se pudo cargar la página";
        } finally {
            if (this.isCurrentList(requestId, searchRequestId)) {
                this.listLoading = false;
                this.root.querySelector(".ra-location-grid").setAttribute("aria-busy", "false");
                this.updateListNavigation();
            }
        }
    }

    updateListNavigation() {
        const previous = this.root.querySelector('[data-action="previous-page"]');
        const next = this.root.querySelector('[data-action="next-page"]');
        if (previous) previous.disabled = this.listLoading || this.pageStart === 0;
        if (next) next.disabled = this.listLoading || !this.hasNext;
    }

    drawList() {
        const records = this.locations;
        const target = this.root.querySelector(".ra-location-grid");
        if (!records.length) {
            const laterPage = this.pageStart > 0;
            const title = laterPage ? "No hay áreas en esta página" : (this.listSearch ? "No se encontraron áreas" : "Aún no hay áreas");
            const hint = laterPage ? "Regresa a la página anterior para consultar las áreas disponibles." : (this.listSearch ? "Prueba con otro nombre o sucursal." : "Crea tu primera área para organizar los espacios del restaurante.");
            target.innerHTML = `<div class="ra-empty-list">${this.symbol("terrace")}<h2>${title}</h2><p>${hint}</p>${!laterPage && !this.listSearch && this.context.can_create ? '<button class="ra-button ra-button-primary" data-action="new">Crear área</button>' : ""}</div>`;
            const emptyIcon = target.querySelector("svg");
            if (emptyIcon) { emptyIcon.style.width = "48px"; emptyIcon.style.height = "48px"; emptyIcon.style.color = "#3b78ff"; }
            return;
        }
        target.innerHTML = records.map((record) => `<button class="ra-location-card" data-name="${this.escape(record.name)}"><span class="ra-list-icon">${this.symbol(this.iconKey(record.icon))}</span><span><strong>${this.escape(record.area_name)}</strong><small>${this.escape(record.branch)} · ${Number(record.capacity) || 0} personas</small><small class="ra-list-status ${record.status === "Inactiva" ? "is-inactive" : ""}">${this.escape(record.status || "Activa")}</small></span></button>`).join("");
    }

    async renderEditor() {
        this.controls = {};
        const isNew = !this.doc.name || this.doc.__islocal;
        this.editable = Boolean(isNew ? this.context.can_create : this.context.can_write);
        const tablesCount = (this.context.tables || []).length;
        this.root.innerHTML = `<header class="ra-toolbar"><div class="ra-heading"><button class="ra-button ra-back" data-action="cancel" aria-label="Volver a áreas">${this.symbol("back")}</button><h1>${isNew ? "Nueva área" : this.escape(this.doc.area_name)}</h1><span class="ra-badge ${isNew ? "" : "ra-badge-saved"}" data-status>${isNew ? "Sin guardar" : "Guardada"}</span></div><div class="ra-actions"><button class="ra-button" data-action="cancel">Cancelar</button>${!isNew ? `<button class="ra-button" data-action="open-table-map">${this.symbol("map")} Mapa de mesas</button>` : ""}${this.editable ? `<button class="ra-button ra-button-primary" data-action="save">${this.symbol("check")} Guardar área</button>` : ""}</div></header>${this.editable ? "" : '<p class="ra-readonly-note">Tienes permiso de lectura. Esta área se muestra sin opciones de edición.</p>'}
        <section class="ra-card"><header class="ra-card-header"><div><h2>Información del área</h2><p>Define el salón o espacio del restaurante y visualiza su distribución de mesas.</p></div><span class="ra-required-note">* Campos obligatorios</span></header><div class="ra-info-layout"><div class="ra-field-grid"><div class="ra-field-wide" data-field="area_name"></div><div data-field="branch"></div><div data-field="capacity"></div><div data-field="status"></div><div data-field="icon"></div><div data-field="floor_background"></div><div data-field="display_order"></div><div class="ra-field-wide" data-field="visible_in_pos"></div><div class="ra-field-wide" data-field="description"></div></div>
        <aside class="ra-preview-card"><div class="ra-preview-top"><div><h3>Plano de mesas del área</h3><p data-preview-summary>${isNew ? "Guarda el área para diseñar su plano y asignar mesas." : `${tablesCount} ${tablesCount === 1 ? "mesa vinculada" : "mesas vinculadas"}`}</p></div><span class="ra-icon-badge" data-preview-icon title="Icono de tarjeta"></span></div><div class="ra-preview"><div class="ra-preview-art"></div><div class="ra-preview-label"><strong data-preview-name></strong><span>${this.symbol("people")} <span data-preview-capacity></span></span></div></div><div class="ra-preview-footer">${!isNew ? `<button type="button" class="ra-button ra-button-primary" style="width:100%" data-action="open-table-map">${this.symbol("map")} Diseñar en Mapa de Mesas</button>` : `<p class="ra-hint" style="margin:0;text-align:center">Al guardar el área se habilitará el diseñador interactivo del Mapa de Mesas.</p>`}</div></aside></div></section>
        <section class="ra-card"><header class="ra-card-header"><div><h2>Mesas vinculadas</h2><p data-tables-subtitle>Mesas que pertenecen a esta área (${tablesCount}).</p></div><div class="ra-actions">${!isNew ? `<button class="ra-button" data-action="open-table-map">${this.symbol("map")} Abrir mapa de mesas</button>` : ""}${!isNew && this.context.can_create_table ? `<button class="ra-button ra-button-primary" data-action="add-table">${this.symbol("plus")} Agregar mesa</button>` : `<button class="ra-button" disabled title="${isNew ? "Guarda el área primero para vincular mesas" : "Sin permisos para crear mesas"}">${this.symbol("plus")} Agregar mesa</button>`}</div></header><div class="ra-table-wrapper"><table class="ra-table"><thead><tr><th>N.°</th><th>Mesa</th><th>Capacidad</th><th>Tipo</th><th>Estado</th><th style="text-align:right">Acciones</th></tr></thead><tbody data-tables-body>${this.renderTablesRows(isNew)}</tbody></table></div></section>`;
        // Numeric text controls avoid the native integer control focus timeout.
        // The DocType and server remain responsible for integer validation.
        const definitions = [
            ["area_name", "Data", "Nombre del área", { reqd: 1 }],
            ["branch", "Link", "Sucursal", { reqd: 1, options: "Branch" }],
            ["capacity", "Data", "Capacidad estimada (personas)", { reqd: 1, description: "Aforo total aproximado de esta área." }],
            ["status", "Select", "Estado", { reqd: 1, options: "Activa\nInactiva" }],
            ["icon", "Select", "Tipo de espacio (icono)", { reqd: 1, options: "Terraza\nSalón\nBarra\nJardín", description: "Icono que identifica al área en el listado." }],
            ["floor_background", "Select", "Fondo del piso en el mapa", { reqd: 1, options: "Madera cálida\nCerámica clara\nMadera gris\nCésped" }],
            ["display_order", "Data", "Orden de visualización", { description: "Los números menores aparecen primero." }],
            ["visible_in_pos", "Check", "Visible en Punto de Venta (POS)", { description: "Mostrar esta área en la operación diaria." }],
            ["description", "Small Text", "Descripción u observaciones", { length: 500 }],
        ];
        for (const [fieldname, fieldtype, label, options] of definitions) {
            const control = frappe.ui.form.make_control({ parent: this.root.querySelector(`[data-field="${fieldname}"]`), df: { fieldname, fieldtype, label, read_only: this.editable ? 0 : 1, ...options, onchange: () => this.fieldChanged(fieldname) }, render_input: true });
            this.controls[fieldname] = control;
            if (["display_order", "capacity"].includes(fieldname)) {
                control.$input?.attr("inputmode", "numeric").attr("pattern", "[0-9]*");
            }
            if (options.length) {
                const counter = document.createElement("div");
                counter.className = "ra-counter";
                counter.dataset.counter = fieldname;
                control.wrapper.appendChild(counter);
                control.$input?.attr("maxlength", options.length).attr("rows", 2);
            }
            if (control.awesomplete?.status) control.awesomplete.status.textContent = "Escribe para buscar resultados.";
            if (control.$input) {
                const inputId = `ra-${fieldname}`;
                control.$input.attr("id", inputId).attr("aria-label", label);
                control.$wrapper.find(".control-label").attr("for", inputId);
                control.$input.on("input", () => { if (!this.loading) { this.markDirty(); this.updatePreview(); } });
            }
        }
        await Promise.all(Object.entries(this.controls).map(([fieldname, control]) => control.set_value(this.doc[fieldname] == null ? "" : this.doc[fieldname])));
        this.updatePreview();
    }

    fieldChanged(fieldname) {
        if (this.loading || !this.controls[fieldname]) return;
        this.doc[fieldname] = this.controls[fieldname].get_value();
        this.markDirty();
        this.updatePreview();
    }

    markDirty() {
        if (!this.editable) return;
        this.dirty = true;
        const badge = this.root.querySelector("[data-status]");
        if (badge) { badge.textContent = "Sin guardar"; badge.classList.remove("ra-badge-saved"); }
    }

    inputValue(fieldname) {
        const control = this.controls[fieldname];
        return control?.$input ? control.$input.val() : this.doc[fieldname];
    }

    liveAreaMiniMap() {
        const tables = this.context?.tables || [];
        const bg = this.inputValue("floor_background") || this.doc.floor_background || "Madera cálida";
        const palette = {
            "Madera cálida": { fill: "#d9b98e", stroke: "#c49e6c" },
            "Cerámica clara": { fill: "#efe9de", stroke: "#dcd3c2" },
            "Madera gris": { fill: "#d4d8dd", stroke: "#b8c0cc" },
            "Césped": { fill: "#2f7d20", stroke: "#256619" },
        }[bg] || { fill: "#d9b98e", stroke: "#c49e6c" };

        if (!tables.length) {
            return `<svg viewBox="0 0 600 310" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Plano del área sin mesas">
                <rect width="600" height="310" fill="${palette.fill}"/>
                <rect x="10" y="10" width="580" height="290" rx="6" fill="none" stroke="${palette.stroke}" stroke-width="4" stroke-dasharray="8 6"/>
            </svg>`;
        }

        const cols = Math.min(4, Math.max(2, Math.ceil(Math.sqrt(tables.length))));
        const rows = Math.ceil(tables.length / cols);
        const cellW = 540 / cols;
        const cellH = 260 / rows;

        const shapesSvg = tables.map((row, idx) => {
            const col = idx % cols;
            const r = Math.floor(idx / cols);
            const cx = Math.round(30 + col * cellW + cellW / 2);
            const cy = Math.round(25 + r * cellH + cellH / 2);
            const statusColors = {
                "Disponible": { fill: "#22c55e", text: "#ffffff" },
                "Ocupada": { fill: "#15803d", text: "#ffffff" },
                "Reservada": { fill: "#ef4444", text: "#ffffff" },
                "Inactiva": { fill: "#64748b", text: "#ffffff" },
            }[row.status] || { fill: "#22c55e", text: "#ffffff" };
            const isRound = row.shape === "Redonda";
            const isWide = row.shape === "Rectangular" || row.shape === "Ovalada";
            const w = isWide ? 88 : 66;
            const h = 58;
            const rx = isRound ? 29 : (row.shape === "Ovalada" ? 26 : 8);
            return `<g transform="translate(${cx},${cy})">
                <rect x="${-w / 2}" y="${-h / 2}" width="${w}" height="${h}" rx="${rx}" fill="${statusColors.fill}" fill-opacity="0.88" stroke="#ffffff" stroke-width="2"/>
                <text x="0" y="-2" text-anchor="middle" fill="${statusColors.text}" font-size="13" font-weight="700" font-family="sans-serif">M-${this.escape(row.table_number)}</text>
                <text x="0" y="14" text-anchor="middle" fill="${statusColors.text}" font-size="10" font-family="sans-serif">${Number(row.seats) || 4}p · ${this.escape(row.status)}</text>
            </g>`;
        }).join("");

        return `<svg viewBox="0 0 600 310" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Plano de mesas del área">
            <rect width="600" height="310" fill="${palette.fill}"/>
            <rect x="8" y="8" width="584" height="294" rx="5" fill="none" stroke="${palette.stroke}" stroke-width="6"/>
            ${shapesSvg}
        </svg>`;
    }

    updatePreview() {
        const name = this.root.querySelector("[data-preview-name]");
        if (!name) return;
        const tables = this.context?.tables || [];
        name.textContent = this.inputValue("area_name") || "Nueva área";
        this.root.querySelector("[data-preview-capacity]").textContent = `${Number(this.inputValue("capacity")) || 0} personas`;
        const iconHolder = this.root.querySelector("[data-preview-icon]");
        if (iconHolder) iconHolder.innerHTML = this.symbol(this.iconKey(this.inputValue("icon") || this.doc.icon));
        const preview = this.root.querySelector(".ra-preview-art");
        if (preview) {
            preview.innerHTML = this.liveAreaMiniMap();
            preview.style.cssText = "width:100%;height:100%";
        }
        const labelOverlay = this.root.querySelector(".ra-preview-label");
        if (labelOverlay) {
            labelOverlay.style.display = tables.length ? "none" : "flex";
        }
        const summary = this.root.querySelector("[data-preview-summary]");
        if (summary && this.doc.name && !this.doc.__islocal) {
            const avail = tables.filter((t) => t.status === "Disponible").length;
            summary.textContent = `${tables.length} ${tables.length === 1 ? "mesa vinculada" : "mesas vinculadas"} · ${avail} disponibles`;
        }
        const sub = this.root.querySelector("[data-tables-subtitle]");
        if (sub) {
            sub.textContent = `Mesas que pertenecen a esta área (${tables.length}).`;
        }
        for (const fieldname of ["description"]) {
            const counter = this.root.querySelector(`[data-counter="${fieldname}"]`);
            if (counter) counter.textContent = `${String(this.inputValue(fieldname) || "").length} / 500`;
        }
        this.root.querySelectorAll(".ra-preview-label svg").forEach((svg) => { svg.style.width = "12px"; svg.style.height = "12px"; svg.style.verticalAlign = "middle"; });
    }

    async save() {
        if (this.saving || !this.editable) return;
        const values = { ...this.doc };
        let missing = false;
        for (const [fieldname, control] of Object.entries(this.controls)) {
            const value = control.get_value();
            values[fieldname] = value;
            if (control.df.reqd && (value === "" || value == null)) {
                control.$wrapper.addClass("has-error");
                missing = true;
            } else control.$wrapper.removeClass("has-error");
        }
        if (missing) { frappe.msgprint("Completa los campos obligatorios antes de guardar."); return; }
        for (const fieldname of ["display_order", "capacity"]) {
            const rawValue = String(values[fieldname] == null ? "" : values[fieldname]).trim();
            const normalizedValue = fieldname === "display_order" && rawValue === "" ? "0" : rawValue;
            const numberValue = Number(normalizedValue);
            if (!/^\d+$/.test(normalizedValue) || !Number.isSafeInteger(numberValue) || (fieldname === "capacity" && numberValue < 1)) {
                this.controls[fieldname].$wrapper.addClass("has-error");
                frappe.msgprint(fieldname === "capacity" ? "La capacidad debe ser un número entero mayor que cero." : "El orden de visualización debe ser un número entero igual o mayor que cero.");
                return;
            }
            values[fieldname] = numberValue;
        }
        this.saving = true;
        const button = this.root.querySelector('[data-action="save"]');
        if (button) { button.disabled = true; button.textContent = "Guardando…"; }
        try {
            const result = await frappe.call({ method: "restaurant.location.save_location", args: { document: JSON.stringify(values) }, freeze: true, freeze_message: "Guardando área…" });
            this.doc = result.message;
            this.dirty = false;
            frappe.show_alert({ message: "Área guardada", indicator: "green" });
            const destination = ["restaurant-location", this.doc.name];
            if (frappe.get_route()[1] === this.doc.name) await this.show();
            else frappe.set_route(...destination);
        } catch (error) {
            // Frappe displays the server validation message and preserves the editor.
        } finally {
            this.saving = false;
            if (button?.isConnected) { button.disabled = false; button.innerHTML = `${this.symbol("check")} Guardar área`; }
        }
    }

    selectIcon() {
        const choices = [["Terraza", "Terraza"], ["Salón", "Salón"], ["Barra", "Barra"], ["Jardín", "Jardín"]];
        const dialog = new frappe.ui.Dialog({ title: "Seleccionar icono", fields: [{ fieldname: "icons", fieldtype: "HTML" }] });
        dialog.fields_dict.icons.$wrapper.html(`<div class="ra-icon-picker">${choices.map(([value, label]) => `<button type="button" class="ra-icon-option" data-icon="${value}" aria-label="${label}">${this.symbol(this.iconKey(value))}<span>${label}</span></button>`).join("")}</div>`);
        dialog.fields_dict.icons.$wrapper.on("click", "[data-icon]", (event) => {
            this.doc.icon = event.currentTarget.dataset.icon;
            this.markDirty();
            this.updatePreview();
            dialog.hide();
        });
        dialog.show();
    }

    changeImage() {
        const isSaved = this.doc.name && !this.doc.__islocal;
        new frappe.ui.FileUploader({
            doctype: isSaved ? "Restaurant Area" : undefined,
            docname: isSaved ? this.doc.name : undefined,
            fieldname: isSaved ? "image" : undefined,
            dialog_title: "Cambiar imagen del área",
            allow_multiple: false,
            restrictions: { allowed_file_types: [".jpg", ".jpeg", ".png", ".webp"], max_file_size: 5 * 1024 * 1024 },
            on_success: (file) => { this.doc.image = file.file_url; this.markDirty(); this.updatePreview(); },
        });
    }

    confirmLeave(destination) {
        const leave = () => { this.dirty = false; frappe.set_route(...destination); };
        if (this.dirty) frappe.confirm("Tienes cambios sin guardar. ¿Deseas descartarlos?", leave);
        else leave();
    }

    renderTablesRows(isNew = false) {
        const tables = this.context?.tables || [];
        if (isNew) {
            return `<tr><td class="ra-empty-cell" colspan="6">Guarda el área primero<p>Una vez guardada el área podrás agregar y diseñar sus mesas.</p></td></tr>`;
        }
        if (!tables.length) {
            return `<tr><td class="ra-empty-cell" colspan="6">Sin mesas vinculadas<p>Usa el botón «Agregar mesa» o abre el «Mapa de mesas» para diseñar el salón.</p></td></tr>`;
        }
        const statusClass = (status) => ({
            "Disponible": "is-available",
            "Ocupada": "is-occupied",
            "Reservada": "is-reserved",
            "Inactiva": "is-inactive",
        }[status] || "is-available");
        return tables.map((row, index) => `
            <tr>
                <td>${index + 1}</td>
                <td><span class="ra-table-dot" style="background:${this.escape(row.color || "#22C55E")}"></span><strong>Mesa ${this.escape(row.table_number)}</strong></td>
                <td>${Number(row.seats) || 4} asientos</td>
                <td>${this.escape(row.shape || "Cuadrada")}</td>
                <td><span class="ra-status-pill ${statusClass(row.status)}">${this.escape(row.status || "Disponible")}</span></td>
                <td style="text-align:right">
                    <div class="ra-row-actions">
                        ${this.context.can_write_table ? `<button type="button" class="ra-button ra-button-sm" data-action="edit-table" data-table="${this.escape(row.name)}">${this.symbol("edit")} Editar</button>` : ""}
                        ${this.context.can_delete_table ? `<button type="button" class="ra-button ra-button-sm ra-button-danger" data-action="delete-table" data-table="${this.escape(row.name)}">${this.symbol("trash")}</button>` : ""}
                    </div>
                </td>
            </tr>
        `).join("");
    }

    openTableDialog(existing = null) {
        if (!this.doc?.name || this.doc.__islocal) {
            frappe.msgprint("Guarda el área antes de agregar mesas.");
            return;
        }
        const tables = this.context?.tables || [];
        const nextNumber = existing ? existing.table_number : String(tables.length + 1);
        const dialog = new frappe.ui.Dialog({
            title: existing ? `Editar Mesa ${existing.table_number}` : "Agregar mesa al área",
            fields: [
                {
                    fieldname: "table_number",
                    fieldtype: "Data",
                    label: "Número o código de mesa",
                    reqd: 1,
                    default: nextNumber,
                },
                {
                    fieldname: "seats",
                    fieldtype: "Int",
                    label: "Capacidad (asientos)",
                    reqd: 1,
                    default: existing ? existing.seats : 4,
                },
                {
                    fieldname: "shape",
                    fieldtype: "Select",
                    label: "Forma / Tipo",
                    reqd: 1,
                    options: "Cuadrada\nRectangular\nRedonda\nOvalada\nCancha azul\nCancha fútbol\nCancha básquetbol",
                    default: existing ? existing.shape : "Cuadrada",
                },
                {
                    fieldname: "status",
                    fieldtype: "Select",
                    label: "Estado operativo",
                    reqd: 1,
                    options: "Disponible\nOcupada\nReservada\nInactiva",
                    default: existing ? existing.status : "Disponible",
                },
                {
                    fieldname: "color",
                    fieldtype: "Color",
                    label: "Color identificador",
                    default: existing ? existing.color : (this.doc.color || "#22C55E"),
                },
                {
                    fieldname: "notes",
                    fieldtype: "Small Text",
                    label: "Observaciones",
                    default: existing ? (existing.notes || "") : "",
                },
            ],
            primary_action_label: existing ? "Guardar cambios" : "Crear mesa",
            primary_action: async (values) => {
                const payload = {
                    doctype: "Restaurant Table",
                    name: existing ? existing.name : undefined,
                    modified: existing ? existing.modified : undefined,
                    restaurant_area: this.doc.name,
                    ...values,
                };
                const res = await frappe.call({
                    method: "restaurant.table_management.save_table",
                    args: { document: payload },
                    freeze: true,
                    freeze_message: "Guardando mesa…",
                });
                if (res && res.message) {
                    this.context.tables = res.message.tables || [];
                    const tbody = this.root.querySelector("[data-tables-body]");
                    if (tbody) tbody.innerHTML = this.renderTablesRows(false);
                    this.updatePreview();
                    frappe.show_alert({ message: existing ? "Mesa actualizada" : "Mesa agregada", indicator: "green" });
                    dialog.hide();
                }
            },
        });
        dialog.show();
    }

    deleteLinkedTable(tableName) {
        const row = (this.context?.tables || []).find((item) => item.name === tableName);
        if (!row) return;
        frappe.confirm(`¿Deseas eliminar la Mesa ${this.escape(row.table_number)} de esta área?`, async () => {
            const res = await frappe.call({
                method: "restaurant.table_management.delete_table",
                args: { name: tableName },
                freeze: true,
                freeze_message: "Eliminando mesa…",
            });
            if (res && res.message) {
                this.context.tables = res.message.tables || [];
                const tbody = this.root.querySelector("[data-tables-body]");
                if (tbody) tbody.innerHTML = this.renderTablesRows(false);
                this.updatePreview();
                frappe.show_alert({ message: "Mesa eliminada", indicator: "orange" });
            }
        });
    }

    handleClick(event) {
        const location = event.target.closest("[data-name]");
        if (location) { frappe.set_route("restaurant-location", location.dataset.name); return; }
        const actionEl = event.target.closest("[data-action]");
        const action = actionEl?.dataset.action;
        if (action === "previous-page" && !this.listLoading && this.pageStart > 0) { this.queueListPage(Math.max(0, this.pageStart - this.pageLength)); return; }
        if (action === "next-page" && !this.listLoading && this.hasNext) { this.queueListPage(this.pageStart + this.pageLength); return; }
        if (action === "retry-list") { this.queueListPage(this.pageStart); return; }
        if (action === "new") frappe.set_route("restaurant-location", "new");
        if (action === "workspace") this.confirmLeave(["Workspaces", "Restaurante"]);
        if (action === "cancel") this.confirmLeave(["restaurant-location"]);
        if (action === "save") this.save();
        if (action === "open-table-map" && this.doc?.name) { this.confirmLeave(["restaurant-table-map", this.doc.name]); return; }
        if (action === "add-table") { this.openTableDialog(); return; }
        if (action === "edit-table") {
            const row = (this.context?.tables || []).find((item) => item.name === actionEl.dataset.table);
            if (row) this.openTableDialog(row);
            return;
        }
        if (action === "delete-table") {
            this.deleteLinkedTable(actionEl.dataset.table);
            return;
        }
        if (!this.editable) return;
        if (action === "image") this.changeImage();
        if (action === "icon") this.selectIcon();
        if (action === "remove-image") { this.doc.image = ""; this.markDirty(); this.updatePreview(); }
    }
}
