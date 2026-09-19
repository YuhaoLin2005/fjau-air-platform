# -*- coding: utf-8 -*-
"""API 回归测试套件（pytest）
前置: uvicorn main:app 运行于 127.0.0.1:8000 且已运行 simulate_sensors.py
运行: python -m pytest tests/test_api.py -v
"""
import os, sys, json, urllib.request

BASE = os.environ.get('FLOOD_BASE', 'http://127.0.0.1:8000')

_admin_token = None
def admin_q():
    global _admin_token
    if _admin_token is None:
        _, d = call('POST', '/api/v1/login', {'username': 'admin', 'password': '123456'})
        _admin_token = d['token']
    return 'token=' + _admin_token

def call(method, path, body=None, expect=200):
    req = urllib.request.Request(BASE + path, method=method,
                                 data=json.dumps(body).encode() if body else None,
                                 headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode())

def test_aq_stations_live():
    """国控监测站端点：未配置 token 也必须 200 + available 布尔（诚实降级，不造假）"""
    code, d = call('GET', '/api/v1/aq/stations/live')
    assert code == 200 and isinstance(d.get('available'), bool)
    assert 'source' in d


def test_health():
    code, d = call('GET', '/health')
    assert code == 200 and d['status'] == 'ok' and d['db'] == 'up'

def test_route_basic():
    code, d = call('GET', f'/api/v1/route?flon=119.236&flat=26.065&tlon=119.28&tlat=26.05&mode=car&{admin_q()}')
    assert code == 200 and d['distance_m'] > 1000

def test_route_avoid_flood_gradient():
    code, d1 = call('GET', f'/api/v1/route?flon=119.236&flat=26.065&tlon=119.28&tlat=26.05&mode=car&{admin_q()}' )
    code, d2 = call('GET', f'/api/v1/route?flon=119.236&flat=26.065&tlon=119.28&tlat=26.05&mode=car&avoid_flood=true&level=8&{admin_q()}' )
    assert d2['distance_m'] >= d1['distance_m']      # 避淹路径必不短于普通路径

def test_route_impossible_is_friendly():
    code, d = call('GET', f'/api/v1/route?flon=119.236&flat=26.065&tlon=119.28&tlat=26.05&mode=car&avoid_flood=true&level=12&{admin_q()}' )
    assert code == 404 and '无可达路径' in d['detail']

def test_flood_nearest_level():
    code, d = call('GET', '/api/v1/flood/geojson?level=9')
    assert code == 200 and d['properties']['level'] in (8.0, 10.0)

def test_user_lifecycle():
    import random
    u = f'pytest_{random.randint(10000,99999)}'
    assert call('POST', '/api/v1/register', {'username': u, 'password': 'p@ss123'})[0] == 200
    assert call('POST', '/api/v1/register', {'username': u, 'password': 'x'})[0] == 400
    code, d = call('POST', '/api/v1/login', {'username': u, 'password': 'p@ss123'})
    assert code == 200 and d['token']
    assert call('GET', '/api/v1/users')[0] in (400, 403, 422)   # 无 token 越权
    code, d = call('POST', '/api/v1/login', {'username': 'admin', 'password': '123456'})
    token = d['token']
    code, d = call('GET', f'/api/v1/users?token={token}')
    assert code == 200 and any(x['username'] == u for x in d['users'])

def test_ogc_landing_and_collections():
    assert call('GET', '/ogc')[0] == 200
    code, d = call('GET', '/ogc/collections')
    ids = [c['id'] for c in d['collections']]
    assert set(ids) >= {'roads', 'pois', 'flood'}

def test_ogc_items_geojson():
    code, d = call('GET', '/ogc/collections/pois/items?limit=50')
    assert code == 200 and d['type'] == 'FeatureCollection'
    assert d['numberReturned'] == len(d['features']) and d['numberMatched'] >= d['numberReturned']

def test_sensors_and_alerts():
    code, d = call('GET', f'/api/v1/sensors/current?{admin_q()}')
    assert code == 200 and len(d) >= 8
    code, a = call('GET', f'/api/v1/alerts/current?{admin_q()}')
    assert code == 200 and a['city_alert'] in ('none', 'blue', 'yellow', 'orange', 'red')
    assert len(a['triggered_stations']) >= 1      # 模拟事件后必有触发

def test_metrics_and_version():
    with urllib.request.urlopen(BASE + '/metrics', timeout=15) as r:
        body = r.read().decode()
    assert 'flood_requests_total' in body
    assert call('GET', '/openapi.json')[0] == 200


# ---------------- 三角色权限矩阵 ----------------
def test_role_matrix():
    # 游客：公开端点可访问
    assert call('GET', '/health')[0] == 200
    assert call('GET', '/api/v1/layers/roads')[0] == 200
    assert call('GET', '/api/v1/aq/grid?pollutant=pm2_5&n=6&m=10')[0] == 200
    # 游客：受保护分析端点 → 401
    assert call('GET', '/api/v1/route?flon=119.236&flat=26.065&tlon=119.28&tlat=26.05')[0] == 401
    assert call('GET', '/api/v1/shelters')[0] == 401
    assert call('GET', '/api/v1/sensors/live')[0] == 401
    assert call('GET', '/api/v1/stats/grid')[0] == 401
    # 普通用户：分析可用，管理端点 403
    import random
    u = f'role_{random.randint(10000,99999)}'
    call('POST', '/api/v1/register', {'username': u, 'password': 'p@ss'})
    _, d = call('POST', '/api/v1/login', {'username': u, 'password': 'p@ss'})
    ut = d['token']
    assert call('GET', f'/api/v1/route?flon=119.236&flat=26.065&tlon=119.28&tlat=26.05&token={ut}')[0] == 200
    assert call('GET', f'/api/v1/sensors/live?token={ut}')[0] == 200
    assert call('GET', f'/api/v1/users?token={ut}')[0] == 403
    assert call('GET', f'/api/v1/admin/sessions?token={ut}')[0] == 403
    # 管理员：全部可用
    _, d = call('POST', '/api/v1/login', {'username': 'admin', 'password': '123456'})
    at = d['token']
    assert call('GET', f'/api/v1/users?token={at}')[0] == 200
    assert call('GET', f'/api/v1/admin/sessions?token={at}')[0] == 200
    # 清理
    _, users = call('GET', f'/api/v1/users?token={at}')
    uid = [x['uid'] for x in users['users'] if x['username'] == u][0]
    call('DELETE', f'/api/v1/users/{uid}?token={at}')


def test_kriging_and_districts():
    code, d = call('GET', '/api/v1/aq/kriging?pollutant=pm2_5')
    assert code == 200 and len(d['features']) == 1600 and 'pykrige' in d['meta']['method']
    code, d = call('GET', '/api/v1/aq/districts?pollutant=pm2_5')
    assert code == 200 and len(d['districts']) == 13
    assert all(x['value'] > 0 for x in d['districts'])
