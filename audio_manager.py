import asyncio
import queue
import random
import signal
import sys
import threading
import time
import uuid
import wave
import json
import copy
from dataclasses import dataclass
from typing import Optional, Dict, Any

import pyaudio

import config
from realtime_dialog_client import RealtimeDialogClient


@dataclass
class AudioConfig:
    format: str
    bit_size: int
    channels: int
    sample_rate: int
    chunk: int


class AudioDeviceManager:
    def __init__(self, input_config: AudioConfig, output_config: AudioConfig):
        self.input_config = input_config
        self.output_config = output_config
        self.pyaudio = pyaudio.PyAudio()
        self.input_stream: Optional[pyaudio.Stream] = None
        self.output_stream: Optional[pyaudio.Stream] = None

    def open_input_stream(self) -> pyaudio.Stream:
        self.input_stream = self.pyaudio.open(
            format=self.input_config.bit_size,
            channels=self.input_config.channels,
            rate=self.input_config.sample_rate,
            input=True,
            frames_per_buffer=self.input_config.chunk
        )
        return self.input_stream

    def open_output_stream(self) -> pyaudio.Stream:
        self.output_stream = self.pyaudio.open(
            format=self.output_config.bit_size,
            channels=self.output_config.channels,
            rate=self.output_config.sample_rate,
            output=True,
            frames_per_buffer=self.output_config.chunk
        )
        return self.output_stream

    def cleanup(self):
        if self.input_stream:
            self.input_stream.stop_stream()
            self.input_stream.close()
        if self.output_stream:
            self.output_stream.stop_stream()
            self.output_stream.close()
        self.pyaudio.terminate()


