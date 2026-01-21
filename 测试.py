# stats_leverage_grouper.py
# -*- coding: utf-8 -*-
import ccxt
import json
import os
import datetime
import time

# ================= 配置区域 =================
KEY_FILE = "key.json"
CONFIG_FILE = "execution_server.json"
OUTPUT_FILE = "ace_strategy_report.txt"
SYMBOL = "COOKIE/USDT:USDT"
START_DATE = "2025-12-01 00:00:00" # 往前一点，确保抓到头

# ⚖️ 偏差容忍度：30%
# 如果买卖数量差异超过这个比例，将被视为“断头数据”或“持仓中”
BALANCE_THRESHOLD = 0.30

def load_json(filename):
    if not os.path.exists(filename): return None
    try:
        with open(filename, "r", encoding="utf-8") as f: return json.load(f)
    except: return None

def get_timestamp(date_str):
    dt = datetime.datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")
    return int(dt.timestamp() * 1000)

def fmt_ts(ts):
    return datetime.datetime.fromtimestamp(ts/1000).strftime('%Y-%m-%d %H:%M')

def analyze_groups(orders):
    """
    核心逻辑：
    1. 按杠杆倍数 (Leverage) 分组
    2. 组内校验买卖数量平衡性 (<30% 偏差)
    3. 计算盈亏
    """
    groups = []
    
    # 临时变量：当前的一组
    current_group = {
        "leverage": None,
        "orders": [],
        "start_ts": 0,
        "end_ts": 0
    }

    # 1. 必须按时间排序
    orders.sort(key=lambda x: x['timestamp'])

    for o in orders:
        # 提取这单的杠杆
        lev = None
        if 'info' in o and 'lever' in o['info']:
            try: lev = float(o['info']['lever'])
            except: pass
        
        # 如果获取不到杠杆，尝试沿用上一单的，如果还是没有，就默认为 10
        if lev is None:
            lev = current_group['leverage'] if current_group['leverage'] else 10.0

        # === 分组判断 ===
        # 如果杠杆变了，说明策略变了，结算上一组，开启新组
        if current_group['leverage'] is not None and lev != current_group['leverage']:
            if current_group['orders']:
                groups.append(current_group)
            current_group = {
                "leverage": lev,
                "orders": [],
                "start_ts": o['timestamp'],
                "end_ts": o['timestamp']
            }
        
        # 初始化第一组
        if current_group['leverage'] is None:
            current_group['leverage'] = lev
            current_group['start_ts'] = o['timestamp']

        # 加入当前组
        current_group['orders'].append(o)
        current_group['end_ts'] = o['timestamp']

    # 把最后一组加上
    if current_group['orders']:
        groups.append(current_group)

    # 2. 组内计算 (30% 过滤逻辑)
    results = []
    
    for i, g in enumerate(groups):
        buy_qty = 0.0
        sell_qty = 0.0
        
        total_buy_cost = 0.0  # 累计投入本金 (名义价值)
        total_gross_pnl = 0.0 # 累计毛利
        total_fees = 0.0
        
        # 遍历组内订单
        for o in g['orders']:
            amount = float(o['amount'])
            is_reduce = o.get('reduceOnly', False)
            side = o['side']

            # 统计数量 (用于平衡性检查)
            if side == 'buy': buy_qty += amount
            elif side == 'sell': sell_qty += amount
            
            # 统计金额
            # 规则：reduceOnly=False 算作投入本金
            if not is_reduce:
                # cost 字段通常是 名义价值 (数量*价格)
                cost_val = float(o['cost']) if o['cost'] else (amount * float(o['price']))
                total_buy_cost += cost_val
            
            # 规则：reduceOnly=True 算作结算盈亏
            if is_reduce:
                if 'info' in o and 'pnl' in o['info']:
                    total_gross_pnl += float(o['info']['pnl'])

            # 费用 (全口径)
            fee_val = 0.0
            if 'fee' in o and o['fee']: fee_val = float(o['fee'].get('cost', 0))
            elif 'fees' in o and o['fees']: 
                for f in o['fees']: fee_val += float(f.get('cost', 0))
            total_fees += abs(fee_val)

        # === 30% 偏差判定 ===
        status = "VALID"
        max_qty = max(buy_qty, sell_qty)
        diff = abs(buy_qty - sell_qty)
        
        # 偏差比例
        ratio = 0.0
        if max_qty > 0:
            ratio = diff / max_qty

        if ratio > BALANCE_THRESHOLD:
            if sell_qty > buy_qty:
                status = "SKIP" # 卖多买少 -> 缺买单 -> 无法算本金
            else:
                status = "HOLDING" # 买多卖少 -> 持仓中
        
        # 算财务数据
        lev = g['leverage']
        # 估算实际占用的保证金 = 总开仓名义价值 / 杠杆
        # 注意：如果是 SKIP 状态，total_buy_cost 可能极小甚至为0
        principal = total_buy_cost / lev if lev > 0 else 0
        net_profit = total_gross_pnl - total_fees
        
        roe = 0.0
        if status == "VALID" and principal > 0:
            roe = (net_profit / principal) * 100
        
        results.append({
            "round": i + 1,
            "period": f"{fmt_ts(g['start_ts'])} ~ {fmt_ts(g['end_ts'])}",
            "leverage": lev,
            "status": status,
            "buy_qty": buy_qty,
            "sell_qty": sell_qty,
            "principal": principal,
            "net_profit": net_profit,
            "roe": roe,
            "ratio": ratio * 100
        })
        
    return results

