# TG侦察兵.py
# -*- coding: utf-8 -*-
import os
import sys  
import json
import asyncio
import time
import datetime
import socks 
import requests 
import logging  # ✅ 新增：引入日志模块
from telethon import TelegramClient, events
from urllib.parse import urlparse

# ================= 🔇 日志静音设置 (关键) =================
# 屏蔽掉 "Server closed the connection" 这类底层重连噪音
logging.basicConfig(level=logging.ERROR)
logging.getLogger('telethon').setLevel(logging.ERROR)
logging.getLogger('asyncio').setLevel(logging.ERROR)

# ================= 🔧 Windows 系统修复 =================
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# ===========================
# 基础配置
# ===========================
当前目录 = os.path.dirname(os.path.abspath(__file__))
密钥文件路径 = os.path.join(当前目录, "key.json")
配置文件路径 = os.path.join(当前目录, "配置.json")
图片缓存目录 = os.path.join(当前目录, "temp_images")

# 全局状态
全局配置 = {
    "KOL名单": {},         
    "目标群组ID": 0,       
    "只允许白名单": True,
    "Webhook地址": ""      
}

if not os.path.exists(图片缓存目录): os.makedirs(图片缓存目录)

# ===========================
# 1. 配置文件读取
# ===========================
def 加载_Key配置():
    if not os.path.exists(密钥文件路径): return None
    try:
        with open(密钥文件路径, 'r', encoding='utf-8') as f: 数据 = json.load(f)
        
        TG配置 = {}
        if "telegram" in 数据:
            TG配置 = 数据["telegram"]
        elif "Telegram身份凭证" in 数据:
            TG配置 = {"api_id": 数据["Telegram身份凭证"]["API_ID"], 
                      "api_hash": 数据["Telegram身份凭证"]["API_HASH"],
                      "session_name": 数据["Telegram身份凭证"]["Session文件名"]}

        proxy_tuple = None
        网络配置 = {}
        if "network" in 数据:
            网络配置 = 数据["network"]
        elif "网络与基础设施" in 数据:
            网络配置 = {"enable_vpn": 数据["网络与基础设施"]["代理设置"]["启用VPN代理"],
                        "proxy_url": 数据["网络与基础设施"]["代理设置"]["代理地址"]}

        if 网络配置.get("enable_vpn", False):
            raw_url = 网络配置.get("proxy_url", "")
            try:
                p = urlparse(raw_url)
                # 根据代理协议自动选择类型
                if p.scheme == "socks5":
                    proxy_tuple = (socks.SOCKS5, p.hostname or "127.0.0.1", p.port)
                elif p.scheme in ["http", "https"]:
                    proxy_tuple = (socks.HTTP, p.hostname or "127.0.0.1", p.port)
                else:
                    print(f"⚠️ 不支持的代理协议: {p.scheme}，将尝试使用 HTTP 代理")
                    proxy_tuple = (socks.HTTP, p.hostname or "127.0.0.1", p.port)
            except Exception as e:
                print(f"⚠️ 代理配置解析失败: {e}")
        
        webhook_url = "http://127.0.0.1:5010/webhook" 

        return {
            "api_id": TG配置.get("api_id"),
            "api_hash": TG配置.get("api_hash"),
            "session": TG配置.get("session_name", "monitor"),
            "proxy": proxy_tuple,
            "webhook": webhook_url
        }
    except Exception as e:
        print(f"❌ Key解析错误: {e}")
        return None

def 刷新_业务配置():
    global 全局配置
    if not os.path.exists(配置文件路径): return
    try:
        with open(配置文件路径, 'r', encoding='utf-8') as f: 数据 = json.load(f)
        
        raw_list = 数据.get("KOL监听名单", {})
        new_map = {}
        for k, v in raw_list.items():
            if k.lstrip("-").isdigit(): 
                new_map[int(k)] = v 
        
        全局开关 = 数据.get("系统全局开关", {})
        
        if new_map != 全局配置["KOL名单"]:
            pass 
            
        全局配置["KOL名单"] = new_map
        全局配置["目标群组ID"] = 全局开关.get("监听群组ID", 0)
        全局配置["只允许白名单"] = 全局开关.get("只允许白名单信号", True)
    except: pass

