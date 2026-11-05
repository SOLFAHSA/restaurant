frappe.pages["restaurant-table-map"].on_page_load = function (wrapper) {
	wrapper.restaurant_table_map = new RestaurantTableMapPage(wrapper);
};

frappe.pages["restaurant-table-map"].on_page_show = function (wrapper) {
	wrapper.restaurant_table_map.show();
};

const CATALOG_ITEMS = {
	tables: [
		{ subtype: "table_square_wood", label: "Mesa cuadrada", width: 90, height: 90, shape: "Cuadrada" },
		{ subtype: "table_round_wood", label: "Mesa redonda", width: 90, height: 90, shape: "Redonda" },
		{ subtype: "table_rect_wood", label: "Mesa rectangular", width: 130, height: 86, shape: "Rectangular" },
		{ subtype: "table_oval_wood", label: "Mesa ovalada", width: 130, height: 86, shape: "Ovalada" },
		{ subtype: "table_court_blue", label: "Cancha azul", width: 96, height: 96, shape: "Cancha azul" },
		{ subtype: "table_court_soccer", label: "Cancha fútbol", width: 96, height: 96, shape: "Cancha fútbol" },
		{ subtype: "table_court_basket", label: "Cancha básquetbol", width: 96, height: 96, shape: "Cancha básquetbol" },
	],
	chairs: [
		{ subtype: "chair_wood", label: "Silla comedor", width: 48, height: 48 },
		{ subtype: "chair_armchair_red", label: "Butaca roja", width: 54, height: 54 },
		{ subtype: "chair_stool_orange", label: "Taburete naranja", width: 44, height: 44 },
	],
	decor: [
		{ subtype: "decor_palm", label: "Palmera en maceta", width: 86, height: 86 },
		{ subtype: "decor_fern", label: "Planta decorativa", width: 74, height: 74 },
		{ subtype: "decor_wall_h", label: "Muro horizontal", width: 160, height: 24 },
		{ subtype: "decor_wall_v", label: "Muro vertical", width: 24, height: 160 },
		{ subtype: "decor_wall_corner", label: "Esquina de muro", width: 88, height: 88 },
		{ subtype: "decor_door", label: "Puerta abatible", width: 88, height: 88 },
		{ subtype: "decor_restroom", label: "Señal baños", width: 64, height: 64 },
		{ subtype: "decor_label", label: "Texto de zona", width: 120, height: 42 },
	],
	backgrounds: [
		{ value: "Madera cálida", label: "Madera cálida", css: "bg-warm-wood" },
		{ value: "Cerámica clara", label: "Cerámica clara", css: "bg-light-tile" },
		{ value: "Madera gris", label: "Madera gris", css: "bg-grey-wood" },
		{ value: "Césped", label: "Césped", css: "bg-grass" },
	],
};

class RestaurantTableMapPage {
	constructor(wrapper) {
		this.wrapper = wrapper;
		$(wrapper).addClass("restaurant-table-map-page");
		this.page = frappe.ui.make_app_page({
			parent: wrapper,
			title: "Mapa de Mesas",
			single_column: true,
		});
		this.root = $(frappe.render_template("restaurant_table_map")).appendTo(this.page.body)[0];
		this.mode = "design";
		this.activeModalTab = "tables";
		this.modalOpen = false;
		this.selectedId = null;
		this.dirty = false;
		this.elements = [];
		this.tables = [];
		this.areas = [];
		this.area = null;
		this.permissions = {};
		this.dragState = null;

		this.root.addEventListener("click", (event) => this.handleClick(event));
		this.root.addEventListener("change", (event) => this.handleChange(event));
		this.root.addEventListener("input", (event) => this.handleInput(event));
		this.root.addEventListener("pointerdown", (event) => this.handlePointerDown(event));
		window.addEventListener("pointermove", (event) => this.handlePointerMove(event));
		window.addEventListener("pointerup", () => this.handlePointerUp());
	}

