/* @ds-bundle: {"format":4,"namespace":"ZerooneDOTSAIDesignSystem_94ab84","components":[{"name":"Navbar","sourcePath":"ui_kits/platform/Navbar.jsx"},{"name":"DotMark","sourcePath":"ui_kits/platform/Sidebar.jsx"},{"name":"Sidebar","sourcePath":"ui_kits/platform/Sidebar.jsx"},{"name":"Eyebrow","sourcePath":"ui_kits/platform/primitives.jsx"},{"name":"Display","sourcePath":"ui_kits/platform/primitives.jsx"},{"name":"Button","sourcePath":"ui_kits/platform/primitives.jsx"},{"name":"Input","sourcePath":"ui_kits/platform/primitives.jsx"},{"name":"Badge","sourcePath":"ui_kits/platform/primitives.jsx"},{"name":"Card","sourcePath":"ui_kits/platform/primitives.jsx"},{"name":"StatCard","sourcePath":"ui_kits/platform/primitives.jsx"},{"name":"Alert","sourcePath":"ui_kits/platform/primitives.jsx"},{"name":"Avatar","sourcePath":"ui_kits/platform/primitives.jsx"}],"sourceHashes":{"explorations/design-canvas.jsx":"5d0e39003628","explorations/logo-intro-variations.jsx":"af05a553b522","explorations/pagebreak-variations.jsx":"d598509c65c8","explorations/pagenav-variations.jsx":"bfc63a3c8aeb","explorations/scrollfuse-variations.jsx":"522dbcd1e9a8","explorations/sidebar-variations.jsx":"110dc333f840","ui_kits/mobile/MobileScreens.jsx":"732455edb275","ui_kits/mobile/design-canvas.jsx":"5d0e39003628","ui_kits/mobile/ios-frame.jsx":"8400a584d7c0","ui_kits/platform/Navbar.jsx":"6e235b1fcba8","ui_kits/platform/Pages.jsx":"293148a2d7e7","ui_kits/platform/Sidebar.jsx":"d22e02cb1205","ui_kits/platform/primitives.jsx":"714385317269"},"inlinedExternals":[],"unexposedExports":[]} */

(() => {

const __ds_ns = (window.ZerooneDOTSAIDesignSystem_94ab84 = window.ZerooneDOTSAIDesignSystem_94ab84 || {});

const __ds_scope = {};

(__ds_ns.__errors = __ds_ns.__errors || []);

// explorations/design-canvas.jsx
try { (() => {
// DesignCanvas.jsx — Figma-ish design canvas wrapper
// Warm gray grid bg + Sections + Artboards + PostIt notes.
// Artboards are reorderable (grip-drag), labels/titles are inline-editable,
// and any artboard can be opened in a fullscreen focus overlay (←/→/Esc).
// State persists to a .design-canvas.state.json sidecar via the host
// bridge. No assets, no deps.
//
// Usage:
//   <DesignCanvas>
//     <DCSection id="onboarding" title="Onboarding" subtitle="First-run variants">
//       <DCArtboard id="a" label="A · Dusk" width={260} height={480}>…</DCArtboard>
//       <DCArtboard id="b" label="B · Minimal" width={260} height={480}>…</DCArtboard>
//     </DCSection>
//   </DesignCanvas>

const DC = {
  bg: '#f0eee9',
  grid: 'rgba(0,0,0,0.06)',
  label: 'rgba(60,50,40,0.7)',
  title: 'rgba(40,30,20,0.85)',
  subtitle: 'rgba(60,50,40,0.6)',
  postitBg: '#fef4a8',
  postitText: '#5a4a2a',
  font: '-apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif'
};

// One-time CSS injection (classes are dc-prefixed so they don't collide with
// the hosted design's own styles).
if (typeof document !== 'undefined' && !document.getElementById('dc-styles')) {
  const s = document.createElement('style');
  s.id = 'dc-styles';
  s.textContent = ['.dc-editable{cursor:text;outline:none;white-space:nowrap;border-radius:3px;padding:0 2px;margin:0 -2px}', '.dc-editable:focus{background:#fff;box-shadow:0 0 0 1.5px #c96442}', '[data-dc-slot]{transition:transform .18s cubic-bezier(.2,.7,.3,1)}', '[data-dc-slot].dc-dragging{transition:none;z-index:10;pointer-events:none}', '[data-dc-slot].dc-dragging .dc-card{box-shadow:0 12px 40px rgba(0,0,0,.25),0 0 0 2px #c96442;transform:scale(1.02)}', '.dc-card{transition:box-shadow .15s,transform .15s}', '.dc-card *{scrollbar-width:none}', '.dc-card *::-webkit-scrollbar{display:none}', '.dc-labelrow{display:flex;align-items:center;gap:4px;height:24px}', '.dc-grip{cursor:grab;display:flex;align-items:center;padding:5px 4px;border-radius:4px;transition:background .12s}', '.dc-grip:hover{background:rgba(0,0,0,.08)}', '.dc-grip:active{cursor:grabbing}', '.dc-labeltext{cursor:pointer;border-radius:4px;padding:3px 6px;display:flex;align-items:center;transition:background .12s}', '.dc-labeltext:hover{background:rgba(0,0,0,.05)}', '.dc-expand{position:absolute;bottom:100%;right:0;margin-bottom:5px;z-index:2;opacity:0;transition:opacity .12s,background .12s;', '  width:22px;height:22px;border-radius:5px;border:none;cursor:pointer;padding:0;', '  background:transparent;color:rgba(60,50,40,.7);display:flex;align-items:center;justify-content:center}', '.dc-expand:hover{background:rgba(0,0,0,.06);color:#2a251f}', '[data-dc-slot]:hover .dc-expand{opacity:1}'].join('\n');
  document.head.appendChild(s);
}
const DCCtx = React.createContext(null);

// ─────────────────────────────────────────────────────────────
// DesignCanvas — stateful wrapper around the pan/zoom viewport.
// Owns runtime state (per-section order, renamed titles/labels, focused
// artboard). Order/titles/labels persist to a .design-canvas.state.json
// sidecar next to the HTML. Reads go via plain fetch() so the saved
// arrangement is visible anywhere the HTML + sidecar are served together
// (omelette preview, direct link, downloaded zip). Writes go through the
// host's window.omelette bridge — editing requires the omelette runtime.
// Focus is ephemeral.
// ─────────────────────────────────────────────────────────────
const DC_STATE_FILE = '.design-canvas.state.json';
function DesignCanvas({
  children,
  minScale,
  maxScale,
  style
}) {
  const [state, setState] = React.useState({
    sections: {},
    focus: null
  });
  // Hold rendering until the sidecar read settles so the saved order/titles
  // appear on first paint (no source-order flash). didRead gates writes until
  // the read settles so the empty initial state can't clobber a slow read;
  // skipNextWrite suppresses the one echo-write that would otherwise follow
  // hydration.
  const [ready, setReady] = React.useState(false);
  const didRead = React.useRef(false);
  const skipNextWrite = React.useRef(false);
  React.useEffect(() => {
    let off = false;
    fetch('./' + DC_STATE_FILE).then(r => r.ok ? r.json() : null).then(saved => {
      if (off || !saved || !saved.sections) return;
      skipNextWrite.current = true;
      setState(s => ({
        ...s,
        sections: saved.sections
      }));
    }).catch(() => {}).finally(() => {
      didRead.current = true;
      if (!off) setReady(true);
    });
    const t = setTimeout(() => {
      if (!off) setReady(true);
    }, 150);
    return () => {
      off = true;
      clearTimeout(t);
    };
  }, []);
  React.useEffect(() => {
    if (!didRead.current) return;
    if (skipNextWrite.current) {
      skipNextWrite.current = false;
      return;
    }
    const t = setTimeout(() => {
      window.omelette?.writeFile(DC_STATE_FILE, JSON.stringify({
        sections: state.sections
      })).catch(() => {});
    }, 250);
    return () => clearTimeout(t);
  }, [state.sections]);

  // Build registries synchronously from children so FocusOverlay can read
  // them in the same render. Only direct DCSection > DCArtboard children are
  // walked — wrapping them in other elements opts out of focus/reorder.
  const registry = {}; // slotId -> { sectionId, artboard }
  const sectionMeta = {}; // sectionId -> { title, subtitle, slotIds[] }
  const sectionOrder = [];
  React.Children.forEach(children, sec => {
    if (!sec || sec.type !== DCSection) return;
    const sid = sec.props.id ?? sec.props.title;
    if (!sid) return;
    sectionOrder.push(sid);
    const persisted = state.sections[sid] || {};
    const srcIds = [];
    React.Children.forEach(sec.props.children, ab => {
      if (!ab || ab.type !== DCArtboard) return;
      const aid = ab.props.id ?? ab.props.label;
      if (!aid) return;
      registry[`${sid}/${aid}`] = {
        sectionId: sid,
        artboard: ab
      };
      srcIds.push(aid);
    });
    const kept = (persisted.order || []).filter(k => srcIds.includes(k));
    sectionMeta[sid] = {
      title: persisted.title ?? sec.props.title,
      subtitle: sec.props.subtitle,
      slotIds: [...kept, ...srcIds.filter(k => !kept.includes(k))]
    };
  });
  const api = React.useMemo(() => ({
    state,
    section: id => state.sections[id] || {},
    patchSection: (id, p) => setState(s => ({
      ...s,
      sections: {
        ...s.sections,
        [id]: {
          ...s.sections[id],
          ...(typeof p === 'function' ? p(s.sections[id] || {}) : p)
        }
      }
    })),
    setFocus: slotId => setState(s => ({
      ...s,
      focus: slotId
    }))
  }), [state]);

  // Esc exits focus; any outside pointerdown commits an in-progress rename.
  React.useEffect(() => {
    const onKey = e => {
      if (e.key === 'Escape') api.setFocus(null);
    };
    const onPd = e => {
      const ae = document.activeElement;
      if (ae && ae.isContentEditable && !ae.contains(e.target)) ae.blur();
    };
    document.addEventListener('keydown', onKey);
    document.addEventListener('pointerdown', onPd, true);
    return () => {
      document.removeEventListener('keydown', onKey);
      document.removeEventListener('pointerdown', onPd, true);
    };
  }, [api]);
  return /*#__PURE__*/React.createElement(DCCtx.Provider, {
    value: api
  }, /*#__PURE__*/React.createElement(DCViewport, {
    minScale: minScale,
    maxScale: maxScale,
    style: style
  }, ready && children), state.focus && registry[state.focus] && /*#__PURE__*/React.createElement(DCFocusOverlay, {
    entry: registry[state.focus],
    sectionMeta: sectionMeta,
    sectionOrder: sectionOrder
  }));
}

// ─────────────────────────────────────────────────────────────
// DCViewport — transform-based pan/zoom (internal)
//
// Input mapping (Figma-style):
//   • trackpad pinch  → zoom   (ctrlKey wheel; Safari gesture* events)
//   • trackpad scroll → pan    (two-finger)
//   • mouse wheel     → zoom   (notched; distinguished from trackpad scroll)
//   • middle-drag / primary-drag-on-bg → pan
//
// Transform state lives in a ref and is written straight to the DOM
// (translate3d + will-change) so wheel ticks don't go through React —
// keeps pans at 60fps on dense canvases.
// ─────────────────────────────────────────────────────────────
function DCViewport({
  children,
  minScale = 0.1,
  maxScale = 8,
  style = {}
}) {
  const vpRef = React.useRef(null);
  const worldRef = React.useRef(null);
  const tf = React.useRef({
    x: 0,
    y: 0,
    scale: 1
  });
  const apply = React.useCallback(() => {
    const {
      x,
      y,
      scale
    } = tf.current;
    const el = worldRef.current;
    if (el) el.style.transform = `translate3d(${x}px, ${y}px, 0) scale(${scale})`;
  }, []);
  React.useEffect(() => {
    const vp = vpRef.current;
    if (!vp) return;
    const zoomAt = (cx, cy, factor) => {
      const r = vp.getBoundingClientRect();
      const px = cx - r.left,
        py = cy - r.top;
      const t = tf.current;
      const next = Math.min(maxScale, Math.max(minScale, t.scale * factor));
      const k = next / t.scale;
      // keep the world point under the cursor fixed
      t.x = px - (px - t.x) * k;
      t.y = py - (py - t.y) * k;
      t.scale = next;
      apply();
    };

    // Mouse-wheel vs trackpad-scroll heuristic. A physical wheel sends
    // line-mode deltas (Firefox) or large integer pixel deltas with no X
    // component (Chrome/Safari, typically multiples of 100/120). Trackpad
    // two-finger scroll sends small/fractional pixel deltas, often with
    // non-zero deltaX. ctrlKey is set by the browser for trackpad pinch.
    const isMouseWheel = e => e.deltaMode !== 0 || e.deltaX === 0 && Number.isInteger(e.deltaY) && Math.abs(e.deltaY) >= 40;
    const onWheel = e => {
      e.preventDefault();
      if (isGesturing) return; // Safari: gesture* owns the pinch — discard concurrent wheels
      if (e.ctrlKey) {
        // trackpad pinch (or explicit ctrl+wheel)
        zoomAt(e.clientX, e.clientY, Math.exp(-e.deltaY * 0.01));
      } else if (isMouseWheel(e)) {
        // notched mouse wheel — fixed-ratio step per click
        zoomAt(e.clientX, e.clientY, Math.exp(-Math.sign(e.deltaY) * 0.18));
      } else {
        // trackpad two-finger scroll — pan
        tf.current.x -= e.deltaX;
        tf.current.y -= e.deltaY;
        apply();
      }
    };

    // Safari sends native gesture* events for trackpad pinch with a smooth
    // e.scale; preferring these over the ctrl+wheel fallback gives a much
    // better feel there. No-ops on other browsers. Safari also fires
    // ctrlKey wheel events during the same pinch — isGesturing makes
    // onWheel drop those entirely so they neither zoom nor pan.
    let gsBase = 1;
    let isGesturing = false;
    const onGestureStart = e => {
      e.preventDefault();
      isGesturing = true;
      gsBase = tf.current.scale;
    };
    const onGestureChange = e => {
      e.preventDefault();
      zoomAt(e.clientX, e.clientY, gsBase * e.scale / tf.current.scale);
    };
    const onGestureEnd = e => {
      e.preventDefault();
      isGesturing = false;
    };

    // Drag-pan: middle button anywhere, or primary button on canvas
    // background (anything that isn't an artboard or an inline editor).
    let drag = null;
    const onPointerDown = e => {
      const onBg = !e.target.closest('[data-dc-slot], .dc-editable');
      if (!(e.button === 1 || e.button === 0 && onBg)) return;
      e.preventDefault();
      vp.setPointerCapture(e.pointerId);
      drag = {
        id: e.pointerId,
        lx: e.clientX,
        ly: e.clientY
      };
      vp.style.cursor = 'grabbing';
    };
    const onPointerMove = e => {
      if (!drag || e.pointerId !== drag.id) return;
      tf.current.x += e.clientX - drag.lx;
      tf.current.y += e.clientY - drag.ly;
      drag.lx = e.clientX;
      drag.ly = e.clientY;
      apply();
    };
    const onPointerUp = e => {
      if (!drag || e.pointerId !== drag.id) return;
      vp.releasePointerCapture(e.pointerId);
      drag = null;
      vp.style.cursor = '';
    };
    vp.addEventListener('wheel', onWheel, {
      passive: false
    });
    vp.addEventListener('gesturestart', onGestureStart, {
      passive: false
    });
    vp.addEventListener('gesturechange', onGestureChange, {
      passive: false
    });
    vp.addEventListener('gestureend', onGestureEnd, {
      passive: false
    });
    vp.addEventListener('pointerdown', onPointerDown);
    vp.addEventListener('pointermove', onPointerMove);
    vp.addEventListener('pointerup', onPointerUp);
    vp.addEventListener('pointercancel', onPointerUp);
    return () => {
      vp.removeEventListener('wheel', onWheel);
      vp.removeEventListener('gesturestart', onGestureStart);
      vp.removeEventListener('gesturechange', onGestureChange);
      vp.removeEventListener('gestureend', onGestureEnd);
      vp.removeEventListener('pointerdown', onPointerDown);
      vp.removeEventListener('pointermove', onPointerMove);
      vp.removeEventListener('pointerup', onPointerUp);
      vp.removeEventListener('pointercancel', onPointerUp);
    };
  }, [apply, minScale, maxScale]);
  const gridSvg = `url("data:image/svg+xml,%3Csvg width='120' height='120' xmlns='http://www.w3.org/2000/svg'%3E%3Cpath d='M120 0H0v120' fill='none' stroke='${encodeURIComponent(DC.grid)}' stroke-width='1'/%3E%3C/svg%3E")`;
  return /*#__PURE__*/React.createElement("div", {
    ref: vpRef,
    className: "design-canvas",
    style: {
      height: '100vh',
      width: '100vw',
      background: DC.bg,
      overflow: 'hidden',
      overscrollBehavior: 'none',
      touchAction: 'none',
      position: 'relative',
      fontFamily: DC.font,
      boxSizing: 'border-box',
      ...style
    }
  }, /*#__PURE__*/React.createElement("div", {
    ref: worldRef,
    style: {
      position: 'absolute',
      top: 0,
      left: 0,
      transformOrigin: '0 0',
      willChange: 'transform',
      width: 'max-content',
      minWidth: '100%',
      minHeight: '100%',
      padding: '60px 0 80px'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      inset: -6000,
      backgroundImage: gridSvg,
      backgroundSize: '120px 120px',
      pointerEvents: 'none',
      zIndex: -1
    }
  }), children));
}

// ─────────────────────────────────────────────────────────────
// DCSection — editable title + h-row of artboards in persisted order
// ─────────────────────────────────────────────────────────────
function DCSection({
  id,
  title,
  subtitle,
  children,
  gap = 48
}) {
  const ctx = React.useContext(DCCtx);
  const sid = id ?? title;
  const all = React.Children.toArray(children);
  const artboards = all.filter(c => c && c.type === DCArtboard);
  const rest = all.filter(c => !(c && c.type === DCArtboard));
  const srcOrder = artboards.map(a => a.props.id ?? a.props.label);
  const sec = ctx && sid && ctx.section(sid) || {};
  const order = React.useMemo(() => {
    const kept = (sec.order || []).filter(k => srcOrder.includes(k));
    return [...kept, ...srcOrder.filter(k => !kept.includes(k))];
  }, [sec.order, srcOrder.join('|')]);
  const byId = Object.fromEntries(artboards.map(a => [a.props.id ?? a.props.label, a]));
  return /*#__PURE__*/React.createElement("div", {
    "data-dc-section": sid,
    style: {
      marginBottom: 80,
      position: 'relative'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      padding: '0 60px 56px'
    }
  }, /*#__PURE__*/React.createElement(DCEditable, {
    tag: "div",
    value: sec.title ?? title,
    onChange: v => ctx && sid && ctx.patchSection(sid, {
      title: v
    }),
    style: {
      fontSize: 28,
      fontWeight: 600,
      color: DC.title,
      letterSpacing: -0.4,
      marginBottom: 6,
      display: 'inline-block'
    }
  }), subtitle && /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 16,
      color: DC.subtitle
    }
  }, subtitle)), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap,
      padding: '0 60px',
      alignItems: 'flex-start',
      width: 'max-content'
    }
  }, order.map(k => /*#__PURE__*/React.createElement(DCArtboardFrame, {
    key: k,
    sectionId: sid,
    artboard: byId[k],
    order: order,
    label: (sec.labels || {})[k] ?? byId[k].props.label,
    onRename: v => ctx && ctx.patchSection(sid, x => ({
      labels: {
        ...x.labels,
        [k]: v
      }
    })),
    onReorder: next => ctx && ctx.patchSection(sid, {
      order: next
    }),
    onFocus: () => ctx && ctx.setFocus(`${sid}/${k}`)
  }))), rest);
}

// DCArtboard — marker; rendered by DCArtboardFrame via DCSection.
function DCArtboard() {
  return null;
}
function DCArtboardFrame({
  sectionId,
  artboard,
  label,
  order,
  onRename,
  onReorder,
  onFocus
}) {
  const {
    id: rawId,
    label: rawLabel,
    width = 260,
    height = 480,
    children,
    style = {}
  } = artboard.props;
  const id = rawId ?? rawLabel;
  const ref = React.useRef(null);

  // Live drag-reorder: dragged card sticks to cursor; siblings slide into
  // their would-be slots in real time via transforms. DOM order only
  // changes on drop.
  const onGripDown = e => {
    e.preventDefault();
    e.stopPropagation();
    const me = ref.current;
    // translateX is applied in local (pre-scale) space but pointer deltas and
    // getBoundingClientRect().left are screen-space — divide by the viewport's
    // current scale so the dragged card tracks the cursor at any zoom level.
    const scale = me.getBoundingClientRect().width / me.offsetWidth || 1;
    const peers = Array.from(document.querySelectorAll(`[data-dc-section="${sectionId}"] [data-dc-slot]`));
    const homes = peers.map(el => ({
      el,
      id: el.dataset.dcSlot,
      x: el.getBoundingClientRect().left
    }));
    const slotXs = homes.map(h => h.x);
    const startIdx = order.indexOf(id);
    const startX = e.clientX;
    let liveOrder = order.slice();
    me.classList.add('dc-dragging');
    const layout = () => {
      for (const h of homes) {
        if (h.id === id) continue;
        const slot = liveOrder.indexOf(h.id);
        h.el.style.transform = `translateX(${(slotXs[slot] - h.x) / scale}px)`;
      }
    };
    const move = ev => {
      const dx = ev.clientX - startX;
      me.style.transform = `translateX(${dx / scale}px)`;
      const cur = homes[startIdx].x + dx;
      let nearest = 0,
        best = Infinity;
      for (let i = 0; i < slotXs.length; i++) {
        const d = Math.abs(slotXs[i] - cur);
        if (d < best) {
          best = d;
          nearest = i;
        }
      }
      if (liveOrder.indexOf(id) !== nearest) {
        liveOrder = order.filter(k => k !== id);
        liveOrder.splice(nearest, 0, id);
        layout();
      }
    };
    const up = () => {
      document.removeEventListener('pointermove', move);
      document.removeEventListener('pointerup', up);
      const finalSlot = liveOrder.indexOf(id);
      me.classList.remove('dc-dragging');
      me.style.transform = `translateX(${(slotXs[finalSlot] - homes[startIdx].x) / scale}px)`;
      // After the settle transition, kill transitions + clear transforms +
      // commit the reorder in the same frame so there's no visual snap-back.
      setTimeout(() => {
        for (const h of homes) {
          h.el.style.transition = 'none';
          h.el.style.transform = '';
        }
        if (liveOrder.join('|') !== order.join('|')) onReorder(liveOrder);
        requestAnimationFrame(() => requestAnimationFrame(() => {
          for (const h of homes) h.el.style.transition = '';
        }));
      }, 180);
    };
    document.addEventListener('pointermove', move);
    document.addEventListener('pointerup', up);
  };
  return /*#__PURE__*/React.createElement("div", {
    ref: ref,
    "data-dc-slot": id,
    style: {
      position: 'relative',
      flexShrink: 0
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "dc-labelrow",
    style: {
      position: 'absolute',
      bottom: '100%',
      left: -4,
      marginBottom: 4,
      color: DC.label
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "dc-grip",
    onPointerDown: onGripDown,
    title: "Drag to reorder"
  }, /*#__PURE__*/React.createElement("svg", {
    width: "9",
    height: "13",
    viewBox: "0 0 9 13",
    fill: "currentColor"
  }, /*#__PURE__*/React.createElement("circle", {
    cx: "2",
    cy: "2",
    r: "1.1"
  }), /*#__PURE__*/React.createElement("circle", {
    cx: "7",
    cy: "2",
    r: "1.1"
  }), /*#__PURE__*/React.createElement("circle", {
    cx: "2",
    cy: "6.5",
    r: "1.1"
  }), /*#__PURE__*/React.createElement("circle", {
    cx: "7",
    cy: "6.5",
    r: "1.1"
  }), /*#__PURE__*/React.createElement("circle", {
    cx: "2",
    cy: "11",
    r: "1.1"
  }), /*#__PURE__*/React.createElement("circle", {
    cx: "7",
    cy: "11",
    r: "1.1"
  }))), /*#__PURE__*/React.createElement("div", {
    className: "dc-labeltext",
    onClick: onFocus,
    title: "Click to focus"
  }, /*#__PURE__*/React.createElement(DCEditable, {
    value: label,
    onChange: onRename,
    onClick: e => e.stopPropagation(),
    style: {
      fontSize: 15,
      fontWeight: 500,
      color: DC.label,
      lineHeight: 1
    }
  }))), /*#__PURE__*/React.createElement("button", {
    className: "dc-expand",
    onClick: onFocus,
    onPointerDown: e => e.stopPropagation(),
    title: "Focus"
  }, /*#__PURE__*/React.createElement("svg", {
    width: "12",
    height: "12",
    viewBox: "0 0 12 12",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: "1.6",
    strokeLinecap: "round"
  }, /*#__PURE__*/React.createElement("path", {
    d: "M7 1h4v4M5 11H1V7M11 1L7.5 4.5M1 11l3.5-3.5"
  }))), /*#__PURE__*/React.createElement("div", {
    className: "dc-card",
    style: {
      borderRadius: 2,
      boxShadow: '0 1px 3px rgba(0,0,0,.08),0 4px 16px rgba(0,0,0,.06)',
      overflow: 'hidden',
      width,
      height,
      background: '#fff',
      ...style
    }
  }, children || /*#__PURE__*/React.createElement("div", {
    style: {
      height: '100%',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      color: '#bbb',
      fontSize: 13,
      fontFamily: DC.font
    }
  }, id)));
}

// Inline rename — commits on blur or Enter.
function DCEditable({
  value,
  onChange,
  style,
  tag = 'span',
  onClick
}) {
  const T = tag;
  return /*#__PURE__*/React.createElement(T, {
    className: "dc-editable",
    contentEditable: true,
    suppressContentEditableWarning: true,
    onClick: onClick,
    onPointerDown: e => e.stopPropagation(),
    onBlur: e => onChange && onChange(e.currentTarget.textContent),
    onKeyDown: e => {
      if (e.key === 'Enter') {
        e.preventDefault();
        e.currentTarget.blur();
      }
    },
    style: style
  }, value);
}

// ─────────────────────────────────────────────────────────────
// Focus mode — overlay one artboard; ←/→ within section, ↑/↓ across
// sections, Esc or backdrop click to exit.
// ─────────────────────────────────────────────────────────────
function DCFocusOverlay({
  entry,
  sectionMeta,
  sectionOrder
}) {
  const ctx = React.useContext(DCCtx);
  const {
    sectionId,
    artboard
  } = entry;
  const sec = ctx.section(sectionId);
  const meta = sectionMeta[sectionId];
  const peers = meta.slotIds;
  const aid = artboard.props.id ?? artboard.props.label;
  const idx = peers.indexOf(aid);
  const secIdx = sectionOrder.indexOf(sectionId);
  const go = d => {
    const n = peers[(idx + d + peers.length) % peers.length];
    if (n) ctx.setFocus(`${sectionId}/${n}`);
  };
  const goSection = d => {
    const ns = sectionOrder[(secIdx + d + sectionOrder.length) % sectionOrder.length];
    const first = sectionMeta[ns] && sectionMeta[ns].slotIds[0];
    if (first) ctx.setFocus(`${ns}/${first}`);
  };
  React.useEffect(() => {
    const k = e => {
      if (e.key === 'ArrowLeft') {
        e.preventDefault();
        go(-1);
      }
      if (e.key === 'ArrowRight') {
        e.preventDefault();
        go(1);
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault();
        goSection(-1);
      }
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        goSection(1);
      }
    };
    document.addEventListener('keydown', k);
    return () => document.removeEventListener('keydown', k);
  });
  const {
    width = 260,
    height = 480,
    children
  } = artboard.props;
  const [vp, setVp] = React.useState({
    w: window.innerWidth,
    h: window.innerHeight
  });
  React.useEffect(() => {
    const r = () => setVp({
      w: window.innerWidth,
      h: window.innerHeight
    });
    window.addEventListener('resize', r);
    return () => window.removeEventListener('resize', r);
  }, []);
  const scale = Math.max(0.1, Math.min((vp.w - 200) / width, (vp.h - 260) / height, 2));
  const [ddOpen, setDd] = React.useState(false);
  const Arrow = ({
    dir,
    onClick
  }) => /*#__PURE__*/React.createElement("button", {
    onClick: e => {
      e.stopPropagation();
      onClick();
    },
    style: {
      position: 'absolute',
      top: '50%',
      [dir]: 28,
      transform: 'translateY(-50%)',
      border: 'none',
      background: 'rgba(255,255,255,.08)',
      color: 'rgba(255,255,255,.9)',
      width: 44,
      height: 44,
      borderRadius: 22,
      fontSize: 18,
      cursor: 'pointer',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      transition: 'background .15s'
    },
    onMouseEnter: e => e.currentTarget.style.background = 'rgba(255,255,255,.18)',
    onMouseLeave: e => e.currentTarget.style.background = 'rgba(255,255,255,.08)'
  }, /*#__PURE__*/React.createElement("svg", {
    width: "18",
    height: "18",
    viewBox: "0 0 18 18",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: "2",
    strokeLinecap: "round"
  }, /*#__PURE__*/React.createElement("path", {
    d: dir === 'left' ? 'M11 3L5 9l6 6' : 'M7 3l6 6-6 6'
  })));

  // Portal to body so position:fixed is the real viewport regardless of any
  // transform on DesignCanvas's ancestors (including the canvas zoom itself).
  return ReactDOM.createPortal(/*#__PURE__*/React.createElement("div", {
    onClick: () => ctx.setFocus(null),
    onWheel: e => e.preventDefault(),
    style: {
      position: 'fixed',
      inset: 0,
      zIndex: 100,
      background: 'rgba(24,20,16,.6)',
      backdropFilter: 'blur(14px)',
      fontFamily: DC.font,
      color: '#fff'
    }
  }, /*#__PURE__*/React.createElement("div", {
    onClick: e => e.stopPropagation(),
    style: {
      position: 'absolute',
      top: 0,
      left: 0,
      right: 0,
      height: 72,
      display: 'flex',
      alignItems: 'flex-start',
      padding: '16px 20px 0',
      gap: 16
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'relative'
    }
  }, /*#__PURE__*/React.createElement("button", {
    onClick: () => setDd(o => !o),
    style: {
      border: 'none',
      background: 'transparent',
      color: '#fff',
      cursor: 'pointer',
      padding: '6px 8px',
      borderRadius: 6,
      textAlign: 'left',
      fontFamily: 'inherit'
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 8
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 18,
      fontWeight: 600,
      letterSpacing: -0.3
    }
  }, meta.title), /*#__PURE__*/React.createElement("svg", {
    width: "11",
    height: "11",
    viewBox: "0 0 11 11",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: "1.8",
    strokeLinecap: "round",
    style: {
      opacity: .7
    }
  }, /*#__PURE__*/React.createElement("path", {
    d: "M2 4l3.5 3.5L9 4"
  }))), meta.subtitle && /*#__PURE__*/React.createElement("span", {
    style: {
      display: 'block',
      fontSize: 13,
      opacity: .6,
      fontWeight: 400,
      marginTop: 2
    }
  }, meta.subtitle)), ddOpen && /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      top: '100%',
      left: 0,
      marginTop: 4,
      background: '#2a251f',
      borderRadius: 8,
      boxShadow: '0 8px 32px rgba(0,0,0,.4)',
      padding: 4,
      minWidth: 200,
      zIndex: 10
    }
  }, sectionOrder.map(sid => /*#__PURE__*/React.createElement("button", {
    key: sid,
    onClick: () => {
      setDd(false);
      const f = sectionMeta[sid].slotIds[0];
      if (f) ctx.setFocus(`${sid}/${f}`);
    },
    style: {
      display: 'block',
      width: '100%',
      textAlign: 'left',
      border: 'none',
      cursor: 'pointer',
      background: sid === sectionId ? 'rgba(255,255,255,.1)' : 'transparent',
      color: '#fff',
      padding: '8px 12px',
      borderRadius: 5,
      fontSize: 14,
      fontWeight: sid === sectionId ? 600 : 400,
      fontFamily: 'inherit'
    }
  }, sectionMeta[sid].title)))), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1
    }
  }), /*#__PURE__*/React.createElement("button", {
    onClick: () => ctx.setFocus(null),
    onMouseEnter: e => e.currentTarget.style.background = 'rgba(255,255,255,.12)',
    onMouseLeave: e => e.currentTarget.style.background = 'transparent',
    style: {
      border: 'none',
      background: 'transparent',
      color: 'rgba(255,255,255,.7)',
      width: 32,
      height: 32,
      borderRadius: 16,
      fontSize: 20,
      cursor: 'pointer',
      lineHeight: 1,
      transition: 'background .12s'
    }
  }, "\xD7")), /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      top: 64,
      bottom: 56,
      left: 100,
      right: 100,
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      justifyContent: 'center',
      gap: 16
    }
  }, /*#__PURE__*/React.createElement("div", {
    onClick: e => e.stopPropagation(),
    style: {
      width: width * scale,
      height: height * scale,
      position: 'relative'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      width,
      height,
      transform: `scale(${scale})`,
      transformOrigin: 'top left',
      background: '#fff',
      borderRadius: 2,
      overflow: 'hidden',
      boxShadow: '0 20px 80px rgba(0,0,0,.4)'
    }
  }, children || /*#__PURE__*/React.createElement("div", {
    style: {
      height: '100%',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      color: '#bbb'
    }
  }, aid))), /*#__PURE__*/React.createElement("div", {
    onClick: e => e.stopPropagation(),
    style: {
      fontSize: 14,
      fontWeight: 500,
      opacity: .85,
      textAlign: 'center'
    }
  }, (sec.labels || {})[aid] ?? artboard.props.label, /*#__PURE__*/React.createElement("span", {
    style: {
      opacity: .5,
      marginLeft: 10,
      fontVariantNumeric: 'tabular-nums'
    }
  }, idx + 1, " / ", peers.length))), /*#__PURE__*/React.createElement(Arrow, {
    dir: "left",
    onClick: () => go(-1)
  }), /*#__PURE__*/React.createElement(Arrow, {
    dir: "right",
    onClick: () => go(1)
  }), /*#__PURE__*/React.createElement("div", {
    onClick: e => e.stopPropagation(),
    style: {
      position: 'absolute',
      bottom: 20,
      left: '50%',
      transform: 'translateX(-50%)',
      display: 'flex',
      gap: 8
    }
  }, peers.map((p, i) => /*#__PURE__*/React.createElement("button", {
    key: p,
    onClick: () => ctx.setFocus(`${sectionId}/${p}`),
    style: {
      border: 'none',
      padding: 0,
      cursor: 'pointer',
      width: 6,
      height: 6,
      borderRadius: 3,
      background: i === idx ? '#fff' : 'rgba(255,255,255,.3)'
    }
  })))), document.body);
}

