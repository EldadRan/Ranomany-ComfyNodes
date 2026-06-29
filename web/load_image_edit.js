import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

app.registerExtension({
    name: "Ranomany.LoadImageEdit",

    async nodeCreated(node) {
        if (node.comfyClass !== "RanomanyLoadImageEdit") return;

        const img = document.createElement("img");
        img.style.cssText = [
            "width:100%",
            "max-height:220px",
            "object-fit:contain",
            "border-radius:4px",
            "display:none",
        ].join(";");

        node.addDOMWidget("imagePreview", "img", img);

        const origOnExecuted = node.onExecuted;
        node.onExecuted = function (message) {
            origOnExecuted?.apply(this, arguments);

            const images = message?.images;
            if (!images?.length) return;

            const { filename, subfolder = "", type = "output" } = images[0];
            img.src = api.apiURL(
                `/view?filename=${encodeURIComponent(filename)}`
                + `&subfolder=${encodeURIComponent(subfolder)}`
                + `&type=${encodeURIComponent(type)}`
                + `&t=${Date.now()}`
            );
            img.style.display = "";

            app.graph.setDirtyCanvas(true, false);
        };
    },
});
