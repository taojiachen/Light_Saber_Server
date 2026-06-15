import aiomysql
from typing import Dict, Any, Optional, List

class AsyncMySQLManager:
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.pool = None

    async def ensure_database(self):
        conn = await aiomysql.connect(
            host=self.config["host"],
            port=self.config["port"],
            user=self.config["user"],
            password=self.config["password"],
            charset=self.config["charset"],
            autocommit=True
        )
        try:
            async with conn.cursor() as cur:
                await cur.execute(
                    f"CREATE DATABASE IF NOT EXISTS `{self.config['db']}` "
                    f"CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
                )
            print(f"✅ 数据库 `{self.config['db']}` 已确保存在")
        finally:
            conn.close()

    async def create_pool(self):
        self.pool = await aiomysql.create_pool(
            host=self.config["host"],
            port=self.config["port"],
            user=self.config["user"],
            password=self.config["password"],
            db=self.config["db"],
            minsize=self.config["minsize"],
            maxsize=self.config["maxsize"],
            charset=self.config["charset"],
            autocommit=True
        )
        print("✅ MySQL 连接池已创建")

    async def close_pool(self):
        if self.pool:
            self.pool.close()
            await self.pool.wait_closed()
            print("🔴 MySQL 连接池已关闭")

    async def execute(self, sql: str, args: tuple = None) -> int:
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                affected = await cur.execute(sql, args)
                return affected

    async def fetchone(self, sql: str, args: tuple = None) -> Optional[Dict[str, Any]]:
        async with self.pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(sql, args)
                return await cur.fetchone()

    async def fetchall(self, sql: str, args: tuple = None) -> List[Dict[str, Any]]:
        async with self.pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(sql, args)
                return await cur.fetchall()

    # ==================== 建表 ====================
    async def init_tables(self):
        statements = [
            """CREATE TABLE IF NOT EXISTS `groups` (
                id INT AUTO_INCREMENT PRIMARY KEY,
                name VARCHAR(100) COMMENT '组名称',
                milestone_count INT NOT NULL DEFAULT 0 COMMENT '里程碑总数',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;""",

            """CREATE TABLE IF NOT EXISTS devices (
                id INT AUTO_INCREMENT PRIMARY KEY,
                mac_address VARCHAR(17) NOT NULL UNIQUE COMMENT 'MAC地址',
                group_id INT NOT NULL,
                persona_description TEXT COMMENT '人物画像',
                preset_photo_url VARCHAR(500) COMMENT '预设照片URL',
                ai_generated_photo_url VARCHAR(500) COMMENT 'AI生成照片URL',
                last_analysis_count INT DEFAULT 0 COMMENT '上次分析时的消息总数',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                FOREIGN KEY (group_id) REFERENCES `groups`(id) ON DELETE CASCADE,
                INDEX idx_group (group_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;""",

            """CREATE TABLE IF NOT EXISTS `milestones` (
                id INT AUTO_INCREMENT PRIMARY KEY,
                device_id INT NOT NULL COMMENT '关联设备',
                milestone_number INT NOT NULL COMMENT '里程碑序号',
                assessment_goal TEXT COMMENT '考核目标',
                assessment_evaluation TEXT COMMENT '考核评价',
                child_answer_text TEXT COMMENT '儿童回答文本',          -- 新增字段
                task_completion_image_url VARCHAR(500) COMMENT '任务完成验收图片URL',
                assessment_audio_url VARCHAR(500) COMMENT '考核指标音频URL',
                child_learning_ai_drawing_url VARCHAR(500) COMMENT '儿童学习成果AI绘图URL',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                FOREIGN KEY (device_id) REFERENCES devices(id) ON DELETE CASCADE,
                UNIQUE KEY unique_device_milestone (device_id, milestone_number)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;""",

            """CREATE TABLE IF NOT EXISTS conversations (
                id INT AUTO_INCREMENT PRIMARY KEY,
                device_id INT NOT NULL,
                role ENUM('user','AI','system') NOT NULL COMMENT '对话角色',
                content TEXT NOT NULL COMMENT '对话文本',
                current_milestone INT NOT NULL DEFAULT 1 COMMENT '对话时的里程碑数',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (device_id) REFERENCES devices(id) ON DELETE CASCADE,
                INDEX idx_device_time (device_id, created_at)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;"""
        ]
        for stmt in statements:
            await self.execute(stmt)
        print("✅ 数据库表初始化完成")

    # ==================== 组操作 ====================
    async def create_group(self, name: str = None, milestone_count: int = 0) -> int:
        async with self.pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(
                    "INSERT INTO `groups` (name, milestone_count) VALUES (%s, %s)",
                    (name or '', milestone_count)
                )
                await conn.commit()
                return cur.lastrowid

    async def get_group_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        return await self.fetchone("SELECT * FROM `groups` WHERE name = %s", (name,))

    async def get_default_group_id(self) -> int:
        row = await self.fetchone("SELECT id FROM `groups` WHERE name = %s", ('三年一班',))
        if not row:
            group_id = await self.create_group('三年一班', 3)
            print(f"✅ 已创建默认分组 '三年一班' (id={group_id})")
            return group_id
        return row['id']

    # ==================== 设备操作 ====================
    async def add_device(self, mac: str, group_id: int) -> int:
        existing = await self.get_device_by_mac(mac)
        if existing:
            return existing['id']
        async with self.pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(
                    "INSERT INTO devices (mac_address, group_id) VALUES (%s, %s)",
                    (mac, group_id)
                )
                await conn.commit()
                return cur.lastrowid

    async def get_device_by_mac(self, mac: str) -> Optional[Dict[str, Any]]:
        return await self.fetchone("SELECT * FROM devices WHERE mac_address = %s", (mac,))

    async def upsert_device(self, mac: str, name: str = None) -> int:
        device = await self.get_device_by_mac(mac)
        if device:
            return device['id']
        group_id = await self.get_default_group_id()
        try:
            device_id = await self.add_device(mac, group_id)
            print(f"✅ 设备 {mac} 已添加到数据库，device_id={device_id}")
            return device_id
        except Exception as e:
            print(f"❌ 添加设备失败: {e}")
            raise

    # ==================== 对话操作 ====================
    async def add_message(self, mac: str, role: str, content: str, current_milestone: int = 1):
        if role not in ('user', 'AI', 'system'):
            raise ValueError("角色必须为 user / AI / system")
        device = await self.get_device_by_mac(mac)
        if not device:
            print(f"⚠️ 设备 {mac} 不存在，尝试自动创建")
            await self.upsert_device(mac)
            device = await self.get_device_by_mac(mac)
            if not device:
                raise ValueError(f"设备 {mac} 创建失败")
        await self.execute(
            "INSERT INTO conversations (device_id, role, content, current_milestone) VALUES (%s, %s, %s, %s)",
            (device['id'], role, content, current_milestone)
        )

    async def get_recent_messages(self, mac: str, limit: int = 100) -> List[Dict[str, Any]]:
        device = await self.get_device_by_mac(mac)
        if not device:
            return []
        rows = await self.fetchall(
            """
            SELECT role, content, current_milestone, created_at
            FROM conversations
            WHERE device_id = %s
            ORDER BY created_at ASC
            LIMIT %s
            """,
            (device['id'], limit)
        )
        return rows

    async def get_total_message_count(self, mac: str) -> int:
        device = await self.get_device_by_mac(mac)
        if not device:
            return 0
        result = await self.fetchone(
            "SELECT COUNT(*) as cnt FROM conversations WHERE device_id = %s",
            (device['id'],)
        )
        return result['cnt'] if result else 0

    async def get_last_analysis_count(self, mac: str) -> int:
        device = await self.get_device_by_mac(mac)
        if not device:
            return 0
        return device.get('last_analysis_count', 0)

    async def set_last_analysis_count(self, mac: str, count: int):
        device = await self.get_device_by_mac(mac)
        if not device:
            return
        await self.execute(
            "UPDATE devices SET last_analysis_count = %s WHERE id = %s",
            (count, device['id'])
        )

    # ==================== 任务统计 ====================
    async def get_task_statistics(self, mac: str) -> Dict[str, Any]:
        # 临时默认值
        return {
            "avg_health": 100,
            "avg_satiety": 100,
            "avg_cleanliness": 100,
            "health_on_time": 100,
            "satiety_on_time": 100,
            "cleanliness_on_time": 100,
            "record_count": 0
        }

    # ==================== 人物画像与照片 ====================
    async def update_persona(self, mac: str, persona: str):
        device = await self.get_device_by_mac(mac)
        if not device:
            return
        await self.execute(
            "UPDATE devices SET persona_description = %s WHERE id = %s",
            (persona, device['id'])
        )

    async def update_preset_photo(self, mac: str, url: str):
        device = await self.get_device_by_mac(mac)
        if not device:
            return
        await self.execute(
            "UPDATE devices SET preset_photo_url = %s WHERE id = %s",
            (url, device['id'])
        )

    async def update_ai_photo(self, mac: str, url: str):
        device = await self.get_device_by_mac(mac)
        if not device:
            return
        await self.execute(
            "UPDATE devices SET ai_generated_photo_url = %s WHERE id = %s",
            (url, device['id'])
        )

    # ==================== 兼容旧接口 ====================
    async def add_conversation_message(self, mac: str, role: str, content: str, current_milestone: int = None):
        if current_milestone is None:
            device = await self.get_device_by_mac(mac)
            if device:
                group_info = await self.fetchone("SELECT * FROM `groups` WHERE id = %s", (device['group_id'],))
                current_milestone = group_info.get('milestone_count', 1) if group_info else 1
            else:
                current_milestone = 1
        await self.add_message(mac, role, content, current_milestone)

    async def get_device_conversations(self, mac: str, limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
        return await self.get_recent_messages(mac, limit)

    async def get_recent_messages_by_device(self, mac: str, limit: int = 100) -> List[Dict[str, Any]]:
        return await self.get_recent_messages(mac, limit)

    async def get_latest_summary_by_mac(self, mac: str) -> Optional[str]:
        return None

    async def update_conversation_summary(self, conv_id: int, summary: str):
        pass