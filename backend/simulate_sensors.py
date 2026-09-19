# -*- coding: utf-8 -*-
"""IoT 感知层模拟器：按一场合成暴雨事件生成各站遥测序列
用法: python simulate_sensors.py [--hours 6 --step-min 10]
口径声明：模拟数据源（教学演示），站点布设位置为研究区易涝点示意
"""
import sys, io, time, math, random, argparse
from core import get_conn, query, log

def main(hours=6, step_min=10):
    with get_conn() as c:
        cur = c.cursor()
        sensors = query(cur, 'SELECT sid, type, name FROM sensors ORDER BY sid')
        assert sensors, '无传感器，请先启动 main:app 完成初始化'
        # 清空旧遥测，重放一场完整事件
        cur.execute('DELETE FROM telemetry')
        now = time.time()
        n_steps = int(hours * 60 / step_min)
        for i in range(n_steps):
            # 暴雨过程：雨峰位于窗口 70% 处——事件结束时仍处于黄/橙预警区间（"正在发生"的演示语义）
            frac = i / max(1, n_steps - 1)
            intensity = math.exp(-((frac - 0.7) ** 2) / 0.08)   # 高斯雨峰
            ts = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(now - (n_steps - 1 - i) * step_min * 60))
            for s in sensors:
                noise = random.uniform(0.9, 1.1)
                if s['type'] == 'rain':
                    rain = round(120.0 * intensity * noise, 1)     # 峰值 120mm/h → 可触红
                    cur.execute('INSERT INTO telemetry (sid, rain_1h, ts) VALUES (%s,%s,%s)', (s['sid'], rain, ts))
                else:
                    # 积水/水位随雨峰累积滞后：depth 站最高 ~0.95m，water 站 ~0.8m
                    peak = 0.95 if s['type'] == 'depth' else 0.80
                    lag = max(0.0, frac - 0.08)
                    water = round(peak * math.exp(-((lag - 0.78) ** 2) / 0.10) * noise, 2)
                    cur.execute('INSERT INTO telemetry (sid, water_m, ts) VALUES (%s,%s,%s)', (s['sid'], water, ts))
        c.commit()
        cur.execute('SELECT count(*) FROM telemetry')
        n = cur.fetchone()[0]
    log.info('模拟遥测写入完成: %d 站 x %d 步 = %d 条（事件窗口 %s h / 步长 %s min）',
             len(sensors), n_steps, n, hours, step_min)

if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--hours', type=float, default=6)
    ap.add_argument('--step-min', type=float, default=10)
    a = ap.parse_args()
    main(a.hours, a.step_min)
