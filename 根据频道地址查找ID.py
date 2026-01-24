# 根据频道地址查找ID.py
# -*- coding: utf-8 -*-
import os
import sys
import json
import asyncio
import socks
from telethon import TelegramClient, events
from urllib.parse import urlparse

# =================  Windows 系统修复 =================
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# ================= 配置区域 =================
当前目录 = os.path.dirname(os.path.abspath(__file__))
密钥文件路径 = os.path.join(当前目录, "key.json")

def 加载_Key配置():
    """
    从 key.json 加载配置，逻辑参考 监听TG.py
    """
    if not os.path.exists(密钥文件路径):
        print(f"❌ [配置] 找不到密钥文件: {密钥文件路径}")
        return None
        
    try:
        with open(密钥文件路径, 'r', encoding='utf-8') as f:
            数据 = json.load(f)
            
        # 1. 提取 Telegram 凭证 (兼容中英文)
        TG配置 = {}
        if "telegram" in 数据:
            TG配置 = 数据["telegram"]
        elif "Telegram身份凭证" in 数据:
            TG配置 = {
                "api_id": 数据["Telegram身份凭证"]["API_ID"], 
                "api_hash": 数据["Telegram身份凭证"]["API_HASH"],
                "session_name": 数据["Telegram身份凭证"]["Session文件名"]
            }
        else:
            print("❌ [配置] key.json 缺少 'telegram' 或 'Telegram身份凭证' 字段")
            return None

        # 2. 提取网络/代理配置 (兼容中英文)
        proxy_tuple = None
        网络配置 = {}
        if "network" in 数据:
            网络配置 = 数据["network"]
        elif "网络与基础设施" in 数据:
            网络配置 = {
                "enable_vpn": 数据["网络与基础设施"]["代理设置"]["启用VPN代理"],
                "proxy_url": 数据["网络与基础设施"]["代理设置"]["代理地址"]
            }

        # 3. 解析代理 (参考 监听TG.py 的逻辑)
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
                    print(f"⚠️ [网络] 不支持的代理协议: {p.scheme}，将尝试使用 HTTP 代理")
                    proxy_tuple = (socks.HTTP, p.hostname or "127.0.0.1", p.port)
                
                print(f"🔌 [网络] 已启用代理: {p.scheme}://{p.hostname}:{p.port}")
            except Exception as e:
                print(f"⚠️ [网络] 代理配置解析失败: {e}")
        else:
            print("🔌 [网络] 未启用代理 (直连模式)")

        return {
            "api_id": TG配置.get("api_id"),
            "api_hash": TG配置.get("api_hash"),
            "session": TG配置.get("session_name", "finder_session"),
            "proxy": proxy_tuple
        }

    except Exception as e:
        print(f"❌ [配置] 解析异常: {e}")
        return None

async def main():
    print("\n🔍 Telegram ID 查找工具 (修复版)")
    print("=" * 40)
    
    # 1. 加载配置
    conf = 加载_Key配置()
    if not conf:
        input("按回车键退出...")
        return

    # 2. 初始化客户端
    # 使用独立的 session 文件，避免与主程序冲突
    session_path = os.path.join(当前目录, str(conf["session"]) + "_finder")
    
    client = TelegramClient(
        session_path,
        conf["api_id"],
        conf["api_hash"],
        proxy=conf["proxy"],
        connection_retries=None,
        retry_delay=5
    )

    # 3. 连接
    print("⏳ 正在连接 Telegram 服务器...")
    try:
        await client.start()
    except Exception as e:
        print(f"❌ 连接失败: {e}")
        print("💡 建议检查 key.json 中的代理设置")
        return

    me = await client.get_me()
    print(f"✅ 连接成功 | 当前账号: {me.first_name} (@{me.username})")
    print("=" * 40)
    print("💡 使用说明:")
    print("   - 输入公开频道/群组链接 (如 https://t.me/durov)")
    print("   - 输入用户名 (如 @durov)")
    print("   - 输入 'q' 退出")
    print("=" * 40)

    # 4. 循环查询
    while True:
        try:
            target = input("\n🎯 请输入目标 (链接/用户名): ").strip()
            if not target: continue
            if target.lower() in ['q', 'exit', 'quit']: break

            # 简单的输入清洗
            clean_target = target
            if "t.me/" in target:
                # 尝试从链接中提取用户名
                # 例如 https://t.me/username/123 -> username
                try:
                    parts = target.split('/')
                    if "t.me" in parts:
                        idx = parts.index("t.me")
                    elif "telegram.me" in parts:
                        idx = parts.index("telegram.me")
                    else:
                        # 处理 t.me/username 这种没协议头的情况
                        idx = -1
                        for i, p in enumerate(parts):
                            if "t.me" in p: idx = i; break
                    
                    if idx != -1 and idx + 1 < len(parts):
                        potential = parts[idx+1]
                        # 排除 'c' (私有频道) 和 'joinchat' (邀请链接)
                        if potential not in ['c', 'joinchat', '+']:
                            clean_target = potential
                            print(f"ℹ️ 识别为用户名: {clean_target}")
                except:
                    pass

            print(f"🔎 正在查询: {clean_target} ...")
            
            try:
                entity = await client.get_entity(clean_target)
                
                # 获取信息
                title = getattr(entity, 'title', getattr(entity, 'first_name', '未知名称'))
                chat_id = entity.id
                username = getattr(entity, 'username', '无')
                
                # 判断类型
                type_desc = "用户"
                if getattr(entity, 'broadcast', False):
                    type_desc = "频道 (Channel)"
                elif getattr(entity, 'megagroup', False):
                    type_desc = "超级群组 (Supergroup)"
                elif getattr(entity, 'gigagroup', False):
                    type_desc = "广播群组 (Gigagroup)"
                elif getattr(entity, 'bot', False):
                    type_desc = "机器人 (Bot)"
                
                print("-" * 30)
                print(f"✅ 名称: {title}")
                print(f"📋 类型: {type_desc}")
                print(f"🔗 用户名: @{username}")
                print(f"🆔 原始ID: {chat_id}")
                
                # 针对频道/群组显示 -100 格式 ID
                if type_desc != "用户" and type_desc != "机器人 (Bot)":
                    # Telethon 返回的 ID 通常是正整数，API 使用通常需要 -100 前缀
                    print(f"🆔 API ID: -100{chat_id}  <-- 复制这个填入配置")
                else:
                    print(f"🆔 API ID: {chat_id}")
                print("-" * 30)

            except ValueError:
                print("❌ 无法找到该目标。")
                print("   可能原因: 链接错误 / 频道不存在 / 私有频道未加入 / 邀请链接失效")
            except Exception as e:
                print(f"❌ 查询出错: {e}")

        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"❌ 程序异常: {e}")

    print("\n👋 程序已退出")

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass