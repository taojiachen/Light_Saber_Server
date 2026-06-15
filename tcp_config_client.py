#!/usr/bin/env python3
"""
TCP 配置客户端，用于与 ESP32-S3 光剑单片机通信。
功能：
1. 连接到单片机的 TCP 服务器（默认端口 8080）
2. 等待接收 JSON_REQ 请求（格式：{"type":"req","action":"get_config"}\n）
3. 响应一个符合协议规范的 JSON 配置（带前缀 JSON:xxxxxx:{...}）
4. 支持命令行参数指定单片机 IP 地址
"""

import socket
import json
import time
import argparse

# 您提供的默认配置
DEFAULT_JSON_CONFIG = {
    "type": 0,
    "data": {
        "duration": 3000,
        "cycles": 10,
        "style": 1,
        "color_st": [255, 0, 0],
        "color_ed": [128, 0, 128],
        "music": "swing_2s",
        "pram": {
            "surge_intensity": 90
        }
    }
}

def build_response(json_obj):
    """
    根据协议构建响应字符串：JSON:xxxxxx:{...}
    其中 xxxxxx 是 JSON 字符串的字节长度（十进制，8位数字，前面补零）
    """
    # 紧凑格式，无多余空格
    json_str = json.dumps(json_obj, separators=(',', ':'))
    content_length = len(json_str.encode('utf-8'))
    length_str = f"{content_length:08d}"
    response = f"JSON:{length_str}:{json_str}"
    return response

def parse_json_req(data):
    """
    解析单片机发送的 JSON_REQ（纯 JSON，无前缀）
    """
    # 查找第一个 '{' 的位置
    start = data.find(b'{')
    if start == -1:
        return None
    json_part = data[start:]
    try:
        req = json.loads(json_part.decode('utf-8'))
        return req
    except Exception as e:
        print(f"JSON 解析失败: {e}")
        return None

def main():
    parser = argparse.ArgumentParser(description='ESP32-S3 TCP 配置客户端')
    parser.add_argument('--ip', type=str, default='192.168.3.82',
                        help='单片机 IP 地址（默认 192.168.3.82）')
    parser.add_argument('--port', type=int, default=8080,
                        help='单片机 TCP 端口（默认 8080）')
    args = parser.parse_args()

    # 准备响应字符串
    response = build_response(DEFAULT_JSON_CONFIG)
    print("响应 JSON:")
    print(json.dumps(DEFAULT_JSON_CONFIG, indent=2))
    print(f"完整响应: {response}\n")

    # 持续尝试连接并处理请求
    while True:
        try:
            print(f"正在连接 {args.ip}:{args.port} ...")
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(10)
            sock.connect((args.ip, args.port))
            print("连接成功！等待单片机发送 JSON_REQ ...")
            sock.settimeout(30)

            while True:
                try:
                    data = sock.recv(4096)
                    if not data:
                        print("连接已断开（单片机关闭连接）")
                        break

                    print(f"收到数据 ({len(data)} 字节): {data[:100]}")
                    req = parse_json_req(data)
                    if req and req.get('type') == 'req' and req.get('action') == 'get_config':
                        print("识别为 JSON_REQ，发送配置响应...")
                        sock.sendall(response.encode('utf-8'))
                        print("配置已发送，等待下一次请求...")
                    else:
                        print("收到非预期数据，忽略")

                except socket.timeout:
                    print("接收超时，继续等待...")
                    continue
                except Exception as e:
                    print(f"接收错误: {e}")
                    break

        except socket.timeout:
            print("连接超时，5秒后重试...")
            time.sleep(5)
        except ConnectionRefusedError:
            print("连接被拒绝，请检查单片机 TCP 服务器是否启动")
            time.sleep(5)
        except Exception as e:
            print(f"连接失败: {e}")
            time.sleep(5)
        finally:
            try:
                sock.close()
            except:
                pass

if __name__ == '__main__':
    main()