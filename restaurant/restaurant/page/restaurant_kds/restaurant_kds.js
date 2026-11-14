/* Kitchen Display System (Cocina KDS) monitor for LEAF Restaurant (/app/restaurant-kds) */

frappe.pages["restaurant-kds"].on_page_load = function (wrapper) {
    wrapper.restaurant_kds = new LeafRestaurantKDS(wrapper);
};

frappe.pages["restaurant-kds"].on_page_show = function (wrapper) {
    wrapper.restaurant_kds.onShow();
};

class LeafRestaurantKDS {
    constructor(wrapper) {
        this.wrapper = wrapper;
        this.page = frappe.ui.make_app_page({
            parent: wrapper,
            title: "Cocina KDS",
            single_column: true,
        });
        this.page.main.empty();
        if (this.page.page_form) this.page.page_form.hide();
        $(wrapper).find(".page-head").hide();

        this.viewMode = "hub";
        this.activeStage = "Todas";
        this.selectedStation = "Todas las estaciones";
        this.stationBarOpen = false;
        this.orders = [];
        this.displays = [];
        this.selectedDisplay = null;
        this.mutating = false;
        this.stations = ["Todas las estaciones"];
        this.counts = {
            "Todas": 0,
        };
        this.inProgressCount = 0;
        this.avgWaitMinutes = 0;
        this.serverClockOffsetMs = 0;
        this.undoStack = [];
        this.loading = false;
        this.pollTimer = null;
        this.clockTimer = null;

        this.stageConfigs = [];

        this.darkMode = false;
        try {
            this.darkMode = window.localStorage?.getItem("rkds_dark_mode") === "1";
        } catch (e) {
            this.darkMode = false;
        }

        this.shell = document.createElement("div");
        this.shell.className = `rkds-shell${this.darkMode ? " is-dark-mode" : ""}`;
        this.page.main[0].appendChild(this.shell);
    }

    escape(value) {
        return frappe.utils.escape_html(String(value == null ? "" : value));
    }

    onShow() {
        const routeOptions = frappe.route_options || {};
        frappe.route_options = null;
        const allowedViews = this.isKdsManager()
            ? ["hub", "preparation", "status-screen", "config", "stages-list"]
            : ["hub", "preparation", "status-screen"];
        if (routeOptions.view && allowedViews.includes(routeOptions.view)) {
            this.viewMode = routeOptions.view;
        } else {
            this.viewMode = "hub";
        }
        if (routeOptions.display) this.selectedDisplay = routeOptions.display;
        if (routeOptions.stage) {
            this.activeStage = routeOptions.stage;
            if (!routeOptions.view) {
                this.viewMode = "preparation";
            }
        }
        if (routeOptions.station) {
            this.selectedStation = routeOptions.station;
        }
        this.startTimers();
        this.refreshOrders();
    }

    startTimers() {
        this.stopTimers();
        this.clockTimer = window.setInterval(() => {
            if (frappe.get_route()[0] !== "restaurant-kds") {
                this.stopTimers();
                return;
            }
            this.updateLiveStopwatches();
        }, 10000);

        this.pollTimer = window.setInterval(() => {
            if (frappe.get_route()[0] !== "restaurant-kds") {
                this.stopTimers();
                return;
            }
            this.refreshOrders({ silent: true });
        }, 12000);
    }

    stopTimers() {
        if (this.clockTimer) {
            window.clearInterval(this.clockTimer);
            this.clockTimer = null;
        }
        if (this.pollTimer) {
            window.clearInterval(this.pollTimer);
            this.pollTimer = null;
        }
    }

    parseTimestampMs(dtStr) {
        if (!dtStr) return Date.now();
        const normalized = String(dtStr).trim().replace(" ", "T");
        const parsed = Date.parse(normalized);
        return Number.isNaN(parsed) ? Date.now() : parsed;
    }

    computeElapsedMinutes(ord) {
        const startStr = ord.kds_timer_start || ord.sent_to_kitchen_at || ord.creation;
        if (!startStr) return Number(ord.kds_wait_minutes || 0);
        const startMs = this.parseTimestampMs(startStr);
        const nowServerMs = Date.now() + (this.serverClockOffsetMs || 0);
        const diffMins = Math.floor((nowServerMs - startMs) / 60000);
        return Math.max(0, Number.isFinite(diffMins) ? diffMins : Number(ord.kds_wait_minutes || 0));
    }

    isOrderUrgent(ord, waitMins) {
        const stage = (ord.stages || this.stageConfigs)[ord.stage_index];
        const threshold = Number(stage?.alert_minutes || 0);
        return threshold > 0 && waitMins >= threshold;
    }

