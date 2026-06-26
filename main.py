"""
免唤醒词插件
允许机器人不需要唤醒词即可触发指令，支持动态开关。
插件加载时自动检测并修补 AstrBot 核心的 stage.py 文件，
确保 "*" 唤醒词逻辑在 AstrBot 更新后仍然生效。
"""

import asyncio
import os

from astrbot.api import logger
from astrbot.api.event import filter, AstrMessageEvent, MessageChain
from astrbot.api.star import Context, Star, register
from astrbot.core.config.astrbot_config import AstrBotConfig
from astrbot.core.platform.message_session import MessageSession
from astrbot.core.platform.message_type import MessageType

# 原始代码片段（AstrBot 更新后会恢复的样子）
_ORIGINAL_CODE = '''        # 检查 wake
        wake_prefixes = self.ctx.astrbot_config["wake_prefix"]
        messages = event.get_messages()
        is_wake = False
        for wake_prefix in wake_prefixes:
            if event.message_str.startswith(wake_prefix):
                if (
                    not event.is_private_chat()
                    and isinstance(messages[0], At)
                    and str(messages[0].qq) != str(event.get_self_id())
                    and str(messages[0].qq) != "all"
                ):
                    # 如果是群聊，且第一个消息段是 At 消息，但不是 At 机器人或 At 全体成员，则不唤醒
                    break
                is_wake = True
                event.is_at_or_wake_command = True
                event.is_wake = True
                event.message_str = event.message_str[len(wake_prefix) :].strip()
                break'''

# 补丁后的代码片段（包含 "*" 唤醒词支持）
_PATCHED_CODE = '''        # 检查是否配置了 "*" 唤醒词，如果是则直接视为唤醒 [no_wake_patched]
        wake_prefixes = self.ctx.astrbot_config["wake_prefix"]
        is_wake = False  # 初始化 is_wake 变量
        if "*" in wake_prefixes:
            is_wake = True
            event.is_wake = True
            event.is_at_or_wake_command = True
            # 继续执行后续的 handler filter 检查
        else:
            # 检查 wake
            messages = event.get_messages()
            is_wake = False
            for wake_prefix in wake_prefixes:
                if event.message_str.startswith(wake_prefix):
                    if (
                        not event.is_private_chat()
                        and isinstance(messages[0], At)
                        and str(messages[0].qq) != str(event.get_self_id())
                        and str(messages[0].qq) != "all"
                    ):
                        # 如果是群聊，且第一个消息段是 At 消息，但不是 At 机器人或 At 全体成员，则不唤醒
                        break
                    is_wake = True
                    event.is_at_or_wake_command = True
                    event.is_wake = True
                    event.message_str = event.message_str[len(wake_prefix) :].strip()
                    break'''

# 补丁标记，用于精确检测是否已修补（防止重复修补）
_PATCH_MARKER = "[no_wake_patched]"


