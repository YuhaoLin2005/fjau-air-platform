/* 页签：实时空气 —— 首屏即答（现状卡）+ 污染物切换 + 点哪查哪 + POI 检索 */
import { state, emit } from '../core/store.js';
import { api } from '../core/api.js';
import { toast, skelHTML } from '../ui/feedback.js';
import * as aq from '../layers/aq.js';
import { AQ_LEVELS, AQ_COLORS, AQ_NAMES, AQ_LIMITS, AQ_ADVICE, levelIndex } from '../core/aqmeta.js';

const $ = id => document.getElementById(id);
export const FUZHOU_CENTER = [26.0745, 119.2965];

/* 现状卡：4 污染物并行取最差等级者为主污染物；部分失败降级为仅当前污染物 */
export async function loadStatusCard() {
  const card = $('statusBody');
  card.innerHTML = skelHTML(4);
  const polys = ['pm2_5', 'pm10', 'ozone', 'nitrogen_dioxide'];
  const results = await Promise.allSettled(polys.map(p => aq.loadGrid(p)));
  const ok = results.map((r, i) => ({ p: polys[i], gj: r.status === 'fulfilled' ? r.value : null })).filter(x => x.gj);
  if (!ok.length) {
    card.innerHTML = `<div class="empty">空气质量数据加载失败<span style="display:block;font-size:12px;color:var(--faint)">后端或外网不可用，稍后自动重试</span></div>`;
    setTimeout(loadStatusCard, 30000);
    return;
  }
  const partial = ok.length < polys.length;
  let worst = ok[0], worstLv = -1;
  ok.forEach(x => {
    const lv = levelIndex(aq.worstLevel(x.gj));
    if (lv > worstLv) { worst = x; worstLv = lv; }
  });
  const dist = aq.distribution(worst.gj);
  const total = Object.values(dist).reduce((s, n) => s + n, 0);
  const wLevel = aq.worstLevel(worst.gj);
  card.innerHTML =
    `<div class="status-main"><span class="aq-badge" style="background:${AQ_COLORS[wLevel]}">${wLevel}</span>` +
    `<span class="status-title">福州现在空气质量</span></div>` +
    `<div class="status-sub">主污染物: <b>${AQ_NAMES[worst.p]}</b>${partial ? '（部分污染物源暂不可用，已降级）' : ''}</div>` +
    `<div class="dist-bar">${AQ_LEVELS.map(lv => dist[lv] ? `<span style="flex:${dist[lv]};background:${AQ_COLORS[lv]}" title="${lv} ${dist[lv]} 格"></span>` : '').join('')}</div>` +
    `<div class="status-advice">${AQ_ADVICE[wLevel] || ''}</div>` +
    `<div class="status-src">Open-Meteo（CAMS 同化）· 采样 ${worst.gj.meta.sampled_at} · HJ 633-2012</div>`;
  card.classList.remove('is-loading');
}

/* 污染物切换：重画插值面 + 图例 + 现状卡污染源徽标 */
export async function switchPollutant(p) {
  state.pollutant = p;
  $('tsPollutant').value = p;
  if ($('lyAQ').checked) await aq.show(p);
  emit('pollutant');
}

export function initLive(map, modules) {
  // 图层开关
  $('lyAQ').onchange = async e => {
    if (e.target.checked) await aq.show(state.pollutant);
    else aq.remove();
    map.setView([26.05, 119.30], 10);
    emit('layers');
  };
  $('lySamples').onchange = e => aq.setSamples(e.target.checked);
  $('lyRadar').onchange = e => modules.radar.toggle(e.target.checked);
$('lyGibs').onchange = e => modules.gibs.toggle(e.target.checked);
  $('lySensors').onchange = e => modules.sensors.toggle(e.target.checked);
  $('lyStations').onchange = e => modules.stations.toggle(e.target.checked);
  $('aqPollutant').onchange = e => switchPollutant(e.target.value);
  $('btnAQRefresh').onclick = async () => {
    aq.invalidateCache(state.pollutant);
    aq.invalidateCache();                        // 现状卡主污染物口径同步失效
    if ($('lyAQ').checked) await aq.show(state.pollutant);
    loadStatusCard();
  };

  // 点哪查哪：与测距/选点工具互斥（state.tool 非 null 时不接管）
  map.on('click', e => {
    if (state.tool || !$('lyAQ').checked) return;
    const f = aq.queryAt(e.latlng);
    if (!f) {
      if (e.latlng.lat < 25.35 || e.latlng.lat > 26.75 || e.latlng.lng < 118.55 || e.latlng.lng > 120.05)
        toast('该位置在福州市域插值范围外（118.55-120.05°E, 25.35-26.75°N）');
      return;
    }
    const p = f.properties;
    L.popup().setLatLng(e.latlng).setContent(
      `<b>${p.value} μg/m³</b>（${AQ_NAMES[state.pollutant]}）<br>等级: <b>${p.level}</b>` +
      `<div style="max-width:220px;font-size:12px;color:#7A6F62;margin-top:4px">${AQ_ADVICE[p.level] || ''}</div>` +
      `<div style="font-size:11px;color:#A99C8C;margin-top:4px">数据源与采样时间见插值面 meta</div>`).openOn(map);
  });

  // POI 检索（结果卡附该点 AQ 值与等级）
  $('btnPoiSearch').onclick = async () => {
    const kw = $('poiKw').value.trim();
    if (!kw) return toast('请输入关键字');
    try {
      const r = await api(`/poi/search?kw=${encodeURIComponent(kw)}`);
      $('poiResult').innerHTML = r.results.length
        ? r.results.map(x => `▸ ${x.name}（${x.category}）`).join('<br>') : '未找到匹配设施';
      if (r.results.length) {
        const first = r.results[0];
        map.setView([first.lat, first.lon], 15);
        const f = aq.queryAt(L.latLng(first.lat, first.lon));
        const aqTxt = f ? `空气质量: <b>${f.properties.value} μg/m³（${f.properties.level}）</b><br>` : '';
        L.popup().setLatLng([first.lat, first.lon]).setContent(
          `<b>${first.name}</b><br>${aqTxt}<span style="font-size:11px;color:#A99C8C">${first.category}</span>`).openOn(map);
      }
    } catch (e) { toast(e.message); }
  };
}
