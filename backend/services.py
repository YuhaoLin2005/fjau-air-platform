# -*- coding: utf-8 -*-
"""service 层：业务逻辑（图层/路径/服务区/选址/统计/用户/传感器/预警）"""
import json
from core import SETTINGS, get_conn, query, hash_password, verify_password, create_session, get_session

# 预警阈值（演示参数，口径：积水深度对交通的影响 + 1h 降雨量近似气象暴雨预警分级）
WATER_THRESHOLDS = [('red', 0.90), ('orange', 0.60), ('yellow', 0.35), ('blue', 0.15)]
RAIN_THRESHOLDS = [('red', 100), ('orange', 50), ('yellow', 25), ('blue', 10)]
ALERT_ORDER = {'none': 0, 'blue': 1, 'yellow': 2, 'orange': 3, 'red': 4}

SHELTER_CATS = ('park', 'school', 'stadium', 'sports_centre', 'community_centre', 'hospital')


def snap(cur, lon, lat):
    """吸附到主连通分量上最近的拓扑节点"""
    return query(cur, '''SELECT v.id, ST_X(v.the_geom) AS lon, ST_Y(v.the_geom) AS lat
                   FROM roads_noded_vertices_pgr v
                   WHERE EXISTS (SELECT 1 FROM roads_noded n
                                 WHERE n.comp = 1 AND (n.source = v.id OR n.target = v.id))
                   ORDER BY v.the_geom <-> ST_SetSRID(ST_MakePoint(%s,%s),4326) LIMIT 1''',
                 (lon, lat), one=True)


def edge_filter(mode: str, avoid: bool, level: float) -> str:
    conds = []
    if mode == 'walk':
        conds.append("highway NOT IN ('motorway','motorway_link','trunk','trunk_link')")
    if avoid:
        conds.append(f'''NOT EXISTS (SELECT 1 FROM flood_levels f
            WHERE f.level_m = {float(level)} AND ST_Intersects(f.geom, n.geom) AND NOT n.bridge)''')
    return (' AND ' + ' AND '.join(conds)) if conds else ''


# ---------------- 图层（带 TTL 缓存） ----------------
def roads_geojson(cache):
    hit = cache.get('roads')
    if hit:
        return hit
    with get_conn() as c:
        rows = query(c.cursor(), '''SELECT n.id AS gid, coalesce(r.name,'') AS name, r.highway,
                          ST_AsGeoJSON(n.geom, 6) AS g
                   FROM roads_noded n JOIN roads r ON r.gid = n.old_id''')
    gj = {'type': 'FeatureCollection',
          'features': [{'type': 'Feature',
                        'properties': {'gid': r['gid'], 'name': r['name'], 'highway': r['highway']},
                        'geometry': json.loads(r['g'])} for r in rows]}
    cache.put('roads', gj)
    return gj


def pois_geojson(cache, category=None):
    key = f'pois:{category or "all"}'
    hit = cache.get(key)
    if hit:
        return hit
    with get_conn() as c:
        sql = '''SELECT pid, coalesce(name,'') AS name, category, ST_AsGeoJSON(geom, 6) AS g FROM pois'''
        rows = query(c.cursor(), sql + ' WHERE category=%s' if category else sql,
                     (category,) if category else None)
    gj = {'type': 'FeatureCollection',
          'features': [{'type': 'Feature',
                        'properties': {'pid': r['pid'], 'name': r['name'], 'category': r['category']},
                        'geometry': json.loads(r['g'])} for r in rows]}
    cache.put(key, gj)
    return gj


# ---------------- 淹没 ----------------
def flood_levels():
    with get_conn() as c:
        rows = query(c.cursor(), '''SELECT level_m, count(*) AS patches,
                       round((SUM(ST_Area(geom::geography))/1000000.0)::numeric,2) AS area_km2
                   FROM flood_levels GROUP BY level_m ORDER BY level_m''')
    return [{'level': float(r['level_m']), 'patches': r['patches'], 'area_km2': float(r['area_km2'])}
            for r in rows]


