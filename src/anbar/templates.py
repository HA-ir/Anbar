# ruff: noqa: E501
"""HTML templates and UI page renderers for standalone web views."""

from __future__ import annotations

import html as _html
import json
from typing import Any


def render_password_page(obj_id: str, sig: str, exp: int | None = 0, failed: bool = False) -> str:
    """Standalone RTL unlock page for a pw-protected link.

    The GET form keeps the link's `sig`/`exp` in hidden fields (a bare
    `?pw=` would drop them and fail auth), shows a server-driven error
    line when the previous try was wrong, and includes a show-password
    eye toggle.
    """
    html = """<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>anbar · قفل</title>
<style>
:root{--bg:#0b0f17;--bg2:#131924;--bg3:#1b2333;--line:#232d3f;--line2:#334155;
--tx:#f1f5f9;--tx2:#94a3b8;--tx3:#8598b0;--brand:#3b82f6;--brand-soft:rgba(59,130,246,0.12);--err:#ef4444}
@media(prefers-color-scheme:light){:root{--bg:#f8fafc;--bg2:#ffffff;--bg3:#f1f5f9;
--line:#e2e8f0;--line2:#cbd5e1;--tx:#0f172a;--tx2:#475569;--tx3:#64748b;--brand:#2563eb;--brand-soft:rgba(37,99,235,0.08);--err:#dc2626}}
*{box-sizing:border-box;margin:0}
:focus-visible{outline:2px solid var(--brand);outline-offset:2px}
body{font-family:'Vazirmatn',system-ui,-apple-system,'Segoe UI',Tahoma,sans-serif;
min-height:100vh;display:flex;align-items:center;justify-content:center;padding:24px;
background:var(--bg);color:var(--tx)}
.card{width:100%;max-width:380px;background:var(--bg2);border:1px solid var(--line);
border-radius:12px;padding:32px 26px;text-align:center;
box-shadow:0 1px 3px rgba(0,0,0,.08),0 12px 32px rgba(0,0,0,.15);animation:rise .25s ease-out}
@keyframes rise{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}
.lock{width:52px;height:52px;margin:0 auto 16px;border-radius:12px;display:flex;
align-items:center;justify-content:center;background:var(--brand-soft);border:1px solid var(--line);color:var(--brand)}
h1{font-size:16.5px;font-weight:700;margin-bottom:6px}
p{font-size:12.5px;color:var(--tx2);margin-bottom:20px;line-height:1.9}
form{display:flex;gap:8px}
.wrap{position:relative;flex:1}
input{width:100%;padding:11px 40px 11px 14px;border:1.5px solid var(--line2);
border-radius:12px;background:var(--bg3);color:var(--tx);font-family:inherit;
font-size:14px;outline:none;direction:ltr;text-align:left;transition:border-color .15s}
input:focus{border-color:var(--brand)}
.eye{position:absolute;right:10px;top:50%;transform:translateY(-50%);
background:none;border:none;color:var(--tx3);cursor:pointer;padding:4px;
display:flex;align-items:center;justify-content:center}
.eye:hover{color:var(--tx)}
button.sub{padding:11px 18px;background:var(--brand);color:#fff;border:none;
border-radius:12px;font-family:inherit;font-size:13.5px;font-weight:600;
cursor:pointer;display:flex;align-items:center;gap:6px;transition:opacity .15s}
button.sub:hover{opacity:.9}
.err{margin-top:14px;font-size:12px;color:var(--err);display:none}
.foot{margin-top:22px;font-size:11px;color:var(--tx3);letter-spacing:.05em}
</style>
</head>
<body>
<div class="card">
  <div class="lock">
    <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <rect x="3" y="11" width="18" height="11" rx="2" ry="2"></rect>
      <path d="M7 11V7a5 5 0 0 1 10 0v4"></path>
    </svg>
  </div>
  <h1>این فایل رمزگذاری شده است</h1>
  <p>برای دریافت و باز کردن فایل، رمز عبور ارائه‌شده توسط فرستنده را وارد کنید.</p>
  <form method="get" action="">
    <input type="hidden" name="sig" value="__SIG__">
    <input type="hidden" name="exp" value="__EXP__">
    <div class="wrap">
      <input type="password" name="pw" id="pwin" placeholder="رمز عبور" autofocus autocomplete="current-password">
      <button type="button" class="eye" id="eyebtn" aria-label="نمایش رمز">
        <svg id="eye-open" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path><circle cx="12" cy="12" r="3"></circle></svg>
        <svg id="eye-shut" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="display:none"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"></path><line x1="1" y1="1" x2="23" y2="23"></line></svg>
      </button>
    </div>
    <button type="submit" class="sub">
      باز کردن
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="5" y1="12" x2="19" y2="12"></line><polyline points="12 5 19 12 12 19"></polyline></svg>
    </button>
  </form>
  <div class="err" id="perr">رمز عبور اشتباه است — دوباره تلاش کنید.</div>
  <div class="foot">powered by anbar</div>
</div>
<script>
var err=document.getElementById('perr');
__FAILED__
document.getElementById('pwin').focus();
document.getElementById('eyebtn').onclick=function(){
  var inp=document.getElementById('pwin'),o=document.getElementById('eye-open'),
      s=document.getElementById('eye-shut'),show=inp.type==='password';
  inp.type=show?'text':'password';
  o.style.display=show?'none':'';
  s.style.display=show?'':'none';
};
</script>
</body>
</html>"""
    html = (
        html.replace("__SIG__", sig)
        .replace("__EXP__", str(int(exp or 0)))
        .replace("__FAILED__", "err.style.display='block';" if failed else "")
    )
    return html