    updateLiveStopwatches() {
        this.shell.querySelectorAll("[data-timer-order]").forEach(pill => {
            const ordName = pill.dataset.timerOrder;
            const ord = this.orders.find(o => pill.dataset.timerTicket ? o.ticket_name === pill.dataset.timerTicket : o.name === ordName);
            if (!ord) return;
            const mins = this.computeElapsedMinutes(ord);
            const labelEl = pill.querySelector(".rkds-timer-val");
            if (labelEl) {
                labelEl.textContent = `${mins}'`;
            }
            pill.classList.toggle("is-urgent", this.isOrderUrgent(ord, mins));
        });
    }

    async refreshOrders(options = {}) {
        if (options.silent && this.viewMode === "config") return;
        if (this.loading) return;
        this.loading = true;
        try {
            const res = await frappe.call({
                method: "restaurant.kds.get_kds_state",
                args: {
                    station: this.selectedStation,
                    display_name: this.selectedDisplay,
                },
            });
            const payload = res?.message || {};
            this.orders = Array.isArray(payload.orders) ? payload.orders : [];
            this.displays = payload.displays || [];
            this.stagesCatalog = payload.stages_catalog || [];
            this.selectedDisplay = payload.selected_display || null;
            this.stageConfigs = this.currentDisplay()?.stages || [];
            if (this.activeStage !== "Todas" && !this.stageConfigs.some(st => st.name === this.activeStage)) {
                this.activeStage = this.stageConfigs[0]?.name || "Todas";
            }
            this.stations = Array.isArray(payload.stations) && payload.stations.length
                ? payload.stations
                : ["Todas las estaciones", "Cocina General"];
            if (payload.server_now) {
                const srvMs = this.parseTimestampMs(payload.server_now);
                this.serverClockOffsetMs = srvMs - Date.now();
            }
            this.recalculateCounts();
            this.render();
        } catch (err) {
            if (!options.silent) {
                frappe.show_alert({
                    message: "No se pudieron actualizar las comandas de cocina.",
                    indicator: "orange",
                });
            }
        } finally {
            this.loading = false;
        }
    }

    recalculateCounts() {
        const counts = { "Todas": 0 };
        this.stageConfigs.forEach(stage => { counts[stage.name] = 0; });
        const cookWaitTimes = [];
        this.orders.forEach(ord => {
            const st = ord.kds_stage || this.stageConfigs[0]?.name || "";
            counts["Todas"] += 1;
            if (counts[st] !== undefined) {
                counts[st] += 1;
            }
            if (Number(ord.stage_index) < (ord.stages || this.stageConfigs).length - 1) {
                cookWaitTimes.push(this.computeElapsedMinutes(ord));
            }
        });
        this.counts = counts;
        this.inProgressCount = cookWaitTimes.length;
        this.avgWaitMinutes = cookWaitTimes.length
            ? Math.round(cookWaitTimes.reduce((acc, m) => acc + m, 0) / cookWaitTimes.length)
            : 0;
    }

    formatCardTitle(ord) {
        const custName = String(ord.customer_name || "").trim();
        const isDefaultCust = !custName || custName.toUpperCase() === "CONSUMIDOR FINAL";
        const rawOrderName = String(ord.order_name || "").trim();
        if (!isDefaultCust) {
            return custName;
        }
        if (ord.table_label) {
            const isGenericMesa = !rawOrderName ||
                rawOrderName.toLowerCase() === `mesa ${String(ord.table_label).toLowerCase()}` ||
                /^orden\s+\d+$/i.test(rawOrderName);
            if (isGenericMesa) {
                return `T${ord.table_label}`;
            }
            return rawOrderName;
        }
        if (/^orden\s+\d+$/i.test(rawOrderName)) {
            const digits = String(ord.name || "").match(/(\d+)$/);
            return digits ? String(1000 + Number(digits[1])) : rawOrderName;
        }
        return rawOrderName || ord.name || "Pedido";
    }

    formatStatusNumber(ord) {
        const rawOrderName = String(ord.order_name || "").trim();
        if (/^\d{3,5}$/.test(rawOrderName)) {
            return rawOrderName;
        }
        const digits = String(ord.name || "").match(/(\d+)$/);
        if (digits) {
            return String(1000 + Number(digits[1]));
        }
        return this.formatCardTitle(ord);
    }

    formatItemModifiers(item) {
        const mods = [];
        const selected = Array.isArray(item.selected_options) ? item.selected_options : [];
        if (selected.length) {
            selected.forEach(opt => {
                if (!opt) return;
                const grp = String(opt.group_name || opt.effect || "").trim();
                const lbl = String(opt.option_label || "").trim();
                if (grp && lbl) {
                    mods.push(`${grp} : ${lbl}`);
                } else if (lbl) {
                    mods.push(lbl);
                }
            });
        } else if (item.options_summary) {
            String(item.options_summary)
                .split(",")
                .map(s => s.trim())
                .filter(Boolean)
                .forEach(part => mods.push(part));
        }
        if (item.note) {
            mods.push(`Nota : ${String(item.note).trim()}`);
        }
        return mods;
    }

