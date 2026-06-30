import { app } from "../../scripts/app.js";

const THREE_URL = new URL("./vendor/three.module.min.js", import.meta.url).href;
const THREE = await import(THREE_URL);

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

class CameraWidget {
    constructor({ container, initialState = {}, onStateChange } = {}) {
        this.container  = container;
        this.onChange   = onStateChange;
        this.state      = {
            azimuth:   initialState.azimuth   ?? 0,
            elevation: initialState.elevation ?? 0,
            distance:  initialState.distance  ?? 5,
        };

        this._liveAz = this.state.azimuth;
        this._liveEl = this.state.elevation;
        this._liveDi = this.state.distance;

        this._isDragging     = false;
        this._dragTarget     = null;
        this._hoveredHandle  = null;
        this._raycaster      = new THREE.Raycaster();
        this._mouse          = new THREE.Vector2();
        this._isOrbitDrag    = false;
        this._orbitStartX    = 0;
        this._orbitStartY    = 0;
        this._orbitStartAz   = 0;
        this._orbitStartEl   = 0;
        this._useCameraView  = false;
        this._animId         = null;
        this._time           = 0;

        this.CENTER        = new THREE.Vector3(0, 0.5, 0);
        this.AZ_RADIUS     = 1.8;
        this.EL_RADIUS     = 1.4;
        this.ELEV_ARC_X    = -0.8;

        this._initScene();
        this._bindEvents();
        this._createHUD();
        this._animate();
    }

    // ── scene setup ──────────────────────────────────────────────────────────

    _initScene() {
        const w = this.container.clientWidth  || 300;
        const h = this.container.clientHeight || 300;

        this._scene = new THREE.Scene();
        this._scene.background = new THREE.Color(0x0a0a0f);

        this._camera = new THREE.PerspectiveCamera(45, w / h, 0.1, 1000);
        this._camera.position.set(4, 3.5, 4);
        this._camera.lookAt(0, 0.3, 0);

        this._previewCam = new THREE.PerspectiveCamera(50, w / h, 0.1, 100);
        this._activeCam  = this._camera;

        this._renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
        this._renderer.setSize(w, h, false);
        this._renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
        this._renderer.outputColorSpace = THREE.SRGBColorSpace;
        const canvas = this._renderer.domElement;
        canvas.style.cssText = "position:absolute;top:0;left:0;width:100%;height:100%;";
        this.container.appendChild(canvas);

        this._scene.add(new THREE.AmbientLight(0xffffff, 0.4));
        const main = new THREE.DirectionalLight(0xffffff, 0.8);
        main.position.set(5, 10, 5);
        this._scene.add(main);
        const fill = new THREE.DirectionalLight(0xE93D82, 0.3);
        fill.position.set(-5, 5, -5);
        this._scene.add(fill);

        this._gridHelper = new THREE.GridHelper(5, 20, 0x1a1a2e, 0x12121a);
        this._gridHelper.position.y = -0.01;
        this._scene.add(this._gridHelper);

        this._buildSubject();
        this._buildCamIndicator();
        this._buildAzRing();
        this._buildElArc();
        this._buildDistHandle();
        this._distTube = null;
        this._updateVisuals();
    }

    _buildSubject() {
        const geo  = new THREE.BoxGeometry(1.2, 1.2, 0.02);
        this._planeMat = new THREE.MeshBasicMaterial({ color: 0x3a3a4a });
        const back = new THREE.MeshBasicMaterial({ color: 0x1a1a2a });
        const edge = new THREE.MeshBasicMaterial({ color: 0x1a1a2a });
        const mats = [edge, edge, edge, edge, this._planeMat, back];
        this._imagePlane = new THREE.Mesh(geo, mats);
        this._imagePlane.position.copy(this.CENTER);
        this._scene.add(this._imagePlane);

        const frameGeo = new THREE.EdgesGeometry(geo);
        this._imageFrame = new THREE.LineSegments(frameGeo, new THREE.LineBasicMaterial({ color: 0xE93D82 }));
        this._imageFrame.position.copy(this.CENTER);
        this._scene.add(this._imageFrame);

        const ringGeo = new THREE.RingGeometry(0.55, 0.58, 64);
        this._glowRing = new THREE.Mesh(ringGeo, new THREE.MeshBasicMaterial({
            color: 0xE93D82, transparent: true, opacity: 0.4, side: THREE.DoubleSide
        }));
        this._glowRing.position.set(0, 0.01, 0);
        this._glowRing.rotation.x = -Math.PI / 2;
        this._scene.add(this._glowRing);
    }

