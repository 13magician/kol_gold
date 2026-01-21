# 决策端.py
# -*- coding: utf-8 -*-
import os
import json
import logging
import math
import time
import traceback
from flask import Flask, request, jsonify

# 引入基建
import 数据库工具 as db
from AI分析 import AI决策大脑
from MT5工具 import MT5助手
from 交易日志美化打印 import 打印器 

# ===========================
# 配置与初始化
# ===========================
app = Flask(__name__)
# 屏蔽 Flask 的常规日志，只显示报错
log = logging.getLogger('werkzeug'); log.setLevel(logging.ERROR)

AI核心 = AI决策大脑()
MT5核心 = MT5助手() # 决策端也需要连MT5，为了查余额算仓位

当前目录 = os.path.dirname(os.path.abspath(__file__))
配置文件路径 = os.path.join(当前目录, "配置.json")
密钥文件路径 = os.path.join(当前目录, "key.json")

def 获取监听端口():
    try:
        if os.path.exists(密钥文件路径):
            with open(密钥文件路径, 'r', encoding='utf-8') as f:
                数据 = json.load(f)
                # 兼容中文/英文配置结构
                if "network" in 数据:
                    return 5010 # 默认
                return 数据.get("网络与基础设施", {}).get("内部通讯", {}).get("监听端口", 5010)
    except: pass
    return 5010

# ===========================
# 核心算法：智能仓位计算 (以损定仓)
# ===========================
def 计算智能手数(KOL名称, 品种, 入场价, 止损价):
    """
    根据 账户余额 + 风险偏好 + 止损距离 -> 计算下单手数
    """
    # [Debug] 初始极端值
    计算手数 = -999.0
    
    try:
        if not os.path.exists(配置文件路径): return 0.01

        with open(配置文件路径, 'r', encoding='utf-8') as f:
            配置 = json.load(f)
        
        资金管理 = 配置.get("资金管理", {})
        模式 = 资金管理.get("当前模式", "固定手数")
        
        # === 模式 A: 固定手数 (兜底逻辑) ===
        # 如果没止损，或者入场价为0(极端情况)，或者模式设为固定
        if 模式 == "固定手数" or 止损价 == 0 or 入场价 == 0:
            固定配置 = 资金管理.get("固定手数配置", {})
            默认 = 固定配置.get("默认", 0.05)
            # 模糊匹配 KOL 名字
            for key, vol in 固定配置.items():
                if key in KOL名称: return float(vol)
            return float(默认)

        # === 模式 B: 以损定仓 (主逻辑) ===
        elif 模式 == "以损定仓":
            风险参数 = 资金管理.get("以损定仓配置", {})
            
            # 1. 确定风险率
            默认风险 = 风险参数.get("默认风险率", 0.03)
            特殊配置 = 风险参数.get("特殊品种风险率", {})
            
            使用风险率 = 默认风险
            for 关键词, 比率 in 特殊配置.items():
                if 关键词 in 品种.upper():
                    使用风险率 = float(比率)
                    break
            
            最大手 = 风险参数.get("单笔最大手数限制", 10.0)
            最小手 = 风险参数.get("单笔最小手数限制", 0.01)
            
            # 2. 获取账户净值
            账户余额 = MT5核心.获取账户余额()
            if 账户余额 <= 0:
                db.带时间的日志打印("⚠️ [风险计算] 无法获取账户余额，降级为 0.01 手")
                return 0.01
                
            # 3. 计算本单允许亏多少钱
            允许亏损金额 = 账户余额 * 使用风险率
            
            # 4. 计算止损距离
            止损距离 = abs(入场价 - 止损价)
            if 止损距离 == 0: return 0.01
            
            # 5. 获取合约规格
            合约大小, 最小交易单位, 步长 = MT5核心.获取合约规格(品种)
            if 合约大小 == 0: 
                db.带时间的日志打印(f"⚠️ [风险计算] 获取合约大小失败 ({品种})，默认使用 100.0")
                合约大小 = 100.0 
            
            # 6. 公式
            计算手数 = 允许亏损金额 / (止损距离 * 合约大小)
            
            # [Debug] 打印详细计算过程，方便排查为何手数过小
            print(f"🧮 [计算] 余额:{账户余额:.0f} | 风险:${允许亏损金额:.1f} | 止损距:{止损距离:.1f} | 合约:{合约大小} -> 算得:{计算手数:.4f}手", flush=True)
            
            # 7. 修正手数
            if 步长 > 0:
                # [优化] 改为四舍五入，避免 0.017 被砍成 0.01 (对小资金更友好)
                计算手数 = round(计算手数 / 步长) * 步长
            计算手数 = round(计算手数, 2)
            
            # 8. 风控截断
            if 计算手数 > 最大手: 计算手数 = 最大手
            if 计算手数 < 最小手: 计算手数 = 最小手
            
            # [修改] 移除冗余打印，保持清爽
            # 打印器.决策_手数计算(品种, 计算手数, 账户余额, 允许亏损金额, 最小手, 最大手)
            return 计算手数

    except Exception as e:
        db.带时间的日志打印(f"⚠️ 资金计算出错: {e}，回退到 0.01")
        db.带时间的日志打印(traceback.format_exc())
        return 0.01

