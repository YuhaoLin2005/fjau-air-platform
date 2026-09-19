# -*- coding: utf-8 -*-
"""DataOps 数据运维层：管线编排 + 质量门 + 数据版本/新鲜度登记
数据资产：roads / pois / dem_flood / telemetry
每条资产登记：来源、获取时间、入库时间、行数、质量门结果——新鲜度可查可保证。
用法: python refresh_data.py   （编排 build_db + prepare_dem + 质量门 + 版本登记）
"""
import sys, io, os, json, subprocess, time
from core import SETTINGS, get_conn, query, log  # core 已统一处理 stdout 编码

BASE = os.path.dirname(os.path.abspath(__file__))

def ensure_registry():
    with get_conn() as c:
        c.cursor().execute('''CREATE TABLE IF NOT EXISTS dataset_versions (
            id SERIAL PRIMARY KEY,
            asset VARCHAR(50) NOT NULL,
            source TEXT NOT NULL,
            fetched_at TIMESTAMPTZ,
            imported_at TIMESTAMPTZ DEFAULT NOW(),
            rows BIGINT,
            quality JSONB,
            status VARCHAR(20) DEFAULT 'ok')''')
        c.commit()

def register(cur, asset, source, fetched_at, rows, quality):
    cur.execute('''INSERT INTO dataset_versions (asset, source, fetched_at, rows, quality)
                   VALUES (%s,%s,%s,%s,%s)''',
                (asset, source, fetched_at, rows, json.dumps(quality, ensure_ascii=False)))

_cache = None
def get_cache():
    global _cache
    if _cache is None:
        from core import TTLCache
        _cache = TTLCache(10)
    return _cache

def quality_gates():
    """数据质量门：真实校验，任何一项不过=管线失败（永远不会红的检查比没有更糟）"""
    gates = []
    with get_conn() as c:
        cur = c.cursor()
        # G1 路网规模
        n_roads = query(cur, 'SELECT count(*) AS n FROM roads', one=True)['n']
        gates.append(('roads_rows', n_roads, n_roads >= 3000, f'{n_roads} 条路段（门限≥3000）'))
        # G2 拓扑完整
        row = query(cur, '''SELECT (SELECT count(*) FROM roads_noded_vertices_pgr) AS v,
                                   (SELECT count(*) FROM roads_noded) AS e''', one=True)
        gates.append(('topology', f"{row['v']}节点/{row['e']}边",
                      row['v'] > 5000 and row['e'] > row['v'], '节点>5000 且 边>节点'))
        # G3 主连通分量占比
        main_e = query(cur, 'SELECT count(*) AS n FROM v_route', one=True)['n']
        ratio = main_e / max(1, row['e'])
        gates.append(('main_component', f'{ratio:.1%}', ratio > 0.9, '最大连通分量占比>90%'))
        # G4 POI 规模
        n_poi = query(cur, 'SELECT count(*) AS n FROM pois', one=True)['n']
        gates.append(('poi_rows', n_poi, n_poi >= 50, f'{n_poi} 处（门限≥50）'))
        # G5 淹没情景单调性（水位↑ 面积↑）
        rows = query(cur, '''SELECT level_m, SUM(ST_Area(geom::geography)) AS a
                             FROM flood_levels GROUP BY level_m ORDER BY level_m''')
        areas = [float(r['a']) for r in rows]
        mono = all(areas[i] < areas[i+1] for i in range(len(areas)-1)) and len(areas) >= 3
        gates.append(('flood_monotonic', f'{len(areas)}档', mono, '淹没面积随水位单调递增'))
        # G6 路径梯度（避淹不短于普通）
        import services as svc
        r1 = svc.route(get_cache(), 119.236, 26.065, 119.28, 26.05, 'car', False, 8)
        r2 = svc.route(get_cache(), 119.236, 26.065, 119.28, 26.05, 'car', True, 8)
        gates.append(('route_gradient', f"{r1['distance_m']}→{r2['distance_m']}m",
                      r2['distance_m'] >= r1['distance_m'], '避淹路径≥普通路径'))
    return gates

def run():
    ensure_registry()
    t0 = time.time()
    # 1. 重跑建库与淹没管线（脚本本身幂等）
    for script in ['build_db.py', 'prepare_dem.py']:
        log.info('管线执行: %s', script)
        r = subprocess.run([sys.executable, os.path.join(BASE, script)],
                           capture_output=True, text=True, encoding='utf-8', errors='ignore')
        if r.returncode != 0:
            log.error('%s 失败:\n%s', script, (r.stdout or '') + (r.stderr or ''))
            return False
    # 2. 登记数据版本（来源与获取时间取自落盘文件）
    from datetime import datetime, timezone
    raw = os.path.join(BASE, '..', 'data', 'raw')
    def fetched(name):
        p = os.path.join(raw, name)
        return datetime.fromtimestamp(os.path.getmtime(p), tz=timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ') \
            if os.path.exists(p) else None
    with get_conn() as c:
        cur = c.cursor()
        stats = query(cur, '''SELECT
            (SELECT count(*) FROM roads) AS roads,
            (SELECT count(*) FROM pois) AS pois,
            (SELECT count(DISTINCT level_m) FROM flood_levels) AS levels''', one=True)
        register(cur, 'roads', 'OpenStreetMap Overpass（构建时快照）', fetched('fuzhou_roads.json'),
                 stats['roads'], {'bbox': '119.19-119.30E,26.03-26.10N'})
        register(cur, 'pois', 'OpenStreetMap Overpass（构建时快照）', fetched('fuzhou_pois.json'),
                 stats['pois'], {'categories': 9})
        register(cur, 'dem_flood', 'AWS Terrarium DEM z13 + 静态水位情景', fetched('flood_scenarios.geojson'),
                 stats['levels'], {'model': 'DEM阈值+连通域（情景推演，非水动力）'})
        # 3. 质量门
        gates = quality_gates()
        ok = all(g[2] for g in gates)
        register(cur, 'quality_gate', '内建六门', None, len(gates),
                 {g[0]: {'value': str(g[1]), 'pass': g[2], 'rule': g[3]} for g in gates})
        c.commit()
    dt = time.time() - t0
    log.info('── 质量门结果 %s（耗时 %.0fs）──', '全部通过 ✓' if ok else '存在失败 ✗', dt)
    for g in gates:
        log.info('  [%s] %-18s = %s （%s）', '✓' if g[2] else '✗', g[0], g[1], g[3])
    return ok

def datasets_meta():
    """供 API：各资产最新版本与新鲜度"""
    ensure_registry()
    with get_conn() as c:
        rows = query(c.cursor(), '''SELECT DISTINCT ON (asset) asset, source, fetched_at,
                       imported_at, rows, quality, status
                   FROM dataset_versions ORDER BY asset, imported_at DESC''')
    return [{'asset': r['asset'], 'source': r['source'],
             'fetched_at': r['fetched_at'].strftime('%Y-%m-%d %H:%M') if r['fetched_at'] else None,
             'imported_at': r['imported_at'].strftime('%Y-%m-%d %H:%M'),
             'rows': r['rows'], 'status': r['status'],
             'quality': r['quality'] if isinstance(r['quality'], dict) else json.loads(r['quality'] or '{}')}
            for r in rows]

if __name__ == '__main__':
    sys.exit(0 if run() else 1)