    _buildCamIndicator() {
        const mat = new THREE.MeshStandardMaterial({
            color: 0xE93D82, emissive: 0xE93D82, emissiveIntensity: 0.5,
            metalness: 0.8, roughness: 0.2
        });
        this._camIndicator = new THREE.Mesh(new THREE.ConeGeometry(0.15, 0.4, 4), mat);
        this._scene.add(this._camIndicator);

        this._camGlow = new THREE.Mesh(new THREE.SphereGeometry(0.08, 16, 16),
            new THREE.MeshBasicMaterial({ color: 0xff6ba8, transparent: true, opacity: 0.8 }));
        this._scene.add(this._camGlow);
    }

    _buildAzRing() {
        this._azRing = new THREE.Mesh(
            new THREE.TorusGeometry(this.AZ_RADIUS, 0.04, 16, 100),
            new THREE.MeshBasicMaterial({ color: 0xE93D82, transparent: true, opacity: 0.7 })
        );
        this._azRing.rotation.x = Math.PI / 2;
        this._azRing.position.y = 0.02;
        this._scene.add(this._azRing);

        const mat = new THREE.MeshStandardMaterial({
            color: 0xE93D82, emissive: 0xE93D82, emissiveIntensity: 0.6,
            metalness: 0.3, roughness: 0.4
        });
        this._azHandle = new THREE.Mesh(new THREE.SphereGeometry(0.16, 32, 32), mat);
        this._scene.add(this._azHandle);

        this._azGlow = new THREE.Mesh(new THREE.SphereGeometry(0.22, 16, 16),
            new THREE.MeshBasicMaterial({ color: 0xE93D82, transparent: true, opacity: 0.2 }));
        this._scene.add(this._azGlow);
    }

    _buildElArc() {
        const pts = [];
        for (let i = 0; i <= 32; i++) {
            const a = (-90 + (180 * i / 32)) * Math.PI / 180;
            pts.push(new THREE.Vector3(
                this.ELEV_ARC_X,
                this.EL_RADIUS * Math.sin(a) + this.CENTER.y,
                this.EL_RADIUS * Math.cos(a)
            ));
        }
        const curve  = new THREE.CatmullRomCurve3(pts);
        const arcGeo = new THREE.TubeGeometry(curve, 32, 0.04, 8, false);
        this._elArc = new THREE.Mesh(arcGeo,
            new THREE.MeshBasicMaterial({ color: 0x00FFD0, transparent: true, opacity: 0.8 }));
        this._scene.add(this._elArc);

        const mat = new THREE.MeshStandardMaterial({
            color: 0x00FFD0, emissive: 0x00FFD0, emissiveIntensity: 0.6,
            metalness: 0.3, roughness: 0.4
        });
        this._elHandle = new THREE.Mesh(new THREE.SphereGeometry(0.16, 32, 32), mat);
        this._scene.add(this._elHandle);

        this._elGlow = new THREE.Mesh(new THREE.SphereGeometry(0.22, 16, 16),
            new THREE.MeshBasicMaterial({ color: 0x00FFD0, transparent: true, opacity: 0.2 }));
        this._scene.add(this._elGlow);
    }

