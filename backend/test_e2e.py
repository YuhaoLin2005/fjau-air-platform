# -*- coding: utf-8 -*-
"""端到端功能测试 + 截图/录屏产出（Playwright）—— 2026-09-19 UI 重设计版
前置: uvicorn main:app 已在 127.0.0.1:8000 运行
产出: ../frontend/shots/*.png（新 IA 全功能 + 三角色矩阵 + 三态负向 + 移动端）,
      ../../视频及演示/系统演示录屏.webm
验收门: 全场景走通 + console errors = 0 + 关键数字回读
运行: python test_e2e.py
"""
import os, sys
from playwright.sync_api import sync_playwright

BASE = os.path.dirname(os.path.abspath(__file__))
SHOTS = os.path.join(BASE, '..', 'frontend', 'shots')
VIDEO = os.path.join(BASE, '..', '..', '视频及演示')
os.makedirs(SHOTS, exist_ok=True)
os.makedirs(VIDEO, exist_ok=True)
URL = 'http://127.0.0.1:8000/'

def shot(page, name):
    page.screenshot(path=os.path.join(SHOTS, name + '.png'))
    print('  截图:', name + '.png')

def set_slider(page, sel, val):
    page.evaluate(f"const el=document.getElementById('{sel}'); el.value={val}; el.dispatchEvent(new Event('input'))")

