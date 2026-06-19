"""Browser collector script generator (request-mirroring version).

The WFS at mulk.kadastr.uz returns HTTP 403 even for same-origin GetFeature
calls made from the authenticated map page, and the portal authenticates via a
DWR session. So instead of *guessing* the WFS request, the collector
**intercepts the page's own network requests**, learns the exact request the
app uses to fetch feature data (URL + auth params + headers), and replays that
template across a grid, changing only the spatial extent. Results are
de-duplicated and downloaded as a GeoJSON file for import into the app.

The collector runs on the UZKAD map page (bookmarklet or pasted in the console)
and never talks to localhost, so CORS / mixed-content / private-network rules
do not apply.
"""
from __future__ import annotations

import json
from typing import List, Optional

from . import config

# __CFG__ is replaced with a JSON config object.
_COLLECTOR_TEMPLATE = r"""
(function(){
  var CFG = __CFG__;
  if (window.__uzkadBox) { try { window.__uzkadBox.remove(); } catch(e){} }

  // ---------------------------------------------------------------- UI ----
  var box = document.createElement('div');
  window.__uzkadBox = box;
  box.style.cssText = 'position:fixed;z-index:2147483647;right:16px;bottom:16px;width:360px;'
    + 'background:#0f172a;color:#e2e8f0;font:13px/1.45 system-ui,sans-serif;border:1px solid #334155;'
    + 'border-radius:12px;padding:14px 16px;box-shadow:0 8px 30px rgba(0,0,0,.5)';
  box.innerHTML =
      '<b>UZKAD kollektor</b>'
    + '<div id="uz-msg" style="margin-top:6px">Xaritada bitta obyektni bosing yoki '
    + 'zoom/suring \u2014 ilova so\u2018rovini o\u2018rganmoqda...</div>'
    + '<div id="uz-cap" style="margin-top:6px;color:#94a3b8;font-size:12px">Ushlangan: 0</div>'
    + '<div style="height:8px;background:#273449;border-radius:5px;margin-top:8px;overflow:hidden">'
    + '<div id="uz-bar" style="height:100%;width:0;background:linear-gradient(90deg,#2563eb,#38bdf8)"></div></div>'
    + '<div style="margin-top:10px;display:flex;gap:8px;flex-wrap:wrap">'
    + '<button id="uz-start" style="background:#2563eb;color:#fff;border:0;border-radius:7px;padding:6px 12px;cursor:pointer">Yig\u2018ishni boshlash</button>'
    + '<button id="uz-copy" style="background:#273449;color:#e2e8f0;border:1px solid #334155;border-radius:7px;padding:6px 12px;cursor:pointer">So\u2018rovni nusxalash</button>'
    + '<button id="uz-stop" style="background:#dc2626;color:#fff;border:0;border-radius:7px;padding:6px 12px;cursor:pointer">To\u2018xtatish</button>'
    + '</div>';
  document.body.appendChild(box);
  var msg = box.querySelector('#uz-msg');
  var capEl = box.querySelector('#uz-cap');
  var bar = box.querySelector('#uz-bar');
  var stopped = false, running = false;
  box.querySelector('#uz-stop').onclick = function(){ stopped = true; box.remove(); };

  // ------------------------------------------------ request interception --
  var captured = [];           // {method,url,headers,status,geo}
  window.__uzkadCaptured = captured;

  function isCandidate(url){
    return /request=GetFeature/i.test(url) || /service=WFS/i.test(url)
        || /\/gis\//i.test(url) || /\/ows\b/i.test(url) || /\/wfs\b/i.test(url);
  }

  function record(method, url, headers, status, bodyText){
    if (!url || !isCandidate(url)) return;
    var geo = !!(bodyText && /FeatureCollection|"features"\s*:/.test(String(bodyText).slice(0, 400)));
    captured.push({ method: method || 'GET', url: url, headers: headers || {}, status: status || 0, geo: geo });
    if (captured.length > 40) captured.shift();
    capEl.textContent = 'Ushlangan: ' + captured.length
      + (pickTemplate() ? ' \u2014 ishlatsa bo\u2018ladigan shablon topildi \u2713' : '');
  }

  // Prefer: 200 + geojson + has bbox; then 200 + has bbox; then any 200; else any.
  function pickTemplate(){
    var ok = captured.filter(function(c){ return c.status >= 200 && c.status < 300; });
    function byBbox(arr){ return arr.filter(function(c){ return /[?&]bbox=/i.test(c.url); }); }
    return (
      byBbox(ok.filter(function(c){ return c.geo; }))[0] ||
      byBbox(ok)[0] ||
      ok.filter(function(c){ return c.geo; })[0] ||
      ok[0] || null
    );
  }

  var of = window.fetch;
  if (of && !of.__uzkad) {
    window.fetch = function(input, init){
      var url = (typeof input === 'string') ? input : (input && input.url);
      var method = (init && init.method) || (input && input.method) || 'GET';
      var headers = {};
      try { if (init && init.headers) new Headers(init.headers).forEach(function(v, k){ headers[k] = v; }); } catch(e){}
      var p = of.apply(this, arguments);
      try {
        if (url && isCandidate(url)) {
          p.then(function(r){ try { r.clone().text().then(function(t){ record(method, url, headers, r.status, t); }); } catch(e){} }).catch(function(){});
        }
      } catch(e){}
      return p;
    };
    window.fetch.__uzkad = 1;
  }

  var XP = XMLHttpRequest.prototype;
  if (!XP.__uzkad) {
    var oOpen = XP.open, oSend = XP.send, oSet = XP.setRequestHeader;
    XP.open = function(m, u){ this.__m = m; this.__u = u; this.__h = {}; return oOpen.apply(this, arguments); };
    XP.setRequestHeader = function(k, v){ try { this.__h[k] = v; } catch(e){} return oSet.apply(this, arguments); };
    XP.send = function(){
      var x = this;
      try {
        x.addEventListener('load', function(){
          try {
            var t = (x.responseType === '' || x.responseType === 'text') ? x.responseText : '';
            record(x.__m, x.__u, x.__h, x.status, t);
          } catch(e){}
        });
      } catch(e){}
      return oSend.apply(this, arguments);
    };
    XP.__uzkad = 1;
  }

  // ------------------------------------------------------- copy template --
  box.querySelector('#uz-copy').onclick = function(){
    var t = pickTemplate() || captured[captured.length - 1];
    var txt = t
      ? (t.method + ' ' + t.url + '\n\nHeaders: ' + JSON.stringify(t.headers, null, 2)
         + '\nStatus: ' + t.status + ' \u00b7 geojson: ' + t.geo)
      : 'Hali hech qanday WFS/ma\u2018lumot so\u2018rovi ushlanmadi. Xaritada obyekt bosing.';
    try { navigator.clipboard.writeText(txt); msg.textContent = 'So\u2018rov nusxalandi. Menga yuboring.'; }
    catch(e){ console.log('[UZKAD] captured request:\n' + txt); msg.textContent = 'Konsolga chiqarildi (clipboard yopiq).'; }
  };

  // --------------------------------------------------------------- grid ---
  function toMerc(lon, lat){
    var x = lon * 20037508.34 / 180;
    var y = Math.log(Math.tan((90 + lat) * Math.PI / 360)) / (Math.PI / 180) * 20037508.34 / 180;
    return [x, y];
  }
  var sw = toMerc(CFG.bbox[0], CFG.bbox[1]);
  var ne = toMerc(CFG.bbox[2], CFG.bbox[3]);
  var cells = [];
  for (var yy = sw[1]; yy < ne[1]; yy += CFG.grid)
    for (var xx = sw[0]; xx < ne[0]; xx += CFG.grid)
      cells.push([xx, yy, Math.min(xx + CFG.grid, ne[0]), Math.min(yy + CFG.grid, ne[1])]);

  function stripParams(u, names){
    var i = u.indexOf('?'); if (i < 0) return u;
    var base = u.slice(0, i), parts = u.slice(i + 1).split('&');
    var keep = parts.filter(function(p){ return names.indexOf(p.split('=')[0].toLowerCase()) < 0; });
    return base + (keep.length ? '?' + keep.join('&') : '');
  }

  function cellUrl(tpl, c, start){
    var u;
    if (tpl) {
      u = stripParams(tpl.url, ['bbox','cql_filter','filter','featureid','resourceid','startindex','count','maxfeatures','propertyname']);
    } else {
      u = CFG.wfs + '?service=WFS&version=2.0.0&request=GetFeature&typeNames=' + encodeURIComponent(CFG.layer);
    }
    u += (u.indexOf('?') < 0 ? '?' : '&') + 'bbox=' + c.join(',') + ',' + CFG.srs;
    if (CFG.cql) u += '&cql_filter=' + encodeURIComponent(CFG.cql);
    u += '&count=' + CFG.page + '&startIndex=' + start;
    if (!/outputformat=/i.test(u)) u += '&outputFormat=' + encodeURIComponent(CFG.format);
    if (!/srsname=/i.test(u)) u += '&srsName=' + encodeURIComponent(CFG.srs);
    if (!/request=/i.test(u)) u += '&service=WFS&version=2.0.0&request=GetFeature';
    return u;
  }

  function replayHeaders(tpl){
    var h = { 'Accept': 'application/json' };
    if (tpl && tpl.headers) {
      for (var k in tpl.headers) {
        var lk = k.toLowerCase();
        if (lk === 'cookie' || lk === 'host' || lk.indexOf('content-') === 0 || lk === 'accept') continue;
        h[k] = tpl.headers[k];
      }
    }
    return h;
  }

  var seen = Object.create(null), feats = [], done = 0, found = 0, errors = 0;

  async function fetchCell(tpl, hdrs, c){
    for (var start = 0; ; start += CFG.page) {
      if (stopped) return;
      var r;
      try { r = await fetch(cellUrl(tpl, c, start), { credentials: 'include', headers: hdrs }); }
      catch(e){ errors++; return; }
      if (!r.ok) { errors++; return; }
      var j; try { j = await r.json(); } catch(e){ errors++; return; }
      var fs = (j && j.features) || [];
      for (var k = 0; k < fs.length; k++) {
        var f = fs[k];
        var key = (f.properties && (f.properties.uid || f.properties.cadastral_number)) || f.id;
        if (key != null) { if (seen[key]) continue; seen[key] = 1; }
        feats.push(f); found++;
      }
      if (fs.length < CFG.page) return;
    }
  }

  function update(){
    var pct = cells.length ? Math.round(done / cells.length * 100) : 100;
    bar.style.width = pct + '%';
    msg.textContent = done + '/' + cells.length + ' katak \u00b7 ' + found + ' obyekt'
      + (errors ? (' \u00b7 ' + errors + ' xato') : '');
  }

  function finish(){
    running = false;
    if (!feats.length) {
      msg.innerHTML = 'Hech narsa olinmadi (' + errors + ' xato). '
        + '<b>So\u2018rovni nusxalash</b> tugmasini bosib, ushlangan so\u2018rovni menga yuboring.';
      return;
    }
    var blob = new Blob([JSON.stringify({ type: 'FeatureCollection', features: feats })], { type: 'application/json' });
    var a = document.createElement('a');
    a.href = URL.createObjectURL(blob); a.download = CFG.filename;
    document.body.appendChild(a); a.click(); a.remove();
    msg.innerHTML = '<b>Tayyor:</b> ' + found + ' obyekt (' + CFG.filename + '). Ilovaga import qiling.';
    bar.style.width = '100%';
  }

  async function run(){
    if (running) return; running = true; stopped = false;
    var tpl = pickTemplate();
    if (!tpl) {
      msg.innerHTML = '<b>Diqqat:</b> ishlatsa bo\u2018ladigan so\u2018rov shabloni hali topilmadi. '
        + 'Xaritada obyekt bosing/suring, keyin yana boshlang. Baribir urinib ko\u2018ramiz...';
    } else {
      msg.textContent = 'Shablon topildi (' + tpl.status + '). Yig\u2018ish boshlandi...';
    }
    var hdrs = replayHeaders(tpl);
    var i = 0;
    async function worker(){ while (i < cells.length && !stopped) { var idx = i++; try { await fetchCell(tpl, hdrs, cells[idx]); } catch(e){ errors++; } done++; update(); } }
    var ws = []; for (var w = 0; w < CFG.concurrency; w++) ws.push(worker());
    await Promise.all(ws); finish();
  }
  box.querySelector('#uz-start').onclick = run;
})();
"""


def build_config(
    region: str,
    bbox_4326: List[float],
    cql_filter: Optional[str],
    layer: str,
    grid_size: int,
    filename: str,
) -> dict:
    return {
        "wfs": config.WFS_URL,
        "layer": layer,
        "format": config.OUTPUT_FORMAT,
        "srs": config.SOURCE_CRS,
        "page": config.DEFAULT_PAGE_SIZE,
        "grid": grid_size,
        "concurrency": 6,
        "bbox": bbox_4326,
        "cql": cql_filter or "",
        "region": region,
        "filename": filename,
    }


def build_script(cfg: dict) -> str:
    return _COLLECTOR_TEMPLATE.replace("__CFG__", json.dumps(cfg))


def build_bookmarklet(script: str) -> str:
    """Wrap the script as a javascript: bookmarklet URL."""
    from urllib.parse import quote

    return "javascript:" + quote(script)
