/* 国控空气监测站实时图层（aqicn.org / WAQI 官方 API，真实数据）
   未配置 WAQI_TOKEN 时诚实引导（对齐天地图 KEY 插槽模式），不回退到模拟数据 */
import { api } from '../core/api.js';
import { toast } from '../ui/feedback.js';

let mapRef = null, layer = null;

export function initStations(map) { mapRef = map; }

export async function toggle(onOff) {
  if (!onOff) {
    if (layer) { mapRef.removeLayer(layer); layer = null; }
    return;
  }
  let d;
  try {
    d = await api('/aq/stations/live');
  } catch (e) {
    toast('监测站拉取失败：' + e.message);
    return;
  }
  if (!d.available) {
    toast(d.reason || '数据源不可用', 5000);
    const ly = document.getElementById('lyStations');
    if (ly) ly.checked = false;
    return;
  }
  if (layer) { mapRef.removeLayer(layer); layer = null; }
  layer = L.layerGroup(d.stations.map(st =>
    L.circleMarker([st.lat, st.lon], {
      radius: 9, color: '#fff', weight: 2, fillOpacity: .95, fillColor: st.color
    }).bindPopup(
      `<b>${st.name}</b><br>实时 AQI: <b>${st.aqi ?? '—'}</b>（${st.level}）<br>` +
      `<span style="color:#7A6F62;font-size:11px">数据源: aqicn.org（WAQI 官方 API · 真实监测站）<br>` +
      `更新: ${st.time || d.fetched_at || ''} · 等级按 HJ 633-2012 映射展示</span>`)
  )).addTo(mapRef);
  toast(`国控空气监测站已接入：${d.stations.length} 站实时 AQI（aqicn.org 真实数据）`);
}