def flood_geojson(cache, level: float):
    key = f'flood:{level}'
    hit = cache.get(key)
    if hit:
        return hit
    with get_conn() as c:
        row = query(c.cursor(), '''SELECT level_m, ST_AsGeoJSON(ST_Union(geom), 6) AS g FROM flood_levels
                       WHERE level_m = (SELECT level_m FROM flood_levels
                                        ORDER BY ABS(level_m - %s) LIMIT 1)
                       GROUP BY level_m''', (level,), one=True)
    if not row:
        return None
    out = {'type': 'Feature', 'properties': {'level': float(row['level_m'])},
           'geometry': json.loads(row['g'])}
    cache.put(key, out)
    return out


# ---------------- 路径 ----------------
def route(cache, flon, flat, tlon, tlat, mode='car', avoid_flood=False, level=10.0):
    key = f'route:{flon:.4f}:{flat:.4f}:{tlon:.4f}:{tlat:.4f}:{mode}:{avoid_flood}:{level}'
    hit = cache.get(key)
    if hit:
        hit['cached'] = True
        return hit
    with get_conn() as c:
        cur = c.cursor()
        s, t = snap(cur, flon, flat), snap(cur, tlon, tlat)
        if not s or not t:
            raise ValueError('起终点附近无可达路网')
        cost_expr = ('n.length_m / (n.speed_kmh / 3.6) / 60' if mode == 'car'
                     else 'n.length_m / 72.0')
        ef = edge_filter(mode, avoid_flood, level)
        sql = f'''SELECT * FROM pgr_dijkstra($$
            SELECT n.eid AS id, n.source, n.target, {cost_expr} AS cost, {cost_expr} AS reverse_cost
            FROM v_route n WHERE TRUE{ef}$$, {s['id']}, {t['id']}, directed:=false)'''
        cur.execute('SET LOCAL statement_timeout = 20000')  # 路径计算硬超时 20s
        cur.execute(sql)
        rows = cur.fetchall()
        col = {d[0]: i for i, d in enumerate(cur.description)}
        if not rows or rows[-1][col['agg_cost']] is None:
            raise ValueError('当前情景下无可达路径（可能路网被淹没切断）')
        edges = [r[col['edge']] for r in rows if r[col['edge']] and r[col['edge']] > 0]
        agg = rows[-1][col['agg_cost']]
        row = query(cur, '''SELECT round(SUM(length_m)::numeric,1) AS dist,
                       ST_AsGeoJSON(ST_UnaryUnion(ST_Collect(geom ORDER BY eid)), 6) AS g
                       FROM v_route WHERE eid = ANY(%s)''', (edges,), one=True)
    out = {'ok': True, 'mode': mode, 'avoid_flood': avoid_flood, 'level': level,
           'distance_m': float(row['dist'] or 0), 'time_min': round(float(agg), 1),
           'start': {'lon': s['lon'], 'lat': s['lat']},
           'end': {'lon': t['lon'], 'lat': t['lat']},
           'geometry': json.loads(row['g'])}
    cache.put(key, out)
    return out


def service_area(cache, lon, lat, minutes=5.0, mode='walk'):
    key = f'sa:{lon:.4f}:{lat:.4f}:{minutes}:{mode}'
    hit = cache.get(key)
    if hit:
        return hit
    speed = (60 / 3.6) if mode == 'car' else 72.0
    with get_conn() as c:
        row = query(c.cursor(), f'''SELECT ST_AsGeoJSON(ST_Buffer(ST_UnaryUnion(ST_Collect(e.geom)), 0.0004), 6) AS g,
                          SUM(e.length_m) AS total
        FROM pgr_drivingDistance($$
            SELECT n.eid AS id, n.source, n.target, n.length_m AS cost, n.length_m AS reverse_cost
            FROM v_route n WHERE TRUE{edge_filter(mode, False, 0)}$$,
            (SELECT v.id FROM roads_noded_vertices_pgr v
             WHERE EXISTS (SELECT 1 FROM roads_noded n WHERE n.comp=1 AND (n.source=v.id OR n.target=v.id))
             ORDER BY v.the_geom <-> ST_SetSRID(ST_MakePoint(%s,%s),4326) LIMIT 1),
            %s, directed:=false) dd
        JOIN v_route e ON e.eid = dd.edge''', (lon, lat, minutes * speed), one=True)
    if not row or not row['g']:
        raise ValueError('服务区计算失败')
    out = {'ok': True, 'minutes': minutes, 'mode': mode,
           'network_km': round(float(row['total'] or 0) / 1000, 2),
           'geometry': json.loads(row['g'])}
    cache.put(key, out)
    return out


