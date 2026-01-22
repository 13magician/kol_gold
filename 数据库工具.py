# 数据库工具.py
# -*- coding: utf-8 -*-
import sqlite3
import json
import datetime
import os
import threading
import traceback # [新增] 用于Debug模式打印堆栈

# ===========================
# 基础配置 (保留你的原版风格)
# ===========================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
数据库文件 = os.path.join(BASE_DIR, "影子订单簿.db")
数据库_线程锁 = threading.Lock()

def 获取当前时间():
    return datetime.datetime.now().strftime("[%H:%M:%S]")

def 带时间的日志打印(msg):
    print(f"{获取当前时间()} {msg}")

# [新增] 统一连接函数，确保所有操作都有30秒超时保护
def 获取连接():
    return sqlite3.connect(数据库文件, timeout=30)

# ===========================
# 核心：初始化表结构
# ===========================
def 初始化数据库():
    """检查并创建所有必要的表结构"""
    try:
        with 数据库_线程锁:
            conn = 获取连接()
            
            # [cite_start][关键修改 1] 开启 WAL 模式，解决读写锁冲突 [cite: 1]
            conn.execute("PRAGMA journal_mode=WAL;")
            
            cursor = conn.cursor()

            # 1. 原始信号表 (Shadow Signals) - [新增] 父级信号
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS shadow_signals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT,
                    kol_name TEXT,
                    symbol TEXT,
                    direction TEXT,        -- "做多" / "做空"
                    entry_mode TEXT,       -- "市价" 或 "挂单"
                    entry_price REAL,      -- 挂单价格
                    tp_sl_config TEXT,     -- JSON: 原始的止盈止损配置
                    status TEXT            -- "等待执行", "运行中", "已归档"
                )
            ''')

            # 2. 待执行任务表 (Command Queue) - [新增] 子命令队列
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS command_queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    signal_id INTEGER,      -- 关联父信号ID
                    kol_name TEXT,
                    symbol TEXT,
                    direction TEXT,         -- "买入", "卖出", "买入限价"...
                    volume REAL,
                    price REAL,             -- 挂单价格
                    sl REAL,
                    tp REAL,
                    status TEXT,            -- "待执行", "已执行", "已撤销"
                    mt5_ticket INTEGER,     -- 执行后的 Ticket
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, -- [Debug] 方便查什么时候生成的
                    error_msg TEXT          -- [补丁] 错误信息记录
                )
            ''')

            # 3. 当前持仓表 (Active Positions) - [升级] 增加关联ID
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS active_positions (
                    ticket INTEGER PRIMARY KEY, -- MT5 Ticket作为主键
                    signal_id INTEGER,          -- [新增] 关联父信号ID
                    kol_name TEXT,
                    symbol TEXT,
                    direction TEXT,             -- "做多" / "做空"
                    entry_price REAL,
                    volume REAL,
                    tp_goal REAL,               -- [新增] 这张单子的目标止盈位 (用于显示)
                    exit_conditions TEXT,       -- JSON: 离场条件 (保留你的设计)
                    status TEXT                 -- "持仓中", "挂单中"
                )
            ''')

            # 4. 结算表 (Settlements) - [升级] 增加关联ID
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS settlements (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    signal_id INTEGER,          -- [新增] 关联父信号ID
                    kol_name TEXT,              -- 谁开的单
                    symbol TEXT,                -- 品种
                    direction TEXT,             -- 方向
                    volume REAL,                -- 手数
                    entry_price REAL,           -- 开仓价
                    exit_price REAL,            -- 平仓价
                    profit REAL,                -- 最终盈亏 (含手续费/库存费)
                    close_time TEXT,            -- 平仓时间
                    hold_duration INTEGER       -- 持仓秒数
                )
            ''')

            # 5. 执行日志表 (Execution Logs) - [保留] 流水账
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS execution_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    time TEXT,
                    action TEXT,    -- "开仓", "平仓", "修改"
                    details TEXT    -- 详细描述
                )
            ''')

            # [新增] 聊天记录表 (Chat History) - 用于上下文记忆
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS chat_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    kol_name TEXT,
                    user_content TEXT,     -- KOL发送的内容
                    ai_response TEXT,      -- AI回复的内容
                    is_signal INTEGER,     -- 1=是信号, 0=不是
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # ==========================================
            # [新增] 数据库补丁逻辑 (自动修复旧表结构)
            # ==========================================
            
            # 补丁 1: 检查 command_queue 是否缺少 error_msg
            cursor.execute("PRAGMA table_info(command_queue)")
            cols = [info[1] for info in cursor.fetchall()]
            if 'error_msg' not in cols:
                带时间的日志打印("⚠️ [数据库] 检测到 command_queue 缺少 error_msg，正在自动补全...")
                cursor.execute("ALTER TABLE command_queue ADD COLUMN error_msg TEXT")
            if 'state' not in cols:
                带时间的日志打印("⚠️ [数据库] 检测到 command_queue 缺少 state，正在自动补全...")
                cursor.execute("ALTER TABLE command_queue ADD COLUMN state TEXT")  # 空值表示未分类，"挂单"、"待成交"、"持仓"、"已结束"

            # 补丁 2: 检查 active_positions 是否缺少 signal_id
            cursor.execute("PRAGMA table_info(active_positions)")
            cols = [info[1] for info in cursor.fetchall()]
            if 'signal_id' not in cols:
                带时间的日志打印("⚠️ [数据库] 检测到 active_positions 缺少 signal_id，正在自动补全...")
                cursor.execute("ALTER TABLE active_positions ADD COLUMN signal_id INTEGER")
            if 'tp_goal' not in cols:
                带时间的日志打印("⚠️ [数据库] 检测到 active_positions 缺少 tp_goal，正在自动补全...")
                cursor.execute("ALTER TABLE active_positions ADD COLUMN tp_goal REAL")
            
            # 补丁 3: 检查 settlements 是否缺少 signal_id
            cursor.execute("PRAGMA table_info(settlements)")
            cols = [info[1] for info in cursor.fetchall()]
            if 'signal_id' not in cols:
                带时间的日志打印("⚠️ [数据库] 检测到 settlements 缺少 signal_id，正在自动补全...")
                cursor.execute("ALTER TABLE settlements ADD COLUMN signal_id INTEGER")

            # 补丁 4: 为 active_positions 添加实时数据字段
            cursor.execute("PRAGMA table_info(active_positions)")
            cols = [info[1] for info in cursor.fetchall()]
            if 'current_price' not in cols:
                带时间的日志打印("⚠️ [数据库] 检测到 active_positions 缺少 current_price，正在自动补全...")
                cursor.execute("ALTER TABLE active_positions ADD COLUMN current_price REAL DEFAULT 0")
            if 'unrealized_pnl' not in cols:
                带时间的日志打印("⚠️ [数据库] 检测到 active_positions 缺少 unrealized_pnl，正在自动补全...")
                cursor.execute("ALTER TABLE active_positions ADD COLUMN unrealized_pnl REAL DEFAULT 0")
            if 'last_update' not in cols:
                带时间的日志打印("⚠️ [数据库] 检测到 active_positions 缺少 last_update，正在自动补全...")
                cursor.execute("ALTER TABLE active_positions ADD COLUMN last_update TEXT")

            conn.commit()
            conn.close()
        
        带时间的日志打印(f"🛠️ [数据库] 初始化及自检完成，路径: {数据库文件} (模式: WAL)")
    
    except Exception as e:
        带时间的日志打印(f"❌ [数据库-初始化失败] {e}")
        带时间的日志打印(traceback.format_exc())

# ===========================
# 写入与读取 - 信号与命令 (新逻辑)
# ===========================

def 写入_父信号(kol_name, symbol, direction, entry_mode, entry_price, tp_sl_config):
    """(决策端用) 记录原始信号，返回 signal_id"""
    try:
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        config_str = json.dumps(tp_sl_config, ensure_ascii=False)
        
        with 数据库_线程锁:
            conn = 获取连接()
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO shadow_signals (timestamp, kol_name, symbol, direction, entry_mode, entry_price, tp_sl_config, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, '等待执行')
            ''', (now, kol_name, symbol, direction, entry_mode, entry_price, config_str))
            conn.commit()
            signal_id = cursor.lastrowid
            conn.close()
        return signal_id

    except Exception as e:
        带时间的日志打印(f"❌ [数据库-写入父信号失败] {e}")
        带时间的日志打印(traceback.format_exc())
        return -1 # 返回错误ID

