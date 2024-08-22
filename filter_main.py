# encoding:utf-8

import time
from bridge.bridge import Bridge
from channel import channel_factory
import plugins
from common.log import logger
from plugins import *
from plugins.plugin_iKnowFilter.filter_group import GroupFilter
from plugins.plugin_iKnowFilter.filter_user import FilterUser


# 群白名单二次过滤,确保
@plugins.register(
    name="IKnowFilter",
    desire_priority=999,
    hidden=False,
    desc="群白名单过滤",
    version="0.2.6",
    author="akun.yunqi",
)
class IKnowFilter(Plugin):
    def __init__(self):
        super().__init__()
        self.config = super().load_config()
        self.filter_config = self.config.get("group_filter")

        self.filter_user = FilterUser(self.config)
        self.filter_group = GroupFilter(self.config)

        self.handlers[Event.ON_HANDLE_CONTEXT] = self.on_handle_context
        self.handlers[Event.ON_SEND_REPLY] = self.on_send_reply

        self.refresh_global_config()

        logger.info(f"======>[IKnowFilter] inited")

    def get_help_text(self, **kwargs):
        return "暂无帮助信息"

    def on_send_reply(self, e_context: EventContext):
        ctx = e_context["context"]
        is_group = ctx.get("isgroup", False)
        if is_group:
            self.filter_group.before_send_reply(e_context)
            return
        self.filter_user.before_send_reply(e_context)

    def on_handle_context(self, e_context: EventContext):
        context = e_context["context"]
        is_group = context.get("isgroup")
        if is_group:
            self.filter_group.before_handle_context(e_context)
            return
        self.filter_user.before_handle_context(e_context)

    # 刷新全局配置config.json
    def refresh_global_config(self):
        time.sleep(8)

        # 系统默认情况关闭所有群应答,只有启动filter才能打开应答,否则乱回答.
        logger_group_white_list = self.filter_config.get("logger_group_white_list")
        conf()["group_name_white_list"].extend(logger_group_white_list)
        logger.info(f"======>接收消息群白名单,加入:{len(logger_group_white_list)}")
        # 群消息处理前缀,加入"",开启所有消息应答,
        conf()["group_chat_prefix"].append("")
        logger.info(f"======>群消息处理前缀,加入空格:{(conf()['group_chat_prefix'])}")

        bot = Bridge().get_bot("chat")
        bot.sessions.clear_all_session()
        Bridge().reset_bot()

        channel_name = conf().get("channel_type", "wx")
        channel = channel_factory.create_channel(channel_name)
        if channel.reload_conf:
            channel.reload_conf()

        # channel.startup()
