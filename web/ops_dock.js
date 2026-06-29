import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

// ── Panel HTML ─────────────────────────────────────────────────────────────────

const PANEL_STYLE = `
  #rnm-ops {
    padding: 14px;
    font-family: monospace;
    font-size: 12px;
    color: var(--input-text, #ddd);
    box-sizing: border-box;
  }
  #rnm-ops h3 {
    margin: 0 0 8px;
    font-size: 13px;
    letter-spacing: 0.05em;
  }
  #rnm-ops button {
    display: block;
    width: 100%;
    padding: 6px 10px;
    margin-bottom: 6px;
    background: var(--comfy-menu-bg, #333);
    color: var(--input-text, #ddd);
    border: 1px solid var(--border-color, #555);
    border-radius: 4px;
    cursor: pointer;
    font-family: monospace;
    font-size: 12px;
    text-align: left;
  }
  #rnm-ops button:hover { background: var(--comfy-input-bg, #444); }
  #rnm-ops button:disabled { opacity: 0.4; cursor: default; }
  #rnm-ops input[type="password"] {
    display: block;
    width: 100%;
    padding: 5px 8px;
    box-sizing: border-box;
    background: var(--comfy-input-bg, #222);
    color: var(--input-text, #ddd);
    border: 1px solid var(--border-color, #555);
    border-radius: 4px;
    font-family: monospace;
    font-size: 12px;
  }
  #rnm-ops select {
    display: block;
    width: 100%;
    padding: 5px 8px;
    box-sizing: border-box;
    background: var(--comfy-input-bg, #222);
    color: var(--input-text, #ddd);
    border: 1px solid var(--border-color, #555);
    border-radius: 4px;
    font-family: monospace;
    font-size: 12px;
    margin-bottom: 6px;
  }
  #rnm-ops hr { border: none; border-top: 1px solid var(--border-color, #444); margin: 10px 0; }
  #rnm-log { color: #888; font-size: 11px; min-height: 16px; word-break: break-all; }
  #rnm-out {
    font-size: 10px;
    max-height: 120px;
    overflow: auto;
    background: #111;
    border: 1px solid #333;
    border-radius: 3px;
    padding: 4px 6px;
    margin: 4px 0;
    white-space: pre-wrap;
    display: none;
  }
  #rnm-msg { min-height: 16px; margin-top: 8px; font-size: 11px; }
  #rnm-admin { display: none; margin-top: 8px; }
  #rnm-label-admin { font-size: 11px; color: #888; margin: 8px 0 4px; }
`;

const PANEL_HTML = `
  <style>${PANEL_STYLE}</style>
  <div id="rnm-ops">
    <h3>⚙ Ranomany Ops</h3>
    <div id="rnm-log">Loading log…</div>
    <hr/>
    <button id="rnm-restart">⟳ Restart ComfyUI</button>
    <hr/>
    <input id="rnm-pw" type="password" placeholder="Admin password" autocomplete="off"/>
    <div id="rnm-admin">
      <div id="rnm-label-admin">— Admin actions —</div>
      <button id="rnm-update">⬆ Update &amp; Restart</button>
      <pre id="rnm-out"></pre>
      <select id="rnm-tag">
        <option value="">↩ Select rollback tag…</option>
      </select>
      <button id="rnm-rollback">↩ Rollback &amp; Restart</button>
    </div>
    <div id="rnm-msg"></div>
  </div>
`;

// ── Panel logic ────────────────────────────────────────────────────────────────