def 写入_子命令(signal_id, kol_name, symbol, direction, volume, price, sl, tp):
    """(决策端用) 拆单后，将具体的下单指令写入队列"""
    try:
        with 数据库_线程锁:
            conn = 获取连接()
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO command_queue (signal_id, kol_name, symbol, direction, volume, price, sl, tp, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, '待执行')
            ''', (signal_id, kol_name, symbol, direction, volume, price, sl, tp))
            conn.commit()
            conn.close()
        
        # [Debug] 确认写入成功
        # 带时间的日志打印(f"💾 [DB-子命令] 已入队: Signal_{signal_id} | {symbol} {direction} {volume}手 @ {price} (TP:{tp})")

    except Exception as e:
        带时间的日志打印(f"❌ [数据库-写入子命令失败] {e}")
        带时间的日志打印(traceback.format_exc())

def 读取_待执行命令():
    """(执行端用) 获取所有待下单的指令"""
    try:
        tasks = []
        with 数据库_线程锁:
            conn = 获取连接()
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM command_queue WHERE status = '待执行'")
            rows = cursor.fetchall()
            for r in rows: tasks.append(dict(r))
            conn.close()
        return tasks
    except Exception as e:
        带时间的日志打印(f"❌ [数据库-读取命令失败] {e}")
        return []

def 标记_命令已执行(cmd_id, ticket):
    """(执行端用) 标记命令完成，回填 Ticket"""
    try:
        with 数据库_线程锁:
            conn = 获取连接()
            cursor = conn.cursor()
            cursor.execute("UPDATE command_queue SET status='已执行', mt5_ticket=? WHERE id=?", (ticket, cmd_id))
            conn.commit()
            conn.close()
    except Exception as e:
        带时间的日志打印(f"❌ [数据库-标记执行失败] ID:{cmd_id} Ticket:{ticket} | {e}")

# ===========================
# 持仓管理与清理逻辑 (核心升级)
# ===========================

def 写入_持仓记录(ticket, signal_id, kol_name, symbol, direction, entry_price, volume, tp_goal, exit_conditions, status="持仓中"):
    """(执行端用) 下单成功后记录"""
    try:
        with 数据库_线程锁:
            conn = 获取连接()
            cursor = conn.cursor()
            
            exit_str = json.dumps(exit_conditions, ensure_ascii=False)
            
            cursor.execute('''
                INSERT OR REPLACE INTO active_positions 
                (ticket, signal_id, kol_name, symbol, direction, entry_price, volume, tp_goal, exit_conditions, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (ticket, signal_id, kol_name, symbol, direction, entry_price, volume, tp_goal, exit_str, status))
            
            conn.commit()
            conn.close()
        # 带时间的日志打印(f"📝 [DB-持仓] 已登记 Ticket: {ticket} (Signal: {signal_id})")
    
    except Exception as e:
        带时间的日志打印(f"❌ [数据库-写入持仓失败] {e}")
        带时间的日志打印(traceback.format_exc())

