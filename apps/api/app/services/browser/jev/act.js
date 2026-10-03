// Resolve an observed target just before input: still connected, enabled and
// reachable by a press at one of its boxes (the snapshot's own hit-test).
// Returns what the input needs, or null when the target changed or is covered:
// the viewport point to press or to turn the wheel at, whether a field still
// holds focus for Enter, or that a <select> was set here, with its events.
// Ported from browser-use/jev-ultrafast (MIT) jev_ultrafast/browser.py.
function gaiaJevAct(action) {
  const c=window.__jevFast, e=c?.nodes.get(action.node);
  if (!e?.isConnected || e.matches(':disabled') || e.closest('[aria-disabled="true"],[inert]')) return null;
  if (action.kind==='scroll') return c.wheelPoint(e);
  if (action.kind==='enter') return c.deepActive()===e ? {focused:true} : null;
  if (['fill','secret'].includes(action.kind) && (e.readOnly || e.getAttribute('aria-readonly')==='true')) return null;
  const point=c.pressPoint(e);
  if (!point) return null;
  if (action.kind==='select') {
    if (e.tagName!=='SELECT' || ![...e.options].some(o=>o.value===action.value &&
        !o.disabled && !o.closest('optgroup[disabled]'))) return null;
    e.value=action.value;
    e.dispatchEvent(new Event('input',{bubbles:true}));
    e.dispatchEvent(new Event('change',{bubbles:true}));
    return {set:true};
  }
  return point;
}
// Whether the field a click just pressed holds focus now, so typed keys reach it.
function gaiaJevFocused(node) {
  const c=window.__jevFast, e=c?.nodes.get(node), active=c?.deepActive();
  return !!e && !!active && (active===e || (e.isContentEditable && e.contains(active)));
}
// What a field holds now: its value, or a rich editor's text.
function gaiaJevValue(node) {
  const e=window.__jevFast?.nodes.get(node);
  if (!e) return null;
  return 'value' in e ? String(e.value) : e.innerText;
}
// Set a field whose value is a format, not keystrokes (date, time, month, week, range), as
// its own value setter does, with the events a change fires; returns what it holds after.
function gaiaJevSet(arg) {
  const c=window.__jevFast, e=c?.nodes.get(arg.node);
  if (!e?.isConnected || e.readOnly || e.matches(':disabled') || !c.pressPoint(e)) return null;
  Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(e,arg.text);
  e.dispatchEvent(new Event('input',{bubbles:true}));
  e.dispatchEvent(new Event('change',{bubbles:true}));
  return String(e.value);
}
