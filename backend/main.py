# -*- coding: utf-8 -*-
"""福州市暴雨内涝应急疏散与救援路径分析系统 —— v2 工业级架构入口
分层：core(配置/池/安全/日志) → services(业务) → api(路由) → main(装配)
启动: uvicorn main:app --host 0.0.0.0 --port 8000
文档: http://127.0.0.1:8000/docs (OpenAPI/Swagger)
标准: OGC API - Features @ /ogc
"""
import os, sys, io, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from pydantic import BaseModel

from core import (SETTINGS, init_pool, get_conn, query, log, metric_incr,
                  metric_latency, metrics_text, START_TIME, TTLCache)
import services as svc
import ogc

BASE = os.path.dirname(os.path.abspath(__file__))

app = FastAPI(
    title='福州市暴雨内涝应急疏散与救援路径分析系统',
    description='WebGIS + PostGIS/pgRouting 空间分析服务 · OGC API - Features · IoT 感知与四级预警',
    version=SETTINGS.APP_VERSION,
    docs_url='/docs', openapi_url='/openapi.json')
app.add_middleware(CORSMiddleware, allow_origins=['*'], allow_methods=['*'], allow_headers=['*'])
app.add_middleware(GZipMiddleware, minimum_size=1024)

layer_cache = TTLCache(600)   # 路网/POI 静态图层 10 分钟
flood_cache = TTLCache(300)


@app.middleware('http')
async def metrics_middleware(request: Request, call_next):
    t0 = time.perf_counter()
    try:
        resp = await call_next(request)
    except Exception:
        metric_incr('flood_requests_error_total')
        raise
    dt = time.perf_counter() - t0
    metric_incr('flood_requests_total')
    metric_incr(f'flood_requests_status_{resp.status_code}')
    metric_latency(dt)
    resp.headers['X-Response-Time-ms'] = f'{dt * 1000:.1f}'
    return resp


class UserIn(BaseModel):
    username: str
    password: str


class TelemetryIn(BaseModel):
    sid: int
    water_m: float = None
    rain_1h: float = None


def err(e: Exception, code=400):
    raise HTTPException(code, str(e))


def require(cur, token: str, role: str = 'user'):
    """角色门禁：guest<user<admin。401=未登录，403=权限不足"""
    from core import get_session
    s = get_session(cur, token)
    if not s:
        raise HTTPException(401, '该功能需要登录后使用（游客模式仅可浏览）')
    if role == 'admin' and s['role'] != 'admin':
        raise HTTPException(403, '需要管理员权限')
    return s


# ================= 用户 =================
@app.post('/api/v1/register')
def register(u: UserIn):
    with get_conn() as c:
        try:
            svc.register(c.cursor(), u.username, u.password)
            c.commit()
        except svc.UserError as e:
            err(e)
    return {'ok': True, 'msg': '注册成功'}


@app.post('/api/v1/login')
def login(u: UserIn):
    with get_conn() as c:
        try:
            r = svc.login(c.cursor(), u.username, u.password)
            c.commit()
        except svc.UserError as e:
            err(e)
    return {'ok': True, 'token': r['token'], 'role': r['role']}


@app.get('/api/v1/users')
def list_users(token: str = ''):
    with get_conn() as c:
        try:
            svc.require_admin(c.cursor(), token)
        except svc.UserError as e:
            err(e, 403)
        rows = query(c.cursor(), 'SELECT uid, username, role, created FROM users ORDER BY uid')
    return {'users': [{'uid': r['uid'], 'username': r['username'], 'role': r['role'],
                       'created': str(r['created'])} for r in rows]}


@app.get('/api/v1/admin/sessions')
def admin_sessions(token: str = ''):
    with get_conn() as c:
        try:
            svc.require_admin(c.cursor(), token)
        except svc.UserError as e:
            err(e, 403)
        rows = query(c.cursor(), '''SELECT username, role, expires_at,
                       round(EXTRACT(EPOCH FROM (expires_at - NOW()))/3600.0, 1) AS hours_left
                   FROM sessions WHERE expires_at > NOW() ORDER BY expires_at DESC LIMIT 100''')
    return {'sessions': [{'username': r['username'], 'role': r['role'],
                          'expires_at': str(r['expires_at']), 'hours_left': float(r['hours_left'])}
                         for r in rows]}


