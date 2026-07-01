#!/usr/bin/env python3
"""
全自动云端数据采集器 v2.0
运行在 GitHub Actions 上，无需手动触发。
采集实时市场数据 + RSS真实财经新闻，输出 market_input.json。
同时存档历史数据到 data/history/。
"""

import json, os, re, shutil, xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from urllib.request import Request, urlopen
from urllib.error import URLError
import ssl

ssl_context = ssl.create_default_context()
HEADERS = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36', 'Referer': 'https://data.eastmoney.com/'}

BASE_DIR = os.path.dirname(__file__)
OUTPUT = os.path.join(BASE_DIR, 'data', 'market_input.json')
HISTORY_DIR = os.path.join(BASE_DIR, 'data', 'history')

def fetch_json(url, timeout=10):
    try:
        req = Request(url, headers=HEADERS)
        with urlopen(req, timeout=timeout, context=ssl_context) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except Exception as e:
        print(f'  ⚠ 请求失败 {url[:60]}: {e}')
        return None

def fetch_text(url, timeout=10):
    try:
        req = Request(url, headers=HEADERS)
        with urlopen(req, timeout=timeout, context=ssl_context) as resp:
            return resp.read().decode('utf-8', errors='ignore')
    except Exception as e:
        print(f'  ⚠ 请求失败 {url[:60]}: {e}')
        return None

# ============================================================
# 实时数据采集
# ============================================================

def fetch_a_share():
    """从东方财富免费接口获取上证指数"""
    try:
        data = fetch_json('https://push2.eastmoney.com/api/qt/stock/get?secid=1.000001&fields=f43,f44,f45,f46,f47,f48,f50,f57,f58,f60,f169,f170')
        if data and data.get('data'):
            d = data['data']
            price = d.get('f43', 0) / 100.0 if d.get('f43') else 0
            change_pct = d.get('f170', 0) / 100.0 if d.get('f170') else 0
            if price > 0:
                trend = '震荡偏强' if change_pct > 0.5 else ('震荡偏弱' if change_pct < -0.5 else '窄幅震荡')
                return f'{int(price)}点附近', trend, change_pct
    except: pass
    return '4000-4100点区间', '震荡偏强', 0.5

def fetch_gold():
    """获取国际金价"""
    try:
        data = fetch_json('https://api.gold-api.com/price/XAU')
        if data and data.get('price'):
            price = data['price']
            return f'约{int(price)}美元/盎司', '震荡'
    except: pass
    return '约4200美元/盎司', '高位震荡'

def fetch_fx():
    """获取美元兑人民币汇率"""
    try:
        data = fetch_json('https://api.exchangerate-api.com/v4/latest/USD')
        if data and data.get('rates'):
            cny = data['rates'].get('CNY', 0)
            if cny:
                return f'约{cny:.2f}', '温和震荡'
    except: pass
    return '约6.76', '温和震荡'

def fetch_cn_bond():
    """中国10年期国债收益率（东方财富国债收益率API）"""
    try:
        url = 'https://datacenter-web.eastmoney.com/api/data/v1/get?reportName=RPTA_WEB_TREASURYYIELD&columns=ALL&pageNumber=1&pageSize=1&sortTypes=-1&sortColumns=SOLAR_DATE'
        data = fetch_json(url, timeout=8)
        if data:
            items = data.get('result', {}).get('data', [])
            if items:
                val = items[0].get('EMM00166469')  # 10年期国债收益率
                if val is not None:
                    yield_val = round(float(val), 2)
                    trend = '下行' if yield_val < 2.5 else ('上行' if yield_val > 3.0 else '低位运行')
                    return f'{yield_val}%', trend
    except Exception as e:
        print(f'  ⚠ 国债收益率获取失败: {e}')
    return '约1.60%', '低位运行'

