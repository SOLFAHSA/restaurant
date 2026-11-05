(() => {
// Restaurant configuration extends Item; it does not post sales or stock movements.
frappe.ui.form.on("Item", {
    refresh(frm) {
        if (!frm.restaurant_editor) frm.restaurant_editor = new RestaurantItemEditor(frm);
        return frm.restaurant_editor.load();
    },
    restaurant_recipe_enabled(frm) {
        frm.restaurant_editor?.render();
    },
    restaurant_options_enabled(frm) {
        frm.restaurant_editor?.render();
    },
});

class RestaurantItemEditor {
    constructor(frm) {
        this.frm = frm;
        this.context = null;
        this.requestId = 0;
    }

    escape(value) {
        return frappe.utils.escape_html(String(value == null ? "" : value));
    }

    quantity(value) {
        return Number(value).toLocaleString("es-HN", { maximumFractionDigits: 6 });
    }

    money(value, currency) {
        const amount = Number(value || 0).toLocaleString("es-HN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
        const code = currency || this.context?.currency || "HNL";
        return code === "HNL" ? `L ${amount}` : `${code} ${amount}`;
    }

    selectionBadge(group) {
        const min = Number(group.min_selections || 0);
        const max = Number(group.max_selections || 1);
        if (min === 1 && max === 1) return "1 Incluido";
        if (min > 1 && min === max) return `${min} Incluidos`;
        if (min === 0) return `Opcional · máx. ${max}`;
        return `Selecciones: ${min}–${max}`;
    }

    async call(method, args) {
        const response = await frappe.call({
            method: `restaurant.item_configuration.${method}`,
            args,
            freeze: true,
            freeze_message: "Procesando configuración del platillo…",
        });
        return response.message;
    }

    async load() {
        const requestId = ++this.requestId;
        const itemCode = this.frm.doc.name;
        if (this.frm.is_new()) {
            this.context = null;
            this.render();
            return;
        }
        try {
            const response = await frappe.call({
                method: "restaurant.item_configuration.get_configuration",
                args: { item_code: itemCode },
            });
            if (requestId !== this.requestId || this.frm.doc.name !== itemCode) return;
            this.context = response.message;
            this.render();
        } catch (error) {
            if (requestId !== this.requestId) return;
            const field = this.frm.fields_dict.restaurant_configuration;
            if (field) field.$wrapper.html('<p class="text-danger" role="alert">No fue posible cargar la configuración. Comprueba tus permisos y recarga el producto.</p>');
        }
    }

    render() {
        const field = this.frm.fields_dict.restaurant_configuration;
        if (!field) return;
        const root = field.$wrapper[0];
        const recipeEnabled = Boolean(this.frm.doc.restaurant_recipe_enabled);
        const optionsEnabled = Boolean(this.frm.doc.restaurant_options_enabled);
        const unsaved = this.frm.is_new() || this.frm.is_dirty();
        const canWrite = Boolean(this.context?.can_write) && !unsaved;
        const recipe = this.context?.recipe || { rows: [], editable: true };
        root.innerHTML = '<p class="text-muted">Esta pestaña guarda la configuración del platillo. La interfaz de ventas y el consumo de inventario se integrarán en otra etapa.</p>';
        if (!recipeEnabled && !optionsEnabled) {
            root.insertAdjacentHTML("beforeend", '<p>Sin configuración de Restaurante. El producto conserva su funcionamiento habitual.</p>');
            return;
        }
        if (unsaved) root.insertAdjacentHTML("beforeend", '<p class="text-warning">Guarda primero el producto y sus casillas de configuración. Después podrás guardar componentes y opciones desde esta pestaña.</p>');
        if (recipeEnabled) {
            const section = document.createElement("section");
            section.style.cssText = "margin:18px 0;padding:16px;border:1px solid var(--border-color);border-radius:8px";
            section.innerHTML = '<h4>Componentes de la receta</h4><p class="text-muted">Cantidades necesarias para una unidad del platillo. Los componentes se guardan en un paquete nativo deshabilitado, pendiente de integración con ventas.</p>';
            if (this.frm.doc.is_stock_item) section.insertAdjacentHTML("beforeend", '<p class="text-danger">Para configurar esta receta, el platillo debe tener Mantener Stock desmarcado. Los ingredientes sí deben mantener inventario.</p>');
            const rows = recipe.rows || [];
            if (rows.length) {
                section.insertAdjacentHTML("beforeend", `<div class="table-responsive"><table class="table table-bordered"><thead><tr><th>Componente</th><th>Cantidad</th><th>Unidad</th><th>Cantidad de inventario</th></tr></thead><tbody>${rows.map(row => `<tr><td>${this.escape(row.item_code)}</td><td>${this.escape(this.quantity(row.qty))}</td><td>${this.escape(row.uom)}</td><td>${this.escape(this.quantity(row.stock_qty))} ${this.escape(row.stock_uom)}</td></tr>`).join("")}</tbody></table></div>`);
            } else section.insertAdjacentHTML("beforeend", '<p>No hay componentes configurados.</p>');
            if (recipe.readonly_reason) section.insertAdjacentHTML("beforeend", `<p class="text-warning">${this.escape(recipe.readonly_reason)}</p>`);
            this.button(section, rows.length ? "Editar componentes" : "Agregar componentes", () => this.editRecipe(), !canWrite || recipe.editable === false || Boolean(this.frm.doc.is_stock_item));
            root.appendChild(section);
        }
        if (optionsEnabled) {
            const section = document.createElement("section");
            section.style.cssText = "margin:18px 0;padding:16px;border:1px solid var(--border-color);border-radius:8px";
            section.innerHTML = '<h4>Opciones del platillo y combos</h4><p class="text-muted">Define grupos como Lados, Extras o secciones de Menú combinado. Cada opción puede mantenerse incluida en el precio (+ L 0.00) o sumar un importe adicional. No modifica aún una venta.</p>';
            if (canWrite && !this.context?.can_create_option_group) section.insertAdjacentHTML("beforeend", '<p class="text-warning">No tienes los permisos necesarios sobre grupos de opciones o monedas para crear grupos. Consulta al administrador.</p>');
            const groups = this.context?.groups || [];
            if (!groups.length) section.insertAdjacentHTML("beforeend", '<p>No hay grupos de opciones configurados.</p>');
            for (const group of groups) {
                const card = document.createElement("div");
                card.style.cssText = "padding:12px 14px;border:1px solid var(--border-color);border-radius:8px;margin-bottom:12px;background:var(--card-bg, #fff)";
                const header = document.createElement("div");
                header.style.cssText = "display:flex;justify-content:space-between;gap:12px;align-items:center;flex-wrap:wrap;margin-bottom:8px";
                header.innerHTML = `<span><strong>${this.escape(group.group_name)}</strong> <em class="text-muted" style="margin-left:6px">${this.escape(this.selectionBadge(group))}</em> · <span class="text-muted">Selecciones: ${this.escape(group.min_selections)}–${this.escape(group.max_selections)} · ${this.escape((group.options || []).length)} opciones${group.disabled ? " · Inactivo" : ""}</span></span>`;
                this.button(header, "Editar grupo", () => this.editGroup(group), !canWrite || !group._can_write);
                card.appendChild(header);
                const pills = document.createElement("div");
                pills.style.cssText = "display:flex;gap:8px;flex-wrap:wrap";
                for (const opt of group.options || []) {
                    const extra = Number(opt.additional_amount || 0);
                    const isDefault = Boolean(Number(opt.is_default));
                    const pill = document.createElement("span");
                    pill.style.cssText = `display:inline-flex;align-items:center;gap:6px;padding:6px 10px;border-radius:6px;font-size:12px;border:1px solid ${isDefault ? "#0284c7" : "var(--border-color)"};background:${isDefault ? "#e0f2fe" : "var(--control-bg, #f8fafc)"}`;
                    const surchargeHtml = extra > 0 ? `<span style="background:#0891b2;color:#fff;padding:1px 7px;border-radius:999px;font-weight:600;font-size:11px">+ ${this.escape(this.money(extra, group.currency))}</span>` : "";
                    pill.innerHTML = `<span>${this.escape(opt.option_label)}</span>${surchargeHtml}`;
                    pills.appendChild(pill);
                }
                card.appendChild(pills);
                section.appendChild(card);
            }
            const actions = document.createElement("div");
            actions.style.cssText = "display:flex;gap:8px;flex-wrap:wrap;margin-top:8px";
            this.button(actions, "Agregar grupo de opciones", () => this.editGroup(), !canWrite || !this.context?.can_create_option_group);
            if (groups.some(group => !Number(group.disabled))) {
                this.button(actions, "Vista previa del modal", () => this.previewModal(), false);
            }
            section.appendChild(actions);
            root.appendChild(section);
        }
    }

    button(parent, label, handler, disabled = false) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "btn btn-default btn-sm";
        button.textContent = label;
        button.disabled = disabled;
        button.addEventListener("click", handler);
        parent.appendChild(button);
    }

    ready() {
        if (this.frm.is_new() || this.frm.is_dirty()) {
            frappe.msgprint("Guarda el producto antes de editar su configuración de Restaurante.");
            return false;
        }
        return true;
    }

    editRecipe() {
        if (!this.ready()) return;
        const recipe = this.context.recipe;
        const rows = (recipe.rows || []).map(row => ({ item_code: row.item_code, qty: row.qty, uom: row.uom }));
        const dialog = new frappe.ui.Dialog({
            title: "Componentes de la receta",
            size: "extra-large",
            fields: [
                { fieldname: "help", fieldtype: "HTML", options: '<p>Pulsa Añadir fila y haz clic en la celda Componente para buscar ingredientes o empaques existentes. La unidad puede quedar vacía para usar la unidad de inventario del ingrediente. Una unidad distinta requiere una conversión válida. Guarda al menos un componente.</p>' },
                { fieldname: "components", fieldtype: "Table", label: "Componentes por unidad de platillo", in_place_edit: true, reqd: 1, data: rows, fields: [
                    { fieldname: "item_code", fieldtype: "Link", options: "Item", label: "Componente", reqd: 1, in_list_view: 1, columns: 4, get_query: () => ({ filters: { disabled: 0, is_stock_item: 1, has_variants: 0, is_fixed_asset: 0 } }) },
                    { fieldname: "qty", fieldtype: "Float", label: "Cantidad", reqd: 1, in_list_view: 1, columns: 3, precision: 6 },
                    { fieldname: "uom", fieldtype: "Link", options: "UOM", label: "Unidad", in_list_view: 1, columns: 3 },
                ] },
            ],
            primary_action_label: "Guardar receta",
            primary_action: async values => {
                if (!values) return;
                dialog.disable_primary_action();
                try {
                    this.context = await this.call("save_recipe", {
                        item_code: this.frm.doc.name,
                        rows: values.components,
                        item_modified: this.frm.doc.modified,
                        bundle_modified: recipe.modified || null,
                    });
                    dialog.hide();
                    this.render();
                    frappe.show_alert({ message: "Receta configurada. No se generaron movimientos de inventario.", indicator: "green" });
                } catch (error) {
                    // The native error dialog preserves the input for correction.
                } finally {
                    dialog.enable_primary_action();
                }
            },
        });
        dialog.show();
    }

    editGroup(group = {}) {
        if (!this.ready()) return;
        const rows = (group.options || []).map(row => ({
            option_label: row.option_label, effect: row.effect, item_code: row.item_code,
            replaces_item: row.replaces_item, qty: row.qty, uom: row.uom,
            additional_amount: row.additional_amount, is_default: row.is_default,
        }));
        const dialog = new frappe.ui.Dialog({
            title: group.name ? "Editar grupo de opciones" : "Nuevo grupo de opciones",
            size: "extra-large",
            fields: [
                { fieldname: "group_name", fieldtype: "Data", label: "Nombre del grupo", reqd: 1, default: group.group_name || "" },
                { fieldname: "min_selections", fieldtype: "Int", label: "Mínimo de selecciones", reqd: 1, default: group.min_selections ?? 1 },
                { fieldname: "max_selections", fieldtype: "Int", label: "Máximo de selecciones", reqd: 1, default: group.max_selections ?? 1 },
                { fieldname: "currency", fieldtype: "Link", options: "Currency", label: "Moneda de los adicionales", reqd: 1, default: group.currency || this.context.currency || "" },
                { fieldname: "disabled", fieldtype: "Check", label: "Grupo inactivo", default: group.disabled || 0 },
                { fieldname: "help", fieldtype: "HTML", options: '<p>Pulsa Añadir fila para definir cada alternativa y elegir su efecto. Solo indicación guarda una preferencia sin ingredientes. Sustituir componente reemplaza un ingrediente de la receta; Agregar componente suma un extra; Incluir en combo vincula un platillo o bebida elegible dentro de un menú combinado. El adicional puede ser cero o positivo.</p>' },
                { fieldname: "options", fieldtype: "Table", label: "Opciones disponibles", in_place_edit: false, reqd: 1, data: rows, fields: [
                    { fieldname: "option_label", fieldtype: "Data", label: "Opción", reqd: 1, in_list_view: 1, columns: 4 },
                    { fieldname: "effect", fieldtype: "Select", label: "Efecto", options: "Solo indicación\nSustituir componente\nAgregar componente\nIncluir en combo", reqd: 1, default: "Solo indicación", in_list_view: 1, columns: 3 },
                    { fieldname: "additional_amount", fieldtype: "Currency", options: "currency", label: "Adicional", default: 0, in_list_view: 1, columns: 3 },
                    { fieldname: "item_code", fieldtype: "Link", options: "Item", label: "Ingrediente, extra o platillo", get_query: () => ({ filters: { disabled: 0, has_variants: 0, is_fixed_asset: 0 } }) },
                    { fieldname: "replaces_item", fieldtype: "Link", options: "Item", label: "Componente que sustituye", get_query: () => ({ filters: { name: ["in", (this.context.recipe.rows || []).map(row => row.item_code)] } }) },
                    { fieldname: "qty", fieldtype: "Float", label: "Cantidad", precision: 6 },
                    { fieldname: "uom", fieldtype: "Link", options: "UOM", label: "Unidad" },
                    { fieldname: "is_default", fieldtype: "Check", label: "Seleccionada por defecto", default: 0 },
                ] },
            ],
            primary_action_label: "Guardar grupo",
            primary_action: async values => {
                if (!values) return;
                dialog.disable_primary_action();
                try {
                    this.context = await this.call("save_option_group", {
                        item_code: this.frm.doc.name,
                        item_modified: this.frm.doc.modified,
                        group: { ...values, name: group.name, modified: group.modified },
                    });
                    dialog.hide();
                    this.render();
                    frappe.show_alert({ message: "Grupo de opciones guardado", indicator: "green" });
                } catch (error) {
                    // Server-side permissions and validation remain authoritative.
                } finally {
                    dialog.enable_primary_action();
                }
            },
        });
        dialog.show();
    }

    previewModal() {
        const activeGroups = (this.context?.groups || []).filter(group => !Number(group.disabled));
        if (!activeGroups.length) return;
        const itemInfo = this.context?.item || {};
        const itemName = itemInfo.item_name || this.frm.doc.item_name || this.frm.doc.name;
        const basePrice = Number(itemInfo.base_price ?? this.frm.doc.standard_rate ?? 0);
        const currency = activeGroups[0]?.currency || this.context?.currency || "HNL";
        const selections = new Map();
        for (const group of activeGroups) {
            const defaults = new Set();
            (group.options || []).forEach((opt, idx) => {
                if (Number(opt.is_default)) defaults.add(idx);
            });
            selections.set(group.name, defaults);
        }
        const dialog = new frappe.ui.Dialog({
            title: `${itemName} | ${this.money(basePrice, currency)}`,
            size: "large",
            fields: [{ fieldname: "preview_area", fieldtype: "HTML" }],
            primary_action_label: "Añadir (Simulación)",
            secondary_action_label: "Descartar",
            secondary_action: () => dialog.hide(),
            primary_action: () => {
                for (const group of activeGroups) {
                    const chosen = selections.get(group.name) || new Set();
                    if (chosen.size < Number(group.min_selections || 0)) {
                        frappe.msgprint(`Selecciona al menos ${group.min_selections} opción(es) en "${this.escape(group.group_name)}".`);
                        return;
                    }
                }
                dialog.hide();
                frappe.show_alert({
                    message: "Simulación verificada. En el futuro POS esta selección se agregará a la orden.",
                    indicator: "green",
                });
            },
        });
        const wrapper = dialog.fields_dict.preview_area.$wrapper[0];
        const renderPreview = () => {
            wrapper.innerHTML = "";
            let extraTotal = 0;
            for (const group of activeGroups) {
                const chosen = selections.get(group.name) || new Set();
                const block = document.createElement("div");
                block.style.cssText = "margin-bottom:18px";
                block.innerHTML = `<div style="margin-bottom:8px"><strong style="font-size:14px">${this.escape(group.group_name)}</strong> <em class="text-muted" style="font-size:12px;margin-left:6px">${this.escape(this.selectionBadge(group))}</em></div>`;
                const grid = document.createElement("div");
                grid.style.cssText = "display:flex;gap:10px;flex-wrap:wrap";
                (group.options || []).forEach((opt, idx) => {
                    const active = chosen.has(idx);
                    const surcharge = Number(opt.additional_amount || 0);
                    if (active) extraTotal += surcharge;
                    const btn = document.createElement("button");
                    btn.type = "button";
                    btn.style.cssText = `display:inline-flex;align-items:center;gap:8px;padding:10px 14px;border-radius:6px;cursor:pointer;font-size:13px;border:1.5px solid ${active ? "#0284c7" : "#cbd5e1"};background:${active ? "#e0f2fe" : "#fff"};color:#0f172a;transition:all .15s ease`;
                    const pill = surcharge > 0 ? `<span style="background:#0891b2;color:#fff;padding:2px 8px;border-radius:999px;font-weight:700;font-size:11px">+ ${this.escape(this.money(surcharge, group.currency))}</span>` : "";
                    btn.innerHTML = `<span>${this.escape(opt.option_label)}</span>${pill}`;
                    btn.addEventListener("click", () => {
                        const max = Number(group.max_selections || 1);
                        const min = Number(group.min_selections || 0);
                        if (max === 1) {
                            if (active && min === 0) chosen.clear();
                            else {
                                chosen.clear();
                                chosen.add(idx);
                            }
                        } else if (active) {
                            chosen.delete(idx);
                        } else if (chosen.size < max) {
                            chosen.add(idx);
                        } else {
                            frappe.show_alert({ message: `Máximo ${max} opciones en ${group.group_name}`, indicator: "orange" });
                            return;
                        }
                        renderPreview();
                    });
                    grid.appendChild(btn);
                });
                block.appendChild(grid);
                wrapper.appendChild(block);
            }
            const footer = document.createElement("div");
            footer.style.cssText = "display:flex;justify-content:space-between;align-items:center;padding-top:12px;border-top:1px solid var(--border-color);font-size:15px";
            footer.innerHTML = `<span class="text-muted" style="font-size:12px">Vista previa interactiva de configuración (sin impacto en ventas ni stock)</span><strong>Total: ${this.escape(this.money(basePrice + extraTotal, currency))}</strong>`;
            wrapper.appendChild(footer);
        };
        renderPreview();
        dialog.show();
    }
}

})();
