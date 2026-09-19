# -*- coding: utf-8 -*-
"""模块级正确性验证套件 —— 用成熟独立实现作 oracle，逐模块对答案
原则：自己写的测试只能证明"代码做了我想做的事"，不能证明"我做的事是对的"。
     所以每个模块找一个久经考验的外部基准跑同一批输入：
  V1 最短路径   : pgRouting.Dijkstra  vs  NetworkX.Dijkstra（30 组随机 OD，比对总长）
  V2 服务区     : pgRouting.DrivingDistance vs NetworkX 单源 Dijkstra 截断（可达节点集 Jaccard）
  V3 缓冲区     : PostGIS.ST_Buffer(地心距) vs 解析几何 π·r²
  V4 测距       : PostGIS.ST_Distance(geography) vs pyproj.Geod（椭球测地线）
  V5 淹没模型   : scipy 连通域标记 vs 独立实现的八邻域 BFS 种子扩散（有源淹没经典算法）
  V6 瓦片数学   : deg2num vs WebMercator 已知参考值
产出: validation_report.json + 控制台判定表（任何一项 FAIL → exit 1）
"""
import sys, io, os, json, math, random, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np

from core import get_conn, query

RESULTS = []

def record(vid, name, detail, ok):
    RESULTS.append({'id': vid, 'module': name, 'detail': detail, 'pass': bool(ok)})
    print(f"  [{'✓' if ok else '✗'}] {vid} {name}: {detail}")
    return ok

# ---------- 导出主分量图为 NetworkX ----------
def export_graph():
    import networkx as nx
    G = nx.Graph()
    with get_conn() as c:
        rows = query(c.cursor(), 'SELECT eid, source, target, length_m FROM v_route')
    for r in rows:
        G.add_edge(r['source'], r['target'], length_m=float(r['length_m']), eid=r['eid'])
    return G

# ---------- V1 最短路径 ----------
def v1_routing(G):
    print('V1 最短路径：pgRouting vs NetworkX（30 组随机 OD）')
    random.seed(42)
    nodes = list(G.nodes)
    pairs = [(random.choice(nodes), random.choice(nodes)) for _ in range(30)]
    n_match, n_skip, worst = 0, 0, 0.0
    with get_conn() as c:
        cur = c.cursor()
        for s, t in pairs:
            if s == t:
                n_skip += 1
                continue
            cur.execute(f'''SELECT COALESCE(SUM(agg.cost),0) AS total FROM (
                SELECT DISTINCT ON (edge) edge, cost FROM pgr_dijkstra($$
                    SELECT eid AS id, source, target, length_m AS cost, length_m AS reverse_cost
                    FROM v_route$$, {s}, {t}, directed:=false) ) agg WHERE edge > 0''')
            pgr_total = float(cur.fetchone()[0])
            try:
                nx_total = nx_shortest(G, s, t)
            except Exception:
                n_skip += 1
                continue
            if pgr_total == 0 and nx_total == 0:
                n_match += 1
                continue
            if pgr_total == 0 or nx_total == 0:
                continue
            rel = abs(pgr_total - nx_total) / max(nx_total, 1e-9)
            worst = max(worst, rel)
            if rel < 0.005:
                n_match += 1
    ok = n_match >= len(pairs) - n_skip - 0   # 全部可比对成功才过
    return record('V1', '最短路径（Dijkstra）',
                  f'{n_match}/{len(pairs)-n_skip} 组一致（最大相对偏差 {worst:.4%}，容差 0.5%）', ok)

def nx_shortest(G, s, t):
    import networkx as nx
    return nx.shortest_path_length(G, s, t, weight='length_m')

