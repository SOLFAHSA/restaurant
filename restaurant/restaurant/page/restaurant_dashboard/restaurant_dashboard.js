// Read-only dashboard: every number comes from restaurant.dashboard.get_dashboard_data.
frappe.pages["restaurant-dashboard"].on_page_load = function (wrapper) {
    wrapper.restaurant_dashboard = new RestaurantDashboardPage(wrapper);
};
frappe.pages["restaurant-dashboard"].on_page_show = function (wrapper) {
    wrapper.restaurant_dashboard.show();
};
frappe.pages["restaurant-dashboard"].on_page_hide = function (wrapper) {
    wrapper.restaurant_dashboard.hide();
};

const RD_REFRESH_MS = 60000;
const RD_REALTIME_DELAY_MS = 1500;
const RD_REALTIME_EVENT = "restaurant_kds_update";
const RD_SERVICE_LABELS = { "Comer en el local": "Salón", "Para llevar": "Para llevar", "Entrega": "Domicilio" };

class RestaurantDashboardPage {
    constructor(wrapper) {
        this.page = frappe.ui.make_app_page({ parent: wrapper, title: "Dashboard", single_column: true });
        this.page.set_secondary_action("Volver al restaurante", () => frappe.set_route("Workspaces", "Restaurante"));
        this.page.set_primary_action("Actualizar", () => this.load(), "refresh");
        this.companyField = this.page.add_field({
            fieldname: "company",
            label: "Compañía",
            fieldtype: "Link",
            options: "Company",
            default: frappe.defaults.get_user_default("Company"),
            change: () => this.load(),
        });
        this.requestId = 0;
        this.shownValues = {};
        this.onRealtime = () => this.scheduleRealtimeLoad();
        this.root = $('<div class="rd-page"></div>').appendTo(this.page.body)[0];
        this.root.innerHTML = this.layout();
        this.root.addEventListener("click", event => {
            const target = event.target.closest("[data-route]");
            if (target) frappe.set_route(...target.dataset.route.split("/"));
        });
    }

    show() {
        this.load();
        clearInterval(this.timer);
        this.timer = setInterval(() => { if (!document.hidden) this.load(); }, RD_REFRESH_MS);
        // Orders and kitchen changes already publish this event; reuse it to refresh at once.
        frappe.realtime.on(RD_REALTIME_EVENT, this.onRealtime);
    }

    hide() {
        clearInterval(this.timer);
        clearTimeout(this.realtimeTimer);
        frappe.realtime.off(RD_REALTIME_EVENT, this.onRealtime);
    }

    scheduleRealtimeLoad() {
        clearTimeout(this.realtimeTimer);
        this.realtimeTimer = setTimeout(() => { if (!document.hidden) this.load(); }, RD_REALTIME_DELAY_MS);
    }

    escape(value) {
        return frappe.utils.escape_html(String(value == null ? "" : value));
    }

    money(value) {
        return format_currency(value || 0, this.currency);
    }

    minutes(value) {
        if (value < 60) return `${value} min`;
        if (value < 1440) return `${Math.floor(value / 60)} h ${value % 60} min`;
        const days = Math.floor(value / 1440);
        return `${days} ${days === 1 ? "día" : "días"}`;
    }

    greeting() {
        const hour = new Date().getHours();
        const name = this.escape((frappe.session.user_fullname || "").split(" ")[0]);
        const text = hour < 12 ? "Buenos días" : hour < 19 ? "Buenas tardes" : "Buenas noches";
        return name ? `${text}, ${name}` : text;
    }

