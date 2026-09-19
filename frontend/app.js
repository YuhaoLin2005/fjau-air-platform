/* 福州市暴雨内涝应急疏散与救援路径分析系统 - 前端逻辑 */
/* global L, echarts, html2canvas */
'use strict';

// ---------------- 全局状态 ----------------
const state = {
  token: null, role: null, username: null,
  level: 10,                       // 当前水位情景 (m)
  tool: null,                      // null | 'from' | 'to' | 'service' | 'measure'
  fromPt: null, toPt: null, servicePt: null,
  measurePts: [], routeLayer: null, serviceLayer: null,
  floodLayer: null, gridLayer: null, shelterLayer: null,
  playTimer: null,
};

const $ = id => document.getElementById(id);
const fmt = m => m >= 1000 ? (m / 1000).toFixed(2) + ' km' : Math.round(m) + ' m';
function toast(msg, ms = 2600) {
  const t = $('toast'); t.textContent = msg; t.style.display = 'block';
  clearTimeout(t._h); t._h = setTimeout(() => t.style.display = 'none', ms);
}
async function api(path, opt = {}) {
  const headers = { 'Content-Type': 'application/json', ...(opt.headers || {}) };
  if (state.token) {
    headers['Authorization'] = 'Bearer ' + state.token;
    path += (path.includes('?') ? '&' : '?') + 'token=' + state.token;  // 后端 query token 统一口径
  }
  const r = await fetch(path, { ...opt, headers });
  if (r.status === 401) {
    // 游客模式触发保护端点 → 引导登录（游客可浏览，分析需用户）
    toast('游客模式：分析功能需登录后使用', 3000);
    openAuth('login');
    throw new Error('请先登录');
  }
  if (!r.ok) {
    let msg = '请求失败';
    try { msg = (await r.json()).detail || msg; } catch (e) { /* noop */ }
    throw new Error(msg);
  }
  return r.json();
}
// 后端未用 Authorization 头而是 query token —— 统一改为 query 附加
async function apiQ(path, opt = {}) {
  if (state.token) path += (path.includes('?') ? '&' : '?') + 'token=' + state.token;
  return api(path, opt);
}

// ---------------- 地图初始化 ----------------
const map = L.map('map', { zoomControl: false, attributionControl: false })
  .setView([26.062, 119.245], 13);
const bounds = [[26.03, 119.19], [26.10, 119.30]];
L.tileLayer('/tiles/{z}/{x}/{y}.png', { maxZoom: 16, minZoom: 11 }).addTo(map);
map.fitBounds(bounds);
L.control.zoom({ position: 'bottomright' }).addTo(map);

// ---------------- 图层 ----------------
const roadStyle = hw => ({
  color: { motorway: '#8c4a2f', trunk: '#a05a2c', primary: '#c96a2b', secondary: '#d9902a',
           tertiary: '#c9b56e' }[hw] || '#9aa5ad',
  weight: { motorway: 4, trunk: 4, primary: 3.5, secondary: 3, tertiary: 2.5 }[hw] || 1.6,
});
fetch('/api/v1/meta/config').then(r => r.json()).then(c => { window.TDT_KEY = c.tdt_key || ''; });
/* ---- 底图切换器：本地瓦片 / OSM 在线 / 天地图插槽（KEY 就绪即激活） ---- */
const basemaps = {
  local: () => L.tileLayer('/tiles/{z}/{x}/{y}.png', { maxZoom: 16, minZoom: 11 }),
  osm: () => L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',
    { maxZoom: 19, attribution: '© OpenStreetMap contributors' }),
  tianditu: () => {
    if (!window.TDT_KEY) { toast('天地图未配置 KEY：在 backend/.env 加 TDT_KEY 后重启'); return null; }
    const tdt = (layer) => L.tileLayer(
      `https://t{s}.tianditu.gov.cn/${layer}/wmts?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0` +
      `&LAYER=${layer}&STYLE=default&TILEMATRIXSET=w&FORMAT=tiles&TILEMATRIX={z}&TILEROW={y}&TILECOL={x}` +
      `&tk=${window.TDT_KEY}`,
      { subdomains: ['0','1','2','3','4','5','6','7'], maxZoom: 18 });
    const vec = tdt('vec_w'), cva = tdt('cva_w');
    vec.on('add', () => cva.addTo(map)); vec.on('remove', () => map.removeLayer(cva));
    return vec;
  },
};
let baseLayer = basemaps.local().addTo(map);
window.basemapSel_change = e => {
  const mk = basemaps[e.target.value] && basemaps[e.target.value]();
  if (!mk) { e.target.value = 'local'; return; }
  map.removeLayer(baseLayer); baseLayer = mk.addTo(map);
};