// ─────────────────────────────────────────────────────────────
// Post-it — absolute-positioned sticky note
// ─────────────────────────────────────────────────────────────
function DCPostIt({
  children,
  top,
  left,
  right,
  bottom,
  rotate = -2,
  width = 180
}) {
  return /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      top,
      left,
      right,
      bottom,
      width,
      background: DC.postitBg,
      padding: '14px 16px',
      fontFamily: '"Comic Sans MS", "Marker Felt", "Segoe Print", cursive',
      fontSize: 14,
      lineHeight: 1.4,
      color: DC.postitText,
      boxShadow: '0 2px 8px rgba(0,0,0,0.12), 0 1px 2px rgba(0,0,0,0.08)',
      transform: `rotate(${rotate}deg)`,
      zIndex: 5
    }
  }, children);
}
Object.assign(window, {
  DesignCanvas,
  DCSection,
  DCArtboard,
  DCPostIt
});
})(); } catch (e) { __ds_ns.__errors.push({ path: "explorations/design-canvas.jsx", error: String((e && e.message) || e) }); }

// explorations/logo-intro-variations.jsx
try { (() => {
// Logo Intro Animations — 2-3s reveals on landing
// All render the 01·DOTS·AI mark. Each variant self-loops every ~3.5s.

if (typeof document !== 'undefined' && !document.getElementById('lg-styles')) {
  const s = document.createElement('style');
  s.id = 'lg-styles';
  s.textContent = `
    .lg-root{font-family:'Satoshi',system-ui,sans-serif;width:100%;height:100%;position:relative;overflow:hidden;display:flex;align-items:center;justify-content:center;background:#FDFCFA}
    .lg-label{position:absolute;top:10px;left:14px;font-family:'JetBrains Mono',monospace;font-size:9.5px;letter-spacing:2px;text-transform:uppercase;color:#918D82;z-index:5}
    .lg-replay{position:absolute;top:10px;right:10px;padding:4px 10px;border-radius:99px;border:1px solid rgba(25,25,36,.12);background:#FDFCFA;font-family:'JetBrains Mono',monospace;font-size:9px;letter-spacing:1.5px;text-transform:uppercase;cursor:pointer;color:#4A4842;z-index:5}
    .lg-stage{display:flex;align-items:center;gap:10px;font-family:'Chubbo',sans-serif;font-weight:900;font-size:38px;letter-spacing:1px;color:#191924}
    .lg-mono{width:56px;height:56px;border-radius:12px;background:#191924;color:#C8B6FF;display:flex;align-items:center;justify-content:center;font-family:'Chubbo';font-weight:900;font-size:20px}
    @keyframes lgFadeUp{0%{opacity:0;transform:translateY(10px)}100%{opacity:1;transform:none}}
    @keyframes lgScaleIn{0%{opacity:0;transform:scale(.4)}60%{opacity:1;transform:scale(1.06)}100%{transform:scale(1)}}
    @keyframes lgSweep{0%{clip-path:inset(0 100% 0 0)}100%{clip-path:inset(0 0 0 0)}}
    @keyframes lgDotsIn{0%{opacity:0;transform:scale(.2)}70%{opacity:1;transform:scale(1.2)}100%{transform:scale(1)}}
    @keyframes lgRotate{0%{transform:rotate(-180deg);opacity:0}100%{transform:rotate(0);opacity:1}}
    @keyframes lgGlow{0%,100%{box-shadow:0 0 0 rgba(91,63,212,0)}50%{box-shadow:0 0 30px rgba(91,63,212,.6)}}
    @keyframes lgTypewriter{0%{width:0}100%{width:var(--w,100%)}}
    @keyframes lgMorph{0%{border-radius:50%;transform:scale(.3)}100%{border-radius:12px;transform:scale(1)}}
    .lg-char{display:inline-block;animation:lgFadeUp .45s both}
  `;
  document.head.appendChild(s);
}
function useReplay() {
  const [k, setK] = React.useState(0);
  React.useEffect(() => {
    const t = setInterval(() => setK(v => v + 1), 3800);
    return () => clearInterval(t);
  }, []);
  return [k, () => setK(v => v + 1)];
}

// V1 — Dots appear first, then letters slide up one by one
function LGV1() {
  const [k, replay] = useReplay();
  return /*#__PURE__*/React.createElement("div", {
    className: "lg-root"
  }, /*#__PURE__*/React.createElement("div", {
    className: "lg-label"
  }, "V1 \xB7 Letter cascade"), /*#__PURE__*/React.createElement("button", {
    className: "lg-replay",
    onClick: replay
  }, "Replay"), /*#__PURE__*/React.createElement("div", {
    key: k,
    className: "lg-stage"
  }, /*#__PURE__*/React.createElement("div", {
    className: "lg-mono",
    style: {
      animation: 'lgScaleIn .6s cubic-bezier(.2,1.2,.3,1) both'
    }
  }, "01"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: 4
    }
  }, 'DOTS'.split('').map((c, i) => /*#__PURE__*/React.createElement("span", {
    key: i,
    className: "lg-char",
    style: {
      animationDelay: `${.3 + i * .08}s`
    }
  }, c)), /*#__PURE__*/React.createElement("span", {
    className: "lg-char",
    style: {
      animationDelay: '.7s',
      color: '#5B3FD4'
    }
  }, "\xB7"), 'AI'.split('').map((c, i) => /*#__PURE__*/React.createElement("span", {
    key: i,
    className: "lg-char",
    style: {
      animationDelay: `${.78 + i * .08}s`
    }
  }, c)))));
}

// V2 — Morph: circle becomes rounded square, then wordmark sweeps in
function LGV2() {
  const [k, replay] = useReplay();
  return /*#__PURE__*/React.createElement("div", {
    className: "lg-root",
    style: {
      background: '#191924',
      color: '#FDFCFA'
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "lg-label",
    style: {
      color: 'rgba(253,252,250,.5)'
    }
  }, "V2 \xB7 Morph + sweep"), /*#__PURE__*/React.createElement("button", {
    className: "lg-replay",
    onClick: replay,
    style: {
      background: 'transparent',
      color: '#FDFCFA',
      borderColor: 'rgba(253,252,250,.15)'
    }
  }, "Replay"), /*#__PURE__*/React.createElement("div", {
    key: k,
    className: "lg-stage",
    style: {
      color: '#FDFCFA'
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "lg-mono",
    style: {
      animation: 'lgMorph .8s cubic-bezier(.4,0,.2,1) both, lgGlow 2s 1s infinite',
      background: 'linear-gradient(135deg,#5B3FD4,#C8B6FF)',
      color: '#191924'
    }
  }, "01"), /*#__PURE__*/React.createElement("div", {
    style: {
      overflow: 'hidden',
      animation: 'lgSweep .9s .5s cubic-bezier(.4,0,.2,1) both'
    }
  }, "DOTS", /*#__PURE__*/React.createElement("span", {
    style: {
      color: '#C8B6FF'
    }
  }, "\xB7"), "AI")));
}

// V3 — Dots assemble: 4 pillar dots fly in and merge into the mark
function LGV3() {
  const [k, replay] = useReplay();
  const dots = [['#C8B6FF', -80, -40], ['#B8E6D3', 80, -40], ['#FFCDB2', -80, 40], ['#A2D2FF', 80, 40]];
  return /*#__PURE__*/React.createElement("div", {
    className: "lg-root"
  }, /*#__PURE__*/React.createElement("div", {
    className: "lg-label"
  }, "V3 \xB7 Pillar assembly"), /*#__PURE__*/React.createElement("button", {
    className: "lg-replay",
    onClick: replay
  }, "Replay"), /*#__PURE__*/React.createElement("div", {
    key: k,
    style: {
      position: 'relative',
      display: 'flex',
      alignItems: 'center',
      gap: 10
    }
  }, dots.map(([c, x, y], i) => /*#__PURE__*/React.createElement("span", {
    key: i,
    style: {
      position: 'absolute',
      left: 26,
      top: 26,
      width: 14,
      height: 14,
      borderRadius: '50%',
      background: c,
      transform: `translate(${x}px,${y}px)`,
      animation: `lgDotsIn .5s ${i * .08}s both, lgGather .6s ${.8 + i * .04}s forwards`,
      opacity: 0
    }
  })), /*#__PURE__*/React.createElement("style", null, `@keyframes lgGather{to{transform:translate(0,0) scale(.4);opacity:0}}`), /*#__PURE__*/React.createElement("div", {
    className: "lg-mono",
    style: {
      animation: 'lgScaleIn .5s 1.3s cubic-bezier(.2,1.2,.3,1) both',
      opacity: 0
    }
  }, "01"), /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: 'Chubbo',
      fontWeight: 900,
      fontSize: 38,
      letterSpacing: 1,
      animation: 'lgFadeUp .5s 1.5s both',
      opacity: 0
    }
  }, "DOTS", /*#__PURE__*/React.createElement("span", {
    style: {
      color: '#5B3FD4'
    }
  }, "\xB7"), "AI")));
}

// V4 — Typewriter
function LGV4() {
  const [k, replay] = useReplay();
  return /*#__PURE__*/React.createElement("div", {
    className: "lg-root",
    style: {
      background: '#F2F0EC'
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "lg-label"
  }, "V4 \xB7 Typewriter"), /*#__PURE__*/React.createElement("button", {
    className: "lg-replay",
    onClick: replay
  }, "Replay"), /*#__PURE__*/React.createElement("div", {
    key: k,
    style: {
      fontFamily: 'JetBrains Mono,JetBrains Mono,monospace',
      fontSize: 22,
      color: '#191924',
      display: 'flex',
      gap: 6,
      alignItems: 'baseline'
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      color: '#918D82'
    }
  }, ">"), /*#__PURE__*/React.createElement("span", {
    style: {
      overflow: 'hidden',
      whiteSpace: 'nowrap',
      animation: 'lgTypewriter 1.5s steps(15) both',
      '--w': '7ch'
    }
  }, "01\xB7DOTS\xB7AI"), /*#__PURE__*/React.createElement("span", {
    style: {
      display: 'inline-block',
      width: 10,
      height: 22,
      background: '#5B3FD4',
      animation: 'lgBlink 1s 1.6s infinite'
    }
  }), /*#__PURE__*/React.createElement("style", null, `@keyframes lgBlink{50%{opacity:0}}`)));
}

// V5 — Zoom + blur reveal
function LGV5() {
  const [k, replay] = useReplay();
  return /*#__PURE__*/React.createElement("div", {
    className: "lg-root",
    style: {
      background: 'linear-gradient(135deg,#2D1B4E,#191924)',
      color: '#FDFCFA'
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "lg-label",
    style: {
      color: 'rgba(253,252,250,.5)'
    }
  }, "V5 \xB7 Zoom blur reveal"), /*#__PURE__*/React.createElement("button", {
    className: "lg-replay",
    onClick: replay,
    style: {
      background: 'transparent',
      color: '#FDFCFA',
      borderColor: 'rgba(253,252,250,.15)'
    }
  }, "Replay"), /*#__PURE__*/React.createElement("div", {
    key: k,
    className: "lg-stage",
    style: {
      color: '#FDFCFA',
      animation: 'lgZoomBlur 1.6s cubic-bezier(.2,.8,.3,1) both'
    }
  }, /*#__PURE__*/React.createElement("style", null, `@keyframes lgZoomBlur{0%{opacity:0;filter:blur(20px);transform:scale(1.4)}100%{opacity:1;filter:none;transform:scale(1)}}`), /*#__PURE__*/React.createElement("div", {
    className: "lg-mono",
    style: {
      background: 'linear-gradient(135deg,#C8B6FF,#5B3FD4)',
      color: '#191924'
    }
  }, "01"), /*#__PURE__*/React.createElement("div", null, "DOTS", /*#__PURE__*/React.createElement("span", {
    style: {
      color: '#C8B6FF'
    }
  }, "\xB7"), "AI")));
}

// V6 — Counter spin: 00 → 01 roulette
function LGV6() {
  const [k, replay] = useReplay();
  const [num, setNum] = React.useState(0);
  React.useEffect(() => {
    setNum(0);
    let i = 0;
    const timer = setInterval(() => {
      i++;
      setNum(i);
      if (i >= 14) clearInterval(timer);
    }, 70);
    return () => clearInterval(timer);
  }, [k]);
  const display = num < 14 ? String(num).padStart(2, '0') : '01';
  return /*#__PURE__*/React.createElement("div", {
    className: "lg-root"
  }, /*#__PURE__*/React.createElement("div", {
    className: "lg-label"
  }, "V6 \xB7 Counter roulette"), /*#__PURE__*/React.createElement("button", {
    className: "lg-replay",
    onClick: replay
  }, "Replay"), /*#__PURE__*/React.createElement("div", {
    key: k,
    className: "lg-stage"
  }, /*#__PURE__*/React.createElement("div", {
    className: "lg-mono",
    style: {
      animation: 'lgScaleIn .5s both'
    }
  }, display), /*#__PURE__*/React.createElement("div", {
    style: {
      animation: 'lgFadeUp .6s 1.2s both',
      opacity: 0
    }
  }, "DOTS", /*#__PURE__*/React.createElement("span", {
    style: {
      color: '#5B3FD4'
    }
  }, "\xB7"), "AI")));
}
window.LogoIntroVariations = [{
  id: 'lg1',
  label: 'V1 · Letter cascade',
  C: LGV1
}, {
  id: 'lg2',
  label: 'V2 · Morph + sweep',
  C: LGV2
}, {
  id: 'lg3',
  label: 'V3 · Pillar assembly',
  C: LGV3
}, {
  id: 'lg4',
  label: 'V4 · Typewriter',
  C: LGV4
}, {
  id: 'lg5',
  label: 'V5 · Zoom blur reveal',
  C: LGV5
}, {
  id: 'lg6',
  label: 'V6 · Counter roulette',
  C: LGV6
}];
})(); } catch (e) { __ds_ns.__errors.push({ path: "explorations/logo-intro-variations.jsx", error: String((e && e.message) || e) }); }

// explorations/pagebreak-variations.jsx
try { (() => {
// Page-break transition variations — shows a "divider" between chapters.
// Each returns a static frame that conveys the idea.

if (typeof document !== 'undefined' && !document.getElementById('pb-styles')) {
  const s = document.createElement('style');
  s.id = 'pb-styles';
  s.textContent = `
    .pb-root{font-family:'Satoshi',system-ui,sans-serif;width:100%;height:100%;position:relative;overflow:hidden;background:#FDFCFA;color:#191924;display:flex;flex-direction:column}
    .pb-label{position:absolute;top:10px;left:14px;font-family:'JetBrains Mono',monospace;font-size:9.5px;letter-spacing:2px;text-transform:uppercase;color:#918D82;z-index:5}
    .pb-half{flex:1;display:flex;align-items:center;justify-content:center;padding:16px}
    .pb-title{font-family:'Chubbo','Chubbo',sans-serif;font-weight:700;font-size:32px;letter-spacing:-.02em;line-height:1}
    .pb-num{font-family:'Chubbo',sans-serif;font-weight:900;font-size:80px;line-height:1;letter-spacing:-.02em}
    .pb-eb{font-family:'JetBrains Mono',monospace;font-size:9px;letter-spacing:2.2px;text-transform:uppercase;color:#918D82}
  `;
  document.head.appendChild(s);
}

// V1 — Inverted color fold
function PBV1() {
  return /*#__PURE__*/React.createElement("div", {
    className: "pb-root"
  }, /*#__PURE__*/React.createElement("div", {
    className: "pb-label"
  }, "V1 \xB7 Inverted fold"), /*#__PURE__*/React.createElement("div", {
    className: "pb-half",
    style: {
      background: '#FDFCFA',
      color: '#191924'
    }
  }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    className: "pb-eb"
  }, "End of \xB7 01"), /*#__PURE__*/React.createElement("div", {
    className: "pb-title"
  }, "Brand."))), /*#__PURE__*/React.createElement("div", {
    className: "pb-half",
    style: {
      background: '#191924',
      color: '#FDFCFA'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      textAlign: 'right'
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "pb-eb",
    style: {
      color: '#C8B6FF'
    }
  }, "Beginning of \xB7 02"), /*#__PURE__*/React.createElement("div", {
    className: "pb-title",
    style: {
      color: '#FDFCFA'
    }
  }, "Color."))));
}

// V2 — Big chapter number as divider
function PBV2() {
  return /*#__PURE__*/React.createElement("div", {
    className: "pb-root",
    style: {
      background: '#F2F0EC'
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "pb-label"
  }, "V2 \xB7 Chapter numeral"), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center'
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "pb-num",
    style: {
      color: 'rgba(25,25,36,.06)',
      fontSize: 220
    }
  }, "02"), /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      textAlign: 'center'
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "pb-eb",
    style: {
      color: '#5B3FD4'
    }
  }, "Chapter two"), /*#__PURE__*/React.createElement("div", {
    className: "pb-title",
    style: {
      fontSize: 48
    }
  }, "Color."))));
}

// V3 — Diagonal split with gradient fuse
function PBV3() {
  return /*#__PURE__*/React.createElement("div", {
    className: "pb-root",
    style: {
      position: 'relative'
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "pb-label"
  }, "V3 \xB7 Diagonal gradient"), /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      inset: 0,
      background: 'linear-gradient(135deg,#FDFCFA 0%,#FDFCFA 45%,#C8B6FF 50%,#5B3FD4 55%,#191924 100%)'
    }
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      top: '30%',
      left: 30,
      color: '#191924'
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "pb-eb"
  }, "End \xB7 01"), /*#__PURE__*/React.createElement("div", {
    className: "pb-title"
  }, "Brand.")), /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      bottom: '30%',
      right: 30,
      color: '#FDFCFA',
      textAlign: 'right'
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "pb-eb",
    style: {
      color: '#C8B6FF'
    }
  }, "Start \xB7 02"), /*#__PURE__*/React.createElement("div", {
    className: "pb-title"
  }, "Color.")));
}

// V4 — Pillar-dot curtain (four color bars sliding in)
function PBV4() {
  return /*#__PURE__*/React.createElement("div", {
    className: "pb-root"
  }, /*#__PURE__*/React.createElement("div", {
    className: "pb-label"
  }, "V4 \xB7 Pillar curtain"), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      display: 'flex'
    }
  }, ['#C8B6FF', '#B8E6D3', '#FFCDB2', '#A2D2FF'].map((c, i) => /*#__PURE__*/React.createElement("div", {
    key: i,
    style: {
      flex: 1,
      background: c,
      display: 'flex',
      alignItems: 'flex-end',
      padding: 20,
      color: '#191924'
    }
  }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    className: "pb-eb"
  }, 'DOTS'[i]), /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: 'Chubbo',
      fontWeight: 800,
      fontSize: 22,
      marginTop: 4
    }
  }, ['Data', 'Ops', 'Tech', 'Str'][i]))))), /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      top: '50%',
      left: '50%',
      transform: 'translate(-50%,-50%)',
      padding: '12px 20px',
      background: '#191924',
      color: '#FDFCFA',
      borderRadius: 99,
      fontFamily: 'JetBrains Mono',
      fontSize: 10,
      letterSpacing: 2,
      textTransform: 'uppercase'
    }
  }, "02 \xB7 Color"));
}

// V5 — Eclipse (dark circle covering page)
function PBV5() {
  return /*#__PURE__*/React.createElement("div", {
    className: "pb-root",
    style: {
      background: '#FDFCFA'
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "pb-label"
  }, "V5 \xB7 Eclipse sweep"), /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      inset: 0,
      background: 'radial-gradient(circle at 20% 50%, #191924 0, #191924 35%, transparent 60%)'
    }
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      top: '35%',
      left: 28,
      color: '#FDFCFA'
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "pb-eb",
    style: {
      color: '#C8B6FF'
    }
  }, "Start \xB7 02"), /*#__PURE__*/React.createElement("div", {
    className: "pb-title"
  }, "Color.")), /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      bottom: '20%',
      right: 30,
      color: '#191924',
      textAlign: 'right'
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "pb-eb"
  }, "End \xB7 01"), /*#__PURE__*/React.createElement("div", {
    className: "pb-title",
    style: {
      fontSize: 24
    }
  }, "Brand.")));
}

// V6 — Horizontal film strip / ticker
function PBV6() {
  return /*#__PURE__*/React.createElement("div", {
    className: "pb-root",
    style: {
      background: '#191924',
      color: '#FDFCFA'
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "pb-label",
    style: {
      color: 'rgba(253,252,250,.5)'
    }
  }, "V6 \xB7 Ticker"), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      display: 'flex',
      alignItems: 'center',
      padding: '0 16px',
      overflow: 'hidden'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: 30,
      fontFamily: 'Chubbo',
      fontWeight: 900,
      fontSize: 56,
      letterSpacing: -1,
      whiteSpace: 'nowrap'
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      color: 'rgba(253,252,250,.2)'
    }
  }, "01 BRAND"), /*#__PURE__*/React.createElement("span", {
    style: {
      color: '#C8B6FF'
    }
  }, "\xB7"), /*#__PURE__*/React.createElement("span", {
    style: {
      color: '#FDFCFA'
    }
  }, "02 COLOR"), /*#__PURE__*/React.createElement("span", {
    style: {
      color: '#C8B6FF'
    }
  }, "\xB7"), /*#__PURE__*/React.createElement("span", {
    style: {
      color: 'rgba(253,252,250,.2)'
    }
  }, "03 TYPE"))), /*#__PURE__*/React.createElement("div", {
    style: {
      height: 3,
      background: 'linear-gradient(90deg,transparent,#C8B6FF,transparent)'
    }
  }));
}

// V7 — Question/answer break (pull-quote)
function PBV7() {
  return /*#__PURE__*/React.createElement("div", {
    className: "pb-root",
    style: {
      background: '#F2F0EC',
      padding: 30
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "pb-label"
  }, "V7 \xB7 Pull-quote"), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      maxWidth: 480,
      textAlign: 'center'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: 'Chubbo,Chubbo,sans-serif',
      fontWeight: 600,
      fontSize: 28,
      lineHeight: 1.2,
      color: '#191924'
    }
  }, "\u201CThe palette is not paint \u2014 it's ", /*#__PURE__*/React.createElement("span", {
    style: {
      color: '#5B3FD4'
    }
  }, "posture"), ".\u201D"), /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: 16,
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      gap: 10
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      width: 32,
      height: 1,
      background: '#918D82'
    }
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: 'JetBrains Mono',
      fontSize: 10,
      letterSpacing: 2,
      textTransform: 'uppercase',
      color: '#918D82'
    }
  }, "Chapter 02 \xB7 Color"), /*#__PURE__*/React.createElement("div", {
    style: {
      width: 32,
      height: 1,
      background: '#918D82'
    }
  })))));
}

// V8 — Horizontal color-fuse (gradient strip between sections)
function PBV8() {
  return /*#__PURE__*/React.createElement("div", {
    className: "pb-root"
  }, /*#__PURE__*/React.createElement("div", {
    className: "pb-label"
  }, "V8 \xB7 Color fuse \xB7 horizontal"), /*#__PURE__*/React.createElement("div", {
    className: "pb-half",
    style: {
      background: '#FDFCFA',
      flex: '0 0 30%'
    }
  }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    className: "pb-eb"
  }, "01"), /*#__PURE__*/React.createElement("div", {
    className: "pb-title",
    style: {
      fontSize: 24
    }
  }, "Brand"))), /*#__PURE__*/React.createElement("div", {
    style: {
      height: 80,
      background: 'linear-gradient(180deg,#FDFCFA,#C8B6FF 40%,#5B3FD4 80%,#2D1B4E)'
    }
  }), /*#__PURE__*/React.createElement("div", {
    className: "pb-half",
    style: {
      background: '#2D1B4E',
      color: '#FDFCFA',
      flex: '0 0 30%'
    }
  }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    className: "pb-eb",
    style: {
      color: '#C8B6FF'
    }
  }, "02"), /*#__PURE__*/React.createElement("div", {
    className: "pb-title",
    style: {
      fontSize: 24
    }
  }, "Color"))));
}
window.PageBreakVariations = [{
  id: 'pb1',
  label: 'V1 · Inverted fold',
  C: PBV1
}, {
  id: 'pb2',
  label: 'V2 · Chapter numeral',
  C: PBV2
}, {
  id: 'pb3',
  label: 'V3 · Diagonal gradient',
  C: PBV3
}, {
  id: 'pb4',
  label: 'V4 · Pillar curtain',
  C: PBV4
}, {
  id: 'pb5',
  label: 'V5 · Eclipse sweep',
  C: PBV5
}, {
  id: 'pb6',
  label: 'V6 · Ticker',
  C: PBV6
}, {
  id: 'pb7',
  label: 'V7 · Pull-quote',
  C: PBV7
}, {
  id: 'pb8',
  label: 'V8 · Color fuse',
  C: PBV8
}];
})(); } catch (e) { __ds_ns.__errors.push({ path: "explorations/pagebreak-variations.jsx", error: String((e && e.message) || e) }); }

// explorations/pagenav-variations.jsx
try { (() => {
// Page Navigation Variations — Next/Prev with vertical + horizontal awareness
// Each variant returns a small demo showing how the nav behaves on one page.

const PN_ICONS = {
  chL: 'M15 18l-6-6 6-6',
  chR: 'M9 18l6-6-6-6',
  chU: 'M18 15l-6-6-6 6',
  chD: 'M6 9l6 6 6-6',
  dot: 'M12 12m-3 0a3 3 0 1 0 6 0a3 3 0 1 0-6 0',
  home: 'M3 12l9-9 9 9M5 10v10h14V10'
};
const pnIc = (d, s = 16) => `<svg width="${s}" height="${s}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="${d}"/></svg>`;
if (typeof document !== 'undefined' && !document.getElementById('pn-styles')) {
  const s = document.createElement('style');
  s.id = 'pn-styles';
  s.textContent = `
    .pn-root{font-family:'Satoshi',system-ui,sans-serif;width:100%;height:100%;position:relative;overflow:hidden;background:#FDFCFA;color:#191924}
    .pn-label{position:absolute;top:12px;left:14px;font-family:'JetBrains Mono',monospace;font-size:9.5px;letter-spacing:2px;text-transform:uppercase;color:#918D82;z-index:5}
    .pn-body{position:absolute;inset:40px 20px 20px;display:flex;align-items:center;justify-content:center;flex-direction:column;gap:10px}
    .pn-title{font-family:'Chubbo','Chubbo',sans-serif;font-weight:700;font-size:48px;letter-spacing:-.02em;line-height:1;color:#191924}
    .pn-sub{font-family:'JetBrains Mono',monospace;font-size:10px;letter-spacing:2px;text-transform:uppercase;color:#918D82}
    .pn-btn{border:none;cursor:pointer;font-family:inherit}
  `;
  document.head.appendChild(s);
}

// V1 — Corner arrows (bottom left/right) with section dots
function PNV1() {
  const [p, setP] = React.useState(1);
  return /*#__PURE__*/React.createElement("div", {
    className: "pn-root"
  }, /*#__PURE__*/React.createElement("div", {
    className: "pn-label"
  }, "V1 \xB7 Corner arrows"), /*#__PURE__*/React.createElement("div", {
    className: "pn-body"
  }, /*#__PURE__*/React.createElement("div", {
    className: "pn-sub"
  }, "Section ", p, "/5"), /*#__PURE__*/React.createElement("div", {
    className: "pn-title"
  }, "Brand.")), /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      left: 0,
      right: 0,
      bottom: 18,
      display: 'flex',
      justifyContent: 'space-between',
      padding: '0 20px',
      alignItems: 'center'
    }
  }, /*#__PURE__*/React.createElement("button", {
    className: "pn-btn",
    onClick: () => setP(Math.max(1, p - 1)),
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 8,
      padding: '8px 12px',
      borderRadius: 8,
      background: 'transparent',
      color: '#4A4842',
      fontSize: 12
    }
  }, /*#__PURE__*/React.createElement("span", {
    dangerouslySetInnerHTML: {
      __html: pnIc(PN_ICONS.chL, 15)
    }
  }), " Prev"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: 5
    }
  }, [1, 2, 3, 4, 5].map(i => /*#__PURE__*/React.createElement("span", {
    key: i,
    onClick: () => setP(i),
    style: {
      width: p === i ? 22 : 6,
      height: 6,
      borderRadius: 3,
      background: p === i ? '#191924' : 'rgba(25,25,36,.2)',
      cursor: 'pointer',
      transition: 'width .2s'
    }
  }))), /*#__PURE__*/React.createElement("button", {
    className: "pn-btn",
    onClick: () => setP(Math.min(5, p + 1)),
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 8,
      padding: '8px 12px',
      borderRadius: 8,
      background: '#191924',
      color: '#FDFCFA',
      fontSize: 12
    }
  }, "Next ", /*#__PURE__*/React.createElement("span", {
    dangerouslySetInnerHTML: {
      __html: pnIc(PN_ICONS.chR, 15)
    }
  }))));
}