def main():
    print(f"🚀 启动战绩分析 (基于杠杆分组 + 30%偏差过滤)...")
    
    # 1. 下载数据
    config = load_json(CONFIG_FILE)
    keys = load_json(KEY_FILE)
    if not config or not keys: return
    
    system_conf = config.get('system', {})
    proxy_url = system_conf.get('proxy', "")
    proxies = {'http': proxy_url, 'https': proxy_url} if proxy_url else None
    
    okx_conf = keys.get('accounts', {}).get('okx')
    exchange = ccxt.okx(okx_conf)
    exchange.options['defaultType'] = 'swap'
    if proxies: exchange.proxies = proxies
    
    print(f"📥 下载 {SYMBOL} 历史订单 (Start: {START_DATE})...")
    all_orders = []
    since_ts = get_timestamp(START_DATE)
    
    while True:
        try:
            batch = exchange.fetch_closed_orders(SYMBOL, since=since_ts, limit=100)
            if not batch: break
            all_orders.extend(batch)
            print(f"   已读取 {len(all_orders)} 条...")
            since_ts = batch[-1]['timestamp'] + 1
            if len(batch) < 100: break
            time.sleep(0.1)
        except Exception as e:
            print(f"❌ 下载错误: {e}")
            break

    # 2. 分析
    print("\n🧮 正在按照【杠杆倍数】分组并计算...")
    reports = analyze_groups(all_orders)

    # 3. 输出报告
    lines = []
    lines.append("="*60)
    lines.append(f"📊 {SYMBOL} 策略战绩报告 (容错版)")
    lines.append(f"🔎 过滤规则: 买卖数量偏差 > {BALANCE_THRESHOLD*100}% 则跳过/标记")
    lines.append("="*60)
    
    valid_profit = 0.0

    for r in reports:
        # 状态图标
        icon = ""
        note = ""
        
        if r['status'] == "VALID":
            icon = "✅ [有效战绩]"
            valid_profit += r['net_profit']
            roe_str = f"{r['roe']:+.2f}%"
        elif r['status'] == "SKIP":
            icon = "🚫 [数据缺失]"
            note = f"(卖出远多于买入，本金不明，偏差 {r['ratio']:.0f}%)"
            roe_str = "---"
        elif r['status'] == "HOLDING":
            icon = "⏳ [持仓中]"
            note = f"(买入远多于卖出，未结算，偏差 {r['ratio']:.0f}%)"
            roe_str = "待定"

        lines.append(f"{icon} 第 {r['round']} 阶段 | 杠杆: {r['leverage']}x")
        lines.append(f"时间: {r['period']}")
        lines.append(f"数量: 买 {r['buy_qty']:.0f} / 卖 {r['sell_qty']:.0f} {note}")
        
        if r['status'] == "VALID":
            lines.append("-" * 30)
            lines.append(f"投入本金: {r['principal']:.2f} U")
            lines.append(f"净利润:   {r['net_profit']:+.2f} U")
            lines.append(f"收益率:   {roe_str}")
        
        lines.append("\n" + "-"*60 + "\n")

    lines.append(f"💰 有效轮次总净利: {valid_profit:+.2f} U")
    lines.append("="*60)

    final_text = "\n".join(lines)
    print(final_text)
    
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(final_text)
    print(f"✅ 报告已保存: {OUTPUT_FILE}")

if __name__ == "__main__":
    main()