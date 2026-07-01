#!/usr/bin/env python3
"""
基金历史业绩采集器
运行在数据管道中，无 CORS 限制，直接请求东方财富 API。
输出 fund_history.json，供前端基金估值Tab使用。
"""
import json, os, re
from datetime import datetime, timedelta
from urllib.request import Request, urlopen
import ssl

ssl_ctx = ssl.create_default_context()
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
    'Referer': 'https://fund.eastmoney.com/',
}

BASE = os.path.dirname(__file__)
PRODUCTS_FILE = os.path.join(BASE, 'data', 'products.json')
OUTPUT_FILE = os.path.join(BASE, 'data', 'fund_history.json')
NAV_HISTORY_FILE = os.path.join(BASE, 'data', 'fund_nav_history.json')

def fetch_text(url, timeout=10):
    try:
        req = Request(url, headers=HEADERS)
        with urlopen(req, timeout=timeout, context=ssl_ctx) as resp:
            return resp.read().decode('utf-8', errors='ignore')
    except Exception as e:
        return None

def fetch_fund_navs(code):
    """获取基金历史净值列表"""
    # 使用东方财富 F10 净值数据接口
    url = f'https://fundf10.eastmoney.com/F10DataApi.aspx?type=lsjz&code={code}&page=1&per=400&sdate=2025-06-01&edate=2026-12-31'
    html = fetch_text(url)
    if not html:
        return []
    
    # 解析 HTML table
    rows = re.findall(r'<tr>(.*?)</tr>', html, re.DOTALL)
    navs = []
    for row in rows:
        tds = re.findall(r'<td[^>]*>(.*?)</td>', row, re.DOTALL)
        if len(tds) >= 2:
            date = re.sub(r'<[^>]+>', '', tds[0]).strip()
            nav = re.sub(r'<[^>]+>', '', tds[1]).strip()
            try:
                nav = float(nav)
                if date and len(date) == 10:  # YYYY-MM-DD
                    navs.append({'date': date, 'nav': nav})
            except ValueError:
                pass
    return navs

def compute_performance(navs):
    """从净值序列计算各期收益"""
    if len(navs) < 2:
        return {}
    
    latest = navs[0]['nav']
    dates = sorted([datetime.strptime(n['date'], '%Y-%m-%d') for n in navs])
    data_start = dates[0]
    data_end = dates[-1]
    now = datetime.now()
    
    periods = {'1m': 30, '3m': 90, '6m': 180, '1y': 365}
    result = {}
    
    for key, days in periods.items():
        target = now - timedelta(days=days)
        # 检查数据范围是否覆盖目标日期
        if target < data_start:
            result[key] = None  # 数据不足
            continue
        # 找目标日期前后最近的实际净值
        closest = min(navs, key=lambda n: abs(
            datetime.strptime(n['date'], '%Y-%m-%d') - target
        ))
        if closest:
            ret = (latest - closest['nav']) / closest['nav'] * 100
            result[key] = round(ret, 2)
    
    # 连续涨跌天数
    streak = 0
    up = None
    if len(navs) >= 2:
        up = navs[0]['nav'] >= navs[1]['nav']
        for i in range(len(navs) - 1):
            is_up = navs[i]['nav'] >= navs[i+1]['nav']
            if is_up == up:
                streak += 1
            else:
                break
    result['streak'] = streak
    result['streak_up'] = up
    
    return result

def main():
    print('📊 采集基金历史业绩...')
    
    with open(PRODUCTS_FILE) as f:
        products = json.load(f)
    
    funds = [p for p in products if p.get('product_category') == '基金']
    codes = [str(f['product_id']) for f in funds if len(str(f.get('product_id', ''))) >= 6]
    
    history = {}
    nav_history = {}  # 新增：完整净值历史 {code: {date: nav, ...}}
    for i, code in enumerate(codes):
        print(f'  [{i+1}/{len(codes)}] {code}', end=' ')
        navs = fetch_fund_navs(code)
        if navs:
            perf = compute_performance(navs)
            history[code] = perf
            # 保存净值历史 {date: nav}
            nav_history[code] = {n['date']: n['nav'] for n in navs}
            print(f'✓ {len(navs)}条净值 1m:{perf.get("1m","?")}%')
        else:
            print('✗ 无数据')
    
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, 'w') as f:
        json.dump(history, f, ensure_ascii=False, indent=2)
    print(f'✅ fund_history.json ({len(history)}只)')
    
    with open(NAV_HISTORY_FILE, 'w') as f:
        json.dump(nav_history, f, ensure_ascii=False, separators=(',',':'))
    print(f'✅ fund_nav_history.json ({len(nav_history)}只, {os.path.getsize(NAV_HISTORY_FILE)} bytes)')

if __name__ == '__main__':
    main()
