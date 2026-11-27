"use strict";
(() => {
  const $ = (s) => document.querySelector(s);
  const $$ = (s) => Array.from(document.querySelectorAll(s));
  const SAMPLE =
    "Huffman coding assigns shorter binary codes to frequent symbols and longer codes to rare ones.\n" +
    "In the sentence you are reading, the letters e, t, a and the space character appear most often,\n" +
    "so they receive the shortest codes. Unicode works too: café, naïve, 日本語, привет, 🙂.\n\n" +
    "Repeat after me: compression is just clever bookkeeping. Compression is just clever bookkeeping.\n";

  const state = { mode: "compress", cBytes: null, cName: "", dBytes: null, dName: "", report: null,
                  download: null, scale: 1, treeSize: { w: 1, h: 1 } };

  // ---------- helpers ----------
  const fmtInt = (n) => Number(n).toLocaleString("en-US");
  const fmtMs = (x) => (x == null ? "—" : x.toFixed(x < 10 ? 3 : 2) + " ms");
  const fmtBytes = (n) => fmtInt(n) + " B";
  const b64ToBytes = (b64) => { const bin = atob(b64); const out = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i); return out; };
  const shortNum = (n) => (n >= 1e6 ? (n / 1e6).toFixed(1) + "M" : n >= 1e4 ? (n / 1e3).toFixed(0) + "k" : String(n));
  const showError = (msg) => { const e = $("#error"); e.textContent = msg; e.hidden = !msg; };

  async function post(url, bytes) {
    const resp = await fetch(url, { method: "POST", body: bytes, headers: { "Content-Type": "application/octet-stream" } });
    let json;
    try { json = await resp.json(); } catch { throw new Error("Server returned an unreadable response."); }
    if (!resp.ok) throw new Error(json.error || "Request failed (" + resp.status + ")");
    return json;
  }

  // ---------- mode + sub-tabs ----------
  $$(".tab").forEach((b) => b.addEventListener("click", () => {
    state.mode = b.dataset.mode;
    $$(".tab").forEach((t) => { const on = t === b; t.classList.toggle("active", on); t.setAttribute("aria-selected", on); });
    $("#panel-compress").hidden = state.mode !== "compress";
    $("#panel-decompress").hidden = state.mode !== "decompress";
    showError("");
  }));
  function showView(name) {
    $$(".subtab").forEach((t) => t.classList.toggle("active", t.dataset.view === name));
    $$(".view").forEach((v) => (v.hidden = v.id !== "view-" + name));
    if (name === "tree") fitTree();
  }
  $$(".subtab").forEach((t) => t.addEventListener("click", () => showView(t.dataset.view)));

  // ---------- file inputs ----------
  function wireDrop(zone, input, onFile) {
    input.addEventListener("change", () => input.files[0] && onFile(input.files[0]));
    ["dragenter", "dragover"].forEach((ev) => zone.addEventListener(ev, (e) => { e.preventDefault(); zone.classList.add("over"); }));
    ["dragleave", "drop"].forEach((ev) => zone.addEventListener(ev, (e) => { e.preventDefault(); zone.classList.remove("over"); }));
    zone.addEventListener("drop", (e) => e.dataTransfer.files[0] && onFile(e.dataTransfer.files[0]));
  }
  const readBytes = async (f) => new Uint8Array(await f.arrayBuffer());

  wireDrop($("#drop-c"), $("#file-c"), async (f) => {
    state.cBytes = await readBytes(f); state.cName = f.name;
    $("#chip-c-name").textContent = f.name + " · " + fmtBytes(f.size);
    $("#chip-c").hidden = false; $("#text-input").value = ""; $("#text-input").disabled = true;
  });
  $("#chip-c-clear").addEventListener("click", () => {
    state.cBytes = null; state.cName = ""; $("#file-c").value = "";
    $("#chip-c").hidden = true; $("#text-input").disabled = false;
  });
  wireDrop($("#drop-d"), $("#file-d"), async (f) => {
    state.dBytes = await readBytes(f); state.dName = f.name;
    $("#chip-d-name").textContent = f.name + " · " + fmtBytes(f.size); $("#chip-d").hidden = false;
  });
  $("#chip-d-clear").addEventListener("click", () => {
    state.dBytes = null; state.dName = ""; $("#file-d").value = ""; $("#chip-d").hidden = true;
  });
  $("#btn-sample").addEventListener("click", () => {
    $("#chip-c-clear").click(); $("#text-input").value = SAMPLE;
  });

  // ---------- actions ----------
  async function run(btn, statusEl, label, fn) {
    showError(""); btn.disabled = true; statusEl.textContent = label;
    try { await fn(); statusEl.textContent = ""; }
    catch (err) { statusEl.textContent = ""; showError(err.message); }
    finally { btn.disabled = false; }
  }

  $("#btn-compress").addEventListener("click", () => run($("#btn-compress"), $("#status-c"), "Compressing…", async () => {
    const bytes = state.cBytes || new TextEncoder().encode($("#text-input").value);
    const rep = await post("/api/compress", bytes);
    const base = state.cName || "pasted-text.txt";
    state.download = { name: base + ".huff", bytes: b64ToBytes(rep.huff_base64), type: "application/octet-stream" };
    render(rep, "compress", "Compression result", "Download .huff");
  }));

  $("#btn-decompress").addEventListener("click", () => run($("#btn-decompress"), $("#status-d"), "Decompressing…", async () => {
    if (!state.dBytes) throw new Error("Choose a .huff file first.");
    const rep = await post("/api/decompress", state.dBytes);
    let name = state.dName.replace(/\.huff$/i, "") || "restored";
    if (name === state.dName || !/\.[^.]+$/.test(name)) name += ".txt";
    state.download = { name, bytes: b64ToBytes(rep.data_base64), type: "text/plain" };
    render(rep, "decompress", "Decompression result", "Download restored file");
  }));

  $("#btn-download").addEventListener("click", () => {
    const d = state.download; if (!d) return;
    const url = URL.createObjectURL(new Blob([d.bytes], { type: d.type }));
    const a = document.createElement("a"); a.href = url; a.download = d.name;
    document.body.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  });

  // ---------- rendering ----------
  function render(r, mode, title, dlLabel) {
    state.report = r;
    $("#results").hidden = false;
    $("#result-title").textContent = title;
    $("#btn-download").textContent = dlLabel;
    const v = $("#verified");
    v.textContent = r.verified ? "✓ Lossless · SHA-256 verified" : "✗ Verification failed";
    v.className = "badge " + (r.verified ? "ok" : "bad");

    $("#s-original").textContent = fmtBytes(r.original_size);
    $("#s-compressed").textContent = fmtBytes(r.compressed_size);
    $("#s-ratio").textContent = r.ratio ? r.ratio.toFixed(3) + " : 1" : "n/a";
    $("#s-saved").textContent = r.space_saved_percent.toFixed(2) + " %";
    $("#s-encode").textContent = fmtMs(r.encode_ms);
    $("#s-decode").textContent = fmtMs(r.decode_ms);

    const cw = r.original_size ? Math.min(100, (r.compressed_size / r.original_size) * 100) : 0;
    $("#bar-o").style.width = r.original_size ? "100%" : "0%";
    $("#bar-c").style.width = cw + "%";
    $("#bar-o-t").textContent = fmtBytes(r.original_size);
    $("#bar-c-t").textContent = fmtBytes(r.compressed_size);

    renderTable(r.table); $("#filter").value = "";
    renderDetails(r);
    state.scale = 1; drawTree(r.tree);

    const hasText = mode === "decompress";
    $("#subtab-text").hidden = !hasText;
    if (hasText) {
      $("#text-preview").textContent = r.text;
      $("#text-note").textContent = r.text_truncated ? "Preview truncated to the first 100,000 bytes — the download contains the full file." : "";
    }
    showView("codes");
    $("#results").scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function renderTable(rows) {
    const body = $("#code-table tbody"); body.textContent = "";
    const frag = document.createDocumentFragment();
    for (const row of rows) {
      const tr = document.createElement("tr");
      tr.dataset.q = (row.label + " " + row.hex + " " + row.code).toLowerCase();
      const cells = [[row.label, "sym"], [row.hex, ""], [fmtInt(row.freq), "num"], [row.percent.toFixed(2) + "%", "num"],
                     [String(row.length), "num"], [row.code, "code"]];
      for (const [text, cls] of cells) { const td = document.createElement("td"); td.textContent = text; if (cls) td.className = cls; tr.appendChild(td); }
      frag.appendChild(tr);
    }
    body.appendChild(frag);
  }
  $("#filter").addEventListener("input", (e) => {
    const q = e.target.value.trim().toLowerCase();
    $$("#code-table tbody tr").forEach((tr) => (tr.hidden = q && !tr.dataset.q.includes(q)));
  });

  function renderDetails(r) {
    const stage = r.stage_ms;
    const rows = [
      ["Header size", fmtBytes(r.header_size) + " (48 B fixed + 2 B per unique symbol)"],
      ["Payload size", fmtBytes(r.payload_size)],
      ["Padding bits (last byte)", String(r.padding_bits)],
      ["Unique symbols (K)", String(r.unique_symbols)],
      ["Average code length", r.avg_code_length.toFixed(4) + " bits/symbol"],
      ["Shannon entropy (lower bound)", r.entropy.toFixed(4) + " bits/symbol"],
      ["Coding efficiency", r.avg_code_length ? ((r.entropy / r.avg_code_length) * 100).toFixed(2) + " %" : "n/a"],
      ["SHA-256 of original", r.sha256],
    ];
    if (stage) {
      rows.push(["Stage: count frequencies", fmtMs(stage.frequency_count)], ["Stage: build tree (min-heap)", fmtMs(stage.build_tree)],
                ["Stage: generate codes", fmtMs(stage.generate_codes)], ["Stage: pack bits + header", fmtMs(stage.pack_bits_and_header)]);
    }
    const body = $("#details-body"); body.textContent = "";
    for (const [k, v] of rows) {
      const tr = document.createElement("tr"); const th = document.createElement("th"); const td = document.createElement("td");
      th.textContent = k; td.textContent = v; if (k.startsWith("SHA")) td.style.wordBreak = "break-all";
      tr.append(th, td); body.appendChild(tr);
    }
  }

  // ---------- tree ----------
  const NS = "http://www.w3.org/2000/svg";
  const XS = 58, YS = 74, PAD = 40;
  function el(name, attrs, text) {
    const n = document.createElementNS(NS, name);
    for (const k in attrs) n.setAttribute(k, attrs[k]);
    if (text != null) n.textContent = text; return n;
  }
  function drawTree(tree) {
    const box = $("#tree-box"); box.textContent = "";
    if (!tree) { box.textContent = "Empty input — no tree."; box.style.padding = "16px"; return; }
    box.style.padding = "0";
    let leafIdx = 0, maxDepth = 0; const nodes = [];
    (function walk(n, d) {
      n.depth = d; maxDepth = Math.max(maxDepth, d); nodes.push(n);
      if (!n.children.length) { n.x = leafIdx++; return; }
      n.children.forEach((c) => walk(c, d + 1));
      n.x = (n.children[0].x + n.children[n.children.length - 1].x) / 2;
    })(tree, 0);
    const W = Math.max(leafIdx, 1) * XS + PAD * 2, H = (maxDepth + 1) * YS + PAD;
    state.treeSize = { w: W, h: H };
    const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "Huffman tree" });
    const px = (n) => PAD + n.x * XS + XS / 2 - XS / 2, py = (n) => PAD / 2 + n.depth * YS + 14;
    for (const n of nodes) for (const c of n.children) {
      svg.appendChild(el("line", { class: "edge", x1: px(n), y1: py(n), x2: px(c), y2: py(c) }));
      svg.appendChild(el("text", { class: "bit", x: (px(n) + px(c)) / 2 + (c.bit ? 8 : -8), y: (py(n) + py(c)) / 2 }, String(c.bit)));
    }
    for (const n of nodes) {
      const g = el("g", {}); const x = px(n), y = py(n);
      if (n.symbol == null) {
        g.appendChild(el("circle", { class: "inode", cx: x, cy: y, r: 17 }));
        g.appendChild(el("text", { class: "w", x, y: y + 3.5 }, shortNum(n.freq)));
        g.appendChild(el("title", {}, "weight " + fmtInt(n.freq)));
      } else {
        g.appendChild(el("rect", { class: "leaf", x: x - 22, y: y - 16, width: 44, height: 34, rx: 6 }));
        g.appendChild(el("text", { class: "l", x, y: y - 1 }, n.label.length > 5 ? "…" + n.label.slice(-2) : n.label));
        g.appendChild(el("text", { class: "f", x, y: y + 12 }, shortNum(n.freq)));
        g.appendChild(el("title", {}, n.label + " · " + fmtInt(n.freq) + " occurrences"));
      }
      svg.appendChild(g);
    }
    box.appendChild(svg); applyScale();
  }
  function applyScale() {
    const svg = $("#tree-box svg"); if (!svg) return;
    svg.setAttribute("width", Math.round(state.treeSize.w * state.scale));
    svg.setAttribute("height", Math.round(state.treeSize.h * state.scale));
  }
  function fitTree() {
    const box = $("#tree-box"); if (!box.firstChild || !box.clientWidth) return;
    state.scale = Math.min(1, (box.clientWidth - 2) / state.treeSize.w); applyScale();
  }
  $("#zoom-in").addEventListener("click", () => { state.scale = Math.min(3, state.scale * 1.25); applyScale(); });
  $("#zoom-out").addEventListener("click", () => { state.scale = Math.max(0.1, state.scale / 1.25); applyScale(); });
  $("#zoom-fit").addEventListener("click", fitTree);
})();
