import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

// "Load Image (from Outputs)" companion.
// The node's `image` widget is a plain recognized image_upload combo (so the
// preview renders in the app/run panel). This extension keeps it pointed at the
// newest output image: a manual "refresh / newest" button, plus an automatic
// snap-to-newest whenever a workflow run finishes.

const CLASS = "RanomanyLoadImageEdit";

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

function relPath(d) {
    return d.subfolder ? `${d.subfolder}/${d.filename}` : d.filename;
}

function applyNewestToNode(node, d) {
    const w = node.widgets?.find((w) => w.name === "image");
    if (!w) return;
    const rel = relPath(d);
    // The newest file may have been generated after the combo options were built.
    const opts = w.options?.values;
    if (Array.isArray(opts) && !opts.includes(rel)) opts.push(rel);
    if (w.value !== rel) {
        w.value = rel;
        try {
            w.callback?.(rel);
        } catch {}
    }
}

function outputLoaderNodes() {
    return (app.graph?._nodes ?? []).filter((n) => n.comfyClass === CLASS);
}

app.registerExtension({
    name: "Ranomany.LoadImageFromOutput",

    async nodeCreated(node) {
        if (node.comfyClass !== CLASS) return;
        // Native button widget — a recognized type, so it renders in app mode too.
        node.addWidget("button", "refresh / newest", null, async () => {
            const d = await fetchNewest();
            if (d) {
                applyNewestToNode(node, d);
                app.graph?.setDirtyCanvas(true, true);
            }
        });
    },

    setup() {
        // When a run finishes, snap every instance to the newest output image.
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