// V2 — Vertical progress rail (right edge)
function PNV2() {
  const [p, setP] = React.useState(2);
  const secs = ['Brand', 'Color', 'Type', 'Shape', 'Components'];
  return /*#__PURE__*/React.createElement("div", {
    className: "pn-root"
  }, /*#__PURE__*/React.createElement("div", {
    className: "pn-label"
  }, "V2 \xB7 Vertical rail"), /*#__PURE__*/React.createElement("div", {
    className: "pn-body"
  }, /*#__PURE__*/React.createElement("div", {
    className: "pn-sub"
  }, secs[p - 1]), /*#__PURE__*/React.createElement("div", {
    className: "pn-title"
  }, secs[p - 1], ".")), /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      right: 16,
      top: '50%',
      transform: 'translateY(-50%)',
      display: 'flex',
      flexDirection: 'column',
      gap: 10
    }
  }, secs.map((s, i) => /*#__PURE__*/React.createElement("div", {
    key: i,
    onClick: () => setP(i + 1),
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 8,
      cursor: 'pointer',
      opacity: p === i + 1 ? 1 : .4,
      transition: 'opacity .2s'
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: 'JetBrains Mono',
      fontSize: 9,
      letterSpacing: 1.5,
      textTransform: 'uppercase',
      color: p === i + 1 ? '#191924' : '#918D82'
    }
  }, s), /*#__PURE__*/React.createElement("span", {
    style: {
      width: p === i + 1 ? 24 : 12,
      height: 2,
      background: p === i + 1 ? '#5B3FD4' : '#B5B1A7',
      transition: 'width .2s'
    }
  })))));
}

// V3 — Horizontal stepper with labels
function PNV3() {
  const [p, setP] = React.useState(2);
  const secs = ['Brand', 'Color', 'Type', 'Shape'];
  return /*#__PURE__*/React.createElement("div", {
    className: "pn-root"
  }, /*#__PURE__*/React.createElement("div", {
    className: "pn-label"
  }, "V3 \xB7 Stepper"), /*#__PURE__*/React.createElement("div", {
    className: "pn-body"
  }, /*#__PURE__*/React.createElement("div", {
    className: "pn-title"
  }, secs[p - 1], ".")), /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      bottom: 20,
      left: '50%',
      transform: 'translateX(-50%)',
      display: 'flex',
      alignItems: 'center',
      gap: 4,
      background: '#F2F0EC',
      padding: '6px',
      borderRadius: 99
    }
  }, secs.map((s, i) => /*#__PURE__*/React.createElement("button", {
    key: i,
    onClick: () => setP(i + 1),
    className: "pn-btn",
    style: {
      padding: '6px 12px',
      borderRadius: 99,
      background: p === i + 1 ? '#191924' : 'transparent',
      color: p === i + 1 ? '#FDFCFA' : '#4A4842',
      fontSize: 11,
      fontFamily: 'JetBrains Mono',
      letterSpacing: 1.5,
      textTransform: 'uppercase'
    }
  }, String(i + 1).padStart(2, '0'), " ", s))));
}

// V4 — Compass (4-way: up=chapter, down=next section, L/R=prev/next within)
function PNV4() {
  return /*#__PURE__*/React.createElement("div", {
    className: "pn-root"
  }, /*#__PURE__*/React.createElement("div", {
    className: "pn-label"
  }, "V4 \xB7 Compass \xB7 4-way"), /*#__PURE__*/React.createElement("div", {
    className: "pn-body"
  }, /*#__PURE__*/React.createElement("div", {
    className: "pn-sub"
  }, "\u2191 Chapter \xB7 \u2193 Next \xB7 \u2190 \u2192 Within"), /*#__PURE__*/React.createElement("div", {
    className: "pn-title"
  }, "Section.")), /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      bottom: 20,
      right: 20,
      width: 110,
      height: 110,
      borderRadius: '50%',
      border: '1px solid rgba(25,25,36,.1)',
      background: '#FDFCFA',
      boxShadow: '0 4px 14px rgba(25,25,36,.06)'
    }
  }, [[PN_ICONS.chU, '50%', '8px', 'translateX(-50%)'], [PN_ICONS.chD, '50%', null, 'translateX(-50%)', true], [PN_ICONS.chL, '8px', '50%', 'translateY(-50%)'], [PN_ICONS.chR, null, '50%', 'translateY(-50%)']].map(([d, l, t, tr, bot], i) => {
    const style = {
      position: 'absolute',
      width: 26,
      height: 26,
      borderRadius: 6,
      border: 'none',
      background: 'transparent',
      color: '#4A4842',
      cursor: 'pointer',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      transform: tr
    };
    if (l != null) style.left = l;
    if (t != null) style.top = t;
    if (!l && i === 3) style.right = '8px';
    if (bot) style.bottom = '8px';
    return /*#__PURE__*/React.createElement("button", {
      key: i,
      className: "pn-btn",
      style: style,
      dangerouslySetInnerHTML: {
        __html: pnIc(d, 14)
      }
    });
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      inset: '35%',
      borderRadius: '50%',
      background: '#191924',
      color: '#C8B6FF',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      fontFamily: 'Chubbo',
      fontWeight: 900,
      fontSize: 10
    }
  }, "02")));
}

// V5 — Floating page dock (title + arrows + progress)
function PNV5() {
  const [p, setP] = React.useState(3);
  return /*#__PURE__*/React.createElement("div", {
    className: "pn-root",
    style: {
      background: '#191924',
      color: '#FDFCFA'
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "pn-label",
    style: {
      color: 'rgba(253,252,250,.5)'
    }
  }, "V5 \xB7 Floating dock \xB7 dark"), /*#__PURE__*/React.createElement("div", {
    className: "pn-body"
  }, /*#__PURE__*/React.createElement("div", {
    className: "pn-sub",
    style: {
      color: '#C8B6FF'
    }
  }, "03 / 12"), /*#__PURE__*/React.createElement("div", {
    className: "pn-title",
    style: {
      color: '#FDFCFA'
    }
  }, "Color.")), /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      bottom: 22,
      left: '50%',
      transform: 'translateX(-50%)',
      display: 'flex',
      alignItems: 'center',
      gap: 4,
      background: 'rgba(253,252,250,.08)',
      backdropFilter: 'blur(8px)',
      padding: 5,
      borderRadius: 99,
      border: '1px solid rgba(253,252,250,.12)'
    }
  }, /*#__PURE__*/React.createElement("button", {
    className: "pn-btn",
    onClick: () => setP(Math.max(1, p - 1)),
    style: {
      width: 32,
      height: 32,
      borderRadius: '50%',
      background: 'transparent',
      color: '#FDFCFA',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center'
    },
    dangerouslySetInnerHTML: {
      __html: pnIc(PN_ICONS.chL, 15)
    }
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      padding: '0 14px',
      fontFamily: 'JetBrains Mono',
      fontSize: 10,
      letterSpacing: 1.5
    }
  }, String(p).padStart(2, '0'), " \xB7 of \xB7 12"), /*#__PURE__*/React.createElement("button", {
    className: "pn-btn",
    onClick: () => setP(Math.min(12, p + 1)),
    style: {
      width: 32,
      height: 32,
      borderRadius: '50%',
      background: '#C8B6FF',
      color: '#191924',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center'
    },
    dangerouslySetInnerHTML: {
      __html: pnIc(PN_ICONS.chR, 15)
    }
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      top: 0,
      left: 0,
      right: 0,
      height: 3,
      background: 'rgba(253,252,250,.1)'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      height: '100%',
      width: `${p / 12 * 100}%`,
      background: '#C8B6FF',
      transition: 'width .3s'
    }
  })));
}

// V6 — Split next-card preview (shows title of next section)
function PNV6() {
  return /*#__PURE__*/React.createElement("div", {
    className: "pn-root"
  }, /*#__PURE__*/React.createElement("div", {
    className: "pn-label"
  }, "V6 \xB7 Previewed next"), /*#__PURE__*/React.createElement("div", {
    className: "pn-body"
  }, /*#__PURE__*/React.createElement("div", {
    className: "pn-sub"
  }, "You are reading"), /*#__PURE__*/React.createElement("div", {
    className: "pn-title"
  }, "Typography.")), /*#__PURE__*/React.createElement("button", {
    className: "pn-btn",
    style: {
      position: 'absolute',
      bottom: 18,
      right: 18,
      display: 'flex',
      alignItems: 'stretch',
      padding: 0,
      borderRadius: 12,
      background: '#FDFCFA',
      border: '1px solid rgba(25,25,36,.1)',
      overflow: 'hidden',
      boxShadow: '0 6px 20px rgba(25,25,36,.06)'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      padding: '12px 14px',
      textAlign: 'left'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: 'JetBrains Mono',
      fontSize: 9,
      letterSpacing: 1.5,
      textTransform: 'uppercase',
      color: '#918D82'
    }
  }, "Up next \xB7 04"), /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: 'Chubbo,Chubbo,sans-serif',
      fontWeight: 700,
      fontSize: 18,
      marginTop: 2
    }
  }, "Spacing & shape")), /*#__PURE__*/React.createElement("div", {
    style: {
      background: '#191924',
      color: '#FDFCFA',
      display: 'flex',
      alignItems: 'center',
      padding: '0 14px'
    },
    dangerouslySetInnerHTML: {
      __html: pnIc(PN_ICONS.chR, 18)
    }
  })), /*#__PURE__*/React.createElement("button", {
    className: "pn-btn",
    style: {
      position: 'absolute',
      bottom: 18,
      left: 18,
      display: 'flex',
      alignItems: 'stretch',
      padding: 0,
      borderRadius: 12,
      background: 'transparent',
      border: '1px dashed rgba(25,25,36,.15)',
      overflow: 'hidden'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      background: '#F2F0EC',
      color: '#4A4842',
      display: 'flex',
      alignItems: 'center',
      padding: '0 14px'
    },
    dangerouslySetInnerHTML: {
      __html: pnIc(PN_ICONS.chL, 18)
    }
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      padding: '12px 14px',
      textAlign: 'left'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: 'JetBrains Mono',
      fontSize: 9,
      letterSpacing: 1.5,
      textTransform: 'uppercase',
      color: '#918D82'
    }
  }, "02 \xB7 Back"), /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: 'Chubbo,Chubbo,sans-serif',
      fontWeight: 700,
      fontSize: 16,
      marginTop: 2,
      color: '#4A4842'
    }
  }, "Color"))));
}

// V7 — Edge swipe zones (L/R hit areas + arrow hints)
function PNV7() {
  const [hov, setHov] = React.useState(null);
  return /*#__PURE__*/React.createElement("div", {
    className: "pn-root"
  }, /*#__PURE__*/React.createElement("div", {
    className: "pn-label"
  }, "V7 \xB7 Edge swipe zones"), /*#__PURE__*/React.createElement("div", {
    className: "pn-body"
  }, /*#__PURE__*/React.createElement("div", {
    className: "pn-sub"
  }, "Hover the left or right edge"), /*#__PURE__*/React.createElement("div", {
    className: "pn-title"
  }, "Swipe.")), ['left', 'right'].map(side => /*#__PURE__*/React.createElement("div", {
    key: side,
    onMouseEnter: () => setHov(side),
    onMouseLeave: () => setHov(null),
    style: {
      position: 'absolute',
      top: 36,
      bottom: 10,
      [side]: 0,
      width: 70,
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      cursor: 'pointer',
      background: hov === side ? `linear-gradient(to ${side === 'left' ? 'right' : 'left'}, rgba(91,63,212,.1), transparent)` : 'transparent',
      transition: 'background .2s'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      width: 36,
      height: 36,
      borderRadius: '50%',
      background: hov === side ? '#191924' : '#FDFCFA',
      color: hov === side ? '#FDFCFA' : '#4A4842',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      boxShadow: '0 2px 10px rgba(25,25,36,.08)',
      transform: hov === side ? 'scale(1.1)' : 'scale(1)',
      transition: 'all .2s'
    },
    dangerouslySetInnerHTML: {
      __html: pnIc(side === 'left' ? PN_ICONS.chL : PN_ICONS.chR, 16)
    }
  }))));
}

// V8 — Mini-map (grid of all pages, current highlighted)
function PNV8() {
  const [p, setP] = React.useState(7);
  return /*#__PURE__*/React.createElement("div", {
    className: "pn-root",
    style: {
      background: '#F2F0EC'
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "pn-label"
  }, "V8 \xB7 Mini-map"), /*#__PURE__*/React.createElement("div", {
    className: "pn-body"
  }, /*#__PURE__*/React.createElement("div", {
    className: "pn-sub"
  }, "Page ", p, " of 16"), /*#__PURE__*/React.createElement("div", {
    className: "pn-title"
  }, "Overview.")), /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      bottom: 16,
      left: '50%',
      transform: 'translateX(-50%)',
      display: 'grid',
      gridTemplateColumns: 'repeat(8,10px)',
      gap: 3,
      padding: 10,
      borderRadius: 8,
      background: '#FDFCFA',
      border: '1px solid rgba(25,25,36,.08)'
    }
  }, Array.from({
    length: 16
  }).map((_, i) => /*#__PURE__*/React.createElement("div", {
    key: i,
    onClick: () => setP(i + 1),
    style: {
      width: 10,
      height: 14,
      borderRadius: 2,
      background: p === i + 1 ? '#5B3FD4' : i < p ? '#191924' : 'rgba(25,25,36,.15)',
      cursor: 'pointer',
      transition: 'background .15s'
    },
    title: `Page ${i + 1}`
  }))));
}
window.PageNavVariations = [{
  id: 'pn1',
  label: 'V1 · Corner arrows + dots',
  C: PNV1
}, {
  id: 'pn2',
  label: 'V2 · Vertical rail',
  C: PNV2
}, {
  id: 'pn3',
  label: 'V3 · Horizontal stepper',
  C: PNV3
}, {
  id: 'pn4',
  label: 'V4 · Compass · 4-way',
  C: PNV4
}, {
  id: 'pn5',
  label: 'V5 · Dark floating dock',
  C: PNV5
}, {
  id: 'pn6',
  label: 'V6 · Previewed next',
  C: PNV6
}, {
  id: 'pn7',
  label: 'V7 · Edge swipe zones',
  C: PNV7
}, {
  id: 'pn8',
  label: 'V8 · Mini-map',
  C: PNV8
}];
})(); } catch (e) { __ds_ns.__errors.push({ path: "explorations/pagenav-variations.jsx", error: String((e && e.message) || e) }); }

// explorations/scrollfuse-variations.jsx
try { (() => {
// Smooth Scroll Color-Fuse Variations — scroll the card to see colors morph.
// Each variant is a small scroll container with color interpolation tied to scroll %.

if (typeof document !== 'undefined' && !document.getElementById('sc-styles')) {
  const s = document.createElement('style');
  s.id = 'sc-styles';
  s.textContent = `
    .sc-root{font-family:'Satoshi',system-ui,sans-serif;width:100%;height:100%;overflow-y:auto;overflow-x:hidden;position:relative;scroll-behavior:smooth}
    .sc-root::-webkit-scrollbar{width:4px}.sc-root::-webkit-scrollbar-thumb{background:rgba(25,25,36,.2);border-radius:2px}
    .sc-label{position:sticky;top:0;padding:10px 14px;font-family:'JetBrains Mono',monospace;font-size:9.5px;letter-spacing:2px;text-transform:uppercase;color:#918D82;background:rgba(253,252,250,.85);backdrop-filter:blur(6px);z-index:10;border-bottom:1px solid rgba(25,25,36,.05)}
    .sc-section{height:var(--h,400px);padding:40px 24px;display:flex;flex-direction:column;justify-content:center;transition:background .5s}
    .sc-title{font-family:'Chubbo','Chubbo',sans-serif;font-weight:700;font-size:36px;letter-spacing:-.02em;line-height:1}
    .sc-eb{font-family:'JetBrains Mono',monospace;font-size:10px;letter-spacing:2px;text-transform:uppercase;opacity:.7;margin-bottom:8px}
  `;
  document.head.appendChild(s);
}
function useScroll(ref) {
  const [y, setY] = React.useState(0);
  React.useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const onS = () => setY(el.scrollTop / Math.max(1, el.scrollHeight - el.clientHeight));
    el.addEventListener('scroll', onS, {
      passive: true
    });
    return () => el.removeEventListener('scroll', onS);
  }, []);
  return y;
}
function lerpColor(a, b, t) {
  const p = c => [parseInt(c.slice(1, 3), 16), parseInt(c.slice(3, 5), 16), parseInt(c.slice(5, 7), 16)];
  const A = p(a),
    B = p(b);
  const m = A.map((v, i) => Math.round(v + (B[i] - v) * t));
  return `rgb(${m.join(',')})`;
}

// V1 — Background morphs through cream → pastel → ink
function SCV1() {
  const ref = React.useRef();
  const y = useScroll(ref);
  const stops = ['#FDFCFA', '#C8B6FF', '#5B3FD4', '#191924'];
  const i = Math.min(Math.floor(y * (stops.length - 1)), stops.length - 2);
  const t = y * (stops.length - 1) - i;
  const bg = lerpColor(stops[i], stops[i + 1], t);
  const dark = y > 0.4;
  return /*#__PURE__*/React.createElement("div", {
    ref: ref,
    className: "sc-root",
    style: {
      background: bg,
      color: dark ? '#FDFCFA' : '#191924',
      transition: 'color .4s'
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "sc-label",
    style: {
      color: dark ? 'rgba(253,252,250,.6)' : '#918D82',
      background: dark ? 'rgba(25,25,36,.5)' : 'rgba(253,252,250,.85)'
    }
  }, "V1 \xB7 Sequential fuse"), [['Cream', '01 · Brand'], ['Lavender', '02 · Color'], ['Violet', '03 · Type'], ['Ink', '04 · Components']].map(([sub, t], k) => /*#__PURE__*/React.createElement("div", {
    key: k,
    className: "sc-section",
    style: {
      '--h': '300px'
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "sc-eb"
  }, sub), /*#__PURE__*/React.createElement("div", {
    className: "sc-title"
  }, t))));
}

// V2 — Pillar color rotation (each section = pillar)
function SCV2() {
  const ref = React.useRef();
  const y = useScroll(ref);
  const pillars = [['#C8B6FF', 'Data', 'D'], ['#B8E6D3', 'Ops', 'O'], ['#FFCDB2', 'Tech', 'T'], ['#A2D2FF', 'Strategy', 'S']];
  const i = Math.min(Math.floor(y * 4), 3);
  const t = y * 4 - i;
  const next = Math.min(i + 1, 3);
  const bg = lerpColor(pillars[i][0], pillars[next][0], t);
  return /*#__PURE__*/React.createElement("div", {
    ref: ref,
    className: "sc-root",
    style: {
      background: bg,
      transition: 'none'
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "sc-label"
  }, "V2 \xB7 Pillar rotation"), pillars.map(([c, n, l], k) => /*#__PURE__*/React.createElement("div", {
    key: k,
    className: "sc-section",
    style: {
      '--h': '340px'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      width: 64,
      height: 64,
      borderRadius: 16,
      background: '#191924',
      color: c,
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      fontFamily: 'Chubbo',
      fontWeight: 900,
      fontSize: 28,
      marginBottom: 14
    }
  }, l), /*#__PURE__*/React.createElement("div", {
    className: "sc-eb"
  }, "Pillar \xB7 ", String(k + 1).padStart(2, '0')), /*#__PURE__*/React.createElement("div", {
    className: "sc-title",
    style: {
      color: '#191924'
    }
  }, n, "."))));
}

// V3 — Fixed header that shifts tint as you scroll
function SCV3() {
  const ref = React.useRef();
  const y = useScroll(ref);
  const tintStops = ['#FDFCFA', '#F2F0EC', '#E8E6E0', '#191924'];
  const i = Math.min(Math.floor(y * 3), 2);
  const t = y * 3 - i;
  const tint = lerpColor(tintStops[i], tintStops[i + 1], t);
  const dark = y > 0.7;
  return /*#__PURE__*/React.createElement("div", {
    ref: ref,
    className: "sc-root",
    style: {
      background: tint,
      color: dark ? '#FDFCFA' : '#191924',
      transition: 'color .4s'
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "sc-label",
    style: {
      background: tint,
      color: dark ? 'rgba(253,252,250,.6)' : '#918D82'
    }
  }, "V3 \xB7 Tint drift"), [0, 1, 2, 3].map(k => /*#__PURE__*/React.createElement("div", {
    key: k,
    className: "sc-section",
    style: {
      '--h': '280px'
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "sc-eb"
  }, "Section ", String(k + 1).padStart(2, '0')), /*#__PURE__*/React.createElement("div", {
    className: "sc-title"
  }, ['Canvas', 'Shape', 'Motion', 'Depth'][k], "."))));
}

// V4 — Gradient that scrolls with you (vertical gradient background = scroll position)
function SCV4() {
  return /*#__PURE__*/React.createElement("div", {
    className: "sc-root"
  }, /*#__PURE__*/React.createElement("div", {
    className: "sc-label"
  }, "V4 \xB7 Fixed gradient mesh"), /*#__PURE__*/React.createElement("div", {
    style: {
      background: 'linear-gradient(180deg,#FDFCFA 0%,#C8B6FF 25%,#B8E6D3 50%,#FFCDB2 75%,#A2D2FF 100%)'
    }
  }, [0, 1, 2, 3, 4].map(k => /*#__PURE__*/React.createElement("div", {
    key: k,
    style: {
      height: 280,
      padding: '30px 24px',
      display: 'flex',
      flexDirection: 'column',
      justifyContent: 'center'
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "sc-eb",
    style: {
      color: '#191924'
    }
  }, "Stop ", String(k + 1).padStart(2, '0')), /*#__PURE__*/React.createElement("div", {
    className: "sc-title",
    style: {
      color: '#191924'
    }
  }, ['Cream', 'Lavender', 'Mint', 'Peach', 'Sky'][k], ".")))));
}

// V5 — Sections have their own bg but edges fuse via gradient spacers
function SCV5() {
  const zones = [['#FDFCFA', '#191924', 'Brand', '01'], ['#C8B6FF', '#2D1B4E', 'Color', '02'], ['#B8E6D3', '#12573D', 'Ops', '03'], ['#191924', '#C8B6FF', 'Systems', '04']];
  return /*#__PURE__*/React.createElement("div", {
    className: "sc-root"
  }, /*#__PURE__*/React.createElement("div", {
    className: "sc-label"
  }, "V5 \xB7 Edge fuse"), zones.map(([bg, fg, t, n], k) => /*#__PURE__*/React.createElement(React.Fragment, {
    key: k
  }, /*#__PURE__*/React.createElement("div", {
    className: "sc-section",
    style: {
      '--h': '240px',
      background: bg,
      color: fg
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "sc-eb"
  }, n), /*#__PURE__*/React.createElement("div", {
    className: "sc-title"
  }, t, ".")), k < zones.length - 1 && /*#__PURE__*/React.createElement("div", {
    style: {
      height: 60,
      background: `linear-gradient(180deg, ${bg}, ${zones[k + 1][0]})`
    }
  }))));
}

// V6 — Scrollbar/progress that IS the color indicator
function SCV6() {
  const ref = React.useRef();
  const y = useScroll(ref);
  const stops = ['#5B3FD4', '#2A9D6E', '#C65D2E', '#2563B8'];
  const i = Math.min(Math.floor(y * 3), 2);
  const t = y * 3 - i;
  const c = lerpColor(stops[i], stops[i + 1], t);
  return /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'relative',
      width: '100%',
      height: '100%'
    }
  }, /*#__PURE__*/React.createElement("div", {
    ref: ref,
    className: "sc-root",
    style: {
      background: '#FDFCFA'
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "sc-label"
  }, "V6 \xB7 Color progress rail"), [0, 1, 2, 3].map(k => /*#__PURE__*/React.createElement("div", {
    key: k,
    className: "sc-section",
    style: {
      '--h': '320px',
      borderLeft: `3px solid ${stops[k]}`,
      paddingLeft: 30
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "sc-eb",
    style: {
      color: stops[k]
    }
  }, "Pillar \xB7 0", k + 1), /*#__PURE__*/React.createElement("div", {
    className: "sc-title"
  }, ['Data', 'Ops', 'Tech', 'Strategy'][k], ".")))), /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      right: 0,
      top: 0,
      bottom: 0,
      width: 4,
      background: 'rgba(25,25,36,.06)'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      height: `${y * 100}%`,
      background: c,
      transition: 'background .1s'
    }
  })));
}
window.ScrollFuseVariations = [{
  id: 'sc1',
  label: 'V1 · Sequential fuse',
  C: SCV1
}, {
  id: 'sc2',
  label: 'V2 · Pillar rotation',
  C: SCV2
}, {
  id: 'sc3',
  label: 'V3 · Tint drift',
  C: SCV3
}, {
  id: 'sc4',
  label: 'V4 · Fixed gradient',
  C: SCV4
}, {
  id: 'sc5',
  label: 'V5 · Edge fuse',
  C: SCV5
}, {
  id: 'sc6',
  label: 'V6 · Color progress rail',
  C: SCV6
}];
})(); } catch (e) { __ds_ns.__errors.push({ path: "explorations/scrollfuse-variations.jsx", error: String((e && e.message) || e) }); }

// explorations/sidebar-variations.jsx
try { (() => {
// Sidebar Variations — 12 collapsible sidebar designs for Zeroone D.O.T.S AI
// Each returns a full sidebar card (width 300 expanded / 64 collapsed when shown).
// All use brand tokens: Ink #191924, Cream #FDFCFA, Violet #5B3FD4, pillar dots.

const SB_ICONS = {
  new: 'M12 5v14M5 12h14',
  search: 'M21 21l-4.3-4.3M11 19a8 8 0 1 1 0-16 8 8 0 0 1 0 16z',
  home: 'M3 12l9-9 9 9M5 10v10h14V10',
  pin: 'M12 17v5M8 2h8l-1 7 3 3H6l3-3-1-7z',
  star: 'M12 2l3 7h7l-6 4 2 7-6-4-6 4 2-7-6-4h7z',
  flag: 'M4 22V4h14l-2 5 2 5H4',
  bolt: 'M13 2L3 14h7l-1 8 10-12h-7l1-8z',
  gear: 'M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8zM19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09a1.65 1.65 0 0 0-1-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09a1.65 1.65 0 0 0 1.51-1 1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33h0a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51h0a1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82v0a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z',
  user: 'M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2M12 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8z',
  filter: 'M4 4h16l-6 8v6l-4 2v-8z',
  folder: 'M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z',
  chat: 'M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z',
  code: 'M16 18l6-6-6-6M8 6l-6 6 6 6',
  chevL: 'M15 18l-6-6 6-6',
  chevR: 'M9 18l6-6-6-6',
  chevD: 'M6 9l6 6 6-6',
  plus: 'M12 5v14M5 12h14',
  grid: 'M3 3h7v7H3zM14 3h7v7h-7zM14 14h7v7h-7zM3 14h7v7H3z',
  spark: 'M12 3l1.5 5L19 9.5 13.5 11 12 17l-1.5-6L5 9.5 10.5 8z',
  bell: 'M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9M13.7 21a2 2 0 0 1-3.4 0',
  moon: 'M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z',
  logo: 'M4 12a8 8 0 1 0 16 0 8 8 0 0 0-16 0zM12 8v4l3 2'
};
const ic = (d, s = 16) => `<svg width="${s}" height="${s}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="${d}"/></svg>`;
const PILLAR = {
  D: '#5B3FD4',
  O: '#2A9D6E',
  T: '#C65D2E',
  S: '#2563B8'
};
const PILLAR_PASTEL = {
  D: '#C8B6FF',
  O: '#B8E6D3',
  T: '#FFCDB2',
  S: '#A2D2FF'
};

// Common stylesheet injected once — all sidebar variations are scoped with .sbv-{id}
if (typeof document !== 'undefined' && !document.getElementById('sbv-styles')) {
  const s = document.createElement('style');
  s.id = 'sbv-styles';
  s.textContent = `
    .sbv-root{font-family:'Satoshi',-apple-system,system-ui,sans-serif;color:#191924;background:#FDFCFA;width:100%;height:100%;display:flex;overflow:hidden;position:relative}
    .sbv-main{flex:1;padding:24px;color:#6E6B62;font-size:11px;letter-spacing:1.2px;text-transform:uppercase;font-family:'JetBrains Mono',monospace}
    .sbv-title{font-family:'JetBrains Mono',monospace;font-size:9.5px;letter-spacing:2px;text-transform:uppercase;color:#918D82}
    .sbv-item{display:flex;align-items:center;gap:10px;padding:8px 10px;border-radius:8px;color:#4A4842;font-size:13px;cursor:pointer;transition:background .12s;position:relative}
    .sbv-item:hover{background:rgba(25,25,36,.05)}
    .sbv-item.active{background:#191924;color:#FDFCFA}
    .sbv-item svg{flex-shrink:0;opacity:.8}
    .sbv-sec{margin-top:14px}
    .sbv-sec-t{font-family:'JetBrains Mono',monospace;font-size:9px;letter-spacing:2px;text-transform:uppercase;color:#B5B1A7;padding:0 10px;margin:10px 0 6px}
    .sbv-divider{height:1px;background:rgba(25,25,36,.08);margin:10px 0}
    .sbv-profile{display:flex;align-items:center;gap:10px;padding:10px;border-radius:10px;cursor:pointer}
    .sbv-avatar{width:32px;height:32px;border-radius:50%;background:linear-gradient(135deg,#C8B6FF,#5B3FD4);display:flex;align-items:center;justify-content:center;color:#fff;font-weight:700;font-size:12px;flex-shrink:0}
    .sbv-pill{display:inline-flex;align-items:center;gap:4px;padding:2px 7px;border-radius:99px;font-family:'JetBrains Mono',monospace;font-size:9px;letter-spacing:1.3px;text-transform:uppercase}
    .sbv-dot{width:6px;height:6px;border-radius:50%;display:inline-block}
    .sbv-kbd{font-family:'JetBrains Mono',monospace;font-size:9.5px;padding:2px 5px;border-radius:4px;background:rgba(25,25,36,.08);color:#6E6B62;margin-left:auto}
    .sbv-demo-btn{position:absolute;top:14px;right:14px;z-index:3;padding:6px 10px;border-radius:6px;border:1px solid rgba(25,25,36,.12);background:#FDFCFA;color:#4A4842;font-family:'JetBrains Mono',monospace;font-size:9.5px;letter-spacing:1.5px;text-transform:uppercase;cursor:pointer;display:flex;align-items:center;gap:6px}
    .sbv-demo-btn:hover{background:#191924;color:#FDFCFA}
    .sbv-counter{margin-left:auto;font-family:'JetBrains Mono',monospace;font-size:9.5px;color:#918D82}
    .sbv-fade{animation:sbvFade .3s ease}
    @keyframes sbvFade{from{opacity:0;transform:translateX(-4px)}to{opacity:1;transform:none}}
    .sbv-main-copy{font-family:'Chubbo','Chubbo',sans-serif;font-size:42px;font-weight:700;letter-spacing:-.02em;color:#191924;line-height:.95;text-transform:none;margin-top:40px}
    .sbv-main-copy small{display:block;font-family:'JetBrains Mono',monospace;font-size:10px;color:#918D82;letter-spacing:2px;text-transform:uppercase;margin-bottom:12px;font-weight:400}
  `;
  document.head.appendChild(s);
}

// Collapsible sidebar hook
function useCollapse(initial = false) {
  const [open, setOpen] = React.useState(!initial);
  return [open, () => setOpen(o => !o)];
}

// ══════════════ V1 — Classic Compartments (matches reference) ══════════════
function SBV1() {
  const [open, toggle] = useCollapse(false);
  return /*#__PURE__*/React.createElement("div", {
    className: "sbv-root sbv-v1"
  }, /*#__PURE__*/React.createElement("button", {
    className: "sbv-demo-btn",
    onClick: toggle
  }, open ? 'Collapse' : 'Expand'), /*#__PURE__*/React.createElement("aside", {
    style: {
      width: open ? 260 : 60,
      background: '#FDFCFA',
      borderRight: '1px solid rgba(25,25,36,.08)',
      padding: '14px 10px',
      transition: 'width .28s cubic-bezier(.2,.7,.3,1)',
      display: 'flex',
      flexDirection: 'column',
      gap: 2,
      overflow: 'hidden'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 8,
      padding: '6px 4px',
      marginBottom: 8
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      width: 26,
      height: 26,
      borderRadius: 7,
      background: '#191924',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      color: '#C8B6FF',
      fontFamily: 'Chubbo',
      fontWeight: 900,
      fontSize: 11,
      flexShrink: 0
    }
  }, "01"), open && /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: 'Chubbo',
      fontWeight: 700,
      fontSize: 13,
      letterSpacing: 1
    }
  }, "DOTS", /*#__PURE__*/React.createElement("span", {
    style: {
      color: '#5B3FD4'
    }
  }, "\xB7"), "AI")), /*#__PURE__*/React.createElement("div", {
    className: "sbv-item",
    dangerouslySetInnerHTML: {
      __html: ic(SB_ICONS.plus) + (open ? '<span>New session</span><span class="sbv-kbd">⌘N</span>' : '')
    }
  }), /*#__PURE__*/React.createElement("div", {
    className: "sbv-item",
    dangerouslySetInnerHTML: {
      __html: ic(SB_ICONS.bolt) + (open ? '<span>Routines</span>' : '')
    }
  }), /*#__PURE__*/React.createElement("div", {
    className: "sbv-item",
    dangerouslySetInnerHTML: {
      __html: ic(SB_ICONS.folder) + (open ? '<span>Customize</span>' : '')
    }
  }), /*#__PURE__*/React.createElement("div", {
    className: "sbv-item",
    dangerouslySetInnerHTML: {
      __html: ic(SB_ICONS.chevD) + (open ? '<span>More</span>' : '')
    }
  }), open && /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("div", {
    className: "sbv-sec-t"
  }, "Pinned"), /*#__PURE__*/React.createElement("div", {
    className: "sbv-sec-t"
  }, "Routines"), /*#__PURE__*/React.createElement("div", {
    className: "sbv-sec-t",
    style: {
      display: 'flex',
      alignItems: 'center'
    }
  }, "Recents ", /*#__PURE__*/React.createElement("span", {
    style: {
      marginLeft: 'auto',
      color: '#5B3FD4'
    }
  }, "\u2195")), /*#__PURE__*/React.createElement("div", {
    className: "sbv-fade"
  }, ['Build Zeroone Dots AI landing', 'Standardize font sizes', 'Create marketing brochures', 'Design mobile landing', 'Build Claude bot'].map((t, i) => /*#__PURE__*/React.createElement("div", {
    key: i,
    className: 'sbv-item' + (i === 0 ? ' active' : ''),
    style: {
      fontSize: 12,
      padding: '6px 10px',
      whiteSpace: 'nowrap',
      overflow: 'hidden',
      textOverflow: 'ellipsis',
      display: 'block'
    }
  }, t)))), /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: 'auto',
      paddingTop: 10,
      borderTop: '1px solid rgba(25,25,36,.08)'
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "sbv-profile"
  }, /*#__PURE__*/React.createElement("div", {
    className: "sbv-avatar"
  }, "MD"), open && /*#__PURE__*/React.createElement("div", {
    style: {
      minWidth: 0
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 12,
      fontWeight: 600
    }
  }, "Meet Deshani"), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 10,
      color: '#918D82'
    }
  }, "Pro \xB7 Private AI"))))), /*#__PURE__*/React.createElement("div", {
    className: "sbv-main"
  }, /*#__PURE__*/React.createElement("div", {
    className: "sbv-title"
  }, "V1 \xB7 Classic compartments"), /*#__PURE__*/React.createElement("div", {
    className: "sbv-main-copy"
  }, /*#__PURE__*/React.createElement("small", null, "Reference parity"), "Foundation.")));
}

