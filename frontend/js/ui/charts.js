/* ECharts 实例管理：同 dom 复用，切页隐藏即销毁（修旧版重复 init 泄漏）。
   echarts 以经典 <script> 全局加载（lib/echarts.min.js），此处取 window 全局而非裸导入 */
const echarts = window.echarts;

const registry = new Map();   // dom -> chart

export function getChart(dom) {
  let c = echarts.getInstanceByDom(dom);
  if (c) { c.dispose(); }
  c = echarts.init(dom);
  registry.set(dom, c);
  return c;
}

export function disposeAll() {
  registry.forEach(c => { try { c.dispose(); } catch (e) { /* dom 已移除 */ } });
  registry.clear();
}
