import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

// "Load Image (Edit Mode)" companion.
//
// Picker: the native image_upload widget (All / Imported / Generated + upload).
// Preview: the native inline preview is hardcoded to node.type === "LoadImage"
// and only renders in the editor anyway, so we add our own <img> DOM widget for
// the APP/run panel. DOM widgets render in both editor and app mode, which would
// double up with the native editor preview — so we gate our <img> to app mode
// only via a CSS ancestor selector (the app panel wraps widgets in
// [data-testid="app-mode-widget-item"] / "builder-widget-item"). Pure CSS, so it
// follows the element as the frontend re-parents it between modes.
// Refresh: a "refresh / newest" button + auto-snap to the newest output on run
// completion (GET /ranomany/latest-output for true mtime).

const CLASS = "RanomanyLoadImageEdit";

// Inject the app-mode gating CSS once.
(function injectStyle() {
    const id = "ranomany-load-preview-style";
    if (document.getElementById(id)) return;
    const s = document.createElement("style");
    s.id = id;
    s.textContent =
        ".ranomany-load-preview{display:none;}" +
        '[data-testid="app-mode-widget-item"] .ranomany-load-preview,' +
        '[data-testid="builder-widget-item"] .ranomany-load-preview{display:flex;}';
    document.head.appendChild(s);
})();

// Build a /view URL from a picker value like "sub/dir/name.png [output]".
function viewURL(value) {
    let v = (value || "").trim();
    let type = "input";
    const m = v.match(/ \[([^\]]+)\]$/);
    if (m) {
        type = m[1];
        v = v.slice(0, -m[0].length);
    }
    if (!v) return "";
    let subfolder = "";
    let filename = v;
    const i = v.lastIndexOf("/");
    if (i !== -1) {
        subfolder = v.slice(0, i);
        filename = v.slice(i + 1);
    }
    const p = new URLSearchParams({ filename, subfolder, type });
    return api.apiURL(`/view?${p}&t=${Date.now()}`);
}

function updatePreview(node) {
    const img = node.__ranomanyPreviewImg;
    if (!img) return;
    const w = node.widgets?.find((w) => w.name === "image");
    const url = viewURL(w?.value);
    if (url) {
        img.src = url;
        img.style.display = "";
    } else {
        img.removeAttribute("src");
        img.style.display = "none";
    }
}

async function fetchNewest() {
    try {
        const r = await api.fetchApi("/ranomany/latest-output");
        const d = await r.json();
        return d && d.filename ? d : null;
    } catch (e) {
        console.warn("[Ranomany] latest-output failed", e);
        return null;
    }
}

function annotatedValue(d) {
    const rel = d.subfolder ? `${d.subfolder}/${d.filename}` : d.filename;
    return `${rel} [output]`;
}

function applyNewestToNode(node, d) {
    const w = node.widgets?.find((w) => w.name === "image");
    if (!w) return;
    const val = annotatedValue(d);
    const opts = w.options?.values;
    if (Array.isArray(opts) && !opts.includes(val)) opts.push(val);
    if (w.value !== val) {
        w.value = val;
        try {
            w.callback?.(val);
        } catch {}
    }
    updatePreview(node);
}

function loaderNodes() {
    return (app.graph?._nodes ?? []).filter((n) => n.comfyClass === CLASS);
}

app.registerExtension({
    name: "Ranomany.LoadImageFromOutput",

    async nodeCreated(node) {
        if (node.comfyClass !== CLASS) return;

        // <img> preview as a DOM widget, gated to app mode via the CSS class.
        const img = document.createElement("img");
        img.style.cssText =
            "max-width:100%;max-height:220px;object-fit:contain;display:none;border-radius:4px;background:#111;";
        const wrap = document.createElement("div");
        wrap.className = "ranomany-load-preview";
        wrap.style.cssText =
            "width:100%;align-items:center;justify-content:center;min-height:48px;";
        wrap.appendChild(img);
        node.__ranomanyPreviewImg = img;
        node.addDOMWidget("preview", "image-preview", wrap, { serialize: false });

        // Keep the preview in sync when the user picks/uploads a different image.
        const w = node.widgets?.find((w) => w.name === "image");
        if (w) {
            const orig = w.callback;
            w.callback = function (v) {
                orig?.apply(this, arguments);
                updatePreview(node);
            };
        }

        // Manual "refresh / newest" button.
        node.addWidget("button", "refresh / newest", null, async () => {
            const d = await fetchNewest();
            if (d) {
                applyNewestToNode(node, d);
                app.graph?.setDirtyCanvas(true, true);
            }
        });

        // Initial preview (covers values restored from a saved workflow).
        const origConfigure = node.onConfigure;
        node.onConfigure = function () {
            origConfigure?.apply(this, arguments);
            updatePreview(node);
        };
        requestAnimationFrame(() => updatePreview(node));
    },

    setup() {
        // On run completion, snap every instance to the newest output image.
        api.addEventListener("execution_success", async () => {
            const nodes = loaderNodes();
            if (!nodes.length) return;
            const d = await fetchNewest();
            if (!d) return;
            for (const n of nodes) applyNewestToNode(n, d);
            app.graph?.setDirtyCanvas(true, true);
        });
    },
});
