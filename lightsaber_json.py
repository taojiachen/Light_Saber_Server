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

def build_json_prompt(user_description: str, previous_json: dict = None) -> str:
    # 基础字段说明（共用）
    field_desc = """
【字段说明及映射规则】
- type: 固定为 0。
- duration: 整体效果持续时间，单位毫秒。根据用户描述的“快慢”、“长短”决定。  
  快速闪烁/短时间 → 1000~5000；中等 → 5000~15000；长时间呼吸/缓慢变化 → 15000~60000。
- cycles: 重复次数。用户说“重复几次”、“循环”等。若未明确，默认 10。
- style: 视觉效果风格（整数 0~3）。  
  0=呼吸灯、两种颜色之间的缓慢过渡，如果没有强调哪种颜色和哪种颜色之间渐变，默认和黑色
  1=快速闪烁、两种颜色之间的瞬间切换，如果没有强调哪种颜色和哪种颜色之间闪烁，默认和黑色
  2=流水灯
  3=脉冲
  根据用户描述中的关键词选择最接近的。例如“流水灯”或“彩虹” → 2。
- color_st: 起始颜色 RGB 数组 [R,G,B]，每个 0-255。根据用户描述的开始颜色或主色调。
- color_ed: 结束颜色 RGB 数组。若描述为单色闪烁，则与 color_st 相同；渐变则设为目标色。
- music: 固定为 "swing_2s"。
- pram.surge_intensity: 强度/功率 0-100。用户说“强/猛/亮/爆闪”则 80-100；“柔和/弱/暗”则 0-30；中等 40-70。
"""

    if previous_json:
        prompt = f"""你是一个专门将自然语言指令转换为光剑灯光/声音控制 JSON 的助手。

【上一次生成的光效 JSON】
{json.dumps(previous_json, ensure_ascii=False, indent=2)}

【用户最新描述】
{user_description}

【意图判断】
- 如果用户描述中包含“修改”、“调整”、“改变”、“再”、“更”、“换成”、“改”等明显表示修改的词语，或者描述的内容与上一次效果有直接关联（例如“快一点”、“亮一些”、“颜色变成蓝色”），则**基于上一次 JSON 进行修改**，只改动用户提到的字段，其余保持不变。
- 如果用户描述是一个全新的效果名称（如“流水灯”、“呼吸灯”、“彩虹”、“爆闪”、“波浪”、“渐变”等），或者描述的内容与上一次完全无关，则**忽略上一次 JSON，完全重新生成**一个新的 JSON。

请根据上述判断，执行相应操作，并输出完整的 JSON。

{field_desc}

【输出要求】
- 只输出纯 JSON 字符串，不要有任何额外文字、注释或 Markdown 标记。
- 必须严格符合上述 JSON 结构（{{"type":0, "data":{{...}}}}）。
- 如果重新生成，请根据描述合理填充所有字段。

请直接输出 JSON："""
    else:
        prompt = f"""你是一个专门将自然语言指令转换为光剑灯光/声音控制 JSON 的助手。

【用户描述】
{user_description}

请根据描述生成一个符合以下格式的 JSON。

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

{field_desc}

【输出要求】
- 只输出纯 JSON 字符串，不要有任何额外文字、注释或 Markdown 标记。
- 必须严格符合上述 JSON 结构，字段名和嵌套层级完全一致。
- 如果描述中缺失某些字段信息，请根据常识或默认值合理推测。

请直接输出 JSON："""
    return prompt

def extract_json(response) -> dict:
    text = ""
    if response.output:
        for item in response.output:
            if hasattr(item, 'content'):
                for content_part in item.content:
                    if content_part.type == 'output_text':
                        text += content_part.text
    text = text.strip()
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

async def generate_lightsaber_json(user_description: str, previous_json: dict = None) -> dict:
    prompt = build_json_prompt(user_description, previous_json)
    print("🎨 正在生成光剑控制 JSON ...")
    response = await async_create_response(
        model="deepseek-v3-2-251201",
        input_messages=[{"role": "user", "content": prompt}]
    )
    return extract_json(response)

async def main():
    parser = argparse.ArgumentParser(description="根据自然语言描述生成光剑控制 JSON")
    parser.add_argument("--description", type=str, help="直接提供描述文本")
    parser.add_argument("--output", type=str, help="输出 JSON 文件路径")
    args = parser.parse_args()

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