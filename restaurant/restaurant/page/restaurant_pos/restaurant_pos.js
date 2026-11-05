/* Unified LEAF Restaurant Point of Sale (/app/restaurant-pos) */

frappe.pages["restaurant-pos"].on_page_load = function (wrapper) {
    wrapper.restaurant_pos = new LeafRestaurantPOS(wrapper);
};

frappe.pages["restaurant-pos"].on_page_show = function (wrapper) {
    wrapper.restaurant_pos.onShow();
};

class LeafRestaurantPOS {
    constructor(wrapper) {
        this.wrapper = wrapper;
        this.page = frappe.ui.make_app_page({
            parent: wrapper,
            title: "LEAF RESTAURANT",
            single_column: true,
        });
        this.page.main.empty();
        if (this.page.page_form) this.page.page_form.hide();
        $(wrapper).find(".page-head").hide();

        this.activeTab = "Caja";
        this.selectedAreaName = "";
        this.selectedCategory = "ALL";
        this.productSearch = "";
        this.orderSearch = "";
        this.orderStatusFilter = "En curso";
        this.orderServiceFilter = "ALL";
        this.selectedOrderPreviewName = "";

        this.numpadMode = "qty";
        this.numpadBuffer = "";
        this.selectedLineIndex = -1;

        this.bootstrap = null;
        this.currentOrder = this.createBlankOrder();
        this.darkMode = false;
        try {
            this.darkMode = window.localStorage?.getItem("rpos_dark_mode") === "1";
        } catch (e) {
            this.darkMode = false;
        }

        this.shell = document.createElement("div");
        this.shell.className = `rpos-shell${this.darkMode ? " is-dark-mode" : ""}`;
        this.page.main[0].appendChild(this.shell);
    }

    escape(value) {
        return frappe.utils.escape_html(String(value == null ? "" : value));
    }

    formatMoney(amount) {
        const num = Number(amount || 0);
        return "L " + num.toLocaleString("es-HN", {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2,
        });
    }

    createBlankOrder(overrides = {}) {
        const defaultCustomer = this.bootstrap?.customers?.[0] || {
            name: "CONSUMIDOR FINAL",
            customer_name: "CONSUMIDOR FINAL",
            tax_id: "",
        };
        const defaultWaiter = this.bootstrap?.waiters?.[0] || null;
        return {
            name: "",
            order_name: "",
            reference_note: "",
            status: "En curso",
            service_type: "Comer en el local",
            restaurant_area: this.selectedAreaName || "",
            restaurant_table: "",
            table_label: "",
            guests: 1,
            waiter: defaultWaiter ? defaultWaiter.name : "",
            waiter_name: defaultWaiter ? defaultWaiter.employee_name : "",
            customer: defaultCustomer.name,
            customer_name: defaultCustomer.customer_name || defaultCustomer.name,
            tax_id: defaultCustomer.tax_id || "",
            pos_profile: this.bootstrap?.opening_shift?.pos_profile || this.bootstrap?.pos_profiles?.[0]?.name || "",
            pos_opening_shift: this.bootstrap?.opening_shift?.name || "",
            selling_price_list: this.bootstrap?.pos_profiles?.[0]?.selling_price_list || "Venta estándar",
            kds_status: "Sin enviar",
            scheduled_time: "",
            customer_note: "",
            subtotal: 0,
            taxed_amount_15: 0,
            isv_15: 0,
            taxed_amount_18: 0,
            isv_18: 0,
            exempt_amount: 0,
            tax_amount: 0,
            tip_percentage: 0,
            tip_amount: 0,
            grand_total: 0,
            items: [],
            ...overrides,
        };
    }

    async onShow() {
        const routeOptions = frappe.route_options || {};
        frappe.route_options = null;
        if (Object.keys(routeOptions).length) this.pendingRouteOptions = routeOptions;
        if (this.loading) return;
        this.loading = true;
        this.showStartupState();
        try {
            await this.loadBootstrap();
            if (frappe.get_route()[0] !== "restaurant-pos") return;
            const options = this.pendingRouteOptions || {};
            this.pendingRouteOptions = null;
            if (options.tab && ["Mesas", "Caja", "Órdenes"].includes(options.tab)) {
                this.activeTab = options.tab;
            }
            if (options.area_name) this.selectedAreaName = options.area_name;
            if (options.order_name) {
                const existing = (this.bootstrap.orders || []).find(order => order.name === options.order_name);
                if (existing) this.loadOrderIntoCaja(existing);
            }
            this.render();
            if (!this.bootstrap.opening_shift) this.openShiftDialog();
            else if (options.open_new_account) this.openNewAccountModal();
        } catch (error) {
            if (frappe.get_route()[0] === "restaurant-pos") this.showStartupState(true);
        } finally {
            this.loading = false;
        }
    }

    showStartupState(failed = false) {
        this.shell.innerHTML = `
            <section class="rpos-startup" role="${failed ? "alert" : "status"}" aria-live="polite" aria-busy="${!failed}">
                <div class="rpos-startup-card">
                    <h1>${failed ? "No se pudo abrir el punto de venta" : "Cargando el punto de venta…"}</h1>
                    <p>${failed ? "Comprueba que el servidor esté disponible y vuelve a intentarlo. Tus órdenes guardadas se conservan." : "Preparando productos, mesas y turno de caja."}</p>
                    <div class="rpos-startup-actions">
                        ${failed ? '<button type="button" class="rpos-btn-green" data-startup-retry>Reintentar</button>' : ""}
                        <button type="button" class="rpos-btn-secondary" data-startup-back>Volver al restaurante</button>
                    </div>
                </div>
            </section>`;
        this.shell.querySelector("[data-startup-retry]")?.addEventListener("click", () => this.onShow());
        this.shell.querySelector("[data-startup-back]").addEventListener("click", () => {
            frappe.set_route("Workspaces", "Restaurante");
        });
    }

    async loadBootstrap() {
        const request = frappe.call({
            method: "restaurant.pos.get_pos_bootstrap",
            args: { area_name: this.selectedAreaName || null },
        });
        // Frappe v14 does not forward a timeout option from frappe.call to AJAX.
        let timer;
        let response;
        try {
            response = await Promise.race([
                request,
                new Promise((resolve, reject) => {
                    timer = setTimeout(() => {
                        reject(new Error("Restaurant POS startup timed out"));
                        request.abort?.();
                    }, 20000);
                }),
            ]);
        } finally {
            clearTimeout(timer);
        }
        if (!response?.message || ["items", "areas", "orders", "pos_profiles"].some(
            key => !Array.isArray(response.message[key])
        )) {
            throw new Error("Restaurant POS bootstrap data is incomplete");
        }
        this.bootstrap = response.message;
        if (!this.selectedAreaName && this.bootstrap.areas?.length) {
            this.selectedAreaName = this.bootstrap.areas[0].name;
        }
        if (!this.currentOrder.customer && this.bootstrap.customers?.length) {
            const c = this.bootstrap.customers[0];
            this.currentOrder.customer = c.name;
            this.currentOrder.customer_name = c.customer_name || c.name;
            this.currentOrder.tax_id = c.tax_id || "";
        }
        if (this.currentOrder.name) {
            const refreshed = (this.bootstrap.orders || []).find(o => o.name === this.currentOrder.name);
            if (refreshed && refreshed.status === "En curso") {
                this.currentOrder = JSON.parse(JSON.stringify(refreshed));
            }
        }
    }

    recalculateLocalTotals() {
        let subtotal = 0;
        let taxed15 = 0;
        let isv15 = 0;
        let taxed18 = 0;
        let isv18 = 0;
        let exempt = 0;

        (this.currentOrder.items || []).forEach(row => {
            const qty = Math.max(0.01, Number(row.qty || 1));
            const baseRate = Math.max(0, Number(row.base_rate ?? row.rate ?? 0));
            const optRate = Math.max(0, Number(row.options_rate || 0));
            const disc = Math.min(100, Math.max(0, Number(row.discount_percentage || 0)));
            const unitRate = Number(((baseRate + optRate) * (1 - disc / 100)).toFixed(2));
            const amount = Number((qty * unitRate).toFixed(2));
            row.qty = qty;
            row.base_rate = baseRate;
            row.options_rate = optRate;
            row.discount_percentage = disc;
            row.rate = unitRate;
            row.amount = amount;

            const taxRate = Number(row.tax_rate ?? 15);
            subtotal += amount;
            if (Math.abs(taxRate - 15) < 0.01) {
                taxed15 += amount;
                isv15 += Number((amount * 0.15).toFixed(2));
            } else if (Math.abs(taxRate - 18) < 0.01) {
                taxed18 += amount;
                isv18 += Number((amount * 0.18).toFixed(2));
            } else {
                exempt += amount;
            }
        });

        this.currentOrder.subtotal = Number(subtotal.toFixed(2));
        this.currentOrder.taxed_amount_15 = Number(taxed15.toFixed(2));
        this.currentOrder.isv_15 = Number(isv15.toFixed(2));
        this.currentOrder.taxed_amount_18 = Number(taxed18.toFixed(2));
        this.currentOrder.isv_18 = Number(isv18.toFixed(2));
        this.currentOrder.exempt_amount = Number(exempt.toFixed(2));
        this.currentOrder.tax_amount = Number((isv15 + isv18).toFixed(2));

        const tipPct = Math.max(0, Number(this.currentOrder.tip_percentage || 0));
        if (tipPct > 0) {
            this.currentOrder.tip_amount = Number((this.currentOrder.subtotal * (tipPct / 100)).toFixed(2));
        } else {
            this.currentOrder.tip_amount = Math.max(0, Number(this.currentOrder.tip_amount || 0));
        }
        this.currentOrder.grand_total = Number(
            (this.currentOrder.subtotal + this.currentOrder.tax_amount + this.currentOrder.tip_amount).toFixed(2)
        );
    }

    brandLeafLogoHtml() {
        const rawLogoSrc =
            document.querySelector(".navbar-brand .app-logo")?.getAttribute("src") ||
            frappe.boot?.app_logo_url ||
            "";
        const isDefaultFrappeLogo =
            !rawLogoSrc || rawLogoSrc.includes("frappe-framework-logo");
        const leafSvg = `
            <svg class="rpos-brand-leaf-svg" viewBox="0 0 36 36" width="28" height="28" xmlns="http://www.w3.org/2000/svg">
                <path d="M5 6 C18 5 28 11 30 24 C17 26 8 18 5 6 Z" fill="#4cbb17" stroke="#0f172a" stroke-width="2.2" stroke-linejoin="round"/>
                <path d="M5 6 C14 14 22 20 31 30" fill="none" stroke="#0f172a" stroke-width="2.2" stroke-linecap="round"/>
                <path d="M13 13 L20 11 M17 17 L24 15 M14 15 L12 21 M19 19 L17 24" fill="none" stroke="#0f172a" stroke-width="1.7" stroke-linecap="round"/>
            </svg>
        `;
        if (!isDefaultFrappeLogo) {
            return `
                <img class="rpos-brand-logo-img" src="${this.escape(rawLogoSrc)}" alt="LEAF" onerror="this.style.display='none';this.nextElementSibling.style.display='block';">
                <span style="display:none;">${leafSvg}</span>
            `;
        }
        return leafSvg;
    }

    render() {
        this.recalculateLocalTotals();
        this.shell.classList.toggle("is-dark-mode", Boolean(this.darkMode));
        const cashierName = this.bootstrap?.cashier?.full_name || frappe.session.user;
        const avatarChar = (cashierName || "C").trim().charAt(0).toUpperCase();
        const shiftBadge = this.bootstrap?.opening_shift
            ? `Turno: ${this.escape(this.bootstrap.opening_shift.pos_profile)}`
            : "Sin turno abierto";
        const pillLabel = this.currentOrder.table_label
            ? `Mesa ${this.escape(this.currentOrder.table_label)} · ${this.escape(this.currentOrder.order_name || "En curso")}`
            : (this.currentOrder.order_name
                ? `${this.escape(this.currentOrder.order_name)} (${this.escape(this.currentOrder.service_type)})`
                : "Venta directa");

        this.shell.innerHTML = `
            <header class="rpos-topbar">
                <div class="rpos-topbar-left">
                    <nav class="rpos-nav-tabs" aria-label="Navegación POS">
                        <button type="button" class="rpos-nav-tab ${this.activeTab === "Mesas" ? "is-active" : ""}" data-nav="Mesas">Mesas</button>
                        <button type="button" class="rpos-nav-tab ${this.activeTab === "Caja" ? "is-active" : ""}" data-nav="Caja">Caja</button>
                        <button type="button" class="rpos-nav-tab ${this.activeTab === "Órdenes" ? "is-active" : ""}" data-nav="Órdenes">Órdenes</button>
                    </nav>
                    ${this.activeTab !== "Mesas" ? `
                        <button type="button" class="rpos-service-pill" data-service="${this.escape(this.currentOrder.service_type)}" data-action="open-preset" title="Cambiar modalidad o cuenta">
                            <span>${pillLabel}</span>
                        </button>
                    ` : ""}
                </div>

                <div class="rpos-brand">
                    <span class="rpos-brand-leaf" aria-hidden="true">
                        ${this.brandLeafLogoHtml()}
                    </span>
                    <span class="rpos-brand-title">LEAF RESTAURANT</span>
                </div>

                <div class="rpos-topbar-right">
                    ${this.activeTab === "Caja" ? `
                        <div class="rpos-search-box">
                            <span class="rpos-search-icon">🔍</span>
                            <input type="search" class="rpos-prod-search" placeholder="Buscar producto..." value="${this.escape(this.productSearch)}">
                        </div>
                    ` : ""}
                    <button type="button" class="rpos-cashier-chip" data-action="shift-info" title="${this.escape(shiftBadge)}">
                        <span class="rpos-cashier-avatar">${this.escape(avatarChar)}</span>
                        <span>${this.escape(cashierName)}</span>
                    </button>
                    <button type="button" class="rpos-icon-btn" data-action="open-kds" title="Cocina KDS">🍳</button>
                    <button type="button" class="rpos-icon-btn" data-action="pos-menu" title="Opciones del Punto de Venta">☰</button>
                </div>
            </header>
            ${this.renderActiveView()}
        `;

        this.bindEvents();
    }

    renderActiveView() {
        if (this.activeTab === "Mesas") return this.renderMesasView();
        if (this.activeTab === "Órdenes") return this.renderOrdenesView();
        return this.renderCajaView();
    }

    backgroundClass(bgName) {
        const bgMap = {
            "Madera cálida": "bg-warm-wood",
            "Cerámica clara": "bg-light-tile",
            "Madera gris": "bg-grey-wood",
            "Césped": "bg-grass",
        };
        return bgMap[bgName] || "bg-warm-wood";
    }

    shapeToTableSubtype(shape) {
        if (shape === "Redonda") return "table_round_wood";
        if (shape === "Rectangular") return "table_rect_wood";
        if (shape === "Ovalada") return "table_oval_wood";
        return "table_square_wood";
    }

