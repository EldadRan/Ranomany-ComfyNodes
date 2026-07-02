import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

// Custom sidebar-tab icon: our reticle mark (web/ops_icon.svg). ComfyUI renders the tab
// icon as an element with the given class, and icon fonts draw via ::before — so we point
// ::before at the SVG via a CSS mask, filled with currentColor so it recolors with the
// theme and highlights on the active tab, matching the built-in PrimeIcons. The URL is
// resolved from this module's location so it works wherever the extension is mounted.
(function injectOpsIcon() {
    const id = "ranomany-ops-icon-style";
    if (document.getElementById(id)) return;
    const iconURL = new URL("./ops_icon.svg", import.meta.url).href;
    const s = document.createElement("style");
    s.id = id;
    s.textContent =
        ".rnm-ops-icon::before{content:'';display:inline-block;width:1em;height:1em;" +
        "vertical-align:-0.125em;background:currentColor;" +
        `-webkit-mask:url('${iconURL}') center/contain no-repeat;` +
        `mask:url('${iconURL}') center/contain no-repeat;}`;
    document.head.appendChild(s);
})();

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
  #rnm-usage-me { color: #9cf; font-size: 11px; margin-bottom: 6px; }
  #rnm-usage-table { width: 100%; border-collapse: collapse; font-size: 10px; }
  #rnm-usage-table th, #rnm-usage-table td {
    border: 1px solid #333; padding: 3px 5px; text-align: left;
  }
  #rnm-usage-table th { color: #888; font-weight: normal; }
  #rnm-usage-table td.num { text-align: right; }
  #rnm-usage-wrap { display: none; max-height: 220px; overflow: auto; margin-top: 4px; }
`;

const PANEL_HTML = `
  <style>${PANEL_STYLE}</style>
  <div id="rnm-ops">
    <h3>⚙ Ranomaly Ops</h3>
    <div id="rnm-log">Loading log…</div>
    <hr/>
    <h3>◷ Usage</h3>
    <div id="rnm-usage-me">Loading usage…</div>
    <div id="rnm-usage-wrap"><table id="rnm-usage-table"></table></div>
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
      <button id="rnm-report">✉ Send weekly report now</button>
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
    const reportEl  = $("rnm-report");
    const msgEl     = $("rnm-msg");
    const usageMeEl = $("rnm-usage-me");
    const usageWrapEl = $("rnm-usage-wrap");
    const usageTableEl = $("rnm-usage-table");

    let locked = false;

    function setMsg(text, color = "#f80") {
        msgEl.style.color = color;
        msgEl.textContent = text;
    }

    function lock() {
        locked = true;
        [restartEl, updateEl, rollbackEl, reportEl].forEach(b => b.disabled = true);
        pwEl.disabled = true;
    }

    // "3 days ago" style relative time from an ISO8601 string
    function ago(iso) {
        if (!iso) return "—";
        const then = Date.parse(iso);
        if (isNaN(then)) return iso;
        const s = Math.max(0, (Date.now() - then) / 1000);
        if (s < 90) return "just now";
        const units = [["day", 86400], ["hr", 3600], ["min", 60]];
        for (const [name, secs] of units) {
            const n = Math.floor(s / secs);
            if (n >= 1) return `${n} ${name}${n > 1 ? "s" : ""} ago`;
        }
        return "just now";
    }

    // Load usage: own stats (always) + all-users table (only if allowlisted -> 200)
    async function loadUsage() {
        try {
            const r = await api.fetchApi("/ranomany/usage");
            const d = await r.json();
            usageMeEl.textContent = d.email
                ? `You (${d.email}): ${d.image} img · ${d.video} vid · ${d.utils} utils this month`
                  + ` (${d.total} lifetime) · last seen ${ago(d.last_seen)}`
                : "Not identified (no Cloudflare Access header).";
        } catch {
            usageMeEl.textContent = "(could not load usage)";
        }
        try {
            const r = await api.fetchApi("/ranomany/usage/all");
            if (!r.ok) { usageWrapEl.style.display = "none"; return; }
            const d = await r.json();
            const rows = d.users || [];
            usageTableEl.innerHTML =
                `<tr><th>User</th><th>Img</th><th>Vid</th><th>Util</th><th>Last seen</th></tr>` +
                (rows.length
                    ? rows.map(u => `<tr><td>${u.email}</td>` +
                        `<td class="num">${u.image}</td>` +
                        `<td class="num">${u.video}</td>` +
                        `<td class="num">${u.utils}</td>` +
                        `<td>${ago(u.last_seen)}</td></tr>`).join("")
                    : `<tr><td colspan="5">(no activity yet)</td></tr>`);
            usageWrapEl.style.display = "block";
        } catch {
            usageWrapEl.style.display = "none";
        }
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

    // Send weekly report now (admin — reuses the password field)
    reportEl.addEventListener("click", async () => {
        if (locked) return;
        if (!confirm("Send the weekly usage report now?")) return;
        setMsg("Sending report…", "#aef");
        reportEl.disabled = true;
        try {
            const r = await api.fetchApi("/ranomany/quota-report", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ password: pwEl.value }),
            });
            const data = await r.json();
            if (!r.ok || !data.sent) {
                setMsg(`Report failed: ${data.error || r.status}`, "#f44");
            } else {
                setMsg(`Report sent to ${(data.recipients || []).join(", ")}`, "#8f8");
            }
        } catch {
            setMsg("Report request failed.", "#f80");
        }
        reportEl.disabled = false;
    });

    loadLog();
    loadUsage();
}

// ── Register sidebar tab ───────────────────────────────────────────────────────
// Must be inside setup() — extensionManager is not ready at module load time.

app.registerExtension({
    name: "Ranomany.OpsDock",
    async setup() {
        app.extensionManager.registerSidebarTab({
            id: "ranomany.ops",
            icon: "pi rnm-ops-icon",
            title: "Ranomaly",
            tooltip: "Ranomaly Ops — restart, update, rollback",
            type: "custom",
            render: mountPanel,
        });
    },
});
