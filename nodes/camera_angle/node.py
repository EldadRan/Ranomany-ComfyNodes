class CameraAngle:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "azimuth":   ("INT",   {"default": 0,   "min": 0,   "max": 359, "step": 1,   "display": "slider"}),
                "elevation": ("INT",   {"default": 0,   "min": -90, "max": 90,  "step": 1,   "display": "slider"}),
                "distance":  ("FLOAT", {"default": 5.0, "min": 0.0, "max": 10.0,"step": 0.1, "display": "slider"}),
            },
            "optional": {
                "image": ("IMAGE",),
            },
        }

    RETURN_TYPES  = ("STRING", "STRING", "STRING", "STRING")
    RETURN_NAMES  = ("prompt", "horizontal", "vertical", "shot_size")
    FUNCTION      = "generate"
    CATEGORY      = "Ranomany/Utils"
    OUTPUT_NODE   = False

    def generate(self, azimuth, elevation, distance, image=None):
        h = self._horizontal(azimuth)
        v = self._vertical(elevation)
        s = self._shot_size(distance)
        prompt = (
            f"Change the camera to a {s} from a {v}, {h} of the same subject. "
            f"Preserve identity, materials, and lighting — only change the camera angle and framing."
        )
        return (prompt, h, v, s)

    @staticmethod
    def _horizontal(az):
        az = az % 360
        if az < 22.5 or az >= 337.5:  return "front view"
        if az < 67.5:                  return "front-right three-quarter angle"
        if az < 112.5:                 return "right side profile"
        if az < 157.5:                 return "rear-right three-quarter angle"
        if az < 202.5:                 return "rear view"
        if az < 247.5:                 return "rear-left three-quarter angle"
        if az < 292.5:                 return "left side profile"
        return                                "front-left three-quarter angle"

    @staticmethod
    def _vertical(el):
        if el < -60: return "worm's-eye view"
        if el < -25: return "low-angle shot"
        if el < -10: return "slight low angle"
        if el <= 10: return "eye-level shot"
        if el <= 25: return "slight high angle"
        if el <= 60: return "high-angle shot"
        return              "bird's-eye view"

    @staticmethod
    def _shot_size(d):
        if d < 1.5: return "extreme wide shot"
        if d < 2.4: return "wide shot"
        if d < 3.6: return "full shot"
        if d < 4.8: return "medium long shot"
        if d < 6.0: return "medium shot"
        if d < 7.5: return "close-up"
        if d < 9.5: return "extreme close-up"
        return             "macro"


NODE_CLASS_MAPPINGS        = {"RananomyCameraAngle": CameraAngle}
NODE_DISPLAY_NAME_MAPPINGS = {"RananomyCameraAngle": "Camera Angle"}
