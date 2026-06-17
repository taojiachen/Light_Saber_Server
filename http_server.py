# http_server.py
import os
import json
import time
from pathlib import Path
from aiohttp import web

# 媒体文件目录（项目根目录下的 media 文件夹）
MEDIA_DIR = Path(__file__).parent / "media"

async def list_files(request):
    """GET /media/list 返回媒体文件列表（JSON）"""
    try:
        files = []
        for entry in MEDIA_DIR.iterdir():
            if entry.is_file() and entry.suffix.lower() == '.opus':
                stat = entry.stat()
                files.append({
                    "name": entry.name,
                    "size": stat.st_size,
                    "modified": stat.st_mtime
                })
        # 按文件名排序
        files.sort(key=lambda x: x["name"])
        return web.json_response({"files": files, "count": len(files)})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

async def download_file(request):
    """GET /media/{filename} 下载指定的 .opus 文件"""
    filename = request.match_info.get('filename')
    if not filename:
        return web.json_response({"error": "Missing filename"}, status=400)

    # 防止路径遍历攻击
    if '..' in filename or '/' in filename or '\\' in filename:
        return web.json_response({"error": "Invalid filename"}, status=400)

    file_path = MEDIA_DIR / filename
    if not file_path.exists():
        return web.json_response({"error": "File not found"}, status=404)

    # 返回文件流（自动处理 Content-Type 和 Content-Length）
    return web.FileResponse(file_path, headers={
        "Content-Disposition": f'attachment; filename="{filename}"'
    })

async def health_check(request):
    """健康检查接口"""
    return web.json_response({"status": "ok", "timestamp": time.time()})

def create_app():
    """创建 aiohttp web 应用并注册路由"""
    app = web.Application()
    app.router.add_get('/media/list', list_files)
    app.router.add_get('/media/{filename}', download_file)
    app.router.add_get('/health', health_check)
    return app

async def start_http_server(host='0.0.0.0', port=8081):
    """启动 HTTP 服务器（作为后台任务）"""
    app = create_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    print(f"✅ HTTP 服务器已启动: http://{host}:{port}")
    # 保持运行，直到被取消
    try:
        await asyncio.Event().wait()  # 永久等待
    except asyncio.CancelledError:
        await runner.cleanup()
        raise