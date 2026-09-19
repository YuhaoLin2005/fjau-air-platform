/* 页签：一阶段成果¹ —— 洪涝模块原功能收纳（淹没推演/疏散路径/避难选址/网格统计）
   功能与后端口径不变；只修竞态（seq 守卫）与静态数据缓存 */
import { state } from '../core/store.js';
import { api } from '../core/api.js';
import { toast } from '../ui/feedback.js';
import { getChart } from '../ui/charts.js';
import { showFlood } from '../ui/legend.js';
import { LEGACY_BBOX } from '../layers/basemap.js';

const $ = id => document.getElementById(id);
let floodCur = 0;
const fmt = m => m >= 1000 ? (m / 1000).toFixed(2) + ' km' : Math.round(m) + ' m';

let map, floodMod, roadsMod, poisMod;
let routeLayer = null, serviceLayer = null, gridLayer = null, shelterLayer = null;
let fromMk = null, toMk = null, serviceMk = null, measureLine = null;
let playTimer = null, floodLevels = null;
export const tool = { current: null };

export function initLegacy(mapRef, mods) {
  map = mapRef; floodMod = mods.flood; roadsMod = mods.roads; poisMod = mods.pois;

  $('lyFlood').onchange = async e => {
    await floodMod.toggle(e.target.checked, state.level);
    if (e.target.checked) showFlood();
  };
  $('lyRoads').onchange = async e => { await roadsMod.toggle(e.target.checked); };
  $('lyPois').onchange = async e => { await poisMod.toggle(e.target.checked); };

  // 漫游工具
  $('btnZoomIn').onclick = () => map.zoomIn();
  $('btnZoomOut').onclick = () => map.zoomOut();
  $('btnReset').onclick = () => map.fitBounds(LEGACY_BBOX);
  $('btnMeasure').onclick = () => {
    state.tool = state.tool === 'measure' ? null : 'measure';
    state.measurePts = [];
    $('btnMeasure').classList.toggle('active-tool', !!state.tool);
    toast(state.tool ? '测距模式：在地图上依次点击两点' : '测距取消');
  };
  $('btnExport').onclick = () => {
    toast('正在渲染导出...');
    html2canvas($('map'), { useCORS: true }).then(canvas => {
      const a = document.createElement('a');
      const ts = new Date().toISOString().replace(/[:T]/g, '-').slice(0, 16);
      a.download = `福州空气质量_${$('aqPollutant').value}_${ts}.png`;
      a.href = canvas.toDataURL('image/png'); a.click();
      toast('地图已导出为 PNG');
    }).catch(() => toast('导出失败'));
  };

  // 淹没推演
  refreshFloodStat();
  $('levelSlider').oninput = async e => {
    const my = ++floodCur;
    state.level = +e.target.value;
    $('levelVal').textContent = state.level.toFixed(1) + ' m';
    if ($('lyFlood').checked) {
      await floodMod.load(state.level);
      if (my !== floodCur) return;
    }
    refreshFloodStat();
  };
  $('btnPlay').onclick = () => {
    if (state.playTimer) return;
    let lv = 6;
    state.playTimer = setInterval(() => {
      if (!$('lyFlood').checked) { $('lyFlood').checked = true; floodMod.toggle(true, lv); }
      $('levelSlider').value = lv;
      $('levelSlider').dispatchEvent(new Event('input'));
      if (++lv > 15) { clearInterval(state.playTimer); state.playTimer = null; }
    }, 1600);
    toast('淹没时间序列回放中（6m→15m）');
  };
  $('btnStop').onclick = () => { clearInterval(state.playTimer); state.playTimer = null; toast('回放已停止'); };

  // 疏散路径
  const mapClickPoint = () => new Promise(resolve => map.once('click', e => resolve([e.latlng.lat, e.latlng.lng])));
  const setMarker = (pt, color) => L.circleMarker(pt, { radius: 7, color: '#fff', weight: 2, fillColor: color, fillOpacity: 1 }).addTo(map);
  $('btnFrom').onclick = async () => {
    toast('请在地图上点击起点');
    const pt = await mapClickPoint();
    if (fromMk) map.removeLayer(fromMk);
    fromMk = setMarker(pt, '#27ae60'); state.fromPt = pt;
    $('btnFrom').textContent = '① 起点 ' + pt[0].toFixed(4) + ',' + pt[1].toFixed(4);
  };
  $('btnTo').onclick = async () => {
    toast('请在地图上点击终点');
    const pt = await mapClickPoint();
    if (toMk) map.removeLayer(toMk);
    toMk = setMarker(pt, '#c0392b'); state.toPt = pt;
    $('btnTo').textContent = '② 终点 ' + pt[0].toFixed(4) + ',' + pt[1].toFixed(4);
  };
  $('btnRoute').onclick = async () => {
    if (!state.fromPt || !state.toPt) return toast('请先设置起终点');
    toast('路径计算中（pgr_dijkstra）...');
    const q = `flon=${state.fromPt[1]}&flat=${state.fromPt[0]}&tlon=${state.toPt[1]}&tlat=${state.toPt[0]}` +
      `&mode=${$('routeMode').value}&avoid_flood=${$('avoidFlood').checked}&level=${state.level}`;
    try {
      const r = await api('/route?' + q);
      if (routeLayer) map.removeLayer(routeLayer);
      routeLayer = L.geoJSON(r.geometry, { style: { color: '#e74c3c', weight: 5, opacity: 0.9 } }).addTo(map);
      map.fitBounds(routeLayer.getBounds(), { padding: [40, 40] });
      $('routeResult').classList.add('show');
      $('routeResult').innerHTML =
        `<b>${r.mode === 'car' ? '车行救援' : '步行疏散'}路径</b>${r.avoid_flood ? `（已避开 ${r.level}m 水位淹没路段）` : '（未考虑淹没）'}<br>` +
        `距离: <b>${fmt(r.distance_m)}</b><br>预计耗时: <b>${r.time_min} 分钟</b><br>` +
        `途经节点: ${r.start.lon.toFixed(4)},${r.start.lat.toFixed(4)} → ${r.end.lon.toFixed(4)},${r.end.lat.toFixed(4)}`;
    } catch (err) {
      $('routeResult').classList.add('show');
      $('routeResult').innerHTML = `<b>计算失败:</b> ${err.message}`;
    }
  };
  $('btnClearRoute').onclick = () => {
    [routeLayer, fromMk, toMk].forEach(l => l && map.removeLayer(l));
    routeLayer = fromMk = toMk = null; state.fromPt = state.toPt = null;
    $('btnFrom').textContent = '① 设起点'; $('btnTo').textContent = '② 设终点';
    $('routeResult').classList.remove('show');
  };

  // 服务区
  $('btnServiceCenter').onclick = async () => {
    toast('请在地图上点击服务区中心点');
    const pt = await mapClickPoint();
    if (serviceMk) map.removeLayer(serviceMk);
    serviceMk = setMarker(pt, '#8e6fc1'); state.servicePt = pt;
    $('serviceCenterHint').textContent = pt[0].toFixed(4) + ',' + pt[1].toFixed(4);
  };
  $('saMin').oninput = e => $('saMinVal').textContent = e.target.value;
  $('btnServiceArea').onclick = async () => {
    if (!state.servicePt) return toast('请先选择中心点');
    toast('服务区计算中（pgr_drivingDistance）...');
    const q = `lon=${state.servicePt[1]}&lat=${state.servicePt[0]}&minutes=${$('saMin').value}&mode=${$('saMode').value}`;
    try {
      const r = await api('/service_area?' + q);
      if (serviceLayer) map.removeLayer(serviceLayer);
      serviceLayer = L.geoJSON(r.geometry, { style: { color: '#8e6fc1', weight: 1, fillColor: '#8e6fc1', fillOpacity: 0.25 } }).addTo(map);
      map.fitBounds(serviceLayer.getBounds(), { padding: [30, 30] });
      toast(`${r.mode === 'car' ? '车行' : '步行'} ${r.minutes} 分钟服务区：覆盖路网 ${r.network_km} km`);
    } catch (e) { toast(e.message); }
  };

  // 避难选址
  $('btnShelter').onclick = async () => {
    toast('选址分析计算中...');
    try {
      const gj = await api(`/shelters?level=${state.level}`);
      if (shelterLayer) map.removeLayer(shelterLayer);
      shelterLayer = L.geoJSON(gj, {
        pointToLayer: (f, latlng) => L.circleMarker(latlng, {
          radius: 9, color: '#fff', weight: 1.5,
          fillColor: f.properties.safe ? '#27ae60' : '#f39c12', fillOpacity: 0.9 }),
        onEachFeature: (f, l) => l.bindPopup(
          `<b>${f.properties.name}</b>（${f.properties.category}）<br>` +
          `高程: ${f.properties.elev_m} m ${f.properties.safe ? '✅高于当前水位' : '⚠️低于当前水位'}<br>` +
          `面积: ${f.properties.area_ha} ha<br>选址适宜性得分: <b>${f.properties.score}</b>`)
      }).addTo(map);
      const n = gj.features.length, safe = gj.features.filter(f => f.properties.safe).length;
      $('shelterResult').classList.add('show');
      $('shelterResult').innerHTML = `候选避难点 <b>${n}</b> 处，其中当前水位下安全 <b>${safe}</b> 处（绿色），受威胁 ${n - safe} 处（橙色）。得分 = 高程安全度×6 + 规模×4。`;
    } catch (e) { toast(e.message); }
  };
  $('btnCoverage').onclick = async () => {
    toast('覆盖率计算中...');
    try {
      const r = await api(`/coverage?level=${state.level}&radius_m=500`);
      $('shelterResult').classList.add('show');
      $('shelterResult').innerHTML = `当前 ${state.level}m 水位情景下，候选避难点 500m 缓冲区对<b>未淹没路网</b>的覆盖率：<b>${r.covered_road_pct}%</b>。`;
    } catch (e) { toast(e.message); }
  };

  // 网格统计
  $('btnGridStat').onclick = async () => {
    toast('渔网叠加统计中...');
    try {
      const gj = await api(`/stats/grid?level=${state.level}&cell_deg=0.005`);
      if (gridLayer) map.removeLayer(gridLayer);
      const maxF = Math.max(1, ...gj.features.map(f => f.properties.flooded_road_m));
      gridLayer = L.geoJSON(gj, {
        style: f => {
          const v = f.properties.flooded_road_m / maxF;
          return { color: '#b58a1b', weight: 0.5, fillOpacity: 0.12 + v * 0.55,
                   fillColor: v > 0.66 ? '#e74c3c' : v > 0.33 ? '#f39c12' : '#f7d774' };
        },
        onEachFeature: (f, l) => l.bindPopup(
          `网格 (${f.properties.ix},${f.properties.iy})<br>POI: ${f.properties.poi_cnt}<br>受灾路段: ${Math.round(f.properties.flooded_road_m)} m`)
      }).addTo(map);
      $('lyGrid').checked = true;
      drawGridChart(gj);
      const totalF = gj.features.reduce((s, f) => s + f.properties.flooded_road_m, 0);
      const totalP = gj.features.reduce((s, f) => s + f.properties.poi_cnt, 0);
      $('regionStat').innerHTML = `研究区网格数: <b>${gj.features.length}</b>（500m 渔网）<br>` +
        `淹没路段总长: <b>${fmt(totalF)}</b><br>设施点总数: <b>${totalP}</b><br>` +
        `受灾网格占比: <b>${(gj.features.filter(f => f.properties.flooded_road_m > 0).length / gj.features.length * 100).toFixed(1)}%</b>`;
    } catch (e) { toast(e.message); }
  };
  $('statClose').onclick = () => $('statCard').classList.remove('show');

  // 测距（全局 click，与点哪查哪互斥：state.tool === 'measure'）
  map.on('click', e => {
    if (state.tool !== 'measure') return;
    state.measurePts.push(e.latlng);
    if (state.measurePts.length === 2) {
      const [a, b] = state.measurePts;
      const d = map.distance(a, b);
      if (measureLine) map.removeLayer(measureLine);
      measureLine = L.polyline([a, b], { color: '#16a085', dashArray: '6 6' }).addTo(map);
      L.popup().setLatLng(b).setContent(`测量距离: <b>${fmt(d)}</b>`).openOn(map);
      state.measurePts = [];
    }
  });
}

