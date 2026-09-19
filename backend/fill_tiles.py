# -*- coding: utf-8 -*-
"""市域瓦片补漏：z8-z12 覆盖福州市域 bbox+1 圈边缘，跳过已存在文件。
依据 playbook 404 清零法；直连 OSM（URL 不带 /tiles 前缀，坑 R2）。"""
import math, os, time, urllib.request

TILE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'tiles')
W, S, E, N = 118.55, 25.35, 120.05, 26.75   # 市域 bbox（FACTS.md）
MARGIN = 1                                   # 视口外扩一圈
UA = {'User-Agent': 'FJAU-GIS-Course/2.0 (air-quality platform tile cache backfill)'}

def tile_range(z):
    n = 2 ** z
    x0 = int((W + 180) / 360 * n) - MARGIN
    x1 = int((E + 180) / 360 * n) + MARGIN
    y0 = int((1 - math.asinh(math.tan(math.radians(N))) / math.pi) / 2 * n) - MARGIN
    y1 = int((1 - math.asinh(math.tan(math.radians(S))) / math.pi) / 2 * n) + MARGIN
    return range(x0, x1 + 1), range(y0, y1 + 1)

def main():
    got = miss = skip = 0
    for z in (8, 9, 10, 11, 12):
        xs, ys = tile_range(z)
        for x in xs:
            for y in ys:
                path = os.path.join(TILE_DIR, str(z), str(x), f'{y}.png')
                if os.path.exists(path):
                    skip += 1
                    continue
                url = f'https://tile.openstreetmap.org/{z}/{x}/{y}.png'
                try:
                    req = urllib.request.Request(url, headers=UA)
                    with urllib.request.urlopen(req, timeout=20) as r:
                        data = r.read()
                    os.makedirs(os.path.dirname(path), exist_ok=True)
                    with open(path, 'wb') as f:
                        f.write(data)
                    got += 1
                    time.sleep(0.15)   # 合规限速
                except Exception as e:
                    miss += 1
                    print(f'MISS z{z}/{x}/{y}: {e}')
    print(f'done: fetched={got} skipped={skip} failed={miss}')

if __name__ == '__main__':
    main()