# ---------- V2 服务区 ----------
def v2_service_area(G):
    print('V2 服务区：pgr_drivingDistance vs NetworkX 单源截断（步行 5min = 360m）')
    import networkx as nx
    cutoff = 5 * 72.0  # 步行 1.2m/s × 60s × 5min
    with get_conn() as c:
        cur = c.cursor()
        row = query(cur, '''SELECT id FROM roads_noded_vertices_pgr v
                       WHERE EXISTS (SELECT 1 FROM roads_noded n WHERE n.comp=1
                                     AND (n.source=v.id OR n.target=v.id))
                       ORDER BY the_geom <-> ST_SetSRID(ST_MakePoint(119.236,26.065),4326) LIMIT 1''', one=True)
        start = row['id']
        cur.execute(f'''SELECT DISTINCT dd.node FROM pgr_drivingDistance($$
            SELECT eid AS id, source, target, length_m AS cost, length_m AS reverse_cost
            FROM v_route$$, {start}, {cutoff}, directed:=false) dd''')
        pgr_nodes = {r[0] for r in cur.fetchall()}
    nx_dist = nx.single_source_dijkstra_path_length(G, start, cutoff=cutoff, weight='length_m')
    nx_nodes = set(nx_dist)
    inter = len(pgr_nodes & nx_nodes)
    union = len(pgr_nodes | nx_nodes)
    jaccard = inter / union if union else 0
    return record('V2', '服务区（DrivingDistance）',
                  f'可达节点集 Jaccard={jaccard:.4f}（pgr {len(pgr_nodes)} vs nx {len(nx_nodes)}，门限 0.98）',
                  jaccard >= 0.98)

# ---------- V3 缓冲区解析验证 ----------
def v3_buffer():
    print('V3 缓冲区：ST_Buffer(500m 地心距) vs π·r² 解析面积')
    with get_conn() as c:
        row = query(c.cursor(), '''SELECT ST_Area(ST_Buffer(ST_SetSRID(ST_MakePoint(119.245,26.062), 4326)::geography, 500)) AS a,
                          ST_Length(ST_MakeLine(ST_SetSRID(ST_MakePoint(119.245,26.062),4326),
                                                ST_SetSRID(ST_MakePoint(119.260,26.070),4326))::geography) AS d''',
                    one=True)
    area = float(row['a'])
    expect = math.pi * 500 ** 2
    rel_area = abs(area - expect) / expect
    return record('V3', '缓冲区（解析几何基准）',
                  f'面积 {area:.0f} m² vs πr²={expect:.0f} m²（偏差 {rel_area:.3%}，门限 1%）', rel_area < 0.01)

# ---------- V4 测地线距离 ----------
def v4_geodesic():
    print('V4 测距：ST_Distance(geography) vs pyproj.Geod 椭球')
    from pyproj import Geod
    with get_conn() as c:
        row = query(c.cursor(), '''SELECT ST_Distance(ST_SetSRID(ST_MakePoint(119.245,26.062),4326)::geography,
                                      ST_SetSRID(ST_MakePoint(119.260,26.070),4326)::geography) AS d''', one=True)
    d_postgis = float(row['d'])
    geod = Geod(ellps='WGS84')
    _, _, d_pyproj = geod.inv(119.245, 26.062, 119.260, 26.070)
    rel = abs(d_postgis - d_pyproj) / d_pyproj
    return record('V4', '测地线距离（pyproj 基准）',
                  f'{d_postgis:.2f} m vs {d_pyproj:.2f} m（偏差 {rel:.5%}，门限 0.1%）', rel < 0.001)

# ---------- V5 淹没模型双算法互证 ----------
def v5_flood():
    print('V5 淹没模型：scipy.ndimage 连通域 vs 独立 BFS 种子扩散（有源淹没经典算法）')
    import rasterio as _rio
    _pd = os.path.join(os.path.dirname(_rio.__file__), 'proj_data')
    os.environ['PROJ_LIB'] = _pd; os.environ['PROJ_DATA'] = _pd
    from scipy import ndimage
    dem_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'dem', 'dem.tif')
    with _rio.open(dem_path) as src:
        dem = src.read(1)
        transform = src.transform
    level = 8.0
    # 算法 A（线上系统同款）：scipy 8 邻域连通域，江面(<4m)为种子
    below = dem < level
    lbl, _ = ndimage.label(below, structure=np.ones((3, 3)))
    river_ids = set(np.unique(lbl[(dem < 4.0) & (lbl > 0)])) - {0}
    maskA = np.isin(lbl, list(river_ids))
    # 算法 B（独立实现）：显式 BFS 种子扩散
    maskB = np.zeros_like(below, dtype=bool)
    stack = list(zip(*np.where((dem < 4.0) & below)))
    for r, c in stack:
        maskB[r, c] = True
    H, W = dem.shape
    while stack:
        r, c = stack.pop()
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                rr, cc = r + dr, c + dc
                if 0 <= rr < H and 0 <= cc < W and below[rr, cc] and not maskB[rr, cc]:
                    maskB[rr, cc] = True
                    stack.append((rr, cc))
    inter = np.logical_and(maskA, maskB).sum()
    union = np.logical_or(maskA, maskB).sum()
    iou = inter / union if union else 0
    return record('V5', '淹没连通性（BFS 独立实现互证）',
                  f'两算法栅格 IoU={iou:.4f}（门限 0.99）', iou >= 0.99)

