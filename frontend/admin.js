/* 运维控制台逻辑：登录 → 五面板加载 → 5s 自刷新 */
'use strict';
const $ = id => document.getElementById(id);
let TOKEN = localStorage.getItem('admin_token') || '';

const ALERT_COLOR = { red:'#C0392B', orange:'#E67E22', yellow:'#F1C40F', blue:'#3498DB', none:'#95A5A6' };
const ALERT_NAME  = { red:'红色', orange:'橙色', yellow:'黄色', blue:'蓝色', none:'无预警' };

async function api(path, opt = {}) {
  const sep = path.includes('?') ? '&' : '?';
  const r = await fetch(path + sep + 'token=' + TOKEN, opt);
  if (!r.ok) {
    let msg = '请求失败';
    try { msg = (await r.json()).detail || msg; } catch (e) {}
    if (r.status === 403) { logout(); }
    throw new Error(msg);
  }
  return r.json();
}
async function text(path) {
  const r = await fetch(path);
  return r.text();
}

function tag(color, text) {
  return `<span class="tag" style="background:${color}">${text}</span>`;
}

async function loadHealth() {
  const d = await api('/health');
  const ok = d.status === 'ok' && d.db === 'up';
  $('healthDot').style.background = ok ? 'var(--ok)' : 'var(--hot)';
  $('healthBody').innerHTML = `
    <div class="kv"><span>整体状态</span><b>${ok ? '正常' : '降级'}</b></div>
    <div class="kv"><span>数据库</span><b>${d.db}</b></div>
    <div class="kv"><span>版本</span><b>v${d.version}</b></div>
    <div class="kv"><span>运行时长</span><b>${Math.floor(d.uptime_s / 60)} 分 ${d.uptime_s % 60} 秒</b></div>`;
}

async function loadAlerts() {
  const d = await api('/api/v1/alerts/current');
  const c = ALERT_COLOR[d.city_alert];
  $('alertBody').innerHTML = `
    <div class="kv"><span>城市级预警</span><b>${tag(c, ALERT_NAME[d.city_alert])}</b></div>
    <div class="kv"><span>触发站点</span><b>${d.triggered_stations.length} / ${d.station_count}</b></div>
    ${d.triggered_stations.slice(0, 4).map(s =>
      `<div class="kv"><span>${s.name}</span><b>${s.water_m != null ? s.water_m + ' m' : s.rain_1h + ' mm'}</b></div>`).join('')}
    <div style="color:var(--faint);font-size:var(--fs-xs);margin-top:6px">${d.note}</div>`;
}

async function loadMetrics() {
  const t = await text('/metrics');
  const lines = t.split('\n').filter(l => !l.startsWith('#') && l.trim());
  const want = ['flood_requests_total', 'flood_requests_error_total', 'flood_request_latency_avg_seconds',
                'flood_telemetry_total'];
  $('metricsBody').innerHTML = lines.filter(l => want.some(w => l.startsWith(w)))
    .map(l => { const [k, v] = l.split(' ');
      return `<div class="kv"><span>${k}</span><b>${(+v).toLocaleString()}</b></div>`; }).join('') ||
    '<div class="empty">暂无指标</div>';
}

async function loadSensors() {
  const list = await api('/api/v1/sensors/current');
  $('sensorTable').innerHTML = `
    <tr><th>站名</th><th>类型</th><th>积水/水位</th><th>1h雨量</th><th>站点预警</th><th>最新遥测时间</th></tr>` +
    list.map(s => `<tr>
      <td>${s.name}</td>
      <td>${s.type === 'rain' ? '雨量' : s.type === 'water' ? '水位' : '积水点'}</td>
      <td class="num">${s.water_m != null ? s.water_m + ' m' : '—'}</td>
      <td class="num">${s.rain_1h != null ? s.rain_1h + ' mm' : '—'}</td>
      <td>${tag(ALERT_COLOR[s.alert], ALERT_NAME[s.alert])}</td>
      <td class="num">${(s.ts || '').slice(5, 19)}</td></tr>`).join('');
}

