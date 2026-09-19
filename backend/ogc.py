# -*- coding: utf-8 -*-
"""OGC API - Features (OGC 17-069r4) 最小合规实现
集合：roads / pois / flood —— 让本系统可被标准 GIS 客户端（QGIS 等）直接消费。
"""
import json
from core import SETTINGS, get_conn, query

CONFORMANCE = [
    'http://www.opengis.net/spec/ogcapi-features-1/1.0/conf/core',
    'http://www.opengis.net/spec/ogcapi-features-1/1.0/conf/geojson']

COLLECTIONS = {
    'roads': {'title': '路网（主连通分量）', 'desc': 'OSM 路网经 pgRouting 拓扑构建后的主连通分量边集',
              'sql': '''SELECT n.eid, coalesce(r.name,'') AS name, r.highway AS type,
                        ST_AsGeoJSON(n.geom, 6) AS g FROM v_route n
                        JOIN roads r ON r.gid = n.old_id''',
              'props': lambda r: {'eid': r['eid'], 'name': r['name'], 'highway': r['type']}},
    'pois': {'title': '设施点 POI', 'desc': '学校/公园/医院/体育场馆等应急相关设施',
             'sql': '''SELECT pid, coalesce(name,'') AS name, category,
                       ST_X(ST_Centroid(geom)) AS lon, ST_Y(ST_Centroid(geom)) AS lat,
                       ST_AsGeoJSON(geom, 6) AS g FROM pois''',
             'props': lambda r: {'pid': r['pid'], 'name': r['name'], 'category': r['category']}},
    'flood': {'title': '内涝淹没情景', 'desc': 'DEM 静态水位阈值情景推演多边形（level 查询参数，默认10m）',
              'sql': '''SELECT level_m, ST_AsGeoJSON(ST_Union(geom), 6) AS g FROM flood_levels
                        WHERE level_m = (SELECT level_m FROM flood_levels
                                         ORDER BY ABS(level_m - %s) LIMIT 1) GROUP BY level_m''',
              'props': lambda r: {'level_m': float(r['level_m'])}},
}


def landing(url_base):
    return {'title': '福州市暴雨内涝应急疏散与救援路径分析系统 · OGC API',
            'description': 'OGC API - Features (Part 1: Core) 最小合规实现',
            'links': [
                {'href': f'{url_base}/ogc', 'rel': 'self', 'type': 'application/json', 'title': '本文档'},
                {'href': f'{url_base}/ogc/conformance', 'rel': 'conformance', 'type': 'application/json'},
                {'href': f'{url_base}/ogc/collections', 'rel': 'data', 'type': 'application/json'}]}


def conformance():
    return {'conformsTo': CONFORMANCE}


def collections(url_base):
    W, S, E, N = SETTINGS.BBOX
    return {'links': [{'href': f'{url_base}/ogc/collections', 'rel': 'self', 'type': 'application/json'}],
            'collections': [
                {'id': cid, 'title': c['title'], 'description': c['desc'],
                 'extent': {'spatial': {'bbox': [[W, S, E, N]]}},
                 'links': [{'href': f'{url_base}/ogc/collections/{cid}', 'rel': 'self',
                            'type': 'application/json', 'title': c['title']},
                           {'href': f'{url_base}/ogc/collections/{cid}/items', 'rel': 'items',
                            'type': 'application/geo+json', 'title': f'{c["title"]} · 要素'}]}
                for cid, c in COLLECTIONS.items()]}


def collection(cid, url_base):
    c = COLLECTIONS.get(cid)
    if not c:
        return None
    W, S, E, N = SETTINGS.BBOX
    return {'id': cid, 'title': c['title'], 'description': c['desc'],
            'extent': {'spatial': {'bbox': [[W, S, E, N]]}},
            'links': [{'href': f'{url_base}/ogc/collections/{cid}/items', 'rel': 'items',
                       'type': 'application/geo+json'}]}


def items(cid, url_base, limit=2000, offset=0, level=10.0):
    c = COLLECTIONS.get(cid)
    if not c:
        return None
    limit = max(1, min(int(limit), 10000))
    offset = max(0, int(offset))
    with get_conn() as conn:
        cur = conn.cursor()
        params = (level,) if cid == 'flood' else None
        cur.execute(f'SELECT count(*) AS n FROM ({c["sql"].rstrip().rstrip(";")}) q', params)
        total = cur.fetchone()[0]
        sql = f'SELECT * FROM ({c["sql"].rstrip().rstrip(";")}) q LIMIT %s OFFSET %s'
        cur.execute(sql, ((params + (limit, offset)) if params else (limit, offset)))
        cols = [d[0] for d in cur.description]
        feats = []
        for row in cur.fetchall():
            d = dict(zip(cols, row))
            geom = json.loads(d.pop('g'))
            feats.append({'type': 'Feature', 'properties': c['props'](d), 'geometry': geom})
    return {'type': 'FeatureCollection',
            'numberMatched': total, 'numberReturned': len(feats),
            'timeStamp': __import__('datetime').datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'),
            'links': [{'href': f'{url_base}/ogc/collections/{cid}/items', 'rel': 'self',
                       'type': 'application/geo+json'}],
            'features': feats}
