import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

app.registerExtension({
    name: "Ranomany.SaveVideoPreview",

    async nodeCreated(node) {
        if (node.comfyClass !== "RananomySaveVideo") return;

        // Create video element — hidden until first execution
        const el = document.createElement("video");
        el.controls = true;
        el.loop = false;
        el.style.cssText = [
            "width:100%",
            "height:200px",
            "object-fit:contain",
            "background:#111",
            "border-radius:4px",
            "display:none",
        ].join(";");

        node.addDOMWidget("videoPreview", "video", el);

        const origOnExecuted = node.onExecuted;
        node.onExecuted = function (message) {
            origOnExecuted?.apply(this, arguments);

            const clips = message?.gifs;
            if (!clips?.length) return;

            const { filename, subfolder = "", type = "output" } = clips[0];
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
