import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

const THREE_URL = new URL("./vendor/three.module.min.js", import.meta.url).href;

// Lazy-loaded Three.js — set before any CameraWidget is constructed
let T = null;
async function loadThree() {
    if (!T) T = await import(THREE_URL);
    return T;
}

// ─── taxonomy (mirrors Python node exactly) ───────────────────────────────────

function getHorizontal(az) {
    az = ((az % 360) + 360) % 360;
    if (az < 22.5 || az >= 337.5) return "front view";
    if (az < 67.5)                 return "front-right three-quarter angle";
    if (az < 112.5)                return "right side profile";
    if (az < 157.5)                return "rear-right three-quarter angle";
    if (az < 202.5)                return "rear view";
    if (az < 247.5)                return "rear-left three-quarter angle";
    if (az < 292.5)                return "left side profile";
    return                                "front-left three-quarter angle";
}

function getVertical(el) {
    if (el < -60) return "worm's-eye view";
    if (el < -25) return "low-angle shot";
    if (el < -10) return "slight low angle";
    if (el <= 10) return "eye-level shot";
    if (el <= 25) return "slight high angle";
    if (el <= 60) return "high-angle shot";
    return               "bird's-eye view";
}

function getShotSize(d) {
    if (d < 1.5) return "extreme wide shot";
    if (d < 2.4) return "wide shot";
    if (d < 3.6) return "full shot";
    if (d < 4.8) return "medium long shot";
    if (d < 6.0) return "medium shot";
    if (d < 7.5) return "close-up";
    if (d < 9.5) return "extreme close-up";
    return              "macro";
}

// ─── CameraWidget ─────────────────────────────────────────────────────────────
// Uses module-level `T` (Three.js) — must be loaded before constructing.

class CameraWidget {
    constructor({ container, initialState = {}, onStateChange } = {}) {
        this.container = container;
        this.onChange  = onStateChange;
        this.state = {
            azimuth:   initialState.azimuth   ?? 0,
            elevation: initialState.elevation ?? 0,
            distance:  initialState.distance  ?? 5,
        };
        this._liveAz = this.state.azimuth;
        this._liveEl = this.state.elevation;
        this._liveDi = this.state.distance;

        this._isDragging    = false;
        this._dragTarget    = null;
        this._hoveredHandle = null;
        this._raycaster     = new T.Raycaster();
        this._mouse         = new T.Vector2();
        this._isOrbitDrag   = false;
        this._orbitStartX   = 0;
        this._orbitStartY   = 0;
        this._orbitStartAz  = 0;
        this._orbitStartEl  = 0;
        this._useCameraView = false;
        this._animId        = null;
        this._time          = 0;
        this._distTube      = null;

        this.CENTER     = new T.Vector3(0, 0.5, 0);
        this.AZ_RADIUS  = 1.8;
        this.EL_RADIUS  = 1.4;
        this.EL_ARC_X   = -0.8;

        this._initScene();
        this._bindEvents();
        this._createHUD();
        this._animate();
    }

    // ── scene ────────────────────────────────────────────────────────────────

    _initScene() {
        const w = this.container.clientWidth  || 300;
        const h = this.container.clientHeight || 300;

        this._scene = new T.Scene();
        this._scene.background = new T.Color(0x0a0a0f);

        this._camera = new T.PerspectiveCamera(45, w / h, 0.1, 1000);
        this._camera.position.set(4, 3.5, 4);
        this._camera.lookAt(0, 0.3, 0);

        this._previewCam = new T.PerspectiveCamera(50, w / h, 0.1, 100);
        this._activeCam  = this._camera;

        this._renderer = new T.WebGLRenderer({ antialias: true, alpha: true });
        this._renderer.setSize(w, h, false);
        this._renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
        this._renderer.outputColorSpace = T.SRGBColorSpace;
        const cv = this._renderer.domElement;
        cv.style.cssText = "position:absolute;top:0;left:0;width:100%;height:100%;";
        this.container.appendChild(cv);

        this._scene.add(new T.AmbientLight(0xffffff, 0.4));
        const main = new T.DirectionalLight(0xffffff, 0.8);
        main.position.set(5, 10, 5);
        this._scene.add(main);
        const fill = new T.DirectionalLight(0xE93D82, 0.3);
        fill.position.set(-5, 5, -5);
        this._scene.add(fill);

        this._gridHelper = new T.GridHelper(5, 20, 0x1a1a2e, 0x12121a);
        this._gridHelper.position.y = -0.01;
        this._scene.add(this._gridHelper);

        this._buildSubject();
        this._buildCamIndicator();
        this._buildAzRing();
        this._buildElArc();
        this._buildDistHandle();
        this._updateVisuals();
    }

