# -*- coding: utf-8 -*-
import sqlite3
import pandas as pd
import os

# 数据库文件路径
当前目录 = os.path.dirname(os.path.abspath(__file__))
数据库文件 = os.path.join(当前目录, "影子订单簿.db")

def 读取数据_df(sql):
    """
    通用数据库读取功能，执行SQL并返回Pandas DataFrame。
    不包含任何UI相关的代码。
    """
    conn = sqlite3.connect(数据库文件)
    df = pd.read_sql_query(sql, conn)
    conn.close()
    return df

def main():
    """
    当作为脚本直接运行时，打印数据库的概览信息。
    """
    conn = sqlite3.connect(数据库文件)
    cursor = conn.cursor()

    # 查看所有表
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = cursor.fetchall()
    print("数据库中的表:", tables)
    print()

    # 查看 settlements 表
    print("=" * 50)
    print("settlements 表前5条数据:")
    print("=" * 50)
    cursor.execute("SELECT * FROM settlements LIMIT 5")
    settlements_data = cursor.fetchall()
    if settlements_data:
        for row in settlements_data:
            print(row)
    else:
        print("settlements 表为空")
    print()

    # 查看 active_positions 表
    print("=" * 50)
    print("active_positions 表前5条数据:")
    print("=" * 50)
    cursor.execute("SELECT * FROM active_positions LIMIT 5")
    active_positions_data = cursor.fetchall()
    if active_positions_data:
        for row in active_positions_data:
            print(row)
    else:
        print("active_positions 表为空")
    print()

    # 查看各表的记录数
    print("=" * 50)
    print("各表记录数统计:")
    print("=" * 50)
    for table in tables:
        table_name = table[0]
        cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
        count = cursor.fetchone()[0]
        print(f"{table_name}: {count} 条记录")

    conn.close()

if __name__ == "__main__":
    main()