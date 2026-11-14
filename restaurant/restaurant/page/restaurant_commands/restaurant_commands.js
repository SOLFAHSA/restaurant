frappe.pages["restaurant-commands"].on_page_load = function (wrapper) {
    wrapper.restaurant_commands = new RestaurantCommandsPage(wrapper);
};
frappe.pages["restaurant-commands"].on_page_show = function (wrapper) {
    wrapper.restaurant_commands.load();
};

class RestaurantCommandsPage {
    constructor(wrapper) {
        this.page = frappe.ui.make_app_page({ parent: wrapper, title: "Comandas", single_column: true });
        this.root = $('<div class="rc-page"></div>').appendTo(this.page.body)[0];
        this.start = 0;
        this.search = "";
        this.requestId = 0;
        this.page.set_secondary_action("Volver al restaurante", () => frappe.set_route("Workspaces", "Restaurante"));
        this.root.innerHTML = `
            <div class="rc-intro"><h2>Comandas</h2><p>Asigna los grupos de platillos a los destinos de preparación de cada sucursal.</p></div>
            <div class="rc-tools"><input class="form-control rc-search" type="search" maxlength="140" placeholder="Buscar comanda o sucursal" aria-label="Buscar comanda o sucursal"><span class="rc-status" role="status" aria-live="polite"></span></div>
            <div class="rc-table-wrap" aria-busy="true"><table class="table rc-table">
                <thead><tr><th>Comanda</th><th>Sucursal</th><th>Impresora / Salida</th><th>Grupos asignados</th><th>Estado</th><th><span class="sr-only">Acciones</span></th></tr></thead>
                <tbody></tbody></table></div>
            <nav class="rc-pagination" aria-label="Paginación de comandas"><button type="button" class="btn btn-default" data-action="previous" disabled>Anterior</button><span data-range></span><button type="button" class="btn btn-default" data-action="next" disabled>Siguiente</button></nav>
            <p class="rc-note">Un grupo puede estar en varias comandas de la misma sucursal. Esta pantalla configura destinos; el envío desde el POS se conectará en la siguiente etapa.</p>`;
        this.root.querySelector(".rc-search").addEventListener("input", event => {
            this.search = event.target.value;
            this.start = 0;
            // Immediately invalidate old responses, even during the debounce.
            ++this.requestId;
            clearTimeout(this.timer);
            this.timer = setTimeout(() => this.load(), 250);
        });
        this.root.addEventListener("click", event => {
            const target = event.target.closest("[data-action]");
            if (!target) return;
            if (target.dataset.action === "edit") this.openEditor(target.dataset.name);
            if (this.loading) return;
            if (target.dataset.action === "previous") { this.start = Math.max(0, this.start - 20); this.load(); }
            if (target.dataset.action === "next") { this.start += 20; this.load(); }
            if (target.dataset.action === "retry") this.load();
        });
    }

    escape(value) {
        return frappe.utils.escape_html(String(value == null ? "" : value));
    }