    _buildSubject() {
        const geo = new T.BoxGeometry(1.2, 1.2, 0.02);
        this._planeMat  = new T.MeshBasicMaterial({ color: 0x3a3a4a });
        const back = new T.MeshBasicMaterial({ color: 0x1a1a2a });
        const edge = new T.MeshBasicMaterial({ color: 0x1a1a2a });
        this._imagePlane = new T.Mesh(geo, [edge, edge, edge, edge, this._planeMat, back]);
        this._imagePlane.position.copy(this.CENTER);
        this._scene.add(this._imagePlane);

        this._imageFrame = new T.LineSegments(
            new T.EdgesGeometry(geo),
            new T.LineBasicMaterial({ color: 0xE93D82 })
        );
        this._imageFrame.position.copy(this.CENTER);
        this._scene.add(this._imageFrame);

        this._glowRing = new T.Mesh(
            new T.RingGeometry(0.55, 0.58, 64),
            new T.MeshBasicMaterial({ color: 0xE93D82, transparent: true, opacity: 0.4, side: T.DoubleSide })
        );
        this._glowRing.position.set(0, 0.01, 0);
        this._glowRing.rotation.x = -Math.PI / 2;
        this._scene.add(this._glowRing);
    }

    _buildCamIndicator() {
        this._camIndicator = new T.Mesh(
            new T.ConeGeometry(0.15, 0.4, 4),
            new T.MeshStandardMaterial({ color: 0xE93D82, emissive: 0xE93D82, emissiveIntensity: 0.5, metalness: 0.8, roughness: 0.2 })
        );
        this._scene.add(this._camIndicator);

        this._camGlow = new T.Mesh(
            new T.SphereGeometry(0.08, 16, 16),
            new T.MeshBasicMaterial({ color: 0xff6ba8, transparent: true, opacity: 0.8 })
        );
        this._scene.add(this._camGlow);
    }

    _buildAzRing() {
        this._azRing = new T.Mesh(
            new T.TorusGeometry(this.AZ_RADIUS, 0.04, 16, 100),
            new T.MeshBasicMaterial({ color: 0xE93D82, transparent: true, opacity: 0.7 })
        );
        this._azRing.rotation.x = Math.PI / 2;
        this._azRing.position.y = 0.02;
        this._scene.add(this._azRing);

        this._azHandle = new T.Mesh(
            new T.SphereGeometry(0.16, 32, 32),
            new T.MeshStandardMaterial({ color: 0xE93D82, emissive: 0xE93D82, emissiveIntensity: 0.6, metalness: 0.3, roughness: 0.4 })
        );
        this._scene.add(this._azHandle);

        this._azGlow = new T.Mesh(
            new T.SphereGeometry(0.22, 16, 16),
            new T.MeshBasicMaterial({ color: 0xE93D82, transparent: true, opacity: 0.2 })
        );
        this._scene.add(this._azGlow);
    }

