/* POI 图层：AQ 模式默认关闭、按需加载 */
import { api } from '../core/api.js';

const poiIcons = {
  park: '🌳', school: '🏫', hospital: '🏥', stadium: '🏟️', sports_centre: '🏊',
  community_centre: '🏘️', pitch: '⚽', place_of_worship: '⛩️', assembly_point: '🚩', driving_school: '🚗',
};

let loaded = false;

export function initPois(map) {
  const layer = L.geoJSON(null, {
    pointToLayer: (f, latlng) => L.marker(latlng, {
      icon: L.divIcon({ html: `<div style="font-size:17px;line-height:17px">${poiIcons[f.properties.category] || '📍'}</div>`, className: '', iconSize: [17, 17] })
    }),
    onEachFeature: (f, l) => l.bindPopup(`<b>${f.properties.name || '未命名设施'}</b><br>类别: ${f.properties.category}`)
  });

  async function toggle(onOff) {
    if (!onOff) { map.removeLayer(layer); return; }
    if (!loaded) {
      const gj = await api('/layers/pois');
      layer.clearLayers(); layer.addData(gj); loaded = true;
    }
    map.addLayer(layer);
  }
  return { toggle, get loaded() { return loaded; }, get layer() { return layer; } };
}
