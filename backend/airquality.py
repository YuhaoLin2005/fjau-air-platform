# -*- coding: utf-8 -*-
"""空气质量时空分析模块：Open-Meteo Air Quality（免费无 key）
网格采样（批量多坐标单请求）→ IDW 空间插值 → 连续污染面
分级标准：HJ 633-2012 环境空气质量指数（AQI）技术规定（国家标准，非自拟参数）
"""
import json, math, time, urllib.request
from core import SETTINGS, TTLCache

_aq_cache = TTLCache(600)  # 10 分钟缓存

POLLUTANTS = {'pm2_5': 'PM2.5', 'pm10': 'PM10', 'ozone': 'O₃', 'nitrogen_dioxide': 'NO₂'}

# HJ 633-2012：24h 浓度限值分级（μg/m³）——1h 实时值参考该标准分级展示
def aq_level(pollutant, v):
    limits = {
        'pm2_5': [(35, '优'), (75, '良'), (115, '轻度'), (150, '中度'), (250, '重度'), (1e9, '严重')],
        'pm10':  [(50, '优'), (150, '良'), (250, '轻度'), (350, '中度'), (420, '重度'), (1e9, '严重')],
        'ozone': [(160, '优'), (200, '良'), (300, '轻度'), (400, '中度'), (800, '重度'), (1e9, '严重')],
        'nitrogen_dioxide': [(100, '优'), (200, '良'), (700, '轻度'), (1200, '中度'), (2340, '重度'), (1e9, '严重')],
    }.get(pollutant)
    if limits is None or v is None:
        return '—'
    for th, name in limits:
        if v < th:
            return name
    return '严重'

LEVEL_COLOR = {'优': '#2E7D52', '良': '#C9A227', '轻度': '#E67E22', '中度': '#C0392B',
               '重度': '#8E2A3C', '严重': '#5B1220', '—': '#95A5A6'}

def _fetch_batch(points, pollutant):
    """Open-Meteo 批量多坐标（单请求）取 current 污染物"""
    lats = ','.join(f'{la:.4f}' for la, lo in points)
    lons = ','.join(f'{lo:.4f}' for la, lo in points)
    url = (f'https://air-quality-api.open-meteo.com/v1/air-quality?latitude={lats}&longitude={lons}'
           f'&current={pollutant}&timezone=Asia%2FShanghai')
    req = urllib.request.Request(url, headers={'User-Agent': 'FJAU-GIS-Course/2.0'})
    with urllib.request.urlopen(req, timeout=20) as r:
        d = json.loads(r.read().decode())
    items = d if isinstance(d, list) else [d]
    out = []
    for (la, lo), item in zip(points, items):
        v = item.get('current', {}).get(pollutant)
        out.append({'lat': la, 'lon': lo, 'value': float(v) if v is not None else None,
                    'obs_time': item.get('current', {}).get('time')})
    return out

def sample_grid(pollutant='pm2_5', n=10):
    """n×n 网格采样研究区真实浓度（Open-Meteo CAMS 模式同化数据，约 11km 分辨率）"""
    key = f'aq:{pollutant}:{n}'
    hit = _aq_cache.get(key)
    if hit:
        return hit
    W, S, E, N = SETTINGS.AQ_BBOX
    pts = [(S + (N - S) * i / (n - 1), W + (E - W) * j / (n - 1))
           for i in range(n) for j in range(n)]
    samples = _fetch_batch(pts, pollutant)
    out = {'samples': samples, 'pollutant': pollutant, 'unit': 'μg/m³',
           'source': 'Open-Meteo Air Quality（CAMS 同化，实时真实）', 'sampled_at': time.strftime('%Y-%m-%d %H:%M')}
    _aq_cache.put(key, out)
    return out