// ══════════════ V2 — Icon rail + drawer (two-column) ══════════════
function SBV2() {
  const [open, toggle] = useCollapse(false);
  const [tab, setTab] = React.useState('chat');
  const rail = [['chat', 'Chat', SB_ICONS.chat], ['bolt', 'Routines', SB_ICONS.bolt], ['folder', 'Library', SB_ICONS.folder], ['code', 'Code', SB_ICONS.code], ['spark', 'Agents', SB_ICONS.spark]];
  return /*#__PURE__*/React.createElement("div", {
    className: "sbv-root sbv-v2"
  }, /*#__PURE__*/React.createElement("button", {
    className: "sbv-demo-btn",
    onClick: toggle
  }, open ? 'Collapse' : 'Expand'), /*#__PURE__*/React.createElement("aside", {
    style: {
      display: 'flex',
      borderRight: '1px solid rgba(25,25,36,.08)',
      transition: 'width .28s',
      width: open ? 312 : 58,
      overflow: 'hidden'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      width: 58,
      background: '#F2F0EC',
      padding: '10px 0',
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      gap: 4,
      flexShrink: 0
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      width: 32,
      height: 32,
      borderRadius: 8,
      background: '#191924',
      color: '#C8B6FF',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      fontFamily: 'Chubbo',
      fontWeight: 900,
      fontSize: 12,
      marginBottom: 10
    }
  }, "01"), rail.map(([k, l, d]) => /*#__PURE__*/React.createElement("button", {
    key: k,
    onClick: () => setTab(k),
    title: l,
    style: {
      width: 40,
      height: 40,
      border: 'none',
      borderRadius: 9,
      cursor: 'pointer',
      background: tab === k ? '#191924' : 'transparent',
      color: tab === k ? '#FDFCFA' : '#4A4842',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center'
    },
    dangerouslySetInnerHTML: {
      __html: ic(d, 18)
    }
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: 'auto',
      width: '100%',
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      gap: 6,
      paddingBottom: 4
    }
  }, /*#__PURE__*/React.createElement("button", {
    style: {
      width: 40,
      height: 40,
      border: 'none',
      borderRadius: 9,
      background: 'transparent',
      color: '#4A4842',
      cursor: 'pointer',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center'
    },
    dangerouslySetInnerHTML: {
      __html: ic(SB_ICONS.gear, 18)
    }
  }), /*#__PURE__*/React.createElement("div", {
    className: "sbv-avatar",
    style: {
      width: 32,
      height: 32,
      fontSize: 11
    }
  }, "MD"))), open && /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      padding: '14px 12px',
      overflow: 'hidden'
    },
    className: "sbv-fade"
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 8,
      marginBottom: 10
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: 'Chubbo',
      fontWeight: 700,
      fontSize: 14
    }
  }, rail.find(r => r[0] === tab)[1]), /*#__PURE__*/React.createElement("span", {
    className: "sbv-counter"
  }, "24"), /*#__PURE__*/React.createElement("button", {
    style: {
      marginLeft: 'auto',
      width: 26,
      height: 26,
      border: '1px dashed rgba(25,25,36,.2)',
      borderRadius: 6,
      background: 'transparent',
      cursor: 'pointer'
    },
    dangerouslySetInnerHTML: {
      __html: ic(SB_ICONS.plus, 13)
    }
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'relative',
      marginBottom: 10
    }
  }, /*#__PURE__*/React.createElement("input", {
    placeholder: "Search\u2026",
    style: {
      width: '100%',
      height: 30,
      padding: '0 10px 0 28px',
      borderRadius: 7,
      border: '1px solid rgba(25,25,36,.1)',
      background: '#fff',
      fontSize: 12,
      fontFamily: 'inherit'
    }
  }), /*#__PURE__*/React.createElement("span", {
    style: {
      position: 'absolute',
      left: 8,
      top: 7,
      color: '#B5B1A7'
    },
    dangerouslySetInnerHTML: {
      __html: ic(SB_ICONS.search, 14)
    }
  })), /*#__PURE__*/React.createElement("div", {
    className: "sbv-sec-t"
  }, "Pinned"), ['Build landing page', 'Standardize fonts'].map((t, i) => /*#__PURE__*/React.createElement("div", {
    key: i,
    className: "sbv-item",
    style: {
      fontSize: 12
    }
  }, t)), /*#__PURE__*/React.createElement("div", {
    className: "sbv-sec-t"
  }, "Today"), ['Marketing brochures', 'Mobile landing', 'Claude group bot'].map((t, i) => /*#__PURE__*/React.createElement("div", {
    key: i,
    className: 'sbv-item' + (i === 1 ? ' active' : ''),
    style: {
      fontSize: 12
    }
  }, t)))), /*#__PURE__*/React.createElement("div", {
    className: "sbv-main"
  }, /*#__PURE__*/React.createElement("div", {
    className: "sbv-title"
  }, "V2 \xB7 Icon rail + drawer"), /*#__PURE__*/React.createElement("div", {
    className: "sbv-main-copy"
  }, /*#__PURE__*/React.createElement("small", null, "Two-column"), "Split rail.")));
}

// ══════════════ V3 — Pillar-coded (D·O·T·S as groups) ══════════════
function SBV3() {
  const [open, toggle] = useCollapse(false);
  const groups = [['D', 'Data', ['Datasets', 'Embeddings', 'Pipelines']], ['O', 'Ops', ['Deployments', 'Monitors', 'Incidents']], ['T', 'Tech', ['Models', 'Agents', 'Evals']], ['S', 'Strategy', ['Roadmap', 'OKRs', 'Metrics']]];
  return /*#__PURE__*/React.createElement("div", {
    className: "sbv-root sbv-v3"
  }, /*#__PURE__*/React.createElement("button", {
    className: "sbv-demo-btn",
    onClick: toggle
  }, open ? 'Collapse' : 'Expand'), /*#__PURE__*/React.createElement("aside", {
    style: {
      width: open ? 280 : 64,
      background: '#FDFCFA',
      borderRight: '1px solid rgba(25,25,36,.08)',
      padding: '12px 8px',
      transition: 'width .28s',
      overflow: 'hidden',
      display: 'flex',
      flexDirection: 'column'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      padding: '6px 6px 12px',
      borderBottom: '1px solid rgba(25,25,36,.06)',
      marginBottom: 8
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: 4
    }
  }, ['D', 'O', 'T', 'S'].map(k => /*#__PURE__*/React.createElement("div", {
    key: k,
    style: {
      flex: 1,
      height: 28,
      borderRadius: 6,
      background: PILLAR_PASTEL[k],
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      fontFamily: 'Chubbo',
      fontWeight: 800,
      fontSize: 11,
      color: PILLAR[k]
    }
  }, k)))), groups.map(([k, name, items]) => /*#__PURE__*/React.createElement("div", {
    key: k,
    style: {
      marginBottom: 8
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 8,
      padding: '6px 8px'
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      width: 22,
      height: 22,
      borderRadius: 5,
      background: PILLAR_PASTEL[k],
      color: PILLAR[k],
      fontFamily: 'Chubbo',
      fontWeight: 800,
      fontSize: 11,
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      flexShrink: 0
    }
  }, k), open && /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 12,
      fontWeight: 600,
      color: '#191924'
    }
  }, name), open && /*#__PURE__*/React.createElement("span", {
    className: "sbv-counter"
  }, items.length)), open && items.map(t => /*#__PURE__*/React.createElement("div", {
    key: t,
    className: "sbv-item",
    style: {
      fontSize: 12,
      padding: '5px 10px 5px 34px'
    }
  }, t)))), /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: 'auto',
      padding: '10px 6px 0',
      borderTop: '1px solid rgba(25,25,36,.06)'
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "sbv-profile",
    style: {
      padding: '6px'
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "sbv-avatar",
    style: {
      background: 'linear-gradient(135deg,#C8B6FF,#A2D2FF)'
    }
  }, "MD"), open && /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 12,
      fontWeight: 600
    }
  }, "Meet D."), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 10,
      color: '#918D82'
    }
  }, "All pillars"))))), /*#__PURE__*/React.createElement("div", {
    className: "sbv-main"
  }, /*#__PURE__*/React.createElement("div", {
    className: "sbv-title"
  }, "V3 \xB7 Pillar-coded groups"), /*#__PURE__*/React.createElement("div", {
    className: "sbv-main-copy"
  }, /*#__PURE__*/React.createElement("small", null, "D\xB7O\xB7T\xB7S"), "Four columns.")));
}

// ══════════════ V4 — Dark canvas with glow ══════════════
function SBV4() {
  const [open, toggle] = useCollapse(false);
  return /*#__PURE__*/React.createElement("div", {
    className: "sbv-root sbv-v4"
  }, /*#__PURE__*/React.createElement("button", {
    className: "sbv-demo-btn",
    onClick: toggle
  }, open ? 'Collapse' : 'Expand'), /*#__PURE__*/React.createElement("aside", {
    style: {
      width: open ? 270 : 64,
      background: '#191924',
      color: '#FDFCFA',
      padding: '12px 10px',
      transition: 'width .28s',
      overflow: 'hidden',
      display: 'flex',
      flexDirection: 'column',
      position: 'relative'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      inset: 0,
      background: 'radial-gradient(circle at 50% 15%, rgba(91,63,212,.35), transparent 60%)',
      pointerEvents: 'none'
    }
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'relative'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 8,
      padding: '4px',
      marginBottom: 14
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      width: 30,
      height: 30,
      borderRadius: 8,
      background: 'linear-gradient(135deg,#5B3FD4,#C8B6FF)',
      boxShadow: '0 0 20px rgba(91,63,212,.6)',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      fontFamily: 'Chubbo',
      fontWeight: 900,
      fontSize: 11,
      color: '#191924'
    }
  }, "01"), open && /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: 'Chubbo',
      fontWeight: 700,
      fontSize: 13,
      letterSpacing: 1
    }
  }, "DOTS", /*#__PURE__*/React.createElement("span", {
    style: {
      color: '#C8B6FF'
    }
  }, "\xB7"), "AI")), [['New', SB_ICONS.plus], ['Search', SB_ICONS.search], ['Pinned', SB_ICONS.pin], ['Library', SB_ICONS.folder]].map(([l, d]) => /*#__PURE__*/React.createElement("div", {
    key: l,
    className: "sbv-item",
    style: {
      color: '#C8B6FF'
    },
    dangerouslySetInnerHTML: {
      __html: ic(d) + (open ? `<span style="color:#FDFCFA">${l}</span>` : '')
    }
  })), open && /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("div", {
    className: "sbv-sec-t",
    style: {
      color: 'rgba(253,252,250,.4)'
    }
  }, "Compartments"), [['Projects', 7, '#C8B6FF'], ['Agents', 3, '#B8E6D3'], ['Sources', 12, '#FFCDB2']].map(([l, n, c]) => /*#__PURE__*/React.createElement("div", {
    key: l,
    className: "sbv-item",
    style: {
      color: '#FDFCFA'
    }
  }, /*#__PURE__*/React.createElement("span", {
    className: "sbv-dot",
    style: {
      background: c,
      boxShadow: `0 0 8px ${c}`
    }
  }), /*#__PURE__*/React.createElement("span", null, l), /*#__PURE__*/React.createElement("span", {
    className: "sbv-counter",
    style: {
      color: 'rgba(253,252,250,.4)'
    }
  }, n))))), /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: 'auto',
      position: 'relative',
      paddingTop: 10,
      borderTop: '1px solid rgba(253,252,250,.08)'
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "sbv-profile"
  }, /*#__PURE__*/React.createElement("div", {
    className: "sbv-avatar",
    style: {
      boxShadow: '0 0 14px rgba(200,182,255,.5)'
    }
  }, "MD"), open && /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 12,
      fontWeight: 600
    }
  }, "Meet Deshani"), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 10,
      color: 'rgba(253,252,250,.5)'
    }
  }, "\u25CF Online"))))), /*#__PURE__*/React.createElement("div", {
    className: "sbv-main"
  }, /*#__PURE__*/React.createElement("div", {
    className: "sbv-title"
  }, "V4 \xB7 Dark canvas glow"), /*#__PURE__*/React.createElement("div", {
    className: "sbv-main-copy"
  }, /*#__PURE__*/React.createElement("small", null, "Ink + violet"), "Focus mode.")));
}

// ══════════════ V5 — Floating island ══════════════
function SBV5() {
  const [open, toggle] = useCollapse(false);
  return /*#__PURE__*/React.createElement("div", {
    className: "sbv-root sbv-v5",
    style: {
      background: 'linear-gradient(180deg,#F2F0EC,#E8E6E0)'
    }
  }, /*#__PURE__*/React.createElement("button", {
    className: "sbv-demo-btn",
    onClick: toggle
  }, open ? 'Collapse' : 'Expand'), /*#__PURE__*/React.createElement("aside", {
    style: {
      width: open ? 260 : 72,
      margin: 16,
      borderRadius: 18,
      background: '#FDFCFA',
      boxShadow: '0 10px 40px rgba(25,25,36,.08),0 1px 0 rgba(255,255,255,.8) inset',
      padding: '14px 10px',
      transition: 'width .28s',
      overflow: 'hidden',
      display: 'flex',
      flexDirection: 'column'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 10,
      padding: '4px 6px',
      marginBottom: 12
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      width: 32,
      height: 32,
      borderRadius: 10,
      background: '#191924',
      color: '#C8B6FF',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      fontFamily: 'Chubbo',
      fontWeight: 900,
      fontSize: 12
    }
  }, "01"), open && /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: 'Chubbo',
      fontWeight: 700,
      fontSize: 12,
      letterSpacing: 1
    }
  }, "DOTS\xB7AI"), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 9,
      color: '#918D82',
      fontFamily: 'JetBrains Mono',
      letterSpacing: 1.5,
      textTransform: 'uppercase'
    }
  }, "Private AI"))), [['New session', SB_ICONS.plus, '⌘N'], ['Search', SB_ICONS.search, '⌘K'], ['Pinned', SB_ICONS.pin], ['Routines', SB_ICONS.bolt]].map(([l, d, k]) => /*#__PURE__*/React.createElement("div", {
    key: l,
    className: "sbv-item",
    dangerouslySetInnerHTML: {
      __html: ic(d) + (open ? `<span>${l}</span>${k ? `<span class="sbv-kbd">${k}</span>` : ''}` : '')
    }
  })), open && /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: 8,
      padding: 10,
      borderRadius: 12,
      background: 'linear-gradient(135deg,#C8B6FF,#A2D2FF)',
      color: '#191924'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: 'JetBrains Mono',
      fontSize: 9,
      letterSpacing: 1.5,
      textTransform: 'uppercase',
      marginBottom: 3
    }
  }, "Pro tip"), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 11,
      lineHeight: 1.4
    }
  }, "Drag compartments to reorder. Long-press to pin.")), /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: 'auto',
      paddingTop: 10
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "sbv-profile",
    style: {
      background: 'rgba(25,25,36,.03)',
      borderRadius: 12
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "sbv-avatar"
  }, "MD"), open && /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 12,
      fontWeight: 600
    }
  }, "Meet Deshani"), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 10,
      color: '#918D82'
    }
  }, "Tier: Pro"))))), /*#__PURE__*/React.createElement("div", {
    className: "sbv-main"
  }, /*#__PURE__*/React.createElement("div", {
    className: "sbv-title"
  }, "V5 \xB7 Floating island"), /*#__PURE__*/React.createElement("div", {
    className: "sbv-main-copy"
  }, /*#__PURE__*/React.createElement("small", null, "Detached"), "Airy shell.")));
}

// ══════════════ V6 — Filter-first (all filters visible) ══════════════
function SBV6() {
  const [open, toggle] = useCollapse(false);
  const [fs, setFs] = React.useState({
    pillar: 'D',
    status: 'active',
    owner: 'me'
  });
  return /*#__PURE__*/React.createElement("div", {
    className: "sbv-root sbv-v6"
  }, /*#__PURE__*/React.createElement("button", {
    className: "sbv-demo-btn",
    onClick: toggle
  }, open ? 'Collapse' : 'Expand'), /*#__PURE__*/React.createElement("aside", {
    style: {
      width: open ? 288 : 64,
      background: '#FDFCFA',
      borderRight: '1px solid rgba(25,25,36,.08)',
      padding: '14px 10px',
      transition: 'width .28s',
      overflow: 'hidden',
      display: 'flex',
      flexDirection: 'column'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 8,
      marginBottom: 12,
      padding: '0 4px'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      width: 28,
      height: 28,
      borderRadius: 7,
      background: '#191924',
      color: '#C8B6FF',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      fontFamily: 'Chubbo',
      fontWeight: 900,
      fontSize: 11
    }
  }, "01"), open && /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: 'Chubbo',
      fontWeight: 700,
      fontSize: 13
    }
  }, "FILTERS")), open ? /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("div", {
    className: "sbv-sec-t"
  }, "Pillar"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: 4,
      padding: '0 6px'
    }
  }, ['D', 'O', 'T', 'S'].map(k => /*#__PURE__*/React.createElement("button", {
    key: k,
    onClick: () => setFs({
      ...fs,
      pillar: k
    }),
    style: {
      flex: 1,
      height: 30,
      borderRadius: 6,
      border: 'none',
      background: fs.pillar === k ? PILLAR[k] : PILLAR_PASTEL[k],
      color: fs.pillar === k ? '#fff' : PILLAR[k],
      fontFamily: 'Chubbo',
      fontWeight: 700,
      fontSize: 11,
      cursor: 'pointer'
    }
  }, k))), /*#__PURE__*/React.createElement("div", {
    className: "sbv-sec-t"
  }, "Status"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexWrap: 'wrap',
      gap: 4,
      padding: '0 6px'
    }
  }, ['active', 'draft', 'archived', 'shared'].map(s => /*#__PURE__*/React.createElement("button", {
    key: s,
    onClick: () => setFs({
      ...fs,
      status: s
    }),
    style: {
      padding: '4px 10px',
      borderRadius: 99,
      border: '1px solid ' + (fs.status === s ? '#191924' : 'rgba(25,25,36,.12)'),
      background: fs.status === s ? '#191924' : '#fff',
      color: fs.status === s ? '#fff' : '#4A4842',
      fontSize: 11,
      cursor: 'pointer'
    }
  }, s))), /*#__PURE__*/React.createElement("div", {
    className: "sbv-sec-t"
  }, "Owner"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: 4,
      padding: '0 6px'
    }
  }, ['me', 'team', 'all'].map(s => /*#__PURE__*/React.createElement("button", {
    key: s,
    onClick: () => setFs({
      ...fs,
      owner: s
    }),
    style: {
      flex: 1,
      padding: '5px 0',
      borderRadius: 6,
      border: '1px solid ' + (fs.owner === s ? '#191924' : 'rgba(25,25,36,.12)'),
      background: fs.owner === s ? '#191924' : '#fff',
      color: fs.owner === s ? '#fff' : '#4A4842',
      fontSize: 11,
      cursor: 'pointer',
      textTransform: 'capitalize'
    }
  }, s))), /*#__PURE__*/React.createElement("div", {
    className: "sbv-sec-t"
  }, "Results"), ['Build landing page', 'Font standardization', 'Mobile brochures'].map((t, i) => /*#__PURE__*/React.createElement("div", {
    key: i,
    className: "sbv-item",
    style: {
      fontSize: 12
    }
  }, /*#__PURE__*/React.createElement("span", {
    className: "sbv-dot",
    style: {
      background: PILLAR[fs.pillar]
    }
  }), /*#__PURE__*/React.createElement("span", null, t)))) : /*#__PURE__*/React.createElement(React.Fragment, null, [SB_ICONS.filter, SB_ICONS.search, SB_ICONS.star, SB_ICONS.folder].map((d, i) => /*#__PURE__*/React.createElement("div", {
    key: i,
    className: "sbv-item",
    dangerouslySetInnerHTML: {
      __html: ic(d)
    }
  }))), /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: 'auto',
      paddingTop: 10,
      borderTop: '1px solid rgba(25,25,36,.06)'
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "sbv-profile"
  }, /*#__PURE__*/React.createElement("div", {
    className: "sbv-avatar"
  }, "MD"), open && /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 12,
      fontWeight: 600
    }
  }, "3 filters active"), /*#__PURE__*/React.createElement("button", {
    style: {
      background: 'none',
      border: 'none',
      color: '#5B3FD4',
      fontSize: 10,
      padding: 0,
      cursor: 'pointer'
    }
  }, "Clear all"))))), /*#__PURE__*/React.createElement("div", {
    className: "sbv-main"
  }, /*#__PURE__*/React.createElement("div", {
    className: "sbv-title"
  }, "V6 \xB7 Filter-first"), /*#__PURE__*/React.createElement("div", {
    className: "sbv-main-copy"
  }, /*#__PURE__*/React.createElement("small", null, "Nav as query"), "All facets.")));
}

// ══════════════ V7 — Editorial / magazine ══════════════
function SBV7() {
  const [open, toggle] = useCollapse(false);
  return /*#__PURE__*/React.createElement("div", {
    className: "sbv-root sbv-v7",
    style: {
      background: '#F2F0EC'
    }
  }, /*#__PURE__*/React.createElement("button", {
    className: "sbv-demo-btn",
    onClick: toggle
  }, open ? 'Collapse' : 'Expand'), /*#__PURE__*/React.createElement("aside", {
    style: {
      width: open ? 300 : 60,
      background: '#FDFCFA',
      padding: open ? '24px 22px' : '18px 10px',
      transition: 'all .28s',
      overflow: 'hidden',
      display: 'flex',
      flexDirection: 'column',
      borderRight: '1px solid #E8E6E0'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: 'JetBrains Mono',
      fontSize: 9,
      letterSpacing: 2.5,
      textTransform: 'uppercase',
      color: '#918D82',
      marginBottom: 4
    }
  }, "Chapter 01"), open && /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: 'Chubbo,Chubbo,sans-serif',
      fontSize: 32,
      fontWeight: 700,
      lineHeight: 1,
      letterSpacing: '-.01em',
      marginBottom: 20,
      color: '#191924'
    }
  }, "Sessions", /*#__PURE__*/React.createElement("span", {
    style: {
      color: '#5B3FD4'
    }
  }, ".")), [['01', 'New session'], ['02', 'Pinned'], ['03', 'Routines'], ['04', 'Library']].map(([n, t]) => /*#__PURE__*/React.createElement("div", {
    key: n,
    style: {
      display: 'flex',
      alignItems: 'baseline',
      gap: 12,
      padding: '8px 0',
      borderBottom: '1px solid rgba(25,25,36,.06)',
      cursor: 'pointer'
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: 'JetBrains Mono',
      fontSize: 10,
      color: '#918D82',
      letterSpacing: 1.5,
      flexShrink: 0
    }
  }, n), open && /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 14,
      fontWeight: 500,
      color: '#191924'
    }
  }, t))), /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: 'auto'
    }
  }, open && /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 11,
      lineHeight: 1.5,
      color: '#6E6B62',
      marginBottom: 14,
      fontFamily: 'Satoshi'
    }
  }, "\"Build private AI, on your terms.\" \u2014 founder, 2026"), /*#__PURE__*/React.createElement("div", {
    className: "sbv-profile"
  }, /*#__PURE__*/React.createElement("div", {
    className: "sbv-avatar"
  }, "MD"), open && /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 12,
      fontWeight: 600
    }
  }, "Meet D."), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 10,
      color: '#918D82'
    }
  }, "Editor"))))), /*#__PURE__*/React.createElement("div", {
    className: "sbv-main"
  }, /*#__PURE__*/React.createElement("div", {
    className: "sbv-title"
  }, "V7 \xB7 Editorial"), /*#__PURE__*/React.createElement("div", {
    className: "sbv-main-copy"
  }, /*#__PURE__*/React.createElement("small", null, "Magazine"), "Serif soul.")));
}

// ══════════════ V8 — Terminal / mono-grid ══════════════
function SBV8() {
  const [open, toggle] = useCollapse(false);
  return /*#__PURE__*/React.createElement("div", {
    className: "sbv-root sbv-v8"
  }, /*#__PURE__*/React.createElement("button", {
    className: "sbv-demo-btn",
    onClick: toggle
  }, open ? 'Collapse' : 'Expand'), /*#__PURE__*/React.createElement("aside", {
    style: {
      width: open ? 280 : 64,
      background: '#0D0D14',
      color: '#C8B6FF',
      fontFamily: 'JetBrains Mono,JetBrains Mono,monospace',
      padding: '12px 8px',
      transition: 'width .28s',
      overflow: 'hidden',
      display: 'flex',
      flexDirection: 'column',
      borderRight: '1px solid rgba(200,182,255,.15)'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 10,
      letterSpacing: 2,
      padding: '4px 8px 12px',
      color: 'rgba(200,182,255,.6)',
      borderBottom: '1px dashed rgba(200,182,255,.15)',
      marginBottom: 8
    }
  }, open ? '// dots@ai ~ $ _' : '$'), [['> new', '⌘N'], ['> search', '⌘K'], ['> pin'], ['> lib'], ['> agents'], ['> settings']].map(([cmd, kb]) => /*#__PURE__*/React.createElement("div", {
    key: cmd,
    style: {
      padding: '5px 8px',
      fontSize: 11,
      display: 'flex',
      alignItems: 'center',
      cursor: 'pointer',
      borderRadius: 3
    },
    onMouseEnter: e => e.currentTarget.style.background = 'rgba(200,182,255,.08)',
    onMouseLeave: e => e.currentTarget.style.background = 'transparent'
  }, /*#__PURE__*/React.createElement("span", null, open ? cmd : cmd[2]), open && kb && /*#__PURE__*/React.createElement("span", {
    style: {
      marginLeft: 'auto',
      color: 'rgba(200,182,255,.4)'
    }
  }, kb))), open && /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 9,
      letterSpacing: 2,
      color: 'rgba(200,182,255,.4)',
      padding: '14px 8px 6px'
    }
  }, "// RECENT"), ['landing.tsx', 'brochure.md', 'brief.pdf'].map((t, i) => /*#__PURE__*/React.createElement("div", {
    key: i,
    style: {
      padding: '4px 8px',
      fontSize: 11,
      color: i === 0 ? '#C8B6FF' : 'rgba(200,182,255,.6)'
    }
  }, i === 0 ? '▸ ' : '  ', t))), /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: 'auto',
      padding: '10px 8px',
      borderTop: '1px dashed rgba(200,182,255,.15)',
      fontSize: 10,
      display: 'flex',
      alignItems: 'center',
      gap: 8
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      width: 8,
      height: 8,
      borderRadius: '50%',
      background: '#B8E6D3',
      boxShadow: '0 0 6px #B8E6D3'
    }
  }), open ? /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("span", {
    style: {
      color: '#FDFCFA'
    }
  }, "meet@dotsai.in"), /*#__PURE__*/React.createElement("span", {
    style: {
      marginLeft: 'auto',
      color: 'rgba(200,182,255,.4)'
    }
  }, "v2.0")) : null)), /*#__PURE__*/React.createElement("div", {
    className: "sbv-main"
  }, /*#__PURE__*/React.createElement("div", {
    className: "sbv-title"
  }, "V8 \xB7 Terminal"), /*#__PURE__*/React.createElement("div", {
    className: "sbv-main-copy"
  }, /*#__PURE__*/React.createElement("small", null, "Power user"), "Command.")));
}

