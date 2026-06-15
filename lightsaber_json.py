import os
import asyncio
import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from volcenginesdkarkruntime import Ark
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv('API_KEY')
if not API_KEY:
    raise RuntimeError("请在 .env 文件中设置 API_KEY")

client = Ark(
    base_url='https://ark.cn-beijing.volces.com/api/v3',
    api_key=API_KEY,
)

_executor = ThreadPoolExecutor(max_workers=2)


async def async_create_response(model: str, input_messages: list):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        _executor,
        lambda: client.responses.create(model=model, input=input_messages)
    )


def build_json_prompt(user_description: str) -> str:
    """
    构建提示词：将用户的自然语言描述转换为光剑控制 JSON。
    """
    prompt = f"""你是一个专门将自然语言指令转换为光剑灯光/声音控制 JSON 的助手。

【用户描述】
{user_description}

【目标 JSON 格式】
{{
    "type": 0,
    "data": {{
        "duration": 20000,
        "cycles": 10,
        "style": 1,
        "color_st": [255, 0, 0],
        "color_ed": [128, 0, 128],
        "music": "swing_2s",
        "pram": {{
            "surge_intensity": 100
        }}
    }}
}}

【字段说明及映射规则】
- type: 固定为 0。
- duration: 整体效果持续时间，单位毫秒。根据用户描述的“快慢”、“长短”决定。  
  快速闪烁/短时间 → 1000~5000；中等 → 5000~15000；长时间呼吸/缓慢变化 → 15000~60000。
- cycles: 重复次数。用户说“重复几次”、“循环”等。若未明确，根据 duration 和单个周期估算，也可默认 10。
- style: 视觉效果风格（整数 0~3）。  
  0=柔和渐变（呼吸灯、缓慢过渡）  
  1=活泼跳变（快速闪烁、彩色切换）  
  2=奇幻波浪（流水灯、彩虹滚动）  
  3=科技脉冲（硬边、高频爆闪）  
  根据用户描述中的形容词选择最接近的。
- color_st: 起始颜色 RGB 数组 [R,G,B]，每个 0-255。根据用户描述的开始颜色或主色调。
- color_ed: 结束颜色 RGB 数组。若描述为单色闪烁，则与 color_st 相同；渐变则设为目标色。
- music: 固定为 "swing_2s"（音频文件名，不含后缀）。
- pram.surge_intensity: 强度/功率 0-100。用户说“强/猛/亮/爆闪”则 80-100；“柔和/弱/暗”则 0-30；中等 40-70。

【输出要求】
- 只输出纯 JSON 字符串，不要有任何额外文字、注释或 Markdown 标记。
- 必须严格符合上述 JSON 结构，字段名和嵌套层级完全一致。
- 如果用户描述中缺失某些字段信息，请根据常识或默认值合理推测（例如未提及颜色则使用默认 [255,255,255]；未提及强度则 70）。

请直接输出 JSON："""

    return prompt


def extract_json(response) -> dict:
    """从大模型响应中提取 JSON 对象。"""
    text = ""
    if response.output:
        for item in response.output:
            if hasattr(item, 'content'):
                for content_part in item.content:
                    if content_part.type == 'output_text':
                        text += content_part.text
    text = text.strip()
    # 清理可能的 markdown 代码块标记
    if text.startswith("```json"):
        text = text[7:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()
    try:
        obj = json.loads(text)
        return obj
    except json.JSONDecodeError:
        print(f"❌ JSON 解析失败，原始输出：\n{text}")
        raise


async def generate_lightsaber_json(user_description: str) -> dict:
    """根据用户描述生成光剑控制 JSON。"""
    prompt = build_json_prompt(user_description)
    print("🎨 正在生成光剑控制 JSON ...")
    response = await async_create_response(
        model="deepseek-v3-2-251201",   # 可根据需要修改模型
        input_messages=[{"role": "user", "content": prompt}]
    )
    return extract_json(response)


async def main():
    parser = argparse.ArgumentParser(description="根据自然语言描述生成光剑控制 JSON")
    parser.add_argument("--description", type=str, help="直接提供描述文本（例如：'快速红色到蓝色闪烁，重复5次'）")
    parser.add_argument("--output", type=str, help="输出 JSON 文件路径（不指定则打印到 stdout）")
    args = parser.parse_args()

    # 获取用户描述
    if args.description:
        user_desc = args.description
    else:
        print("请输入光剑效果描述（可包含颜色、速度、强度、风格等，输入空行结束）：")
        lines = []
        while True:
            line = sys.stdin.readline().strip()
            if not line:
                break
            lines.append(line)
        user_desc = " ".join(lines)

    if not user_desc:
        print("❌ 未提供任何描述，退出。")
        sys.exit(1)

    print(f"📝 用户描述: {user_desc}")

    try:
        result_json = await generate_lightsaber_json(user_desc)
        output_str = json.dumps(result_json, ensure_ascii=False, indent=2)
        if args.output:
            with open(args.output, 'w', encoding='utf-8') as f:
                f.write(output_str)
            print(f"✅ JSON 已保存至 {args.output}")
        else:
            print(output_str)
    except Exception as e:
        print(f"❌ 生成失败: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())