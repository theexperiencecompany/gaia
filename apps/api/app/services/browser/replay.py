"""Short replay codes + the recap slideshow page.

When a browser task finishes (success or failure), its step screenshots are already
uploaded. A short code maps to the URLs they were served at, so the delivered
recap link (browser.heygaia.io/replays/{code}) opens a self-contained
slideshow that plays every step back — a scrubber, a filmstrip of thumbnails, and
arrow-key navigation. The code is the secret, and the images are whatever URLs
the run produced, whether an object store or this API served them.
"""

from __future__ import annotations

import json
from time import perf_counter

from app.constants.browser import (
    BROWSER_LIVE_CODE_ENTROPY_BYTES,
    BROWSER_REPLAY_CODE_KEY_PREFIX,
    BROWSER_REPLAY_CODE_TTL_SECONDS,
)
from app.constants.log_tags import LogTag
from app.schemas.browser import ReplayRecord
from app.services.browser.capability_code import CapabilityCodes
from app.services.browser.exceptions import BrowserUnavailableError
from app.services.browser.links import browser_link_base
from shared.py.wide_events import log

_CODES = CapabilityCodes(
    BROWSER_REPLAY_CODE_KEY_PREFIX, ReplayRecord, entropy_bytes=BROWSER_LIVE_CODE_ENTROPY_BYTES
)


async def resolve_replay_code(code: str) -> ReplayRecord | None:
    """Return the finished session a replay code opens, or None if unknown or expired."""
    return await _CODES.resolve(code)


async def create_replay_link(session_id: str, shots: list[str]) -> str | None:
    """Return a recap slideshow link, or None when there is nothing to replay or the code was not kept.

    Takes the URLs the run really produced rather than a step count: an upload is
    best-effort, so a count would promise frames the slideshow cannot show.
    """
    if not shots:
        return None
    started = perf_counter()
    try:
        code = await _CODES.mint(
            ReplayRecord(session_id=session_id, shots=shots), ttl=BROWSER_REPLAY_CODE_TTL_SECONDS
        )
    except BrowserUnavailableError as exc:
        # The run's result still goes out, only without a recap link that would open nothing.
        log.error(f"{LogTag.BROWSER} Browser replay code not stored", error_type=type(exc).__name__)
        return None
    mint_ms = round((perf_counter() - started) * 1000)
    log.set_ns("browser", session_id=session_id, replay_shots=len(shots), replay_mint_ms=mint_ms)
    log.info(f"{LogTag.BROWSER} Browser replay code minted", shot_count=len(shots), mint_ms=mint_ms)
    return f"{browser_link_base()}/replays/{code}"


def render_replay_page(record: ReplayRecord) -> str:
    """Return the self-contained slideshow HTML for one finished session."""
    # Inlined into a <script>, so close any tag sequence the encoder would leave intact.
    urls = json.dumps(record.shots).replace("</", "<\\/")
    return _REPLAY_TEMPLATE.replace("__URLS__", urls)