# ---------------- 选址 ----------------
def shelters(level: float):
    with get_conn() as c:
        rows = query(c.cursor(), f'''SELECT p.pid, coalesce(p.name,'未命名') AS name, p.category,
                       round((ST_Area(p.geom::geography)/10000.0)::numeric,2) AS area_ha,
                       ST_AsGeoJSON(ST_Centroid(p.geom), 6) AS g
                FROM pois p WHERE p.category IN {SHELTER_CATS}
                  AND NOT EXISTS (SELECT 1 FROM flood_levels f
                                  WHERE f.level_m = %s AND ST_Intersects(f.geom, ST_Centroid(p.geom)))''',
                     (level,))
    import os
    import rasterio as _rio
    _pd = os.path.join(os.path.dirname(_rio.__file__), 'proj_data')
    os.environ['PROJ_LIB'] = _pd
    os.environ['PROJ_DATA'] = _pd
    dem_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'dem', 'dem.tif')
    feats = []
    with _rio.open(dem_path) as src:
        for r in rows:
            g = json.loads(r['g'])
            try:
                elev = float(next(src.sample([(g['coordinates'][0], g['coordinates'][1])]))[0])
            except Exception:
                elev = -9999
            score = min(100, max(0, (elev - level) * 6 + min(float(r['area_ha'] or 0), 5) * 4))
            feats.append({'type': 'Feature', 'properties': {
                'pid': r['pid'], 'name': r['name'], 'category': r['category'],
                'elev_m': elev, 'area_ha': float(r['area_ha'] or 0),
                'score': round(score, 1), 'safe': elev > level}, 'geometry': g})
    return {'type': 'FeatureCollection', 'features': feats}


def coverage(level: float, radius_m: int):
    with get_conn() as c:
        row = query(c.cursor(), f'''WITH shelters AS (
            SELECT ST_Centroid(p.geom) g FROM pois p WHERE p.category IN {SHELTER_CATS}
              AND NOT EXISTS (SELECT 1 FROM flood_levels f WHERE f.level_m=%s
                              AND ST_Intersects(f.geom, ST_Centroid(p.geom)))),
        buf AS (SELECT ST_Union(ST_Buffer(g, %s::double precision)) b FROM shelters)
        SELECT round((SUM(ST_Length(ST_Intersection(n.geom, b.b)::geography)) /
               NULLIF(SUM(ST_Length(n.geom::geography)), 0) * 100)::numeric, 1) AS pct
        FROM roads_noded n CROSS JOIN buf b
        WHERE NOT EXISTS (SELECT 1 FROM flood_levels f
                          WHERE f.level_m=%s AND ST_Intersects(f.geom, n.geom))''',
            (level, radius_m / 111320.0, level), one=True)
    return {'ok': True, 'level': level, 'radius_m': radius_m,
            'covered_road_pct': float(row['pct'] or 0)}


# ---------------- 网格统计 ----------------
def grid_stats(level: float, cell_deg: float = 0.005):
    import math
    W, S, E, N = SETTINGS.BBOX
    ncols, nrows = math.ceil((E - W) / cell_deg), math.ceil((N - S) / cell_deg)
    with get_conn() as c:
        rows = query(c.cursor(), f'''SELECT g.ix, g.iy, ST_AsGeoJSON(g.cell, 6) AS g,
        (SELECT count(*) FROM pois p WHERE ST_Intersects(p.geom, g.cell)) AS poi_cnt,
        COALESCE((SELECT round(SUM(ST_Length(ST_Intersection(
                ST_Intersection(n.geom, f.geom), g.cell)::geography))::numeric, 0)
          FROM roads_noded n, flood_levels f
          WHERE f.level_m = %s AND ST_Intersects(n.geom, f.geom) AND ST_Intersects(n.geom, g.cell)), 0) AS flooded
        FROM (SELECT x.n AS ix, y.n AS iy,
                     ST_Translate(ST_MakeEnvelope({W}, {S}, {W}+{cell_deg}, {S}+{cell_deg}, 4326),
                                  x.n*{cell_deg}, y.n*{cell_deg}) AS cell
              FROM generate_series(0, %s) x(n), generate_series(0, %s) y(n)) g''',
            (level, ncols - 1, nrows - 1))
    return {'type': 'FeatureCollection', 'features': [
        {'type': 'Feature',
         'properties': {'ix': r['ix'], 'iy': r['iy'], 'poi_cnt': r['poi_cnt'],
                        'flooded_road_m': float(r['flooded'] or 0)},
         'geometry': json.loads(r['g'])} for r in rows]}


