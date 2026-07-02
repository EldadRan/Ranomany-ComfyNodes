import { app } from "../../scripts/app.js";

// "Multi Concat" companion — let ANY output type (INT / FLOAT / STRING / …) wire into the
// value inputs while keeping their editable text widgets.
//
// The inputs are declared STRING on the backend so they render editable widgets (GUI entry)
// and are convertible to input sockets. But a STRING-typed socket makes the frontend's
// LiteGraph.isValidConnection() reject INT/FLOAT links ("accepts only text, not numbers").
// Here we relax each value input's *connection* type to the wildcard "*", which
// isValidConnection() always accepts. The Python side coerces every value to text and its
// VALIDATE_INPUTS(input_types) skips backend type-checking, so numbers concatenate fine.

const CLASS = "RanomanyMultiConcat";
const WILDCARD = "*";

function isValueInput(name) {
    return /^value_\d+$/.test(name) || name === "separator";
}

app.registerExtension({
    name: "Ranomany.MultiConcat",

    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== CLASS) return;

        // Never veto an incoming connection on this node.
        const onConnectInput = nodeType.prototype.onConnectInput;
        nodeType.prototype.onConnectInput = function () {
            const r = onConnectInput ? onConnectInput.apply(this, arguments) : undefined;
            return r === false ? false : true;
        };
    },

    async nodeCreated(node) {
        if (node.comfyClass !== CLASS) return;

        const relax = () => {
            for (const inp of node.inputs || []) {
                if (isValueInput(inp.name)) inp.type = WILDCARD;
            }
        };
        relax();
        requestAnimationFrame(relax);

        // Widget→input sockets can appear/reappear on load and on (dis)connect — re-relax.
        const origConfigure = node.onConfigure;
        node.onConfigure = function () {
            origConfigure?.apply(this, arguments);
            relax();
        };
        const origChange = node.onConnectionsChange;
        node.onConnectionsChange = function () {
            const r = origChange?.apply(this, arguments);
            relax();
            return r;
        };
    },
});
