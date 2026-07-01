import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

// "Load Video (Info)" companion.
//
// Picker: the native video_upload widget, which already renders an inline <video>
// player in the EDITOR. A DOM widget renders in both editor and app mode, so a naive
// custom <video> would double up with that native editor preview. As with our
// "Load Image (Edit Mode)" node (see load_image_from_output.js), we therefore gate our
// custom <video> to APP mode only via a CSS ancestor selector: the app panel wraps
// widgets in [data-testid="app-mode-widget-item"] / "builder-widget-item". Pure CSS, so
// it follows the element as the frontend re-parents it between modes — editor shows the
// native preview, app mode shows ours.

const CLASS = "RanomanyLoadVideoInfo";

// Inject the app-mode gating CSS once.
(function injectStyle() {
    const id = "ranomany-video-preview-style";
    if (document.getElementById(id)) return;
    const s = document.createElement("style");
    s.id = id;
    s.textContent =
        ".ranomany-video-preview,.ranomany-video-info{display:none;}" +
        '[data-testid="app-mode-widget-item"] .ranomany-video-preview,' +
        '[data-testid="builder-widget-item"] .ranomany-video-preview{display:flex;}' +
        '[data-testid="app-mode-widget-item"] .ranomany-video-info,' +
        '[data-testid="builder-widget-item"] .ranomany-video-info{display:block;}' +
        ".ranomany-video-info{width:100%;box-sizing:border-box;padding:8px 10px;" +
        "background:#1a1a1a;border-radius:4px;font-size:12px;line-height:1.6;color:#ddd;}" +
        ".ranomany-video-info .rv-row{display:flex;justify-content:space-between;gap:12px;}" +
        ".ranomany-video-info .rv-k{color:#8a8a8a;}" +
        ".ranomany-video-info .rv-v{color:#fff;font-variant-numeric:tabular-nums;}" +
        ".ranomany-video-info .rv-empty{color:#8a8a8a;text-align:center;}";
    document.head.appendChild(s);
})();

// Populate the app-mode info panel from the node's ui.video_info payload.
function renderInfo(node, data) {
    const box = node.__ranomanyInfoBox;
    if (!box) return;
    if (!data) {
        box.innerHTML = '<div class="rv-empty">Run to load video info</div>';
        return;
    }
    const fmtDur = (s) => {
        const total = Math.max(0, Math.round(s));
        const m = Math.floor(total / 60);
        const sec = total % 60;
        return `${m}:${String(sec).padStart(2, "0")} (${(+s).toFixed(2)}s)`;
    };
    const rows = [
        ["resolution", `${data.width} × ${data.height}`],
        ["fps", `${data.fps}`],
        ["frames", `${data.frame_count}`],
        ["duration", fmtDur(data.duration_seconds)],
    ];
    box.innerHTML = rows
        .map(([k, v]) => `<div class="rv-row"><span class="rv-k">${k}</span><span class="rv-v">${v}</span></div>`)
        .join("");
}

// Build a /view URL from a picker value like "sub/dir/clip.mp4 [input]".
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
    const el = node.__ranomanyVideoEl;
    if (!el) return;
    const w = node.widgets?.find((w) => w.name === "video");
    const url = viewURL(w?.value);
    if (url) {
        el.src = url;
        el.style.display = "";
        el.load();
    } else {
        el.removeAttribute("src");
        el.style.display = "none";
    }
}

// Probe the picked clip on the backend (fps/frames need PyAV, not the browser) and
// fill the info panel immediately — no graph run required.
async function fetchInfo(node) {
    const w = node.widgets?.find((w) => w.name === "video");
    const value = (w?.value || "").trim();
    if (!value) {
        node.__ranomanyInfo = null;
        renderInfo(node, null);
        return;
    }
    const token = ++node.__ranomanyInfoReq;
    try {
        const r = await api.fetchApi(`/ranomany/video-info?file=${encodeURIComponent(value)}`);
        if (token !== node.__ranomanyInfoReq) return; // a newer pick superseded this one
        if (!r.ok) return;
        const info = await r.json();
        if (info && !info.error) {
            node.__ranomanyInfo = info;
            renderInfo(node, info);
        }
    } catch (e) {
        console.warn("[Ranomany] video-info failed", e);
    }
}

app.registerExtension({
    name: "Ranomany.VideoInfoPreview",

    async nodeCreated(node) {
        if (node.comfyClass !== CLASS) return;

        // <video> preview built as a DOM widget, gated to app mode via the CSS class.
        const el = document.createElement("video");
        el.controls = true;
        el.loop = false;
        el.style.cssText =
            "width:100%;max-height:220px;object-fit:contain;background:#111;border-radius:4px;display:none;";
        const wrap = document.createElement("div");
        wrap.className = "ranomany-video-preview";
        wrap.style.cssText = "width:100%;align-items:center;justify-content:center;min-height:48px;";
        wrap.appendChild(el);
        node.__ranomanyVideoEl = el;
        node.addDOMWidget("videoPreview", "video-preview", wrap, { serialize: false });

        // App-mode-only info panel (fps / frames / duration / resolution).
        const infoBox = document.createElement("div");
        infoBox.className = "ranomany-video-info";
        node.__ranomanyInfoBox = infoBox;
        node.__ranomanyInfoReq = 0;
        node.addDOMWidget("videoInfo", "video-info", infoBox, { serialize: false });
        renderInfo(node, node.__ranomanyInfo || null);

        // Refresh preview + info when the user picks/uploads a different clip.
        const w = node.widgets?.find((w) => w.name === "video");
        if (w) {
            const orig = w.callback;
            w.callback = function (v) {
                orig?.apply(this, arguments);
                updatePreview(node);
                fetchInfo(node);
            };
        }

        // Re-draw on workflow load, and once on creation.
        const origConfigure = node.onConfigure;
        node.onConfigure = function () {
            origConfigure?.apply(this, arguments);
            updatePreview(node);
            fetchInfo(node);
        };
        requestAnimationFrame(() => {
            updatePreview(node);
            fetchInfo(node);
        });

        // After a run, snap to the file the backend actually loaded.
        const origOnExecuted = node.onExecuted;
        node.onExecuted = function (message) {
            origOnExecuted?.apply(this, arguments);

            const info = message?.video_info?.[0];
            if (info) {
                node.__ranomanyInfo = info;
                renderInfo(node, info);
            }

            const clips = message?.gifs;
            if (!clips?.length) {
                updatePreview(node);
                return;
            }
            const { filename, subfolder = "", type = "input" } = clips[0];
            el.src = api.apiURL(
                `/view?filename=${encodeURIComponent(filename)}`
                + `&subfolder=${encodeURIComponent(subfolder)}`
                + `&type=${encodeURIComponent(type)}`
                + `&t=${Date.now()}`
            );
            el.style.display = "";
            el.load();
            app.graph.setDirtyCanvas(true, false);
        };
    },
});
