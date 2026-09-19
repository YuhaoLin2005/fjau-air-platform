/* 页签：暴露评估 —— 污染面 × 学校/医院叠加（纯前端 pip，零新端点）
   诚实口径：POI 库覆盖金山片区（86 条）；插值面分辨率≈4km/格（m=40） */
import { state } from '../core/store.js';
import { api } from '../core/api.js';
import { skelHTML } from '../ui/feedback.js';
import * as aq from '../layers/aq.js';
import { AQ_COLORS, AQ_LEVELS, levelIndex } from '../core/aqmeta.js';

const $ = id => document.getElementById(id);
let cur = 0;
let hlLayer = null, mapRef = null;

export function initExposure(map) {
  mapRef = map;
  $('btnExposure').onclick = run;
  $('expCat').onchange = () => run();
  $('expLevel').onchange = () => run();
}

async function run() {
  const body = $('expBody');
  body.innerHTML = skelHTML(3);
  const my = ++cur;
  try {
    const gj = await aq.loadGrid(state.pollutant);
    const pois = (await api('/layers/pois')).features.filter(
      f => $('expCat').value.split(',').includes(f.properties.category));
    if (my !== cur) return;
    const thLv = $('expLevel').value;                       // '轻度' 等
    const hits = [], miss = [];
    pois.forEach(f => {
      const cell = aq.queryAt({ lat: f.properties.lat ?? f.geometry.coordinates[1], lng: f.properties.lon ?? f.geometry.coordinates[0] });
      // POI GeoJSON 无 lat/lon 属性时从几何取；queryAt 只认 aq 层
      (cell && levelIndex(cell.properties.level) >= levelIndex(thLv) ? hits : miss).push({ f, cell });
    });
    if (hlLayer) { mapRef.removeLayer(hlLayer); hlLayer = null; }
    hlLayer = L.layerGroup(hits.map(({ f, cell }) =>
      L.circleMarker([f.geometry.coordinates[1], f.geometry.coordinates[0]], {
        radius: 10, color: '#fff', weight: 2, fillOpacity: 0.95, fillColor: AQ_COLORS[cell.properties.level]
      }).bindPopup(`<b>${f.properties.name || '未命名'}</b>（${f.properties.category}）<br>` +
        `所在格浓度: <b>${cell.properties.value} μg/m³</b>（${cell.properties.level}）`)
    )).addTo(mapRef);

    const schools = hits.filter(h => h.f.properties.category === 'school').length;
    const hospitals = hits.filter(h => h.f.properties.category === 'hospital').length;
    body.classList.remove('is-loading');
    body.innerHTML =
      `<div class="exp-num"><b>${hits.length}</b> 处敏感设施处于「${thLv}」及以上区域</div>` +
      `<div class="exp-row">🏫 学校: <b>${schools}</b> / 16　🏥 医院: <b>${hospitals}</b> / 13</div>` +
      `<div class="status-src">叠加口径: ${AQ_LEVELS[levelIndex(thLv)]} 起算 · 污染面≈4km/格（IDW m=40）· POI 库覆盖金山片区</div>`;
  } catch (e) {
    if (my !== cur) return;
    body.innerHTML = `<div class="empty">评估失败：${e.message}<br><button class="btn btn-sm" id="expRetry">重试</button></div>`;
    $('expRetry').onclick = run;
  }
}