class NoWakePlugin(Star):
    """免唤醒词插件，支持动态开关"""

    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        # 是否启用免唤醒功能
        self.enabled = getattr(config, "enabled", True)
        # 是否仅在私聊中启用
        self.private_only = getattr(config, "private_only", False)
        # 是否仅在群聊中启用
        self.group_only = getattr(config, "group_only", False)
        # 是否启用自动补丁（AstrBot 更新后自动修补 stage.py）
        self.auto_patch = getattr(config, "auto_patch", True)
        # 是否启用管理员通知
        self.notify_admin = getattr(config, "notify_admin", True)

        # 延迟通知机制：记录补丁结果，等待管理员交互时发送通知
        self._patch_notification: str | None = None
        self._need_notify: bool = False

        logger.info(
            f"免唤醒词插件已加载 - 启用: {self.enabled}, "
            f"仅私聊: {self.private_only}, 仅群聊: {self.group_only}, "
            f"自动补丁: {self.auto_patch}, 管理员通知: {self.notify_admin}"
        )

        # 插件加载时自动检测并修补 stage.py
        if self.auto_patch:
            self._apply_stage_patch()

        # 如果有补丁结果需要通知管理员，使用异步任务发送
        if self._need_notify and self.notify_admin and self._patch_notification:
            asyncio.create_task(self._send_admin_notification(self._patch_notification))

    @filter.command("免唤醒", alias={"nowake", "nowakeword"})
    async def toggle_nowake(self, event: AstrMessageEvent, action: str = "status"):
        """
        控制免唤醒词功能
        :param action: 操作类型，可选值：
            - status: 查看当前状态
            - on: 开启功能
            - off: 关闭功能
            - private: 仅私聊启用
            - group: 仅群聊启用
            - all: 所有场景启用
        """
        action = action.lower().strip()

        if action == "status":
            status_msg = self._get_status_message()
            yield event.plain_result(status_msg)
            return

        if action == "on":
            self.enabled = True
            self.config["enabled"] = True
            self._update_wake_prefix()
            yield event.plain_result("✅ 免唤醒词功能已开启")
            logger.info("免唤醒词功能已开启")
            return

        if action == "off":
            self.enabled = False
            self.config["enabled"] = False
            self._update_wake_prefix()
            yield event.plain_result("❌ 免唤醒词功能已关闭")
            logger.info("免唤醒词功能已关闭")
            return

        if action == "private":
            self.enabled = True
            self.private_only = True
            self.group_only = False
            self.config["enabled"] = True
            self.config["private_only"] = True
            self.config["group_only"] = False
            self._update_wake_prefix()
            yield event.plain_result("🔒 免唤醒词功能已开启，仅在私聊中生效")
            logger.info("免唤醒词功能已开启，仅在私聊中生效")
            return

        if action == "group":
            self.enabled = True
            self.private_only = False
            self.group_only = True
            self.config["enabled"] = True
            self.config["private_only"] = False
            self.config["group_only"] = True
            self._update_wake_prefix()
            yield event.plain_result("👥 免唤醒词功能已开启，仅在群聊中生效")
            logger.info("免唤醒词功能已开启，仅在群聊中生效")
            return

        if action == "all":
            self.enabled = True
            self.private_only = False
            self.group_only = False
            self.config["enabled"] = True
            self.config["private_only"] = False
            self.config["group_only"] = False
            self._update_wake_prefix()
            yield event.plain_result("🌐 免唤醒词功能已开启，在所有场景中生效")
            logger.info("免唤醒词功能已开启，在所有场景中生效")
            return

        # 未知操作
        yield event.plain_result(
            "❓ 未知操作，可用指令：\n"
            "• 免唤醒 status - 查看状态\n"
            "• 免唤醒 on - 开启功能\n"
            "• 免唤醒 off - 关闭功能\n"
            "• 免唤醒 private - 仅私聊启用\n"
            "• 免唤醒 group - 仅群聊启用\n"
            "• 免唤醒 all - 所有场景启用"
        )

    def _get_status_message(self) -> str:
        """获取当前状态信息"""
        status = "✅ 已开启" if self.enabled else "❌ 已关闭"

        if self.private_only:
            scope = "🔒 仅私聊"
        elif self.group_only:
            scope = "👥 仅群聊"
        else:
            scope = "🌐 所有场景"

        patch_status = self._get_patch_status()

        return (
            f"【免唤醒词插件状态】\n"
            f"功能状态：{status}\n"
            f"生效范围：{scope}\n"
            f"核心补丁：{patch_status}"
        )

    def _update_wake_prefix(self):
        """
        更新唤醒词配置
        通过修改 AstrBot 主配置的 wake_prefix 来实现免唤醒功能
        """
        try:
            # 获取 AstrBot 主配置
            astrbot_config = self.context.get_config()

            if self.enabled:
                # 开启免唤醒：添加 "*" 作为唤醒词
                wake_prefixes = astrbot_config.get("wake_prefix", [])
                if "*" not in wake_prefixes:
                    wake_prefixes.append("*")
                    astrbot_config["wake_prefix"] = wake_prefixes
                    astrbot_config.save_config()
                    logger.info(f"已添加 '*' 唤醒词，当前配置: {wake_prefixes}")
            else:
                # 关闭免唤醒：移除 "*" 唤醒词
                wake_prefixes = astrbot_config.get("wake_prefix", [])
                if "*" in wake_prefixes:
                    wake_prefixes.remove("*")
                    astrbot_config["wake_prefix"] = wake_prefixes
                    astrbot_config.save_config()
                    logger.info(f"已移除 '*' 唤醒词，当前配置: {wake_prefixes}")

        except Exception as e:
            logger.error(f"更新唤醒词配置失败: {e}")

    def _get_stage_file_path(self) -> str:
        """
        获取 AstrBot 核心 stage.py 文件的绝对路径
        通过查找 astrbot 目录来定位，支持不同的安装结构
        :return: stage.py 的绝对路径
        """
        # 从当前插件文件向上追溯，查找包含 astrbot 目录的根目录
        # 插件路径: */data/plugins/astrbot_plugin_no_wake/main.py
        current_dir = os.path.dirname(os.path.abspath(__file__))

        # 向上遍历目录，查找包含 astrbot/core/pipeline 目录的路径
        for _ in range(10):  # 最多向上查找10层
            # 检查当前目录下是否有 astrbot/core/pipeline/waking_check/stage.py
            stage_path = os.path.join(
                current_dir, "astrbot", "core", "pipeline", "waking_check", "stage.py"
            )
            if os.path.exists(stage_path):
                return stage_path

            # 检查当前目录是否就是 astrbot 目录
            if os.path.basename(current_dir) == "astrbot":
                parent_dir = os.path.dirname(current_dir)
                stage_path = os.path.join(
                    parent_dir, "astrbot", "core", "pipeline", "waking_check", "stage.py"
                )
                if os.path.exists(stage_path):
                    return stage_path

            # 向上一级目录
            parent_dir = os.path.dirname(current_dir)
            if parent_dir == current_dir:
                break  # 已经到达根目录
            current_dir = parent_dir

        # 如果找不到，返回默认路径（可能不存在）
        plugin_dir = os.path.dirname(os.path.abspath(__file__))
        astrbot_root = os.path.abspath(
            os.path.join(plugin_dir, "..", "..", "..")
        )
        return os.path.join(
            astrbot_root, "astrbot", "core", "pipeline", "waking_check", "stage.py"
        )

    def _is_stage_patched(self, content: str) -> bool:
        """
        检查 stage.py 是否已包含补丁（"*" 唤醒词逻辑）
        通过补丁标记 _PATCH_MARKER 进行精确检测，避免误判。
        :param content: stage.py 的文件内容
        :return: True 表示已修补，False 表示未修补
        """
        # 优先使用精确的补丁标记检测，防止重复修补
        if _PATCH_MARKER in content:
            return True
        # 兼容旧版补丁（没有标记的情况），通过特征代码判断
        return 'if "*" in wake_prefixes:' in content

    def _apply_stage_patch(self) -> bool:
        """
        检测并修补 stage.py 文件。
        如果文件已包含补丁则跳过，否则将原始代码替换为补丁代码。
        修补结果会记录到 _patch_notification，用于延迟通知管理员。
        :return: True 表示进行了修补，False 表示无需修补或修补失败
        """
        stage_path = self._get_stage_file_path()

        try:
            if not os.path.exists(stage_path):
                msg = f"stage.py 文件不存在: {stage_path}，跳过补丁"
                logger.warning(msg)
                self._patch_notification = f"⚠️ {msg}"
                self._need_notify = True
                return False

            # 读取文件内容
            with open(stage_path, "r", encoding="utf-8") as f:
                content = f.read()

            # 已包含补丁，无需操作
            if self._is_stage_patched(content):
                logger.info("stage.py 已包含补丁，无需修补")
                return False

            # 检查是否包含需要替换的原始代码
            if _ORIGINAL_CODE not in content:
                msg = (
                    "stage.py 中未找到原始代码片段，可能 AstrBot 版本已变更，"
                    "请手动检查或更新插件"
                )
                logger.warning(msg)
                self._patch_notification = f"⚠️ 补丁失败：{msg}"
                self._need_notify = True
                return False

            # 执行替换
            new_content = content.replace(_ORIGINAL_CODE, _PATCHED_CODE)

            # 写回文件
            with open(stage_path, "w", encoding="utf-8") as f:
                f.write(new_content)

            msg = f"已成功修补 stage.py: {stage_path}"
            logger.info(f"✅ {msg}")
            self._patch_notification = f"✅ 免唤醒词插件补丁通知\n{msg}"
            self._need_notify = True
            return True

        except Exception as e:
            msg = f"修补 stage.py 失败: {e}"
            logger.error(f"❌ {msg}")
            self._patch_notification = f"❌ 免唤醒词插件补丁通知\n{msg}"
            self._need_notify = True
            return False

    def _get_patch_status(self) -> str:
        """
        获取当前补丁状态描述
        :return: 补丁状态字符串
        """
        stage_path = self._get_stage_file_path()
        try:
            if not os.path.exists(stage_path):
                return "❓ 文件不存在"
            with open(stage_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            if self._is_stage_patched(content):
                return "✅ 已修补"
            return "⚠️ 未修补"
        except Exception:
            return "❓ 检测失败"

    async def _send_admin_notification(self, message: str) -> None:
        """
        主动发送通知给所有管理员（通过QQ私聊）。
        遍历所有平台，为每个管理员构造私聊session并发送消息。
        消息中会附带当前免唤醒功能的状态信息。
        :param message: 要发送的通知消息内容
        """
        try:
            # 获取管理员ID列表
            config = self.context.get_config()
            admin_ids = config.get("admins_id", [])
            if not admin_ids:
                logger.warning("未配置管理员ID，跳过发送通知")
                return

            # 获取所有平台实例
            platforms = self.context.platform_manager.platform_insts
            if not platforms:
                logger.warning("未找到可用平台，跳过发送通知")
                return

            # 构造完整消息，包含免唤醒状态
            status = "✅ 已开启" if self.enabled else "❌ 已关闭"
            if self.private_only:
                scope = "🔒 仅私聊"
            elif self.group_only:
                scope = "👥 仅群聊"
            else:
                scope = "🌐 所有场景"
            
            full_message = (
                f"{message}\n\n"
                f"--- 当前免唤醒状态 ---\n"
                f"功能状态：{status}\n"
                f"生效范围：{scope}"
            )

            # 遍历所有平台，尝试发送通知给管理员
            for platform in platforms:
                platform_id = platform.meta().id
                for admin_id in admin_ids:
                    try:
                        # 构造私聊session：platform_id:FriendMessage:admin_id
                        session = MessageSession(
                            platform_name=platform_id,
                            message_type=MessageType.FRIEND_MESSAGE,
                            session_id=str(admin_id)
                        )
                        # 构建消息链
                        message_chain = MessageChain().message(full_message)
                        # 发送消息
                        await self.context.send_message(session, message_chain)
                        logger.info(f"已向管理员 {admin_id} 发送补丁通知（平台: {platform_id}）")
                    except Exception as e:
                        logger.warning(f"向管理员 {admin_id} 发送通知失败（平台: {platform_id}）: {e}")

            # 清除通知标记，避免重复发送
            self._need_notify = False
            self._patch_notification = None

        except Exception as e:
            logger.error(f"发送管理员通知失败: {e}")

    def _is_admin(self, event: AstrMessageEvent) -> bool:
        """
        检查当前消息发送者是否为管理员
        :param event: 消息事件对象
        :return: True 表示是管理员，False 表示不是
        """
        try:
            config = self.context.get_config()
            admin_ids = config.get("admins_id", [])
            sender_id = str(event.get_sender_id())
            return sender_id in admin_ids
        except Exception:
            return False