	escape(value) {
		return frappe.utils.escape_html(String(value == null ? "" : value));
	}

	backgroundClass(bgName) {
		const found = CATALOG_ITEMS.backgrounds.find((item) => item.value === bgName);
		return found ? found.css : "bg-warm-wood";
	}

	async show() {
		const route = frappe.get_route();
		const requestedArea = route[1] || (this.area ? this.area.name : null);
		await this.loadContext(requestedArea);
	}

	async loadContext(areaName = null) {
		this.root.innerHTML = '<div class="rtm-empty-state" role="status">Cargando mapa de mesas…</div>';
		try {
			const res = await frappe.call({
				method: "restaurant.table_management.get_map_context",
				args: { area_name: areaName },
			});
			const data = res.message || {};
			this.areas = data.areas || [];
			this.area = data.area || null;
			this.elements = Array.isArray(data.elements) ? data.elements : [];
			this.tables = Array.isArray(data.tables) ? data.tables : [];
			this.permissions = data.permissions || {};
			this.dirty = false;
			if (this.selectedId && !this.elements.some((el) => el.id === this.selectedId)) {
				this.selectedId = this.elements[0]?.id || null;
			} else if (!this.selectedId && this.elements.length) {
				this.selectedId = this.elements[0].id;
			}
			this.render();
		} catch (error) {
			this.root.innerHTML = '<div class="rtm-empty-state" role="alert"><h2>No fue posible cargar el mapa</h2><p>Verifica tus permisos e inténtalo nuevamente.</p></div>';
		}
	}

	selectedElement() {
		return this.elements.find((el) => el.id === this.selectedId) || null;
	}

	tableByName(tableName) {
		if (!tableName) return null;
		return this.tables.find((row) => row.name === tableName) || null;
	}

	statusSummary() {
		const counts = { Disponible: 0, Ocupada: 0, Reservada: 0 };
		for (const row of this.tables) {
			if (counts[row.status] !== undefined) counts[row.status] += 1;
		}
		return counts;
	}

