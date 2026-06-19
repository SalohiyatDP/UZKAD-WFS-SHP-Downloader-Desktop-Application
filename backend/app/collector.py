"""Browser collector script generator.

Because the WFS at mulk.kadastr.uz rejects external credentials (HTTP 403),
the most reliable way to harvest features is to run the collection *inside the
already-authenticated map page*. This module builds a self-contained JavaScript
collector that the user runs on the UZKAD map page (as a bookmarklet or pasted
into the DevTools console). It:

  * builds a grid over the region (Web-Mercator) entirely in the browser,
  * fetches WFS GetFeature(BBOX) same-origin with ``credentials:'include'`` so
    the real session cookies are sent automatically (and adds a bearer token
    from localStorage/sessionStorage if the SPA uses one),
  * de-duplicates by uid / cadastral_number,
  * downloads the combined GeoJSON as a file.

The user then imports that file into the desktop app, which converts it to
SHP / GPKG / GeoJSON / KML. No localhost networking is required from the page,
so CORS / mixed-content / private-network restrictions do not apply.
"""
from __future__ import annotations

import json
from typing import List, Optional

from . import config

# The collector logic. __CFG__ is replaced with a JSON config object.
_COLLECTOR_TEMPLATE = r"""
(function(){
  var CFG = __CFG__;
  if (window.__uzkadRunning) { alert('UZKAD kollektor allaqachon ishlamoqda.'); return; }
  window.__uzkadRunning = true;

  var box = document.createElement('div');
  box.style.cssText = 'position:fixed;z-index:2147483647;right:16px;bottom:16px;width:320px;'
    + 'background:#0f172a;color:#e2e8f0;font:13px/1.4 system-ui,sans-serif;border:1px solid #334155;'
    + 'border-radius:12px;padding:14px 16px;box-shadow:0 8px 30px rgba(0,0,0,.5)';
  box.innerHTML = '<b>UZKAD kollektor</b><div id="uzkad-msg" style="margin-top:6px">Tayyorlanmoqda...</div>'
    + '<div style="height:8px;background:#273449;border-radius:5px;margin-top:8px;overflow:hidden">'
    + '<div id="uzkad-bar" style="height:100%;width:0;background:linear-gradient(90deg,#2563eb,#38bdf8)"></div></div>'
    + '<button id="uzkad-stop" style="margin-top:10px;background:#dc2626;color:#fff;border:0;'
    + 'border-radius:7px;padding:6px 12px;cursor:pointer">To\u2018xtatish</button>';
  document.body.appendChild(box);
  var msg = box.querySelector('#uzkad-msg');
  var bar = box.querySelector('#uzkad-bar');
  var stopped = false;
  box.querySelector('#uzkad-stop').onclick = function(){ stopped = true; };

  function toMerc(lon, lat){
    var x = lon * 20037508.34 / 180;
    var y = Math.log(Math.tan((90 + lat) * Math.PI / 360)) / (Math.PI / 180);
    y = y * 20037508.34 / 180;
    return [x, y];
  }

  var sw = toMerc(CFG.bbox[0], CFG.bbox[1]);
  var ne = toMerc(CFG.bbox[2], CFG.bbox[3]);
  var cells = [];
  for (var yy = sw[1]; yy < ne[1]; yy += CFG.grid) {
    for (var xx = sw[0]; xx < ne[0]; xx += CFG.grid) {
      cells.push([xx, yy, Math.min(xx + CFG.grid, ne[0]), Math.min(yy + CFG.grid, ne[1])]);
    }
  }

  // Try to locate a JWT-like bearer token in storage.
  var token = null;
  try {
    var stores = [window.localStorage, window.sessionStorage];
    var re = /ey[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]+/;
    for (var s = 0; s < stores.length && !token; s++) {
      var st = stores[s]; if (!st) continue;
      for (var i = 0; i < st.length; i++) {
        var v = st.getItem(st.key(i)); if (!v) continue;
        var m = re.exec(v); if (m) { token = m[0]; break; }
      }
    }
  } catch (e) {}

  var headers = { 'Accept': 'application/json' };
  if (token) headers['Authorization'] = 'Bearer ' + token;

  function cellUrl(c, start){
    var u = CFG.wfs + '?service=WFS&version=2.0.0&request=GetFeature'
      + '&typeNames=' + encodeURIComponent(CFG.layer)
      + '&outputFormat=' + encodeURIComponent(CFG.format)
      + '&srsName=' + encodeURIComponent(CFG.srs)
      + '&count=' + CFG.page + '&startIndex=' + start
      + '&bbox=' + c.join(',') + ',' + CFG.srs;
    if (CFG.cql) u += '&cql_filter=' + encodeURIComponent(CFG.cql);
    return u;
  }

  var seen = Object.create(null);
  var feats = [];
  var done = 0, found = 0, errors = 0;

  async function fetchCell(c){
    for (var start = 0; ; start += CFG.page) {
      if (stopped) return;
      var r;
      try { r = await fetch(cellUrl(c, start), { credentials: 'include', headers: headers }); }
      catch (e) { errors++; return; }
      if (!r.ok) { errors++; return; }
      var j;
      try { j = await r.json(); } catch (e) { errors++; return; }
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
    msg.textContent = done + '/' + cells.length + ' katak \u00b7 ' + found
      + ' obyekt' + (errors ? (' \u00b7 ' + errors + ' xato') : '');
  }

  async function run(){
    update();
    var i = 0;
    async function worker(){
      while (i < cells.length && !stopped) {
        var idx = i++;
        try { await fetchCell(cells[idx]); } catch (e) { errors++; }
        done++; update();
      }
    }
    var ws = [];
    for (var w = 0; w < CFG.concurrency; w++) ws.push(worker());
    await Promise.all(ws);
    finish();
  }

  function finish(){
    if (!feats.length) {
      msg.innerHTML = 'Hech narsa topilmadi (' + errors + ' xato). '
        + 'Sahifa login qilinganmi va qatlam/hudud to\u2018g\u2018rimi tekshiring.';
      window.__uzkadRunning = false;
      return;
    }
    var fc = { type: 'FeatureCollection', features: feats };
    var blob = new Blob([JSON.stringify(fc)], { type: 'application/json' });
    var a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = CFG.filename;
    document.body.appendChild(a); a.click(); a.remove();
    msg.innerHTML = '<b>Tayyor:</b> ' + found + ' obyekt yuklab olindi (' + CFG.filename
      + ').<br>Endi ilovadagi <b>"GeoJSON faylni import qilish"</b> orqali yuklang.';
    bar.style.width = '100%';
    window.__uzkadRunning = false;
  }

  run();
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
    # Bookmarklets must be URL-encoded and prefixed with javascript:
    from urllib.parse import quote

    return "javascript:" + quote(script)
