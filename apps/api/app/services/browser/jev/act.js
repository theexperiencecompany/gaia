// Resolve an observed target just before input: still connected, enabled,
// visible, inside the viewport and not covered at its centre. Returns the
// viewport point to press, or null. A <select> is set here, with its events.
// Ported from browser-use/jev-ultrafast (MIT) jev_ultrafast/browser.py.
(action => {
  const c=window.__jevFast, e=c?.nodes.get(action.node);
  if (!e?.isConnected || e.matches(':disabled') || e.closest('[aria-disabled="true"],[inert]') ||
      !e.checkVisibility({checkOpacity:true,checkVisibilityCSS:true})) return null;
  if (['fill','secret'].includes(action.kind) && (e.readOnly || e.getAttribute('aria-readonly')==='true')) return null;
  const [ox,oy]=c.offsetOf(e), r=e.getBoundingClientRect(), lx=r.x+r.width/2, ly=r.y+r.height/2;
  const x=ox+lx, y=oy+ly;
  if (!r.width || !r.height || x<0 || y<0 || x>=innerWidth || y>=innerHeight) return null;
  const root=e.getRootNode(), hit=(root.elementFromPoint ? root : document).elementFromPoint(lx,ly);
  if (!e.contains(hit)) return null;
  if (action.kind==='select') {
    if (e.tagName!=='SELECT' || ![...e.options].some(o=>o.value===action.value &&
        !o.disabled && !o.closest('optgroup[disabled]'))) return null;
    e.value=action.value;
    e.dispatchEvent(new Event('input',{bubbles:true}));
    e.dispatchEvent(new Event('change',{bubbles:true}));
  }
  return {x,y};
})