    layout() {
        const kpi = (key, label, icon, tone) => `
            <div class="rd-card rd-kpi is-${tone}">
                <span class="rd-kpi-icon">${frappe.utils.icon(icon, "md")}</span>
                <div class="rd-kpi-body"><span class="rd-kpi-label">${label}</span><strong data-kpi="${key}">—</strong>
                    <span class="rd-badge" data-badge="${key}" hidden></span></div>
                <span class="rd-kpi-bar"><i data-bar="${key}"></i></span>
            </div>`;
        const shortcut = (route, title, description, icon, tone) => `
            <button type="button" class="rd-card rd-shortcut is-${tone}" data-route="${route}">
                <span class="rd-kpi-icon">${frappe.utils.icon(icon, "md")}</span>
                <span><strong>${title}</strong><small>${description}</small></span>
            </button>`;
        return `
            <header class="rd-hero">
                <div class="rd-hero-main">
                    <span class="rd-live"><i></i>En vivo</span>
                    <h2 data-greeting>${this.greeting()}</h2>
                    <p data-hero-date></p>
                </div>
                <div class="rd-hero-sales">
                    <small>Ventas de hoy</small>
                    <strong data-kpi="sales">—</strong>
                    <span class="rd-hero-change" data-badge="sales" hidden></span>
                </div>
            </header>
            <p class="rd-status" role="status" aria-live="polite"></p>
            <section class="rd-kpis" aria-label="Indicadores principales">
                ${kpi("tables", "Mesas ocupadas", "table", "navy")}
                ${kpi("open", "Cuentas abiertas", "file", "green")}
                ${kpi("kitchen", "Pedidos en cocina", "list-alt", "amber")}
                ${kpi("ticket", "Ticket promedio", "income", "lime")}
            </section>
            <section class="rd-row">
                <div class="rd-card rd-chart-card">
                    <div class="rd-card-head"><div><h3>Ventas por hora</h3>
                        <p class="rd-sub">Facturas emitidas hoy desde el restaurante, comparadas con ayer.</p></div>
                        <span class="rd-peak" data-peak hidden></span></div>
                    <div class="rd-chart"></div>
                </div>
                <div class="rd-card rd-occupancy">
                    <h3>Ocupación del salón</h3><p class="rd-sub">Mesas activas en este momento.</p>
                    <div class="rd-occupancy-body">
                        <div class="rd-donut" role="img"><span><strong data-donut-percent>0%</strong><small data-donut-label></small></span></div>
                        <ul class="rd-legend">
                            <li><i class="is-occupied"></i>Ocupadas<strong data-legend="occupied">0</strong></li>
                            <li><i class="is-reserved"></i>Reservadas<strong data-legend="reserved">0</strong></li>
                            <li><i class="is-available"></i>Disponibles<strong data-legend="available">0</strong></li>
                        </ul>
                    </div>
                </div>
            </section>
            <section class="rd-row rd-row-even">
                <div class="rd-card">
                    <h3>Más vendidos hoy</h3><p class="rd-sub">Productos facturados hoy, por importe sin ISV.</p>
                    <ol class="rd-top-list"></ol>
                </div>
                <div class="rd-card rd-activity">
                    <h3>Actividad reciente</h3><p class="rd-sub">Últimos movimientos de cuentas.</p>
                    <ul class="rd-activity-list"></ul>
                </div>
            </section>
            <section class="rd-shortcuts" aria-label="Accesos rápidos">
                ${shortcut("restaurant-pos", "Punto de venta", "Abre cuentas y toma pedidos", "sell", "green")}
                ${shortcut("restaurant-kds", "Cocina KDS", "Pedidos en preparación", "list-alt", "amber")}
                ${shortcut("restaurant-table-map", "Mapa de mesas", "Estado del salón", "table", "navy")}
                ${shortcut("query-report/Sales Register", "Registro de ventas", "Facturas emitidas", "chart", "lime")}
            </section>
            <section class="rd-row rd-row-even">
                <div class="rd-card">
                    <div class="rd-card-head"><h3>Pedidos pendientes en cocina</h3>
                        <button type="button" class="btn btn-link btn-sm" data-route="restaurant-kds">Ir a Cocina KDS</button></div>
                    <div class="rd-table-wrap"><table class="table rd-table">
                        <thead><tr><th>Pedido</th><th>Origen</th><th>Mesa / Cliente</th><th>Platillos</th><th>Tiempo</th><th>Estado</th></tr></thead>
                        <tbody data-table="kitchen"></tbody></table></div>
                </div>
                <div class="rd-card">
                    <div class="rd-card-head"><h3>Mesas pendientes</h3>
                        <button type="button" class="btn btn-link btn-sm" data-route="restaurant-table-map">Ver mapa de mesas</button></div>
                    <div class="rd-table-wrap"><table class="table rd-table">
                        <thead><tr><th>Mesa</th><th>Comensales</th><th>Tiempo</th><th>Cuenta</th><th><span class="sr-only">Acciones</span></th></tr></thead>
                        <tbody data-table="tables"></tbody></table></div>
                </div>
            </section>`;
    }