@app.delete('/api/v1/users/{uid}')
def del_user(uid: int, token: str = ''):
    with get_conn() as c:
        try:
            s = svc.require_admin(c.cursor(), token)
        except svc.UserError as e:
            err(e, 403)
        c.cursor().execute('DELETE FROM users WHERE uid=%s AND username<>%s', (uid, s['username']))
        c.commit()
    return {'ok': True}


# ================= 图层 =================
@app.get('/api/v1/layers/roads')
def layer_roads():
    return svc.roads_geojson(layer_cache)


@app.get('/api/v1/layers/pois')
def layer_pois(category: str = None):
    return svc.pois_geojson(layer_cache, category)


# ================= 淹没 =================
@app.get('/api/v1/flood/levels')
def flood_levels():
    return {'levels': svc.flood_levels()}


@app.get('/api/v1/flood/geojson')
def flood_geojson(level: float = 10.0):
    g = svc.flood_geojson(flood_cache, level)
    if not g:
        raise HTTPException(404, '无该水位情景')
    return g


# ================= 路径 =================
@app.get('/api/v1/route')
def route(flon: float, flat: float, tlon: float, tlat: float, token: str = '',
          mode: str = 'car', avoid_flood: bool = False, level: float = 10.0):
    with get_conn() as c:
        require(c.cursor(), token, 'user')
    try:
        return svc.route(layer_cache, flon, flat, tlon, tlat, mode, avoid_flood, level)
    except ValueError as e:
        raise HTTPException(404, str(e))


# ================= 服务区 =================
@app.get('/api/v1/service_area')
def service_area(lon: float, lat: float, minutes: float = 5.0, mode: str = 'walk', token: str = ''):
    with get_conn() as c:
        require(c.cursor(), token, 'user')
    try:
        return svc.service_area(layer_cache, lon, lat, minutes, mode)
    except ValueError as e:
        raise HTTPException(404, str(e))


# ================= 选址 =================
@app.get('/api/v1/shelters')
def shelters(level: float = 8.0, token: str = ''):
    with get_conn() as c:
        require(c.cursor(), token, 'user')
    return svc.shelters(level)


@app.get('/api/v1/coverage')
def coverage(level: float = 8.0, radius_m: int = 500, token: str = ''):
    with get_conn() as c:
        require(c.cursor(), token, 'user')
    return svc.coverage(level, radius_m)


# ================= 统计 =================
@app.get('/api/v1/stats/grid')
def stats_grid(level: float = 10.0, cell_deg: float = 0.005, token: str = ''):
    with get_conn() as c:
        require(c.cursor(), token, 'user')
    return svc.grid_stats(level, cell_deg)


@app.get('/api/v1/poi/search')
def poi_search(kw: str):
    with get_conn() as c:
        rows = query(c.cursor(), '''SELECT pid, coalesce(name,'') AS name, category,
                       ST_X(ST_Centroid(geom)) AS lon, ST_Y(ST_Centroid(geom)) AS lat
                   FROM pois WHERE name LIKE %s LIMIT 20''', (f'%{kw}%',))
    return {'results': [{'pid': r['pid'], 'name': r['name'], 'category': r['category'],
                         'lon': float(r['lon']), 'lat': float(r['lat'])} for r in rows]}


# ================= IoT 感知与四级预警 =================
@app.get('/api/v1/sensors/current')
def sensors_current(token: str = ''):
    with get_conn() as c:
        require(c.cursor(), token, 'user')
    return svc.sensors_current()


@app.get('/api/v1/sensors/history')
def sensors_history(sid: int, hours: float = 6.0):
    with get_conn() as c:
        rows = query(c.cursor(), '''SELECT water_m, rain_1h, ts FROM telemetry
                   WHERE sid=%s AND ts > NOW() - (%s || ' hours')::interval ORDER BY ts''',
                     (sid, hours))
    return {'sid': sid, 'series': [{'water_m': float(r['water_m']) if r['water_m'] is not None else None,
                                    'rain_1h': float(r['rain_1h']) if r['rain_1h'] is not None else None,
                                    'ts': str(r['ts'])} for r in rows]}


@app.post('/api/v1/sensors/telemetry')
def ingest(t: TelemetryIn):
    with get_conn() as c:
        ok = svc.ingest_telemetry(c.cursor(), t.sid, t.water_m, t.rain_1h)
        c.commit()
    if not ok:
        raise HTTPException(404, '传感器不存在')
    metric_incr('flood_telemetry_total')
    return {'ok': True}