const roadsLayer = L.geoJSON(null, { style: f => roadStyle(f.properties.highway) }).addTo(map);
roadsLayer.on('click', e => {
  const p = e.layer.feature.properties;
  L.popup().setLatLng(e.latlng).setContent(
    `<b>${p.name || '无名道路'}</b><br>类型: ${p.highway}<br>gid: ${p.gid}`).openOn(map);
});
const poiIcons = {
  park: '🌳', school: '🏫', hospital: '🏥', stadium: '🏟️', sports_centre: '🏊',
  community_centre: '🏘️', pitch: '⚽', place_of_worship: '⛩️', assembly_point: '🚩', driving_school: '🚗',
};
const poisLayer = L.geoJSON(null, {
  pointToLayer: (f, latlng) => L.marker(latlng, {
    icon: L.divIcon({ html: `<div style="font-size:17px;line-height:17px">${poiIcons[f.properties.category] || '📍'}</div>`,
                      className: '', iconSize: [17, 17] })
  }),
  onEachFeature: (f, l) => l.bindPopup(
    `<b>${f.properties.name || '未命名设施'}</b><br>类别: ${f.properties.category}`)
}).addTo(map);
let floodPolygons = null;
const floodLayerGroup = L.geoJSON(null, {
  style: { color: '#1a6fa8', weight: 1, fillColor: '#2a9fd8', fillOpacity: 0.45 }
}).addTo(map);

async function loadRoads() {
  toast('路网加载中...');
  const gj = await api('/api/layers/roads');
  roadsLayer.clearLayers(); roadsLayer.addData(gj);
  toast(`路网加载完成：${gj.features.length} 条路段`);
}
async function loadPois() {
  const gj = await api('/api/layers/pois');
  poisLayer.clearLayers(); poisLayer.addData(gj);
}
async function loadFlood() {
  const gj = await api(`/api/flood/geojson?level=${state.level}`);
  floodLayerGroup.clearLayers(); floodLayerGroup.addData(gj);
}
loadRoads(); loadPois(); loadFlood();

// ---------------- 图层开关 ----------------
$('lyRoads').onchange = e => e.target.checked ? map.addLayer(roadsLayer) : map.removeLayer(roadsLayer);
$('lyPois').onchange = e => e.target.checked ? map.addLayer(poisLayer) : map.removeLayer(poisLayer);
$('lyFlood').onchange = e => e.target.checked ? map.addLayer(floodLayerGroup) : map.removeLayer(floodLayerGroup);
$('lyGrid').onchange = e => state.gridLayer && (e.target.checked ? map.addLayer(state.gridLayer) : map.removeLayer(state.gridLayer));
$('lyService').onchange = e => state.serviceLayer && (e.target.checked ? map.addLayer(state.serviceLayer) : map.removeLayer(state.serviceLayer));

// ---------------- 漫游工具 ----------------
$('btnZoomIn').onclick = () => map.zoomIn();
$('btnZoomOut').onclick = () => map.zoomOut();
$('btnReset').onclick = () => map.fitBounds(bounds);
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
    a.download = `福州内涝应急地图_水位${state.level}m.png`;
    a.href = canvas.toDataURL('image/png');
    a.click();
    toast('地图已导出为 PNG');
  });
};

// ---------------- POI 检索 ----------------
$('btnPoiSearch').onclick = async () => {
  const kw = $('poiKw').value.trim();
  if (!kw) return toast('请输入关键字');
  const r = await api(`/api/poi/search?kw=${encodeURIComponent(kw)}`);
  $('poiResult').innerHTML = r.results.length
    ? r.results.map(x => `▸ ${x.name}（${x.category}）`).join('<br>') : '未找到匹配设施';
  if (r.results.length) {
    const first = r.results[0];
    map.setView([first.lat, first.lon], 15);
    L.popup().setLatLng([first.lat, first.lon]).setContent(`<b>${first.name}</b>`).openOn(map);
  }
};