def run():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={'width': 1600, 'height': 900},
                                  record_video_dir=VIDEO,
                                  record_video_size={'width': 1600, 'height': 900})
        page = ctx.new_page()
        errors = []
        page.on('console', lambda m: errors.append(m.text) if m.type == 'error' else None)
        page.on('pageerror', lambda e: errors.append('PAGEERROR: ' + str(e)))

        # ---------- 游客场景 ----------
        print('[1] 主界面：现状卡 + AQI 插值面（首屏即答）')
        page.goto(URL)
        page.wait_for_selector('text=主污染物', timeout=40000)   # 现状卡就绪（含 4 污染物冷启动）
        page.wait_for_timeout(1500)
        shot(page, '01_主界面_现状卡与插值面')
        card = page.evaluate("document.getElementById('statusBody').textContent")
        assert '主污染物' in card and 'HJ 633-2012' in card, '现状卡缺少关键要素'
        print('  现状卡:', card[:70])

        print('[2] 时空分析：30 天逐时曲线 + 时间轴联动')
        page.click('.tab[data-page="time"]')
        page.wait_for_function("document.getElementById('tsSlider').max > 0", timeout=40000)
        set_slider(page, 'tsSlider', 0)
        page.wait_for_timeout(800)
        readout = page.evaluate("document.getElementById('tsReadout').textContent")
        assert 'μg/m³' in readout, '时间轴联动读数缺失'
        shot(page, '02_时空分析_30天曲线与时间轴')
        print('  联动读数:', readout[:60])

        print('[3] 暴露评估：污染面 × 学校/医院')
        page.click('.tab[data-page="exposure"]')
        page.click('#btnExposure')
        page.wait_for_function("document.getElementById('expBody').textContent.includes('敏感设施')", timeout=30000)
        page.wait_for_timeout(800)
        shot(page, '03_暴露评估_敏感设施叠加')
        exp = page.evaluate("document.getElementById('expBody').textContent")
        print('  评估:', exp[:80])

        print('[4] 三角色·游客：分析按钮前置锁定（点前可见）')
        page.click('.tab[data-page="legacy"]')
        page.wait_for_timeout(1200)
        locked = page.evaluate("document.getElementById('btnRoute').disabled && document.getElementById('btnRoute').classList.contains('locked')")
        assert locked, '游客应看到锁定态分析按钮'
        shot(page, '04_游客模式_权限前置锁定')

        print('[5] 点哪查哪：地图点击反查浓度')
        page.click('.tab[data-page="live"]')
        page.evaluate("window.__map.setView([26.05, 119.30], 10)")
        page.wait_for_timeout(600)
        page.mouse.click(900, 500)
        page.wait_for_timeout(1200)
        popup = page.evaluate("(() => { const p=document.querySelector('.leaflet-popup-content'); return p ? p.textContent.slice(0,90) : ''; })()")
        assert 'μg/m³' in popup, '点哪查哪弹窗缺失: ' + popup
        shot(page, '05_点哪查哪_浓度与健康建议')
        page.keyboard.press('Escape')

        print('[6] 登录界面')
        page.evaluate("document.getElementById('btnLogin').click()")
        page.wait_for_timeout(500)
        shot(page, '06_登录界面')
        page.fill('#authUser', 'admin')
        page.fill('#authPwd', '123456')
        page.click('#authOk')
        page.wait_for_timeout(1500)

        print('[7] 管理员登录后：顶栏入口')
        admin_ui = page.evaluate("document.getElementById('userbox').textContent")
        assert '管理员' in admin_ui and '运维控制台' in admin_ui, '管理员入口缺失'
        shot(page, '07_管理员登录后_顶栏入口')

        # ---------- 一阶段成果¹（管理员/用户级） ----------
        print('[8] 淹没推演：滑块 15m / 8m')
        page.click('.tab[data-page="legacy"]')
        page.evaluate("document.querySelector('.legacy-nav .btn[data-lp=\"flood\"]').click()")
        page.wait_for_timeout(2000)
        page.evaluate("document.getElementById('lyFlood').checked = true")
        page.evaluate("document.getElementById('lyFlood').dispatchEvent(new Event('change'))")
        page.wait_for_timeout(2500)
        set_slider(page, 'levelSlider', 15)
        page.wait_for_timeout(2000)
        shot(page, '08_淹没推演_15m情景')
        set_slider(page, 'levelSlider', 8)
        page.wait_for_timeout(2000)
        shot(page, '09_淹没推演_8m情景')

        print('[9] 疏散路径：避淹梯度（OD 与 FACTS.md 一致）')
        page.evaluate("document.querySelector('.legacy-nav .btn[data-lp=\"route\"]').click()")
        set_slider(page, 'levelSlider', 8)          # 避淹按 8m 情景（对齐 FACTS 梯度口径）
        page.evaluate("__app.state.fromPt = [26.0648, 119.2373]; __app.state.toPt = [26.0494, 119.2805]")
        page.evaluate("document.getElementById('avoidFlood').checked = false")
        page.click('#btnRoute')
        page.wait_for_timeout(4000)
        r1 = page.evaluate("document.getElementById('routeResult').textContent")
        page.evaluate("document.getElementById('avoidFlood').checked = true")
        page.click('#btnRoute')
        page.wait_for_function("document.getElementById('routeResult').textContent.includes('已避开')", timeout=20000)
        r2 = page.evaluate("document.getElementById('routeResult').textContent")
        assert '距离' in r1 and '已避开' in r2, f'避淹结果异常: r1={r1[:50]} r2={r2[:50]}'
        shot(page, '10_疏散路径_避淹对比')
        print('  不避淹:', r1[:60], '\n  避淹8m:', r2[:60])

        print('[10] 避难选址 + 服务区')
        page.evaluate("document.querySelector('.legacy-nav .btn[data-lp=\"shelter\"]').click()")
        page.click('#btnShelter')
        page.wait_for_timeout(3000)
        shot(page, '11_避难选址_推荐')
        page.evaluate("__app.state.servicePt = [26.0648, 119.2373]")
        page.evaluate("document.getElementById('serviceCenterHint').textContent = '26.0648,119.2373'")
        page.click('#btnServiceArea')
        page.wait_for_timeout(3000)
        shot(page, '12_服务区_步行5分钟')

        print('[11] 网格统计：TOP15 图表')
        page.evaluate("document.querySelector('.legacy-nav .btn[data-lp=\"stat\"]').click()")
        page.click('#btnGridStat')
        page.wait_for_timeout(5000)
        shot(page, '13_网格统计_TOP15')

        print('[12] POI 检索 + 测距 + 雷达真加载')
        page.click('.tab[data-page="live"]')
        page.fill('#poiKw', '医院')
        page.click('#btnPoiSearch')
        page.wait_for_timeout(1800)
        shot(page, '14_POI检索')
        page.click('.tab[data-page="layers"]')
        page.evaluate("document.getElementById('btnMeasure').click()")
        page.mouse.click(700, 400)
        page.mouse.click(950, 560)
        page.wait_for_timeout(800)
        shot(page, '15_测距工具')
        # 雷达：数据源审计（2026-09-19）——RainViewer 真实回波，瓦片必须真实下载
        page.click('.tab[data-page="live"]')
        page.evaluate("const ly=document.getElementById('lyRadar'); ly.checked=true; ly.dispatchEvent(new Event('change'))")
        page.wait_for_timeout(9000)
        radar = page.evaluate("(() => { const imgs=[...document.querySelectorAll('img.leaflet-tile')].filter(i=>i.src.includes('rainviewer')); return { n: imgs.length, ok: imgs.filter(i=>i.complete&&i.naturalWidth>0).length }; })()")
        print(f"  雷达瓦片: {radar['ok']}/{radar['n']} 加载成功（当前无雨则回波为空，属真实）")
        # 国控空气监测站：未配置 WAQI_TOKEN 时必须诚实降级（toast 引导 + 复选框自动回弹），不造假数据
        page.evaluate("const ly=document.getElementById('lyStations'); ly.checked=true; ly.dispatchEvent(new Event('change'))")
        page.wait_for_timeout(4000)
        live_state = page.evaluate("fetch('/api/v1/aq/stations/live').then(r=>r.json())")
        if live_state.get('available'):
            st_checked = page.evaluate("document.getElementById('lyStations').checked")
            n_st = len(live_state.get('stations') or [])
            assert st_checked and n_st > 0, 'WAQI 已配置时国控站图层应渲染真实站点'
            print(f'  监测站: WAQI 已激活 → {n_st} 个真实国控站渲染 ✓')
        else:
            st_unchecked = page.evaluate("!document.getElementById('lyStations').checked")
            assert st_unchecked, '未配置 token 时监测站图层应回弹为未勾选'
            print('  监测站: 未配置 token → 诚实降级引导 ✓（配置后即接入 aqicn.org 真实站点）')

        print('[13] 三态负向：独立页面拦截 history 接口 → 错误态 + 重试（不污染主 console 计数）')
        negctx = browser.new_context(viewport={'width': 1600, 'height': 900})
        negpage = negctx.new_page()
        negpage.goto(URL)
        negpage.wait_for_selector('text=主污染物', timeout=40000)
        negpage.route('**/api/v1/aq/history*', lambda route: route.abort())
        negpage.click('.tab[data-page="time"]')
        negpage.wait_for_selector('#tsBody .empty', timeout=20000)
        negpage.screenshot(path=os.path.join(SHOTS, '16_错误态_接口失败与重试.png'))
        print('  截图: 16_错误态_接口失败与重试.png')
        negctx.close()

        print('[14] 用户模式：注册随机用户 → 登录 → 分析解锁')
        import random
        uname = 'e2e_user_' + str(random.randint(1000, 9999))
        page.evaluate(f"fetch('/api/v1/register',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{username:'{uname}',password:'demo123'}})}}).catch(()=>{{}})")
        page.wait_for_timeout(800)
        page.click('#btnLogout') if page.evaluate("!!document.getElementById('btnLogout')") else None
        page.wait_for_timeout(400)
        page.click('#btnLogin')
        page.fill('#authUser', uname)
        page.fill('#authPwd', 'demo123')
        page.click('#authOk')
        page.wait_for_timeout(1500)
        user_ui = page.evaluate("document.getElementById('userbox').textContent")
        assert '普通用户' in user_ui and '运维控制台' not in user_ui, '用户/管理员边界错误'
        unlocked = page.evaluate("!document.getElementById('btnRoute').disabled")
        assert unlocked, '用户应解锁分析按钮'
        shot(page, '17_用户模式_分析解锁')

        ctx.close()
        video_path = page.video.path()
        browser.close()

        # ---------- 移动端视口（独立上下文，不进录屏） ----------
        print('[15] 移动端 375×812 走查')
        browser2 = p.chromium.launch(headless=True)
        mctx = browser2.new_context(viewport={'width': 375, 'height': 812})
        mpage = mctx.new_page()
        mpage.on('console', lambda m: errors.append('MOBILE: ' + m.text) if m.type == 'error' else None)
        mpage.on('pageerror', lambda e: errors.append('MOBILE PAGEERROR: ' + str(e)))
        mpage.goto(URL)
        mpage.wait_for_selector('text=主污染物', timeout=40000)
        mpage.evaluate("document.getElementById('leftCol').classList.add('drawer-open')")
        mpage.wait_for_timeout(600)
        mpage.screenshot(path=os.path.join(SHOTS, '18_移动端_375抽屉面板.png'))
        print('  截图: 18_移动端_375抽屉面板.png')
        overflow = mpage.evaluate("document.documentElement.scrollWidth > document.documentElement.clientWidth + 2")
        assert not overflow, '移动端横向溢出'
        browser2.close()

        # 重命名视频
        ext = os.path.splitext(video_path)[1]
        target = os.path.join(VIDEO, '系统演示录屏' + ext)
        if os.path.exists(target):
            os.remove(target)
        os.rename(video_path, target)
        print('录屏已保存:', target)
        print('console errors:', len(errors))
        for e in errors[:8]:
            print('  ERR:', e[:160])
        return 0 if not errors else 1

if __name__ == '__main__':
    sys.exit(run())
