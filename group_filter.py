# encoding:utf-8

import json
import os

import plugins
from bridge.context import ContextType
from common.log import logger
from plugins import *
from channel.chat_channel import check_contain
from plugins.plugin_chat2db.api_groupx import ApiGroupx
from plugins.plugin_comm.remark_name_info import RemarkNameInfo
from plugins.plugin_comm.plugin_comm import EthZero, get_itchat_group, get_itchat_user, make_chat_sign_req


# 群白名单二次过滤,确保
@plugins.register(
    name="group_filter",
    desire_priority=999,
    hidden=False,
    desc="群白名单过滤",
    version="0.2.5",
    author="akun.yunqi",
    path=__file__,
)
class GroupFilter(Plugin):
    def __init__(self):
        super().__init__()
        self.config = super().load_config()
        if self.config:
            self.filter_config = self.config.get("group_filter")
        else:
            self.filter_config = []

        self.group_white_list = self.filter_config.get("group_name_white_list")
        self.handlers[Event.ON_HANDLE_CONTEXT] = self.on_handle_context
        self.groupx = ApiGroupx()
        self.agent = conf().get("bot_account") or "123112312"

        logger.info(f"======>[GroupFilter] inited, config={self.config}")

    def get_help_text(self, **kwargs):
        return "暂无帮助信息"

    def _post_group_msg(self, cmsg):
        wx_user_id = cmsg.actual_user_id
        wx_group_id = cmsg.other_user_id
        user = get_itchat_user(wx_user_id)
        group = get_itchat_group(wx_group_id)

        rm = RemarkNameInfo(user.RemarkName)
        account = rm.get_account()
        self.groupx.post_chat_record_group_not_at(account, {"agent": self.agent, "user": user, "group": group, "content": cmsg.content})

    def on_handle_context(self, e_context: EventContext):
        context = e_context["context"]
        if context.type not in [ContextType.TEXT]:
            return  # 转给系统及其它插件处理
        is_group = context.get("isgroup")
        if not is_group:
            return  # 转给系统及其它插件处理

        msg = context.get("msg")
        if msg.is_at:
            logger.info(f"--->群名称过滤:带at消息")
            return  # 转给系统及其他插件
        # 无 @ 也进行处理
        group_name = msg.from_user_nickname
        if group_name not in self.group_white_list:
            # logger.info(f"--->群名称过滤:群不在白名单中 {group_name}") #频率非常高
            e_context.action = EventAction.BREAK_PASS
            return  # 不响应,中止

        self._post_group_msg(msg)

        content = context.content
        match_contain = check_contain(content, self.filter_config.get("group_chat_keyword"))
        if not match_contain:
            logger.info(f"--->群名称过滤:文本不包含关键词,中止 {content}")
            e_context.action = EventAction.BREAK_PASS
            return  # 不响应,中止

        logger.info(f"--->群名称过滤后文本,继续: {content}")  # 转系统及其他插件处理
