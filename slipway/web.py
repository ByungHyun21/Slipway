"""The Slipway web surface: the launch gallery.

Server-rendered HTML with progressive vanilla-JS (filter, search, lightbox).
No external assets: system font stack + prefers-color-scheme so the tool works
offline on a LAN. Only approved artifacts are previewable; unapproved work
renders as sealed plates.
"""

from __future__ import annotations

import html
import struct
import wave
from pathlib import Path
from urllib.parse import quote

from . import model, previews

CSS = r"""
:root{
  color-scheme:light dark;
  --bg:#f5f6f8; --card:#ffffff; --plate:#eef0f3; --border:#dde2e8;
  --fg:#1c242c; --muted:#5d6a76; --faint:#8a97a3;
  --accent:#0f766e; --accent-weak:rgba(15,118,110,.08);
  --ok:#188038; --gate:#1a56db; --warn:#b45309; --bad:#dc2626; --gray:#6b7280;
  --paper:#fffdf6; --paper-ink:#26303a;
  --shadow:0 1px 2px rgba(16,24,40,.06),0 1px 3px rgba(16,24,40,.1);
  --font-ui:system-ui,-apple-system,'Segoe UI',Roboto,'Helvetica Neue',sans-serif;
  --font-mono:ui-monospace,'SF Mono',SFMono-Regular,Menlo,Consolas,'Liberation Mono',monospace;
}
@media (prefers-color-scheme:dark){
  :root{
    --bg:#0f1216; --card:#171b21; --plate:#10141a; --border:#2a313a;
    --fg:#e6eaee; --muted:#9aa7b2; --faint:#697885;
    --accent:#2dd4bf; --accent-weak:rgba(45,212,191,.10);
    --ok:#3fb950; --gate:#58a6ff; --warn:#d29922; --bad:#f85149; --gray:#8b949e;
    --shadow:0 1px 3px rgba(0,0,0,.5);
  }
  .btn.flare{color:#06211c}
}
*{box-sizing:border-box;margin:0}
html{scroll-behavior:smooth}
body{background:var(--bg);color:var(--fg);font:14px/1.6 var(--font-ui)}
.wrap{max-width:76rem;margin:0 auto;padding:0 clamp(1rem,4vw,2rem) 3.5rem}

/* ---- masthead ---------------------------------------------------------- */
.masthead{display:flex;justify-content:space-between;align-items:flex-end;gap:1.5rem;
  flex-wrap:wrap;padding:2.4rem 0 1.5rem;border-bottom:1px solid var(--border)}
.ship-class{display:block;font:600 11px/1 var(--font-mono);letter-spacing:.14em;
  text-transform:uppercase;color:var(--accent)}
.masthead h1{font:600 2rem/1.2 var(--font-ui);margin:.35rem 0 .3rem}
.coordinates{color:var(--muted);font:12px/1.5 var(--font-mono)}
.coordinates b{color:var(--fg);font-weight:600}
.actions{display:flex;flex-wrap:wrap;gap:.5rem;align-items:center}

/* ---- buttons ------------------------------------------------------------ */
.btn{font:600 13px var(--font-ui);color:var(--fg);text-decoration:none;text-align:center;
  cursor:pointer;padding:.55rem .95rem;border:1px solid var(--border);border-radius:8px;
  background:var(--card);box-shadow:var(--shadow);
  transition:border-color .15s,color .15s,background .15s,transform .15s;display:inline-block}
.btn:hover{border-color:var(--accent);color:var(--accent)}
.btn.flare{background:var(--accent);border-color:var(--accent);color:#fff}
.btn.flare:hover{color:#fff;filter:brightness(1.08)}
.btn:disabled,.btn.disabled{opacity:.45;cursor:not-allowed;box-shadow:none}
.btn:disabled:hover{border-color:var(--border);color:var(--fg)}
.btn.mini{font-size:11.5px;padding:.4rem .7rem;border-radius:6px}
sup.planned{font:400 10px var(--font-mono);color:var(--faint);margin-left:.4em}

/* ---- funnel + toolbar ---------------------------------------------------- */
.funnel{display:flex;flex-wrap:wrap;gap:.25rem;align-items:stretch;margin:1.5rem 0 .4rem}
.stage{appearance:none;background:none;border:1px solid transparent;border-radius:8px;
  color:var(--muted);font-family:var(--font-ui);text-align:left;cursor:pointer;
  padding:.45rem .8rem .4rem;display:flex;flex-direction:column;gap:.05rem;
  transition:border-color .15s,color .15s,background .15s}
.stage:hover{background:var(--card);border-color:var(--border)}
.stage .n{font:600 1.2rem/1.2 var(--font-mono)}
.stage .lbl{font:600 9.5px var(--font-mono);letter-spacing:.08em;text-transform:uppercase}
.stage.active{color:var(--accent);border-color:var(--accent);background:var(--accent-weak)}
.arrow{align-self:center;color:var(--faint);font-size:12px}
.toolbar{display:flex;gap:1rem;align-items:center;border-bottom:1px solid var(--border);
  padding:.45rem 0 .8rem}
.toolbar input{appearance:none;background:none;border:none;outline:none;width:100%;
  color:var(--fg);font:13px var(--font-mono)}
.toolbar input::placeholder{color:var(--faint)}
.toolbar .count{white-space:nowrap;font:11px var(--font-mono);color:var(--muted)}

/* ---- gallery grid --------------------------------------------------------- */
.gallery{display:grid;grid-template-columns:repeat(auto-fill,minmax(14.5rem,1fr));
  gap:1rem;margin-top:1.3rem}
@media (min-width:60rem){.tile.wide{grid-column:span 2}.tile.wide .plate{aspect-ratio:5/2}}
.tile{position:relative}
.tile.hide{display:none}
.tile-btn{appearance:none;width:100%;padding:0;text-align:left;color:inherit;
  font:inherit;cursor:pointer;display:block;background:var(--card);
  border:1px solid var(--border);border-radius:10px;overflow:hidden;
  box-shadow:var(--shadow);transition:border-color .15s,transform .15s,box-shadow .15s}
.tile-btn:hover{border-color:var(--accent);transform:translateY(-2px);
  box-shadow:0 4px 14px rgba(16,24,40,.12)}
.plate{position:relative;aspect-ratio:4/3;overflow:hidden;background:var(--plate);
  display:grid;place-items:center;border-bottom:1px solid var(--border)}
.tile .stamp{position:absolute;top:.6rem;right:.6rem;z-index:2;
  font:600 9.5px var(--font-mono);letter-spacing:.08em;text-transform:uppercase;
  padding:.28rem .55rem;border-radius:999px;border:1px solid currentColor;
  background:color-mix(in srgb,currentColor 9%,var(--card));color:var(--gray)}
.tile .stamp.brief,.tile .stamp.generated{border-style:dashed}
.tile .stamp.generated{color:var(--warn)}
.tile .stamp.gated{color:var(--gate)}
.tile .stamp.approved,.tile .stamp.exported{color:var(--ok)}
.tile-btn:hover .peek{opacity:1}
.peek{position:absolute;left:.7rem;bottom:.55rem;z-index:2;font:600 10px var(--font-mono);
  color:var(--accent);opacity:0;transition:opacity .15s}
.plate img,.plate video{max-width:100%;max-height:100%;object-fit:contain;display:block}
.plate model-viewer{width:100%;height:100%;--poster-color:transparent;display:block}
.plate img.pixel{image-rendering:pixelated;height:68%;width:auto;max-width:64%}
.wave{width:78%;height:34%;color:var(--accent)}
.prose{position:absolute;inset:0;background:var(--paper);color:var(--paper-ink);
  padding:1rem 1.15rem;font:12px/1.65 var(--font-mono);overflow:hidden;
  border:1px solid rgba(120,110,80,.18)}
.prose::after{content:"";position:absolute;inset:auto 0 0 0;height:2.6rem;
  background:linear-gradient(transparent,var(--paper))}
.prose p{margin:0;white-space:pre-wrap}
.sealed{position:absolute;inset:0;display:grid;place-items:center;text-align:center;
  background:repeating-linear-gradient(135deg,transparent 0 14px,
    color-mix(in srgb,var(--faint) 7%,transparent) 14px 15px);
  color:var(--faint)}
.sealed b{display:block;font:600 10.5px var(--font-mono);letter-spacing:.16em}
.sealed span{display:block;margin-top:.4rem;font-size:11px}
.glyph{width:30%;color:var(--faint)}
.meta{display:flex;align-items:baseline;gap:.6rem;padding:.7rem .85rem}
.meta h3{font:600 14.5px/1.3 var(--font-ui);white-space:nowrap;overflow:hidden;
  text-overflow:ellipsis}
.type{font:500 9.5px var(--font-mono);color:var(--muted);border:1px solid var(--border);
  border-radius:4px;padding:.16rem .4rem;white-space:nowrap;text-transform:uppercase}
.revs{margin-left:auto;font:10px var(--font-mono);color:var(--faint);white-space:nowrap}

/* ---- dossier sheet (lightbox) --------------------------------------------- */
#scrim{position:fixed;inset:0;z-index:40;background:rgba(10,14,18,.5);
  opacity:0;pointer-events:none;transition:opacity .2s}
body.modal #scrim{opacity:1;pointer-events:auto}
.sheet{position:fixed;inset:6vh 8vw;z-index:50;display:none;flex-direction:column;
  background:var(--card);border:1px solid var(--border);border-radius:12px;
  box-shadow:0 24px 80px rgba(0,0,0,.35)}
.sheet.open{display:flex;animation:pop .22s ease-out}
@keyframes pop{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:none}}
.sheet-head{display:flex;align-items:center;gap:.8rem;padding:1rem 1.4rem;
  border-bottom:1px solid var(--border)}
.sheet-head h2{font:600 18px var(--font-ui)}
.sheet-head .stamp{font:600 9.5px var(--font-mono);letter-spacing:.08em;
  text-transform:uppercase;padding:.25rem .55rem;border-radius:999px;
  border:1px solid currentColor;color:var(--gray)}
.sheet-head .stamp.approved,.sheet-head .stamp.exported{color:var(--ok)}
.sheet-head .stamp.gated{color:var(--gate)}
.sheet-close{margin-left:auto;appearance:none;background:none;
  border:1px solid var(--border);border-radius:8px;color:var(--muted);
  font:500 14px var(--font-ui);width:2.2rem;height:2.2rem;cursor:pointer;
  transition:color .15s,border-color .15s}
.sheet-close:hover{color:var(--bad);border-color:var(--bad)}
.sheet-body{overflow:auto;padding:1.2rem 1.4rem 1.8rem}
.sheet-hero{border:1px solid var(--border);border-radius:8px;background:var(--plate);
  display:grid;place-items:center;padding:1rem;max-height:46vh;overflow:hidden;
  margin-bottom:1.1rem}
.sheet-hero img{max-width:100%;max-height:42vh;object-fit:contain}
.sheet-hero img.pixel{image-rendering:pixelated;max-height:38vh}
.sheet-hero video{max-width:100%;max-height:42vh}
.sheet-hero model-viewer{width:100%;height:42vh;display:block;--poster-color:transparent}
.sheet-hero .prose{position:static;inset:auto;max-height:38vh;overflow:auto;
  width:100%;background:var(--paper)}
.sheet-hero .prose::after{display:none}
.sheet-hero audio{width:80%}
.sheet-hero .wave{width:80%;height:5.5rem;margin-bottom:.7rem}
.sheet-hero .sealed{position:static;background:none;padding:1.5rem}

/* ---- revisions inside sheet ------------------------------------------------ */
.rev{display:grid;grid-template-columns:4.6rem minmax(0,1fr);gap:.3rem 1.2rem;
  padding:.9rem 0 .8rem;border-top:1px solid var(--border)}
.rev-no{color:var(--accent);font:600 11px var(--font-mono);letter-spacing:.06em}
.rev-meta{color:var(--faint);font:11px var(--font-mono)}
.rev-meta .backend{color:var(--muted)}
.gates{display:flex;gap:.4rem;flex-wrap:wrap;margin:.3rem 0}
.gate{font:600 10px var(--font-mono);border:1px solid;border-radius:5px;padding:.15rem .5rem}
.gate.pass{color:var(--ok);border-color:color-mix(in srgb,var(--ok) 45%,transparent)}
.gate.fail{color:var(--bad);border-color:color-mix(in srgb,var(--bad) 45%,transparent)}
.files{list-style:none;padding:0;margin:.1rem 0}
.files li{display:flex;align-items:center;gap:.7rem;padding:.14rem 0}
.dl{color:var(--fg);text-decoration:underline;text-underline-offset:3px;
  text-decoration-color:var(--border);word-break:break-all;font-size:13px}
.dl:hover{color:var(--accent);text-decoration-color:var(--accent)}
.size{font:10px var(--font-mono);color:var(--faint)}
.copy{margin-left:auto;opacity:0;border:1px solid var(--border);border-radius:5px;
  background:none;color:var(--muted);font:400 10px var(--font-mono);
  padding:.12rem .45rem;cursor:pointer;transition:opacity .15s,color .15s}
.files li:hover .copy{opacity:1}
.copy:hover{color:var(--accent);border-color:var(--accent)}
.copy.ok{color:var(--ok);border-color:var(--ok);opacity:1}
.reasons{margin:.3rem 0 0;padding-left:1.1rem;color:var(--bad);font-size:11.5px}
.awaiting{color:var(--gate);font:600 10.5px var(--font-mono);letter-spacing:.05em}
.refs{color:var(--faint);font:11px var(--font-mono);margin:0 0 .9rem}
.refs code{color:var(--muted)}

details.stub{margin-top:1rem}
details.stub summary{cursor:pointer;list-style:none;font:600 10.5px var(--font-mono);
  letter-spacing:.06em;text-transform:uppercase;color:var(--muted);user-select:none}
details.stub summary::-webkit-details-marker{display:none}
details.stub summary::before{content:"+ ";color:var(--accent)}
details.stub[open] summary::before{content:"\2013  "}
.placeholder{border:1px dashed var(--border);border-radius:8px;padding:.8rem 1rem;
  color:var(--faint);font:11px/1.7 var(--font-mono);margin-top:.6rem}
.placeholder code{color:var(--muted)}

.empty{border:1px dashed var(--border);border-radius:10px;padding:2.6rem 2rem;
  text-align:center;color:var(--faint);margin-top:1.3rem;grid-column:1/-1}
.empty p{font:500 15px var(--font-ui);color:var(--muted)}
footer{margin-top:3.5rem;padding-top:1.2rem;border-top:1px solid var(--border);
  color:var(--faint);font:11px var(--font-mono);
  display:flex;justify-content:space-between;gap:1.2rem;flex-wrap:wrap}
footer a{color:var(--muted);text-decoration:underline;text-underline-offset:3px}
footer a:hover{color:var(--accent)}

.reveal{opacity:0;animation:rise .4s ease-out forwards;
  animation-delay:calc(.05s + var(--i,0)*.06s)}
@keyframes rise{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}
:focus-visible{outline:2px solid var(--accent);outline-offset:2px;border-radius:4px}
@media (prefers-reduced-motion:reduce){
  *,*::after,*::before{animation:none!important;transition:none!important}
  .reveal{opacity:1}
}
@media (max-width:640px){.sheet{inset:3vh 3vw}.rev{grid-template-columns:1fr}}
"""