// ══════════════ V9 — Hover-reveal rail ══════════════
function SBV9() {
  const [hov, setHov] = React.useState(false);
  return /*#__PURE__*/React.createElement("div", {
    className: "sbv-root sbv-v9"
  }, /*#__PURE__*/React.createElement("div", {
    className: "sbv-demo-btn",
    style: {
      cursor: 'default'
    }
  }, "Hover to reveal"), /*#__PURE__*/React.createElement("aside", {
    onMouseEnter: () => setHov(true),
    onMouseLeave: () => setHov(false),
    style: {
      width: hov ? 240 : 48,
      background: '#FDFCFA',
      borderRight: '1px solid rgba(25,25,36,.08)',
      padding: '10px 6px',
      transition: 'width .24s cubic-bezier(.2,.7,.3,1)',
      overflow: 'hidden',
      display: 'flex',
      flexDirection: 'column',
      boxShadow: hov ? '0 10px 40px rgba(25,25,36,.12)' : 'none'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      width: 30,
      height: 30,
      borderRadius: 7,
      background: '#191924',
      color: '#C8B6FF',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      fontFamily: 'Chubbo',
      fontWeight: 900,
      fontSize: 11,
      margin: '2px 4px 10px'
    }
  }, "01"), [['New session', SB_ICONS.plus, '#5B3FD4'], ['Search', SB_ICONS.search, '#2563B8'], ['Pinned', SB_ICONS.pin, '#C65D2E'], ['Routines', SB_ICONS.bolt, '#2A9D6E'], ['Library', SB_ICONS.folder, '#918D82']].map(([l, d, c]) => /*#__PURE__*/React.createElement("div", {
    key: l,
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 12,
      padding: '9px 8px',
      borderRadius: 7,
      cursor: 'pointer',
      color: '#4A4842'
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      color: c
    },
    dangerouslySetInnerHTML: {
      __html: ic(d, 18)
    }
  }), hov && /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 13,
      whiteSpace: 'nowrap'
    },
    className: "sbv-fade"
  }, l))), /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: 'auto',
      padding: '8px 6px 4px'
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "sbv-profile",
    style: {
      padding: 4,
      gap: 10
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "sbv-avatar",
    style: {
      width: 30,
      height: 30,
      fontSize: 11
    }
  }, "MD"), hov && /*#__PURE__*/React.createElement("div", {
    className: "sbv-fade"
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 12,
      fontWeight: 600,
      whiteSpace: 'nowrap'
    }
  }, "Meet Deshani"), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 10,
      color: '#918D82'
    }
  }, "Pro"))))), /*#__PURE__*/React.createElement("div", {
    className: "sbv-main"
  }, /*#__PURE__*/React.createElement("div", {
    className: "sbv-title"
  }, "V9 \xB7 Hover-reveal"), /*#__PURE__*/React.createElement("div", {
    className: "sbv-main-copy"
  }, /*#__PURE__*/React.createElement("small", null, "Always slim"), "Space first.")));
}

// ══════════════ V10 — Omnibox + command ══════════════
function SBV10() {
  const [open, toggle] = useCollapse(false);
  return /*#__PURE__*/React.createElement("div", {
    className: "sbv-root sbv-v10"
  }, /*#__PURE__*/React.createElement("button", {
    className: "sbv-demo-btn",
    onClick: toggle
  }, open ? 'Collapse' : 'Expand'), /*#__PURE__*/React.createElement("aside", {
    style: {
      width: open ? 290 : 64,
      background: '#FDFCFA',
      borderRight: '1px solid rgba(25,25,36,.08)',
      padding: '12px 10px',
      transition: 'width .28s',
      overflow: 'hidden',
      display: 'flex',
      flexDirection: 'column'
    }
  }, open ? /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'relative',
      marginBottom: 14
    }
  }, /*#__PURE__*/React.createElement("input", {
    placeholder: "Type / for commands\u2026",
    style: {
      width: '100%',
      height: 36,
      padding: '0 12px 0 34px',
      borderRadius: 10,
      border: '1.5px solid #191924',
      background: '#fff',
      fontSize: 12,
      fontFamily: 'Satoshi',
      outline: 'none'
    }
  }), /*#__PURE__*/React.createElement("span", {
    style: {
      position: 'absolute',
      left: 10,
      top: 10,
      color: '#191924'
    },
    dangerouslySetInnerHTML: {
      __html: ic(SB_ICONS.search, 15)
    }
  }), /*#__PURE__*/React.createElement("span", {
    style: {
      position: 'absolute',
      right: 8,
      top: 8,
      fontFamily: 'JetBrains Mono',
      fontSize: 9,
      padding: '3px 6px',
      borderRadius: 4,
      background: 'rgba(25,25,36,.08)',
      color: '#6E6B62',
      letterSpacing: 1
    }
  }, "\u2318K")) : /*#__PURE__*/React.createElement("div", {
    style: {
      width: 40,
      height: 40,
      borderRadius: 10,
      background: '#191924',
      color: '#FDFCFA',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      margin: '0 auto 14px',
      cursor: 'pointer'
    },
    dangerouslySetInnerHTML: {
      __html: ic(SB_ICONS.search, 18)
    }
  }), open && /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("div", {
    className: "sbv-sec-t",
    style: {
      color: '#5B3FD4'
    }
  }, "Quick commands"), [['/ new', 'New session'], ['/ pin', 'Pin current'], ['/ route', 'Run routine'], ['/ ask', 'Ask agent']].map(([c, t]) => /*#__PURE__*/React.createElement("div", {
    key: c,
    className: "sbv-item",
    style: {
      fontSize: 12
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: 'JetBrains Mono',
      fontSize: 10,
      color: '#5B3FD4',
      background: 'rgba(91,63,212,.08)',
      padding: '2px 6px',
      borderRadius: 4
    }
  }, c), /*#__PURE__*/React.createElement("span", {
    style: {
      color: '#4A4842'
    }
  }, t))), /*#__PURE__*/React.createElement("div", {
    className: "sbv-sec-t"
  }, "Recent"), ['Build landing page', 'Font standard', 'Mobile brochures'].map((t, i) => /*#__PURE__*/React.createElement("div", {
    key: i,
    className: 'sbv-item' + (i === 0 ? ' active' : ''),
    style: {
      fontSize: 12
    }
  }, t))), /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: 'auto',
      paddingTop: 10,
      borderTop: '1px solid rgba(25,25,36,.06)'
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "sbv-profile"
  }, /*#__PURE__*/React.createElement("div", {
    className: "sbv-avatar"
  }, "MD"), open && /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 12,
      fontWeight: 600
    }
  }, "Meet D."), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 10,
      color: '#918D82'
    }
  }, "\u2318K from anywhere"))))), /*#__PURE__*/React.createElement("div", {
    className: "sbv-main"
  }, /*#__PURE__*/React.createElement("div", {
    className: "sbv-title"
  }, "V10 \xB7 Omnibox"), /*#__PURE__*/React.createElement("div", {
    className: "sbv-main-copy"
  }, /*#__PURE__*/React.createElement("small", null, "Slash first"), "Keyboard.")));
}

// ══════════════ V11 — Layered drawer (workspaces + projects) ══════════════
function SBV11() {
  const [open, toggle] = useCollapse(false);
  const [ws, setWs] = React.useState(0);
  const wss = [['ZeroOne HQ', '#5B3FD4'], ['Client · Acme', '#2A9D6E'], ['Personal', '#C65D2E']];
  return /*#__PURE__*/React.createElement("div", {
    className: "sbv-root sbv-v11"
  }, /*#__PURE__*/React.createElement("button", {
    className: "sbv-demo-btn",
    onClick: toggle
  }, open ? 'Collapse' : 'Expand'), /*#__PURE__*/React.createElement("aside", {
    style: {
      display: 'flex',
      transition: 'width .28s',
      width: open ? 340 : 60,
      overflow: 'hidden',
      borderRight: '1px solid rgba(25,25,36,.08)'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      width: 60,
      background: '#191924',
      padding: '10px 0',
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      gap: 8,
      flexShrink: 0
    }
  }, wss.map(([n, c], i) => /*#__PURE__*/React.createElement("button", {
    key: i,
    onClick: () => setWs(i),
    title: n,
    style: {
      width: 42,
      height: 42,
      borderRadius: 11,
      border: ws === i ? '2px solid #FDFCFA' : '2px solid transparent',
      background: c,
      color: '#fff',
      cursor: 'pointer',
      fontFamily: 'Chubbo',
      fontWeight: 800,
      fontSize: 14
    }
  }, n[0])), /*#__PURE__*/React.createElement("button", {
    style: {
      width: 42,
      height: 42,
      borderRadius: 11,
      border: '1.5px dashed rgba(253,252,250,.3)',
      background: 'transparent',
      color: 'rgba(253,252,250,.5)',
      cursor: 'pointer'
    },
    dangerouslySetInnerHTML: {
      __html: ic(SB_ICONS.plus, 16)
    }
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: 'auto',
      paddingBottom: 6
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "sbv-avatar",
    style: {
      width: 36,
      height: 36
    }
  }, "MD"))), open && /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      padding: '14px 12px',
      display: 'flex',
      flexDirection: 'column'
    },
    className: "sbv-fade"
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 8,
      marginBottom: 12
    }
  }, /*#__PURE__*/React.createElement("span", {
    className: "sbv-dot",
    style: {
      background: wss[ws][1],
      width: 10,
      height: 10
    }
  }), /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: 'Chubbo',
      fontWeight: 700,
      fontSize: 14
    }
  }, wss[ws][0]), /*#__PURE__*/React.createElement("span", {
    className: "sbv-counter"
  }, "12")), /*#__PURE__*/React.createElement("div", {
    className: "sbv-sec-t"
  }, "Quick actions"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'grid',
      gridTemplateColumns: '1fr 1fr',
      gap: 6,
      padding: '0 4px'
    }
  }, [['New', SB_ICONS.plus], ['Invite', SB_ICONS.user], ['Routines', SB_ICONS.bolt], ['Library', SB_ICONS.folder]].map(([l, d]) => /*#__PURE__*/React.createElement("button", {
    key: l,
    style: {
      padding: '10px 6px',
      borderRadius: 8,
      border: '1px solid rgba(25,25,36,.08)',
      background: '#fff',
      color: '#4A4842',
      fontSize: 11,
      cursor: 'pointer',
      display: 'flex',
      alignItems: 'center',
      gap: 6,
      fontFamily: 'inherit'
    }
  }, /*#__PURE__*/React.createElement("span", {
    dangerouslySetInnerHTML: {
      __html: ic(d, 14)
    }
  }), l))), /*#__PURE__*/React.createElement("div", {
    className: "sbv-sec-t"
  }, "Projects"), ['Landing v2', 'Brochures', 'Mobile app'].map((t, i) => /*#__PURE__*/React.createElement("div", {
    key: i,
    className: 'sbv-item' + (i === 0 ? ' active' : ''),
    style: {
      fontSize: 12
    }
  }, t)))), /*#__PURE__*/React.createElement("div", {
    className: "sbv-main"
  }, /*#__PURE__*/React.createElement("div", {
    className: "sbv-title"
  }, "V11 \xB7 Layered workspaces"), /*#__PURE__*/React.createElement("div", {
    className: "sbv-main-copy"
  }, /*#__PURE__*/React.createElement("small", null, "Multi-org"), "Stacked.")));
}

// ══════════════ V12 — Bento grid sidebar ══════════════
function SBV12() {
  const [open, toggle] = useCollapse(false);
  return /*#__PURE__*/React.createElement("div", {
    className: "sbv-root sbv-v12",
    style: {
      background: '#F2F0EC'
    }
  }, /*#__PURE__*/React.createElement("button", {
    className: "sbv-demo-btn",
    onClick: toggle
  }, open ? 'Collapse' : 'Expand'), /*#__PURE__*/React.createElement("aside", {
    style: {
      width: open ? 300 : 72,
      padding: '14px 10px',
      transition: 'width .28s',
      overflow: 'hidden',
      display: 'flex',
      flexDirection: 'column',
      gap: 8
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      background: '#191924',
      color: '#FDFCFA',
      borderRadius: 14,
      padding: open ? '14px' : '10px',
      display: 'flex',
      alignItems: 'center',
      gap: 10
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      width: 32,
      height: 32,
      borderRadius: 8,
      background: '#C8B6FF',
      color: '#191924',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      fontFamily: 'Chubbo',
      fontWeight: 900,
      fontSize: 12
    }
  }, "01"), open && /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: 'Chubbo',
      fontWeight: 700,
      fontSize: 13
    }
  }, "DOTS\xB7AI"), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 9,
      color: 'rgba(253,252,250,.5)',
      fontFamily: 'JetBrains Mono',
      letterSpacing: 1.5,
      textTransform: 'uppercase'
    }
  }, "Workstream"))), open ? /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'grid',
      gridTemplateColumns: '1fr 1fr',
      gap: 8
    }
  }, [['New', SB_ICONS.plus, '#C8B6FF'], ['Search', SB_ICONS.search, '#B8E6D3'], ['Pin', SB_ICONS.pin, '#FFCDB2'], ['Library', SB_ICONS.folder, '#A2D2FF']].map(([l, d, c]) => /*#__PURE__*/React.createElement("div", {
    key: l,
    style: {
      background: c,
      borderRadius: 12,
      padding: '12px 10px',
      cursor: 'pointer',
      color: '#191924'
    }
  }, /*#__PURE__*/React.createElement("div", {
    dangerouslySetInnerHTML: {
      __html: ic(d, 18)
    }
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 11,
      fontWeight: 600,
      marginTop: 6
    }
  }, l)))), /*#__PURE__*/React.createElement("div", {
    style: {
      background: '#FDFCFA',
      borderRadius: 12,
      padding: '10px 12px',
      flex: 1
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "sbv-sec-t",
    style: {
      padding: 0,
      margin: '0 0 6px'
    }
  }, "Recent"), ['Landing page', 'Font standard', 'Brochures'].map((t, i) => /*#__PURE__*/React.createElement("div", {
    key: i,
    style: {
      fontSize: 12,
      padding: '5px 0',
      color: '#4A4842',
      borderBottom: i < 2 ? '1px solid rgba(25,25,36,.06)' : 'none'
    }
  }, t)))) : [SB_ICONS.plus, SB_ICONS.search, SB_ICONS.pin, SB_ICONS.folder].map((d, i) => /*#__PURE__*/React.createElement("div", {
    key: i,
    style: {
      width: 52,
      height: 52,
      borderRadius: 12,
      background: '#FDFCFA',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      cursor: 'pointer'
    },
    dangerouslySetInnerHTML: {
      __html: ic(d, 18)
    }
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      background: '#FDFCFA',
      borderRadius: 12,
      padding: '10px'
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "sbv-profile",
    style: {
      padding: 0
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "sbv-avatar"
  }, "MD"), open && /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 12,
      fontWeight: 600
    }
  }, "Meet D."), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 10,
      color: '#918D82'
    }
  }, "Pro"))))), /*#__PURE__*/React.createElement("div", {
    className: "sbv-main"
  }, /*#__PURE__*/React.createElement("div", {
    className: "sbv-title"
  }, "V12 \xB7 Bento grid"), /*#__PURE__*/React.createElement("div", {
    className: "sbv-main-copy"
  }, /*#__PURE__*/React.createElement("small", null, "Card-based"), "Blocks.")));
}
window.SidebarVariations = [{
  id: 'sbv1',
  label: 'V1 · Classic compartments',
  C: SBV1
}, {
  id: 'sbv2',
  label: 'V2 · Icon rail + drawer',
  C: SBV2
}, {
  id: 'sbv3',
  label: 'V3 · Pillar-coded groups',
  C: SBV3
}, {
  id: 'sbv4',
  label: 'V4 · Dark canvas glow',
  C: SBV4
}, {
  id: 'sbv5',
  label: 'V5 · Floating island',
  C: SBV5
}, {
  id: 'sbv6',
  label: 'V6 · Filter-first',
  C: SBV6
}, {
  id: 'sbv7',
  label: 'V7 · Editorial',
  C: SBV7
}, {
  id: 'sbv8',
  label: 'V8 · Terminal',
  C: SBV8
}, {
  id: 'sbv9',
  label: 'V9 · Hover-reveal',
  C: SBV9
}, {
  id: 'sbv10',
  label: 'V10 · Omnibox',
  C: SBV10
}, {
  id: 'sbv11',
  label: 'V11 · Layered workspaces',
  C: SBV11
}, {
  id: 'sbv12',
  label: 'V12 · Bento grid',
  C: SBV12
}];
})(); } catch (e) { __ds_ns.__errors.push({ path: "explorations/sidebar-variations.jsx", error: String((e && e.message) || e) }); }

// ui_kits/mobile/MobileScreens.jsx
try { (() => {
/* MobileScreens.jsx — D.O.T.S mobile UI kit. Screens render INSIDE the device's safe canvas; frame owns status bar / nav / home indicator. */

function Eyebrow({
  children,
  color = '#918D82',
  style = {}
}) {
  return /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: 'JetBrains Mono, JetBrains Mono, monospace',
      fontSize: 10,
      letterSpacing: 1.8,
      textTransform: 'uppercase',
      color,
      ...style
    }
  }, children);
}

// ═══ 1. HOME — uses custom top row (no standard nav) ═══
function MobileHome() {
  const pillars = [{
    k: 'D',
    nm: 'Data',
    sub: '3 sources connected',
    tint: '#EDE6FF',
    deep: '#5B3FD4'
  }, {
    k: 'O',
    nm: 'Operations',
    sub: '12 workflows running',
    tint: '#E5F3EC',
    deep: '#1F7A5C'
  }, {
    k: 'T',
    nm: 'Tech',
    sub: 'Pipeline healthy',
    tint: '#FFEFE3',
    deep: '#A8521A'
  }, {
    k: 'S',
    nm: 'Strategy',
    sub: 'Roadmap Q2 in review',
    tint: '#E5F1FF',
    deep: '#1E5B9C'
  }];
  return /*#__PURE__*/React.createElement("div", {
    style: {
      background: '#FDFCFA',
      height: '100%',
      display: 'flex',
      flexDirection: 'column',
      fontFamily: 'Satoshi'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      padding: '14px 20px 10px',
      display: 'flex',
      justifyContent: 'space-between',
      alignItems: 'center'
    }
  }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement(Eyebrow, null, "Meet Deshani"), /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: 'Chubbo',
      fontWeight: 700,
      fontSize: 22,
      color: '#191924',
      marginTop: 2,
      letterSpacing: '-0.01em'
    }
  }, "Good morning")), /*#__PURE__*/React.createElement("div", {
    style: {
      width: 40,
      height: 40,
      borderRadius: '50%',
      background: 'linear-gradient(135deg,#C8B6FF,#A2D2FF)',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      fontFamily: 'Chubbo',
      fontWeight: 700,
      color: '#191924',
      fontSize: 14
    }
  }, "MH")), /*#__PURE__*/React.createElement("div", {
    style: {
      margin: '6px 16px 14px',
      padding: '18px 18px 16px',
      borderRadius: 16,
      background: 'linear-gradient(135deg,#2D1B4E,#191924)',
      color: '#fff',
      position: 'relative',
      overflow: 'hidden'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      right: -30,
      top: -30,
      width: 120,
      height: 120,
      borderRadius: '50%',
      background: 'radial-gradient(circle,#5B3FD4 0%,transparent 70%)',
      opacity: .6
    }
  }), /*#__PURE__*/React.createElement(Eyebrow, {
    color: "rgba(255,255,255,.55)"
  }, "Margin \xB7 Q2 26"), /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: 'Chubbo',
      fontWeight: 700,
      fontSize: 44,
      lineHeight: 1,
      letterSpacing: '-0.01em',
      marginTop: 6
    }
  }, "+23%"), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 12,
      color: 'rgba(255,255,255,.65)',
      marginTop: 4
    }
  }, "Up from +18% last quarter")), /*#__PURE__*/React.createElement("div", {
    style: {
      padding: '0 16px',
      flex: 1,
      overflow: 'auto'
    }
  }, /*#__PURE__*/React.createElement(Eyebrow, {
    style: {
      marginBottom: 10
    }
  }, "Four Pillars"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 8
    }
  }, pillars.map(p => /*#__PURE__*/React.createElement("div", {
    key: p.k,
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 12,
      padding: '12px 14px',
      borderRadius: 12,
      background: '#fff',
      border: '1px solid #E8E6E0',
      minHeight: 44
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      width: 36,
      height: 36,
      borderRadius: 10,
      background: p.tint,
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      color: p.deep,
      fontFamily: 'Chubbo',
      fontWeight: 700,
      fontSize: 16
    }
  }, p.k), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      minWidth: 0
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontWeight: 600,
      fontSize: 14,
      color: '#191924'
    }
  }, p.nm), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 11,
      color: '#918D82',
      marginTop: 1
    }
  }, p.sub)), /*#__PURE__*/React.createElement("div", {
    style: {
      color: '#B5B1A7',
      fontSize: 18
    }
  }, "\u203A"))))), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      borderTop: '1px solid #E8E6E0',
      background: '#fff',
      padding: '8px 0 6px'
    }
  }, [['Home', true], ['Data', false], ['Tools', false], ['Settings', false]].map(([lbl, on]) => /*#__PURE__*/React.createElement("div", {
    key: lbl,
    style: {
      flex: 1,
      textAlign: 'center',
      minHeight: 44,
      display: 'flex',
      flexDirection: 'column',
      justifyContent: 'center',
      gap: 2
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 18,
      color: on ? '#191924' : '#918D82'
    }
  }, on ? '●' : '○'), /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: 'JetBrains Mono, monospace',
      fontSize: 9,
      letterSpacing: 1,
      textTransform: 'uppercase',
      color: on ? '#191924' : '#918D82'
    }
  }, lbl)))));
}

// ═══ 2. PILLAR DETAIL — content only; frame provides nav ═══
function MobilePillarDetail() {
  return /*#__PURE__*/React.createElement("div", {
    style: {
      background: '#FDFCFA',
      height: '100%',
      display: 'flex',
      flexDirection: 'column',
      fontFamily: 'Satoshi'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      padding: '4px 20px 14px'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'inline-flex',
      alignItems: 'center',
      gap: 6,
      padding: '4px 10px',
      borderRadius: 999,
      background: 'rgba(200,182,255,.22)',
      color: '#2D1B4E',
      fontFamily: 'JetBrains Mono, monospace',
      fontSize: 9,
      letterSpacing: 1.5,
      textTransform: 'uppercase'
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      width: 6,
      height: 6,
      borderRadius: '50%',
      background: '#C8B6FF'
    }
  }), " D \xB7 Data"), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 13,
      color: '#4A4842',
      lineHeight: 1.55,
      marginTop: 8
    }
  }, "Your data pipeline is ", /*#__PURE__*/React.createElement("em", {
    style: {
      color: '#2D1B4E',
      fontStyle: 'italic'
    }
  }, "95% ready"), ". Connect two more sources to unlock full D.O.T.S scoring.")), /*#__PURE__*/React.createElement("div", {
    style: {
      padding: '0 16px',
      display: 'grid',
      gridTemplateColumns: '1fr 1fr',
      gap: 8,
      marginBottom: 12
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      padding: 14,
      borderRadius: 12,
      background: '#fff',
      border: '1px solid #E8E6E0'
    }
  }, /*#__PURE__*/React.createElement(Eyebrow, null, "Sources"), /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: 'Chubbo',
      fontWeight: 700,
      fontSize: 26,
      color: '#191924',
      lineHeight: 1,
      marginTop: 6
    }
  }, "12"), /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: 'JetBrains Mono, monospace',
      fontSize: 10,
      color: '#0A7A5E',
      marginTop: 4,
      fontWeight: 600
    }
  }, "\u2197 +3 this week")), /*#__PURE__*/React.createElement("div", {
    style: {
      padding: 14,
      borderRadius: 12,
      background: '#fff',
      border: '1px solid #E8E6E0'
    }
  }, /*#__PURE__*/React.createElement(Eyebrow, null, "Health"), /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: 'Chubbo',
      fontWeight: 700,
      fontSize: 26,
      color: '#191924',
      lineHeight: 1,
      marginTop: 6
    }
  }, "95%"), /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: 'JetBrains Mono, monospace',
      fontSize: 10,
      color: '#0A7A5E',
      marginTop: 4,
      fontWeight: 600
    }
  }, "Healthy"))), /*#__PURE__*/React.createElement("div", {
    style: {
      padding: '0 16px',
      flex: 1,
      overflow: 'auto'
    }
  }, /*#__PURE__*/React.createElement(Eyebrow, {
    style: {
      marginBottom: 8
    }
  }, "Connected Sources"), ['Salesforce CRM', 'Stripe Ledger', 'Segment Events'].map(s => /*#__PURE__*/React.createElement("div", {
    key: s,
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 12,
      padding: '12px 14px',
      borderRadius: 10,
      background: '#fff',
      border: '1px solid #E8E6E0',
      marginBottom: 6,
      minHeight: 44
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      width: 8,
      height: 8,
      borderRadius: '50%',
      background: '#0A7A5E'
    }
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      fontSize: 13,
      fontWeight: 500,
      color: '#191924'
    }
  }, s), /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: 'JetBrains Mono, monospace',
      fontSize: 10,
      color: '#918D82'
    }
  }, "Live")))), /*#__PURE__*/React.createElement("div", {
    style: {
      padding: '12px 16px',
      borderTop: '1px solid #E8E6E0',
      background: '#FDFCFA'
    }
  }, /*#__PURE__*/React.createElement("button", {
    style: {
      width: '100%',
      minHeight: 48,
      border: 'none',
      borderRadius: 12,
      background: '#191924',
      color: '#fff',
      fontFamily: 'Satoshi',
      fontWeight: 600,
      fontSize: 14
    }
  }, "Connect another source \u2192")));
}

// ═══ 3. BOTTOM SHEET ═══
function MobileBottomSheet() {
  return /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'relative',
      background: 'linear-gradient(135deg,#2D1B4E,#191924)',
      height: '100%',
      overflow: 'hidden',
      fontFamily: 'Satoshi'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      padding: 20,
      opacity: .35
    }
  }, /*#__PURE__*/React.createElement(Eyebrow, {
    color: "rgba(255,255,255,.5)"
  }, "Dashboard"), /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: 'Chubbo',
      fontWeight: 700,
      fontSize: 32,
      color: '#fff',
      lineHeight: 1.05,
      marginTop: 6
    }
  }, "Welcome back, Meet.")), /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      inset: 0,
      background: 'rgba(0,0,0,.35)'
    }
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      left: 0,
      right: 0,
      bottom: 0,
      background: '#FDFCFA',
      borderTopLeftRadius: 20,
      borderTopRightRadius: 20,
      paddingBottom: 16,
      boxShadow: '0 -20px 60px rgba(0,0,0,.3)'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      justifyContent: 'center',
      padding: '8px 0 4px'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      width: 38,
      height: 4,
      borderRadius: 2,
      background: '#D4D1C9'
    }
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      padding: '8px 20px 12px',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between'
    }
  }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: 'Chubbo',
      fontWeight: 700,
      fontSize: 20,
      color: '#191924'
    }
  }, "Quick Actions"), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 11,
      color: '#918D82',
      marginTop: 2,
      fontFamily: 'JetBrains Mono, monospace',
      letterSpacing: 1
    }
  }, "4 SUGGESTED")), /*#__PURE__*/React.createElement("div", {
    style: {
      width: 32,
      height: 32,
      borderRadius: '50%',
      background: '#F2F0EC',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      color: '#4A4842',
      fontSize: 14
    }
  }, "\u2715")), /*#__PURE__*/React.createElement("div", {
    style: {
      padding: '0 16px 12px',
      display: 'flex',
      flexDirection: 'column',
      gap: 6
    }
  }, [{
    ic: '+',
    nm: 'Connect new data source',
    sub: 'Snowflake, BigQuery, Postgres',
    tint: '#EDE6FF',
    deep: '#5B3FD4'
  }, {
    ic: '⟳',
    nm: 'Run D.O.T.S assessment',
    sub: 'Re-score all 4 pillars',
    tint: '#E5F3EC',
    deep: '#1F7A5C'
  }, {
    ic: '◎',
    nm: 'Schedule advisor call',
    sub: 'Next: Fri 3pm IST',
    tint: '#FFEFE3',
    deep: '#A8521A'
  }, {
    ic: '⟴',
    nm: 'Export margin report',
    sub: 'PDF, last 12 months',
    tint: '#E5F1FF',
    deep: '#1E5B9C'
  }].map(a => /*#__PURE__*/React.createElement("div", {
    key: a.nm,
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 12,
      padding: '10px 12px',
      borderRadius: 12,
      background: '#fff',
      border: '1px solid #E8E6E0',
      minHeight: 48
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      width: 36,
      height: 36,
      borderRadius: 10,
      background: a.tint,
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      color: a.deep,
      fontFamily: 'Chubbo',
      fontWeight: 700,
      fontSize: 16
    }
  }, a.ic), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 13,
      fontWeight: 600,
      color: '#191924'
    }
  }, a.nm), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 10.5,
      color: '#918D82',
      marginTop: 1
    }
  }, a.sub)), /*#__PURE__*/React.createElement("div", {
    style: {
      color: '#B5B1A7',
      fontSize: 16
    }
  }, "\u203A"))))));
}

