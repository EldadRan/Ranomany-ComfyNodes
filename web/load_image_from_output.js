import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

// "Load Image (Edit Mode)" companion.
//
// The native app-mode image preview is hardcoded to node.type === "LoadImage"
// (AppModeWidgetList.vue -> getDropIndicator), so a custom node can't get it.
// Instead we render our own <img> as a DOM widget — DOM widgets ARE rendered in
// the app/run panel (NodeWidgets.vue -> WidgetDOM.vue), so the preview shows in
// both the editor and the app builder. The picker itself is the native
// image_upload widget (All / Imported / Generated browser + upload).

const CLASS = "RanomanyLoadImageEdit";

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

        // Keep the preview in sync when the user picks/uploads a different image.
        const w = node.widgets?.find((w) => w.name === "image");
        if (w) {
            const orig = w.callback;
            w.callback = function (v) {
                orig?.apply(this, arguments);
                updatePreview(node);
            };
        }

        // Initial preview (covers values restored from a saved workflow).
        const origConfigure = node.onConfigure;
        node.onConfigure = function () {
            origConfigure?.apply(this, arguments);
            updatePreview(node);
        };
        requestAnimationFrame(() => updatePreview(node));
    },
});