    _buildElArc() {
        const pts = [];
        for (let i = 0; i <= 32; i++) {
            const a = (-90 + (180 * i / 32)) * Math.PI / 180;
            pts.push(new T.Vector3(
                this.EL_ARC_X,
                this.EL_RADIUS * Math.sin(a) + this.CENTER.y,
                this.EL_RADIUS * Math.cos(a)
            ));
        }
        this._elArc = new T.Mesh(
            new T.TubeGeometry(new T.CatmullRomCurve3(pts), 32, 0.04, 8, false),
            new T.MeshBasicMaterial({ color: 0x00FFD0, transparent: true, opacity: 0.8 })
        );
        this._scene.add(this._elArc);

        this._elHandle = new T.Mesh(
            new T.SphereGeometry(0.16, 32, 32),
            new T.MeshStandardMaterial({ color: 0x00FFD0, emissive: 0x00FFD0, emissiveIntensity: 0.6, metalness: 0.3, roughness: 0.4 })
        );
        this._scene.add(this._elHandle);

        this._elGlow = new T.Mesh(
            new T.SphereGeometry(0.22, 16, 16),
            new T.MeshBasicMaterial({ color: 0x00FFD0, transparent: true, opacity: 0.2 })
        );
        this._scene.add(this._elGlow);
    }

    _buildDistHandle() {
        this._distHandle = new T.Mesh(
            new T.SphereGeometry(0.15, 32, 32),
            new T.MeshStandardMaterial({ color: 0xFFB800, emissive: 0xFFB800, emissiveIntensity: 0.7, metalness: 0.5, roughness: 0.3 })
        );
        this._scene.add(this._distHandle);

        this._distGlow = new T.Mesh(
            new T.SphereGeometry(0.22, 16, 16),
            new T.MeshBasicMaterial({ color: 0xFFB800, transparent: true, opacity: 0.25 })
        );
        this._scene.add(this._distGlow);
    }

    // ── HUD overlay ──────────────────────────────────────────────────────────

    _createHUD() {
        const hud = document.createElement("div");
        hud.style.cssText = [
            "position:absolute;bottom:8px;left:0;right:0;",
            "text-align:center;pointer-events:none;",
            "font:12px/1.4 'SF Mono',monospace;",
            "color:#e0e0e0;text-shadow:0 1px 3px #000;",
        ].join("");
        this.container.appendChild(hud);
        this._hud = hud;
        this._updateHUD();
    }

    _updateHUD() {
        const h = getHorizontal(this._liveAz);
        const v = getVertical(this._liveEl);
        const s = getShotSize(this._liveDi);
        this._hud.textContent = `${s}  ·  ${h}  ·  ${v}`;
    }

    // ── visuals ──────────────────────────────────────────────────────────────

    _updateDistLine(start, end) {
        if (this._distTube) {
            this._scene.remove(this._distTube);
            this._distTube.geometry.dispose();
            this._distTube.material.dispose();
        }
        this._distTube = new T.Mesh(
            new T.TubeGeometry(new T.LineCurve3(start, end), 1, 0.025, 8, false),
            new T.MeshBasicMaterial({ color: 0xFFB800, transparent: true, opacity: 0.8 })
        );
        this._scene.add(this._distTube);
    }

    _updateVisuals() {
        const azRad = this._liveAz * Math.PI / 180;
        const elRad = this._liveEl * Math.PI / 180;
        const vDist = 2.6 - (this._liveDi / 10) * 2.0;

        const cx = vDist * Math.sin(azRad) * Math.cos(elRad);
        const cy = this.CENTER.y + vDist * Math.sin(elRad);
        const cz = vDist * Math.cos(azRad) * Math.cos(elRad);

        this._camIndicator.position.set(cx, cy, cz);
        this._camIndicator.lookAt(this.CENTER);
        this._camIndicator.rotateX(Math.PI / 2);
        this._camGlow.position.copy(this._camIndicator.position);

        this._azHandle.position.set(this.AZ_RADIUS * Math.sin(azRad), 0.16, this.AZ_RADIUS * Math.cos(azRad));
        this._azGlow.position.copy(this._azHandle.position);

        this._elHandle.position.set(this.EL_ARC_X, this.CENTER.y + this.EL_RADIUS * Math.sin(elRad), this.EL_RADIUS * Math.cos(elRad));
        this._elGlow.position.copy(this._elHandle.position);

        const distT = 0.15 + ((10 - this._liveDi) / 10) * 0.7;
        this._distHandle.position.lerpVectors(this.CENTER, this._camIndicator.position, distT);
        this._distGlow.position.copy(this._distHandle.position);

        this._updateDistLine(this.CENTER.clone(), this._camIndicator.position.clone());
        this._previewCam.position.copy(this._camIndicator.position);
        this._previewCam.lookAt(this.CENTER);
        this._updateHUD();
    }

