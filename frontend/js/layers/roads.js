/* 路网图层：canvas 渲染（5451 条 way 的最大单项性能收益）+ AQ/洪涝双模式样式 */
import { api } from '../core/api.js';
import { toast } from '../ui/feedback.js';

const roadStyleLegacy = hw => ({
  color: { motorway: '#8c4a2f', trunk: '#a05a2c', primary: '#c96a2b', secondary: '#d9902a', tertiary: '#c9b56e' }[hw] || '#9aa5ad',
  weight: { motorway: 4, trunk: 4, primary: 3.5, secondary: 3, tertiary: 2.5 }[hw] || 1.6,
});
/* AQ 主叙事下路网降为中性灰细线，不再与 AQI 暖色带同域竞争 */
const roadStyleNeutral = () => ({ color: '#8f9aa5', weight: 1, opacity: 0.55 });

let loaded = false, mode = 'aq';

export function initRoads(map) {
  const layer = L.geoJSON(null, { renderer: L.canvas(), style: f => mode === 'aq' ? roadStyleNeutral() : roadStyleLegacy(f.properties.highway) });
  layer.on('click', e => {
    const p = e.layer.feature.properties;
    L.popup().setLatLng(e.latlng).setContent(
      `<b>${p.name || '无名道路'}</b><br>类型: ${p.highway}<br>gid: ${p.gid}`).openOn(map);
  });

  async function ensureLoaded() {
    if (loaded) return;
    toast('路网加载中...');
    const gj = await api('/layers/roads');
    layer.clearLayers(); layer.addData(gj); loaded = true;
    toast(`路网加载完成：${gj.features.length} 条路段`);
  }

  async function toggle(on) {
    if (!on) { map.removeLayer(layer); return; }
    await ensureLoaded();
    map.addLayer(layer);
  }

  function setMode(m) {
    mode = m;
    layer.setStyle(f => mode === 'aq' ? roadStyleNeutral() : roadStyleLegacy(f.properties.highway));
  }
  return { toggle, setMode, get loaded() { return loaded; } };
}