    formatQty(qty) {
        const num = Number(qty || 1);
        return Number.isInteger(num) ? `${num}x` : `${num.toLocaleString("es-HN")}x`;
    }

    visibleOrders() {
        if (this.activeStage === "Todas") {
            return this.orders;
        }
        return this.orders.filter(ord => (ord.kds_stage || this.stageConfigs[0]?.name || "") === this.activeStage);
    }

    currentDisplay() {
        return this.displays.find(display => display.name === this.selectedDisplay);
    }

    render() {
        this.shell.classList.toggle("is-dark-mode", Boolean(this.darkMode));
        if (this.viewMode === "hub") {
            this.shell.innerHTML = this.renderHubView();
            this.bindEvents();
            return;
        }
        if (this.viewMode === "config") {
            this.shell.innerHTML = this.renderConfigView();
            this.mountConfigControls();
            this.bindEvents();
            return;
        }
        if (this.viewMode === "stages-list") {
            this.shell.innerHTML = this.renderStagesListView();
            this.bindEvents();
            return;
        }
        if (this.viewMode === "status-screen") {
            this.shell.innerHTML = this.renderOrderStatusView();
            this.bindEvents();
            return;
        }
        this.shell.innerHTML = this.renderPreparationView();
        this.bindEvents();
    }

    isKdsManager() {
        const roles = Array.isArray(frappe.user_roles) ? frappe.user_roles : [];
        return roles.includes("Restaurant Manager") || roles.includes("System Manager") || frappe.session.user === "Administrator";
    }

    renderHubView() {
        const canConfig = this.isKdsManager();
        return `<header class="rkds-hub-topbar">
            <div class="rkds-hub-topbar-left">
                ${canConfig ? `<button type="button" class="rkds-admin-new-btn" data-kds-action="new-display">Nuevo</button>` : ""}
                <span class="rkds-hub-page-title">Pantallas de preparación</span>
                </div>
            <button type="button" class="rkds-top-btn" data-kds-action="close-kds">Cerrar</button>
        </header><main class="rkds-hub-container rkds-display-grid">
            ${this.displays.map(display => `<section class="rkds-hub-card" aria-label="${this.escape(display.display_name)}">
                <div class="rkds-hub-card-top">
                    <div class="rkds-hub-title-row"><h2 class="rkds-hub-title">${this.escape(display.display_name)}</h2>
                        ${canConfig ? `<button type="button" class="rkds-hub-card-config-btn" data-kds-action="open-config" data-display="${this.escape(display.name)}" title="Configurar pantalla">⋮</button>` : ""}
                    </div><p>${this.escape(display.description || "")}</p>
                    <div class="rkds-hub-stage-pills">${display.stages.map(stage => `<button type="button" class="rkds-hub-pill" data-kds-action="open-prep-stage" data-display="${this.escape(display.name)}" data-stage="${this.escape(stage.name)}">${this.escape(stage.stage_name)}</button>`).join("")}</div>
                </div><div class="rkds-hub-card-bottom"><div class="rkds-hub-actions">
                    <button type="button" class="rkds-hub-btn is-leaf-green" data-kds-action="open-preparation" data-display="${this.escape(display.name)}">Pantalla de<br>preparación</button>
                    <button type="button" class="rkds-hub-btn is-grintsys-blue" data-kds-action="open-status-screen" data-display="${this.escape(display.name)}">Pantalla del estado de<br>la orden</button>
                </div><div class="rkds-hub-metrics">
                    <div class="rkds-hub-metric-row"><span>En progreso</span><span>${Number(display.in_progress_count || 0)}</span></div>
                    <div class="rkds-hub-metric-row"><span>Tiempo promedio</span><span>${Number(display.avg_wait_minutes || 0)}'</span></div>
                </div></div>
            </section>`).join("") || '<div class="rkds-empty-state">Crea una pantalla de preparación para comenzar.</div>'}
        </main>`;
    }

    renderConfigView() {
        const display = this.editingNewDisplay ? null : this.currentDisplay();
        return `<header class="rkds-hub-topbar"><div class="rkds-hub-topbar-left">
            <span class="rkds-hub-page-title">Pantalla de preparación · ${this.escape(display?.display_name || "Nueva")}</span>
        </div><div class="rkds-hub-topbar-actions">
            <button type="button" class="rkds-admin-new-btn" data-kds-action="save-display">Guardar</button>
            <button type="button" class="rkds-top-btn" data-kds-action="open-hub">Volver</button>
        </div></header><main class="rkds-hub-container"><section class="rkds-config-sheet">
            <div class="rkds-config-name-block" data-config-control="display_name"></div>
            <div data-config-control="description"></div><div class="rkds-config-grid">
                <div class="rkds-config-col"><div data-config-control="pos_profiles"></div><div data-config-control="item_groups"></div><div data-config-control="stages"></div>
                    <p class="text-muted">Selecciona las etapas en orden: preparación → entrega → completada. Al marcar todos los platillos se avanza automáticamente.</p>
                </div><div class="rkds-config-col"><div data-config-control="auto_clear"></div><div data-config-control="auto_clear_minutes"></div>
                    <p class="text-muted">El retiro automático oculta las tarjetas completadas y conserva las comandas.</p><div data-config-control="enabled"></div>
                </div>
            </div></section></main>`;
    }