	render() {
		if (!this.areas.length || !this.area) {
			this.root.innerHTML = `
				<header class="rtm-header">
					<div class="rtm-title-group">
						<button type="button" class="rtm-back-btn" data-action="back-workspace" aria-label="Volver al restaurante">${this.iconSvg("back")}</button>
						<h1>Mapa de Mesas</h1>
					</div>
				</header>
				<div class="rtm-empty-state">
					<h2>Aún no hay áreas registradas</h2>
					<p>Crea primero un área o salón (por ejemplo, Salón Principal o Terraza) para diseñar su mapa de mesas.</p>
					${this.permissions.can_create_area ? '<button type="button" class="rtm-btn rtm-btn-sky" data-action="new-area">+ NUEVA ÁREA</button>' : ""}
				</div>
			`;
			return;
		}

		const canEdit = Boolean(this.permissions.can_write_area);
		const selected = this.selectedElement();
		const widthVal = selected ? selected.width : 90;
		const heightVal = selected ? selected.height : 90;
		const rotationVal = selected ? selected.rotation : 0;
		const counts = this.statusSummary();

		this.root.className = `rtm-app ${this.mode === "operational" ? "is-operational" : ""}`;
		this.root.innerHTML = `
			<header class="rtm-header">
				<div class="rtm-title-group">
					<button type="button" class="rtm-back-btn" data-action="back-workspace" aria-label="Volver al restaurante" title="Volver al panel de Restaurante">${this.iconSvg("back")}</button>
					<h1>Mapa de Mesas</h1>
					<div class="rtm-status-counters" aria-label="Resumen de estado de mesas">
						<span class="rtm-counter-pill" title="Mesas disponibles"><span class="rtm-counter-dot" style="background:#22c55e"></span>${counts.Disponible} disponibles</span>
						<span class="rtm-counter-pill" title="Mesas ocupadas"><span class="rtm-counter-dot" style="background:#15803d"></span>${counts.Ocupada} ocupadas</span>
						<span class="rtm-counter-pill" title="Mesas reservadas"><span class="rtm-counter-dot" style="background:#ef4444"></span>${counts.Reservada} reservadas</span>
					</div>
				</div>
				<div class="rtm-header-right">
					<div class="rtm-mode-switch" role="tablist" aria-label="Modo del mapa">
						<button type="button" class="rtm-mode-btn ${this.mode === "design" ? "is-active" : ""}" data-action="set-mode" data-mode="design">Editor del mapa</button>
						<button type="button" class="rtm-mode-btn ${this.mode === "operational" ? "is-active" : ""}" data-action="set-mode" data-mode="operational">Vista operativa</button>
					</div>
					<button type="button" class="rtm-btn rtm-btn-outline" data-action="open-area-editor">Configurar área (${this.tables.length} mesas)</button>
					<button type="button" class="rtm-btn rtm-btn-outline" data-action="open-table-list">Catálogo de mesas</button>
				</div>
			</header>

			<div class="rtm-topbar">
				<div class="rtm-area-picker">
					<select class="rtm-area-select" data-role="area-select" aria-label="Seleccionar área del restaurante">
						${this.areas.map((item) => `<option value="${this.escape(item.name)}" ${item.name === this.area.name ? "selected" : ""}>${this.escape(item.area_name)}</option>`).join("")}
					</select>
					${this.permissions.can_create_area ? '<button type="button" class="rtm-btn rtm-btn-sky" data-action="new-area">+ NUEVO</button>' : ""}
				</div>
				<div class="rtm-top-actions">
					${canEdit && this.mode === "design" ? `
						<button type="button" class="rtm-btn rtm-btn-clear" data-action="clear-map">${this.iconSvg("refresh")} LIMPIAR</button>
						<button type="button" class="rtm-btn rtm-btn-save" data-action="save-map">${this.iconSvg("save")} GUARDAR</button>
					` : ""}
				</div>
			</div>

			<div class="rtm-designer-frame">
				<div class="rtm-props-bar">
					<div>
						<button type="button" class="rtm-add-element-btn" data-action="open-catalog" ${canEdit ? "" : "disabled"}>AGREGAR ELEMENTO</button>
					</div>
					<div class="rtm-dimensions-group">
						<label class="rtm-dim-input">
							<span>Ancho</span>
							<input type="number" min="24" max="600" value="${widthVal}" data-prop="width" aria-label="Ancho del elemento" ${selected && canEdit ? "" : "disabled"}/>
						</label>
						<label class="rtm-dim-input">
							<span>Alto</span>
							<input type="number" min="24" max="600" value="${heightVal}" data-prop="height" aria-label="Alto del elemento" ${selected && canEdit ? "" : "disabled"}/>
						</label>
					</div>
					<div class="rtm-rotation-group">
						<span class="rtm-rotation-title">Rotación</span>
						<div class="rtm-rotation-Quick">
							<button type="button" class="rtm-rot-btn" data-action="rotate-quick" data-angle="270" title="270°" ${selected && canEdit ? "" : "disabled"}>&lt;</button>
							<button type="button" class="rtm-rot-btn" data-action="rotate-quick" data-angle="0" title="0°" ${selected && canEdit ? "" : "disabled"}>^</button>
							<button type="button" class="rtm-rot-btn" data-action="rotate-quick" data-angle="180" title="180°" ${selected && canEdit ? "" : "disabled"}>v</button>
							<button type="button" class="rtm-rot-btn" data-action="rotate-quick" data-angle="90" title="90°" ${selected && canEdit ? "" : "disabled"}>&gt;</button>
						</div>
						<div class="rtm-Slider-box">
							<input type="range" min="0" max="360" value="${rotationVal}" data-prop="rotation" aria-label="Rotación del elemento" ${selected && canEdit ? "" : "disabled"}/>
						</div>
					</div>
				</div>

				<div class="rtm-canvas-wrap">
					<div class="rtm-canvas ${this.backgroundClass(this.area.floor_background)}" data-role="canvas">
						${this.elements.map((el) => this.renderCanvasElement(el, canEdit)).join("")}
					</div>
				</div>
			</div>

			<div class="rtm-footer-bar">
				<span>Área activa: <strong>${this.escape(this.area.area_name)}</strong> · Sucursal: <strong>${this.escape(this.area.branch)}</strong> · Fondo: <strong>${this.escape(this.area.floor_background || "Madera cálida")}</strong></span>
				<span>${this.dirty ? "● Cambios pendientes de guardar" : "✓ Diseño sincronizado"}</span>
			</div>

			${this.modalOpen ? this.renderCatalogModal() : ""}
		`;
	}

