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
        this.orderPage = 1;
        this.orderPageSize = 14;

        this.numpadMode = "qty";
        this.numpadBuffer = "";
        this.selectedLineIndex = -1;
        this.operationMode = null;
        this.operationContext = null;
        this.operationBusy = false;
        this.splitSelection = new Map();
        this.splitQuote = null;
        this.splitQuoteSequence = 0;
        this.splitQuoteTimer = null;
        this.splitAccountName = "";

        this.bootstrap = null;
        this.categorySearch = "";
        this.currentOrder = this.createBlankOrder();
        this.paymentScreenState = null;
        this.customerDisplayWindow = null;
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

    getRposConfig() {
        return this.bootstrap?.rpos_config || {};
    }

    formatDisplayItemPrice(item) {
        const cfg = this.getRposConfig();
        const basePrice = Number(item?.price || 0);
        const taxRate = Number(item?.tax_rate ?? 15);
        if (cfg.price_display_mode === "Precio sin impuesto incluido" && taxRate > 0) {
            return this.formatMoney(basePrice / (1 + taxRate / 100));
        }
        return this.formatMoney(basePrice);
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

    getPermissions() {
        return this.bootstrap?.permissions || {
            can_invoice: true,
            is_waiter_only: false,
            is_cashier_only: false,
            is_direct_cashier: false,
            can_manage_tables: true,
            can_create_accounts: true,
            can_access_backend: true,
            is_supervisor: true,
            requires_supervisor_auth: false,
            linked_waiter: null,
        };
    }

    canInvoice() {
        return Boolean(this.getPermissions().can_invoice);
    }

    requiresSupervisorAuth() {
        return Boolean(this.getPermissions().requires_supervisor_auth);
    }

    isSentToKitchenLine(line) {
        if (!line) return false;
        if (line.is_cancelled || line.kds_status === "Cancelado") return false;
        return Boolean(line.kds_status && line.kds_status !== "Pendiente");
    }

    requestSupervisorAuthModal(actionLabel, method, extraArgs = {}, options = {}) {
        const requireReason = options.requireReason !== false;
        const orderLabel = options.orderLabel || this.currentOrder?.order_name || extraArgs.order_name || "Orden actual";
        const itemLabel = options.itemLabel || "";
        const requester = frappe.session.user || "";
        const warningBanner = options.warningText
            ? `<div style="background:#FEE2E2;border:1px solid #EF4444;border-radius:8px;padding:8px 12px;margin-bottom:10px;color:#991B1B;font-size:12.5px;">${this.escape(options.warningText)}</div>`
            : "";
        return new Promise(resolve => {
            const backdrop = this.createModal(
                "Autorización de supervisor requerida",
                `
                    <div style="background:#FEF3C7;border:1px solid #F59E0B;border-radius:8px;padding:10px 12px;margin-bottom:12px;color:#92400E;font-size:13px;">
                        Esta operación requiere autorización de un supervisor. Ingrese el código de seguridad para continuar.
                    </div>
                    ${warningBanner}
                    <div style="background:#F8FAFC;border:1px solid #E2E8F0;border-radius:8px;padding:10px 12px;margin-bottom:12px;font-size:12.5px;color:#334155;display:grid;gap:4px;">
                        <div><strong>Operación solicitada:</strong> ${this.escape(actionLabel)}</div>
                        <div><strong>Cuenta u orden afectada:</strong> ${this.escape(orderLabel)}</div>
                        ${itemLabel ? `<div><strong>Producto afectado:</strong> ${this.escape(itemLabel)}</div>` : ""}
                        <div><strong>Usuario solicitante:</strong> ${this.escape(requester)}</div>
                    </div>
                    <div class="rpos-field">
                        <label>PIN o código de supervisor *</label>
                        <input type="password" data-sup-pin autocomplete="new-password" placeholder="Ingresa el PIN o código del supervisor">
                    </div>
                    <div class="rpos-field">
                        <label>Motivo de cancelación ${requireReason ? "*" : "(opcional)"}</label>
                        <input type="text" data-sup-reason maxlength="180" placeholder="Ej. Error de digitación, solicitud del cliente...">
                    </div>
                `,
                `
                    <button type="button" class="rpos-btn-secondary" data-sup-cancel>Cancelar</button>
                    <button type="button" class="rpos-btn-primary" data-sup-confirm>Autorizar</button>
                `,
                "500px"
            );

            let settled = false;
            const finish = (val) => {
                if (settled) return;
                settled = true;
                resolve(val);
            };

            backdrop.querySelector("[data-sup-cancel]").addEventListener("click", () => {
                backdrop.remove();
                finish(null);
            });
            backdrop.querySelectorAll("[data-modal-close]").forEach(btn => {
                btn.addEventListener("click", () => finish(null));
            });

            const pinInput = backdrop.querySelector("[data-sup-pin]");
            const reasonInput = backdrop.querySelector("[data-sup-reason]");
            setTimeout(() => pinInput?.focus(), 60);

            backdrop.querySelector("[data-sup-confirm]").addEventListener("click", async () => {
                const supervisorPin = pinInput.value;
                const reason = reasonInput.value.trim();
                if (!supervisorPin) {
                    frappe.msgprint("Ingresa el PIN o código de seguridad del supervisor.");
                    pinInput.focus();
                    return;
                }
                if (requireReason && !reason) {
                    frappe.msgprint("Debes ingresar el motivo obligatorio de la cancelación.");
                    reasonInput.focus();
                    return;
                }
                try {
                    const res = await frappe.call({
                        method,
                        type: "POST",
                        args: {
                            ...extraArgs,
                            supervisor_user: "",
                            supervisor_pin: supervisorPin,
                            reason,
                        },
                        freeze: true,
                        freeze_message: "Validando autorización del supervisor...",
                    });
                    backdrop.remove();
                    finish(res.message || { authorized: true });
                } catch (err) {
                    pinInput.value = "";
                    pinInput.focus();
                }
            });
        });
    }

    requestWaiterPinModal(orderData) {
        const waiterLabel = orderData.waiter_name || orderData.waiter || "Mesero asignado";
        return new Promise(resolve => {
            const backdrop = this.createModal(
                "Cuenta Protegida por Mesero",
                `
                    <div style="background:#EFF6FF;border:1px solid #93C5FD;border-radius:8px;padding:10px 12px;margin-bottom:12px;color:#1E3A8A;font-size:13px;">
                        Esta cuenta está asignada a <strong>${this.escape(waiterLabel)}</strong>. Ingresa tu código/PIN de mesero para abrirla.
                    </div>
                    <div class="rpos-field">
                        <label>Código / PIN de ${this.escape(waiterLabel)} *</label>
                        <input type="password" data-waiter-pin autocomplete="off" placeholder="Ingresa el PIN del mesero">
                    </div>
                `,
                `
                    <button type="button" class="rpos-btn-secondary" data-wpin-cancel>Cancelar</button>
                    <button type="button" class="rpos-btn-primary" data-wpin-confirm>Desbloquear cuenta</button>
                `,
                "440px"
            );

            let settled = false;
            const finish = (val) => {
                if (settled) return;
                settled = true;
                resolve(val);
            };

            backdrop.querySelector("[data-wpin-cancel]").addEventListener("click", () => {
                backdrop.remove();
                finish(null);
            });
            backdrop.querySelectorAll("[data-modal-close]").forEach(btn => {
                btn.addEventListener("click", () => finish(null));
            });

            const pinInput = backdrop.querySelector("[data-waiter-pin]");
            setTimeout(() => pinInput?.focus(), 60);

            backdrop.querySelector("[data-wpin-confirm]").addEventListener("click", async () => {
                const pin = pinInput.value;
                if (!pin) {
                    frappe.msgprint("Ingresa el PIN del mesero asignado.");
                    return;
                }
                try {
                    const res = await frappe.call({
                        method: "restaurant.pos.unlock_waiter_order",
                        type: "POST",
                        args: {
                            order_name: orderData.name,
                            pin,
                        },
                        freeze: true,
                        freeze_message: "Verificando PIN de mesero...",
                    });
                    const unlockedOrder = res.message?.order || orderData;
                    this.upsertOrderInBootstrap(unlockedOrder);
                    backdrop.remove();
                    finish(unlockedOrder);
                } catch (err) {
                    pinInput.value = "";
                    pinInput.focus();
                }
            });
        });
    }

    createBlankOrder(overrides = {}) {
        const defaultCustomer = this.bootstrap?.customers?.[0] || {
            name: "CONSUMIDOR FINAL",
            customer_name: "CONSUMIDOR FINAL",
            tax_id: "",
        };
        const perms = this.getPermissions();
        const defaultWaiter = perms.linked_waiter
            ? perms.linked_waiter
            : (perms.is_waiter_only ? null : (this.bootstrap?.waiters?.[0] || null));
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
            this.setupIdleWallpaperManager();
            if (this.canInvoice() && !this.bootstrap.opening_shift) this.openShiftDialog();
            else if (options.open_new_account) this.openNewAccountModal();
        } catch (error) {
            if (frappe.get_route()[0] === "restaurant-pos") this.showStartupState(true);
        } finally {
            this.loading = false;
        }
    }

    showStartupState(failed = false) {
        if (!failed) {
            this.shell.innerHTML = `
                <section class="rpos-startup" role="status" aria-live="polite" aria-busy="true" aria-label="Cargando">
                    <img class="leaf-loader-img" src="/assets/frappe/images/leaf.gif" alt="Cargando" style="width:68px;height:68px;">
                </section>`;
            return;
        }
        this.shell.innerHTML = `
            <section class="rpos-startup" role="alert" aria-live="polite" aria-busy="false">
                <div class="rpos-startup-card">
                    <h1>No se pudo abrir el punto de venta</h1>
                    <p>Comprueba que el servidor esté disponible y vuelve a intentarlo. Tus órdenes guardadas se conservan.</p>
                    <div class="rpos-startup-actions">
                        <button type="button" class="rpos-btn-green" data-startup-retry>Reintentar</button>
                        <button type="button" class="rpos-btn-secondary" data-startup-back>Volver al restaurante</button>
                    </div>
                </div>
            </section>`;
        this.shell.querySelector("[data-startup-retry]")?.addEventListener("click", () => this.onShow());
        this.shell.querySelector("[data-startup-back]")?.addEventListener("click", () => {
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
            if (row.is_cancelled || row.kds_status === "Cancelado") {
                row.amount = 0;
                return;
            }
            const rawQty = Number(row.qty);
            const qty = Number.isFinite(rawQty) && rawQty > 0 ? rawQty : 1;
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

    formatTopbarScheduleLabel() {
        const raw = String(this.currentOrder?.scheduled_time || "").trim();
        if (!raw) return "--:--";
        const match = raw.match(/(\d{2}:\d{2})/);
        return match ? match[1] : raw;
    }

    currentPresetConfig() {
        const srv = this.currentOrder?.service_type || "Comer en el local";
        const presets = this.bootstrap?.presets || [];
        return presets.find(p => (p.preset_name || p.label) === srv) || {
            preset_name: srv,
            color_bg: srv === "Para llevar" ? "#fef0a6" : (srv === "Entrega" ? "#fcd5b5" : "#cce3fd"),
            color_border: srv === "Para llevar" ? "#eab308" : (srv === "Entrega" ? "#f97316" : "#3b82f6"),
            require_customer: srv === "Entrega" ? 1 : 0,
            enable_scheduling: srv !== "Comer en el local" ? 1 : 0,
            slot_interval_minutes: 20,
            schedule_start_time: "12:00",
            schedule_end_time: "22:00",
        };
    }

    detectApplicableCombo() {
        const items = this.currentOrder?.items || [];
        if (items.length < 2) return null;
        const catalog = this.bootstrap?.items || [];
        const combos = catalog.filter(it => it.is_combo && Array.isArray(it.option_groups) && it.option_groups.length);
        for (const combo of combos) {
            const matchedLineIndices = [];
            const chosenOptions = [];
            let allGroupsSatisfied = true;
            for (const grp of combo.option_groups) {
                const opts = grp.options || [];
                const foundIdx = items.findIndex((line, lIdx) =>
                    !matchedLineIndices.includes(lIdx) &&
                    (line.kds_status || "Pendiente") === "Pendiente" &&
                    opts.some(o =>
                        (o.item_code && o.item_code === line.item_code) ||
                        String(o.option_label || "").toLowerCase() === String(line.item_name || "").toLowerCase()
                    )
                );
                if (foundIdx >= 0) {
                    matchedLineIndices.push(foundIdx);
                    const matchedOpt = opts.find(o =>
                        (o.item_code && o.item_code === items[foundIdx].item_code) ||
                        String(o.option_label || "").toLowerCase() === String(items[foundIdx].item_name || "").toLowerCase()
                    );
                    if (matchedOpt) chosenOptions.push({ ...matchedOpt, group_name: grp.group_name });
                } else if (Number(grp.min_selections || 0) > 0) {
                    allGroupsSatisfied = false;
                    break;
                }
            }
            if (allGroupsSatisfied && matchedLineIndices.length >= 2) {
                return { combo, matchedLineIndices, chosenOptions };
            }
        }
        return null;
    }

    async applyDetectedCombo() {
        const detected = this.detectApplicableCombo();
        if (!detected) return;
        const { combo, matchedLineIndices, chosenOptions } = detected;
        const sortedDesc = [...matchedLineIndices].sort((a, b) => b - a);
        for (const idx of sortedDesc) {
            if (this.currentOrder.items[idx].qty > 1) {
                this.currentOrder.items[idx].qty -= 1;
            } else {
                this.currentOrder.items.splice(idx, 1);
            }
        }
        await this.addItemToCurrentOrder(combo, chosenOptions);
        frappe.show_alert({ message: `Combo "${combo.item_name}" aplicado a la orden`, indicator: "green" });
    }

    render() {
        if (!this.operationMode) this.recalculateLocalTotals();
        this.shell.classList.toggle("is-dark-mode", Boolean(this.darkMode));
        this.shell.classList.toggle("is-splitting", this.operationMode === "split");
        this.shell.classList.toggle("is-large-scrollbars", Boolean(this.getRposConfig().large_scrollbars));
        const cashierName = this.bootstrap?.cashier?.full_name || frappe.session.user;
        const avatarChar = (cashierName || "C").trim().charAt(0).toUpperCase();
        const shiftBadge = this.bootstrap?.opening_shift
            ? `Turno: ${this.escape(this.bootstrap.opening_shift.pos_profile)}`
            : "Sin turno abierto";
        const pillLabel = this.currentOrder.table_label
            ? `Mesa ${this.escape(this.currentOrder.table_label)} · ${this.escape(this.currentOrder.order_name || "En curso")}`
            : (this.currentOrder.order_name
                ? `${this.escape(this.currentOrder.order_name)}`
                : "Venta directa");
        const presetCfg = this.currentPresetConfig();
        const showClockPill = this.activeTab === "Caja" && (Boolean(presetCfg.enable_scheduling) || Boolean(this.currentOrder.scheduled_time));
        const clockLabel = this.formatTopbarScheduleLabel();

        const perms = this.getPermissions();
        if (!perms.can_manage_tables && this.activeTab === "Mesas") {
            this.activeTab = "Caja";
        }
        this.shell.innerHTML = `
            <header class="rpos-topbar">
                <div class="rpos-topbar-left">
                    <nav class="rpos-nav-tabs" aria-label="Navegación POS">
                        ${perms.can_manage_tables ? `<button type="button" class="rpos-nav-tab ${this.activeTab === "Mesas" ? "is-active" : ""}" data-nav="Mesas">Mesas</button>` : ""}
                        <button type="button" class="rpos-nav-tab ${this.activeTab === "Caja" ? "is-active" : ""}" data-nav="Caja">Caja</button>
                        <button type="button" class="rpos-nav-tab ${this.activeTab === "Órdenes" ? "is-active" : ""}" data-nav="Órdenes">Órdenes</button>
                    </nav>
                    ${this.activeTab !== "Mesas" ? `
                        <button type="button" class="rpos-service-pill" data-service="${this.escape(this.currentOrder.service_type)}" data-action="open-order-name-modal" title="Definir o cambiar nombre de la orden" ${this.operationMode ? "disabled" : ""}>
                            <span>${pillLabel}</span>
                        </button>
                    ` : ""}
                    ${showClockPill ? `
                        <button type="button" class="rpos-schedule-top-pill" data-action="open-schedule-modal" title="Programar fecha y hora (${this.escape(this.currentOrder.service_type)})" style="display:inline-flex;align-items:center;gap:5px;padding:4px 10px;border-radius:999px;border:1px solid #cbd5e1;background:#f1f5f9;color:#1e293b;font-size:12.5px;font-weight:700;cursor:pointer;">
                            <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
                            <span>${this.escape(clockLabel)}</span>
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
                            <span class="rpos-search-icon">
                                <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
                            </span>
                            <input type="search" class="rpos-prod-search" placeholder="Buscar producto..." value="${this.escape(this.productSearch)}">
                        </div>
                    ` : ""}
                    <button type="button" class="rpos-icon-btn is-borderless" data-action="open-kds" title="Cocina KDS / Pantalla">
                        <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                            <path d="M6 2L3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4z"/>
                            <line x1="3" y1="6" x2="21" y2="6"/>
                            <path d="M16 10a4 4 0 0 1-8 0"/>
                        </svg>
                    </button>
                    <button type="button" class="rpos-cashier-chip" data-action="shift-info" title="${this.escape(shiftBadge)}">
                        <span class="rpos-cashier-avatar">${this.escape(avatarChar)}</span>
                        <span>${this.escape(cashierName)}</span>
                    </button>
                    <button type="button" class="rpos-icon-btn" data-action="pos-menu" title="Opciones del Punto de Venta">
                        <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round">
                            <line x1="4" y1="7" x2="20" y2="7"/>
                            <line x1="4" y1="12" x2="20" y2="12"/>
                            <line x1="4" y1="17" x2="20" y2="17"/>
                        </svg>
                    </button>
                </div>
            </header>
            ${this.renderActiveView()}
        `;

        this.bindEvents();
        this.bindSplitEvents();
    }

    renderActiveView() {
        this.syncCustomerDisplayLive();
        if (this.operationMode === "split") return this.renderSplitView();
        if (this.paymentScreenState) return this.renderPaymentScreenView();
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
        const pendingLines = (this.currentOrder.items || []).filter(
            row => (row.kds_status || "Pendiente") === "Pendiente"
        );
        const pendingByGroup = {};
        pendingLines.forEach(row => {
            const grp = row.item_group || row.command_station || "Cocina";
            pendingByGroup[grp] = (pendingByGroup[grp] || 0) + Number(row.qty || 1);
        });
        const pendingGroupEntries = Object.entries(pendingByGroup);
        const applicableCombo = this.detectApplicableCombo();

        return `
            <div class="rpos-caja-body">
                <!-- Left Ticket & Controls -->
                <aside class="rpos-ticket-pane">
                    <div class="rpos-ticket-header">
                        <div>
                            <strong>${this.escape(this.currentOrder.order_name || "Venta directa")}</strong>
                            ${this.currentOrder.reference_note ? `<span> · Ref: ${this.escape(this.currentOrder.reference_note)}</span>` : ""}
                        </div>
                        <div style="display:flex;align-items:center;gap:8px;">
                            ${this.currentOrder.waiter_name ? `<span>Mesero: ${this.escape(this.currentOrder.waiter_name)}</span>` : `<span>Sin mesero</span>`}
                            ${this.currentOrder.name ? `<button type="button" data-action="exit-current-order" title="Salir de esta cuenta sin modificarla y dejar Caja lista para nueva orden" style="border:1px solid #CBD5E1;background:#FFFFFF;color:#334155;border-radius:6px;padding:2px 8px;font-size:11.5px;font-weight:600;cursor:pointer;">+ Nueva</button>` : ""}
                        </div>
                    </div>

                    <div class="rpos-ticket-lines">
                        ${this.currentOrder.items.length ? this.currentOrder.items.map((line, idx) => {
            const isCancelled = Boolean(line.is_cancelled) || line.kds_status === "Cancelado";
            const isSent = this.isSentToKitchenLine(line);
            return `
                            <div class="rpos-line ${idx === this.selectedLineIndex ? "is-selected" : ""} ${isCancelled ? "is-cancelled" : ""}" data-line-idx="${idx}" ${isCancelled ? `style="opacity:0.65;"` : ""}>
                                <div class="rpos-line-main" ${isCancelled ? `style="text-decoration:line-through;color:#b91c1c;"` : ""}>
                                    <span class="rpos-line-qty">${Number(line.qty).toLocaleString("es-HN")}</span>
                                    <span class="rpos-line-name">
                                        ${this.escape(line.item_name)}
                                        ${isCancelled ? `<span style="margin-left:6px;padding:1px 6px;border-radius:4px;background:#fee2e2;color:#b91c1c;font-size:10px;font-weight:700;text-decoration:none;display:inline-block;">CANCELADO</span>` : (isSent ? `<span style="margin-left:6px;padding:1px 6px;border-radius:4px;background:#dcfce7;color:#166534;font-size:10px;font-weight:600;display:inline-block;">${this.escape(line.kds_status)}</span>` : "")}
                                    </span>
                                    <span class="rpos-line-amount">${isCancelled ? this.formatMoney(0) : this.formatMoney(line.amount)}</span>
                                </div>
                                ${isCancelled && line.cancellation_reason ? `<div class="rpos-line-sub" style="color:#b91c1c;">Cancelado (${this.escape(line.cancellation_reason)})</div>` : ""}
                                ${line.discount_percentage > 0 ? `<div class="rpos-line-sub">Descuento: ${line.discount_percentage}%</div>` : ""}
                                ${(line.selected_options || []).map(opt => `
                                    <div class="rpos-line-sub">- ${this.escape(opt.option_label)}${Number(opt.additional_amount) > 0 ? ` (+${this.formatMoney(opt.additional_amount)})` : ""}</div>
                                `).join("")}
                                ${(!line.selected_options?.length && line.options_summary) ? `<div class="rpos-line-sub">- ${this.escape(line.options_summary)}</div>` : ""}
                                ${line.note ? `<div class="rpos-line-note">${this.escape(line.note)}</div>` : ""}
                            </div>
                        `;
        }).join("") : `
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
                            <span>Impuestos</span>
                            <span>${this.formatMoney(this.currentOrder.tax_amount)}</span>
                        </div>
                        ${this.getRposConfig().tips_enabled !== 0 ? `
                            <div class="rpos-totals-row is-tip" data-action="open-tip-modal" title="Clic para configurar Servicio sugerido o Propina">
                                <span>Servicio sugerido / Propina ${this.currentOrder.tip_percentage > 0 ? `(${this.currentOrder.tip_percentage}%)` : ""} ✎</span>
                                <span>${this.formatMoney(this.currentOrder.tip_amount)}</span>
                            </div>
                        ` : ""}
                        <div class="rpos-totals-row is-grand">
                            <span>Total</span>
                            <span>${this.formatMoney(this.currentOrder.grand_total)}</span>
                        </div>
                    </div>

                    ${applicableCombo ? `
                        <div class="rpos-combo-banner" style="display:flex;justify-content:space-between;align-items:center;padding:6px 10px;background:#effbe9;border-top:1px solid #a4ce87;font-size:12.5px;color:#1e5a00;">
                            <span>1 ${this.escape(applicableCombo.combo.item_name)}</span>
                            <button type="button" data-action="apply-combo-suggestion" style="background:#2F8500;color:#fff;border:none;border-radius:5px;padding:4px 12px;font-weight:700;font-size:12px;cursor:pointer;">Aplicar</button>
                        </div>
                    ` : ""}

                    <div class="rpos-controls-grid" style="grid-template-columns:minmax(60px,0.9fr) minmax(44px,0.65fr) minmax(96px,1.25fr) 38px minmax(96px,1.25fr) 34px;gap:4px;">
                        <button type="button" class="rpos-ctrl-btn" data-action="open-customer-modal" title="Cliente: ${this.escape(this.currentOrder.customer_name)} (RTN: ${this.escape(this.currentOrder.tax_id || "N/A")})" style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">
                            ${this.escape(customerBtnLabel)}
                        </button>
                        <button type="button" class="rpos-ctrl-btn" data-action="open-note-modal" title="Agregar comentario o nota al platillo seleccionado">
                            Nota
                        </button>
                        <button type="button" class="rpos-ctrl-btn ${presetClass}" data-action="open-preset" title="Seleccionar modalidad de operación" style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">
                            ${this.escape(presetLabel)}
                        </button>
                        <button type="button" class="rpos-ctrl-btn" data-action="clear-current-order" title="Vaciar la orden o eliminar todo el contenido del Punto de Venta">
                            <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 12v7a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-7"/><polyline points="16 6 12 2 8 6"/><line x1="12" y1="2" x2="12" y2="15"/></svg>
                        </button>
                        <button type="button" class="rpos-ctrl-btn is-command ${pendingLines.length ? "has-pending" : ""}" data-action="open-command-modal" title="Comandar: imprimir comandas de cocina o barra por estación">
                            🖨 Comandar${pendingLines.length ? ` (${pendingLines.length})` : ""}
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
                        <button type="button" class="rpos-key ${this.numpadMode === "disc" ? "is-mode-active" : ""}" data-mode="disc" ${(this.getRposConfig().allow_line_discount === 0 || !this.canInvoice()) ? 'disabled style="opacity:0.4;cursor:not-allowed;" title="Descuento por línea no habilitado para este rol"' : ""}>%</button>
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
                        ${pendingGroupEntries.length ? `
                            <button type="button" class="rpos-bottom-btn is-plum" data-action="send-kds" style="grid-column:span 2;flex-direction:row;justify-content:space-between;padding:8px 14px;background:#2F8500;border-color:#236600;">
                                <span style="font-size:15px;font-weight:800;">Enviar</span>
                                <span style="display:flex;flex-direction:column;gap:3px;align-items:flex-end;font-size:11.5px;">
                                    ${pendingGroupEntries.slice(0, 3).map(([grpName, grpCnt]) => `
                                        <span style="display:inline-flex;align-items:center;gap:6px;">
                                            <span>${this.escape(grpName)}</span>
                                            <strong style="background:rgba(0,0,0,0.28);padding:1px 6px;border-radius:4px;">${grpCnt}</strong>
                                        </span>
                                    `).join("")}
                                </span>
                            </button>
                        ` : (this.getPermissions().can_manage_tables ? `
                            <button type="button" class="rpos-bottom-btn is-plum" data-action="assign-table">
                                <span>Asignar</span>
                                <span>mesa</span>
                            </button>
                            <button type="button" class="rpos-bottom-btn is-plum" data-action="assign-account">
                                <span>Asignar</span>
                                <span>cuenta</span>
                            </button>
                        ` : "")}
                        ${this.canInvoice() ? `
                        <button type="button" class="rpos-bottom-btn is-pay ${this.currentOrder.items.length ? "has-items" : ""}" data-action="open-payment-modal">
                            <span>Pago</span>
                        </button>
                        ` : ""}
                    </div>
                </aside>

                <!-- Right Categories & Products -->
                <section class="rpos-catalog-pane">
                    ${(() => {
                const rposCfg = this.getRposConfig();
                const showCatImgs = rposCfg.show_category_images !== 0;
                const showProdImgs = rposCfg.show_product_images !== 0;
                const allowCatSearch = rposCfg.allow_category_search !== 0;
                const catTerm = (this.categorySearch || "").trim().toLowerCase();
                const visibleCats = allowCatSearch && catTerm
                    ? categories.filter(c => (c.label || c.name || "").toLowerCase().includes(catTerm))
                    : categories;
                const renderItemCard = (item) => {
                    const inCartQty = qtyByItem[item.item_code] || 0;
                    const hasPhoto = showProdImgs && Boolean(item.image);
                    const priceTxt = this.formatDisplayItemPrice(item);
                    return `
                                <div class="rpos-prod-card ${hasPhoto ? "has-photo" : ""}"
                                     data-item-code="${this.escape(item.item_code)}"
                                     style="border-bottom-color:${this.escape(item.color || "#EC4899")};">
                                    ${hasPhoto ? `
                                        <div class="rpos-prod-photo-frame">
                                            <img class="rpos-prod-photo" src="${this.escape(item.image)}" alt="${this.escape(item.item_name)}">
                                        </div>
                                        <div class="rpos-prod-photo-overlay">
                                            <div class="rpos-prod-title">${this.escape(item.item_name)}</div>
                                            <div class="rpos-prod-price">${priceTxt}</div>
                                        </div>
                                    ` : `
                                        <div class="rpos-prod-title">${this.escape(item.item_name)}</div>
                                        <div class="rpos-prod-price">${priceTxt}</div>
                                    `}
                                    ${inCartQty > 0 ? `<span class="rpos-prod-qty-badge">${Number(inCartQty).toLocaleString("es-HN")}</span>` : ""}
                                </div>
                            `;
                };

                let productsHtml = "";
                if (rposCfg.group_by_category && this.selectedCategory === "ALL" && filteredItems.length) {
                    const grouped = {};
                    filteredItems.forEach(it => {
                        const grp = it.item_group || "Otros";
                        (grouped[grp] = grouped[grp] || []).push(it);
                    });
                    productsHtml = Object.entries(grouped).map(([grpName, grpItems]) => `
                                <div class="rpos-cat-group-block" style="grid-column:1 / -1;">
                                    <div style="font-size:13px;font-weight:800;color:#002456;padding:6px 4px;border-bottom:2px solid #a4ce87;margin-bottom:8px;">${this.escape(grpName)}</div>
                                    <div class="rpos-products-grid" style="padding:0;">
                                        ${grpItems.map(renderItemCard).join("")}
                                    </div>
                                </div>
                            `).join("");
                } else {
                    productsHtml = filteredItems.map(renderItemCard).join("");
                }

                return `
                            <div class="rpos-categories-bar">
                                ${allowCatSearch ? `
                                    <input type="search"
                                           class="rpos-cat-search-input"
                                           data-category-search
                                           placeholder="Buscar categoría..."
                                           value="${this.escape(this.categorySearch || "")}"
                                           style="min-width:140px;max-width:170px;height:40px;padding:0 10px;border:1px solid #cbd5e1;border-radius:8px;font-size:12.5px;background:#ffffff;color:#0f172a;">
                                ` : ""}
                                <button type="button"
                                        class="rpos-cat-card ${this.selectedCategory === "ALL" ? "is-active" : ""}"
                                        data-cat="ALL"
                                        style="background:#e2e8f0;color:#0f172a;">
                                    <span>Todos</span>
                                </button>
                                ${visibleCats.map(cat => `
                                    <button type="button"
                                            class="rpos-cat-card ${this.selectedCategory === cat.name ? "is-active" : ""}"
                                            data-cat="${this.escape(cat.name)}"
                                            style="background:${this.escape(cat.color || "#2F8500")};">
                                        ${showCatImgs && cat.image ? `<img class="rpos-cat-photo" src="${this.escape(cat.image)}" alt="${this.escape(cat.label)}">` : ""}
                                        <span>${this.escape(cat.label)}</span>
                                    </button>
                                `).join("")}
                            </div>

                            <div class="rpos-products-grid">
                                ${productsHtml}
                            </div>
                        `;
            })()}
                </section>
            </div>
        `;
    }

    formatOrderDateTime(creationStr) {
        const now = new Date();
        const localTodayIso = (typeof frappe !== "undefined" && frappe.datetime?.get_today)
            ? frappe.datetime.get_today()
            : `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
        if (!creationStr) {
            const hh = String(now.getHours()).padStart(2, "0");
            const min = String(now.getMinutes()).padStart(2, "0");
            return { dateLabel: "Hoy", timeLabel: `${hh}:${min}` };
        }
        const raw = String(creationStr).trim();
        const [datePart, timePart = ""] = raw.split(" ");
        const [yyyy, mm, dd] = (datePart || "").split("-");
        const dateLabel = datePart === localTodayIso
            ? "Hoy"
            : (dd && mm && yyyy ? `${dd}/${mm}/${yyyy}` : (datePart || "Hoy"));
        const timeLabel = timePart.slice(0, 5);
        return { dateLabel, timeLabel };
    }

    formatScheduledRowInfo(schedStr) {
        const raw = String(schedStr || "").trim();
        if (!raw) return { dateLine: "", timeLine: "", remainingLabel: "" };
        if (/^\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}/.test(raw)) {
            const [datePart, timePart] = raw.split(/\s+/);
            const [y, m, d] = datePart.split("-").map(Number);
            const [hh, mm] = timePart.split(":").map(Number);
            const target = new Date(y, (m || 1) - 1, d || 1, hh || 0, mm || 0);
            const now = new Date();
            const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
            const targetDay = new Date(y, (m || 1) - 1, d || 1);
            const diffDays = Math.round((targetDay - today) / 86400000);
            const diffMins = Math.round((target - now) / 60000);
            let remainingLabel = "";
            if (diffDays === 1) {
                remainingLabel = "Queda 1 día";
            } else if (diffDays > 1) {
                remainingLabel = `Quedan ${diffDays} días`;
            } else if (diffMins > 60) {
                remainingLabel = `En ${Math.round(diffMins / 60)} h`;
            } else if (diffMins > 0) {
                remainingLabel = `En ${diffMins} min`;
            }
            return {
                dateLine: `${String(d).padStart(2, "0")}/${String(m).padStart(2, "0")}/${y}`,
                timeLine: timePart.slice(0, 5),
                remainingLabel,
            };
        }
        return { dateLine: "", timeLine: raw, remainingLabel: "" };
    }

    formatOrderRowTitles(ord) {
        if (ord.is_draft_row) {
            return {
                title: ord.order_name || "Venta directa",
                sub: ord.reference_note || "En caja activa",
            };
        }
        const rawName = String(ord.name || "");
        const digitsMatch = rawName.match(/(\d+)$/);
        const seqNum = digitsMatch ? Number(digitsMatch[1]) : 0;
        const shortTicketNum = seqNum > 0 ? String(1000 + seqNum) : rawName;
        const rawOrderName = String(ord.order_name || "").trim();
        const isGenericMesa = ord.table_label && (
            !rawOrderName ||
            rawOrderName.toLowerCase() === `mesa ${String(ord.table_label).toLowerCase()}` ||
            /^orden\s+\d+$/i.test(rawOrderName)
        );
        const isGenericOrder = !ord.table_label && /^orden\s+\d+$/i.test(rawOrderName);
        const title = isGenericMesa
            ? `T ${ord.table_label} - ${shortTicketNum}`
            : (isGenericOrder ? shortTicketNum : (rawOrderName || "Venta directa"));
        const sub = ord.reference_note || rawName;
        return { title, sub };
    }

    renderOrdenesView() {
        const rawOrders = [...(this.bootstrap?.orders || [])].sort((a, b) => {
            const ca = String(a.creation || "");
            const cb = String(b.creation || "");
            return ca.localeCompare(cb);
        });

        const hasSavedCurrent = Boolean(
            this.currentOrder?.name && rawOrders.some(o => o.name === this.currentOrder.name)
        );
        if (!hasSavedCurrent) {
            rawOrders.push({
                ...this.currentOrder,
                name: this.currentOrder?.name || "__DRAFT__",
                order_name: this.currentOrder?.order_name || "Venta directa",
                status: this.currentOrder?.status || "En curso",
                service_type: this.currentOrder?.service_type || "Comer en el local",
                grand_total: this.currentOrder?.grand_total || 0,
                is_draft_row: !this.currentOrder?.name,
            });
        }

        const q = (this.orderSearch || "").trim().toLowerCase();

        const filtered = rawOrders.filter(ord => {
            if (this.orderStatusFilter !== "ALL" && ord.status !== this.orderStatusFilter) {
                return false;
            }
            if (this.orderServiceFilter !== "ALL" && ord.service_type !== this.orderServiceFilter) {
                return false;
            }
            if (q) {
                const titles = this.formatOrderRowTitles(ord);
                const hay = `${ord.name} ${ord.order_name} ${titles.title} ${titles.sub} ${ord.reference_note} ${ord.customer_name} ${ord.waiter_name} ${ord.table_label}`.toLowerCase();
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
        const pageSize = this.orderPageSize || 14;
        const totalPages = Math.max(1, Math.ceil(totalFiltered / pageSize));
        if (!this.orderPage || this.orderPage > totalPages) {
            this.orderPage = totalPages;
        }
        if (this.orderPage < 1) {
            this.orderPage = 1;
        }
        const startIdx = (this.orderPage - 1) * pageSize;
        const endIdx = Math.min(startIdx + pageSize, totalFiltered);
        const pageRows = filtered.slice(startIdx, endIdx);
        const rangeLabel = totalFiltered ? `${startIdx + 1}-${endIdx} / ${totalFiltered}` : `0-0 / 0`;
        const activeOrderKey = this.selectedOrderPreviewName || (this.currentOrder?.name || "__DRAFT__");

        return `
            <div class="rpos-orders-view">
                <div class="rpos-orders-main">
                    <div class="rpos-orders-toolbar">
                        <div class="rpos-orders-search-group">
                            <span class="rpos-orders-search-icon" aria-hidden="true">
                                <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
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
                                    <button type="button" class="rpos-pager-btn" data-ord-page="prev" ${this.orderPage <= 1 ? "disabled" : ""} aria-label="Página anterior">
                                        <svg viewBox="0 0 12 12" width="10" height="10" fill="currentColor"><path d="M8 2L3.5 6 8 10V2z"/></svg>
                                    </button>
                                    <button type="button" class="rpos-pager-btn" data-ord-page="next" ${this.orderPage >= totalPages ? "disabled" : ""} aria-label="Página siguiente">
                                        <svg viewBox="0 0 12 12" width="10" height="10" fill="currentColor"><path d="M4 2l4.5 4L4 10V2z"/></svg>
                                    </button>
                                </div>
                            </div>
                        </div>
                    </div>

                    <div class="rpos-orders-list">
                        ${pageRows.length ? pageRows.map(ord => {
            const dt = this.formatOrderDateTime(ord.creation);
            const titles = this.formatOrderRowTitles(ord);
            const custUpper = (ord.customer_name || "").trim().toUpperCase();
            const showCustName = Boolean(ord.customer_name && custUpper !== "CONSUMIDOR FINAL");
            const isHighlighted = activeOrderKey === ord.name;
            const showTakeoutProgress = ord.service_type === "Para llevar" || Boolean(ord.scheduled_time);
            const schedInfo = this.formatScheduledRowInfo(ord.scheduled_time);
            const custObj = (this.bootstrap?.customers || []).find(c => c.name === ord.customer);
            const custAddr = custObj?.address || "";
            return `
                                <div class="rpos-order-row ${isHighlighted ? "is-selected" : ""}" data-order-row="${this.escape(ord.name)}">
                                    <div class="rpos-ord-col-date">
                                        <div class="rpos-ord-date">${this.escape(dt.dateLabel)}</div>
                                        <div class="rpos-ord-time">${this.escape(dt.timeLabel)}</div>
                                    </div>
                                    <div class="rpos-ord-col-name">
                                        <div class="rpos-ord-title">${this.escape(titles.title)}</div>
                                        <div class="rpos-ord-sub">${this.escape(titles.sub)}</div>
                                    </div>
                                    <div class="rpos-ord-col-meta">
                                        ${showCustName ? `<div class="rpos-ord-cust">${this.escape(ord.customer_name)}</div>` : ""}
                                        <div class="rpos-ord-badges">
                                            <span class="rpos-service-pill" data-service="${this.escape(ord.service_type)}">${this.escape(ord.service_type)}</span>
                                            ${ord.table_label ? `<span class="rpos-table-badge">Mesa ${this.escape(ord.table_label)}</span>` : ""}
                                            ${(!ord.table_label && custAddr) ? `<span style="font-size:11.5px;color:#475569;margin-left:6px;">${this.escape(custAddr)}</span>` : ""}
                                        </div>
                                    </div>
                                    <div class="rpos-ord-col-extra" style="display:flex;align-items:center;gap:14px;">
                                        ${ord.scheduled_time ? `
                                            <div style="font-size:11.5px;font-weight:700;color:#0f172a;line-height:1.25;text-align:left;">
                                                ${schedInfo.dateLine ? `<div>${this.escape(schedInfo.dateLine)}</div>` : ""}
                                                <div>${this.escape(schedInfo.timeLine)}</div>
                                            </div>
                                        ` : ""}
                                        ${showTakeoutProgress ? `
                                            <div class="rpos-ord-takeout-ind" title="Estado de preparación / entrega" style="display:flex;flex-direction:column;align-items:center;min-width:90px;">
                                                <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                                                    <path d="M6 2L3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4z"/>
                                                    <line x1="3" y1="6" x2="21" y2="6"/>
                                                    <path d="M16 10a4 4 0 0 1-8 0"/>
                                                </svg>
                                                <span class="rpos-ord-takeout-bar" style="width:80px;height:4px;border-radius:999px;background:${schedInfo.remainingLabel ? "#e2e8f0" : "#2F8500"};margin-top:3px;"></span>
                                                ${schedInfo.remainingLabel ? `<span style="font-size:10.5px;font-weight:700;color:#9f1239;margin-top:2px;">${this.escape(schedInfo.remainingLabel)}</span>` : ""}
                                            </div>
                                        ` : ""}
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
                                        ${!ord.is_draft_row ? `
                                            <button type="button" class="rpos-ord-act-btn is-info" data-action="preview-precuenta" data-order="${this.escape(ord.name)}" title="Ver detalle / Pre-cuenta">i</button>
                                            ${ord.status === "En curso" ? `
                                                <button type="button" class="rpos-ord-act-btn is-trash" data-action="cancel-order-row" data-order="${this.escape(ord.name)}" title="Cancelar orden">
                                                    <svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor"><path d="M9 3a1 1 0 0 0-1 1v1H4a1 1 0 1 0 0 2h1v12a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V7h1a1 1 0 1 0 0-2h-4V4a1 1 0 0 0-1-1H9zm1 2h4v1h-4V5zm-1 5a1 1 0 1 1 2 0v7a1 1 0 1 1-2 0v-7zm4 0a1 1 0 1 1 2 0v7a1 1 0 1 1-2 0v-7z"/></svg>
                                                </button>
                                            ` : ""}
                                        ` : `
                                            <button type="button" class="rpos-ord-act-btn is-info" data-action="open-precuenta" title="Ver Pre-cuenta">i</button>
                                            <button type="button" class="rpos-ord-act-btn is-trash" data-action="reset-draft-order" title="Limpiar orden actual">
                                                <svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor"><path d="M9 3a1 1 0 0 0-1 1v1H4a1 1 0 1 0 0 2h1v12a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V7h1a1 1 0 1 0 0-2h-4V4a1 1 0 0 0-1-1H9zm1 2h4v1h-4V5zm-1 5a1 1 0 1 1 2 0v7a1 1 0 1 1-2 0v-7zm4 0a1 1 0 1 1 2 0v7a1 1 0 1 1-2 0v-7z"/></svg>
                                            </button>
                                        `}
                                    </div>
                                </div>
                            `;
        }).join("") : `
                            <div style="padding:48px;text-align:center;color:#64748b;">No se encontraron órdenes con los filtros seleccionados.</div>
                        `}
                    </div>
                </div>

                <aside class="rpos-ticket-pane ${selectedOrd ? "" : "is-empty-preview"}">
                    ${selectedOrd ? `
                        <div class="rpos-ticket-header">
                            <div><strong>${this.escape(selectedOrd.order_name || "Venta directa")}</strong> ${!selectedOrd.is_draft_row ? `(${this.escape(selectedOrd.name)})` : ""}</div>
                            <div>${this.escape(selectedOrd.status)}</div>
                        </div>
                        <div class="rpos-ticket-lines">
                            ${(selectedOrd.items || []).length ? (selectedOrd.items || []).map(line => `
                                <div class="rpos-line">
                                    <div class="rpos-line-main">
                                        <span class="rpos-line-qty">${line.qty}</span>
                                        <span class="rpos-line-name">${this.escape(line.item_name)}</span>
                                        <span class="rpos-line-amount">${this.formatMoney(line.amount)}</span>
                                    </div>
                                    ${line.options_summary ? `<div class="rpos-line-sub">- ${this.escape(line.options_summary)}</div>` : ""}
                                    ${line.note ? `<div class="rpos-line-note">${this.escape(line.note)}</div>` : ""}
                                </div>
                            `).join("") : `
                                <div style="padding:36px 20px;text-align:center;color:#64748b;font-size:13px;">Esta orden aún no tiene platillos agregados.</div>
                            `}
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
                            <button type="button" class="rpos-btn-secondary" data-action="${selectedOrd.is_draft_row ? "open-precuenta" : "preview-precuenta"}" data-order="${this.escape(selectedOrd.name)}">Ver Precuenta</button>
                            <button type="button" class="rpos-btn-primary" data-action="load-selected-order" data-order="${this.escape(selectedOrd.name)}">Cargar orden</button>
                        </div>
                    ` : `
                        <div class="rpos-ticket-empty">
                            <svg viewBox="0 0 24 24" width="60" height="60" fill="none" stroke="#1e293b" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" style="margin-bottom:14px;">
                                <circle cx="9" cy="21" r="1.6" fill="#1e293b"/>
                                <circle cx="19" cy="21" r="1.6" fill="#1e293b"/>
                                <path d="M2.5 3h2.8l2.4 11.5a2 2 0 0 0 2 1.5h9.8a2 2 0 0 0 1.9-1.4L23 6H6"/>
                            </svg>
                            <div class="rpos-ticket-empty-label">Seleccione una orden o escaneé un código QR.</div>
                        </div>
                    `}
                </aside>
            </div>
        `;
    }

    bindEvents() {
        this.shell.querySelectorAll("[data-nav]").forEach(btn => {
            btn.addEventListener("click", () => {
                if (this.operationBusy) return;
                this.closeSplitView(false);
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

        const catSearch = this.shell.querySelector("[data-category-search]");
        if (catSearch) {
            catSearch.addEventListener("input", e => {
                this.categorySearch = e.target.value;
                this.render();
                const input = this.shell.querySelector("[data-category-search]");
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
                this.orderPage = 1;
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
                this.orderPage = 1;
                this.render();
            });
        }

        this.shell.querySelectorAll("[data-ord-srv]").forEach(btn => {
            btn.addEventListener("click", () => {
                const targetSrv = btn.dataset.ordSrv;
                this.orderServiceFilter = this.orderServiceFilter === targetSrv ? "ALL" : targetSrv;
                this.orderPage = 1;
                this.render();
            });
        });

        this.shell.querySelectorAll("[data-ord-page]").forEach(btn => {
            btn.addEventListener("click", () => {
                if (btn.disabled) return;
                const dir = btn.dataset.ordPage;
                this.orderPage = Math.max(1, (this.orderPage || 1) + (dir === "next" ? 1 : -1));
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
                const rowId = row.dataset.orderRow;
                if (rowId === "__DRAFT__") {
                    this.activeTab = "Caja";
                    this.render();
                    return;
                }
                const ord = (this.bootstrap?.orders || []).find(o => o.name === rowId);
                if (ord) this.loadOrderIntoCaja(ord);
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
        if (action.startsWith("split-")) {
            if (this.operationBusy) return;
            if (action === "split-back") return this.closeSplitView();
            if (action === "split-retry") return this.refreshSplitQuote();
            if (action === "split-pay") return this.performSplit(true);
            if (action === "split-create") return this.performSplit(false);
            if (action === "split-transfer") return this.openTransferTableModal(true);
            if (action === "split-toggle") {
                const item = this.currentOrder.items.find(row => row.name === el.dataset.itemName);
                if (!item) return;
                const selected = this.splitSelection.get(item.name) || 0;
                return this.setSplitQuantity(item.name, selected >= Number(item.qty) ? 0 : Math.min(Number(item.qty), selected + 1));
            }
        }
        if (action === "new-order-modal") return this.openNewAccountModal();
        if (action === "assign-account") return this.openOrderNameModal();
        if (action === "open-order-name-modal") return this.openOrderNameModal();
        if (action === "open-schedule-modal") return this.openScheduleModal();
        if (action === "apply-combo-suggestion") return this.applyDetectedCombo();
        if (action.startsWith("pay-screen-")) return this.handlePaymentScreenAction(action, el);
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
        if (action === "exit-current-order") return this.resetCajaForNextOrder();
        if (action === "open-precuenta") return this.openPrecuentaModal();
        if (action === "open-payment-modal") return this.openPaymentModal();
        if (action === "clear-current-order") return this.clearCurrentOrderContents();
        if (action === "open-command-modal") return this.openCommandModal();
        if (action === "send-kds" || action === "send-kitchen") return this.sendToKdsOnly();
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
            if (ordName === "__DRAFT__") {
                this.activeTab = "Caja";
                this.render();
                return;
            }
            const ord = (this.bootstrap?.orders || []).find(o => o.name === ordName);
            if (ord) this.loadOrderIntoCaja(ord);
            return;
        }
        if (action === "reset-draft-order") {
            this.currentOrder = this.createBlankOrder();
            this.selectedLineIndex = -1;
            this.selectedOrderPreviewName = "";
            this.render();
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

    async loadOrderIntoCaja(orderData) {
        if (orderData?.requires_pin_unlock) {
            const unlocked = await this.requestWaiterPinModal(orderData);
            if (!unlocked) return;
            orderData = unlocked;
        }
        this.closeSplitView(false);
        this.currentOrder = JSON.parse(JSON.stringify(orderData));
        this.selectedLineIndex = (this.currentOrder.items?.length || 0) - 1;
        this.activeTab = "Caja";
        this.render();
    }

    handleProductClick(item) {
        if (this.canInvoice() && !this.bootstrap?.opening_shift) {
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
                (row.kds_status || "Pendiente") === "Pendiente" &&
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

    async requestCancelSentItem(lineIdx, cancelQty = null) {
        const line = this.currentOrder.items[lineIdx];
        if (!line || !this.currentOrder.name || !line.name) return;
        const qtyToCancel = cancelQty === null ? Number(line.qty) : Number(cancelQty);
        if (!Number.isFinite(qtyToCancel) || qtyToCancel <= 0) return;

        const itemLabel = `${qtyToCancel} x ${line.item_name || line.item_code} (Estado: ${line.kds_status})`;
        const orderLabel = this.currentOrder.order_name || this.currentOrder.name;
        const warningText = (line.kds_status === "Listo" || line.kds_status === "Entregado")
            ? `Atención: este platillo ya figura como "${line.kds_status}" en cocina.`
            : "";

        let payload = null;
        if (this.requiresSupervisorAuth()) {
            payload = await this.requestSupervisorAuthModal(
                "Cancelar producto enviado a cocina",
                "restaurant.pos.cancel_sent_order_item",
                {
                    order_name: this.currentOrder.name,
                    item_row_name: line.name,
                    cancel_qty: qtyToCancel,
                    expected_modified: this.currentOrder.modified || "",
                },
                {
                    orderLabel,
                    itemLabel,
                    warningText,
                    requireReason: true,
                }
            );
            if (!payload) return;
        } else {
            const reason = await new Promise(resolve => {
                frappe.prompt(
                    [{ fieldname: "reason", fieldtype: "Small Text", label: "Motivo de cancelación", reqd: 1 }],
                    vals => resolve((vals.reason || "").trim()),
                    `Cancelar producto (${itemLabel})`,
                    "Confirmar cancelación"
                );
            });
            if (!reason) return;
            const res = await frappe.call({
                method: "restaurant.pos.cancel_sent_order_item",
                type: "POST",
                args: {
                    order_name: this.currentOrder.name,
                    item_row_name: line.name,
                    cancel_qty: qtyToCancel,
                    reason,
                    expected_modified: this.currentOrder.modified || "",
                },
                freeze: true,
                freeze_message: "Cancelando producto...",
            });
            payload = res.message;
        }

        if (payload?.order) {
            this.currentOrder = payload.order;
            this.upsertOrderInBootstrap(payload.order);
        }
        if (payload?.areas) {
            this.bootstrap.areas = payload.areas;
        }
        this.numpadBuffer = "";
        this.recalculateLocalTotals();
        this.render();
        frappe.show_alert({
            message: "Producto cancelado y notificado a cocina con registro de auditoría.",
            indicator: "orange",
        });
    }

    handleNumpadKey(key) {
        if (this.selectedLineIndex < 0 || !this.currentOrder.items[this.selectedLineIndex]) return;
        const line = this.currentOrder.items[this.selectedLineIndex];
        if (line.is_cancelled || line.kds_status === "Cancelado") {
            frappe.show_alert({ message: "Este producto ya fue cancelado.", indicator: "orange" });
            return;
        }
        const isSent = this.isSentToKitchenLine(line);

        if (key === "BACK") {
            this.numpadBuffer = this.numpadBuffer.slice(0, -1);
            if (!this.numpadBuffer) {
                if (this.numpadMode === "qty") {
                    if (isSent) {
                        this.requestCancelSentItem(this.selectedLineIndex);
                        return;
                    }
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
            if (isSent && val > 0) {
                const currentQty = Number(line.qty);
                this.numpadBuffer = "";
                if (val < currentQty - 0.001) {
                    this.requestCancelSentItem(this.selectedLineIndex, Number((currentQty - val).toFixed(3)));
                } else if (val > currentQty + 0.001) {
                    frappe.show_alert({
                        message: "Platillo ya enviado a cocina. Agrega una nueva línea para unidades adicionales.",
                        indicator: "orange",
                    });
                }
                return;
            }
            if (val > 0) line.qty = val;
        } else if (this.numpadMode === "disc") {
            if (this.getRposConfig().allow_line_discount === 0 || !this.canInvoice()) {
                frappe.show_alert({ message: "Tu rol no tiene permiso para aplicar descuentos por línea.", indicator: "orange" });
                this.numpadMode = "qty";
                this.numpadBuffer = "";
                return;
            }
            line.discount_percentage = Math.min(100, Math.max(0, val));
        } else if (this.numpadMode === "price") {
            line.base_rate = Math.max(0, val);
        }
        this.render();
        this.persistCurrentOrderSilently();
    }

    getNextSequentialOrderNumber() {
        const orders = this.bootstrap?.orders || [];
        let maxSeq = 1000;
        orders.forEach(o => {
            const idMatch = String(o.name || "").match(/(\d+)$/);
            if (idMatch) {
                const fromId = 1000 + Number(idMatch[1]);
                if (fromId > maxSeq) maxSeq = fromId;
            }
            const rawName = String(o.order_name || "").trim();
            if (/^\d{4}$/.test(rawName)) {
                const n = Number(rawName);
                if (n >= 1000 && n < 3000 && n > maxSeq) {
                    maxSeq = n;
                }
            }
        });
        return String(maxSeq + 1);
    }

    async persistCurrentOrderSilently() {
        if (!this.currentOrder.order_name && !this.currentOrder.items.length) return;
        if (!this.currentOrder.order_name) {
            this.currentOrder.order_name = this.currentOrder.table_label
                ? `Mesa ${this.currentOrder.table_label}`
                : this.getNextSequentialOrderNumber();
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

    /* 1. Apertura de Punto de Venta (diseño POS Awesome OpeningDialog) */
    openShiftDialog() {
        if (!this.canInvoice()) {
            frappe.show_alert({
                message: "Solo cajeros o supervisores pueden abrir turnos de caja.",
                indicator: "orange",
            });
            return;
        }
        const cashier = this.bootstrap?.cashier || { user: frappe.session.user, full_name: frappe.session.user };
        const profiles = this.bootstrap?.pos_profiles || [];
        const companies = (this.bootstrap?.companies && this.bootstrap.companies.length)
            ? this.bootstrap.companies
            : [...new Set(profiles.map(p => p.company).filter(Boolean))];
        const defaultCompany = this.bootstrap?.company?.name || companies[0] || "";

        const backdrop = this.createModal(
            `<span class="rpos-posa-title">Crear Turno de Apertura de POS</span>`,
            `
                <div class="rpos-posa-subtitle">
                    Cajero: <strong>${this.escape(cashier.full_name)}</strong> (${this.escape(cashier.user)})
                </div>
                <div class="rpos-field">
                    <label>Empresa *</label>
                    <select data-shift-company>
                        ${companies.map(c => `<option value="${this.escape(c)}" ${c === defaultCompany ? "selected" : ""}>${this.escape(c)}</option>`).join("")}
                    </select>
                </div>
                <div class="rpos-field">
                    <label>Perfil de Punto de Venta *</label>
                    <select data-shift-profile></select>
                </div>
                <div class="rpos-posa-table-wrap">
                    <table class="rpos-posa-table">
                        <thead>
                            <tr>
                                <th>Modo de Pago</th>
                                <th class="is-center">Monto de Apertura</th>
                            </tr>
                        </thead>
                        <tbody data-shift-payments-body></tbody>
                    </table>
                </div>
            `,
            `
                <button type="button" class="rpos-posa-btn-error" data-shift-exit>Cancelar</button>
                <button type="button" class="rpos-posa-btn-success" data-shift-open>Enviar</button>
            `,
            "600px"
        );

        const closeBtn = backdrop.querySelector(".rpos-modal-header [data-modal-close]");
        if (closeBtn) closeBtn.style.display = "none";

        const companySel = backdrop.querySelector("[data-shift-company]");
        const profileSel = backdrop.querySelector("[data-shift-profile]");
        const paymentsBody = backdrop.querySelector("[data-shift-payments-body]");

        const renderPaymentRows = (profileName) => {
            const prof = profiles.find(p => p.name === profileName) || profiles[0];
            const methods = prof?.payments?.length ? prof.payments : [{ mode_of_payment: "Efectivo" }];
            const curr = prof?.currency === "HNL" || !prof?.currency ? "L" : prof.currency;
            paymentsBody.innerHTML = methods.map(m => `
                <tr>
                    <td><strong>${this.escape(m.mode_of_payment)}</strong></td>
                    <td class="is-center">
                        <div class="rpos-posa-amount-input">
                            <span>${this.escape(curr)}</span>
                            <input type="number" step="0.01" min="0" value="0.00" data-open-mop="${this.escape(m.mode_of_payment)}">
                        </div>
                    </td>
                </tr>
            `).join("");
        };

        const renderProfilesForCompany = (comp) => {
            const matching = profiles.filter(p => !comp || p.company === comp);
            profileSel.innerHTML = matching.map(p => (
                `<option value="${this.escape(p.name)}">${this.escape(p.name)}</option>`
            )).join("");
            renderPaymentRows(profileSel.value);
        };

        companySel.addEventListener("change", () => renderProfilesForCompany(companySel.value));
        profileSel.addEventListener("change", () => renderPaymentRows(profileSel.value));
        renderProfilesForCompany(companySel.value);

        backdrop.querySelector("[data-shift-exit]").addEventListener("click", () => {
            backdrop.remove();
            frappe.set_route("Workspaces", "Restaurante");
        });

        backdrop.querySelector("[data-shift-open]").addEventListener("click", async () => {
            const company = companySel.value;
            const profile = profileSel.value;
            const balanceDetails = [];
            paymentsBody.querySelectorAll("[data-open-mop]").forEach(inp => {
                balanceDetails.push({
                    mode_of_payment: inp.dataset.openMop,
                    amount: Math.max(0, Number(inp.value || 0)),
                });
            });
            if (!company || !profile || !balanceDetails.length) {
                frappe.msgprint("Selecciona una empresa y un perfil de Punto de Venta válido.");
                return;
            }
            const res = await frappe.call({
                method: "restaurant.pos.open_pos_shift",
                args: {
                    company,
                    pos_profile: profile,
                    balance_details: balanceDetails,
                },
                freeze: true,
                freeze_message: "Creando turno de apertura de POS...",
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

        const perms = this.getPermissions();
        const linkedWaiterName = perms.linked_waiter?.name || "";
        const defaultWaiterVal = isEdit
            ? this.currentOrder.waiter
            : (linkedWaiterName || (perms.is_waiter_only ? "" : (waiters[0]?.name || "")));

        const backdrop = this.createModal(
            isEdit ? "Datos de la Cuenta u Orden" : "Abrir Cuenta u Orden",
            `
                <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">
                    <div class="rpos-field">
                        <label>Mesero que atenderá ${perms.is_waiter_only && !linkedWaiterName ? "(opcional)" : "*"}</label>
                        <select data-acc-waiter ${linkedWaiterName ? "disabled" : ""}>
                            <option value="">-- Seleccionar mesero --</option>
                            ${waiters.map(w => `
                                <option value="${this.escape(w.name)}" ${defaultWaiterVal === w.name ? "selected" : ""}>
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
        const rawPresets = (this.bootstrap?.presets && this.bootstrap.presets.length)
            ? this.bootstrap.presets
            : [
                { preset_name: "Comer en el local", color_bg: "#cce3fd", color_border: "#3b82f6", require_customer: 0, enable_scheduling: 0 },
                { preset_name: "Para llevar", color_bg: "#fef0a6", color_border: "#eab308", require_customer: 0, enable_scheduling: 1 },
                { preset_name: "Entrega", color_bg: "#fcd5b5", color_border: "#f97316", require_customer: 1, enable_scheduling: 1 },
            ];
        const presets = rawPresets.map(p => ({
            label: p.preset_name || p.label,
            bg: p.color_bg || p.bg || "#cce3fd",
            border: p.color_border || p.border || "#3b82f6",
            require_customer: Number(p.require_customer || 0),
            enable_scheduling: Number(p.enable_scheduling || 0),
        }));
        const backdrop = this.createModal(
            "Seleccionar el ajuste preestablecido",
            `
                <div class="rpos-preset-list">
                    ${presets.map(p => `
                        <button type="button"
                                class="rpos-preset-row ${this.currentOrder.service_type === p.label ? "is-active" : ""}"
                                data-preset-choice="${this.escape(p.label)}"
                                style="background:${p.bg};border:1.5px solid ${p.border};">
                            <span>${this.escape(p.label)}</span>
                            <span class="rpos-preset-chevron">›</span>
                        </button>
                    `).join("")}
                </div>
            `,
            "",
            "540px"
        );

        backdrop.querySelectorAll("[data-preset-choice]").forEach(btn => {
            btn.addEventListener("click", async () => {
                const chosenLabel = btn.dataset.presetChoice;
                const chosenPreset = presets.find(p => p.label === chosenLabel);
                this.currentOrder.service_type = chosenLabel;
                backdrop.remove();
                this.render();

                if (chosenPreset?.require_customer || chosenLabel === "Entrega") {
                    await this.persistCurrentOrderSilently();
                    this.openCustomerModal({ openScheduleAfter: Boolean(chosenPreset?.enable_scheduling) });
                } else if (chosenPreset?.enable_scheduling || chosenLabel === "Para llevar") {
                    this.openOrderNameModal({ openScheduleAfter: true });
                } else {
                    await this.persistCurrentOrderSilently();
                }
            });
        });
    }

    /* 5b. Modal Definir nombre de la orden (con consecutivo estricto +1 y chips rápidos) */
    openOrderNameModal(opts = {}) {
        const activeOrders = (this.bootstrap?.orders || []).filter(o => o.status === "En curso");
        const nextSuggested = this.getNextSequentialOrderNumber();
        const rawCurrentName = String(this.currentOrder.order_name || "").trim();
        const isAutoGeneratedName = !rawCurrentName || /^orden\s+\d+/i.test(rawCurrentName) || /^mesa\s+/i.test(rawCurrentName);
        const initialVal = isAutoGeneratedName ? nextSuggested : rawCurrentName;

        const chipNames = [];
        activeOrders.forEach(o => {
            const raw = String(o.order_name || "").trim();
            if (!raw) return;
            // Exclude old random placeholders like "Orden 2857" or "Orden 5626 (Cuenta 2)" or "Mesa 1"
            if (/^orden\s+\d+/i.test(raw) || /^mesa\s+/i.test(raw)) return;
            if (!chipNames.includes(raw) && raw !== initialVal) {
                chipNames.push(raw);
            }
        });

        const baseNum = Number(nextSuggested) || 1001;
        for (let offset = 1; offset <= 4; offset++) {
            const seqCandidate = String(baseNum + offset);
            if (chipNames.length < 4 && !chipNames.includes(seqCandidate)) {
                chipNames.push(seqCandidate);
            }
        }

        const visibleChips = chipNames.slice(0, 3);
        const extraChips = chipNames.slice(3);

        const existing = document.querySelector(".rpos-modal-backdrop");
        if (existing) existing.remove();

        const chipBtnStyle = [
            "padding:10px 18px",
            "font-size:15.5px",
            "font-weight:600",
            "color:#1e293b",
            "background:#f1f5f9",
            "border:1px solid #e2e8f0",
            "border-radius:8px",
            "cursor:pointer",
            "line-height:1.2",
        ].join(";");

        const backdrop = document.createElement("div");
        backdrop.className = "rpos-modal-backdrop";
        backdrop.innerHTML = `
            <div class="rpos-modal" style="max-width:430px;border-radius:12px;border:1px solid #e2e8f0;box-shadow:0 20px 45px rgba(15,23,42,0.22);">
                <div class="rpos-modal-header" style="border-bottom:none;padding:20px 22px 10px;">
                    <h3 style="font-size:20px;font-weight:700;color:#0f172a;margin:0;">Definir nombre de la orden</h3>
                    <button type="button" data-modal-close style="background:transparent;border:none;font-size:24px;line-height:1;color:#64748b;cursor:pointer;padding:2px 6px;">×</button>
                </div>
                <div class="rpos-modal-body" style="padding:6px 22px 16px;">
                    <div style="margin-bottom:12px;">
                        <input type="text" data-order-name-inp maxlength="140" value="${this.escape(initialVal)}" placeholder="Ej. 2014, padilla, llevar..." style="font-size:16.5px;font-weight:500;color:#0f172a;background:#ffffff;padding:10px 14px;border:1px solid #cbd5e1;border-radius:8px;width:100%;outline:none;">
                    </div>
                    <div style="display:flex;flex-wrap:wrap;gap:8px;" data-order-name-chips>
                        ${visibleChips.map(c => `
                            <button type="button" data-name-chip="${this.escape(c)}" style="${chipBtnStyle}">
                                ${this.escape(c)}
                            </button>
                        `).join("")}
                        ${extraChips.length ? `
                            <button type="button" data-name-chip-more style="${chipBtnStyle};font-weight:700;">
                                +${extraChips.length}
                            </button>
                        ` : ""}
                    </div>
                </div>
                <div class="rpos-modal-footer" style="border-top:none;background:#ffffff;padding:6px 22px 22px;justify-content:flex-start;gap:10px;">
                    <button type="button" data-order-name-apply style="background:#2F8500;border:1px solid #236600;color:#ffffff;font-size:15.5px;font-weight:700;padding:11px 22px;border-radius:8px;cursor:pointer;">Aplicar</button>
                    <button type="button" data-modal-close style="background:#f1f5f9;border:1px solid #e2e8f0;color:#1e293b;font-size:15.5px;font-weight:600;padding:11px 22px;border-radius:8px;cursor:pointer;">Descartar</button>
                </div>
            </div>
        `;
        backdrop.querySelectorAll("[data-modal-close]").forEach(btn => btn.addEventListener("click", () => backdrop.remove()));
        document.body.appendChild(backdrop);

        const inp = backdrop.querySelector("[data-order-name-inp]");
        setTimeout(() => { inp.focus(); inp.select(); }, 40);

        const bindChips = () => {
            backdrop.querySelectorAll("[data-name-chip]").forEach(btn => {
                btn.addEventListener("click", () => {
                    inp.value = btn.dataset.nameChip;
                    inp.focus();
                });
            });
        };
        bindChips();

        const moreBtn = backdrop.querySelector("[data-name-chip-more]");
        if (moreBtn) {
            moreBtn.addEventListener("click", () => {
                const container = backdrop.querySelector("[data-order-name-chips]");
                container.innerHTML = chipNames.map(c => `
                    <button type="button" data-name-chip="${this.escape(c)}" style="${chipBtnStyle}">
                        ${this.escape(c)}
                    </button>
                `).join("");
                bindChips();
            });
        }

        const saveName = async () => {
            const val = inp.value.trim();
            if (!val) {
                frappe.msgprint("Ingresa un nombre o número para la orden.");
                return;
            }
            this.currentOrder.order_name = val;
            backdrop.remove();
            this.render();
            await this.persistCurrentOrderSilently();
            if (opts.openScheduleAfter) {
                this.openScheduleModal();
            }
        };

        backdrop.querySelector("[data-order-name-apply]").addEventListener("click", saveName);
        inp.addEventListener("keydown", e => {
            if (e.key === "Enter") {
                e.preventDefault();
                saveName();
            }
        });
    }

    /* 5c. Modal Programador de Horario (7 días y bloques de 20 minutos para Para llevar / Entrega) */
    openScheduleModal() {
        const presetCfg = this.currentPresetConfig();
        const intervalMins = Math.max(5, Number(presetCfg.slot_interval_minutes || 20));
        const startStr = String(presetCfg.schedule_start_time || "12:00");
        const endStr = String(presetCfg.schedule_end_time || "22:00");

        const parseHm = hm => {
            const [h, m] = String(hm).split(":").map(Number);
            return (Number.isFinite(h) ? h : 12) * 60 + (Number.isFinite(m) ? m : 0);
        };
        const startTotalMins = parseHm(startStr);
        const endTotalMins = parseHm(endStr);

        const dayNames = ["domingo", "lunes", "martes", "miércoles", "jueves", "viernes", "sábado"];
        const monthLong = [
            "enero", "febrero", "marzo", "abril", "mayo", "junio",
            "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"
        ];
        const baseNow = new Date(Date.now() + (this.serverClockOffsetMs || 0));

        const days = [];
        for (let i = 0; i < 7; i++) {
            const d = new Date(baseNow.getFullYear(), baseNow.getMonth(), baseNow.getDate() + i);
            const yyyy = d.getFullYear();
            const mm = String(d.getMonth() + 1).padStart(2, "0");
            const dd = String(d.getDate()).padStart(2, "0");
            const isoDate = `${yyyy}-${mm}-${dd}`;
            const title = i === 0 ? "Hoy" : (i === 1 ? "Mañana" : dayNames[d.getDay()]);
            const subtitle = i <= 1 ? "" : `${d.getDate()} de ${monthLong[d.getMonth()]}`;
            days.push({ index: i, isoDate, title, subtitle });
        }

        let selectedDayIdx = 0;
        let selectedSlot = "";
        if (this.currentOrder.scheduled_time) {
            const norm = String(this.currentOrder.scheduled_time).trim().replace("T", " ");
            const [existDate, existTime] = norm.split(" ");
            const foundIdx = days.findIndex(d => d.isoDate === existDate);
            if (foundIdx >= 0) selectedDayIdx = foundIdx;
            if (existTime) selectedSlot = existTime.slice(0, 5);
        }

        const buildSlotsForDay = dayIdx => {
            const nowMins = baseNow.getHours() * 60 + baseNow.getMinutes();
            const morning = [];
            const afternoon = [];
            for (let mins = startTotalMins; mins <= endTotalMins; mins += intervalMins) {
                if (dayIdx === 0 && mins <= nowMins + 5) continue;
                const hh = String(Math.floor(mins / 60)).padStart(2, "0");
                const mm = String(mins % 60).padStart(2, "0");
                const hm = `${hh}:${mm}`;
                if (mins <= 12 * 60 + 40) morning.push(hm);
                else afternoon.push(hm);
            }
            return { morning, afternoon, total: morning.length + afternoon.length };
        };

        const modalTitle = this.currentOrder.service_type === "Entrega" ? "Entrega" : "Para llevar";
        const existing = document.querySelector(".rpos-modal-backdrop");
        if (existing) existing.remove();

        const backdrop = document.createElement("div");
        backdrop.className = "rpos-modal-backdrop";
        backdrop.innerHTML = `
            <div class="rpos-modal" style="max-width:980px;">
                <div class="rpos-modal-header" style="border-bottom:none;padding:18px 22px 6px;">
                    <h3 style="font-size:20px;font-weight:700;color:#0f172a;margin:0;">${this.escape(modalTitle)}</h3>
                    <button type="button" class="rpos-icon-btn" data-modal-close>×</button>
                </div>
                <div class="rpos-modal-body" style="padding:12px 22px 18px;">
                    <div style="display:flex;gap:6px;overflow-x:auto;padding-bottom:4px;" data-sched-days></div>
                    <hr style="border:0;border-top:1px solid #e2e8f0;margin:14px 0 18px;">
                    <div style="min-height:110px;" data-sched-body></div>
                </div>
                <div class="rpos-modal-footer" style="justify-content:flex-start;gap:10px;border-top:none;padding:6px 22px 20px;">
                    <button type="button" class="rpos-btn-primary" data-sched-confirm style="background:#2F8500;border-color:#236600;min-width:118px;padding:10px 20px;font-size:14.5px;justify-content:center;">Continuar</button>
                    ${this.currentOrder.scheduled_time ? `<button type="button" class="rpos-btn-secondary" data-sched-clear>Quitar horario</button>` : ""}
                </div>
            </div>
        `;
        backdrop.querySelectorAll("[data-modal-close]").forEach(btn => btn.addEventListener("click", () => backdrop.remove()));
        document.body.appendChild(backdrop);

        const renderSchedule = () => {
            const daysContainer = backdrop.querySelector("[data-sched-days]");
            daysContainer.innerHTML = days.map(d => {
                const isAct = d.index === selectedDayIdx;
                return `
                    <button type="button" data-sched-day="${d.index}" style="min-width:112px;padding:9px 12px;border-radius:7px;border:1.5px solid ${isAct ? "#236600" : "#cbd5e1"};background:${isAct ? "#2F8500" : "#f1f5f9"};color:${isAct ? "#ffffff" : "#1e293b"};cursor:pointer;text-align:center;display:flex;flex-direction:column;align-items:center;justify-content:center;min-height:54px;">
                        <div style="font-size:13px;font-weight:700;line-height:1.25;">${this.escape(d.title)}</div>
                        ${d.subtitle ? `<div style="font-size:11.5px;font-weight:600;opacity:${isAct ? "0.95" : "0.8"};margin-top:2px;">${this.escape(d.subtitle)}</div>` : ""}
                    </button>
                `;
            }).join("");

            daysContainer.querySelectorAll("[data-sched-day]").forEach(btn => {
                btn.addEventListener("click", () => {
                    selectedDayIdx = Number(btn.dataset.schedDay);
                    selectedSlot = "";
                    renderSchedule();
                });
            });

            const { morning, afternoon, total } = buildSlotsForDay(selectedDayIdx);
            const body = backdrop.querySelector("[data-sched-body]");

            if (total === 0) {
                body.innerHTML = `
                    <div style="background:#fef3c7;border:1px solid #fde68a;color:#92400e;padding:14px 18px;border-radius:7px;font-size:13.5px;font-weight:600;">
                        No hay un espacio disponible para ese día
                    </div>
                `;
                return;
            }

            if (selectedSlot && !morning.includes(selectedSlot) && !afternoon.includes(selectedSlot)) {
                selectedSlot = "";
            }

            const renderSlotGrid = list => `
                <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(66px,1fr));gap:8px;margin-bottom:16px;">
                    ${list.map(hm => {
                const isSel = hm === selectedSlot;
                return `
                            <button type="button" data-sched-slot="${hm}" style="padding:8px 6px;border-radius:6px;border:1.5px solid ${isSel ? "#0284c7" : "#86efac"};background:${isSel ? "#1898e8" : "#bbf7d0"};color:${isSel ? "#ffffff" : "#14532d"};font-weight:700;font-size:13px;cursor:pointer;text-align:center;">
                                ${hm}
                            </button>
                        `;
            }).join("")}
                </div>
            `;

            body.innerHTML = `
                ${morning.length ? `<div style="font-size:13px;color:#334155;font-weight:600;margin-bottom:8px;">Mañana</div>${renderSlotGrid(morning)}` : ""}
                ${afternoon.length ? `<div style="font-size:13px;color:#334155;font-weight:600;margin-bottom:8px;">Tarde</div>${renderSlotGrid(afternoon)}` : ""}
            `;

            body.querySelectorAll("[data-sched-slot]").forEach(btn => {
                btn.addEventListener("click", () => {
                    selectedSlot = btn.dataset.schedSlot;
                    renderSchedule();
                });
            });
        };

        renderSchedule();

        const clearBtn = backdrop.querySelector("[data-sched-clear]");
        if (clearBtn) {
            clearBtn.addEventListener("click", async () => {
                this.currentOrder.scheduled_time = null;
                backdrop.remove();
                this.render();
                await this.persistCurrentOrderSilently();
            });
        }

        backdrop.querySelector("[data-sched-confirm]").addEventListener("click", async () => {
            if (selectedSlot) {
                const chosenDay = days[selectedDayIdx];
                this.currentOrder.scheduled_time = `${chosenDay.isoDate} ${selectedSlot}:00`;
            }
            backdrop.remove();
            this.render();
            await this.persistCurrentOrderSilently();
        });
    }

    /* 6. Modal de Cliente ("Elige un cliente" con búsqueda, dirección, correo y botón Crear) */
    openCustomerModal(opts = {}) {
        const customers = this.bootstrap?.customers || [];
        let searchQuery = "";
        let editingCustomer = null;

        const existing = document.querySelector(".rpos-modal-backdrop");
        if (existing) existing.remove();

        const backdrop = document.createElement("div");
        backdrop.className = "rpos-modal-backdrop";
        backdrop.innerHTML = `
            <div class="rpos-modal" style="max-width:780px;">
                <div class="rpos-modal-header" style="display:flex;align-items:center;justify-content:space-between;gap:12px;padding:12px 18px;border-bottom:1px solid #e2e8f0;">
                    <div style="display:flex;align-items:center;gap:12px;">
                        <button type="button" class="rpos-btn-primary" data-cust-create-btn style="background:#2F8500;border-color:#236600;padding:7px 16px;">Crear</button>
                        <h3 style="margin:0;font-size:17px;">Elige un cliente</h3>
                    </div>
                    <div style="display:flex;align-items:center;gap:10px;flex:1;max-width:300px;">
                        <input type="search" data-cust-search-inp placeholder="🔍 Buscar clientes..." style="width:100%;padding:7px 12px;border:1px solid #cbd5e1;border-radius:7px;font-size:13.5px;">
                        <button type="button" class="rpos-icon-btn" data-modal-close>×</button>
                    </div>
                </div>
                <div class="rpos-modal-body" style="padding:0;min-height:360px;max-height:460px;overflow-y:auto;" data-cust-body></div>
                <div class="rpos-modal-footer" style="padding:12px 18px;background:#ffffff;">
                    <button type="button" data-modal-close style="width:100%;justify-content:center;background:#f1f5f9;border:1px solid #cbd5e1;color:#1e293b;border-radius:7px;padding:10px 18px;font-size:14px;font-weight:600;cursor:pointer;">Descartar</button>
                </div>
            </div>
        `;
        backdrop.querySelectorAll("[data-modal-close]").forEach(btn => btn.addEventListener("click", () => backdrop.remove()));
        document.body.appendChild(backdrop);

        const renderBody = () => {
            const body = backdrop.querySelector("[data-cust-body]");
            if (editingCustomer) {
                const isNew = !editingCustomer.name;
                body.innerHTML = `
                    <div style="padding:18px;">
                        <h4 style="margin:0 0 14px;font-size:15px;">${isNew ? "Crear nuevo cliente" : `Editar cliente · ${this.escape(editingCustomer.customer_name)}`}</h4>
                        <div style="display:grid;grid-template-columns:1.2fr 1fr;gap:12px;">
                            <div class="rpos-field">
                                <label>Nombre o Razón Social *</label>
                                <input type="text" data-edit-cust-name value="${this.escape(editingCustomer.customer_name || "")}" placeholder="Ej. Juan Padilla">
                            </div>
                            <div class="rpos-field">
                                <label>RTN Fiscal (SAR)</label>
                                <input type="text" data-edit-cust-rtn value="${this.escape(editingCustomer.tax_id || "")}" placeholder="Ej. 08011999123456">
                            </div>
                        </div>
                        <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;">
                            <div class="rpos-field">
                                <label>Dirección / Ciudad</label>
                                <input type="text" data-edit-cust-address value="${this.escape(editingCustomer.address || "")}" placeholder="Ej. sps, Honduras">
                            </div>
                            <div class="rpos-field">
                                <label>Correo electrónico</label>
                                <input type="email" data-edit-cust-email value="${this.escape(editingCustomer.email_id || "")}" placeholder="correo@ejemplo.com">
                            </div>
                            <div class="rpos-field">
                                <label>Teléfono / Celular</label>
                                <input type="text" data-edit-cust-phone value="${this.escape(editingCustomer.mobile_no || "")}" placeholder="+504 ...">
                            </div>
                        </div>
                        <div style="display:flex;justify-content:flex-end;gap:10px;margin-top:16px;">
                            <button type="button" class="rpos-btn-secondary" data-edit-cust-cancel>Volver a la lista</button>
                            <button type="button" class="rpos-btn-primary" data-edit-cust-save style="background:#2F8500;border-color:#236600;">Guardar y Seleccionar</button>
                        </div>
                    </div>
                `;
                body.querySelector("[data-edit-cust-cancel]").addEventListener("click", () => {
                    editingCustomer = null;
                    renderBody();
                });
                body.querySelector("[data-edit-cust-save]").addEventListener("click", async () => {
                    const cName = body.querySelector("[data-edit-cust-name]").value.trim();
                    if (!cName) {
                        frappe.msgprint("Ingresa el nombre del cliente.");
                        return;
                    }
                    const res = await frappe.call({
                        method: "restaurant.pos.save_customer_with_rtn",
                        args: {
                            customer_id: editingCustomer.name || null,
                            customer_name: cName,
                            tax_id: body.querySelector("[data-edit-cust-rtn]").value.trim(),
                            address: body.querySelector("[data-edit-cust-address]").value.trim(),
                            email_id: body.querySelector("[data-edit-cust-email]").value.trim(),
                            mobile_no: body.querySelector("[data-edit-cust-phone]").value.trim(),
                        },
                    });
                    const saved = res.message;
                    const idx = customers.findIndex(c => c.name === saved.name);
                    if (idx >= 0) customers[idx] = saved;
                    else customers.unshift(saved);
                    this.currentOrder.customer = saved.name;
                    this.currentOrder.customer_name = saved.customer_name;
                    this.currentOrder.tax_id = saved.tax_id || "";
                    backdrop.remove();
                    this.render();
                    await this.persistCurrentOrderSilently();
                    if (opts.openScheduleAfter) {
                        this.openScheduleModal();
                    }
                });
                return;
            }

            const q = searchQuery.trim().toLowerCase();
            const filtered = customers.filter(c => {
                if (!q) return true;
                return `${c.customer_name || ""} ${c.tax_id || ""} ${c.address || ""} ${c.email_id || ""} ${c.mobile_no || ""}`.toLowerCase().includes(q);
            });

            body.innerHTML = filtered.length ? filtered.map(c => {
                const isSelected = this.currentOrder.customer === c.name;
                return `
                    <div class="rpos-cust-row" data-cust-pick="${this.escape(c.name)}" style="display:grid;grid-template-columns:1.3fr 1fr 1.3fr auto;align-items:center;gap:12px;padding:14px 18px;border-bottom:1px solid #f1f5f9;cursor:pointer;background:${isSelected ? "#f0f9ff" : "#ffffff"};">
                        <div style="font-weight:700;font-size:13.5px;color:#0f172a;">${this.escape(c.customer_name)}</div>
                        <div style="font-size:12.5px;color:#475569;">${this.escape(c.address || (c.tax_id ? `RTN: ${c.tax_id}` : ""))}</div>
                        <div style="font-size:12.5px;color:#475569;">
                            ${c.email_id ? `<span>✉ ${this.escape(c.email_id)}</span>` : ""}
                            ${c.mobile_no ? `<span style="margin-left:6px;">📞 ${this.escape(c.mobile_no)}</span>` : ""}
                        </div>
                        <button type="button" data-cust-edit="${this.escape(c.name)}" title="Editar cliente" style="padding:6px 10px;background:#f1f5f9;border:1px solid #cbd5e1;color:#1e293b;border-radius:6px;font-weight:700;cursor:pointer;">≡</button>
                    </div>
                `;
            }).join("") : `
                <div style="padding:36px;text-align:center;color:#64748b;font-size:13.5px;">
                    No se encontraron clientes con "${this.escape(searchQuery)}". Pulsa <strong>Crear</strong> para registrarlo.
                </div>
            `;

            body.querySelectorAll("[data-cust-pick]").forEach(row => {
                row.addEventListener("click", async e => {
                    if (e.target.closest("[data-cust-edit]")) return;
                    const chosen = customers.find(c => c.name === row.dataset.custPick);
                    if (!chosen) return;
                    this.currentOrder.customer = chosen.name;
                    this.currentOrder.customer_name = chosen.customer_name;
                    this.currentOrder.tax_id = chosen.tax_id || "";
                    backdrop.remove();
                    this.render();
                    await this.persistCurrentOrderSilently();
                    if (opts.openScheduleAfter) {
                        this.openScheduleModal();
                    }
                });
            });

            body.querySelectorAll("[data-cust-edit]").forEach(btn => {
                btn.addEventListener("click", e => {
                    e.stopPropagation();
                    const chosen = customers.find(c => c.name === btn.dataset.custEdit);
                    if (chosen) {
                        editingCustomer = { ...chosen };
                        renderBody();
                    }
                });
            });
        };

        renderBody();

        backdrop.querySelector("[data-cust-create-btn]").addEventListener("click", () => {
            editingCustomer = { customer_name: searchQuery.trim(), tax_id: "", address: "", email_id: "", mobile_no: "" };
            renderBody();
        });

        backdrop.querySelector("[data-cust-search-inp]").addEventListener("input", e => {
            searchQuery = e.target.value;
            editingCustomer = null;
            renderBody();
        });
    }

    /* 6b. Modal Número de invitados con teclado numérico y cálculo L X / Invitado */
    openGuestsModal() {
        this.recalculateLocalTotals();
        const total = Number(this.currentOrder.grand_total || 0);
        let buffer = String(Math.max(1, Number(this.currentOrder.guests || 1)));
        let freshStart = true;

        const backdrop = this.createModal(
            "Número de invitados",
            `
                <div style="text-align:center;margin-bottom:10px;">
                    <div data-guests-display style="font-size:22px;font-weight:700;padding:10px;border:1.5px solid #cbd5e1;border-radius:8px;background:#ffffff;margin-bottom:6px;">
                        ${this.escape(buffer)}
                    </div>
                    <div data-guests-per-label style="font-size:13px;color:#475569;font-weight:600;"></div>
                </div>
                <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:6px;margin-bottom:6px;">
                    ${["1", "2", "3", "4", "5", "6", "7", "8", "9"].map(k => `
                        <button type="button" class="rpos-key" data-guest-key="${k}" style="height:52px;font-size:18px;font-weight:700;">${k}</button>
                    `).join("")}
                    <button type="button" class="rpos-key is-dot" data-guest-key="," style="height:52px;font-size:18px;">,</button>
                    <button type="button" class="rpos-key" data-guest-key="0" style="height:52px;font-size:18px;font-weight:700;">0</button>
                    <button type="button" class="rpos-key is-back" data-guest-key="BACK" style="height:52px;font-size:18px;">⌫</button>
                </div>
            `,
            `
                <button type="button" class="rpos-btn-primary" data-guests-confirm style="flex:1;justify-content:center;background:#2F8500;border-color:#236600;">Confirmar</button>
                <button type="button" data-modal-close style="flex:1;justify-content:center;background:#f1f5f9;border:1px solid #cbd5e1;color:#1e293b;border-radius:6px;padding:9px 20px;font-size:14px;font-weight:600;cursor:pointer;">Descartar</button>
            `,
            "380px"
        );

        const dispEl = backdrop.querySelector("[data-guests-display]");
        const perEl = backdrop.querySelector("[data-guests-per-label]");

        const refreshView = () => {
            const count = Math.max(1, parseInt(buffer || "1", 10) || 1);
            dispEl.textContent = buffer || "1";
            const perGuest = total / count;
            perEl.textContent = `${this.formatMoney(perGuest)} / Invitado`;
        };
        refreshView();

        backdrop.querySelectorAll("[data-guest-key]").forEach(btn => {
            btn.addEventListener("click", () => {
                const k = btn.dataset.guestKey;
                if (k === "BACK") {
                    buffer = buffer.slice(0, -1);
                    freshStart = false;
                } else if (k === ",") {
                    return;
                } else {
                    if (freshStart) {
                        buffer = k;
                        freshStart = false;
                    } else if (buffer.length < 3) {
                        buffer += k;
                    }
                }
                refreshView();
            });
        });

        backdrop.querySelector("[data-guests-confirm]").addEventListener("click", async () => {
            const count = Math.max(1, parseInt(buffer || "1", 10) || 1);
            this.currentOrder.guests = count;
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
                            <svg viewBox="0 0 24 24" width="38" height="38" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="8" y1="13" x2="16" y2="13"/><line x1="8" y1="17" x2="13" y2="17"/></svg>
                        </span>
                        <span>Nota para el cliente</span>
                    </button>
                    <button type="button" class="rpos-action-tile" data-act-tile="precuenta">
                        <span class="rpos-action-icon" aria-hidden="true">
                            <svg viewBox="0 0 24 24" width="38" height="38" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 6 2 18 2 18 9"/><path d="M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2"/><rect x="6" y="14" width="12" height="8"/></svg>
                        </span>
                        <span>Pre-cuenta</span>
                    </button>
                    <button type="button" class="rpos-action-tile" data-act-tile="guests">
                        <span class="rpos-action-guest-badge">${guestsCount}</span>
                        <span>Invitado</span>
                    </button>
                    <button type="button" class="rpos-action-tile" data-act-tile="split">
                        <span class="rpos-action-icon" aria-hidden="true">
                            <svg viewBox="0 0 24 24" width="38" height="38" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="5" width="11" height="14" rx="2"/><path d="M5 19H4a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2h9"/></svg>
                        </span>
                        <span>Dividir</span>
                    </button>
                    <button type="button" class="rpos-action-tile" data-act-tile="transfer">
                        <span class="rpos-action-icon" aria-hidden="true">
                            <svg viewBox="0 0 24 24" width="38" height="38" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><line x1="5" y1="12" x2="19" y2="12"/><polyline points="12 5 19 12 12 19"/></svg>
                        </span>
                        <span>Transferir / Fusionar</span>
                    </button>
                    <button type="button" class="rpos-action-tile" data-act-tile="transfer-food">
                        <span class="rpos-action-icon" aria-hidden="true">
                            <svg viewBox="0 0 24 24" width="38" height="38" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="5" x2="12" y2="19"/><polyline points="19 12 12 19 5 12"/></svg>
                        </span>
                        <span>Transferir comida</span>
                    </button>
                    <button type="button" class="rpos-action-tile" data-act-tile="rename">
                        <span class="rpos-action-icon" aria-hidden="true">
                            <svg viewBox="0 0 24 24" width="38" height="38" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
                        </span>
                        <span>Definir nombre de la orden</span>
                    </button>
                    ${!this.getPermissions().is_waiter_only ? `
                    <button type="button" class="rpos-action-tile" data-act-tile="pricelist">
                        <span class="rpos-action-icon" aria-hidden="true">
                            <svg viewBox="0 0 24 24" width="38" height="38" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="16" rx="2"/><line x1="3" y1="10" x2="21" y2="10"/><line x1="9" y1="4" x2="9" y2="20"/></svg>
                        </span>
                        <span>Lista de precios</span>
                    </button>
                    ` : ""}
                </div>
                <button type="button" class="rpos-action-cancel-bar" data-act-tile="cancel">
                    <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/><path d="M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/></svg>
                    <span>Cancelar orden</span>
                </button>
            `,
            "",
            "1040px"
        );

        const modalBox = backdrop.querySelector(".rpos-modal");
        if (modalBox) modalBox.classList.add("rpos-modal-actions-lg");

        backdrop.querySelectorAll("[data-act-tile]").forEach(btn => {
            btn.addEventListener("click", () => {
                const tile = btn.dataset.actTile;
                backdrop.remove();
                if (tile === "precuenta") return this.openPrecuentaModal();
                if (tile === "tip") return this.openTipModal();
                if (tile === "rename") return this.openOrderNameModal();
                if (tile === "guests") return this.openGuestsModal();
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
                ${this.canInvoice() ? '<button type="button" class="rpos-btn-green" data-precuenta-pay>Pasar a Facturar</button>' : ""}
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

    /* 10. Pantalla Completa de Pago (estilo Odoo) y Emisión de Factura Fiscal SAR */
    async openPaymentModal() {
        if (!this.canInvoice()) {
            frappe.msgprint("No tienes permiso para cobrar ni emitir facturas SAR. Solicita al cajero o supervisor.");
            return;
        }
        if (!this.currentOrder.items.length) {
            frappe.msgprint("Agrega al menos un platillo o bebida antes de proceder al pago.");
            return;
        }
        await this.persistCurrentOrderSilently();
        this.recalculateLocalTotals();
        const mops = this.bootstrap?.modes_of_payment || [{ name: "Efectivo" }, { name: "Tarjetas de credito" }, { name: "Transferencia bancaria" }];
        const defaultMop = mops.find(m => m.name.toLowerCase().includes("efectivo"))?.name || mops[0]?.name || "Efectivo";

        this.paymentScreenState = {
            step: "pay",
            selectedMop: defaultMop,
            tenderedBuffer: "",
            payments: [],
            invoiceToggle: true,
            invoice: null,
            finishedOrder: null,
        };
        this.render();
    }

    renderPaymentScreenView() {
        const st = this.paymentScreenState;
        if (!st) return "";

        if (st.step === "done") {
            const cfg = this.getRposConfig();
            const paidTotal = Number(st.invoice?.grand_total ?? st.finishedOrder?.grand_total ?? 0);
            const [intPart, decPart] = paidTotal.toFixed(2).split(".");
            return `
                <div style="display:flex;flex-direction:column;justify-content:space-between;height:calc(100vh - 64px);background:#f8fafc;padding:36px 28px 20px;">
                    <div style="flex:1;display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;">
                        <div style="width:76px;height:76px;border-radius:50%;background:#16a34a;color:#ffffff;display:flex;align-items:center;justify-content:center;margin-bottom:18px;box-shadow:0 8px 20px rgba(22,163,74,0.25);">
                            <svg viewBox="0 0 24 24" width="42" height="42" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>
                        </div>
                        <h2 style="font-size:36px;font-weight:800;color:#1e293b;margin:0 0 12px;">Importe pagado</h2>
                        <div style="font-size:112px;font-weight:800;line-height:1;color:#1e293b;letter-spacing:-2px;">
                            <span style="font-size:68px;color:#64748b;margin-right:8px;">L</span><span>${this.escape(intPart)}</span><span style="color:#64748b;">,${this.escape(decPart)}</span>
                        </div>
                        ${st.invoice?.name ? `<div style="margin-top:14px;font-size:13.5px;color:#475569;font-weight:600;">Factura Fiscal SAR: <strong>${this.escape(st.invoice.name)}</strong> · Cliente: ${this.escape(st.invoice.customer_name || "Consumidor Final")}</div>` : ""}
                        ${cfg.enable_self_invoicing && st.invoice?.name ? `
                            <div style="margin-top:10px;">
                                <button type="button" data-action="pay-screen-self-invoice" style="padding:8px 16px;border-radius:6px;border:1px solid #002456;background:#eff6ff;color:#002456;font-size:12.5px;font-weight:700;cursor:pointer;">
                                    🧾 Datos de Autofacturación (QR / URL)
                                </button>
                            </div>
                        ` : ""}
                    </div>
                    <div style="display:flex;flex-wrap:wrap;gap:12px;padding-top:16px;">
                        <button type="button" data-action="pay-screen-back-done" style="flex:1;min-width:120px;height:52px;justify-content:center;font-size:14px;font-weight:700;background:#f1f5f9;border:1px solid #cbd5e1;color:#1e293b;border-radius:7px;cursor:pointer;">
                            ‹ Regresar
                        </button>
                        <button type="button" data-action="pay-screen-print-invoice" style="flex:1;min-width:120px;height:52px;justify-content:center;font-size:14px;font-weight:700;background:#f1f5f9;border:1px solid #cbd5e1;color:#1e293b;border-radius:7px;cursor:pointer;">
                            🖨 Imprimir
                        </button>
                        ${cfg.allow_email_invoice !== 0 ? `
                            <button type="button" data-action="pay-screen-email-receipt" style="flex:1;min-width:140px;height:52px;justify-content:center;font-size:14px;font-weight:700;background:#f1f5f9;border:1px solid #cbd5e1;color:#1e293b;border-radius:7px;cursor:pointer;">
                                ✉️ Enviar por Correo
                            </button>
                        ` : ""}
                        ${cfg.allow_whatsapp_invoice ? `
                            <button type="button" data-action="pay-screen-whatsapp-receipt" style="flex:1;min-width:150px;height:52px;justify-content:center;font-size:14px;font-weight:700;background:#effbe9;border:1px solid #a4ce87;color:#2f8500;border-radius:7px;cursor:pointer;">
                                💬 Enviar por WhatsApp
                            </button>
                        ` : ""}
                        <button type="button" class="rpos-btn-primary" data-action="pay-screen-continue" style="flex:1.2;min-width:140px;height:52px;justify-content:center;font-size:14px;font-weight:700;background:#2F8500;border-color:#236600;">
                            Continuar
                        </button>
                    </div>
                </div>
            `;
        }

        const cfg = this.getRposConfig();
        this.recalculateLocalTotals();
        const grand = Number(this.currentOrder.grand_total || 0);
        const tenderedNum = st.tenderedBuffer ? Number(st.tenderedBuffer) : grand;
        const change = Math.max(0, Number((tenderedNum - grand).toFixed(2)));
        const [intPart, decPart] = grand.toFixed(2).split(".");

        const rawMops = this.bootstrap?.modes_of_payment || [];
        const mopIcon = (name) => {
            const lower = (name || "").toLowerCase();
            if (lower.includes("efectivo") || lower.includes("cash")) return "💵";
            if (lower.includes("tarjeta") || lower.includes("card")) return "💳";
            if (lower.includes("transferencia") || lower.includes("banco")) return "🏦";
            return "🪪";
        };
        const mopCards = rawMops.length
            ? rawMops.map(m => ({ label: m.name, mop: m.name, icon: mopIcon(m.name) }))
            : [{ label: "Efectivo", mop: "Efectivo", icon: "💵" }];
        if (!mopCards.some(c => c.mop === st.selectedMop) && mopCards.length) {
            st.selectedMop = mopCards[0].mop;
            st.selectedLabel = mopCards[0].label;
        }

        return `
            <div style="display:grid;grid-template-columns:360px 1fr;height:calc(100vh - 64px);background:#f8fafc;">
                <div style="display:flex;flex-direction:column;justify-content:space-between;padding:14px;border-right:1px solid #e2e8f0;background:#ffffff;overflow-y:auto;">
                    <div style="display:flex;flex-direction:column;gap:8px;">
                        ${mopCards.map(mc => {
            const isSel = st.selectedMop === mc.mop || (!st.selectedMop && mc === mopCards[0]);
            return `
                                <button type="button" data-action="pay-screen-mop" data-mop="${this.escape(mc.mop)}" data-mop-label="${this.escape(mc.label)}" style="display:flex;align-items:center;gap:12px;padding:12px 14px;border-radius:8px;border:1.5px solid ${isSel ? "#002456" : "#cbd5e1"};background:${isSel ? "#eff6ff" : "#f8fafc"};font-size:14px;font-weight:700;color:#1e293b;cursor:pointer;text-align:left;">
                                    <span style="font-size:18px;">${mc.icon}</span>
                                    <span>${this.escape(mc.label)}</span>
                                </button>
                            `;
        }).join("")}
                        ${st.tenderedBuffer ? `
                            <div style="margin-top:6px;padding:10px 12px;background:#f0fdf4;border:1px solid #86efac;border-radius:7px;display:flex;justify-content:space-between;font-size:13.5px;font-weight:700;color:#166534;">
                                <span>Recibido (${this.escape(st.selectedLabel || st.selectedMop || "Efectivo")}):</span>
                                <span>${this.formatMoney(tenderedNum)}</span>
                            </div>
                        ` : ""}
                        ${change > 0 ? `
                            <div style="padding:8px 12px;background:#eff6ff;border:1px solid #bfdbfe;border-radius:7px;display:flex;justify-content:space-between;font-size:13px;font-weight:700;color:#1d4ed8;">
                                <span>Cambio a entregar:</span>
                                <span>${this.formatMoney(change)}</span>
                            </div>
                        ` : ""}
                        ${st.globalDiscountPct > 0 ? `<div style="padding:6px 10px;background:#effbe9;border:1px solid #a4ce87;border-radius:6px;font-size:12px;font-weight:700;color:#2f8500;">Descuento global: ${st.globalDiscountPct}%</div>` : ""}
                        ${st.couponCode ? `<div style="padding:6px 10px;background:#effbe9;border:1px solid #a4ce87;border-radius:6px;font-size:12px;font-weight:700;color:#2f8500;">Cupón: ${this.escape(st.couponCode)}</div>` : ""}
                        ${st.giftCardCode ? `<div style="padding:6px 10px;background:#eff6ff;border:1px solid #bfdbfe;border-radius:6px;font-size:12px;font-weight:700;color:#002456;">Tarjeta Regalo: ${this.escape(st.giftCardCode)} (${this.formatMoney(st.giftCardAmount)})</div>` : ""}
                    </div>

                    <div style="display:flex;flex-direction:column;gap:8px;margin-top:10px;">
                        <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;">
                            <button type="button" data-action="open-customer-modal" style="justify-content:center;padding:10px 8px;font-size:12.5px;font-weight:700;background:#f8fafc;border:1px solid #cbd5e1;color:#1e293b;border-radius:7px;cursor:pointer;">
                                👤 ${this.escape((this.currentOrder.customer_name || "Cliente").slice(0, 16))}
                            </button>
                            <button type="button" data-action="pay-screen-fiscal-modal" style="justify-content:center;padding:10px 8px;font-size:12.5px;font-weight:700;background:${st.invoiceToggle ? "#f0f9ff" : "#f8fafc"};border:1px solid ${st.invoiceToggle ? "#38bdf8" : "#cbd5e1"};color:#1e293b;border-radius:7px;cursor:pointer;">
                                🧾 Recibo/Factura
                            </button>
                        </div>
                        ${cfg.tips_enabled !== 0 ? `
                            <button type="button" data-action="open-tip-modal" style="justify-content:center;padding:10px;font-size:13px;font-weight:700;background:#f8fafc;border:1px solid #cbd5e1;color:#1e293b;border-radius:7px;cursor:pointer;">
                                ♥ Propina ${Number(this.currentOrder.tip_amount) > 0 ? `(${this.formatMoney(this.currentOrder.tip_amount)})` : ""}
                            </button>
                        ` : ""}
                        ${(cfg.allow_global_discount !== 0 || cfg.enable_promotions_coupons || cfg.enable_gift_cards || cfg.enable_loyalty_program) ? `
                            <div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;">
                                ${cfg.allow_global_discount !== 0 ? `<button type="button" data-action="pay-screen-global-discount" style="padding:8px 6px;font-size:12px;font-weight:700;background:#f8fafc;border:1px solid #cbd5e1;color:#1e293b;border-radius:6px;cursor:pointer;">🏷 Desc. Global</button>` : ""}
                                ${cfg.enable_promotions_coupons ? `<button type="button" data-action="pay-screen-coupon" style="padding:8px 6px;font-size:12px;font-weight:700;background:#f8fafc;border:1px solid #cbd5e1;color:#1e293b;border-radius:6px;cursor:pointer;">🎟 Cupón</button>` : ""}
                                ${cfg.enable_gift_cards ? `<button type="button" data-action="pay-screen-gift-card" style="padding:8px 6px;font-size:12px;font-weight:700;background:#f8fafc;border:1px solid #cbd5e1;color:#1e293b;border-radius:6px;cursor:pointer;">🎁 Tarjeta Regalo</button>` : ""}
                                ${cfg.enable_loyalty_program ? `<button type="button" data-action="pay-screen-loyalty" style="padding:8px 6px;font-size:12px;font-weight:700;background:#f8fafc;border:1px solid #cbd5e1;color:#1e293b;border-radius:6px;cursor:pointer;">⭐ Puntos Lealtad</button>` : ""}
                            </div>
                        ` : ""}

                        <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:4px;">
                            ${["1", "2", "3"].map(k => `<button type="button" class="rpos-key" data-action="pay-screen-key" data-key="${k}" style="height:48px;">${k}</button>`).join("")}
                            <button type="button" class="rpos-key" data-action="pay-screen-add" data-add="10" style="height:48px;background:#bbf7d0;color:#14532d;font-weight:800;">+10</button>
                            ${["4", "5", "6"].map(k => `<button type="button" class="rpos-key" data-action="pay-screen-key" data-key="${k}" style="height:48px;">${k}</button>`).join("")}
                            <button type="button" class="rpos-key" data-action="pay-screen-add" data-add="20" style="height:48px;background:#bbf7d0;color:#14532d;font-weight:800;">+20</button>
                            ${["7", "8", "9"].map(k => `<button type="button" class="rpos-key" data-action="pay-screen-key" data-key="${k}" style="height:48px;">${k}</button>`).join("")}
                            <button type="button" class="rpos-key" data-action="pay-screen-add" data-add="50" style="height:48px;background:#bbf7d0;color:#14532d;font-weight:800;">+50</button>
                            <button type="button" class="rpos-key is-sign" data-action="pay-screen-key" data-key="+/-" style="height:48px;">+/-</button>
                            <button type="button" class="rpos-key" data-action="pay-screen-key" data-key="0" style="height:48px;">0</button>
                            <button type="button" class="rpos-key is-dot" data-action="pay-screen-key" data-key="." style="height:48px;">,</button>
                            <button type="button" class="rpos-key is-back" data-action="pay-screen-key" data-key="BACK" style="height:48px;">⌫</button>
                        </div>

                        <div style="display:grid;grid-template-columns:1fr 1.3fr;gap:8px;margin-top:4px;">
                            <button type="button" data-action="pay-screen-back" style="height:52px;justify-content:center;font-weight:700;font-size:14px;background:#f1f5f9;border:1px solid #cbd5e1;color:#1e293b;border-radius:7px;cursor:pointer;">
                                Regresar
                            </button>
                            <button type="button" class="rpos-btn-primary" data-action="pay-screen-validate" style="height:52px;justify-content:center;font-weight:700;font-size:14.5px;background:#2F8500;border-color:#236600;">
                                ${this.escape(st.selectedLabel || "Efectivo")}
                            </button>
                        </div>
                    </div>
                </div>

                <div style="display:flex;flex-direction:column;align-items:center;justify-content:center;padding:32px;">
                    <div style="font-size:96px;font-weight:800;line-height:1;color:#1e293b;letter-spacing:-2px;">
                        <span style="font-size:58px;color:#64748b;margin-right:6px;">L</span><span>${this.escape(intPart)}</span><span style="color:#64748b;">,${this.escape(decPart)}</span>
                    </div>
                </div>
            </div>
        `;
    }

    async handlePaymentScreenAction(action, el) {
        const st = this.paymentScreenState;
        if (!st) return;

        if (action === "pay-screen-back") {
            this.paymentScreenState = null;
            this.render();
            return;
        }
        if (action === "pay-screen-mop") {
            st.selectedMop = el.dataset.mop;
            st.selectedLabel = el.dataset.mopLabel;
            this.render();
            return;
        }
        if (action === "pay-screen-key") {
            const k = el.dataset.key;
            if (k === "BACK") {
                st.tenderedBuffer = st.tenderedBuffer.slice(0, -1);
            } else if (k === "+/-") {
                return;
            } else if (k === ".") {
                if (!st.tenderedBuffer.includes(".")) {
                    st.tenderedBuffer = (st.tenderedBuffer || "0") + ".";
                }
            } else {
                st.tenderedBuffer += k;
            }
            this.render();
            return;
        }
        if (action === "pay-screen-add") {
            const addVal = Number(el.dataset.add || 0);
            const curVal = st.tenderedBuffer ? Number(st.tenderedBuffer) : Number(this.currentOrder.grand_total || 0);
            st.tenderedBuffer = (curVal + addVal).toFixed(2);
            this.render();
            return;
        }
        if (action === "pay-screen-fiscal-modal") {
            return this.openFiscalPaymentModal();
        }
        if (action === "pay-screen-global-discount") {
            frappe.prompt([{ fieldname: "pct", fieldtype: "Float", label: "Descuento Global (%)", default: st.globalDiscountPct || 0 }], vals => {
                st.globalDiscountPct = Math.min(100, Math.max(0, Number(vals.pct || 0)));
                this.render();
            }, "Aplicar Descuento Global", "Aplicar");
            return;
        }
        if (action === "pay-screen-coupon") {
            frappe.prompt([{ fieldname: "code", fieldtype: "Data", label: "Código de Cupón", reqd: 1 }], async vals => {
                const res = await frappe.call({
                    method: "restaurant.pos.validate_coupon_code",
                    args: { coupon_code: vals.code, order_total: this.currentOrder.grand_total, customer: this.currentOrder.customer },
                });
                const info = res.message || {};
                st.couponCode = info.coupon_code;
                if (info.discount_percentage > 0) st.globalDiscountPct = info.discount_percentage;
                frappe.show_alert({ message: `Cupón ${info.coupon_code} aplicado`, indicator: "green" });
                this.render();
            }, "Validar Cupón / Promoción", "Aplicar");
            return;
        }
        if (action === "pay-screen-gift-card") {
            frappe.prompt([
                { fieldname: "code", fieldtype: "Data", label: "Código de Tarjeta de Regalo", reqd: 1 },
                { fieldname: "amount", fieldtype: "Currency", label: "Monto a redimir (L)", default: this.currentOrder.grand_total, reqd: 1 },
            ], async vals => {
                const res = await frappe.call({
                    method: "restaurant.pos.validate_gift_card",
                    args: { card_code: vals.code },
                });
                const gc = res.message || {};
                const redeem = Math.min(Number(vals.amount || 0), Number(gc.balance || 0), Number(this.currentOrder.grand_total || 0));
                st.giftCardCode = gc.card_code;
                st.giftCardAmount = redeem;
                frappe.show_alert({ message: `Tarjeta ${gc.card_code} validada (${this.formatMoney(redeem)})`, indicator: "green" });
                this.render();
            }, "Redimir Tarjeta de Regalo", "Validar");
            return;
        }
        if (action === "pay-screen-loyalty") {
            const res = await frappe.call({
                method: "restaurant.pos.get_customer_loyalty_points",
                args: { customer: this.currentOrder.customer, company: this.bootstrap?.company?.name },
            });
            const lp = res.message || {};
            if (!lp.loyalty_points) {
                frappe.msgprint(`El cliente actual no tiene puntos disponibles (${lp.loyalty_program || "Sin programa asignado"}).`);
                return;
            }
            frappe.prompt([{ fieldname: "pts", fieldtype: "Int", label: `Puntos a redimir (Disponibles: ${lp.loyalty_points})`, default: lp.loyalty_points }], vals => {
                st.loyaltyPoints = Math.min(lp.loyalty_points, Math.max(0, Number(vals.pts || 0)));
                frappe.show_alert({ message: `${st.loyaltyPoints} puntos aplicados`, indicator: "green" });
                this.render();
            }, "Programa de Lealtad", "Aplicar");
            return;
        }
        if (action === "pay-screen-validate") {
            this.recalculateLocalTotals();
            const grand = Number(this.currentOrder.grand_total || 0);
            const caiDefault = this.currentOrder.cai || this.bootstrap?.fiscal_defaults?.cai || "3A8F9E-12B4C6-78D0E2-9F1A3B-45C6D8-01";
            const dueCaiDefault = this.currentOrder.due_date_cai || this.bootstrap?.fiscal_defaults?.due_date_cai || "2026-12-31";
            const authRangeDefault = this.bootstrap?.fiscal_defaults?.authorized_range || "000-001-01-00000001 al 000-001-01-00050000";

            const res = await frappe.call({
                method: "restaurant.pos.pay_and_invoice_order",
                args: {
                    order_name: this.currentOrder.name,
                    customer: this.currentOrder.customer,
                    tax_id: this.currentOrder.tax_id || "",
                    cai: caiDefault,
                    due_date_cai: dueCaiDefault,
                    authorized_range: authRangeDefault,
                    tip_percentage: this.currentOrder.tip_percentage || 0,
                    tip_amount: this.currentOrder.tip_amount || 0,
                    global_discount_percentage: st.globalDiscountPct || 0,
                    coupon_code: st.couponCode || "",
                    gift_card_code: st.giftCardCode || "",
                    gift_card_amount: st.giftCardAmount || 0,
                    loyalty_points: st.loyaltyPoints || 0,
                    payments: [{ mode_of_payment: st.selectedMop || "Efectivo", amount: grand }],
                },
                freeze: true,
                freeze_message: "Emitiendo Factura Fiscal SAR y registrando pago...",
            });

            const invoice = res.message.invoice;
            const finishedOrder = res.message.order;
            this.bootstrap.areas = res.message.areas || this.bootstrap.areas;
            this.upsertOrderInBootstrap(finishedOrder);
            st.step = "done";
            st.invoice = invoice;
            st.finishedOrder = finishedOrder;
            this.render();
            return;
        }
        if (action === "pay-screen-print-invoice") {
            if (st.invoice && st.finishedOrder) {
                this.showInvoiceReceiptModal(st.invoice, st.finishedOrder);
            }
            return;
        }
        if (action === "pay-screen-email-receipt") {
            if (!st.invoice?.name) return;
            frappe.prompt([{ fieldname: "email", fieldtype: "Data", label: "Correo electrónico del cliente", reqd: 1 }], async vals => {
                await frappe.call({
                    method: "restaurant.pos.send_invoice_email",
                    args: { invoice_name: st.invoice.name, recipient_email: vals.email },
                    freeze: true,
                    freeze_message: "Enviando comprobante por correo...",
                });
                frappe.show_alert({ message: `Factura ${st.invoice.name} enviada a ${vals.email}`, indicator: "green" });
            }, "Enviar Factura por Correo", "Enviar");
            return;
        }
        if (action === "pay-screen-whatsapp-receipt") {
            if (!st.invoice?.name) return;
            frappe.prompt([{ fieldname: "phone", fieldtype: "Data", label: "Número WhatsApp (opcional con código de país)" }], async vals => {
                const res = await frappe.call({
                    method: "restaurant.pos.get_whatsapp_invoice_share_link",
                    args: { invoice_name: st.invoice.name, phone: vals.phone || "" },
                });
                if (res.message?.url) window.open(res.message.url, "_blank", "noopener");
            }, "Compartir Factura por WhatsApp", "Abrir WhatsApp");
            return;
        }
        if (action === "pay-screen-self-invoice") {
            if (!st.invoice?.name) return;
            const res = await frappe.call({
                method: "restaurant.pos.get_self_invoicing_receipt_data",
                args: { invoice_name: st.invoice.name },
            });
            const info = res.message || {};
            frappe.msgprint({
                title: `Autofacturación · ${info.invoice}`,
                indicator: "blue",
                message: `
                    <div><strong>Empresa:</strong> ${this.escape(info.company)}</div>
                    <div><strong>Cliente:</strong> ${this.escape(info.customer)} (RTN: ${this.escape(info.tax_id || "N/A")})</div>
                    <div><strong>CAI:</strong> ${this.escape(info.cai || "N/A")}</div>
                    <div><strong>Total:</strong> ${this.escape(info.currency)} ${Number(info.grand_total || 0).toFixed(2)}</div>
                    <div style="margin-top:8px;"><strong>URL Comprobante:</strong> <a href="${this.escape(info.portal_url)}" target="_blank">${this.escape(info.portal_url)}</a></div>
                `,
            });
            return;
        }
        if (action === "pay-screen-back-done" || action === "pay-screen-continue") {
            this.paymentScreenState = null;
            this.currentOrder = this.createBlankOrder();
            this.selectedLineIndex = -1;
            this.render();
        }
    }

    async openFiscalPaymentModal() {
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

                <div style="display:grid;grid-template-columns:${this.getRposConfig().tips_enabled !== 0 ? "1fr 1fr" : "1fr"};gap:12px;">
                    <div class="rpos-field">
                        <label>Método de pago</label>
                        <select data-pay-mop>
                            ${mops.map((m, idx) => `<option value="${this.escape(m.name)}" ${idx === 0 ? "selected" : ""}>${this.escape(m.name)}</option>`).join("")}
                        </select>
                    </div>
                    ${this.getRposConfig().tips_enabled !== 0 ? `
                        <div class="rpos-field">
                            <label>Servicio sugerido / Propina (L)</label>
                            <input type="number" step="0.01" min="0" data-pay-tip value="${Number(this.currentOrder.tip_amount || 0).toFixed(2)}">
                        </div>
                    ` : `<input type="hidden" data-pay-tip value="0">`}
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
            if (this.paymentScreenState) {
                this.paymentScreenState.step = "done";
                this.paymentScreenState.invoice = invoice;
                this.paymentScreenState.finishedOrder = finishedOrder;
                this.render();
            } else {
                this.currentOrder = this.createBlankOrder();
                this.selectedLineIndex = -1;
                this.render();
                this.showInvoiceReceiptModal(invoice, finishedOrder);
            }
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

    async clearCurrentOrderContents() {
        const hasItems = Boolean(this.currentOrder?.items?.length);
        const hasSavedName = Boolean(this.currentOrder?.name);
        const hasActiveItems = (this.currentOrder?.items || []).some(r => !r.is_cancelled && r.kds_status !== "Cancelado");
        if (!hasActiveItems && !hasSavedName) {
            this.currentOrder = this.createBlankOrder();
            this.selectedLineIndex = -1;
            this.numpadBuffer = "";
            this.render();
            frappe.show_alert({ message: "La orden ya está vacía", indicator: "blue" });
            return;
        }
        const hasSentItems = (this.currentOrder?.items || []).some(r => this.isSentToKitchenLine(r));
        if (hasSavedName && hasSentItems) {
            let payload = null;
            if (this.requiresSupervisorAuth()) {
                payload = await this.requestSupervisorAuthModal(
                    "Vaciar orden confirmada",
                    "restaurant.pos.clear_pos_order",
                    {
                        order_name: this.currentOrder.name,
                        expected_modified: this.currentOrder.modified || "",
                    },
                    {
                        orderLabel: this.currentOrder.order_name || this.currentOrder.name,
                        requireReason: true,
                    }
                );
                if (!payload) return;
            } else {
                const reason = await new Promise(resolve => {
                    frappe.prompt(
                        [{ fieldname: "reason", fieldtype: "Small Text", label: "Motivo para vaciar la orden", reqd: 1 }],
                        vals => resolve((vals.reason || "").trim()),
                        "Vaciar orden confirmada",
                        "Confirmar"
                    );
                });
                if (!reason) return;
                const res = await frappe.call({
                    method: "restaurant.pos.clear_pos_order",
                    type: "POST",
                    args: {
                        order_name: this.currentOrder.name,
                        reason,
                        expected_modified: this.currentOrder.modified || "",
                    },
                    freeze: true,
                    freeze_message: "Vaciando orden...",
                });
                payload = res.message;
            }
            if (payload?.order) {
                this.currentOrder = payload.order;
                this.upsertOrderInBootstrap(payload.order);
            }
            if (payload?.areas) {
                this.bootstrap.areas = payload.areas;
            }
        } else if (hasSavedName) {
            const res = await frappe.call({
                method: "restaurant.pos.clear_pos_order",
                type: "POST",
                args: {
                    order_name: this.currentOrder.name,
                    expected_modified: this.currentOrder.modified || "",
                },
                freeze: true,
                freeze_message: "Vaciando borrador...",
            });
            if (res.message?.order) {
                this.currentOrder = res.message.order;
                this.upsertOrderInBootstrap(res.message.order);
            }
            if (res.message?.areas) {
                this.bootstrap.areas = res.message.areas;
            }
        } else {
            this.currentOrder.items = [];
            this.currentOrder.tip_percentage = 0;
            this.currentOrder.tip_amount = 0;
        }
        this.selectedLineIndex = -1;
        this.numpadBuffer = "";
        this.recalculateLocalTotals();
        this.render();
        frappe.show_alert({
            message: "Contenido de la orden vaciado correctamente",
            indicator: "green",
        });
    }

    resetCajaForNextOrder() {
        this.currentOrder = this.createBlankOrder();
        this.selectedLineIndex = -1;
        this.numpadBuffer = "";
        this.selectedOrderPreviewName = "";
        this.render();
    }

    async sendToKdsOnly() {
        if (!this.currentOrder.items.length) {
            frappe.msgprint("Agrega platillos o bebidas antes de enviar al Monitor de Cocina (KDS).");
            return;
        }
        await this.persistCurrentOrderSilently();

        const hasPending = (this.currentOrder.items || []).some(row => (row.kds_status || "Pendiente") === "Pendiente");
        const res = await frappe.call({
            method: "restaurant.pos.send_order_to_kitchen",
            args: {
                order_name: this.currentOrder.name,
                station: "ALL",
                include_sent: hasPending ? 0 : 1,
            },
            freeze: true,
            freeze_message: "Enviando orden al Monitor de Cocina (KDS)...",
        });
        const sentOrder = res.message.order;
        if (res.message.areas) {
            this.bootstrap.areas = res.message.areas;
        }
        this.upsertOrderInBootstrap(sentOrder);
        this.resetCajaForNextOrder();
        frappe.show_alert({
            message: `Orden "${sentOrder.order_name}" enviada al Monitor de Cocina (KDS). Punto de venta listo para nuevo pedido.`,
            indicator: "green",
        });
    }

    async openCommandModal() {
        if (!this.currentOrder.items.length) {
            frappe.msgprint("Agrega platillos antes de comandar.");
            return;
        }
        await this.persistCurrentOrderSilently();

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
                    Selecciona la estación de impresión de comandas. Marca «Reimprimir» para enviar una copia de platillos ya comandados.
                </p>
                <div class="rpos-command-grid">
                    ${stations.map(st => tile(st, `Comandas ${st}`, pendingByStation[st] || 0)).join("")}
                    ${tile("ALL", "Comandar todo", pendingTotal)}
                </div>
                <label style="display:flex;align-items:center;gap:8px;margin-top:14px;font-size:12.5px;color:#334155;">
                    <input type="checkbox" data-cmd-reprint ${pendingTotal === 0 ? "checked" : ""}> Reimprimir también platillos ya comandados
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
                if (reprint && this.requiresSupervisorAuth() && this.currentOrder?.name) {
                    const auth = await this.requestSupervisorAuthModal(
                        "Reimprimir comandas",
                        "restaurant.pos.authorize_reprint_command",
                        { order_name: this.currentOrder.name }
                    );
                    if (!auth) return;
                }
                const res = await frappe.call({
                    method: "restaurant.pos.send_order_to_kitchen",
                    args: {
                        order_name: this.currentOrder.name,
                        station: btn.dataset.cmdStation,
                        include_sent: reprint ? 1 : 0,
                    },
                    freeze: true,
                    freeze_message: "Enviando comanda a impresora...",
                });
                backdrop.remove();
                const sentOrder = res.message.order;
                if (res.message.areas) {
                    this.bootstrap.areas = res.message.areas;
                }
                this.upsertOrderInBootstrap(sentOrder);
                this.printCommandTickets(res.message.stations || {}, res.message.sent_at, sentOrder);
                this.resetCajaForNextOrder();
                frappe.show_alert({
                    message: `Comanda "${sentOrder.order_name}" impresa (${Object.keys(res.message.stations || {}).join(", ")}). Punto de venta listo para nuevo pedido.`,
                    indicator: "green",
                });
            });
        });
    }

    async sendToKitchen() {
        return this.sendToKdsOnly();
    }

    printCommandTickets(stations, sentAt, orderOverride = null) {
        const order = orderOverride || this.currentOrder;
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
    async prepareOrderOperation() {
        if (this.currentOrder.status !== "En curso" || !this.currentOrder.items?.length) {
            frappe.msgprint("Selecciona una cuenta en curso con platillos.");
            return null;
        }
        const saved = await frappe.call({ method: "restaurant.pos.save_pos_order", type: "POST", args: { order: this.currentOrder }, freeze: true, freeze_message: "Guardando la cuenta…" });
        if (!saved.message?.order) return null;
        this.currentOrder = saved.message.order;
        this.upsertOrderInBootstrap(this.currentOrder);
        const result = await frappe.call({ method: "restaurant.pos.get_order_operation_context", args: { order_name: this.currentOrder.name } });
        this.operationContext = result.message;
        this.currentOrder = result.message.order;
        return this.operationContext;
    }

    async openSplitOrderModal() {
        if (this.operationBusy) return;
        if (this.currentOrder.status !== "En curso" || !this.currentOrder.items?.length) {
            frappe.msgprint("Selecciona una cuenta en curso con platillos.");
            return;
        }
        this.operationBusy = true;
        try {
            if (!this.currentOrder.name) {
                await this.persistCurrentOrderSilently();
            }
            this.operationContext = {
                order: this.currentOrder,
                can_split: true,
                can_transfer: true,
                tables: [],
                orders: []
            };
            this.splitSelection = new Map();
            this.splitAccountName = "";
            this.splitQuote = this.calculateLocalSplitQuote();
            this.splitQuoteError = false;
            this.operationMode = "split";
            this.activeTab = "Órdenes";
            this.render();
        } catch (error) {
            frappe.show_alert({ message: "No se pudo abrir la división. Actualiza la cuenta y vuelve a intentarlo.", indicator: "red" });
        } finally { this.operationBusy = false; }
    }

    calculateLocalSplitQuote() {
        const items = this.selectedSplitItems();
        const total = Number(this.operationContext?.order?.grand_total ?? this.currentOrder.grand_total ?? 0);
        if (!items.length) {
            return {
                selected_total: 0,
                original_total: total,
                remaining_total: total,
                selected_qty: 0,
                selected_lines: 0,
                can_split: false,
                all_selected: false,
                rounding_difference: 0
            };
        }
        let selected_total = 0;
        let selected_qty = 0;
        let all_selected = true;
        const orderItems = this.currentOrder.items || [];
        for (const row of orderItems) {
            const sel = this.splitSelection.get(row.name) || 0;
            selected_qty += sel;
            if (sel > 0) {
                const ratio = Number(row.qty) > 0 ? (sel / Number(row.qty)) : 0;
                selected_total += Number(row.amount || 0) * ratio;
            }
            if (sel < Number(row.qty)) {
                all_selected = false;
            }
        }
        selected_total = Math.round(selected_total * 100) / 100;
        const remaining_total = Math.max(0, Math.round((total - selected_total) * 100) / 100);
        return {
            selected_total,
            original_total: total,
            remaining_total,
            selected_qty,
            selected_lines: items.length,
            can_split: !all_selected && selected_qty > 0,
            all_selected,
            rounding_difference: 0
        };
    }

    closeSplitView(render = true) {
        this.operationMode = null;
        this.splitQuoteSequence++;
        clearTimeout(this.splitQuoteTimer);
        this.splitSelection = new Map();
        this.splitQuote = null;
        if (render) { this.activeTab = "Caja"; this.render(); }
    }

    selectedSplitItems() {
        return [...this.splitSelection].filter(([, qty]) => qty > 0).map(([item_name, qty]) => ({ item_name, qty }));
    }

    renderSplitView() {
        return `<section class="rpos-split-view" aria-label="Dividir la cuenta">
            <header class="rpos-split-header">
                <button type="button" class="rpos-btn-secondary" data-action="split-back">‹ Volver</button>
                <h2>Dividir la cuenta</h2><span></span>
            </header>
            <div class="rpos-split-columns">
                <div class="rpos-split-items">
                    ${(this.currentOrder.items || []).map(item => {
            const selected = this.splitSelection.get(item.name) || 0;
            return `<div class="rpos-split-item ${selected ? "is-selected" : ""}">
                            <button type="button" class="rpos-split-item-select" data-action="split-toggle" data-item-name="${this.escape(item.name)}" aria-pressed="${selected > 0}">
                                <span class="rpos-split-item-heading"><span><strong>${selected ? `${selected} / ` : ""}${this.escape(item.qty)}</strong> ${this.escape(item.item_name)}</span><strong>${this.formatMoney(item.amount)}</strong></span>
                                ${item.options_summary ? `<span class="rpos-split-item-option">${this.escape(item.options_summary)}</span>` : ""}
                                ${item.note ? `<span class="rpos-split-item-note">${this.escape(item.note)}</span>` : ""}
                            </button>
                        </div>`;
        }).join("")}
                </div>
                <aside class="rpos-split-panel">
                    <div class="rpos-split-summary">${this.renderSplitSummary()}</div>
                    <label class="rpos-split-account-name">Nombre de la nueva cuenta <input type="text" maxlength="140" value="${this.escape(this.splitAccountName)}" placeholder="Nombre de la persona o número de orden" data-split-account-name></label>
                    <div class="rpos-split-actions">${this.renderSplitActions()}</div>
                </aside>
            </div>
        </section>`;
    }

    renderSplitSummary() {
        const quote = this.splitQuote || this.calculateLocalSplitQuote();
        const total = Number(quote?.original_total ?? this.operationContext?.order?.grand_total ?? this.currentOrder.grand_total ?? 0);
        const selected = quote ? this.formatMoney(quote.selected_total) : this.formatMoney(0);
        return `<div class="rpos-split-amount" aria-live="polite">${this.escape(selected)}<small>/ ${this.formatMoney(total)}</small></div>
            <div class="rpos-split-count">${this.splitQuoteError ? 'No se pudo calcular la selección. <button type="button" class="rpos-split-retry" data-action="split-retry">Reintentar</button>' : `${Number(quote?.selected_qty || 0)} producto(s) seleccionado(s)`}</div>
            ${quote ? `<p class="rpos-split-remaining">Quedará en la cuenta original: ${this.formatMoney(quote.remaining_total)}</p>` : ""}
            ${quote && Number(quote.rounding_difference) ? `<p class="rpos-split-remaining">Diferencia por redondeo al separar: ${this.formatMoney(quote.rounding_difference)}</p>` : ""}`;
    }

    renderSplitActions() {
        const quote = this.splitQuote || this.calculateLocalSplitQuote();
        const ready = Boolean(quote && this.selectedSplitItems().length && !this.operationBusy);
        return `<button type="button" class="rpos-split-pay" data-action="split-pay" ${ready && (quote.can_split || quote.all_selected) ? "" : "disabled"}>Pago</button>
            <div class="rpos-split-secondary-actions">
                <button type="button" data-action="split-create" ${ready && quote.can_split ? "" : "disabled"}>Dividir orden</button>
                <button type="button" data-action="split-transfer" ${ready ? "" : "disabled"}>Transferir</button>
            </div>`;
    }

    bindSplitEvents() {
        this.shell.querySelectorAll("[data-split-quantity]").forEach(input => input.addEventListener("change", () => this.setSplitQuantity(input.dataset.splitQuantity, Number(input.value))));
        this.shell.querySelector("[data-split-account-name]")?.addEventListener("input", event => { this.splitAccountName = event.target.value; });
    }

    setSplitQuantity(itemName, quantity) {
        if (this.operationBusy) return;
        const item = this.currentOrder.items.find(row => row.name === itemName);
        if (!item || !Number.isFinite(quantity) || quantity < 0 || quantity > Number(item.qty)) {
            frappe.msgprint("La cantidad debe estar entre cero y la cantidad disponible del platillo.");
            this.render(); return;
        }
        if (quantity) this.splitSelection.set(itemName, quantity);
        else this.splitSelection.delete(itemName);
        this.splitQuote = this.calculateLocalSplitQuote();
        this.splitQuoteError = false;
        this.splitQuoteSequence++;
        this.render();
    }

    async refreshSplitQuote() {
        this.splitQuote = this.calculateLocalSplitQuote();
        this.splitQuoteError = false;
        if (this.operationMode === "split") this.render();
    }

    async performSplit(pay = false) {
        if (this.operationBusy || !this.selectedSplitItems().length) return;
        const quote = this.splitQuote || this.calculateLocalSplitQuote();
        if (quote.all_selected && pay) {
            this.closeSplitView();
            await this.openPaymentModal();
            return;
        }
        if (!quote.can_split) return;
        this.operationBusy = true;
        clearTimeout(this.splitQuoteTimer);
        this.render();
        try {
            const expected_modified = this.currentOrder.modified || this.operationContext?.order?.modified || null;
            const response = await frappe.call({
                method: "restaurant.pos.split_order", type: "POST", args: {
                    order_name: this.currentOrder.name, split_items: this.selectedSplitItems(),
                    new_order_name: this.splitAccountName.trim() || null, expected_modified: expected_modified,
                }, freeze: true, freeze_message: "Separando la cuenta…"
            });
            const payload = response.message;
            this.upsertOrderInBootstrap(payload.original_order);
            this.upsertOrderInBootstrap(payload.new_order);
            this.bootstrap.areas = payload.areas || this.bootstrap.areas;
            this.currentOrder = payload.new_order;
            this.closeSplitView(false);
            this.activeTab = "Caja";
            this.render();
            frappe.show_alert({ message: `Se creó la cuenta ${payload.new_order.order_name}.`, indicator: "green" });
            if (pay) await this.openPaymentModal();
        } catch (error) {
            frappe.show_alert({ message: "No se pudo dividir la cuenta. La selección se conserva para volver a intentarlo.", indicator: "red" });
        } finally { this.operationBusy = false; if (this.operationMode === "split") this.render(); }
    }

    async openTransferTableModal(selectedOnly = false) {
        if (this.operationBusy) return;
        if (selectedOnly && !this.selectedSplitItems().length) return;
        this.operationBusy = true;
        try {
            const res = await frappe.call({ method: "restaurant.pos.get_order_operation_context", args: { order_name: this.currentOrder.name } });
            this.operationContext = res.message;
            const context = this.operationContext;
            const rawTables = context.tables || [];
            // Filter only active tables in POS (active and not disabled)
            const activeTables = rawTables.filter(t => t.disabled !== 1 && t.active !== 0);
            // Filter only active orders in current session (status "En curso" and not current order)
            const activeOrders = (context.orders || []).filter(o => (!o.status || o.status === "En curso") && o.name !== context.order.name);
            const defaultNewName = `${context.order.order_name || "Cuenta"} (Nueva)`;

            const backdrop = this.createModal(
                "Transferir / Fusionar",
                `
                    <p class="rpos-transfer-description">${selectedOnly ? "Transfiere los platillos seleccionados" : "Transfiere la cuenta completa"} a una mesa activa, fusiónala con otra cuenta activa o crea una nueva cuenta independiente.</p>
                    <div class="rpos-transfer-tabs">
                        <button type="button" class="is-active" data-transfer-tab="tables">Mesas activas (${activeTables.length})</button>
                        <button type="button" data-transfer-tab="orders">Cuentas activas (${activeOrders.length})</button>
                        <button type="button" data-transfer-tab="new-account">+ Nueva cuenta / orden</button>
                    </div>
                    <div data-transfer-search-wrap>
                        <label class="rpos-field"><span>Buscar destino</span><input type="search" data-transfer-search placeholder="Mesa, área, nombre o número de orden"></label>
                    </div>
                    <div class="rpos-transfer-destinations" data-transfer-destinations></div>
                    <div class="rpos-transfer-new-account-wrap" data-transfer-new-wrap style="display:none;">
                        <div style="background:#f8fafc;border:1px solid #cbd5e1;border-radius:8px;padding:16px;">
                            <label class="rpos-field" style="margin-bottom:10px;">
                                <span style="font-weight:700;">Nombre de la nueva cuenta u orden *</span>
                                <input type="text" data-transfer-new-name placeholder="Ej: Barra 1, Cliente Juan, Cuenta 2..." value="${this.escape(defaultNewName)}" style="font-size:15px;padding:10px;">
                            </label>
                            <p class="text-muted" style="font-size:13px;margin:0;">
                                ${selectedOnly ? "Se creará una nueva cuenta activa independiente con los platillos seleccionados." : "Se creará una nueva orden activa independiente con toda la cuenta."}
                            </p>
                        </div>
                    </div>
                    <p class="rpos-transfer-selection" data-transfer-selection>Selecciona una mesa o cuenta activa.</p>
                `,
                `<button type="button" class="rpos-btn-secondary" data-modal-close>Volver</button><button type="button" class="rpos-btn-primary" data-transfer-confirm disabled>Transferir</button>`,
                "820px"
            );

            let activeTab = "tables";
            let chosen = null;

            const renderDestinations = () => {
                const searchWrap = backdrop.querySelector("[data-transfer-search-wrap]");
                const destinationsContainer = backdrop.querySelector("[data-transfer-destinations]");
                const newWrap = backdrop.querySelector("[data-transfer-new-wrap]");
                const confirmBtn = backdrop.querySelector("[data-transfer-confirm]");
                const selectionLabel = backdrop.querySelector("[data-transfer-selection]");

                if (activeTab === "new-account") {
                    searchWrap.style.display = "none";
                    destinationsContainer.style.display = "none";
                    newWrap.style.display = "block";
                    chosen = { type: "new-account" };
                    confirmBtn.disabled = false;
                    confirmBtn.textContent = selectedOnly ? "Separar en nueva cuenta" : "Transferir a nueva cuenta";
                    selectionLabel.textContent = "Destino: Nueva cuenta independiente";
                    return;
                }

                searchWrap.style.display = "block";
                destinationsContainer.style.display = "grid";
                newWrap.style.display = "none";

                const search = (backdrop.querySelector("[data-transfer-search]").value || "").trim().toLocaleLowerCase();
                let destinations = [];

                if (activeTab === "orders") {
                    destinations = activeOrders.map(order => ({
                        type: "order",
                        name: order.name,
                        title: order.order_name,
                        subtitle: `${order.table_label ? `Mesa ${order.table_label}` : "Sin mesa"} · ${this.formatMoney(order.grand_total || 0)}`,
                        badge: "Activa (En curso)",
                        modified: order.modified
                    }));
                } else {
                    destinations = activeTables.map(table => {
                        const tableOrders = (table.orders || []).filter(o => !o.status || o.status === "En curso");
                        const isCurrent = table.name === context.order.restaurant_table;
                        const occupied = tableOrders.length > 0;
                        const subtitle = occupied
                            ? `${table.area_name || "Área principal"} · Ocupada (${tableOrders.map(o => o.order_name).join(", ")})`
                            : `${table.area_name || "Área principal"} · Disponible`;
                        return {
                            type: occupied ? "order" : "table",
                            name: occupied ? tableOrders[0].name : table.name,
                            tableName: table.name,
                            title: `Mesa ${table.table_number}`,
                            subtitle,
                            badge: occupied ? "Activa" : "Disponible",
                            isOccupied: occupied,
                            isCurrent,
                            modified: occupied ? tableOrders[0].modified : null,
                            disabled: isCurrent && (!occupied || (tableOrders.length === 1 && tableOrders[0].name === context.order.name))
                        };
                    });
                }

                const shown = destinations.filter(d => `${d.title} ${d.subtitle}`.toLocaleLowerCase().includes(search));
                destinationsContainer.innerHTML = shown.map((d, index) => `
                    <button type="button" class="rpos-transfer-destination ${chosen?.type === d.type && chosen?.name === d.name ? "is-selected" : ""}" data-destination-index="${index}" ${d.disabled ? "disabled" : ""}>
                        <div style="display:flex;justify-content:space-between;align-items:center;">
                            <strong>${this.escape(d.title)}</strong>
                            <span class="rpos-table-status-pill ${d.badge.includes("Activa") || d.badge.includes("curso") ? "is-active" : "is-free"}">${d.badge}</span>
                        </div>
                        <span>${this.escape(d.subtitle)}${d.isCurrent ? " (Mesa actual)" : ""}</span>
                    </button>
                `).join("") || '<p class="rpos-transfer-empty" style="grid-column:span 2;padding:20px;text-align:center;color:#64748b;">No hay destinos activos con esta búsqueda.</p>';

                destinationsContainer.querySelectorAll("[data-destination-index]").forEach(button => button.addEventListener("click", () => {
                    chosen = shown[Number(button.dataset.destinationIndex)];
                    confirmBtn.disabled = false;
                    confirmBtn.textContent = chosen.type === "order" ? "Fusionar con cuenta" : "Transferir a mesa";
                    selectionLabel.textContent = `Destino: ${chosen.title}`;
                    renderDestinations();
                }));
            };

            backdrop.querySelectorAll("[data-transfer-tab]").forEach(button => button.addEventListener("click", () => {
                activeTab = button.dataset.transferTab;
                backdrop.querySelectorAll("[data-transfer-tab]").forEach(tab => tab.classList.toggle("is-active", tab === button));
                if (activeTab !== "new-account") chosen = null;
                renderDestinations();
            }));

            backdrop.querySelector("[data-transfer-search]").addEventListener("input", renderDestinations);

            backdrop.querySelector("[data-transfer-confirm]").addEventListener("click", async () => {
                if (!chosen || this.operationBusy) return;
                this.operationBusy = true;
                const confirmBtn = backdrop.querySelector("[data-transfer-confirm]");
                confirmBtn.disabled = true;

                try {
                    if (chosen.type === "new-account") {
                        const newName = (backdrop.querySelector("[data-transfer-new-name]").value || "").trim() || "Nueva cuenta";
                        if (selectedOnly) {
                            const response = await frappe.call({
                                method: "restaurant.pos.split_order",
                                type: "POST",
                                args: {
                                    order_name: context.order.name,
                                    split_items: this.selectedSplitItems(),
                                    new_order_name: newName,
                                    expected_modified: context.order.modified
                                },
                                freeze: true,
                                freeze_message: "Creando nueva cuenta…"
                            });
                            const payload = response.message;
                            backdrop.remove();
                            if (payload.original_order) this.upsertOrderInBootstrap(payload.original_order);
                            this.upsertOrderInBootstrap(payload.new_order);
                            this.currentOrder = payload.new_order;
                            this.closeSplitView(false);
                            this.activeTab = "Caja";
                            await this.loadBootstrap();
                            this.render();
                            frappe.show_alert({ message: `Se transfirieron los platillos a la nueva cuenta ${payload.new_order.order_name}.`, indicator: "green" });
                            return;
                        } else {
                            const response = await frappe.call({
                                method: "restaurant.pos.transfer_order_table",
                                type: "POST",
                                args: {
                                    order_name: context.order.name,
                                    new_order_name: newName,
                                    expected_modified: context.order.modified
                                },
                                freeze: true,
                                freeze_message: "Transfiriendo a nueva cuenta…"
                            });
                            const payload = response.message;
                            backdrop.remove();
                            this.upsertOrderInBootstrap(payload.order);
                            this.currentOrder = payload.order;
                            this.closeSplitView(false);
                            this.activeTab = "Caja";
                            await this.loadBootstrap();
                            this.render();
                            frappe.show_alert({ message: `La cuenta se transfirió como ${payload.order.order_name}.`, indicator: "green" });
                            return;
                        }
                    }

                    const args = { order_name: context.order.name, expected_modified: context.order.modified };
                    if (chosen.type === "table") args.target_table = chosen.name;
                    else {
                        args.target_order = chosen.name;
                        if (chosen.modified) args.target_modified = chosen.modified;
                    }
                    if (selectedOnly) {
                        args.split_items = this.selectedSplitItems();
                        if (this.splitAccountName.trim()) args.new_order_name = this.splitAccountName.trim();
                    }
                    const response = await frappe.call({
                        method: "restaurant.pos.transfer_order_table",
                        type: "POST",
                        args,
                        freeze: true,
                        freeze_message: "Transfiriendo la cuenta…"
                    });
                    const payload = response.message;
                    backdrop.remove();
                    if (payload.original_order) this.upsertOrderInBootstrap(payload.original_order);
                    this.upsertOrderInBootstrap(payload.order);
                    this.currentOrder = payload.order;
                    this.bootstrap.areas = payload.areas || this.bootstrap.areas;
                    this.closeSplitView(false);
                    this.activeTab = "Caja";
                    await this.loadBootstrap();
                    this.render();
                    frappe.show_alert({ message: payload.merged ? "Las cuentas se fusionaron correctamente." : "La cuenta se transfirió correctamente.", indicator: "green" });
                } catch (error) {
                    frappe.show_alert({ message: "No se pudo transferir. Revisa que las mesas o cuentas sigan activas y disponibles.", indicator: "red" });
                } finally {
                    this.operationBusy = false;
                    if (backdrop.isConnected) confirmBtn.disabled = false;
                }
            });

            renderDestinations();
        } catch (error) {
            frappe.show_alert({ message: "No se pudieron cargar los destinos. Actualiza la cuenta y vuelve a intentarlo.", indicator: "red" });
        } finally {
            this.operationBusy = false;
        }
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
        let payload = null;
        if (this.requiresSupervisorAuth()) {
            payload = await this.requestSupervisorAuthModal(
                "Cancelar orden completa / Anular cuenta",
                "restaurant.pos.cancel_pos_order",
                { order_name: orderName },
                { orderLabel: this.currentOrder?.name === orderName ? (this.currentOrder.order_name || orderName) : orderName, requireReason: true }
            );
            if (!payload) return;
        } else {
            const reason = await new Promise(resolve => {
                frappe.prompt(
                    [{ fieldname: "reason", fieldtype: "Small Text", label: "Motivo de cancelación", reqd: 1 }],
                    vals => resolve((vals.reason || "").trim()),
                    "Cancelar orden completa",
                    "Confirmar cancelación"
                );
            });
            if (!reason) return;
            const res = await frappe.call({
                method: "restaurant.pos.cancel_pos_order",
                type: "POST",
                args: { order_name: orderName, reason },
                freeze: true,
                freeze_message: "Cancelando orden...",
            });
            payload = res.message;
        }
        if (this.currentOrder.name === orderName) {
            this.currentOrder = this.createBlankOrder();
            this.selectedLineIndex = -1;
        }
        this.bootstrap.areas = payload.areas || this.bootstrap.areas;
        this.upsertOrderInBootstrap(payload.order);
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
            <div class="rpos-modal rpos-pos-menu-modal" style="max-width:760px;">
                <div class="rpos-modal-header rpos-pos-menu-header">
                    <span class="rpos-menu-status-pill" title="${shift ? `Turno activo: ${this.escape(shift.name)}` : "Sin turno activo"}">
                        <span class="rpos-menu-status-dot ${shift ? "is-online" : ""}"></span>
                        <span>${this.escape(shiftCode)}</span>
                    </span>
                    <button type="button" class="rpos-icon-btn" data-modal-close>×</button>
                </div>
                <div class="rpos-modal-body">
                    <div class="rpos-pos-menu-grid">
                        ${!this.getPermissions().is_waiter_only ? `
                        <button type="button" class="rpos-pos-menu-tile" data-menu-tile="customer-display">
                            <span class="rpos-pos-menu-icon" aria-hidden="true">
                                <svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                                    <rect x="2" y="3" width="20" height="14" rx="2"/>
                                    <line x1="8" y1="21" x2="16" y2="21"/>
                                    <line x1="12" y1="17" x2="12" y2="21"/>
                                </svg>
                            </span>
                            <span>Pantalla del cliente</span>
                        </button>
                        ` : ""}

                        <button type="button" class="rpos-pos-menu-tile" data-menu-tile="toggle-theme">
                            <span class="rpos-pos-menu-icon" aria-hidden="true">
                                <svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                                    <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>
                                </svg>
                            </span>
                            <span>${this.escape(themeLabel)}</span>
                        </button>

                        ${!this.getPermissions().is_waiter_only ? `
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

                        <button type="button" class="rpos-pos-menu-tile" data-menu-tile="cash-count">
                            <span class="rpos-pos-menu-icon" aria-hidden="true">
                                <svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                                    <rect x="4" y="2" width="16" height="20" rx="2"/>
                                    <line x1="8" y1="6" x2="16" y2="6"/>
                                    <line x1="8" y1="11" x2="10" y2="11"/>
                                    <line x1="12" y1="11" x2="16" y2="11"/>
                                    <line x1="8" y1="15" x2="10" y2="15"/>
                                    <line x1="12" y1="15" x2="16" y2="15"/>
                                    <line x1="8" y1="19" x2="16" y2="19"/>
                                </svg>
                            </span>
                            <span>Arqueo de caja</span>
                        </button>
                        ` : ""}

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

                        ${this.getPermissions().can_access_backend ? `
                        <button type="button" class="rpos-pos-menu-tile" data-menu-tile="backend">
                            <span class="rpos-pos-menu-icon" aria-hidden="true">
                                <svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                                    <polyline points="15 18 9 12 15 6"/>
                                </svg>
                            </span>
                            <span>Backend</span>
                        </button>
                        ` : ""}

                        ${!this.getPermissions().is_waiter_only ? `
                        <button type="button" class="rpos-pos-menu-tile is-danger" data-menu-tile="close-register">
                            <span class="rpos-pos-menu-icon" aria-hidden="true">
                                <svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                                    <path d="M21 2l-2 2m-7.61 7.61a5.5 5.5 0 1 1-7.778 7.778 5.5 5.5 0 0 1 7.777-7.777zm0 0L15.5 7.5m0 0l3 3L22 7l-3-3m-3.5 3.5L19 4"/>
                                </svg>
                            </span>
                            <span>Cerrar caja registradora</span>
                        </button>
                        ` : ""}
                    </div>
                </div>
            </div>
        `;

        backdrop.querySelectorAll("[data-modal-close]").forEach(btn => {
            btn.addEventListener("click", () => backdrop.remove());
        });
        document.body.appendChild(backdrop);

        backdrop.querySelectorAll("[data-menu-tile]").forEach(btn => {
            btn.addEventListener("click", async () => {
                const tile = btn.dataset.menuTile;
                backdrop.remove();
                if (tile === "customer-display") return this.openCustomerDisplayModal();
                if (tile === "toggle-theme") return this.toggleDarkMode();
                if (tile === "cash-movement") return this.openCashMovementModal();
                if (tile === "cash-count") return this.openCashCountModal("Arqueo de Cierre");
                if (tile === "reprint-commands") return this.openReprintCommandsModal();
                if (tile === "backend") {
                    frappe.set_route("Workspaces", "Restaurante");
                    return;
                }
                if (tile === "close-register") return this.openCloseRegisterModal();
            });
        });
    }

    getWallpaperSettings() {
        const bootstrapIdle = this.bootstrap?.idle_wallpaper || {};
        const rposCfg = this.bootstrap?.rpos_config || {};
        const defaults = {
            enabled: bootstrapIdle.enabled ?? true,
            idle_minutes: (bootstrapIdle.timeout_seconds || rposCfg.idle_wallpaper_timeout || 120) / 60,
            background_url: bootstrapIdle.background_url || rposCfg.idle_wallpaper_background_url || "/assets/restaurant/images/background-light.svg",
            logo_url: bootstrapIdle.logo_url || rposCfg.idle_wallpaper_logo_url || this.bootstrap?.company?.company_logo || "",
            show_clock: bootstrapIdle.show_clock !== undefined ? Boolean(bootstrapIdle.show_clock) : (rposCfg.idle_wallpaper_show_clock !== undefined ? Boolean(rposCfg.idle_wallpaper_show_clock) : true),
        };
        try {
            const raw = window.localStorage?.getItem("rpos_wallpaper_settings");
            if (raw) {
                const parsed = JSON.parse(raw);
                return Object.assign({}, defaults, parsed);
            }
        } catch (e) {
            // Use defaults on storage access restriction
        }
        return defaults;
    }

    openSettingsModal() {
        const settings = this.getWallpaperSettings();
        const companyName = this.bootstrap?.company?.name || "LEAF RESTAURANT";
        const defaultLogo = this.bootstrap?.company?.company_logo || "";

        const bodyHtml = `
            <div class="rpos-settings-container">
                <div class="rpos-settings-card">
                    <div class="rpos-settings-card-header">
                        <div class="rpos-settings-card-icon">
                            <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                                <rect x="3" y="3" width="18" height="18" rx="2" ry="2"/>
                                <circle cx="8.5" cy="8.5" r="1.5"/>
                                <polyline points="21 15 16 10 5 21"/>
                            </svg>
                        </div>
                        <div>
                            <h4 style="margin:0;font-size:16px;font-weight:700;color:#0f172a;">Wallpaper / Protector por Inactividad</h4>
                            <p style="margin:2px 0 0;font-size:12.5px;color:#64748b;">Configura el tiempo sin manipulación, la imagen de fondo y el logotipo corporativo centrado.</p>
                        </div>
                    </div>

                    <div class="rpos-settings-body" style="display:flex;flex-direction:column;gap:16px;margin-top:16px;">
                        <!-- Switch Activar -->
                        <div style="display:flex;align-items:center;justify-content:space-between;padding:12px 14px;background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;">
                            <div>
                                <label style="margin:0;font-weight:600;font-size:14px;color:#1e293b;cursor:pointer;" for="rpos-set-wp-enabled">Activar protector de pantalla por inactividad</label>
                                <div style="font-size:12px;color:#64748b;">Muestra el wallpaper cuando el POS no reciba manipulación del usuario.</div>
                            </div>
                            <input type="checkbox" id="rpos-set-wp-enabled" style="width:20px;height:20px;cursor:pointer;accent-color:#714b67;" ${settings.enabled ? "checked" : ""}>
                        </div>

                        <!-- Tiempo de inactividad -->
                        <div class="rpos-form-group">
                            <label style="display:block;font-size:13px;font-weight:600;color:#334155;margin-bottom:6px;">Tiempo de inactividad antes de activarse</label>
                            <div style="display:flex;align-items:center;gap:10px;">
                                <input type="number" id="rpos-set-wp-minutes" min="0.5" max="180" step="0.5" value="${settings.idle_minutes || 2}" style="width:100px;padding:8px 12px;border:1px solid #cbd5e1;border-radius:6px;font-size:14px;font-weight:700;color:#0f172a;">
                                <span style="font-size:13.5px;font-weight:500;color:#475569;">minuto(s) sin manipulación</span>
                            </div>
                            <div style="font-size:11.5px;color:#64748b;margin-top:4px;">Define cuánto tiempo puede estar el punto de venta sin tocarse (ej. 2 min = 120s).</div>
                        </div>

                        <!-- Imagen de Fondo -->
                        <div class="rpos-form-group">
                            <label style="display:block;font-size:13px;font-weight:600;color:#334155;margin-bottom:6px;">Imagen de Fondo del Wallpaper</label>
                            <div style="display:flex;gap:10px;align-items:center;">
                                <input type="text" id="rpos-set-wp-bg" value="${this.escape(settings.background_url || "/assets/restaurant/images/background-light.svg")}" placeholder="/assets/restaurant/images/background-light.svg" style="flex:1;padding:8px 12px;border:1px solid #cbd5e1;border-radius:6px;font-size:13px;">
                                <button type="button" class="rpos-btn-soft" data-action="upload-wp-bg" style="white-space:nowrap;display:inline-flex;align-items:center;gap:6px;font-size:13px;">
                                    <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
                                    Adjuntar imagen
                                </button>
                            </div>
                            <div style="font-size:11.5px;color:#64748b;margin-top:4px;">Ruta estática (ej. /assets/restaurant/images/background-light.svg) o haz clic en "Adjuntar imagen" para subir tu propio SVG o foto.</div>
                        </div>

                        <!-- Logotipo centrado -->
                        <div class="rpos-form-group">
                            <label style="display:block;font-size:13px;font-weight:600;color:#334155;margin-bottom:6px;">Logotipo de la Empresa (Centrado)</label>
                            <div style="display:flex;gap:10px;align-items:center;">
                                <input type="text" id="rpos-set-wp-logo" value="${this.escape(settings.logo_url || defaultLogo)}" placeholder="URL o archivo del logotipo corporativo" style="flex:1;padding:8px 12px;border:1px solid #cbd5e1;border-radius:6px;font-size:13px;">
                                <button type="button" class="rpos-btn-soft" data-action="upload-wp-logo" style="white-space:nowrap;display:inline-flex;align-items:center;gap:6px;font-size:13px;">
                                    <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
                                    Subir logo
                                </button>
                            </div>
                            <div style="font-size:11.5px;color:#64748b;margin-top:4px;">Este logotipo aparecerá centrado en la pantalla de wallpaper mientras el POS esté en reposo.</div>
                        </div>

                        <!-- Vista previa -->
                        <div class="rpos-form-group">
                            <label style="display:block;font-size:13px;font-weight:600;color:#334155;margin-bottom:6px;">Vista previa del Wallpaper</label>
                            <div id="rpos-wp-preview-box" style="height:160px;border-radius:8px;border:1px solid #cbd5e1;overflow:hidden;position:relative;display:flex;flex-direction:column;align-items:center;justify-content:center;background:#f1f5f9;background-size:cover;background-position:center;transition:background 0.2s ease;">
                                <img id="rpos-wp-preview-logo-img" src="" alt="Logo" style="max-width:180px;max-height:80px;object-fit:contain;filter:drop-shadow(0 4px 10px rgba(0,0,0,0.18));display:none;">
                                <div id="rpos-wp-preview-fallback-badge" style="display:flex;align-items:center;gap:8px;padding:8px 18px;background:rgba(255,255,255,0.9);border-radius:12px;box-shadow:0 4px 12px rgba(0,0,0,0.08);display:none;">
                                    <span class="rpos-brand-leaf" aria-hidden="true" style="display:inline-flex;width:24px;height:24px;">${this.brandLeafLogoHtml()}</span>
                                    <span style="font-weight:800;font-size:15px;color:#1e293b;">${this.escape(companyName)}</span>
                                </div>
                                <div style="position:absolute;bottom:8px;padding:3px 12px;background:rgba(255,255,255,0.85);backdrop-filter:blur(4px);border-radius:12px;font-size:11px;font-weight:600;color:#475569;">Vista previa en miniatura</div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        `;

        const footerHtml = `
            <div style="display:flex;align-items:center;justify-content:space-between;width:100%;gap:10px;flex-wrap:wrap;">
                <button type="button" class="rpos-btn-soft" data-action="test-wallpaper-now" style="display:inline-flex;align-items:center;gap:6px;">
                    <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><polygon points="10 8 16 12 10 16 10 8"/></svg>
                    Probar protector ahora
                </button>
                <div style="display:flex;align-items:center;gap:10px;">
                    <button type="button" class="rpos-btn-soft" data-modal-close>Descartar</button>
                    <button type="button" class="rpos-btn-primary" data-action="save-wallpaper-settings" style="background:#714b67;border-color:#714b67;">Guardar configuración</button>
                </div>
            </div>
        `;

        const backdrop = this.createModal("Configuraciones del Punto de Venta", bodyHtml, footerHtml, "740px");

        const updatePreview = () => {
            const bgVal = backdrop.querySelector("#rpos-set-wp-bg")?.value?.trim() || "";
            const logoVal = backdrop.querySelector("#rpos-set-wp-logo")?.value?.trim() || "";
            const previewBox = backdrop.querySelector("#rpos-wp-preview-box");
            const previewLogo = backdrop.querySelector("#rpos-wp-preview-logo-img");
            const fallbackBadge = backdrop.querySelector("#rpos-wp-preview-fallback-badge");

            if (previewBox) {
                if (bgVal) {
                    previewBox.style.backgroundImage = `url("${bgVal}")`;
                } else {
                    previewBox.style.backgroundImage = "none";
                    previewBox.style.backgroundColor = "#f1f5f9";
                }
            }

            if (logoVal) {
                if (previewLogo) {
                    previewLogo.src = logoVal;
                    previewLogo.style.display = "block";
                }
                if (fallbackBadge) fallbackBadge.style.display = "none";
            } else {
                if (previewLogo) previewLogo.style.display = "none";
                if (fallbackBadge) fallbackBadge.style.display = "flex";
            }
        };

        updatePreview();

        backdrop.querySelector("#rpos-set-wp-bg")?.addEventListener("input", updatePreview);
        backdrop.querySelector("#rpos-set-wp-logo")?.addEventListener("input", updatePreview);

        // Upload background image via native Frappe FileUploader
        backdrop.querySelector('[data-action="upload-wp-bg"]')?.addEventListener("click", () => {
            new frappe.ui.FileUploader({
                make_attachments_public: 1,
                on_success: (file_doc) => {
                    if (file_doc && file_doc.file_url) {
                        const bgInput = backdrop.querySelector("#rpos-set-wp-bg");
                        if (bgInput) {
                            bgInput.value = file_doc.file_url;
                            updatePreview();
                        }
                    }
                }
            });
        });

        // Upload logo image via native Frappe FileUploader
        backdrop.querySelector('[data-action="upload-wp-logo"]')?.addEventListener("click", () => {
            new frappe.ui.FileUploader({
                make_attachments_public: 1,
                on_success: (file_doc) => {
                    if (file_doc && file_doc.file_url) {
                        const logoInput = backdrop.querySelector("#rpos-set-wp-logo");
                        if (logoInput) {
                            logoInput.value = file_doc.file_url;
                            updatePreview();
                        }
                    }
                }
            });
        });

        // Test screensaver now
        backdrop.querySelector('[data-action="test-wallpaper-now"]')?.addEventListener("click", () => {
            const tempSettings = {
                enabled: true,
                idle_minutes: Number(backdrop.querySelector("#rpos-set-wp-minutes")?.value || 2),
                background_url: backdrop.querySelector("#rpos-set-wp-bg")?.value?.trim() || "/assets/restaurant/images/background-light.svg",
                logo_url: backdrop.querySelector("#rpos-set-wp-logo")?.value?.trim() || "",
            };
            this.showIdleWallpaper(tempSettings);
        });

        // Save settings
        backdrop.querySelector('[data-action="save-wallpaper-settings"]')?.addEventListener("click", () => {
            const newSettings = {
                enabled: Boolean(backdrop.querySelector("#rpos-set-wp-enabled")?.checked),
                idle_minutes: Math.max(0.1, Number(backdrop.querySelector("#rpos-set-wp-minutes")?.value || 2)),
                background_url: backdrop.querySelector("#rpos-set-wp-bg")?.value?.trim() || "/assets/restaurant/images/background-light.svg",
                logo_url: backdrop.querySelector("#rpos-set-wp-logo")?.value?.trim() || "",
            };
            try {
                window.localStorage?.setItem("rpos_wallpaper_settings", JSON.stringify(newSettings));
            } catch (e) {
                // Ignore storage limits
            }
            this.resetIdleTimer();
            backdrop.remove();
            frappe.show_alert({
                message: "Configuración de wallpaper guardada exitosamente",
                indicator: "green",
            }, 4);
        });
    }

    setupIdleWallpaperManager() {
        if (this._idleEventsBound) {
            this.resetIdleTimer();
            return;
        }
        this._idleEventsBound = true;

        const onUserActivity = () => {
            if (document.getElementById("rpos-idle-screensaver")) {
                this.dismissIdleWallpaper();
            }
            this.resetIdleTimer();
        };

        const activityEvents = ["mousemove", "mousedown", "keydown", "touchstart", "scroll", "pointerdown"];
        activityEvents.forEach(evt => {
            window.addEventListener(evt, onUserActivity, { passive: true });
        });

        this.resetIdleTimer();
    }

    resetIdleTimer() {
        if (this._idleTimer) {
            clearTimeout(this._idleTimer);
            this._idleTimer = null;
        }
        const settings = this.getWallpaperSettings();
        if (!settings.enabled) return;

        const minutes = Number(settings.idle_minutes || 0);
        if (minutes <= 0) return;

        const ms = Math.max(5000, minutes * 60 * 1000);
        this._idleTimer = setTimeout(() => {
            if (frappe.get_route()?.[0] === "restaurant-pos") {
                this.showIdleWallpaper();
            }
        }, ms);
    }

    formatIdleClock(date = new Date()) {
        const pad = (n) => String(n).padStart(2, "0");
        const hh = pad(date.getHours());
        const mm = pad(date.getMinutes());
        const ss = pad(date.getSeconds());

        const days = ["domingo", "lunes", "martes", "miércoles", "jueves", "viernes", "sábado"];
        const months = [
            "enero", "febrero", "marzo", "abril", "mayo", "junio",
            "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"
        ];

        return {
            time: `${hh}:${mm}:${ss}`,
            day: days[date.getDay()],
            date: `${date.getDate()}, ${months[date.getMonth()]}, ${date.getFullYear()}`,
        };
    }

    startIdleClock() {
        this.stopIdleClock();
        const update = () => {
            const timeEl = document.getElementById("rpos-idle-live-time");
            const dayEl = document.getElementById("rpos-idle-live-day");
            const dateEl = document.getElementById("rpos-idle-live-date");
            if (!timeEl) return;
            const info = this.formatIdleClock();
            timeEl.textContent = info.time;
            if (dayEl) dayEl.textContent = info.day;
            if (dateEl) dateEl.textContent = info.date;
        };
        update();
        this._idleClockTimer = setInterval(update, 1000);
    }

    stopIdleClock() {
        if (this._idleClockTimer) {
            clearInterval(this._idleClockTimer);
            this._idleClockTimer = null;
        }
    }

    showIdleWallpaper(overrideSettings = null) {
        const existing = document.getElementById("rpos-idle-screensaver");
        if (existing) return;

        const settings = overrideSettings || this.getWallpaperSettings();
        const bgUrl = settings.background_url || "/assets/restaurant/images/background-light.svg";
        const logoUrl = settings.logo_url || "";
        const showClock = settings.show_clock !== false;
        const companyName = this.bootstrap?.company?.name || "LEAF RESTAURANT";

        const screensaver = document.createElement("div");
        screensaver.id = "rpos-idle-screensaver";
        screensaver.className = "rpos-idle-screensaver";
        screensaver.innerHTML = `
            <div class="rpos-idle-inner">
                ${showClock ? `
                    <div class="rpos-idle-top">
                        <div class="rpos-idle-clock-box">
                            <span class="rpos-idle-time" id="rpos-idle-live-time"></span>
                            <div class="rpos-idle-date-box">
                                <div class="rpos-idle-day" id="rpos-idle-live-day"></div>
                                <div class="rpos-idle-date" id="rpos-idle-live-date"></div>
                            </div>
                        </div>
                    </div>
                ` : `<div class="rpos-idle-top"></div>`}
                <div class="rpos-idle-center">
                    ${logoUrl ? `
                        <img src="${this.escape(logoUrl)}" class="rpos-idle-logo" alt="Logo corporativo">
                    ` : `
                        <div class="rpos-idle-badge">
                            <span class="rpos-brand-leaf" aria-hidden="true">${this.brandLeafLogoHtml()}</span>
                            <h1 class="rpos-idle-brand-title">${this.escape(companyName)}</h1>
                        </div>
                    `}
                </div>
                <div class="rpos-idle-footer">
                    <div class="rpos-idle-prompt">
                        <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83"/></svg>
                        <span>Toque o presione cualquier tecla para continuar</span>
                    </div>
                </div>
            </div>
        `;

        if (bgUrl) {
            screensaver.style.backgroundImage = `url("${bgUrl}")`;
            screensaver.style.backgroundSize = "cover";
            screensaver.style.backgroundPosition = "center";
            screensaver.style.backgroundRepeat = "no-repeat";
        }

        const dismiss = (e) => {
            if (e) {
                e.preventDefault();
                e.stopPropagation();
            }
            this.dismissIdleWallpaper();
        };

        screensaver.addEventListener("click", dismiss);
        screensaver.addEventListener("touchstart", dismiss, { passive: false });

        document.body.appendChild(screensaver);
        if (showClock) {
            this.startIdleClock();
        }
    }

    dismissIdleWallpaper() {
        this.stopIdleClock();
        const screensaver = document.getElementById("rpos-idle-screensaver");
        if (screensaver) {
            screensaver.classList.add("is-fading-out");
            setTimeout(() => screensaver.remove(), 250);
        }
        this.resetIdleTimer();
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

    buildCustomerDisplayHtml() {
        this.recalculateLocalTotals();
        const ord = this.currentOrder;
        const catalogMap = new Map((this.bootstrap?.items || []).map(i => [i.item_code, i]));

        return `
            <div id="rpos-customer-display-box" style="display:grid;grid-template-columns:1fr 1fr;min-height:460px;height:100%;background:#f1f5f9;border-radius:10px;overflow:hidden;border:1px solid #cbd5e1;font-family:sans-serif;">
                <div style="background:#ffffff;display:flex;flex-direction:column;align-items:center;justify-content:center;position:relative;padding:32px;border-right:1px solid #e2e8f0;">
                    <div style="width:96px;height:96px;border-radius:50%;border:6px solid #cbd5e1;display:flex;align-items:center;justify-content:center;font-size:34px;font-weight:900;color:#64748b;margin-bottom:14px;">
                        L
                    </div>
                    <div style="font-size:20px;font-weight:800;color:#334155;letter-spacing:0.5px;">${this.escape(this.bootstrap?.company?.name || "LEAF RESTAURANT")}</div>
                    <div style="position:absolute;bottom:18px;background:#f8fafc;border:1px solid #e2e8f0;border-radius:6px;padding:6px 14px;font-size:12px;color:#64748b;">
                        Con la tecnología de <strong style="color:#2F8500;">LEAF ERP</strong>
                    </div>
                </div>
                <div style="display:flex;flex-direction:column;justify-content:space-between;padding:18px;background:#f8fafc;">
                    <div style="flex:1;overflow-y:auto;display:flex;flex-direction:column;gap:8px;padding-bottom:12px;">
                        ${(ord.items || []).length ? ord.items.map(it => {
            const catItem = catalogMap.get(it.item_code);
            const img = catItem?.image || "";
            return `
                                <div style="background:#ffffff;border:1px solid #e2e8f0;border-radius:8px;padding:10px 12px;display:flex;align-items:center;justify-content:space-between;gap:12px;">
                                    <div style="display:flex;align-items:center;gap:10px;">
                                        ${img ? `<img src="${this.escape(img)}" alt="" style="width:42px;height:42px;object-fit:cover;border-radius:6px;">` : `<div style="width:42px;height:42px;border-radius:6px;background:#e2e8f0;display:flex;align-items:center;justify-content:center;font-weight:800;color:#475569;">${this.escape((it.item_name || "P").slice(0, 2).toUpperCase())}</div>`}
                                        <div>
                                            <div style="font-weight:700;font-size:14px;color:#0f172a;">${this.escape(it.item_name)}</div>
                                            <div style="font-size:12px;color:#64748b;">${it.qty} x ${this.formatMoney(it.rate)} / ${this.escape(it.uom || "Unidades")}</div>
                                            ${it.options_summary ? `<div style="font-size:11.5px;color:#475569;font-style:italic;">- ${this.escape(it.options_summary)}</div>` : ""}
                                        </div>
                                    </div>
                                    <div style="font-weight:800;font-size:14.5px;color:#0f172a;white-space:nowrap;">${this.formatMoney(it.amount)}</div>
                                </div>
                            `;
        }).join("") : `
                            <div style="flex:1;display:flex;align-items:center;justify-content:center;color:#94a3b8;font-size:14px;text-align:center;">
                                Bienvenido. Sus productos aparecerán aquí en tiempo real.
                            </div>
                        `}
                    </div>
                    <div style="border-top:1px solid #cbd5e1;padding-top:12px;">
                        <div style="display:flex;justify-content:space-between;font-size:13.5px;color:#64748b;margin-bottom:4px;">
                            <span>Subtotal</span>
                            <span>${this.formatMoney(ord.subtotal)}</span>
                        </div>
                        <div style="display:flex;justify-content:space-between;font-size:13.5px;color:#64748b;margin-bottom:8px;">
                            <span>Impuestos</span>
                            <span>${this.formatMoney(ord.tax_amount)}</span>
                        </div>
                        <div style="display:flex;justify-content:space-between;font-size:28px;font-weight:800;color:#0f172a;">
                            <span>Total</span>
                            <span>${this.formatMoney(ord.grand_total)}</span>
                        </div>
                    </div>
                </div>
            </div>
        `;
    }

    syncCustomerDisplayLive() {
        try {
            if (this.customerDisplayWindow && !this.customerDisplayWindow.closed) {
                const container = this.customerDisplayWindow.document.getElementById("leaf-live-cust-root");
                if (container) {
                    container.innerHTML = this.buildCustomerDisplayHtml();
                }
            }
        } catch (e) {
            // Ignore cross-window errors
        }
    }

    openCustomerDisplayModal() {
        const companyName = this.bootstrap?.company?.name || "LEAF RESTAURANT";
        const backdrop = this.createModal(
            `Pantalla del cliente · ${this.escape(companyName)}`,
            this.buildCustomerDisplayHtml(),
            `
                <button type="button" class="rpos-btn-secondary" data-modal-close>Cerrar vista previa</button>
                <button type="button" class="rpos-btn-primary" data-cust-disp-popup style="background:#714b67;border-color:#714b67;">Abrir en pantalla secundaria en vivo</button>
            `,
            "920px"
        );

        backdrop.querySelector("[data-cust-disp-popup]").addEventListener("click", () => {
            const win = window.open("", "LeafCustomerDisplay", "width=1024,height=680");
            if (win) {
                this.customerDisplayWindow = win;
                win.document.write(`<!DOCTYPE html><html><head><meta charset="utf-8"><title>Pantalla del cliente - ${this.escape(companyName)}</title></head><body style="margin:0;height:100vh;background:#f1f5f9;"><div id="leaf-live-cust-root" style="height:100vh;">${this.buildCustomerDisplayHtml()}</div></body></html>`);
                win.document.close();
                backdrop.remove();
            }
        });
    }

    openPosaPrintView(doctype, docname, printFormat, letterHead) {
        if (!docname || !printFormat) return;
        const baseUrl = frappe.urllib.get_base_url();
        const url = `${baseUrl}/printview?doctype=${encodeURIComponent(doctype)}&name=${encodeURIComponent(docname)}&trigger_print=1&format=${encodeURIComponent(printFormat)}&no_letterhead=${encodeURIComponent(letterHead || 0)}`;
        const printWindow = window.open(url, "Print");
        if (printWindow) {
            printWindow.addEventListener("load", () => {
                printWindow.print();
            }, true);
        }
    }

    getActivePosProfileObj() {
        const profName = this.bootstrap?.opening_shift?.pos_profile;
        return (this.bootstrap?.pos_profiles || []).find(p => p.name === profName) || this.bootstrap?.pos_profiles?.[0] || {};
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
            `<span class="rpos-posa-title">Crear Ingreso/Retiro de efectivo</span>`,
            `
                <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">
                    <div class="rpos-field">
                        <label>Tipo *</label>
                        <select data-cm-type>
                            <option value="Retiro">Retiro</option>
                            <option value="Ingreso">Ingreso</option>
                        </select>
                    </div>
                    <div class="rpos-field">
                        <label>Monto *</label>
                        <input type="number" step="any" min="0.01" data-cm-amount placeholder="0.00">
                    </div>
                </div>
                <div class="rpos-field">
                    <label>Nota *</label>
                    <input type="text" data-cm-note placeholder="Ej. Cambio sencillo para caja, pago proveedor menor, retiro parcial...">
                </div>

                ${(data.movements || []).length ? `
                    <div style="margin-top:10px;">
                        <div style="font-size:12px;font-weight:700;color:#475569;margin-bottom:4px;">
                            Movimientos del turno (${this.escape(shift.name)}) · Neto: ${this.formatMoney(data.net_cash_movement)}
                        </div>
                        <div style="max-height:140px;overflow-y:auto;border:1px solid #e2e8f0;border-radius:6px;" data-cm-list>
                            ${data.movements.map(m => `
                                <div style="display:flex;justify-content:space-between;align-items:center;padding:7px 10px;border-bottom:1px solid #f1f5f9;font-size:12px;">
                                    <div>
                                        <span style="font-weight:700;color:${m.type_transaction === "Ingreso" ? "#16a34a" : "#dc2626"};">${this.escape(m.type_transaction)}</span>
                                        <span> · ${this.escape(m.note)}</span>
                                    </div>
                                    <strong style="color:${m.type_transaction === "Ingreso" ? "#16a34a" : "#dc2626"};">
                                        ${m.type_transaction === "Ingreso" ? "+" : "-"} ${this.formatMoney(m.amount)}
                                    </strong>
                                </div>
                            `).join("")}
                        </div>
                    </div>
                ` : ""}
            `,
            `
                <button type="button" class="rpos-posa-btn-error" data-modal-close>Cerrar</button>
                <button type="button" class="rpos-posa-btn-success" data-cm-submit>Enviar</button>
            `,
            "600px"
        );

        backdrop.querySelector("[data-cm-submit]").addEventListener("click", async () => {
            const txType = backdrop.querySelector("[data-cm-type]").value;
            const amount = Number(backdrop.querySelector("[data-cm-amount]").value || 0);
            const note = backdrop.querySelector("[data-cm-note]").value.trim();
            if (!txType) {
                frappe.msgprint("Tipo de transacción es requerido.");
                return;
            }
            if (amount <= 0) {
                frappe.msgprint("Monto es requerido.");
                return;
            }
            if (!note) {
                frappe.msgprint("Nota es requerido.");
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
            const createdName = saveRes.message?.created?.name || "";
            backdrop.remove();
            frappe.show_alert({
                message: `Creado exitosamente (${createdName || txType})`,
                indicator: "green",
            });
            const prof = this.getActivePosProfileObj();
            const fmt = prof.print_format_for_online || prof.cash_movements_format;
            if (createdName && fmt) {
                this.openPosaPrintView("Retiro de efectivo", createdName, fmt, prof.letter_head);
            }
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
                if (this.requiresSupervisorAuth()) {
                    const auth = await this.requestSupervisorAuthModal(
                        "Reimprimir comandas",
                        "restaurant.pos.authorize_reprint_command",
                        { order_name: orderName }
                    );
                    if (!auth) return;
                }
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
        const hideExpected = Boolean(preview.hide_expected_amount);
        const movements = preview.cash_movements?.movements || [];

        const isCashRow = (r) => {
            if (r.is_cash !== undefined) return Boolean(Number(r.is_cash));
            const low = String(r.mode_of_payment || "").toLowerCase();
            return low.includes("efectivo") || low.includes("cash");
        };

        // Replicate Odoo: only display payment methods used in opening, sales, or cash movements.
        const activeRows = rows.filter(r =>
            isCashRow(r)
            || Math.abs(Number(r.opening_amount || 0)) > 0.005
            || Math.abs(Number(r.sales_amount || 0)) > 0.005
            || Math.abs(Number(r.expected_amount || 0)) > 0.005
            || Math.abs(Number(r.cash_movement_net || 0)) > 0.005
        );
        const displayRows = activeRows.length ? activeRows : rows.slice(0, 1);

        const formatSignedMoney = (val) => {
            const num = Number(val || 0);
            const sign = num > 0.005 ? "+ " : num < -0.005 ? "- " : "+ ";
            return `${sign}${this.formatMoney(Math.abs(num))}`;
        };

        const renderMethodBlock = (r) => {
            const mopEsc = this.escape(r.mode_of_payment);
            const isCash = isCashRow(r);
            const expectedVal = Number(r.expected_amount || 0);
            const closingVal = Number(r.closing_amount ?? expectedVal);

            return `
                <div class="rpos-odoo-method">
                    <div class="rpos-odoo-method-head">
                        <span class="rpos-odoo-method-name">${mopEsc}</span>
                        ${hideExpected ? "" : `<span class="rpos-odoo-method-exp">${this.formatMoney(expectedVal)}</span>`}
                    </div>
                    <div class="rpos-odoo-tree">
                        ${isCash ? `
                            <div class="rpos-odoo-line">
                                <span>Apertura</span>
                                <span>${this.formatMoney(r.opening_amount || 0)}</span>
                            </div>
                            <div class="rpos-odoo-line">
                                <span>Pagos en Efectivo</span>
                                <span>${this.formatMoney(r.sales_amount || 0)}</span>
                            </div>
                            <div class="rpos-odoo-line is-toggle" data-odoo-mv-toggle>
                                <span><span class="rpos-odoo-caret" data-odoo-caret>&#9656;</span> Entrada y salida de efectivo</span>
                                <span>${formatSignedMoney(r.cash_movement_net || 0)}</span>
                            </div>
                            <div class="rpos-odoo-mv-sublist" data-odoo-mv-list hidden>
                                ${movements.length ? movements.map(mv => `
                                    <div class="rpos-odoo-mv-subrow">
                                        <span>${this.escape(mv.type_transaction)}: ${this.escape(mv.note || "Sin motivo")}</span>
                                        <span>${mv.type_transaction === "Ingreso" ? "+" : "-"}${this.formatMoney(mv.amount || 0)}</span>
                                    </div>
                                `).join("") : `<div class="rpos-odoo-mv-empty">Sin movimientos en este turno</div>`}
                            </div>
                        ` : ""}
                        <div class="rpos-odoo-line">
                            <span>Contado</span>
                            <span data-odoo-counted="${mopEsc}">${this.formatMoney(closingVal)}</span>
                        </div>
                        ${hideExpected ? "" : `
                            <div class="rpos-odoo-line is-diff" data-odoo-diff-row="${mopEsc}">
                                <span>Diferencia</span>
                                <span data-odoo-diff="${mopEsc}">${this.formatMoney(closingVal - expectedVal)}</span>
                            </div>
                        `}
                    </div>
                </div>
            `;
        };

        const renderInputField = (r) => {
            const mopEsc = this.escape(r.mode_of_payment);
            const isCash = isCashRow(r);
            const expectedVal = Number(r.expected_amount || 0);
            const closingVal = Number(r.closing_amount ?? expectedVal);
            return `
                <div class="rpos-odoo-input-col">
                    <label class="rpos-odoo-input-lbl">${isCash ? "Conteo de efectivo" : mopEsc}</label>
                    <div class="rpos-odoo-input-row">
                        <div class="rpos-odoo-input-box">
                            <input type="number" step="0.01" min="0"
                                data-close-mop="${mopEsc}"
                                data-expected="${expectedVal}"
                                value="${closingVal.toFixed(2)}">
                            <button type="button" class="rpos-odoo-clear-btn" data-close-clear="${mopEsc}" title="Limpiar monto">&times;</button>
                        </div>
                        ${isCash ? `
                            <button type="button" class="rpos-odoo-denom-btn" data-open-arqueo title="Abrir Arqueo por Denominación">
                                &#128181;
                            </button>
                        ` : ""}
                    </div>
                </div>
            `;
        };

        const orderCount = Number(preview.invoice_count || 0);
        const orderLabel = orderCount === 1 ? "1 orden" : `${orderCount} órdenes`;
        const backdrop = this.createModal(
            `<div class="rpos-odoo-modal-title">
                <span>Cierre de caja registradora</span>
                <span class="rpos-odoo-orders-summary">${orderLabel}: ${this.formatMoney(preview.total_sales || 0)}</span>
            </div>`,
            `
                <div class="rpos-odoo-body" data-odoo-body>
                    <div class="rpos-odoo-methods">
                        ${displayRows.map(renderMethodBlock).join("")}
                    </div>
                    <hr class="rpos-odoo-divider">
                    <div class="rpos-odoo-inputs-grid">
                        ${displayRows.map(renderInputField).join("")}
                    </div>
                    <div class="rpos-odoo-note-wrap">
                        <label class="rpos-odoo-input-lbl">Nota de cierre</label>
                        <textarea class="rpos-input rpos-odoo-note" rows="2" data-close-note placeholder="Agregar una nota de cierre..."></textarea>
                    </div>
                    <div class="rpos-odoo-warn-overlay" data-odoo-warn hidden>
                        <div class="rpos-odoo-warn-card">
                            <div class="rpos-odoo-warn-head">
                                <h4>Diferencia de pagos</h4>
                                <button type="button" class="rpos-odoo-warn-x" data-diff-cancel>&times;</button>
                            </div>
                            <p class="rpos-odoo-warn-msg">
                                El dinero contado no coincide con el esperado. ¿Desea registrar esta diferencia en los libros?
                            </p>
                            <div class="rpos-odoo-warn-summary" data-odoo-warn-summary></div>
                            <div class="rpos-odoo-warn-actions">
                                <button type="button" class="rpos-btn rpos-btn-primary" data-diff-continue>Continuar de todos modos</button>
                                <button type="button" class="rpos-btn rpos-btn-soft" data-diff-cancel>Descartar</button>
                            </div>
                        </div>
                    </div>
                </div>
            `,
            `
                <div class="rpos-odoo-footer">
                    <div class="rpos-odoo-footer-left">
                        <button type="button" class="rpos-btn rpos-btn-primary" data-close-confirm>Cerrar caja registradora</button>
                        <button type="button" class="rpos-btn rpos-btn-soft" data-modal-close>Descartar</button>
                    </div>
                    <div class="rpos-odoo-footer-right">
                        <button type="button" class="rpos-btn rpos-btn-soft" data-close-movement>Entrada/salida de efectivo</button>
                        <button type="button" class="rpos-btn rpos-btn-soft rpos-odoo-daily-btn" data-close-daily>
                            <span>Venta diaria</span>
                            <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
                                <polyline points="7 10 12 15 17 10"/>
                                <line x1="12" y1="15" x2="12" y2="3"/>
                            </svg>
                        </button>
                    </div>
                </div>
            `,
            "760px"
        );

        backdrop.querySelector("[data-odoo-mv-toggle]")?.addEventListener("click", () => {
            const list = backdrop.querySelector("[data-odoo-mv-list]");
            const caret = backdrop.querySelector("[data-odoo-caret]");
            if (!list) return;
            const willOpen = list.hasAttribute("hidden");
            if (willOpen) {
                list.removeAttribute("hidden");
                if (caret) caret.innerHTML = "&#9662;";
            } else {
                list.setAttribute("hidden", "");
                if (caret) caret.innerHTML = "&#9656;";
            }
        });

        backdrop.querySelector("[data-open-arqueo]")?.addEventListener("click", () => {
            backdrop.remove();
            this.openCashCountModal("Arqueo de Cierre");
        });

        backdrop.querySelector("[data-close-movement]")?.addEventListener("click", () => {
            backdrop.remove();
            this.openCashMovementModal();
        });

        backdrop.querySelector("[data-close-daily]")?.addEventListener("click", () => {
            this.openDailySalesSummaryModal(preview, displayRows);
        });

        const updateDiff = (inp) => {
            const mop = inp.dataset.closeMop;
            const expected = Number(inp.dataset.expected || 0);
            const closing = Math.max(0, Number(inp.value || 0));
            const diff = Number((closing - expected).toFixed(2));
            const countedEl = [...backdrop.querySelectorAll("[data-odoo-counted]")].find(el => el.dataset.odooCounted === mop);
            if (countedEl) countedEl.textContent = this.formatMoney(closing);
            if (hideExpected) return;
            const diffEl = [...backdrop.querySelectorAll("[data-odoo-diff]")].find(el => el.dataset.odooDiff === mop);
            const diffRow = [...backdrop.querySelectorAll("[data-odoo-diff-row]")].find(el => el.dataset.odooDiffRow === mop);
            if (diffEl) diffEl.textContent = this.formatMoney(diff);
            if (diffRow) diffRow.classList.toggle("has-diff", Math.abs(diff) >= 0.01);
        };

        backdrop.querySelectorAll("[data-close-mop]").forEach(inp => {
            inp.addEventListener("input", () => updateDiff(inp));
            updateDiff(inp);
        });

        backdrop.querySelectorAll("[data-close-clear]").forEach(btn => {
            btn.addEventListener("click", () => {
                const mop = btn.dataset.closeClear;
                const inp = [...backdrop.querySelectorAll("[data-close-mop]")].find(el => el.dataset.closeMop === mop);
                if (!inp) return;
                inp.value = "0.00";
                updateDiff(inp);
                inp.focus();
                inp.select();
            });
        });

        const executeClose = async () => {
            const enteredByMop = {};
            backdrop.querySelectorAll("[data-close-mop]").forEach(inp => {
                enteredByMop[inp.dataset.closeMop] = Math.max(0, Number(inp.value || 0));
            });
            const closingAmounts = rows.map(r => ({
                mode_of_payment: r.mode_of_payment,
                closing_amount: enteredByMop[r.mode_of_payment] !== undefined
                    ? enteredByMop[r.mode_of_payment]
                    : Number(r.expected_amount || 0),
            }));
            const note = (backdrop.querySelector("[data-close-note]")?.value || "").trim();
            const closeRes = await frappe.call({
                method: "restaurant.pos.close_pos_shift",
                args: {
                    pos_opening_shift: shift.name,
                    closing_amounts: closingAmounts,
                    note,
                },
                freeze: true,
                freeze_message: "Cerrando turno y generando POS Closing Shift...",
            });
            backdrop.remove();
            this.bootstrap.opening_shift = null;
            const closingDoc = closeRes.message?.pos_closing_shift;
            frappe.show_alert({
                message: closingDoc
                    ? `Turno POS cerrado correctamente (Cierre: ${closingDoc})`
                    : "Turno de caja cerrado correctamente",
                indicator: "green",
            });
            const prof = this.getActivePosProfileObj();
            const fmt = prof.print_format_for_online || prof.close_pos_format;
            if (closingDoc && fmt) {
                this.openPosaPrintView("POS Closing Shift", closingDoc, fmt, prof.letter_head);
            }
            this.openShiftDialog();
        };

        const warnOverlay = backdrop.querySelector("[data-odoo-warn]");
        const warnSummary = backdrop.querySelector("[data-odoo-warn-summary]");
        backdrop.querySelectorAll("[data-diff-cancel]").forEach(btn => {
            btn.addEventListener("click", () => warnOverlay?.setAttribute("hidden", ""));
        });
        backdrop.querySelector("[data-diff-continue]")?.addEventListener("click", () => {
            warnOverlay?.setAttribute("hidden", "");
            executeClose();
        });

        backdrop.querySelector("[data-close-confirm]").addEventListener("click", () => {
            if (!hideExpected) {
                const diffs = [];
                backdrop.querySelectorAll("[data-close-mop]").forEach(inp => {
                    const expected = Number(inp.dataset.expected || 0);
                    const closing = Math.max(0, Number(inp.value || 0));
                    const diff = Number((closing - expected).toFixed(2));
                    if (Math.abs(diff) >= 0.01) {
                        diffs.push({ mop: inp.dataset.closeMop, diff });
                    }
                });
                if (diffs.length && warnOverlay) {
                    if (warnSummary) {
                        warnSummary.innerHTML = diffs.map(d => `
                            <div class="rpos-odoo-warn-item">
                                <span>${this.escape(d.mop)}</span>
                                <strong>${this.formatMoney(d.diff)}</strong>
                            </div>
                        `).join("");
                    }
                    warnOverlay.removeAttribute("hidden");
                    return;
                }
            }
            executeClose();
        });
    }

    openDailySalesSummaryModal(preview, displayRows) {
        const movements = preview.cash_movements?.movements || [];
        const backdrop = this.createModal(
            "Venta Diaria del Turno",
            `
                <div class="rpos-posa-meta-bar">
                    <span><strong>Perfil:</strong> ${this.escape(preview.pos_profile)}</span>
                    <span><strong>Turno:</strong> ${this.escape(preview.pos_opening_shift)}</span>
                    <span><strong>Cajero:</strong> ${this.escape(preview.cashier_name || preview.user)}</span>
                    <span><strong>Órdenes:</strong> ${Number(preview.invoice_count || 0)}</span>
                    <span><strong>Total Ventas:</strong> ${this.formatMoney(preview.total_sales || 0)}</span>
                </div>
                <table class="rpos-posa-table">
                    <thead>
                        <tr>
                            <th>Método de Pago</th>
                            <th class="is-num">Apertura</th>
                            <th class="is-num">Ventas</th>
                            <th class="is-num">Mov. Efectivo</th>
                            <th class="is-num">Esperado</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${(displayRows || []).map(r => `
                            <tr>
                                <td><strong>${this.escape(r.mode_of_payment)}</strong></td>
                                <td class="is-num">${this.formatMoney(r.opening_amount || 0)}</td>
                                <td class="is-num">${this.formatMoney(r.sales_amount || 0)}</td>
                                <td class="is-num">${this.formatMoney(r.cash_movement_net || 0)}</td>
                                <td class="is-num"><strong>${this.formatMoney(r.expected_amount || 0)}</strong></td>
                            </tr>
                        `).join("")}
                    </tbody>
                </table>
                ${movements.length ? `
                    <div style="margin-top:12px;">
                        <strong style="font-size:12px;">Movimientos de Efectivo (${movements.length})</strong>
                        <div style="margin-top:6px;display:flex;flex-direction:column;gap:4px;">
                            ${movements.map(mv => `
                                <div class="rpos-arq-mv-item">
                                    <span><strong>${this.escape(mv.type_transaction)}:</strong> ${this.escape(mv.note || "-")}</span>
                                    <strong>${mv.type_transaction === "Ingreso" ? "+" : "-"}${this.formatMoney(mv.amount || 0)}</strong>
                                </div>
                            `).join("")}
                        </div>
                    </div>
                ` : ""}
            `,
            `
                <button type="button" class="rpos-btn rpos-btn-soft" data-daily-print>Imprimir Resumen</button>
                <button type="button" class="rpos-btn rpos-btn-primary" data-modal-close>Cerrar</button>
            `,
            "720px"
        );
        backdrop.querySelector("[data-daily-print]")?.addEventListener("click", () => {
            window.print();
        });
    }

    async openCashCountModal(defaultType = "Arqueo de Cierre") {
        const shift = this.bootstrap?.opening_shift;
        if (!shift) {
            this.openShiftDialog();
            return;
        }

        const previewRes = await frappe.call({
            method: "restaurant.cash_count.get_cash_count_preview",
            args: { pos_opening_shift: shift.name },
            freeze: true,
            freeze_message: "Cargando arqueo de caja y datos del turno...",
        });
        let snapshot = previewRes.message;
        if (!snapshot) return;

        let countType = defaultType === "Arqueo Parcial" ? "Arqueo Parcial" : "Arqueo de Cierre";
        const hideExpected = Boolean(Number(snapshot.hide_expected_amount || 0));
        const denomState = (snapshot.denominations || []).map(d => ({
            denomination_type: d.denomination_type,
            unit_value: Number(d.unit_value || 0),
            denomination_label: d.denomination_label,
            quantity: Math.max(0, Math.floor(Number(d.quantity || 0))),
        }));
        const methodDetails = {};
        (snapshot.payment_methods || []).forEach(m => {
            if (!Number(m.is_cash)) {
                methodDetails[m.mode_of_payment] = [
                    { pos_terminal: "", bank_name: "", reference: "", amount: 0 },
                ];
            }
        });
        const commonHondurasBanks = [
            "BAC Credomatic",
            "Banco Atlántida",
            "Banco Ficohsa",
            "Banco de Occidente",
            "Banpaís",
            "Davivienda",
            "Banco Promerica",
            "Banco Lafise",
        ];
        const bankOptions = Array.from(
            new Set([...(snapshot.banks || []), ...commonHondurasBanks].filter(Boolean))
        );
        const posTerminalOptions = [
            "BAC Credomatic",
            "Banco Ficohsa",
            "Banco Atlántida",
            "Banpaís",
            "POS Principal",
            "POS Caja 2",
        ];
        let notesText = "";

        const formatCurrency = (val) => `${snapshot.currency || "L"} ${Number(val || 0).toFixed(2)}`;
        const backdrop = this.createModal(
            "Arqueo de Caja · LEAF Restaurant",
            `<div data-arq-root></div>`,
            `<div data-arq-footer style="display:flex;align-items:center;justify-content:space-between;width:100%;gap:10px;flex-wrap:wrap;"></div>`,
            "1180px"
        );
        const rootEl = backdrop.querySelector("[data-arq-root]");
        const footerEl = backdrop.querySelector("[data-arq-footer]");

        const computeTotals = () => {
            let billsTotal = 0;
            let coinsTotal = 0;
            denomState.forEach(d => {
                const qty = Math.max(0, Math.floor(Number(d.quantity || 0)));
                const sub = Number((qty * d.unit_value).toFixed(2));
                if (d.denomination_type === "Moneda") coinsTotal += sub;
                else billsTotal += sub;
            });
            billsTotal = Number(billsTotal.toFixed(2));
            coinsTotal = Number(coinsTotal.toFixed(2));
            const cashTotal = Number((billsTotal + coinsTotal).toFixed(2));

            let totalExpected = 0;
            let totalCounted = 0;
            const methods = (snapshot.payment_methods || []).map(m => {
                const isCash = Boolean(Number(m.is_cash));
                const detailRows = methodDetails[m.mode_of_payment] || [];
                const detailSum = Number(
                    detailRows
                        .reduce((acc, row) => acc + Math.max(0, Number(row.amount || 0)), 0)
                        .toFixed(2)
                );
                const counted = isCash ? cashTotal : detailSum;
                const expected = Number(m.expected_amount || 0);
                const diff = Number((counted - expected).toFixed(2));
                totalExpected += expected;
                totalCounted += counted;
                return {
                    ...m,
                    isCash,
                    detail_kind: m.detail_kind || (isCash ? "cash" : "other"),
                    counted_amount: counted,
                    difference: diff,
                };
            });
            totalExpected = Number(totalExpected.toFixed(2));
            totalCounted = Number(totalCounted.toFixed(2));
            const rawDiff = Number((totalCounted - totalExpected).toFixed(2));
            const totalDiff = Math.abs(rawDiff) < 0.01 ? 0 : rawDiff;
            let status = "Cuadrado";
            let statusClass = "is-status-ok";
            if (totalDiff > 0) {
                status = "Sobrante";
                statusClass = "is-status-over";
            } else if (totalDiff < 0) {
                status = "Faltante";
                statusClass = "is-status-short";
            }
            return {
                billsTotal,
                coinsTotal,
                cashTotal,
                totalExpected,
                totalCounted,
                totalDiff,
                status,
                statusClass,
                methods,
            };
        };

        const updateLiveDom = () => {
            const calc = computeTotals();
            const setText = (sel, val) => {
                const el = rootEl.querySelector(sel);
                if (el) el.textContent = val;
            };
            denomState.forEach((d, idx) => {
                const subEl = rootEl.querySelector(`[data-denom-sub="${idx}"]`);
                if (subEl) subEl.textContent = formatCurrency(d.quantity * d.unit_value);
            });
            setText("[data-arq-bills]", formatCurrency(calc.billsTotal));
            setText("[data-arq-cash]", formatCurrency(calc.cashTotal));
            setText("[data-arq-kpi-cash]", formatCurrency(calc.cashTotal));
            setText("[data-arq-kpi-counted]", formatCurrency(calc.totalCounted));
            if (!hideExpected) {
                setText("[data-arq-kpi-diff]", formatCurrency(calc.totalDiff));
                setText("[data-arq-kpi-status]", calc.status);
                const statusBox = rootEl.querySelector("[data-arq-kpi-status-box]");
                if (statusBox) {
                    statusBox.classList.remove("is-status-ok", "is-status-over", "is-status-short");
                    statusBox.classList.add(calc.statusClass);
                }
            }

            calc.methods.forEach(m => {
                const countedInput = rootEl.querySelector(`[data-arq-mop-counted="${CSS.escape(m.mode_of_payment)}"]`);
                if (countedInput) countedInput.value = m.counted_amount.toFixed(2);
                const detailSub = rootEl.querySelector(`[data-arq-detail-sub="${CSS.escape(m.mode_of_payment)}"]`);
                if (detailSub) detailSub.textContent = formatCurrency(m.counted_amount);

                const diffEl = rootEl.querySelector(`[data-arq-mop-diff="${CSS.escape(m.mode_of_payment)}"]`);
                if (diffEl && !hideExpected) {
                    diffEl.textContent = formatCurrency(m.difference);
                    diffEl.classList.remove("is-positive", "is-negative");
                    if (m.difference > 0.009) diffEl.classList.add("is-positive");
                    else if (m.difference < -0.009) diffEl.classList.add("is-negative");
                }
            });
        };

        const renderConfirmedState = (saved) => {
            const c = saved.cash_count;
            const fmts = saved.print_formats || {
                ticket: "Arqueo de Caja - Ticket 80mm",
                letter: "Arqueo de Caja - Carta",
            };
            const prof = this.getActivePosProfileObj();
            const badgeStyle =
                c.status === "Cuadrado"
                    ? "background:#dcfce7;color:#166534;border:1px solid #86efac;"
                    : c.status === "Sobrante"
                        ? "background:#dbeafe;color:#1e40af;border:1px solid #93c5fd;"
                        : "background:#fee2e2;color:#991b1b;border:1px solid #fca5a5;";

            rootEl.innerHTML = `
                <div class="rpos-arq-done-box">
                    <div class="rpos-arq-done-badge" style="${badgeStyle}">${this.escape(c.status)} · ${this.escape(c.count_type)}</div>
                    <h3 style="margin:4px 0 6px;font-size:20px;font-weight:800;color:#0f172a;">
                        Arqueo ${this.escape(c.name)} registrado correctamente
                    </h3>
                    <p style="margin:0 0 14px;color:#475569;font-size:13px;">
                        ${c.pos_closing_shift
                    ? `Turno <strong>${this.escape(c.pos_opening_shift)}</strong> cerrado con POS Closing Shift <strong>${this.escape(c.pos_closing_shift)}</strong>.`
                    : `Arqueo parcial guardado para el turno <strong>${this.escape(c.pos_opening_shift)}</strong>.`}
                    </p>
                    <div class="rpos-arq-kpis" style="max-width:780px;margin:0 auto 14px;text-align:left;">
                        <div class="rpos-arq-kpi">
                            <div class="rpos-arq-kpi-lbl">Efectivo Físico</div>
                            <div class="rpos-arq-kpi-val">${this.escape(formatCurrency(c.cash_counted_total))}</div>
                        </div>
                        <div class="rpos-arq-kpi">
                            <div class="rpos-arq-kpi-lbl">Total Esperado</div>
                            <div class="rpos-arq-kpi-val">${this.escape(formatCurrency(c.total_expected))}</div>
                        </div>
                        <div class="rpos-arq-kpi">
                            <div class="rpos-arq-kpi-lbl">Total Contado</div>
                            <div class="rpos-arq-kpi-val">${this.escape(formatCurrency(c.total_counted))}</div>
                        </div>
                        <div class="rpos-arq-kpi ${c.status === "Cuadrado" ? "is-status-ok" : c.status === "Sobrante" ? "is-status-over" : "is-status-short"}">
                            <div class="rpos-arq-kpi-lbl">Diferencia Final</div>
                            <div class="rpos-arq-kpi-val">${this.escape(formatCurrency(c.total_difference))}</div>
                        </div>
                    </div>
                    <div class="rpos-arq-print-actions">
                        <button type="button" class="rpos-btn rpos-btn-primary" data-print-ticket>
                            Imprimir Ticket (80mm)
                        </button>
                        <button type="button" class="rpos-btn rpos-btn-soft" data-print-letter>
                            Imprimir Tamaño Carta
                        </button>
                    </div>
                </div>
            `;

            footerEl.innerHTML = `
                <span style="font-size:12px;color:#64748b;">Puedes reimprimir este arqueo en cualquier momento desde el módulo Restaurante.</span>
                <button type="button" class="rpos-posa-btn-success" data-arq-finish>Finalizar</button>
            `;

            rootEl.querySelector("[data-print-ticket]")?.addEventListener("click", () => {
                this.openPosaPrintView("Restaurant Cash Count", c.name, fmts.ticket, prof.letter_head);
            });
            rootEl.querySelector("[data-print-letter]")?.addEventListener("click", () => {
                this.openPosaPrintView("Restaurant Cash Count", c.name, fmts.letter, prof.letter_head);
            });
            footerEl.querySelector("[data-arq-finish]")?.addEventListener("click", () => {
                backdrop.remove();
                if (c.pos_closing_shift) {
                    this.bootstrap.opening_shift = null;
                    this.openShiftDialog();
                }
            });
        };

        const renderWorkspace = () => {
            const calc = computeTotals();
            const bills = denomState.map((d, idx) => ({ ...d, idx })).filter(d => d.denomination_type !== "Moneda");
            const coins = denomState.map((d, idx) => ({ ...d, idx })).filter(d => d.denomination_type === "Moneda");
            const nonCashMethods = calc.methods.filter(m => !m.isCash);

            const renderDenomRows = (items) => items.map(d => `
                <div class="rpos-arq-denom-row">
                    <span class="rpos-arq-denom-label">${this.escape(d.denomination_label)}</span>
                    <div class="rpos-arq-stepper">
                        <button type="button" class="rpos-arq-step-btn" data-denom-dec="${d.idx}" aria-label="Restar 1">-</button>
                        <input type="number" min="0" step="1" class="rpos-arq-qty-input" data-denom-qty="${d.idx}" value="${d.quantity}">
                        <button type="button" class="rpos-arq-step-btn" data-denom-inc="${d.idx}" aria-label="Sumar 1">+</button>
                    </div>
                    <span class="rpos-arq-denom-sub" data-denom-sub="${d.idx}">${this.escape(formatCurrency(d.quantity * d.unit_value))}</span>
                </div>
            `).join("");

            const renderNonCashCards = () => nonCashMethods.map((m, idx) => {
                const mop = m.mode_of_payment;
                const isCard = m.detail_kind === "card";
                const rows = methodDetails[mop] || [{ pos_terminal: "", bank_name: "", reference: "", amount: 0 }];
                const firstColLabel = isCard ? "POS" : "Nombre del Banco";
                const firstFieldKey = isCard ? "pos_terminal" : "bank_name";
                const firstPlaceholder = isCard ? "Ej. BAC / Ficohsa / POS 1" : "Nombre del banco";
                const listId = isCard ? "rpos-arq-pos-list" : "rpos-arq-bank-list";

                return `
                    <div class="rpos-arq-card">
                        <div class="rpos-arq-card-head">
                            <h4 class="rpos-arq-card-title">${idx + 2}. ${this.escape(mop)}</h4>
                            <div style="display:flex;align-items:center;gap:8px;">
                                <span class="rpos-arq-sec-tag">Total: <strong data-arq-detail-sub="${this.escape(mop)}">${this.escape(formatCurrency(m.counted_amount))}</strong></span>
                                <button type="button" class="rpos-btn rpos-btn-soft" style="padding:4px 9px;font-size:11px;" data-arq-add-detail="${this.escape(mop)}">+ Agregar</button>
                            </div>
                        </div>
                        <div class="rpos-arq-det-head">
                            <span>${firstColLabel}</span>
                            <span>Referencia</span>
                            <span style="text-align:right;">Monto</span>
                            <span></span>
                        </div>
                        <div class="rpos-arq-det-list">
                            ${rows.map((row, rIdx) => `
                                <div class="rpos-arq-det-row">
                                    <input type="text" class="rpos-arq-det-inp" list="${listId}"
                                        placeholder="${firstPlaceholder}"
                                        data-arq-det-mop="${this.escape(mop)}"
                                        data-arq-det-idx="${rIdx}"
                                        data-arq-det-field="${firstFieldKey}"
                                        value="${this.escape(row[firstFieldKey] || "")}">
                                    <input type="text" class="rpos-arq-det-inp"
                                        placeholder="Núm. referencia"
                                        data-arq-det-mop="${this.escape(mop)}"
                                        data-arq-det-idx="${rIdx}"
                                        data-arq-det-field="reference"
                                        value="${this.escape(row.reference || "")}">
                                    <input type="number" step="0.01" min="0" class="rpos-arq-det-amt"
                                        data-arq-det-mop="${this.escape(mop)}"
                                        data-arq-det-idx="${rIdx}"
                                        data-arq-det-field="amount"
                                        value="${Number(row.amount || 0).toFixed(2)}">
                                    <button type="button" class="rpos-arq-det-del" title="Quitar o limpiar fila"
                                        data-arq-del-mop="${this.escape(mop)}"
                                        data-arq-del-idx="${rIdx}">&times;</button>
                                </div>
                            `).join("")}
                        </div>
                    </div>
                `;
            }).join("");

            rootEl.innerHTML = `
                <datalist id="rpos-arq-pos-list">
                    ${posTerminalOptions.map(p => `<option value="${this.escape(p)}"></option>`).join("")}
                </datalist>
                <datalist id="rpos-arq-bank-list">
                    ${bankOptions.map(b => `<option value="${this.escape(b)}"></option>`).join("")}
                </datalist>

                <div class="rpos-arq-topbar">
                    <div class="rpos-arq-meta">
                        <span class="rpos-arq-meta-pill">Perfil: <strong>${this.escape(snapshot.pos_profile)}</strong></span>
                        <span class="rpos-arq-meta-pill">Turno: <strong>${this.escape(snapshot.pos_opening_shift)}</strong></span>
                        <span class="rpos-arq-meta-pill">Cajero: <strong>${this.escape(snapshot.cashier_name || snapshot.cashier)}</strong></span>
                        <span class="rpos-arq-meta-pill">Facturas: <strong>${Number(snapshot.invoice_count || 0)}</strong> (${this.escape(formatCurrency(snapshot.total_sales))})</span>
                    </div>
                    <div class="rpos-arq-type-switch" role="group" aria-label="Tipo de Arqueo">
                        <button type="button" class="rpos-arq-type-btn ${countType === "Arqueo Parcial" ? "is-active" : ""}" data-arq-type="Arqueo Parcial">Arqueo Parcial</button>
                        <button type="button" class="rpos-arq-type-btn ${countType === "Arqueo de Cierre" ? "is-active" : ""}" data-arq-type="Arqueo de Cierre">Arqueo de Cierre</button>
                    </div>
                </div>

                <div class="rpos-arq-kpis">
                    <div class="rpos-arq-kpi">
                        <div class="rpos-arq-kpi-lbl">Efectivo Contado</div>
                        <div class="rpos-arq-kpi-val" data-arq-kpi-cash>${this.escape(formatCurrency(calc.cashTotal))}</div>
                        <div class="rpos-arq-kpi-sub">Billetes en Lempiras</div>
                    </div>
                    <div class="rpos-arq-kpi">
                        <div class="rpos-arq-kpi-lbl">Total Contado</div>
                        <div class="rpos-arq-kpi-val" data-arq-kpi-counted>${this.escape(formatCurrency(calc.totalCounted))}</div>
                        <div class="rpos-arq-kpi-sub">Efectivo + Tarjetas / Bancos</div>
                    </div>
                    <div class="rpos-arq-kpi">
                        <div class="rpos-arq-kpi-lbl">Total Esperado</div>
                        <div class="rpos-arq-kpi-val">${hideExpected ? "Oculto" : this.escape(formatCurrency(calc.totalExpected))}</div>
                        <div class="rpos-arq-kpi-sub">${hideExpected ? "Modo arqueo ciego" : "Apertura + Ventas + Movs."}</div>
                    </div>
                    <div class="rpos-arq-kpi ${hideExpected ? "" : calc.statusClass}" data-arq-kpi-status-box>
                        <div class="rpos-arq-kpi-lbl">Diferencia / Estado</div>
                        <div class="rpos-arq-kpi-val" data-arq-kpi-diff>${hideExpected ? "—" : this.escape(formatCurrency(calc.totalDiff))}</div>
                        <div class="rpos-arq-kpi-sub" data-arq-kpi-status>${hideExpected ? "Se valida al guardar" : this.escape(calc.status)}</div>
                    </div>
                </div>

                <div class="rpos-arq-grid">
                    <div>
                        <div class="rpos-arq-card">
                            <div class="rpos-arq-card-head">
                                <h4 class="rpos-arq-card-title"><span class="rpos-arq-step-badge">1</span> Conteo de Efectivo (Lempiras)</h4>
                                <button type="button" class="rpos-btn rpos-btn-soft" style="padding:4px 9px;font-size:11px;" data-arq-reset-denom>Limpiar</button>
                            </div>
                            <div class="rpos-arq-denom-group">Billetes</div>
                            <div class="rpos-arq-denom-list">${renderDenomRows(bills)}</div>
                            ${coins.length ? `
                                <div class="rpos-arq-denom-group">Monedas</div>
                                <div class="rpos-arq-denom-list">${renderDenomRows(coins)}</div>
                            ` : ""}
                            <div class="rpos-arq-denom-footer">
                                <span>Billetes: <strong data-arq-bills>${this.escape(formatCurrency(calc.billsTotal))}</strong></span>
                                <span>Total Efectivo: <strong data-arq-cash>${this.escape(formatCurrency(calc.cashTotal))}</strong></span>
                            </div>
                        </div>

                        ${renderNonCashCards()}
                    </div>

                    <div>
                        <div class="rpos-arq-card">
                            <div class="rpos-arq-card-head">
                                <h4 class="rpos-arq-card-title"><span class="rpos-arq-step-badge">2</span> Conciliación por Método de Pago</h4>
                                <span class="rpos-arq-sec-tag">Sistema vs Contado</span>
                            </div>
                            <table class="rpos-arq-table">
                                <thead>
                                    <tr>
                                        <th>Método</th>
                                        <th class="num">Apertura</th>
                                        <th class="num">Ventas</th>
                                        ${hideExpected ? "" : '<th class="num">Esperado</th>'}
                                        <th class="num">Contado (${this.escape(snapshot.currency || "L")})</th>
                                        ${hideExpected ? "" : '<th class="num">Diferencia</th>'}
                                    </tr>
                                </thead>
                                <tbody>
                                    ${calc.methods.map(m => `
                                        <tr>
                                            <td>
                                                <strong>${this.escape(m.mode_of_payment)}</strong>
                                                ${m.isCash ? '<span class="rpos-arq-cash-chip">Conteo físico</span>' : ""}
                                            </td>
                                            <td class="num">${this.escape(formatCurrency(m.opening_amount))}</td>
                                            <td class="num">${this.escape(formatCurrency(m.sales_amount))}</td>
                                            ${hideExpected ? "" : `<td class="num"><strong>${this.escape(formatCurrency(m.expected_amount))}</strong></td>`}
                                            <td class="num">
                                                <input type="number" step="0.01" min="0"
                                                    class="rpos-arq-counted-inp"
                                                    data-arq-mop-counted="${this.escape(m.mode_of_payment)}"
                                                    value="${m.counted_amount.toFixed(2)}"
                                                    readonly
                                                    title="${m.isCash ? "Se calcula automáticamente desde el conteo de billetes" : "Se calcula automáticamente desde el detalle de este método"}">
                                            </td>
                                            ${hideExpected ? "" : `<td class="num"><span class="rpos-posa-diff" data-arq-mop-diff="${this.escape(m.mode_of_payment)}"></span></td>`}
                                        </tr>
                                    `).join("")}
                                </tbody>
                            </table>
                        </div>

                        <div class="rpos-arq-card">
                            <div class="rpos-arq-card-head">
                                <h4 class="rpos-arq-card-title"><span class="rpos-arq-step-badge">3</span> Ingresos y Egresos del Turno</h4>
                                <span style="font-size:11.5px;color:#334155;">
                                    +<strong style="color:#15803d;">${this.escape(formatCurrency(snapshot.total_income))}</strong> ·
                                    -<strong style="color:#b91c1c;">${this.escape(formatCurrency(snapshot.total_expense))}</strong>
                                </span>
                            </div>
                            <div class="rpos-arq-mv-form">
                                <select class="rpos-input" data-arq-mv-type>
                                    <option value="Retiro">Egreso / Retiro (-)</option>
                                    <option value="Ingreso">Ingreso Extra (+)</option>
                                </select>
                                <input type="number" step="0.01" min="0.01" class="rpos-input" data-arq-mv-amount placeholder="Monto (L)">
                                <input type="text" class="rpos-input" data-arq-mv-note placeholder="Motivo (ej. Compra de hielo / Fondo extra)">
                                <button type="button" class="rpos-btn rpos-btn-primary" data-arq-mv-add>Agregar</button>
                            </div>
                            <div class="rpos-arq-mv-list">
                                ${(snapshot.movements || []).length ? snapshot.movements.map(mv => `
                                    <div class="rpos-arq-mv-item">
                                        <div>
                                            <span class="rpos-badge ${mv.type_transaction === "Ingreso" ? "is-success" : "is-danger"}" style="margin-right:6px;">
                                                ${this.escape(mv.type_transaction)}
                                            </span>
                                            <span>${this.escape(mv.note || "Sin descripción")}</span>
                                            <span style="color:#64748b;font-size:11px;margin-left:6px;">(${this.escape(mv.name)})</span>
                                        </div>
                                        <strong style="font-variant-numeric:tabular-nums;color:${mv.type_transaction === "Ingreso" ? "#15803d" : "#b91c1c"};">
                                            ${mv.type_transaction === "Ingreso" ? "+" : "-"}${this.escape(formatCurrency(mv.amount))}
                                        </strong>
                                    </div>
                                `).join("") : `<div style="font-size:12px;color:#64748b;padding:4px 2px;">No hay ingresos ni retiros registrados en este turno.</div>`}
                            </div>
                        </div>

                        <div class="rpos-arq-card" style="margin-bottom:0;">
                            <div class="rpos-arq-card-head">
                                <h4 class="rpos-arq-card-title"><span class="rpos-arq-step-badge">4</span> Observaciones e Historial del Turno</h4>
                            </div>
                            <textarea class="rpos-input" rows="2" data-arq-notes placeholder="Observaciones del arqueo (motivo de diferencia, billetes deteriorados, cierre de datafono, etc.)">${this.escape(notesText)}</textarea>
                            ${(snapshot.recent_counts || []).length ? `
                                <div style="margin-top:8px;font-size:11.5px;color:#475569;">
                                    <strong>Arqueos previos en este turno:</strong>
                                    <div style="display:flex;flex-wrap:wrap;gap:6px;margin-top:5px;">
                                        ${snapshot.recent_counts.map(rc => `
                                            <span style="display:inline-flex;align-items:center;gap:6px;background:#f1f5f9;border:1px solid #cbd5e1;border-radius:6px;padding:3px 8px;">
                                                <strong>${this.escape(rc.name)}</strong> (${this.escape(rc.status)})
                                                <button type="button" class="rpos-btn rpos-btn-soft" style="padding:2px 6px;font-size:10px;" data-reprint-id="${this.escape(rc.name)}" data-reprint-fmt="ticket">Ticket</button>
                                                <button type="button" class="rpos-btn rpos-btn-soft" style="padding:2px 6px;font-size:10px;" data-reprint-id="${this.escape(rc.name)}" data-reprint-fmt="letter">Carta</button>
                                            </span>
                                        `).join("")}
                                    </div>
                                </div>
                            ` : ""}
                        </div>
                    </div>
                </div>
            `;

            const submitLabel = countType === "Arqueo de Cierre"
                ? "Guardar Arqueo y Cerrar Turno"
                : "Guardar Arqueo Parcial";
            footerEl.innerHTML = `
                <span style="font-size:12px;color:#475569;">
                    ${countType === "Arqueo de Cierre"
                    ? "Al guardar se registrará el arqueo y se generará automáticamente el Cierre de Turno POS."
                    : "El arqueo parcial queda guardado y validado sin cerrar el turno actual."}
                </span>
                <div style="display:flex;gap:8px;align-items:center;">
                    <button type="button" class="rpos-posa-btn-error" data-modal-close>Cancelar</button>
                    <button type="button" class="rpos-posa-btn-success" data-arq-submit>${submitLabel}</button>
                </div>
            `;

            footerEl.querySelectorAll("[data-modal-close]").forEach(btn => {
                btn.addEventListener("click", () => backdrop.remove());
            });

            rootEl.querySelectorAll("[data-arq-type]").forEach(btn => {
                btn.addEventListener("click", () => {
                    countType = btn.dataset.arqType;
                    renderWorkspace();
                });
            });

            rootEl.querySelector("[data-arq-reset-denom]")?.addEventListener("click", () => {
                denomState.forEach(d => { d.quantity = 0; });
                renderWorkspace();
            });

            rootEl.querySelectorAll("[data-denom-dec]").forEach(btn => {
                btn.addEventListener("click", () => {
                    const idx = Number(btn.dataset.denomDec);
                    denomState[idx].quantity = Math.max(0, denomState[idx].quantity - 1);
                    const inp = rootEl.querySelector(`[data-denom-qty="${idx}"]`);
                    if (inp) inp.value = denomState[idx].quantity;
                    updateLiveDom();
                });
            });

            rootEl.querySelectorAll("[data-denom-inc]").forEach(btn => {
                btn.addEventListener("click", () => {
                    const idx = Number(btn.dataset.denomInc);
                    denomState[idx].quantity = Math.max(0, denomState[idx].quantity + 1);
                    const inp = rootEl.querySelector(`[data-denom-qty="${idx}"]`);
                    if (inp) inp.value = denomState[idx].quantity;
                    updateLiveDom();
                });
            });

            rootEl.querySelectorAll("[data-denom-qty]").forEach(inp => {
                inp.addEventListener("input", () => {
                    const idx = Number(inp.dataset.denomQty);
                    denomState[idx].quantity = Math.max(0, Math.floor(Number(inp.value || 0)));
                    updateLiveDom();
                });
            });

            rootEl.querySelectorAll("[data-arq-add-detail]").forEach(btn => {
                btn.addEventListener("click", () => {
                    const mop = btn.dataset.arqAddDetail;
                    if (!methodDetails[mop]) methodDetails[mop] = [];
                    methodDetails[mop].push({ pos_terminal: "", bank_name: "", reference: "", amount: 0 });
                    renderWorkspace();
                });
            });

            rootEl.querySelectorAll("[data-arq-det-field]").forEach(inp => {
                inp.addEventListener("input", () => {
                    const mop = inp.dataset.arqDetMop;
                    const idx = Number(inp.dataset.arqDetIdx);
                    const field = inp.dataset.arqDetField;
                    const row = methodDetails[mop]?.[idx];
                    if (!row) return;
                    if (field === "amount") {
                        row.amount = Math.max(0, Number(inp.value || 0));
                        updateLiveDom();
                    } else {
                        row[field] = inp.value;
                    }
                });
            });

            rootEl.querySelectorAll("[data-arq-del-mop]").forEach(btn => {
                btn.addEventListener("click", () => {
                    const mop = btn.dataset.arqDelMop;
                    const idx = Number(btn.dataset.arqDelIdx);
                    const rows = methodDetails[mop];
                    if (!rows) return;
                    if (rows.length > 1) {
                        rows.splice(idx, 1);
                    } else {
                        rows[0] = { pos_terminal: "", bank_name: "", reference: "", amount: 0 };
                    }
                    renderWorkspace();
                });
            });

            rootEl.querySelector("[data-arq-notes]")?.addEventListener("input", (e) => {
                notesText = e.target.value;
            });

            rootEl.querySelectorAll("[data-reprint-id]").forEach(btn => {
                btn.addEventListener("click", () => {
                    const prof = this.getActivePosProfileObj();
                    const fmt = btn.dataset.reprintFmt === "ticket"
                        ? (snapshot.print_formats?.ticket || "Arqueo de Caja - Ticket 80mm")
                        : (snapshot.print_formats?.letter || "Arqueo de Caja - Carta");
                    this.openPosaPrintView("Restaurant Cash Count", btn.dataset.reprintId, fmt, prof.letter_head);
                });
            });

            rootEl.querySelector("[data-arq-mv-add]")?.addEventListener("click", async () => {
                const typeTx = rootEl.querySelector("[data-arq-mv-type]")?.value || "Retiro";
                const amt = Number(rootEl.querySelector("[data-arq-mv-amount]")?.value || 0);
                const note = (rootEl.querySelector("[data-arq-mv-note]")?.value || "").trim();
                if (!(amt > 0)) {
                    frappe.show_alert({ message: "Ingresa un monto mayor que cero para el movimiento.", indicator: "orange" });
                    return;
                }
                if (!note) {
                    frappe.show_alert({ message: "Ingresa el motivo o descripción del ingreso/egreso.", indicator: "orange" });
                    return;
                }
                const mvRes = await frappe.call({
                    method: "restaurant.cash_count.register_cash_count_movement",
                    args: {
                        type_transaction: typeTx,
                        amount: amt,
                        note,
                        pos_opening_shift: snapshot.pos_opening_shift,
                    },
                    freeze: true,
                    freeze_message: "Registrando movimiento de efectivo...",
                });
                if (mvRes.message) {
                    snapshot = mvRes.message;
                    (snapshot.payment_methods || []).forEach(m => {
                        if (!Number(m.is_cash) && !methodDetails[m.mode_of_payment]) {
                            methodDetails[m.mode_of_payment] = [
                                { pos_terminal: "", bank_name: "", reference: "", amount: 0 },
                            ];
                        }
                    });
                    frappe.show_alert({ message: `${typeTx} registrado y descontado/sumado en el arqueo.`, indicator: "green" });
                    renderWorkspace();
                }
            });

            footerEl.querySelector("[data-arq-submit]")?.addEventListener("click", async () => {
                const currentCalc = computeTotals();
                const paymentDetailsPayload = [];
                currentCalc.methods.forEach(m => {
                    if (m.isCash) return;
                    (methodDetails[m.mode_of_payment] || []).forEach(row => {
                        const amt = Math.max(0, Number(row.amount || 0));
                        const posTerm = (row.pos_terminal || "").trim();
                        const bankName = (row.bank_name || "").trim();
                        const ref = (row.reference || "").trim();
                        if (amt > 0 || posTerm || bankName || ref) {
                            paymentDetailsPayload.push({
                                mode_of_payment: m.mode_of_payment,
                                pos_terminal: posTerm,
                                bank_name: bankName,
                                reference: ref,
                                amount: amt,
                            });
                        }
                    });
                });
                const payload = {
                    pos_opening_shift: snapshot.pos_opening_shift,
                    count_type: countType,
                    notes: notesText,
                    denominations: denomState.map(d => ({
                        denomination_type: d.denomination_type,
                        unit_value: d.unit_value,
                        denomination_label: d.denomination_label,
                        quantity: Math.max(0, Math.floor(Number(d.quantity || 0))),
                    })),
                    payment_methods: currentCalc.methods.map(m => ({
                        mode_of_payment: m.mode_of_payment,
                        counted_amount: m.counted_amount,
                    })),
                    payment_details: paymentDetailsPayload,
                };

                const saveRes = await frappe.call({
                    method: "restaurant.cash_count.save_and_submit_cash_count",
                    args: { payload },
                    freeze: true,
                    freeze_message: countType === "Arqueo de Cierre"
                        ? "Validando arqueo y cerrando turno POS..."
                        : "Guardando y validando arqueo parcial...",
                });
                if (saveRes.message?.cash_count) {
                    frappe.show_alert({
                        message: `Arqueo ${saveRes.message.cash_count.name} guardado (${saveRes.message.cash_count.status}).`,
                        indicator: "green",
                    });
                    renderConfirmedState(saveRes.message);
                }
            });

            updateLiveDom();
        };

        renderWorkspace();
    }
}
