"""
同步挂单状态工具
用于清理数据库中已失效的挂单记录
"""
import sqlite3
import MetaTrader5 as mt5
from datetime import datetime

def 获取当前时间():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def 同步挂单状态():
    """同步MT5挂单状态到数据库"""

    # 1. 连接MT5
    if not mt5.initialize():
        print(f"[错误] MT5初始化失败")
        return False

    print(f"\n{获取当前时间()} [开始] 同步挂单状态")

    # 2. 获取MT5当前所有挂单
    mt5_挂单列表 = mt5.orders_get()
    mt5_ticket_集合 = set()

    if mt5_挂单列表:
        print(f"\n[MT5] 当前挂单数量: {len(mt5_挂单列表)}")
        for order in mt5_挂单列表:
            mt5_ticket_集合.add(order.ticket)
            print(f"  Ticket:{order.ticket} | {order.symbol} | 价格:{order.price_open}")
    else:
        print(f"\n[MT5] 当前无挂单")

    # 3. 连接数据库
    conn = sqlite3.connect('影子订单簿.db')
    cursor = conn.cursor()

    # 4. 获取数据库中"等待执行"的信号
    cursor.execute("""
        SELECT id, symbol, direction, entry_mode, entry_price
        FROM shadow_signals
        WHERE status='等待执行'
    """)
    db_信号列表 = cursor.fetchall()

    print(f"\n[数据库] 等待执行的信号数量: {len(db_信号列表)}")

    # 5. 检查每个信号对应的挂单是否还在MT5中
    需要更新的信号 = []
    for 信号 in db_信号列表:
        signal_id, symbol, direction, entry_mode, entry_price = 信号

        # 从command_queue表查找这个信号对应的ticket
        cursor.execute("""
            SELECT mt5_ticket FROM command_queue
            WHERE signal_id=? AND status='已执行'
        """, (signal_id,))
        ticket_row = cursor.fetchone()

        if ticket_row:
            mt5_ticket = ticket_row[0]

            # 检查这个ticket是否还在MT5的挂单列表中
            if mt5_ticket not in mt5_ticket_集合:
                需要更新的信号.append((signal_id, mt5_ticket, symbol, direction, entry_mode, entry_price))
                print(f"  [失效] Signal ID:{signal_id} | Ticket:{mt5_ticket} | {symbol} {direction} {entry_mode}")
        else:
            # 如果command_queue里都没有执行记录,说明信号还没被处理过
            print(f"  [未执行] Signal ID:{signal_id} | {symbol} {direction} {entry_mode} (未找到执行记录)")

    # 6. 更新失效的信号状态
    if 需要更新的信号:
        print(f"\n[更新] 发现 {len(需要更新的信号)} 个失效挂单，开始更新状态...")

        for signal_id, mt5_ticket, symbol, direction, entry_mode, entry_price in 需要更新的信号:
            # 更新信号状态为"已取消"
            cursor.execute("""
                UPDATE shadow_signals
                SET status='已取消',
                    cancel_time=?,
                    cancel_reason='MT5挂单已失效(可能被取消或成交)'
                WHERE id=?
            """, (获取当前时间(), signal_id))

            print(f"  [已更新] Signal ID:{signal_id} -> 状态:已取消")

        conn.commit()
        print(f"\n[完成] 已更新 {len(需要更新的信号)} 条记录")
    else:
        print(f"\n[完成] 所有挂单状态正常，无需更新")

    # 7. 显示更新后的统计
    cursor.execute("SELECT COUNT(*) FROM shadow_signals WHERE status='等待执行'")
    剩余等待数 = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM shadow_signals WHERE status='已取消'")
    已取消数 = cursor.fetchone()[0]

    print(f"\n[统计] 等待执行: {剩余等待数} | 已取消: {已取消数}")

    # 8. 清理
    conn.close()
    mt5.shutdown()

    return True

if __name__ == "__main__":
    同步挂单状态()