    mountConfigControls() {
        const display = this.editingNewDisplay ? {} : (this.currentDisplay() || {});
        this.configControls = {};
        const definitions = [
            {fieldname:"display_name",fieldtype:"Data",label:"Nombre",reqd:1},
            {fieldname:"description",fieldtype:"Small Text",label:"Descripción"},
            {fieldname:"pos_profiles",fieldtype:"MultiSelectPills",label:"Puntos de venta",description:"Vacío: todos los puntos de venta",get_data:txt=>frappe.db.get_link_options("POS Profile",txt)},
            {fieldname:"item_groups",fieldtype:"MultiSelectPills",label:"Categorías de producto",description:"Vacío: todas las categorías",get_data:txt=>frappe.db.get_link_options("Item Group",txt)},
            {fieldname:"stages",fieldtype:"MultiSelectPills",label:"Etapas de preparación",reqd:1,description:"Selecciona al menos tres etapas, en el orden de trabajo.",get_data:()=> (this.stagesCatalog || []).map(stage=>({value:stage.name,label:stage.stage_name}))},
            {fieldname:"auto_clear",fieldtype:"Check",label:"Eliminación automática",onchange:()=>{const control=this.configControls.auto_clear_minutes; if(control) control.toggle(Boolean(this.configControls.auto_clear.get_value()));}},
            {fieldname:"auto_clear_minutes",fieldtype:"Int",label:"Retirar completadas después de (minutos)"},
            {fieldname:"enabled",fieldtype:"Check",label:"Habilitada"},
        ];
        definitions.forEach(df=>{
            const control=frappe.ui.form.make_control({parent:this.shell.querySelector(`[data-config-control="${df.fieldname}"]`),df,render_input:true});
            this.configControls[df.fieldname]=control;
            let value=display[df.fieldname];
            if(df.fieldname==="stages") value=(display.stages || []).map(stage=>stage.name);
            if(df.fieldname==="enabled" && value==null) value=1;
            if(df.fieldname==="auto_clear_minutes" && value==null) value=5;
            control.set_value(value ?? (["pos_profiles","item_groups","stages"].includes(df.fieldname) ? [] : ""));
        });
        this.configControls.auto_clear_minutes.toggle(Boolean(display.auto_clear));
    }

    async saveDisplay() {
        const data={};
        Object.entries(this.configControls || {}).forEach(([key,control])=>{data[key]=control.get_value();});
        if(!this.editingNewDisplay) {
            data.name=this.selectedDisplay;
            data.modified=this.currentDisplay()?.modified;
        }
        if(!data.display_name || (data.stages || []).length<3){frappe.msgprint("Indica un nombre y al menos tres etapas de preparación."); return;}
        if(await this.callMutation("save_display",{data:JSON.stringify(data)},false)){
            this.editingNewDisplay=false; this.viewMode="hub"; await this.refreshOrders();
        }
    }

    renderStagesListView() {
        return `<header class="rkds-hub-topbar"><div class="rkds-hub-topbar-left">
            <button type="button" class="rkds-admin-new-btn" data-kds-action="new-stage">Nuevo</button><span class="rkds-hub-page-title">Etapas de preparación</span>
        </div><button type="button" class="rkds-top-btn" data-kds-action="open-hub">Volver</button></header>
        <main class="rkds-stages-table-wrap"><table class="rkds-stages-table">
            <thead><tr><th>Nombre</th><th>Color</th><th>Temporizador (min)</th><th>Pantallas de preparación</th></tr></thead>
            <tbody>${(this.stagesCatalog || []).map(stage=>`<tr data-kds-action="edit-stage" data-stage="${this.escape(stage.name)}">
                <td><strong>${this.escape(stage.stage_name)}</strong></td><td><span class="rkds-stage-color-dot" style="background:${this.escape(stage.color)}"></span></td>
                <td>${Number(stage.alert_minutes || 0)}</td><td>${this.displays.filter(display=>display.stages.some(row=>row.name===stage.name)).map(display=>this.escape(display.display_name)).join(", ")}</td>
            </tr>`).join("")}</tbody></table></main>`;
    }

