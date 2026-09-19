# -*- coding: utf-8 -*-
"""并发基准压测：核心端点 QPS / P95 / 错误率（工业级证据产出）
用法: python benchmark.py [--c 20 --n 200]
"""
import sys, io, time, json, threading, argparse, statistics, urllib.request
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

BASE = 'http://127.0.0.1:8000'

def hit(path):
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(BASE + path, timeout=30) as r:
            r.read()
        return time.perf_counter() - t0, None
    except Exception as e:
        return time.perf_counter() - t0, str(e)[:80]

def bench(name, path, concurrency, total):
    lat, errs = [], []
    lock = threading.Lock()
    per = max(1, total // concurrency)
    def worker():
        for _ in range(per):
            dt, e = hit(path)
            with lock:
                lat.append(dt)
                if e:
                    errs.append(e)
    threads = [threading.Thread(target=worker) for _ in range(concurrency)]
    t0 = time.perf_counter()
    for t in threads: t.start()
    for t in threads: t.join()
    wall = time.perf_counter() - t0
    lat.sort()
    n = len(lat)
    qps = n / wall
    p50 = lat[n // 2] * 1000
    p95 = lat[int(n * 0.95)] * 1000
    err_rate = len(errs) / n * 100
    print(f'{name:22s} c={concurrency:<3d} n={n:<5d} QPS={qps:8.1f} P50={p50:7.1f}ms P95={p95:8.1f}ms err={err_rate:.1f}%')
    return {'name': name, 'concurrency': concurrency, 'n': n, 'qps': round(qps, 1),
            'p50_ms': round(p50, 1), 'p95_ms': round(p95, 1), 'err_rate': round(err_rate, 2)}

if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--c', type=int, default=20)
    ap.add_argument('--n', type=int, default=200)
    a = ap.parse_args()
    print(f'基准压测 · 并发 {a.c} · 目标请求数 {a.n} · {BASE}')
    print('-' * 78)
    results = []
    results.append(bench('health', '/health', 4, 40))
    results.append(bench('route(避淹路径)', '/api/v1/route?flon=119.236&flat=26.065&tlon=119.28&tlat=26.05&mode=car&avoid_flood=true&level=8', a.c, a.n))
    results.append(bench('service_area', '/api/v1/service_area?lon=119.236&lat=26.065&minutes=5&mode=walk', a.c, a.n))
    results.append(bench('sensors+alerts', '/api/v1/alerts/current', a.c, a.n))
    results.append(bench('ogc items(pois)', '/ogc/collections/pois/items?limit=100', a.c, a.n))
    print('-' * 78)
    json.dump(results, open('benchmark_result.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('结果已写入 benchmark_result.json')
