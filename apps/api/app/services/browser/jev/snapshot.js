// Atomic page snapshot for Jev: visible content and the controls a press can reach,
// code-owned node identity, and the guards that tell a stale decision.
// Ported from browser-use/jev-ultrafast (MIT) jev_ultrafast/snapshot.js, then
// extended to open shadow roots, same-origin iframes, password fields (offered
// as secret targets, never with their value), inner scroll containers, and
// each control's id or name. A control is offered only where a press at one of
// its boxes reaches it: the hit-test act.js repeats just before the input.
(() => {
  const TEXT_BUDGET=6000, MAX_ACTIONS=250, LABEL_CHARS=300, PAGE_SCROLL=560;
  // An inner container turns by most of its visible height, so a row stays in view across the turn.
  const CONTAINER_SCROLL=0.8;
  const WAIT={id:'wait',kind:'wait',label:'Wait for the page to update'};
  const ROLES=['button','link','checkbox','radio','switch','tab','menuitem','menuitemradio',
    'menuitemcheckbox','option','gridcell','treeitem','slider','combobox','textbox','searchbox','spinbutton'];
  const SELECTOR='a[href],button,input,textarea,select,summary,[contenteditable="true"],'+
    '[onclick]:not(html):not(body),'+ROLES.map(role=>'[role="'+role+'"]').join(',');
  const INPUT_ROLES={checkbox:'checkbox',radio:'radio',button:'button',submit:'button',reset:'button',
    image:'button',search:'searchbox',number:'spinbutton',password:'password',range:'slider',text:'textbox',
    email:'textbox',url:'textbox',tel:'textbox',date:'textbox','datetime-local':'textbox',month:'textbox',
    week:'textbox',time:'textbox'};
  const TAG_ROLES={BUTTON:'button',SUMMARY:'button',SELECT:'combobox',TEXTAREA:'textbox'};

  const isFrame = e => e.tagName==='IFRAME' || e.tagName==='FRAME';
  const isSecret = e => e.tagName==='INPUT' && e.type==='password';
  const isSafe = e => !['file','hidden'].includes(e.type);
  const isFormControl = e => ['INPUT','SELECT','TEXTAREA'].includes(e.tagName);
  // A form control styled away (opacity 0 under a custom box) is judged by the press alone.
  const isVisible = e => !e.closest('[aria-hidden="true"],[inert]') &&
    e.checkVisibility({checkOpacity:!isFormControl(e),checkVisibilityCSS:true});
  const frameDocument = frame => { try { return frame.contentDocument; } catch (_) { return null; } };
  // Where a frame's content starts, in its owner document's viewport: inside border and padding.
  const contentOrigin = frame => {
    const r=frame.getBoundingClientRect(), s=getComputedStyle(frame);
    return [r.x+parseFloat(s.borderLeftWidth)+parseFloat(s.paddingLeft),
      r.y+parseFloat(s.borderTopWidth)+parseFloat(s.paddingTop)];
  };
  const up = n => n.parentElement || (n.getRootNode() instanceof ShadowRoot ? n.getRootNode().host : null);
  const inViewport = (r, ox, oy) =>
    r.width>0 && r.height>0 && r.bottom+oy>0 && r.top+oy<innerHeight && r.right+ox>0 && r.left+ox<innerWidth;

  // A document still parsing has no body yet, and says so at once: the caller waits for it.
  // One that is parsed and never has a body offers nothing.
  function bodiless(cache) {
    if (document.readyState==='loading') return {loading:true,url:location.href};
    cache.pageKey=()=>[performance.timeOrigin,location.href];
    cache.guard=()=>null;
    return {url:location.href,title:document.title,text:'',text_cut:false,actions:[WAIT],
      page_key:cache.pageKey(),guards:{},omitted_actions:0,frames:[]};
  }

  // Every document and open shadow root the snapshot reads, with the offset from its
  // viewport to the top one (same-origin iframes only), and every frame on the page.
  function collectRoots() {
    const roots=[], frames=[];
    const collect = (root, ox, oy) => {
      roots.push({root, ox, oy});
      for (const e of root.querySelectorAll('*')) {
        if (e.shadowRoot) collect(e.shadowRoot, ox, oy);
        if (isFrame(e)) frameOf(e, ox, oy, frames, collect);
      }
    };
    collect(document, 0, 0);
    return {roots, frames};
  }

  function frameOf(e, ox, oy, frames, collect) {
    const r=e.getBoundingClientRect(), doc=frameDocument(e);
    frames.push({src:e.src || '', same_origin:!!doc, loaded:!!doc && doc.readyState==='complete',
      visible:r.width>0 && r.height>0 && r.bottom+oy>0 && r.top+oy<innerHeight && isVisible(e)});
    if (doc && doc.body) { const [fx,fy]=contentOrigin(e); collect(doc, ox+fx, oy+fy); }
  }

  // A control's accessible name: what it references, its own labels, then its text and hints.
  function accessibleName(e, seen=new Set()) {
    if (!e || seen.has(e)) return '';
    seen.add(e);
    return referencedName(e, seen) || e.getAttribute('aria-label') || labelsName(e, seen) ||
      buttonValue(e) || e.getAttribute('alt') || childrenName(e, seen) ||
      e.getAttribute('title') || e.getAttribute('placeholder') || '';
  }

  function referencedName(e, seen) {
    // aria-labelledby ids resolve in the element's own tree: a shadow root, or its document.
    const scope=e.getRootNode().getElementById ? e.getRootNode() : (e.ownerDocument || document);
    return (e.getAttribute('aria-labelledby')||'').split(/\s+/).filter(Boolean)
      .map(id=>accessibleName(scope.getElementById(id), seen)).filter(Boolean).join(' ');
  }

  const labelsName = (e, seen) => [...(e.labels||[])].map(l=>accessibleName(l, seen)).filter(Boolean).join(' ');
  const buttonValue = e => ['button','submit','reset'].includes(e.type) ? e.value : '';

  function childrenName(e, seen) {
    if (e.tagName==='INPUT') return '';
    return [...e.childNodes].map(n=>childName(n, seen)).join(' ').trim();
  }

  function childName(n, seen) {
    if (n.nodeType===3) return n.textContent;
    return n.nodeType===1 && n.getAttribute('aria-hidden')!=='true' ? accessibleName(n, seen) : '';
  }

  function roleOf(e) {
    const explicit=e.getAttribute('role');
    if (ROLES.includes(explicit)) return explicit;
    if (TAG_ROLES[e.tagName]) return TAG_ROLES[e.tagName];
    if (e.tagName==='A' && e.hasAttribute('href')) return 'link';
    if (e.isContentEditable) return 'textbox';
    if (e.tagName==='INPUT' && INPUT_ROLES[e.type]) return INPUT_ROLES[e.type];
    return e.hasAttribute('onclick') ? 'button' : null;
  }

  // The deepest element a press at a top-viewport point lands on, through open shadow roots and same-origin frames.
  function deepHit(x, y) {
    let hit=document.elementFromPoint(x,y), ox=0, oy=0;
    while (hit) {
      const inner=hit.shadowRoot && hit.shadowRoot.elementFromPoint(x-ox,y-oy);
      if (inner && inner!==hit) { hit=inner; continue; }
      const doc=isFrame(hit) && frameDocument(hit);
      if (!doc) break;
      const [fx,fy]=contentOrigin(hit); ox+=fx; oy+=fy;
      const next=doc.elementFromPoint(x-ox,y-oy);
      if (!next) break;
      hit=next;
    }
    return hit;
  }

  // Whether a press landing on hit reaches e itself: no other control nearer the press, or a label of e.
  function reaches(hit, e) {
    for (let n=hit; n; n=up(n)) {
      if (n===e || (n.tagName==='LABEL' && n.control===e)) return true;
      if (n.matches(SELECTOR)) return false;
    }
    return false;
  }

  function within(hit, e) {
    for (let n=hit; n; n=up(n)) if (n===e) return true;
    return false;
  }

  // The centre of the first box, clipped to the viewport, where a press is accepted for e.
  function pointFor(e, accepts, boxes, offsetOf) {
    const [ox,oy]=offsetOf(e);
    for (const r of boxes) {
      const left=Math.max(ox+r.left,0), right=Math.min(ox+r.right,innerWidth);
      const top=Math.max(oy+r.top,0), bottom=Math.min(oy+r.bottom,innerHeight);
      if (right-left<1 || bottom-top<1) continue;
      const x=(left+right)/2, y=(top+bottom)/2;
      if (accepts(deepHit(x,y), e)) return {x,y};
    }
    return null;
  }

  // Its own text: where a press reaches it when a control nested in it covers its centre.
  function* ownText(e) {
    const doc=e.ownerDocument || document, walker=doc.createTreeWalker(e,NodeFilter.SHOW_TEXT), range=doc.createRange();
    let node;
    while ((node=walker.nextNode())) {
      if (!node.textContent.trim() || node.parentElement?.closest(SELECTOR)!==e) continue;
      range.selectNodeContents(node);
      yield* range.getClientRects();
    }
  }

  // A control's boxes, then its own text, then its labels: the first a press reaches.
  function* pressBoxes(e) {
    yield* e.getClientRects();
    yield* ownText(e);
    for (const label of e.labels || []) yield* label.getClientRects();
  }

  function deepActive() {
    let a=document.activeElement;
    while (a) {
      if (a.shadowRoot && a.shadowRoot.activeElement) { a=a.shadowRoot.activeElement; continue; }
      const doc=isFrame(a) && frameDocument(a);
      if (!doc || !doc.activeElement || doc.activeElement===doc.body) break;
      a=doc.activeElement;
    }
    return a;
  }

  // An inner container that scrolls and a press inside can reach: its scroll is part of the page key.
  function isScroller(e, cache) {
    if (e===document.documentElement || e===document.body || !e.clientHeight) return false;
    if (e.scrollHeight<=e.clientHeight+1 || !isVisible(e)) return false;
    return ['auto','scroll','overlay'].includes(getComputedStyle(e).overflowY) && !!cache.wheelPoint(e);
  }

  // The cache act.js and guard.js read: identity, reachability, focus, the page key and each guard.
  function prepare(cache, roots) {
    const identity = e => {
      if (!cache.ids.has(e)) cache.ids.set(e,cache.next++);
      const id=cache.ids.get(e); cache.nodes.set(id,e); return id;
    };
    for (const [id,e] of cache.nodes) if (!e.isConnected) cache.nodes.delete(id);
    cache.identity=identity;
    cache.roots=roots.map(({root}) => root);
    cache.offsets=new WeakMap(roots.map(({root, ox, oy}) => [root, [ox, oy]]));
    const offsetOf = e => cache.offsets.get(e.getRootNode()) || [0, 0];
    cache.pressPoint = e => pointFor(e, reaches, pressBoxes(e), offsetOf);
    cache.wheelPoint = e => pointFor(e, within, [...e.getClientRects()], offsetOf);
    cache.deepActive = deepActive;
    const fields = () => roots.flatMap(({root}) => [...root.querySelectorAll('input,textarea,select')]).filter(isSafe);
    cache.scrollers = roots.flatMap(({root}) => [...root.querySelectorAll('*')])
      .filter(e => isScroller(e, cache)).map(identity);
    // A password field contributes whether it holds something, never what.
    cache.pageKey=()=>[performance.timeOrigin,location.href,scrollX,scrollY,innerWidth,innerHeight,
      cache.scrollers.map(id=>cache.nodes.get(id)?.scrollTop ?? null),
      fields().map(e=>[identity(e),isSecret(e) ? e.value.length : e.value,e.checked,e.selectedIndex,e.disabled,e.readOnly])];
    cache.guard = e => guardOf(e, identity);
  }

  function guardOf(e, identity) {
    if (!e?.isConnected || !isVisible(e)) return null;
    const scope=e.closest('form,dialog,[role="dialog"],article,li,tr,[role="row"]') || e.parentElement;
    return [identity(e),roleOf(e),accessibleName(e),isSecret(e) ? e.value.length : e.value??null,e.checked??null,
      e.selectedIndex??null,e.readOnly??null,e.matches(':disabled'),e.getAttribute('aria-disabled'),
      e.getAttribute('aria-expanded'),e.getAttribute('aria-checked'),e.getAttribute('aria-selected'),
      e.getAttribute('href'),scope?.innerText?.slice(0,6000)||''];
  }

  // What every action on a control carries: its identity, role, name, id or name attribute, box and states.
  function describe(e, rname, ox, oy, cache) {
    const r=e.getBoundingClientRect();
    const base={node:cache.identity(e),role:rname,label:(accessibleName(e)||rname).slice(0,LABEL_CHARS),
      ident:e.id || e.getAttribute('name') || '',rect:{x:ox+r.x,y:oy+r.y,w:r.width,h:r.height}};
    if (e.tagName==='INPUT') base.input_type=e.type;
    // The format a typed value takes, as the field states it.
    for (const key of ['placeholder','pattern']) {
      const hint=e.getAttribute(key);
      if (hint) base[key]=hint;
    }
    if (e.tagName==='A' && e.href) base.href=e.href;
    for (const key of ['checked','selected','expanded']) {
      const value=e.getAttribute('aria-'+key);
      if (value!==null) base[key]=value;
    }
    if (['checkbox','radio'].includes(e.type)) base.checked=String(e.checked);
    return base;
  }

  const isEditable = (e, rname) => !e.readOnly && e.getAttribute('aria-readonly')!=='true' &&
    (['textbox','searchbox','spinbutton'].includes(rname) || (rname==='slider' && e.tagName==='INPUT') ||
      (rname==='combobox' && ['INPUT','TEXTAREA'].includes(e.tagName)));

  // The actions one control offers: a secret to fill, a dropdown to set, a field to fill (and open), or a press.
  function controlActions(e, base) {
    if (isSecret(e)) return e.readOnly ? [] : [{...base,kind:'secret',value:'',filled:e.value.length>0}];
    if (e.tagName==='SELECT') return dropdownActions(e, base);
    const value='value' in e ? String(e.value) :
      e.isContentEditable || base.role==='combobox' ? e.innerText.trim() : '';
    if (!isEditable(e, base.role)) return [{...base,kind:'click',value}];
    return [{...base,kind:'fill',value}, {...base,kind:'click',value,label:'Open '+base.label}];
  }

  // One action per dropdown, its choices inside it: a long list never crowds out the controls after it.
  function dropdownActions(e, base) {
    const options=[...e.options].filter(o=>!o.selected && !o.disabled && !o.closest('optgroup[disabled]'))
      .map(o=>({value:o.value,label:o.label}));
    if (!options.length) return [];
    return [{...base,kind:'select',value:e.value,
      current_value:[...e.selectedOptions].map(o=>o.label).join(', '),options}];
  }

  const offered = e => isSafe(e) && isVisible(e) && !e.matches(':disabled') && !e.closest('[aria-disabled="true"]');

  // Every control a press reaches, and Enter for the observed field that holds focus.
  function collectActions(roots, cache) {
    const active=deepActive(), actions=[];
    let focused=null;
    for (const {root, ox, oy} of roots) for (const e of root.querySelectorAll(SELECTOR)) {
      const rname=offered(e) ? roleOf(e) : null;
      if (!rname || !cache.pressPoint(e)) continue;
      const own=controlActions(e, describe(e, rname, ox, oy, cache));
      actions.push(...own);
      if (e===active && own.some(a=>a.kind==='fill' || a.kind==='secret'))
        focused={id:'enter',kind:'enter',node:own[0].node,label:'Press Enter in '+own[0].label};
    }
    return {actions, focused};
  }

  // Visible text, in the order it reads down the screen, across every document and shadow root.
  function visibleText(roots) {
    const pieces=[];
    for (const {root, ox, oy} of roots) {
      const top=root.body || root, doc=root.ownerDocument || root;
      const walker=doc.createTreeWalker(top,NodeFilter.SHOW_TEXT), range=doc.createRange();
      let node;
      while ((node=walker.nextNode())) {
        const value=node.textContent.trim(), parent=node.parentElement;
        if (!value || !parent || parent.closest('script,style,noscript,template') || !isVisible(parent)) continue;
        range.selectNodeContents(node);
        const r=range.getBoundingClientRect();
        if (inViewport(r, ox, oy)) pieces.push({value, y:Math.max(r.top+oy,0)});
      }
    }
    // Stable: pieces on one line keep their document order.
    pieces.sort((a,b)=>Math.round(a.y)-Math.round(b.y));
    const words=[];
    let length=0;
    for (const {value} of pieces) { if (length>=TEXT_BUDGET) break; words.push(value); length+=value.length; }
    const joined=words.join('\n');
    return {text:joined.slice(0,TEXT_BUDGET), text_cut:joined.length>TEXT_BUDGET};
  }

  // Scrolling the page itself, and each inner container that has more to show either way.
  function scrollActions(cache) {
    const actions=[];
    if (scrollY+innerHeight<document.documentElement.scrollHeight-2)
      actions.push({id:'scroll_down',kind:'scroll',label:'Scroll down the page',delta:PAGE_SCROLL});
    if (scrollY>0) actions.push({id:'scroll_up',kind:'scroll',label:'Scroll up the page',delta:-PAGE_SCROLL});
    for (const node of cache.scrollers) actions.push(...containerScrolls(cache.nodes.get(node), node));
    return actions;
  }

  function containerScrolls(e, node) {
    const step=Math.round(e.clientHeight*CONTAINER_SCROLL), actions=[];
    const where=(e.getAttribute('aria-label') || e.textContent.trim().replace(/\s+/g,' ')).slice(0,80) ||
      'the scrollable area';
    if (e.scrollTop+e.clientHeight<e.scrollHeight-1)
      actions.push({id:'scroll_down_'+node,kind:'scroll',node,label:'Scroll down in '+where,delta:step});
    if (e.scrollTop>0)
      actions.push({id:'scroll_up_'+node,kind:'scroll',node,label:'Scroll up in '+where,delta:-step});
    return actions;
  }

  function snapshot() {
    const cache=window.__jevFast ||= {ids:new WeakMap(), nodes:new Map(), next:1};
    if (!document.body) return bodiless(cache);
    const {roots, frames}=collectRoots();
    prepare(cache, roots);
    const {actions, focused}=collectActions(roots, cache);
    const omitted_actions=Math.max(0,actions.length-MAX_ACTIONS);
    actions.splice(MAX_ACTIONS);
    actions.forEach((a,i)=>a.id='e'+(i+1));
    if (focused) actions.push(focused);
    actions.push(...scrollActions(cache), WAIT);
    const guards={};
    for (const a of actions) if (a.node!==undefined && !(a.node in guards)) guards[a.node]=cache.guard(cache.nodes.get(a.node));
    return {url:location.href,title:document.title,...visibleText(roots),
      actions,page_key:cache.pageKey(),guards,omitted_actions,frames};
  }

  return snapshot();
})()