# ---------- V6 瓦片数学 ----------
def v6_tiles():
    print('V6 瓦片数学：deg2num vs WebMercator 参考值')
    def deg2num(lat, lon, z):
        n = 2 ** z
        x = (lon + 180) / 360 * n
        y = (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n
        return x, y
    # 参考值：lat 0/lon 0 任何层级 → (n/2, n/2)；北京(39.9042,116.4074) z10 → 瓦片 (843,388)（OSM Wiki 官方样例）
    x0, y0 = deg2num(0, 0, 10)
    ok0 = abs(x0 - 512) < 1e-9 and abs(y0 - 512) < 1e-9
    xb, yb = deg2num(39.9042, 116.4074, 10)
    ok1 = int(xb) == 843 and int(yb) == 388
    return record('V6', 'WebMercator 瓦片数学（OSM Wiki 样例基准）',
                  f'原点={ok0}；北京z10 → ({xb:.2f},{yb:.2f}) 取整 (843,388)={ok1}', ok0 and ok1)

def main():
    t0 = time.time()
    print('═══ 模块正确性验证套件（oracle 交叉验证）═══')
    G = export_graph()
    print(f'  图导出: {G.number_of_nodes()} 节点 / {G.number_of_edges()} 边（NetworkX）')
    v1_routing(G)
    v2_service_area(G)
    v3_buffer()
    v4_geodesic()
    v5_flood()
    v6_tiles()
    v7_kriging_idw()
    passed = sum(1 for r in RESULTS if r['pass'])
    dt = time.time() - t0
    print(f'═══ {passed}/{len(RESULTS)} 通过 · 耗时 {dt:.1f}s ═══')
    report = {'passed': passed, 'total': len(RESULTS), 'duration_s': round(dt, 1),
              'oracles': ['NetworkX(路径)', '解析几何(缓冲)', 'pyproj/PROJ(测地线)', '经典BFS有源淹没算法', 'WebMercator参考值'],
              'results': RESULTS}
    json.dump(report, open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                        'validation_report.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    print('报告已写入 validation_report.json')
    return passed == len(RESULTS)

# ---------- V7 插值方法互证 ----------
def v7_kriging_idw():
    print('V7 插值互证：IDW（自研） vs OrdinaryKriging（pykrige）——同采样输入，网格相关性与均值偏差')
    import airquality as aq
    idw = aq.idw_surface('pm2_5', 12, 40)
    kr = aq.kriging_surface('pm2_5', 12, 40)
    a = [f['properties']['value'] for f in idw['features']]
    b = [f['properties']['value'] for f in kr['features']]
    n = min(len(a), len(b)); a, b = a[:n], b[:n]
    ma, mb = sum(a)/n, sum(b)/n
    cov = sum((x-ma)*(y-mb) for x, y in zip(a, b))
    sa = (sum((x-ma)**2 for x in a))**.5; sb = (sum((y-mb)**2 for y in b))**.5
    corr = cov/(sa*sb) if sa*sb else 0
    bias = abs(ma-mb)/max(abs(mb), 1e-9)
    ok = corr >= 0.85 and bias <= 0.25
    return record('V7', '插值方法互证（pykrige 基准）',
                  f'相关系数 r={corr:.4f}（门限 0.85）· 均值偏差 {bias:.1%}（门限 25%）', ok)


if __name__ == '__main__':
    sys.exit(0 if main() else 1)
