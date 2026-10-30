// Extend the native Desk sprite so Workspace icons also work in the icon picker.
(() => {
    const sprite = document.getElementById("frappe-symbols");
    if (!sprite || document.getElementById("icon-restaurant")) {
        return;
    }

    const namespace = "http://www.w3.org/2000/svg";
    const symbol = document.createElementNS(namespace, "symbol");
    symbol.id = "icon-restaurant";
    symbol.setAttribute("viewBox", "0 0 24 24");

    const group = document.createElementNS(namespace, "g");
    group.setAttribute("fill", "none");
    group.setAttribute("stroke", "var(--icon-stroke)");
    group.setAttribute("stroke-width", "1.5");
    group.setAttribute("stroke-linecap", "round");
    group.setAttribute("stroke-linejoin", "round");

    const paths = [
        "M3 3v5a2 2 0 0 0 4 0V3M5 3v18",
        "M16 12a4 4 0 1 1-8 0 4 4 0 0 1 8 0Z",
        "M21 3c-2 2-3 4-3 7h3V3Zm0 7v11",
    ];
    paths.forEach((data) => {
        const path = document.createElementNS(namespace, "path");
        path.setAttribute("d", data);
        group.appendChild(path);
    });
    symbol.appendChild(group);
    sprite.appendChild(symbol);
})();