	renderCanvasElement(el, canEdit) {
		const isSelected = el.id === this.selectedId;
		const linkedTable = el.category === "tables" ? this.tableByName(el.table_name) : null;
		const isRound = el.subtype === "table_round_wood";

		let overlayHtml = "";
		if (el.category === "tables") {
			if (this.mode === "operational") {
				const status = linkedTable ? linkedTable.status : "Disponible";
				const label = linkedTable ? linkedTable.table_number : "?";
				const seats = linkedTable ? `${linkedTable.seats}p` : "Sin asignar";
				overlayHtml = `
					<div class="rtm-op-badge status-${this.escape(status)} ${isRound ? "is-round" : ""}" data-action="op-table-click" data-id="${this.escape(el.id)}">
						<strong>${this.escape(label)}</strong>
						<span>${this.escape(seats)} · ${this.escape(status)}</span>
					</div>
				`;
			} else {
				const btnLabel = linkedTable
					? `MESA ${this.escape(linkedTable.table_number)}<small>${Number(linkedTable.seats) || 4} asientos · ${this.escape(linkedTable.status)}</small>`
					: "ASIGNAR MESA";
				overlayHtml = `
					<button type="button" class="rtm-assign-btn ${linkedTable ? "is-assigned" : ""}" data-action="assign-table" data-id="${this.escape(el.id)}">
						${btnLabel}
					</button>
				`;
			}
		}

		return `
			<div class="rtm-element ${isSelected ? "is-selected" : ""}"
				data-element-id="${this.escape(el.id)}"
				style="left:${Number(el.x) || 0}px;top:${Number(el.y) || 0}px;width:${Number(el.width) || 90}px;height:${Number(el.height) || 90}px;">
				${canEdit ? `
					<div class="rtm-el-controls">
						<button type="button" class="rtm-el-radio" data-action="select-element" data-id="${this.escape(el.id)}" aria-label="Seleccionar elemento"></button>
						<button type="button" class="rtm-el-delete" data-action="delete-element" data-id="${this.escape(el.id)}" aria-label="Eliminar elemento">${this.iconSvg("trash")}</button>
					</div>
				` : ""}
				<div class="rtm-element-art" style="transform:rotate(${Number(el.rotation) || 0}deg)">
					${this.elementArtwork(el.subtype, el.label)}
				</div>
				${overlayHtml}
			</div>
		`;
	}

