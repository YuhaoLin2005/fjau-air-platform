/* 空气质量插值面（产品主角）：
   - 竞态守卫（seq+AbortController）+ 客户端 10min 缓存（对齐后端 TTL）
   - 色盲冗余编码：深色边界描边 + 重度/严重档 SVG 斜纹图案
   - 点哪查哪（pip 反查）+ 图例 hover 反向高亮 */
import { api } from '../core/api.js';
import { state, on } from '../core/store.js';
import { toast } from '../ui/feedback.js';
import { AQ_COLORS, AQ_ADVICE, AQ_NAMES, AQ_LEVELS, levelIndex } from '../core/aqmeta.js';

let showCur = 0;                     // show() 渲染序号（自增取号+比对，勿用 seq() 比较自增陷阱）
const gridCache = {};                // pollutant -> geojson（对齐后端 10min TTL）
const inFlight = {};                 // pollutant -> 共享 Promise（并发调用同源不互耗）
const controllers = {};
let layer = null; let sampleLayer = null; let mapRef = null;
export let lastMeta = null;    // {source, sampled_at, standard}

/* 重度/严重档斜纹：注入到本图层 SVG renderer 的 defs */
function ensurePatterns(renderer) {
  const svg = renderer._container;
  if (!svg || svg.querySelector('#aqHatch5')) return;
  const defs = document.createElementNS('http://www.w3.org/2000/svg', 'defs');
  defs.innerHTML =
    `<pattern id="aqHatch5" patternUnits="userSpaceOnUse" width="8" height="8">
       <rect width="8" height="8" fill="#8E2A3C"/><path d="M0 8L8 0" stroke="#ffffff" stroke-width="1.6" opacity=".55"/></pattern>
     <pattern id="aqHatch6" patternUnits="userSpaceOnUse" width="6" height="6">
       <rect width="6" height="6" fill="#5B1220"/><path d="M0 8L8 0" stroke="#ffffff" stroke-width="2" opacity=".6"/></pattern>`;
  svg.appendChild(defs);
}

function style(f) {
  const lv = f.properties.level;
  const fill = lv === '重度' ? 'url(#aqHatch5)' : lv === '严重' ? 'url(#aqHatch6)' : f.properties.color;
  return { color: '#3d3833', weight: 0.6, opacity: 0.9, fillColor: fill, fillOpacity: 0.7 };
}

function popupHTML(f) {
  const p = f.properties;
  return `<b>${p.value} μg/m³</b>（${AQ_NAMES[state.pollutant]}）<br>等级: <b>${p.level}</b>` +
    `<div style="max-width:220px;font-size:12px;color:#7A6F62;margin-top:4px">${AQ_ADVICE[p.level] || ''}</div>` +
    `<div style="font-size:11px;color:#A99C8C;margin-top:4px">${lastMeta?.source || ''}<br>采样 ${lastMeta?.sampled_at || ''} · ${lastMeta?.standard || ''}</div>`;
}

export function initAQ(map) {
  mapRef = map;
  on('aq:highlight', lv => {
    if (!layer) return;
    layer.eachLayer(l => {
      if (l.feature.geometry.type !== 'Polygon') return;
      l.setStyle({ fillOpacity: lv == null ? 0.7 : (l.feature.properties.level === lv ? 0.85 : 0.15) });
    });
  });
}

export async function loadGrid(pollutant = state.pollutant) {
  if (gridCache[pollutant]) return gridCache[pollutant];
  if (inFlight[pollutant]) return inFlight[pollutant];
  controllers[pollutant]?.abort();
  const ctl = new AbortController(); controllers[pollutant] = ctl;
  inFlight[pollutant] = api(`/aq/grid?pollutant=${pollutant}&n=12&m=40`, { signal: ctl.signal })
    .then(gj => { gridCache[pollutant] = gj; return gj; })
    .catch(e => { if (e.name === 'AbortError') return null; throw e; })
    .finally(() => { delete inFlight[pollutant]; });
  return inFlight[pollutant];
}

export function invalidateCache(pollutant) {
  if (pollutant) {
    delete gridCache[pollutant]; delete inFlight[pollutant]; controllers[pollutant]?.abort();
  } else {
    Object.keys(gridCache).forEach(k => delete gridCache[k]);
    Object.keys(inFlight).forEach(k => delete inFlight[k]);
  }
}

export async function show(pollutant = state.pollutant) {
  const my = ++showCur;
  toast('空气质量网格采样 + IDW 插值中...');
  const gj = await loadGrid(pollutant);
  if (!gj || my !== showCur) return;
  lastMeta = gj.meta;
  remove();
  document.getElementById('map').classList.add('aq-mode');
  layer = L.geoJSON(
    { ...gj, features: gj.features.filter(f => f.geometry.type === 'Polygon') },
    { style, onEachFeature: (f, l) => l.bindPopup(popupHTML(f)) }
  ).addTo(mapRef);
  ensurePatterns(mapRef.getRenderer(layer));
  toast('插值面加载完成（HJ 633-2012 六级分级）');
}

export function remove() {
  if (layer) { mapRef.removeLayer(layer); layer = null; }
  setSamples(false);
  mapRef && document.getElementById('map').classList.remove('aq-mode');
}

/* 采样点子图层：默认隐藏，开启时按等级着色（真实采样 vs 插值对照） */
export function setSamples(onOff) {
  if (sampleLayer) { mapRef.removeLayer(sampleLayer); sampleLayer = null; }
  if (onOff && layer) {
    const gj = gridCache[state.pollutant];
    if (gj) sampleLayer = L.geoJSON(gj.samples, {
      pointToLayer: (f, ll) => L.circleMarker(ll, { radius: 4.5, color: '#fff', weight: 1, fillOpacity: 1, fillColor: AQ_COLORS[f.properties.level] || '#95A5A6' })
    }).addTo(mapRef);
  }
}

/* 点哪查哪：射线法 pip，返回所在格 */
export function queryAt(latlng) {
  if (!layer) return null;
  const x = latlng.lng, y = latlng.lat;
  let hit = null;
  layer.eachLayer(l => {
    if (hit || l.feature.geometry.type !== 'Polygon') return;
    const rings = l.feature.geometry.coordinates;
    const outer = rings[0];
    let inside = false;
    for (let i = 0, j = outer.length - 1; i < outer.length; j = i++) {
      const xi = outer[i][0], yi = outer[i][1], xj = outer[j][0], yj = outer[j][1];
      if (((yi > y) !== (yj > y)) && (x < (xj - xi) * (y - yi) / (yj - yi) + xi)) inside = !inside;
    }
    if (inside) hit = l.feature;
  });
  return hit;
}

/* 全市等级分布（现状卡用）：{level: count} */
export function distribution(gj) {
  const dist = {}; AQ_LEVELS.forEach(l => dist[l] = 0);
  gj.features.forEach(f => { if (f.geometry.type === 'Polygon') dist[f.properties.level] = (dist[f.properties.level] || 0) + 1; });
  return dist;
}

export function worstLevel(gj) {
  let worst = '优';
  gj.features.forEach(f => {
    if (f.geometry.type === 'Polygon' && levelIndex(f.properties.level) > levelIndex(worst)) worst = f.properties.level;
  });
  return worst;
}
