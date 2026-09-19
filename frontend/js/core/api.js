/* 统一 HTTP 口径：/api/v1 前缀常量 + query token 单点注入 + 401 引导 + seq 守卫 */
import { state } from './store.js';
import { toast, showPermBar } from '../ui/feedback.js';

export const API = '/api/v1';

export async function api(path, opt = {}) {
  const { public: isPublic = false, ...rest } = opt;
  rest.headers = { 'Content-Type': 'application/json', ...(rest.headers || {}) };
  let url = path.startsWith('/api') ? path : API + path;
  if (state.token) url += (url.includes('?') ? '&' : '?') + 'token=' + state.token;
  const r = await fetch(url, rest);
  if (r.status === 401) {
    if (!isPublic) { showPermBar(); }
    throw new Error('请先登录');
  }
  if (!r.ok) {
    let msg = `请求失败（${r.status}）`;
    try { msg = (await r.json()).detail || msg; } catch (e) { /* 非 JSON 错误体 */ }
    throw new Error(msg);
  }
  return r.json();
}

/* 裸 JSON 获取（公开端点不需要登录引导时也可用，统一错误解析） */
export async function getJSON(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`请求失败（${r.status}）`);
  return r.json();
}
