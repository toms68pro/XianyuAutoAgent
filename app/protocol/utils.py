import time
import random
import hashlib
from typing import Dict


def trans_cookies(cookies_str: str) -> Dict[str, str]:
    """解析 Cookie 字符串为标准字典"""
    cookies = {}
    if not cookies_str:
        return cookies
    for cookie in cookies_str.split(";"):
        cookie = cookie.strip()
        if not cookie:
            continue
        parts = cookie.split('=', 1)
        if len(parts) == 2:
            cookies[parts[0].strip()] = parts[1].strip()
    return cookies


def generate_mid() -> str:
    """生成 LWP 消息包唯一 ID"""
    random_part = int(1000 * random.random())
    timestamp = int(time.time() * 1000)
    return f"{random_part}{timestamp} 0"


def generate_uuid() -> str:
    """生成唯一 UUID 消息跟踪码"""
    timestamp = int(time.time() * 1000)
    return f"-{timestamp}1"


def generate_device_id(user_id: str) -> str:
    """生成模拟浏览器/客户端设备 ID"""
    chars = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
    result = []
    for i in range(36):
        if i in [8, 13, 18, 23]:
            result.append("-")
        elif i == 14:
            result.append("4")
        elif i == 19:
            rand_val = int(16 * random.random())
            result.append(chars[(rand_val & 0x3) | 0x8])
        else:
            rand_val = int(16 * random.random())
            result.append(chars[rand_val])
    return ''.join(result) + "-" + str(user_id)


def generate_sign(t: str, token: str, data: str) -> str:
    """生成闲鱼 MTOP 请求 MD5 签名"""
    app_key = "34839810"
    msg = f"{token}&{t}&{app_key}&{data}"
    md5_hash = hashlib.md5()
    md5_hash.update(msg.encode('utf-8'))
    return md5_hash.hexdigest()