# ===========================
# 辅助算法：拆单计划
# ===========================
def 计算拆单计划(总手数, TP列表, 原始方向=None):
    TP数量 = len(TP列表)
    if TP数量 == 0: return [{"手数": 总手数, "tp": 0.0}] 

    if 总手数 < 0.01 * TP数量:
        db.带时间的日志打印(f"⚠️ 总手数 {总手数} 不足以分配给 {TP数量} 个TP，合并为一单")
        return [{"手数": 总手数, "tp": TP列表[0]}]

    # 均衡分配
    保底手数 = math.floor((总手数 / TP数量) * 100) / 100.0
    总余数 = round(总手数 - (保底手数 * TP数量), 2)
    余数分配次数 = int(round(总余数 * 100))
    
    计划列表 = []
    for i, tp_price in enumerate(TP列表):
        本单手数 = 保底手数
        if i < 余数分配次数: 本单手数 = round(本单手数 + 0.01, 2)
        if 本单手数 > 0: 计划列表.append({"手数": 本单手数, "tp": tp_price})
            
    return 计划列表

# ===========================
# Webhook 接口 (接收侦察兵数据)
# ===========================
@app.route('/webhook', methods=['POST'])
def 接收情报接口():
    try:
        数据包 = request.json
        if not 数据包: return jsonify({"状态": "忽略"}), 200

        KOL名称 = 数据包.get("author", "匿名")
        原始内容 = 数据包.get("content", "")
        图片列表 = 数据包.get("images", [])

        # [修改 1] 调用紧凑版头部
        打印器.决策_收到信号_紧凑版(KOL名称, len(图片列表))
        # db.带时间的日志打印(f"📨 [决策端] 收到: {KOL名称} | 图片: {len(图片列表)}张") # 系统日志可以保留，也可以注释

        # 1. 呼叫 AI 大脑分析 (增加计时)
        开始时间 = time.time()
        是否信号, 分析结果 = AI核心.分析信号(KOL名称, 原始内容, 图片列表)
        耗时 = time.time() - 开始时间

        # [修改 2] 打印 AI 结果提示
        # 打印器.决策_AI结果_提示(耗时)

        if 是否信号 and 分析结果:
            原始品种 = 分析结果.get("symbol")

            # ================= [新增] 品种映射修正逻辑 =================
            品种 = 原始品种 # 默认用AI说的
            # try:
            #     if os.path.exists(配置文件路径):
            #         with open(配置文件路径, 'r', encoding='utf-8') as f:
            #             config_data = json.load(f)
            #             mapping = config_data.get("品种映射表", {})
            #
            #             # 1. 尝试精确匹配 (例如 XAUUSD -> XAUUSD+)
            #             if 原始品种 in mapping:
            #                 品种 = mapping[原始品种]
            #                 # [修改 3] 调用映射显示
            #                 打印器.决策_显示映射(原始品种, 品种)
            #             # 2. 尝试去大小写匹配
            #             elif 原始品种.upper() in mapping:
            #                 品种 = mapping[原始品种.upper()]
            #                 # [修改 3] 调用映射显示
            #                 打印器.决策_显示映射(原始品种, 品种)
            # except Exception as map_err:
            #     db.带时间的日志打印(f"⚠️ [Debug] 读取品种映射配置失败: {map_err}")
            # ========================================================

            方向 = 分析结果.get("direction")
            模式 = 分析结果.get("entry_mode")
            挂单价 = float(分析结果.get("entry_price", 0.0) or 0.0)
            止损 = float(分析结果.get("sl", 0.0) or 0.0)
            TP列表 = 分析结果.get("tps", [])

            # [新增] 强制风控：无止损则跳过 (仅针对开仓信号)
            if 方向 != "平仓" and 止损 <= 0.00001:
                db.带时间的日志打印(f"🛑 [风控拦截] {KOL名称} 信号未包含止损 (SL={止损}) -> 放弃执行")
                return jsonify({"状态": "忽略", "原因": "无止损"}), 200

            # 1. 确定计算仓位用的基准价格 (提前计算以用于展示)
            计算基准价 = 挂单价
            是市价单 = False
            
            if 计算基准价 <= 0 and 方向 != "平仓": # 市价单
                是市价单 = True
                # db.带时间的日志打印(f"ℹ️ [Debug] 挂单价为0，尝试获取 {品种} 实时报价...")
                bid, ask = MT5核心.获取实时报价(品种)
                if bid: 
                    计算基准价 = ask if 方向 == "做多" else bid
                else: 
                    计算基准价 = 止损 

            # [修改 4] 打印紧凑版信号详情 (核心两行)
            打印器.决策_信号详情_紧凑版(KOL名称, 品种, 方向, 计算基准价, 止损, TP列表, 是市价单)
            
            # === 🔥 分支 A: 平仓指令 ===
            if 方向 == "平仓":
                打印器.决策_平仓令(KOL名称, 品种)
                db.带时间的日志打印(f"🚨 [收到清盘令] {KOL名称} 要求平仓 {品种}")
                父ID = db.写入_父信号(KOL名称, 品种, "平仓", "市价", 0, {})
                db.写入_子命令(父ID, KOL名称, 品种, "平仓", 0, 0, 0, 0)
                return jsonify({"状态": "成功", "类型": "平仓指令"}), 200

            # === 🔥 分支 B: 开仓指令 (做多/做空) ===
            
            # 2. 智能计算总手数
            总手数 = 计算智能手数(KOL名称, 品种, 计算基准价, 止损)

            # 3. 计算拆单
            拆单结果 = 计算拆单计划(总手数, TP列表)
            
            # [修改 5] 打印紧凑版拆单表格 (传入总手数和止损)
            打印器.决策_拆单计划_紧凑版(拆单结果, 总手数, 止损)

            # 4. 写入数据库
            try:
                # (1) 父信号
                父ID = db.写入_父信号(KOL名称, 品种, 方向, 模式, 挂单价, {"sl": 止损, "tps": TP列表})
                
                # (2) 转换方向
                mt5_direction = ""
                if 模式 == "市价":
                    mt5_direction = "买入" if 方向 == "做多" else "卖出"
                else:
                    mt5_direction = "买入限价" if 方向 == "做多" else "卖出限价"
                    if 挂单价 <= 0: 挂单价 = 0 

                # (3) 子命令入队
                for 计划 in 拆单结果:
                    db.写入_子命令(父ID, KOL名称, 品种, mt5_direction, 计划['手数'], 挂单价, 止损, 计划['tp'])

                # [修改 6] 移除大块的决策完成打印，仅保留简短的系统日志
                # db.带时间的日志打印(f"✅ [系统日志] 决策入库成功 SignalID:{父ID}")
                return jsonify({"状态": "成功", "SignalID": 父ID}), 200
            
            except Exception as e:
                打印器.决策_错误(str(e), traceback.format_exc())
                db.带时间的日志打印(f"❌ [决策端-数据库错误] {e}")
                db.带时间的日志打印(traceback.format_exc())
                return jsonify({"状态": "数据库错误"}), 500
        
        else:
            return jsonify({"状态": "忽略", "类型": "非交易信号/闲聊"}), 200

    except Exception as e:
        打印器.决策_错误(f"决策端异常: {str(e)}", traceback.format_exc())
        db.带时间的日志打印(f"❌ [决策端] 异常: {e}")
        db.带时间的日志打印(traceback.format_exc())
        return jsonify({"状态": "错误"}), 500

if __name__ == "__main__":
    端口 = 获取监听端口()
    print(f"\n🔥 决策端已启动 (Port: {端口}) [大脑就绪]...\n")
    app.run(host='0.0.0.0', port=端口, debug=False)