def idw_surface(pollutant='pm2_5', n=10, m=30, power=2):
    """IDW 插值到 m×m 细网格 → 连续污染面 GeoJSON（含 HJ633 分级）"""
    key = f'idw:{pollutant}:{n}:{m}'
    hit = _aq_cache.get(key)
    if hit:
        return hit
    s = sample_grid(pollutant, n)
    samples = [p for p in s['samples'] if p['value'] is not None]
    if len(samples) < 4:
        return None
    W, S, E, N = SETTINGS.AQ_BBOX
    feats = []
    for i in range(m):
        for j in range(m):
            la = S + (N - S) * (i + .5) / m
            lo = W + (E - W) * (j + .5) / m
            num = den = 0.0
            for p in samples:
                d2 = (la - p['lat']) ** 2 + (lo - p['lon']) ** 2
                if d2 < 1e-12:
                    num, den = p['value'], 1.0
                    break
                w = 1.0 / (d2 ** (power / 2))
                num += w * p['value']; den += w
            v = num / den if den else None
            lvl = aq_level(pollutant, v)
            half_lat, half_lon = (N - S) / m / 2, (E - W) / m / 2
            feats.append({'type': 'Feature', 'properties': {
                'value': round(v, 1), 'level': lvl, 'color': LEVEL_COLOR[lvl]},
                'geometry': {'type': 'Polygon', 'coordinates': [[
                    [lo - half_lon, la - half_lat], [lo + half_lon, la - half_lat],
                    [lo + half_lon, la + half_lat], [lo - half_lon, la + half_lat],
                    [lo - half_lon, la - half_lat]]]}})
    out = {'type': 'FeatureCollection', 'features': feats,
           'samples': {'type': 'FeatureCollection', 'features': [
               {'type': 'Feature', 'properties': {
                   'value': p['value'], 'level': aq_level(pollutant, p['value'])},
                'geometry': {'type': 'Point', 'coordinates': [p['lon'], p['lat']]}}
               for p in samples]},
           'meta': {'pollutant': pollutant, 'source': s['source'],
                    'sampled_at': s['sampled_at'], 'standard': 'HJ 633-2012（1h 实时值参考分级）'}}
    _aq_cache.put(key, out)
    return out


def kriging_surface(pollutant='pm2_5', n=12, m=40):
    """ Ordinary Kriging 插值（pykrige 成熟库实现）——与 IDW 双方法互证 """
    s = sample_grid(pollutant, n)
    samples = [p for p in s['samples'] if p['value'] is not None]
    if len(samples) < 4:
        return None
    from pykrige.ok import OrdinaryKriging
    import numpy as np
    lats = np.array([p['lat'] for p in samples])
    lons = np.array([p['lon'] for p in samples])
    vals = np.array([p['value'] for p in samples])
    W, S, E, N = SETTINGS.AQ_BBOX
    gridlon = np.linspace(W, E, m)
    gridlat = np.linspace(S, N, m)
    ok = OrdinaryKriging(lons, lats, vals, variogram_model='spherical',
                         enable_plotting=False, coordinates_type='geographic')
    z, ss = ok.execute('grid', gridlon, gridlat)
    feats = []
    for i in range(m):
        for j in range(m):
            v = float(z[i, j])
            la = float(gridlat[i]); lo = float(gridlon[j])
            half_lat, half_lon = (N - S) / m / 2, (E - W) / m / 2
            feats.append({'type': 'Feature', 'properties': {
                'value': round(v, 1), 'level': aq_level(pollutant, v), 'color': LEVEL_COLOR[aq_level(pollutant, v)]},
                'geometry': {'type': 'Polygon', 'coordinates': [[
                    [lo - half_lon, la - half_lat], [lo + half_lon, la - half_lat],
                    [lo + half_lon, la + half_lat], [lo - half_lon, la + half_lat],
                    [lo - half_lon, la - half_lat]]]}})
    return {'type': 'FeatureCollection', 'features': feats,
            'meta': {'pollutant': pollutant, 'method': 'OrdinaryKriging(pykrige, spherical)',
                     'source': s['source'], 'sampled_at': s['sampled_at'],
                     'standard': 'HJ 633-2012（1h 实时值参考分级）'}}


def districts_stats(pollutant='pm2_5'):
    """分区县统计：真实区县边界（DataV）× 插值面（真实浓度）空间叠加"""
    s = sample_grid(pollutant, 12)
    samples = [p for p in s['samples'] if p['value'] is not None]
    from shapely.geometry import shape, Point
    dj = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                     '..', 'data', 'raw', 'fuzhou_districts.json'), encoding='utf-8'))
    out = []
    for f in dj['features']:
        geom = shape(f['geometry'])
        # 区县内插值面均值：以区县内网格采样点为准，无采样点则取面中心插值
        inside = [p['value'] for p in samples if geom.contains(Point(p['lon'], p['lat']))]
        if inside:
            v = sum(inside) / len(inside)
            method = f'{len(inside)} 采样点均值'
        else:
            c = geom.centroid
            num = den = 0.0
            for p in samples:
                d2 = (c.y - p['lat']) ** 2 + (c.x - p['lon']) ** 2
                w = 1.0 / (d2 ** 1.0) if d2 > 1e-12 else 1e12
                num += w * p['value']; den += w
            v, method = num / den, 'IDW 面中心插值'
        lvl = aq_level(pollutant, v)
        out.append({'name': f['properties']['name'], 'value': round(v, 1), 'level': lvl,
                    'color': LEVEL_COLOR[lvl], 'method': method})
    return {'districts': out, 'pollutant': pollutant,
            'source': s['source'], 'boundaries': 'DataV 行政区划（真实边界）',
            'standard': 'HJ 633-2012（1h 实时值参考分级）', 'sampled_at': s['sampled_at']}


import os  # noqa: E402  (供 districts_stats 读取边界文件)
