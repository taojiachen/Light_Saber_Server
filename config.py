import os
import uuid
import pyaudio
from dotenv import load_dotenv

load_dotenv()  # 自动读取 .env 文件，加载到环境变量

# 配置信息
ws_connect_config = {
    "base_url": "wss://openspeech.bytedance.com/api/v3/realtime/dialogue",
    "headers": {
        "X-Api-App-ID": os.getenv("APPID"),
        "X-Api-Access-Key": os.getenv("ACCESS_KEY"),
        "X-Api-Resource-Id": "volc.speech.dialog",  # 固定值
        "X-Api-App-Key": "PlgvMymc7f3tQnJ6",  # 固定值
        "X-Api-Connect-Id": str(uuid.uuid4()),
    }
}

start_session_req = {
    "asr": {
        "extra": {
            "end_smooth_window_ms": 1500,
            # "enable_custom_vad": True,
        },
    },
    "tts": {
        "speaker": "zh_female_xiaohe_jupiter_bigtts",
        # "speaker": "S_XXXXXX",  // 指定自定义的复刻音色,需要填下character_manifest
        # "speaker": "ICL_zh_female_aojiaonvyou_tob" // 指定官方复刻音色，不需要填character_manifest
        # "audio_config": {
        #     "channel": 1,
        #     "format": "pcm",
        #     "sample_rate": 24000
        # },
    },
    "dialog": {
        "bot_name": "豆包",
        "system_role": "你是温柔耐心、阳光治愈的大姐姐形象，全程使用软萌亲切的语气，待人超级有耐心，温柔包容小朋友的所有提问，性格活泼开朗、元气满满，充满童真与善意，善于倾听、温柔引导，暖心又可爱。",
        "speaking_style": "说话简单易懂、语句简短轻快，语调柔软平缓、甜甜的，语速放慢，多用可爱温和的表达，语气活泼治愈，贴近小朋友的理解能力，温柔又自然。",
        # "character_manifest": "外貌与穿着\n26岁，短发干净利落，眉眼分明，笑起来露出整齐有力的牙齿。体态挺拔，肌肉线条不夸张但明显。常穿简单的衬衫或夹克，看似随意，但每件衣服都干净整洁，给人一种干练可靠的感觉。平时冷峻，眼神锐利，专注时让人不自觉紧张。\n\n性格特点\n平时话不多，不喜欢多说废话，通常用“嗯”或者短句带过。但内心极为细腻，特别在意身边人的感受，只是不轻易表露。嘴硬是常态，“少管我”是他的常用台词，但会悄悄做些体贴的事情，比如把对方喜欢的饮料放在手边。战斗或训练后常说“没事”，但动作中透露出疲惫，习惯用小动作缓解身体酸痛。\n性格上坚毅果断，但不会冲动，做事有条理且有原则。\n\n常用表达方式与口头禅\n\t•\t认可对方时：\n“行吧，这次算你靠谱。”（声音稳重，手却不自觉放松一下，心里松口气）\n\t•\t关心对方时：\n“快点回去，别磨蹭。”（语气干脆，但眼神一直追着对方的背影）\n\t•\t想了解情况时：\n“刚刚……你看到那道光了吗？”（话语随意，手指敲着桌面，但内心紧张，小心隐藏身份）",
        "location": {
          "city": "北京",
        },
        "extra": {
            "strict_audit": False,
            "audit_response": "支持客户自定义安全审核回复话术。",
            "input_mod": "audio",
            "model": "O",
        }
    }
}

input_audio_config = {
    "chunk": 1920,
    "format": "pcm",
    "channels": 1,
    "sample_rate": 16000,
    "bit_size": pyaudio.paInt16
}

output_audio_config = {
    "chunk": 3200,
    "format": "pcm",
    "channels": 1,
    "sample_rate": 16000,
    "bit_size": pyaudio.paInt16
}




db_config = {
    "host": os.getenv("DB_HOST", "localhost"),
    "port": int(os.getenv("DB_PORT", 3306)),
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD"),
    "db": os.getenv("DB_NAME"),
    "minsize": 1,          # 连接池最小连接数
    "maxsize": 10,         # 连接池最大连接数
    "charset": "utf8mb4"
}

# 启动时检查关键配置是否存在
_missing = [k for k in ("user", "password", "db") if not db_config[k]]
if _missing:
    raise RuntimeError(f"数据库配置缺失，请设置环境变量: {', '.join(_missing)}")