/**
 * The fixed part of every card widget: GAIA's theme and the script that runs
 * the card's buttons. A card's own markup goes between {@link WIDGET_STYLE} and
 * {@link WIDGET_SCRIPT}.
 *
 * The bubble keeps its own colour, so a card reads as a message in the chat's
 * theme (light or dark) rather than as a picture pasted into it; GAIA is in
 * the brand cyan for the one primary action, status badges as a tint plus
 * full-colour text, and rounded inner panels (DESIGN.md). Painting the
 * background made a widget read as an image. Widgets may use system fonts only.
 *
 * The script is the only code that runs in the sandbox. A button asks the bot
 * with `TelegramWidget.request(<wire id>)`; the bot answers with
 * {@link WidgetAnswer} and writes the settled status into the chat state
 * ({@link WidgetState}), which also redraws the widget after a restart. Text is
 * set with `textContent`, never `innerHTML`, so nothing the bot sends back can
 * inject markup.
 *
 * Runtime and limits: https://core.telegram.org/bots/widgets
 *
 * @module
 */
import type { CardStatusTone } from "@gaia/shared/bots";

/** A settled card's badge, compact on the wire: `{ l: label, t: tone }`. */
export interface WidgetStatus {
  l: string;
  t: CardStatusTone;
}

/** The widget's chat state: set once a tap settles the card. */
export interface WidgetState {
  s: WidgetStatus;
}

/** The bot's answer to a tap: the line to show, and the badge when it settled. */
export interface WidgetAnswer {
  m: string;
  s?: WidgetStatus;
}

export const WIDGET_STYLE = `<style>
[hidden]{display:none!important}
body{margin:0;padding:12px 12px calc(10px + env(safe-area-inset-bottom));font:15px/1.4 system-ui,sans-serif}
a{color:#00bbff;text-decoration:none}
.chip{display:inline-block;font-size:12px;font-weight:600;padding:3px 9px;border-radius:999px;margin-bottom:8px}
.info{background:#00bbff1f;color:#00bbff}.warning{background:#fbbf241f;color:#f59e0b}
.success{background:#34d3991f;color:#10b981}.danger{background:#f871711f;color:#ef4444}
h1{font-size:17px;font-weight:650;margin:0 0 6px;line-height:1.3}
p{margin:0 0 10px;font-size:14px}
.box{background:var(--tg-theme-secondary-bg-color);border-radius:14px;padding:8px 12px;margin-bottom:10px}
.box:last-child{margin-bottom:0}
.row{display:flex;gap:10px;padding:3px 0;font-size:14px}
.k,.cite,.m,.more{color:var(--tg-theme-hint-color)}
.k{flex:0 0 72px}
.cite{font-size:12px;margin-bottom:4px}
.q{font-size:14px;overflow:hidden}
.fold .q{max-height:4.2em}
.it{padding:7px 0;border-top:1px solid var(--tg-theme-section-separator-color);font-size:14px}
.it:first-child{border-top:0}
.it b{font-weight:600}
.m{font-size:12px}
.sn{color:var(--tg-theme-subtitle-text-color);max-height:2.8em;overflow:hidden}
.more{font-size:12px;padding-top:6px}
.btns{display:flex;gap:8px;margin-top:8px}
button{flex:1;border:0;border-radius:12px;padding:10px 0;font:600 15px system-ui,sans-serif;background:var(--tg-theme-secondary-bg-color);color:var(--tg-theme-text-color)}
button.p{background:#00bbff;color:#000}
button.d{color:var(--tg-theme-destructive-text-color)}
button.r{background:none;color:var(--tg-theme-hint-color);font-size:14px;padding:4px 0}
button.t{flex:none;background:none;color:#00bbff;font-size:13px;padding:4px 0 0}
button[disabled]{color:var(--tg-theme-hint-color)}
.note{font-size:13px;color:#f59e0b;margin-top:8px}
.done .acts{display:none}
</style>`;

export const WIDGET_SCRIPT = `<script>
var W=window.TelegramWidget,root=document.getElementById('c'),note=document.getElementById('n'),busy=false;
function say(t){note.textContent=t;note.hidden=!t}
function settle(s){var c=document.getElementById('st');c.textContent=s.l;c.className='chip '+s.t;c.hidden=false;root.classList.add('done')}
function load(){try{var s=JSON.parse(W.chatData);if(s&&s.s)settle(s.s)}catch(e){}}
function lock(on){busy=on;var b=document.querySelectorAll('.acts button');for(var i=0;i<b.length;i++)b[i].disabled=on}
function q(el){if(busy)return;lock(true);say('');
W.request(el.getAttribute('data-q')).then(function(a){var r=null;try{r=JSON.parse(a.result)}catch(e){}
if(r&&r.s)settle(r.s);else if(r&&r.m)say(r.m)},function(e){say(e.code==='RATE_LIMITED'?'Too many taps. Try again in a moment.':'Couldn\\'t reach GAIA. Try again.')}).then(function(){lock(false)})}
function u(el){W.openLink(el.getAttribute('data-u'))}
function fold(el){var b=el.parentNode;b.classList.toggle('fold');el.textContent=b.classList.contains('fold')?'Show more':'Show less'}
if(W.isForward)root.classList.add('done');
W.onEvent('chatDataChanged',load);load();W.ready();
</script>`;