    elementArtwork(subtype, customLabel = "Zona") {
        switch (subtype) {
            case "table_square_wood":
                return `<svg viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg">
                    <rect x="4" y="4" width="92" height="92" rx="5" fill="#c88a4b" stroke="#8c5828" stroke-width="3"/>
                    <line x1="6" y1="26" x2="94" y2="26" stroke="#b07339" stroke-width="1.5"/>
                    <line x1="6" y1="50" x2="94" y2="50" stroke="#b07339" stroke-width="1.5"/>
                    <line x1="6" y1="74" x2="94" y2="74" stroke="#b07339" stroke-width="1.5"/>
                </svg>`;
            case "table_round_wood":
                return `<svg viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg">
                    <circle cx="50" cy="50" r="45" fill="#cf8f3f" stroke="#8c5828" stroke-width="3"/>
                    <circle cx="50" cy="50" r="38" fill="none" stroke="#b5772d" stroke-width="1.4" opacity=".65"/>
                </svg>`;
            case "table_rect_wood":
                return `<svg viewBox="0 0 140 90" xmlns="http://www.w3.org/2000/svg">
                    <rect x="4" y="5" width="132" height="80" rx="6" fill="#c88a4b" stroke="#8c5828" stroke-width="3"/>
                    <line x1="6" y1="28" x2="134" y2="28" stroke="#b07339" stroke-width="1.5"/>
                    <line x1="6" y1="50" x2="134" y2="50" stroke="#b07339" stroke-width="1.5"/>
                    <line x1="6" y1="68" x2="134" y2="68" stroke="#b07339" stroke-width="1.5"/>
                </svg>`;
            case "table_oval_wood":
                return `<svg viewBox="0 0 140 90" xmlns="http://www.w3.org/2000/svg">
                    <rect x="4" y="6" width="132" height="78" rx="39" fill="#cf8f3f" stroke="#8c5828" stroke-width="3"/>
                    <rect x="14" y="14" width="112" height="62" rx="31" fill="none" stroke="#b5772d" stroke-width="1.5"/>
                </svg>`;
            case "table_court_blue":
                return `<svg viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg">
                    <rect x="3" y="3" width="94" height="94" rx="4" fill="#5da6db" stroke="#296fa3" stroke-width="3"/>
                    <rect x="10" y="14" width="80" height="72" fill="none" stroke="#fff" stroke-width="1.8"/>
                    <line x1="50" y1="14" x2="50" y2="86" stroke="#fff" stroke-width="1.6"/>
                    <line x1="3" y1="50" x2="97" y2="50" stroke="#1e3a5f" stroke-width="2"/>
                </svg>`;
            case "table_court_soccer":
                return `<svg viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg">
                    <rect x="3" y="3" width="94" height="94" rx="4" fill="#1aa31a" stroke="#0f690f" stroke-width="3"/>
                    <rect x="8" y="8" width="84" height="84" fill="none" stroke="#fff" stroke-width="1.8"/>
                    <line x1="8" y1="50" x2="92" y2="50" stroke="#fff" stroke-width="1.8"/>
                    <circle cx="50" cy="50" r="14" fill="none" stroke="#fff" stroke-width="1.8"/>
                    <rect x="28" y="8" width="44" height="16" fill="none" stroke="#fff" stroke-width="1.6"/>
                    <rect x="28" y="76" width="44" height="16" fill="none" stroke="#fff" stroke-width="1.6"/>
                </svg>`;
            case "table_court_basket":
                return `<svg viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg">
                    <rect x="3" y="3" width="94" height="94" rx="4" fill="#f3a847" stroke="#b96d16" stroke-width="3"/>
                    <rect x="8" y="8" width="84" height="84" fill="none" stroke="#fff" stroke-width="1.8"/>
                    <line x1="8" y1="50" x2="92" y2="50" stroke="#fff" stroke-width="1.8"/>
                    <circle cx="50" cy="50" r="12" fill="#d97724" stroke="#fff" stroke-width="1.8"/>
                    <path d="M22 8 A28 28 0 0 0 78 8" fill="none" stroke="#fff" stroke-width="1.6"/>
                    <path d="M22 92 A28 28 0 0 1 78 92" fill="none" stroke="#fff" stroke-width="1.6"/>
                </svg>`;
            case "chair_wood":
                return `<svg viewBox="0 0 60 60" xmlns="http://www.w3.org/2000/svg">
                    <path d="M10 12 Q30 4 50 12 L48 20 Q30 14 12 20 Z" fill="#8b6239" stroke="#5b3e21" stroke-width="2"/>
                    <rect x="13" y="20" width="34" height="30" rx="5" fill="#7c7d82" stroke="#52525b" stroke-width="2"/>
                </svg>`;
            case "chair_armchair_red":
                return `<svg viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg">
                    <path d="M10 46 C6 20 20 8 32 8 C44 8 58 20 54 46 Z" fill="#dc2626" stroke="#991b1b" stroke-width="2.5"/>
                    <ellipse cx="32" cy="36" rx="15" ry="13" fill="#f87171" stroke="#b91c1c" stroke-width="1.5"/>
                </svg>`;
            case "chair_stool_orange":
                return `<svg viewBox="0 0 56 56" xmlns="http://www.w3.org/2000/svg">
                    <circle cx="28" cy="28" r="20" fill="#fb923c" stroke="#c2410c" stroke-width="2.5"/>
                    <circle cx="28" cy="28" r="13" fill="#fdba74"/>
                </svg>`;
            case "decor_palm":
                return `<svg viewBox="0 0 90 90" xmlns="http://www.w3.org/2000/svg">
                    <circle cx="45" cy="45" r="14" fill="#1f2937" stroke="#78350f" stroke-width="3"/>
                    <g stroke="#2d5a18" stroke-width="2" fill="#4d7c0f">
                        <path d="M45 45 C25 20 10 22 6 12 C22 10 35 20 45 45 Z"/>
                        <path d="M45 45 C65 18 80 20 84 10 C68 8 55 18 45 45 Z"/>
                        <path d="M45 45 C20 55 8 70 10 82 C24 76 36 62 45 45 Z"/>
                        <path d="M45 45 C70 55 82 70 80 82 C66 76 54 62 45 45 Z"/>
                        <path d="M45 45 C42 15 48 6 45 3 C52 15 50 28 45 45 Z"/>
                    </g>
                </svg>`;
            case "decor_fern":
                return `<svg viewBox="0 0 80 80" xmlns="http://www.w3.org/2000/svg">
                    <g fill="#15803d" stroke="#14532d" stroke-width="1.4">
                        <ellipse cx="40" cy="40" rx="8" ry="30" transform="rotate(0 40 40)"/>
                        <ellipse cx="40" cy="40" rx="8" ry="30" transform="rotate(45 40 40)"/>
                        <ellipse cx="40" cy="40" rx="8" ry="30" transform="rotate(90 40 40)"/>
                        <ellipse cx="40" cy="40" rx="8" ry="30" transform="rotate(135 40 40)"/>
                    </g>
                    <circle cx="40" cy="40" r="7" fill="#22c55e"/>
                </svg>`;
            case "decor_wall_h":
                return `<svg viewBox="0 0 160 24" xmlns="http://www.w3.org/2000/svg">
                    <rect x="2" y="6" width="156" height="12" rx="3" fill="#1e293b" stroke="#fff" stroke-width="1.5"/>
                </svg>`;
            case "decor_wall_v":
                return `<svg viewBox="0 0 24 160" xmlns="http://www.w3.org/2000/svg">
                    <rect x="6" y="2" width="12" height="156" rx="3" fill="#1e293b" stroke="#fff" stroke-width="1.5"/>
                </svg>`;
            case "decor_wall_corner":
                return `<svg viewBox="0 0 90 90" xmlns="http://www.w3.org/2000/svg">
                    <path d="M8 8 H82 V22 H22 V82 H8 Z" fill="#1e293b" stroke="#fff" stroke-width="1.5"/>
                </svg>`;
            case "decor_door":
                return `<svg viewBox="0 0 90 90" xmlns="http://www.w3.org/2000/svg">
                    <line x1="12" y1="10" x2="12" y2="80" stroke="#111827" stroke-width="4"/>
                    <line x1="12" y1="80" x2="80" y2="80" stroke="#111827" stroke-width="2.5"/>
                    <path d="M80 80 A68 68 0 0 0 12 12" fill="none" stroke="#111827" stroke-width="2" stroke-dasharray="4 4"/>
                </svg>`;
            case "decor_restroom":
                return `<svg viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg">
                    <rect x="4" y="4" width="56" height="56" rx="10" fill="#1e293b" stroke="#e2e8f0" stroke-width="2"/>
                    <circle cx="22" cy="18" r="5" fill="#fff"/>
                    <path d="M16 26 H28 V40 H25 V50 H19 V40 H16 Z" fill="#fff"/>
                    <circle cx="43" cy="18" r="5" fill="#fff"/>
                    <path d="M37 26 H49 L52 40 H46 V50 H40 V40 H34 Z" fill="#fff"/>
                </svg>`;
            case "decor_label":
                return `<svg viewBox="0 0 140 46" xmlns="http://www.w3.org/2000/svg">
                    <rect x="2" y="4" width="136" height="38" rx="8" fill="#0f172a" fill-opacity=".78" stroke="#fff" stroke-width="1.5"/>
                    <text x="70" y="28" text-anchor="middle" fill="#fff" font-size="14" font-weight="700" font-family="sans-serif">${this.escape(customLabel || "Zona")}</text>
                </svg>`;
            default:
                return "";
        }
    }

    renderTableMapOverlay(tbl, fallbackLabel = "M") {
        if (!tbl || !tbl.name) {
            return `
                <button type="button" class="rtm-assign-btn" data-action="open-map-designer">
                    ASIGNAR MESA
                </button>
            `;
        }
        const status = tbl.status || "Disponible";
        const seats = Number(tbl.seats) || 4;
        const live = tbl.active_order;
        const liveDetail = live ? ` · ${this.formatMoney(live.grand_total)}` : "";
        return `
            <button type="button"
                class="rtm-assign-btn is-assigned status-${this.escape(status)}"
                data-action="click-map-table"
                data-table="${this.escape(tbl.name)}"
                data-status="${this.escape(status)}">
                MESA ${this.escape(tbl.table_number || fallbackLabel)}
                <small>${seats} asientos · ${this.escape(status)}${liveDetail}</small>
            </button>
        `;
    }

    renderMesasView() {
        const allAreas = this.bootstrap?.areas || [];
        const activeAreas = allAreas.filter(
            a => (Array.isArray(a.elements) && a.elements.length > 0) || (Array.isArray(a.tables) && a.tables.length > 0)
        );
        const areas = activeAreas.length ? activeAreas : allAreas;
        const currentArea = areas.find(a => a.name === this.selectedAreaName) || areas[0] || null;
        if (currentArea && currentArea.name !== this.selectedAreaName) {
            this.selectedAreaName = currentArea.name;
        }
        const areaTables = currentArea?.tables || [];
        const tablesByName = {};
        areaTables.forEach(t => {
            tablesByName[t.name] = t;
        });

        const elements = currentArea?.elements || [];
        let floorItemsHtml = "";

        if (elements.length) {
            const refW = Math.max(960, ...elements.map(e => (Number(e.x) || 0) + (Number(e.width) || 90) + 40));
            const refH = Math.max(540, ...elements.map(e => (Number(e.y) || 0) + (Number(e.height) || 90) + 40));
            floorItemsHtml = elements.map(el => {
                const isTable = el.category === "tables";
                const tbl = isTable && el.table_name ? tablesByName[el.table_name] : null;
                const overlayHtml = isTable ? this.renderTableMapOverlay(tbl, el.label || "?") : "";
                const clickAttrs = (isTable && tbl?.name)
                    ? `data-action="click-map-table" data-table="${this.escape(tbl.name)}" data-status="${this.escape(tbl.status || "Disponible")}"`
                    : "";
                const leftPct = (((Number(el.x) || 0) / refW) * 100).toFixed(2);
                const topPct = (((Number(el.y) || 0) / refH) * 100).toFixed(2);
                const widthPct = (((Number(el.width) || 90) / refW) * 100).toFixed(2);
                const heightPct = (((Number(el.height) || 90) / refH) * 100).toFixed(2);
                return `
                    <div class="rtm-element ${isTable ? "is-table-el" : "is-decor-el"}"
                         data-element-id="${this.escape(el.id || "")}"
                         ${clickAttrs}
                         style="left:${leftPct}%;top:${topPct}%;width:${widthPct}%;height:${heightPct}%;">
                        <div class="rtm-element-art" style="transform:rotate(${Number(el.rotation) || 0}deg)">
                            ${this.elementArtwork(el.subtype, el.label)}
                        </div>
                        ${overlayHtml}
                    </div>
                `;
            }).join("");
        } else if (areaTables.length) {
            const refW = 960;
            const refH = 540;
            floorItemsHtml = areaTables.map((tbl, idx) => {
                const col = idx % 4;
                const row = Math.floor(idx / 4);
                const x = Number(tbl.pos_x) > 0 ? Number(tbl.pos_x) : (70 + col * 210);
                const y = Number(tbl.pos_y) > 0 ? Number(tbl.pos_y) : (70 + row * 170);
                const w = Number(tbl.width) > 0 ? Number(tbl.width) : (tbl.shape === "Rectangular" || tbl.shape === "Ovalada" ? 136 : 98);
                const h = Number(tbl.height) > 0 ? Number(tbl.height) : 94;
                const subtype = this.shapeToTableSubtype(tbl.shape);
                const leftPct = ((x / refW) * 100).toFixed(2);
                const topPct = ((y / refH) * 100).toFixed(2);
                const widthPct = ((w / refW) * 100).toFixed(2);
                const heightPct = ((h / refH) * 100).toFixed(2);
                return `
                    <div class="rtm-element is-table-el"
                         data-action="click-map-table"
                         data-table="${this.escape(tbl.name)}"
                         data-status="${this.escape(tbl.status || "Disponible")}"
                         style="left:${leftPct}%;top:${topPct}%;width:${widthPct}%;height:${heightPct}%;">
                        <div class="rtm-element-art" style="transform:rotate(${Number(tbl.rotation) || 0}deg)">
                            ${this.elementArtwork(subtype, tbl.table_number)}
                        </div>
                        ${this.renderTableMapOverlay(tbl, tbl.table_number)}
                    </div>
                `;
            }).join("");
        } else {
            floorItemsHtml = `<div style="position:absolute;inset:0;display:flex;align-items:center;justify-content:center;color:#1e293b;font-weight:700;font-size:16px;">Esta área aún no tiene mesas registradas en el Mapa de Mesas.</div>`;
        }

        const bgClass = this.backgroundClass(currentArea?.floor_background);

        return `
            <div class="rpos-subbar">
                <div class="rpos-subbar-left">
                    <button type="button" class="rpos-btn-new-order" data-action="new-order-modal">
                        <span>+ Nueva orden</span>
                    </button>
                </div>
                <div class="rpos-area-tabs" role="tablist" aria-label="Áreas en uso">
                    ${areas.map(a => `
                        <button type="button" class="rpos-area-tab ${a.name === currentArea?.name ? "is-active" : ""}" data-area="${this.escape(a.name)}">
                            ${this.escape(a.area_name)}
                        </button>
                    `).join("")}
                </div>
                <div class="rpos-subbar-right">
                    <button type="button" class="rpos-area-tab rpos-subbar-icon-btn" data-action="open-map-designer" title="Editar Mapa de Mesas">✎</button>
                    <button type="button" class="rpos-area-tab rpos-subbar-icon-btn" data-action="quick-table-number" title="Buscar mesa por número">#</button>
                </div>
            </div>
            <div class="rpos-floor-wrap">
                <div class="rtm-canvas ${bgClass}" data-role="canvas" data-bg="${this.escape(currentArea?.floor_background || "Madera cálida")}">
                    ${floorItemsHtml}
                </div>
            </div>
        `;
    }

    renderCajaView() {
        const categories = this.bootstrap?.categories || [];
        const allItems = this.bootstrap?.items || [];
        const search = (this.productSearch || "").trim().toLowerCase();

        const filteredItems = allItems.filter(it => {
            if (this.selectedCategory !== "ALL" && it.item_group !== this.selectedCategory) {
                return false;
            }
            if (search) {
                const hay = `${it.item_name} ${it.item_code} ${it.description || ""}`.toLowerCase();
                return hay.includes(search);
            }
            return true;
        });

        const qtyByItem = {};
        (this.currentOrder.items || []).forEach(line => {
            qtyByItem[line.item_code] = (qtyByItem[line.item_code] || 0) + Number(line.qty || 0);
        });

        const presetClass =
            this.currentOrder.service_type === "Para llevar"
                ? "is-preset-takeout"
                : this.currentOrder.service_type === "Entrega"
                    ? "is-preset-delivery"
                    : "is-preset-local";
        const presetLabel =
            this.currentOrder.service_type === "Para llevar"
                ? "Para llevar"
                : this.currentOrder.service_type === "Entrega"
                    ? "Entrega"
                    : "Comer en el local";

        const rawCustName = (this.currentOrder.customer_name || "").trim();
        const customerBtnLabel = (!rawCustName || rawCustName.toUpperCase() === "CONSUMIDOR FINAL")
            ? "Cliente"
            : rawCustName;
        const pendingCommandCount = (this.currentOrder.items || []).filter(
            row => (row.kds_status || "Pendiente") === "Pendiente"
        ).length;

        return `
            <div class="rpos-caja-body">
                <!-- Left Ticket & Controls -->
                <aside class="rpos-ticket-pane">
                    <div class="rpos-ticket-header">
                        <div>
                            <strong>${this.escape(this.currentOrder.order_name || "Cuenta sin nombre")}</strong>
                            ${this.currentOrder.reference_note ? `<span> · Ref: ${this.escape(this.currentOrder.reference_note)}</span>` : ""}
                        </div>
                        <div>
                            ${this.currentOrder.waiter_name ? `<span>Mesero: ${this.escape(this.currentOrder.waiter_name)}</span>` : `<span>Sin mesero</span>`}
                        </div>
                    </div>

                    <div class="rpos-ticket-lines">
                        ${this.currentOrder.items.length ? this.currentOrder.items.map((line, idx) => `
                            <div class="rpos-line ${idx === this.selectedLineIndex ? "is-selected" : ""}" data-line-idx="${idx}">
                                <div class="rpos-line-main">
                                    <span class="rpos-line-qty">${Number(line.qty).toLocaleString("es-HN")}</span>
                                    <span class="rpos-line-name">${this.escape(line.item_name)}</span>
                                    <span class="rpos-line-amount">${this.formatMoney(line.amount)}</span>
                                </div>
                                ${line.discount_percentage > 0 ? `<div class="rpos-line-sub">Descuento: ${line.discount_percentage}%</div>` : ""}
                                ${(line.selected_options || []).map(opt => `
                                    <div class="rpos-line-sub">- ${this.escape(opt.option_label)}${Number(opt.additional_amount) > 0 ? ` (+${this.formatMoney(opt.additional_amount)})` : ""}</div>
                                `).join("")}
                                ${(!line.selected_options?.length && line.options_summary) ? `<div class="rpos-line-sub">- ${this.escape(line.options_summary)}</div>` : ""}
                                ${line.note ? `<div class="rpos-line-note">${this.escape(line.note)}</div>` : ""}
                            </div>
                        `).join("") : `
                            <div class="rpos-ticket-empty">
                                <div style="font-size:28px;margin-bottom:8px;">🍽️</div>
                                <div>Selecciona platillos o bebidas a la derecha para agregarlos a la cuenta.</div>
                            </div>
                        `}
                    </div>

                    <div class="rpos-totals-box">
                        <div class="rpos-totals-row">
                            <span>Subtotal</span>
                            <span>${this.formatMoney(this.currentOrder.subtotal)}</span>
                        </div>
                        <div class="rpos-totals-row">
                            <span>Impuestos (ISV)</span>
                            <span>${this.formatMoney(this.currentOrder.tax_amount)}</span>
                        </div>
                        <div class="rpos-totals-row is-tip" data-action="open-tip-modal" title="Clic para configurar Servicio sugerido o Propina">
                            <span>Servicio sugerido / Propina ${this.currentOrder.tip_percentage > 0 ? `(${this.currentOrder.tip_percentage}%)` : ""} ✎</span>
                            <span>${this.formatMoney(this.currentOrder.tip_amount)}</span>
                        </div>
                        <div class="rpos-totals-row is-grand">
                            <span>Total</span>
                            <span>${this.formatMoney(this.currentOrder.grand_total)}</span>
                        </div>
                    </div>

                    <div class="rpos-controls-grid">
                        <button type="button" class="rpos-ctrl-btn" data-action="open-customer-modal" title="Cliente: ${this.escape(this.currentOrder.customer_name)} (RTN: ${this.escape(this.currentOrder.tax_id || "N/A")})">
                            ${this.escape(customerBtnLabel)}
                        </button>
                        <button type="button" class="rpos-ctrl-btn" data-action="open-note-modal" title="Agregar comentario o nota al platillo seleccionado">
                            Nota
                        </button>
                        <button type="button" class="rpos-ctrl-btn ${presetClass}" data-action="open-preset" title="Seleccionar modalidad de operación">
                            ${this.escape(presetLabel)}
                        </button>
                        <button type="button" class="rpos-ctrl-btn is-command ${pendingCommandCount ? "has-pending" : ""}" data-action="send-kitchen" title="Comandar: enviar platillos pendientes a cocina o barra">
                            🖨 Comandar${pendingCommandCount ? ` (${pendingCommandCount})` : ""}
                        </button>
                        <button type="button" class="rpos-ctrl-btn" data-action="open-precuenta" title="Imprimir o visualizar Pre-cuenta para el cliente">
                            Precuenta
                        </button>
                        <button type="button" class="rpos-ctrl-btn" data-action="open-actions-modal" title="Más acciones de la orden">
                            ⋮
                        </button>
                    </div>

                    <div class="rpos-numpad">
                        <button type="button" class="rpos-key" data-key="1">1</button>
                        <button type="button" class="rpos-key" data-key="2">2</button>
                        <button type="button" class="rpos-key" data-key="3">3</button>
                        <button type="button" class="rpos-key ${this.numpadMode === "qty" ? "is-mode-active" : ""}" data-mode="qty">Cant.</button>
                        <button type="button" class="rpos-key" data-key="4">4</button>
                        <button type="button" class="rpos-key" data-key="5">5</button>
                        <button type="button" class="rpos-key" data-key="6">6</button>
                        <button type="button" class="rpos-key ${this.numpadMode === "disc" ? "is-mode-active" : ""}" data-mode="disc">%</button>
                        <button type="button" class="rpos-key" data-key="7">7</button>
                        <button type="button" class="rpos-key" data-key="8">8</button>
                        <button type="button" class="rpos-key" data-key="9">9</button>
                        <button type="button" class="rpos-key ${this.numpadMode === "price" ? "is-mode-active" : ""}" data-mode="price">Precio</button>
                        <button type="button" class="rpos-key is-sign" data-key="+/-">+/-</button>
                        <button type="button" class="rpos-key" data-key="0">0</button>
                        <button type="button" class="rpos-key is-decimal" data-key=".">,</button>
                        <button type="button" class="rpos-key is-back" data-key="BACK">⌫</button>
                    </div>

                    <div class="rpos-bottom-actions">
                        <button type="button" class="rpos-bottom-btn is-plum" data-action="assign-table">
                            <span>Asignar</span>
                            <span>mesa</span>
                        </button>
                        <button type="button" class="rpos-bottom-btn is-plum" data-action="assign-account">
                            <span>Asignar</span>
                            <span>cuenta</span>
                        </button>
                        <button type="button" class="rpos-bottom-btn is-pay ${this.currentOrder.items.length ? "has-items" : ""}" data-action="open-payment-modal">
                            <span>Pago</span>
                        </button>
                    </div>
                </aside>

                <!-- Right Categories & Products -->
                <section class="rpos-catalog-pane">
                    <div class="rpos-categories-bar">
                        <button type="button"
                                class="rpos-cat-card ${this.selectedCategory === "ALL" ? "is-active" : ""}"
                                data-cat="ALL"
                                style="background:#e2e8f0;color:#0f172a;">
                            <span>Todos</span>
                        </button>
                        ${categories.map(cat => `
                            <button type="button"
                                    class="rpos-cat-card ${this.selectedCategory === cat.name ? "is-active" : ""}"
                                    data-cat="${this.escape(cat.name)}"
                                    style="background:${this.escape(cat.color || "#2F8500")};">
                                ${cat.image ? `<img class="rpos-cat-photo" src="${this.escape(cat.image)}" alt="${this.escape(cat.label)}">` : ""}
                                <span>${this.escape(cat.label)}</span>
                            </button>
                        `).join("")}
                    </div>

                    <div class="rpos-products-grid">
                        ${filteredItems.map(item => {
                            const inCartQty = qtyByItem[item.item_code] || 0;
                            const hasPhoto = Boolean(item.image);
                            return `
                                <div class="rpos-prod-card ${hasPhoto ? "has-photo" : ""}"
                                     data-item-code="${this.escape(item.item_code)}"
                                     style="border-bottom-color:${this.escape(item.color || "#EC4899")};">
                                    ${hasPhoto ? `
                                        <img class="rpos-prod-photo" src="${this.escape(item.image)}" alt="${this.escape(item.item_name)}">
                                        <div class="rpos-prod-photo-overlay">
                                            <div class="rpos-prod-title">${this.escape(item.item_name)}</div>
                                            <div class="rpos-prod-price">${this.formatMoney(item.price)}</div>
                                        </div>
                                    ` : `
                                        <div class="rpos-prod-title">${this.escape(item.item_name)}</div>
                                        <div class="rpos-prod-price">${this.formatMoney(item.price)}</div>
                                    `}
                                    ${inCartQty > 0 ? `<span class="rpos-prod-qty-badge">${Number(inCartQty).toLocaleString("es-HN")}</span>` : ""}
                                </div>
                            `;
                        }).join("")}
                    </div>
                </section>
            </div>
        `;
    }

