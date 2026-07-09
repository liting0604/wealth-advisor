#!/usr/bin/env python3
"""
科技行业追踪数据采集器 v1.0
运行在 GitHub Actions 上，采集30家国内外头部科技公司实时股价。
数据来源：腾讯证券 qt.gtimg.cn + 新浪 sina.com.cn（A股/港股/美股）。
输出：data/tech_data.json
"""

import json, os, re
from datetime import datetime, timezone, timedelta
from urllib.request import Request, urlopen
import ssl

ssl_context = ssl.create_default_context()
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': '*/*',
    'Accept-Language': 'zh-CN,zh;q=0.9',
}

BASE_DIR = os.path.dirname(__file__)
COMPANIES_FILE = os.path.join(BASE_DIR, 'data', 'tech_companies.json')
OUTPUT = os.path.join(BASE_DIR, 'data', 'tech_data.json')

# 腾讯股票API前缀映射
TENCENT_PREFIX = {
    'SH': 'sh',    # 上海
    'SZ': 'sz',    # 深圳
    'HK': 'hk',    # 港股
    'US': 'us',    # 美股
}


def fetch_text(url, timeout=10):
    """获取文本响应，使用 GBK 解码"""
    try:
        req = Request(url, headers=HEADERS)
        with urlopen(req, timeout=timeout, context=ssl_context) as resp:
            raw = resp.read()
            # 尝试 GBK 解码（腾讯API使用GBK编码）
            try:
                return raw.decode('gbk')
            except:
                return raw.decode('utf-8', errors='ignore')
    except Exception as e:
        return None


def parse_tencent_stock(text, prefix, code):
    """
    解析腾讯股票API返回的数据。
    格式: v_<prefix><code>="<field1>~<field2>~..."
    
    通用字段索引（0-based）:
    - [1]: 名称
    - [3]: 当前价
    - [4]: 昨收
    - [5]: 今开
    - [31]: 涨跌额
    - [32]: 涨跌幅(%)
    - [33]: 最高
    - [34]: 最低
    - [6]: 成交量
    - [39]: 市盈率(TTM)
    
    A股: [45] = 总市值(亿)
    港股: [44] = 总市值(亿)
    美股: [44] = 总市值(亿)
    """
    if not text:
        return None

    # 匹配数据行
    pattern = rf'v_{prefix}{re.escape(code)}="([^"]*)"'
    m = re.search(pattern, text)
    if not m:
        return None

    fields = m.group(1).split('~')
    if len(fields) < 40:
        return None

    try:
        price = float(fields[3]) if fields[3] else None
        prev_close = float(fields[4]) if fields[4] else None
        open_price = float(fields[5]) if fields[5] else None
        change_pct = float(fields[32]) if fields[32] else None
        high = float(fields[33]) if fields[33] else None
        low = float(fields[34]) if fields[34] else None
        volume = float(fields[6]) if fields[6] else None
        pe = float(fields[39]) if fields[39] else None
    except (ValueError, IndexError):
        return None

    # 总市值字段因市场而异
    try:
        if prefix in ('sh', 'sz'):
            # A股: 字段45 = 总市值(亿)
            cap_raw = float(fields[45]) if len(fields) > 45 and fields[45] else None
        else:
            # 港股/美股: 字段44 = 总市值(亿)
            cap_raw = float(fields[44]) if len(fields) > 44 and fields[44] else None
    except (ValueError, IndexError):
        cap_raw = None

    # 格式化市值
    def fmt_cap(val, mkt):
        if val is None or val == 0:
            return '—'
        yi = val  # 已经是亿单位
        if yi >= 10000:
            return f'{yi/10000:.1f}万亿'
        return f'{yi:.0f}亿'

    currency_map = {'sh': 'CNY', 'sz': 'CNY', 'hk': 'HKD', 'us': 'USD'}

    return {
        'price': round(price, 2),
        'change_pct': round(change_pct, 2) if change_pct else 0,
        'open': round(open_price, 2) if open_price else None,
        'high': round(high, 2) if high else None,
        'low': round(low, 2) if low else None,
        'prev_close': round(prev_close, 2) if prev_close else None,
        'pe': round(pe, 2) if pe else None,
        'market_cap': fmt_cap(cap_raw, prefix),
        'volume': int(volume) if volume else None,
        'currency': currency_map.get(prefix, ''),
    }


def fetch_stock_batch(companies):
    """
    批量获取股票数据。
    腾讯API支持一次请求多只同市场股票（用逗号分隔）。
    """
    # 按市场分组
    groups = {}
    for c in companies:
        mkt = c['market']
        if mkt not in groups:
            groups[mkt] = []
        groups[mkt].append(c)

    results = {}

    for mkt, comps in groups.items():
        prefix = TENCENT_PREFIX[mkt]
        codes = ','.join([f'{prefix}{c["code"]}' for c in comps])
        url = f'https://qt.gtimg.cn/q={codes}'

        text = fetch_text(url, timeout=15)
        if not text:
            print(f'  ⚠ {mkt} 批量请求失败')
            for c in comps:
                results[c['code']] = None
            continue

        for c in comps:
            data = parse_tencent_stock(text, TENCENT_PREFIX[c['market']], c['code'])
            results[c['code']] = data
            status = '✓' if data else '✗'
            print(f'  {status} {c["name"]} ({c["code"]}) [{c["market"]}]')

    return results


def main():
    now = datetime.now(timezone(timedelta(hours=8)))
    print(f'🔬 科技行业数据采集 v1.0 | {now.strftime("%Y-%m-%d %H:%M:%S")}')

    # 读取公司列表
    with open(COMPANIES_FILE, 'r', encoding='utf-8') as f:
        companies = json.load(f)

    print(f'📋 共 {len(companies)} 家公司，按市场分组批量获取...')

    # 批量获取股价
    stock_data = fetch_stock_batch(companies)

    # 合并结果
    results = []
    success = 0
    for c in companies:
        code = c['code']
        sd = stock_data.get(code)

        entry = {
            'code': code,
            'market': c['market'],
            'name': c['name'],
            'en_name': c.get('en_name', ''),
            'sector': c.get('sector', ''),
            'sub_sector': c.get('sub_sector', ''),
            'description': c.get('description', ''),
            'ceo': c.get('ceo', ''),
            'founded': c.get('founded'),
            'headquarters': c.get('headquarters', ''),
            'business': c.get('business', None),
            'rd_focus': c.get('rd_focus', ''),
            'supply_chain': c.get('supply_chain', None),
            'financials': c.get('financials', None),
            'recent_news': c.get('recent_news', ''),
            'trend': c.get('trend', ''),
            'stock': sd if sd else {
                'price': None, 'change_pct': None, 'pe': None,
                'market_cap': '—', 'currency': ''
            },
            'fetch_status': 'ok' if sd else 'failed',
        }

        if sd:
            success += 1
        results.append(entry)

    # 构建输出
    output = {
        'updated': now.isoformat(),
        'updated_display': now.strftime('%Y-%m-%d %H:%M'),
        'total': len(results),
        'success': success,
        'failed': len(results) - success,
        'companies': results,
    }

    os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)
    with open(OUTPUT, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f'\n✅ tech_data.json 已生成 ({os.path.getsize(OUTPUT)} bytes)')
    print(f'   成功: {success}/{len(companies)}, 失败: {len(companies)-success}/{len(companies)}')
    return OUTPUT


if __name__ == '__main__':
    main()
