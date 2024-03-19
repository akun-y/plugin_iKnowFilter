# encoding:utf-8

import json
import os
from sys import prefix

import plugins
from bridge.context import ContextType
from common.log import logger
from plugins import *
from channel.chat_channel import check_contain
from plugins.plugin_chat2db.api_groupx import ApiGroupx
from plugins.plugin_comm.remark_name_info import RemarkNameInfo
from plugins.plugin_comm.plugin_comm import (
    EthZero,
    get_itchat_group,
    get_itchat_user,
    is_valid_string,
    make_chat_sign_req,
)


class FilterUser(object):
    def __init__(self, config):
        self.config = config

    def filter_user_msg(self, e_context: EventContext):
        context = e_context["context"]
        if context.type not in [ContextType.TEXT]:
            return  # 转给系统及其它插件处理
        # 2- 是 @ 我，直接转给系统及其它插件处理
        msg = context.get("msg")

        # 3- 是带有约定前缀的，转给系统及其它插件处理
        prefix_array = self.config.get("group_forward_prefix")
        if any(msg.content.startswith(item) for item in prefix_array):
            return  # 转给系统及其他插件

        # 4- 是机器人发出的消息， 终止处理
        if msg.my_msg:
            logger.info("--->group filter:我自己发出的消息")
            e_context.action = EventAction.BREAK_PASS  # 不响应
            return

        # 7- 不匹配关键字，中止处理
        content = context.content
        match_contain = check_contain(
            content, self.config.get("group_chat_keyword")
        )
        if not match_contain:
            logger.info(
                f"--->grooup filter 无关键字,中止：{content}  {msg.actual_user_nickname}"
            )
            e_context.action = EventAction.BREAK_PASS
            return  # 不响应,中止

        # 8- 包含关键字，转系统及其他插件处理
        logger.info(
            f"--->grooup filter 包含关键字,继续:{content}  {msg.actual_user_nickname}"
        )  # 转系统及其他插件处理
    def before_send_reply(self, e_context: EventContext):
        pass
    def before_handle_context(self, e_context: EventContext):
        pass