// ---------------- 淹没分析 ----------------
async function refreshFloodStat() {
  const r = await api('/api/flood/levels');
  const cur = r.levels.find(x => x.level === state.level);
  $('floodArea').textContent = cur ? `淹没面积 ${cur.area_km2} km²` : '';
  $('floodStat').innerHTML = '水位情景 → 淹没斑块数 / 面积：<br>' +
    r.levels.map(x => `<span style="${x.level === state.level ? 'font-weight:bold;color:#c0392b' : ''}">
      ${x.level}m：${x.patches} 块 / ${x.area_km2} km²</span>`).join('<br>');
}
refreshFloodStat();

$('levelSlider').oninput = async e => {
  state.level = +e.target.value;
  $('levelVal').textContent = state.level.toFixed(1) + ' m';
  await loadFlood(); refreshFloodStat();
};
$('btnPlay').onclick = () => {
  if (state.playTimer) return;
  let lv = 6;
  state.playTimer = setInterval(() => {
    $('levelSlider').value = lv;
    $('levelSlider').dispatchEvent(new Event('input'));
    if (++lv > 15) { clearInterval(state.playTimer); state.playTimer = null; }
  }, 1600);
  toast('淹没时间序列回放中（6m→15m）');
};
$('btnStop').onclick = () => { clearInterval(state.playTimer); state.playTimer = null; toast('回放已停止'); };

// ---------------- 路径分析 ----------------
function mapClickPoint() {
  return new Promise(resolve => {
    map.once('click', e => resolve([e.latlng.lat, e.latlng.lng]));
  });
}
function setMarker(pt, color) {
  return L.circleMarker(pt, { radius: 7, color: '#fff', weight: 2, fillColor: color, fillOpacity: 1 }).addTo(map);
}
let fromMk = null, toMk = null;
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
    const r = await api('/api/route?' + q);
    if (state.routeLayer) map.removeLayer(state.routeLayer);
    state.routeLayer = L.geoJSON(r.geometry, { style: { color: '#e74c3c', weight: 5, opacity: 0.9 } }).addTo(map);
    map.fitBounds(state.routeLayer.getBounds(), { padding: [40, 40] });
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
  [state.routeLayer, fromMk, toMk].forEach(l => l && map.removeLayer(l));
  state.routeLayer = fromMk = toMk = null; state.fromPt = state.toPt = null;
  $('btnFrom').textContent = '① 设起点'; $('btnTo').textContent = '② 设终点';
  $('routeResult').classList.remove('show');
};

// ---------------- 服务区 ----------------
let serviceMk = null;
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
  const r = await api('/api/service_area?' + q);
  if (state.serviceLayer) map.removeLayer(state.serviceLayer);
  state.serviceLayer = L.geoJSON(r.geometry, {
    style: { color: '#8e6fc1', weight: 1, fillColor: '#8e6fc1', fillOpacity: 0.25 } }).addTo(map);
  map.fitBounds(state.serviceLayer.getBounds(), { padding: [30, 30] });
  toast(`${r.mode === 'car' ? '车行' : '步行'} ${r.minutes} 分钟服务区：覆盖路网 ${r.network_km} km`);
};

