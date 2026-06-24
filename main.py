"""
免唤醒词插件
允许机器人不需要唤醒词即可触发指令，支持动态开关
"""

from astrbot.api import logger
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.core.config.astrbot_config import AstrBotConfig


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

        logger.info(
            f"免唤醒词插件已加载 - 启用: {self.enabled}, "
            f"仅私聊: {self.private_only}, 仅群聊: {self.group_only}"
        )

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

        return f"【免唤醒词插件状态】\n功能状态：{status}\n生效范围：{scope}"

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
