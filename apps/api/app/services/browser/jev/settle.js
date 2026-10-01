// After an input: resolve once a whole animation frame passed with no DOM change
// anywhere Jev reads (every document and open shadow root of the snapshot), or at
// the cap. True when the page went quiet, false when the cap ended the wait.
function gaiaJevSettle(capMs) {
  return new Promise(resolve => {
    const roots=window.__jevFast?.roots?.filter(r=>r.isConnected!==false) || [document];
    let changed=false, frames=0, done=false;
    const observer=new MutationObserver(()=>{ changed=true; });
    for (const root of roots)
      observer.observe(root,{subtree:true,childList:true,attributes:true,characterData:true});
    const finish=quiet=>{ if (done) return; done=true; observer.disconnect(); resolve(quiet); };
    setTimeout(()=>finish(false),capMs);
    const frame=()=>{
      if (done) return;
      // The first frame takes in what the input already changed; quiet is a frame after it with none.
      if (++frames>=2 && !changed) return finish(true);
      changed=false;
      requestAnimationFrame(frame);
    };
    requestAnimationFrame(frame);
  });
}
// An explicit WAIT: resolve at the first DOM change anywhere Jev reads, or at the cap.
function gaiaJevWait(capMs) {
  return new Promise(resolve => {
    const roots=window.__jevFast?.roots?.filter(r=>r.isConnected!==false) || [document];
    let done=false;
    const finish=changed=>{ if (done) return; done=true; observer.disconnect(); resolve(changed); };
    const observer=new MutationObserver(()=>finish(true));
    for (const root of roots)
      observer.observe(root,{subtree:true,childList:true,attributes:true,characterData:true});
    setTimeout(()=>finish(false),capMs);
  });
}
