# 仪表盘.py
#streamlit run 仪表盘.py
# -*- coding: utf-8 -*-
import streamlit as st
import sqlite3
import pandas as pd
import time
import os
import plotly.express as px
import traceback # [Debug] 引入堆栈工具
import sys # [Debug] 用于强制刷新输出
from datetime import datetime
from 查看数据库 import 读取数据_df

# [Debug] 全局日志函数
def 控制台日志(消息, 是否错误=False):
    # 只有报错才打印，平时保持安静
    if 是否错误:
        时间戳 = time.strftime("%H:%M:%S")
        print(f"[{时间戳}] {消息}")
        sys.stdout.flush()

# console_log("🚀 仪表盘脚本开始启动...") # 已静默

# ===========================
# 配置
# ===========================
st.set_page_config(
    page_title="Shadow OMS 指挥中心",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 数据库路径
当前目录 = os.path.dirname(os.path.abspath(__file__))
数据库文件 = os.path.join(当前目录, "影子订单簿.db")

# ===========================
# 数据库读取函数
# ===========================
def 读取数据(sql):
    try:
        return 读取数据_df(sql)
    except Exception as e:
        控制台日志(f"❌ [SQL崩溃] {e}", 是否错误=True) # 仅保留报错
        st.error(f"❌ SQL执行失败: {e}")
        return pd.DataFrame()

# ===========================
# 页面布局 - 侧边栏
# ===========================
# console_log("🎨 正在渲染侧边栏...")
st.sidebar.title("🚀 控制台")

# 环境诊断
st.sidebar.subheader("🛠️ 环境诊断")
if os.path.exists(数据库文件):
    st.sidebar.success(f"✅ 数据库已连接")
    # 简易检查表
    try:
        conn_check = sqlite3.connect(数据库文件)
        cursor = conn_check.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = [t[0] for t in cursor.fetchall()]
        conn_check.close()
        st.sidebar.expander("📚 查看已加载的表").json(tables)
    except:
        st.sidebar.error("数据库文件损坏")
else:
    st.sidebar.error(f"❌ 找不到数据库: {数据库文件}")

st.sidebar.markdown("---")
# 自动刷新开关
自动刷新 = st.sidebar.checkbox('开启自动刷新 (5s)', value=True)
st.sidebar.markdown("---")
if st.sidebar.button("🔄 立即刷新"):
    st.rerun()

# ===========================
# 核心数据读取 (放在中间，确保执行)
# ===========================
# console_log("📥 开始读取核心业务数据...")

# 1. 结算数据
结算表 = 读取数据("SELECT * FROM settlements")
# 2. 持仓数据
持仓表 = 读取数据("SELECT * FROM active_positions")

# ===========================
# 主界面渲染
# ===========================
# console_log("🎨 正在渲染主界面...")
st.title("📊 MT5交易系统 - 实时监控仪表盘")

# --- KPI 区域 ---
if not 结算表.empty:
    总盈亏 = 结算表['profit'].sum()
    总单数 = len(结算表)
    胜单数 = len(结算表[结算表['profit'] > 0])
    胜率 = (胜单数 / 总单数 * 100) if 总单数 > 0 else 0
    浮动盈亏 = 持仓表['unrealized_pnl'].sum() if (not 持仓表.empty and 'unrealized_pnl' in 持仓表.columns) else 0.0

    列1, 列2, 列3, 列4 = st.columns(4)
    列1.metric("💰 净利润 (USD)", f"${总盈亏:.2f}")
    列2.metric("📈 胜率", f"{胜率:.1f}%")
    列3.metric("📦 总交易数", f"{总单数}")
    列4.metric("💹 浮动盈亏", f"${浮动盈亏:.2f}")
else:
    st.info("暂无历史结算数据")

# --- Tabs 区域 ---
标签1, 标签2, 标签3, 标签4 = st.tabs(["🏆 KOL 琅琊榜", "⚔️ 当前战场 (持仓)", "🕸️ 埋伏计划 (挂单)", "📜 历史流水"])

# Tab 1: 琅琊榜
with 标签1:
    if not 结算表.empty:
        统计 = 结算表.groupby('kol_name').agg(
            总收益=('profit', 'sum'),
            交易次数=('id', 'count'),
            胜单=('profit', lambda x: (x > 0).sum())
        ).reset_index()
        统计['胜率'] = (统计['胜单'] / 统计['交易次数'] * 100).map('{:.1f}%'.format)
        统计 = 统计.sort_values('总收益', ascending=False)

        st.dataframe(统计, hide_index=True, width='stretch')
        try:
            图表 = px.bar(统计, x='kol_name', y='总收益', title="KOL 盈利对比")
            st.plotly_chart(图表, width="stretch") # [修正] 替换过时的 use_container_width
        except: pass
    else:
        st.write("暂无数据")

# Tab 2: 持仓
with 标签2:
    # 只从数据库读取持仓数据（包括手动持仓，由统计端负责同步）
    if not 持仓表.empty:
        # 中文列名映射
        列名映射 = {
            'ticket': '订单号',
            'kol_name': 'KOL名称',
            'symbol': '品种',
            'direction': '方向',
            'entry_price': '开仓价',
            'current_price': '当前价',
            'unrealized_pnl': '浮动盈亏',
            'tp_goal': '止盈价'
        }

        # 智能筛选存在的列
        列表 = [c for c in ['ticket', 'kol_name', 'symbol', 'direction', 'entry_price', 'current_price', 'unrealized_pnl', 'tp_goal'] if c in 持仓表.columns]
        显示表 = 持仓表[列表].copy()
        显示表.columns = [列名映射.get(c, c) for c in 显示表.columns]
        st.dataframe(显示表, hide_index=True, width='stretch')
    else:
        st.success("当前空仓")

# Tab 3: 埋伏计划 (挂单)
with 标签3:
    st.subheader("📋 所有挂单 (由统计端同步)")

    # 从数据库读取所有挂单（只显示 state='挂单' 的记录）
    所有挂单 = 读取数据("""
        SELECT
            c.id, c.created_at, c.kol_name, c.symbol,
            c.direction, c.volume, c.price, c.sl, c.tp, c.mt5_ticket, c.state
        FROM command_queue c
        WHERE c.status = '已执行' AND c.state = '挂单'
        ORDER BY c.created_at DESC
    """)

    if not 所有挂单.empty:
        # 中文列名映射
        列名映射 = {
            'created_at': '创建时间',
            'kol_name': 'KOL名称',
            'symbol': '品种',
            'direction': '方向',
            'volume': '手数',
            'price': '挂单价',
            'sl': '止损',
            'tp': '止盈',
            'mt5_ticket': '订单号',
            'state': '状态'
        }

        # 显示所有挂单（包括 KOL 和手动）
        列表 = [c for c in ['created_at', 'kol_name', 'symbol', 'direction', 'volume', 'price', 'sl', 'tp', 'mt5_ticket', 'state'] if c in 所有挂单.columns]
        显示表 = 所有挂单[列表].copy()
        显示表.columns = [列名映射.get(c, c) for c in 显示表.columns]
        st.dataframe(显示表, hide_index=True, width='stretch')
    else:
        st.info("暂无挂单")

# Tab 4: 流水
with 标签4:
    if not 结算表.empty:
        st.dataframe(结算表, hide_index=True, width='stretch')
    else:
        st.write("暂无流水")

# console_log("🏁 渲染完成")

# ===========================
# 自动刷新逻辑 (必须放在最后!!)
# ===========================
if 自动刷新:
    time.sleep(5)
    st.rerun()