    formatOrderDateTime(creationStr) {
        if (!creationStr) return { dateLabel: "Hoy", timeLabel: "" };
        const raw = String(creationStr).trim();
        const [datePart, timePart = ""] = raw.split(" ");
        const [yyyy, mm, dd] = (datePart || "").split("-");
        const todayIso = new Date().toISOString().slice(0, 10);
        const dateLabel = datePart === todayIso
            ? "Hoy"
            : (dd && mm && yyyy ? `${dd}/${mm}/${yyyy}` : (datePart || "Hoy"));
        const timeLabel = timePart.slice(0, 5);
        return { dateLabel, timeLabel };
    }

    renderOrdenesView() {
        const orders = this.bootstrap?.orders || [];
        const q = (this.orderSearch || "").trim().toLowerCase();

        const filtered = orders.filter(ord => {
            if (this.orderStatusFilter !== "ALL" && ord.status !== this.orderStatusFilter) {
                return false;
            }
            if (this.orderServiceFilter !== "ALL" && ord.service_type !== this.orderServiceFilter) {
                return false;
            }
            if (q) {
                const hay = `${ord.name} ${ord.order_name} ${ord.reference_note} ${ord.customer_name} ${ord.waiter_name} ${ord.table_label}`.toLowerCase();
                return hay.includes(q);
            }
            return true;
        });

        const selectedOrd = this.selectedOrderPreviewName
            ? (filtered.find(o => o.name === this.selectedOrderPreviewName) || null)
            : null;
        if (!selectedOrd && this.selectedOrderPreviewName) {
            this.selectedOrderPreviewName = "";
        }

        const totalFiltered = filtered.length;
        const rangeLabel = totalFiltered ? `1-${totalFiltered} / ${totalFiltered}` : `0-0 / 0`;

        return `
            <div class="rpos-orders-view">
                <div class="rpos-orders-main">
                    <div class="rpos-orders-toolbar">
                        <div class="rpos-orders-search-group">
                            <span class="rpos-orders-search-icon" aria-hidden="true">
                                <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
                            </span>
                            <input type="search" class="form-control rpos-order-search" placeholder="Buscar órdenes..." value="${this.escape(this.orderSearch)}">
                            <select class="form-control rpos-order-status-select" aria-label="Estado de orden">
                                <option value="En curso" ${this.orderStatusFilter === "En curso" ? "selected" : ""}>Activo</option>
                                <option value="Facturada" ${this.orderStatusFilter === "Facturada" ? "selected" : ""}>Facturadas</option>
                                <option value="Cancelada" ${this.orderStatusFilter === "Cancelada" ? "selected" : ""}>Canceladas</option>
                                <option value="ALL" ${this.orderStatusFilter === "ALL" ? "selected" : ""}>Todas</option>
                            </select>
                        </div>
                        <div class="rpos-orders-toolbar-right">
                            <div class="rpos-orders-srv-tabs" role="group" aria-label="Filtrar por modalidad">
                                <button type="button" class="rpos-area-tab ${this.orderServiceFilter === "Comer en el local" ? "is-active" : ""}" data-ord-srv="Comer en el local">Comer en el local</button>
                                <button type="button" class="rpos-area-tab ${this.orderServiceFilter === "Para llevar" ? "is-active" : ""}" data-ord-srv="Para llevar">Para llevar</button>
                                <button type="button" class="rpos-area-tab ${this.orderServiceFilter === "Entrega" ? "is-active" : ""}" data-ord-srv="Entrega">Entrega</button>
                            </div>
                            <div class="rpos-orders-pager">
                                <span class="rpos-orders-count">${rangeLabel}</span>
                                <div class="rpos-orders-pager-btns">
                                    <button type="button" class="rpos-pager-btn" disabled aria-label="Página anterior">‹</button>
                                    <button type="button" class="rpos-pager-btn" disabled aria-label="Página siguiente">›</button>
                                </div>
                            </div>
                        </div>
                    </div>

                    <div class="rpos-orders-list">
                        ${filtered.length ? filtered.map(ord => {
                            const dt = this.formatOrderDateTime(ord.creation);
                            const custUpper = (ord.customer_name || "").trim().toUpperCase();
                            const showCustName = Boolean(ord.customer_name && custUpper !== "CONSUMIDOR FINAL");
                            return `
                                <div class="rpos-order-row ${selectedOrd?.name === ord.name ? "is-selected" : ""}" data-order-row="${this.escape(ord.name)}">
                                    <div class="rpos-ord-col-date">
                                        <div class="rpos-ord-date">${this.escape(dt.dateLabel)}</div>
                                        <div class="rpos-ord-time">${this.escape(dt.timeLabel)}</div>
                                    </div>
                                    <div class="rpos-ord-col-name">
                                        <div class="rpos-ord-title">${this.escape(ord.order_name || "Venta directa")}</div>
                                        <div class="rpos-ord-sub">${this.escape(ord.name)}</div>
                                    </div>
                                    <div class="rpos-ord-col-meta">
                                        ${showCustName ? `<div class="rpos-ord-cust">${this.escape(ord.customer_name)}</div>` : ""}
                                        <div class="rpos-ord-badges">
                                            <span class="rpos-service-pill" data-service="${this.escape(ord.service_type)}">${this.escape(ord.service_type)}</span>
                                            ${ord.table_label ? `<span class="rpos-table-badge">Mesa ${this.escape(ord.table_label)}</span>` : ""}
                                        </div>
                                    </div>
                                    <div class="rpos-ord-col-extra">
                                        ${ord.scheduled_time ? `<span class="rpos-ord-sched-pill">${this.escape(ord.scheduled_time)}</span>` : ""}
                                    </div>
                                    <div class="rpos-ord-col-total">
                                        ${this.formatMoney(ord.grand_total)}
                                    </div>
                                    <div class="rpos-ord-col-status">
                                        <span class="rpos-ord-status-pill" data-status="${this.escape(ord.status)}">
                                            ${this.escape(ord.status)}
                                        </span>
                                    </div>
                                    <div class="rpos-ord-col-actions">
                                        <button type="button" class="rpos-ord-act-btn is-info" data-action="preview-precuenta" data-order="${this.escape(ord.name)}" title="Ver detalle / Pre-cuenta">i</button>
                                        ${ord.status === "En curso" ? `
                                            <button type="button" class="rpos-ord-act-btn is-trash" data-action="cancel-order-row" data-order="${this.escape(ord.name)}" title="Cancelar orden">
                                                <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/><path d="M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/></svg>
                                            </button>
                                        ` : ""}
                                    </div>
                                </div>
                            `;
                        }).join("") : `
                            <div style="padding:48px;text-align:center;color:#64748b;">No se encontraron órdenes con los filtros seleccionados.</div>
                        `}
                    </div>
                </div>

                <aside class="rpos-ticket-pane">
                    ${selectedOrd ? `
                        <div class="rpos-ticket-header">
                            <div><strong>${this.escape(selectedOrd.order_name)}</strong> (${this.escape(selectedOrd.name)})</div>
                            <div>${this.escape(selectedOrd.status)}</div>
                        </div>
                        <div class="rpos-ticket-lines">
                            ${(selectedOrd.items || []).map(line => `
                                <div class="rpos-line">
                                    <div class="rpos-line-main">
                                        <span class="rpos-line-qty">${line.qty}</span>
                                        <span class="rpos-line-name">${this.escape(line.item_name)}</span>
                                        <span class="rpos-line-amount">${this.formatMoney(line.amount)}</span>
                                    </div>
                                    ${line.options_summary ? `<div class="rpos-line-sub">- ${this.escape(line.options_summary)}</div>` : ""}
                                    ${line.note ? `<div class="rpos-line-note">${this.escape(line.note)}</div>` : ""}
                                </div>
                            `).join("")}
                        </div>
                        <div class="rpos-totals-box">
                            <div class="rpos-totals-row"><span>Cliente</span><span>${this.escape(selectedOrd.customer_name)} ${selectedOrd.tax_id ? `(${this.escape(selectedOrd.tax_id)})` : ""}</span></div>
                            <div class="rpos-totals-row"><span>Subtotal</span><span>${this.formatMoney(selectedOrd.subtotal)}</span></div>
                            <div class="rpos-totals-row"><span>Impuestos (ISV)</span><span>${this.formatMoney(selectedOrd.tax_amount)}</span></div>
                            <div class="rpos-totals-row"><span>Servicio / Propina</span><span>${this.formatMoney(selectedOrd.tip_amount)}</span></div>
                            <div class="rpos-totals-row is-grand"><span>Total</span><span>${this.formatMoney(selectedOrd.grand_total)}</span></div>
                            ${selectedOrd.sales_invoice ? `<div class="rpos-totals-row" style="margin-top:6px;color:#16a34a;"><span>Factura SAR</span><span>${this.escape(selectedOrd.sales_invoice)}</span></div>` : ""}
                        </div>
                        <div style="padding:10px;display:grid;grid-template-columns:1fr 1fr;gap:8px;background:#f8fafc;border-top:1px solid #e2e8f0;">
                            <button type="button" class="rpos-btn-secondary" data-action="preview-precuenta" data-order="${this.escape(selectedOrd.name)}">Ver Precuenta</button>
                            <button type="button" class="rpos-btn-primary" data-action="load-selected-order" data-order="${this.escape(selectedOrd.name)}">Cargar orden</button>
                        </div>
                    ` : `
                        <div class="rpos-ticket-empty">
                            <svg viewBox="0 0 24 24" width="56" height="56" fill="none" stroke="#1e293b" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round" style="margin-bottom:12px;">
                                <circle cx="9" cy="21" r="1.5" fill="#1e293b"/>
                                <circle cx="19" cy="21" r="1.5" fill="#1e293b"/>
                                <path d="M2.5 3h2.8l2.4 11.5a2 2 0 0 0 2 1.5h9.8a2 2 0 0 0 1.9-1.4L23 6H6"/>
                            </svg>
                            <div style="font-size:15px;font-weight:700;color:#1e293b;max-width:250px;line-height:1.35;">Seleccione una orden o escaneé un código QR.</div>
                        </div>
                    `}
                </aside>
            </div>
        `;
    }

    bindEvents() {
        this.shell.querySelectorAll("[data-nav]").forEach(btn => {
            btn.addEventListener("click", () => {
                this.activeTab = btn.dataset.nav;
                if (this.activeTab === "Órdenes") {
                    this.selectedOrderPreviewName = "";
                }
                this.render();
            });
        });

        const prodSearch = this.shell.querySelector(".rpos-prod-search");
        if (prodSearch) {
            prodSearch.addEventListener("input", e => {
                this.productSearch = e.target.value;
                this.render();
                const input = this.shell.querySelector(".rpos-prod-search");
                if (input) {
                    input.focus();
                    input.setSelectionRange(input.value.length, input.value.length);
                }
            });
        }

        const ordSearch = this.shell.querySelector(".rpos-order-search");
        if (ordSearch) {
            ordSearch.addEventListener("input", e => {
                this.orderSearch = e.target.value;
                this.render();
                const input = this.shell.querySelector(".rpos-order-search");
                if (input) {
                    input.focus();
                    input.setSelectionRange(input.value.length, input.value.length);
                }
            });
        }

        const ordStatusSelect = this.shell.querySelector(".rpos-order-status-select");
        if (ordStatusSelect) {
            ordStatusSelect.addEventListener("change", e => {
                this.orderStatusFilter = e.target.value;
                this.render();
            });
        }

        this.shell.querySelectorAll("[data-ord-srv]").forEach(btn => {
            btn.addEventListener("click", () => {
                const targetSrv = btn.dataset.ordSrv;
                this.orderServiceFilter = this.orderServiceFilter === targetSrv ? "ALL" : targetSrv;
                this.render();
            });
        });

        this.shell.querySelectorAll("[data-order-row]").forEach(row => {
            row.addEventListener("click", e => {
                if (e.target.closest("[data-action]")) return;
                this.selectedOrderPreviewName = row.dataset.orderRow;
                this.render();
            });
            row.addEventListener("dblclick", e => {
                if (e.target.closest("[data-action]")) return;
                this.loadOrderIntoPos(row.dataset.orderRow);
            });
        });

        this.shell.querySelectorAll("[data-area]").forEach(btn => {
            btn.addEventListener("click", () => {
                this.selectedAreaName = btn.dataset.area;
                this.render();
            });
        });

        const posAreaSelect = this.shell.querySelector('[data-role="pos-area-select"]');
        if (posAreaSelect) {
            posAreaSelect.addEventListener("change", e => {
                this.selectedAreaName = e.target.value;
                this.render();
            });
        }

        this.shell.querySelectorAll("[data-cat]").forEach(btn => {
            btn.addEventListener("click", () => {
                this.selectedCategory = btn.dataset.cat;
                this.render();
            });
        });

        this.shell.querySelectorAll("[data-item-code]").forEach(card => {
            card.addEventListener("click", () => {
                const itemCode = card.dataset.itemCode;
                const item = (this.bootstrap?.items || []).find(i => i.item_code === itemCode);
                if (item) this.handleProductClick(item);
            });
        });

        this.shell.querySelectorAll("[data-line-idx]").forEach(lineEl => {
            lineEl.addEventListener("click", () => {
                this.selectedLineIndex = Number(lineEl.dataset.lineIdx);
                this.numpadBuffer = "";
                this.render();
            });
        });

        this.shell.querySelectorAll("[data-mode]").forEach(btn => {
            btn.addEventListener("click", () => {
                this.numpadMode = btn.dataset.mode;
                this.numpadBuffer = "";
                this.render();
            });
        });

        this.shell.querySelectorAll("[data-key]").forEach(btn => {
            btn.addEventListener("click", () => {
                this.handleNumpadKey(btn.dataset.key);
            });
        });

        this.shell.querySelectorAll("[data-action]").forEach(el => {
            el.addEventListener("click", e => {
                e.stopPropagation();
                this.handleAction(el.dataset.action, el);
            });
        });
    }

