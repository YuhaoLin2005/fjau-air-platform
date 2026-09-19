/* 洪水淹没图层（一阶段成果）：默认关闭、按需加载；/flood/levels 静态数据缓存 */
import { api } from '../core/api.js';

let levelsCache = null;

export function initFlood(map) {
  const layer = L.geoJSON(null, { style: { color: '#1a6fa8', weight: 1, fillColor: '#2a9fd8', fillOpacity: 0.45 } });

  async function load(level) {
    const gj = await api(`/flood/geojson?level=${level}`);
    layer.clearLayers(); layer.addData(gj);
  }
  async function toggle(onOff, level) {
    if (!onOff) { map.removeLayer(layer); return; }
    await load(level);
    map.addLayer(layer);
  }
  /* 水位-面积关系是不变量：拉一次查表，不再逐 tick 重取 */
  async function levels() {
    if (!levelsCache) levelsCache = (await api('/flood/levels')).levels;
    return levelsCache;
  }
  return { toggle, load, levels, get layer() { return layer; } };
}