def fetch_hotspots():
    """热点板块"""
    return [
        {"sector": "AI算力/大模型", "driver": "大模型降价+算力需求爆发", "momentum": "强"},
        {"sector": "半导体/芯片", "driver": "国产替代加速+周期复苏", "momentum": "强"},
        {"sector": "机器人/自动化", "driver": "产业规模化落地+政策支持", "momentum": "中强"},
        {"sector": "新能源/新材料", "driver": "技术突破+出口高增长", "momentum": "中"},
        {"sector": "高股息红利", "driver": "低利率环境+险资增配", "momentum": "中强"},
    ]

# ============================================================
# RSS 真实新闻采集
# ============================================================

def fetch_rss_news():
    """从新浪财经采集真实新闻"""
    all_news = []
    sina_news = fetch_sina_headlines()
    if sina_news: all_news.extend(sina_news); print(f'  ✓ 新浪财经: {len(sina_news)}条')
    seen = set(); unique = []
    for n in all_news:
        key = n['title'][:30]
        if key not in seen: seen.add(key); unique.append(n)
    if len(unique) < 5:
        print(f'  ⚠ 不足({len(unique)})条，补充模板')
        unique.extend(get_fallback_news())
    return unique[:15]

def fetch_sina_headlines():
    """从新浪财经API获取滚动新闻"""
    try:
        url = 'https://feed.mix.sina.com.cn/api/roll/get?pageid=153&lid=2509&k=&num=20&page=1'
        data = fetch_json(url, timeout=10)
        if not data: return []
        items = data.get('result', {}).get('data', [])
        if not items: return []
        news = []
        for item in items:
            title = (item.get('title') or '').strip()
            if not title or len(title) < 5: continue
            intro = (item.get('intro') or item.get('ctime') or '').strip()
            news.append({'title': title[:80], 'summary': intro[:120], 'category': classify_news(title)})
        return news
    except Exception as e: print(f'  ⚠ 新浪: {e}')
    return []

def classify_news(title):
    text = title
    if any(w in text for w in ['美联储','央行','LPR','利率','CPI','通胀','GDP','降息','降准','宏观']): return '宏观经济'
    if any(w in text for w in ['A股','上证','深证','创业板','科创板','涨停','跌停','板块','行情']): return '行业动态'
    if any(w in text for w in ['公司','股份','回购','分红','业绩','财报','IPO','上市','融资']): return '上市公司'
    if any(w in text for w in ['美国','欧洲','日本','俄','乌','中东','地缘','制裁']): return '国际地缘'
    if any(w in text for w in ['AI','芯片','半导体','机器人','新能源','光伏','锂电','算力']): return '行业动态'
    return '行业动态'

def get_fallback_news():
    now = datetime.now(timezone(timedelta(hours=8)))
    today = now.strftime('%m月%d日')
    return [
        {"title": f"A股市场结构性机会延续（{today}）", "summary": f"今日A股结构性行情，科技成长活跃。", "category": "行业动态"},
        {"title": "央行维持LPR不变", "summary": "1年期LPR维持3.10%、5年期维持3.60%。银行净息差承压，降息预期仍在。", "category": "宏观经济"},
        {"title": "AI大模型降价加速应用落地", "summary": "国内大模型厂商大幅调降API价格，加速推理部署。", "category": "行业动态"},
        {"title": "人形机器人产业化提速", "summary": "头部企业加速量产，产业链订单持续爆发。", "category": "行业动态"},
        {"title": "高股息策略持续受追捧", "summary": "低利率环境下高分红板块获险资持续增配。", "category": "行业动态"},
        {"title": "全球市场关注美联储政策信号", "summary": "美联储维持利率但释放鹰派信号，美元波动加大。", "category": "宏观经济"},
        {"title": "新能源出口保持高增长", "summary": "光伏组件出口同比增超30%，锂电池新能源汽车出口强劲。", "category": "行业动态"},
        {"title": "央企市值管理改革推进", "summary": "市值管理改革纵深推进，多企启动回购和分红。", "category": "上市公司"},
    ]