async function loadUsers() {
  const d = await api('/api/v1/users');
  $('userTable').innerHTML = `
    <tr><th>UID</th><th>用户名</th><th>角色</th><th>创建时间</th><th></th></tr>` +
    d.users.map(u => `<tr>
      <td class="num">${u.uid}</td><td>${u.username}</td>
      <td>${u.role === 'admin' ? tag('var(--accent-strong)', '管理员') : tag('#8798A8', '用户')}</td>
      <td class="num">${String(u.created).slice(0, 16)}</td>
      <td>${u.username !== 'admin' ? `<button class="btn red" style="padding:2px 10px;font-size:var(--fs-xs)"
            onclick="delUser(${u.uid})">删除</button>` : ''}</td></tr>`).join('');
}

async function delUser(uid) {
  await api('/api/v1/users/' + uid, { method: 'DELETE' });
  loadUsers();
}

async function loadDataops() {
  const d = await api('/api/v1/meta/datasets');
  $('dataopsTable').innerHTML = `
    <tr><th>资产</th><th>来源</th><th>获取时间(UTC)</th><th>入库时间</th><th>规模</th><th>质量门</th></tr>` +
    d.datasets.map(x => {
      const q = x.quality || {};
      const gateVals = Object.values(q).filter(v => typeof v === 'object' && v !== null && 'pass' in v);
      const passed = gateVals.filter(v => v.pass).length;
      const gate = gateVals.length
        ? tag(passed === gateVals.length ? 'var(--ok)' : 'var(--hot)', `${passed}/${gateVals.length} 门`)
        : (Object.keys(q).length ? `<span style="color:var(--faint)">说明项</span>` : '—');
      return `<tr><td><b>${x.asset}</b></td><td>${x.source}</td>
        <td class="num">${x.fetched_at || '—'}</td><td class="num">${x.imported_at}</td>
        <td class="num">${x.rows}</td><td>${gate}</td></tr>`;
    }).join('');
}

async function loadSessions() {
  const d = await api('/api/v1/admin/sessions');
  $('sessionTable').innerHTML = `
    <tr><th>用户</th><th>角色</th><th>过期时间</th><th>剩余</th></tr>` +
    (d.sessions.map(s => `<tr>
      <td>${s.username}</td><td>${s.role}</td>
      <td class="num">${s.expires_at.slice(0, 19)}</td>
      <td class="num">${s.hours_left} h</td></tr>`).join('') || '<tr><td colspan="4" class="empty">无活跃会话</td></tr>');
}

function logout() {
  TOKEN = '';
  localStorage.removeItem('admin_token');
  $('loginMask').style.display = 'flex';
  $('app').style.display = 'none';
}

async function refreshAll() {
  const jobs = [['healthBody', loadHealth], ['alertBody', loadAlerts], ['metricsBody', loadMetrics],
                ['sensorTable', loadSensors], ['userTable', loadUsers], ['sessionTable', loadSessions],
                ['dataopsTable', loadDataops]];
  for (const [id, fn] of jobs) {
    try { await fn(); }
    catch (e) { if ($(id)) $(id).innerHTML = `<div class="empty">${e.message}</div>`; }
  }
}

$('loginBtn').onclick = async () => {
  try {
    const r = await fetch('/api/v1/login', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username: $('user').value, password: $('pwd').value }) });
    const d = await r.json();
    if (!r.ok) throw new Error(d.detail || '登录失败');
    if (d.role !== 'admin') { $('err').textContent = '需要管理员账号'; return; }
    TOKEN = d.token;
    localStorage.setItem('admin_token', TOKEN);
    $('loginMask').style.display = 'none';
    $('app').style.display = 'block';
    refreshAll();
  } catch (e) { $('err').textContent = e.message; }
};

(async () => {
  if (TOKEN) {
    // 校验既有 token
    try {
      await api('/api/v1/users');
      $('loginMask').style.display = 'none';
      $('app').style.display = 'block';
    } catch (e) { /* token 失效，停留登录页 */ }
  }
  if ($('app').style.display === 'block') refreshAll();
  setInterval(() => { if (TOKEN && $('app').style.display === 'block') refreshAll(); }, 5000);
})();