	renderCatalogModal() {
		const tabTitles = {
			tables: "Mesas",
			chairs: "Sillas",
			decor: "Decoración",
			backgrounds: "Fondos",
		};
		const currentTab = this.activeModalTab || "tables";
		let gridContent = "";
		if (currentTab === "backgrounds") {
			gridContent = CATALOG_ITEMS.backgrounds.map((bg) => `
				<button type="button" class="rtm-catalog-item ${this.area.floor_background === bg.value ? "is-selected" : ""}" data-action="choose-background" data-bg="${this.escape(bg.value)}">
					<div class="rtm-bg-swatch rtm-canvas ${bg.css}" style="min-width:0;height:78px"></div>
					<span>${this.escape(bg.label)}</span>
				</button>
			`).join("");
		} else {
			const list = CATALOG_ITEMS[currentTab] || [];
			gridContent = list.map((item) => `
				<button type="button" class="rtm-catalog-item" data-action="add-catalog-item" data-category="${this.escape(currentTab)}" data-subtype="${this.escape(item.subtype)}">
					<div class="rtm-catalog-thumb">${this.elementArtwork(item.subtype, "Zona")}</div>
					<span>${this.escape(item.label)}</span>
				</button>
			`).join("");
		}

		return `
			<div class="rtm-modal-backdrop" data-action="close-modal-backdrop">
				<div class="rtm-modal" role="dialog" aria-modal="true" aria-label="Seleccione un Elemento">
					<header class="rtm-modal-header">
						<h2>Seleccione un Elemento</h2>
						<button type="button" class="rtm-modal-close" data-action="close-modal" aria-label="Cerrar">&times;</button>
					</header>
					<nav class="rtm-modal-tabs" aria-label="Categorías de elementos">
						<button type="button" class="rtm-tab-btn ${currentTab === "tables" ? "is-active" : ""}" data-action="modal-tab" data-tab="tables">MESAS</button>
						<button type="button" class="rtm-tab-btn ${currentTab === "chairs" ? "is-active" : ""}" data-action="modal-tab" data-tab="chairs">SILLAS</button>
						<button type="button" class="rtm-tab-btn ${currentTab === "decor" ? "is-active" : ""}" data-action="modal-tab" data-tab="decor">DECORACIÓN</button>
						<button type="button" class="rtm-tab-btn ${currentTab === "backgrounds" ? "is-active" : ""}" data-action="modal-tab" data-tab="backgrounds">FONDOS</button>
					</nav>
					<div class="rtm-modal-body">
						<h3 class="rtm-modal-section-title">${tabTitles[currentTab]}</h3>
						<div class="rtm-catalog-grid">${gridContent}</div>
					</div>
					<footer class="rtm-modal-footer">
						<button type="button" class="rtm-modal-close-pill" data-action="close-modal">CERRAR</button>
					</footer>
				</div>
			</div>
		`;
	}