def save_history():
    """将当天的 daily.json 存档到 data/history/YYYY-MM-DD.json"""
    daily_path = os.path.join(BASE_DIR, 'data', 'daily.json')
    if not os.path.exists(daily_path):
        print('  ⚠ daily.json 不存在，跳过存档')
        return
    
    now = datetime.now(timezone(timedelta(hours=8)))
    date_str = now.strftime('%Y-%m-%d')
    hist_path = os.path.join(HISTORY_DIR, f'{date_str}.json')
    
    os.makedirs(HISTORY_DIR, exist_ok=True)
    shutil.copy2(daily_path, hist_path)
    print(f'  📁 历史存档: {hist_path} ({os.path.getsize(hist_path)} bytes)')
    
    # 清理超过60天的旧数据
    cutoff = (now - timedelta(days=60)).strftime('%Y-%m-%d')
    for f in os.listdir(HISTORY_DIR):
        if f.endswith('.json') and f < f'{cutoff}.json':
            os.remove(os.path.join(HISTORY_DIR, f))
            print(f'  🗑 清理旧数据: {f}')

# ============================================================
# 每日市场展望（债/股/金/汇 四维度）
# ============================================================

def generate_outlook(a_share, gold, fx, bond):
    """
    基于实时市场数据生成每日展望。
    返回 {债券:{label,analysis}, 股票, 黄金, 汇率} 四个维度。
    """
    a_trend = a_share[1]
    gold_trend = gold[1]
    fx_trend = fx[1]
    bond_trend = bond[1]
    
    outlook = {}
    
    # 债券展望
    if '低位' in bond_trend:
        bond_label = '弱势债牛'
        bond_analysis = '10年期国债收益率维持低位运行，货币政策稳健偏松，但海外加息预期制约下行空间。短期维持弱势债牛判断，关注LPR调整窗口。'
    else:
        bond_label = '震荡偏强'
        bond_analysis = '国债收益率窄幅震荡，基本面对债市仍有支撑。后续聚焦内需复苏节奏和货币政策信号。'
    outlook['债券'] = {'label': bond_label, 'analysis': bond_analysis}
    
    # 股票展望
    if '强' in a_trend:
        stock_label = '顺风期进行中'
        stock_analysis = 'A股震荡偏强，科技成长主线明确，AI、半导体、机器人等新质生产力方向持续活跃。政策面持续呵护，中长期资金入市渠道拓宽，结构性机会丰富。关注美联储政策动向对外资流向的影响。'
    elif '弱' in a_trend:
        stock_label = '短期承压'
        stock_analysis = 'A股短期调整，市场情绪偏谨慎。关注高股息红利等防御性板块，控制仓位等待企稳信号。中长期看，估值处于历史中低位区域，调整即是布局机会。'
    else:
        stock_label = '震荡蓄力'
        stock_analysis = 'A股窄幅震荡，结构性行情延续。科技成长与高股息两条主线交替活跃。耐心等待市场选择方向，均衡配置、分散风险。'
    outlook['股票'] = {'label': stock_label, 'analysis': stock_analysis}
    
    # 黄金展望
    if '回落' in gold_trend or '跌' in gold_trend:
        gold_label = '弱势反弹'
        gold_analysis = '黄金短期承压，美联储鹰派信号打压金价，全球通胀预期回落。但中长期看，地缘风险和各国央行购金需求仍在，金价大幅下行空间有限。短期弱势反弹，暂无上行趋势。'
    elif '涨' in gold_trend or '强' in gold_trend:
        gold_label = '偏强震荡'
        gold_analysis = '黄金受避险情绪和美元走弱支撑，短期偏强。但美联储政策不确定性仍是最大变量。建议逢低配置，作为资产组合的压舱石。'
    else:
        gold_label = '弱势震荡'
        gold_analysis = '黄金短期缺乏方向性驱动，美联储政策与地缘风险交织。建议控制仓位，等待更明确的入场信号。中长期避险配置价值不变。'
    outlook['黄金'] = {'label': gold_label, 'analysis': gold_analysis}
    
    # 汇率展望
    if '升值' in fx_trend or '走强' in fx_trend:
        fx_label = '继续升值'
        fx_analysis = '人民币温和走强，强劲出口数据和中美利差边际变化提供支撑。短期升值趋势延续，有利于跨境配置和出境消费。关注美元指数走势和美联储政策变化。'
    elif '贬值' in fx_trend:
        fx_label = '短期承压'
        fx_analysis = '人民币面临美元走强压力，中美利差倒挂持续。但出口韧性和央行调控工具有效，大幅贬值风险可控。建议适度增加美元资产配置。'
    else:
        fx_label = '温和震荡'
        fx_analysis = '人民币短期缺乏方向性突破，在岸汇率维持区间波动。出口数据和中美关系是核心变量。建议保持汇率中性策略。'
    outlook['汇率'] = {'label': fx_label, 'analysis': fx_analysis}
    
    return outlook