@app.get('/api/v1/sensors/live')
def sensors_live(token: str = ''):
    """实时感知：雨量站=Open-Meteo 真实实况，其余站标注为模拟"""
    with get_conn() as c:
        require(c.cursor(), token, 'user')
    return svc.sensors_current('live')


@app.get('/api/v1/alerts/live')
def alerts_live(token: str = ''):
    with get_conn() as c:
        require(c.cursor(), token, 'user')
    return svc.alerts_current('live')


@app.get('/api/v1/radar/frames')
def radar_frames():
    import realtime
    return realtime.rainviewer_frames()


@app.get('/api/v1/alerts/current')
def alerts_current(token: str = ''):
    with get_conn() as c:
        require(c.cursor(), token, 'user')
    return svc.alerts_current()


# ================= 数据资产（DataOps） =================
@app.get('/api/v1/aq/history')
def aq_history(lat: float, lon: float, pollutant: str = 'pm2_5', days: int = 30):
    """真实历史逐时序列（Open-Meteo archives），供时序回放与分析"""
    import urllib.request, json as _json
    url = (f'https://air-quality-api.open-meteo.com/v1/air-quality?latitude={lat:.4f}&longitude={lon:.4f}'
           f'&hourly={pollutant}&past_days={min(days,92)}&timezone=Asia%2FShanghai')
    req = urllib.request.Request(url, headers={'User-Agent': 'FJAU-GIS-Course/2.0'})
    with urllib.request.urlopen(req, timeout=25) as r:
        d = _json.loads(r.read().decode())
    return {'lat': lat, 'lon': lon, 'pollutant': pollutant,
            'times': d['hourly']['time'], 'values': d['hourly'][pollutant],
            'source': 'Open-Meteo CAMS（真实历史）'}


@app.get('/api/v1/meta/config')
def meta_config():
    # 底图 key 属公开客户端凭据（天地图 JS 端本就随请求暴露），返回与否不影响安全边界
    return {'tdt_key': SETTINGS.TDT_KEY or ''}


@app.get('/api/v1/meta/datasets')
def meta_datasets():
    import dataops
    return {'datasets': dataops.datasets_meta()}


# ================= 空气质量时空分析 =================
@app.get('/api/v1/aq/grid')
def aq_grid(pollutant: str = 'pm2_5', n: int = 10, m: int = 30):
    import airquality
    g = airquality.idw_surface(pollutant, min(max(n, 4), 15), min(max(m, 10), 60))
    if not g:
        raise HTTPException(503, '采样不足')
    return g


@app.get('/api/v1/aq/stations/live')
def aq_stations_live():
    """国控空气监测站实时 AQI（WAQI/aqicn.org 真实数据）；未配置 token 返回引导（游客可用）"""
    import realtime
    return realtime.aq_stations_live()


@app.get('/api/v1/aq/kriging')
def aq_kriging(pollutant: str = 'pm2_5', n: int = 12, m: int = 40):
    import airquality
    g = airquality.kriging_surface(pollutant, min(max(n, 4), 15), min(max(m, 10), 60))
    if not g:
        raise HTTPException(503, '采样不足')
    return g


@app.get('/api/v1/aq/districts')
def aq_districts(pollutant: str = 'pm2_5'):
    import airquality
    return airquality.districts_stats(pollutant)


# ================= OGC API - Features =================
@app.get('/ogc')
def ogc_landing():
    return ogc.landing(str(app_root()))


@app.get('/ogc/conformance')
def ogc_conf():
    return ogc.conformance()


@app.get('/ogc/collections')
def ogc_collections():
    return ogc.collections(str(app_root()))


@app.get('/ogc/collections/{cid}')
def ogc_collection(cid: str):
    r = ogc.collection(cid, str(app_root()))
    if not r:
        raise HTTPException(404, '未知集合')
    return r


@app.get('/ogc/collections/{cid}/items', responses={200: {'content': {'application/geo+json': {}}}})
def ogc_items(cid: str, limit: int = 2000, offset: int = 0, level: float = 10.0):
    r = ogc.items(cid, str(app_root()), limit, offset, level)
    if not r:
        raise HTTPException(404, '未知集合')
    return JSONResponse(r, media_type='application/geo+json')


def app_root():
    return 'http://127.0.0.1:8000'