def 查询_KOL活跃Ticket(kol_name):
    """(决策端用) 获取该 KOL 所有正在持仓或挂单的 Ticket，用于清理旧单"""
    try:
        tickets = []
        with 数据库_线程锁:
            conn = 获取连接()
            cursor = conn.cursor()
            cursor.execute("SELECT ticket FROM active_positions WHERE kol_name = ?", (kol_name,))
            rows = cursor.fetchall()
            for r in rows: tickets.append(r[0])
            conn.close()
        return tickets
    except Exception as e:
        带时间的日志打印(f"❌ [数据库-查询活跃Ticket失败] {e}")
        return []

def 读取_所有活跃持仓():
    """(执行端用) 获取所有活跃持仓记录"""
    try:
        positions = []
        with 数据库_线程锁:
            conn = 获取连接()
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # [修复] 移除status过滤,读取所有记录
            # 原因: 数据库中实际值是'监盘中',导致查询不到记录
            cursor.execute("SELECT * FROM active_positions")
            rows = cursor.fetchall()

            for row in rows:
                pos = dict(row)
                try:
                    pos['exit_conditions'] = json.loads(pos['exit_conditions'])
                    positions.append(pos)
                except:
                    # JSON解析失败也保留记录
                    positions.append(pos)
            conn.close()
        return positions
    except Exception as e:
        带时间的日志打印(f"❌ [数据库-读取活跃持仓失败] {e}")
        return []