    async load() {
        const requestId = ++this.requestId;
        const status = this.root.querySelector(".rd-status");
        status.textContent = "Actualizando…";
        try {
            const response = await frappe.call({
                method: "restaurant.dashboard.get_dashboard_data",
                args: { company: this.companyField.get_value() || null },
            });
            if (requestId !== this.requestId) return;
            this.render(response.message);
            status.textContent = `Actualizado a las ${frappe.datetime.now_time().slice(0, 5)}. Se actualiza solo cuando hay movimientos.`;
        } catch (error) {
            if (requestId !== this.requestId) return;
            status.textContent = "No se pudo cargar el dashboard. Revisa tu conexión o tus permisos y presiona Actualizar.";
        }
    }

    render(data) {
        this.currency = data.currency;
        const { tables, sales, kitchen } = data;
        this.root.querySelector("[data-greeting]").innerHTML = this.greeting();
        this.root.querySelector("[data-hero-date]").textContent =
            `${frappe.datetime.str_to_user(data.date)} · ${data.company}`;

        const change = sales.change_percent;
        this.setKpi("sales", sales.today, value => this.money(value),
            change == null ? "" : `${change >= 0 ? "▲" : "▼"} ${Math.abs(change)}% vs. ayer`,
            change != null && change < 0 ? "is-down" : "is-up");
        this.setKpi("tables", tables.occupied, value => `${Math.round(value)} / ${tables.total}`,
            `${tables.occupied_percent}%`, "", tables.occupied_percent);
        this.setKpi("open", data.open_orders.count, Math.round, this.money(data.open_orders.amount), "is-neutral");
        this.setKpi("kitchen", kitchen.count, Math.round,
            kitchen.delayed ? `${kitchen.delayed} demorados` : "", "is-warning");
        this.setKpi("ticket", sales.average_ticket, value => this.money(value),
            `${sales.invoices} ${sales.invoices === 1 ? "factura" : "facturas"}`, "is-neutral");

        this.renderOccupancy(tables);
        this.renderChart(sales);
        this.renderTopItems(data.top_items);
        this.renderActivity(data.recent_activity);
        this.renderKitchen(kitchen);
        this.renderTables(data.pending_tables);
    }

    setKpi(key, value, format, badge, badgeClass = "", barPercent = null) {
        const node = this.root.querySelector(`[data-kpi="${key}"]`);
        this.countUp(node, key, value || 0, format);
        const badgeNode = this.root.querySelector(`[data-badge="${key}"]`);
        badgeNode.textContent = badge || "";
        badgeNode.className = `${badgeNode.className.split(" ")[0]} ${badgeClass}`;
        badgeNode.hidden = !badge;
        const bar = this.root.querySelector(`[data-bar="${key}"]`);
        if (bar) {
            bar.parentElement.hidden = barPercent === null;
            bar.style.width = `${Math.max(0, Math.min(100, barPercent || 0))}%`;
        }
    }

    countUp(node, key, target, format) {
        // Animate from the last shown value; users who prefer less motion see the final value directly.
        const start = this.shownValues[key] || 0;
        this.shownValues[key] = target;
        cancelAnimationFrame(node._rdFrame);
        if (start === target || window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
            node.textContent = format(target);
            return;
        }
        const began = performance.now();
        const step = now => {
            const progress = Math.min(1, (now - began) / 700);
            const eased = 1 - Math.pow(1 - progress, 3);
            node.textContent = format(start + (target - start) * eased);
            if (progress < 1) node._rdFrame = requestAnimationFrame(step);
        };
        node._rdFrame = requestAnimationFrame(step);
    }

    renderOccupancy(tables) {
        const donut = this.root.querySelector(".rd-donut");
        const total = tables.total || 1;
        donut.style.setProperty("--rd-occupied", `${tables.occupied / total * 100}%`);
        donut.style.setProperty("--rd-reserved", `${(tables.occupied + tables.reserved) / total * 100}%`);
        donut.setAttribute("aria-label", `${tables.occupied_percent}% de mesas ocupadas`);
        this.root.querySelector("[data-donut-percent]").textContent = `${tables.occupied_percent}%`;
        this.root.querySelector("[data-donut-label]").textContent = `${tables.occupied} de ${tables.total}`;
        ["occupied", "available", "reserved"].forEach(key => {
            this.root.querySelector(`[data-legend="${key}"]`).textContent = tables[key];
        });
    }

