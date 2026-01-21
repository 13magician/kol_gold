# AI分析.py
# -*- coding: utf-8 -*-
import json
import os
import requests
import base64
import time
import re
import traceback # [新增] 用于打印堆栈

# 引用数据库工具 (用于打印日志)
import 数据库工具 as db_util

# ===========================
# 配置文件路径
# ===========================
当前目录 = os.path.dirname(os.path.abspath(__file__))
配置文件路径 = os.path.join(当前目录, "配置.json")
密钥文件路径 = os.path.join(当前目录, "key.json")
提示词文件路径 = os.path.join(当前目录, "提示词.txt")

class AI决策大脑:
    def __init__(self):
        self.API地址 = ""
        self.API密钥 = ""
        self.主模型 = ""
        self.备用模型 = ""
        self.系统提示词 = ""
        self.初始化成功 = False
        
        # 启动时加载
        self.加载配置()
        self.加载提示词()

    def 加载配置(self):
        """从 key.json 读取 API 设置"""
        if not os.path.exists(密钥文件路径):
            db_util.带时间的日志打印(f"❌ [AI] 找不到密钥文件: {密钥文件路径}")
            return

        try:
            with open(密钥文件路径, 'r', encoding='utf-8') as f:
                密钥数据 = json.load(f)
                
            AI配置 = 密钥数据.get("AI决策", {})
            self.API地址 = AI配置.get("API地址", "https://api-666.cc/v1")
            self.API密钥 = AI配置.get("API密钥", "")
            
            模型列表 = AI配置.get("模型配置", {})
            self.主模型 = 模型列表.get("主模型", "gpt-4o")
            self.备用模型 = 模型列表.get("备用模型", "")
            
            self.初始化成功 = True
            db_util.带时间的日志打印(f"✅ [AI] 大脑已激活 | 主模型: {self.主模型} | 备用: {self.备用模型}")
            
        except Exception as e:
            db_util.带时间的日志打印(f"❌ [AI] 配置加载失败: {e}")
            db_util.带时间的日志打印(traceback.format_exc())

    def 加载提示词(self):
        """从 txt 文件读取 System Prompt"""
        if not os.path.exists(提示词文件路径):
            db_util.带时间的日志打印(f"⚠️ [AI] 找不到 {提示词文件路径}，将使用内置默认值")
            self.系统提示词 = "你是一个交易信号解析器，请输出包含 tps 数组的 JSON 格式。"
            return

        try:
            with open(提示词文件路径, 'r', encoding='utf-8') as f:
                self.系统提示词 = f.read().strip()
        except Exception as e:
            db_util.带时间的日志打印(f"❌ [AI] 提示词读取错误: {e}")

    def 图片转Base64(self, 图片路径):
        if not 图片路径 or not os.path.exists(图片路径):
            return None
        try:
            # 检查文件扩展名，只接受标准图片格式
            _, 扩展名 = os.path.splitext(图片路径)
            扩展名 = 扩展名.lower()

            # 只支持标准静态图片格式
            支持的格式 = {'.jpg', '.jpeg', '.png'}
            if 扩展名 not in 支持的格式:
                db_util.带时间的日志打印(f"⚠️ [AI] 跳过非标准图片格式: {扩展名} ({图片路径})")
                return None

            with open(图片路径, "rb") as image_file:
                return base64.b64encode(image_file.read()).decode('utf-8')
        except Exception as e:
            db_util.带时间的日志打印(f"⚠️ [AI] 图片读取失败: {e}")
            return None

    def 修正JSON数据(self, 原始JSON):
        """防止 AI 格式偶尔出错的补丁"""
        try:
            # 1. 确保 tps 是列表
            if "tps" in 原始JSON and not isinstance(原始JSON["tps"], list):
                db_util.带时间的日志打印(f"🔧 [Debug] 自动修正 tps 格式: {原始JSON['tps']} -> list")
                # 如果 AI 傻了给了个字符串 "2000, 2010"，尝试修一下
                if isinstance(原始JSON["tps"], (int, float)):
                    原始JSON["tps"] = [原始JSON["tps"]]
                else:
                    原始JSON["tps"] = [] # 放弃治疗
            
            # 2. 确保 entry_price 是数字
            if "entry_price" not in 原始JSON or 原始JSON["entry_price"] == "":
                原始JSON["entry_price"] = 0.0
            
            return 原始JSON
        except:
            return 原始JSON

    def 分析信号(self, KOL名称, 文本内容, 图片路径列表=[]):
        if not self.初始化成功: self.加载配置()

        db_util.带时间的日志打印(f"🤖 [AI] 正在分析: {KOL名称} 的消息...")

        消息列表 = [
            {"role": "system", "content": self.系统提示词},
            {"role": "user", "content": []}
        ]

        用户内容 = 消息列表[1]["content"]
        用户内容.append({
            "type": "text", 
            "text": f"KOL名称: {KOL名称}\n原始消息:\n{文本内容}"
        })

        for 图片路径 in 图片路径列表:
            Base64字串 = self.图片转Base64(图片路径)
            if Base64字串:
                用户内容.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{Base64字串}"}
                })

        请求头 = {
            "Authorization": f"Bearer {self.API密钥}",
            "Content-Type": "application/json"
        }
        
        当前模型 = self.主模型
        if 图片路径列表 and len(图片路径列表) > 0 and self.备用模型:
            当前模型 = self.备用模型
            db_util.带时间的日志打印(f"🖼️ [AI] 检测到图片，切换至备用模型: {当前模型}")

        请求体 = {
            "model": 当前模型,
            "messages": 消息列表,
            "temperature": 0.0,
            "max_tokens": 1500
        }

        try:
            开始时间 = time.time()
            响应 = requests.post(
                f"{self.API地址}/chat/completions", 
                headers=请求头, 
                json=请求体,
                timeout=240
            )
            耗时 = time.time() - 开始时间
            
            if 响应.status_code != 200:
                db_util.带时间的日志打印(f"❌ [AI] API 报错 {响应.status_code}: {响应.text}")
                return False, None

            结果 = 响应.json()
            AI回复文本 = 结果['choices'][0]['message']['content']
            
            # [Debug] 打印原始回复，方便调试 Prompt
            # db_util.带时间的日志打印(f"📜 [Debug] AI原始回复: {AI回复文本[:100]}...") 

            # 清洗 Markdown
            清洗后的文本 = AI回复文本.replace("```json", "").replace("```", "").strip()
            
            # 解析 JSON
            解析数据 = json.loads(清洗后的文本)
            解析数据 = self.修正JSON数据(解析数据) # 自动修复
            
            if 解析数据.get("is_signal"):
                方向 = 解析数据.get('direction')
                品种 = 解析数据.get('symbol')
                模式 = 解析数据.get('entry_mode', '市价')
                TP数量 = len(解析数据.get('tps', []))
                
                db_util.带时间的日志打印(f"✅ [AI] 返回分析结果 ({耗时:.2f}s)")#: {方向} {品种} | {模式} | {TP数量}个TP")
                return True, 解析数据
            else:
                db_util.带时间的日志打印(f"💤 [AI] 判定为闲聊/无效 ({耗时:.2f}s)")
                return False, None

        except json.JSONDecodeError:
            db_util.带时间的日志打印(f"❌ [AI] JSON 格式错误: {AI回复文本}...")
            return False, None
        except Exception as e:
            db_util.带时间的日志打印(f"❌ [AI] 请求异常: {e}")
            db_util.带时间的日志打印(traceback.format_exc())
            return False, None

# ===========================
# 单元测试
# ===========================
if __name__ == "__main__":
    大脑 = AI决策大脑()
    
    # 模拟一个复杂的挂单信号
    测试文本 = """
    XAUUSD Buy Limit @ 2000.0
    SL: 1990
    TP1: 2010
    TP2: 2020
    TP3: 2050
    """
    成功, 结果 = 大脑.分析信号("测试员", 测试文本)
    
    if 成功:
        print(json.dumps(结果, indent=4, ensure_ascii=False))