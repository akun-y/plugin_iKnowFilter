# encoding:utf-8

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

        self.filter_user = FilterUser(self.config)
        self.filter_group = GroupFilter(self.config)

        self.handlers[Event.ON_HANDLE_CONTEXT] = self.on_handle_context
        self.handlers[Event.ON_SEND_REPLY] = self.on_send_reply


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