    editStage(stageName) {
        const stage=(this.stagesCatalog || []).find(row=>row.name===stageName) || {};
        const dialog=new frappe.ui.Dialog({title:stage.name ? "Editar etapa de preparación" : "Crear etapa de preparación",fields:[
            {fieldname:"stage_name",fieldtype:"Data",label:"Nombre",reqd:1,default:stage.stage_name},
            {fieldname:"color",fieldtype:"Color",label:"Color",reqd:1,default:stage.color || "#9ca3af"},
            {fieldname:"alert_minutes",fieldtype:"Int",label:"Temporizador de alerta (min)",default:stage.alert_minutes || 0,description:"0 desactiva la alerta."},
            {fieldname:"help",fieldtype:"HTML",options:"<p>Asigna esta etapa desde la configuración de cada pantalla de preparación.</p>"},
        ],primary_action_label:"Guardar",primary_action:async values=>{
            if(stage.name) { values.name=stage.name; values.modified=stage.modified; }
            if(await this.callMutation("save_stage",{data:JSON.stringify(values)},false)){dialog.hide(); await this.refreshOrders();}
        }});
        dialog.show();
    }

    renderOrderStatusView() {
        const grouped = new Map();
        this.orders.forEach(order => {
            const previous = grouped.get(order.name);
            if (!previous || order.stage_index < previous.stage_index) grouped.set(order.name, order);
        });
        const statusOrders = [...grouped.values()];
        const inProgressOrders = statusOrders.filter(o => o.stage_index < (o.stages || this.stageConfigs).length - 2);
        const readyOrders = statusOrders.filter(o => o.stage_index === (o.stages || this.stageConfigs).length - 2);

        return `
            <div class="rkds-customer-status-screen">
                <button type="button" class="rkds-customer-status-back" data-kds-action="open-hub" title="Volver a Kitchen Display">
                    ← Kitchen Display
                </button>

                <section class="rkds-customer-col is-almost-ready">
                    <h2 class="rkds-customer-heading">Casi lista</h2>
                    <div class="rkds-customer-badges">
                        ${inProgressOrders.map(ord => `
                            <div class="rkds-customer-badge is-almost">
                                ${this.escape(this.formatStatusNumber(ord))}
                            </div>
                        `).join("")}
                    </div>
                </section>

                <section class="rkds-customer-col is-ready-now">
                    <h2 class="rkds-customer-heading">Lista</h2>
                    <div class="rkds-customer-badges">
                        ${readyOrders.map(ord => `
                            <div class="rkds-customer-badge is-ready">
                                ${this.escape(this.formatStatusNumber(ord))}
                            </div>
                        `).join("")}
                    </div>
                    <div class="rkds-customer-watermark">LEAF</div>
                </section>
            </div>
        `;
    }