_REPLAY_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1"/>
<title>GAIA: Browser Recap</title>
<style>
  :root { --bg:#0b0b0d; --panel:#141417; --panel2:#1c1c21; --line:#26262c; --fg:#e7e7ea; --muted:#8a8a93; --accent:#00bbff; }
  * { box-sizing:border-box; }
  html,body { margin:0; height:100%; background:var(--bg); color:var(--fg);
    font:14px/1.4 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; overflow:hidden; }
  .wrap { display:flex; flex-direction:column; height:100vh; }
  header { display:flex; align-items:center; gap:10px; padding:10px 16px; border-bottom:1px solid var(--line); }
  header .brand { font-weight:700; letter-spacing:.2px; }
  header .tag { color:var(--muted); font-size:12px; }
  .stage { flex:1; display:flex; min-height:0; }
  .main { flex:1; display:flex; align-items:center; justify-content:center; padding:16px; min-width:0; background:
    radial-gradient(1200px 600px at 50% -10%, rgba(0,187,255,.07), transparent 60%); }
  .main img { max-width:100%; max-height:100%; border-radius:10px; border:1px solid var(--line);
    box-shadow:0 12px 40px rgba(0,0,0,.5); background:#fff; }
  .film { width:184px; flex:none; border-left:1px solid var(--line); overflow-y:auto; padding:8px; background:var(--panel); }
  .film .thumb { position:relative; width:100%; margin-bottom:8px; border:2px solid transparent; border-radius:8px;
    overflow:hidden; cursor:pointer; background:var(--panel2); }
  .film .thumb.active { border-color:var(--accent); }
  .film .thumb img { display:block; width:100%; }
  .film .thumb .n { position:absolute; top:4px; left:4px; font-size:11px; color:#fff; background:rgba(0,0,0,.55);
    padding:1px 6px; border-radius:6px; }
  footer { display:flex; align-items:center; gap:14px; padding:12px 16px; border-top:1px solid var(--line); background:var(--panel); }
  .btn { appearance:none; border:1px solid var(--line); background:var(--panel2); color:var(--fg); width:40px; height:40px;
    border-radius:10px; cursor:pointer; font-size:16px; display:flex; align-items:center; justify-content:center; }
  .btn:hover { border-color:var(--accent); }
  .count { color:var(--muted); font-variant-numeric:tabular-nums; white-space:nowrap; min-width:88px; }
  input[type=range] { flex:1; accent-color:var(--accent); height:6px; }
  @media (max-width:640px){ .film{ display:none; } }
</style>
</head>
<body>
<div class="wrap">
  <header><span class="brand">GAIA</span><span class="tag">Browser recap</span></header>
  <div class="stage">
    <div class="main"><img id="main" alt="step"/></div>
    <div class="film" id="film"></div>
  </div>
  <footer>
    <button class="btn" id="prev" title="Previous (←)">‹</button>
    <button class="btn" id="play" title="Play/Pause (space)">▶</button>
    <button class="btn" id="next" title="Next (→)">›</button>
    <span class="count" id="count"></span>
    <input type="range" id="scrub" min="1" step="1"/>
  </footer>
</div>
<script>
  var urls=__URLS__, N=urls.length;
  var idx=0, playing=false, timer=null;
  var main=document.getElementById("main"), film=document.getElementById("film"),
      count=document.getElementById("count"), scrub=document.getElementById("scrub"),
      playBtn=document.getElementById("play");
  scrub.max=N; scrub.value=1;
  // build filmstrip
  var thumbs=[];
  for (var j=0;j<N;j++){
    var t=document.createElement("div"); t.className="thumb"; t.dataset.i=j;
    var im=document.createElement("img"); im.loading="lazy"; im.src=urls[j];
    var n=document.createElement("span"); n.className="n"; n.textContent=j+1;
    t.appendChild(im); t.appendChild(n); t.onclick=(function(k){return function(){go(k);};})(j);
    film.appendChild(t); thumbs.push(t);
  }
  function render(){
    main.src=urls[idx];
    count.textContent="Step "+(idx+1)+" / "+N;
    scrub.value=idx+1;
    for (var k=0;k<thumbs.length;k++) thumbs[k].classList.toggle("active", k===idx);
    var a=thumbs[idx]; if (a && a.scrollIntoView) a.scrollIntoView({block:"nearest"});
  }
  function go(i){ idx=Math.max(0,Math.min(N-1,i)); render(); }
  function next(){ if (idx>=N-1){ pause(); return; } go(idx+1); }
  function play(){ playing=true; playBtn.textContent="❚❚"; timer=setInterval(next,1400); }
  function pause(){ playing=false; playBtn.textContent="▶"; if (timer){ clearInterval(timer); timer=null; } }
  document.getElementById("prev").onclick=function(){ pause(); go(idx-1); };
  document.getElementById("next").onclick=function(){ pause(); go(idx+1); };
  playBtn.onclick=function(){ playing?pause():play(); };
  scrub.oninput=function(){ pause(); go(parseInt(scrub.value,10)-1); };
  document.addEventListener("keydown",function(e){
    if (e.key==="ArrowRight"){ pause(); go(idx+1); e.preventDefault(); }
    else if (e.key==="ArrowLeft"){ pause(); go(idx-1); e.preventDefault(); }
    else if (e.key===" "){ playing?pause():play(); e.preventDefault(); }
    else if (e.key==="Home"){ pause(); go(0); }
    else if (e.key==="End"){ pause(); go(N-1); }
  });
  render();
</script>
</body>
</html>"""