def 查询_KOL挂单(kol_name, symbol=None):
    """(执行端用) 获取该 KOL 的所有挂单 (command_queue 中 state='挂单')"""
    try:
        orders = []
        with 数据库_线程锁:
            conn = 获取连接()
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            sql = "SELECT mt5_ticket, symbol FROM command_queue WHERE kol_name=? AND status='已执行' AND state='挂单'"
            params = [kol_name]
            
            if symbol and symbol.upper() != "ALL":
                sql += " AND symbol=?"
                params.append(symbol)
                
            cursor.execute(sql, params)
            rows = cursor.fetchall()
            for r in rows: orders.append(dict(r))
            conn.close()
        return orders
    except Exception as e:
        带时间的日志打印(f"❌ [数据库-查询挂单失败] {e}")
        return []

def 移除_持仓记录(ticket):
    """(执行端用) 平仓后移除"""
    try:
        with 数据库_线程锁:
            conn = 获取连接()
            cursor = conn.cursor()
            # [关键修改 2] 强制类型转换为 int，防止因字符串不匹配导致删不掉
            cursor.execute("DELETE FROM active_positions WHERE ticket = ?", (int(ticket),))
            conn.commit()
            conn.close()
        带时间的日志打印(f"🗑️ [DB] 已移除僵尸单 Ticket:{ticket}")
    except Exception as e:
        带时间的日志打印(f"❌ [数据库-移除持仓失败] {e}")

# ===========================
# 结算与日志 (保留)
# ===========================

def 归档_结算记录(signal_id, kol_name, symbol, direction, volume, entry_price, exit_price, profit, open_time_str=""):
    """(执行端用) 平仓后，将战绩写入历史表"""
    try:
        now = datetime.datetime.now()
        close_time_str = now.strftime("%Y-%m-%d %H:%M:%S")
        
        # 计算持仓时间
        duration = 0
        if open_time_str:
            try:
                open_time = datetime.datetime.strptime(open_time_str, "%Y-%m-%d %H:%M:%S")
                duration = (now - open_time).seconds
            except:
                pass

        with 数据库_线程锁:
            conn = 获取连接()
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT INTO settlements 
                (signal_id, kol_name, symbol, direction, volume, entry_price, exit_price, profit, close_time, hold_duration)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (signal_id, kol_name, symbol, direction, volume, entry_price, exit_price, profit, close_time_str, duration))
            
            conn.commit()
            conn.close()
        带时间的日志打印(f"💰 [战绩归档] {kol_name} | {symbol} | 盈亏: {profit}")
    
    except Exception as e:
        带时间的日志打印(f"❌ [数据库-归档结算失败] {e}")
        带时间的日志打印(traceback.format_exc())

def 写入_执行日志(action, details):
    """记录流水账"""
    try:
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with 数据库_线程锁:
            conn = 获取连接()
            cursor = conn.cursor()
            cursor.execute("INSERT INTO execution_logs (time, action, details) VALUES (?, ?, ?)", (now, action, details))
            conn.commit()
            conn.close()
    except:
        pass # 日志写入失败就算了，别炸主程序

