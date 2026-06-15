# RealtimeDialog

实时语音对话程序，支持语音输入和语音输出。

## 使用说明

此demo使用python3.7环境进行开发调试，其他python版本可能会有兼容性问题，需要自己尝试解决。

1. 配置API密钥
   - 打开 `config.py` 文件
   - 修改以下两个字段：
     ```python
     "X-Api-App-ID": "火山控制台上端到端大模型对应的App ID",
     "X-Api-Access-Key": "火山控制台上端到端大模型对应的Access Key",
     ```
   - 修改speaker字段指定发音人，本次支持四个发音人：
     - `zh_female_vv_jupiter_bigtts`：中文vv女声
     - `zh_female_xiaohe_jupiter_bigtts`：中文xiaohe女声
     - `zh_male_yunzhou_jupiter_bigtts`：中文云洲男声
     - `zh_male_xiaotian_jupiter_bigtts`：中文小天男声

2. 安装依赖
   ```bash
   pip install -r requirements.txt
   
3. 通过麦克风运行程序
   ```bash
   python main.py --format=pcm
   ```
4. 通过录音文件启动程序
   ```bash
   python main.py --audio=whoareyou.wav
   ```
5. 通过纯文本输入和程序交互
   ```bash
   python main.py --mod=text --recv_timeout=120
   ```

## 注意事项
- 需要在火山控制台上开通端到端大模型服务，并获取对应的App ID和Access Key。
- 安装火山引擎Python SDK(AI推理任务画像，精简上下文)
   ```bash
   pip install --upgrade "volcengine-python-sdk[ark]"
   ```
- 安装异步IO库（AI绘图模块使用
   ```bash
   pip install aiohttp aiofiles
   ```