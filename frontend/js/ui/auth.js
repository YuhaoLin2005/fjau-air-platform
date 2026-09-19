/* 登录/注册 + 用户管理（模态，替代旧版地图 popup 容器）+ 三角色门禁 */
import { state, emit } from '../core/store.js';
import { api } from '../core/api.js';
import { toast } from './feedback.js';

const $ = id => document.getElementById(id);
let authMode = 'login';

export function openAuth(mode = 'login') {
  authMode = mode;
  $('authTitle').textContent = mode === 'login' ? '用户登录' : '用户注册';
  $('authErr').textContent = '';
  $('authMask').classList.add('show');
}

export function renderUser() {
  const box = $('userbox');
  if (!state.username) {
    box.innerHTML = `<button class="tb-btn" id="btnLogin">登录</button><button class="tb-btn" id="btnRegister">注册</button>`;
    $('btnLogin').onclick = () => openAuth('login');
    $('btnRegister').onclick = () => openAuth('register');
  } else {
    box.innerHTML = `<span>👤 ${state.username}（${state.role === 'admin' ? '管理员' : '普通用户'}）</span>` +
      (state.role === 'admin' ? `<a class="tb-btn" href="/admin.html" target="_blank">运维控制台</a><button class="tb-btn" id="btnUsers">用户管理</button>` : '') +
      `<button class="tb-btn" id="btnLogout">退出</button>`;
    if (state.role === 'admin') $('btnUsers').onclick = showUsers;
    $('btnLogout').onclick = () => {
      state.token = state.role = state.username = null;
      renderUser(); emit('auth'); toast('已退出登录');
    };
  }
  emit('auth');
}

/* 三角色门禁：登录态已知即前置可见，不再"点了才被 401 拦截" */
function applyPerms() {
  const level = state.role === 'admin' ? 2 : state.role === 'user' ? 1 : 0;
  document.querySelectorAll('[data-requires]').forEach(el => {
    const need = +el.dataset.requires;
    const locked = level < need;
    el.classList.toggle('locked', locked);
    el.disabled = locked;
    if (locked) el.title = '登录后可用';
  });
}
export { applyPerms };

export function initAuth() {
  $('authCancel').onclick = () => $('authMask').classList.remove('show');
  $('authOk').onclick = async () => {
    try {
      const body = JSON.stringify({ username: $('authUser').value, password: $('authPwd').value });
      const r = await api(`/${authMode}`, { method: 'POST', body });
      if (authMode === 'login') {
        state.token = r.token; state.role = r.role; state.username = $('authUser').value;
        $('authMask').classList.remove('show'); renderUser();
        toast(`欢迎，${state.username}`);
      } else {
        $('authErr').style.color = '#2E7D52'; $('authErr').textContent = '注册成功，请登录';
      }
    } catch (err) {
      $('authErr').style.color = '#C0392B'; $('authErr').textContent = err.message;
    }
  };
  $('permLogin').onclick = () => openAuth('login');
  $('permClose').onclick = () => $('permBar').style.display = 'none';
  $('userModalClose').onclick = () => $('userMask').classList.remove('show');
  renderUser();
  applyPerms();
}

async function showUsers() {
  $('userMask').classList.add('show');
  const tb = $('userTable');
  try {
    const r = await api('/users');
    tb.innerHTML = `<tr><th>UID</th><th>用户名</th><th>角色</th><th></th></tr>` +
      r.users.map(u => `<tr><td>${u.uid}</td><td>${u.username}</td><td>${u.role}</td>` +
        `<td>${u.username === 'admin' ? '' : `<button class="btn btn-red btn-sm" data-uid="${u.uid}">删除</button>`}</td></tr>`).join('');
    tb.querySelectorAll('button[data-uid]').forEach(b => b.onclick = async () => {
      try { await api(`/users/${b.dataset.uid}`, { method: 'DELETE' }); toast('已删除'); showUsers(); }
      catch (e) { toast(e.message); }
    });
  } catch (e) {
    tb.innerHTML = `<tr><td>${e.message}</td></tr>`;
  }
}
