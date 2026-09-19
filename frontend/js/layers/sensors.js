/* 实时雨量站（Open-Meteo 真实数据）。
   数据源纪律（2026-09-19 用户裁决）：模拟数据一律不上屏——
   sensors 表中的水位/积水站为 simulate_sensors 合成（无免费公开实时源），已过滤；
   内涝预警横幅由模拟水位规则引擎驱动，已随之下屏。
   雨量读数真实，但站点坐标为易涝点示意布设，popup 明示口径。 */
import { api } from '../core/api.js';

let mapRef = null, layer = null, timer = null;

export function initSensors(map) { mapRef = map; }

async function render() {
  try {
    const list = await api('/sensors/live');
    const rain = list.filter(st => st.type === 'rain' && st.rain_1h != null);
    layer.clearLayers();
    rain.forEach(st => {
      const m = L.circleMarker([st.lat, st.lon], {
        radius: 8, color: '#fff', weight: 1.5,
        fillColor: st.rain_1h > 0 ? '#2874A6' : '#85A3B8', fillOpacity: .92 });
      m.bindPopup(`<b>${st.name}</b>（实时雨量站）<br>1h 雨量: <b>${st.rain_1h} mm</b><br>` +
        `<span style="color:#7A6F62;font-size:11px">数据源: Open-Meteo 实时（真实）<br>站点位置为易涝点示意布设，非实体雨量计</span>`);
      layer.addLayer(m);
    });
    if (!rain.length) layer.clearLayers();
  } catch (e) {
    stopPolling();                                  // 401/网络失败后停止空转轮询
  }
}

function stopPolling() { if (timer) { clearInterval(timer); timer = null; } }

export function toggle(onOff) {
  if (!onOff) {
    stopPolling();
    if (layer) { mapRef.removeLayer(layer); layer = null; }
    return;
  }
  if (!layer) layer = L.layerGroup().addTo(mapRef);
  render();
  timer = setInterval(render, 5000);
}
