// ── Layers View: stacked pills with curved connections ──
let layersInitialized = false;
let focusMode = false;
let focusedId = null;

function renderLayers() {
  if (layersInitialized) return;
  layersInitialized = true;

  if (!LAYERS.layers.length) {
    document.getElementById('layers-svg').outerHTML =
      '<div class="flex items-center justify-center h-full text-overlay0">No structural data available for layers view.</div>';
    return;
  }

  const svg = d3.select("#layers-svg");
  const W = window.innerWidth;
  const H = window.innerHeight - 60;
  const g = svg.append("g");
  const zoomBehavior = d3.zoom().scaleExtent([0.02, 10]).on("zoom", (e) => g.attr("transform", e.transform));
  svg.call(zoomBehavior);

  const tooltip = d3.select("#layers-tooltip");
  const info = document.getElementById("layer-info");

  // ── Build dependency maps ──
  const parentsOf = {};   // name → [input names]
  const childrenOf = {};  // name → [consumer names]
  LAYERS.edges.forEach(e => {
    if (!parentsOf[e.target]) parentsOf[e.target] = [];
    parentsOf[e.target].push(e.source);
    if (!childrenOf[e.source]) childrenOf[e.source] = [];
    childrenOf[e.source].push(e.target);
  });

  function collectPath(id) {
    const path = new Set();
    const upQ = [id];
    while (upQ.length) {
      const n = upQ.pop();
      if (path.has(n)) continue;
      path.add(n);
      (parentsOf[n] || []).forEach(p => upQ.push(p));
    }
    const downQ = [id];
    while (downQ.length) {
      const n = downQ.pop();
      if (path.has(n)) continue;
      path.add(n);
      (childrenOf[n] || []).forEach(c => downQ.push(c));
    }
    return path;
  }

  // ── Layout: "rails but pills" — input column + result column per layer ──
  const PH = 26;           // result pill height
  const SUB_PH = 18;       // input sub-pill height
  const PW_MIN = 130;      // min result pill width
  const PW_MAX = 240;      // max result pill width
  const SPW_MIN = 80;      // min sub-pill width
  const SPW_MAX = 180;     // max sub-pill width
  const GAP_X = 50;        // gap between layers
  const GAP_XI = 12;       // gap between input col and result col
  const GAP_Y = 8;         // gap between consumer rows
  const SUB_GAP_Y = 2;     // gap between input pills in a group
  const LABEL_H = 68;      // layer label height (L title + stats widget)
  const HEADER_GAP = 18;   // gap between header zone and pill stacks
  const PAD = 30;           // padding

  const pos = {};
  const nodeData = {};
  const inputPillData = {};

  function getConsumerInputs(n) {
    // Uses and declares (facts) get input sub-pills. Pulls are just lines.
    const pills = [];
    (n.uses || []).forEach(u => pills.push({id: 'inp:'+u+'>'+n.name, label: u, consumer: n.name, type: 'use'}));
    (n.declares || []).forEach(d => pills.push({id: 'inp:'+d+'>'+n.name, label: d, consumer: n.name, type: 'declare'}));
    return pills;
  }

  const TYPE_COLOR = {'use':'#a6e3a1','declare':'#6c7086','pull':'#89b4fa','axiom-ref':'#fab387'};
  const TYPE_STROKE = {'use':'#a6e3a1','declare':'#585b70','pull':'#89b4fa'};

  // ── Identify hanging nodes: L0 nodes that never reach a deeper layer ──
  // A node is hanging if no path from it leads to any node in layer > 0.
  const deepNames = new Set();
  LAYERS.layers.forEach(lay => { if (lay.depth > 0) lay.nodes.forEach(n => deepNames.add(n.name)); });
  const l0Names = new Set();
  LAYERS.layers.forEach(lay => { if (lay.depth === 0) lay.nodes.forEach(n => l0Names.add(n.name)); });
  // Build forward adjacency: source → [targets]
  const fwd = {};
  LAYERS.edges.forEach(e => { if (!fwd[e.source]) fwd[e.source] = []; fwd[e.source].push(e.target); });
  // BFS from each L0 node — does it reach any deep node?
  const reachesDeep = new Set();
  l0Names.forEach(start => {
    if (reachesDeep.has(start)) return;
    const visited = new Set();
    const q = [start];
    let found = false;
    while (q.length) {
      const n = q.pop();
      if (visited.has(n)) continue;
      visited.add(n);
      if (deepNames.has(n)) { found = true; break; }
      (fwd[n] || []).forEach(t => q.push(t));
    }
    if (found) visited.forEach(v => { if (l0Names.has(v)) reachesDeep.add(v); });
  });
  const hangingNodes = [];

  // ── Measure and layout ──
  let curX = PAD;
  LAYERS.layers.forEach((lay, li) => {
    // Separate hanging from connected in layer 0
    if (lay.depth === 0) {
      const connected = [];
      lay.nodes.forEach(n => {
        nodeData[n.name] = n;
        if (reachesDeep.has(n.name)) connected.push(n);
        else hangingNodes.push(n);
      });
      lay.nodes = connected;
      if (!connected.length) return;
    } else {
      lay.nodes.forEach(n => { nodeData[n.name] = n; });
    }

    // Collect input pills — deduped by source name within layer (uses + declares)
    const useSeen = {};
    const layerInputs = [];
    lay.nodes.forEach(n => {
      (n.uses || []).forEach(u => {
        if (!useSeen[u]) {
          useSeen[u] = {id: 'inp:'+u+'@'+li, label: u, consumers: [], type: 'use'};
          layerInputs.push(useSeen[u]);
        }
        useSeen[u].consumers.push(n.name);
      });
      (n.declares || []).forEach(d => {
        if (!useSeen[d]) {
          useSeen[d] = {id: 'inp:'+d+'@'+li, label: d, consumers: [], type: 'declare'};
          layerInputs.push(useSeen[d]);
        }
        useSeen[d].consumers.push(n.name);
      });
    });
    layerInputs.forEach(p => { inputPillData[p.id] = p; });
    const hasInputs = layerInputs.length > 0;

    // Measure input column width
    let inputColW = 0;
    if (hasInputs) {
      layerInputs.forEach(inp => {
        const short = inp.label.includes('.') ? inp.label.split('.').slice(1).join('.') : inp.label;
        inp._w = Math.min(SPW_MAX, Math.max(SPW_MIN, short.length * 5.5 + 20));
        inputColW = Math.max(inputColW, inp._w);
      });
    }

    // Measure result column width
    let resultColW = 0;
    lay.nodes.forEach(n => {
      const short = n.name.includes('.') ? n.name.split('.').slice(1).join('.') : n.name;
      const label = short + (n.value ? ' =' + String(n.value).slice(0,15) : '');
      n._w = Math.min(PW_MAX, Math.max(PW_MIN, label.length * 6.5 + 28));
      resultColW = Math.max(resultColW, n._w);
    });

    const inputX = curX;
    const resultX = hasInputs ? curX + inputColW + GAP_XI : curX;
    lay._labelX = curX;
    lay._colW = resultX + resultColW - curX;
    lay._inputX = inputX;
    lay._inputColW = inputColW;
    lay._hasInputs = hasInputs;

    // Position input pills (deduped, stacked in input column)
    let inputY = PAD + LABEL_H + HEADER_GAP;
    layerInputs.forEach(inp => {
      pos[inp.id] = {
        x: inputX, y: inputY,
        w: inp._w, h: SUB_PH, isInput: true, type: inp.type, depth: lay.depth
      };
      inputY += SUB_PH + SUB_GAP_Y;
    });

    // Position result pills (stacked in result column)
    let resultY = PAD + LABEL_H + HEADER_GAP;
    lay.nodes.forEach(n => {
      pos[n.name] = { x: resultX, y: resultY, w: n._w, h: PH, depth: lay.depth };
      resultY += PH + GAP_Y;
    });
    lay._colH = Math.max(inputY, resultY);
    curX = resultX + resultColW + GAP_X;
  });

  // ── Taint computation (needed for stats) ──
  const taintSources = new Set();
  DATA.forEach(d => {
    const hasEv = d.evidence && d.evidence.length > 0;
    if (!hasEv) { taintSources.add(d.id); return; }
    const allOk = d.evidence.every(e => e.status === 'verified' || e.status === 'derived' || e.status === 'manual');
    if (!allOk) taintSources.add(d.id);
  });
  function computeTainted() {
    const tainted = new Set(taintSources);
    const q = [...taintSources];
    while (q.length) {
      const n = q.pop();
      (childrenOf[n] || []).forEach(c => {
        if (!tainted.has(c)) { tainted.add(c); q.push(c); }
      });
    }
    return tainted;
  }
  const _allTainted = computeTainted();

  // ── Draw layer labels + stats widget ──
  function pct(n, t) { return t ? Math.round(n / t * 100) : 0; }

  // Store per-layer stats metadata for recomputation on selection
  const layerStatsInfo = [];  // [{lay, cx, wx, labelY}]

  function computeLayerStats(lay, filterSet) {
    // Compute kind counts + taint numbers, optionally filtered to a path set
    const kindCounts = {};
    let taintedCount = 0, taintSourceCount = 0;

    const nodes = filterSet ? lay.nodes.filter(n => filterSet.has(n.name)) : lay.nodes;
    nodes.forEach(n => {
      if (!kindCounts[n.kind]) kindCounts[n.kind] = {main: 0, input: 0};
      kindCounts[n.kind].main++;
      if (taintSources.has(n.name)) taintSourceCount++;
      if (_allTainted.has(n.name)) taintedCount++;
    });

    const inpSeen = new Set();
    nodes.forEach(n => {
      (n.uses || []).forEach(u => { if (!filterSet || filterSet.has(u)) { if (!inpSeen.has(u)) inpSeen.add(u); } });
      (n.declares || []).forEach(d => { if (!filterSet || filterSet.has(d)) { if (!inpSeen.has(d)) inpSeen.add(d); } });
    });
    let inpTainted = 0, inpUnverified = 0;
    inpSeen.forEach(name => {
      if (_allTainted.has(name)) inpTainted++;
      if (taintSources.has(name)) inpUnverified++;
      const item = ITEM_BY_ID[name];
      const k = item ? item.kind : 'unknown';
      if (!kindCounts[k]) kindCounts[k] = {main: 0, input: 0};
      kindCounts[k].input++;
    });

    const total = nodes.length;
    const inputTotal = inpSeen.size;
    const allTotal = total + inputTotal;
    const allUnverified = taintSourceCount + inpUnverified;
    const allTaintedN = taintedCount + inpTainted;
    const allPropagated = allTaintedN - allUnverified;

    const kindEntries = Object.entries(kindCounts).sort((a,b) => (b[1].main + b[1].input) - (a[1].main + a[1].input));
    const maxCount = kindEntries.length ? Math.max(...kindEntries.map(([,v]) => v.main + v.input)) : 1;

    return {kindEntries, maxCount, allUnverified, allPropagated, allTotal, nodes};
  }

  function drawStats(parentG, lay, stats, wx, labelY) {
    const {kindEntries, maxCount, allUnverified, allPropagated, allTotal} = stats;

    const panelS = 66;
    const barChartW = panelS;
    const barH = Math.min(6, Math.max(3, (panelS - 4) / Math.max(kindEntries.length, 1) - 1));
    const panelH = Math.max(panelS, kindEntries.length * (barH + 1) + 4);
    const taintLineH = 12;
    const widgetH = panelH + taintLineH;

    const widgetBottom = labelY + 2;
    const widgetTop = widgetBottom - widgetH;

    // Remove old stats group if any
    parentG.selectAll('.stats-widget-' + lay.depth).remove();

    const sg = parentG.append("g")
      .attr("transform", `translate(${wx},${widgetTop})`)
      .attr("class", "layer-label stats-widget-" + lay.depth);

    // Background
    const labelW = kindEntries.length ? Math.max(...kindEntries.map(([k, v]) => (k + ' ' + (v.main + v.input)).length)) * 3.2 + 4 : 20;
    const totalW = barChartW + labelW + 4;
    sg.append("rect").attr("width", totalW).attr("height", widgetH).attr("rx", 4)
      .attr("fill", "#181825").attr("stroke", "#313244").attr("stroke-width", 0.5).attr("opacity", 0.85);

    let by = 3;
    const barsMaxW = barChartW - 6;
    kindEntries.forEach(([k, counts]) => {
      const totalK = counts.main + counts.input;
      const fullW = Math.max(2, (totalK / maxCount) * barsMaxW);
      const mainW = Math.max(1, (counts.main / maxCount) * barsMaxW);
      const color = kindDot(k);

      if (counts.input > 0) {
        sg.append("rect")
          .attr("x", 3).attr("y", by).attr("width", fullW).attr("height", barH).attr("rx", 1)
          .attr("fill", color).attr("opacity", 0.25);
      }
      if (counts.main > 0) {
        sg.append("rect")
          .attr("x", 3).attr("y", by).attr("width", mainW).attr("height", barH).attr("rx", 1)
          .attr("fill", color).attr("opacity", 0.85);
      }
      let kindTainted = 0;
      lay.nodes.forEach(n => { if (n.kind === k && _allTainted.has(n.name)) kindTainted++; });
      if (kindTainted > 0) {
        const tw = Math.max(1, (kindTainted / maxCount) * barsMaxW);
        sg.append("rect")
          .attr("x", 3).attr("y", by + barH - 1.5).attr("width", tw).attr("height", 1.5).attr("rx", 0.5)
          .attr("fill", "#f38ba8").attr("opacity", 0.7);
      }

      sg.append("text")
        .attr("x", barChartW).attr("y", by + barH - 0.5)
        .attr("fill", color).attr("font-size", "5px").attr("opacity", 0.8)
        .text(`${k} ${totalK}`);
      by += barH + 1;
    });

    const ty = panelH + 1;
    let tx = 4;
    if (allUnverified > 0) {
      sg.append("text").attr("x", tx).attr("y", ty + 7)
        .attr("fill", "#f38ba8").attr("font-size", "7px").attr("font-weight", "bold")
        .text(`${allUnverified}/${pct(allUnverified, allTotal)}%`);
      tx += (`${allUnverified}/${pct(allUnverified, allTotal)}%`).length * 4 + 2;
      sg.append("text").attr("x", tx).attr("y", ty + 7)
        .attr("fill", "#f38ba8").attr("font-size", "5px").attr("opacity", 0.7)
        .text(`unverified`);
      tx += 32;
    }
    if (allPropagated > 0) {
      sg.append("text").attr("x", tx).attr("y", ty + 7)
        .attr("fill", "#f9e2af").attr("font-size", "7px").attr("font-weight", "bold")
        .text(`${allPropagated}/${pct(allPropagated, allTotal)}%`);
      tx += (`${allPropagated}/${pct(allPropagated, allTotal)}%`).length * 4 + 2;
      sg.append("text").attr("x", tx).attr("y", ty + 7)
        .attr("fill", "#f9e2af").attr("font-size", "5px").attr("opacity", 0.7)
        .text(`tainted`);
    }
    if (allUnverified === 0 && allPropagated === 0) {
      sg.append("text").attr("x", tx).attr("y", ty + 7)
        .attr("fill", "#a6e3a1").attr("font-size", "5.5px").attr("opacity", 0.7)
        .text('\u2713 clean');
    }
  }

  function recomputeAllStats(filterSet) {
    layerStatsInfo.forEach(({lay, cx, wx, labelY}) => {
      const stats = computeLayerStats(lay, filterSet);
      drawStats(g, lay, stats, wx, labelY);
    });
  }

  LAYERS.layers.forEach(lay => {
    if (!lay.nodes.length) return;
    const cx = lay._labelX + lay._colW / 2;

    // Separator line
    g.append("line")
      .attr("x1", lay._labelX - 6).attr("y1", PAD)
      .attr("x2", lay._labelX - 6).attr("y2", lay._colH || PAD + 40)
      .attr("stroke", "#313244").attr("stroke-width", 1).attr("stroke-dasharray", "3,3")
      .attr("class", "layer-label");

    // "inputs" label
    if (lay._hasInputs) {
      g.append("text")
        .attr("x", lay._inputX + lay._inputColW / 2).attr("y", PAD + LABEL_H - 4)
        .attr("text-anchor", "middle")
        .attr("fill", "#a6e3a1").attr("font-size", "8px").attr("font-style", "italic")
        .attr("class", "layer-label")
        .text("inputs");
    }

    // L label aligned with inputs label
    const labelY = PAD + LABEL_H - 4;
    g.append("text")
      .attr("x", cx).attr("y", labelY)
      .attr("text-anchor", "middle")
      .attr("fill", "#6c7086").attr("font-size", "10px").attr("font-weight", "bold")
      .attr("class", "layer-label")
      .text(`L${lay.depth} (${lay.nodes.length})`);

    const wx = cx + 36;
    layerStatsInfo.push({lay, cx, wx, labelY});

    // Draw initial stats (unfiltered)
    const stats = computeLayerStats(lay, null);
    drawStats(g, lay, stats, wx, labelY);
  });

  // ── Helper: draw bezier between two positioned elements ──
  function bezier(sp, tp, fromRight, toLeft) {
    const x1 = fromRight ? sp.x + sp.w : sp.x;
    const y1 = sp.y + sp.h / 2;
    const x2 = toLeft ? tp.x : tp.x + tp.w;
    const y2 = tp.y + tp.h / 2;
    if (Math.abs(x2 - x1) < 2) {
      // Vertical: arc left
      const xBase = Math.min(sp.x, tp.x);
      const arcW = 16 + Math.abs(y2 - y1) * 0.05;
      return `M${xBase},${y1} C${xBase-arcW},${y1} ${xBase-arcW},${y2} ${xBase},${y2}`;
    }
    const dx = (x2 - x1) * 0.35;
    return `M${x1},${y1} C${x1+dx},${y1} ${x2-dx},${y2} ${x2},${y2}`;
  }

  // ── Draw edges routed through input pills ──
  const edgeEls = [];
  const drawnSourceToInp = new Set();  // avoid duplicate source→inp lines
  // Build layerIdx lookup for targets
  const nodeLayerIdx = {};
  LAYERS.layers.forEach((lay, li) => { lay.nodes.forEach(n => { nodeLayerIdx[n.name] = li; }); });

  LAYERS.edges.forEach(e => {
    const sp = pos[e.source];
    const tp = pos[e.target];
    const color = TYPE_COLOR[e.type] || '#a6adc8';

    if (e.type === 'use' || e.type === 'declare') {
      // Route through deduped input pill
      const li = nodeLayerIdx[e.target];
      if (li === undefined || !tp) return;
      const inpId = 'inp:' + e.source + '@' + li;
      const ip = pos[inpId];
      if (ip) {
        // Segment 1: source → input pill (only if source is in view)
        if (sp) {
          const seg1Key = e.source + '>' + inpId;
          if (!drawnSourceToInp.has(seg1Key)) {
            drawnSourceToInp.add(seg1Key);
            const d1 = bezier(sp, ip, true, true);
            const el1 = g.append("path")
              .attr("d", d1).attr("fill", "none").attr("stroke", color)
              .attr("stroke-opacity", 0.2).attr("stroke-width", 1.2)
              .attr("data-source", e.source).attr("data-target", e.target).attr("data-type", e.type)
              .attr("data-seg", "1").node();
            edgeEls.push(el1);
          }
        }
        // Segment 2: input pill → consumer result (always drawn)
        const d2 = bezier(ip, tp, true, true);
        const el2 = g.append("path")
          .attr("d", d2).attr("fill", "none").attr("stroke", color)
          .attr("stroke-opacity", 0.2).attr("stroke-width", 1.2)
          .attr("data-source", e.source).attr("data-target", e.target).attr("data-type", e.type)
          .attr("data-seg", "2").node();
        edgeEls.push(el2);
      } else if (sp && tp) {
        // Fallback direct
        const d = bezier(sp, tp, true, true);
        const el = g.append("path").attr("d", d).attr("fill", "none").attr("stroke", color)
          .attr("stroke-opacity", 0.2).attr("stroke-width", 1.2)
          .attr("data-source", e.source).attr("data-target", e.target).attr("data-type", e.type).node();
        edgeEls.push(el);
      }
    } else {
      if (!sp || !tp) return;
      // Direct connection: pull, axiom-ref
      const d = bezier(sp, tp, sp.depth !== tp.depth, sp.depth !== tp.depth);
      const el = g.append("path")
        .attr("d", d).attr("fill", "none").attr("stroke", color)
        .attr("stroke-opacity", e.type === 'axiom-ref' ? 0.35 : 0.2)
        .attr("stroke-width", 1.2)
        .attr("data-source", e.source).attr("data-target", e.target).attr("data-type", e.type)
        .node();
      edgeEls.push(el);
    }
  });

  // ── Draw input sub-pills ──
  Object.entries(inputPillData).forEach(([id, inp]) => {
    const p = pos[id];
    if (!p) return;
    const stroke = TYPE_STROKE[inp.type] || '#585b70';
    const isDeclare = inp.type === 'declare';

    const pg = g.append("g")
      .attr("transform", `translate(${p.x},${p.y})`)
      .attr("class", "cursor-pointer pill-node pill-input").attr("data-name", inp.label);

    pg.append("rect")
      .attr("width", p.w).attr("height", SUB_PH).attr("rx", 9)
      .attr("fill", isDeclare ? '#1e1e2e' : '#262637')
      .attr("stroke", stroke).attr("stroke-width", 1)
      .attr("stroke-dasharray", isDeclare ? '3,2' : 'none');

    const short = inp.label.includes('.') ? inp.label.split('.').slice(1).join('.') : inp.label;
    const maxCh = Math.floor((p.w - 16) / 5.2);
    pg.append("text")
      .attr("x", 8).attr("y", SUB_PH / 2 + 1).attr("dominant-baseline", "middle")
      .attr("fill", stroke).attr("font-size", "8.5px")
      .text((inp.type === 'use' ? ':use ' + short : ':' + short).slice(0, maxCh));

    pg.on("mouseover", (ev) => {
      tooltip.html(`<b>:${inp.label}</b>\ntype: ${inp.type}\nconsumer: ${inp.consumer}`)
        .classed("hidden", false)
        .style("left", (ev.pageX + 12) + "px").style("top", (ev.pageY - 8) + "px");
    }).on("mouseout", () => { tooltip.classed("hidden", true); });
    pg.on("click", (ev) => {
      ev.stopPropagation();
      focusNode(inp.label);
    });
  });

  // ── Draw result pills ──
  Object.entries(pos).forEach(([name, p]) => {
    if (p.isInput) return;
    const n = nodeData[name];
    if (!n) return;

    const pg = g.append("g")
      .attr("transform", `translate(${p.x},${p.y})`)
      .attr("class", "cursor-pointer pill-node pill-result").attr("data-name", name);

    pg.append("rect")
      .attr("width", p.w).attr("height", PH).attr("rx", 14)
      .attr("fill", "#313244").attr("stroke", kindDot(n.kind)).attr("stroke-width", 1.5);
    pg.append("circle")
      .attr("cx", 12).attr("cy", PH / 2).attr("r", 4).attr("fill", kindDot(n.kind));

    const short = name.includes('.') ? name.split('.').slice(1).join('.') : name;
    const valS = n.value ? ` =${String(n.value).slice(0,15)}` : '';
    const maxCh = Math.floor((p.w - 28) / 6);
    pg.append("text")
      .attr("x", 22).attr("y", PH / 2 + 1).attr("dominant-baseline", "middle")
      .attr("fill", "#cdd6f4").attr("font-size", "10px")
      .text((short + valS).slice(0, maxCh));

    pg.on("mouseover", (ev) => {
      let html = `<b>${name}</b>\nkind: ${n.kind}`;
      if (n.value) html += `\nvalue: ${String(n.value).slice(0,100)}`;
      if (n.uses && n.uses.length) html += `\nuses: ${n.uses.join(', ')}`;
      if (n.declares && n.declares.length) html += `\ndeclares: ${n.declares.join(', ')}`;
      if (n.pulls && n.pulls.length) html += `\npulls: ${n.pulls.join(', ')}`;
      const downs = childrenOf[name] || [];
      if (downs.length) html += `\ndownstream: ${downs.join(', ')}`;
      tooltip.html(html).classed("hidden", false)
        .style("left", (ev.pageX + 12) + "px").style("top", (ev.pageY - 8) + "px");
    }).on("mouseout", () => { tooltip.classed("hidden", true); });
    pg.on("click", (ev) => {
      ev.stopPropagation();
      focusNode(name);
    });
  });

  // ── Hanging section: disconnected L0 nodes ──
  if (hangingNodes.length > 0) {
    // Find max Y from all positioned elements to place hanging below
    let maxY = 0;
    Object.values(pos).forEach(p => { maxY = Math.max(maxY, p.y + p.h); });
    const hangY = maxY + 40;

    g.append("text")
      .attr("x", PAD).attr("y", hangY)
      .attr("fill", "#585b70").attr("font-size", "11px").attr("font-weight", "bold")
      .attr("class", "layer-label")
      .text(`Hanging (${hangingNodes.length})`);
    g.append("line")
      .attr("x1", PAD).attr("y1", hangY + 4)
      .attr("x2", PAD + 200).attr("y2", hangY + 4)
      .attr("stroke", "#585b70").attr("stroke-width", 0.5)
      .attr("class", "layer-label");

    const hangSet = new Set(hangingNodes.map(n => n.name));
    const HANG_W = 180;

    // Collect internal edges among hanging nodes
    const hangEdges = [];
    const hangFwd = {};
    const hangInDeg = {};
    hangingNodes.forEach(n => { hangInDeg[n.name] = 0; });
    LAYERS.edges.forEach(e => {
      if (hangSet.has(e.source) && hangSet.has(e.target)) {
        hangEdges.push(e);
        if (!hangFwd[e.source]) hangFwd[e.source] = [];
        hangFwd[e.source].push(e.target);
        hangInDeg[e.target] = (hangInDeg[e.target] || 0) + 1;
      }
    });

    // Topological layers for DAG layout
    const hangLayers = [];
    const hangAssigned = new Set();
    // Start with roots (in-degree 0)
    let frontier = hangingNodes.filter(n => (hangInDeg[n.name] || 0) === 0).map(n => n.name);
    while (frontier.length) {
      hangLayers.push(frontier);
      frontier.forEach(n => hangAssigned.add(n));
      const next = new Set();
      frontier.forEach(n => {
        (hangFwd[n] || []).forEach(t => {
          if (!hangAssigned.has(t)) next.add(t);
        });
      });
      // Only include nodes whose ALL parents are assigned
      frontier = [...next].filter(n => {
        const parents = LAYERS.edges.filter(e => e.target === n && hangSet.has(e.source)).map(e => e.source);
        return parents.every(p => hangAssigned.has(p));
      });
      if (frontier.length === 0 && hangAssigned.size < hangingNodes.length) {
        // Remaining unassigned (cycles) — dump them
        const remaining = hangingNodes.filter(n => !hangAssigned.has(n.name)).map(n => n.name);
        hangLayers.push(remaining);
        remaining.forEach(n => hangAssigned.add(n));
      }
    }

    // Layout hanging nodes in LTR columns per topo layer
    const hangNodeMap = {};
    hangingNodes.forEach(n => { hangNodeMap[n.name] = n; });

    let hx = PAD;
    hangLayers.forEach(layer => {
      let hy = hangY + 14;
      // Measure col width
      let colW = HANG_W;
      layer.forEach(name => {
        const short = name.includes('.') ? name.split('.').slice(1).join('.') : name;
        colW = Math.max(colW, Math.min(220, short.length * 6.5 + 28));
      });

      layer.forEach(name => {
        const n = hangNodeMap[name];
        if (!n) return;
        nodeData[n.name] = n;
        pos[n.name] = { x: hx, y: hy, w: colW, h: PH, depth: 0, hanging: true };

        const pg = g.append("g")
          .attr("transform", `translate(${hx},${hy})`)
          .attr("class", "cursor-pointer pill-node pill-result").attr("data-name", n.name);
        pg.append("rect")
          .attr("width", colW).attr("height", PH).attr("rx", 14)
          .attr("fill", "#1e1e2e").attr("stroke", "#585b70").attr("stroke-width", 1)
          .attr("stroke-dasharray", "4,2");
        pg.append("circle")
          .attr("cx", 12).attr("cy", PH / 2).attr("r", 4).attr("fill", kindDot(n.kind));
        const short = n.name.includes('.') ? n.name.split('.').slice(1).join('.') : n.name;
        pg.append("text")
          .attr("x", 22).attr("y", PH / 2 + 1).attr("dominant-baseline", "middle")
          .attr("fill", "#585b70").attr("font-size", "10px")
          .text(short.slice(0, Math.floor((colW - 28) / 6)));
        pg.on("mouseover", (ev) => {
          tooltip.html(`<b>${n.name}</b>\nkind: ${n.kind}\n(hanging)`)
            .classed("hidden", false)
            .style("left", (ev.pageX + 12) + "px").style("top", (ev.pageY - 8) + "px");
        }).on("mouseout", () => { tooltip.classed("hidden", true); });
        pg.on("click", (ev) => {
          ev.stopPropagation();
          const d = ITEM_BY_ID[n.name];
          if (d) showDetail(d);
        });
        hy += PH + GAP_Y;
      });
      hx += colW + 30;
    });

    // Draw internal edges among hanging nodes
    hangEdges.forEach(e => {
      const sp = pos[e.source];
      const tp = pos[e.target];
      if (!sp || !tp) return;
      const color = TYPE_COLOR[e.type] || '#585b70';
      const sameCol = sp.x === tp.x;
      const d = sameCol
        ? bezier(sp, tp, false, false)
        : bezier(sp, tp, true, true);
      g.append("path")
        .attr("d", d).attr("fill", "none").attr("stroke", color)
        .attr("stroke-opacity", 0.3).attr("stroke-width", 1)
        .attr("stroke-dasharray", "4,2");
    });
  }

  // ── Focus mode toggle ──
  const btnFocus = document.getElementById('btn-focus-mode');
  const btnUnfocus = document.getElementById('btn-unfocus');

  function syncFocusBtnStyle() {
    btnFocus.textContent = focusMode ? 'Focus ON' : 'Focus mode';
    btnFocus.className = focusMode
      ? 'px-3 py-1 rounded-lg text-xs bg-mauve text-crust font-bold border border-mauve'
      : 'px-3 py-1 rounded-lg text-xs bg-surface0 text-subtext border border-surface2 hover:bg-surface1';
  }
  btnFocus.onclick = () => {
    focusMode = !focusMode;
    syncFocusBtnStyle();
    if (focusMode && focusedId) focusNode(focusedId);
    else if (!focusMode) unfocusAll();
  };
  btnUnfocus.onclick = () => unfocusAll();
  svg.on("click", () => { if (!focusMode) unfocusAll(); });

  // ── Taint propagation (visual) ──
  let taintsOn = false;
  const btnTaints = document.getElementById('btn-taints');

  function applyTaints() {
    const tainted = computeTainted();
    g.selectAll(".pill-result").each(function() {
      const el = d3.select(this);
      const name = el.attr("data-name");
      if (tainted.has(name)) {
        const isSource = taintSources.has(name);
        el.select("rect")
          .attr("stroke", isSource ? "#f38ba8" : "#f9e2af")
          .attr("stroke-width", isSource ? 2.5 : 2)
          .attr("stroke-dasharray", isSource ? "none" : "6,2");
      }
    });
    g.selectAll(".pill-input").each(function() {
      const el = d3.select(this);
      const name = el.attr("data-name");
      if (tainted.has(name)) {
        el.select("rect").attr("stroke", "#f9e2af").attr("stroke-width", 1.5);
      }
    });
    edgeEls.forEach(el => {
      const s = el.getAttribute("data-source");
      const t = el.getAttribute("data-target");
      if (tainted.has(s) && tainted.has(t)) {
        el.setAttribute("stroke", "#f9e2af");
        el.setAttribute("stroke-opacity", "0.5");
        el.setAttribute("stroke-width", "1.8");
      }
    });
    // Show count
    info.innerHTML = `<div class="font-bold text-red mb-1">Taint analysis</div>`
      + `<div><span class="text-overlay0">sources:</span> <span class="text-red">${taintSources.size}</span> unverified</div>`
      + `<div><span class="text-overlay0">tainted:</span> <span class="text-yellow">${tainted.size}</span> total</div>`
      + `<div class="mt-1 text-[10px] text-overlay0">Red = unverified source, Yellow = tainted downstream</div>`;
    info.classList.remove("hidden");
  }

  function clearTaints() {
    g.selectAll(".pill-result").each(function() {
      const el = d3.select(this);
      const name = el.attr("data-name");
      const n = nodeData[name];
      const p = pos[name];
      if (n && p && !p.hanging) {
        el.select("rect").attr("stroke", kindDot(n.kind)).attr("stroke-width", 1.5).attr("stroke-dasharray", "none");
      } else if (p && p.hanging) {
        el.select("rect").attr("stroke", "#585b70").attr("stroke-width", 1).attr("stroke-dasharray", "4,2");
      }
    });
    g.selectAll(".pill-input").each(function() {
      const el = d3.select(this);
      el.select("rect").attr("stroke", "#a6e3a1").attr("stroke-width", 1);
    });
    edgeEls.forEach(el => {
      const t = el.getAttribute("data-type");
      el.setAttribute("stroke", TYPE_COLOR[t] || '#a6adc8');
      el.setAttribute("stroke-opacity", t === 'axiom-ref' ? "0.35" : "0.2");
      el.setAttribute("stroke-width", "1.2");
    });
    info.classList.add("hidden");
  }

  function applyFocusTaints() {
    if (!focusG) return;
    const tainted = computeTainted();
    focusG.selectAll(".fpill-result").each(function() {
      const el = d3.select(this);
      const name = el.attr("data-name");
      if (tainted.has(name)) {
        const isSource = taintSources.has(name);
        el.select("rect")
          .attr("stroke", isSource ? "#f38ba8" : "#f9e2af")
          .attr("stroke-width", isSource ? 2.5 : 2)
          .attr("stroke-dasharray", isSource ? "none" : "6,2");
      }
    });
    focusG.selectAll(".fpill-input").each(function() {
      const el = d3.select(this);
      const name = el.attr("data-name");
      if (tainted.has(name)) {
        el.select("rect").attr("stroke", "#f9e2af").attr("stroke-width", 1.5);
      }
    });
  }

  function clearFocusTaints() {
    if (!focusG) return;
    focusG.selectAll(".fpill-result").each(function() {
      const el = d3.select(this);
      const name = el.attr("data-name");
      const n = nodeData[name];
      el.select("rect").attr("stroke", kindDot(n ? n.kind : '')).attr("stroke-width", 1.5).attr("stroke-dasharray", "none");
    });
    focusG.selectAll(".fpill-input").each(function() {
      const el = d3.select(this);
      el.select("rect").attr("stroke", TYPE_STROKE[el.attr("data-type")] || '#585b70').attr("stroke-width", 1);
    });
  }

  btnTaints.onclick = () => {
    taintsOn = !taintsOn;
    btnTaints.textContent = taintsOn ? 'Taints ON' : 'Taints';
    btnTaints.className = taintsOn
      ? 'px-3 py-1 rounded-lg text-xs bg-red text-crust font-bold border border-red'
      : 'px-3 py-1 rounded-lg text-xs bg-surface0 text-subtext border border-surface2 hover:bg-surface1';
    if (taintsOn) { applyTaints(); applyFocusTaints(); }
    else { clearTaints(); clearFocusTaints(); }
  };

  function focusNode(id) {
    focusedId = id;
    const path = collectPath(id);
    btnUnfocus.classList.remove("hidden");

    if (focusMode) {
      rebuildFocused(path, id);
      return;
    }

    // ── Dim mode: dim non-path, highlight path ──
    g.selectAll(".pill-node").each(function() {
      const el = d3.select(this);
      const name = el.attr("data-name");
      if (path.has(name)) {
        el.attr("opacity", 1);
        if (name === id) el.select("rect").attr("stroke", "#cba6f7").attr("stroke-width", 3);
        else el.select("rect").attr("stroke-width", el.classed("pill-input") ? 1 : 1.5);
      } else {
        el.attr("opacity", 0.08);
      }
    });

    edgeEls.forEach(el => {
      const s = el.getAttribute("data-source");
      const t = el.getAttribute("data-target");
      if (path.has(s) && path.has(t)) {
        el.setAttribute("stroke-opacity", "0.8");
        el.setAttribute("stroke-width", "2");
      } else {
        el.setAttribute("stroke-opacity", "0.03");
        el.setAttribute("stroke-width", "1");
      }
    });

    g.selectAll(".layer-label").each(function() {
      const el = d3.select(this);
      // Keep stats widgets visible, dim everything else
      const cls = el.attr("class") || '';
      if (cls.includes('stats-widget-')) {
        el.attr("opacity", 1);
      } else {
        el.attr("opacity", 0.15);
      }
    });
    // Recompute stats filtered to selection path
    recomputeAllStats(path);

    const d = ITEM_BY_ID[id];
    if (d) {
      info.innerHTML = _infoHtml(d, path);
      info.classList.remove("hidden");
      showDetail(d);
    }
  }

  // ── Rebuild SVG with only focused path nodes (rails-but-pills layout) ──
  let focusG = null;
  function rebuildFocused(path, focusId) {
    g.selectAll("*").style("display", "none");
    if (focusG) focusG.remove();
    focusG = svg.append("g");
    svg.call(zoomBehavior);
    zoomBehavior.on("zoom", (e) => focusG.attr("transform", e.transform));

    // Filter layers to path nodes
    const fLayers = [];
    LAYERS.layers.forEach(lay => {
      const fnodes = lay.nodes.filter(n => path.has(n.name));
      if (fnodes.length) fLayers.push({ depth: lay.depth, nodes: fnodes });
    });

    const fPos = {};
    const fInputPills = {};
    const fNodeLayerIdx = {};
    let fX = PAD;

    fLayers.forEach((lay, li) => {
      lay.nodes.forEach(n => { fNodeLayerIdx[n.name] = li; });

      // Deduped input pills for this layer (uses + declares)
      const useSeen = {};
      const layerInputs = [];
      lay.nodes.forEach(n => {
        (n.uses || []).forEach(u => {
          if (path.has(u) || path.has(n.name)) {
            if (!useSeen[u]) {
              useSeen[u] = {id: 'inp:'+u+'@'+li, label: u, consumers: [], type: 'use'};
              layerInputs.push(useSeen[u]);
            }
            useSeen[u].consumers.push(n.name);
          }
        });
        (n.declares || []).forEach(d => {
          if (path.has(d) || path.has(n.name)) {
            if (!useSeen[d]) {
              useSeen[d] = {id: 'inp:'+d+'@'+li, label: d, consumers: [], type: 'declare'};
              layerInputs.push(useSeen[d]);
            }
            useSeen[d].consumers.push(n.name);
          }
        });
      });
      layerInputs.forEach(p => { fInputPills[p.id] = p; });
      const hasInputs = layerInputs.length > 0;

      // Measure widths
      let inputColW = 0;
      if (hasInputs) layerInputs.forEach(inp => {
        const short = inp.label.includes('.') ? inp.label.split('.').slice(1).join('.') : inp.label;
        inp._w = Math.min(SPW_MAX, Math.max(SPW_MIN, short.length * 5.5 + 20));
        inputColW = Math.max(inputColW, inp._w);
      });
      let resultColW = 0;
      lay.nodes.forEach(n => {
        const short = n.name.includes('.') ? n.name.split('.').slice(1).join('.') : n.name;
        n._fw = Math.min(PW_MAX, Math.max(PW_MIN, (short + (n.value ? ' =' + String(n.value).slice(0,15) : '')).length * 6.5 + 28));
        resultColW = Math.max(resultColW, n._fw);
      });

      const inputXf = fX;
      const resultXf = hasInputs ? fX + inputColW + GAP_XI : fX;

      focusG.append("text")
        .attr("x", fX + (resultXf + resultColW - fX) / 2).attr("y", PAD + 12)
        .attr("text-anchor", "middle")
        .attr("fill", "#6c7086").attr("font-size", "10px").attr("font-weight", "bold")
        .text(`L${lay.depth}`);

      // Stack input pills
      let inputY = PAD + LABEL_H + HEADER_GAP;
      layerInputs.forEach(inp => {
        fPos[inp.id] = { x: inputXf, y: inputY, w: inp._w, h: SUB_PH, isInput: true, type: inp.type };
        inputY += SUB_PH + SUB_GAP_Y;
      });
      // Stack result pills
      let resultY = PAD + LABEL_H + HEADER_GAP;
      lay.nodes.forEach(n => {
        fPos[n.name] = { x: resultXf, y: resultY, w: n._fw, h: PH };
        resultY += PH + GAP_Y;
      });
      fX = resultXf + resultColW + GAP_X;
    });

    // Draw focused edges
    const fDrawnSrcInp = new Set();
    LAYERS.edges.forEach(e => {
      const sp = fPos[e.source];
      const tp = fPos[e.target];
      const color = TYPE_COLOR[e.type] || '#a6adc8';

      if (e.type === 'use' || e.type === 'declare') {
        const li = fNodeLayerIdx[e.target];
        if (li === undefined || !tp) return;
        const inpId = 'inp:' + e.source + '@' + li;
        const ip = fPos[inpId];
        if (ip) {
          if (sp) {
            const seg1Key = e.source + '>' + inpId;
            if (!fDrawnSrcInp.has(seg1Key)) {
              fDrawnSrcInp.add(seg1Key);
              focusG.append("path").attr("d", bezier(sp, ip, true, true))
                .attr("fill", "none").attr("stroke", color).attr("stroke-opacity", 0.6).attr("stroke-width", 1.8);
            }
          }
          focusG.append("path").attr("d", bezier(ip, tp, true, true))
            .attr("fill", "none").attr("stroke", color).attr("stroke-opacity", 0.6).attr("stroke-width", 1.8);
        } else if (sp && tp) {
          focusG.append("path").attr("d", bezier(sp, tp, true, true))
            .attr("fill", "none").attr("stroke", color).attr("stroke-opacity", 0.6).attr("stroke-width", 1.8);
        }
      } else {
        if (!sp || !tp) return;
        focusG.append("path").attr("d", bezier(sp, tp, true, true))
          .attr("fill", "none").attr("stroke", color)
          .attr("stroke-opacity", e.type === 'axiom-ref' ? 0.5 : 0.6).attr("stroke-width", 1.8);
      }
    });

    // Draw focused input pills
    Object.entries(fInputPills).forEach(([id, inp]) => {
      const p = fPos[id];
      if (!p) return;
      const stroke = TYPE_STROKE[inp.type] || '#585b70';
      const pg = focusG.append("g").attr("transform", `translate(${p.x},${p.y})`).attr("class", "cursor-pointer fpill-input").attr("data-name", inp.label);
      pg.append("rect").attr("width", p.w).attr("height", SUB_PH).attr("rx", 9)
        .attr("fill", '#262637').attr("stroke", stroke).attr("stroke-width", 1);
      const short = inp.label.includes('.') ? inp.label.split('.').slice(1).join('.') : inp.label;
      pg.append("text").attr("x", 8).attr("y", SUB_PH / 2 + 1).attr("dominant-baseline", "middle")
        .attr("fill", stroke).attr("font-size", "8.5px")
        .text((inp.type === 'use' ? ':use ' + short : ':' + short).slice(0, Math.floor((p.w - 16) / 5.2)));
      pg.on("click", (ev) => {
        ev.stopPropagation();
        const np = collectPath(inp.label);
        rebuildFocused(np, inp.label);
        const d = ITEM_BY_ID[inp.label];
        if (d) { info.innerHTML = _infoHtml(d, np); info.classList.remove("hidden"); showDetail(d); }
      });
    });

    // Draw focused result pills
    fLayers.forEach(lay => lay.nodes.forEach(n => {
      const p = fPos[n.name];
      if (!p || p.isInput) return;
      const isFocused = n.name === focusId;
      const pg = focusG.append("g").attr("transform", `translate(${p.x},${p.y})`).attr("class", "cursor-pointer fpill-result").attr("data-name", n.name);
      pg.append("rect").attr("width", p.w).attr("height", PH).attr("rx", 14)
        .attr("fill", isFocused ? "#45475a" : "#313244")
        .attr("stroke", isFocused ? "#cba6f7" : kindDot(n.kind))
        .attr("stroke-width", isFocused ? 3 : 1.5);
      pg.append("circle").attr("cx", 12).attr("cy", PH / 2).attr("r", 4).attr("fill", kindDot(n.kind));
      const short = n.name.includes('.') ? n.name.split('.').slice(1).join('.') : n.name;
      const maxCh = Math.floor((p.w - 28) / 6);
      pg.append("text").attr("x", 22).attr("y", PH / 2 + 1).attr("dominant-baseline", "middle")
        .attr("fill", "#cdd6f4").attr("font-size", "10px")
        .text((short + (n.value ? ' =' + String(n.value).slice(0,15) : '')).slice(0, maxCh));
      pg.on("click", (ev) => {
        ev.stopPropagation();
        const np = collectPath(n.name);
        rebuildFocused(np, n.name);
        const d = ITEM_BY_ID[n.name];
        if (d) { info.innerHTML = _infoHtml(d, np); info.classList.remove("hidden"); showDetail(d); }
      });
      pg.on("mouseover", (ev) => {
        tooltip.html(`<b>${n.name}</b>\n${n.kind}${n.value ? '\n' + String(n.value).slice(0,80) : ''}`)
          .classed("hidden", false)
          .style("left", (ev.pageX + 12) + "px").style("top", (ev.pageY - 8) + "px");
      }).on("mouseout", () => tooltip.classed("hidden", true));
    }));

    // Apply taints if active
    if (taintsOn) applyFocusTaints();

    // Info + zoom to fit
    const d = ITEM_BY_ID[focusId];
    if (d) { info.innerHTML = _infoHtml(d, path); info.classList.remove("hidden"); showDetail(d); }
    requestAnimationFrame(() => {
      const bounds = focusG.node().getBBox();
      if (bounds.width > 0) {
        const scale = Math.min(W / (bounds.width + 80), H / (bounds.height + 80), 2);
        const cx = bounds.x + bounds.width / 2, cy = bounds.y + bounds.height / 2;
        svg.transition().duration(300).call(
          zoomBehavior.transform,
          d3.zoomIdentity.translate(W/2 - cx*scale, H/2 - cy*scale).scale(scale)
        );
      }
    });
  }

  function unfocusAll() {
    focusedId = null;
    focusMode = false;
    syncFocusBtnStyle();
    btnUnfocus.classList.add("hidden");
    if (focusG) { focusG.remove(); focusG = null; }
    g.selectAll("*").style("display", null);
    zoomBehavior.on("zoom", (e) => g.attr("transform", e.transform));

    g.selectAll(".pill-result").attr("opacity", 1).each(function() {
      const el = d3.select(this);
      const name = el.attr("data-name");
      const n = nodeData[name];
      el.select("rect").attr("stroke-width", 1.5).attr("stroke", kindDot(n ? n.kind : ''));
    });
    g.selectAll(".pill-input").attr("opacity", 1);
    edgeEls.forEach(el => {
      el.setAttribute("stroke-opacity", "0.2");
      el.setAttribute("stroke-width", "1.2");
    });
    g.selectAll(".layer-label").attr("opacity", 1);
    // Restore full stats (unfiltered)
    recomputeAllStats(null);
    info.classList.add("hidden");

    // Restore taints if active
    if (taintsOn) applyTaints();

    requestAnimationFrame(() => {
      const bounds = g.node().getBBox();
      if (bounds.width > 0) {
        const scale = Math.min(W / (bounds.width + 80), H / (bounds.height + 80), 1);
        const tx = 40 - bounds.x * scale, ty = 20 - bounds.y * scale;
        svg.transition().duration(300).call(
          zoomBehavior.transform, d3.zoomIdentity.translate(tx, ty).scale(scale)
        );
      }
    });
  }

  function _infoHtml(d, path) {
    let html = `<div class="font-bold text-lavender mb-1">${esc(d.id)}</div>`;
    html += `<div><span class="text-overlay0">kind:</span> <span style="color:${kindDot(d.kind)}">${esc(d.kind)}</span></div>`;
    html += `<div><span class="text-overlay0">layer:</span> ${d.depth}</div>`;
    html += `<div><span class="text-overlay0">path:</span> ${path.size} nodes</div>`;
    const downs = childrenOf[d.id] || [];
    if (downs.length) html += `<div><span class="text-overlay0">downstream:</span> ${downs.length}</div>`;
    if (d.value) html += `<div class="mt-1 text-subtext truncate" style="max-width:250px">${esc(String(d.value).slice(0,80))}</div>`;
    return html;
  }

  // Initial zoom to fit
  requestAnimationFrame(() => {
    const bounds = g.node().getBBox();
    if (bounds.width > 0 && bounds.height > 0) {
      const scale = Math.min(W / (bounds.width + 80), H / (bounds.height + 80), 1);
      const tx = 40 - bounds.x * scale;
      const ty = 20 - bounds.y * scale;
      svg.call(zoomBehavior.transform, d3.zoomIdentity.translate(tx, ty).scale(scale));
    }
  });
}
