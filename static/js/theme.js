// Shared theme toggle, used by both index.html and reports.html. Pages
// that need to redraw anything JS-rendered (e.g. the treemap's SVG
// colors, which CSS variables alone can't reach) define a global
// onThemeChange(theme) function before this script runs; it's optional.

function applyThemeToggleLabel(theme) {
    var btn = document.getElementById("theme-toggle");
    if (btn) btn.textContent = theme === "dark" ? "Light mode" : "Dark mode";
}

function setTheme(theme) {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem("theme", theme);
    applyThemeToggleLabel(theme);
    if (typeof onThemeChange === "function") onThemeChange(theme);
}

document.addEventListener("DOMContentLoaded", function() {
    applyThemeToggleLabel(document.documentElement.getAttribute("data-theme") || "light");
    var btn = document.getElementById("theme-toggle");
    if (btn) {
        btn.addEventListener("click", function() {
            var next = document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark";
            setTheme(next);
        });
    }
});