# ============================================================
# 主流程
# ============================================================

def main():
    now = datetime.now(timezone(timedelta(hours=8)))
    print(f'🌐 云端数据采集 v2.0 | {now.strftime("%Y-%m-%d %H:%M:%S")}')
    
    # 采集市场数据
    print('📊 采集行情数据...')
    a_level, a_trend, a_chg = fetch_a_share()
    gold_price, gold_trend = fetch_gold()
    fx_rate, fx_trend = fetch_fx()
    bond_rate, bond_trend = fetch_cn_bond()
    
    print(f'  上证: {a_level} ({a_trend})')
    print(f'  黄金: {gold_price} | 汇率: USD/CNY {fx_rate}')
    
    # 采集新闻
    print('📰 采集财经新闻...')
    news = fetch_rss_news()
    print(f'  共采集 {len(news)} 条新闻')
    
    # 构建输出
    output = {
        "market": {
            "asset_prices": {
                "a_share": {"level": a_level, "trend": a_trend, "ytd": "+约5%"},
                "bond": {"cn_10y": bond_rate, "us_10y": "约4.55%", "trend": bond_trend},
                "gold": {"price": gold_price, "trend": gold_trend, "outlook": "短期震荡，中长期避险配置价值存在"},
                "fx": {"usd_cny": fx_rate, "dxy": "约99.8", "trend": fx_trend}
            },
            "deposit_rate": {
                "current": "1年期定存基准约1.1%，3年期约1.5%",
                "trend": "持续下行（银行净息差历史低位）",
                "outlook": "存款利率中长期下行趋势明确，储蓄型保险锁定利率价值持续凸显。"
            },
            "macro": {"lpr_1y": "3.10%", "lpr_5y": "3.60%", "cpi_status": "物价温和回升", "pmi_status": "制造业PMI维持扩张区间"},
            "capital_market": {
                "policy_stance": "中央经济工作会议明确持续深化资本市场投融资综合改革，推动中长期资金入市。全球流动性因美联储政策受关注。",
                "market_outlook": "A股结构性机会丰富，科技成长主线明确。AI/半导体/机器人等新质生产力方向持续活跃。"
            },
            "sector_rotation": {
                "current_hotspots": fetch_hotspots(),
                "risk_factors": ["美联储政策不确定性", "中美利差倒挂持续", "A股短期涨幅较快存在回调风险", "地缘政治不确定性"]
            }
        },
        "news": news,
        "daily_outlook": generate_outlook(
            (a_level, a_trend, a_chg),
            (gold_price, gold_trend),
            (fx_rate, fx_trend),
            (bond_rate, bond_trend)
        )
    }
    
    os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)
    with open(OUTPUT, 'w') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    
    print(f'✅ market_input.json 已生成 ({os.path.getsize(OUTPUT)} bytes)')
    return OUTPUT

if __name__ == '__main__':
    main()
