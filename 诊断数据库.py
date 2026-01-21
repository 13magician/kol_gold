# -*- coding: utf-8 -*-
import sqlite3
import os

BASE_DIR = r"G:\Gold_kol"
数据库文件 = os.path.join(BASE_DIR, "影子订单簿.db")

print("=" * 60)
print("数据库诊断工具 - 详细分析")
print("=" * 60)

conn = sqlite3.connect(数据库文件)
cursor = conn.cursor()

# 1. 查看 active_positions 表结构
print("\n【1】active_positions 表结构:")
cursor.execute("PRAGMA table_info(active_positions)")
columns = cursor.fetchall()
for col in columns:
    print(f"  {col[1]:20s} {col[2]:10s} (可空: {col[3] == 0})")

# 2. 查看所有记录的原始数据
print("\n【2】active_positions 所有记录 (原始数据):")
cursor.execute("SELECT * FROM active_positions")
rows = cursor.fetchall()

print(f"  总记录数: {len(rows)}")
for i, row in enumerate(rows, 1):
    print(f"\n  记录 #{i}:")
    for j, col in enumerate(columns):
        col_name = col[1]
        value = row[j]
        # 显示原始值和类型
        print(f"    {col_name:20s} = {repr(value):40s} (类型: {type(value).__name__})")

# 3. 专门检查 status 字段
print("\n【3】status 字段详细分析:")
cursor.execute("SELECT ticket, status FROM active_positions")
status_rows = cursor.fetchall()
for ticket, status in status_rows:
    print(f"  Ticket {ticket}: status = {repr(status)}")
    if status:
        print(f"    -> 十六进制: {status.encode('utf-8', errors='ignore').hex()}")
        print(f"    -> 字节长度: {len(status.encode('utf-8', errors='ignore'))}")

# 4. 测试查询条件
print("\n【4】测试不同查询条件:")
test_conditions = [
    "status = '持仓中'",
    "status LIKE '%持仓%'",
    "1=1",  # 无条件
]

for condition in test_conditions:
    cursor.execute(f"SELECT COUNT(*) FROM active_positions WHERE {condition}")
    count = cursor.fetchone()[0]
    print(f"  WHERE {condition:30s} -> {count} 条记录")

conn.close()

print("\n" + "=" * 60)
print("诊断完成")
print("=" * 60)
