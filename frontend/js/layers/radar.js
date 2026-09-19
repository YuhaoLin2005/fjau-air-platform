/* 实时降水雷达（RainViewer 真实帧）：gen 序号守卫修旧版两条定时器泄漏路径 */
import { getJSON } from '../core/api.js';
import { toast } from '../ui/feedback.js';

let mapRef = null, group = null, timer = null, gen = 0;

export function initRadar(map) { mapRef = map; }

export async function toggle(onOff) {
  const my = ++gen;
  if (!onOff) { stop(); return; }
  try {
    const d = await getJSON('/api/v1/radar/frames');
    if (my !== gen) return;                       // 期间被取消，丢弃
    const frames = d.frames || [];
    if (!frames.length) { toast('雷达帧拉取失败'); return; }
    stop();
    group = L.layerGroup(frames.map(f => L.tileLayer(f.path, { opacity: 0 })));
    const layers = group.getLayers();
    mapRef.addLayer(group);
    let idx = layers.length - 1;
    timer = setInterval(() => {
      layers.forEach((l, i) => l.setOpacity(i === idx ? 0.55 : 0));
      idx = (idx + 1) % layers.length;
    }, 900);
    toast('实时降水雷达已接入（RainViewer 真实回波）：当前福州市域无降水则显示为空，非故障');
  } catch (e) {
    if (my === gen) toast('雷达拉取失败：' + e.message);
  }
}

function stop() {
  if (timer) { clearInterval(timer); timer = null; }   // 幂等：重设前必清
  if (group) { mapRef.removeLayer(group); group = null; }
}