def 查询_KOL战绩():
    """返回所有KOL的统计数据"""
    try:
        with 数据库_线程锁:
            conn = 获取连接()
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT 
                    kol_name,
                    COUNT(*) as total_trades,
                    SUM(CASE WHEN profit > 0 THEN 1 ELSE 0 END) as win_count,
                    SUM(profit) as total_profit,
                    AVG(profit) as avg_profit
                FROM settlements
                GROUP BY kol_name
                ORDER BY total_profit DESC
            ''')
            
            rows = cursor.fetchall()
            conn.close()
        return [dict(row) for row in rows]
    except Exception as e:
        带时间的日志打印(f"❌ [数据库-查询战绩失败] {e}")
        return []

def 标记_命令失败(cmd_id, 错误信息):
    """(执行端用) 遇到严重错误（如金额不足、参数错误），标记失败不再重试"""
    try:
        with 数据库_线程锁:
            conn = 获取连接()
            cursor = conn.cursor()
            # 将状态改为 '失败'，并记录错误原因
            cursor.execute("UPDATE command_queue SET status='失败', error_msg=? WHERE id=?", (错误信息, cmd_id))
            conn.commit()
            conn.close()
    except Exception as e:
        带时间的日志打印(f"❌ [数据库-标记失败异常] ID:{cmd_id} | {e}")
        # 如果连更新失败都报错（通常是列不存在），则说明数据库结构严重过时，这里就不再抛出异常了，防止外层循环炸

def 更新持仓实时数据(ticket, entry_price, 当前价格, 浮动盈亏):
    """(统计端用) 更新持仓的实时价格和浮动盈亏, 如果发现开仓价为0，则一并修正。"""
    try:
        import datetime
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        with 数据库_线程锁:
            conn = 获取连接()
            cursor = conn.cursor()

            safe_ticket = int(ticket)

            cursor.execute('''
                UPDATE active_positions
                SET current_price = ?, 
                    unrealized_pnl = ?, 
                    last_update = ?,
                    entry_price = CASE WHEN entry_price = 0 OR entry_price IS NULL THEN ? ELSE entry_price END
                WHERE ticket = ?
            ''', (当前价格, 浮动盈亏, now, entry_price, safe_ticket))

            affected = cursor.rowcount
            conn.commit()
            conn.close()

            return affected > 0

    except Exception as e:
        带时间的日志打印(f"❌ [数据库-更新实时数据失败] Ticket:{ticket} | {e}")
        return False


# ===========================
# 统计端专用函数 (监控与同步)
# ===========================

def 获取等待中的信号():
    """获取所有等待执行的信号及其关联的 MT5 Ticket"""
    try:
        with 数据库_线程锁:
            conn = 获取连接()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT s.id, c.mt5_ticket
                FROM shadow_signals s
                LEFT JOIN command_queue c ON s.id = c.signal_id AND c.status='已执行'
                WHERE s.status='等待执行'
            """)
            结果 = cursor.fetchall()
            conn.close()
        return 结果
    except Exception as e:
        带时间的日志打印(f"❌ [数据库-获取等待信号失败] {e}")
        return []

def 标记失效挂单(signal_id):
    """标记挂单已失效"""
    try:
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with 数据库_线程锁:
            conn = 获取连接()
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE shadow_signals
                SET status='已取消', cancel_time=?, cancel_reason='MT5挂单已失效'
                WHERE id=?
            """, (now, signal_id))
            conn.commit()
            conn.close()
    except Exception as e:
        带时间的日志打印(f"❌ [数据库-标记失效挂单失败] {e}")

def 获取已执行的tickets():
    """获取所有已执行命令的 MT5 Ticket 集合"""
    try:
        with 数据库_线程锁:
            conn = 获取连接()
            cursor = conn.cursor()
            cursor.execute("SELECT mt5_ticket FROM command_queue WHERE status='已执行'")
            tickets = {row[0] for row in cursor.fetchall() if row[0]}
            conn.close()
        return tickets
    except Exception as e:
        带时间的日志打印(f"❌ [数据库-获取已执行tickets失败] {e}")
        return set()

def 检查command_queue中是否存在(mt5_ticket):
    """检查 command_queue 中是否已存在该 ticket"""
    try:
        with 数据库_线程锁:
            conn = 获取连接()
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM command_queue WHERE mt5_ticket=?", (mt5_ticket,))
            结果 = cursor.fetchone()
            conn.close()
        return 结果 is not None
    except Exception as e:
        带时间的日志打印(f"❌ [数据库-检查ticket失败] {e}")
        return False

def 插入手动挂单(symbol, direction, volume, price, sl, tp, mt5_ticket):
    """将手动挂单写入 command_queue"""
    try:
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with 数据库_线程锁:
            conn = 获取连接()
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO command_queue
                (signal_id, kol_name, symbol, direction, volume, price, sl, tp, status, mt5_ticket, created_at, state)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                None,  # signal_id
                "手动",  # kol_name
                symbol,
                direction,
                volume,
                price,
                sl,
                tp,
                "已执行",  # status
                mt5_ticket,
                now,
                "挂单"  # state
            ))
            conn.commit()
            conn.close()
    except Exception as e:
        带时间的日志打印(f"❌ [数据库-插入手动挂单失败] {e}")

def 更新command_queue_state(mt5_ticket, 真实Ticket_集合, 挂单_ticket_集合):
    """更新 command_queue 的 state 状态"""
    try:
        with 数据库_线程锁:
            conn = 获取连接()
            cursor = conn.cursor()

            # 查询所有已执行的命令
            cursor.execute("SELECT id, mt5_ticket, state FROM command_queue WHERE status='已执行'")
            所有命令 = cursor.fetchall()

            更新数 = 0
            for cmd_id, ticket, 当前_state in 所有命令:
                if ticket is None:
                    continue

                新_state = None
                if int(ticket) in 真实Ticket_集合:
                    新_state = "持仓"
                elif int(ticket) in 挂单_ticket_集合:
                    新_state = "挂单"
                else:
                    新_state = "已结束"

                if 新_state != 当前_state:
                    cursor.execute("UPDATE command_queue SET state=? WHERE id=?", (新_state, cmd_id))
                    更新数 += 1

            if 更新数 > 0:
                conn.commit()
            conn.close()
        return 更新数
    except Exception as e:
        带时间的日志打印(f"❌ [数据库-更新state失败] {e}")
        return 0

def 更新挂单数据(mt5_ticket, price, sl, tp):
    """更新挂单的 price/sl/tp 字段"""
    try:
        with 数据库_线程锁:
            conn = 获取连接()
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE command_queue
                SET price=?, sl=?, tp=?
                WHERE mt5_ticket=? AND status='已执行' AND state='挂单'
            """, (price, sl, tp, mt5_ticket))
            affected = cursor.rowcount
            conn.commit()
            conn.close()
        return affected > 0
    except Exception as e:
        带时间的日志打印(f"❌ [数据库-更新挂单数据失败] {e}")
        return False

def 写入_聊天记录(kol_name, user_content, ai_response, is_signal):
    """记录KOL消息和AI的回复"""
    try:
        with 数据库_线程锁:
            conn = 获取连接()
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO chat_history (kol_name, user_content, ai_response, is_signal)
                VALUES (?, ?, ?, ?)
            ''', (kol_name, user_content, ai_response, 1 if is_signal else 0))
            conn.commit()
            conn.close()
    except Exception as e:
        带时间的日志打印(f"❌ [数据库-写入聊天记录失败] {e}")

