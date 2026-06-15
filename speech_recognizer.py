import json
import time
import uuid
import requests
import base64
import os
from dotenv import load_dotenv

load_dotenv()

def file_to_base64(file_path):
    with open(file_path, 'rb') as file:
        return base64.b64encode(file.read()).decode('utf-8')

def recognize_audio(file_path: str) -> str:
    """
    识别音频文件，返回识别出的文字字符串。
    如果识别失败，抛出异常。
    """
    recognize_url = "https://openspeech.bytedance.com/api/v3/auc/bigmodel/recognize/flash"
    appid = os.getenv("APPID")
    token = os.getenv("ACCESS_KEY")

    if not appid or not token:
        raise RuntimeError("请在 .env 文件中设置 APPID 和 ACCESS_KEY")

    headers = {
        "X-Api-App-Key": appid,
        "X-Api-Access-Key": token,
        "X-Api-Resource-Id": "volc.bigasr.auc_turbo",
        "X-Api-Request-Id": str(uuid.uuid4()),
        "X-Api-Sequence": "-1",
    }

    if not os.path.exists(file_path):
        raise FileNotFoundError(f"音频文件不存在: {file_path}")

    base64_data = file_to_base64(file_path)
    request_body = {
        "user": {"uid": appid},
        "audio": {"data": base64_data},
        "request": {"model_name": "bigmodel"},
    }

    response = requests.post(recognize_url, json=request_body, headers=headers)
    status_code = response.headers.get('X-Api-Status-Code')
    if status_code != '20000000':
        error_msg = response.headers.get('X-Api-Message', '未知错误')
        raise RuntimeError(f"识别失败 {status_code}: {error_msg}")

    result = response.json()
    # 提取文字：根据您实际返回的结构，文字在 result['result']['text']
    text = result.get('result', {}).get('text', '')
    if not text:
        # 备用方案：可能直接在顶层
        text = result.get('text', '')
    return text.strip()