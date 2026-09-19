/* 页签：时空分析 —— 30 天逐时曲线（/aq/history）+ 时间轴拖动联动地图（着色 marker）
   诚实边界：后端无历史面插值端点，回放是逐点的；默认预选市中心锚点保证拖轴永远有联动对象 */
import { state } from '../core/store.js';
import { api } from '../core/api.js';
import { toast, skelHTML } from '../ui/feedback.js';
import { getChart } from '../ui/charts.js';
import { AQ_COLORS, AQ_NAMES, AQ_LIMITS, levelOf, levelIndex } from '../core/aqmeta.js';
import { FUZHOU_CENTER } from './live.js';

const $ = id => document.getElementById(id);
const AQ_LEVELS6 = ['优', '良', '轻度', '中度', '重度', '严重'];
let cur = 0;                       // 请求序号：++cur 取号，回来比对（seq() 自增陷阱已修）
let marker = null, anchor = FUZHOU_CENTER, data = null;   // data = {times, values}

export function initTimeseries(map) {
  // 选点：地图点选（工具态互斥）
  $('btnTsPoint').onclick = () => {
    state.tool = 'ts-point';
    toast('请在地图上点击选择分析点');
  };
  map.on('click', async e => {
    if (state.tool !== 'ts-point') return;
    state.tool = null;
    anchor = [e.latlng.lat, e.latlng.lng];
    await load();
  });

  $('tsPollutant').onchange = e => { state.pollutant = e.target.value; load(); };
  $('tsSlider').oninput = e => scrub(+e.target.value);

  map.on('popupclose', () => {});
}

export async function load() {
  const body = $('tsBody');
  body.innerHTML = skelHTML(2) + `<div class="ts-meta skel-meta"></div>`;
  body.classList.add('is-loading');
  const my = ++cur;
  try {
    const r = await api(`/aq/history?lat=${anchor[0].toFixed(4)}&lon=${anchor[1].toFixed(4)}&pollutant=${state.pollutant}&days=30`);
    if (my !== cur) return;
    data = { times: r.times, values: r.values };
    const pts = r.times.map((t, i) => [t, r.values[i]]).filter(p => p[1] != null);   // null 小时值跳过
    drawChart(pts);
    placeMarker(pts.length ? pts[pts.length - 1] : null);
    const sl = $('tsSlider');
    sl.max = pts.length - 1; sl.value = pts.length - 1;
    body.classList.remove('is-loading');
    scrub(pts.length - 1);
    $('tsAnchor').textContent = `分析点: ${anchor[0].toFixed(4)}, ${anchor[1].toFixed(4)}（默认市中心，可点「选点」重设）`;
  } catch (e) {
    if (my !== cur) return;
    body.innerHTML = `<div class="empty">历史曲线加载失败：${e.message}<br><button class="btn btn-sm" id="tsRetry">重试</button></div>`;
    $('tsRetry').onclick = load;
  }
}

let chart = null;
function drawChart(pts) {
  const th = AQ_LIMITS[state.pollutant] || [];
  const pieces = [];
  let lo = 0;
  ['优', '良', '轻度', '中度', '重度'].forEach((lv, i) => {
    pieces.push({ lt: th[i], color: AQ_COLORS[lv] }); lo = th[i];
  });
  pieces.push({ gte: lo, color: AQ_COLORS['严重'] });
  chart = getChart($('tsChart'));
  chart.setOption({
    grid: { left: 52, right: 14, bottom: 46, top: 14 },
    xAxis: { type: 'time', axisLabel: { fontSize: 11 } },
    yAxis: { type: 'value', name: 'μg/m³', nameTextStyle: { fontSize: 11 }, scale: true },
    visualMap: { show: false, dimension: 1, pieces },
    series: [{
      type: 'line', showSymbol: false, data: pts,
      lineStyle: { width: 1.5 }, emphasis: { disabled: true },
    }],
    tooltip: { trigger: 'axis', valueFormatter: v => v?.toFixed(1) + ' μg/m³' },
  });
  // 分级堆叠概览：30 天逐时值按六级占比
  const counts = {}; AQ_LEVELS6.forEach(l => counts[l] = 0);
  pts.forEach(p => counts[levelOf(state.pollutant, p[1])]++);
  drawStack(counts);
}

function drawStack(counts) {
  const total = Object.values(counts).reduce((s, n) => s + n, 0) || 1;
  $('tsStack').innerHTML = AQ_LEVELS6.map(l =>
    counts[l] ? `<span style="flex:${counts[l]};background:${AQ_COLORS[l]}" title="${l} ${counts[l]} 小时（${(counts[l] / total * 100).toFixed(1)}%）"></span>` : ''
  ).join('') || '<span class="hint">无数据</span>';
}

/* 时间轴拖动 → 该时刻浓度/等级/着色 marker 联动地图 */
function scrub(i) {
  if (!data || !data.times[i]) return;
  const v = data.values[i];
  if (v == null) { $('tsReadout').textContent = '该时刻无数值'; return; }
  const lv = levelOf(state.pollutant, v);
  $('tsReadout').innerHTML = `<span class="aq-badge" style="background:${AQ_COLORS[lv]}">${lv}</span> ` +
    `<b>${v.toFixed ? v.toFixed(1) : v}</b> μg/m³ · ${data.times[i].replace('T', ' ')}`;
  placeMarker([data.times[i], v]);
}

function placeMarker(pt) {
  if (!pt) return;
  const lv = levelOf(state.pollutant, pt[1]);
  if (marker) marker.setLatLng(latlngOf(pt)).setStyle({ fillColor: AQ_COLORS[lv] });
  else marker = L.circleMarker(latlngOf(pt), { radius: 9, color: '#fff', weight: 2, fillOpacity: 1, fillColor: AQ_COLORS[lv] }).addTo(window.__map);
  marker.bindPopup(`<b>${pt[1].toFixed(1)} μg/m³（${lv}）</b><br>${pt[0].replace('T', ' ')}<br>${AQ_NAMES[state.pollutant]} · 30 天逐时（Open-Meteo）`);
}
const latlngOf = pt => [anchor[0], anchor[1]];