def render_album_page(title: str, items: list[dict[str, Any]]) -> str:
    """Public gallery page for a shared album (no auth)."""
    escaped_title = _html.escape(title, quote=True)
    payload = json.dumps(items).replace("</", "<\\/")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>{_html.escape(title)}</title>
<style>
:root{{--bg:#0b0f17;--bg2:#131924;--bg3:#1b2333;--line:#232d3f;--line2:#334155;
--tx:#f1f5f9;--tx2:#94a3b8;--tx3:#8598b0;--brand:#3b82f6;--brand-soft:rgba(59,130,246,0.12)}}
@media(prefers-color-scheme:light){{:root{{--bg:#f8fafc;--bg2:#ffffff;--bg3:#f1f5f9;
--line:#e2e8f0;--line2:#cbd5e1;--tx:#0f172a;--tx2:#475569;--tx3:#64748b;--brand:#2563eb;--brand-soft:rgba(37,99,235,0.08)}}}}
*{{box-sizing:border-box;margin:0}}
:focus-visible{{outline:2px solid var(--brand);outline-offset:2px}}
body{{background:var(--bg);color:var(--tx);
font-family:'Vazirmatn',system-ui,'Segoe UI',Tahoma,sans-serif;padding:24px 16px}}
html[lang="en"] body{{font-family:'Inter',system-ui,-apple-system,'Segoe UI',sans-serif}}
.num,.size{{font-family:ui-monospace,SFMono-Regular,Menlo,Monaco,Consolas,monospace;font-variant-numeric:tabular-nums}}
h1{{font-size:17px;font-weight:700;text-align:center;margin-bottom:4px}}
.sub{{text-align:center;color:var(--tx3);font-size:12px;margin-bottom:22px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:14px;
max-width:1100px;margin:0 auto}}
.cell{{background:var(--bg2);border:1px solid var(--line);border-radius:14px;overflow:hidden}}
.thumb{{height:130px;background:var(--bg3);display:flex;align-items:center;
justify-content:center;overflow:hidden;cursor:pointer;position:relative}}
.thumb img,.thumb video{{width:100%;height:100%;object-fit:cover}}
.thumb .ico{{color:var(--tx3);font-weight:800;font-size:13px;letter-spacing:.1em;
display:flex;flex-direction:column;align-items:center;gap:6px}}
.thumb .ico svg{{width:32px;height:32px;fill:none;stroke:currentColor;
stroke-width:2;stroke-linecap:round;stroke-linejoin:round}}
.meta{{padding:10px 12px;display:flex;align-items:center;justify-content:space-between;
gap:8px;border-top:1px solid var(--line)}}
.name{{font-size:12.5px;font-weight:600;white-space:nowrap;overflow:hidden;
text-overflow:ellipsis;direction:rtl;text-align:right}}
.size{{font-size:11px;color:var(--tx3);white-space:nowrap}}
.btn-dl{{padding:5px 9px;border:1px solid var(--line2);border-radius:8px;
background:transparent;color:var(--tx2);cursor:pointer;display:inline-flex;
align-items:center;text-decoration:none;font-size:11px}}
.btn-dl:hover{{color:var(--tx);border-color:var(--brand)}}
.btn-dl svg{{width:13px;height:13px;fill:none;stroke:currentColor;stroke-width:2;
stroke-linecap:round;stroke-linejoin:round}}
.lb{{display:none;position:fixed;inset:0;background:rgba(0,0,0,.88);
z-index:999;align-items:center;justify-content:center;padding:20px}}
.lb.on{{display:flex}}
.lb-box{{max-width:92vw;max-height:90vh;position:relative;display:flex;
align-items:center;justify-content:center}}
.lb-box img,.lb-box video{{max-width:92vw;max-height:86vh;border-radius:10px}}
.lb-box iframe{{width:80vw;height:80vh;border:none;border-radius:10px;background:#fff}}
.lb-close{{position:absolute;top:-40px;right:0;color:#fff;font-size:28px;
background:none;border:none;cursor:pointer}}
.lb-dl{{position:absolute;bottom:-40px;right:0;color:#fff;text-decoration:none;
font-size:13px;display:flex;align-items:center;gap:6px}}
.lb-dl:hover{{color:var(--brand)}}
</style>
</head>
<body>
<h1>{escaped_title}</h1>
<div class="sub">{len(items)} files · anbar</div>
<div class="grid" id="grid"></div>
<div class="lb" id="lb">
  <div class="lb-box">
    <button class="lb-close" id="lbc" aria-label="close">&times;</button>
    <div id="lbcnt"></div>
    <a class="lb-dl" id="lbdl" download>Download</a>
  </div>
</div>
<script>
const ITEMS = __PAYLOAD__;
const grid = document.getElementById('grid');
const lb = document.getElementById('lb');
const cnt = document.getElementById('lbcnt');
const bdl = document.getElementById('lbdl');
function _esc(s){{return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');}}
function fsize(b){{
  if(!b)return'0 B';
  const u=['B','KB','MB','GB'];let i=0;
  while(b>=1024&&i<u.length-1){{b/=1024;i++;}}
  return (i===0?b:b.toFixed(1))+' '+u[i];
}}
grid.innerHTML = ITEMS.map((it,i)=>{{
  let th = '';
  if(it.kind==='image') th = '<img src=\"'+it.thumb_url+'\" loading=\"lazy\">';
  else if(it.kind==='video') th = '<video src=\"'+it.url+'#t=0.5\" preload=\"metadata\" muted playsinline></video>';
  else th = '<div class=\"ico\"><svg viewBox=\"0 0 24 24\"><path d=\"M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z\"></path><polyline points=\"14 2 14 8 20 8\"></polyline></svg><span>'+it.kind.toUpperCase()+'</span></div>';
  return '<div class=\"cell\">'
    +'<div class=\"thumb\" data-i=\"'+i+'\">'+th+'</div>'
    +'<div class=\"meta\">'
    +'<div style=\"min-width:0\"><div class=\"name\" title=\"'+_esc(it.name)+'\">'+_esc(it.name)+'</div><div class=\"size\">'+fsize(it.size)+'</div></div>'
    +'<a class=\"btn-dl\" href=\"'+it.url+'\" download=\"'+_esc(it.name)+'\" aria-label=\"download\"><svg viewBox=\"0 0 24 24\"><path d=\"M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4\"></path><polyline points=\"7 10 12 15 17 10\"></polyline><line x1=\"12\" y1=\"15\" x2=\"12\" y2=\"3\"></line></svg></a>'
    +'</div></div>';
}}).join('');

function openLb(idx){{
  const it = ITEMS[idx];
  if(!it) return;
  const url = it.url;
  if(it.kind==='image') cnt.innerHTML='<img src=\"'+url+'\">';
  else if(it.kind==='video'){{
    let vh='<video src=\"'+url+'\" controls autoplay playsinline crossorigin=\"anonymous\">';
    (it.subs||[]).forEach(tr=>{{
      vh+='<track kind=\"subtitles\" label=\"'+_esc(tr.label||tr.lang||'Sub')
        +'\" srclang=\"'+_esc(tr.lang||'')+'\" default=\"'+(tr.default?'true':'false')
        +'\" src=\"/f/'+it.id+'/subs/'+encodeURIComponent(tr.id)+'?sig='+it.sig+'&exp='+it.exp+'\">';
    }});
    vh+='</video>';
    cnt.innerHTML=vh;
    const v=cnt.querySelector('video');
    if(v&&v.textTracks){{
      const want=it.subs||[];
      for(let k=0;k<v.textTracks.length;k++)
        v.textTracks[k].mode=(want[k]&&want[k].default)?'showing':'disabled';
    }}
  }}
  else if(it.kind==='audio')cnt.innerHTML='<audio src=\"'+url
    +'\" controls autoplay style=\"width:min(500px,90vw)\"></audio>';
  else if(it.kind==='pdf')cnt.innerHTML='<iframe src=\"'+url+'\"></iframe>';
  else cnt.innerHTML='';
  bdl.href=url;bdl.download=it.name||'file';
  lb.classList.add('on');
}}
grid.addEventListener('click',e=>{{
  const t=e.target.closest('.thumb');if(!t)return;
  openLb(+t.dataset.i);
}});
document.getElementById('lbc').onclick=()=>{{
  lb.classList.remove('on');cnt.innerHTML='';}};
lb.addEventListener('click',e=>{{
  if(e.target===lb){{lb.classList.remove('on');cnt.innerHTML='';}}}});
document.addEventListener('keydown',e=>{{
  if(e.key==='Escape'){{lb.classList.remove('on');cnt.innerHTML='';}}}});
</script>
</body>
</html>""".replace("__PAYLOAD__", payload)


def render_links_manage_page(
    obj_id: str,
    exp: int,
    row: dict[str, Any],
    opts: str,
    maxdl: int,
    fname: str,
    pw_checked: str,
    slug_js: str,
) -> str:
    """Standalone RTL admin manage page for re-minting / updating a link."""
    return f"""<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>anbar · مدیریت لینک</title>
<style>
:root{{--bg:#0b0f17;--bg2:#131924;--bg3:#1b2333;--line:#232d3f;--line2:#334155;
--tx:#f1f5f9;--tx2:#94a3b8;--tx3:#8598b0;--brand:#3b82f6;--brand-soft:rgba(59,130,246,0.12);--ok:#22c55e;--err:#ef4444}}
@media(prefers-color-scheme:light){{:root{{--bg:#f8fafc;--bg2:#ffffff;--bg3:#f1f5f9;
--line:#e2e8f0;--line2:#cbd5e1;--tx:#0f172a;--tx2:#475569;--tx3:#64748b;--brand:#2563eb;--brand-soft:rgba(37,99,235,0.08);--ok:#16a34a;--err:#dc2626}}}}
*{{box-sizing:border-box;margin:0}}
:focus-visible{{outline:2px solid var(--brand);outline-offset:2px}}
body{{font-family:'Vazirmatn',system-ui,'Segoe UI',Tahoma,sans-serif;min-height:100vh;
display:flex;align-items:center;justify-content:center;padding:16px;color:var(--tx);
background:var(--bg)}}
.card{{width:100%;max-width:430px;background:var(--bg2);border:1px solid var(--line);
border-radius:12px;padding:24px 20px;box-shadow:0 1px 3px rgba(0,0,0,.08),0 12px 32px rgba(0,0,0,.15)}}
h1{{font-size:16px;font-weight:700;margin-bottom:4px}}
.fname{{font-size:12px;color:var(--tx3);margin-bottom:18px;direction:ltr;text-align:left}}
.row{{margin-bottom:14px}}
label{{display:block;font-size:12.5px;font-weight:600;margin-bottom:6px}}
input[type=text],input[type=number],select{{width:100%;padding:10px 12px;
border:1.5px solid var(--line2);border-radius:10px;background:var(--bg3);
color:var(--tx);font-family:inherit;font-size:13.5px;outline:none}}
input:focus,select:focus{{border-color:var(--brand)}}
.check{{display:flex;align-items:center;gap:7px;font-size:13px;cursor:pointer;user-select:none}}
.check input{{width:16px;height:16px;accent-color:var(--brand)}}
.actions{{display:flex;gap:8px;margin-top:20px}}
button{{flex:1;padding:11px 14px;border:none;border-radius:11px;font-family:inherit;
font-size:13.5px;font-weight:700;cursor:pointer}}
.primary{{background:var(--brand);color:#fff}}
.danger{{background:transparent;border:1.5px solid var(--err);color:var(--err);flex:0 0 auto;
padding-inline:18px}}
.msg{{display:none;margin-top:14px;padding:10px 12px;border-radius:10px;
font-size:12.5px;line-height:1.9}}
.msg.ok{{background:rgba(49,196,141,.12);color:var(--ok);word-break:break-word}}
.msg.err{{background:rgba(255,93,108,.12);color:var(--err)}}
.linkout{{margin-top:14px;display:none;background:var(--bg3);border:1px solid var(--line);
border-radius:10px;padding:10px 12px;font-family:ui-monospace,monospace;
font-size:11.5px;direction:ltr;text-align:left;word-break:break-all;user-select:all}}
@media(max-width:480px){{.card{{padding:20px 14px}}.actions{{flex-direction:column}}
.danger{{flex:auto}}}}
</style>
</head>
<body>
<div class="card">
  <h1>مدیریت لینک اشتراک</h1>
  <div class="fname">{fname}</div>
  <form id="mf">
    <div class="row">
      <label for="ttl">انقضای لینک</label>
      <select id="ttl">{opts}</select>
    </div>
    <div class="row">
      <label class="check"><input type="checkbox" id="haspw" {pw_checked}>
        محافظت با رمز عبور</label>
    </div>
    <div class="row" id="pwrow" style="display:none">
      <label for="npw">رمز عبور جدید</label>
      <input type="text" id="npw" autocomplete="off" placeholder="رمز دلخواه">
    </div>
    <div class="row">
      <label for="maxdl">سقف تعداد دانلود (۰ = بی‌نهایت)</label>
      <input type="number" id="maxdl" min="0" value="{maxdl}">
    </div>
    <div class="actions">
      <button type="submit" class="primary">ذخیره و ساخت لینک جدید</button>
      <button type="button" class="danger" id="revBtn">ابطال لینک</button>
    </div>
  </form>
  <div class="msg ok" id="mok"></div>
  <div class="msg err" id="merr"></div>
  <div class="linkout" id="lout"></div>
</div>
<script>
const OID = {obj_id!r}, OLD_EXP = {exp};
const SLUG = {slug_js!r};
const H = {{'Content-Type': 'application/json'}};

function show(id, txt) {{
  const e = document.getElementById(id);
  e.textContent = txt; e.style.display = 'block';
}}
document.getElementById('haspw').onchange = e => {{
  document.getElementById('pwrow').style.display =
    e.target.checked ? 'block' : 'none';
}};
document.getElementById('mf').onsubmit = async ev => {{
  ev.preventDefault();
  const ttl = parseInt(document.getElementById('ttl').value, 10);
  const hasPw = document.getElementById('haspw').checked;
  const npw = document.getElementById('npw').value.trim();
  if (hasPw && !npw) {{
    show('merr', 'برای محافظت با رمز، یک رمز وارد کنید.');
    return;
  }}
  const maxdl = parseInt(document.getElementById('maxdl').value, 10) || 0;
  try {{
    // revoke the current window first (idempotent; 404 is fine)
    await fetch('/api/v1/admin/links/' + OID + '/revoke/' + OLD_EXP,
      {{method: 'POST', headers: H}});
    let q = 'ttl=' + ttl + (hasPw ? '&password=' + encodeURIComponent(npw) : '')
      + (maxdl ? '&max_dl=' + maxdl : '')
      + (SLUG ? '&slug=' + encodeURIComponent(SLUG) : '');
    const r = await fetch('/f/' + OID + '/link?' + q,
      {{method: 'POST', headers: H}});
    if (!r.ok) throw new Error((await r.json()).detail || r.status);
    const j = await r.json();
    document.getElementById('merr').style.display = 'none';
    show('mok', 'لینک جدید ساخته شد — لینک قبلی ابطال شد:');
    const lo = document.getElementById('lout');
    lo.textContent = j.pretty_url || j.url;
    lo.style.display = 'block';
  }} catch (e) {{ show('merr', e.message || String(e)); }}
}};
document.getElementById('revBtn').onclick = async () => {{
  if (!confirm('این لینک برای همیشه ابطال شود؟')) return;
  try {{
    await fetch('/api/v1/admin/links/' + OID + '/revoke/' + OLD_EXP,
      {{method: 'POST', headers: H}});
    document.getElementById('mok').style.display = 'none';
    document.getElementById('lout').style.display = 'none';
    show('merr', 'لینک ابطال شد — این صفحه دیگر کار نمی‌کند.');
  }} catch (e) {{ show('merr', e.message || String(e)); }}
}};
document.getElementById('pwrow').style.display =
  document.getElementById('haspw').checked ? 'block' : 'none';
</script>
</body>
</html>"""
