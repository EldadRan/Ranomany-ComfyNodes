"""
MultiConcat ("Multi Concat") — concatenate up to 10 values into a single string.

Each input accepts a number OR a string, and can either be typed in the node's GUI or wired
in from another node's output. The first two inputs are required; inputs 3-10 are optional.
Empty / unconnected inputs are skipped, so the separator never leaves stray gaps.

Type handling: inputs render as STRING widgets (editable in the GUI, convertible to input
sockets). VALIDATE_INPUTS(input_types) accepts any wired type — INT / FLOAT / STRING — and
`_to_str` coerces each value, printing integer-valued floats without the trailing ".0".
"""

import logging

log = logging.getLogger("MultiConcat")

_COUNT = 10  # value_1 .. value_10


def _to_str(v) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


class MultiConcat:

    @classmethod
    def INPUT_TYPES(cls):
        def field(placeholder):
            return ("STRING", {"default": "", "multiline": False, "placeholder": placeholder})

        optional = {f"value_{i}": field(f"value {i} (optional)") for i in range(3, _COUNT + 1)}
        optional["separator"] = ("STRING", {
            "default": "",
            "multiline": False,
            "tooltip": "Inserted between joined values. Leave empty for pure concatenation.",
        })
        return {
            "required": {
                "value_1": field("value 1"),
                "value_2": field("value 2"),
            },
            "optional": optional,
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("string",)
    FUNCTION     = "concat"
    CATEGORY     = "Ranomany/Utils"

    @classmethod
    def VALIDATE_INPUTS(cls, input_types):
        # Accept any wired type (number or string); coercion happens in `concat`.
        return True

    def concat(self, value_1="", value_2="", separator="", **kwargs):
        parts = [value_1, value_2]
        for i in range(3, _COUNT + 1):
            parts.append(kwargs.get(f"value_{i}", ""))
        pieces = [s for s in (_to_str(p) for p in parts) if s != ""]
        return (_to_str(separator).join(pieces),)


NODE_CLASS_MAPPINGS = {
    "RanomanyMultiConcat": MultiConcat,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "RanomanyMultiConcat": "Multi Concat",
}
