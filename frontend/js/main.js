/* 入口：装配地图与全部模块、页签切换、三角色门禁、首屏叙事（AQ 面默认开 + 市域视野） */
import { state, emit } from './core/store.js';
import { initRoads } from './layers/roads.js';
import { initPois } from './layers/pois.js';
import { initFlood } from './layers/flood.js';
import { initAQ, show as aqShow, loadGrid } from './layers/aq.js';
import { initRadar, toggle as radarToggle } from './layers/radar.js';
import { initGibs, toggle as gibsToggle } from './layers/gibs.js';
import { initSensors, toggle as sensorsToggle } from './layers/sensors.js';
import { initStations, toggle as stationsToggle } from './layers/stations.js';
import { initBasemaps } from './layers/basemap.js';
import { initAuth, applyPerms } from './ui/auth.js';
import { showAQ, showFlood, hide as hideLegend } from './ui/legend.js';
import { initLive, loadStatusCard } from './pages/live.js';
import { initTimeseries, load as tsLoad } from './pages/timeseries.js';
import { initExposure } from './pages/exposure.js';
import { initLegacy } from './pages/legacy.js';
import { on } from './core/store.js';

const $ = id => document.getElementById(id);
const map = L.map('map', { zoomControl: false, attributionControl: false, minZoom: 8 });
/* 定焦 z10：市域 z10 瓦片 30 张全覆盖；fitBounds 在窄视口会落到 z9（仅 9 张）打穿缓存 */
map.setView([26.05, 119.30], 10);
L.control.zoom({ position: 'bottomright' }).addTo(map);
window.__map = map;                                   // E2E 受控出口（配 test_e2e）

const modules = {
  roads: initRoads(map),
  pois: initPois(map),
  flood: initFlood(map),
  radar: { toggle: radarToggle },
  gibs: { toggle: gibsToggle },
  sensors: { toggle: sensorsToggle },
  stations: { toggle: stationsToggle },
};
initRadar(map);
  initGibs(map); initSensors(map); initStations(map); initAQ(map);

initBasemaps(map);
initAuth();
initLive(map, modules);
initTimeseries(map);
initExposure(map);
initLegacy(map, modules);

/* 页签切换（含一阶段成果¹ 子页导航） */
document.querySelectorAll('.tab').forEach(t => t.onclick = () => {
  document.querySelectorAll('.tab').forEach(x => x.classList.remove('active'));
  document.querySelectorAll('.page').forEach(x => x.classList.remove('active'));
  t.classList.add('active');
  $('page-' + t.dataset.page).classList.add('active');
  if (t.dataset.page === 'time') tsLoad();
  if (t.dataset.page === 'legacy') showFlood(); else if (!$('lyAQ').checked) hideLegend(); else showAQ();
});

document.querySelectorAll('.legacy-nav .btn').forEach(b => b.onclick = () => {
  document.querySelectorAll('.legacy-nav .btn').forEach(x => x.classList.remove('active'));
  document.querySelectorAll('.legacy-page').forEach(x => x.classList.remove('active'));
  b.classList.add('active');
  $('lp-' + b.dataset.lp).classList.add('active');
});

/* 登录态变化 → 重算门禁；退出后 AQ 公开功能不受影响 */
on('auth', () => { applyPerms(); });

/* 首屏叙事：AQ 面默认开启 + 现状卡，0 点击回答"现在福州空气如何" */
(async () => {
  $('lyAQ').checked = true;
  try {
    await Promise.all([aqShow('pm2_5'), loadStatusCard()]);
  } catch (e) { /* show/status 内部已有错误态 */ }
  showAQ();
  applyPerms();
})();

/* 移动端底部抽屉 */
$('drawerToggle').onclick = () => {
  const col = $('leftCol');
  col.classList.toggle('drawer-open');
  $('drawerToggle').textContent = col.classList.contains('drawer-open') ? '▼ 功能面板' : '▲ 功能面板';
};

/* 测试受控出口（test_e2e 用，业务代码不依赖） */
window.__app = { state, map, modules };
