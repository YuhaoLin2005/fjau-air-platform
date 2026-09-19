/* 底图切换器：本地瓦片（市域 z8-13 / 金山 z14-16）/ OSM 在线 / 天地图插槽 */
import { toast } from '../ui/feedback.js';

export const AQ_BBOX = [[25.35, 118.55], [26.75, 120.05]];   // 福州市域（FACTS.md）
export const LEGACY_BBOX = [[26.03, 119.19], [26.10, 119.30]]; // 一阶段金山片区

export function initBasemaps(map) {
  let TDT_KEY = '';
  fetch('/api/v1/meta/config').then(r => r.json()).then(c => { TDT_KEY = c.tdt_key || ''; })
    .catch(() => {});   // 配置拉取失败只影响天地图项，不阻塞主流程

  const makers = {
    // 市域视角需 z8-10（已核实瓦片齐备），旧金山视角沿用 z11-16
    local: () => L.tileLayer('/tiles/{z}/{x}/{y}.png', { minZoom: 8, maxZoom: 16 }),
    osm: () => L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',
      { minZoom: 8, maxZoom: 19, attribution: '© OpenStreetMap contributors' }),
    tianditu: () => {
      if (!TDT_KEY) { toast('天地图未配置 KEY：在 backend/.env 加 TDT_KEY 后重启'); return null; }
      const tdt = layer => L.tileLayer(
        `https://t{s}.tianditu.gov.cn/${layer}/wmts?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0` +
        `&LAYER=${layer}&STYLE=default&TILEMATRIXSET=w&FORMAT=tiles&TILEMATRIX={z}&TILEROW={y}&TILECOL={x}&tk=${TDT_KEY}`,
        { subdomains: ['0', '1', '2', '3', '4', '5', '6', '7'], minZoom: 8, maxZoom: 18 });
      const vec = tdt('vec_w'), cva = tdt('cva_w');
      vec.on('add', () => cva.addTo(map)); vec.on('remove', () => map.removeLayer(cva));
      return vec;
    },
  };

  let current = makers.local().addTo(map);
  document.getElementById('basemapSel').onchange = e => {
    const mk = makers[e.target.value] && makers[e.target.value]();
    if (!mk) { e.target.value = 'local'; return; }
    map.removeLayer(current); current = mk.addTo(map);
  };
  return { get current() { return current; } };
}