    _setScale(mesh, glow, s) {
        mesh.scale.setScalar(s);
        if (glow) glow.scale.setScalar(s);
    }

    // ── events ───────────────────────────────────────────────────────────────

    _bindEvents() {
        const cv = this._renderer.domElement;
        cv.addEventListener("mousedown",  e => this._onDown(e));
        cv.addEventListener("mousemove",  e => this._onMove(e));
        cv.addEventListener("mouseup",    () => this._onUp());
        cv.addEventListener("mouseleave", () => this._onUp());
        cv.addEventListener("touchstart", e => { e.preventDefault(); this._onDown({ clientX: e.touches[0].clientX, clientY: e.touches[0].clientY }); }, { passive: false });
        cv.addEventListener("touchmove",  e => { e.preventDefault(); this._onMove({ clientX: e.touches[0].clientX, clientY: e.touches[0].clientY }); }, { passive: false });
        cv.addEventListener("touchend",   () => this._onUp());
        cv.addEventListener("wheel",      e => this._onWheel(e), { passive: false });

        new ResizeObserver(() => {
            const w = this.container.clientWidth, h = this.container.clientHeight;
            if (!w || !h) return;
            this._camera.aspect     = w / h;
            this._previewCam.aspect = w / h;
            this._camera.updateProjectionMatrix();
            this._previewCam.updateProjectionMatrix();
            this._renderer.setSize(w, h, false);
        }).observe(this.container);
    }

    _getMousePos(e) {
        const r = this._renderer.domElement.getBoundingClientRect();
        this._mouse.x =  ((e.clientX - r.left) / r.width)  * 2 - 1;
        this._mouse.y = -((e.clientY - r.top)  / r.height) * 2 + 1;
    }

    _handles() {
        return [
            { mesh: this._azHandle,   glow: this._azGlow,   name: "azimuth" },
            { mesh: this._elHandle,   glow: this._elGlow,   name: "elevation" },
            { mesh: this._distHandle, glow: this._distGlow, name: "distance" },
        ];
    }

    _onDown(e) {
        this._getMousePos(e);
        if (this._useCameraView) {
            this._isOrbitDrag  = true;
            this._orbitStartX  = e.clientX;
            this._orbitStartY  = e.clientY;
            this._orbitStartAz = this._liveAz;
            this._orbitStartEl = this._liveEl;
            this._renderer.domElement.style.cursor = "grabbing";
            return;
        }
        this._raycaster.setFromCamera(this._mouse, this._camera);
        for (const h of this._handles()) {
            if (this._raycaster.intersectObject(h.mesh).length) {
                this._isDragging = true;
                this._dragTarget = h.name;
                this._setScale(h.mesh, h.glow, 1.3);
                this._renderer.domElement.style.cursor = "grabbing";
                return;
            }
        }
    }

