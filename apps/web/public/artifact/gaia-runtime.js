/* gaia-runtime: the only script in an artifact. Interaction state is client-side; there is no model code and no network. */
(() => {
  const $$ = (root, sel) => Array.from(root.querySelectorAll(sel));
  const visible = (el) => el.getClientRects().length > 0;

  /* charts: tooltips on any [data-tip] mark, arrow keys to step through them, legend toggles per series */
  function charts(root) {
    for (const plot of $$(root, ".chart-plot")) {
      const tip = plot.querySelector(".chart-tip");
      if (!tip) continue;
      let idx = -1;
      const marks = () => $$(plot, "[data-tip]").filter((m) => visible(m) && !m.closest(".off"));
      const show = (mark, x, y) => {
        $$(plot, ".is-hot").forEach((m) => m.classList.remove("is-hot"));
        mark.classList.add("is-hot");
        tip.textContent = mark.dataset.tip;
        tip.dataset.on = "";
        const box = plot.getBoundingClientRect();
        const w = tip.offsetWidth;
        const left = Math.min(Math.max(0, x - box.left + 12), box.width - w);
        tip.style.left = `${left}px`;
        tip.style.top = `${Math.max(0, y - box.top - 44)}px`;
      };
      const hide = () => {
        delete tip.dataset.on;
        $$(plot, ".is-hot").forEach((m) => m.classList.remove("is-hot"));
      };
      plot.addEventListener("pointermove", (ev) => {
        const mark = ev.target.closest("[data-tip]");
        if (mark) show(mark, ev.clientX, ev.clientY);
        else hide();
      });
      plot.addEventListener("pointerleave", hide);
      plot.addEventListener("blur", hide);
      plot.addEventListener("keydown", (ev) => {
        const step = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[ev.key];
        if (ev.key === "Escape") return hide();
        if (!step) return;
        ev.preventDefault();
        const list = marks();
        if (!list.length) return;
        idx = (idx + step + list.length) % list.length;
        const r = list[idx].getBoundingClientRect();
        show(list[idx], r.left + r.width / 2, r.top);
      });
    }
    for (const btn of $$(root, ".chart-legend button[data-series]")) {
      btn.addEventListener("click", () => {
        const fig = btn.closest("figure");
        const on = btn.getAttribute("aria-pressed") === "true";
        const pressed = $$(fig, ".chart-legend button[aria-pressed='true']");
        if (on && pressed.length === 1) return; // keep one series visible
        btn.setAttribute("aria-pressed", String(!on));
        fig.classList.toggle(`off-${btn.dataset.series}`, on);
      });
    }
  }

  /* tables: sort by any header, filter long tables, open a summary row into its detail rows */
  function tables(root) {
    for (const wrap of $$(root, ".table[data-sortable]")) {
      const tbody = wrap.querySelector("tbody");
      for (const btn of $$(wrap, "thead button[data-sort]")) {
        btn.addEventListener("click", () => {
          const col = Number(btn.dataset.sort);
          const th = btn.closest("th");
          const dir = th.getAttribute("aria-sort") === "ascending" ? -1 : 1;
          $$(wrap, "thead th").forEach((h) => h.removeAttribute("aria-sort"));
          th.setAttribute("aria-sort", dir === 1 ? "ascending" : "descending");
          const groups = $$(tbody, "tr:not(.child)").map((r) => [r, $$(tbody, `tr.child[data-parent="${r.dataset.row}"]`)]);
          const key = (r) => r.children[col]?.dataset.key ?? r.children[col]?.textContent ?? "";
          groups.sort(([a], [b]) => {
            const x = key(a), y = key(b);
            const nx = Number(x), ny = Number(y);
            const cmp = x !== "" && y !== "" && !Number.isNaN(nx) && !Number.isNaN(ny) ? nx - ny : x.localeCompare(y, undefined, { numeric: true });
            return cmp * dir;
          });
          for (const [row, kids] of groups) tbody.append(row, ...kids);
        });
      }
      const filter = wrap.querySelector("[data-filter]");
      filter?.addEventListener("input", () => {
        const q = filter.value.trim().toLowerCase();
        for (const r of $$(tbody, "tr:not(.child)")) {
          const hit = !q || r.textContent.toLowerCase().includes(q);
          r.hidden = !hit;
          if (!hit) $$(tbody, `tr.child[data-parent="${r.dataset.row}"]`).forEach((c) => { c.hidden = true; });
        }
      });
    }
    for (const btn of $$(root, "button.drill")) {
      btn.addEventListener("click", () => {
        const open = btn.getAttribute("aria-expanded") !== "true";
        btn.setAttribute("aria-expanded", String(open));
        const tbody = btn.closest("tbody");
        $$(tbody, `tr.child[data-parent="${btn.dataset.drill}"]`).forEach((r) => { r.hidden = !open; });
      });
    }
  }

  /* calculator: the same small grammar the server validated: numbers, input ids, + - * / ** and a few functions */
  const FUNCS = { min: Math.min, max: Math.max, round: Math.round, abs: Math.abs, floor: Math.floor, ceil: Math.ceil, pow: Math.pow, sqrt: Math.sqrt };
  function evaluate(expr, vars) {
    const toks = expr.match(/\d+(?:\.\d+)?|[a-z_][a-z0-9_]*|\*\*|[-+*/(),]/g) || [];
    let i = 0;
    const peek = () => toks[i];
    const take = () => toks[i++];
    const atom = () => {
      const t = take();
      if (t === "-") return -atom();
      if (t === "+") return atom();
      if (t === "(") { const v = sum(); take(); return v; }
      if (/^\d/.test(t)) return Number(t);
      if (t in FUNCS) { take(); const args = [sum()]; while (peek() === ",") { take(); args.push(sum()); } take(); return FUNCS[t](...args); }
      return Number(vars[t]) || 0;
    };
    const power = () => { const b = atom(); if (peek() === "**") { take(); return b ** power(); } return b; };
    const product = () => { let v = power(); while (peek() === "*" || peek() === "/") { const op = take(); const r = power(); v = op === "*" ? v * r : r ? v / r : 0; } return v; };
    const sum = () => { let v = product(); while (peek() === "+" || peek() === "-") { const op = take(); const r = product(); v = op === "+" ? v + r : v - r; } return v; };
    return sum();
  }
  function calculators(root) {
    for (const form of $$(root, "form[data-calc]")) {
      const run = () => {
        const vars = {};
        for (const el of form.elements) if (el.name) vars[el.name] = Number(el.value);
        for (const out of $$(form, "output[data-for]")) {
          out.textContent = out.dataset.prefix + form.elements[out.dataset.for].value + out.dataset.suffix;
        }
        for (const out of $$(form, "output[data-formula]")) {
          const v = evaluate(out.dataset.formula, vars);
          const d = Number(out.dataset.decimals);
          const n = Math.abs(v).toLocaleString("en", { minimumFractionDigits: d, maximumFractionDigits: d });
          out.textContent = (v < 0 ? "−" : "") + out.dataset.prefix + n + out.dataset.suffix;
        }
      };
      form.addEventListener("input", run);
      // outputs start empty in model-written markup, so compute them from the defaults now
      run();
    }
  }

  function init(root) {
    charts(root);
    tables(root);
    calculators(root);
  }

  /* live data: only the embedding GAIA page may swap a bound block, and only for a block that declared the binding */
  window.addEventListener("message", (ev) => {
    if (ev.source !== window.parent || !ev.data || ev.data.type !== "gaia:block") return;
    const { bind, html, updatedAt } = ev.data;
    if (typeof bind !== "string" || typeof html !== "string") return;
    const old = document.querySelector(`[data-bind="${CSS.escape(bind)}"]`);
    if (!old) return;
    const tpl = document.createElement("template");
    tpl.innerHTML = html;
    const fresh = tpl.content.firstElementChild;
    if (!fresh || fresh.getAttribute("data-bind") !== bind || tpl.content.querySelector("script")) return;
    old.replaceWith(fresh);
    const stamp = fresh.querySelector("[data-live-stamp]");
    if (stamp) { stamp.hidden = false; stamp.textContent = `Live · updated ${updatedAt}`; }
    init(fresh);
  });

  init(document);
})();
