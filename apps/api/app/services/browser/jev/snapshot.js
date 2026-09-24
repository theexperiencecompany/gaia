// Atomic page snapshot for Jev: visible content and controls with live values,
// code-owned node identity, and the guards that tell a stale decision.
// Ported from browser-use/jev-ultrafast (MIT) jev_ultrafast/snapshot.js, then
// extended to open shadow roots, same-origin iframes, password fields (offered
// as secret targets, never with their value), and each control's id or name.
(() => {
  if (!document.body) return null;
  const cache = window.__jevFast ||= {ids:new WeakMap(), nodes:new Map(), next:1};
  const identity = e => {
    if (!cache.ids.has(e)) cache.ids.set(e,cache.next++);
    const id=cache.ids.get(e); cache.nodes.set(id,e); return id;
  };
  for (const [id,e] of cache.nodes) if (!e.isConnected) cache.nodes.delete(id);
  const secret = e => e.tagName==='INPUT' && e.type==='password';
  const safe = e => !['file','hidden'].includes(e.type);
  const visible = e => !e.closest('[aria-hidden="true"],[inert]') &&
    e.checkVisibility({checkOpacity:true,checkVisibilityCSS:true});
  // Every document and open shadow root the snapshot reads, with the offset
  // from its viewport to the top one (same-origin iframes only).
  const roots = [];
  const frames = [];
  const collect = (root, ox, oy) => {
    roots.push({root, ox, oy});
    for (const e of root.querySelectorAll('*')) {
      if (e.shadowRoot) collect(e.shadowRoot, ox, oy);
      if (e.tagName !== 'IFRAME' && e.tagName !== 'FRAME') continue;
      const r = e.getBoundingClientRect();
      let doc = null;
      try { doc = e.contentDocument; } catch (_) { doc = null; }
      frames.push({src: e.src || '', same_origin: !!doc,
        visible: r.width>0 && r.height>0 && r.bottom+oy>0 && r.top+oy<innerHeight && visible(e)});
      if (doc && doc.body) collect(doc, ox + r.x + e.clientLeft, oy + r.y + e.clientTop);
    }
  };
  collect(document, 0, 0);
  cache.offsets = new WeakMap(roots.map(({root, ox, oy}) => [root, [ox, oy]]));
  const offsetOf = e => cache.offsets.get(e.getRootNode()) || [0, 0];
  cache.offsetOf = offsetOf;
  const name = (e,seen=new Set()) => {
    if (!e || seen.has(e)) return '';
    seen.add(e);
    const doc = e.ownerDocument || document;
    const referenced=(e.getAttribute('aria-labelledby')||'').split(/\s+/)
      .map(id=>name(doc.getElementById(id),seen)).filter(Boolean).join(' ');
    return referenced || e.getAttribute('aria-label') ||
      [...(e.labels||[])].map(l=>name(l,seen)).filter(Boolean).join(' ') ||
      (['button','submit','reset'].includes(e.type) ? e.value : '') || e.getAttribute('alt') ||
      (e.tagName==='INPUT' ? '' : [...e.childNodes].map(n=>n.nodeType===3 ? n.textContent :
        n.nodeType===1 && n.getAttribute('aria-hidden')!=='true' ? name(n,seen) : '').join(' ').trim()) ||
      e.getAttribute('title') || e.getAttribute('placeholder') || '';
  };
  const roles=['button','link','checkbox','radio','switch','tab','menuitem','menuitemradio',
    'option','gridcell','combobox','textbox','searchbox','spinbutton'];
  const selector='a[href],button,input,textarea,select,summary,[contenteditable="true"],'+
    roles.map(role=>'[role="'+role+'"]').join(',');
  const role = e => {
    const explicit=e.getAttribute('role');
    if (roles.includes(explicit)) return explicit;
    if (e.tagName==='BUTTON' || e.tagName==='SUMMARY') return 'button';
    if (e.tagName==='A') return 'link';
    if (e.tagName==='SELECT') return 'combobox';
    if (e.tagName==='TEXTAREA' || e.isContentEditable) return 'textbox';
    if (e.tagName==='INPUT') {
      if (['checkbox','radio'].includes(e.type)) return e.type;
      if (['button','submit','reset','image'].includes(e.type)) return 'button';
      if (e.type==='search') return 'searchbox';
      if (e.type==='number') return 'spinbutton';
      if (e.type==='password') return 'password';
      if (['text','email','url','tel','date','datetime-local','month','week','time'].includes(e.type)) return 'textbox';
    }
    return null;
  };
  const fields = () => roots.flatMap(({root}) => [...root.querySelectorAll('input,textarea,select')]).filter(safe);
  // A password field contributes whether it holds something, never what.
  cache.pageKey=()=>[performance.timeOrigin,location.href,scrollX,scrollY,innerWidth,innerHeight,
    fields().map(e=>[identity(e),secret(e) ? e.value.length : e.value,e.checked,e.selectedIndex,e.disabled,e.readOnly])];
  cache.guard=e=>{
    if (!e?.isConnected || !visible(e)) return null;
    const scope=e.closest('form,dialog,[role="dialog"],article,li,tr,[role="row"]') || e.parentElement;
    return [identity(e),role(e),name(e),secret(e) ? e.value.length : e.value??null,e.checked??null,
      e.selectedIndex??null,e.readOnly??null,e.matches(':disabled'),e.getAttribute('aria-disabled'),
      e.getAttribute('aria-expanded'),e.getAttribute('aria-checked'),e.getAttribute('aria-selected'),
      e.getAttribute('href'),scope?.innerText?.slice(0,6000)||''];
  };
  const actions=[];
  for (const {root, ox, oy} of roots) for (const e of root.querySelectorAll(selector)) {
    if (!safe(e) || !visible(e) || e.matches(':disabled') || e.closest('[aria-disabled="true"]')) continue;
    const r=e.getBoundingClientRect(), x=ox+r.x+r.width/2, y=oy+r.y+r.height/2, rname=role(e);
    if (!rname || r.width<=0 || r.height<=0 || x<0 || y<0 || x>=innerWidth || y>=innerHeight) continue;
    if (rname==='gridcell' && e.querySelector('button,[role="button"]')) continue;
    const base={node:identity(e),role:rname,label:name(e)||rname,
      ident:e.id || e.getAttribute('name') || '',rect:{x:ox+r.x,y:oy+r.y,w:r.width,h:r.height}};
    for (const key of ['checked','selected','expanded']) {
      const value=e.getAttribute('aria-'+key);
      if (value!==null) base[key]=value;
    }
    if (['checkbox','radio'].includes(e.type)) base.checked=String(e.checked);
    if (secret(e)) {
      if (!e.readOnly) actions.push({...base,kind:'secret',value:'',filled:e.value.length>0});
    } else if (e.tagName==='SELECT') {
      for (const o of e.options) if (!o.selected && !o.disabled && !o.closest('optgroup[disabled]'))
        actions.push({...base,kind:'select',value:o.value,
          current_value:[...e.selectedOptions].map(o=>o.label).join(', '),label:base.label+' → '+o.label});
    } else {
      const editable=!e.readOnly && e.getAttribute('aria-readonly')!=='true' &&
        (['textbox','searchbox','spinbutton'].includes(rname) ||
          (rname==='combobox' && ['INPUT','TEXTAREA'].includes(e.tagName)));
      const value='value' in e ? String(e.value) :
        e.isContentEditable || rname==='combobox' ? e.innerText.trim() : '';
      actions.push({...base,kind:editable?'fill':'click',value});
      if (editable) actions.push({...base,kind:'click',value,label:'Open '+base.label});
    }
  }
  const words=[];
  let length=0;
  for (const {root, ox, oy} of roots) {
    const top = root.body || root;
    if (!top || length>=6000) continue;
    const walker=(root.ownerDocument || root).createTreeWalker(top,NodeFilter.SHOW_TEXT);
    const range=(root.ownerDocument || root).createRange(); let node;
    while ((node=walker.nextNode()) && length<6000) {
      const value=node.textContent.trim(), parent=node.parentElement;
      if (!value || !parent || parent.closest('script,style,noscript,template') || !visible(parent)) continue;
      range.selectNodeContents(node); const r=range.getBoundingClientRect();
      if (r.width>0 && r.height>0 && r.bottom+oy>0 && r.top+oy<innerHeight && r.right+ox>0 && r.left+ox<innerWidth) {
        words.push(value); length+=value.length;
      }
    }
  }
  const text=words.join('\n').slice(0,6000), height=document.documentElement.scrollHeight;
  const page_key=cache.pageKey(), guards={};
  for (const a of actions) if (!(a.node in guards)) guards[a.node]=cache.guard(cache.nodes.get(a.node));
  // Compare meaning and identity. Geometry is always resolved and hit-tested just before input.
  const semantics=actions.map(({rect,...action})=>action);
  const marker=[performance.timeOrigin,location.href,scrollX,scrollY,innerWidth,innerHeight,
    document.title,text,semantics,page_key[6]];
  const omitted_actions=Math.max(0,actions.length-250);
  actions.splice(250);
  actions.forEach((a,i)=>a.id='e'+(i+1));
  if (scrollY+innerHeight<height-2) actions.push({id:'scroll_down',kind:'scroll',label:'Scroll down',delta:560});
  if (scrollY>0) actions.push({id:'scroll_up',kind:'scroll',label:'Scroll up',delta:-560});
  actions.push({id:'wait',kind:'wait',label:'Wait for the page to update'});
  return {url:location.href,title:document.title,w:innerWidth,h:innerHeight,text,
    scroll:{y:scrollY,height},actions,marker,page_key,guards,omitted_actions,frames};
})()
