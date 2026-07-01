import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

// "Cloudflare Access Identity" companion.
//
// Node execution can't read HTTP headers, so the backend route GET /ranomany/cf-identity
// reads the Cf-Access-* headers from the request and we pull the result into the node's
// widgets here. The widget values then flow into execution as the node's outputs.
//
// The values are refreshed on create/load, via a button, and — crucially — right before a
// prompt is queued, so they reflect whoever actually clicks Run.

const CLASS = "RanomanyCFIdentity";

// Inject the app-mode-visible info panel CSS once (panel shows in editor + app).
(function injectStyle() {
    const id = "ranomany-cf-info-style";
    if (document.getElementById(id)) return;
    const s = document.createElement("style");
    s.id = id;
    s.textContent =
        ".ranomany-cf-info{display:block;width:100%;box-sizing:border-box;padding:8px 10px;" +
        "background:#1a1a1a;border-radius:4px;font-size:12px;line-height:1.6;color:#ddd;}" +
        ".ranomany-cf-info .rv-row{display:flex;justify-content:space-between;gap:12px;}" +
        ".ranomany-cf-info .rv-k{color:#8a8a8a;}" +
        ".ranomany-cf-info .rv-v{color:#fff;overflow:hidden;text-overflow:ellipsis;}" +
        ".ranomany-cf-info .rv-ok{color:#5fd35f;}" +
        ".ranomany-cf-info .rv-no{color:#d98a3a;}";
    document.head.appendChild(s);
})();

function renderInfo(node) {
    const box = node.__ranomanyCfBox;
    if (!box) return;
    const email = node.widgets?.find((w) => w.name === "email")?.value || "";
    const authed = !!node.widgets?.find((w) => w.name === "authenticated")?.value;
    const status = authed
        ? '<span class="rv-ok">✓ authenticated</span>'
        : '<span class="rv-no">✗ not behind Access</span>';
    box.innerHTML =
        `<div class="rv-row"><span class="rv-k">email</span>` +
        `<span class="rv-v">${email || "—"}</span></div>` +
        `<div class="rv-row"><span class="rv-k">status</span><span class="rv-v">${status}</span></div>`;
}

function setWidget(node, name, value) {
    const w = node.widgets?.find((w) => w.name === name);
    if (!w) return;
    if (w.value !== value) {
        w.value = value;
        try { w.callback?.(value); } catch {}
    }
}

async function fetchIdentity(node) {
    const token = ++node.__ranomanyCfReq;
    try {
        const r = await api.fetchApi("/ranomany/cf-identity");
        if (token !== node.__ranomanyCfReq) return; // superseded by a newer fetch
        if (!r.ok) return;
        const d = await r.json();
        setWidget(node, "email", d.email || "");
        setWidget(node, "authenticated", !!d.authenticated);
        setWidget(node, "identity_json", JSON.stringify(d.headers || {}, null, 2));
        renderInfo(node);
        app.graph?.setDirtyCanvas(true, false);
    } catch (e) {
        console.warn("[Ranomany] cf-identity failed", e);
    }
}

function cfNodes() {
    return (app.graph?._nodes ?? []).filter((n) => n.comfyClass === CLASS);
}

app.registerExtension({
    name: "Ranomany.CloudflareIdentity",

    async nodeCreated(node) {
        if (node.comfyClass !== CLASS) return;

        node.__ranomanyCfReq = 0;

        const box = document.createElement("div");
        box.className = "ranomany-cf-info";
        node.__ranomanyCfBox = box;
        node.addDOMWidget("cfInfo", "cf-info", box, { serialize: false });
        renderInfo(node);

        node.addWidget("button", "refresh identity", null, () => fetchIdentity(node));

        const origConfigure = node.onConfigure;
        node.onConfigure = function () {
            origConfigure?.apply(this, arguments);
            fetchIdentity(node);
        };
        requestAnimationFrame(() => fetchIdentity(node));
    },

    setup() {
        // Refresh every identity node right before a prompt is queued, so the captured
        // value reflects whoever actually runs the workflow. Wrap once.
        const origQueue = app.queuePrompt;
        app.queuePrompt = async function (...args) {
            const nodes = cfNodes();
            if (nodes.length) {
                await Promise.all(nodes.map((n) => fetchIdentity(n)));
            }
            return origQueue.apply(this, args);
        };
    },
});