# ================= 运维 =================
@app.get('/health')
def health():
    try:
        with get_conn() as c:
            query(c.cursor(), 'SELECT 1')
        db = 'up'
    except Exception:
        db = 'down'
    return {'status': 'ok' if db == 'up' else 'degraded', 'db': db,
            'version': SETTINGS.APP_VERSION, 'uptime_s': int(time.time() - START_TIME)}


@app.get('/metrics')
def metrics():
    return Response(metrics_text(), media_type='text/plain')


# ================= 静态资源 =================
app.mount('/tiles', StaticFiles(directory=os.path.join(BASE, '..', 'data', 'tiles')), name='tiles')
app.mount('/lib', StaticFiles(directory=os.path.join(BASE, '..', 'frontend', 'lib')), name='lib')
app.mount('/static', StaticFiles(directory=os.path.join(BASE, '..', 'frontend')), name='static')


@app.get('/')
def index():
    return FileResponse(os.path.join(BASE, '..', 'frontend', 'index.html'))


@app.get('/admin.html')
def admin_page():
    return FileResponse(os.path.join(BASE, '..', 'frontend', 'admin.html'))


# ================= 旧版路径兼容（/api/* → /api/v1/*） =================
from fastapi.routing import APIRoute

_legacy = []
for r in app.routes:
    if isinstance(r, APIRoute) and r.path.startswith('/api/v1'):
        _legacy.append(APIRoute(r.path.replace('/api/v1', '/api', 1), r.endpoint,
                                methods=r.methods, name='legacy_' + r.name))
for r in _legacy:
    app.router.routes.append(r)


# ================= 启动初始化 =================
@app.on_event('startup')
def startup():
    init_pool()
    with get_conn() as c:
        cur = c.cursor()
        # 会话表（token 持久化，重启不失效）
        cur.execute('''CREATE TABLE IF NOT EXISTS sessions (
            token VARCHAR(64) PRIMARY KEY, username VARCHAR(50) NOT NULL,
            role VARCHAR(20) NOT NULL, expires_at TIMESTAMPTZ NOT NULL)''')
        # 密码升级：遗留明文 sha256 → PBKDF2（种子账号重置为 admin/123456）
        cur.execute("SELECT pwdhash FROM users WHERE username='admin'")
        row = cur.fetchone()
        if not row or not row[0].startswith('pbkdf2$'):
            from core import hash_password
            cur.execute("UPDATE users SET pwdhash=%s WHERE username='admin'",
                        (hash_password('123456'),))
        # IoT 感知层：传感器布点（研究区易涝位置示意）
        cur.execute('''CREATE TABLE IF NOT EXISTS sensors (
            sid SERIAL PRIMARY KEY, name VARCHAR(100) NOT NULL,
            type VARCHAR(20) NOT NULL, warn_level numeric,
            geom geometry(Point,4326))''')
        cur.execute('''CREATE TABLE IF NOT EXISTS telemetry (
            tid BIGSERIAL PRIMARY KEY, sid INT REFERENCES sensors(sid),
            water_m numeric, rain_1h numeric, ts TIMESTAMPTZ DEFAULT NOW())''')
        cur.execute('CREATE INDEX IF NOT EXISTS telemetry_sid_ts ON telemetry(sid, ts DESC)')
        cur.execute('SELECT count(*) FROM sensors')
        if cur.fetchone()[0] == 0:
            for name, stype, lon, lat in [
                    ('闽江上渡段水位站', 'water', 119.2285, 26.0455),
                    ('金山寺江边水位站', 'water', 119.2502, 26.0510),
                    ('乌龙江大桥北水位站', 'water', 119.2601, 26.0389),
                    ('农大东门积水点', 'depth', 119.2391, 26.0632),
                    ('上渡路下穿通道', 'depth', 119.2320, 26.0487),
                    ('金山大道低洼段', 'depth', 119.2560, 26.0560),
                    ('建新南路易涝点', 'depth', 119.2705, 26.0450),
                    ('仓山科技园雨量站', 'rain', 119.2830, 26.0460),
                    ('农林大学雨量站', 'rain', 119.2370, 26.0660),
                    ('洪山桥雨量站', 'rain', 119.2510, 26.0730)]:
                cur.execute('INSERT INTO sensors (name, type, warn_level, geom) VALUES (%s,%s,%s, ST_SetSRID(ST_MakePoint(%s,%s),4326))',
                            (name, stype, 0.35 if stype == 'depth' else None, lon, lat))
        c.commit()
    log.info('startup complete: pool ready, sessions/sensors ensured, v%s', SETTINGS.APP_VERSION)
