# 执行端.py
# -*- coding: utf-8 -*-
import time
import json
import datetime
import traceback
import MetaTrader5 as mt5

# 引入基建
import 数据库工具 as db
from MT5工具 import MT5助手
from 交易日志美化打印 import 打印器

class 执行指挥官:
    def __init__(self):
        # ==========================================
        # [新增] 强制初始化数据库
        # 防止第一次运行时报 "no such table"
        # ==========================================
        try:
            print("🛠️ 正在检查数据库完整性...")
            db.初始化数据库()
        except Exception as e:
            print(f"❌ 数据库初始化失败: {e}")
            
        self.MT5 = MT5助手()
        if not self.MT5.启动连接():
            print("❌ 无法启动执行端，请检查 MT5 设置")
            exit()
        self.正在运行 = True

    def 核心循环(self):
        打印器.执行_启动完成()

        while self.正在运行:
            try:
                # 1. 处理新命令 (开仓/挂单)
                self.处理_待执行命令()
                
                # 2. 监控持仓 (状态同步 + 触发保本)
                self.监控_持仓与保本()
                
                # 休息一下 (1秒)
                time.sleep(1)
                
            except KeyboardInterrupt:
                print("\n🛑 用户停止程序")
                self.正在运行 = False
            except Exception as e:
                db.带时间的日志打印(f"❌ [执行端] 严重错误: {e}")
                db.带时间的日志打印(traceback.format_exc()) # [Debug] 打印完整堆栈
                time.sleep(5)

    # ==========================================
    # 模块 A: 执行下单
    # ==========================================
    def 处理_待执行命令(self):
        # 1. 从数据库读取
        try:
            待办列表 = db.读取_待执行命令()
        except Exception as e:
            db.带时间的日志打印(f"⚠️ 读取命令队列失败 (可能数据库繁忙): {e}")
            return
        
        for 任务 in 待办列表:
            try:
                命令ID = 任务['id']
                SignalID = 任务['signal_id']
                KOL = 任务['kol_name']
                品种 = 任务['symbol']
                方向 = 任务['direction'] 
                手数 = 任务['volume']
                价格 = 任务['price']
                止损 = 任务['sl']
                止盈 = 任务['tp']

                # ===========================
                # [新增] 价格与止损预检查 (防止 10015 Invalid Price)
                # ===========================
                bid, ask = self.MT5.获取实时报价(品种)
                
                if bid is None or ask is None:
                    db.带时间的日志打印(f"⚠️ [执行端] 无法获取 {品种} 报价，暂缓执行 (等待行情)")
                    continue

                # [新增] 打印当前状态，不做无头苍蝇
                db.带时间的日志打印(f"🔍 [价格检查] {品种} {方向} | 目标价:{价格} | 现价(Bid/Ask):{bid:.4f}/{ask:.4f} | SL:{止损}")

                if bid and ask:
                    # ===========================
                    # [新增] 策略失效检查 (现价已过止损线 -> 放弃)
                    # ===========================
                    if 止损 > 0.00001:
                        if "买" in 方向 and bid < 止损:
                            错误信息 = f"🛑 策略失效: 现价({bid}) 已跌破止损({止损})，放弃做多"
                            打印器.执行_下单失败(品种, 手数, 错误信息)
                            db.标记_命令失败(命令ID, 错误信息)
                            continue
                        elif "卖" in 方向 and ask > 止损:
                            错误信息 = f"🛑 策略失效: 现价({ask}) 已涨破止损({止损})，放弃做空"
                            打印器.执行_下单失败(品种, 手数, 错误信息)
                            db.标记_命令失败(命令ID, 错误信息)
                            continue

                    # --- 优化逻辑: 现价更优且SL合法时，转为市价 ---
                    # 做多: 目标价 > Ask (想买贵的) 且 SL < Bid (止损在现价下方，安全)
                    if "买" in 方向 and 价格 > ask and 止损 > 0 and 止损 < bid:
                         db.带时间的日志打印(f"💡 [优化] 目标价({价格}) > 现价({ask}) 且 SL安全，转为市价买入")
                         方向 = "买入"
                         价格 = 0.0 # 市价单价格设为0
                    
                    # 做空: 目标价 < Bid (想卖便宜) 且 SL > Ask (止损在现价上方，安全)
                    elif "卖" in 方向 and 价格 > 0 and 价格 < bid and 止损 > 0 and 止损 > ask:
                         db.带时间的日志打印(f"💡 [优化] 目标价({价格}) < 现价({bid}) 且 SL安全，转为市价卖出")
                         方向 = "卖出"
                         价格 = 0.0

                    # ===========================
                    # [新增] 挂单类型自动修正 (Limit <-> Stop)
                    # ===========================
                    if 价格 > 0: # 仅针对挂单
                        # --- 做多修正 ---
                        if "买" in 方向:
                            # [修改] 移除 Buy Limit -> Buy Stop 的自动转换 (拒绝突破交易)
                            if 价格 < ask: # 目标价 < 现价 -> 必须是 Buy Limit
                                if "止损" in 方向 and "限价" not in 方向:
                                    db.带时间的日志打印(f"💡 [修正] 目标价({价格}) < Ask({ask}) -> 抄底/回调逻辑 (Buy Limit)")
                                    方向 = "买入限价"
                        
                        # --- 做空修正 ---
                        elif "卖" in 方向:
                            # [修改] 移除 Sell Limit -> Sell Stop 的自动转换
                            if 价格 > bid: # 目标价 > 现价 -> 必须是 Sell Limit
                                if "止损" in 方向 and "限价" not in 方向:
                                    db.带时间的日志打印(f"💡 [修正] 目标价({价格}) > Bid({bid}) -> 摸顶/反弹逻辑 (Sell Limit)")
                                    方向 = "卖出限价"

                    # 1. 确定基准价格 (用于判断 SL 是否合法)
                    基准价 = 价格 # 默认为挂单价
                    
                    # 如果是市价单 (价格为0) 或者 显式市价指令
                    if 价格 <= 0.00001 or ("限价" not in 方向 and "止损" not in 方向):
                        if "买" in 方向: 基准价 = ask
                        elif "卖" in 方向: 基准价 = bid
                    
                    # 2. 检查止损逻辑
                    if 止损 > 0.00001:
                        if "买" in 方向: # 做多: SL 必须 < 价格
                            if 止损 >= 基准价:
                                错误信息 = f"预判拦截: 做多SL({止损}) >= 开仓价({基准价})"
                                打印器.执行_下单失败(品种, 手数, 错误信息)
                                db.标记_命令失败(命令ID, 错误信息)
                                continue
                        elif "卖" in 方向: # 做空: SL 必须 > 价格
                            if 止损 <= 基准价:
                                错误信息 = f"预判拦截: 做空SL({止损}) <= 开仓价({基准价})"
                                打印器.执行_下单失败(品种, 手数, 错误信息)
                                db.标记_命令失败(命令ID, 错误信息)
                                continue

                打印器.执行_收到任务(KOL, 品种, 方向, 手数, 价格, 止损, 止盈)
                # db.带时间的日志打印(f"🔫 [执行] 收到任务: {品种} {方向} {手数}手 (TP:{止盈})")

                # 2. 调用 MT5
                成功, 结果 = self.MT5.执行下单(
                    品种=品种, 
                    方向=方向, 
                    手数=手数, 
                    挂单价格=价格, 
                    止损=止损, 
                    止盈=止盈, 
                    备注=f"Sig_{SignalID}"
                )
                
                # 3. 处理结果
                if 成功:
                    Ticket = 结果
                    # 从 MT5 获取详细信息（可选，如果需要美化输出）
                    # 这里简化处理，直接用入参
                    打印器.执行_下单成功(品种, Ticket, 手数, 价格, 止损, 止盈)

                    # A. 标记命令完成
                    db.标记_命令已执行(命令ID, Ticket)
                    
                    # B. 记录到持仓表
                    退出描述 = [{"类型": "止盈", "价格": 止盈}, {"类型": "止损", "价格": 止损}]
                    db.写入_持仓记录(
                        ticket=Ticket,
                        signal_id=SignalID,
                        kol_name=KOL,
                        symbol=品种,
                        direction=方向,
                        entry_price=价格 if "限价" in 方向 else 0,
                        volume=手数,
                        tp_goal=止盈,
                        exit_conditions=退出描述,
                        status="监控中"
                    )
                else:
                    # === 🔥 [修改点] 失败处理逻辑 🔥 ===
                    错误信息 = str(结果)
                    打印器.执行_下单失败(品种, 手数, 错误信息)
                    db.带时间的日志打印(f"⚠️ 下单失败: {错误信息} -> 🛑 已丢弃该任务，不再重试")
                    # 调用数据库工具，把状态改成 '失败'，这样下一轮循环就不会再读到它了
                    db.标记_命令失败(命令ID, 错误信息)

            except Exception as inner_e:
                db.带时间的日志打印(f"❌ [执行端-单任务异常] {inner_e}")
                db.带时间的日志打印(traceback.format_exc())
                # 如果是代码报错，也标记为失败，防止卡死
                db.标记_命令失败(任务['id'], f"程序异常: {str(inner_e)}")

    # ==========================================
    # 模块 B: 状态同步与保本逻辑
    # ==========================================
    def 监控_持仓与保本(self):
        # 获取数据库里认为 "活着" 的单子
        try:
            活跃单列表 = db.读取_所有活跃持仓()
        except:
            return # 数据库可能忙

        if not 活跃单列表: return

        # 获取 MT5 里的真实情况
        # 1. 真实持仓 (Positions)
        真实持仓 = {p.ticket: p for p in self.MT5.获取所有持仓()}
        # 2. 真实挂单 (Orders - Limit/Stop)
        真实挂单 = {o.ticket: o for o in self.MT5.获取所有挂单()}

        for DB单 in 活跃单列表:
            Ticket = DB单['ticket']
            SignalID = DB单['signal_id']
            KOL = DB单['kol_name']
            EntryPrice = DB单['entry_price']
            
            # === 情况 1: 单子在持仓里 (Running) ===
            if Ticket in 真实持仓:
                MT5单 = 真实持仓[Ticket]
                # 更新一下真实的开仓价和浮盈 (给仪表盘看)
                # 这里需要去 update 数据库，为了性能，我们可以每几秒更一次，或者暂不更新浮盈
                # 关键：如果有必要，修正 EntryPrice (因为挂单成交后，开仓价就确定了)
                if abs(EntryPrice - MT5单.price_open) > 0.00001:
                    # [Debug] 发现数据库记录的入场价和实际不同（通常发生在挂单成交瞬间）
                    # db.带时间的日志打印(f"ℹ️ [Debug] 修正开仓价: DB={EntryPrice} -> MT5={MT5单.price_open}")
                    # TODO: 更新数据库里的 entry_price
                    pass

            # === 情况 2: 单子在挂单里 (Pending) ===
            elif Ticket in 真实挂单:
                pass # 还在挂着，不用管

            # === 情况 3: 单子不见了！(Closed / Filled / Cancelled) ===
            else:
                # 这意味单子结束了。我们需要查查它是赚了还是赔了。
                # 这一步比较麻烦，需要查历史。
                # 简化逻辑：直接从 active_positions 移除，归档到 settlements
                
                # 尝试获取该单的最终盈亏 (需要查 HistoryDeal)
                from_date = datetime.datetime.now() - datetime.timedelta(days=1)
                history = mt5.history_deals_get(ticket=Ticket)
                
                盈亏 = 0.0
                平仓价 = 0.0
                if history:
                    # 通常最后一笔 deal 是平仓/进场
                    deal = history[-1]
                    盈亏 = deal.profit + deal.commission + deal.swap
                    平仓价 = deal.price
                else:
                    db.带时间的日志打印(f"⚠️ [Debug] 查不到历史订单 {Ticket}，可能被手动删除或未成交撤单")

                打印器.执行_单子结束(KOL, Ticket, DB单['symbol'], 盈亏, DB单['entry_price'], 平仓价)
                db.带时间的日志打印(f"🏁 [单子结束] {KOL} Ticket:{Ticket} 盈亏: {盈亏:.2f}")
                
                # 1. 归档
                db.归档_结算记录(
                    signal_id=SignalID,
                    kol_name=KOL,
                    symbol=DB单['symbol'],
                    direction=DB单['direction'],
                    volume=DB单['volume'],
                    entry_price=DB单['entry_price'], # 数据库里存的
                    exit_price=平仓价,
                    profit=盈亏
                )
                
                # 2. 从活跃表移除
                db.移除_持仓记录(Ticket)
                
                # === 🔥 核心：触发同组保本逻辑 🔥 ===
                # 如果这是一张止盈单 (盈亏 > 0)，且它有兄弟姐妹
                if 盈亏 > 0:
                    self.执行_保本操作(SignalID, DB单['entry_price'])

    def 执行_保本操作(self, signal_id, 开仓价格):
        """
        当 TP1 止盈后，把同组剩下的单子 SL 移到 开仓价
        """
        # 1. 找同组的兄弟
        所有活跃 = db.读取_所有活跃持仓()
        兄弟单子 = [p for p in 所有活跃 if p['signal_id'] == signal_id]
        
        if not 兄弟单子:
            return # 没兄弟了，全平完了

        打印器.执行_保本触发(signal_id, len(兄弟单子))
        db.带时间的日志打印(f"🛡️ [触发保本] Signal_{signal_id} 已有止盈，正在保护剩余 {len(兄弟单子)} 张单子...")

        for 单 in 兄弟单子:
            Ticket = 单['ticket']
            # 调用 MT5 修改止损
            # 注意：MT5 要求 SL 和现价有一定距离。如果现价就在开仓价附近，可能会修改失败。
            # 这里简单处理，直接设为开仓价。

            # 为了防止反复修改，可以查一下当前 SL 是多少
            # 这里偷懒直接发请求，MT5 如果数值一样会忽略
            result = self.MT5.修改订单(Ticket, 新止损=开仓价格)
            if result:
                打印器.执行_保本成功(Ticket, 开仓价格)

if __name__ == "__main__":
    指挥官 = 执行指挥官()
    指挥官.核心循环()