    renderChart(sales) {
        const container = this.root.querySelector(".rd-chart");
        const peak = this.root.querySelector("[data-peak]");
        const today = Object.fromEntries(sales.by_hour.map(row => [row.hour, row.total]));
        const yesterday = Object.fromEntries((sales.by_hour_yesterday || []).map(row => [row.hour, row.total]));
        const hours = Object.keys({ ...today, ...yesterday }).map(Number);
        if (!sales.by_hour.length) {
            container.innerHTML = '<p class="rd-empty">Todavía no hay ventas facturadas hoy.</p>';
            peak.hidden = true;
            this.chart = null;
            return;
        }
        const labels = [];
        const todayValues = [];
        const yesterdayValues = [];
        for (let hour = Math.min(...hours); hour <= Math.max(...hours); hour++) {
            labels.push(`${String(hour).padStart(2, "0")}:00`);
            todayValues.push(today[hour] || 0);
            yesterdayValues.push(yesterday[hour] || 0);
        }
        const best = sales.by_hour.reduce((top, row) => (row.total > top.total ? row : top));
        peak.textContent = `Hora pico: ${String(best.hour).padStart(2, "0")}:00`;
        peak.hidden = false;
        container.innerHTML = "";
        this.chart = new frappe.Chart(container, {
            type: "axis-mixed",
            height: 250,
            colors: ["#2f8500", "#002456"],
            data: {
                labels,
                datasets: [
                    { name: "Hoy", chartType: "bar", values: todayValues },
                    { name: "Ayer", chartType: "line", values: yesterdayValues },
                ],
            },
            barOptions: { spaceRatio: 0.35 },
            lineOptions: { dotSize: 4, regionFill: 0 },
            tooltipOptions: { formatTooltipY: value => this.money(value) },
        });
    }

    renderTopItems(rows) {
        const list = this.root.querySelector(".rd-top-list");
        if (!rows.length) {
            list.innerHTML = '<li class="rd-empty">Todavía no hay productos facturados hoy.</li>';
            return;
        }
        const max = Math.max(...rows.map(row => row.amount)) || 1;
        list.innerHTML = rows.map((row, index) => `
            <li>
                <span class="rd-rank">${index + 1}</span>
                <div class="rd-top-body">
                    <div class="rd-top-line"><strong>${this.escape(row.item_name)}</strong>
                        <span>${this.escape(this.money(row.amount))}</span></div>
                    <span class="rd-top-bar"><i style="width:${(row.amount / max * 100).toFixed(1)}%"></i></span>
                    <small>${this.escape(row.qty)} ${row.qty === 1 ? "unidad" : "unidades"}</small>
                </div>
            </li>`).join("");
    }

    renderActivity(rows) {
        this.root.querySelector(".rd-activity-list").innerHTML = rows.length ? rows.map(row => `
            <li><span class="rd-dot is-${this.escape(row.kind)}"></span><div><strong>${this.escape(row.event)}</strong>
                <small>${this.escape(row.reference)}${row.amount ? ` · ${this.escape(this.money(row.amount))}` : ""}</small></div>
                <time>Hace ${this.escape(this.minutes(row.minutes))}</time></li>`).join("")
            : '<li class="rd-empty">Sin movimientos todavía.</li>';
    }

    renderKitchen(kitchen) {
        this.root.querySelector('[data-table="kitchen"]').innerHTML = kitchen.orders.length ? kitchen.orders.map(row => {
            const state = row.delayed ? "Demorado" : row.kds_status;
            const stateClass = row.delayed ? "is-danger" : (row.kds_status === "Listo" ? "is-success" : "is-warning");
            return `<tr class="${row.delayed ? "rd-row-delayed" : ""}"><td><strong>${this.escape(row.name)}</strong></td>
                <td>${this.escape(RD_SERVICE_LABELS[row.service_type] || row.service_type)}</td>
                <td>${this.escape(row.reference)}</td><td>${this.escape(row.items)}</td>
                <td>${this.escape(this.minutes(row.minutes))}</td>
                <td><span class="rd-state ${stateClass}">${this.escape(state)}</span></td></tr>`;
        }).join("") : '<tr><td colspan="6" class="rd-empty">No hay pedidos en cocina.</td></tr>';
    }

    renderTables(rows) {
        this.root.querySelector('[data-table="tables"]').innerHTML = rows.length ? rows.map(row => `
            <tr><td><strong>${this.escape(row.table)}</strong></td><td>${this.escape(row.guests)}</td>
                <td>${this.escape(this.minutes(row.minutes))}</td><td>${this.escape(this.money(row.amount))}</td>
                <td><button type="button" class="btn btn-default btn-xs" data-route="Form/Restaurant Order/${this.escape(row.order)}">Ver cuenta</button></td></tr>`).join("")
            : '<tr><td colspan="5" class="rd-empty">No hay mesas con cuentas abiertas.</td></tr>';
    }
}