    async load() {
        clearTimeout(this.timer);
        const requestId = ++this.requestId;
        this.loading = true;
        this.root.querySelector(".rc-table-wrap").setAttribute("aria-busy", "true");
        this.root.querySelector(".rc-status").innerHTML = frappe.leaf_loader
            ? frappe.leaf_loader.html("Cargando…", true)
            : "Cargando…";
        this.root.querySelectorAll(".rc-pagination button").forEach(button => { button.disabled = true; });
        try {
            const response = await frappe.call({
                method: "restaurant.commands.get_commands",
                args: { search: this.search, start: this.start, page_length: 20 },
            });
            if (requestId !== this.requestId) return;
            const context = response.message;
            this.page.clear_primary_action();
            if (context.can_create) this.page.set_primary_action("Nueva comanda", () => this.openEditor(), "add");
            this.page.clear_inner_toolbar();
            if (context.can_view_formats) this.page.add_inner_button("Formatos de impresión", () => {
                frappe.set_route("List", "Print Format");
            });
            this.root.querySelector("tbody").innerHTML = context.items.length ? context.items.map(row => `
                <tr><td><strong>${this.escape(row.command_name)}</strong></td><td>${this.escape(row.branch)}</td>
                <td><span class="rc-chip">${this.escape(row.print_mode || "Impresora del navegador")}${row.printer_ip ? ` (${this.escape(row.printer_ip)}:${row.printer_port || 9100})` : (row.network_printer ? ` (${this.escape(row.network_printer)})` : "")}</span></td>
                <td><div class="rc-chips">${row.groups.map(group => `<span class="rc-chip">${this.escape(group)}</span>`).join("")}</div></td>
                <td><span class="rc-state ${row.enabled ? "" : "is-disabled"}">${row.enabled ? "Activa" : "Inactiva"}</span></td>
                <td><button type="button" class="btn btn-default btn-sm" data-action="edit" data-name="${this.escape(row.name)}">${row.can_write ? "Editar" : "Ver"}</button></td></tr>
            `).join("") : '<tr><td colspan="6" class="rc-empty">No hay comandas para mostrar.<p>Crea una comanda o cambia la búsqueda.</p></td></tr>';
            this.root.querySelector('[data-action="previous"]').disabled = this.start === 0;
            this.root.querySelector('[data-action="next"]').disabled = !context.has_next;
            this.root.querySelector("[data-range]").textContent = context.items.length ? `${this.start + 1}–${this.start + context.items.length}` : "0 registros";
            this.root.querySelector(".rc-status").textContent = "";
        } catch (error) {
            if (requestId !== this.requestId) return;
            this.root.querySelector("tbody").innerHTML = '<tr><td colspan="6" class="rc-empty">No se pudieron cargar las comandas. <button type="button" class="btn btn-default" data-action="retry">Reintentar</button></td></tr>';
            this.root.querySelector(".rc-status").textContent = "Error al cargar";
        } finally {
            if (requestId === this.requestId) {
                this.loading = false;
                this.root.querySelector(".rc-table-wrap").setAttribute("aria-busy", "false");
            }
        }
    }

