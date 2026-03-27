// ── D3 Graph — depth-organized force layout ──
let graphInitialized = false;

function renderGraph() {
  if (graphInitialized) return;
  graphInitialized = true;

  const items = filtered(STRUCTURE_DATA);
  const nodes = [];
  const links = [];
  const seen = new Set();
  const itemById = {};

  // Build nodes from DATA items
  items.forEach(d => {
    const id = d.id || `${d.doc}:${d.line}`;
    if (seen.has(id)) return;
    seen.add(id);
    itemById[id] = d;
    const depth = d.depth != null ? d.depth : 0;
    nodes.push({ id, kind: d.kind || d.category || '', value: d.value || d.ctx || '', depth, color: kindDot(d.kind || d.category || '') });
  });

  // Build links from LAYERS.edges — the authoritative structural connections
  // (use, declare, pull, axiom-ref)
  const edgeTypes = {};
  const seenEdge = new Set();
  LAYERS.edges.forEach(e => {
    edgeTypes[e.source + '>' + e.target] = e.type;
    const key = e.source + '>' + e.target;
    if (seenEdge.has(key)) return;
    seenEdge.add(key);
    // Ensure both endpoints exist as nodes
    [e.source, e.target].forEach(name => {
      if (!seen.has(name)) {
        seen.add(name);
        const item = ITEM_BY_ID[name];
        const depth = item ? (item.depth != null ? item.depth : 0) : 0;
        const kind = item ? (item.kind || item.category || '') : 'input';
        nodes.push({ id: name, kind, value: '', depth, color: kindDot(kind) });
      }
    });
    links.push({ source: e.source, target: e.target });
  });

  // Also add input edges from ALL DATA items not covered by LAYERS.edges
  DATA.forEach(d => {
    const id = d.id || `${d.doc}:${d.line}`;
    if (!seen.has(id)) return;
    if (d.inputs) d.inputs.forEach(inp => {
      const inpName = typeof inp === 'string' ? inp : inp.name;
      const key = inpName + '>' + id;
      if (seenEdge.has(key)) return;
      seenEdge.add(key);
      if (!seen.has(inpName)) {
        seen.add(inpName);
        const inpItem = ITEM_BY_ID[inpName];
        const inpDepth = inpItem ? (inpItem.depth != null ? inpItem.depth : 0) : 0;
        nodes.push({ id: inpName, kind: inpItem ? inpItem.kind : 'input', value: '', depth: inpDepth, color: kindDot(inpItem ? inpItem.kind : 'input') });
      }
      links.push({ source: inpName, target: id });
    });
  });

  const TYPE_COLOR = {'use':C.green,'declare':C.overlay0,'pull':C.blue,'axiom-ref':C.peach,'diff':C.patronus};

  // ── Identify dangling nodes (no edges) ──
  const connectedSet = new Set();
  links.forEach(l => {
    const sid = typeof l.source === 'string' ? l.source : l.source.id;
    const tid = typeof l.target === 'string' ? l.target : l.target.id;
    connectedSet.add(sid);
    connectedSet.add(tid);
  });
  const danglingSet = new Set();
  nodes.forEach(n => { if (!connectedSet.has(n.id)) { n.dangling = true; danglingSet.add(n.id); } });

  // ── Graph metrics: connected components + interconnectivity ──
  // Build undirected adjacency for component detection (non-dangling only)
  const adj = {};
  links.forEach(l => {
    const sid = typeof l.source === 'string' ? l.source : l.source.id;
    const tid = typeof l.target === 'string' ? l.target : l.target.id;
    if (!adj[sid]) adj[sid] = [];
    if (!adj[tid]) adj[tid] = [];
    adj[sid].push(tid);
    adj[tid].push(sid);
  });

  const componentOf = {};  // node id → component index
  const components = [];   // array of Sets
  const visited = new Set();
  nodes.filter(n => !n.dangling).forEach(n => {
    if (visited.has(n.id)) return;
    const comp = new Set();
    const q = [n.id];
    while (q.length) {
      const cur = q.pop();
      if (visited.has(cur)) continue;
      visited.add(cur);
      comp.add(cur);
      (adj[cur] || []).forEach(nb => { if (!visited.has(nb)) q.push(nb); });
    }
    const idx = components.length;
    components.push(comp);
    comp.forEach(id => { componentOf[id] = idx; });
  });

  // Find largest component
  let mainCompIdx = 0;
  components.forEach((c, i) => { if (c.size > components[mainCompIdx].size) mainCompIdx = i; });
  const mainComp = components[mainCompIdx] || new Set();

  // Leaves = nodes with no outgoing edges (no children in directed graph)
  const hasChild = new Set();
  links.forEach(l => {
    const sid = typeof l.source === 'string' ? l.source : l.source.id;
    hasChild.add(sid);
  });
  const leaves = nodes.filter(n => !n.dangling && !hasChild.has(n.id));
  const mainLeaves = leaves.filter(n => mainComp.has(n.id));
  const interconnectivity = leaves.length > 0 ? mainLeaves.length / leaves.length : 1;

  // ── Taint data (pre-computed by Python, single source of truth) ──
  const _gtd = (typeof TAINT_DATA !== 'undefined') ? TAINT_DATA : {sources:[], tainted:[], reasons:{}};
  const taintSources = new Set(_gtd.sources);
  const _gAllTainted = new Set(_gtd.tainted);
  const taintPropagated = new Set([..._gAllTainted].filter(n => !taintSources.has(n)));
  const taintReasons = _gtd.reasons || {};

  // ── Depth bands ──
  const maxDepth = Math.max(0, ...nodes.filter(n => !n.dangling).map(n => n.depth));
  const svg = d3.select("#graph");
  const width = window.innerWidth;
  const height = window.innerHeight - 60;
  const gRoot = svg.append("g");
  const zoomBehavior = d3.zoom().scaleExtent([0.05, 8]).on("zoom", (e) => gRoot.attr("transform", e.transform));
  svg.call(zoomBehavior);
  svg.on("click.zoom", null);

  const BAND_W = Math.max(300, (width - 160) / Math.max(maxDepth + 1, 1));
  const PAD_LEFT = 80;
  const DANGLE_X = PAD_LEFT + (maxDepth + 2) * BAND_W;

  // ── Dangling kind bands (group by type on Y axis) ──
  const danglingKinds = [...new Set(nodes.filter(n => n.dangling).map(n => n.kind))].sort();
  const DANGLE_BAND_H = danglingKinds.length > 1 ? height / (danglingKinds.length + 1) : height;
  const danglingKindY = {};
  danglingKinds.forEach((k, i) => { danglingKindY[k] = (i + 1) * DANGLE_BAND_H; });

  // ── Force simulation ──
  const DIFF_Y = height + 120;  // push diff nodes below main structure
  const sim = d3.forceSimulation(nodes)
    .force("link", d3.forceLink(links).id(d => d.id).distance(80).strength(0.3))
    .force("charge", d3.forceManyBody().strength(-200))
    .force("collide", d3.forceCollide().radius(28))
    .force("depthX", d3.forceX(d => {
      if (d.dangling) return DANGLE_X;
      if (d.kind === 'diff') return PAD_LEFT + maxDepth * BAND_W;  // right side
      return PAD_LEFT + d.depth * BAND_W;
    }).strength(d => d.dangling ? 0.8 : d.kind === 'diff' ? 0.9 : 0.85))
    .force("centerY", d3.forceY(d => {
      if (d.dangling) return danglingKindY[d.kind] || height / 2;
      if (d.kind === 'diff') return DIFF_Y;
      return height / 2;
    }).strength(d => d.dangling ? 0.3 : d.kind === 'diff' ? 0.7 : 0.05));

  // ── Draw edges ──
  const linkG = gRoot.append("g");
  const link = linkG.selectAll("line")
    .data(links).join("line")
    .attr("stroke", l => {
      const sid = typeof l.source === 'string' ? l.source : l.source.id;
      const tid = typeof l.target === 'string' ? l.target : l.target.id;
      const t = edgeTypes[sid + '>' + tid] || edgeTypes[tid + '>' + sid];
      return TYPE_COLOR[t] || C.surface2;
    })
    .attr("stroke-opacity", 0.35)
    .attr("stroke-width", 1);

  // ── Draw nodes ──
  const NODE_R = 6;
  const DANGLE_R = 4;
  const nodeG = gRoot.append("g");
  const node = nodeG.selectAll("g")
    .data(nodes).join("g").attr("class", "cursor-pointer");

  // Node circles — smaller for dangling
  node.append("circle")
    .attr("r", d => d.dangling ? DANGLE_R : NODE_R)
    .attr("fill", d => d.color)
    .attr("stroke", d => d.dangling ? C.base : C.surface0)
    .attr("stroke-width", d => d.dangling ? 0.5 : 1.5)
    .attr("opacity", d => d.dangling ? 0.5 : 1);

  // Labels — all nodes, dimmer for dangling
  node.append("text")
    .attr("dx", d => (d.dangling ? DANGLE_R : NODE_R) + 4).attr("dy", 3)
    .attr("fill", d => d.dangling ? C.surface2 : C.text)
    .attr("font-size", d => d.dangling ? '7px' : '8px')
    .text(d => {
      const short = d.id.includes('.') ? d.id.split('.').slice(1).join('.') : d.id;
      return short.length > 25 ? short.slice(0, 22) + '...' : short;
    });

  // Drag
  node.call(d3.drag()
    .on("start", (e, d) => { if (!e.active) sim.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; })
    .on("drag", (e, d) => { d.fx = e.x; d.fy = e.y; })
    .on("end", (e, d) => { if (!e.active) sim.alphaTarget(0); d.fx = null; d.fy = null; }));

  // ── Selection + taint state ──
  let selectedPath = null;
  let selectedFocusId = null;
  let taintMode = false;

  // ── Stats + controls wrapper ──
  const wrapper = document.createElement('div');
  wrapper.className = 'absolute top-4 left-4 flex items-start gap-3 z-20 pointer-events-none';
  document.getElementById('graph-view').appendChild(wrapper);

  const statsDiv = document.createElement('div');
  statsDiv.id = 'graph-stats';
  statsDiv.className = 'bg-mantle/95 backdrop-blur border border-surface1 rounded-lg p-3 text-xs min-w-[160px] pointer-events-auto';
  wrapper.appendChild(statsDiv);

  const taintBtnEl = document.createElement('button');
  taintBtnEl.id = 'btn-graph-taints';
  taintBtnEl.className = 'px-3 py-1 rounded-lg text-xs bg-surface0 text-subtext border border-surface2 hover:bg-surface1 pointer-events-auto';
  taintBtnEl.textContent = 'Taints';
  wrapper.appendChild(taintBtnEl);

  // ── Visual helpers ──
  const tooltip = d3.select("#tooltip");

  function applySelectionVisuals(path, focusId) {
    node.select("circle")
      .attr("opacity", n => path.has(n.id) ? 1 : 0.08)
      .attr("stroke", n => n.id === focusId ? C.mauve : (n.dangling ? C.base : C.surface0))
      .attr("stroke-width", n => n.id === focusId ? 3 : (n.dangling ? 0.5 : 1.5));
    node.select("text").attr("opacity", n => path.has(n.id) ? 1 : 0.05);
    link.attr("stroke-opacity", l => path.has(l.source.id) && path.has(l.target.id) ? 0.8 : 0.03)
        .attr("stroke-width", l => path.has(l.source.id) && path.has(l.target.id) ? 2 : 0.5);
  }

  function clearSelectionVisuals() {
    link.attr("stroke-opacity", 0.35).attr("stroke-width", 1);
    node.select("circle")
      .attr("opacity", d => d.dangling ? 0.5 : 1)
      .attr("stroke", d => d.dangling ? C.base : C.surface0)
      .attr("stroke-width", d => d.dangling ? 0.5 : 1.5);
    node.select("text").attr("opacity", 1);
  }

  function applyTaintVisuals() {
    const allTainted = new Set([...taintSources, ...taintPropagated]);
    node.select("circle")
      .attr("fill", n => {
        if (taintSources.has(n.id)) return C.red;
        if (taintPropagated.has(n.id)) return C.yellow;
        return n.color;
      })
      .attr("opacity", n => allTainted.has(n.id) ? 1 : 0.15)
      .attr("stroke", n => taintSources.has(n.id) ? C.red : (taintPropagated.has(n.id) ? C.yellow : (n.dangling ? C.base : C.surface0)))
      .attr("stroke-width", n => (taintSources.has(n.id) || taintPropagated.has(n.id)) ? 2 : (n.dangling ? 0.5 : 1.5));
    node.select("text").attr("opacity", n => allTainted.has(n.id) ? 1 : 0.05);
    link.attr("stroke-opacity", l => {
      const s = allTainted.has(l.source.id), t = allTainted.has(l.target.id);
      if (s && t) return 0.7;
      return 0.03;
    }).attr("stroke", l => {
      if (allTainted.has(l.source.id) && allTainted.has(l.target.id)) return C.red;
      const sid = l.source.id, tid = l.target.id;
      const t = edgeTypes[sid + '>' + tid] || edgeTypes[tid + '>' + sid];
      return TYPE_COLOR[t] || C.surface2;
    }).attr("stroke-width", l => (allTainted.has(l.source.id) && allTainted.has(l.target.id)) ? 2 : 0.5);
  }

  function clearTaintVisuals() {
    node.select("circle")
      .attr("fill", d => d.color)
      .attr("opacity", d => d.dangling ? 0.5 : 1)
      .attr("stroke", d => d.dangling ? C.base : C.surface0)
      .attr("stroke-width", d => d.dangling ? 0.5 : 1.5);
    node.select("text").attr("opacity", 1);
    link.attr("stroke", l => {
      const sid = l.source.id, tid = l.target.id;
      const t = edgeTypes[sid + '>' + tid] || edgeTypes[tid + '>' + sid];
      return TYPE_COLOR[t] || C.surface2;
    }).attr("stroke-opacity", 0.35).attr("stroke-width", 1);
  }

  // ── Taint mode toggle ──
  taintBtnEl.addEventListener('click', () => {
    taintMode = !taintMode;
    selectedPath = null;
    selectedFocusId = null;
    if (taintMode) {
      taintBtnEl.classList.add('bg-red', 'text-crust', 'border-red');
      taintBtnEl.classList.remove('bg-surface0', 'text-subtext', 'border-surface2');
      applyTaintVisuals();
    } else {
      taintBtnEl.classList.remove('bg-red', 'text-crust', 'border-red');
      taintBtnEl.classList.add('bg-surface0', 'text-subtext', 'border-surface2');
      clearTaintVisuals();
    }
    updateGraphStats(null);
  });

  // ── Hover ──
  node.on("mouseover", (e, d) => {
    let html = `<b>${d.id}</b>\nkind: ${d.kind}\ndepth: ${d.depth}`;
    if (d.value) html += `\n${d.value.slice(0, 120)}`;
    if (d.dangling) html += '\n(dangling)';
    if (taintSources.has(d.id)) html += '\n<span style="color:' + C.red + '">taint source</span>';
    else if (taintPropagated.has(d.id)) html += '\n<span style="color:' + C.yellow + '">taint propagated</span>';
    tooltip.html(html).classed("hidden", false)
      .style("left", (e.pageX + 12) + "px").style("top", (e.pageY - 8) + "px");
    if (!selectedPath && !taintMode) {
      link.attr("stroke-opacity", l => (l.source.id === d.id || l.target.id === d.id) ? 0.9 : 0.1)
          .attr("stroke-width", l => (l.source.id === d.id || l.target.id === d.id) ? 2.5 : 0.5);
      node.select("circle").attr("opacity", n =>
        n.id === d.id || links.some(l => (l.source.id === d.id && l.target.id === n.id) || (l.target.id === d.id && l.source.id === n.id)) ? 1 : 0.15);
      node.select("text").attr("opacity", n =>
        n.id === d.id || links.some(l => (l.source.id === d.id && l.target.id === n.id) || (l.target.id === d.id && l.source.id === n.id)) ? 1 : 0.15);
    }
  }).on("mouseout", () => {
    tooltip.classed("hidden", true);
    if (taintMode) {
      applyTaintVisuals();
    } else if (selectedPath) {
      applySelectionVisuals(selectedPath, selectedFocusId);
    } else {
      clearSelectionVisuals();
    }
  });

  // ── Click: select subgraph + show detail ──
  function collectGraphPath(id) {
    const parents = {};
    const children = {};
    links.forEach(l => {
      const sid = l.source.id, tid = l.target.id;
      if (!parents[tid]) parents[tid] = [];
      parents[tid].push(sid);
      if (!children[sid]) children[sid] = [];
      children[sid].push(tid);
      // axiom-ref is bidirectional
      const t = edgeTypes[sid + '>' + tid] || edgeTypes[tid + '>' + sid];
      if (t === 'axiom-ref') {
        if (!parents[sid]) parents[sid] = [];
        parents[sid].push(tid);
        if (!children[tid]) children[tid] = [];
        children[tid].push(sid);
      }
    });
    // Upstream
    const path = new Set();
    const q = [id];
    while (q.length) {
      const n = q.pop();
      if (path.has(n)) continue;
      path.add(n);
      (parents[n] || []).forEach(p => q.push(p));
    }
    // Downstream — separate visited set so id isn't skipped
    const downVisited = new Set();
    const dq = [id];
    while (dq.length) {
      const n = dq.pop();
      if (downVisited.has(n)) continue;
      downVisited.add(n);
      path.add(n);
      (children[n] || []).forEach(c => dq.push(c));
    }
    return path;
  }

  node.on("click", (e, d) => {
    e.stopPropagation();
    const item = ITEM_BY_ID[d.id];
    if (item) showDetail(item);

    if (taintMode) return;  // no selection visuals in taint mode

    const path = collectGraphPath(d.id);
    selectedPath = path;
    selectedFocusId = d.id;

    applySelectionVisuals(path, d.id);
    updateGraphStats(path);
  });

  // Clear selection on background click
  svg.on("click", () => {
    if (taintMode) return;
    selectedPath = null;
    selectedFocusId = null;
    clearSelectionVisuals();
    updateGraphStats(null);
  });

  function updateGraphStats(filterSet) {
    const fNodes = filterSet
      ? nodes.filter(n => filterSet.has(n.id))
      : nodes;

    const kindCounts = {};
    let danglingCount = 0;
    fNodes.forEach(n => {
      if (!kindCounts[n.kind]) kindCounts[n.kind] = 0;
      kindCounts[n.kind]++;
      if (n.dangling) danglingCount++;
    });

    const total = fNodes.length;
    const maxDepthF = Math.max(0, ...fNodes.map(n => n.depth));
    const kindEntries = Object.entries(kindCounts).sort((a,b) => b[1] - a[1]);
    const maxK = kindEntries.length ? Math.max(...kindEntries.map(([,v]) => v)) : 1;

    let html = `<div class="font-bold text-lavender mb-2">${filterSet ? 'Selection' : 'Graph'} <span class="text-overlay0 font-normal">${total} nodes</span></div>`;

    // Kind bar chart
    kindEntries.forEach(([k, count]) => {
      const barW = Math.max(4, (count / maxK) * 80);
      const color = kindDot(k);
      html += `<div class="flex items-center gap-2 mb-0.5">`;
      html += `<div style="width:${barW}px;height:5px;background:${color};border-radius:2px;opacity:0.85"></div>`;
      html += `<span style="color:${color}" class="text-[10px]">${k} ${count}</span>`;
      html += `</div>`;
    });

    // Depth range
    html += `<div class="mt-2 text-overlay0">depth: 0\u2013${maxDepthF}</div>`;

    // Dangling
    if (danglingCount > 0) {
      html += `<div class="text-overlay0">dangling: ${danglingCount}</div>`;
    }

    // Graph metrics (only for full graph, not selection)
    if (!filterSet) {
      html += `<div class="mt-2 border-t border-surface1 pt-2">`;
      html += `<div class="text-overlay0">components: <span class="text-text font-bold">${components.length}</span></div>`;
      const icPct = Math.round(interconnectivity * 100);
      const icColor = icPct >= 80 ? C.green : icPct >= 50 ? C.yellow : C.red;
      html += `<div class="text-overlay0">interconnectivity: <span style="color:${icColor}" class="font-bold">${icPct}%</span></div>`;
      html += `<div class="text-overlay0 text-[10px]">${mainLeaves.length}/${leaves.length} leaves in main</div>`;
      html += `</div>`;
    }

    // Taint summary
    const fNodeIds = filterSet || new Set(nodes.map(n => n.id));
    const fSources = [...taintSources].filter(id => fNodeIds.has(id));
    const fPropagated = [...taintPropagated].filter(id => fNodeIds.has(id));
    if (fSources.length > 0) {
      const pctS = total ? Math.round(fSources.length / total * 100) : 0;
      html += `<div class="mt-1"><span class="text-red font-bold">${fSources.length}/${pctS}%</span> <span class="text-red text-[10px]">unverified</span></div>`;
    }
    if (fPropagated.length > 0) {
      const pctP = total ? Math.round(fPropagated.length / total * 100) : 0;
      html += `<div><span class="text-yellow font-bold">${fPropagated.length}/${pctP}%</span> <span class="text-yellow text-[10px]">propagated</span></div>`;
    }
    if (fSources.length === 0 && fPropagated.length === 0) {
      html += `<div class="mt-1 text-green text-[10px]">\u2713 clean</div>`;
    }

    statsDiv.innerHTML = html;
  }

  updateGraphStats(null);

  // ── External focus API ──
  window._graphFocusNode = function(name) {
    const target = nodes.find(n => n.id === name);
    if (!target) return;
    taintMode = false;
    taintBtnEl.classList.remove('bg-red', 'text-crust', 'border-red');
    taintBtnEl.classList.add('bg-surface0', 'text-subtext', 'border-surface2');
    const path = collectGraphPath(name);
    selectedPath = path;
    selectedFocusId = name;
    applySelectionVisuals(path, name);
    updateGraphStats(path);
    // Zoom to center on the focused node
    const scale = 1.2;
    const tx = width / 2 - target.x * scale;
    const ty = height / 2 - target.y * scale;
    svg.transition().duration(600).call(
      zoomBehavior.transform, d3.zoomIdentity.translate(tx, ty).scale(scale)
    );
    // Open detail panel
    const item = ITEM_BY_ID[name];
    if (item) showDetail(item);
  };

  // ── Depth band labels ──
  for (let d = 0; d <= maxDepth; d++) {
    gRoot.append("text")
      .attr("x", PAD_LEFT + d * BAND_W).attr("y", 20)
      .attr("text-anchor", "middle")
      .attr("fill", C.overlay0).attr("font-size", "9px").attr("font-weight", "bold")
      .text(`d${d}`);
  }
  if (danglingSet.size > 0) {
    gRoot.append("text")
      .attr("x", DANGLE_X).attr("y", 20)
      .attr("text-anchor", "middle")
      .attr("fill", C.surface2).attr("font-size", "9px").attr("font-style", "italic")
      .text(`dangling (${danglingSet.size})`);
    // Kind group labels for dangling column
    danglingKinds.forEach(k => {
      const count = nodes.filter(n => n.dangling && n.kind === k).length;
      gRoot.append("text")
        .attr("x", DANGLE_X - 60).attr("y", danglingKindY[k])
        .attr("text-anchor", "end")
        .attr("fill", kindDot(k)).attr("font-size", "8px").attr("font-style", "italic")
        .text(`${k} (${count})`);
    });
  }

  // ── Tick ──
  sim.on("tick", () => {
    link.attr("x1", d => d.source.x).attr("y1", d => d.source.y)
        .attr("x2", d => d.target.x).attr("y2", d => d.target.y);
    node.attr("transform", d => `translate(${d.x},${d.y})`);
  });

  // Auto-zoom to fit — only once on first settle
  let initialFitDone = false;
  sim.on("end", () => {
    if (initialFitDone) return;
    initialFitDone = true;
    requestAnimationFrame(() => {
      const bounds = gRoot.node().getBBox();
      if (bounds.width > 0 && bounds.height > 0) {
        const scale = Math.min(width / (bounds.width + 160), height / (bounds.height + 160), 1);
        const tx = (width - bounds.width * scale) / 2 - bounds.x * scale;
        const ty = (height - bounds.height * scale) / 2 - bounds.y * scale;
        svg.transition().duration(800).call(
          zoomBehavior.transform, d3.zoomIdentity.translate(tx, ty).scale(scale)
        );
      }
    });
  });
}
