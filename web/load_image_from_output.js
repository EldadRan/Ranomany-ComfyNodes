import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

// "Load Image (from Outputs)" companion.
//
// The native app-mode image preview is hardcoded to node.type === "LoadImage"
// (AppModeWidgetList.vue -> getDropIndicator), so a custom node can't get it.
// Instead we render our own <img> as a DOM widget — DOM widgets ARE rendered in
// the app/run panel (NodeWidgets.vue -> WidgetDOM.vue), the same way the Camera
// Angle 3D widget shows there. That gives a preview in both editor and app mode,
// fully under our control.
//
// Behavior: a plain combo lets the user pick any output image (preview follows
// the selection); a "refresh / newest" button and an automatic snap on run
// completion point it at the newest output image.

const CLASS = "RanomanyLoadImageEdit";

// Build a /view URL from a combo value like "sub/dir/name.png [output]".
function viewURL(value) {
    let v = (value || "").trim();
    let type = "output";
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

function outputLoaderNodes() {
    return (app.graph?._nodes ?? []).filter((n) => n.comfyClass === CLASS);
}

app.registerExtension({
    name: "Ranomany.LoadImageFromOutput",

    async nodeCreated(node) {
        if (node.comfyClass !== CLASS) return;

        // <img> preview as a DOM widget (renders in editor AND app mode).
        const img = document.createElement("img");
        img.style.cssText =
            "max-width:100%;max-height:220px;object-fit:contain;display:none;border-radius:4px;background:#111;";
        const wrap = document.createElement("div");
        wrap.style.cssText =
            "width:100%;display:flex;align-items:center;justify-content:center;min-height:48px;";
        wrap.appendChild(img);
        node.__ranomanyPreviewImg = img;
        node.addDOMWidget("preview", "image-preview", wrap, { serialize: false });

        // Keep the preview in sync when the user picks a different image.
        const w = node.widgets?.find((w) => w.name === "image");
        if (w) {
            const orig = w.callback;
            w.callback = function (v) {
                orig?.apply(this, arguments);
                updatePreview(node);
            };
        }

        // Manual "refresh / newest" button (recognized widget -> renders in app mode).
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
            const nodes = outputLoaderNodes();
            if (!nodes.length) return;
            const d = await fetchNewest();
            if (!d) return;
            for (const n of nodes) applyNewestToNode(n, d);
            app.graph?.setDirtyCanvas(true, true);
        });
    },
});
