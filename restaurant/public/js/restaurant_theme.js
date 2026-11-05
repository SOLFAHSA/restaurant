// A theme is a navigation context, never a global Desk palette.
(() => {
    if (frappe.restaurant_theme) return;
    const storageKey = "leaf.restaurant.theme.v1";
    const ownPages = new Set(["restaurant-location", "restaurant-table-map"]);
    const ownTypes = new Set(["Restaurant Area", "Restaurant Table", "Restaurant Option Group", "Restaurant Dish Option"]);
    const sharedTypes = new Set(["Item", "Item Group", "Item Price", "Price List", "Customer", "Employee", "Designation", "Branch", "UOM"]);
    const reports = new Set(["Sales Analytics", "Sales Register", "Item-wise Sales Register"]);
    let active = false;
    let workspace = false;
    let pendingRoute = null;
    let modalOrigin = false;
    let previousRoute = [];
    let scheduled = false;
    const routeKey = route => route.slice(0, 2).join("/");
    const isWorkspace = route => route[0] === "Workspaces" && ["Restaurante", "Restaurant"].includes(route[1]);
    const isOwn = route => ownPages.has(route[0]) || (["List", "Form", "Tree"].includes(route[0]) && ownTypes.has(route[1]));
    const isShared = route => (["List", "Form", "Tree"].includes(route[0]) && sharedTypes.has(route[1])) || (route[0] === "query-report" && reports.has(route[1]));
    try {
        const saved = JSON.parse(sessionStorage.getItem(storageKey) || "null");
        active = Boolean(saved && saved.path === location.pathname && saved.active);
    } catch (error) { /* Storage may be disabled by the browser. */ }

    function remember() {
        try {
            if (active) sessionStorage.setItem(storageKey, JSON.stringify({ active: true, path: location.pathname }));
            else sessionStorage.removeItem(storageKey);
        } catch (error) { /* The in-memory context still works. */ }
    }
    function markWorkspaceAction() {
        if (!workspace) return;
        const label = encodeURIComponent(__("Create Workspace"));
        document.querySelectorAll(".page-actions .custom-actions button[data-label]").forEach(button => {
            if (button.dataset.label === label) button.classList.add("restaurant-create-workspace");
        });
    }
    function apply() {
        document.body.classList.toggle("restaurant-theme-context", active);
        document.body.classList.toggle("restaurant-theme-workspace", workspace);
        remember();
        markWorkspaceAction();
    }
    function update() {
        const route = frappe.get_route();
        // Desk assets can load before the router establishes its initial route.
        if (!Array.isArray(route) || !route.length) return;
        workspace = isWorkspace(route);
        if (workspace || isOwn(route)) active = true;
        else if (pendingRoute && pendingRoute === routeKey(route) && isShared(route)) active = true;
        else if (isShared(route) && active && (isShared(previousRoute) || isOwn(previousRoute) || !previousRoute.length)) active = true;
        else active = false;
        pendingRoute = null;
        previousRoute = route.slice();
        apply();
    }
    frappe.restaurant_theme = {
        enter(route) { pendingRoute = routeKey(route); if (!isShared(route) && !isOwn(route)) active = false; },
        clear() { active = false; workspace = false; pendingRoute = null; modalOrigin = false; apply(); },
        refresh: update,
    };
    document.addEventListener("awesomplete-select", event => {
        if (event.target.id === "navbar-search") {
            frappe.restaurant_theme.clear();
            frappe.restaurant_item_navigation = false;
        }
    }, true);
    function recordOrigin(event) {
        const path = event.composedPath?.() || [event.target];
        modalOrigin = active && path.some(node => node.matches?.(".page-container, .restaurant-theme-dialog")) && !path.some(node => node.matches?.(".navbar"));
    }
    document.addEventListener("click", recordOrigin, true);
    document.addEventListener("keydown", recordOrigin, true);
    $(document).on("show.bs.modal.restaurantTheme", ".modal", function () {
        this.classList.toggle("restaurant-theme-dialog", active && modalOrigin);
    });
    // Bootstrap can emit show before a newly created dialog is attached to the DOM.
    $(document).on("frappe.ui.Dialog:shown.restaurantTheme", () => {
        const modal = window.cur_dialog?.$wrapper?.[0];
        modal?.classList.toggle("restaurant-theme-dialog", active && modalOrigin);
    });
    frappe.router.on("change", update);
    new MutationObserver(() => {
        if (!workspace || scheduled) return;
        scheduled = true;
        requestAnimationFrame(() => { scheduled = false; markWorkspaceAction(); });
    }).observe(document.body, { childList: true, subtree: true });
    update();
})();