    async openEditor(name = null) {
        if (this.opening) return;
        this.opening = true;
        let context;
        try {
            context = (await frappe.call({ method: "restaurant.commands.get_editor_context", args: { name } })).message;
        } finally { this.opening = false; }
        const doc = context.doc;
        const selected = new Set((doc.groups || []).map(row => row.item_group));
        const known = new Set(context.groups.map(group => group.name));
        const unavailable = [...selected].filter(group => !known.has(group));
        // Keep saved hidden selections until the user has permission to edit them.
        const editable = context.can_write && !unavailable.length;
        let saving = false;
        const dialog = new frappe.ui.Dialog({
            title: name ? "Editar comanda" : "Nueva comanda",
            size: "large",
            fields: [
                { fieldname: "command_name", fieldtype: "Data", label: "Nombre o descripción de la comanda", reqd: 1, default: doc.command_name || "", read_only: !editable },
                { fieldname: "branch", fieldtype: "Link", label: "Sucursal", options: "Branch", reqd: 1, default: doc.branch || "", read_only: !editable },
                { fieldname: "enabled", fieldtype: "Check", label: "Activa", default: name ? doc.enabled : 1, read_only: !editable },
                { fieldname: "printer_section", fieldtype: "Section Break", label: "Configuración de Impresora de Estación" },
                { fieldname: "print_mode", fieldtype: "Select", label: "Modo de impresión de comanda", options: "Impresora del navegador\nImpresora de red directa (ESC/POS IP:Puerto)\nNetwork Printer Settings (CUPS)\nSolo KDS (Sin ticket físico)", default: doc.print_mode || "Impresora del navegador", read_only: !editable },
                { fieldname: "auto_print_on_send", fieldtype: "Check", label: "Imprimir automáticamente al pulsar Enviar", default: name ? (doc.auto_print_on_send ?? 1) : 1, read_only: !editable },
                { fieldname: "paper_width_mm", fieldtype: "Select", label: "Ancho de papel térmico", options: "80mm\n58mm", default: doc.paper_width_mm || "80mm", read_only: !editable },
                { fieldname: "printer_col", fieldtype: "Column Break" },
                { fieldname: "network_printer", fieldtype: "Link", label: "Impresora de red Frappe (Network Printer Settings)", options: "Network Printer Settings", default: doc.network_printer || "", read_only: !editable },
                { fieldname: "printer_ip", fieldtype: "Data", label: "IP de impresora térmica (ESC/POS)", default: doc.printer_ip || "", read_only: !editable },
                { fieldname: "printer_port", fieldtype: "Int", label: "Puerto TCP (9100)", default: doc.printer_port || 9100, read_only: !editable },
                { fieldname: "groups_section", fieldtype: "Section Break", label: "Grupos asignados" },
                { fieldname: "group_picker", fieldtype: "HTML" },
            ],
            primary_action_label: "Guardar",
            primary_action: async values => {
                if (!editable || saving) return;
                if (!selected.size) { frappe.msgprint("Selecciona al menos un grupo para la comanda."); return; }
                saving = true;
                dialog.disable_primary_action();
                try {
                    await frappe.call({
                        method: "restaurant.commands.save_command",
                        args: { document: {
                            doctype: "Restaurant Command", ...(name ? { name, modified: doc.modified } : {}),
                            ...values, groups: [...selected].map(item_group => ({ item_group })),
                        } },
                        freeze: true, freeze_message: "Guardando comanda…",
                    });
                    dialog.hide();
                    frappe.show_alert({ message: "Comanda guardada", indicator: "green" });
                    await this.load();
                } catch (error) {
                    // Keep inputs and selections available after a server validation error.
                } finally { saving = false; dialog.enable_primary_action(); }
            },
            secondary_action_label: "Cancelar",
            secondary_action: () => { if (!saving) dialog.hide(); },
        });
        const picker = dialog.fields_dict.group_picker.$wrapper[0];
        picker.classList.add("rc-picker");
        picker.innerHTML = `
            <p class="text-muted">Marca los grupos que recibirá esta comanda. La selección es exacta: marcar un grupo padre no marca sus subgrupos. Puedes asignar un grupo a varias comandas.</p>
            <div class="rc-picker-tools"><input type="search" class="form-control" placeholder="Buscar grupo" aria-label="Buscar grupo"><span role="status" aria-live="polite" data-selected-count></span></div>
            <div class="rc-group-list"></div>
            ${unavailable.length ? '<p class="text-warning">Hay grupos asignados que no puedes consultar. Solicita acceso antes de editar esta comanda.</p>' : ""}`;
        const list = picker.querySelector(".rc-group-list");
        const updateCount = () => { picker.querySelector("[data-selected-count]").textContent = `${selected.size} seleccionados`; };
        const renderGroups = search => {
            const filtered = context.groups.filter(group => group.name.toLocaleLowerCase().includes(search.toLocaleLowerCase()));
            list.innerHTML = filtered.length ? filtered.map(group => `
                <label class="rc-group-option"><input type="checkbox" value="${this.escape(group.name)}" ${selected.has(group.name) ? "checked" : ""} ${editable ? "" : "disabled"}>
                <span><strong>${this.escape(group.name)}</strong>${group.parent_item_group ? `<small>${this.escape(group.parent_item_group)}</small>` : (group.parent_item_group === "" ? '<small>Grupo raíz</small>' : "")}</span>
                ${group.is_group ? '<span class="rc-parent">Grupo padre</span>' : ""}</label>
            `).join("") : '<p class="rc-empty">No hay grupos disponibles para esta búsqueda.</p>';
        };
        picker.querySelector('input[type="search"]').addEventListener("input", event => renderGroups(event.target.value));
        list.addEventListener("change", event => {
            if (!editable || !event.target.matches('input[type="checkbox"]')) return;
            if (event.target.checked) selected.add(event.target.value); else selected.delete(event.target.value);
            updateCount();
        });
        renderGroups("");
        updateCount();
        dialog.show();
        if (!editable) dialog.get_primary_btn().hide();
    }
}