    _buildDistHandle() {
        const mat = new THREE.MeshStandardMaterial({
            color: 0xFFB800, emissive: 0xFFB800, emissiveIntensity: 0.7,
            metalness: 0.5, roughness: 0.3
        });
        this._distHandle = new THREE.Mesh(new THREE.SphereGeometry(0.15, 32, 32), mat);
        this._scene.add(this._distHandle);

        this._distGlow = new THREE.Mesh(new THREE.SphereGeometry(0.22, 16, 16),
            new THREE.MeshBasicMaterial({ color: 0xFFB800, transparent: true, opacity: 0.25 }));
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
            "padding:4px 8px;"
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
        const path = new THREE.LineCurve3(start, end);
        const geo  = new THREE.TubeGeometry(path, 1, 0.025, 8, false);
        const mat  = new THREE.MeshBasicMaterial({ color: 0xFFB800, transparent: true, opacity: 0.8 });
        this._distTube = new THREE.Mesh(geo, mat);
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

        const elY = this.CENTER.y + this.EL_RADIUS * Math.sin(elRad);
        const elZ = this.EL_RADIUS * Math.cos(elRad);
        this._elHandle.position.set(this.ELEV_ARC_X, elY, elZ);
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
        const canvas = this._renderer.domElement;
        canvas.addEventListener("mousedown",  e => this._onDown(e));
        canvas.addEventListener("mousemove",  e => this._onMove(e));
        canvas.addEventListener("mouseup",    () => this._onUp());
        canvas.addEventListener("mouseleave", () => this._onUp());
        canvas.addEventListener("touchstart", e => { e.preventDefault(); this._onDown({ clientX: e.touches[0].clientX, clientY: e.touches[0].clientY }); }, { passive: false });
        canvas.addEventListener("touchmove",  e => { e.preventDefault(); this._onMove({ clientX: e.touches[0].clientX, clientY: e.touches[0].clientY }); }, { passive: false });
        canvas.addEventListener("touchend",   () => this._onUp());
        canvas.addEventListener("wheel",      e => this._onWheel(e), { passive: false });

        new ResizeObserver(() => {
            const w = this.container.clientWidth, h = this.container.clientHeight;
            if (!w || !h) return;
            this._camera.aspect    = w / h;
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
            this._isOrbitDrag = true;
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
            let el = this._orbitStartEl + (e.clientY - this._orbitStartY) * sens;
            el = Math.max(-90, Math.min(90, el));
            this._liveAz = az; this.state.azimuth   = Math.round(az);
            this._liveEl = el; this.state.elevation  = Math.round(el);
            this._updateVisuals();
            this._notify();
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

        const plane   = new THREE.Plane();
        const hit     = new THREE.Vector3();

        if (this._dragTarget === "azimuth") {
            plane.setFromNormalAndCoplanarPoint(new THREE.Vector3(0, 1, 0), new THREE.Vector3(0, 0, 0));
            if (this._raycaster.ray.intersectPlane(plane, hit)) {
                let az = Math.atan2(hit.x, hit.z) * 180 / Math.PI;
                if (az < 0) az += 360;
                this._liveAz = az; this.state.azimuth = Math.round(az);
                this._updateVisuals(); this._notify();
            }
        } else if (this._dragTarget === "elevation") {
            const ePlane = new THREE.Plane(new THREE.Vector3(1, 0, 0), -this.ELEV_ARC_X);
            if (this._raycaster.ray.intersectPlane(ePlane, hit)) {
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
        if (this._isDragging)
            this._handles().forEach(h => this._setScale(h.mesh, h.glow, 1.0));
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
        this._time += 0.01;
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

    setCameraView(enabled) {
        this._useCameraView = enabled;
        this._isOrbitDrag   = false;
        const handles = [this._azHandle, this._azGlow, this._azRing,
                         this._elHandle, this._elGlow, this._elArc,
                         this._distHandle, this._distGlow, this._distTube,
                         this._camIndicator, this._camGlow, this._glowRing,
                         this._gridHelper, this._imageFrame];
        handles.forEach(h => { if (h) h.visible = !enabled; });
        this._activeCam = enabled ? this._previewCam : this._camera;
        this._renderer.domElement.style.cursor = enabled ? "grab" : "default";
    }

    dispose() {
        if (this._animId !== null) cancelAnimationFrame(this._animId);
        this._renderer.dispose();
        this._scene.clear();
    }

    _notify() {
        this.onChange?.({ ...this.state });
    }
}

// ─── ComfyUI extension ────────────────────────────────────────────────────────

const instances = new WeakMap();

app.registerExtension({
    name: "Ranomany.CameraAngle",

    nodeCreated(node) {
        if (node.constructor?.comfyClass !== "RananomyCameraAngle") return;

        node.setSize([Math.max(node.size[0], 350), Math.max(node.size[1], 520)]);

        const container = document.createElement("div");
        container.style.cssText = "width:100%;height:350px;min-height:350px;position:relative;";

        const readWidget = name => node.widgets?.find(w => w.name === name);

        const widget = new CameraWidget({
            container,
            initialState: {
                azimuth:   Number(readWidget("azimuth")?.value   ?? 0),
                elevation: Number(readWidget("elevation")?.value ?? 0),
                distance:  Number(readWidget("distance")?.value  ?? 5),
            },
            onStateChange(state) {
                const az = readWidget("azimuth");
                const el = readWidget("elevation");
                const di = readWidget("distance");
                if (az) az.value = state.azimuth;
                if (el) el.value = state.elevation;
                if (di) di.value = state.distance;
                app.graph?.setDirtyCanvas(true, true);
            }
        });

        // sync slider → 3D scene
        ["azimuth", "elevation", "distance"].forEach(name => {
            const w = readWidget(name);
            if (!w) return;
            const orig = w.callback;
            w.callback = v => {
                orig?.call(w, v);
                widget.setState({ [name]: Number(v) });
            };
        });

        instances.set(node, widget);

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
