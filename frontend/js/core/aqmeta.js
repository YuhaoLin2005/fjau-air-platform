/* HJ 633-2012 分级元数据（前端镜像常量）
   色值逐值镜像后端 airquality.py LEVEL_COLOR；限值镜像 airquality.py aq_level —— 实现验证门含逐值对照 */
export const AQ_LEVELS = ['优', '良', '轻度', '中度', '重度', '严重'];
export const AQ_COLORS = { '优': '#2E7D52', '良': '#C9A227', '轻度': '#E67E22', '中度': '#C0392B', '重度': '#8E2A3C', '严重': '#5B1220', '—': '#95A5A6' };
export const AQ_LIMITS = {          // μg/m³，各级上限（末级 1e9 由 aq_level 处理）
  pm2_5: [35, 75, 115, 150, 250],
  pm10: [50, 150, 250, 350, 420],
  ozone: [160, 200, 300, 400, 800],
  nitrogen_dioxide: [100, 200, 700, 1200, 2340],
};
export const AQ_NAMES = { pm2_5: 'PM2.5', pm10: 'PM10', ozone: 'O₃', nitrogen_dioxide: 'NO₂' };

/* 依据 HJ 633-2012 的分级健康指引（国标文字口径） */
export const AQ_ADVICE = {
  '优': '空气质量令人满意，基本无空气污染，各类人群可正常活动。',
  '良': '空气质量可接受，极少数异常敏感人群应减少户外活动。',
  '轻度': '儿童、老年人及心脏病、呼吸系统疾病患者应减少长时间户外锻炼。',
  '中度': '疾病患者避免长时间高强度户外锻炼，一般人群适量减少户外活动。',
  '重度': '儿童、老人及病患者应停止户外活动，一般人群避免户外活动。',
  '严重': '所有人群应避免户外活动，关闭门窗，有条件者开启空气净化。',
};

export function levelIndex(level) { return AQ_LEVELS.indexOf(level); }

export function levelOf(pollutant, v) {
  const th = AQ_LIMITS[pollutant];
  if (!th || v == null) return '—';
  for (let i = 0; i < th.length; i++) if (v < th[i]) return AQ_LEVELS[i];
  return '严重';
}

export function rangeText(pollutant, i) {
  const th = AQ_LIMITS[pollutant] || [];
  const lo = i === 0 ? 0 : th[i - 1], hi = th[i];
  return `${lo}–${hi ?? '+'}`;
}
