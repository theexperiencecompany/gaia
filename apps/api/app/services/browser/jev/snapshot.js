// Atomic page snapshot for Jev: visible content and the controls a press can reach,
// code-owned node identity, and the guards that tell a stale decision.
// Ported from browser-use/jev-ultrafast (MIT) jev_ultrafast/snapshot.js, then
// extended to open shadow roots, same-origin iframes, password fields (offered
// as secret targets, never with their value), inner scroll containers, and
// each control's id or name. A control is offered only where a press at one of
// its boxes reaches it: the hit-test act.js repeats just before the input.
(() => {
  // A document still parsing is read once its body exists; one that never has one offers nothing.
  if (!document.body && document.readyState==='loading')
    return new Promise(resolve=>document.addEventListener('DOMContentLoaded',()=>resolve(null),{once:true}));
  const cache = window.__jevFast ||= {ids:new WeakMap(), nodes:new Map(), next:1};
  if (!document.body) {
    cache.pageKey=()=>[performance.timeOrigin,location.href];
    cache.guard=()=>null;
    return {url:location.href,title:document.title,text:'',text_cut:false,
      actions:[{id:'wait',kind:'wait',label:'Wait for the page to update'}],
      page_key:cache.pageKey(),guards:{},omitted_actions:0,frames:[]};
  }
  const identity = e => {
    if (!cache.ids.has(e)) cache.ids.set(e,cache.next++);
    const id=cache.ids.get(e); cache.nodes.set(id,e); return id;
  };
  for (const [id,e] of cache.nodes) if (!e.isConnected) cache.nodes.delete(id);
  const TEXT_BUDGET=6000, MAX_ACTIONS=250, LABEL_CHARS=300, PAGE_SCROLL=560;
  // An inner container turns by most of its visible height, so a row stays in view across the turn.
  const CONTAINER_SCROLL=0.8;
  const secret = e => e.tagName==='INPUT' && e.type==='password';
  const safe = e => !['file','hidden'].includes(e.type);
  const formControl = e => ['INPUT','SELECT','TEXTAREA'].includes(e.tagName);
  // A form control styled away (opacity 0 under a custom box) is judged by the press alone.
  const visible = e => !e.closest('[aria-hidden="true"],[inert]') &&
    e.checkVisibility({checkOpacity:!formControl(e),checkVisibilityCSS:true});
  // Where a frame's content starts, in its owner document's viewport: inside border and padding.
  const contentOrigin = frame => {
    const r=frame.getBoundingClientRect(), s=getComputedStyle(frame);
    return [r.x+frame.clientLeft+parseFloat(s.paddingLeft), r.y+frame.clientTop+parseFloat(s.paddingTop)];
  };
  const frameDocument = frame => { try { return frame.contentDocument; } catch (_) { return null; } };
  // Every document and open shadow root the snapshot reads, with the offset
  // from its viewport to the top one (same-origin iframes only).
  const roots = [];
  const frames = [];
  const collect = (root, ox, oy) => {
    roots.push({root, ox, oy});
    for (const e of root.querySelectorAll('*')) {
      if (e.shadowRoot) collect(e.shadowRoot, ox, oy);
      if (e.tagName !== 'IFRAME' && e.tagName !== 'FRAME') continue;
      const r = e.getBoundingClientRect(), doc = frameDocument(e);
      frames.push({src: e.src || '', same_origin: !!doc,
        visible: r.width>0 && r.height>0 && r.bottom+oy>0 && r.top+oy<innerHeight && visible(e)});
      if (doc && doc.body) { const [fx,fy]=contentOrigin(e); collect(doc, ox+fx, oy+fy); }
    }
  };
  collect(document, 0, 0);
  cache.roots = roots.map(({root}) => root);
  cache.offsets = new WeakMap(roots.map(({root, ox, oy}) => [root, [ox, oy]]));
  const offsetOf = e => cache.offsets.get(e.getRootNode()) || [0, 0];
  const name = (e,seen=new Set()) => {
    if (!e || seen.has(e)) return '';
    seen.add(e);
    const scope = e.getRootNode().getElementById ? e.getRootNode() : (e.ownerDocument || document);
    const referenced=(e.getAttribute('aria-labelledby')||'').split(/\s+/).filter(Boolean)
      .map(id=>name(scope.getElementById(id),seen)).filter(Boolean).join(' ');
    return referenced || e.getAttribute('aria-label') ||
      [...(e.labels||[])].map(l=>name(l,seen)).filter(Boolean).join(' ') ||
      (['button','submit','reset'].includes(e.type) ? e.value : '') || e.getAttribute('alt') ||
      (e.tagName==='INPUT' ? '' : [...e.childNodes].map(n=>n.nodeType===3 ? n.textContent :
        n.nodeType===1 && n.getAttribute('aria-hidden')!=='true' ? name(n,seen) : '').join(' ').trim()) ||
      e.getAttribute('title') || e.getAttribute('placeholder') || '';
  };
  const roles=['button','link','checkbox','radio','switch','tab','menuitem','menuitemradio',
    'menuitemcheckbox','option','gridcell','treeitem','slider','combobox','textbox','searchbox','spinbutton'];
  const selector='a[href],button,input,textarea,select,summary,[contenteditable="true"],'+
    '[onclick]:not(html):not(body),'+
    roles.map(role=>'[role="'+role+'"]').join(',');
  const role = e => {
    const explicit=e.getAttribute('role');
    if (roles.includes(explicit)) return explicit;
    if (e.tagName==='BUTTON' || e.tagName==='SUMMARY') return 'button';
    if (e.tagName==='A' && e.hasAttribute('href')) return 'link';
    if (e.tagName==='SELECT') return 'combobox';
    if (e.tagName==='TEXTAREA' || e.isContentEditable) return 'textbox';
    if (e.tagName==='INPUT') {
      if (['checkbox','radio'].includes(e.type)) return e.type;
      if (['button','submit','reset','image'].includes(e.type)) return 'button';
      if (e.type==='search') return 'searchbox';
      if (e.type==='number') return 'spinbutton';
      if (e.type==='password') return 'password';
      if (e.type==='range') return 'slider';
      if (['text','email','url','tel','date','datetime-local','month','week','time'].includes(e.type)) return 'textbox';
    }
    if (e.hasAttribute('onclick')) return 'button';
    return null;
  };
  // The deepest element a press at a top-viewport point lands on, through open shadow roots and same-origin frames.
  const deepHit = (x, y) => {
    let hit=document.elementFromPoint(x,y), ox=0, oy=0;
    while (hit) {
      const inner = hit.shadowRoot && hit.shadowRoot.elementFromPoint(x-ox,y-oy);
      if (inner && inner!==hit) { hit=inner; continue; }
      const doc = (hit.tagName==='IFRAME' || hit.tagName==='FRAME') && frameDocument(hit);
      if (!doc) break;
      const [fx,fy]=contentOrigin(hit); ox+=fx; oy+=fy;
      const next=doc.elementFromPoint(x-ox,y-oy);
      if (!next) break;
      hit=next;
    }
    return hit;
  };
  const up = n => n.parentElement || (n.getRootNode() instanceof ShadowRoot ? n.getRootNode().host : null);
  // Whether a press landing on hit reaches e itself: no other control nearer the press, or a label of e.
  const reaches = (hit, e) => {
    for (let n=hit; n; n=up(n)) {
      if (n===e) return true;
      if (n.tagName==='LABEL' && n.control===e) return true;
      if (n.matches(selector)) return false;
    }
    return false;
  };
  const within = (hit, e) => { for (let n=hit; n; n=up(n)) if (n===e) return true; return false; };
  // The centre of the first of e's boxes (then its labels') that a press there reaches, clipped to the viewport.
  const pointFor = (e, accepts, boxes) => {
    const [ox,oy]=offsetOf(e);
    for (const r of boxes) {
      const left=Math.max(ox+r.left,0), right=Math.min(ox+r.right,innerWidth);
      const top=Math.max(oy+r.top,0), bottom=Math.min(oy+r.bottom,innerHeight);
      if (right-left<1 || bottom-top<1) continue;
      const x=(left+right)/2, y=(top+bottom)/2;
      if (accepts(deepHit(x,y), e)) return {x,y};
    }
    return null;
  };
  // Its own text: where a press reaches it when a control nested in it covers its centre.
  const ownText = function* (e) {
    const doc=e.ownerDocument || document, walker=doc.createTreeWalker(e,NodeFilter.SHOW_TEXT), range=doc.createRange();
    let node;
    while ((node=walker.nextNode())) {
      if (!node.textContent.trim() || node.parentElement?.closest(selector)!==e) continue;
      range.selectNodeContents(node);
      yield* range.getClientRects();
    }
  };
  // A control's boxes, then its own text, then its labels: the first a press reaches.
  cache.pressPoint = e => pointFor(e, reaches, (function* () {
    yield* e.getClientRects();
    yield* ownText(e);
    for (const label of e.labels || []) yield* label.getClientRects();
  })());
  cache.wheelPoint = e => pointFor(e, within, [...e.getClientRects()]);
  cache.deepActive = () => {
    let a=document.activeElement;
    while (a) {
      if (a.shadowRoot && a.shadowRoot.activeElement) { a=a.shadowRoot.activeElement; continue; }
      const doc=(a.tagName==='IFRAME' || a.tagName==='FRAME') && frameDocument(a);
      if (doc && doc.activeElement && doc.activeElement!==doc.body) { a=doc.activeElement; continue; }
      break;
    }
    return a;
  };
  const fields = () => roots.flatMap(({root}) => [...root.querySelectorAll('input,textarea,select')]).filter(safe);
  // Inner scroll containers, and how far each is scrolled: part of the page key, as the window's scroll is.
  const scrollers=[];
  for (const {root} of roots) for (const e of root.querySelectorAll('*')) {
    if (e===document.documentElement || e===document.body || e.scrollHeight<=e.clientHeight+1 || !e.clientHeight) continue;
    if (!['auto','scroll','overlay'].includes(getComputedStyle(e).overflowY) || !visible(e)) continue;
    if (cache.wheelPoint(e)) scrollers.push(e);
  }
  cache.scrollers = scrollers.map(identity);
  // A password field contributes whether it holds something, never what.
  cache.pageKey=()=>[performance.timeOrigin,location.href,scrollX,scrollY,innerWidth,innerHeight,
    cache.scrollers.map(id=>cache.nodes.get(id)?.scrollTop ?? null),
    fields().map(e=>[identity(e),secret(e) ? e.value.length : e.value,e.checked,e.selectedIndex,e.disabled,e.readOnly])];
  cache.guard=e=>{
    if (!e?.isConnected || !visible(e)) return null;
    const scope=e.closest('form,dialog,[role="dialog"],article,li,tr,[role="row"]') || e.parentElement;
    return [identity(e),role(e),name(e),secret(e) ? e.value.length : e.value??null,e.checked??null,
      e.selectedIndex??null,e.readOnly??null,e.matches(':disabled'),e.getAttribute('aria-disabled'),
      e.getAttribute('aria-expanded'),e.getAttribute('aria-checked'),e.getAttribute('aria-selected'),
      e.getAttribute('href'),scope?.innerText?.slice(0,6000)||''];
  };
  const active=cache.deepActive();
  const actions=[];
  let focused=null;
  for (const {root, ox, oy} of roots) for (const e of root.querySelectorAll(selector)) {
    if (!safe(e) || !visible(e) || e.matches(':disabled') || e.closest('[aria-disabled="true"]')) continue;
    const rname=role(e);
    if (!rname || !cache.pressPoint(e)) continue;
    const r=e.getBoundingClientRect();
    const base={node:identity(e),role:rname,label:(name(e)||rname).slice(0,LABEL_CHARS),
      ident:e.id || e.getAttribute('name') || '',rect:{x:ox+r.x,y:oy+r.y,w:r.width,h:r.height}};
    if (e.tagName==='INPUT') base.input_type=e.type;
    if (e.tagName==='A' && e.href) base.href=e.href;
    for (const key of ['checked','selected','expanded']) {
      const value=e.getAttribute('aria-'+key);
      if (value!==null) base[key]=value;
    }
    if (['checkbox','radio'].includes(e.type)) base.checked=String(e.checked);
    if (secret(e)) {
      if (e.readOnly) continue;
      actions.push({...base,kind:'secret',value:'',filled:e.value.length>0});
      if (e===active) focused={id:'enter',kind:'enter',node:base.node,label:'Press Enter in '+base.label};
    } else if (e.tagName==='SELECT') {
      // One action per dropdown, its choices inside it: a long list never crowds out the controls after it.
      const options=[...e.options].filter(o=>!o.selected && !o.disabled && !o.closest('optgroup[disabled]'))
        .map(o=>({value:o.value,label:o.label}));
      if (options.length) actions.push({...base,kind:'select',value:e.value,
        current_value:[...e.selectedOptions].map(o=>o.label).join(', '),options});
    } else {
      const editable=!e.readOnly && e.getAttribute('aria-readonly')!=='true' &&
        (['textbox','searchbox','spinbutton'].includes(rname) || (rname==='slider' && e.tagName==='INPUT') ||
          (rname==='combobox' && ['INPUT','TEXTAREA'].includes(e.tagName)));
      const value='value' in e ? String(e.value) :
        e.isContentEditable || rname==='combobox' ? e.innerText.trim() : '';
      actions.push({...base,kind:editable?'fill':'click',value});
      if (editable) actions.push({...base,kind:'click',value,label:'Open '+base.label});
      if (editable && e===active) focused={id:'enter',kind:'enter',node:base.node,label:'Press Enter in '+base.label};
    }
  }
  // Visible text, in the order it reads down the screen, across every document and shadow root.
  const pieces=[];
  for (const {root, ox, oy} of roots) {
    const top = root.body || root;
    if (!top) continue;
    const walker=(root.ownerDocument || root).createTreeWalker(top,NodeFilter.SHOW_TEXT);
    const range=(root.ownerDocument || root).createRange(); let node;
    while ((node=walker.nextNode())) {
      const value=node.textContent.trim(), parent=node.parentElement;
      if (!value || !parent || parent.closest('script,style,noscript,template') || !visible(parent)) continue;
      range.selectNodeContents(node); const r=range.getBoundingClientRect();
      if (r.width>0 && r.height>0 && r.bottom+oy>0 && r.top+oy<innerHeight && r.right+ox>0 && r.left+ox<innerWidth)
        pieces.push({value, y:Math.max(r.top+oy,0)});
    }
  }
  // Stable: pieces on one line keep their document order.
  pieces.sort((a,b)=>Math.round(a.y)-Math.round(b.y));
  const words=[];
  let length=0;
  for (const {value} of pieces) { if (length>=TEXT_BUDGET) break; words.push(value); length+=value.length; }
  const joined=words.join('\n'), text=joined.slice(0,TEXT_BUDGET), height=document.documentElement.scrollHeight;
  const omitted_actions=Math.max(0,actions.length-MAX_ACTIONS);
  actions.splice(MAX_ACTIONS);
  actions.forEach((a,i)=>a.id='e'+(i+1));
  if (focused) actions.push(focused);
  if (scrollY+innerHeight<height-2) actions.push({id:'scroll_down',kind:'scroll',label:'Scroll down the page',delta:PAGE_SCROLL});
  if (scrollY>0) actions.push({id:'scroll_up',kind:'scroll',label:'Scroll up the page',delta:-PAGE_SCROLL});
  for (const e of scrollers) {
    const node=identity(e), step=Math.round(e.clientHeight*CONTAINER_SCROLL);
    const where=(e.getAttribute('aria-label') || e.textContent.trim().replace(/\s+/g,' ')).slice(0,80) ||
      'the scrollable area';
    if (e.scrollTop+e.clientHeight<e.scrollHeight-1)
      actions.push({id:'scroll_down_'+node,kind:'scroll',node,label:'Scroll down in '+where,delta:step});
    if (e.scrollTop>0)
      actions.push({id:'scroll_up_'+node,kind:'scroll',node,label:'Scroll up in '+where,delta:-step});
  }
  actions.push({id:'wait',kind:'wait',label:'Wait for the page to update'});
  const page_key=cache.pageKey(), guards={};
  for (const a of actions) if (a.node!==undefined && !(a.node in guards)) guards[a.node]=cache.guard(cache.nodes.get(a.node));
  return {url:location.href,title:document.title,text,text_cut:joined.length>TEXT_BUDGET,
    actions,page_key,guards,omitted_actions,frames};
})()