    _onMove(e) {
        this._getMousePos(e);

        if (this._useCameraView && this._isOrbitDrag) {
            const sens = 0.5;
            let az = this._orbitStartAz - (e.clientX - this._orbitStartX) * sens;
            az = ((az % 360) + 360) % 360;
            let el = Math.max(-90, Math.min(90, this._orbitStartEl + (e.clientY - this._orbitStartY) * sens));
            this._liveAz = az; this.state.azimuth   = Math.round(az);
            this._liveEl = el; this.state.elevation  = Math.round(el);
            this._updateVisuals(); this._notify();
            return;
        }

        this._raycaster.setFromCamera(this._mouse, this._camera);

        if (!this._isDragging) {
            let found = null;
            for (const h of this._handles()) {
                if (this._raycaster.intersectObject(h.mesh).length) { found = h; break; }
            }
            if (this._hoveredHandle && this._hoveredHandle !== found)
                this._setScale(this._hoveredHandle.mesh, this._hoveredHandle.glow, 1.0);
            if (found) {
                this._setScale(found.mesh, found.glow, 1.15);
                this._renderer.domElement.style.cursor = "grab";
                this._hoveredHandle = found;
            } else {
                this._renderer.domElement.style.cursor = "default";
                this._hoveredHandle = null;
            }
            return;
        }

        const plane = new T.Plane();
        const hit   = new T.Vector3();

        if (this._dragTarget === "azimuth") {
            plane.setFromNormalAndCoplanarPoint(new T.Vector3(0, 1, 0), new T.Vector3(0, 0, 0));
            if (this._raycaster.ray.intersectPlane(plane, hit)) {
                let az = Math.atan2(hit.x, hit.z) * 180 / Math.PI;
                if (az < 0) az += 360;
                this._liveAz = az; this.state.azimuth = Math.round(az);
                this._updateVisuals(); this._notify();
            }
        } else if (this._dragTarget === "elevation") {
            const ep = new T.Plane(new T.Vector3(1, 0, 0), -this.EL_ARC_X);
            if (this._raycaster.ray.intersectPlane(ep, hit)) {
                let el = Math.atan2(hit.y - this.CENTER.y, hit.z) * 180 / Math.PI;
                el = Math.max(-90, Math.min(90, el));
                this._liveEl = el; this.state.elevation = Math.round(el);
                this._updateVisuals(); this._notify();
            }
        } else if (this._dragTarget === "distance") {
            const d = Math.max(0, Math.min(10, 5 - this._mouse.y * 5));
            this._liveDi = d; this.state.distance = Math.round(d * 10) / 10;
            this._updateVisuals(); this._notify();
        }
    }

    _onUp() {
        if (this._isOrbitDrag) {
            this._isOrbitDrag = false;
            this._renderer.domElement.style.cursor = this._useCameraView ? "grab" : "default";
            return;
        }
        if (this._isDragging) this._handles().forEach(h => this._setScale(h.mesh, h.glow, 1.0));
        this._isDragging = false;
        this._dragTarget = null;
        this._renderer.domElement.style.cursor = "default";
    }

    _onWheel(e) {
        if (!this._useCameraView) return;
        e.preventDefault();
        const d = Math.max(0, Math.min(10, this._liveDi - e.deltaY * 0.01));
        this._liveDi = d; this.state.distance = Math.round(d * 10) / 10;
        this._updateVisuals(); this._notify();
    }

    // ── render loop ──────────────────────────────────────────────────────────

    _animate() {
        this._animId = requestAnimationFrame(() => this._animate());
        this._time  += 0.01;
        this._camGlow.scale.setScalar(1 + Math.sin(this._time * 2) * 0.03);
        this._glowRing.rotation.z += 0.003;
        this._renderer.render(this._scene, this._activeCam);
    }

    // ── public API ───────────────────────────────────────────────────────────

    setState(patch) {
        if (patch.azimuth   !== undefined) { this.state.azimuth   = patch.azimuth;   this._liveAz = patch.azimuth; }
        if (patch.elevation !== undefined) { this.state.elevation = patch.elevation; this._liveEl = patch.elevation; }
        if (patch.distance  !== undefined) { this.state.distance  = patch.distance;  this._liveDi = patch.distance; }
        this._updateVisuals();
    }