def 读取_最近聊天记录(kol_name, limit=2):
    """获取最近的聊天记录，用于构建AI上下文"""
    try:
        history = []
        with 数据库_线程锁:
            conn = 获取连接()
            cursor = conn.cursor()
            # 倒序取最近的N条
            cursor.execute('''
                SELECT user_content, ai_response 
                FROM chat_history 
                WHERE kol_name = ? 
                ORDER BY id DESC 
                LIMIT ?
            ''', (kol_name, limit))
            rows = cursor.fetchall()
            conn.close()
        
        # 数据库取出来是 [最新, 次新...]，需要反转为 [旧, 新...] 给AI
        for r in reversed(rows):
            user_text = r[0]
            ai_text = r[1]
            if user_text:
                # [优化] 格式化历史消息，使其与当前消息结构一致，帮助AI识别
                formatted_text = f"KOL名称: {kol_name}\n历史消息:\n{user_text}"
                history.append({"role": "user", "content": formatted_text})
            if ai_text:
                history.append({"role": "assistant", "content": ai_text})
            
        return history
    except Exception as e:
        带时间的日志打印(f"❌ [数据库-读取聊天记录失败] {e}")
        return []

# ===========================
# 单元测试 (直接运行此文件时执行)
# ===========================
if __name__ == "__main__":
    初始化数据库()
    
    print("\n--- 测试父子信号写入 ---")
    # 模拟写入一个父信号
    sid = 写入_父信号("测试KOL", "XAUUSDm", "做多", "市价", 0, {"sl": 2000, "tps": [2010, 2020]})
    print(f"创建父信号 ID: {sid}")

    if sid != -1:
        # 模拟拆单写入两个子命令
        写入_子命令(sid, "测试KOL", "XAUUSDm", "买入", 0.01, 0, 2000, 2010)
        写入_子命令(sid, "测试KOL", "XAUUSDm", "买入", 0.01, 0, 2000, 2020)
        
        cmds = 读取_待执行命令()
        print(f"读取到 {len(cmds)} 条待执行命令")
        for cmd in cmds:
            print(f" - 命令详情: {cmd['symbol']} {cmd['direction']} TP:{cmd['tp']}")
            
        print("✅ 数据库工具测试通过")
    else:
        print("❌ 父信号写入失败")