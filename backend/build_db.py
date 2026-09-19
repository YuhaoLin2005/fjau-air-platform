# -*- coding: utf-8 -*-
"""数据入库管线：OSM 路网 GeoJSON -> PostGIS 路网表 -> pgRouting 拓扑
用法: python build_db.py
前置: raw/fuzhou_roads.json (Overpass 一次下载落盘), 数据库 gis_flood(postgis+pgrouting)
"""
import json, os, sys, io
import psycopg2
from psycopg2.extras import execute_values

BASE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(BASE, '..', 'data', 'raw')

from core import SETTINGS
DB = dict(host=SETTINGS.DB_HOST, port=SETTINGS.DB_PORT, dbname=SETTINGS.DB_NAME,
           user=SETTINGS.DB_USER, password=SETTINGS.DB_PASSWORD)

def main():
    print('[1/5] 读取 Overpass 数据...')
    with open(os.path.join(RAW, 'fuzhou_roads.json'), encoding='utf-8') as f:
        data = json.load(f)
    nodes = {e['id']: (e['lon'], e['lat']) for e in data['elements'] if e['type'] == 'node'}
    ways = [e for e in data['elements'] if e['type'] == 'way' and 'highway' in e.get('tags', {})]
    print(f'  节点 {len(nodes)}, 道路 {len(ways)}')

    conn = psycopg2.connect(**DB)
    conn.autocommit = True
    cur = conn.cursor()
    print('[2/5] 建表...')
    cur.execute('DROP TABLE IF EXISTS roads CASCADE')
    cur.execute('''CREATE TABLE roads (
        gid SERIAL PRIMARY KEY,
        osm_id BIGINT,
        name text,
        highway text,
        oneway boolean DEFAULT false,
        maxspeed numeric,
        bridge boolean DEFAULT false,
        geom geometry(LineString, 4326))''')

    print('[3/5] 写入路网...')
    rows = []
    for w in ways:
        t = w.get('tags', {})
        nds = w.get('nodes', [])
        if len(nds) < 2:
            continue
        pts = [nodes[n] for n in nds if n in nodes]
        if len(pts) < 2:
            continue
        wkt = 'LINESTRING(' + ','.join(f'{x:.7f} {y:.7f}' for x, y in pts) + ')'
        rows.append((w['id'], t.get('name'), t.get('highway'),
                     t.get('oneway') in ('yes', 'true', '1'),
                     t.get('maxspeed'), t.get('bridge') in ('yes', 'true', '1'), wkt))
    execute_values(cur, '''INSERT INTO roads (osm_id,name,highway,oneway,maxspeed,bridge,geom)
        VALUES %s''', rows, page_size=500)
    cur.execute("CREATE INDEX roads_gix ON roads USING GIST(geom)")
    print(f'  入库 {len(rows)} 条路段')

    print('[4/5] 构建路网拓扑 (pgr_nodeNetwork + pgr_createTopology)...')
    cur.execute('DROP TABLE IF EXISTS roads_noded CASCADE')
    cur.execute("SELECT pgr_nodeNetwork('roads', 0.00001, id:='gid', the_geom:='geom')")
    cur.execute("DROP TABLE IF EXISTS roads_noded_vertices_pgr CASCADE")
    cur.execute("SELECT pgr_createTopology('roads_noded', 0.00001, the_geom:='geom', id:='id', source:='source', target:='target')")
    # 打拓扑质量报告
    cur.execute('''SELECT count(*) FROM roads_noded_vertices_pgr''')
    v = cur.fetchone()[0]
    cur.execute('SELECT count(*) FROM roads_noded')
    e = cur.fetchone()[0]
    cur.execute('''SELECT count(*) FROM (
        SELECT a.id FROM roads_noded_vertices_pgr a
        LEFT JOIN roads_noded s ON s.source=a.id
        LEFT JOIN roads_noded t ON t.target=a.id
        WHERE s.id IS NULL AND t.id IS NULL) q''')
    dead = cur.fetchone()[0]
    print(f'  拓扑节点 {v}, 边 {e}, 孤立节点 {dead}')

    print('[5/5] 建分析辅助视图...')
    cur.execute('''CREATE OR REPLACE VIEW v_road_network AS
        SELECT n.id AS gid, n.source, n.target, r.name, r.highway,
               ST_Length(n.geom::geography) AS length_m,
               CASE WHEN r.highway IN ('motorway','trunk','primary') THEN 60
                    WHEN r.highway IN ('secondary','tertiary') THEN 40
                    WHEN r.highway IN ('residential','unclassified','living_street') THEN 30
                    ELSE 15 END AS speed_kmh,
               n.geom
        FROM roads_noded n JOIN roads r ON r.gid = n.old_id''')
    # POI 入库
    with open(os.path.join(RAW, 'fuzhou_pois.json'), encoding='utf-8') as f:
        pdata = json.load(f)
    cur.execute('DROP TABLE IF EXISTS pois CASCADE')
    cur.execute('''CREATE TABLE pois (
        pid SERIAL PRIMARY KEY, osm_id BIGINT, name text, category text,
        geom geometry(Geometry, 4326))''')
    prows = []
    for el in pdata['elements']:
        t = el.get('tags', {})
        cat = None
        if 'amenity' in t: cat = t['amenity']
        elif 'leisure' in t: cat = t['leisure']
        elif t.get('emergency') == 'assembly_point': cat = 'assembly_point'
        elif t.get('building') == 'stadium': cat = 'stadium'
        if not cat: continue
        if el['type'] == 'node':
            wkt = f"POINT({el['lon']:.7f} {el['lat']:.7f})"
        elif el['type'] in ('way', 'relation'):
            nds = [nodes[n] for n in el.get('nodes', []) if n in nodes] if 'nodes' in el else []
            if el['type'] == 'relation':
                continue
            if len(nds) >= 4:
                if nds[0] != nds[-1]:
                    nds = nds + [nds[0]]
                wkt = 'POLYGON((' + ','.join(f'{x:.7f} {y:.7f}' for x, y in nds) + '))'
            elif len(nds) >= 2:
                wkt = 'LINESTRING(' + ','.join(f'{x:.7f} {y:.7f}' for x, y in nds) + ')'
            else:
                continue
        else:
            continue
        prows.append((el['id'], t.get('name'), cat, wkt))
    execute_values(cur, 'INSERT INTO pois (osm_id,name,category,geom) VALUES %s',
                   [(r[0], r[1], r[2], f"SRID=4326;{r[3]}") for r in prows], page_size=500)
    cur.execute('CREATE INDEX pois_gix ON pois USING GIST(geom)')
    cur.execute("CREATE INDEX pois_cat_idx ON pois(category)")
    print(f'  POI 入库 {len(prows)} 条')
    cur.execute('SELECT category, count(*) FROM pois GROUP BY category ORDER BY 2 DESC LIMIT 10')
    for r in cur.fetchall():
        print('   ', r)

    print('[6/6] 连通分量分析 + 路由视图（最大分量过滤）...')
    cur.execute('ALTER TABLE roads_noded ADD COLUMN IF NOT EXISTS comp bigint')
    cur.execute('''UPDATE roads_noded n SET comp = c.component
        FROM (SELECT node, component FROM pgr_connectedComponents(
              'SELECT id, source, target, 1 AS cost FROM roads_noded')) c
        WHERE n.source = c.node''')
    cur.execute('SELECT comp, count(*) FROM roads_noded GROUP BY comp ORDER BY 2 DESC')
    comps = cur.fetchall()
    main_comp = comps[0][0]
    print(f'  连通分量 {len(comps)} 个，最大分量 {main_comp} 含 {comps[0][1]}/{sum(c[1] for c in comps)} 条边')
    cur.execute('DROP VIEW IF EXISTS v_route')
    cur.execute(f'''CREATE VIEW v_route AS
        SELECT n.id AS eid, n.source, n.target, r.name, r.highway, coalesce(r.bridge,false) AS bridge,
               ST_Length(n.geom::geography) AS length_m,
               CASE WHEN r.highway IN ('motorway','trunk','primary') THEN 60
                    WHEN r.highway IN ('secondary','tertiary') THEN 40
                    WHEN r.highway IN ('residential','unclassified','living_street') THEN 30
                    ELSE 15 END AS speed_kmh,
               n.geom
        FROM roads_noded n JOIN roads r ON r.gid = n.old_id
        WHERE n.comp = {main_comp}''')
    conn.close()
    print('完成。')

if __name__ == '__main__':
    main()