    handleAction(action, el) {
        if (action === "new-order-modal") return this.openNewAccountModal();
        if (action === "assign-account") return this.openNewAccountModal({ editCurrent: true });
        if (action === "assign-table") {
            this.activeTab = "Mesas";
            this.render();
            return;
        }
        if (action === "open-preset") return this.openPresetModal();
        if (action === "open-customer-modal") return this.openCustomerModal();
        if (action === "open-note-modal") return this.openNoteModal();
        if (action === "open-tip-modal") return this.openTipModal();
        if (action === "open-actions-modal") return this.openActionsModal();
        if (action === "open-precuenta") return this.openPrecuentaModal();
        if (action === "open-payment-modal") return this.openPaymentModal();
        if (action === "send-kitchen") return this.sendToKitchen();
        if (action === "open-kds") {
            frappe.set_route("restaurant-kds");
            return;
        }
        if (action === "open-map-designer") {
            frappe.route_options = { area_name: this.selectedAreaName };
            frappe.set_route("restaurant-table-map");
            return;
        }
        if (action === "quick-table-number") return this.openQuickTableNumberModal();
        if (action === "shift-info" || action === "pos-menu") return this.openPosMenuModal();
        if (action === "click-map-table") {
            const tableName = el.dataset.table;
            if (!tableName) return;
            this.handleTableClick(tableName);
            return;
        }
        if (action === "load-selected-order") {
            const ordName = el.dataset.order;
            const ord = (this.bootstrap?.orders || []).find(o => o.name === ordName);
            if (ord) this.loadOrderIntoCaja(ord);
            return;
        }
        if (action === "preview-precuenta") {
            const ordName = el.dataset.order;
            if (ordName) this.openPrecuentaModal(ordName);
            return;
        }
        if (action === "cancel-order-row") {
            const ordName = el.dataset.order;
            if (ordName) this.cancelOrderById(ordName);
        }
    }

    handleTableClick(tableName) {
        const currentArea = (this.bootstrap?.areas || []).find(a => a.name === this.selectedAreaName);
        const table = (currentArea?.tables || []).find(t => t.name === tableName);
        if (!table) return;

        if (table.active_order?.order_id) {
            const existing = (this.bootstrap?.orders || []).find(o => o.name === table.active_order.order_id);
            if (existing) {
                this.loadOrderIntoCaja(existing);
                return;
            }
        }
        this.openNewAccountModal({
            preselectedTable: table.name,
            preselectedTableLabel: table.table_number,
            preselectedArea: currentArea.name,
        });
    }

    loadOrderIntoCaja(orderData) {
        this.currentOrder = JSON.parse(JSON.stringify(orderData));
        this.selectedLineIndex = (this.currentOrder.items?.length || 0) - 1;
        this.activeTab = "Caja";
        this.render();
    }

    handleProductClick(item) {
        if (!this.bootstrap?.opening_shift) {
            this.openShiftDialog();
            return;
        }
        if (item.restaurant_options_enabled && item.option_groups?.length) {
            this.openDishOptionsModal(item);
            return;
        }
        this.addItemToCurrentOrder(item, []);
    }

    async addItemToCurrentOrder(item, selectedOptions = []) {
        const optKey = JSON.stringify(selectedOptions.map(o => o.option_label).sort());
        const existingIdx = (this.currentOrder.items || []).findIndex(
            row => row.item_code === item.item_code &&
                   JSON.stringify((row.selected_options || []).map(o => o.option_label).sort()) === optKey &&
                   !row.note
        );
        const optionsRate = selectedOptions.reduce((sum, o) => sum + Number(o.additional_amount || 0), 0);
        const optionsSummary = selectedOptions
            .map(o => Number(o.additional_amount) > 0 ? `${o.option_label} (+${this.formatMoney(o.additional_amount)})` : o.option_label)
            .join(", ");

        if (existingIdx >= 0) {
            this.currentOrder.items[existingIdx].qty += 1;
            this.selectedLineIndex = existingIdx;
        } else {
            this.currentOrder.items.push({
                item_code: item.item_code,
                item_name: item.item_name,
                item_group: item.item_group,
                qty: 1,
                uom: item.uom || "Unidad",
                base_rate: Number(item.price || 0),
                options_rate: Number(optionsRate.toFixed(2)),
                discount_percentage: 0,
                rate: Number((Number(item.price || 0) + optionsRate).toFixed(2)),
                amount: Number((Number(item.price || 0) + optionsRate).toFixed(2)),
                tax_rate: Number(item.tax_rate ?? 15),
                selected_options: selectedOptions,
                options_summary: optionsSummary,
                note: "",
                command_station: item.command_station || "Cocina General",
                kds_status: "Pendiente",
            });
            this.selectedLineIndex = this.currentOrder.items.length - 1;
        }
        this.numpadBuffer = "";
        this.render();
        await this.persistCurrentOrderSilently();
    }

    handleNumpadKey(key) {
        if (this.selectedLineIndex < 0 || !this.currentOrder.items[this.selectedLineIndex]) return;
        const line = this.currentOrder.items[this.selectedLineIndex];

        if (key === "BACK") {
            this.numpadBuffer = this.numpadBuffer.slice(0, -1);
            if (!this.numpadBuffer) {
                if (this.numpadMode === "qty") {
                    this.currentOrder.items.splice(this.selectedLineIndex, 1);
                    this.selectedLineIndex = Math.min(this.selectedLineIndex, this.currentOrder.items.length - 1);
                } else if (this.numpadMode === "disc") {
                    line.discount_percentage = 0;
                }
                this.render();
                this.persistCurrentOrderSilently();
                return;
            }
        } else if (key === "+/-") {
            return;
        } else {
            this.numpadBuffer += key;
        }

        const val = Number(this.numpadBuffer);
        if (!Number.isFinite(val)) return;

        if (this.numpadMode === "qty") {
            if (val > 0) line.qty = val;
        } else if (this.numpadMode === "disc") {
            line.discount_percentage = Math.min(100, Math.max(0, val));
        } else if (this.numpadMode === "price") {
            line.base_rate = Math.max(0, val);
        }
        this.render();
        this.persistCurrentOrderSilently();
    }

    async persistCurrentOrderSilently() {
        if (!this.currentOrder.order_name && !this.currentOrder.items.length) return;
        if (!this.currentOrder.order_name) {
            this.currentOrder.order_name = this.currentOrder.table_label
                ? `Mesa ${this.currentOrder.table_label}`
                : `Orden ${Math.floor(1000 + Math.random() * 9000)}`;
        }
        try {
            const res = await frappe.call({
                method: "restaurant.pos.save_pos_order",
                args: { order: this.currentOrder },
            });
            if (res.message?.order) {
                this.currentOrder = res.message.order;
                this.bootstrap.areas = res.message.areas || this.bootstrap.areas;
                this.upsertOrderInBootstrap(this.currentOrder);
                this.render();
            }
        } catch (e) {
            // Validation feedback is handled by Frappe
        }
    }

    upsertOrderInBootstrap(orderObj) {
        if (!this.bootstrap) return;
        const list = this.bootstrap.orders || [];
        const idx = list.findIndex(o => o.name === orderObj.name);
        if (idx >= 0) list[idx] = orderObj;
        else list.unshift(orderObj);
        this.bootstrap.orders = list;
    }

    createModal(title, bodyHtml, footerHtml, maxWidth = "620px") {
        const existing = document.querySelector(".rpos-modal-backdrop");
        if (existing) existing.remove();

        const backdrop = document.createElement("div");
        backdrop.className = "rpos-modal-backdrop";
        backdrop.innerHTML = `
            <div class="rpos-modal" style="max-width:${maxWidth};">
                <div class="rpos-modal-header">
                    <h3>${title}</h3>
                    <button type="button" class="rpos-icon-btn" data-modal-close>×</button>
                </div>
                <div class="rpos-modal-body">${bodyHtml}</div>
                ${footerHtml ? `<div class="rpos-modal-footer">${footerHtml}</div>` : ""}
            </div>
        `;
        backdrop.querySelectorAll("[data-modal-close]").forEach(btn => {
            btn.addEventListener("click", () => backdrop.remove());
        });
        document.body.appendChild(backdrop);
        return backdrop;
    }

    /* 1. Apertura de Punto de Venta (Turno de Caja) */
    openShiftDialog() {
        const cashier = this.bootstrap?.cashier || { user: frappe.session.user, full_name: frappe.session.user };
        const profiles = this.bootstrap?.pos_profiles || [];
        const backdrop = this.createModal(
            "Apertura de Punto de Venta · LEAF RESTAURANT",
            `
                <p style="color:#475569;font-size:13px;margin-top:0;">
                    Registra el monto inicial de efectivo en caja para iniciar tu turno como cajero en el restaurante.
                </p>
                <div class="rpos-field">
                    <label>Usuario logueado (Cajero responsable)</label>
                    <input type="text" value="${this.escape(cashier.full_name)} (${this.escape(cashier.user)})" readonly style="opacity:0.85;">
                </div>
                <div class="rpos-field">
                    <label>Perfil de Punto de Venta</label>
                    <select data-shift-profile>
                        ${profiles.map(p => `<option value="${this.escape(p.name)}">${this.escape(p.name)} · ${this.escape(p.company)}</option>`).join("")}
                    </select>
                </div>
                <div class="rpos-field">
                    <label>Monto de apertura de dinero (L)</label>
                    <input type="number" step="0.01" min="0" value="500.00" data-shift-amount placeholder="0.00">
                </div>
            `,
            `
                <button type="button" class="rpos-btn-secondary" data-shift-exit>Salir</button>
                <button type="button" class="rpos-btn-green" data-shift-open>Abrir Punto de Venta</button>
            `,
            "520px"
        );

        const closeBtn = backdrop.querySelector(".rpos-modal-header [data-modal-close]");
        if (closeBtn) closeBtn.style.display = "none";

        backdrop.querySelector("[data-shift-exit]").addEventListener("click", () => {
            backdrop.remove();
            frappe.set_route("Workspaces", "Restaurante");
        });

        backdrop.querySelector("[data-shift-open]").addEventListener("click", async () => {
            const profile = backdrop.querySelector("[data-shift-profile]").value;
            const amount = Number(backdrop.querySelector("[data-shift-amount]").value || 0);
            const res = await frappe.call({
                method: "restaurant.pos.open_pos_shift",
                args: { pos_profile: profile, opening_amount: amount },
                freeze: true,
                freeze_message: "Abriendo turno de Punto de Venta...",
            });
            this.bootstrap.opening_shift = res.message;
            backdrop.remove();
            frappe.show_alert({ message: "Turno de Punto de Venta abierto correctamente", indicator: "green" });
            this.render();
        });
    }

    /* 2. Crear / Editar Cuenta u Orden */
    openNewAccountModal(opts = {}) {
        const isEdit = Boolean(opts.editCurrent && this.currentOrder.name);
        const waiters = this.bootstrap?.waiters || [];
        const customers = this.bootstrap?.customers || [];
        const areas = this.bootstrap?.areas || [];
        const allTables = [];
        areas.forEach(a => {
            (a.tables || []).forEach(t => {
                allTables.push({ ...t, area_label: a.area_name });
            });
        });

        const initialTable = opts.preselectedTable ?? (isEdit ? this.currentOrder.restaurant_table : "");
        const initialTableLabel = opts.preselectedTableLabel || "";
        const defaultName = isEdit
            ? this.currentOrder.order_name
            : (initialTableLabel ? `Mesa ${initialTableLabel}` : "");

        const backdrop = this.createModal(
            isEdit ? "Datos de la Cuenta u Orden" : "Abrir Cuenta u Orden",
            `
                <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">
                    <div class="rpos-field">
                        <label>Mesero que atenderá *</label>
                        <select data-acc-waiter>
                            <option value="">-- Seleccionar mesero --</option>
                            ${waiters.map(w => `
                                <option value="${this.escape(w.name)}" ${(isEdit ? this.currentOrder.waiter : waiters[0]?.name) === w.name ? "selected" : ""}>
                                    ${this.escape(w.employee_name)} (${this.escape(w.name)})
                                </option>
                            `).join("")}
                        </select>
                    </div>
                    <div class="rpos-field">
                        <label>Nombre de la cuenta u orden *</label>
                        <input type="text" data-acc-name maxlength="140" placeholder="Ej. Mesa 1, Familia López, 1013..." value="${this.escape(defaultName)}">
                    </div>
                </div>
                <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">
                    <div class="rpos-field">
                        <label>Referencia (opcional)</label>
                        <input type="text" data-acc-ref maxlength="140" placeholder="Ej. Cumpleaños, terraza norte, ventana..." value="${this.escape(isEdit ? this.currentOrder.reference_note : "")}">
                    </div>
                    <div class="rpos-field">
                        <label>Modalidad de servicio</label>
                        <select data-acc-service>
                            ${["Comer en el local", "Para llevar", "Entrega"].map(s => `
                                <option value="${s}" ${(isEdit ? this.currentOrder.service_type : "Comer en el local") === s ? "selected" : ""}>${s}</option>
                            `).join("")}
                        </select>
                    </div>
                </div>
                <div style="display:grid;grid-template-columns:1.3fr 1fr;gap:12px;">
                    <div class="rpos-field">
                        <label>Cliente *</label>
                        <select data-acc-customer>
                            ${customers.map(c => `
                                <option value="${this.escape(c.name)}" data-rtn="${this.escape(c.tax_id || "")}" ${(isEdit ? this.currentOrder.customer : customers[0]?.name) === c.name ? "selected" : ""}>
                                    ${this.escape(c.customer_name)} ${c.tax_id ? `· RTN: ${this.escape(c.tax_id)}` : ""}
                                </option>
                            `).join("")}
                        </select>
                    </div>
                    <div class="rpos-field">
                        <label>RTN del cliente (Control Fiscal SAR)</label>
                        <input type="text" data-acc-rtn maxlength="60" placeholder="Ej. 08011999123456" value="${this.escape(isEdit ? this.currentOrder.tax_id : (customers[0]?.tax_id || ""))}">
                    </div>
                </div>
                <div style="display:grid;grid-template-columns:1.3fr 0.7fr;gap:12px;">
                    <div class="rpos-field">
                        <label>Mesa asignada</label>
                        <select data-acc-table>
                            <option value="">-- Sin mesa / Venta rápida --</option>
                            ${allTables.map(t => `
                                <option value="${this.escape(t.name)}" ${initialTable === t.name ? "selected" : ""}>
                                    Mesa ${this.escape(t.table_number)} · ${this.escape(t.area_label)} (${this.escape(t.status)})
                                </option>
                            `).join("")}
                        </select>
                    </div>
                    <div class="rpos-field">
                        <label>Invitados</label>
                        <input type="number" min="1" max="200" data-acc-guests value="${isEdit ? (this.currentOrder.guests || 1) : 2}">
                    </div>
                </div>
            `,
            `
                <button type="button" class="rpos-btn-secondary" data-modal-close>Salir</button>
                <button type="button" class="rpos-btn-primary" data-acc-submit>${isEdit ? "Guardar cambios" : "Abrir cuenta u orden"}</button>
            `,
            "640px"
        );

        const custSel = backdrop.querySelector("[data-acc-customer]");
        const rtnInp = backdrop.querySelector("[data-acc-rtn]");
        custSel.addEventListener("change", () => {
            const opt = custSel.selectedOptions[0];
            if (opt && opt.dataset.rtn) rtnInp.value = opt.dataset.rtn;
        });

        backdrop.querySelector("[data-acc-submit]").addEventListener("click", async () => {
            const orderName = backdrop.querySelector("[data-acc-name]").value.trim();
            if (!orderName) {
                frappe.msgprint("Ingresa el nombre de la cuenta u orden.");
                return;
            }
            const payload = isEdit
                ? { ...this.currentOrder }
                : this.createBlankOrder();

            payload.order_name = orderName;
            payload.reference_note = backdrop.querySelector("[data-acc-ref]").value.trim();
            payload.waiter = backdrop.querySelector("[data-acc-waiter]").value;
            payload.service_type = backdrop.querySelector("[data-acc-service]").value;
            payload.customer = custSel.value;
            payload.tax_id = rtnInp.value.trim();
            payload.restaurant_table = backdrop.querySelector("[data-acc-table]").value;
            payload.guests = Number(backdrop.querySelector("[data-acc-guests]").value || 1);

            const res = await frappe.call({
                method: "restaurant.pos.save_pos_order",
                args: { order: payload },
                freeze: true,
                freeze_message: "Guardando cuenta u orden...",
            });
            if (res.message?.order) {
                this.currentOrder = res.message.order;
                this.bootstrap.areas = res.message.areas || this.bootstrap.areas;
                this.upsertOrderInBootstrap(this.currentOrder);
                this.activeTab = "Caja";
                backdrop.remove();
                frappe.show_alert({ message: `Cuenta "${this.currentOrder.order_name}" lista`, indicator: "green" });
                this.render();
            }
        });
    }

    /* 3. Modal de Opciones / Extras / Combo de Platillos */
    openDishOptionsModal(item) {
        const groups = item.option_groups || [];
        const selectionsByGroup = {};
        groups.forEach(g => {
            const defaults = (g.options || []).filter(o => o.is_default).slice(0, g.max_selections || 1);
            if (!defaults.length && g.min_selections > 0 && g.options?.length) {
                selectionsByGroup[g.name] = [g.options[0]];
            } else {
                selectionsByGroup[g.name] = defaults;
            }
        });

        const computeExtraTotal = () => {
            let extra = 0;
            Object.values(selectionsByGroup).forEach(list => {
                list.forEach(o => { extra += Number(o.additional_amount || 0); });
            });
            return extra;
        };

        const backdrop = this.createModal(
            `${this.escape(item.item_name)} | ${this.formatMoney(item.price)}`,
            `<div data-opt-container></div>`,
            `
                <div style="margin-right:auto;font-size:15px;font-weight:800;" data-opt-total-label></div>
                <button type="button" class="rpos-btn-primary" data-opt-confirm style="flex:1;">${item.is_combo ? "Agregar a la orden" : "Añadir"}</button>
                <button type="button" class="rpos-btn-secondary" data-modal-close style="flex:1;">Descartar</button>
            `,
            "680px"
        );

        const renderChoices = () => {
            const container = backdrop.querySelector("[data-opt-container]");
            container.innerHTML = groups.map(grp => {
                const chosen = selectionsByGroup[grp.name] || [];
                const badgeText = grp.min_selections > 0
                    ? `${grp.max_selections} Incluido / Requerido`
                    : `Hasta ${grp.max_selections}`;
                return `
                    <div class="rpos-opt-group">
                        <div class="rpos-opt-group-title">
                            <span>${this.escape(grp.group_name)}</span>
                            <span class="rpos-opt-group-badge">${this.escape(badgeText)}</span>
                        </div>
                        <div class="rpos-opt-choices">
                            ${(grp.options || []).map((opt, oIdx) => {
                                const isSel = chosen.some(c => c.option_label === opt.option_label);
                                return `
                                    <button type="button"
                                            class="rpos-opt-btn ${isSel ? "is-selected" : ""}"
                                            data-grp="${this.escape(grp.name)}"
                                            data-opt-idx="${oIdx}">
                                        <span>${this.escape(opt.option_label)}</span>
                                        ${Number(opt.additional_amount) > 0 ? `<span class="rpos-opt-extra-pill">+ ${this.formatMoney(opt.additional_amount)}</span>` : ""}
                                    </button>
                                `;
                            }).join("")}
                        </div>
                    </div>
                `;
            }).join("");

            const total = Number(item.price || 0) + computeExtraTotal();
            backdrop.querySelector("[data-opt-total-label]").textContent = `Total: ${this.formatMoney(total)}`;

            container.querySelectorAll("[data-grp]").forEach(btn => {
                btn.addEventListener("click", () => {
                    const gName = btn.dataset.grp;
                    const oIdx = Number(btn.dataset.optIdx);
                    const grp = groups.find(g => g.name === gName);
                    if (!grp) return;
                    const opt = grp.options[oIdx];
                    let current = selectionsByGroup[gName] || [];
                    const exists = current.some(c => c.option_label === opt.option_label);

                    if (grp.max_selections === 1) {
                        current = exists && grp.min_selections === 0 ? [] : [opt];
                    } else if (exists) {
                        current = current.filter(c => c.option_label !== opt.option_label);
                    } else if (current.length < grp.max_selections) {
                        current = [...current, opt];
                    }
                    selectionsByGroup[gName] = current;
                    renderChoices();
                });
            });
        };

        renderChoices();

        backdrop.querySelector("[data-opt-confirm]").addEventListener("click", () => {
            for (const grp of groups) {
                const chosen = selectionsByGroup[grp.name] || [];
                if (chosen.length < grp.min_selections) {
                    frappe.msgprint(`Selecciona al menos ${grp.min_selections} opción en "${grp.group_name}".`);
                    return;
                }
            }
            const flat = [];
            groups.forEach(g => {
                (selectionsByGroup[g.name] || []).forEach(o => flat.push(o));
            });
            backdrop.remove();
            this.addItemToCurrentOrder(item, flat);
        });
    }

