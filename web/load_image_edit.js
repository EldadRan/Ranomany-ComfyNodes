import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

const MARGIN = 10;
const LABEL_H = 16;

app.registerExtension({
    name: "Ranomany.LoadImageEdit",

    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== "RanomanyLoadImageEdit") return;

        // ── on execution: load the returned output image ──────────────────
        const origOnExecuted = nodeType.prototype.onExecuted;
        nodeType.prototype.onExecuted = function (message) {
            origOnExecuted?.apply(this, arguments);

            const images = message?.images;
            if (!images?.length) return;

            const { filename, subfolder = "", type = "output" } = images[0];
            const img = new Image();
            img.onload = () => {
                this._previewImg = img;
                this.setSize(this.computeSize());
                this.setDirtyCanvas(true, false);
            };
            img.src = api.apiURL(
                `/view?filename=${encodeURIComponent(filename)}`
                + `&subfolder=${encodeURIComponent(subfolder)}`
                + `&type=${encodeURIComponent(type)}`
                + `&t=${Date.now()}`
            );
        };

        // ── expand node height to fit the preview ──────────────────────────
        const origComputeSize = nodeType.prototype.computeSize;
        nodeType.prototype.computeSize = function (out) {
            const size = origComputeSize
                ? origComputeSize.apply(this, arguments)
                : [this.size[0], this.size[1]];

            if (this._previewImg) {
                const w = size[0] - MARGIN * 2;
                const ratio = this._previewImg.naturalHeight / this._previewImg.naturalWidth;
                size[1] += MARGIN + w * ratio + MARGIN + LABEL_H;
            }
            return size;
        };

        // ── paint the preview on the canvas ───────────────────────────────
        const origOnDrawForeground = nodeType.prototype.onDrawForeground;
        nodeType.prototype.onDrawForeground = function (ctx) {
            origOnDrawForeground?.apply(this, arguments);
            if (!this._previewImg || this.flags?.collapsed) return;

            // y = bottom of the last widget
            let y = this.size[1]; // fallback: bottom of node
            if (this.widgets?.length) {
                const last = this.widgets[this.widgets.length - 1];
                y = (last.last_y ?? 0) + (LiteGraph?.NODE_WIDGET_HEIGHT ?? 28) + MARGIN;
            }

            const w = this.size[0] - MARGIN * 2;
            const ratio = this._previewImg.naturalHeight / this._previewImg.naturalWidth;
            const h = w * ratio;

            ctx.drawImage(this._previewImg, MARGIN, y, w, h);

            // dimension label
            ctx.fillStyle = "rgba(255,255,255,0.55)";
            ctx.font = "11px sans-serif";
            ctx.textAlign = "center";
            ctx.fillText(
                `${this._previewImg.naturalWidth} × ${this._previewImg.naturalHeight}`,
                this.size[0] / 2,
                y + h + LABEL_H - 2
            );
        };
    },
});
