# -*- coding: utf-8 -*-
"""DEM 预处理：terrarium 瓦片拼接 -> dem.tif -> 多水位情景淹没多边形
产出: data/dem/dem.tif, data/raw/flood_scenarios.geojson, 并入库 flood_levels 表
淹没模型边界（须与文档/答辩口径一致）：
  基于 DEM 静态水位阈值的情景推演（水位-面积关系），并做"与闽江水域连通"约束，
  非水动力数值模拟。
"""
import os, sys, io, json, glob
# PostgreSQL/PostGIS 自带的旧版 proj.db 会经 PROJ_LIB/PROJ_DATA 环境变量污染 Python，
# 强制指向 rasterio 内置的 proj 数据目录（必须是本脚本已知约束，放到 import rasterio 之前）
import rasterio as _r
_proj_dir = os.path.join(os.path.dirname(_r.__file__), 'proj_data')
os.environ['PROJ_LIB'] = _proj_dir
os.environ['PROJ_DATA'] = _proj_dir
import numpy as np
from PIL import Image
import rasterio
from rasterio.transform import from_bounds
from rasterio.features import shapes
from shapely.geometry import shape, mapping
from scipy import ndimage

BASE = os.path.dirname(os.path.abspath(__file__))
DEM_DIR = os.path.join(BASE, '..', 'data', 'dem')
RAW = os.path.join(BASE, '..', 'data', 'raw')
Z = 13
# 研究区范围（与 Overpass 下载一致）
W, S, E, N = 119.19, 26.03, 119.30, 26.10

def tile2lonlat(x, y, z):
    n = 2 ** z
    lon = x / n * 360.0 - 180.0
    lat = np.degrees(np.arctan(np.sinh(np.pi * (1 - 2 * y / n))))
    return lon, lat

def main():
    # [1] 拼接 terrarium 瓦片
    files = sorted(glob.glob(os.path.join(DEM_DIR, f'terr_{Z}_*_*.png')))
    assert files, '未找到 DEM 瓦片'
    xs, ys = [], []
    for f in files:
        _, _, x, y = os.path.basename(f).replace('.png', '').split('_')
        xs.append(int(x)); ys.append(int(y))
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    tw, th = 256, 256
    mosaic = np.zeros(((y1 - y0 + 1) * th, (x1 - x0 + 1) * tw), dtype=np.float64)
    for f in files:
        _, _, xs_, ys_ = os.path.basename(f).replace('.png', '').split('_')
        xs_, ys_ = int(xs_), int(ys_)
        img = np.array(Image.open(f)).astype(np.float64)
        elev = img[:, :, 0] * 256 + img[:, :, 1] + img[:, :, 2] / 256 - 32768
        mosaic[(ys_ - y0) * th:(ys_ - y0 + 1) * th, (xs_ - x0) * tw:(xs_ - x0 + 1) * tw] = elev
    # 裁剪到研究区
    lon_l, lat_t = tile2lonlat(x0, y0, Z)
    lon_r, lat_b = tile2lonlat(x1 + 1, y1 + 1, Z)
    px = (lon_r - lon_l) / mosaic.shape[1]
    py = (lat_t - lat_b) / mosaic.shape[0]
    c0 = int((W - lon_l) / px); c1 = int((E - lon_l) / px)
    r0 = int((lat_t - N) / py); r1 = int((lat_t - S) / py)
    crop = mosaic[r0:r1, c0:c1]
    transform = from_bounds(W, S, E, N, crop.shape[1], crop.shape[0])
    os.makedirs(os.path.join(DEM_DIR), exist_ok=True)
    with rasterio.open(os.path.join(DEM_DIR, 'dem.tif'), 'w', driver='GTiff',
                       height=crop.shape[0], width=crop.shape[1], count=1, dtype='float32',
                       crs='EPSG:4326', transform=transform) as dst:
        dst.write(crop.astype(np.float32), 1)
    print(f'dem.tif: {crop.shape[1]}x{crop.shape[0]}, 高程范围 {crop.min():.1f}~{crop.max():.1f} m')

    # [2] 多水位情景淹没多边形（连通闽江水域约束）
    levels = [6.0, 8.0, 10.0, 12.0, 15.0]
    feats = []
    for lv in levels:
        below = crop < lv
        # 连通性约束：只保留与低洼水网连通的淹没区（8邻域连通域）
        lbl, n = ndimage.label(below, structure=np.ones((3, 3)))
        river_ids = set(np.unique(lbl[(crop < 4.0) & (lbl > 0)]))  # 高程<4m 视为江面种子
        river_ids.discard(0)
        if river_ids:
            mask = np.isin(lbl, list(river_ids))
        else:
            mask = below
        mask = ndimage.binary_opening(mask, np.ones((2, 2)))  # 去椒盐
        polys = [shape(g) for g, v in shapes(mask.astype(np.uint8), mask=mask, transform=transform) if v == 1]
        area_km2 = sum(p.area for p in polys) * 111.32 * 111.32 * np.cos(np.radians(26.06)) if polys else 0
        # 面积粗算（度->km，纬度余弦近似）
        area_km2 = sum(p.area for p in polys) * (111.32 * np.cos(np.radians(26.06))) * 111.32 if polys else 0
        print(f'  水位 {lv}m: 淹没斑块 {len(polys)}, 面积约 {area_km2:.2f} km²')
        for p in polys:
            feats.append({'type': 'Feature',
                          'properties': {'level': lv},
                          'geometry': mapping(p)})
    with open(os.path.join(RAW, 'flood_scenarios.geojson'), 'w', encoding='utf-8') as f:
        json.dump({'type': 'FeatureCollection', 'features': feats}, f, ensure_ascii=False)
    print('flood_scenarios.geojson 完成')

    # [3] 入库（供 SQL 空间叠加：淹没掩膜路网）
    import psycopg2
    from psycopg2.extras import execute_values
    from core import SETTINGS
    conn = psycopg2.connect(host=SETTINGS.DB_HOST, port=SETTINGS.DB_PORT, dbname=SETTINGS.DB_NAME,
                            user=SETTINGS.DB_USER, password=SETTINGS.DB_PASSWORD)
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute('DROP TABLE IF EXISTS flood_levels CASCADE')
    cur.execute('''CREATE TABLE flood_levels (
        fid SERIAL PRIMARY KEY, level_m numeric, geom geometry(MultiPolygon, 4326))''')
    for f in feats:
        cur.execute('INSERT INTO flood_levels (level_m, geom) VALUES (%s, ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326))',
                    (f['properties']['level'], json.dumps(f['geometry'])))
    cur.execute('CREATE INDEX flood_gix ON flood_levels USING GIST(geom)')
    cur.execute('SELECT level_m, count(*), round((SUM(ST_Area(geom::geography))/1000000.0)::numeric, 2) FROM flood_levels GROUP BY level_m ORDER BY level_m')
    for r in cur.fetchall():
        print('   DB:', r)
    conn.close()
    print('淹没情景入库完成')

if __name__ == '__main__':
    main()