// ═══ 4. FORM — content only; frame owns top nav ═══
function MobileForm() {
  return /*#__PURE__*/React.createElement("div", {
    style: {
      background: '#FDFCFA',
      height: '100%',
      display: 'flex',
      flexDirection: 'column',
      fontFamily: 'Satoshi'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      padding: '2px 20px 8px'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 13,
      color: '#4A4842'
    }
  }, "Give it something your team will recognize.")), /*#__PURE__*/React.createElement("div", {
    style: {
      padding: '8px 16px 0',
      display: 'flex',
      flexDirection: 'column',
      gap: 14
    }
  }, /*#__PURE__*/React.createElement("label", null, /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: 'JetBrains Mono, monospace',
      fontSize: 10,
      letterSpacing: 1.5,
      textTransform: 'uppercase',
      color: '#918D82',
      marginBottom: 6
    }
  }, "Workflow name"), /*#__PURE__*/React.createElement("div", {
    style: {
      padding: '14px',
      borderRadius: 12,
      background: '#fff',
      border: '1.5px solid #5B3FD4',
      boxShadow: '0 0 0 4px rgba(200,182,255,.22)',
      display: 'flex',
      alignItems: 'center',
      minHeight: 48
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 15,
      color: '#191924'
    }
  }, "Quarterly margin report"), /*#__PURE__*/React.createElement("span", {
    style: {
      marginLeft: 4,
      width: 2,
      height: 18,
      background: '#5B3FD4'
    }
  }))), /*#__PURE__*/React.createElement("label", null, /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: 'JetBrains Mono, monospace',
      fontSize: 10,
      letterSpacing: 1.5,
      textTransform: 'uppercase',
      color: '#918D82',
      marginBottom: 6
    }
  }, "Pillar"), /*#__PURE__*/React.createElement("div", {
    style: {
      padding: '14px',
      borderRadius: 12,
      background: '#fff',
      border: '1px solid #E8E6E0',
      display: 'flex',
      justifyContent: 'space-between',
      alignItems: 'center',
      minHeight: 48
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 8
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      width: 8,
      height: 8,
      borderRadius: '50%',
      background: '#C8B6FF'
    }
  }), /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 15,
      color: '#191924'
    }
  }, "Data")), /*#__PURE__*/React.createElement("span", {
    style: {
      color: '#918D82',
      fontSize: 16
    }
  }, "\u2304"))), /*#__PURE__*/React.createElement("label", null, /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: 'JetBrains Mono, monospace',
      fontSize: 10,
      letterSpacing: 1.5,
      textTransform: 'uppercase',
      color: '#918D82',
      marginBottom: 6
    }
  }, "Description \xB7 optional"), /*#__PURE__*/React.createElement("div", {
    style: {
      padding: '14px',
      borderRadius: 12,
      background: '#fff',
      border: '1px solid #E8E6E0',
      minHeight: 64,
      fontSize: 14,
      color: '#918D82'
    }
  }, "Add context for your team\u2026"))));
}
Object.assign(window, {
  MobileHome,
  MobilePillarDetail,
  MobileBottomSheet,
  MobileForm
});
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/mobile/MobileScreens.jsx", error: String((e && e.message) || e) }); }

// ui_kits/mobile/design-canvas.jsx
try { (() => {
// DesignCanvas.jsx — Figma-ish design canvas wrapper
// Warm gray grid bg + Sections + Artboards + PostIt notes.
// Artboards are reorderable (grip-drag), labels/titles are inline-editable,
// and any artboard can be opened in a fullscreen focus overlay (←/→/Esc).
// State persists to a .design-canvas.state.json sidecar via the host
// bridge. No assets, no deps.
//
// Usage:
//   <DesignCanvas>
//     <DCSection id="onboarding" title="Onboarding" subtitle="First-run variants">
//       <DCArtboard id="a" label="A · Dusk" width={260} height={480}>…</DCArtboard>
//       <DCArtboard id="b" label="B · Minimal" width={260} height={480}>…</DCArtboard>
//     </DCSection>
//   </DesignCanvas>

const DC = {
  bg: '#f0eee9',
  grid: 'rgba(0,0,0,0.06)',
  label: 'rgba(60,50,40,0.7)',
  title: 'rgba(40,30,20,0.85)',
  subtitle: 'rgba(60,50,40,0.6)',
  postitBg: '#fef4a8',
  postitText: '#5a4a2a',
  font: '-apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif'
};

// One-time CSS injection (classes are dc-prefixed so they don't collide with
// the hosted design's own styles).
if (typeof document !== 'undefined' && !document.getElementById('dc-styles')) {
  const s = document.createElement('style');
  s.id = 'dc-styles';
  s.textContent = ['.dc-editable{cursor:text;outline:none;white-space:nowrap;border-radius:3px;padding:0 2px;margin:0 -2px}', '.dc-editable:focus{background:#fff;box-shadow:0 0 0 1.5px #c96442}', '[data-dc-slot]{transition:transform .18s cubic-bezier(.2,.7,.3,1)}', '[data-dc-slot].dc-dragging{transition:none;z-index:10;pointer-events:none}', '[data-dc-slot].dc-dragging .dc-card{box-shadow:0 12px 40px rgba(0,0,0,.25),0 0 0 2px #c96442;transform:scale(1.02)}', '.dc-card{transition:box-shadow .15s,transform .15s}', '.dc-card *{scrollbar-width:none}', '.dc-card *::-webkit-scrollbar{display:none}', '.dc-labelrow{display:flex;align-items:center;gap:4px;height:24px}', '.dc-grip{cursor:grab;display:flex;align-items:center;padding:5px 4px;border-radius:4px;transition:background .12s}', '.dc-grip:hover{background:rgba(0,0,0,.08)}', '.dc-grip:active{cursor:grabbing}', '.dc-labeltext{cursor:pointer;border-radius:4px;padding:3px 6px;display:flex;align-items:center;transition:background .12s}', '.dc-labeltext:hover{background:rgba(0,0,0,.05)}', '.dc-expand{position:absolute;bottom:100%;right:0;margin-bottom:5px;z-index:2;opacity:0;transition:opacity .12s,background .12s;', '  width:22px;height:22px;border-radius:5px;border:none;cursor:pointer;padding:0;', '  background:transparent;color:rgba(60,50,40,.7);display:flex;align-items:center;justify-content:center}', '.dc-expand:hover{background:rgba(0,0,0,.06);color:#2a251f}', '[data-dc-slot]:hover .dc-expand{opacity:1}'].join('\n');
  document.head.appendChild(s);
}
const DCCtx = React.createContext(null);

// ─────────────────────────────────────────────────────────────
// DesignCanvas — stateful wrapper around the pan/zoom viewport.
// Owns runtime state (per-section order, renamed titles/labels, focused
// artboard). Order/titles/labels persist to a .design-canvas.state.json
// sidecar next to the HTML. Reads go via plain fetch() so the saved
// arrangement is visible anywhere the HTML + sidecar are served together
// (omelette preview, direct link, downloaded zip). Writes go through the
// host's window.omelette bridge — editing requires the omelette runtime.
// Focus is ephemeral.
// ─────────────────────────────────────────────────────────────
const DC_STATE_FILE = '.design-canvas.state.json';
function DesignCanvas({
  children,
  minScale,
  maxScale,
  style
}) {
  const [state, setState] = React.useState({
    sections: {},
    focus: null
  });
  // Hold rendering until the sidecar read settles so the saved order/titles
  // appear on first paint (no source-order flash). didRead gates writes until
  // the read settles so the empty initial state can't clobber a slow read;
  // skipNextWrite suppresses the one echo-write that would otherwise follow
  // hydration.
  const [ready, setReady] = React.useState(false);
  const didRead = React.useRef(false);
  const skipNextWrite = React.useRef(false);
  React.useEffect(() => {
    let off = false;
    fetch('./' + DC_STATE_FILE).then(r => r.ok ? r.json() : null).then(saved => {
      if (off || !saved || !saved.sections) return;
      skipNextWrite.current = true;
      setState(s => ({
        ...s,
        sections: saved.sections
      }));
    }).catch(() => {}).finally(() => {
      didRead.current = true;
      if (!off) setReady(true);
    });
    const t = setTimeout(() => {
      if (!off) setReady(true);
    }, 150);
    return () => {
      off = true;
      clearTimeout(t);
    };
  }, []);
  React.useEffect(() => {
    if (!didRead.current) return;
    if (skipNextWrite.current) {
      skipNextWrite.current = false;
      return;
    }
    const t = setTimeout(() => {
      window.omelette?.writeFile(DC_STATE_FILE, JSON.stringify({
        sections: state.sections
      })).catch(() => {});
    }, 250);
    return () => clearTimeout(t);
  }, [state.sections]);

  // Build registries synchronously from children so FocusOverlay can read
  // them in the same render. Only direct DCSection > DCArtboard children are
  // walked — wrapping them in other elements opts out of focus/reorder.
  const registry = {}; // slotId -> { sectionId, artboard }
  const sectionMeta = {}; // sectionId -> { title, subtitle, slotIds[] }
  const sectionOrder = [];
  React.Children.forEach(children, sec => {
    if (!sec || sec.type !== DCSection) return;
    const sid = sec.props.id ?? sec.props.title;
    if (!sid) return;
    sectionOrder.push(sid);
    const persisted = state.sections[sid] || {};
    const srcIds = [];
    React.Children.forEach(sec.props.children, ab => {
      if (!ab || ab.type !== DCArtboard) return;
      const aid = ab.props.id ?? ab.props.label;
      if (!aid) return;
      registry[`${sid}/${aid}`] = {
        sectionId: sid,
        artboard: ab
      };
      srcIds.push(aid);
    });
    const kept = (persisted.order || []).filter(k => srcIds.includes(k));
    sectionMeta[sid] = {
      title: persisted.title ?? sec.props.title,
      subtitle: sec.props.subtitle,
      slotIds: [...kept, ...srcIds.filter(k => !kept.includes(k))]
    };
  });
  const api = React.useMemo(() => ({
    state,
    section: id => state.sections[id] || {},
    patchSection: (id, p) => setState(s => ({
      ...s,
      sections: {
        ...s.sections,
        [id]: {
          ...s.sections[id],
          ...(typeof p === 'function' ? p(s.sections[id] || {}) : p)
        }
      }
    })),
    setFocus: slotId => setState(s => ({
      ...s,
      focus: slotId
    }))
  }), [state]);

  // Esc exits focus; any outside pointerdown commits an in-progress rename.
  React.useEffect(() => {
    const onKey = e => {
      if (e.key === 'Escape') api.setFocus(null);
    };
    const onPd = e => {
      const ae = document.activeElement;
      if (ae && ae.isContentEditable && !ae.contains(e.target)) ae.blur();
    };
    document.addEventListener('keydown', onKey);
    document.addEventListener('pointerdown', onPd, true);
    return () => {
      document.removeEventListener('keydown', onKey);
      document.removeEventListener('pointerdown', onPd, true);
    };
  }, [api]);
  return /*#__PURE__*/React.createElement(DCCtx.Provider, {
    value: api
  }, /*#__PURE__*/React.createElement(DCViewport, {
    minScale: minScale,
    maxScale: maxScale,
    style: style
  }, ready && children), state.focus && registry[state.focus] && /*#__PURE__*/React.createElement(DCFocusOverlay, {
    entry: registry[state.focus],
    sectionMeta: sectionMeta,
    sectionOrder: sectionOrder
  }));
}

// ─────────────────────────────────────────────────────────────
// DCViewport — transform-based pan/zoom (internal)
//
// Input mapping (Figma-style):
//   • trackpad pinch  → zoom   (ctrlKey wheel; Safari gesture* events)
//   • trackpad scroll → pan    (two-finger)
//   • mouse wheel     → zoom   (notched; distinguished from trackpad scroll)
//   • middle-drag / primary-drag-on-bg → pan
//
// Transform state lives in a ref and is written straight to the DOM
// (translate3d + will-change) so wheel ticks don't go through React —
// keeps pans at 60fps on dense canvases.
// ─────────────────────────────────────────────────────────────
function DCViewport({
  children,
  minScale = 0.1,
  maxScale = 8,
  style = {}
}) {
  const vpRef = React.useRef(null);
  const worldRef = React.useRef(null);
  const tf = React.useRef({
    x: 0,
    y: 0,
    scale: 1
  });
  const apply = React.useCallback(() => {
    const {
      x,
      y,
      scale
    } = tf.current;
    const el = worldRef.current;
    if (el) el.style.transform = `translate3d(${x}px, ${y}px, 0) scale(${scale})`;
  }, []);
  React.useEffect(() => {
    const vp = vpRef.current;
    if (!vp) return;
    const zoomAt = (cx, cy, factor) => {
      const r = vp.getBoundingClientRect();
      const px = cx - r.left,
        py = cy - r.top;
      const t = tf.current;
      const next = Math.min(maxScale, Math.max(minScale, t.scale * factor));
      const k = next / t.scale;
      // keep the world point under the cursor fixed
      t.x = px - (px - t.x) * k;
      t.y = py - (py - t.y) * k;
      t.scale = next;
      apply();
    };

    // Mouse-wheel vs trackpad-scroll heuristic. A physical wheel sends
    // line-mode deltas (Firefox) or large integer pixel deltas with no X
    // component (Chrome/Safari, typically multiples of 100/120). Trackpad
    // two-finger scroll sends small/fractional pixel deltas, often with
    // non-zero deltaX. ctrlKey is set by the browser for trackpad pinch.
    const isMouseWheel = e => e.deltaMode !== 0 || e.deltaX === 0 && Number.isInteger(e.deltaY) && Math.abs(e.deltaY) >= 40;
    const onWheel = e => {
      e.preventDefault();
      if (isGesturing) return; // Safari: gesture* owns the pinch — discard concurrent wheels
      if (e.ctrlKey) {
        // trackpad pinch (or explicit ctrl+wheel)
        zoomAt(e.clientX, e.clientY, Math.exp(-e.deltaY * 0.01));
      } else if (isMouseWheel(e)) {
        // notched mouse wheel — fixed-ratio step per click
        zoomAt(e.clientX, e.clientY, Math.exp(-Math.sign(e.deltaY) * 0.18));
      } else {
        // trackpad two-finger scroll — pan
        tf.current.x -= e.deltaX;
        tf.current.y -= e.deltaY;
        apply();
      }
    };

    // Safari sends native gesture* events for trackpad pinch with a smooth
    // e.scale; preferring these over the ctrl+wheel fallback gives a much
    // better feel there. No-ops on other browsers. Safari also fires
    // ctrlKey wheel events during the same pinch — isGesturing makes
    // onWheel drop those entirely so they neither zoom nor pan.
    let gsBase = 1;
    let isGesturing = false;
    const onGestureStart = e => {
      e.preventDefault();
      isGesturing = true;
      gsBase = tf.current.scale;
    };
    const onGestureChange = e => {
      e.preventDefault();
      zoomAt(e.clientX, e.clientY, gsBase * e.scale / tf.current.scale);
    };
    const onGestureEnd = e => {
      e.preventDefault();
      isGesturing = false;
    };

    // Drag-pan: middle button anywhere, or primary button on canvas
    // background (anything that isn't an artboard or an inline editor).
    let drag = null;
    const onPointerDown = e => {
      const onBg = !e.target.closest('[data-dc-slot], .dc-editable');
      if (!(e.button === 1 || e.button === 0 && onBg)) return;
      e.preventDefault();
      vp.setPointerCapture(e.pointerId);
      drag = {
        id: e.pointerId,
        lx: e.clientX,
        ly: e.clientY
      };
      vp.style.cursor = 'grabbing';
    };
    const onPointerMove = e => {
      if (!drag || e.pointerId !== drag.id) return;
      tf.current.x += e.clientX - drag.lx;
      tf.current.y += e.clientY - drag.ly;
      drag.lx = e.clientX;
      drag.ly = e.clientY;
      apply();
    };
    const onPointerUp = e => {
      if (!drag || e.pointerId !== drag.id) return;
      vp.releasePointerCapture(e.pointerId);
      drag = null;
      vp.style.cursor = '';
    };
    vp.addEventListener('wheel', onWheel, {
      passive: false
    });
    vp.addEventListener('gesturestart', onGestureStart, {
      passive: false
    });
    vp.addEventListener('gesturechange', onGestureChange, {
      passive: false
    });
    vp.addEventListener('gestureend', onGestureEnd, {
      passive: false
    });
    vp.addEventListener('pointerdown', onPointerDown);
    vp.addEventListener('pointermove', onPointerMove);
    vp.addEventListener('pointerup', onPointerUp);
    vp.addEventListener('pointercancel', onPointerUp);
    return () => {
      vp.removeEventListener('wheel', onWheel);
      vp.removeEventListener('gesturestart', onGestureStart);
      vp.removeEventListener('gesturechange', onGestureChange);
      vp.removeEventListener('gestureend', onGestureEnd);
      vp.removeEventListener('pointerdown', onPointerDown);
      vp.removeEventListener('pointermove', onPointerMove);
      vp.removeEventListener('pointerup', onPointerUp);
      vp.removeEventListener('pointercancel', onPointerUp);
    };
  }, [apply, minScale, maxScale]);
  const gridSvg = `url("data:image/svg+xml,%3Csvg width='120' height='120' xmlns='http://www.w3.org/2000/svg'%3E%3Cpath d='M120 0H0v120' fill='none' stroke='${encodeURIComponent(DC.grid)}' stroke-width='1'/%3E%3C/svg%3E")`;
  return /*#__PURE__*/React.createElement("div", {
    ref: vpRef,
    className: "design-canvas",
    style: {
      height: '100vh',
      width: '100vw',
      background: DC.bg,
      overflow: 'hidden',
      overscrollBehavior: 'none',
      touchAction: 'none',
      position: 'relative',
      fontFamily: DC.font,
      boxSizing: 'border-box',
      ...style
    }
  }, /*#__PURE__*/React.createElement("div", {
    ref: worldRef,
    style: {
      position: 'absolute',
      top: 0,
      left: 0,
      transformOrigin: '0 0',
      willChange: 'transform',
      width: 'max-content',
      minWidth: '100%',
      minHeight: '100%',
      padding: '60px 0 80px'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      inset: -6000,
      backgroundImage: gridSvg,
      backgroundSize: '120px 120px',
      pointerEvents: 'none',
      zIndex: -1
    }
  }), children));
}

// ─────────────────────────────────────────────────────────────
// DCSection — editable title + h-row of artboards in persisted order
// ─────────────────────────────────────────────────────────────
function DCSection({
  id,
  title,
  subtitle,
  children,
  gap = 48
}) {
  const ctx = React.useContext(DCCtx);
  const sid = id ?? title;
  const all = React.Children.toArray(children);
  const artboards = all.filter(c => c && c.type === DCArtboard);
  const rest = all.filter(c => !(c && c.type === DCArtboard));
  const srcOrder = artboards.map(a => a.props.id ?? a.props.label);
  const sec = ctx && sid && ctx.section(sid) || {};
  const order = React.useMemo(() => {
    const kept = (sec.order || []).filter(k => srcOrder.includes(k));
    return [...kept, ...srcOrder.filter(k => !kept.includes(k))];
  }, [sec.order, srcOrder.join('|')]);
  const byId = Object.fromEntries(artboards.map(a => [a.props.id ?? a.props.label, a]));
  return /*#__PURE__*/React.createElement("div", {
    "data-dc-section": sid,
    style: {
      marginBottom: 80,
      position: 'relative'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      padding: '0 60px 56px'
    }
  }, /*#__PURE__*/React.createElement(DCEditable, {
    tag: "div",
    value: sec.title ?? title,
    onChange: v => ctx && sid && ctx.patchSection(sid, {
      title: v
    }),
    style: {
      fontSize: 28,
      fontWeight: 600,
      color: DC.title,
      letterSpacing: -0.4,
      marginBottom: 6,
      display: 'inline-block'
    }
  }), subtitle && /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 16,
      color: DC.subtitle
    }
  }, subtitle)), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap,
      padding: '0 60px',
      alignItems: 'flex-start',
      width: 'max-content'
    }
  }, order.map(k => /*#__PURE__*/React.createElement(DCArtboardFrame, {
    key: k,
    sectionId: sid,
    artboard: byId[k],
    order: order,
    label: (sec.labels || {})[k] ?? byId[k].props.label,
    onRename: v => ctx && ctx.patchSection(sid, x => ({
      labels: {
        ...x.labels,
        [k]: v
      }
    })),
    onReorder: next => ctx && ctx.patchSection(sid, {
      order: next
    }),
    onFocus: () => ctx && ctx.setFocus(`${sid}/${k}`)
  }))), rest);
}

// DCArtboard — marker; rendered by DCArtboardFrame via DCSection.
function DCArtboard() {
  return null;
}
function DCArtboardFrame({
  sectionId,
  artboard,
  label,
  order,
  onRename,
  onReorder,
  onFocus
}) {
  const {
    id: rawId,
    label: rawLabel,
    width = 260,
    height = 480,
    children,
    style = {}
  } = artboard.props;
  const id = rawId ?? rawLabel;
  const ref = React.useRef(null);

  // Live drag-reorder: dragged card sticks to cursor; siblings slide into
  // their would-be slots in real time via transforms. DOM order only
  // changes on drop.
  const onGripDown = e => {
    e.preventDefault();
    e.stopPropagation();
    const me = ref.current;
    // translateX is applied in local (pre-scale) space but pointer deltas and
    // getBoundingClientRect().left are screen-space — divide by the viewport's
    // current scale so the dragged card tracks the cursor at any zoom level.
    const scale = me.getBoundingClientRect().width / me.offsetWidth || 1;
    const peers = Array.from(document.querySelectorAll(`[data-dc-section="${sectionId}"] [data-dc-slot]`));
    const homes = peers.map(el => ({
      el,
      id: el.dataset.dcSlot,
      x: el.getBoundingClientRect().left
    }));
    const slotXs = homes.map(h => h.x);
    const startIdx = order.indexOf(id);
    const startX = e.clientX;
    let liveOrder = order.slice();
    me.classList.add('dc-dragging');
    const layout = () => {
      for (const h of homes) {
        if (h.id === id) continue;
        const slot = liveOrder.indexOf(h.id);
        h.el.style.transform = `translateX(${(slotXs[slot] - h.x) / scale}px)`;
      }
    };
    const move = ev => {
      const dx = ev.clientX - startX;
      me.style.transform = `translateX(${dx / scale}px)`;
      const cur = homes[startIdx].x + dx;
      let nearest = 0,
        best = Infinity;
      for (let i = 0; i < slotXs.length; i++) {
        const d = Math.abs(slotXs[i] - cur);
        if (d < best) {
          best = d;
          nearest = i;
        }
      }
      if (liveOrder.indexOf(id) !== nearest) {
        liveOrder = order.filter(k => k !== id);
        liveOrder.splice(nearest, 0, id);
        layout();
      }
    };
    const up = () => {
      document.removeEventListener('pointermove', move);
      document.removeEventListener('pointerup', up);
      const finalSlot = liveOrder.indexOf(id);
      me.classList.remove('dc-dragging');
      me.style.transform = `translateX(${(slotXs[finalSlot] - homes[startIdx].x) / scale}px)`;
      // After the settle transition, kill transitions + clear transforms +
      // commit the reorder in the same frame so there's no visual snap-back.
      setTimeout(() => {
        for (const h of homes) {
          h.el.style.transition = 'none';
          h.el.style.transform = '';
        }
        if (liveOrder.join('|') !== order.join('|')) onReorder(liveOrder);
        requestAnimationFrame(() => requestAnimationFrame(() => {
          for (const h of homes) h.el.style.transition = '';
        }));
      }, 180);
    };
    document.addEventListener('pointermove', move);
    document.addEventListener('pointerup', up);
  };
  return /*#__PURE__*/React.createElement("div", {
    ref: ref,
    "data-dc-slot": id,
    style: {
      position: 'relative',
      flexShrink: 0
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "dc-labelrow",
    style: {
      position: 'absolute',
      bottom: '100%',
      left: -4,
      marginBottom: 4,
      color: DC.label
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "dc-grip",
    onPointerDown: onGripDown,
    title: "Drag to reorder"
  }, /*#__PURE__*/React.createElement("svg", {
    width: "9",
    height: "13",
    viewBox: "0 0 9 13",
    fill: "currentColor"
  }, /*#__PURE__*/React.createElement("circle", {
    cx: "2",
    cy: "2",
    r: "1.1"
  }), /*#__PURE__*/React.createElement("circle", {
    cx: "7",
    cy: "2",
    r: "1.1"
  }), /*#__PURE__*/React.createElement("circle", {
    cx: "2",
    cy: "6.5",
    r: "1.1"
  }), /*#__PURE__*/React.createElement("circle", {
    cx: "7",
    cy: "6.5",
    r: "1.1"
  }), /*#__PURE__*/React.createElement("circle", {
    cx: "2",
    cy: "11",
    r: "1.1"
  }), /*#__PURE__*/React.createElement("circle", {
    cx: "7",
    cy: "11",
    r: "1.1"
  }))), /*#__PURE__*/React.createElement("div", {
    className: "dc-labeltext",
    onClick: onFocus,
    title: "Click to focus"
  }, /*#__PURE__*/React.createElement(DCEditable, {
    value: label,
    onChange: onRename,
    onClick: e => e.stopPropagation(),
    style: {
      fontSize: 15,
      fontWeight: 500,
      color: DC.label,
      lineHeight: 1
    }
  }))), /*#__PURE__*/React.createElement("button", {
    className: "dc-expand",
    onClick: onFocus,
    onPointerDown: e => e.stopPropagation(),
    title: "Focus"
  }, /*#__PURE__*/React.createElement("svg", {
    width: "12",
    height: "12",
    viewBox: "0 0 12 12",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: "1.6",
    strokeLinecap: "round"
  }, /*#__PURE__*/React.createElement("path", {
    d: "M7 1h4v4M5 11H1V7M11 1L7.5 4.5M1 11l3.5-3.5"
  }))), /*#__PURE__*/React.createElement("div", {
    className: "dc-card",
    style: {
      borderRadius: 2,
      boxShadow: '0 1px 3px rgba(0,0,0,.08),0 4px 16px rgba(0,0,0,.06)',
      overflow: 'hidden',
      width,
      height,
      background: '#fff',
      ...style
    }
  }, children || /*#__PURE__*/React.createElement("div", {
    style: {
      height: '100%',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      color: '#bbb',
      fontSize: 13,
      fontFamily: DC.font
    }
  }, id)));
}

// Inline rename — commits on blur or Enter.
function DCEditable({
  value,
  onChange,
  style,
  tag = 'span',
  onClick
}) {
  const T = tag;
  return /*#__PURE__*/React.createElement(T, {
    className: "dc-editable",
    contentEditable: true,
    suppressContentEditableWarning: true,
    onClick: onClick,
    onPointerDown: e => e.stopPropagation(),
    onBlur: e => onChange && onChange(e.currentTarget.textContent),
    onKeyDown: e => {
      if (e.key === 'Enter') {
        e.preventDefault();
        e.currentTarget.blur();
      }
    },
    style: style
  }, value);
}

// ─────────────────────────────────────────────────────────────
// Focus mode — overlay one artboard; ←/→ within section, ↑/↓ across
// sections, Esc or backdrop click to exit.
// ─────────────────────────────────────────────────────────────
function DCFocusOverlay({
  entry,
  sectionMeta,
  sectionOrder
}) {
  const ctx = React.useContext(DCCtx);
  const {
    sectionId,
    artboard
  } = entry;
  const sec = ctx.section(sectionId);
  const meta = sectionMeta[sectionId];
  const peers = meta.slotIds;
  const aid = artboard.props.id ?? artboard.props.label;
  const idx = peers.indexOf(aid);
  const secIdx = sectionOrder.indexOf(sectionId);
  const go = d => {
    const n = peers[(idx + d + peers.length) % peers.length];
    if (n) ctx.setFocus(`${sectionId}/${n}`);
  };
  const goSection = d => {
    const ns = sectionOrder[(secIdx + d + sectionOrder.length) % sectionOrder.length];
    const first = sectionMeta[ns] && sectionMeta[ns].slotIds[0];
    if (first) ctx.setFocus(`${ns}/${first}`);
  };
  React.useEffect(() => {
    const k = e => {
      if (e.key === 'ArrowLeft') {
        e.preventDefault();
        go(-1);
      }
      if (e.key === 'ArrowRight') {
        e.preventDefault();
        go(1);
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault();
        goSection(-1);
      }
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        goSection(1);
      }
    };
    document.addEventListener('keydown', k);
    return () => document.removeEventListener('keydown', k);
  });
  const {
    width = 260,
    height = 480,
    children
  } = artboard.props;
  const [vp, setVp] = React.useState({
    w: window.innerWidth,
    h: window.innerHeight
  });
  React.useEffect(() => {
    const r = () => setVp({
      w: window.innerWidth,
      h: window.innerHeight
    });
    window.addEventListener('resize', r);
    return () => window.removeEventListener('resize', r);
  }, []);
  const scale = Math.max(0.1, Math.min((vp.w - 200) / width, (vp.h - 260) / height, 2));
  const [ddOpen, setDd] = React.useState(false);
  const Arrow = ({
    dir,
    onClick
  }) => /*#__PURE__*/React.createElement("button", {
    onClick: e => {
      e.stopPropagation();
      onClick();
    },
    style: {
      position: 'absolute',
      top: '50%',
      [dir]: 28,
      transform: 'translateY(-50%)',
      border: 'none',
      background: 'rgba(255,255,255,.08)',
      color: 'rgba(255,255,255,.9)',
      width: 44,
      height: 44,
      borderRadius: 22,
      fontSize: 18,
      cursor: 'pointer',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      transition: 'background .15s'
    },
    onMouseEnter: e => e.currentTarget.style.background = 'rgba(255,255,255,.18)',
    onMouseLeave: e => e.currentTarget.style.background = 'rgba(255,255,255,.08)'
  }, /*#__PURE__*/React.createElement("svg", {
    width: "18",
    height: "18",
    viewBox: "0 0 18 18",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: "2",
    strokeLinecap: "round"
  }, /*#__PURE__*/React.createElement("path", {
    d: dir === 'left' ? 'M11 3L5 9l6 6' : 'M7 3l6 6-6 6'
  })));

  // Portal to body so position:fixed is the real viewport regardless of any
  // transform on DesignCanvas's ancestors (including the canvas zoom itself).
  return ReactDOM.createPortal(/*#__PURE__*/React.createElement("div", {
    onClick: () => ctx.setFocus(null),
    onWheel: e => e.preventDefault(),
    style: {
      position: 'fixed',
      inset: 0,
      zIndex: 100,
      background: 'rgba(24,20,16,.6)',
      backdropFilter: 'blur(14px)',
      fontFamily: DC.font,
      color: '#fff'
    }
  }, /*#__PURE__*/React.createElement("div", {
    onClick: e => e.stopPropagation(),
    style: {
      position: 'absolute',
      top: 0,
      left: 0,
      right: 0,
      height: 72,
      display: 'flex',
      alignItems: 'flex-start',
      padding: '16px 20px 0',
      gap: 16
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'relative'
    }
  }, /*#__PURE__*/React.createElement("button", {
    onClick: () => setDd(o => !o),
    style: {
      border: 'none',
      background: 'transparent',
      color: '#fff',
      cursor: 'pointer',
      padding: '6px 8px',
      borderRadius: 6,
      textAlign: 'left',
      fontFamily: 'inherit'
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 8
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 18,
      fontWeight: 600,
      letterSpacing: -0.3
    }
  }, meta.title), /*#__PURE__*/React.createElement("svg", {
    width: "11",
    height: "11",
    viewBox: "0 0 11 11",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: "1.8",
    strokeLinecap: "round",
    style: {
      opacity: .7
    }
  }, /*#__PURE__*/React.createElement("path", {
    d: "M2 4l3.5 3.5L9 4"
  }))), meta.subtitle && /*#__PURE__*/React.createElement("span", {
    style: {
      display: 'block',
      fontSize: 13,
      opacity: .6,
      fontWeight: 400,
      marginTop: 2
    }
  }, meta.subtitle)), ddOpen && /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      top: '100%',
      left: 0,
      marginTop: 4,
      background: '#2a251f',
      borderRadius: 8,
      boxShadow: '0 8px 32px rgba(0,0,0,.4)',
      padding: 4,
      minWidth: 200,
      zIndex: 10
    }
  }, sectionOrder.map(sid => /*#__PURE__*/React.createElement("button", {
    key: sid,
    onClick: () => {
      setDd(false);
      const f = sectionMeta[sid].slotIds[0];
      if (f) ctx.setFocus(`${sid}/${f}`);
    },
    style: {
      display: 'block',
      width: '100%',
      textAlign: 'left',
      border: 'none',
      cursor: 'pointer',
      background: sid === sectionId ? 'rgba(255,255,255,.1)' : 'transparent',
      color: '#fff',
      padding: '8px 12px',
      borderRadius: 5,
      fontSize: 14,
      fontWeight: sid === sectionId ? 600 : 400,
      fontFamily: 'inherit'
    }
  }, sectionMeta[sid].title)))), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1
    }
  }), /*#__PURE__*/React.createElement("button", {
    onClick: () => ctx.setFocus(null),
    onMouseEnter: e => e.currentTarget.style.background = 'rgba(255,255,255,.12)',
    onMouseLeave: e => e.currentTarget.style.background = 'transparent',
    style: {
      border: 'none',
      background: 'transparent',
      color: 'rgba(255,255,255,.7)',
      width: 32,
      height: 32,
      borderRadius: 16,
      fontSize: 20,
      cursor: 'pointer',
      lineHeight: 1,
      transition: 'background .12s'
    }
  }, "\xD7")), /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      top: 64,
      bottom: 56,
      left: 100,
      right: 100,
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      justifyContent: 'center',
      gap: 16
    }
  }, /*#__PURE__*/React.createElement("div", {
    onClick: e => e.stopPropagation(),
    style: {
      width: width * scale,
      height: height * scale,
      position: 'relative'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      width,
      height,
      transform: `scale(${scale})`,
      transformOrigin: 'top left',
      background: '#fff',
      borderRadius: 2,
      overflow: 'hidden',
      boxShadow: '0 20px 80px rgba(0,0,0,.4)'
    }
  }, children || /*#__PURE__*/React.createElement("div", {
    style: {
      height: '100%',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      color: '#bbb'
    }
  }, aid))), /*#__PURE__*/React.createElement("div", {
    onClick: e => e.stopPropagation(),
    style: {
      fontSize: 14,
      fontWeight: 500,
      opacity: .85,
      textAlign: 'center'
    }
  }, (sec.labels || {})[aid] ?? artboard.props.label, /*#__PURE__*/React.createElement("span", {
    style: {
      opacity: .5,
      marginLeft: 10,
      fontVariantNumeric: 'tabular-nums'
    }
  }, idx + 1, " / ", peers.length))), /*#__PURE__*/React.createElement(Arrow, {
    dir: "left",
    onClick: () => go(-1)
  }), /*#__PURE__*/React.createElement(Arrow, {
    dir: "right",
    onClick: () => go(1)
  }), /*#__PURE__*/React.createElement("div", {
    onClick: e => e.stopPropagation(),
    style: {
      position: 'absolute',
      bottom: 20,
      left: '50%',
      transform: 'translateX(-50%)',
      display: 'flex',
      gap: 8
    }
  }, peers.map((p, i) => /*#__PURE__*/React.createElement("button", {
    key: p,
    onClick: () => ctx.setFocus(`${sectionId}/${p}`),
    style: {
      border: 'none',
      padding: 0,
      cursor: 'pointer',
      width: 6,
      height: 6,
      borderRadius: 3,
      background: i === idx ? '#fff' : 'rgba(255,255,255,.3)'
    }
  })))), document.body);
}