    /* 4. Modal de Nota de Cocina (con botones rápidos de color) */
    openNoteModal() {
        if (this.selectedLineIndex < 0 || !this.currentOrder.items[this.selectedLineIndex]) {
            frappe.msgprint("Selecciona primero un platillo en el ticket de la izquierda para agregarle una nota.");
            return;
        }
        const line = this.currentOrder.items[this.selectedLineIndex];
        const quickTags = [
            { label: "Esperar", color: "#ef4444" },
            { label: "Para servir", color: "#f97316" },
            { label: "Urgente", color: "#ca8a04" },
            { label: "Sin aderezo", color: "#3b82f6" },
            { label: "Término medio", color: "#8b5cf6" },
            { label: "Bien cocido", color: "#16a34a" },
        ];

        const backdrop = this.createModal(
            `${this.escape(line.item_name)}: Agregar Nota`,
            `
                <div class="rpos-note-tags">
                    ${quickTags.map(t => `
                        <button type="button" class="rpos-note-tag" data-quick-tag="${this.escape(t.label)}" style="background:${t.color};">
                            ${this.escape(t.label)}
                        </button>
                    `).join("")}
                </div>
                <div class="rpos-field">
                    <textarea rows="4" data-note-text placeholder="Escribe el comentario o instrucción para cocina...">${this.escape(line.note || "")}</textarea>
                </div>
            `,
            `
                <button type="button" class="rpos-btn-primary" data-note-apply>Aplicar</button>
                <button type="button" class="rpos-btn-secondary" data-modal-close>Descartar</button>
            `,
            "540px"
        );

        const txt = backdrop.querySelector("[data-note-text]");
        backdrop.querySelectorAll("[data-quick-tag]").forEach(btn => {
            btn.addEventListener("click", () => {
                const tag = btn.dataset.quickTag;
                txt.value = txt.value.trim() ? `${txt.value.trim()}, ${tag}` : tag;
                txt.focus();
            });
        });

        backdrop.querySelector("[data-note-apply]").addEventListener("click", async () => {
            line.note = txt.value.trim();
            backdrop.remove();
            this.render();
            await this.persistCurrentOrderSilently();
        });
    }

    /* 5. Modal de Ajuste Preestablecido (Comer en el local / Para llevar / Entrega) */
    openPresetModal() {
        const presets = [
            { label: "Comer en el local", bg: "#bfdbfe", border: "#3b82f6" },
            { label: "Para llevar", bg: "#fde68a", border: "#b45309" },
            { label: "Entrega", bg: "#fed7aa", border: "#9a3412" },
        ];
        const backdrop = this.createModal(
            "Seleccionar el ajuste preestablecido",
            `
                <div class="rpos-preset-list">
                    ${presets.map(p => `
                        <button type="button"
                                class="rpos-preset-row ${this.currentOrder.service_type === p.label ? "is-active" : ""}"
                                data-preset-choice="${p.label}"
                                style="background:${p.bg};border:1.5px solid ${p.border};">
                            <span>${p.label}</span>
                            <span class="rpos-preset-chevron">›</span>
                        </button>
                    `).join("")}
                </div>
            `,
            "",
            "520px"
        );

        backdrop.querySelectorAll("[data-preset-choice]").forEach(btn => {
            btn.addEventListener("click", async () => {
                this.currentOrder.service_type = btn.dataset.presetChoice;
                backdrop.remove();
                this.render();
                await this.persistCurrentOrderSilently();
            });
        });
    }

    /* 6. Modal de Cliente y RTN Fiscal */
    openCustomerModal() {
        const customers = this.bootstrap?.customers || [];
        const backdrop = this.createModal(
            "Seleccionar o Registrar Cliente (Control Fiscal RTN)",
            `
                <div class="rpos-field">
                    <label>Seleccionar cliente existente</label>
                    <select data-cust-select>
                        ${customers.map(c => `
                            <option value="${this.escape(c.name)}" data-rtn="${this.escape(c.tax_id || "")}" ${this.currentOrder.customer === c.name ? "selected" : ""}>
                                ${this.escape(c.customer_name)} ${c.tax_id ? `· RTN: ${this.escape(c.tax_id)}` : ""}
                            </option>
                        `).join("")}
                    </select>
                </div>
                <div class="rpos-field">
                    <label>RTN del cliente seleccionado</label>
                    <input type="text" data-cust-rtn maxlength="60" placeholder="Ej. 08011999123456" value="${this.escape(this.currentOrder.tax_id || "")}">
                </div>
                <hr style="border-color:#e2e8f0;margin:14px 0;">
                <div style="font-size:13px;font-weight:700;color:#1898e8;margin-bottom:8px;">+ O crear nuevo cliente rápido con RTN</div>
                <div style="display:grid;grid-template-columns:1.2fr 1fr;gap:10px;">
                    <div class="rpos-field">
                        <label>Nombre o Razón Social</label>
                        <input type="text" data-new-cust-name placeholder="Nombre en factura">
                    </div>
                    <div class="rpos-field">
                        <label>RTN</label>
                        <input type="text" data-new-cust-rtn placeholder="0801...">
                    </div>
                </div>
            `,
            `
                <button type="button" class="rpos-btn-secondary" data-modal-close>Cancelar</button>
                <button type="button" class="rpos-btn-primary" data-cust-apply>Aplicar cliente</button>
            `,
            "560px"
        );

        const sel = backdrop.querySelector("[data-cust-select]");
        const rtnInp = backdrop.querySelector("[data-cust-rtn]");
        sel.addEventListener("change", () => {
            const opt = sel.selectedOptions[0];
            rtnInp.value = opt?.dataset?.rtn || "";
        });

        backdrop.querySelector("[data-cust-apply]").addEventListener("click", async () => {
            const newName = backdrop.querySelector("[data-new-cust-name]").value.trim();
            const newRtn = backdrop.querySelector("[data-new-cust-rtn]").value.trim();

            if (newName) {
                const res = await frappe.call({
                    method: "restaurant.pos.save_customer_with_rtn",
                    args: { customer_name: newName, tax_id: newRtn },
                });
                const created = res.message;
                this.bootstrap.customers.unshift(created);
                this.currentOrder.customer = created.name;
                this.currentOrder.customer_name = created.customer_name;
                this.currentOrder.tax_id = created.tax_id;
            } else {
                const chosen = customers.find(c => c.name === sel.value);
                const updatedRtn = rtnInp.value.trim();
                if (chosen) {
                    this.currentOrder.customer = chosen.name;
                    this.currentOrder.customer_name = chosen.customer_name;
                    this.currentOrder.tax_id = updatedRtn;
                    if (updatedRtn !== (chosen.tax_id || "")) {
                        await frappe.call({
                            method: "restaurant.pos.save_customer_with_rtn",
                            args: {
                                customer_id: chosen.name,
                                customer_name: chosen.customer_name,
                                tax_id: updatedRtn,
                            },
                        });
                        chosen.tax_id = updatedRtn;
                    }
                }
            }
            backdrop.remove();
            this.render();
            await this.persistCurrentOrderSilently();
        });
    }

    /* 7. Modal de Servicio Sugerido / Propina */
    openTipModal() {
        const backdrop = this.createModal(
            "Servicio Sugerido o Propina",
            `
                <p style="color:#475569;font-size:13px;margin-top:0;">
                    Selecciona un porcentaje de servicio sugerido sobre el subtotal (${this.formatMoney(this.currentOrder.subtotal)}) o ingresa un monto fijo de propina.
                </p>
                <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-bottom:14px;">
                    ${[0, 10, 12, 15].map(pct => `
                        <button type="button" class="rpos-opt-btn ${Number(this.currentOrder.tip_percentage) === pct ? "is-selected" : ""}" data-tip-pct="${pct}" style="justify-content:center;">
                            ${pct === 0 ? "Sin propina" : `${pct}%`}
                        </button>
                    `).join("")}
                </div>
                <div class="rpos-field">
                    <label>O monto fijo de propina (L)</label>
                    <input type="number" step="0.01" min="0" data-tip-custom value="${Number(this.currentOrder.tip_amount || 0).toFixed(2)}">
                </div>
            `,
            `
                <button type="button" class="rpos-btn-secondary" data-modal-close>Cancelar</button>
                <button type="button" class="rpos-btn-primary" data-tip-save>Aplicar propina</button>
            `,
            "480px"
        );

        let selectedPct = Number(this.currentOrder.tip_percentage || 0);
        const customInput = backdrop.querySelector("[data-tip-custom]");

        backdrop.querySelectorAll("[data-tip-pct]").forEach(btn => {
            btn.addEventListener("click", () => {
                selectedPct = Number(btn.dataset.tipPct);
                backdrop.querySelectorAll("[data-tip-pct]").forEach(b => b.classList.remove("is-selected"));
                btn.classList.add("is-selected");
                customInput.value = ((this.currentOrder.subtotal * selectedPct) / 100).toFixed(2);
            });
        });

        customInput.addEventListener("input", () => {
            selectedPct = 0;
            backdrop.querySelectorAll("[data-tip-pct]").forEach(b => b.classList.remove("is-selected"));
        });

        backdrop.querySelector("[data-tip-save]").addEventListener("click", async () => {
            this.currentOrder.tip_percentage = selectedPct;
            this.currentOrder.tip_amount = Math.max(0, Number(customInput.value || 0));
            backdrop.remove();
            this.render();
            await this.persistCurrentOrderSilently();
        });
    }

    /* 8. Modal de Acciones (⋮) */
    openActionsModal() {
        const guestsCount = Number(this.currentOrder.guests) || 1;
        const backdrop = this.createModal(
            "Acciones",
            `
                <div class="rpos-actions-grid">
                    <button type="button" class="rpos-action-tile" data-act-tile="customer-note">
                        <span class="rpos-action-icon" aria-hidden="true">
                            <svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="8" y1="13" x2="16" y2="13"/><line x1="8" y1="17" x2="13" y2="17"/></svg>
                        </span>
                        <span>Nota para el cliente</span>
                    </button>
                    <button type="button" class="rpos-action-tile" data-act-tile="precuenta">
                        <span class="rpos-action-icon" aria-hidden="true">
                            <svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 6 2 18 2 18 9"/><path d="M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2"/><rect x="6" y="14" width="12" height="8"/></svg>
                        </span>
                        <span>Factura</span>
                    </button>
                    <button type="button" class="rpos-action-tile" data-act-tile="guests">
                        <span class="rpos-action-guest-badge">${guestsCount}</span>
                        <span>Invitado</span>
                    </button>
                    <button type="button" class="rpos-action-tile" data-act-tile="split">
                        <span class="rpos-action-icon" aria-hidden="true">
                            <svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="5" width="11" height="14" rx="2"/><path d="M5 19H4a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2h9"/></svg>
                        </span>
                        <span>Dividir</span>
                    </button>
                    <button type="button" class="rpos-action-tile" data-act-tile="transfer">
                        <span class="rpos-action-icon" aria-hidden="true">
                            <svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><line x1="5" y1="12" x2="19" y2="12"/><polyline points="12 5 19 12 12 19"/></svg>
                        </span>
                        <span>Transferir / Fusionar</span>
                    </button>
                    <button type="button" class="rpos-action-tile" data-act-tile="transfer-food">
                        <span class="rpos-action-icon" aria-hidden="true">
                            <svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="5" x2="12" y2="19"/><polyline points="19 12 12 19 5 12"/></svg>
                        </span>
                        <span>Transferir comida</span>
                    </button>
                    <button type="button" class="rpos-action-tile" data-act-tile="rename">
                        <span class="rpos-action-icon" aria-hidden="true">
                            <svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
                        </span>
                        <span>Definir nombre de la orden</span>
                    </button>
                    <button type="button" class="rpos-action-tile" data-act-tile="pricelist">
                        <span class="rpos-action-icon" aria-hidden="true">
                            <svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="16" rx="2"/><line x1="3" y1="10" x2="21" y2="10"/><line x1="9" y1="4" x2="9" y2="20"/></svg>
                        </span>
                        <span>Lista de precios</span>
                    </button>
                </div>
                <button type="button" class="rpos-action-cancel-bar" data-act-tile="cancel">
                    <svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/><path d="M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/></svg>
                    <span>Cancelar orden</span>
                </button>
            `,
            "",
            "720px"
        );

        backdrop.querySelectorAll("[data-act-tile]").forEach(btn => {
            btn.addEventListener("click", () => {
                const tile = btn.dataset.actTile;
                backdrop.remove();
                if (tile === "precuenta") return this.openPrecuentaModal();
                if (tile === "tip") return this.openTipModal();
                if (tile === "rename" || tile === "guests") return this.openNewAccountModal({ editCurrent: true });
                if (tile === "split" || tile === "transfer-food") return this.openSplitOrderModal();
                if (tile === "transfer") return this.openTransferTableModal();
                if (tile === "customer-note") return this.openCustomerNoteModal();
                if (tile === "pricelist") return this.openPriceListModal();
                if (tile === "info") return this.openOrderInfoModal();
                if (tile === "cancel") return this.cancelCurrentOrder();
            });
        });
    }

    /* 9. Pre-cuenta (No Fiscal) para el Cliente */
    async openPrecuentaModal(orderId = null) {
        if (!orderId) {
            if (!this.currentOrder.items.length) {
                frappe.msgprint("Agrega platillos a la cuenta antes de generar la Pre-cuenta.");
                return;
            }
            await this.persistCurrentOrderSilently();
            orderId = this.currentOrder.name;
        }
        if (!orderId) return;

        const res = await frappe.call({
            method: "restaurant.pos.get_precuenta_data",
            args: {
                order_name: orderId,
                tip_percentage: this.currentOrder.tip_percentage,
                tip_amount: this.currentOrder.tip_amount,
            },
        });
        const data = res.message;
        const ord = data.order;

        const backdrop = this.createModal(
            `Pre-cuenta · ${this.escape(ord.order_name)}`,
            `
                <div class="rpos-receipt-paper" id="rpos-printable-precuenta">
                    <h4>${this.escape(data.company_name)}</h4>
                    <div style="text-align:center;font-size:11.5px;">RTN: ${this.escape(data.company_rtn)}</div>
                    <div style="text-align:center;font-weight:800;margin:6px 0;padding:3px;background:#f1f5f9;border:1px solid #cbd5e1;">
                        PRE-CUENTA (NO ES FACTURA FISCAL)
                    </div>
                    <div><strong>Fecha:</strong> ${this.escape(data.printed_at)}</div>
                    <div><strong>Cuenta:</strong> ${this.escape(ord.order_name)} (${this.escape(ord.name)})</div>
                    ${ord.reference_note ? `<div><strong>Referencia:</strong> ${this.escape(ord.reference_note)}</div>` : ""}
                    <div><strong>Mesa:</strong> ${this.escape(ord.table_label || ord.service_type)} · <strong>Invitados:</strong> ${ord.guests || 1}</div>
                    <div><strong>Mesero:</strong> ${this.escape(ord.waiter_name || "General")}</div>
                    <div><strong>Cliente:</strong> ${this.escape(ord.customer_name)}</div>
                    <div><strong>RTN Cliente:</strong> ${this.escape(ord.tax_id || "______________________")}</div>
                    <div class="rpos-receipt-hr"></div>
                    ${(ord.items || []).map(it => `
                        <div style="display:flex;justify-content:space-between;font-weight:700;">
                            <span>${it.qty} x ${this.escape(it.item_name)}</span>
                            <span>${this.formatMoney(it.amount)}</span>
                        </div>
                        ${it.options_summary ? `<div style="font-size:11px;padding-left:14px;">- ${this.escape(it.options_summary)}</div>` : ""}
                    `).join("")}
                    <div class="rpos-receipt-hr"></div>
                    <div style="display:flex;justify-content:space-between;"><span>Subtotal:</span><span>${this.formatMoney(ord.subtotal)}</span></div>
                    <div style="display:flex;justify-content:space-between;"><span>Importe Exento:</span><span>${this.formatMoney(ord.exempt_amount)}</span></div>
                    <div style="display:flex;justify-content:space-between;"><span>Importe Gravado 15%:</span><span>${this.formatMoney(ord.taxed_amount_15)}</span></div>
                    <div style="display:flex;justify-content:space-between;"><span>ISV 15%:</span><span>${this.formatMoney(ord.isv_15)}</span></div>
                    <div style="display:flex;justify-content:space-between;"><span>ISV 18%:</span><span>${this.formatMoney(ord.isv_18)}</span></div>
                    <div style="display:flex;justify-content:space-between;">
                        <span>Servicio sugerido / Propina ${ord.tip_percentage > 0 ? `(${ord.tip_percentage}%)` : ""}:</span>
                        <span>${this.formatMoney(ord.tip_amount)}</span>
                    </div>
                    <div class="rpos-receipt-hr"></div>
                    <div style="display:flex;justify-content:space-between;font-size:15px;font-weight:800;">
                        <span>TOTAL SUGERIDO:</span>
                        <span>${this.formatMoney(ord.grand_total)}</span>
                    </div>
                    <div class="rpos-receipt-hr"></div>
                    <div style="font-size:11px;text-align:center;margin-top:8px;">
                        Verifique sus datos para factura con RTN.<br>¡Gracias por su visita!
                    </div>
                </div>
            `,
            `
                <button type="button" class="rpos-btn-secondary" data-precuenta-tip>Ajustar Propina</button>
                <button type="button" class="rpos-btn-primary" data-precuenta-print>🖨 Imprimir Pre-cuenta</button>
                <button type="button" class="rpos-btn-green" data-precuenta-pay>Pasar a Facturar</button>
            `,
            "520px"
        );

        backdrop.querySelector("[data-precuenta-tip]").addEventListener("click", () => {
            backdrop.remove();
            this.openTipModal();
        });

        backdrop.querySelector("[data-precuenta-print]").addEventListener("click", () => {
            const html = backdrop.querySelector("#rpos-printable-precuenta").outerHTML;
            const win = window.open("", "_blank", "width=420,height=640");
            if (win) {
                win.document.write(`<html><head><title>Pre-cuenta ${this.escape(ord.order_name)}</title></head><body style="font-family:monospace;padding:12px;">${html}</body></html>`);
                win.document.close();
                win.focus();
                win.print();
            }
        });

        backdrop.querySelector("[data-precuenta-pay]").addEventListener("click", () => {
            backdrop.remove();
            this.openPaymentModal();
        });
    }