	iconSvg(name) {
		const paths = {
			back: '<path d="M19 12H5m6-6-6 6 6 6"/>',
			trash: '<path d="M3 6h18"/><path d="M8 6V4h8v2"/><path d="M6 6v14h12V6"/>',
			refresh: '<path d="M21 12a9 9 0 1 1-2.64-6.36"/><polyline points="21 3 21 9 15 9"/>',
			save: '<path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/><polyline points="17 21 17 13 7 13 7 21"/>',
		};
		return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" style="width:14px;height:14px">${paths[name] || ""}</svg>`;
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

	addCatalogElement(category, subtype) {
		const list = CATALOG_ITEMS[category] || [];
		const spec = list.find((item) => item.subtype === subtype);
		if (!spec) return;
		const offset = (this.elements.length % 7) * 26;
		const newEl = {
			id: `el_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`,
			category,
			subtype,
			x: 60 + offset,
			y: 60 + offset,
			width: spec.width || 90,
			height: spec.height || 90,
			rotation: 0,
		};
		if (subtype === "decor_label") {
			newEl.label = "Zona";
		}
		this.elements.push(newEl);
		this.selectedId = newEl.id;
		this.modalOpen = false;
		this.dirty = true;
		this.render();
	}

	openAssignTableDialog(elementId) {
		const el = this.elements.find((item) => item.id === elementId);
		if (!el || el.category !== "tables") return;
		const spec = CATALOG_ITEMS.tables.find((item) => item.subtype === el.subtype);
		const defaultShape = spec ? spec.shape : "Cuadrada";

		const usedTableNames = new Set(
			this.elements
				.filter((item) => item.id !== el.id && item.table_name)
				.map((item) => item.table_name)
		);
		const availableTables = this.tables.filter((row) => !usedTableNames.has(row.name));
		const currentTable = this.tableByName(el.table_name);
		const nextNumber = String(this.tables.length + 1);

		const optionsList = [
			{ label: "➕ Crear una mesa nueva para esta posición", value: "__new__" },
			...availableTables.map((row) => ({
				label: `Mesa ${row.table_number} (${row.seats} asientos · ${row.status})`,
				value: row.name,
			})),
		];

		const dialog = new frappe.ui.Dialog({
			title: currentTable ? `Mesa asignada: Mesa ${currentTable.table_number}` : "Asignar mesa al plano",
			fields: [
				{
					fieldname: "assignment_mode",
					fieldtype: "Select",
					label: "Seleccionar mesa del área o crear nueva",
					options: optionsList.map((o) => o.value).join("\n"),
					default: currentTable ? currentTable.name : (availableTables[0]?.name || "__new__"),
					reqd: 1,
				},
				{
					fieldname: "table_number",
					fieldtype: "Data",
					label: "Número o código de mesa",
					default: currentTable ? currentTable.table_number : nextNumber,
					reqd: 1,
				},
				{
					fieldname: "seats",
					fieldtype: "Int",
					label: "Capacidad (asientos)",
					default: currentTable ? currentTable.seats : 4,
					reqd: 1,
				},
				{
					fieldname: "status",
					fieldtype: "Select",
					label: "Estado operativo",
					options: "Disponible\nOcupada\nReservada\nInactiva",
					default: currentTable ? currentTable.status : "Disponible",
					reqd: 1,
				},
			],
			primary_action_label: "Asignar a esta ubicación",
			primary_action: async (values) => {
				if (values.assignment_mode === "__new__") {
					const res = await frappe.call({
						method: "restaurant.table_management.save_table",
						args: {
							document: {
								doctype: "Restaurant Table",
								restaurant_area: this.area.name,
								table_number: values.table_number,
								seats: values.seats,
								shape: defaultShape,
								status: values.status,
							},
						},
						freeze: true,
						freeze_message: "Creando y vinculando mesa…",
					});
					if (res && res.message) {
						this.tables = res.message.tables || [];
						el.table_name = res.message.table.name;
					}
				} else {
					const existing = this.tableByName(values.assignment_mode);
					if (existing && (
						String(existing.table_number) !== String(values.table_number) ||
						Number(existing.seats) !== Number(values.seats) ||
						existing.status !== values.status
					)) {
						const res = await frappe.call({
							method: "restaurant.table_management.save_table",
							args: {
								document: {
									doctype: "Restaurant Table",
									name: existing.name,
									modified: existing.modified,
									restaurant_area: this.area.name,
									table_number: values.table_number,
									seats: values.seats,
									shape: defaultShape,
									status: values.status,
								},
							},
							freeze: true,
							freeze_message: "Actualizando mesa…",
						});
						if (res && res.message) {
							this.tables = res.message.tables || [];
						}
					}
					el.table_name = values.assignment_mode;
				}
				this.dirty = true;
				dialog.hide();
				this.render();
			},
		});

		const selectField = dialog.fields_dict.assignment_mode;
		if (selectField && selectField.$input) {
			selectField.$input.empty();
			for (const opt of optionsList) {
				selectField.$input.append($("<option>", { value: opt.value, text: opt.label }));
			}
			const initialValue = currentTable ? currentTable.name : (availableTables[0]?.name || "__new__");
			selectField.set_value(initialValue);
			selectField.$input.on("change", () => {
				const chosen = this.tableByName(selectField.get_value());
				if (chosen) {
					dialog.set_value("table_number", chosen.table_number);
					dialog.set_value("seats", chosen.seats);
					dialog.set_value("status", chosen.status);
				} else {
					dialog.set_value("table_number", String(this.tables.length + 1));
					dialog.set_value("seats", 4);
					dialog.set_value("status", "Disponible");
				}
			});
			selectField.$input.trigger("change");
		}
		dialog.show();
	}

	openOperationalStatusDialog(elementId) {
		const el = this.elements.find((item) => item.id === elementId);
		if (!el || !el.table_name) {
			frappe.msgprint("Esta mesa aún no tiene un número asignado. Cambia al «Editor del mapa» y haz clic en ASIGNAR MESA.");
			return;
		}
		const table = this.tableByName(el.table_name);
		if (!table) return;
		const dialog = new frappe.ui.Dialog({
			title: `Mesa ${table.table_number} (${table.seats} asientos)`,
			fields: [
				{
					fieldname: "status",
					fieldtype: "Select",
					label: "Estado de la mesa",
					options: "Disponible\nOcupada\nReservada\nInactiva",
					default: table.status,
					reqd: 1,
				},
			],
			primary_action_label: "Actualizar estado",
			primary_action: async (values) => {
				const res = await frappe.call({
					method: "restaurant.table_management.update_table_status",
					args: { table_name: table.name, status: values.status },
					freeze: true,
					freeze_message: "Actualizando estado…",
				});
				if (res && res.message) {
					this.tables = res.message.tables || [];
					frappe.show_alert({ message: `Mesa ${table.table_number}: ${values.status}`, indicator: "green" });
					dialog.hide();
					this.render();
				}
			},
		});
		dialog.show();
	}

	async saveMap() {
		if (!this.area) return;
		const res = await frappe.call({
			method: "restaurant.table_management.save_area_map",
			args: {
				area_name: this.area.name,
				floor_background: this.area.floor_background || "Madera cálida",
				elements: JSON.stringify(this.elements),
				area_modified: this.area.modified,
			},
			freeze: true,
			freeze_message: "Guardando mapa de mesas…",
		});
		if (res && res.message) {
			this.area = res.message.area;
			this.elements = res.message.elements || [];
			this.tables = res.message.tables || [];
			this.dirty = false;
			frappe.show_alert({ message: "Mapa de mesas guardado", indicator: "green" });
			this.render();
		}
	}

	clearMap() {
		if (!this.elements.length) return;
		frappe.confirm("¿Deseas limpiar todos los elementos visuales de este mapa?", () => {
			this.elements = [];
			this.selectedId = null;
			this.dirty = true;
			this.render();
		});
	}

	handleClick(event) {
		const actionEl = event.target.closest("[data-action]");
		if (!actionEl) return;
		const action = actionEl.dataset.action;

		if (action === "back-workspace") {
			frappe.set_route("Workspaces", "Restaurante");
			return;
		}
		if (action === "new-area") {
			frappe.set_route("restaurant-location", "new");
			return;
		}
		if (action === "open-area-editor" && this.area) {
			frappe.set_route("restaurant-location", this.area.name);
			return;
		}
		if (action === "open-table-list") {
			frappe.set_route("List", "Restaurant Table", { restaurant_area: this.area?.name });
			return;
		}
		if (action === "set-mode") {
			this.mode = actionEl.dataset.mode || "design";
			this.render();
			return;
		}
		if (action === "open-catalog") {
			this.modalOpen = true;
			this.render();
			return;
		}
		if (action === "close-modal" || (action === "close-modal-backdrop" && event.target === actionEl)) {
			this.modalOpen = false;
			this.render();
			return;
		}
		if (action === "modal-tab") {
			this.activeModalTab = actionEl.dataset.tab || "tables";
			this.render();
			return;
		}
		if (action === "add-catalog-item") {
			this.addCatalogElement(actionEl.dataset.category, actionEl.dataset.subtype);
			return;
		}
		if (action === "choose-background" && this.area) {
			this.area.floor_background = actionEl.dataset.bg || "Madera cálida";
			this.modalOpen = false;
			this.dirty = true;
			this.render();
			return;
		}
		if (action === "select-element") {
			this.selectedId = actionEl.dataset.id;
			this.render();
			return;
		}
		if (action === "delete-element") {
			const id = actionEl.dataset.id;
			this.elements = this.elements.filter((el) => el.id !== id);
			if (this.selectedId === id) {
				this.selectedId = this.elements[0]?.id || null;
			}
			this.dirty = true;
			this.render();
			return;
		}
		if (action === "assign-table") {
			this.openAssignTableDialog(actionEl.dataset.id);
			return;
		}
		if (action === "op-table-click") {
			this.openOperationalStatusDialog(actionEl.dataset.id);
			return;
		}
		if (action === "rotate-quick") {
			const selected = this.selectedElement();
			if (!selected) return;
			selected.rotation = Number(actionEl.dataset.angle) || 0;
			this.dirty = true;
			this.render();
			return;
		}
		if (action === "clear-map") {
			this.clearMap();
			return;
		}
		if (action === "save-map") {
			this.saveMap();
		}
	}

	handleChange(event) {
		if (event.target.matches('[data-role="area-select"]')) {
			const nextArea = event.target.value;
			frappe.set_route("restaurant-table-map", nextArea);
			this.loadContext(nextArea);
		}
	}

	handleInput(event) {
		const prop = event.target.dataset.prop;
		if (!prop) return;
		const selected = this.selectedElement();
		if (!selected) return;
		const val = Number(event.target.value);
		if (prop === "width" || prop === "height") {
			selected[prop] = Math.max(24, Math.min(600, val || 90));
		} else if (prop === "rotation") {
			selected.rotation = ((val % 360) + 360) % 360;
		}
		this.dirty = true;
		const node = this.root.querySelector(`[data-element-id="${CSS.escape(selected.id)}"]`);
		if (node) {
			node.style.width = `${selected.width}px`;
			node.style.height = `${selected.height}px`;
			const art = node.querySelector(".rtm-element-art");
			if (art) art.style.transform = `rotate(${selected.rotation}deg)`;
		}
	}

	handlePointerDown(event) {
		if (this.mode !== "design" || !this.permissions.can_write_area) return;
		if (event.target.closest("button")) return;
		const elementNode = event.target.closest("[data-element-id]");
		if (!elementNode) return;
		const id = elementNode.dataset.elementId;
		const el = this.elements.find((item) => item.id === id);
		if (!el) return;

		this.selectedId = id;
		const canvas = this.root.querySelector('[data-role="canvas"]');
		const rect = canvas.getBoundingClientRect();
		this.dragState = {
			id,
			startX: event.clientX,
			startY: event.clientY,
			origX: el.x,
			origY: el.y,
			maxX: Math.max(0, rect.width - el.width),
			maxY: Math.max(0, rect.height - el.height),
			node: elementNode,
		};
		this.root.querySelectorAll(".rtm-element").forEach((n) => n.classList.toggle("is-selected", n === elementNode));
		const widthInput = this.root.querySelector('[data-prop="width"]');
		const heightInput = this.root.querySelector('[data-prop="height"]');
		const rotInput = this.root.querySelector('[data-prop="rotation"]');
		if (widthInput) { widthInput.disabled = false; widthInput.value = el.width; }
		if (heightInput) { heightInput.disabled = false; heightInput.value = el.height; }
		if (rotInput) { rotInput.disabled = false; rotInput.value = el.rotation; }
	}

	handlePointerMove(event) {
		if (!this.dragState) return;
		const el = this.elements.find((item) => item.id === this.dragState.id);
		if (!el) return;
		const dx = event.clientX - this.dragState.startX;
		const dy = event.clientY - this.dragState.startY;
		el.x = Math.round(Math.max(0, Math.min(this.dragState.maxX, this.dragState.origX + dx)));
		el.y = Math.round(Math.max(0, Math.min(this.dragState.maxY, this.dragState.origY + dy)));
		this.dragState.node.style.left = `${el.x}px`;
		this.dragState.node.style.top = `${el.y}px`;
		this.dirty = true;
	}

	handlePointerUp() {
		this.dragState = null;
	}
}

