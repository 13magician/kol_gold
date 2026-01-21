# MT5工具.py
# -*- coding: utf-8 -*-
import MetaTrader5 as mt5
import os
import json
import time
import traceback

# 引用数据库工具用于打印日志
import 数据库工具 as db

# ===========================
# 配置文件路径
# ===========================
当前目录 = os.path.dirname(os.path.abspath(__file__))
密钥文件路径 = os.path.join(当前目录, "key.json")

class MT5助手:
    def __init__(self):
        self.已连接 = False
        self.终端路径 = ""
        self.账号ID = 0
        self.加载配置()

    def 加载配置(self):
        """从 key.json 读取 MT5 路径"""
        if not os.path.exists(密钥文件路径):
            db.带时间的日志打印(f"❌ [MT5] 找不到密钥文件: {密钥文件路径}")
            return

        try:
            with open(密钥文件路径, 'r', encoding='utf-8') as f:
                数据 = json.load(f)
            
            环境配置 = 数据.get("MT5交易所环境", {})
            self.终端路径 = 环境配置.get("终端路径_EXE", "")
            self.账号ID = 环境配置.get("登录账号ID", 0)
            
        except Exception as e:
            db.带时间的日志打印(f"❌ [MT5] 配置读取失败: {e}")

    def 启动连接(self):
        """初始化 MT5 连接"""
        if self.已连接:
            return True
            
        if not self.终端路径:
            db.带时间的日志打印("❌ [MT5] 未配置终端路径，无法启动")
            return False

        try:
            # 尝试连接指定路径的 MT5
            if not mt5.initialize(path=self.终端路径):
                错误码 = mt5.last_error()
                db.带时间的日志打印(f"❌ [MT5] 启动失败，错误码: {错误码}")
                return False
            
            # 确认账号
            当前账号信息 = mt5.account_info()
            if 当前账号信息:
                if 当前账号信息.login != self.账号ID:
                    db.带时间的日志打印(f"⚠️ [MT5] 警告：当前登录账号 ({当前账号信息.login}) 与配置 ({self.账号ID}) 不一致！")
                else:
                    # db.带时间的日志打印(f"✅ [MT5] 连接成功 | 账号: {self.账号ID} | 余额: {当前账号信息.balance}")
                    pass
            
            self.已连接 = True
            return True

        except Exception as e:
            db.带时间的日志打印(f"❌ [MT5] 连接异常: {e}")
            db.带时间的日志打印(traceback.format_exc())
            return False

    def 获取实时报价(self, 品种名称):
        """
        返回: (卖价Bid, 买价Ask)
        """
        if not self.已连接: self.启动连接()

        if not mt5.symbol_select(品种名称, True):
            db.带时间的日志打印(f"⚠️ [MT5] 无法选中品种: {品种名称}")
            return None, None

        Tick数据 = mt5.symbol_info_tick(品种名称)
        if Tick数据:
            return Tick数据.bid, Tick数据.ask
        else:
            return None, None

    # ==========================================
    # [新增] 账户与合约查询功能 (修复决策端报错)
    # ==========================================
    def 获取账户余额(self):
        """获取当前账户净值/余额"""
        if not self.已连接: self.启动连接()
        
        info = mt5.account_info()
        if info:
            # [Debug] 频繁查询时可注释掉下一行，但调试期保留
            # db.带时间的日志打印(f"💰 [Debug-MT5] 当前余额: {info.balance}") 
            return info.balance
        
        db.带时间的日志打印("❌ [MT5] 获取账户信息失败")
        return 0.0

    def 获取合约规格(self, 品种):
        """
        返回: (合约大小, 最小手数, 手数步长)
        """
        if not self.已连接: self.启动连接()
        
        if not mt5.symbol_select(品种, True):
            db.带时间的日志打印(f"❌ [MT5] 找不到品种 {品种}，无法获取规格")
            return 0, 0, 0
            
        info = mt5.symbol_info(品种)
        if info:
            # trade_contract_size 是关键，比如黄金是100还是1
            return info.trade_contract_size, info.volume_min, info.volume_step
        
        db.带时间的日志打印(f"❌ [MT5] 获取合约 {品种} 规格失败 (Info为None)")
        return 0, 0, 0

    # ==========================================
    # 核心交易功能 (支持 市价 + 挂单)
    # ==========================================
    def 执行下单(self, 品种, 方向, 手数, 挂单价格=0.0, 止损=0.0, 止盈=0.0, 备注="AI-Order"):
        """
        通用下单函数
        :param 方向: "买入", "卖出", "买入限价", "卖出限价", "买入止损", "卖出止损"
        :param 挂单价格: 如果是限价/止损单，必填
        """
        if not self.已连接: self.启动连接()

        # 1. 映射 MT5 订单类型
        MT5动作 = mt5.TRADE_ACTION_DEAL # 默认市价成交
        MT5类型 = mt5.ORDER_TYPE_BUY
        
        # 预读取报价
        bid, ask = self.获取实时报价(品种)
        if not bid: return False, "无法获取报价"

        目标价格 = 0.0

        if 方向 == "买入":
            MT5类型 = mt5.ORDER_TYPE_BUY
            目标价格 = ask
        elif 方向 == "卖出":
            MT5类型 = mt5.ORDER_TYPE_SELL
            目标价格 = bid
            
        # --- 挂单逻辑 (Pending Order) ---
        elif 方向 == "买入限价": # Buy Limit
            MT5动作 = mt5.TRADE_ACTION_PENDING
            MT5类型 = mt5.ORDER_TYPE_BUY_LIMIT
            目标价格 = float(挂单价格)
        elif 方向 == "卖出限价": # Sell Limit
            MT5动作 = mt5.TRADE_ACTION_PENDING
            MT5类型 = mt5.ORDER_TYPE_SELL_LIMIT
            目标价格 = float(挂单价格)
        elif 方向 == "买入止损": # Buy Stop
            MT5动作 = mt5.TRADE_ACTION_PENDING
            MT5类型 = mt5.ORDER_TYPE_BUY_STOP
            目标价格 = float(挂单价格)
        elif 方向 == "卖出止损": # Sell Stop
            MT5动作 = mt5.TRADE_ACTION_PENDING
            MT5类型 = mt5.ORDER_TYPE_SELL_STOP
            目标价格 = float(挂单价格)
            
        # 构造请求
        请求 = {
            "action": MT5动作,
            "symbol": 品种,
            "volume": float(手数),
            "type": MT5类型,
            "price": 目标价格,
            "sl": float(止损),
            "tp": float(止盈),
            "deviation": 20,
            "magic": 23333,
            "comment": 备注,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }

        # 市价单不需要 filling 检查，挂单有时候需要
        if MT5动作 == mt5.TRADE_ACTION_PENDING:
            请求["type_filling"] = mt5.ORDER_FILLING_RETURN

        # db.带时间的日志打印(f"📤 [MT5-发送请求] {方向} {品种} {手数}手 @ {目标价格} (SL:{止损} TP:{止盈})")

        结果 = mt5.order_send(请求)
        
        if 结果 is None:
            return False, "MT5无响应"

        if 结果.retcode == mt5.TRADE_RETCODE_DONE:
            类型文本 = "挂单" if MT5动作 == mt5.TRADE_ACTION_PENDING else "开仓"
            # db.带时间的日志打印(f"🚀 [{类型文本}成功] Ticket: {结果.order}")
            return True, 结果.order
        else:
            错误信息 = f"下单失败 Code: {结果.retcode} ({结果.comment})"
            db.带时间的日志打印(f"❌ {错误信息}")
            return False, 错误信息

    # ==========================================
    # 订单管理 (修改/撤销/平仓)
    # ==========================================
    def 修改订单(self, ticket, 新止损=None, 新止盈=None):
        """修改 SL/TP (用于保本策略)"""
        if not self.已连接: self.启动连接()
        
        # 1. 尝试在持仓里找
        是持仓 = True
        订单 = None
        
        持仓列表 = mt5.positions_get(ticket=ticket)
        if 持仓列表:
            订单 = 持仓列表[0]
        else:
            # 2. 尝试在挂单里找
            是持仓 = False
            挂单列表 = mt5.orders_get(ticket=ticket)
            if 挂单列表:
                订单 = 挂单列表[0]
        
        if not 订单:
            return False, f"找不到订单 {ticket}"

        # 准备参数
        sl = float(新止损) if 新止损 is not None else 订单.sl
        tp = float(新止盈) if 新止盈 is not None else 订单.tp
        
        # 动作类型不同
        action_type = mt5.TRADE_ACTION_SLTP if 是持仓 else mt5.TRADE_ACTION_MODIFY
        
        请求 = {
            "action": action_type,
            "symbol": 订单.symbol,
            "sl": sl,
            "tp": tp,
            "magic": 23333, # 保持一致
        }
        
        # 如果是挂单修改，需要带上 original order ticket 和 price
        if not 是持仓:
            请求["order"] = ticket
            请求["price"] = 订单.price_open # 挂单价格不变

        # 如果是持仓修改SLTP，position参数是必须的
        if 是持仓:
            请求["position"] = ticket

        结果 = mt5.order_send(请求)
        
        if 结果.retcode == mt5.TRADE_RETCODE_DONE:
            db.带时间的日志打印(f"🔧 [修改成功] Ticket:{ticket} -> SL:{sl} TP:{tp}")
            return True, "修改成功"
        else:
            return False, f"修改失败: {结果.comment}"

    def 撤销挂单(self, ticket):
        """删除未成交的 Limit/Stop 单"""
        if not self.已连接: self.启动连接()
        
        请求 = {
            "action": mt5.TRADE_ACTION_REMOVE,
            "order": ticket,
            "magic": 23333,
        }
        
        结果 = mt5.order_send(请求)
        
        if 结果.retcode == mt5.TRADE_RETCODE_DONE:
            db.带时间的日志打印(f"🗑️ [撤单成功] Ticket:{ticket}")
            return True, "已撤单"
        else:
            return False, f"撤单失败: {结果.comment}"

    def 执行平仓(self, ticket, 剩余手数=None):
        """市价平掉持仓"""
        if not self.已连接: self.启动连接()

        持仓列表 = mt5.positions_get(ticket=ticket)
        if not 持仓列表:
            return False, f"找不到持仓 {ticket}"
        
        持仓 = 持仓列表[0]
        平仓手数 = float(剩余手数) if 剩余手数 else 持仓.volume
        
        # 反向操作
        平仓类型 = mt5.ORDER_TYPE_SELL if 持仓.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY
        bid, ask = self.获取实时报价(持仓.symbol)
        平仓价格 = bid if 平仓类型 == mt5.ORDER_TYPE_SELL else ask
        
        请求 = {
            "action": mt5.TRADE_ACTION_DEAL,
            "position": ticket,
            "symbol": 持仓.symbol,
            "volume": 平仓手数,
            "type": 平仓类型,
            "price": 平仓价格,
            "deviation": 20,
            "magic": 23333,
            "comment": "AI-Close",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        
        结果 = mt5.order_send(请求)
        
        if 结果.retcode == mt5.TRADE_RETCODE_DONE:
            db.带时间的日志打印(f"✅ [平仓成功] Ticket: {ticket} | 盈利: {结果.profit}")
            return True, 结果
        else:
            return False, f"平仓失败: {结果.comment}"

    # ==========================================
    # 数据查询
    # ==========================================
    def 获取所有持仓(self):
        """返回当前持仓列表"""
        if not self.已连接: self.启动连接()
        return mt5.positions_get()

    def 获取所有挂单(self):
        """返回当前未成交挂单"""
        if not self.已连接: self.启动连接()
        return mt5.orders_get()

    # ==========================================
    # 统计端专用函数
    # ==========================================
    def 获取持仓ticket集合(self):
        """获取当前所有持仓的 Ticket 集合"""
        try:
            持仓_列表 = self.获取所有持仓()
            if 持仓_列表 is None:
                return None
            return {int(p.ticket) for p in 持仓_列表}
        except Exception as e:
            db.带时间的日志打印(f"❌ [MT5] 获取持仓集合失败: {e}")
            return None

    def 获取挂单ticket集合(self):
        """获取当前所有挂单的 Ticket 集合"""
        try:
            挂单_列表 = self.获取所有挂单()
            if 挂单_列表 is None:
                return set()
            return {int(order.ticket) for order in 挂单_列表}
        except Exception as e:
            db.带时间的日志打印(f"❌ [MT5] 获取挂单集合失败: {e}")
            return set()

    def 映射挂单类型(self, order_type):
        """将 MT5 挂单类型转换为中文描述"""
        方向映射 = {
            0: "买入",        # ORDER_TYPE_BUY
            1: "卖出",        # ORDER_TYPE_SELL
            2: "买入限价",    # ORDER_TYPE_BUY_LIMIT
            3: "卖出限价",    # ORDER_TYPE_SELL_LIMIT
            4: "买入止损",    # ORDER_TYPE_BUY_STOP
            5: "卖出止损",    # ORDER_TYPE_SELL_STOP
        }
        return 方向映射.get(order_type, "未知")

    def 查找挂单(self, mt5_ticket):
        """从所有挂单中查找指定 ticket 的挂单"""
        try:
            挂单_列表 = self.获取所有挂单()
            if 挂单_列表:
                for order in 挂单_列表:
                    if int(order.ticket) == int(mt5_ticket):
                        return order
            return None
        except Exception as e:
            db.带时间的日志打印(f"❌ [MT5] 查找挂单失败: {e}")
            return None

    def 查找持仓(self, mt5_ticket):
        """从所有持仓中查找指定 ticket 的持仓"""
        try:
            持仓_列表 = self.获取所有持仓()
            if 持仓_列表:
                for pos in 持仓_列表:
                    if int(pos.ticket) == int(mt5_ticket):
                        return pos
            return None
        except Exception as e:
            db.带时间的日志打印(f"❌ [MT5] 查找持仓失败: {e}")
            return None

    def 断开连接(self):
        """标记连接已断开（用于错误恢复）"""
        self.已连接 = False


# ===========================
# 单元测试 (运行时请谨慎)
# ===========================
if __name__ == "__main__":
    print("\n🔥 开始 MT5 助手单元测试 (Debug模式)...")
    助手 = MT5助手()
    
    if 助手.启动连接():
        print("\n--- 1. 测试行情获取 ---")
        # 🔴 修改前: bid, ask = 助手.获取实时报价("XAUUSDm")
        # 🟢 修改后:
        bid, ask = 助手.获取实时报价("XAUUSD+") 
        print(f"XAUUSD+ 报价: Bid={bid}, Ask={ask}")
        
        print("\n--- 2. 测试账户查询 (关键) ---")
        余额 = 助手.获取账户余额()
        print(f"账户余额: {余额}")
        
        print("\n--- 3. 测试合约规格 (关键) ---")
        # 🔴 修改前: size, min_v, step = 助手.获取合约规格("XAUUSDm")
        # 🟢 修改后:
        size, min_v, step = 助手.获取合约规格("XAUUSD+")
        print(f"合约大小: {size} (若为0则计算会错)")
        print(f"最小手数: {min_v}")
        print(f"手数步长: {step}")
        
    else:
        print("❌ 连接失败，请检查路径和Key配置")