    /* 10. Pago y Emisión de Factura Fiscal SAR (con CAI + RTN + Propina) */
    async openPaymentModal() {
        if (!this.currentOrder.items.length) {
            frappe.msgprint("Agrega al menos un platillo o bebida antes de proceder al pago.");
            return;
        }
        await this.persistCurrentOrderSilently();

        const customers = this.bootstrap?.customers || [];
        const mops = this.bootstrap?.modes_of_payment || [{ name: "Efectivo" }, { name: "Tarjetas de credito" }, { name: "Transferencia bancaria" }];
        const caiDefault = this.currentOrder.cai || this.bootstrap?.fiscal_defaults?.cai || "3A8F9E-12B4C6-78D0E2-9F1A3B-45C6D8-01";
        const dueCaiDefault = this.currentOrder.due_date_cai || this.bootstrap?.fiscal_defaults?.due_date_cai || "2026-12-31";
        const authRangeDefault = this.bootstrap?.fiscal_defaults?.authorized_range || "000-001-01-00000001 al 000-001-01-00050000";

        const backdrop = this.createModal(
            `Facturación Fiscal SAR y Pago · ${this.escape(this.currentOrder.order_name)}`,
            `
                <div style="display:grid;grid-template-columns:1.2fr 1fr;gap:12px;">
                    <div class="rpos-field">
                        <label>Cliente a facturar *</label>
                        <select data-pay-customer>
                            ${customers.map(c => `
                                <option value="${this.escape(c.name)}" data-rtn="${this.escape(c.tax_id || "")}" ${this.currentOrder.customer === c.name ? "selected" : ""}>
                                    ${this.escape(c.customer_name)}
                                </option>
                            `).join("")}
                        </select>
                    </div>
                    <div class="rpos-field">
                        <label>RTN del Cliente (Control Fiscal SAR)</label>
                        <input type="text" data-pay-rtn maxlength="60" placeholder="0801..." value="${this.escape(this.currentOrder.tax_id || "")}">
                    </div>
                </div>

                <div style="display:grid;grid-template-columns:1.3fr 0.7fr;gap:12px;">
                    <div class="rpos-field">
                        <label>CAI SAR Activo</label>
                        <input type="text" data-pay-cai value="${this.escape(caiDefault)}">
                    </div>
                    <div class="rpos-field">
                        <label>Fecha límite CAI</label>
                        <input type="date" data-pay-due-cai value="${this.escape(dueCaiDefault)}">
                    </div>
                </div>

                <div class="rpos-field">
                    <label>Rango Autorizado de Facturación SAR</label>
                    <input type="text" data-pay-auth-range value="${this.escape(authRangeDefault)}">
                </div>

                <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">
                    <div class="rpos-field">
                        <label>Método de pago</label>
                        <select data-pay-mop>
                            ${mops.map(m => `<option value="${this.escape(m.name)}" ${m.name === "Efectivo" ? "selected" : ""}>${this.escape(m.name)}</option>`).join("")}
                        </select>
                    </div>
                    <div class="rpos-field">
                        <label>Servicio sugerido / Propina (L)</label>
                        <input type="number" step="0.01" min="0" data-pay-tip value="${Number(this.currentOrder.tip_amount || 0).toFixed(2)}">
                    </div>
                </div>

                <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">
                    <div class="rpos-field">
                        <label>Monto recibido (L)</label>
                        <input type="number" step="0.01" min="0" data-pay-tendered value="${Number(this.currentOrder.grand_total).toFixed(2)}">
                    </div>
                    <div class="rpos-field">
                        <label>Cambio a entregar</label>
                        <input type="text" data-pay-change readonly value="L 0.00" style="color:#16a34a;font-weight:800;">
                    </div>
                </div>

                <div style="background:#f8fafc;border:1px solid #cbd5e1;border-radius:8px;padding:12px;margin-top:6px;">
                    <div style="display:flex;justify-content:space-between;font-size:13px;color:#475569;">
                        <span>Subtotal gravado / exento:</span>
                        <span>${this.formatMoney(this.currentOrder.subtotal)}</span>
                    </div>
                    <div style="display:flex;justify-content:space-between;font-size:13px;color:#475569;">
                        <span>ISV 15% (${this.formatMoney(this.currentOrder.isv_15)}) + ISV 18% (${this.formatMoney(this.currentOrder.isv_18)}):</span>
                        <span>${this.formatMoney(this.currentOrder.tax_amount)}</span>
                    </div>
                    <div style="display:flex;justify-content:space-between;font-size:18px;font-weight:800;color:#0f172a;margin-top:6px;padding-top:6px;border-top:1px solid #cbd5e1;">
                        <span>Total Factura SAR:</span>
                        <span data-pay-grand-label>${this.formatMoney(this.currentOrder.grand_total)}</span>
                    </div>
                </div>
            `,
            `
                <button type="button" class="rpos-btn-secondary" data-modal-close>Volver</button>
                <button type="button" class="rpos-btn-green" data-pay-submit>✓ Emitir Factura SAR y Cobrar</button>
            `,
            "640px"
        );

        const custSel = backdrop.querySelector("[data-pay-customer]");
        const rtnInp = backdrop.querySelector("[data-pay-rtn]");
        const tipInp = backdrop.querySelector("[data-pay-tip]");
        const tenderedInp = backdrop.querySelector("[data-pay-tendered]");
        const changeInp = backdrop.querySelector("[data-pay-change]");
        const grandLbl = backdrop.querySelector("[data-pay-grand-label]");

        const refreshPaymentMath = () => {
            const tip = Math.max(0, Number(tipInp.value || 0));
            const grand = Number((this.currentOrder.subtotal + this.currentOrder.tax_amount + tip).toFixed(2));
            grandLbl.textContent = this.formatMoney(grand);
            const tendered = Math.max(0, Number(tenderedInp.value || 0));
            const change = Math.max(0, Number((tendered - grand).toFixed(2)));
            changeInp.value = this.formatMoney(change);
            return { tip, grand, tendered };
        };

        custSel.addEventListener("change", () => {
            const opt = custSel.selectedOptions[0];
            if (opt?.dataset?.rtn) rtnInp.value = opt.dataset.rtn;
        });
        tipInp.addEventListener("input", () => {
            const { grand } = refreshPaymentMath();
            tenderedInp.value = grand.toFixed(2);
            refreshPaymentMath();
        });
        tenderedInp.addEventListener("input", refreshPaymentMath);

        backdrop.querySelector("[data-pay-submit]").addEventListener("click", async () => {
            const { tip, grand, tendered } = refreshPaymentMath();
            if (tendered < grand) {
                frappe.msgprint("El monto recibido no puede ser menor al total de la factura.");
                return;
            }
            const mop = backdrop.querySelector("[data-pay-mop]").value;
            const res = await frappe.call({
                method: "restaurant.pos.pay_and_invoice_order",
                args: {
                    order_name: this.currentOrder.name,
                    customer: custSel.value,
                    tax_id: rtnInp.value.trim(),
                    cai: backdrop.querySelector("[data-pay-cai]").value.trim(),
                    due_date_cai: backdrop.querySelector("[data-pay-due-cai]").value,
                    authorized_range: backdrop.querySelector("[data-pay-auth-range]").value.trim(),
                    tip_percentage: 0,
                    tip_amount: tip,
                    payments: [{ mode_of_payment: mop, amount: grand }],
                },
                freeze: true,
                freeze_message: "Emitiendo Factura Fiscal SAR y registrando pago...",
            });

            backdrop.remove();
            const invoice = res.message.invoice;
            const finishedOrder = res.message.order;
            this.bootstrap.areas = res.message.areas || this.bootstrap.areas;
            this.upsertOrderInBootstrap(finishedOrder);
            this.currentOrder = this.createBlankOrder();
            this.selectedLineIndex = -1;
            this.render();
            this.showInvoiceReceiptModal(invoice, finishedOrder);
        });
    }

    showInvoiceReceiptModal(invoice, order) {
        const backdrop = this.createModal(
            `Factura Fiscal Emitida · ${this.escape(invoice.name)}`,
            `
                <div class="rpos-receipt-paper" id="rpos-printable-invoice">
                    <h4>${this.escape(invoice.company)}</h4>
                    <div style="text-align:center;font-size:11.5px;">RTN Empresa: ${this.escape(invoice.company_tax_id)}</div>
                    <div style="text-align:center;font-weight:800;margin:6px 0;padding:3px;background:#dcfce7;border:1px solid #86efac;">
                        FACTURA FISCAL SAR: ${this.escape(invoice.name)}
                    </div>
                    <div><strong>CAI:</strong> ${this.escape(invoice.cai)}</div>
                    <div><strong>Fecha Límite Emisión:</strong> ${this.escape(invoice.due_date_cai)}</div>
                    ${invoice.authorized_range ? `<div><strong>Rango Autorizado:</strong> ${this.escape(invoice.authorized_range)}</div>` : ""}
                    <div><strong>Fecha:</strong> ${this.escape(invoice.posting_date)}</div>
                    <div><strong>Cuenta / Mesa:</strong> ${this.escape(order.order_name)} ${order.table_label ? `(Mesa ${this.escape(order.table_label)})` : ""}</div>
                    <div><strong>Mesero:</strong> ${this.escape(order.waiter_name || "General")}</div>
                    <div><strong>Cliente:</strong> ${this.escape(invoice.customer_name)}</div>
                    <div><strong>RTN Cliente:</strong> ${this.escape(invoice.tax_id || "CONSUMIDOR FINAL")}</div>
                    <div class="rpos-receipt-hr"></div>
                    ${(order.items || []).map(it => `
                        <div style="display:flex;justify-content:space-between;font-weight:700;">
                            <span>${it.qty} x ${this.escape(it.item_name)}</span>
                            <span>${this.formatMoney(it.amount)}</span>
                        </div>
                    `).join("")}
                    <div class="rpos-receipt-hr"></div>
                    <div style="display:flex;justify-content:space-between;"><span>Importe Exonerado:</span><span>${this.formatMoney(invoice.exonerated_amount)}</span></div>
                    <div style="display:flex;justify-content:space-between;"><span>Importe Exento:</span><span>${this.formatMoney(invoice.exempt_amount)}</span></div>
                    <div style="display:flex;justify-content:space-between;"><span>Importe Gravado 15%:</span><span>${this.formatMoney(invoice.taxed_amount_15)}</span></div>
                    <div style="display:flex;justify-content:space-between;"><span>Importe Gravado 18%:</span><span>${this.formatMoney(invoice.taxed_amount_18)}</span></div>
                    <div style="display:flex;justify-content:space-between;"><span>ISV 15%:</span><span>${this.formatMoney(invoice.isv_15)}</span></div>
                    <div style="display:flex;justify-content:space-between;"><span>ISV 18%:</span><span>${this.formatMoney(invoice.isv_18)}</span></div>
                    <div style="display:flex;justify-content:space-between;"><span>Servicio / Propina:</span><span>${this.formatMoney(invoice.tip_amount)}</span></div>
                    <div class="rpos-receipt-hr"></div>
                    <div style="display:flex;justify-content:space-between;font-size:15px;font-weight:800;">
                        <span>TOTAL FACTURADO:</span>
                        <span>${this.formatMoney(invoice.grand_total)}</span>
                    </div>
                </div>
            `,
            `
                <button type="button" class="rpos-btn-secondary" data-inv-desk>Ver en ERPNext</button>
                <button type="button" class="rpos-btn-primary" data-inv-print>🖨 Imprimir Factura</button>
                <button type="button" class="rpos-btn-green" data-modal-close>Nueva Venta</button>
            `,
            "520px"
        );

        backdrop.querySelector("[data-inv-desk]").addEventListener("click", () => {
            backdrop.remove();
            frappe.set_route("Form", "Sales Invoice", invoice.name);
        });
        backdrop.querySelector("[data-inv-print]").addEventListener("click", () => {
            const html = backdrop.querySelector("#rpos-printable-invoice").outerHTML;
            const win = window.open("", "_blank", "width=420,height=680");
            if (win) {
                win.document.write(`<html><head><title>Factura ${this.escape(invoice.name)}</title></head><body style="font-family:monospace;padding:12px;">${html}</body></html>`);
                win.document.close();
                win.focus();
                win.print();
            }
        });
    }

    async sendToKitchen() {
        if (!this.currentOrder.items.length) {
            frappe.msgprint("Agrega platillos antes de comandar.");
            return;
        }
        await this.persistCurrentOrderSilently();

        // Count pending lines per station so each tile shows what will be sent.
        const pendingByStation = {};
        let pendingTotal = 0;
        (this.currentOrder.items || []).forEach(row => {
            if ((row.kds_status || "Pendiente") !== "Pendiente") return;
            pendingTotal += 1;
            String(row.command_station || "Cocina General").split(",").map(s => s.trim()).filter(Boolean)
                .forEach(st => { pendingByStation[st] = (pendingByStation[st] || 0) + 1; });
        });
        const stations = [...new Set([...(this.bootstrap?.command_stations || []), ...Object.keys(pendingByStation)])]
            .filter(st => st !== "Cocina General" || pendingByStation[st]);

        const printerSvg = `<svg viewBox="0 0 24 24" width="44" height="44" fill="currentColor" aria-hidden="true"><path d="M6 3h12v5H6z" opacity=".85"/><path d="M4 9h16a2 2 0 0 1 2 2v6h-4v4H6v-4H2v-6a2 2 0 0 1 2-2Zm4 8v2h8v-4H8Zm10-5.5a1 1 0 1 0 0 2 1 1 0 0 0 0-2Z"/></svg>`;
        const tile = (station, label, count) => `
            <button type="button" class="rpos-command-tile" data-cmd-station="${this.escape(station)}" ${count ? "" : "data-empty=\"1\""}>
                <span class="rpos-command-icon">${printerSvg}</span>
                <span class="rpos-command-label">${this.escape(label)}</span>
                <span class="rpos-command-count">${count ? `${count} pendiente(s)` : "Sin pendientes"}</span>
            </button>`;

        const backdrop = this.createModal(
            `Comandar · ${this.escape(this.currentOrder.order_name || "Orden")}`,
            `
                <p style="color:#475569;font-size:13px;margin-top:0;">
                    Selecciona el destino de la comanda. Solo se envían los platillos que aún no se han comandado.
                </p>
                <div class="rpos-command-grid">
                    ${stations.map(st => tile(st, `Comandas ${st}`, pendingByStation[st] || 0)).join("")}
                    ${tile("ALL", "Comandar todo", pendingTotal)}
                </div>
                <label style="display:flex;align-items:center;gap:8px;margin-top:14px;font-size:12.5px;color:#334155;">
                    <input type="checkbox" data-cmd-reprint> Reimprimir también platillos ya comandados
                </label>
            `,
            `<button type="button" class="rpos-btn-secondary" data-modal-close>Cerrar</button>`,
            "620px"
        );

        backdrop.querySelectorAll("[data-cmd-station]").forEach(btn => {
            btn.addEventListener("click", async () => {
                const reprint = backdrop.querySelector("[data-cmd-reprint]").checked;
                if (btn.dataset.empty && !reprint) {
                    frappe.msgprint("No hay platillos pendientes para este destino. Marca «Reimprimir» si necesitas otra copia.");
                    return;
                }
                const res = await frappe.call({
                    method: "restaurant.pos.send_order_to_kitchen",
                    args: {
                        order_name: this.currentOrder.name,
                        station: btn.dataset.cmdStation,
                        include_sent: reprint ? 1 : 0,
                    },
                    freeze: true,
                    freeze_message: "Enviando comanda...",
                });
                backdrop.remove();
                this.currentOrder = res.message.order;
                this.upsertOrderInBootstrap(this.currentOrder);
                this.render();
                this.printCommandTickets(res.message.stations || {}, res.message.sent_at);
                frappe.show_alert({
                    message: `Comanda enviada a: ${Object.keys(res.message.stations || {}).join(", ")}`,
                    indicator: "green",
                });
            });
        });
    }

    printCommandTickets(stations, sentAt) {
        const order = this.currentOrder;
        const tickets = Object.entries(stations).map(([station, lines]) => `
            <section style="page-break-after:always;font-family:monospace;font-size:13px;width:280px;">
                <h3 style="text-align:center;margin:0 0 4px;">COMANDA · ${this.escape(station).toUpperCase()}</h3>
                <div>Cuenta: ${this.escape(order.order_name)}</div>
                <div>Mesa: ${this.escape(order.table_label || order.service_type)}</div>
                <div>Mesero: ${this.escape(order.waiter_name || "General")}</div>
                <div>Hora: ${this.escape(sentAt || "")}</div>
                <hr style="border-top:1px dashed #000;">
                ${lines.map(l => `
                    <div style="font-size:15px;font-weight:bold;">${l.qty} x ${this.escape(l.item_name)}</div>
                    ${l.options_summary ? `<div style="padding-left:12px;">- ${this.escape(l.options_summary)}</div>` : ""}
                    ${l.note ? `<div style="padding-left:12px;">** ${this.escape(l.note)} **</div>` : ""}
                `).join("")}
                <hr style="border-top:1px dashed #000;">
            </section>`).join("");
        const win = window.open("", "_blank", "width=360,height=600");
        if (!win) return;
        win.document.write(`<html><head><title>Comanda ${this.escape(order.order_name)}</title></head><body>${tickets}</body></html>`);
        win.document.close();
        win.focus();
        win.print();
    }

