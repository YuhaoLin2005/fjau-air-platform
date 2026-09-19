/* 轻量反馈件：toast / 权限提示条 / 骨架屏，避免 ui/auth ↔ api 循环依赖单独拆出 */
const $ = id => document.getElementById(id);

export function toast(msg, ms = 2600) {
  const t = $('toast'); t.textContent = msg; t.style.display = 'block';
  clearTimeout(t._h); t._h = setTimeout(() => t.style.display = 'none', ms);
}

/* 401 非模态提示条：替代旧版"点击后被模态弹窗拦截" */
export function showPermBar() {
  const bar = $('permBar');
  bar.style.display = 'flex';
  clearTimeout(bar._h); bar._h = setTimeout(() => bar.style.display = 'none', 6000);
}

/* 三态之一：骨架屏。sel 为容器选择器，on=true 显示骨架 */
export function skeleton(el, on) {
  el.classList.toggle('is-loading', on);
}

/* 生成骨架占位 HTML（容器内复用） */
export function skelHTML(rows = 3) {
  return Array.from({ length: rows }, () => '<div class="skel-line"></div>').join('');
}
