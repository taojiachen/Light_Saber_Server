import asyncio
import argparse
import ssl

import config
from audio_manager import DialogSession
from esp_websocket_server import ESPWebSocketServer
from db_manager import AsyncMySQLManager
import ip_shadow_updater
from http_server import start_http_server   # 新增导入 HTTP 服务器启动函数

async def main() -> None:
    parser = argparse.ArgumentParser(description="Real-time Dialog Client")
    parser.add_argument("--format", type=str, default="pcm", help="The audio format (e.g., pcm, pcm_s16le).")
    parser.add_argument("--audio", type=str, default="", help="audio file send to server, if not set, will use microphone input.")
    parser.add_argument("--mod", type=str, default="audio", help="Use mod to select plain text input mode or audio mode, the default is audio mode")
    parser.add_argument("--recv_timeout", type=int, default=10, help="Timeout for receiving messages,value range [10,120]")
    parser.add_argument("--use-microphone", action="store_true", help="Use computer microphone instead of ESP device audio")
    args = parser.parse_args()

    # ---------- 数据库 ----------
    db_manager = AsyncMySQLManager(config.db_config)
    await db_manager.ensure_database()
    await db_manager.create_pool()
    await db_manager.init_tables()

    # ---------- 对话会话 ----------
    session = DialogSession(
        ws_config=config.ws_connect_config,
        output_audio_format=args.format,
        audio_file_path=args.audio,
        mod=args.mod,
        recv_timeout=args.recv_timeout,
        use_microphone=args.use_microphone
    )

    # ---------- ESP WebSocket 服务器 ----------
    esp_server = ESPWebSocketServer(host='0.0.0.0', port=8765)
    esp_server.db_manager = db_manager

    session.set_esp_server(esp_server)
    session.db_manager = db_manager

    # ---------- 任务定义 ----------
    async def start_server():
        try:
            await esp_server.start(session)
        except Exception as e:
            print(f"ESP WebSocket服务器启动失败: {e}")

    async def start_client():
        try:
            await session.start()
        except Exception as e:
            print(f"对话客户端启动失败: {e}")

    # ---------- SSL 配置 ----------
    ssl_context = None
    try:
        ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        ssl_context.load_cert_chain('server.crt', 'server.key')
        print("✅ 加载 SSL 证书成功")
    except Exception as e:
        print(f"⚠️ 加载 SSL 证书失败，将使用 HTTP: {e}")

    # 启动 IP 影子监控（每 60 秒检查一次）
    ip_monitor_task = asyncio.create_task(ip_shadow_updater.start_ip_shadow_monitor(60))

    # 启动 HTTP 服务器（监听 8081 端口，提供 /media/list 和 /media/{filename} 接口）
    http_task = asyncio.create_task(start_http_server(host='0.0.0.0', port=8081))

    # 同时运行 ESP 服务器、对话客户端、IP 监控和 HTTP 服务器
    try:
        await asyncio.gather(
            start_server(),
            start_client(),
            ip_monitor_task,
            http_task,
            return_exceptions=True
        )
    finally:
        await db_manager.close_pool()

if __name__ == "__main__":
    asyncio.run(main())