    /* Acciones adicionales: Dividir, Transferir, Nota cliente, Cancelar, Menú POS */
    async openSplitOrderModal() {
        if (!this.currentOrder.items.length || this.currentOrder.items.length < 1) {
            frappe.msgprint("La cuenta necesita platillos para poder dividirse.");
            return;
        }
        await this.persistCurrentOrderSilently();
        const items = this.currentOrder.items || [];
        const backdrop = this.createModal(
            `Dividir Cuenta · ${this.escape(this.currentOrder.order_name)}`,
            `
                <p style="color:#475569;font-size:13px;margin-top:0;">
                    Indica qué cantidad de cada platillo deseas separar hacia la nueva cuenta (Cuenta 2):
                </p>
                ${items.map(it => `
                    <div style="display:flex;align-items:center;justify-content:space-between;padding:8px 0;border-bottom:1px solid #e2e8f0;">
                        <div>
                            <div style="font-weight:700;color:#0f172a;">${this.escape(it.item_name)}</div>
                            <div style="font-size:12px;color:#64748b;">En cuenta actual: ${it.qty} · ${this.formatMoney(it.rate)} c/u</div>
                        </div>
                        <input type="number" min="0" max="${it.qty}" step="1" value="0" data-split-idx="${it.idx}" style="width:90px;background:#ffffff;color:#0f172a;border:1px solid #cbd5e1;border-radius:6px;padding:6px;">
                    </div>
                `).join("")}
            `,
            `
                <button type="button" class="rpos-btn-secondary" data-modal-close>Cancelar</button>
                <button type="button" class="rpos-btn-primary" data-split-confirm>Dividir en 2 Cuentas</button>
            `,
            "540px"
        );

        backdrop.querySelector("[data-split-confirm]").addEventListener("click", async () => {
            const splitRows = [];
            backdrop.querySelectorAll("[data-split-idx]").forEach(inp => {
                const q = Number(inp.value || 0);
                if (q > 0) splitRows.push({ idx: Number(inp.dataset.splitIdx), qty: q });
            });
            if (!splitRows.length) {
                frappe.msgprint("Selecciona una cantidad mayor a cero en al menos un platillo.");
                return;
            }
            const res = await frappe.call({
                method: "restaurant.pos.split_order",
                args: { order_name: this.currentOrder.name, split_items: splitRows },
                freeze: true,
                freeze_message: "Dividiendo cuenta...",
            });
            backdrop.remove();
            this.currentOrder = res.message.original_order;
            this.upsertOrderInBootstrap(res.message.original_order);
            this.upsertOrderInBootstrap(res.message.new_order);
            this.bootstrap.areas = res.message.areas || this.bootstrap.areas;
            frappe.show_alert({ message: `Se creó ${res.message.new_order.order_name}`, indicator: "green" });
            this.render();
        });
    }

    async openTransferTableModal() {
        if (!this.currentOrder.name) {
            await this.persistCurrentOrderSilently();
        }
        const allTables = [];
        (this.bootstrap?.areas || []).forEach(a => {
            (a.tables || []).forEach(t => {
                allTables.push({ ...t, area_label: a.area_name });
            });
        });
        const backdrop = this.createModal(
            "Transferir o Fusionar Mesa",
            `
                <div class="rpos-field">
                    <label>Selecciona la mesa destino (si está ocupada, las cuentas se fusionarán)</label>
                    <select data-transfer-target>
                        ${allTables.map(t => `
                            <option value="${this.escape(t.name)}">
                                Mesa ${this.escape(t.table_number)} · ${this.escape(t.area_label)} (${this.escape(t.status)})
                            </option>
                        `).join("")}
                    </select>
                </div>
            `,
            `
                <button type="button" class="rpos-btn-secondary" data-modal-close>Cancelar</button>
                <button type="button" class="rpos-btn-primary" data-transfer-confirm>Confirmar transferencia</button>
            `,
            "480px"
        );

        backdrop.querySelector("[data-transfer-confirm]").addEventListener("click", async () => {
            const target = backdrop.querySelector("[data-transfer-target]").value;
            const res = await frappe.call({
                method: "restaurant.pos.transfer_order_table",
                args: { order_name: this.currentOrder.name, target_table: target },
                freeze: true,
                freeze_message: "Transfiriendo mesa...",
            });
            backdrop.remove();
            this.currentOrder = res.message.order;
            this.bootstrap.areas = res.message.areas || this.bootstrap.areas;
            await this.loadBootstrap();
            this.render();
            frappe.show_alert({
                message: res.message.merged ? "Cuentas fusionadas en la mesa destino" : "Mesa transferida correctamente",
                indicator: "green",
            });
        });
    }

    openCustomerNoteModal() {
        const backdrop = this.createModal(
            "Nota general para el cliente / factura",
            `
                <div class="rpos-field">
                    <label>Observación general de la cuenta</label>
                    <textarea rows="3" data-cust-note-txt>${this.escape(this.currentOrder.customer_note || "")}</textarea>
                </div>
            `,
            `
                <button type="button" class="rpos-btn-secondary" data-modal-close>Cancelar</button>
                <button type="button" class="rpos-btn-primary" data-cust-note-save>Guardar</button>
            `,
            "480px"
        );
        backdrop.querySelector("[data-cust-note-save]").addEventListener("click", async () => {
            this.currentOrder.customer_note = backdrop.querySelector("[data-cust-note-txt]").value.trim();
            backdrop.remove();
            await this.persistCurrentOrderSilently();
        });
    }

    openPriceListModal() {
        const lists = this.bootstrap?.price_lists || [{ name: "Venta estándar" }];
        const backdrop = this.createModal(
            "Seleccionar Lista de Precios",
            `
                <div class="rpos-field">
                    <label>Lista de precios activa</label>
                    <select data-pl-select>
                        ${lists.map(pl => `<option value="${this.escape(pl.name)}" ${this.currentOrder.selling_price_list === pl.name ? "selected" : ""}>${this.escape(pl.name)}</option>`).join("")}
                    </select>
                </div>
            `,
            `
                <button type="button" class="rpos-btn-secondary" data-modal-close>Cancelar</button>
                <button type="button" class="rpos-btn-primary" data-pl-save>Aplicar</button>
            `,
            "440px"
        );
        backdrop.querySelector("[data-pl-save]").addEventListener("click", async () => {
            this.currentOrder.selling_price_list = backdrop.querySelector("[data-pl-select]").value;
            backdrop.remove();
            await this.persistCurrentOrderSilently();
        });
    }

    openOrderInfoModal() {
        this.createModal(
            "Información de la Orden y Turno",
            `
                <div style="font-size:13.5px;line-height:1.7;">
                    <div><strong>ID Interno:</strong> ${this.escape(this.currentOrder.name || "Sin guardar")}</div>
                    <div><strong>Nombre de la Cuenta:</strong> ${this.escape(this.currentOrder.order_name || "N/A")}</div>
                    <div><strong>Referencia:</strong> ${this.escape(this.currentOrder.reference_note || "N/A")}</div>
                    <div><strong>Mesero:</strong> ${this.escape(this.currentOrder.waiter_name || "N/A")}</div>
                    <div><strong>Cliente:</strong> ${this.escape(this.currentOrder.customer_name)} (RTN: ${this.escape(this.currentOrder.tax_id || "Sin RTN")})</div>
                    <div><strong>Cajero en Turno:</strong> ${this.escape(this.bootstrap?.cashier?.full_name)}</div>
                    <div><strong>Turno POS:</strong> ${this.escape(this.bootstrap?.opening_shift?.name || "N/A")}</div>
                    <div><strong>Estado KDS:</strong> ${this.escape(this.currentOrder.kds_status)}</div>
                </div>
            `,
            `<button type="button" class="rpos-btn-secondary" data-modal-close>Cerrar</button>`,
            "480px"
        );
    }

    async cancelCurrentOrder() {
        if (!this.currentOrder.name) {
            this.currentOrder = this.createBlankOrder();
            this.selectedLineIndex = -1;
            this.render();
            return;
        }
        await this.cancelOrderById(this.currentOrder.name);
    }

    async cancelOrderById(orderName) {
        const res = await frappe.call({
            method: "restaurant.pos.cancel_pos_order",
            args: { order_name: orderName },
            freeze: true,
            freeze_message: "Cancelando orden...",
        });
        if (this.currentOrder.name === orderName) {
            this.currentOrder = this.createBlankOrder();
            this.selectedLineIndex = -1;
        }
        this.bootstrap.areas = res.message.areas || this.bootstrap.areas;
        this.upsertOrderInBootstrap(res.message.order);
        this.render();
        frappe.show_alert({ message: "Orden cancelada y mesa liberada", indicator: "orange" });
    }

    openQuickTableNumberModal() {
        const backdrop = this.createModal(
            "Ir a Mesa por Número",
            `
                <div class="rpos-field">
                    <label>Ingresa el número o código de la mesa</label>
                    <input type="text" data-quick-tbl-num placeholder="Ej. 1, 4, Cancha 1...">
                </div>
            `,
            `
                <button type="button" class="rpos-btn-secondary" data-modal-close>Cancelar</button>
                <button type="button" class="rpos-btn-primary" data-quick-tbl-go>Abrir mesa</button>
            `,
            "420px"
        );
        backdrop.querySelector("[data-quick-tbl-go]").addEventListener("click", () => {
            const code = backdrop.querySelector("[data-quick-tbl-num]").value.trim().toLowerCase();
            if (!code) return;
            for (const area of (this.bootstrap?.areas || [])) {
                const found = (area.tables || []).find(t => String(t.table_number).toLowerCase() === code);
                if (found) {
                    this.selectedAreaName = area.name;
                    backdrop.remove();
                    this.handleTableClick(found.name);
                    return;
                }
            }
            frappe.msgprint("No se encontró una mesa con ese número.");
        });
    }

    openPosMenuModal() {
        const shift = this.bootstrap?.opening_shift;
        const shiftCode = shift?.pos_profile
            ? String(shift.pos_profile).slice(0, 18)
            : "LNA";
        const themeLabel = this.darkMode ? "Cambiar al modo claro" : "Cambiar al modo oscuro";

        const existing = document.querySelector(".rpos-modal-backdrop");
        if (existing) existing.remove();

        const backdrop = document.createElement("div");
        backdrop.className = "rpos-modal-backdrop";
        backdrop.innerHTML = `
            <div class="rpos-modal rpos-pos-menu-modal" style="max-width:740px;">
                <div class="rpos-modal-header rpos-pos-menu-header">
                    <span class="rpos-menu-status-pill" title="${shift ? `Turno activo: ${this.escape(shift.name)}` : "Sin turno activo"}">
                        <span class="rpos-menu-status-dot ${shift ? "is-online" : ""}"></span>
                        <span>${this.escape(shiftCode)}</span>
                    </span>
                    <button type="button" class="rpos-icon-btn" data-modal-close>×</button>
                </div>
                <div class="rpos-modal-body">
                    <div class="rpos-pos-menu-grid">
                        <button type="button" class="rpos-pos-menu-tile" data-menu-tile="customer-display">
                            <span class="rpos-pos-menu-icon" aria-hidden="true">
                                <svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                                    <rect x="2" y="3" width="20" height="14" rx="2"/>
                                    <line x1="8" y1="21" x2="16" y2="21"/>
                                    <line x1="12" y1="17" x2="12" y2="21"/>
                                </svg>
                            </span>
                            <span>Customer Display</span>
                        </button>

                        <button type="button" class="rpos-pos-menu-tile" data-menu-tile="toggle-theme">
                            <span class="rpos-pos-menu-icon" aria-hidden="true">
                                <svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                                    <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>
                                </svg>
                            </span>
                            <span>${this.escape(themeLabel)}</span>
                        </button>

                        <button type="button" class="rpos-pos-menu-tile" data-menu-tile="cash-movement">
                            <span class="rpos-pos-menu-icon" aria-hidden="true">
                                <svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                                    <rect x="2" y="6" width="20" height="12" rx="2"/>
                                    <circle cx="12" cy="12" r="2.5"/>
                                    <path d="M6 12h.01M18 12h.01"/>
                                </svg>
                            </span>
                            <span>Entrada/salida de efectivo</span>
                        </button>

                        <button type="button" class="rpos-pos-menu-tile" data-menu-tile="create-product">
                            <span class="rpos-pos-menu-icon" aria-hidden="true">
                                <svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
                                    <line x1="12" y1="5" x2="12" y2="19"/>
                                    <line x1="5" y1="12" x2="19" y2="12"/>
                                </svg>
                            </span>
                            <span>Crear Productos</span>
                        </button>

                        <button type="button" class="rpos-pos-menu-tile" data-menu-tile="reprint-commands">
                            <span class="rpos-pos-menu-icon" aria-hidden="true">
                                <svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                                    <polyline points="6 9 6 2 18 2 18 9"/>
                                    <path d="M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2"/>
                                    <rect x="6" y="14" width="12" height="8"/>
                                </svg>
                            </span>
                            <span>Reimprimir Comandas</span>
                        </button>

                        <button type="button" class="rpos-pos-menu-tile is-danger" data-menu-tile="close-register">
                            <span class="rpos-pos-menu-icon" aria-hidden="true">
                                <svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                                    <path d="M21 2l-2 2m-7.61 7.61a5.5 5.5 0 1 1-7.778 7.778 5.5 5.5 0 0 1 7.777-7.777zm0 0L15.5 7.5m0 0l3 3L22 7l-3-3m-3.5 3.5L19 4"/>
                                </svg>
                            </span>
                            <span>Cerrar caja registradora</span>
                        </button>
                    </div>
                </div>
            </div>
        `;

        backdrop.querySelectorAll("[data-modal-close]").forEach(btn => {
            btn.addEventListener("click", () => backdrop.remove());
        });
        document.body.appendChild(backdrop);

        backdrop.querySelectorAll("[data-menu-tile]").forEach(btn => {
            btn.addEventListener("click", () => {
                const tile = btn.dataset.menuTile;
                backdrop.remove();
                if (tile === "customer-display") return this.openCustomerDisplayModal();
                if (tile === "toggle-theme") return this.toggleDarkMode();
                if (tile === "cash-movement") return this.openCashMovementModal();
                if (tile === "create-product") return this.openCreateProductModal();
                if (tile === "reprint-commands") return this.openReprintCommandsModal();
                if (tile === "close-register") return this.openCloseRegisterModal();
            });
        });
    }

    toggleDarkMode() {
        this.darkMode = !this.darkMode;
        try {
            window.localStorage?.setItem("rpos_dark_mode", this.darkMode ? "1" : "0");
        } catch (e) {
            // Ignore storage restrictions
        }
        this.shell.classList.toggle("is-dark-mode", Boolean(this.darkMode));
        this.render();
    }

    openCustomerDisplayModal() {
        this.recalculateLocalTotals();
        const ord = this.currentOrder;
        const companyName = this.bootstrap?.company?.name || "LEAF RESTAURANT";
        const backdrop = this.createModal(
            `Customer Display · ${this.escape(companyName)}`,
            `
                <div id="rpos-customer-display-box" style="background:#0f172a;color:#f8fafc;border-radius:10px;padding:20px;">
                    <div style="display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid #334155;padding-bottom:12px;margin-bottom:14px;">
                        <div>
                            <div style="font-size:18px;font-weight:800;color:#4ade80;">LEAF RESTAURANT</div>
                            <div style="font-size:13px;color:#94a3b8;">Cuenta: ${this.escape(ord.order_name || "Venta directa")} · Cliente: ${this.escape(ord.customer_name || "Consumidor Final")}</div>
                        </div>
                        <div style="text-align:right;">
                            <div style="font-size:12px;color:#94a3b8;">TOTAL A PAGAR</div>
                            <div style="font-size:28px;font-weight:800;color:#38bdf8;">${this.formatMoney(ord.grand_total)}</div>
                        </div>
                    </div>
                    <div style="max-height:240px;overflow-y:auto;margin-bottom:14px;">
                        ${(ord.items || []).length ? ord.items.map(it => `
                            <div style="display:flex;justify-content:space-between;padding:8px 0;border-bottom:1px solid #1e293b;font-size:15px;">
                                <span><strong>${it.qty}x</strong> ${this.escape(it.item_name)} ${it.options_summary ? `<small style="color:#94a3b8;">(${this.escape(it.options_summary)})</small>` : ""}</span>
                                <span style="font-weight:700;">${this.formatMoney(it.amount)}</span>
                            </div>
                        `).join("") : `<div style="text-align:center;color:#94a3b8;padding:24px;">Bienvenido a LEAF Restaurant.</div>`}
                    </div>
                    <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:10px;border-top:1px solid #334155;padding-top:12px;font-size:13px;color:#cbd5e1;">
                        <div>Subtotal: <strong>${this.formatMoney(ord.subtotal)}</strong></div>
                        <div>ISV: <strong>${this.formatMoney(ord.tax_amount)}</strong></div>
                        <div>Propina: <strong>${this.formatMoney(ord.tip_amount)}</strong></div>
                    </div>
                </div>
            `,
            `
                <button type="button" class="rpos-btn-secondary" data-modal-close>Cerrar</button>
                <button type="button" class="rpos-btn-primary" data-cust-disp-popup>Abrir en pantalla secundaria</button>
            `,
            "640px"
        );

        backdrop.querySelector("[data-cust-disp-popup]").addEventListener("click", () => {
            const html = backdrop.querySelector("#rpos-customer-display-box").outerHTML;
            const win = window.open("", "LeafCustomerDisplay", "width=800,height=600");
            if (win) {
                win.document.write(`<html><head><title>LEAF Restaurant - Customer Display</title></head><body style="margin:0;background:#0f172a;font-family:sans-serif;padding:24px;">${html}</body></html>`);
                win.document.close();
            }
        });
    }

