// ── D3 Graph v2 — canvas edges + viewport culling + zoom-based labels ──
// Diff nodes are always SVG (with animated glow). Regular nodes use canvas
// at overview zoom and SVG when zoomed in past SVG_DETAIL_ZOOM.
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

  // Build links from LAYERS.edges
  const edgeTypes = {};
  const seenEdge = new Set();
  LAYERS.edges.forEach(e => {
    edgeTypes[e.source + '>' + e.target] = e.type;
    const key = e.source + '>' + e.target;
    if (seenEdge.has(key)) return;
    seenEdge.add(key);
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

  // Also add input edges from DATA items not covered by LAYERS.edges
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

  const TYPE_COLOR = {'use':C.green,'declare':C.overlay0,'pull':C.blue,'axiom-ref':C.peach,'diff':C.patronusGlow};

  // ── Pre-build adjacency map for O(1) neighbor lookups ──
  const neighbors = {};
  nodes.forEach(n => { neighbors[n.id] = new Set(); });
  links.forEach(l => {
    const sid = typeof l.source === 'string' ? l.source : l.source.id;
    const tid = typeof l.target === 'string' ? l.target : l.target.id;
    if (neighbors[sid]) neighbors[sid].add(tid);
    if (neighbors[tid]) neighbors[tid].add(sid);
  });

  // ── Identify dangling nodes ──
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
  const adj = {};
  links.forEach(l => {
    const sid = typeof l.source === 'string' ? l.source : l.source.id;
    const tid = typeof l.target === 'string' ? l.target : l.target.id;
    if (!adj[sid]) adj[sid] = [];
    if (!adj[tid]) adj[tid] = [];
    adj[sid].push(tid);
    adj[tid].push(sid);
  });

  const componentOf = {};
  const components = [];
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

  let mainCompIdx = 0;
  components.forEach((c, i) => { if (c.size > components[mainCompIdx].size) mainCompIdx = i; });
  const mainComp = components[mainCompIdx] || new Set();

  const hasChild = new Set();
  links.forEach(l => {
    const sid = typeof l.source === 'string' ? l.source : l.source.id;
    hasChild.add(sid);
  });
  const leaves = nodes.filter(n => !n.dangling && !hasChild.has(n.id));
  const mainLeaves = leaves.filter(n => mainComp.has(n.id));
  const interconnectivity = leaves.length > 0 ? mainLeaves.length / leaves.length : 1;

  // ── Taint data ──
  const _gtd = (typeof TAINT_DATA !== 'undefined') ? TAINT_DATA : {sources:[], tainted:[], reasons:{}};
  const taintSources = new Set(_gtd.sources);
  const _gAllTainted = new Set(_gtd.tainted);
  const taintPropagated = new Set([..._gAllTainted].filter(n => !taintSources.has(n)));
  const allTaintedSet = new Set([...taintSources, ...taintPropagated]);

  // ── Separate diff vs regular nodes ──
  const diffNodes = nodes.filter(n => n.kind === 'diff');
  const regularNodes = nodes.filter(n => n.kind !== 'diff');
  const diffIds = new Set(diffNodes.map(n => n.id));

  // ── Layout constants ──
  const maxDepth = Math.max(0, ...nodes.filter(n => !n.dangling).map(n => n.depth));
  const graphView = document.getElementById('graph-view');
  const width = window.innerWidth;
  const height = window.innerHeight - 60;

  const BAND_W = Math.max(300, (width - 160) / Math.max(maxDepth + 1, 1));
  const PAD_LEFT = 80;
  const DANGLE_X = PAD_LEFT + (maxDepth + 2) * BAND_W;
  const NODE_R = 6;
  const DANGLE_R = 4;
  const DIFF_R = NODE_R * 1.4;
  const GLOW_R = DIFF_R * 2.5;

  // ── Canvas layer (edges + overview regular nodes) ──
  const canvas = document.createElement('canvas');
  canvas.width = width * window.devicePixelRatio;
  canvas.height = height * window.devicePixelRatio;
  canvas.style.width = width + 'px';
  canvas.style.height = height + 'px';
  canvas.style.position = 'absolute';
  canvas.style.top = '0';
  canvas.style.left = '0';
  canvas.style.pointerEvents = 'none';
  graphView.insertBefore(canvas, graphView.firstChild);
  const ctx = canvas.getContext('2d');
  ctx.scale(window.devicePixelRatio, window.devicePixelRatio);

  // ── SVG layer ──
  const svg = d3.select("#graph");
  svg.style("position", "absolute").style("top", "0").style("left", "0");
  const gRoot = svg.append("g");

  // ── SVG defs for diff gradients ──
  const defs = svg.append("defs");
  function _addGrad(id, highlight, core, outer) {
    const g = defs.append("radialGradient").attr("id", id).attr("cx", "35%").attr("cy", "35%");
    g.append("stop").attr("offset", "0%").attr("stop-color", highlight);
    g.append("stop").attr("offset", "50%").attr("stop-color", core);
    g.append("stop").attr("offset", "100%").attr("stop-color", outer);
  }
  _addGrad("patronus-coherent", C.patronusHighlight, C.patronusCore, C.patronusGlowOuter);
  _addGrad("patronus-tainted", C.red, C.patronusTaintCore, C.patronusTaintOuter);
  _addGrad("patronus-warn", C.yellow, C.patronusWarnCore, C.patronusWarnOuter);

  function _addGlowGrad(id, glow, outer) {
    const g = defs.append("radialGradient").attr("id", id);
    g.append("stop").attr("offset", "0%").attr("stop-color", glow).attr("stop-opacity", 1);
    g.append("stop").attr("offset", "40%").attr("stop-color", outer).attr("stop-opacity", 0.6);
    g.append("stop").attr("offset", "70%").attr("stop-color", outer).attr("stop-opacity", 0);
    g.append("stop").attr("offset", "100%").attr("stop-color", outer).attr("stop-opacity", 0);
  }
  _addGlowGrad("patronus-glow-coherent", C.patronusGlow, C.patronusGlowOuter);
  _addGlowGrad("patronus-glow-tainted", C.patronusTaintGlow, C.patronusTaintOuter);
  _addGlowGrad("patronus-glow-warn", C.patronusWarnGlow, C.patronusWarnOuter);

  function diffFillUrl(id) {
    const st = DIFF_STATE[id] || 'coherent';
    return `url(#patronus-${st})`;
  }
  function diffGlowUrl(id) {
    const st = DIFF_STATE[id] || 'coherent';
    return `url(#patronus-glow-${st})`;
  }

  // ── Dangling kind bands ──
  const danglingKinds = [...new Set(nodes.filter(n => n.dangling).map(n => n.kind))].sort();
  const DANGLE_BAND_H = danglingKinds.length > 1 ? height / (danglingKinds.length + 1) : height;
  const danglingKindY = {};
  danglingKinds.forEach((k, i) => { danglingKindY[k] = (i + 1) * DANGLE_BAND_H; });

  // ── Permanent SVG diff nodes (with animated glow, like v1) ──
  const diffNodeG = gRoot.append("g").attr("class", "diff-nodes-permanent");
  const diffSvgNode = diffNodeG.selectAll("g")
    .data(diffNodes).join("g").attr("class", "graph-node graph-diff-node cursor-pointer");

  // Diff glow — pulsing outer circle
  const diffGlow = diffSvgNode.append("circle")
    .attr("r", GLOW_R)
    .attr("fill", d => diffGlowUrl(d.id))
    .attr("opacity", 0.55);
  // Pulse animation via SVG <animate> — matches v1 exactly
  diffGlow.each(function() {
    const el = d3.select(this);
    el.append("animate").attr("attributeName", "r")
      .attr("values", `${GLOW_R*0.85};${GLOW_R*1.15};${GLOW_R*0.85}`)
      .attr("dur", "3s").attr("repeatCount", "indefinite");
    el.append("animate").attr("attributeName", "opacity")
      .attr("values", "0.55;0.35;0.55")
      .attr("dur", "3s").attr("repeatCount", "indefinite");
  });

  // Diff core
  diffSvgNode.append("circle")
    .attr("class", "node-dot")
    .attr("r", DIFF_R)
    .attr("fill", d => diffFillUrl(d.id))
    .attr("stroke", "none");

  // Diff labels
  diffSvgNode.append("text")
    .attr("class", "node-label")
    .attr("dx", DIFF_R + 4).attr("dy", 3)
    .attr("fill", C.text).attr("font-size", "8px")
    .text(d => {
      const short = d.id.includes('.') ? d.id.split('.').slice(1).join('.') : d.id;
      return short.length > 25 ? short.slice(0, 22) + '...' : short;
    });

  // Diff events
  diffSvgNode.on('mouseover', handleMouseOver)
    .on('mouseout', handleMouseOut)
    .on('click', handleClick);

  // ── Zoom state ──
  let currentTransform = d3.zoomIdentity;
  const LABEL_ZOOM_MIN = 0.35;
  const LABEL_ZOOM_FULL = 0.7;
  const SVG_DETAIL_ZOOM = 0.5;

  // ── Viewport culling ──
  function getViewport(transform) {
    const inv = transform.invert([0, 0]);
    const inv2 = transform.invert([width, height]);
    const pad = 50 / transform.k;
    return { x0: inv[0] - pad, y0: inv[1] - pad, x1: inv2[0] + pad, y1: inv2[1] + pad };
  }

  function inViewport(n, vp) {
    return n.x >= vp.x0 && n.x <= vp.x1 && n.y >= vp.y0 && n.y <= vp.y1;
  }

  // ── Pre-compute link colors ──
  let linkColors = null;
  function ensureLinkColors() {
    if (linkColors) return;
    linkColors = links.map(l => {
      const sid = l.source.id || l.source;
      const tid = l.target.id || l.target;
      const t = edgeTypes[sid + '>' + tid] || edgeTypes[tid + '>' + sid];
      return TYPE_COLOR[t] || C.surface2;
    });
  }

  // ── Selection + taint state ──
  // Taint and focus can coexist: taint is the base layer, focus overlays on top.
  let selectedPath = null;
  let selectedFocusId = null;
  let taintMode = false;

  // ── Compute visual state for a node ──
  function nodeAlpha(id, isDangling) {
    if (selectedPath && taintMode) {
      // Both active: path nodes bright, everything else equally dim
      if (selectedPath.has(id)) return 1;
      return 0.05;
    }
    if (selectedPath) return selectedPath.has(id) ? 1 : 0.08;
    if (taintMode) return allTaintedSet.has(id) ? 1 : 0.15;
    return isDangling ? 0.5 : 1;
  }

  function nodeColor(n) {
    if (taintMode) {
      if (n.kind === 'diff') return null; // handled by SVG gradient
      if (taintSources.has(n.id)) return C.red;
      if (taintPropagated.has(n.id)) return C.yellow;
    }
    return n.color;
  }

  function edgeAlpha(sid, tid) {
    if (selectedPath && taintMode) {
      if (selectedPath.has(sid) && selectedPath.has(tid)) return 0.8;
      return 0.02;
    }
    if (selectedPath) {
      return (selectedPath.has(sid) && selectedPath.has(tid)) ? 0.8 : 0.03;
    }
    if (taintMode) {
      return (allTaintedSet.has(sid) && allTaintedSet.has(tid)) ? 0.7 : 0.03;
    }
    return 0.35;
  }

  function edgeColor(sid, tid, baseColor) {
    if (taintMode && allTaintedSet.has(sid) && allTaintedSet.has(tid)) return C.red;
    return baseColor;
  }

  function edgeLw(sid, tid) {
    if (selectedPath && selectedPath.has(sid) && selectedPath.has(tid)) return 2;
    if (taintMode && allTaintedSet.has(sid) && allTaintedSet.has(tid)) return 2;
    if (selectedPath || taintMode) return 0.5;
    return 1;
  }

  // ── Canvas draw ──
  function drawCanvas(transform) {
    ensureLinkColors();
    ctx.save();
    ctx.clearRect(0, 0, width, height);
    ctx.translate(transform.x, transform.y);
    ctx.scale(transform.k, transform.k);

    const vp = getViewport(transform);
    const scale = transform.k;
    const showLabels = scale >= LABEL_ZOOM_MIN;
    const labelAlpha = showLabels ? Math.min(1, (scale - LABEL_ZOOM_MIN) / (LABEL_ZOOM_FULL - LABEL_ZOOM_MIN)) : 0;

    // ── Draw edges ──
    for (let i = 0; i < links.length; i++) {
      const l = links[i];
      const sx = l.source.x, sy = l.source.y, tx = l.target.x, ty = l.target.y;
      if ((sx < vp.x0 && tx < vp.x0) || (sx > vp.x1 && tx > vp.x1) ||
          (sy < vp.y0 && ty < vp.y0) || (sy > vp.y1 && ty > vp.y1)) continue;

      const sid = l.source.id, tid = l.target.id;
      ctx.beginPath();
      ctx.moveTo(sx, sy);
      ctx.lineTo(tx, ty);
      ctx.strokeStyle = edgeColor(sid, tid, linkColors[i]);
      ctx.globalAlpha = edgeAlpha(sid, tid);
      ctx.lineWidth = edgeLw(sid, tid);
      ctx.stroke();
    }

    // ── Draw regular nodes on canvas (diff nodes are always SVG) ──
    const drawSvgNodes = scale >= SVG_DETAIL_ZOOM;
    ctx.globalAlpha = 1;

    for (let i = 0; i < regularNodes.length; i++) {
      const n = regularNodes[i];
      if (!inViewport(n, vp)) continue;
      if (drawSvgNodes) continue; // SVG layer handles these

      const r = n.dangling ? DANGLE_R : NODE_R;
      const color = nodeColor(n) || n.color;
      const alpha = nodeAlpha(n.id, n.dangling);

      ctx.beginPath();
      ctx.arc(n.x, n.y, r, 0, Math.PI * 2);
      ctx.fillStyle = color;
      ctx.globalAlpha = alpha;
      ctx.fill();

      // Labels on canvas when zoomed in enough but below SVG threshold
      if (showLabels && alpha > 0.1) {
        const fontSize = Math.max(6, Math.min(10, 8));
        ctx.font = `${fontSize}px sans-serif`;
        ctx.fillStyle = n.dangling ? C.surface2 : C.text;
        ctx.globalAlpha = alpha * labelAlpha;
        const short = n.id.includes('.') ? n.id.split('.').slice(1).join('.') : n.id;
        const label = short.length > 25 ? short.slice(0, 22) + '...' : short;
        ctx.fillText(label, n.x + r + 3, n.y + 3);
      }
    }

    ctx.restore();
  }

  // ── Dynamic SVG for regular nodes (only when zoomed in) ──
  let svgNodesCreated = false;
  let regularNode = null;  // D3 selection of regular SVG nodes
  let currentVisibleIds = new Set();

  function updateSvgNodes(transform) {
    const scale = transform.k;
    const showSvg = scale >= SVG_DETAIL_ZOOM;
    const vp = getViewport(transform);
    const showLabels = scale >= LABEL_ZOOM_MIN;
    const labelAlpha = showLabels ? Math.min(1, (scale - LABEL_ZOOM_MIN) / (LABEL_ZOOM_FULL - LABEL_ZOOM_MIN)) : 0;

    if (!showSvg) {
      if (svgNodesCreated) {
        gRoot.selectAll('.graph-node:not(.graph-diff-node)').remove();
        svgNodesCreated = false;
        currentVisibleIds.clear();
        regularNode = null;
      }
      // Still update diff node visuals
      _updateDiffVisuals(labelAlpha);
      return;
    }

    // Determine which regular nodes are in viewport
    const visibleNodes = regularNodes.filter(n => inViewport(n, vp));
    const visibleIds = new Set(visibleNodes.map(n => n.id));

    const added = visibleNodes.filter(n => !currentVisibleIds.has(n.id));
    const removed = [...currentVisibleIds].filter(id => !visibleIds.has(id));

    if (added.length > 0 || removed.length > 0) {
      if (removed.length > 0) {
        const removeSet = new Set(removed);
        gRoot.selectAll('.graph-node:not(.graph-diff-node)').filter(d => removeSet.has(d.id)).remove();
      }

      if (added.length > 0) {
        const newNodes = gRoot.selectAll('.graph-node-new')
          .data(added, d => d.id)
          .join('g')
          .attr('class', 'graph-node cursor-pointer')
          .attr('transform', d => `translate(${d.x},${d.y})`);

        newNodes.append('circle')
          .attr('class', 'node-dot')
          .attr('r', d => d.dangling ? DANGLE_R : NODE_R)
          .attr('fill', d => d.color)
          .attr('stroke', d => d.dangling ? C.base : C.surface0)
          .attr('stroke-width', d => d.dangling ? 0.5 : 1.5)
          .attr('opacity', d => d.dangling ? 0.5 : 1);

        newNodes.append('text')
          .attr('class', 'node-label')
          .attr('dx', d => (d.dangling ? DANGLE_R : NODE_R) + 4)
          .attr('dy', 3)
          .attr('fill', d => d.dangling ? C.surface2 : C.text)
          .attr('font-size', d => d.dangling ? '7px' : '8px')
          .text(d => {
            const short = d.id.includes('.') ? d.id.split('.').slice(1).join('.') : d.id;
            return short.length > 25 ? short.slice(0, 22) + '...' : short;
          });

        newNodes.on('mouseover', handleMouseOver)
          .on('mouseout', handleMouseOut)
          .on('click', handleClick);

        newNodes.call(d3.drag()
          .on('start', (e, d) => { if (!e.active) sim.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; })
          .on('drag', (e, d) => { d.fx = e.x; d.fy = e.y; })
          .on('end', (e, d) => { if (!e.active) sim.alphaTarget(0); d.fx = null; d.fy = null; }));
      }

      currentVisibleIds = visibleIds;
    }

    regularNode = gRoot.selectAll('.graph-node:not(.graph-diff-node)');
    _applyRegularSvgVisuals(labelAlpha);
    _updateDiffVisuals(labelAlpha);
  }

  // ── Apply visuals to regular SVG nodes ──
  function _applyRegularSvgVisuals(labelAlpha) {
    if (!regularNode) return;
    regularNode.select('.node-dot')
      .attr('fill', d => nodeColor(d) || d.color)
      .attr('opacity', d => nodeAlpha(d.id, d.dangling))
      .attr('stroke', d => {
        if (selectedPath && d.id === selectedFocusId) return C.mauve;
        if (taintMode && taintSources.has(d.id)) return C.red;
        if (taintMode && taintPropagated.has(d.id)) return C.yellow;
        return d.dangling ? C.base : C.surface0;
      })
      .attr('stroke-width', d => {
        if (selectedPath && d.id === selectedFocusId) return 3;
        if (taintMode && (taintSources.has(d.id) || taintPropagated.has(d.id))) return 2;
        return d.dangling ? 0.5 : 1.5;
      });
    regularNode.select('.node-label').attr('opacity', d => nodeAlpha(d.id, d.dangling) * (labelAlpha != null ? labelAlpha : 1));
  }

  // ── Apply visuals to permanent diff SVG nodes ──
  function _updateDiffVisuals(labelAlpha) {
    diffSvgNode.select('.node-dot')
      .attr('opacity', d => nodeAlpha(d.id, false));
    diffGlow.each(function(d) {
      const el = d3.select(this);
      const a = nodeAlpha(d.id, false);
      // Pause/resume animation based on visibility
      if (a < 0.1) {
        el.attr('opacity', 0.08);
        el.selectAll('animate').attr('begin', 'indefinite');
      } else {
        el.attr('opacity', null); // let animate control it
        el.selectAll('animate').attr('begin', '0s');
      }
    });
    diffSvgNode.select('.node-label').attr('opacity', d => nodeAlpha(d.id, false) * (labelAlpha != null ? labelAlpha : 1));
  }

  // ── Tooltip ──
  const tooltip = d3.select("#tooltip");

  function handleMouseOver(e, d) {
    let html = `<b>${d.id}</b>\nkind: ${d.kind}\ndepth: ${d.depth}`;
    if (d.value) html += `\n${d.value.slice(0, 120)}`;
    if (d.dangling) html += '\n(dangling)';
    if (taintSources.has(d.id)) html += '\n<span style="color:' + C.red + '">taint source</span>';
    else if (taintPropagated.has(d.id)) html += '\n<span style="color:' + C.yellow + '">taint propagated</span>';
    tooltip.html(html).classed("hidden", false)
      .style("left", (e.pageX + 12) + "px").style("top", (e.pageY - 8) + "px");
    if (!selectedPath && !taintMode) {
      // Highlight neighbors
      const nb = neighbors[d.id] || new Set();
      const isNb = id => id === d.id || nb.has(id);
      if (regularNode) {
        regularNode.select('.node-dot').attr('opacity', n => isNb(n.id) ? 1 : 0.15);
        regularNode.select('.node-label').attr('opacity', n => isNb(n.id) ? 1 : 0.15);
      }
      diffGlow.each(function(n) {
        d3.select(this).attr('opacity', isNb(n.id) ? null : 0.08);
      });
      diffSvgNode.select('.node-dot').attr('opacity', n => isNb(n.id) ? 1 : 0.15);
      diffSvgNode.select('.node-label').attr('opacity', n => isNb(n.id) ? 1 : 0.15);
    }
    requestCanvasDraw();
  }

  function handleMouseOut() {
    tooltip.classed("hidden", true);
    requestCanvasDraw();
  }

  function handleClick(e, d) {
    e.stopPropagation();
    const item = ITEM_BY_ID[d.id];
    if (item) showDetail(item);
    // Focus works in both normal and taint mode
    const path = collectGraphPath(d.id);
    selectedPath = path;
    selectedFocusId = d.id;
    requestCanvasDraw();
    updateGraphStats(path);
  }

  // ── Collect subgraph path ──
  function collectGraphPath(id) {
    const parents = {};
    const children = {};
    links.forEach(l => {
      const sid = l.source.id, tid = l.target.id;
      if (!parents[tid]) parents[tid] = [];
      parents[tid].push(sid);
      if (!children[sid]) children[sid] = [];
      children[sid].push(tid);
      const t = edgeTypes[sid + '>' + tid] || edgeTypes[tid + '>' + sid];
      if (t === 'axiom-ref') {
        if (!parents[sid]) parents[sid] = [];
        parents[sid].push(tid);
        if (!children[tid]) children[tid] = [];
        children[tid].push(sid);
      }
    });
    const path = new Set();
    const q = [id];
    while (q.length) {
      const n = q.pop();
      if (path.has(n)) continue;
      path.add(n);
      (parents[n] || []).forEach(p => q.push(p));
    }
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

  // ── Force simulation ──
  const DIFF_Y = height + 120;
  const sim = d3.forceSimulation(nodes)
    .force("link", d3.forceLink(links).id(d => d.id).distance(80).strength(0.3))
    .force("charge", d3.forceManyBody().strength(-200))
    .force("collide", d3.forceCollide().radius(28))
    .force("depthX", d3.forceX(d => {
      if (d.dangling) return DANGLE_X;
      if (d.kind === 'diff') return PAD_LEFT + maxDepth * BAND_W;
      return PAD_LEFT + d.depth * BAND_W;
    }).strength(d => d.dangling ? 0.8 : d.kind === 'diff' ? 0.9 : 0.85))
    .force("centerY", d3.forceY(d => {
      if (d.dangling) return danglingKindY[d.kind] || height / 2;
      if (d.kind === 'diff') return DIFF_Y;
      return height / 2;
    }).strength(d => d.dangling ? 0.3 : d.kind === 'diff' ? 0.7 : 0.05));

  // Diff drag
  diffSvgNode.call(d3.drag()
    .on('start', (e, d) => { if (!e.active) sim.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; })
    .on('drag', (e, d) => { d.fx = e.x; d.fy = e.y; })
    .on('end', (e, d) => { if (!e.active) sim.alphaTarget(0); d.fx = null; d.fy = null; }));

  // ── Zoom handler ──
  let canvasDrawScheduled = false;
  function requestCanvasDraw() {
    if (canvasDrawScheduled) return;
    canvasDrawScheduled = true;
    requestAnimationFrame(() => {
      canvasDrawScheduled = false;
      drawCanvas(currentTransform);
      updateSvgNodes(currentTransform);
    });
  }

  const zoomBehavior = d3.zoom()
    .scaleExtent([0.05, 8])
    .on("zoom", (e) => {
      currentTransform = e.transform;
      gRoot.attr("transform", e.transform);
      if (e.sourceEvent) userInteracted = true;
      requestCanvasDraw();
    });
  svg.call(zoomBehavior);
  svg.on("click.zoom", null);  // disable double-click zoom (matches v1)

  // Background click to clear selection
  svg.on("click", () => {
    selectedPath = null;
    selectedFocusId = null;
    requestCanvasDraw();
    updateGraphStats(null);
  });

  // ── Stats + controls ──
  const wrapper = document.createElement('div');
  wrapper.className = 'absolute top-4 left-4 flex items-start gap-3 z-20 pointer-events-none';
  graphView.appendChild(wrapper);

  const statsDiv = document.createElement('div');
  statsDiv.id = 'graph-stats';
  statsDiv.className = 'bg-mantle/95 backdrop-blur border border-surface1 rounded-lg p-3 text-xs min-w-[160px] pointer-events-auto';
  wrapper.appendChild(statsDiv);

  const taintBtnEl = document.createElement('button');
  taintBtnEl.id = 'btn-graph-taints';
  taintBtnEl.className = 'px-3 py-1 rounded-lg text-xs bg-surface0 text-subtext border border-surface2 hover:bg-surface1 pointer-events-auto';
  taintBtnEl.textContent = 'Taints';
  wrapper.appendChild(taintBtnEl);

  taintBtnEl.addEventListener('click', () => {
    taintMode = !taintMode;
    // Don't clear selection — taint + focus coexist
    if (taintMode) {
      taintBtnEl.classList.add('bg-red', 'text-crust', 'border-red');
      taintBtnEl.classList.remove('bg-surface0', 'text-subtext', 'border-surface2');
    } else {
      taintBtnEl.classList.remove('bg-red', 'text-crust', 'border-red');
      taintBtnEl.classList.add('bg-surface0', 'text-subtext', 'border-surface2');
    }
    requestCanvasDraw();
    updateGraphStats(selectedPath);
  });

  // ── Depth band labels ──
  let bandLabelsDrawn = false;
  function drawBandLabels() {
    if (bandLabelsDrawn) return;
    bandLabelsDrawn = true;
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
      danglingKinds.forEach(k => {
        const count = nodes.filter(n => n.dangling && n.kind === k).length;
        gRoot.append("text")
          .attr("x", DANGLE_X - 60).attr("y", danglingKindY[k])
          .attr("text-anchor", "end")
          .attr("fill", kindDot(k)).attr("font-size", "8px").attr("font-style", "italic")
          .text(`${k} (${count})`);
      });
    }
  }

  // ── Stats ──
  function updateGraphStats(filterSet) {
    const fNodes = filterSet ? nodes.filter(n => filterSet.has(n.id)) : nodes;
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
    kindEntries.forEach(([k, count]) => {
      const barW = Math.max(4, (count / maxK) * 80);
      const color = kindDot(k);
      html += `<div class="flex items-center gap-2 mb-0.5">`;
      html += `<div style="width:${barW}px;height:5px;background:${color};border-radius:2px;opacity:0.85"></div>`;
      html += `<span style="color:${color}" class="text-[10px]">${k} ${count}</span>`;
      html += `</div>`;
    });
    html += `<div class="mt-2 text-overlay0">depth: 0\u2013${maxDepthF}</div>`;
    if (danglingCount > 0) html += `<div class="text-overlay0">dangling: ${danglingCount}</div>`;
    if (!filterSet) {
      html += `<div class="mt-2 border-t border-surface1 pt-2">`;
      html += `<div class="text-overlay0">components: <span class="text-text font-bold">${components.length}</span></div>`;
      const icPct = Math.round(interconnectivity * 100);
      const icColor = icPct >= 80 ? C.green : icPct >= 50 ? C.yellow : C.red;
      html += `<div class="text-overlay0">interconnectivity: <span style="color:${icColor}" class="font-bold">${icPct}%</span></div>`;
      html += `<div class="text-overlay0 text-[10px]">${mainLeaves.length}/${leaves.length} leaves in main</div>`;
      html += `</div>`;
    }
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
    // Don't disable taint — focus overlays on top
    const path = collectGraphPath(name);
    selectedPath = path;
    selectedFocusId = name;
    requestCanvasDraw();
    updateGraphStats(path);
    const scale = 1.2;
    const fitW = width;
    const tx = fitW / 2 - target.x * scale;
    const ty = height / 2 - target.y * scale;
    svg.transition().duration(600).call(
      zoomBehavior.transform, d3.zoomIdentity.translate(tx, ty).scale(scale)
    );
    const item = ITEM_BY_ID[name];
    if (item) showDetail(item);
  };

  // ── Tick ──
  sim.on("tick", () => {
    // Update permanent diff SVG positions
    diffSvgNode.attr('transform', d => `translate(${d.x},${d.y})`);
    // Update dynamic regular SVG positions
    if (svgNodesCreated || currentTransform.k >= SVG_DETAIL_ZOOM) {
      gRoot.selectAll('.graph-node:not(.graph-diff-node)').attr('transform', d => `translate(${d.x},${d.y})`);
      svgNodesCreated = gRoot.selectAll('.graph-node:not(.graph-diff-node)').size() > 0;
    }
    // Camera follow: track focused node during simulation until user interacts
    if (selectedFocusId && !userInteracted) {
      const target = nodes.find(n => n.id === selectedFocusId);
      if (target) {
        const scale = currentTransform.k;
        const tx = width / 2 - target.x * scale;
        const ty = height / 2 - target.y * scale;
        svg.call(zoomBehavior.transform, d3.zoomIdentity.translate(tx, ty).scale(scale));
      }
    }
    requestCanvasDraw();
  });

  // Auto-zoom to fit — only if user hasn't manually zoomed/panned
  // Uses getBBox() on the SVG gRoot (same as v1) for consistent framing.
  let initialFitDone = false;
  let userInteracted = false;
  sim.on("end", () => {
    if (initialFitDone) return;
    initialFitDone = true;
    if (userInteracted) { drawBandLabels(); return; }
    drawBandLabels();
    requestAnimationFrame(() => {
      // Temporarily add all nodes as SVG so getBBox captures their labels
      const tempG = gRoot.append("g").attr("class", "temp-fit-nodes");
      regularNodes.forEach(n => {
        const g = tempG.append("g").attr("transform", `translate(${n.x},${n.y})`);
        g.append("circle").attr("r", n.dangling ? DANGLE_R : NODE_R);
        const short = n.id.includes('.') ? n.id.split('.').slice(1).join('.') : n.id;
        const label = short.length > 25 ? short.slice(0, 22) + '...' : short;
        g.append("text").attr("dx", (n.dangling ? DANGLE_R : NODE_R) + 4).attr("dy", 3)
          .attr("font-size", n.dangling ? "7px" : "8px").text(label);
      });
      const bounds = gRoot.node().getBBox();
      tempG.remove();

      if (bounds.width > 0 && bounds.height > 0) {
        const fitW = width;
        const scale = Math.min(fitW / (bounds.width + 160), height / (bounds.height + 160), 1);
        const tx = (fitW - bounds.width * scale) / 2 - bounds.x * scale;
        const ty = (height - bounds.height * scale) / 2 - bounds.y * scale;
        svg.transition().duration(800).call(
          zoomBehavior.transform, d3.zoomIdentity.translate(tx, ty).scale(scale)
        );
      }
    });
  });
}
