/* 单一动态图例组件：随主图层切换内容（AQI 六级 / 洪水 / 隐藏），替代旧版三处分裂图例 */
import { AQ_LEVELS, AQ_COLORS, AQ_NAMES, rangeText } from '../core/aqmeta.js';
import { state, emit } from '../core/store.js';

export function showAQ() {
  const el = document.getElementById('legendBox');
  el.style.display = 'block';
  el.innerHTML = `<b>AQI 分级 · ${AQ_NAMES[state.pollutant]}（μg/m³）</b>` +
    `<span class="lg-src">HJ 633-2012 · Open-Meteo 实时</span>` +
    AQ_LEVELS.map((lv, i) =>
      `<div class="lg-row" data-level="${lv}"><span class="lg-swatch" style="background:${AQ_COLORS[lv]}"></span>${lv}` +
      `<span class="lg-range">${rangeText(state.pollutant, i)}</span></div>`).join('') +
    `<div class="lg-tip">点地图任意处查询该处浓度与建议</div>`;
  // hover 反向联动：高亮该等级网格
  el.querySelectorAll('.lg-row').forEach(row => {
    row.onmouseenter = () => emit('aq:highlight', row.dataset.level);
    row.onmouseleave = () => emit('aq:highlight', null);
  });
}

export function showFlood() {
  const el = document.getElementById('legendBox');
  el.style.display = 'block';
  el.innerHTML = `<b>一阶段成果¹ · 洪涝图例</b>
    <div class="lg-row"><span class="lg-swatch" style="background:#2a9fd8"></span>内涝淹没范围</div>
    <div class="lg-row"><span class="lg-swatch" style="background:#e74c3c"></span>疏散/救援路径</div>
    <div class="lg-row"><span class="lg-swatch" style="background:#27ae60"></span>安全避难点</div>
    <div class="lg-row"><span class="lg-swatch" style="background:#f39c12"></span>受威胁避难点</div>
    <div class="lg-row"><span class="lg-swatch" style="background:#8e6fc1"></span>服务区</div>`;
}

export function hide() { document.getElementById('legendBox').style.display = 'none'; }

export function refresh() {
  const aqOn = document.getElementById('lyAQ')?.checked;
  const floodOn = document.getElementById('lyFlood')?.checked || document.getElementById('page-legacy').querySelector('.legacy-page.active') != null;
  if (aqOn) showAQ();
  else if (floodOn) showFlood();
  else hide();
}