def get_topic_id(event):
    reply = event.message.reply_to
    if not reply: return None
    if hasattr(reply, 'reply_to_top_id') and reply.reply_to_top_id:
        return reply.reply_to_top_id
    return reply.reply_to_msg_id

# ===========================
# 2. 核心逻辑
# ===========================
async def 启动侦察兵():
    Key信息 = 加载_Key配置()
    if not Key信息: 
        print("❌ 未能加载配置")
        return
        
    全局配置["Webhook地址"] = Key信息["webhook"]
    刷新_业务配置()
    
    session_path = os.path.join(当前目录, str(Key信息["session"]) + "_scout_final")
    
    client = TelegramClient(
        session_path, 
        Key信息["api_id"], 
        Key信息["api_hash"], 
        proxy=Key信息["proxy"],
        connection_retries=None,
        retry_delay=5
    )

    @client.on(events.NewMessage)
    async def 监听新消息(event):
        chat_id = event.chat_id
        topic_id = get_topic_id(event)
        
        目标群ID = 全局配置["目标群组ID"]
        匹配到的KOL = None

        if chat_id == 目标群ID and topic_id and topic_id in 全局配置["KOL名单"]:
            匹配到的KOL = 全局配置["KOL名单"][topic_id]
        elif chat_id in 全局配置["KOL名单"]:
            匹配到的KOL = 全局配置["KOL名单"][chat_id]

        if not 匹配到的KOL:
            return

        # === 1. 语境处理 ===
        最终内容 = event.text or ""
        if event.is_reply:
            try:
                被回复 = await event.get_reply_message()
                if 被回复 and 被回复.text:
                    旧文 = 被回复.text.replace('\n', ' ').strip()[:80]
                    最终内容 = f"【前文】{旧文}\n-----\n{最终内容}"
            except: pass

        # === 2. 图片处理 ===
        图片路径列表 = []
        if event.message.media:
            try:
                # [修正] 不强制指定 .jpg，让 Telethon 自动识别后缀 (如 .mp4, .gif)
                # 避免将动图/视频强行存为 jpg 传给 AI 导致 400 错误
                fname_base = f"{匹配到的KOL}_{event.id}"
                save_path_base = os.path.join(图片缓存目录, fname_base)
                saved_path = await client.download_media(event.message, file=save_path_base)
                if saved_path:
                    图片路径列表.append(os.path.abspath(saved_path))
            except Exception as e:
                print(f"⚠️ 媒体下载失败: {e}")

        # === 3. UI 打印 ===
        now = datetime.datetime.now().strftime("%H:%M:%S")
        print(f"\n[{now}]") 
        print("=" * 35)
        print(f"🤖 [{匹配到的KOL}] ID: {topic_id}")
        
        if 图片路径列表:
            print("🖼️")
        
        print("📄")
        print(最终内容) 

        # === 4. 推送 ===
        try:
            requests.post(
                全局配置["Webhook地址"], 
                json={"author": 匹配到的KOL, "content": 最终内容, "images": 图片路径列表}, 
                timeout=5
            )
        except Exception as e:
            print("")#(f"❌ Webhook Err: {e}")

    async def 热更新守护():
        while True:
            await asyncio.sleep(10)
            刷新_业务配置()

    print(f"\n🕵️‍♀️ 侦察兵正在连接 (v2.9 UI风格版 + 静音模式)...")
    if Key信息["proxy"]:
        proxy_type = "SOCKS5" if Key信息["proxy"][0] == socks.SOCKS5 else "HTTP"
        print(f"🔌 使用 {proxy_type} 代理: {Key信息['proxy'][1]}:{Key信息['proxy'][2]}")
    else:
        print("🔌 未启用代理")
        
    await client.start()
    me = await client.get_me()
    print(f"✅ 连接成功 | 账号: {me.first_name}")
    print(f"📋 监听群组: {全局配置['目标群组ID']}")
    print(f"📋 监听话题: {list(全局配置['KOL名单'].keys())}")
    
    asyncio.create_task(热更新守护())
    await client.run_until_disconnected()

if __name__ == "__main__":
    # [新增] 自动重启机制，防止因 Telethon 解析错误(如 TypeNotFoundError)导致程序退出
    while True:
        try:
            asyncio.run(启动侦察兵())
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"❌ 发生错误: {e}")
            print("🔄 3秒后自动重启侦察兵...")
            time.sleep(3)