# scan.py
# -*- coding: utf-8 -*-
import asyncio
import sys
import os
import json
import socks
from telethon import TelegramClient

# ================= 🔧 Windows 修复 =================
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
# ===================================================

# 配置文件路径
CONFIG_FILE = "telegram.json"
KEY_FILE = "key.json"

# 目标大群 ID
TARGET_GROUP_ID = -1003666423607

# 扫描深度
SCAN_LIMIT = 1000

# 代理设置
PROXY = (socks.SOCKS5, '127.0.0.1', 7897)

def load_keys():
    """读取 key.json 获取 Telegram 凭证"""
    if not os.path.exists(KEY_FILE):
        print(f"❌ 错误: 找不到 {KEY_FILE}")
        sys.exit(1)
    
    try:
        with open(KEY_FILE, 'r', encoding='utf-8') as f:
            keys = json.load(f)
            if "telegram" not in keys:
                print(f"❌ 错误: {KEY_FILE} 中缺少 'telegram' 字段")
                sys.exit(1)
            return keys["telegram"]
    except Exception as e:
        print(f"❌ 读取密钥文件失败: {e}")
        sys.exit(1)

def load_existing_topics():
    """读取 telegram.json 里已有的 topic ID"""
    if not os.path.exists(CONFIG_FILE):
        print(f"⚠️ 未找到 {CONFIG_FILE}，将显示所有扫描结果。")
        return set()
    
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            raw_topics = data.get("topics", {})
            return set(int(k) for k in raw_topics.keys())
    except Exception as e:
        print(f"⚠️ 读取配置文件出错: {e}，将显示所有扫描结果。")
        return set()

async def main():
    # 1. 加载密钥
    tg_creds = load_keys()
    api_id = tg_creds['api_id']
    api_hash = tg_creds['api_hash']
    
    # 🔥🔥🔥 核心修改在这里 🔥🔥🔥
    # 给 session 名字加个后缀 "_scan"，这就变成了一个独立的文件
    # 这样就不会和主程序的 session 文件冲突了！
    session_name = tg_creds['session_name'] + "_scan"

    # 2. 加载已有 ID
    existing_ids = load_existing_topics()
    print(f"📂 已从 JSON 加载了 {len(existing_ids)} 个已有话题。")

    print(f"🔌 正在连接 Telegram (Session: {session_name})...")
    print("⚠️ 提示：如果是第一次运行此 scan 脚本，请输入手机号登录 (不会影响主程序)。")
    
    async with TelegramClient(session_name, api_id, api_hash, proxy=PROXY) as client:
        print(f"✅ 连接成功！正在扫描最近 {SCAN_LIMIT} 条消息...")
        
        found_topics = set()
        topic_info = {} 

        # 3. 扫描最近的消息
        try:
            async for message in client.iter_messages(TARGET_GROUP_ID, limit=SCAN_LIMIT):
                tid = None
                # 兼容多种回复结构获取 ID
                if message.reply_to:
                    if hasattr(message.reply_to, 'reply_to_top_id') and message.reply_to.reply_to_top_id:
                        tid = message.reply_to.reply_to_top_id
                    else:
                        tid = message.reply_to.reply_to_msg_id
                
                if tid:
                    found_topics.add(tid)
        except ValueError:
             print("❌ 错误：找不到该群组 (ID 可能错误或未加入)。")
             return

        print(f"🔍 扫描到 {len(found_topics)} 个活跃话题 ID，正在解析名称...")

        # 4. 解析标题
        if found_topics:
            topic_creation_messages = await client.get_messages(TARGET_GROUP_ID, ids=list(found_topics))
            
            for msg in topic_creation_messages:
                if msg:
                    title = "未知标题"
                    if hasattr(msg, 'action') and hasattr(msg.action, 'title'):
                        title = msg.action.title
                    elif hasattr(msg, 'message') and msg.message:
                         title = msg.message[:20].replace('\n', ' ')
                    
                    safe_title = title.replace('"', "'")
                    topic_info[msg.id] = safe_title
                    
                    # 打印进度
                    status = "✅ 已存在" if msg.id in existing_ids else "🆕 新发现"
                    print(f"   -> [{status}] ID {msg.id} = {safe_title}")

        # 5. 筛选增量
        new_topics_info = {tid: title for tid, title in topic_info.items() if tid not in existing_ids}

        # === 输出区域: 仅新增列表 ===
        print("\n" + "="*20 + " 🚀 增量结果 (仅 JSON 里没有的) " + "="*20)
        
        if not new_topics_info:
            print("😴 没有发现新话题。")
        else:
            print("👇 请复制下面这些新行，粘贴到 telegram.json 的 topics 列表末尾 (注意补逗号) 👇\n")
            
            sorted_new = sorted(new_topics_info.items(), key=lambda x: x[0])
            
            for tid, title in sorted_new:
                print(f'    "{tid}": "{title}",')
        
        print("\n" + "="*60)

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"❌ 发生未知错误: {e}")