class DialogSession:
    is_audio_file_input: bool
    mod: str

    def __init__(self, ws_config: Dict[str, Any], output_audio_format: str = "pcm", audio_file_path: str = "",
                 mod: str = "audio", recv_timeout: int = 10, use_microphone: bool = False):
        self.audio_file_path = audio_file_path
        self.recv_timeout = recv_timeout
        self.is_audio_file_input = self.audio_file_path != ""
        self.use_microphone = use_microphone
        self.db_manager = None
        self.mac_address = None
        self.history_summary = None
        self.custom_start_session_req = copy.deepcopy(config.start_session_req)
        self.current_milestone = 1

        self.current_audio_buffer = b''
        self.is_audio_accumulating = False
        self.audio_start_time = None
        self.real_time_sending = False
        self.audio_send_queue = asyncio.Queue()
        self.send_task = None
        self.accumulated_buffer = b''
        self.say_hello_over_event = asyncio.Event()

        if self.is_audio_file_input:
            mod = 'audio_file'
        elif not self.use_microphone:
            mod = 'esp_audio'
        self.mod = mod
        self.session_id = str(uuid.uuid4())

        self.client = RealtimeDialogClient(
            config=ws_config,
            session_id=self.session_id,
            output_audio_format=output_audio_format,
            mod=mod,
            recv_timeout=recv_timeout,
            start_session_req=self.custom_start_session_req
        )

        if output_audio_format == "pcm_s16le":
            config.output_audio_config["format"] = "pcm_s16le"
            config.output_audio_config["bit_size"] = pyaudio.paInt16

        self.is_processing_audio = False
        self.current_audio_task = None
        self.audio_pending_queue = asyncio.Queue()
        self.is_running = True
        self.is_session_finished = False
        self.is_user_querying = False
        self.is_sending_chat_tts_text = False
        self.audio_buffer = b''
        self.esp_server = None

        signal.signal(signal.SIGINT, self._keyboard_signal)
        self.audio_queue = queue.Queue()
        if not self.is_audio_file_input:
            self.audio_device = AudioDeviceManager(
                AudioConfig(**config.input_audio_config),
                AudioConfig(**config.output_audio_config)
            )
            self.output_stream = self.audio_device.open_output_stream()

    def _audio_player_thread(self):
        while self.is_playing:
            try:
                audio_data = self.audio_queue.get(timeout=1.0)
                if audio_data is not None:
                    print(f"播放音频数据: {len(audio_data)} 字节")
                    self.output_stream.write(audio_data)
            except queue.Empty:
                time.sleep(0.1)
            except Exception as e:
                print(f"音频播放错误: {e}")

    def set_esp_server(self, esp_server):
        self.esp_server = esp_server
        print("ESP服务器引用已设置")

    async def handle_server_response(self, response):
        if response['message_type'] == 'SERVER_ACK' and isinstance(response.get('payload_msg'), bytes):
            print(f"\n接收到音频数据: {len(response['payload_msg'])} 字节")
            audio_data = response['payload_msg']
            if not self.is_audio_file_input:
                self.audio_queue.put(audio_data)
            self.audio_buffer += audio_data

            if not self.is_audio_accumulating:
                self.is_audio_accumulating = True
                self.current_audio_buffer = b''
                self.audio_start_time = time.time()
                await self.start_real_time_sending()

            self.current_audio_buffer += audio_data

            if self.real_time_sending and self.esp_server and hasattr(self.esp_server, 'active_connections'):
                self.accumulated_buffer += audio_data
                while len(self.accumulated_buffer) >= 960:
                    chunk = self.accumulated_buffer[:960]
                    self.accumulated_buffer = self.accumulated_buffer[960:]
                    await asyncio.gather(
                        *[conn.send(chunk) for conn in self.esp_server.active_connections],
                        return_exceptions=True
                    )
                    await asyncio.sleep(0.08)

        elif response['message_type'] == 'SERVER_FULL_RESPONSE':
            print(f"服务器响应: {response}")
            event = response.get('event')
            payload_msg = response.get('payload_msg', {})

            if event == 450:
                print(f"清空缓存音频: {response['session_id']}")
                while not self.audio_queue.empty():
                    try:
                        self.audio_queue.get_nowait()
                    except queue.Empty:
                        continue
                self.is_user_querying = False
                self.current_audio_buffer = b''
                self.is_audio_accumulating = False
                await self.stop_real_time_sending()
                self.accumulated_buffer = b''
                self.current_reply_text = ''

            if event == 550:
                content = payload_msg.get('content', '')
                if content:
                    self.current_reply_text += content

            if event == 350 and payload_msg.get("tts_type") in ["chat_tts_text", "external_rag"]:
                while not self.audio_queue.empty():
                    try:
                        self.audio_queue.get_nowait()
                    except queue.Empty:
                        continue
                self.is_sending_chat_tts_text = False

            if event == 451:
                results = payload_msg.get('results', [])
                for result in results:
                    if not result.get('is_interim', True):
                        user_text = result.get('text', '')
                        if user_text:
                            print(f"用户说: {user_text}")
                            if self.db_manager and self.mac_address:
                                await self.db_manager.add_message(self.mac_address, 'user', user_text, self.current_milestone)

            if event == 351:
                text = payload_msg.get('text', '')
                full_reply = text if text else self.current_reply_text
                if full_reply:
                    print(f"AI 回复: {full_reply}")
                    if self.db_manager and self.mac_address:
                        await self.db_manager.add_message(self.mac_address, 'AI', full_reply, self.current_milestone)
                    self.current_reply_text = ''

            if event == 459:
                self.is_user_querying = False
                if random.randint(0, 100000) % 1000 == 0:
                    self.is_sending_chat_tts_text = True
                    asyncio.create_task(self.trigger_chat_tts_text())
                    asyncio.create_task(self.trigger_chat_rag_text())

            if event == 359:
                if self.current_reply_text:
                    if self.db_manager and self.mac_address:
                        await self.db_manager.add_message(self.mac_address, 'AI', self.current_reply_text, self.current_milestone)
                    self.current_reply_text = ''
                print("收到音频结束事件，发送剩余音频数据")
                if len(self.accumulated_buffer) > 0:
                    await asyncio.gather(
                        *[conn.send(self.accumulated_buffer) for conn in self.esp_server.active_connections],
                        return_exceptions=True
                    )
                    self.accumulated_buffer = b''
                await self.send_audio_end_notification()
                self.current_audio_buffer = b''
                self.is_audio_accumulating = False

        elif response['message_type'] == 'SERVER_ERROR':
            print(f"服务器错误: {response['payload_msg']}")
            raise Exception("服务器错误")

    async def start_real_time_sending(self):
        if self.real_time_sending:
            return
        self.real_time_sending = True
        await self.send_audio_start_notification()

    async def stop_real_time_sending(self):
        if not self.real_time_sending:
            return
        self.real_time_sending = False

    async def send_audio_start_notification(self):
        if not self.esp_server or not self.esp_server.active_connections:
            return
        start_notification = {
            "type": "audio_start",
            "timestamp": int(time.time()),
            "message": "开始实时接收音频数据"
        }
        start_json = json.dumps(start_notification)
        await asyncio.gather(
            *[conn.send(start_json) for conn in self.esp_server.active_connections],
            return_exceptions=True
        )
        print("已发送音频开始通知到单片机")

    async def send_audio_end_notification(self):
        if not self.esp_server or not self.esp_server.active_connections:
            return
        end_notification = {
            "type": "audio_end",
            "timestamp": int(time.time()),
            "message": "音频数据接收完成"
        }
        end_json = json.dumps(end_notification)
        await asyncio.gather(
            *[conn.send(end_json) for conn in self.esp_server.active_connections],
            return_exceptions=True
        )
        print("已发送音频结束通知到单片机")

    async def restart_receive_loop(self):
        print("重启接收循环...")
        if hasattr(self, '_receive_loop_task') and self._receive_loop_task and not self._receive_loop_task.done():
            self._receive_loop_task.cancel()
            try:
                await self._receive_loop_task
            except asyncio.CancelledError:
                pass
        self.is_session_finished = False
        self.is_user_querying = False
        self.is_sending_chat_tts_text = False
        self.audio_buffer = b''
        while not self.audio_queue.empty():
            try:
                self.audio_queue.get_nowait()
            except queue.Empty:
                continue
        self._receive_loop_task = asyncio.create_task(self.receive_loop())
        print("接收循环已重启")

    def _keyboard_signal(self, sig, frame):
        print(f"receive keyboard Ctrl+C")
        asyncio.create_task(self.stop())

    async def stop(self):
        self.is_recording = False
        self.is_playing = False
        self.is_running = False

    async def receive_loop(self):
        try:
            while True:
                response = await self.client.receive_server_response()
                await self.handle_server_response(response)
                if 'event' in response and (response['event'] == 152 or response['event'] == 153):
                    print(f"receive session finished event: {response['event']}")
                    self.is_session_finished = True
                    break
                if 'event' in response and response['event'] == 359:
                    if self.is_audio_file_input:
                        print(f"receive tts ended event")
                        self.is_session_finished = True
                        break
                    else:
                        if not self.say_hello_over_event.is_set():
                            print(f"receive tts sayhello ended event")
                            self.say_hello_over_event.set()
                        if self.mod == "text":
                            print("请输入内容：")
                if 'event' in response and response['event'] == 350 and response['payload_msg'].get("tts_type") == "chat_tts_text":
                    content = response['payload_msg'].get("content", "")
        except asyncio.CancelledError:
            print("接收任务已取消")
        except Exception as e:
            print(f"接收消息错误: {e}")
        finally:
            await self.stop()
            self.is_session_finished = True

    async def process_audio_file(self) -> None:
        await self.process_audio_file_input(self.audio_file_path)

    async def process_text_input(self) -> None:
        await self.client.say_hello()
        await self.say_hello_over_event.wait()
        try:
            input_queue = queue.Queue()
            input_thread = threading.Thread(target=self.input_listener, args=(input_queue,), daemon=True)
            input_thread.start()
            while self.is_running:
                try:
                    input_str = input_queue.get_nowait()
                    if input_str is None:
                        print("Input channel closed")
                        break
                    if input_str:
                        await self.client.chat_text_query(input_str)
                except queue.Empty:
                    await asyncio.sleep(0.1)
                except Exception as e:
                    print(f"Main loop error: {e}")
                    break
        finally:
            pass

    def input_listener(self, input_queue):
        try:
            while True:
                user_input = input()
                input_queue.put(user_input)
        except EOFError:
            input_queue.put(None)

    async def trigger_chat_tts_text(self):
        pass

    async def trigger_chat_rag_text(self):
        pass

    async def process_audio_file_input(self, audio_file_path: str):
        if not audio_file_path:
            print("音频文件路径不能为空")
            return
        try:
            with wave.open(audio_file_path, 'rb') as wf:
                channels = wf.getnchannels()
                sample_width = wf.getsampwidth()
                sample_rate = wf.getframerate()
                num_frames = wf.getnframes()
                print(f"音频文件信息：通道数={channels}, 采样宽度={sample_width}, 采样率={sample_rate}, 总帧数={num_frames}")
                await self.client.say_hello()
                await self.say_hello_over_event.wait()
                chunk_size = config.input_audio_config["chunk"]
                data = wf.readframes(chunk_size)
                while data:
                    await self.client.task_request(data)
                    await asyncio.sleep(0.01)
                    data = wf.readframes(chunk_size)
                print(f"音频文件处理完成，等待服务器响应...")
        except Exception as e:
            print(f"处理音频文件时出错: {e}")

    async def process_silence_audio(self) -> None:
        silence_data = b'\x00' * 320
        await self.client.task_request(silence_data)

    async def process_microphone_input(self) -> None:
        await self.client.say_hello()
        await self.say_hello_over_event.wait()
        await self.client.chat_text_query("你好，我也叫豆包")
        stream = self.audio_device.open_input_stream()
        print("已打开麦克风，请讲话...")
        while self.is_recording:
            try:
                audio_data = stream.read(config.input_audio_config["chunk"], exception_on_overflow=False)
                save_input_pcm_to_wav(audio_data, "input.pcm")
                await self.client.task_request(audio_data)
                await asyncio.sleep(0.01)
            except Exception as e:
                print(f"读取麦克风数据出错: {e}")
                await asyncio.sleep(0.1)

    async def process_audio_queue(self):
        try:
            while True:
                try:
                    audio_data = await self.audio_pending_queue.get()
                    self.audio_pending_queue.task_done()
                    await asyncio.sleep(0.01)
                except asyncio.QueueEmpty:
                    break
        finally:
            self.is_processing_audio = False

    async def update_current_milestone(self, milestone: int):
        self.current_milestone = milestone
        if self.db_manager and self.mac_address:
            await self.db_manager.update_device_current_milestone(self.mac_address, milestone)
            print(f"🔄 对话会话里程碑已更新为 {milestone}")

    async def start(self) -> None:
        try:
            if self.db_manager and not self.mac_address:
                print("⏳ 等待 ESP 设备上报 MAC 地址...")
                while not self.mac_address:
                    await asyncio.sleep(0.2)
                print(f"✅ 已获取 MAC 地址: {self.mac_address}")

            if self.db_manager and self.mac_address:
                self.current_milestone = await self.db_manager.get_device_current_milestone(self.mac_address)
                print(f"📌 当前里程碑: {self.current_milestone}")
                # 不再加载历史摘要，保持纯净的对话

            await self.client.connect()

            if self.mod == "text":
                asyncio.create_task(self.process_text_input())
                self._receive_loop_task = asyncio.create_task(self.receive_loop())
                while self.is_running:
                    await asyncio.sleep(0.1)
            else:
                if self.is_audio_file_input:
                    asyncio.create_task(self.process_audio_file())
                    await self.receive_loop()
                elif self.use_microphone:
                    asyncio.create_task(self.process_microphone_input())
                    self._receive_loop_task = asyncio.create_task(self.receive_loop())
                    while self.is_running:
                        await asyncio.sleep(0.1)
                else:
                    await self.client.say_hello()
                    self._receive_loop_task = asyncio.create_task(self.receive_loop())
                    while self.is_running:
                        await asyncio.sleep(0.1)

            await self.client.finish_session()
            while not self.is_session_finished:
                await asyncio.sleep(0.1)
            await self.client.finish_connection()
            await asyncio.sleep(0.1)
            await self.client.close()
            print(f"dialog request logid: {self.client.logid}, chat mod: {self.mod}")
        except Exception as e:
            print(f"会话错误: {e}")
        finally:
            if not self.is_audio_file_input:
                self.audio_device.cleanup()


def save_input_pcm_to_wav(pcm_data: bytes, filename: str) -> None:
    with wave.open(filename, 'wb') as wf:
        wf.setnchannels(config.input_audio_config["channels"])
        wf.setsampwidth(2)
        wf.setframerate(config.input_audio_config["sample_rate"])
        wf.writeframes(pcm_data)


def save_output_to_file(audio_data: bytes, filename: str) -> None:
    if not audio_data:
        print("No audio data to save.")
        return
    try:
        with open(filename, 'wb') as f:
            f.write(audio_data)
    except IOError as e:
        print(f"Failed to save pcm file: {e}")