    async openCashMovementModal() {
        const shift = this.bootstrap?.opening_shift;
        if (!shift) {
            this.openShiftDialog();
            return;
        }
        const res = await frappe.call({
            method: "restaurant.pos.get_shift_cash_movements",
            args: { pos_opening_shift: shift.name },
        });
        const data = res.message || { movements: [], total_ingreso: 0, total_retiro: 0, net_cash_movement: 0 };

        const backdrop = this.createModal(
            "Entrada / Salida de Efectivo (POS Awesome)",
            `
                <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-bottom:14px;">
                    <div style="background:#f0fdf4;border:1px solid #86efac;border-radius:8px;padding:10px;text-align:center;">
                        <div style="font-size:11.5px;color:#166534;font-weight:700;">Total Entradas (Ingreso)</div>
                        <div style="font-size:16px;font-weight:800;color:#15803d;" data-cm-in>${this.formatMoney(data.total_ingreso)}</div>
                    </div>
                    <div style="background:#fef2f2;border:1px solid #fca5a5;border-radius:8px;padding:10px;text-align:center;">
                        <div style="font-size:11.5px;color:#991b1b;font-weight:700;">Total Salidas (Retiro)</div>
                        <div style="font-size:16px;font-weight:800;color:#dc2626;" data-cm-out>${this.formatMoney(data.total_retiro)}</div>
                    </div>
                    <div style="background:#f8fafc;border:1px solid #cbd5e1;border-radius:8px;padding:10px;text-align:center;">
                        <div style="font-size:11.5px;color:#334155;font-weight:700;">Efectivo Neto Movimientos</div>
                        <div style="font-size:16px;font-weight:800;color:#0f172a;" data-cm-net>${this.formatMoney(data.net_cash_movement)}</div>
                    </div>
                </div>

                <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">
                    <div class="rpos-field">
                        <label>Tipo de transacción *</label>
                        <select data-cm-type>
                            <option value="Ingreso">Entrada de efectivo (Ingreso)</option>
                            <option value="Retiro">Salida de efectivo (Retiro)</option>
                        </select>
                    </div>
                    <div class="rpos-field">
                        <label>Monto en Lempiras (L) *</label>
                        <input type="number" step="0.01" min="0.01" data-cm-amount placeholder="0.00">
                    </div>
                </div>
                <div class="rpos-field">
                    <label>Motivo / Nota del movimiento *</label>
                    <input type="text" data-cm-note placeholder="Ej. Cambio sencillo para caja, pago proveedor menor, retiro parcial...">
                </div>

                <div style="margin-top:14px;">
                    <div style="font-size:12.5px;font-weight:700;color:#334155;margin-bottom:6px;">Movimientos registrados en este turno (${this.escape(shift.name)})</div>
                    <div style="max-height:170px;overflow-y:auto;border:1px solid #e2e8f0;border-radius:7px;" data-cm-list>
                        ${(data.movements || []).length ? data.movements.map(m => `
                            <div style="display:flex;justify-content:space-between;align-items:center;padding:8px 12px;border-bottom:1px solid #f1f5f9;font-size:12.5px;">
                                <div>
                                    <span style="font-weight:700;color:${m.type_transaction === "Ingreso" ? "#16a34a" : "#dc2626"};">${this.escape(m.type_transaction)}</span>
                                    <span> · ${this.escape(m.note)}</span>
                                    <div style="font-size:11px;color:#64748b;">${this.escape(m.name)} · ${this.escape(String(m.posting_date).slice(0, 19))}</div>
                                </div>
                                <strong style="color:${m.type_transaction === "Ingreso" ? "#16a34a" : "#dc2626"};">
                                    ${m.type_transaction === "Ingreso" ? "+" : "-"} ${this.formatMoney(m.amount)}
                                </strong>
                            </div>
                        `).join("") : `<div style="padding:14px;text-align:center;color:#64748b;font-size:12.5px;">Sin movimientos de efectivo en este turno.</div>`}
                    </div>
                </div>
            `,
            `
                <button type="button" class="rpos-btn-secondary" data-modal-close>Cancelar</button>
                <button type="button" class="rpos-btn-primary" data-cm-submit>Registrar Movimiento</button>
            `,
            "620px"
        );

        backdrop.querySelector("[data-cm-submit]").addEventListener("click", async () => {
            const txType = backdrop.querySelector("[data-cm-type]").value;
            const amount = Number(backdrop.querySelector("[data-cm-amount]").value || 0);
            const note = backdrop.querySelector("[data-cm-note]").value.trim();
            if (amount <= 0) {
                frappe.msgprint("Ingresa un monto válido mayor que cero.");
                return;
            }
            if (!note) {
                frappe.msgprint("Ingresa el motivo o descripción del movimiento de efectivo.");
                return;
            }
            const saveRes = await frappe.call({
                method: "restaurant.pos.create_cash_movement",
                args: {
                    type_transaction: txType,
                    amount,
                    note,
                    pos_opening_shift: shift.name,
                },
                freeze: true,
                freeze_message: "Registrando movimiento de efectivo en POS Awesome...",
            });
            backdrop.remove();
            frappe.show_alert({
                message: `${txType} de ${this.formatMoney(amount)} registrado (${saveRes.message?.created?.name || ""})`,
                indicator: "green",
            });
        });
    }

    openCreateProductModal() {
        const categories = this.bootstrap?.categories || [];
        const backdrop = this.createModal(
            "Crear Producto o Platillo · Catálogo de Restaurante",
            `
                <div style="display:grid;grid-template-columns:1.3fr 0.7fr;gap:12px;">
                    <div class="rpos-field">
                        <label>Nombre del producto o platillo *</label>
                        <input type="text" data-prod-name placeholder="Ej. Hamburguesa Doble Queso, Limonada con Hierbabuena...">
                    </div>
                    <div class="rpos-field">
                        <label>Código (opcional)</label>
                        <input type="text" data-prod-code placeholder="Automático si se deja vacío">
                    </div>
                </div>
                <div style="display:grid;grid-template-columns:1fr 1fr 0.7fr;gap:12px;">
                    <div class="rpos-field">
                        <label>Categoría (Grupo de artículos) *</label>
                        <select data-prod-group>
                            ${categories.map(c => `<option value="${this.escape(c.name)}">${this.escape(c.label)}</option>`).join("")}
                        </select>
                    </div>
                    <div class="rpos-field">
                        <label>Precio de venta (L) *</label>
                        <input type="number" step="0.01" min="0" value="0.00" data-prod-price>
                    </div>
                    <div class="rpos-field">
                        <label>Color en POS</label>
                        <input type="color" value="#1898e8" data-prod-color style="height:38px;padding:3px;">
                    </div>
                </div>
                <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin:6px 0 12px;padding:10px 12px;background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;">
                    <label style="display:flex;align-items:center;gap:8px;font-size:13px;font-weight:600;color:#0f172a;cursor:pointer;">
                        <input type="checkbox" data-prod-recipe> Activar receta (Product Bundle nativo)
                    </label>
                    <label style="display:flex;align-items:center;gap:8px;font-size:13px;font-weight:600;color:#0f172a;cursor:pointer;">
                        <input type="checkbox" data-prod-options> Activar opciones del platillo / combos
                    </label>
                </div>
                <div data-prod-options-box style="display:none;padding:12px;background:#f0f9ff;border:1px solid #bae6fd;border-radius:8px;margin-bottom:10px;">
                    <div style="font-size:12.5px;font-weight:700;color:#0369a1;margin-bottom:8px;">Grupo inicial de opciones (Opcional)</div>
                    <div style="display:grid;grid-template-columns:1.2fr 0.8fr;gap:10px;">
                        <div class="rpos-field" style="margin-bottom:0;">
                            <label>Nombre del grupo (ej. Término, Extras)</label>
                            <input type="text" data-prod-opt-group placeholder="Ej. Término de cocción">
                        </div>
                        <div class="rpos-field" style="margin-bottom:0;">
                            <label>Opciones separadas por coma</label>
                            <input type="text" data-prod-opt-values placeholder="Ej. Término medio, Tres cuartos, Bien cocido">
                        </div>
                    </div>
                </div>
            `,
            `
                <button type="button" class="rpos-btn-secondary" data-modal-close>Cancelar</button>
                <button type="button" class="rpos-btn-primary" data-prod-open-form>Abrir Formulario Completo</button>
                <button type="button" class="rpos-btn-green" data-prod-save>Guardar y Actualizar POS</button>
            `,
            "640px"
        );

        const optCheck = backdrop.querySelector("[data-prod-options]");
        const optBox = backdrop.querySelector("[data-prod-options-box]");
        optCheck.addEventListener("change", () => {
            optBox.style.display = optCheck.checked ? "block" : "none";
        });

        const buildPayload = () => {
            const itemName = backdrop.querySelector("[data-prod-name]").value.trim();
            const itemCode = backdrop.querySelector("[data-prod-code]").value.trim();
            const itemGroup = backdrop.querySelector("[data-prod-group]").value;
            const price = Number(backdrop.querySelector("[data-prod-price]").value || 0);
            const color = backdrop.querySelector("[data-prod-color]").value;
            const recipeEnabled = backdrop.querySelector("[data-prod-recipe]").checked ? 1 : 0;
            const optionsEnabled = optCheck.checked ? 1 : 0;
            const optGroupName = backdrop.querySelector("[data-prod-opt-group]").value.trim();
            const optValues = backdrop.querySelector("[data-prod-opt-values]").value
                .split(",")
                .map(s => s.trim())
                .filter(Boolean);

            const payload = {
                item_name: itemName,
                item_code: itemCode || itemName,
                item_group: itemGroup,
                price,
                restaurant_color: color,
                restaurant_recipe_enabled: recipeEnabled,
                restaurant_options_enabled: optionsEnabled,
                selling_price_list: this.currentOrder.selling_price_list || "Venta estándar",
            };
            if (optionsEnabled && optGroupName && optValues.length) {
                payload.option_group = {
                    group_name: optGroupName,
                    min_selections: 1,
                    max_selections: 1,
                    currency: "HNL",
                    disabled: 0,
                    options: optValues.map((lbl, idx) => ({
                        option_label: lbl,
                        effect: "Solo indicación",
                        additional_amount: 0,
                        is_default: idx === 0 ? 1 : 0,
                    })),
                };
            }
            return payload;
        };

        backdrop.querySelector("[data-prod-open-form]").addEventListener("click", async () => {
            const payload = buildPayload();
            if (!payload.item_name) {
                backdrop.remove();
                frappe.restaurant_item_navigation = true;
                frappe.model.with_doctype("Item", () => {
                    const doc = frappe.model.get_new_doc("Item", null, null, true);
                    frappe.set_route("Form", "Item", doc.name);
                });
                return;
            }
            const res = await frappe.call({
                method: "restaurant.pos.create_pos_product",
                args: { product: payload },
                freeze: true,
                freeze_message: "Creando producto y abriendo configurador...",
            });
            backdrop.remove();
            if (res.message?.categories) this.bootstrap.categories = res.message.categories;
            if (res.message?.items) this.bootstrap.items = res.message.items;
            frappe.restaurant_item_navigation = true;
            frappe.set_route("Form", "Item", res.message.item_code);
        });

        backdrop.querySelector("[data-prod-save]").addEventListener("click", async () => {
            const payload = buildPayload();
            if (!payload.item_name) {
                frappe.msgprint("Ingresa el nombre del producto o platillo.");
                return;
            }
            const res = await frappe.call({
                method: "restaurant.pos.create_pos_product",
                args: { product: payload },
                freeze: true,
                freeze_message: "Guardando producto en el catálogo...",
            });
            if (res.message?.categories) this.bootstrap.categories = res.message.categories;
            if (res.message?.items) this.bootstrap.items = res.message.items;
            backdrop.remove();
            this.render();
            frappe.show_alert({
                message: `Producto "${payload.item_name}" creado y disponible en el POS`,
                indicator: "green",
            });
        });
    }

    async openReprintCommandsModal() {
        const res = await frappe.call({
            method: "restaurant.pos.get_emitted_commands",
            args: { limit: 40 },
        });
        const commands = res.message?.commands || [];

        const backdrop = this.createModal(
            "Reimprimir Comandas Emitidas",
            `
                <p style="color:#475569;font-size:13px;margin-top:0;">
                    Selecciona una comanda ya emitida para volver a imprimir su ticket de cocina o barra:
                </p>
                <div style="max-height:360px;overflow-y:auto;border:1px solid #e2e8f0;border-radius:8px;">
                    ${commands.length ? commands.map(cmd => `
                        <div style="display:flex;justify-content:space-between;align-items:center;gap:12px;padding:10px 14px;border-bottom:1px solid #f1f5f9;">
                            <div>
                                <div style="font-weight:700;font-size:13.5px;color:#0f172a;">
                                    ${this.escape(cmd.order_name)} ${cmd.table_label ? `· Mesa ${this.escape(cmd.table_label)}` : `· ${this.escape(cmd.service_type)}`}
                                </div>
                                <div style="font-size:11.5px;color:#64748b;">
                                    ${this.escape(cmd.name)} · Emitida: ${this.escape(String(cmd.sent_to_kitchen_at).slice(0, 19))} · Estaciones: ${this.escape((cmd.stations || []).join(", "))}
                                </div>
                                <div style="font-size:12px;color:#334155;margin-top:3px;">
                                    ${(cmd.items || []).map(it => `${it.qty}x ${this.escape(it.item_name)}`).join(", ")}
                                </div>
                            </div>
                            <button type="button" class="rpos-btn-primary" data-reprint-order="${this.escape(cmd.name)}" style="white-space:nowrap;padding:7px 14px;font-size:12.5px;">
                                🖨 Reimprimir
                            </button>
                        </div>
                    `).join("") : `
                        <div style="padding:28px;text-align:center;color:#64748b;font-size:13.5px;">
                            Aún no hay comandas emitidas para reimprimir.
                        </div>
                    `}
                </div>
            `,
            `<button type="button" class="rpos-btn-secondary" data-modal-close>Cerrar</button>`,
            "680px"
        );

        backdrop.querySelectorAll("[data-reprint-order]").forEach(btn => {
            btn.addEventListener("click", async () => {
                const orderName = btn.dataset.reprintOrder;
                const repRes = await frappe.call({
                    method: "restaurant.pos.send_order_to_kitchen",
                    args: {
                        order_name: orderName,
                        station: "ALL",
                        include_sent: 1,
                    },
                    freeze: true,
                    freeze_message: "Reimprimiendo comanda...",
                });
                const prevOrder = this.currentOrder;
                this.currentOrder = repRes.message.order;
                this.printCommandTickets(repRes.message.stations || {}, repRes.message.sent_at);
                this.currentOrder = prevOrder;
                frappe.show_alert({
                    message: `Comanda ${repRes.message.order?.order_name || orderName} enviada a reimpresión`,
                    indicator: "green",
                });
            });
        });
    }

    async openCloseRegisterModal() {
        const shift = this.bootstrap?.opening_shift;
        if (!shift) {
            frappe.msgprint("No hay un turno de caja abierto actualmente.");
            return;
        }
        const res = await frappe.call({
            method: "restaurant.pos.get_closing_shift_preview",
            args: { pos_opening_shift: shift.name },
        });
        const preview = res.message;
        const rows = preview.payment_reconciliation || [];

        const backdrop = this.createModal(
            `Cerrar Caja Registradora · ${this.escape(preview.pos_profile)}`,
            `
                <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-bottom:14px;">
                    <div style="background:#f8fafc;border:1px solid #cbd5e1;border-radius:8px;padding:10px;text-align:center;">
                        <div style="font-size:11.5px;color:#475569;font-weight:700;">Facturas SAR del Turno</div>
                        <div style="font-size:17px;font-weight:800;color:#0f172a;">${preview.invoice_count}</div>
                    </div>
                    <div style="background:#f0f9ff;border:1px solid #bae6fd;border-radius:8px;padding:10px;text-align:center;">
                        <div style="font-size:11.5px;color:#0369a1;font-weight:700;">Total Ventas Facturadas</div>
                        <div style="font-size:17px;font-weight:800;color:#0284c7;">${this.formatMoney(preview.total_sales)}</div>
                    </div>
                    <div style="background:#f0fdf4;border:1px solid #86efac;border-radius:8px;padding:10px;text-align:center;">
                        <div style="font-size:11.5px;color:#166534;font-weight:700;">Movimientos Efectivo Neto</div>
                        <div style="font-size:17px;font-weight:800;color:#15803d;">${this.formatMoney(preview.cash_movements?.net_cash_movement || 0)}</div>
                    </div>
                </div>

                <div style="font-size:13px;font-weight:700;color:#0f172a;margin-bottom:8px;">
                    Arqueo y Conciliación por Método de Pago (POS Closing Shift)
                </div>
                <div style="border:1px solid #cbd5e1;border-radius:8px;overflow:hidden;margin-bottom:12px;">
                    <div style="display:grid;grid-template-columns:1.3fr 1fr 1fr 1fr 1.1fr;gap:8px;padding:8px 12px;background:#f1f5f9;font-size:11.5px;font-weight:700;color:#334155;">
                        <span>Método</span>
                        <span>Apertura</span>
                        <span>Ventas</span>
                        <span>Esperado</span>
                        <span>Conteo Cierre (L)</span>
                    </div>
                    ${rows.map(r => `
                        <div style="display:grid;grid-template-columns:1.3fr 1fr 1fr 1fr 1.1fr;gap:8px;padding:8px 12px;border-top:1px solid #e2e8f0;align-items:center;font-size:12.5px;">
                            <strong>${this.escape(r.mode_of_payment)}</strong>
                            <span>${this.formatMoney(r.opening_amount)}</span>
                            <span>${this.formatMoney(r.sales_amount)}</span>
                            <span style="font-weight:700;">${this.formatMoney(r.expected_amount)}</span>
                            <input type="number" step="0.01" min="0" data-close-mop="${this.escape(r.mode_of_payment)}" value="${Number(r.closing_amount).toFixed(2)}" style="width:100%;border:1px solid #cbd5e1;border-radius:5px;padding:5px 8px;font-weight:700;">
                        </div>
                    `).join("")}
                </div>
            `,
            `
                <button type="button" class="rpos-btn-secondary" data-modal-close>Cancelar</button>
                <button type="button" class="rpos-btn-primary" data-close-confirm>Confirmar Cierre de Caja</button>
            `,
            "680px"
        );

        backdrop.querySelector("[data-close-confirm]").addEventListener("click", async () => {
            const closingAmounts = [];
            backdrop.querySelectorAll("[data-close-mop]").forEach(inp => {
                closingAmounts.push({
                    mode_of_payment: inp.dataset.closeMop,
                    closing_amount: Number(inp.value || 0),
                });
            });
            const closeRes = await frappe.call({
                method: "restaurant.pos.close_pos_shift",
                args: {
                    pos_opening_shift: shift.name,
                    closing_amounts: closingAmounts,
                },
                freeze: true,
                freeze_message: "Cerrando turno y generando POS Closing Shift...",
            });
            backdrop.remove();
            this.bootstrap.opening_shift = null;
            const closingDoc = closeRes.message?.pos_closing_shift;
            frappe.show_alert({
                message: closingDoc
                    ? `Caja cerrada correctamente (Cierre: ${closingDoc})`
                    : "Turno de caja cerrado correctamente",
                indicator: "green",
            });
            this.openShiftDialog();
        });
    }
}