# ---------------- 用户 ----------------
class UserError(Exception):
    pass


def register(cur, username, password):
    if not username.strip() or not password:
        raise UserError('用户名和密码不能为空')
    try:
        cur.execute('INSERT INTO users (username, pwdhash) VALUES (%s, %s)',
                    (username.strip(), hash_password(password)))
    except Exception:
        raise UserError('用户名已存在')


def login(cur, username, password):
    row = query(cur, 'SELECT pwdhash, role FROM users WHERE username=%s', (username.strip(),), one=True)
    if not row or not verify_password(password, row['pwdhash']):
        raise UserError('用户名或密码错误')
    return {'token': create_session(cur, username.strip(), row['role']), 'role': row['role']}


def require_admin(cur, token):
    s = get_session(cur, token)
    if not s or s['role'] != 'admin':
        raise UserError('需要管理员权限')
    return s


# ---------------- 传感器与四级预警 ----------------
def station_alert(water_m=None, rain_1h=None):
    lv = 'none'
    for name, th in WATER_THRESHOLDS:
        if water_m is not None and water_m >= th:
            lv = name
            break
    for name, th in RAIN_THRESHOLDS:
        if rain_1h is not None and rain_1h >= th:
            if ALERT_ORDER[name] > ALERT_ORDER[lv]:
                lv = name
    return lv


def sensors_current(source='db'):
    """source='live': 雨量站接 Open-Meteo 真实实况（逐站标注 source），其余站仍为模拟并标注"""
    """每站最新遥测 + 站点预警等级"""
    with get_conn() as c:
        rows = query(c.cursor(), '''SELECT s.sid, s.name, s.type, s.warn_level,
                       ST_X(s.geom) AS lon, ST_Y(s.geom) AS lat,
                       t.water_m, t.rain_1h, t.ts
                FROM sensors s
                LEFT JOIN LATERAL (SELECT water_m, rain_1h, ts FROM telemetry t
                                   WHERE t.sid = s.sid ORDER BY ts DESC LIMIT 1) t ON true
                ORDER BY s.sid''')
    out = []
    for r in rows:
        lv = station_alert(r['water_m'], r['rain_1h']) if r['water_m'] is not None else 'none'
        src = 'simulated'
        rain, ts = (float(r['rain_1h']) if r['rain_1h'] is not None else None), str(r['ts'])
        if source == 'live' and r['type'] == 'rain':
            import realtime
            live = realtime.real_rain_1h(float(r['lat']), float(r['lon']))
            if live and live.get('rain_1h') is not None:
                rain = live['rain_1h']; ts = live['obs_time']; src = 'open-meteo(实时真实)'
            else:
                src = 'open-meteo(拉取失败→回退模拟)'
        elif source == 'live':
            src = 'simulated(无公开实时源)'
        out.append({'sid': r['sid'], 'name': r['name'], 'type': r['type'],
                    'lon': float(r['lon']), 'lat': float(r['lat']),
                    'water_m': float(r['water_m']) if r['water_m'] is not None else None,
                    'rain_1h': rain, 'ts': ts, 'alert': lv,
                    'threshold': r['warn_level'], 'source': src})
    return out


def alerts_current(source='db'):
    """城市级预警 = 各站最高级 + 触发站清单"""
    stations = sensors_current(source)
    city = 'none'
    triggered = []
    for st in stations:
        if ALERT_ORDER.get(st['alert'], 0) > ALERT_ORDER[city]:
            city = st['alert']
        if st['alert'] != 'none':
            triggered.append(st)
    return {'city_alert': city,
            'levels': ['blue', 'yellow', 'orange', 'red'],
            'triggered_stations': triggered,
            'station_count': len(stations),
            'note': '阈值口径为演示参数（积水深度/1h雨量四级），数据源为模拟 IoT feed'}


def ingest_telemetry(cur, sid: int, water_m, rain_1h):
    cur.execute('''INSERT INTO telemetry (sid, water_m, rain_1h, ts)
                   SELECT %s, %s, %s, NOW() WHERE EXISTS (SELECT 1 FROM sensors WHERE sid=%s)''',
                (sid, water_m, rain_1h, sid))
    return cur.rowcount > 0
