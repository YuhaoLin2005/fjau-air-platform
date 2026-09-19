/* 全局状态与事件总线 —— 全站唯一可变状态出口 */
export const state = {
  token: null, role: null, username: null,
  pollutant: 'pm2_5',          // 当前污染物（实时空气 / 时空分析共用）
  tool: null,                  // null | 'from' | 'to' | 'service' | 'measure' | 'ts-point'
  level: 10,                   // 洪水水位情景（一阶段成果）
  fromPt: null, toPt: null, servicePt: null, measurePts: [],
};

const handlers = {};
export function on(evt, fn) { (handlers[evt] = handlers[evt] || []).push(fn); }
export function emit(evt, data) { (handlers[evt] || []).forEach(fn => fn(data)); }

/* 竞态守卫工厂：每模块一个 makeSeq()，请求前取号，回来后比对 */
export function makeSeq() { let n = 0; return () => ++n; }