function mountPanel(el) {
    el.innerHTML = PANEL_HTML;

    const $ = (id) => el.querySelector(`#${id}`);

    const logEl     = $("rnm-log");
    const restartEl = $("rnm-restart");
    const pwEl      = $("rnm-pw");
    const adminEl   = $("rnm-admin");
    const updateEl  = $("rnm-update");
    const outEl     = $("rnm-out");
    const tagEl     = $("rnm-tag");
    const rollbackEl = $("rnm-rollback");
    const msgEl     = $("rnm-msg");

    let locked = false;

    function setMsg(text, color = "#f80") {
        msgEl.style.color = color;
        msgEl.textContent = text;
    }

    function lock() {
        locked = true;
        [restartEl, updateEl, rollbackEl].forEach(b => b.disabled = true);
        pwEl.disabled = true;
    }

    // Load last ops log entry
    async function loadLog() {
        try {
            const r = await api.fetchApi("/ranomany/ops-log");
            const data = await r.json();
            const lines = data.lines || [];
            logEl.textContent = lines.length ? lines[lines.length - 1] : "(no log entries yet)";
        } catch {
            logEl.textContent = "(could not load log)";
        }
    }

    // Load rollback tags into select
    async function loadTags() {
        try {
            const r = await api.fetchApi("/ranomany/rollback-tags");
            const data = await r.json();
            const tags = data.tags || [];
            tagEl.innerHTML = `<option value="">↩ Select rollback tag…</option>` +
                tags.map(t => `<option value="${t}">${t}</option>`).join("");
        } catch {
            // ignore — tags section just stays empty
        }
    }

    // Restart
    restartEl.addEventListener("click", async () => {
        if (locked) return;
        if (!confirm("Restart ComfyUI now?")) return;
        lock();
        setMsg("Restarting…", "#aef");
        try {
            await api.fetchApi("/ranomany/restart", { method: "POST" });
        } catch {
            // Expected — server exits before responding
        }
    });

    // Password reveal
    pwEl.addEventListener("input", () => {
        const hasPassword = pwEl.value.length > 0;
        adminEl.style.display = hasPassword ? "block" : "none";
        if (hasPassword) loadTags();
    });

    // Update
    updateEl.addEventListener("click", async () => {
        if (locked) return;
        if (!confirm("Pull latest code and restart ComfyUI?")) return;
        lock();
        setMsg("Updating…", "#aef");
        outEl.style.display = "block";
        outEl.textContent = "";
        try {
            const r = await api.fetchApi("/ranomany/update", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ password: pwEl.value }),
            });
            const data = await r.json();
            if (!r.ok) {
                outEl.textContent = data.output || "";
                setMsg(`Error: ${data.error}`, "#f44");
                [updateEl, rollbackEl].forEach(b => b.disabled = false);
                pwEl.disabled = false;
                locked = false;
                return;
            }
            outEl.textContent = data.output || "";
            setMsg(`Updated — tag: ${data.rollback_tag}. Restarting…`, "#8f8");
        } catch {
            setMsg("Request failed or server restarted.", "#f80");
        }
    });

    // Rollback
    rollbackEl.addEventListener("click", async () => {
        if (locked) return;
        const tag = tagEl.value;
        if (!tag) { setMsg("Select a tag first.", "#f80"); return; }
        if (!confirm(`Roll back to ${tag} and restart?`)) return;
        lock();
        setMsg(`Rolling back to ${tag}…`, "#aef");
        try {
            const r = await api.fetchApi("/ranomany/rollback", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ password: pwEl.value, tag }),
            });
            const data = await r.json();
            if (!r.ok) {
                setMsg(`Error: ${data.error}`, "#f44");
                [updateEl, rollbackEl].forEach(b => b.disabled = false);
                pwEl.disabled = false;
                locked = false;
                return;
            }
            setMsg(`Rolled back to ${tag}. Restarting…`, "#8f8");
        } catch {
            setMsg("Request failed or server restarted.", "#f80");
        }
    });

    loadLog();
}

// ── Register sidebar tab ───────────────────────────────────────────────────────
// Must be inside setup() — extensionManager is not ready at module load time.

app.registerExtension({
    name: "Ranomany.OpsDock",
    async setup() {
        app.extensionManager.registerSidebarTab({
            id: "ranomany.ops",
            icon: "pi pi-cog",
            title: "Ranomany Ops",
            tooltip: "Ranomany Ops — restart, update, rollback",
            type: "custom",
            render: mountPanel,
        });
    },
});