    updateImage(url) {
        if (!url) {
            this._planeMat.map = null;
            this._planeMat.color.set(0x3a3a4a);
            this._planeMat.needsUpdate = true;
            this._imagePlane.scale.set(1, 1, 1);
            this._imageFrame.scale.set(1, 1, 1);
            return;
        }
        const img = new Image();
        if (!url.startsWith("data:")) img.crossOrigin = "anonymous";
        img.onload = () => {
            const tex = new T.Texture(img);
            tex.colorSpace  = T.SRGBColorSpace;
            tex.needsUpdate = true;
            this._planeMat.map = tex;
            this._planeMat.color.set(0xffffff);
            this._planeMat.needsUpdate = true;
            const ar = img.width / img.height, max = 1.5;
            const sx = ar > 1 ? max : max * ar, sy = ar > 1 ? max / ar : max;
            this._imagePlane.scale.set(sx, sy, 1);
            this._imageFrame.scale.set(sx, sy, 1);
        };
        img.src = url;
    }

    setCameraView(enabled) {
        this._useCameraView = enabled;
        this._isOrbitDrag   = false;
        [this._azHandle, this._azGlow, this._azRing,
         this._elHandle, this._elGlow, this._elArc,
         this._distHandle, this._distGlow, this._distTube,
         this._camIndicator, this._camGlow, this._glowRing,
         this._gridHelper, this._imageFrame
        ].forEach(h => { if (h) h.visible = !enabled; });
        this._activeCam = enabled ? this._previewCam : this._camera;
        this._renderer.domElement.style.cursor = enabled ? "grab" : "default";
    }

    dispose() {
        if (this._animId !== null) cancelAnimationFrame(this._animId);
        this._renderer.dispose();
        this._scene.clear();
    }

    _notify() { this.onChange?.({ ...this.state }); }
}

// ─── ComfyUI extension ────────────────────────────────────────────────────────

const instances = new WeakMap();

app.registerExtension({
    name: "Ranomany.CameraAngle",

    async nodeCreated(node) {
        const cls = node.comfyClass ?? node.constructor?.comfyClass;
        if (cls !== "RananomyCameraAngle") return;

        // Load Three.js on first use (cached after that)
        await loadThree();

        node.setSize([Math.max(node.size[0], 350), Math.max(node.size[1], 520)]);

        const container = document.createElement("div");
        container.style.cssText = "width:100%;height:350px;min-height:350px;position:relative;overflow:hidden;";

        const rw = name => node.widgets?.find(w => w.name === name);

        const widget = new CameraWidget({
            container,
            initialState: {
                azimuth:   Number(rw("azimuth")?.value   ?? 0),
                elevation: Number(rw("elevation")?.value ?? 0),
                distance:  Number(rw("distance")?.value  ?? 5),
            },
            onStateChange(state) {
                const az = rw("azimuth"), el = rw("elevation"), di = rw("distance");
                if (az) az.value = state.azimuth;
                if (el) el.value = state.elevation;
                if (di) di.value = state.distance;
                app.graph?.setDirtyCanvas(true, true);
            }
        });

        // sync sliders → 3D scene
        ["azimuth", "elevation", "distance"].forEach(name => {
            const w = rw(name);
            if (!w) return;
            const orig = w.callback;
            w.callback = v => { orig?.call(w, v); widget.setState({ [name]: Number(v) }); };
        });

        instances.set(node, widget);

        // display image from execution output in the 3D subject plane
        node.onExecuted = function(output) {
            const imgs = output?.preview_images ?? output?.images;
            if (imgs?.length) {
                const { filename, subfolder, type } = imgs[0];
                const url = api.apiURL(`/view?filename=${encodeURIComponent(filename)}&subfolder=${encodeURIComponent(subfolder)}&type=${type}`);
                widget.updateImage(url);
            }
        };

        const domWidget = node.addDOMWidget("camera_preview", "camera-angle", container, {
            getMinHeight: () => 370,
            hideOnZoom:   false,
            serialize:    false,
        });

        const origRemove = domWidget.onRemove?.bind(domWidget);
        domWidget.onRemove = () => {
            origRemove?.();
            instances.get(node)?.dispose();
            instances.delete(node);
        };
    }
});