    renderPreparationView() {
        const visible = this.visibleOrders();
        const finalStage = this.stageConfigs[this.stageConfigs.length - 1]?.name;
        const isCompletedView = this.activeStage === finalStage;

        return `
            <header class="rkds-topbar">
                <div class="rkds-topbar-left">
                    <button type="button" class="rkds-icon-btn ${this.stationBarOpen ? "is-active" : ""}" data-kds-action="toggle-stations" title="Filtrar por estación de comanda">
                        <svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                            <rect x="3" y="3" width="18" height="18" rx="2"/>
                            <line x1="9" y1="3" x2="9" y2="21"/>
                        </svg>
                    </button>
                    <button type="button" class="rkds-icon-btn" data-kds-action="toggle-theme" title="Cambiar modo de color">
                        <svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                            <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>
                        </svg>
                    </button>
                </div>

                <nav class="rkds-stage-tabs" aria-label="Etapas de cocina">
                    <button type="button" class="rkds-stage-tab is-all ${this.activeStage === "Todas" ? "is-active" : ""}" data-stage="Todas">
                        <span class="rkds-stage-label">Todas</span>
                    </button>
                    ${this.stageConfigs.map((stage, index) => `
                        <button type="button" class="rkds-stage-tab ${index === this.stageConfigs.length - 1 ? "is-completed" : index === this.stageConfigs.length - 2 ? "is-ready" : "is-to-cook"} ${this.activeStage === stage.name ? "is-active" : ""}" data-stage="${this.escape(stage.name)}" style="--rkds-stage-color:${this.escape(stage.color)}">
                            <span class="rkds-stage-label">${this.escape(stage.stage_name)}</span>
                            <span class="rkds-stage-badge" style="background:${this.escape(stage.color)}">${this.counts[stage.name] || 0}</span>
                        </button>
                    `).join("")}
                </nav>

                <div class="rkds-topbar-right">
                    ${isCompletedView ? `
                        <button type="button" class="rkds-top-btn" data-kds-action="clear-completed" ${!this.counts[finalStage] ? "disabled" : ""} title="Retirar todas las tarjetas completadas de esta pantalla">
                            <svg viewBox="0 0 24 24" width="15" height="15" fill="currentColor">
                                <path d="M9 3a1 1 0 0 0-1 1v1H4a1 1 0 1 0 0 2h1v12a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V7h1a1 1 0 1 0 0-2h-4V4a1 1 0 0 0-1-1H9zm1 2h4v1h-4V5zm-1 5a1 1 0 1 1 2 0v7a1 1 0 1 1-2 0v-7zm4 0a1 1 0 1 1 2 0v7a1 1 0 1 1-2 0v-7z"/>
                            </svg>
                            <span>Listo</span>
                        </button>
                    ` : `
                        <button type="button" class="rkds-top-btn is-undo" data-kds-action="undo-stage" ${!this.undoStack.length ? "disabled" : ""} title="Regresar la última orden a su etapa anterior">
                            <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round">
                                <polyline points="9 14 4 9 9 4"/>
                                <path d="M20 20v-7a4 4 0 0 0-4-4H4"/>
                            </svg>
                            <span>Regresar a etapa anterior</span>
                        </button>
                    `}
                    <button type="button" class="rkds-top-btn is-close" data-kds-action="open-hub" title="Cerrar monitor y volver a Kitchen Display">
                        <span>Cerrar</span>
                        <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round">
                            <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/>
                            <polyline points="16 17 21 12 16 7"/>
                            <line x1="21" y1="12" x2="9" y2="12"/>
                        </svg>
                    </button>
                </div>
            </header>

            ${this.stationBarOpen ? `
                <div class="rkds-station-bar">
                    <span class="rkds-station-title">Estación:</span>
                    ${this.stations.map(st => `
                        <button type="button" class="rkds-station-chip ${this.selectedStation === st ? "is-active" : ""}" data-station="${this.escape(st)}">
                            ${this.escape(st)}
                        </button>
                    `).join("")}
                </div>
            ` : ""}

            <main class="rkds-board">
                ${visible.length ? visible.map(ord => this.renderTicketCard(ord)).join("") : `
                    <div class="rkds-empty-state">
                        <div class="rkds-empty-title">No hay pedidos en "${this.escape(this.stageConfigs.find(stage => stage.name === this.activeStage)?.stage_name || this.activeStage)}"</div>
                        <div class="rkds-empty-sub">Las comandas enviadas desde el Punto de Venta aparecerán aquí automáticamente.</div>
                    </div>
                `}
            </main>
        `;
    }

