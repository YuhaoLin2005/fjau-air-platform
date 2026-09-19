# -*- coding: utf-8 -*-
"""实时数据接入层：Open-Meteo（免费无 key）真实逐小时降水
口径：rain 站 = Open-Meteo 实测/实况降水（真实数据）；water/depth 站无免费公开源，保持模拟并标注。
"""
import json, time, urllib.request
from core import TTLCache, log, SETTINGS

_wx_cache = TTLCache(300)   # 5 分钟缓存，尊重免费服务

def _fetch_json(url, timeout=15):
    req = urllib.request.Request(url, headers={'User-Agent': 'FJAU-GIS-Course/2.0'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())

def real_rain_1h(lat: float, lon: float):
    """Open-Meteo 实况：最近一个完整小时的降水 mm（真实数据）"""
    key = f'wx:{lat:.3f}:{lon:.3f}'
    hit = _wx_cache.get(key)
    if hit is not None:
        return hit
    url = (f'https://api.open-meteo.com/v1/forecast?latitude={lat:.4f}&longitude={lon:.4f}'
           f'&hourly=precipitation&past_days=1&forecast_days=1&timezone=Asia%2FShanghai')
    out = None
    try:
        d = _fetch_json(url)
        h = d['hourly']
        now_local = time.strftime('%Y-%m-%dT%H:00', time.localtime())
        times = h['time']
        i = times.index(now_local) if now_local in times else len(times) - 1
        # 最近一个完整小时 = 上一小时（当小时未结束，用前一小时累计 + 当小时已有值近似 1h 雨量）
        prev = float(h['precipitation'][i - 1]) if i >= 1 else 0.0
        cur = float(h['precipitation'][i]) if i < len(h['precipitation']) else 0.0
        out = {'rain_1h': round(prev + cur, 1), 'obs_time': now_local,
               'source': 'Open-Meteo 实况（真实数据，5min 缓存）'}
    except Exception as e:
        log.warning('Open-Meteo 拉取失败: %s', e)
        out = None
    _wx_cache.put(key, out or {'rain_1h': None, 'obs_time': None, 'source': '拉取失败'})
    return out

def rainviewer_frames():
    """RainViewer 公开雷达帧列表（真实降水雷达，约 10min/帧）"""
    key = 'rv:frames'
    hit = _wx_cache.get(key)
    if hit:
        return hit
    try:
        d = _fetch_json('https://api.rainviewer.com/public/weather-maps.json', timeout=10)
        host = d['host']
        frames = [{'time': f['time'], 'path': host + f['path'] + '/256/{z}/{x}/{y}/2/1_1.png'}
                  for f in (d['radar']['past'] + d['radar'].get('nowcast', []))[-8:]]
        out = {'frames': frames, 'source': 'RainViewer 实况雷达（真实数据）'}
        _wx_cache.put(key, out)
        return out
    except Exception as e:
        log.warning('RainViewer 拉取失败: %s', e)
        return {'frames': [], 'source': '拉取失败'}


# ---------------- 国控空气监测站实时数据（aqicn.org / WAQI 官方 API） ----------------
# 免费 token 申请：https://aqicn.org/data-api/token/（填邮箱即发，含使用条款与署名要求）
# 端点 /map/bounds/ 返回 bbox 内全部监测站的实时 AQI——真实国控/省控站，非模拟。
_waqi_cache = TTLCache(600)   # 10 分钟缓存，与 AQ 插值面对齐

def _aqi_level(aqi):
    """AQI 数值 → HJ 633-2012 六级（AQI 分级与浓度分级同口径映射）"""
    try:
        v = float(aqi)
    except (TypeError, ValueError):
        return '—'
    for th, name in ((50, '优'), (100, '良'), (150, '轻度'), (200, '中度'), (300, '重度')):
        if v <= th:
            return name
    return '严重'

LEVEL_COLOR = {'优': '#2E7D52', '良': '#C9A227', '轻度': '#E67E22', '中度': '#C0392B',
               '重度': '#8E2A3C', '严重': '#5B1220', '—': '#95A5A6'}

def aq_stations_live():
    """市域 bbox 内监测站实时 AQI（WAQI map/bounds，真实数据）。未配置 token 时返回引导信息。"""
    base = {'source': 'WAQI / aqicn.org 官方 API（实时监测站，真实数据，10min 缓存）',
            'standard': '站点 AQI（US EPA 口径，WAQI 原值）· 等级按 HJ 633-2012 映射展示'}
    if not SETTINGS.WAQI_TOKEN:
        return {'available': False,
                'reason': '未配置 WAQI_TOKEN：在 backend/.env 填入 token（aqicn.org/data-api/token 免费申请）后重启',
                **base}
    key = 'waqi:stations'
    hit = _waqi_cache.get(key)
    if hit is not None:
        return hit
    W, S, E, N = SETTINGS.AQ_BBOX
    url = (f'https://api.waqi.info/map/bounds/?latlng={S:.4f},{W:.4f},{N:.4f},{E:.4f}'
           f'&token={SETTINGS.WAQI_TOKEN}')
    out = dict(base, available=False, stations=[])
    try:
        d = _fetch_json(url)
        if d.get('status') == 'ok':
            stations = []
            for it in d.get('data', []):
                stations.append({
                    'lat': float(it['lat']), 'lon': float(it['lon']),
                    'name': (it.get('station') or {}).get('name', '未命名站'),
                    'aqi': it.get('aqi'), 'level': _aqi_level(it.get('aqi')),
                    'color': LEVEL_COLOR.get(_aqi_level(it.get('aqi')), '#95A5A6'),
                    'time': (it.get('station') or {}).get('time'),
                })
            out = dict(base, available=True, stations=stations,
                       fetched_at=time.strftime('%Y-%m-%d %H:%M'))
        else:
            out['reason'] = f"WAQI 返回异常: {d.get('data')}"
    except Exception as e:
        log.warning('WAQI 拉取失败: %s', e)
        out['reason'] = f'WAQI 拉取失败: {e}'
    _waqi_cache.put(key, out)
    return out