JS = r"""
const stages=[...document.querySelectorAll('.stage')];
const cards=[...document.querySelectorAll('.tile')];
const shown=document.getElementById('shown-count');
const emptyFilter=document.getElementById('empty-filter');
let status='';
function apply(){
  const q=(document.getElementById('q').value||'').toLowerCase();
  let n=0;
  for(const c of cards){
    const ok=(!status||c.dataset.status===status)&&(!q||c.dataset.text.includes(q));
    c.classList.toggle('hide',!ok);
    if(ok)n++;
  }
  shown.textContent=n+(n===1?' asset':' assets');
  if(emptyFilter)emptyFilter.style.display=n?'none':'';
}
for(const s of stages)s.addEventListener('click',()=>{
  status=(status===s.dataset.status)?'':s.dataset.status;
  for(const x of stages)x.classList.toggle('active',x.dataset.status===status);
  apply();
});
document.getElementById('q').addEventListener('input',apply);
/* lightbox sheets */
let openSheet=null;
function closeSheet(){
  if(openSheet){openSheet.classList.remove('open');openSheet=null;}
  document.body.classList.remove('modal');
}
function openSheetFor(btn){
  const s=btn.parentElement.querySelector('.sheet');
  if(openSheet===s){closeSheet();return;}
  if(openSheet)openSheet.classList.remove('open');
  openSheet=s;s.classList.add('open');
  document.body.classList.add('modal');
  s.querySelector('.sheet-close').focus();
}
for(const b of document.querySelectorAll('.tile-btn'))
  b.addEventListener('click',()=>openSheetFor(b));
for(const x of document.querySelectorAll('.sheet-close'))
  x.addEventListener('click',closeSheet);
document.getElementById('scrim').addEventListener('click',closeSheet);
addEventListener('keydown',e=>{if(e.key==='Escape')closeSheet();});
/* copy buttons */
for(const b of document.querySelectorAll('.copy')){
  b.addEventListener('click',async()=>{
    try{await navigator.clipboard.writeText(new URL(b.dataset.url,location.origin).href);
      b.textContent='COPIED';b.classList.add('ok');
    }catch(e){b.textContent=b.dataset.url;}
    setTimeout(()=>{b.textContent='COPY';b.classList.remove('ok');},1400);
  });
}
"""

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
VIDEO_EXT = {".mp4", ".webm", ".mov"}
AUDIO_EXT = {".wav", ".mp3", ".flac", ".ogg"}
MODEL_EXT = {".glb", ".gltf"}