    formatScheduledHeader(schedStr) {
        const raw = String(schedStr || "").trim();
        if (!raw) return "";
        if (/^\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}/.test(raw)) {
            const [datePart, timePart] = raw.split(/\s+/);
            const [y, m, d] = datePart.split("-").map(Number);
            const target = new Date(y, (m || 1) - 1, d || 1);
            const now = new Date();
            const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
            const diffDays = Math.round((target - today) / 86400000);
            const hhmm = timePart.slice(0, 5);
            if (diffDays === 0) return hhmm;
            if (diffDays === 1) return `${hhmm} Mañana`;
            return `${hhmm} ${String(d).padStart(2, "0")}/${String(m).padStart(2, "0")}`;
        }
        return raw;
    }

    renderTicketCard(ord) {
        const title = this.formatCardTitle(ord);
        const schedHeader = this.formatScheduledHeader(ord.scheduled_time);
        const guests = Math.max(1, Number(ord.guests || 1));
        const waitMins = this.computeElapsedMinutes(ord);
        const stage = ord.kds_stage;
        const stageCount = (ord.stages || this.stageConfigs).length;
        const isCookStage = ord.stage_index < stageCount - 2;
        const isReadyStage = ord.stage_index === stageCount - 2;
        const isCompleted = ord.stage_index === stageCount - 1;
        const isUrgent = this.isOrderUrgent(ord, waitMins);
        const serviceType = ord.service_type || "Comer en el local";

        return `
            <article class="rkds-card is-stage-${isCookStage ? "cook" : (isReadyStage ? "ready" : "completed")}"
                     data-card-order="${this.escape(ord.name)}"
                     data-card-ticket="${this.escape(ord.ticket_name)}"
                     data-card-stage="${this.escape(stage)}">
                <header class="rkds-card-header">
                    <div class="rkds-card-title">${this.escape(title)}${Number(ord.batch_count) > 1 ? `<small class="rkds-batch-label"> · Grupo ${Number(ord.batch_index)} de ${Number(ord.batch_count)}</small>` : ""}</div>
                    ${schedHeader ? `<div class="rkds-card-sched" style="font-size:12.5px;font-weight:700;color:#1e293b;">${this.escape(schedHeader)}</div>` : ""}
                    <div class="rkds-card-guests" title="Comensales">
                        <svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor">
                            <path d="M16 11c1.66 0 2.99-1.34 2.99-3S17.66 5 16 5c-1.66 0-3 1.34-3 3s1.34 3 3 3zm-8 0c1.66 0 2.99-1.34 2.99-3S9.66 5 8 5C6.34 5 5 6.34 5 8s1.34 3 3 3zm0 2c-2.33 0-7 1.17-7 3.5V19h14v-2.5c0-2.33-4.67-3.5-7-3.5zm8 0c-.29 0-.62.02-.97.05 1.16.84 1.97 1.97 1.97 3.45V19h6v-2.5c0-2.33-4.67-3.5-7-3.5z"/>
                        </svg>
                        <span>${guests}</span>
                    </div>
                </header>

                <div class="rkds-card-body">
                    <div class="rkds-card-meta">
                        <span class="rkds-service-pill" data-service="${this.escape(serviceType)}">
                            ${this.escape(serviceType)}
                        </span>
                        <span class="rkds-timer-pill ${isUrgent ? "is-urgent" : ""}" data-timer-order="${this.escape(ord.name)}" data-timer-ticket="${this.escape(ord.ticket_name)}" title="Tiempo en espera">
                            <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
                                <circle cx="12" cy="12" r="10"/>
                                <polyline points="12 6 12 12 16 14"/>
                            </svg>
                            <span class="rkds-timer-val">${waitMins}'</span>
                        </span>
                    </div>

                    <div class="rkds-card-items">
                        ${(ord.items || []).map(item => {
                            const mods = this.formatItemModifiers(item);
                            const isItemCancelled = Boolean(item.is_cancelled) || item.kds_status === "Cancelado";
                            const isItemStruck = !isItemCancelled && !isCompleted && (ord.completed_item_names || []).includes(item.name);
                            const canToggle = !isCompleted && !isItemCancelled;
                            return `
                                <div class="rkds-item-row ${canToggle ? "is-clickable" : ""} ${isItemStruck ? "is-struck" : ""} ${isItemCancelled ? "is-cancelled" : ""}"
                                     ${canToggle ? `role="button" tabindex="0" aria-pressed="${isItemStruck}" data-kds-action="toggle-item" data-order="${this.escape(ord.name)}" data-item-name="${this.escape(item.name)}" title="Marcar o desmarcar este platillo en la etapa actual"` : ""}>
                                    <div class="rkds-item-main" ${isItemCancelled ? `style="text-decoration:line-through;color:#dc2626;opacity:0.85;"` : ""}>
                                        <span class="rkds-item-qty">${this.escape(this.formatQty(item.qty))}</span>
                                        <span class="rkds-item-name">${this.escape(item.item_name)}</span>
                                        ${isItemCancelled ? `<span style="margin-left:6px;padding:1px 6px;border-radius:4px;background:#fee2e2;color:#b91c1c;font-size:10px;font-weight:700;text-decoration:none;display:inline-block;">CANCELADO</span>` : ""}
                                    </div>
                                    ${isItemCancelled && item.cancellation_reason ? `<div class="rkds-item-mod" style="color:#b91c1c;">Motivo: ${this.escape(item.cancellation_reason)}</div>` : ""}
                                    ${mods.map(m => `
                                        <div class="rkds-item-mod">- ${this.escape(m)}</div>
                                    `).join("")}
                                </div>
                            `;
                        }).join("")}
                    </div>
                </div>

                ${isCompleted ? `
                    <footer class="rkds-card-footer">
                        <button type="button" class="rkds-card-btn is-reset" data-kds-action="reset-order" data-order="${this.escape(ord.name)}">
                            <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
                                <polyline points="9 14 4 9 9 4"/>
                                <path d="M20 20v-7a4 4 0 0 0-4-4H4"/>
                            </svg>
                            <span>Restablecer</span>
                        </button>
                        <button type="button" class="rkds-card-btn is-done" data-kds-action="close-order" data-order="${this.escape(ord.name)}">
                            <span>Listo</span>
                        </button>
                    </footer>
                ` : ""}
            </article>
        `;
    }

    bindEvents() {
        this.shell.querySelectorAll("[data-stage]").forEach(btn => {
            if (btn.dataset.kdsAction) return;
            btn.addEventListener("click", () => {
                this.activeStage = btn.dataset.stage;
                this.render();
            });
        });

        this.shell.querySelectorAll("[data-station]").forEach(btn => {
            btn.addEventListener("click", () => {
                this.selectedStation = btn.dataset.station;
                this.refreshOrders();
            });
        });

        this.shell.querySelectorAll("[data-kds-action]").forEach(el => {
            const action = el.dataset.kdsAction;
            if (!action) return;
            el.addEventListener("click", e => {
                e.stopPropagation();
                this.handleAction(action, el);
            });
            if (el.getAttribute("role") === "button") {
                el.addEventListener("keydown", event => {
                    if (event.key === "Enter" || event.key === " ") {
                        event.preventDefault();
                        this.handleAction(action, el);
                    }
                });
            }
        });
    }

    async handleAction(action, el) {
        if (this.mutating) return;
        if (["open-preparation", "open-prep-stage", "open-status-screen", "open-config"].includes(action) && el.dataset.display) {
            if (this.selectedDisplay !== el.dataset.display) this.undoStack = [];
            this.selectedDisplay = el.dataset.display;
            await this.refreshOrders();
        }
        if (action === "open-hub") {this.viewMode="hub"; this.render(); return;}
        if (action === "new-display" || action === "open-config") {
            this.editingNewDisplay=action === "new-display";
            this.viewMode="config"; this.render(); return;
        }
        if (action === "save-display") {await this.saveDisplay(); return;}
        if (action === "open-stages-list") {this.viewMode="stages-list"; this.render(); return;}
        if (action === "new-stage" || action === "edit-stage") {this.editStage(el.dataset.stage); return;}
        if (action === "open-preparation" || action === "open-prep-stage") {
            this.activeStage=el.dataset.stage || this.stageConfigs[0]?.name || "Todas";
            this.viewMode="preparation"; this.render(); return;
        }
        if (action === "open-status-screen") {this.viewMode="status-screen"; this.render(); return;}
        if (action === "toggle-stations") {this.stationBarOpen=!this.stationBarOpen; this.render(); return;}
        if (action === "toggle-theme") {
            this.darkMode=!this.darkMode;
            try {window.localStorage?.setItem("rkds_dark_mode",this.darkMode ? "1" : "0");} catch(e) { /* Storage may be disabled. */ }
            this.render(); return;
        }
        if (action === "close-kds") {this.stopTimers(); frappe.set_route("Workspaces", "Restaurante"); return;}
        if (action === "toggle-item") {await this.toggleOrderItemStrike(el.dataset.order,el.dataset.itemName,el.closest("[data-card-ticket]")?.dataset.cardTicket); return;}
        if (action === "reset-order" || action === "close-order") {
            const ticketId = el.closest("[data-card-ticket]")?.dataset.cardTicket;
            const order = this.orders.find(row => ticketId ? row.ticket_name === ticketId : row.name === el.dataset.order);
            if (!order) return;
            await this.callMutation(action === "reset-order" ? "reset_ticket" : "dismiss_ticket",{display_name:this.selectedDisplay,order_name:el.dataset.order,ticket_id:order.ticket_name,expected_stage:order.kds_stage});
            return;
        }
        if (action === "undo-stage") {
            const last=this.undoStack[this.undoStack.length-1];
            if (!last) return;
            if (await this.callMutation("move_previous_stage",{display_name:this.selectedDisplay,order_name:last.orderName,ticket_id:last.ticketId,expected_stage:last.expectedStage})) this.undoStack.pop();
            this.render(); return;
        }
        if (action === "clear-completed") {
            const completed=this.orders.filter(order=>order.stage_index===(order.stages || this.stageConfigs).length-1);
            for (const order of completed) {
                if (!await this.callMutation("dismiss_ticket",{display_name:this.selectedDisplay,order_name:order.name,ticket_id:order.ticket_name,expected_stage:order.kds_stage},false)) break;
            }
            await this.refreshOrders({silent:true});
        }
    }

    async callMutation(method, args, refresh = true) {
        if (this.mutating) return false;
        this.mutating = true;
        this.shell.classList.add("is-updating");
        try {
            await frappe.call({method:`restaurant.kds.${method}`,type:"POST",args});
            if (refresh) await this.refreshOrders({silent:true});
            return true;
        } catch (error) {
            frappe.show_alert({message:"No se pudo guardar el cambio. Revisa el mensaje y vuelve a intentarlo.",indicator:"red"});
            return false;
        } finally {
            this.mutating=false;
            this.shell.classList.remove("is-updating");
        }
    }

    async toggleOrderItemStrike(orderName, itemName, ticketId) {
        const order=this.orders.find(row=>ticketId ? row.ticket_name===ticketId : row.name===orderName);
        if (!order || !itemName) return;
        const stage=order.kds_stage;
        const completed=!(order.completed_item_names || []).includes(itemName);
        if (await this.callMutation("toggle_item",{display_name:this.selectedDisplay,order_name:orderName,ticket_id:order.ticket_name,item_name:itemName,expected_stage:stage,completed:completed ? 1 : 0})) {
            const updated=this.orders.find(row=>row.ticket_name===order.ticket_name);
            if(updated && updated.kds_stage!==stage) this.undoStack.push({orderName,ticketId:updated.ticket_name,expectedStage:updated.kds_stage});
            this.render();
        }
    }
}
