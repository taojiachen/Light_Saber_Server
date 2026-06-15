# ip_shadow_updater.py
import asyncio
import time
import socket
import hmac
import hashlib
import json
import os
from dotenv import load_dotenv
import paho.mqtt.client as mqtt

load_dotenv()

PRODUCT_KEY = os.getenv("PRODUCT_KEY")
DEVICE_NAME = os.getenv("DEVICE_NAME")
DEVICE_SECRET = os.getenv("DEVICE_SECRET")

if not all([PRODUCT_KEY, DEVICE_NAME, DEVICE_SECRET]):
    raise RuntimeError("请在 .env 中设置 PRODUCT_KEY, DEVICE_NAME, DEVICE_SECRET")

SHADOW_UPDATE_TOPIC = f"/shadow/update/{PRODUCT_KEY}/{DEVICE_NAME}"
BROKER = f"{PRODUCT_KEY}.iot-as-mqtt.cn-shanghai.aliyuncs.com"
PORT = 1883

# 全局变量：记录上一次上传的 IP
_last_uploaded_ip = None

def get_local_ip():
    """获取本机局域网 IPv4 地址（用于访问外网的网卡）"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

def generate_mqtt_credentials():
    """生成阿里云 MQTT 连接凭证"""
    timestamp = str(int(time.time() * 1000))
    client_id = f"{DEVICE_NAME}|securemode=3,signmethod=hmacsha1,timestamp={timestamp}|"
    username = f"{DEVICE_NAME}&{PRODUCT_KEY}"
    content = f"clientId{DEVICE_NAME}deviceName{DEVICE_NAME}productKey{PRODUCT_KEY}timestamp{timestamp}"
    signature = hmac.new(DEVICE_SECRET.encode(), msg=content.encode(), digestmod=hashlib.sha1).hexdigest()
    password = signature
    return client_id, username, password

def update_ip_shadow(ip_address):
    """
    同步方式：连接 MQTT 并更新影子中的 reported.ip
    返回 True 表示成功
    """
    client_id, username, password = generate_mqtt_credentials()
    mqtt_client = mqtt.Client(client_id=client_id, clean_session=False)
    mqtt_client.username_pw_set(username, password)

    # 连接标志
    connected = False

    def on_connect(client, userdata, flags, rc):
        nonlocal connected
        if rc == 0:
            connected = True
            print(f"[IP影子] MQTT 连接成功")
        else:
            print(f"[IP影子] MQTT 连接失败，rc={rc}")

    mqtt_client.on_connect = on_connect
    mqtt_client.connect(BROKER, PORT, 60)
    mqtt_client.loop_start()  # 非阻塞循环，等待连接完成

    # 等待连接建立（最多 5 秒）
    timeout = 5
    start = time.time()
    while not connected and time.time() - start < timeout:
        time.sleep(0.1)
    if not connected:
        print("[IP影子] 连接超时，无法更新影子")
        mqtt_client.loop_stop()
        return False

    # 构造更新 payload
    payload = {
        "method": "update",
        "state": {
            "reported": {
                "ip": ip_address
            }
        },
        "version": 0  # 0 表示强制覆盖
    }
    msg = json.dumps(payload)
    result = mqtt_client.publish(SHADOW_UPDATE_TOPIC, msg, qos=1)
    if result.rc == mqtt.MQTT_ERR_SUCCESS:
        print(f"[IP影子] 成功上传 IP: {ip_address}")
    else:
        print(f"[IP影子] 发布失败，rc={result.rc}")

    mqtt_client.loop_stop()
    mqtt_client.disconnect()
    return result.rc == mqtt.MQTT_ERR_SUCCESS

async def _monitor_loop(interval_seconds: int):
    """后台监控协程：每隔 interval 秒检查一次 IP，变化时上传"""
    global _last_uploaded_ip
    # 启动时立即上传一次
    current_ip = get_local_ip()
    if current_ip:
        print(f"[IP影子] 启动检测，当前 IP = {current_ip}")
        # 在线程中执行同步上传任务，避免阻塞事件循环
        await asyncio.to_thread(update_ip_shadow, current_ip)
        _last_uploaded_ip = current_ip
    else:
        print("[IP影子] 警告：无法获取本机 IP")

    while True:
        await asyncio.sleep(interval_seconds)
        new_ip = get_local_ip()
        if new_ip and new_ip != _last_uploaded_ip:
            print(f"[IP影子] IP 已变更：{_last_uploaded_ip} -> {new_ip}，正在上传...")
            await asyncio.to_thread(update_ip_shadow, new_ip)
            _last_uploaded_ip = new_ip
        else:
            print(f"[IP影子] IP 未变化 ({new_ip})，跳过上传")

def start_ip_shadow_monitor(interval_seconds: int = 60):
    """
    启动 IP 影子监控任务，作为后台 asyncio 任务运行。
    建议在 main() 函数中调用：
        asyncio.create_task(start_ip_shadow_monitor(60))
    """
    return _monitor_loop(interval_seconds)