def esc(s: object) -> str:
    return html.escape(str(s), quote=True)


def human_size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    for unit, div in (("KB", 1024), ("MB", 1024**2), ("GB", 1024**3)):
        if n < div * 1024 or unit == "GB":
            return f"{n / div:.1f} {unit}"
    return f"{n} B"


STATUS_LABEL = {"brief": "BRIEF", "generated": "GENERATED", "gated": "GATED",
                "approved": "APPROVED", "exported": "EXPORTED"}
FUNNEL = ["brief", "generated", "gated", "approved", "exported"]


def latest_approved(a: dict) -> dict | None:
    for r in reversed(a["revisions"]):
        if r.get("approved_at"):
            return r
    return None


def _file_url(a_id: str, rev: dict, f: dict, inline: bool = False) -> str:
    url = f"/download/{quote(a_id)}/{rev['rev']}/{quote(f['name'])}"
    return url + ("?inline=1" if inline else "")


def _waveform(path: Path, bars: int = 46) -> str:
    """Deterministic SVG waveform from a 16-bit WAV; fallback: size-derived bars."""
    peaks = None
    try:
        with wave.open(str(path), "rb") as wf:
            if wf.getsampwidth() == 2:
                data = wf.readframes(wf.getnframes())
                samples = struct.unpack(f"<{len(data) // 2}h", data[: len(data) // 2 * 2])
                per = max(1, len(samples) // bars)
                peaks = []
                for i in range(bars):
                    chunk = samples[i * per:(i + 1) * per] or (0,)
                    peaks.append(max(abs(s) for s in chunk) / 32768)
    except Exception:
        peaks = None
    if peaks is None:
        n = path.stat().st_size
        peaks = [(abs((n >> (i % 9)) - 4096) % 100) / 100 * 0.6 + 0.15 for i in range(bars)]
    h = 100.0
    w = 100.0 / bars
    rects = "".join(
        f'<rect x="{i * w + w * 0.18:.2f}" y="{(h - p * h * 0.92) / 2:.2f}" '
        f'width="{w * 0.64:.2f}" height="{max(p * h * 0.92, 1.5):.2f}" fill="currentColor" '
        f'rx="0.6"/>' for i, p in enumerate(peaks))
    return (f'<svg class="wave" viewBox="0 0 100 100" preserveAspectRatio="none" '
            f'aria-label="audio waveform">{rects}</svg>')


def _read_text(root: Path, a_id: str, rev: dict, f: dict, limit: int) -> str:
    try:
        text = (root / "approved" / a_id / str(rev["rev"]) / f["name"]).read_text(
            encoding="utf-8", errors="replace").strip()
    except OSError:
        text = ""
    if len(text) > limit:
        text = text[:limit].rstrip() + "\u2026"
    return esc(text).replace("\n", "<br>")


def _glyph_mesh() -> str:
    return ('<svg class="glyph" viewBox="0 0 100 100" fill="none" stroke="currentColor" '
            'stroke-width="2" aria-hidden="true">'
            '<path d="M50 8 L88 30 L88 70 L50 92 L12 70 L12 30 Z"/>'
            '<path d="M50 8 L50 50 M12 30 L50 50 L88 30 M50 50 L50 92" '
            'stroke-dasharray="4 4"/></svg>')


def _glyph_video() -> str:
    return ('<svg class="glyph" viewBox="0 0 100 100" fill="none" stroke="currentColor" '
            'stroke-width="2" aria-hidden="true">'
            '<rect x="12" y="22" width="76" height="56"/><path d="M42 38 L62 50 L42 62 Z" '
            'fill="currentColor" stroke="none"/></svg>')


def _plate(root: Path, a: dict, rev: dict, big: bool = False) -> str:
    """Preview surface for an approved revision."""
    atype = a["type"]
    f = rev["files"][0]
    ext = Path(f["name"]).suffix.lower()
    px = " pixel" if atype in ("sprite", "image") and ext in {".png", ".gif"} else ""
    if ext in IMAGE_EXT:
        return f'<img class="{px.strip()}" src="{_file_url(a["id"], rev, f)}" alt="{esc(f["name"])}" loading="lazy">'
    if ext in VIDEO_EXT:
        stem = Path(f["name"]).stem
        poster = previews.poster_path(root, a["id"], rev["rev"], stem)
        poster_url = (f'/previews/{quote(a["id"])}/{rev["rev"]}/{quote(poster.name)}'
                      if poster.is_file() else None)
        if big:
            url = _file_url(a["id"], rev, f, inline=True)
            pattr = f' poster="{poster_url}"' if poster_url else ""
            return f'<video src="{url}"{pattr} controls preload="metadata" playsinline></video>'
        if poster_url:
            return f'<img src="{poster_url}" alt="{esc(f["name"])} preview" loading="lazy">'
        url = _file_url(a["id"], rev, f, inline=True)
        return f'<video src="{url}#t=0.1" muted preload="metadata" playsinline></video>'
    if atype == "story" or ext in {".md", ".txt"}:
        text = _read_text(root, a["id"], rev, f, 900 if big else 190)
        return f'<div class="prose"><p>{text}</p></div>'
    if ext in AUDIO_EXT:
        try:
            p = root / "approved" / a["id"] / str(rev["rev"]) / f["name"]
            w = _waveform(p)
        except OSError:
            w = _waveform(Path(__file__), bars=46)
        if big:
            return (w + f'<audio controls preload="metadata" '
                    f'src="{_file_url(a["id"], rev, f, inline=True)}"></audio>')
        return w
    if atype == "mesh":
        if ext in MODEL_EXT:
            src = _file_url(a["id"], rev, f, inline=True)
            if big:
                return (f'<model-viewer src="{src}" camera-controls auto-rotate '
                        f'shadow-soft alt="{esc(a["id"])} 3D preview"></model-viewer>')
            return (f'<model-viewer src="{src}" reveal="auto" disable-zoom '
                    f'interaction-prompt="none" shadow-soft></model-viewer>')
        return _glyph_mesh()
    if atype == "video":
        return _glyph_video()
    return _glyph_mesh()


def _sealed(a: dict) -> str:
    why = ("awaiting first generation" if a["status"] == "brief"
           else "visible after human approval")
    return f'<div class="sealed"><div><b>NOT APPROVED</b><span>{esc(why)}</span></div></div>'


def _gates_html(rev: dict) -> str:
    chips = "".join(
        f'<span class="gate {"pass" if v == "pass" else "fail"}">'
        f"{'\u2713' if v == 'pass' else '\u2715'} {esc(k).upper()}</span>"
        for k, v in (rev.get("gates") or {}).items())
    reasons = ""
    if rev.get("gate_reasons"):
        items = "".join(f"<li>{esc(r)}</li>" for r in rev["gate_reasons"])
        reasons = f'<ul class="reasons">{items}</ul>'
    return f'<div class="gates">{chips}</div>{reasons}' if chips else ""


def _files_html(a_id: str, rev: dict) -> str:
    rows = []
    for f in rev["files"]:
        url = _file_url(a_id, rev, f)
        if rev.get("approved_at"):
            rows.append(
                f'<li><a class="dl" href="{url}">{esc(f["name"])}</a>'
                f'<span class="size">{human_size(f["bytes"])}</span>'
                f'<button class="copy" data-url="{url}" '
                f'title="copy download link">COPY</button></li>')
        else:
            rows.append(f'<li><span class="dl" style="text-decoration:none">{esc(f["name"])}</span>'
                        f'<span class="size">{human_size(f["bytes"])}</span></li>')
    return f'<ul class="files">{"".join(rows)}</ul>'


def _rev_html(a: dict, rev: dict) -> str:
    params = (" \u00b7 ".join(f"{k}={v}" for k, v in (rev.get("params") or {}).items())
              or "no params recorded")
    if rev.get("approved_at"):
        actions = (f'<a class="btn mini" href="/download/{quote(a["id"])}/{rev["rev"]}.zip">'
                   f'Download revision (.zip)</a>')
        cls = " approved-row"
    elif rev.get("gates") and all(v == "pass" for v in rev["gates"].values()):
        actions = (f'<span class="awaiting">Awaiting human pick &mdash; </span>'
                   f'<button class="btn mini" disabled>Approve'
                   f'<sup class="planned">CLI: slip approve {esc(a["id"])} --rev {rev["rev"]}</sup></button>')
        cls = ""
    else:
        actions = (f'<button class="btn mini" disabled>Approve'
                   f'<sup class="planned">gates not passed</sup></button>')
        cls = ""
    return f"""
    <div class="rev{cls}">
      <span class="rev-no">REV {rev['rev']:02d}</span>
      <div>
        <div class="rev-meta"><span class="backend">{esc(rev.get('backend', '?'))}</span>
          \u00b7 {esc(rev.get('created', ''))} \u00b7 <i>{esc(params)}</i></div>
        {_gates_html(rev)}{_files_html(a['id'], rev)}
        {actions}
      </div>
    </div>"""


def _tile(a: dict, root: Path, i: int) -> str:
    status = a["status"]
    rev = latest_approved(a)
    plate = _plate(root, a, rev) if rev else _sealed(a)
    if rev:
        rev_tag = f'REV {rev["rev"]:02d} \u00b7 {esc(rev.get("backend", "?"))}'
    else:
        rev_tag = f'{len(a["revisions"])} REV' if a["revisions"] else "EMPTY"
    refs = []
    if a.get("scene_ref"):
        refs.append(f"SCENE <code>{esc(a['scene_ref'])}</code>")
    if a.get("character"):
        refs.append(f"CANON <code>{esc(a['character'])}</code>")
    refs_html = f'<p class="refs">{" \u00b7 ".join(refs)}</p>' if refs else ""
    hero = (f'<div class="sheet-hero">{_plate(root, a, rev, big=True)}</div>'
            if rev else
            '<div class="sheet-hero"><div class="sealed"><div>'
            '<b>NO PREVIEW</b><span>approval unlocks the preview</span></div></div></div>')
    revs_html = ("".join(_rev_html(a, r) for r in a["revisions"])
                 or f'<p class="placeholder">No revisions yet \u2014 '
                    f'<code>slip add {esc(a["id"])} &lt;file&gt; --backend &hellip;</code></p>')
    stub = ""
    if a["revisions"]:
        stub_rows = "".join(
            f'rev {r["rev"]}: <code>' + esc(" ".join(
                f"{k}={v}" for k, v in (r.get("params") or {}).items()) or "\u2014")
            + "</code><br>" for r in a["revisions"])
        stub = (f'<details class="stub"><summary>Parameter provenance &amp; gate log</summary>'
                f'<div class="placeholder">{stub_rows} Visual rev-comparator &amp; canon '
                f'ref-sheet diff \u2014 <i>planned</i>.</div></details>')
    search = " ".join([a["id"], a["type"], a["status"],
                       *(str(r.get("backend", "")) for r in a["revisions"])]).lower()
    wide = " wide" if a["type"] == "story" else ""
    return f"""
  <article class="tile{wide}" data-status="{status}" data-text="{esc(search)}">
    <button class="tile-btn reveal" style="--i:{i}" aria-haspopup="dialog"
            aria-label="open dossier for {esc(a['id'])}">
      <div class="plate">
        <span class="stamp {status}">{STATUS_LABEL[status]}</span>
        {plate}<span class="peek">Details \u2192</span>
      </div>
      <div class="meta"><h3>{esc(a['id'])}</h3>
        <span class="type">{esc(a['type'])}</span>
        <span class="revs">{rev_tag}</span></div>
    </button>
    <div class="sheet" role="dialog" aria-modal="true" aria-label="{esc(a['id'])} dossier">
      <div class="sheet-head"><h2>{esc(a['id'])}</h2>
        <span class="type">{esc(a['type'])}</span>
        <span class="stamp {status}">{STATUS_LABEL[status]}</span>
        <button class="sheet-close" aria-label="close">\u00d7</button></div>
      <div class="sheet-body">{refs_html}{hero}{revs_html}{stub}</div>
    </div>
  </article>"""


def render_catalog(root: Path) -> str:
    assets = model.list_assets(root)
    counts = {s: sum(1 for a in assets if a["status"] == s) for s in FUNNEL}
    approved = sum(1 for a in assets if a["status"] in ("approved", "exported"))
    total_bytes = sum(f["bytes"] for a in assets for r in a["revisions"] for f in r["files"])
    mv_needed = any(a["type"] == "mesh" and (rv := latest_approved(a)) is not None
                    and Path(rv["files"][0]["name"]).suffix.lower() in MODEL_EXT
                    for a in assets)
    mv_script = ('<script type="module" src="/static/model-viewer.min.js"></script>'
                 if mv_needed else "")

    stages = []
    for idx, s in enumerate(FUNNEL):
        if idx:
            stages.append('<span class="arrow">\u2192</span>')
        stages.append(f'<button class="stage" data-status="{s}">'
                      f'<span class="n">{counts[s]}</span><span class="lbl">{STATUS_LABEL[s]}</span></button>')

    if assets:
        tiles = "".join(_tile(a, root, i) for i, a in enumerate(assets))
        empty_filter = ('<div class="empty" id="empty-filter" style="display:none">'
                        '<p>No assets match the current filter.</p></div>')
    else:
        tiles = ('<div class="empty"><p>No assets yet.</p>'
                 '<span><code>slip brief &lt;id&gt; --type &hellip;</code></span></div>')
        empty_filter = ""

    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light dark">
<title>Slipway \u00b7 {esc(root.name)}</title>
<style>{CSS}</style>
{mv_script}
</head><body>
<div id="scrim"></div>
<div class="wrap">

<header class="masthead">
  <div>
    <span class="ship-class">Slipway \u00b7 Artifact Manager</span>
    <h1>{esc(root.name)}</h1>
    <p class="coordinates"><b>{len(assets)}</b> assets \u00b7 <b>{approved}</b> approved
      \u00b7 <b>{human_size(total_bytes)}</b> \u00b7 only approved artifacts are downloadable</p>
  </div>
  <nav class="actions">
    <button class="btn disabled" disabled>New asset<sup class="planned">planned \u00b7 CLI now</sup></button>
    <button class="btn disabled" disabled>Submit generation<sup class="planned">planned</sup></button>
    <a class="btn flare" href="/download/all.zip">Download all approved (ZIP)</a>
  </nav>
</header>

<section class="funnel" aria-label="lifecycle funnel">{''.join(stages)}</section>

<section class="toolbar">
  <input id="q" placeholder="Search \u2014 id / type / backend" autocomplete="off" spellcheck="false">
  <span class="count" id="shown-count">{len(assets)} assets</span>
</section>

<main class="gallery">{tiles}{empty_filter}</main>

<footer>
  <span>Slipway \u2014 assets are built here, launched into the engine</span>
  <span><a href="/api/assets">JSON API</a> \u00b7 <a href="/download/all.zip">approved bundle</a>
    \u00b7 no auth \u2014 trusted LAN</span>
</footer>

</div>
<script>{JS}</script>
</body></html>"""