// ─────────────────────────────────────────────────────────────
// Post-it — absolute-positioned sticky note
// ─────────────────────────────────────────────────────────────
function DCPostIt({
  children,
  top,
  left,
  right,
  bottom,
  rotate = -2,
  width = 180
}) {
  return /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      top,
      left,
      right,
      bottom,
      width,
      background: DC.postitBg,
      padding: '14px 16px',
      fontFamily: '"Comic Sans MS", "Marker Felt", "Segoe Print", cursive',
      fontSize: 14,
      lineHeight: 1.4,
      color: DC.postitText,
      boxShadow: '0 2px 8px rgba(0,0,0,0.12), 0 1px 2px rgba(0,0,0,0.08)',
      transform: `rotate(${rotate}deg)`,
      zIndex: 5
    }
  }, children);
}
Object.assign(window, {
  DesignCanvas,
  DCSection,
  DCArtboard,
  DCPostIt
});
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/mobile/design-canvas.jsx", error: String((e && e.message) || e) }); }

// ui_kits/mobile/ios-frame.jsx
try { (() => {
// iOS.jsx — iOS 26 device frame with consistent safe-area canvas.
// Exports: IOSDevice, IOSStatusBar, IOSNavBar, IOSGlassPill, IOSList, IOSListRow, IOSKeyboard, IOSActivityDots

// Constants — one source of truth
const SAFE_TOP = 59; // status bar band (island sits inside this)
const SAFE_BOT = 34; // home indicator band
const ISLAND_W = 126;
const ISLAND_H = 37;
const ISLAND_TOP = 11;

// ─────────────────────────────────────────────
// Status bar — split around the dynamic island
// ─────────────────────────────────────────────
function IOSStatusBar({
  dark = false,
  time = '9:41'
}) {
  const c = dark ? '#fff' : '#000';
  return /*#__PURE__*/React.createElement("div", {
    style: {
      height: SAFE_TOP,
      width: '100%',
      boxSizing: 'border-box',
      position: 'relative',
      zIndex: 20,
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
      padding: '0 28px',
      pointerEvents: 'none'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: '-apple-system, "SF Pro", system-ui',
      fontWeight: 590,
      fontSize: 17,
      lineHeight: '22px',
      color: c,
      paddingTop: 2
    }
  }, time), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 7,
      paddingTop: 2
    }
  }, /*#__PURE__*/React.createElement("svg", {
    width: "19",
    height: "12",
    viewBox: "0 0 19 12"
  }, /*#__PURE__*/React.createElement("rect", {
    x: "0",
    y: "7.5",
    width: "3.2",
    height: "4.5",
    rx: "0.7",
    fill: c
  }), /*#__PURE__*/React.createElement("rect", {
    x: "4.8",
    y: "5",
    width: "3.2",
    height: "7",
    rx: "0.7",
    fill: c
  }), /*#__PURE__*/React.createElement("rect", {
    x: "9.6",
    y: "2.5",
    width: "3.2",
    height: "9.5",
    rx: "0.7",
    fill: c
  }), /*#__PURE__*/React.createElement("rect", {
    x: "14.4",
    y: "0",
    width: "3.2",
    height: "12",
    rx: "0.7",
    fill: c
  })), /*#__PURE__*/React.createElement("svg", {
    width: "16",
    height: "12",
    viewBox: "0 0 17 12"
  }, /*#__PURE__*/React.createElement("path", {
    d: "M8.5 3.2C10.8 3.2 12.9 4.1 14.4 5.6L15.5 4.5C13.7 2.7 11.2 1.5 8.5 1.5C5.8 1.5 3.3 2.7 1.5 4.5L2.6 5.6C4.1 4.1 6.2 3.2 8.5 3.2Z",
    fill: c
  }), /*#__PURE__*/React.createElement("path", {
    d: "M8.5 6.8C9.9 6.8 11.1 7.3 12 8.2L13.1 7.1C11.8 5.9 10.2 5.1 8.5 5.1C6.8 5.1 5.2 5.9 3.9 7.1L5 8.2C5.9 7.3 7.1 6.8 8.5 6.8Z",
    fill: c
  }), /*#__PURE__*/React.createElement("circle", {
    cx: "8.5",
    cy: "10.5",
    r: "1.5",
    fill: c
  })), /*#__PURE__*/React.createElement("svg", {
    width: "26",
    height: "13",
    viewBox: "0 0 27 13"
  }, /*#__PURE__*/React.createElement("rect", {
    x: "0.5",
    y: "0.5",
    width: "23",
    height: "12",
    rx: "3.5",
    stroke: c,
    strokeOpacity: "0.4",
    fill: "none"
  }), /*#__PURE__*/React.createElement("rect", {
    x: "2",
    y: "2",
    width: "20",
    height: "9",
    rx: "2",
    fill: c
  }), /*#__PURE__*/React.createElement("path", {
    d: "M25 4.5V8.5C25.8 8.2 26.5 7.5 26.5 6.5C26.5 5.5 25.8 4.8 25 4.5Z",
    fill: c,
    fillOpacity: "0.4"
  }))));
}

// ─────────────────────────────────────────────
// Activity dots — live-process indicator hugging the island
// variants: 'running' (pulsing green), 'recording' (red), 'uploading' (amber), 'ai' (purple shimmer)
// ─────────────────────────────────────────────
function IOSActivityDots({
  variant = 'running',
  label,
  side = 'left'
}) {
  const colors = {
    running: {
      c: '#30D158',
      label: 'Live'
    },
    recording: {
      c: '#FF453A',
      label: 'REC'
    },
    uploading: {
      c: '#FF9F0A',
      label: 'Sync'
    },
    ai: {
      c: '#BF5AF2',
      label: 'AI'
    }
  };
  const v = colors[variant] || colors.running;
  const text = label ?? v.label;
  // Island is centered; hug left or right edge of it
  const offset = ISLAND_W / 2 + 10; // from center
  const pos = side === 'left' ? {
    right: `calc(50% + ${offset}px)`
  } : {
    left: `calc(50% + ${offset}px)`
  };
  return /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      top: ISLAND_TOP + (ISLAND_H - 22) / 2,
      ...pos,
      height: 22,
      display: 'flex',
      alignItems: 'center',
      gap: 5,
      padding: '0 9px 0 7px',
      borderRadius: 11,
      background: 'rgba(0,0,0,0.85)',
      backdropFilter: 'blur(8px)',
      WebkitBackdropFilter: 'blur(8px)',
      zIndex: 45,
      pointerEvents: 'none',
      fontFamily: '-apple-system, "SF Pro", system-ui',
      fontSize: 11,
      fontWeight: 600,
      color: '#fff',
      letterSpacing: 0.2
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      width: 7,
      height: 7,
      borderRadius: '50%',
      background: v.c,
      boxShadow: `0 0 0 0 ${v.c}`,
      animation: `iosdot-${variant} 1.4s ease-in-out infinite`
    }
  }), /*#__PURE__*/React.createElement("span", null, text), /*#__PURE__*/React.createElement("style", null, `
        @keyframes iosdot-${variant} {
          0%, 100% { box-shadow: 0 0 0 0 ${v.c}80; opacity: .9 }
          50%      { box-shadow: 0 0 0 4px ${v.c}00; opacity: 1 }
        }
      `));
}

// ─────────────────────────────────────────────
// Liquid glass pill
// ─────────────────────────────────────────────
function IOSGlassPill({
  children,
  dark = false,
  style = {}
}) {
  return /*#__PURE__*/React.createElement("div", {
    style: {
      height: 40,
      minWidth: 40,
      borderRadius: 9999,
      position: 'relative',
      overflow: 'hidden',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      boxShadow: dark ? '0 2px 6px rgba(0,0,0,0.35)' : '0 1px 3px rgba(0,0,0,0.07), 0 3px 10px rgba(0,0,0,0.05)',
      ...style
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      inset: 0,
      borderRadius: 9999,
      backdropFilter: 'blur(10px) saturate(170%)',
      WebkitBackdropFilter: 'blur(10px) saturate(170%)',
      background: dark ? 'rgba(120,120,128,0.28)' : 'rgba(255,255,255,0.55)'
    }
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      inset: 0,
      borderRadius: 9999,
      boxShadow: dark ? 'inset 1px 1px 1px rgba(255,255,255,0.12)' : 'inset 1px 1px 1px rgba(255,255,255,0.7), inset -1px -1px 1px rgba(255,255,255,0.35)',
      border: dark ? '0.5px solid rgba(255,255,255,0.14)' : '0.5px solid rgba(0,0,0,0.05)'
    }
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'relative',
      zIndex: 1,
      display: 'flex',
      alignItems: 'center'
    }
  }, children));
}

// ─────────────────────────────────────────────
// Nav bar — always below the safe-top canvas
// ─────────────────────────────────────────────
function IOSNavBar({
  title = 'Title',
  dark = false,
  trailingIcon = true,
  large = true,
  trailingLabel
}) {
  const muted = dark ? 'rgba(255,255,255,0.6)' : '#404040';
  const text = dark ? '#fff' : '#000';
  const pillIcon = content => /*#__PURE__*/React.createElement(IOSGlassPill, {
    dark: dark
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      width: 40,
      height: 40,
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center'
    }
  }, content));
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: large ? 10 : 0,
      paddingTop: 8,
      paddingBottom: 10,
      position: 'relative',
      zIndex: 5
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
      padding: '0 16px',
      minHeight: 40
    }
  }, pillIcon(/*#__PURE__*/React.createElement("svg", {
    width: "11",
    height: "18",
    viewBox: "0 0 12 20",
    fill: "none"
  }, /*#__PURE__*/React.createElement("path", {
    d: "M10 2L2 10l8 8",
    stroke: muted,
    strokeWidth: "2.5",
    strokeLinecap: "round",
    strokeLinejoin: "round"
  }))), trailingLabel ? /*#__PURE__*/React.createElement(IOSGlassPill, {
    dark: dark,
    style: {
      padding: '0 14px'
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: '-apple-system, system-ui',
      fontSize: 15,
      fontWeight: 600,
      color: '#5B3FD4',
      padding: '0 4px'
    }
  }, trailingLabel)) : trailingIcon && pillIcon(/*#__PURE__*/React.createElement("svg", {
    width: "22",
    height: "6",
    viewBox: "0 0 22 6"
  }, /*#__PURE__*/React.createElement("circle", {
    cx: "3",
    cy: "3",
    r: "2.5",
    fill: muted
  }), /*#__PURE__*/React.createElement("circle", {
    cx: "11",
    cy: "3",
    r: "2.5",
    fill: muted
  }), /*#__PURE__*/React.createElement("circle", {
    cx: "19",
    cy: "3",
    r: "2.5",
    fill: muted
  })))), large && /*#__PURE__*/React.createElement("div", {
    style: {
      padding: '6px 20px 0',
      fontFamily: '-apple-system, system-ui',
      fontSize: 32,
      fontWeight: 700,
      lineHeight: '38px',
      color: text,
      letterSpacing: -0.3
    }
  }, title));
}

// ─────────────────────────────────────────────
// Grouped list
// ─────────────────────────────────────────────
function IOSListRow({
  title,
  detail,
  icon,
  chevron = true,
  isLast = false,
  dark = false
}) {
  const text = dark ? '#fff' : '#000';
  const sec = dark ? 'rgba(235,235,245,0.6)' : 'rgba(60,60,67,0.6)';
  const ter = dark ? 'rgba(235,235,245,0.3)' : 'rgba(60,60,67,0.3)';
  const sep = dark ? 'rgba(84,84,88,0.65)' : 'rgba(60,60,67,0.12)';
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'center',
      minHeight: 52,
      padding: '0 16px',
      position: 'relative',
      fontFamily: '-apple-system, system-ui',
      fontSize: 17,
      letterSpacing: -0.43
    }
  }, icon && /*#__PURE__*/React.createElement("div", {
    style: {
      width: 30,
      height: 30,
      borderRadius: 7,
      background: icon,
      marginRight: 12,
      flexShrink: 0
    }
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      color: text
    }
  }, title), detail && /*#__PURE__*/React.createElement("span", {
    style: {
      color: sec,
      marginRight: 6
    }
  }, detail), chevron && /*#__PURE__*/React.createElement("svg", {
    width: "8",
    height: "14",
    viewBox: "0 0 8 14",
    style: {
      flexShrink: 0
    }
  }, /*#__PURE__*/React.createElement("path", {
    d: "M1 1l6 6-6 6",
    stroke: ter,
    strokeWidth: "2",
    fill: "none",
    strokeLinecap: "round",
    strokeLinejoin: "round"
  })), !isLast && /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      bottom: 0,
      right: 0,
      left: icon ? 58 : 16,
      height: 0.5,
      background: sep
    }
  }));
}
function IOSList({
  header,
  children,
  dark = false
}) {
  const hc = dark ? 'rgba(235,235,245,0.6)' : 'rgba(60,60,67,0.6)';
  const bg = dark ? '#1C1C1E' : '#fff';
  return /*#__PURE__*/React.createElement("div", null, header && /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: '-apple-system, system-ui',
      fontSize: 13,
      color: hc,
      textTransform: 'uppercase',
      padding: '8px 36px 6px',
      letterSpacing: -0.08
    }
  }, header), /*#__PURE__*/React.createElement("div", {
    style: {
      background: bg,
      borderRadius: 26,
      margin: '0 16px',
      overflow: 'hidden'
    }
  }, children));
}

// ─────────────────────────────────────────────
// Device frame — consistent canvas
// ─────────────────────────────────────────────
function IOSDevice({
  children,
  width = 402,
  height = 874,
  dark = false,
  title,
  keyboard = false,
  activity,
  trailingLabel
}) {
  return /*#__PURE__*/React.createElement("div", {
    style: {
      width,
      height,
      borderRadius: 48,
      overflow: 'hidden',
      position: 'relative',
      background: dark ? '#000' : '#F2F2F7',
      boxShadow: '0 40px 80px rgba(0,0,0,0.18), 0 0 0 1px rgba(0,0,0,0.12)',
      fontFamily: '-apple-system, system-ui, sans-serif',
      WebkitFontSmoothing: 'antialiased'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      top: ISLAND_TOP,
      left: '50%',
      transform: 'translateX(-50%)',
      width: ISLAND_W,
      height: ISLAND_H,
      borderRadius: 24,
      background: '#000',
      zIndex: 50
    }
  }), activity && /*#__PURE__*/React.createElement(IOSActivityDots, typeof activity === 'string' ? {
    variant: activity
  } : activity), /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      top: 0,
      left: 0,
      right: 0,
      zIndex: 10,
      pointerEvents: 'none'
    }
  }, /*#__PURE__*/React.createElement(IOSStatusBar, {
    dark: dark
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      top: SAFE_TOP,
      left: 0,
      right: 0,
      bottom: SAFE_BOT,
      display: 'flex',
      flexDirection: 'column'
    }
  }, title !== undefined && /*#__PURE__*/React.createElement(IOSNavBar, {
    title: title,
    dark: dark,
    trailingLabel: trailingLabel
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      overflow: 'auto',
      minHeight: 0
    }
  }, children), keyboard && /*#__PURE__*/React.createElement(IOSKeyboard, {
    dark: dark
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      bottom: 0,
      left: 0,
      right: 0,
      zIndex: 60,
      height: SAFE_BOT,
      display: 'flex',
      justifyContent: 'center',
      alignItems: 'flex-end',
      paddingBottom: 8,
      pointerEvents: 'none',
      background: 'linear-gradient(to top, rgba(0,0,0,0.02), transparent)'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      width: 139,
      height: 5,
      borderRadius: 100,
      background: dark ? 'rgba(255,255,255,0.7)' : 'rgba(0,0,0,0.3)'
    }
  })));
}

// ─────────────────────────────────────────────
// Keyboard
// ─────────────────────────────────────────────
function IOSKeyboard({
  dark = false
}) {
  const glyph = dark ? 'rgba(255,255,255,0.7)' : '#595959';
  const sugg = dark ? 'rgba(255,255,255,0.6)' : '#333';
  const keyBg = dark ? 'rgba(255,255,255,0.22)' : 'rgba(255,255,255,0.85)';
  const icons = {
    shift: /*#__PURE__*/React.createElement("svg", {
      width: "19",
      height: "17",
      viewBox: "0 0 19 17"
    }, /*#__PURE__*/React.createElement("path", {
      d: "M9.5 1L1 9.5h4.5V16h8V9.5H18L9.5 1z",
      fill: glyph
    })),
    del: /*#__PURE__*/React.createElement("svg", {
      width: "23",
      height: "17",
      viewBox: "0 0 23 17"
    }, /*#__PURE__*/React.createElement("path", {
      d: "M7 1h13a2 2 0 012 2v11a2 2 0 01-2 2H7l-6-7.5L7 1z",
      fill: "none",
      stroke: glyph,
      strokeWidth: "1.6",
      strokeLinejoin: "round"
    }), /*#__PURE__*/React.createElement("path", {
      d: "M10 5l7 7M17 5l-7 7",
      stroke: glyph,
      strokeWidth: "1.6",
      strokeLinecap: "round"
    })),
    ret: /*#__PURE__*/React.createElement("svg", {
      width: "20",
      height: "14",
      viewBox: "0 0 20 14"
    }, /*#__PURE__*/React.createElement("path", {
      d: "M18 1v6H4m0 0l4-4M4 7l4 4",
      fill: "none",
      stroke: "#fff",
      strokeWidth: "1.8",
      strokeLinecap: "round",
      strokeLinejoin: "round"
    }))
  };
  const key = (content, {
    w,
    flex,
    ret,
    fs = 22,
    k
  } = {}) => /*#__PURE__*/React.createElement("div", {
    key: k,
    style: {
      height: 42,
      borderRadius: 8.5,
      flex: flex ? 1 : undefined,
      width: w,
      minWidth: 0,
      background: ret ? '#08f' : keyBg,
      boxShadow: '0 1px 0 rgba(0,0,0,0.075)',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      fontFamily: '-apple-system, "SF Compact", system-ui',
      fontSize: fs,
      fontWeight: 458,
      color: ret ? '#fff' : glyph
    }
  }, content);
  const row = (keys, pad = 0) => /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: 6,
      justifyContent: 'center',
      padding: `0 ${pad}px`
    }
  }, keys.map(l => key(l, {
    flex: true,
    k: l
  })));
  return /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'relative',
      zIndex: 15,
      padding: '10px 0 4px',
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      inset: 0,
      backdropFilter: 'blur(12px) saturate(180%)',
      WebkitBackdropFilter: 'blur(12px) saturate(180%)',
      background: dark ? 'rgba(60,60,70,0.55)' : 'rgba(209,213,219,0.65)'
    }
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: 20,
      alignItems: 'center',
      padding: '6px 22px 10px',
      width: '100%',
      boxSizing: 'border-box',
      position: 'relative'
    }
  }, ['"The"', 'the', 'to'].map((w, i) => /*#__PURE__*/React.createElement(React.Fragment, {
    key: i
  }, i > 0 && /*#__PURE__*/React.createElement("div", {
    style: {
      width: 1,
      height: 22,
      background: '#aaa',
      opacity: 0.4
    }
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      textAlign: 'center',
      fontFamily: '-apple-system, system-ui',
      fontSize: 16,
      color: sugg,
      lineHeight: '22px'
    }
  }, w)))), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 10,
      padding: '0 6px',
      width: '100%',
      boxSizing: 'border-box',
      position: 'relative'
    }
  }, row(['q', 'w', 'e', 'r', 't', 'y', 'u', 'i', 'o', 'p']), row(['a', 's', 'd', 'f', 'g', 'h', 'j', 'k', 'l'], 18), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: 12,
      alignItems: 'center'
    }
  }, key(icons.shift, {
    w: 42,
    k: 'shift'
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: 6,
      flex: 1
    }
  }, ['z', 'x', 'c', 'v', 'b', 'n', 'm'].map(l => key(l, {
    flex: true,
    k: l
  }))), key(icons.del, {
    w: 42,
    k: 'del'
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: 6,
      alignItems: 'center'
    }
  }, key('ABC', {
    w: 85,
    fs: 15,
    k: 'abc'
  }), key('', {
    flex: true,
    k: 'space'
  }), key(icons.ret, {
    w: 85,
    ret: true,
    k: 'ret'
  }))));
}
Object.assign(window, {
  IOSDevice,
  IOSStatusBar,
  IOSNavBar,
  IOSGlassPill,
  IOSList,
  IOSListRow,
  IOSKeyboard,
  IOSActivityDots
});
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/mobile/ios-frame.jsx", error: String((e && e.message) || e) }); }

// ui_kits/platform/Navbar.jsx
try { (() => {
/* Navbar.jsx — top bar with search, pillar tabs, profile */
function Navbar({
  pillar,
  onPillarChange,
  user
}) {
  const pillars = [{
    k: 'data',
    letter: 'D',
    color: '#C8B6FF',
    label: 'Data'
  }, {
    k: 'operations',
    letter: 'O',
    color: '#B8E0D2',
    label: 'Ops'
  }, {
    k: 'tech',
    letter: 'T',
    color: '#FFCDB2',
    label: 'Tech'
  }, {
    k: 'strategy',
    letter: 'S',
    color: '#A2D2FF',
    label: 'Strategy'
  }];
  return /*#__PURE__*/React.createElement("header", {
    style: {
      height: 64,
      background: 'rgba(253,252,250,.88)',
      backdropFilter: 'blur(20px)',
      borderBottom: '1px solid #E8E6E0',
      position: 'sticky',
      top: 0,
      zIndex: 10,
      display: 'flex',
      alignItems: 'center',
      gap: 16,
      padding: '0 24px'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      flex: '0 0 auto',
      display: 'flex',
      alignItems: 'center',
      gap: 6,
      padding: '6px 8px',
      background: '#F8F7F4',
      borderRadius: 999
    }
  }, pillars.map(p => /*#__PURE__*/React.createElement("button", {
    key: p.k,
    onClick: () => onPillarChange(p.k),
    style: {
      border: 'none',
      cursor: 'pointer',
      padding: '6px 12px',
      borderRadius: 999,
      background: pillar === p.k ? '#fff' : 'transparent',
      boxShadow: pillar === p.k ? '0 1px 2px rgba(25,25,36,.06)' : 'none',
      display: 'flex',
      alignItems: 'center',
      gap: 6,
      fontFamily: 'Satoshi',
      fontSize: 12,
      fontWeight: pillar === p.k ? 600 : 400,
      color: pillar === p.k ? '#191924' : '#6E6B62'
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      width: 16,
      height: 16,
      borderRadius: '50%',
      background: p.color,
      display: 'inline-flex',
      alignItems: 'center',
      justifyContent: 'center',
      fontFamily: 'Chubbo, sans-serif',
      fontSize: 10,
      fontWeight: 800,
      color: '#191924'
    }
  }, p.letter), p.label))), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      display: 'flex',
      alignItems: 'center',
      gap: 8,
      background: '#F8F7F4',
      border: '1px solid #E8E6E0',
      borderRadius: 12,
      padding: '8px 14px',
      maxWidth: 420
    }
  }, /*#__PURE__*/React.createElement("i", {
    "data-lucide": "search",
    style: {
      width: 14,
      height: 14,
      color: '#918D82'
    }
  }), /*#__PURE__*/React.createElement("input", {
    placeholder: "Search agents, workflows, data\u2026",
    style: {
      border: 'none',
      background: 'transparent',
      outline: 'none',
      fontFamily: 'Satoshi',
      fontSize: 13,
      color: '#191924',
      flex: 1
    }
  }), /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: 'JetBrains Mono, monospace',
      fontSize: 10,
      letterSpacing: 1,
      color: '#918D82',
      background: '#fff',
      padding: '2px 6px',
      borderRadius: 4,
      border: '1px solid #E8E6E0'
    }
  }, "\u2318K")), /*#__PURE__*/React.createElement("button", {
    style: {
      position: 'relative',
      border: '1px solid #E8E6E0',
      background: '#fff',
      borderRadius: 10,
      width: 36,
      height: 36,
      cursor: 'pointer',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center'
    }
  }, /*#__PURE__*/React.createElement("i", {
    "data-lucide": "bell",
    style: {
      width: 15,
      height: 15,
      color: '#4A4842'
    }
  }), /*#__PURE__*/React.createElement("span", {
    style: {
      position: 'absolute',
      top: 7,
      right: 7,
      width: 7,
      height: 7,
      borderRadius: '50%',
      background: '#FFB5C2',
      border: '1.5px solid #fff'
    }
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 8
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      width: 34,
      height: 34,
      borderRadius: '50%',
      background: 'linear-gradient(135deg, #C8B6FF, #A2D2FF)',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      fontFamily: 'Chubbo, sans-serif',
      fontWeight: 800,
      color: '#191924',
      fontSize: 13,
      letterSpacing: '-0.02em'
    }
  }, user?.initials || 'MD')));
}
Object.assign(window, {
  Navbar
});
Object.assign(__ds_scope, { Navbar });
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/platform/Navbar.jsx", error: String((e && e.message) || e) }); }