// ---------------- 避难点选址 ----------------
$('btnShelter').onclick = async () => {
  toast('选址分析计算中...');
  const gj = await apiQ(`/api/shelters?level=${state.level}`);
  if (state.shelterLayer) map.removeLayer(state.shelterLayer);
  state.shelterLayer = L.geoJSON(gj, {
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
};

// ---------------- 覆盖分析 ----------------
$('btnCoverage').onclick = async () => {
  toast('覆盖率计算中...');
  const r = await api(`/api/coverage?level=${state.level}&radius_m=500`);
  $('shelterResult').classList.add('show');
  $('shelterResult').innerHTML = `当前 ${state.level}m 水位情景下，候选避难点 500m 缓冲区对<b>未淹没路网</b>的覆盖率：<b>${r.covered_road_pct}%</b>。`;
};

// ---------------- 网格统计 ----------------
$('btnGridStat').onclick = async () => {
  toast('渔网叠加统计中...');
  const gj = await api(`/api/stats/grid?level=${state.level}&cell_deg=0.005`);
  if (state.gridLayer) map.removeLayer(state.gridLayer);
  const maxF = Math.max(1, ...gj.features.map(f => f.properties.flooded_road_m));
  state.gridLayer = L.geoJSON(gj, {
    style: f => {
      const v = f.properties.flooded_road_m / maxF;
      return { color: '#b58a1b', weight: 0.5, fillOpacity: 0.12 + v * 0.55,
               fillColor: v > 0.66 ? '#e74c3c' : v > 0.33 ? '#f39c12' : '#f7d774' };
    },
    onEachFeature: (f, l) => l.bindPopup(
      `网格 (${f.properties.ix},${f.properties.iy})<br>POI: ${f.properties.poi_cnt}<br>受灾路段: ${Math.round(f.properties.flooded_road_m)} m`)
  }).addTo(map);
  $('lyGrid').checked = true;

  // echarts 柱状图：受灾路段长度 TOP15 网格
  const rows = gj.features.map(f => ({ ix: f.properties.ix, iy: f.properties.iy,
    v: f.properties.flooded_road_m, poi: f.properties.poi_cnt }))
    .sort((a, b) => b.v - a.v).slice(0, 15);
  $('statCard').classList.add('show');
  $('statTitle').textContent = `受灾路段长度 TOP15 网格（水位 ${state.level}m）`;
  const chart = echarts.init($('statChart'));
  chart.setOption({
    grid: { left: 55, right: 15, bottom: 45, top: 15 },
    xAxis: { type: 'category', data: rows.map(r => `${r.ix},${r.iy}`), axisLabel: { fontSize: 9, rotate: 40 } },
    yAxis: { type: 'value', name: 'm', nameTextStyle: { fontSize: 9 } },
    series: [{ type: 'bar', data: rows.map(r => Math.round(r.v)),
      itemStyle: { color: '#2a9fd8' }, barMaxWidth: 18 }],
    tooltip: { trigger: 'axis' },
  });
  chart.on('click', p => {
    const r = rows[p.dataIndex];
    map.fitBounds(state.gridLayer.getLayers()[0] ? state.gridLayer.getBounds() : bounds);
    toast(`网格 (${r.ix},${r.iy})：受灾路段 ${Math.round(r.v)} m，POI ${r.poi} 处`);
  });
  // 区域摘要
  const totalF = gj.features.reduce((s, f) => s + f.properties.flooded_road_m, 0);
  const totalP = gj.features.reduce((s, f) => s + f.properties.poi_cnt, 0);
  $('regionStat').innerHTML = `研究区网格数: <b>${gj.features.length}</b>（500m 渔网）<br>` +
    `淹没路段总长: <b>${fmt(totalF)}</b><br>设施点总数: <b>${totalP}</b><br>` +
    `受灾网格占比: <b>${(gj.features.filter(f => f.properties.flooded_road_m > 0).length / gj.features.length * 100).toFixed(1)}%</b>`;
};
$('statClose').onclick = () => $('statCard').classList.remove('show');

// ---------------- 地图点击（测距） ----------------
let measureLine = null;
map.on('click', async e => {
  if (state.tool === 'measure') {
    state.measurePts.push(e.latlng);
    if (state.measurePts.length === 2) {
      const [a, b] = state.measurePts;
      const d = map.distance(a, b);
      if (measureLine) map.removeLayer(measureLine);
      measureLine = L.polyline([a, b], { color: '#16a085', dashArray: '6 6' }).addTo(map);
      L.popup().setLatLng(b).setContent(`测量距离: <b>${fmt(d)}</b>`).openOn(map);
      state.measurePts = [];
    }
  }
});

// ---------------- 登录/注册 ----------------
let authMode = 'login';
function renderUser() {
  $('userbox').innerHTML = state.username
    ? `<span>👤 ${state.username}（${state.role === 'admin' ? '管理员' : '普通用户'}）</span>` +
      (state.role === 'admin' ? `<a href="/admin.html" target="_blank" style="color:#fff;font-size:13px;border:1px solid rgba(255,255,255,.4);border-radius:4px;padding:4px 12px;text-decoration:none">运维控制台</a><button id="btnUsers">用户管理</button>` : '') +
      `<button id="btnLogout">退出</button>`
    : `<button id="btnLogin">登录</button><button id="btnRegister">注册</button>`;
  if (state.username) {
    if (state.role === 'admin') $('btnUsers').onclick = showUsers;
    $('btnLogout').onclick = () => { state.token = state.role = state.username = null; renderUser(); toast('已退出登录'); };
  } else {
    $('btnLogin').onclick = () => openAuth('login');
    $('btnRegister').onclick = () => openAuth('register');
  }
}
function openAuth(mode) {
  authMode = mode;
  $('authTitle').textContent = mode === 'login' ? '用户登录' : '用户注册';
  $('authErr').textContent = '';
  $('authMask').classList.add('show');
}
$('authCancel').onclick = () => $('authMask').classList.remove('show');
$('authOk').onclick = async () => {
  try {
    const body = JSON.stringify({ username: $('authUser').value, password: $('authPwd').value });
    const r = await api(`/api/${authMode}`, { method: 'POST', body });
    if (authMode === 'login') {
      state.token = r.token; state.role = r.role; state.username = $('authUser').value;
      $('authMask').classList.remove('show'); renderUser();
      toast(`欢迎，${state.username}`);
    } else {
      $('authErr').style.color = '#27ae60'; $('authErr').textContent = '注册成功，请登录';
    }
  } catch (err) {
    $('authErr').style.color = '#c0392b'; $('authErr').textContent = err.message;
  }
};
async function showUsers() {
  try {
    const r = await apiQ('/api/users');
    L.popup().setLatLng(map.getCenter()).setContent(
      `<b>用户列表（${r.users.length}）</b><br>` +
      r.users.map(u => `${u.uid}. ${u.username} [${u.role}]`).join('<br>')).openOn(map);
  } catch (e) { toast(e.message); }
}
renderUser();

// ---------------- Tab 切换 ----------------
$('basemapSel').onchange = window.basemapSel_change;

document.querySelectorAll('.tab').forEach(t => t.onclick = () => {
  document.querySelectorAll('.tab').forEach(x => x.classList.remove('active'));
  document.querySelectorAll('.page').forEach(x => x.classList.remove('active'));
  t.classList.add('active');
  $('page-' + t.dataset.page).classList.add('active');
});

/* ---------------- IoT 感知一张图 + 四级预警（蓝黄橙红） ---------------- */
const ALERT_COLOR = { red:'#C0392B', orange:'#E67E22', yellow:'#F1C40F', blue:'#3498DB', none:'#95A5A6' };
const ALERT_NAME  = { red:'红色', orange:'橙色', yellow:'黄色', blue:'蓝色', none:'无' };
const sensorsLayer = L.layerGroup();
let sensorTimer = null;

function renderSensors() {
  fetch('/api/v1/sensors/live').then(r => r.json()).then(list => {
    sensorsLayer.clearLayers();
    list.forEach(st => {
      const c = ALERT_COLOR[st.alert] || ALERT_COLOR.none;
      const m = L.circleMarker([st.lat, st.lon], {
        radius: st.alert==='none' ? 6 : 9, color:'#fff', weight:1.5, fillColor:c, fillOpacity:.92 });
      m.bindPopup(`<b>${st.name}</b>（${st.type==='rain'?'雨量站':st.type==='water'?'水位站':'积水点'}）<br>` +
        `<span style="color:var(--muted);font-size:11px">数据源: ${st.source||'模拟'}</span><br>` +
        (st.water_m!=null ? `积水/水位: <b>${st.water_m} m</b><br>` : '') +
        (st.rain_1h!=null ? `1h 雨量: <b>${st.rain_1h} mm</b><br>` : '') +
        `站点预警: <b style="color:${c}">${ALERT_NAME[st.alert]}</b>`);
      sensorsLayer.addLayer(m);
    });
  });
  fetch('/api/v1/alerts/live').then(r => r.json()).then(a => {
    const b = document.getElementById('alertBanner');
    if (a.city_alert === 'none') { b.style.display='none'; return; }
    const c = ALERT_COLOR[a.city_alert];
    b.style.background = c; b.style.display = 'flex';
    document.getElementById('alertText').textContent =
      `福州市内涝${ALERT_NAME[a.city_alert]}预警 · ${a.triggered_stations.length} 个监测站超阈值` +
      `（首站：${a.triggered_stations[0].name}）`;
  });
}
$('lySensors').onchange = e => {
  if (e.target.checked) {
    map.addLayer(sensorsLayer); renderSensors();
    sensorTimer = setInterval(renderSensors, 5000);
    toast('感知站接入：雨量站=Open-Meteo 实时真实数据，5s 轮询');
  } else {
    map.removeLayer(sensorsLayer); clearInterval(sensorTimer);
    document.getElementById('alertBanner').style.display = 'none';
  }
};


/* ---------------- 空气质量插值面（Open-Meteo 真实，HJ633 国标分级） ---------------- */
let aqLayer = null;
const AQ_BBOX = [[25.35, 118.55], [26.75, 120.05]];
async function loadAQ() {
  const pol = $('aqPollutant').value;
  toast('空气质量网格采样 + IDW 插值中（真实数据）...');
  const gj = await fetch(`/api/v1/aq/grid?pollutant=${pol}&n=12&m=40`).then(r => r.json());
  if (aqLayer) map.removeLayer(aqLayer);
  document.getElementById('map').classList.add('aq-mode');
  document.getElementById('aqLegend').style.display = 'flex';
  aqLayer = L.geoJSON(gj.features.filter(f => f.geometry.type === 'Polygon'), {
    style: f => ({ color: '#ffffff33', weight: 0.3, fillColor: f.properties.color, fillOpacity: 0.7 }),
    onEachFeature: (f, l) => l.bindPopup(
      `<b>${f.properties.value} μg/m³</b>（${pol.toUpperCase()}）<br>等级: <b>${f.properties.level}</b><br>` +
      `<span style="font-size:11px;color:#63737F">${gj.meta.source}<br>采样 ${gj.meta.sampled_at} · 分级依据 ${gj.meta.standard}</span>`)
  }).addTo(map);
  const pts = L.geoJSON(gj.samples, {
    pointToLayer: (f, ll) => L.circleMarker(ll, { radius: 4, color: '#fff', weight: 1, fillOpacity: 1,
      fillColor: '#0D3B66' })
  });
  aqLayer.addLayer(pts);
  map.fitBounds(AQ_BBOX);
  toast('真实浓度插值面加载完成（HJ 633-2012 分级）');
}
$('lyAQ').onchange = e => {
  if (e.target.checked) { loadAQ(); } else if (aqLayer) { map.removeLayer(aqLayer); aqLayer = null; map.fitBounds(bounds); document.getElementById('map').classList.remove('aq-mode'); document.getElementById('aqLegend').style.display = 'none'; }
};
$('btnAQRefresh').onclick = () => { if ($('lyAQ').checked) loadAQ(); else toast('请先勾选空气质量图层'); };


/* ---------------- NASA GIBS 卫星气溶胶 AOD（真实卫星测量，逐日） ---------------- */
let gibsLayer = null;
$('lyGibs').onchange = e => {
  if (e.target.checked) {
    // AOD 日产品约 1 天延迟：取昨日日期；原生最高 z6（MODIS 1km），放大后重采样展示
    const d = new Date(Date.now() - 86400000).toISOString().slice(0, 10);
    gibsLayer = L.tileLayer(
      `https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/MODIS_Combined_Value_Added_AOD/default/${d}/GoogleMapsCompatible_Level6/{z}/{y}/{x}.png`,
      { maxNativeZoom: 6, maxZoom: 12, opacity: 0.75, tileSize: 256 });
    gibsLayer.addTo(map);
    toast(`NASA 卫星气溶胶 AOD 已叠加（${d}，真实卫星测量·逐日）`);
  } else if (gibsLayer) { map.removeLayer(gibsLayer); gibsLayer = null; }
};

/* ---------------- 实时降水雷达（RainViewer 真实数据，可播动画） ---------------- */
let radarLayers = [], radarFrames = [], radarIdx = 0, radarTimer = null;
const radarGroup = L.layerGroup();
$('lyRadar').onchange = async e => {
  if (e.target.checked) {
    const d = await fetch('/api/v1/radar/frames').then(r => r.json());
    radarFrames = d.frames || [];
    if (!radarFrames.length) { toast('雷达帧拉取失败'); return; }
    radarLayers = radarFrames.map(f => L.tileLayer(f.path, { opacity: 0 }));
    radarLayers.forEach(l => radarGroup.addLayer(l));
    map.addLayer(radarGroup);
    radarIdx = radarLayers.length - 1;
    radarTimer = setInterval(() => {
      radarLayers.forEach((l, i) => l.setOpacity(i === radarIdx ? 0.55 : 0));
      radarIdx = (radarIdx + 1) % radarLayers.length;
    }, 900);
    toast('实时降水雷达：' + radarFrames.length + ' 帧真实雷达回波，动画播放中');
  } else {
    map.removeLayer(radarGroup); clearInterval(radarTimer); radarLayers = [];
  }
};