async function refreshFloodStat() {
  try {
    if (!floodLevels) floodLevels = (await api('/flood/levels')).levels;
    const cur = floodLevels.find(x => x.level === state.level);
    $('floodArea').textContent = cur ? `淹没面积 ${cur.area_km2} km²` : '';
    $('floodStat').innerHTML = '水位情景 → 淹没斑块数 / 面积：<br>' +
      floodLevels.map(x => `<span style="${x.level === state.level ? 'font-weight:bold;color:#8E2A3C' : ''}">
      ${x.level}m：${x.patches} 块 / ${x.area_km2} km²</span>`).join('<br>');
  } catch (e) {
    $('floodStat').innerHTML = `加载失败: ${e.message}`;
  }
}

let gridChart = null;
function drawGridChart(gj) {
  const rows = gj.features.map(f => ({ ix: f.properties.ix, iy: f.properties.iy,
    v: f.properties.flooded_road_m, poi: f.properties.poi_cnt }))
    .sort((a, b) => b.v - a.v).slice(0, 15);
  $('statCard').classList.add('show');
  $('statTitle').textContent = `受灾路段长度 TOP15 网格（水位 ${state.level}m）`;
  gridChart = getChart($('statChart'));
  gridChart.setOption({
    grid: { left: 55, right: 15, bottom: 45, top: 15 },
    xAxis: { type: 'category', data: rows.map(r => `${r.ix},${r.iy}`), axisLabel: { fontSize: 12, rotate: 40 } },
    yAxis: { type: 'value', name: 'm', nameTextStyle: { fontSize: 12 } },
    series: [{ type: 'bar', data: rows.map(r => Math.round(r.v)),
      itemStyle: { color: '#1D6FB8' }, barMaxWidth: 18 }],
    tooltip: { trigger: 'axis' },
  });
  gridChart.on('click', p => {
    const r = rows[p.dataIndex];
    const target = gridLayer && gridLayer.getLayers().find(l =>
      l.feature.properties.ix === r.ix && l.feature.properties.iy === r.iy);
    if (target) map.fitBounds(target.getBounds(), { padding: [60, 60], maxZoom: 14 });
    toast(`网格 (${r.ix},${r.iy})：受灾路段 ${Math.round(r.v)} m，POI ${r.poi} 处`);
  });
}