// ui_kits/platform/Pages.jsx
try { (() => {
/* Pages.jsx — screens for the click-thru */
const {
  useState
} = React;
function LoginPage({
  onLogin
}) {
  const [email, setEmail] = useState('meet@dotsai.in');
  const [password, setPassword] = useState('••••••••');
  return /*#__PURE__*/React.createElement("div", {
    style: {
      minHeight: '100%',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      padding: '60px 40px',
      background: '#FDFCFA',
      position: 'relative',
      overflow: 'hidden'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      top: '-10%',
      left: '-10%',
      width: 500,
      height: 500,
      borderRadius: '50%',
      background: 'radial-gradient(circle, rgba(200,182,255,.35), transparent 70%)',
      filter: 'blur(40px)'
    }
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      bottom: '-15%',
      right: '-10%',
      width: 500,
      height: 500,
      borderRadius: '50%',
      background: 'radial-gradient(circle, rgba(184,224,210,.3), transparent 70%)',
      filter: 'blur(40px)'
    }
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      width: 440,
      background: '#fff',
      border: '1px solid #E8E6E0',
      borderRadius: 24,
      padding: 40,
      boxShadow: '0 20px 50px rgba(25,25,36,.06)',
      zIndex: 1
    }
  }, /*#__PURE__*/React.createElement(DotMatrix, {
    size: 36
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: 18
    }
  }, /*#__PURE__*/React.createElement(Eyebrow, null, "Welcome back"), /*#__PURE__*/React.createElement(Display, {
    size: 32,
    style: {
      marginTop: 6
    }
  }, "Sign in to ", /*#__PURE__*/React.createElement("em", {
    style: {
      color: '#2D1B4E'
    }
  }, "the dots")), /*#__PURE__*/React.createElement("p", {
    style: {
      fontFamily: 'Satoshi',
      fontSize: 14,
      color: '#6E6B62',
      margin: '10px 0 28px',
      lineHeight: 1.55
    }
  }, "Your employees' dedicated AI agents, waiting for you."), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'grid',
      gap: 14
    }
  }, /*#__PURE__*/React.createElement(Input, {
    label: "Email",
    value: email,
    onChange: e => setEmail(e.target.value),
    icon: "mail"
  }), /*#__PURE__*/React.createElement(Input, {
    label: "Password",
    type: "password",
    value: password,
    onChange: e => setPassword(e.target.value),
    icon: "lock"
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: 24,
      display: 'flex',
      flexDirection: 'column',
      gap: 10
    }
  }, /*#__PURE__*/React.createElement(Button, {
    variant: "primary",
    size: "lg",
    iconRight: "arrow-right",
    onClick: onLogin
  }, "Sign in"), /*#__PURE__*/React.createElement(Button, {
    variant: "outline",
    size: "lg",
    icon: "chrome"
  }, "Continue with Google")), /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: 22,
      fontFamily: 'Satoshi',
      fontSize: 12,
      color: '#918D82',
      textAlign: 'center'
    }
  }, "New to ZeroOne? ", /*#__PURE__*/React.createElement("a", {
    style: {
      color: '#2D1B4E',
      textDecoration: 'none',
      fontWeight: 500
    }
  }, "Request access \u2192")))));
}
function HomePage() {
  return /*#__PURE__*/React.createElement("div", {
    style: {
      padding: '40px 48px'
    }
  }, /*#__PURE__*/React.createElement(Eyebrow, null, "Dashboard \xB7 Feb 2026"), /*#__PURE__*/React.createElement(Display, {
    size: 48,
    style: {
      marginTop: 8,
      maxWidth: 720
    }
  }, "Good morning, Meet. Your ", /*#__PURE__*/React.createElement("em", {
    style: {
      color: '#2D1B4E'
    }
  }, "margins"), " are up 23% this quarter."), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: 10,
      marginTop: 18,
      flexWrap: 'wrap'
    }
  }, /*#__PURE__*/React.createElement(Badge, {
    pillar: "data"
  }, "D \xB7 Data \xB7 94 score"), /*#__PURE__*/React.createElement(Badge, {
    pillar: "operations"
  }, "O \xB7 Ops \xB7 88 score"), /*#__PURE__*/React.createElement(Badge, {
    pillar: "tech"
  }, "T \xB7 Tech \xB7 91 score"), /*#__PURE__*/React.createElement(Badge, {
    pillar: "strategy"
  }, "S \xB7 Strategy \xB7 86 score")), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'grid',
      gridTemplateColumns: 'repeat(4,1fr)',
      gap: 16,
      marginTop: 32
    }
  }, /*#__PURE__*/React.createElement(StatCard, {
    label: "Margin lift",
    value: "+23%",
    delta: "+4.1 vs Q4",
    pillar: "data"
  }), /*#__PURE__*/React.createElement(StatCard, {
    label: "Active agents",
    value: "18",
    delta: "+3 this week",
    pillar: "operations"
  }), /*#__PURE__*/React.createElement(StatCard, {
    label: "Workflows",
    value: "142",
    delta: "+12%",
    pillar: "tech"
  }), /*#__PURE__*/React.createElement(StatCard, {
    label: "ROI \xB7 90d",
    value: "4.7\xD7",
    delta: "+0.3",
    pillar: "strategy"
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: 40,
      display: 'grid',
      gridTemplateColumns: '2fr 1fr',
      gap: 20
    }
  }, /*#__PURE__*/React.createElement(Card, null, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      justifyContent: 'space-between',
      alignItems: 'flex-start',
      marginBottom: 18
    }
  }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement(Eyebrow, null, "Private Model \xB7 v3.2.1"), /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: 'Chubbo, sans-serif',
      fontWeight: 800,
      fontSize: 20,
      marginTop: 6,
      color: '#191924',
      letterSpacing: '-0.02em'
    }
  }, "Self-improvement run")), /*#__PURE__*/React.createElement(Badge, {
    tone: "success"
  }, "Live")), /*#__PURE__*/React.createElement("div", {
    style: {
      height: 160,
      background: 'linear-gradient(180deg, rgba(200,182,255,.12), transparent)',
      borderRadius: 12,
      position: 'relative',
      overflow: 'hidden'
    }
  }, /*#__PURE__*/React.createElement("svg", {
    width: "100%",
    height: "100%",
    viewBox: "0 0 600 160",
    preserveAspectRatio: "none"
  }, /*#__PURE__*/React.createElement("path", {
    d: "M0,130 C80,120 140,90 200,80 C260,70 320,100 380,70 C440,45 500,30 600,20",
    stroke: "#C8B6FF",
    strokeWidth: "2.5",
    fill: "none"
  }), /*#__PURE__*/React.createElement("path", {
    d: "M0,130 C80,120 140,90 200,80 C260,70 320,100 380,70 C440,45 500,30 600,20 L600,160 L0,160 Z",
    fill: "url(#grad1)"
  }), /*#__PURE__*/React.createElement("defs", null, /*#__PURE__*/React.createElement("linearGradient", {
    id: "grad1",
    x1: "0",
    x2: "0",
    y1: "0",
    y2: "1"
  }, /*#__PURE__*/React.createElement("stop", {
    offset: "0",
    stopColor: "#C8B6FF",
    stopOpacity: ".35"
  }), /*#__PURE__*/React.createElement("stop", {
    offset: "1",
    stopColor: "#C8B6FF",
    stopOpacity: "0"
  }))))), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      justifyContent: 'space-between',
      marginTop: 14,
      fontFamily: 'JetBrains Mono, monospace',
      fontSize: 10,
      color: '#918D82',
      letterSpacing: 1.5,
      textTransform: 'uppercase'
    }
  }, /*#__PURE__*/React.createElement("span", null, "DEC"), /*#__PURE__*/React.createElement("span", null, "JAN"), /*#__PURE__*/React.createElement("span", null, "FEB"), /*#__PURE__*/React.createElement("span", null, "MAR"), /*#__PURE__*/React.createElement("span", null, "APR"))), /*#__PURE__*/React.createElement(Card, {
    variant: "dark"
  }, /*#__PURE__*/React.createElement(Eyebrow, {
    color: "rgba(200,182,255,.85)"
  }, "Next best action"), /*#__PURE__*/React.createElement(Display, {
    size: 22,
    style: {
      color: '#fff',
      marginTop: 8
    }
  }, "Fine-tune ", /*#__PURE__*/React.createElement("em", {
    style: {
      color: '#C8B6FF'
    }
  }, "invoicing agent"), " on Q1 data"), /*#__PURE__*/React.createElement("p", {
    style: {
      fontFamily: 'Satoshi',
      fontSize: 13,
      color: 'rgba(255,255,255,.7)',
      lineHeight: 1.55,
      margin: '12px 0 18px'
    }
  }, "Est. +$14k / month. 18 min to deploy. We've pre-flagged 2,840 tickets."), /*#__PURE__*/React.createElement(Button, {
    variant: "secondary",
    size: "md",
    iconRight: "arrow-right"
  }, "Review run"))), /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: 32
    }
  }, /*#__PURE__*/React.createElement(Alert, {
    tone: "info"
  }, "D.O.T.S. assessment for Acme Co. is ready \u2014 4 pillars scored, roadmap generated.")));
}
function AgentsPage() {
  const agents = [{
    name: 'Invoice Triage',
    pillar: 'operations',
    desc: 'Auto-categorizes & routes 12k invoices/day',
    status: 'Live',
    runs: '48,291'
  }, {
    name: 'Contract Analyst',
    pillar: 'data',
    desc: 'Summarizes, redlines, extracts clauses',
    status: 'Live',
    runs: '3,104'
  }, {
    name: 'Support Synthesizer',
    pillar: 'tech',
    desc: 'Clusters support tickets into fix-signals',
    status: 'Live',
    runs: '22,841'
  }, {
    name: 'Roadmap Writer',
    pillar: 'strategy',
    desc: 'Drafts quarterly roadmaps from metrics',
    status: 'Tuning',
    runs: '142'
  }, {
    name: 'Sales Researcher',
    pillar: 'data',
    desc: 'Finds ICP matches + drafts outreach',
    status: 'Live',
    runs: '9,772'
  }, {
    name: 'Ops Monitor',
    pillar: 'operations',
    desc: 'Watches dashboards, flags anomalies',
    status: 'Live',
    runs: '∞'
  }];
  return /*#__PURE__*/React.createElement("div", {
    style: {
      padding: '40px 48px'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      justifyContent: 'space-between',
      alignItems: 'flex-end',
      marginBottom: 28
    }
  }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement(Eyebrow, null, "Your team's AI agents"), /*#__PURE__*/React.createElement(Display, {
    size: 40,
    style: {
      marginTop: 8
    }
  }, "Agents"), /*#__PURE__*/React.createElement("p", {
    style: {
      fontFamily: 'Satoshi',
      fontSize: 14,
      color: '#6E6B62',
      maxWidth: 540,
      marginTop: 10
    }
  }, "Dedicated agents, fine-tuned on your business. Each one earns its keep \u2014 we'll tell you if it doesn't.")), /*#__PURE__*/React.createElement(Button, {
    variant: "primary",
    icon: "plus",
    size: "lg"
  }, "New agent")), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'grid',
      gridTemplateColumns: 'repeat(3,1fr)',
      gap: 16
    }
  }, agents.map(a => /*#__PURE__*/React.createElement(Card, {
    key: a.name,
    pillar: a.pillar,
    onClick: () => {}
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      justifyContent: 'space-between',
      alignItems: 'flex-start',
      marginBottom: 10
    }
  }, /*#__PURE__*/React.createElement(Badge, {
    pillar: a.pillar
  }, a.pillar.slice(0, 1).toUpperCase(), " \xB7 ", a.pillar), /*#__PURE__*/React.createElement(Badge, {
    tone: a.status === 'Live' ? 'success' : 'warning'
  }, a.status)), /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: 'Chubbo, sans-serif',
      fontWeight: 800,
      fontSize: 18,
      color: '#191924',
      lineHeight: 1.15,
      letterSpacing: '-0.02em'
    }
  }, a.name), /*#__PURE__*/React.createElement("p", {
    style: {
      fontFamily: 'Satoshi',
      fontSize: 13,
      color: '#6E6B62',
      lineHeight: 1.5,
      marginTop: 8,
      marginBottom: 16
    }
  }, a.desc), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      justifyContent: 'space-between',
      alignItems: 'center',
      paddingTop: 14,
      borderTop: '1px solid #E8E6E0'
    }
  }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: 'JetBrains Mono, monospace',
      fontSize: 9,
      letterSpacing: 1.5,
      textTransform: 'uppercase',
      color: '#918D82'
    }
  }, "Runs \xB7 30d"), /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: 'Chubbo, sans-serif',
      fontWeight: 800,
      fontSize: 18,
      color: '#191924',
      letterSpacing: '-0.03em'
    }
  }, a.runs)), /*#__PURE__*/React.createElement(Button, {
    variant: "ghost",
    size: "sm",
    iconRight: "arrow-right"
  }, "Open"))))));
}
function DataPage() {
  return /*#__PURE__*/React.createElement("div", {
    style: {
      padding: '40px 48px'
    }
  }, /*#__PURE__*/React.createElement(Eyebrow, null, "D \xB7 Data pillar"), /*#__PURE__*/React.createElement(Display, {
    size: 44,
    style: {
      marginTop: 8
    }
  }, "The ", /*#__PURE__*/React.createElement("em", {
    style: {
      color: '#2D1B4E'
    }
  }, "right data"), ", well-shaped."), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'grid',
      gridTemplateColumns: 'repeat(3,1fr)',
      gap: 16,
      marginTop: 32
    }
  }, [{
    t: 'Sources',
    v: '12',
    s: '3 CRMs · 2 warehouses · 7 docs'
  }, {
    t: 'Freshness',
    v: '4m',
    s: 'p95 lag across connectors'
  }, {
    t: 'Synthetic',
    v: '1.2M',
    s: 'Hypothesis rows generated'
  }].map(s => /*#__PURE__*/React.createElement(Card, {
    key: s.t,
    pillar: "data"
  }, /*#__PURE__*/React.createElement(Eyebrow, null, s.t), /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: 'Chubbo, sans-serif',
      fontWeight: 900,
      fontSize: 44,
      color: '#191924',
      margin: '6px 0 4px',
      lineHeight: 1,
      letterSpacing: '-0.04em'
    }
  }, s.v), /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: 'Satoshi',
      fontSize: 12,
      color: '#918D82'
    }
  }, s.s)))), /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: 32
    }
  }, /*#__PURE__*/React.createElement(Card, null, /*#__PURE__*/React.createElement(Eyebrow, null, "Connectors"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'grid',
      gridTemplateColumns: 'repeat(4,1fr)',
      gap: 12,
      marginTop: 16
    }
  }, ['Salesforce', 'HubSpot', 'Snowflake', 'Postgres', 'Notion', 'Drive', 'Slack', 'Zendesk'].map(c => /*#__PURE__*/React.createElement("div", {
    key: c,
    style: {
      padding: '14px 16px',
      border: '1px solid #E8E6E0',
      borderRadius: 12,
      background: '#FDFCFA',
      display: 'flex',
      alignItems: 'center',
      gap: 10
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      width: 28,
      height: 28,
      borderRadius: 8,
      background: 'rgba(200,182,255,.18)',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center'
    }
  }, /*#__PURE__*/React.createElement("i", {
    "data-lucide": "database",
    style: {
      width: 14,
      height: 14,
      color: '#2D1B4E'
    }
  })), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: 'Satoshi',
      fontSize: 13,
      fontWeight: 500,
      color: '#191924'
    }
  }, c), /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: 'JetBrains Mono, monospace',
      fontSize: 9,
      letterSpacing: 1,
      color: '#918D82'
    }
  }, "CONNECTED"))))))));
}
Object.assign(window, {
  LoginPage,
  HomePage,
  AgentsPage,
  DataPage
});
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/platform/Pages.jsx", error: String((e && e.message) || e) }); }

// ui_kits/platform/Sidebar.jsx
try { (() => {
/* sidebar.jsx — dark collapsible sidebar */
const {
  useState
} = React;
const PILLARS = [{
  k: 'home',
  ic: 'home',
  label: 'Home'
}, {
  k: 'data',
  ic: 'database',
  label: 'Data',
  pillar: 'data'
}, {
  k: 'ops',
  ic: 'git-branch',
  label: 'Operations',
  pillar: 'operations'
}, {
  k: 'tech',
  ic: 'cpu',
  label: 'Tech',
  pillar: 'tech'
}, {
  k: 'strategy',
  ic: 'compass',
  label: 'Strategy',
  pillar: 'strategy'
}, {
  k: 'agents',
  ic: 'sparkles',
  label: 'Agents'
}, {
  k: 'analytics',
  ic: 'bar-chart-3',
  label: 'Analytics'
}];

/* Dot grid mark — 3×3, diagonal accent dots matching each pillar */
function DotMark({
  size = 32
}) {
  const dot = Math.round(size / 3.8);
  const gap = Math.round(dot * 0.55);
  const colors = ['#C8B6FF', 'rgba(255,255,255,.10)', 'rgba(255,255,255,.06)', 'rgba(255,255,255,.06)', '#B8E0D2', 'rgba(255,255,255,.10)', 'rgba(255,255,255,.06)', 'rgba(255,255,255,.10)', '#FFCDB2'];
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'grid',
      gridTemplateColumns: `repeat(3,${dot}px)`,
      gap: `${gap}px`,
      flexShrink: 0
    }
  }, colors.map((c, i) => /*#__PURE__*/React.createElement("span", {
    key: i,
    style: {
      width: dot,
      height: dot,
      borderRadius: '50%',
      background: c,
      display: 'block'
    }
  })));
}

/* Full logo lockup for expanded sidebar */
function LogoLockup() {
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 11
    }
  }, /*#__PURE__*/React.createElement(DotMark, {
    size: 34
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 2,
      lineHeight: 1
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: 'Chubbo, sans-serif',
      fontWeight: 900,
      fontSize: 13,
      letterSpacing: '0.18em',
      color: '#fff',
      textTransform: 'uppercase'
    }
  }, "Zeroone"), /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: 'JetBrains Mono, monospace',
      fontWeight: 700,
      fontSize: 8.5,
      letterSpacing: '0.12em',
      display: 'flex',
      alignItems: 'center',
      gap: 1
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      color: '#C8B6FF'
    }
  }, "D"), /*#__PURE__*/React.createElement("span", {
    style: {
      color: 'rgba(255,255,255,.28)'
    }
  }, "\xB7"), /*#__PURE__*/React.createElement("span", {
    style: {
      color: '#B8E0D2'
    }
  }, "O"), /*#__PURE__*/React.createElement("span", {
    style: {
      color: 'rgba(255,255,255,.28)'
    }
  }, "\xB7"), /*#__PURE__*/React.createElement("span", {
    style: {
      color: '#FFCDB2'
    }
  }, "T"), /*#__PURE__*/React.createElement("span", {
    style: {
      color: 'rgba(255,255,255,.28)'
    }
  }, "\xB7"), /*#__PURE__*/React.createElement("span", {
    style: {
      color: '#A2D2FF'
    }
  }, "S"), /*#__PURE__*/React.createElement("span", {
    style: {
      color: 'rgba(255,255,255,.38)'
    }
  }, "\xA0AI"))));
}
function Sidebar({
  page,
  onNavigate,
  collapsed,
  onToggle
}) {
  return /*#__PURE__*/React.createElement("aside", {
    style: {
      width: collapsed ? 64 : 232,
      background: '#13131D',
      color: '#A8A6B0',
      transition: 'width 250ms cubic-bezier(0.16,1,0.3,1)',
      display: 'flex',
      flexDirection: 'column',
      borderRight: '1px solid #1F1F2E',
      flexShrink: 0,
      overflow: 'hidden'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      padding: collapsed ? '16px 0' : '16px 16px 14px',
      display: 'flex',
      alignItems: 'center',
      justifyContent: collapsed ? 'center' : 'flex-start',
      borderBottom: '1px solid #1F1F2E',
      minHeight: 60
    }
  }, collapsed ? /*#__PURE__*/React.createElement(DotMark, {
    size: 28
  }) : /*#__PURE__*/React.createElement(LogoLockup, null)), /*#__PURE__*/React.createElement("nav", {
    style: {
      flex: 1,
      padding: '12px 10px',
      display: 'flex',
      flexDirection: 'column',
      gap: 2
    }
  }, PILLARS.map(it => {
    const active = page === it.k;
    const pillarColor = {
      data: '#C8B6FF',
      operations: '#B8E0D2',
      tech: '#FFCDB2',
      strategy: '#A2D2FF'
    }[it.pillar];
    return /*#__PURE__*/React.createElement("button", {
      key: it.k,
      onClick: () => onNavigate(it.k),
      style: {
        display: 'flex',
        alignItems: 'center',
        gap: 12,
        padding: '9px 12px',
        borderRadius: 10,
        border: 'none',
        background: active ? '#252538' : 'transparent',
        color: active ? '#fff' : '#A8A6B0',
        fontFamily: 'Satoshi, sans-serif',
        fontSize: 13,
        fontWeight: active ? 500 : 400,
        cursor: 'pointer',
        textAlign: 'left',
        width: '100%',
        position: 'relative',
        transition: 'background 150ms'
      },
      onMouseEnter: e => {
        if (!active) e.currentTarget.style.background = '#1E1E2E';
      },
      onMouseLeave: e => {
        if (!active) e.currentTarget.style.background = 'transparent';
      }
    }, pillarColor && active && /*#__PURE__*/React.createElement("span", {
      style: {
        position: 'absolute',
        left: 0,
        top: 8,
        bottom: 8,
        width: 3,
        borderRadius: 2,
        background: pillarColor
      }
    }), /*#__PURE__*/React.createElement("i", {
      "data-lucide": it.ic,
      style: {
        width: 16,
        height: 16,
        color: active && pillarColor ? pillarColor : undefined,
        flexShrink: 0
      }
    }), !collapsed && /*#__PURE__*/React.createElement("span", null, it.label));
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      padding: '12px 10px',
      borderTop: '1px solid #2A2A3C',
      display: 'flex',
      flexDirection: 'column',
      gap: 2
    }
  }, /*#__PURE__*/React.createElement("button", {
    onClick: () => onNavigate('settings'),
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 12,
      padding: '9px 12px',
      borderRadius: 10,
      border: 'none',
      background: 'transparent',
      color: '#A8A6B0',
      fontFamily: 'Satoshi',
      fontSize: 13,
      cursor: 'pointer',
      textAlign: 'left'
    }
  }, /*#__PURE__*/React.createElement("i", {
    "data-lucide": "settings",
    style: {
      width: 16,
      height: 16
    }
  }), !collapsed && /*#__PURE__*/React.createElement("span", null, "Settings")), /*#__PURE__*/React.createElement("button", {
    onClick: onToggle,
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 12,
      padding: '9px 12px',
      borderRadius: 10,
      border: 'none',
      background: 'transparent',
      color: '#6E6B78',
      fontFamily: 'Satoshi',
      fontSize: 13,
      cursor: 'pointer',
      textAlign: 'left'
    }
  }, /*#__PURE__*/React.createElement("i", {
    "data-lucide": collapsed ? 'chevron-right' : 'chevron-left',
    style: {
      width: 16,
      height: 16
    }
  }), !collapsed && /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 11,
      letterSpacing: 1,
      textTransform: 'uppercase'
    }
  }, "Collapse"))));
}
Object.assign(window, {
  Sidebar,
  DotMark
});
Object.assign(__ds_scope, { DotMark, Sidebar });
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/platform/Sidebar.jsx", error: String((e && e.message) || e) }); }

// ui_kits/platform/primitives.jsx
try { (() => {
/* Components.jsx — shared primitives */

function Eyebrow({
  children,
  color = '#918D82',
  style = {}
}) {
  return /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: 'JetBrains Mono, monospace',
      fontSize: 10,
      letterSpacing: 2,
      textTransform: 'uppercase',
      color,
      ...style
    }
  }, children);
}
function Display({
  children,
  size = 36,
  style = {},
  as = 'h1'
}) {
  const Tag = as;
  return /*#__PURE__*/React.createElement(Tag, {
    style: {
      fontFamily: 'Chubbo, sans-serif',
      fontWeight: 800,
      fontSize: size,
      lineHeight: 1.02,
      color: '#191924',
      margin: 0,
      letterSpacing: '-0.025em',
      ...style
    }
  }, children);
}
function Button({
  children,
  variant = 'primary',
  size = 'md',
  icon,
  iconRight,
  onClick,
  disabled
}) {
  const sizes = {
    sm: {
      p: '6px 12px',
      fs: 12
    },
    md: {
      p: '10px 18px',
      fs: 13
    },
    lg: {
      p: '12px 22px',
      fs: 14
    }
  }[size];
  const variants = {
    primary: {
      bg: '#191924',
      fg: '#fff',
      bd: 'none'
    },
    secondary: {
      bg: '#C8B6FF',
      fg: '#191924',
      bd: 'none'
    },
    outline: {
      bg: 'transparent',
      fg: '#191924',
      bd: '1.5px solid #E8E6E0'
    },
    ghost: {
      bg: 'transparent',
      fg: '#6E6B62',
      bd: 'none'
    }
  }[variant];
  return /*#__PURE__*/React.createElement("button", {
    onClick: onClick,
    disabled: disabled,
    style: {
      display: 'inline-flex',
      alignItems: 'center',
      gap: 6,
      padding: sizes.p,
      fontSize: sizes.fs,
      fontFamily: 'Satoshi',
      fontWeight: 500,
      borderRadius: 999,
      border: variants.bd,
      background: variants.bg,
      color: variants.fg,
      cursor: disabled ? 'not-allowed' : 'pointer',
      opacity: disabled ? .4 : 1,
      transition: 'all 150ms'
    },
    onMouseEnter: e => {
      if (!disabled) e.currentTarget.style.opacity = '.85';
    },
    onMouseLeave: e => {
      if (!disabled) e.currentTarget.style.opacity = '1';
    }
  }, icon && /*#__PURE__*/React.createElement("i", {
    "data-lucide": icon,
    style: {
      width: 14,
      height: 14
    }
  }), children, iconRight && /*#__PURE__*/React.createElement("i", {
    "data-lucide": iconRight,
    style: {
      width: 14,
      height: 14
    }
  }));
}
function Input({
  label,
  value,
  onChange,
  placeholder,
  type = 'text',
  error,
  hint,
  icon
}) {
  const [focus, setFocus] = React.useState(false);
  return /*#__PURE__*/React.createElement("label", {
    style: {
      display: 'block'
    }
  }, label && /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: 'Satoshi',
      fontSize: 11,
      fontWeight: 600,
      textTransform: 'uppercase',
      letterSpacing: 1.5,
      color: '#918D82',
      marginBottom: 6
    }
  }, label), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 8,
      padding: '10px 14px',
      borderRadius: 12,
      background: '#fff',
      border: `1.5px solid ${error ? '#EF4444' : focus ? '#C8B6FF' : '#E8E6E0'}`,
      boxShadow: focus && !error ? '0 0 0 4px rgba(200,182,255,.18)' : 'none',
      transition: 'border-color 150ms, box-shadow 150ms'
    }
  }, icon && /*#__PURE__*/React.createElement("i", {
    "data-lucide": icon,
    style: {
      width: 14,
      height: 14,
      color: '#918D82'
    }
  }), /*#__PURE__*/React.createElement("input", {
    type: type,
    value: value,
    onChange: onChange,
    placeholder: placeholder,
    onFocus: () => setFocus(true),
    onBlur: () => setFocus(false),
    style: {
      border: 'none',
      outline: 'none',
      background: 'transparent',
      fontFamily: 'Satoshi',
      fontSize: 13,
      color: '#191924',
      flex: 1,
      padding: 0
    }
  })), (error || hint) && /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 11,
      marginTop: 5,
      color: error ? '#EF4444' : '#918D82',
      fontFamily: 'Satoshi'
    }
  }, error || hint));
}
function Badge({
  children,
  pillar,
  tone = 'default'
}) {
  const pillarStyles = {
    data: {
      bg: 'rgba(200,182,255,.2)',
      fg: '#2D1B4E',
      dot: '#C8B6FF'
    },
    operations: {
      bg: 'rgba(184,224,210,.25)',
      fg: '#1a5c42',
      dot: '#B8E0D2'
    },
    tech: {
      bg: 'rgba(255,205,178,.25)',
      fg: '#8b4513',
      dot: '#FFCDB2'
    },
    strategy: {
      bg: 'rgba(162,210,255,.25)',
      fg: '#1a4a7a',
      dot: '#A2D2FF'
    }
  };
  const toneStyles = {
    default: {
      bg: '#F8F7F4',
      fg: '#4A4842',
      dot: '#918D82'
    },
    success: {
      bg: 'rgba(184,224,210,.2)',
      fg: '#1a5c42',
      dot: '#B8E0D2'
    },
    warning: {
      bg: 'rgba(255,243,176,.35)',
      fg: '#8b6914',
      dot: '#FFF3B0'
    }
  };
  const s = pillar && pillarStyles[pillar] || toneStyles[tone] || toneStyles.default;
  return /*#__PURE__*/React.createElement("span", {
    style: {
      display: 'inline-flex',
      alignItems: 'center',
      gap: 6,
      padding: '4px 10px',
      borderRadius: 999,
      background: s.bg,
      color: s.fg,
      fontFamily: 'JetBrains Mono, monospace',
      fontSize: 10,
      letterSpacing: 1.5,
      textTransform: 'uppercase'
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      width: 6,
      height: 6,
      borderRadius: '50%',
      background: s.dot
    }
  }), children);
}
function Card({
  children,
  style = {},
  pillar,
  variant = 'default',
  onClick
}) {
  const pillarColors = {
    data: '#C8B6FF',
    operations: '#B8E0D2',
    tech: '#FFCDB2',
    strategy: '#A2D2FF'
  };
  const variants = {
    default: {
      bg: '#fff',
      border: '1px solid #E8E6E0',
      color: '#191924'
    },
    cream: {
      bg: '#F8F7F4',
      border: '1px solid #E8E6E0',
      color: '#191924'
    },
    dark: {
      bg: 'linear-gradient(135deg, #2D1B4E, #191924)',
      border: 'none',
      color: '#fff'
    }
  }[variant];
  return /*#__PURE__*/React.createElement("div", {
    onClick: onClick,
    style: {
      background: variants.bg,
      border: variants.border,
      color: variants.color,
      borderRadius: 16,
      padding: 20,
      borderLeft: pillar ? `3px solid ${pillarColors[pillar]}` : variants.border.includes('1px') ? undefined : undefined,
      cursor: onClick ? 'pointer' : 'default',
      transition: 'transform 200ms cubic-bezier(0.16,1,0.3,1), box-shadow 200ms',
      ...style
    },
    onMouseEnter: e => {
      if (onClick) {
        e.currentTarget.style.transform = 'translateY(-3px)';
        e.currentTarget.style.boxShadow = '0 10px 32px rgba(25,25,36,.08)';
      }
    },
    onMouseLeave: e => {
      if (onClick) {
        e.currentTarget.style.transform = 'translateY(0)';
        e.currentTarget.style.boxShadow = 'none';
      }
    }
  }, children);
}
function StatCard({
  label,
  value,
  delta,
  deltaDir = 'up',
  pillar
}) {
  return /*#__PURE__*/React.createElement(Card, {
    pillar: pillar
  }, /*#__PURE__*/React.createElement(Eyebrow, null, label), /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: 'Chubbo, sans-serif',
      fontWeight: 800,
      fontSize: 38,
      lineHeight: 1,
      letterSpacing: '-0.03em',
      margin: '8px 0 6px',
      color: '#191924'
    }
  }, value), delta && /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: 'JetBrains Mono, monospace',
      fontSize: 11,
      color: deltaDir === 'up' ? '#10B981' : '#EF4444'
    }
  }, deltaDir === 'up' ? '↗' : '↘', " ", delta));
}
function Alert({
  tone = 'info',
  children,
  icon
}) {
  const tones = {
    success: {
      bg: 'rgba(184,224,210,.2)',
      bd: 'rgba(184,224,210,.5)',
      fg: '#1a5c42',
      ic: icon || 'check-circle'
    },
    warning: {
      bg: 'rgba(255,243,176,.35)',
      bd: 'rgba(255,224,160,.55)',
      fg: '#8b6914',
      ic: icon || 'alert-triangle'
    },
    error: {
      bg: 'rgba(255,181,194,.18)',
      bd: 'rgba(255,155,155,.4)',
      fg: '#8b2222',
      ic: icon || 'x-circle'
    },
    info: {
      bg: 'rgba(162,210,255,.2)',
      bd: 'rgba(162,210,255,.5)',
      fg: '#1a4a7a',
      ic: icon || 'info'
    }
  }[tone];
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 10,
      padding: '12px 16px',
      borderRadius: 12,
      background: tones.bg,
      border: `1px solid ${tones.bd}`,
      color: tones.fg,
      fontFamily: 'Satoshi',
      fontSize: 13
    }
  }, /*#__PURE__*/React.createElement("i", {
    "data-lucide": tones.ic,
    style: {
      width: 16,
      height: 16,
      flexShrink: 0
    }
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1
    }
  }, children));
}
function Avatar({
  initials = 'MD',
  size = 36,
  gradient = '135deg, #C8B6FF, #A2D2FF'
}) {
  return /*#__PURE__*/React.createElement("div", {
    style: {
      width: size,
      height: size,
      borderRadius: '50%',
      background: `linear-gradient(${gradient})`,
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      fontFamily: 'Chubbo, sans-serif',
      fontWeight: 800,
      color: '#191924',
      fontSize: Math.round(size * 0.36),
      letterSpacing: '-0.02em'
    }
  }, initials);
}
Object.assign(window, {
  Eyebrow,
  Display,
  Button,
  Input,
  Badge,
  Card,
  StatCard,
  Alert,
  Avatar
});
Object.assign(__ds_scope, { Eyebrow, Display, Button, Input, Badge, Card, StatCard, Alert, Avatar });
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/platform/primitives.jsx", error: String((e && e.message) || e) }); }

__ds_ns.Navbar = __ds_scope.Navbar;

__ds_ns.DotMark = __ds_scope.DotMark;

__ds_ns.Sidebar = __ds_scope.Sidebar;

__ds_ns.Eyebrow = __ds_scope.Eyebrow;

__ds_ns.Display = __ds_scope.Display;

__ds_ns.Button = __ds_scope.Button;

__ds_ns.Input = __ds_scope.Input;

__ds_ns.Badge = __ds_scope.Badge;

__ds_ns.Card = __ds_scope.Card;

__ds_ns.StatCard = __ds_scope.StatCard;

__ds_ns.Alert = __ds_scope.Alert;

__ds_ns.Avatar = __ds_scope.Avatar;

})();
