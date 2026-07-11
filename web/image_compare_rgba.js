import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

// "Compare Images (RGBA)" companion.
//
// The native ImageCompare renders its before/after slider via the built-in
// `imagecompare` widget, populated by core's `Comfy.ImageCompare` extension —
// but that extension is keyed to `comfyClass === "ImageCompare"`, so it never
// fires for our class. This re-binds the identical handler to our node: on
// execute, turn the backend's a_images/b_images (each {filename,subfolder,type})
// into /view URLs and hand them to the slider widget. The RGBA transparency is
// already baked into those PNGs by the Python side, so the widget composites
// them over the canvas checkerboard for free.

const CLASS = "RanomanyImageCompareRGBA";

app.registerExtension({
    name: "Ranomany.ImageCompareRGBA",

    async nodeCreated(node) {
        if (node.comfyClass !== CLASS) return;

        // Give the slider room, matching the native node's minimum.
        const [w, h] = node.size;
        node.setSize([Math.max(w, 400), Math.max(h, 350)]);

        const toUrl = (img) => {
            const p = new URLSearchParams(img);
            return api.apiURL(`/view?${p}&t=${Date.now()}`);
        };

        const orig = node.onExecuted;
        node.onExecuted = function (message) {
            orig?.apply(this, arguments);

            const a = message?.a_images;
            const b = message?.b_images;
            const beforeImages = a && a.length > 0 ? a.map(toUrl) : [];
            const afterImages = b && b.length > 0 ? b.map(toUrl) : [];

            const widget = node.widgets?.find((x) => x.type === "imagecompare");
            if (widget) {
                widget.value = { beforeImages, afterImages };
                widget.callback?.(widget.value);
            }
        };
    },
});
