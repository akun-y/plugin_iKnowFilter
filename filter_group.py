# encoding:utf-8

import json
import os
from sys import prefix

from bridge.bridge import Bridge
from bridge.reply import ReplyType
from lib import itchat
import plugins
from bridge.context import ContextType
from common.log import logger
from plugins import *
from channel.chat_channel import check_contain, check_prefix
from plugins.plugin_chat2db.api_groupx import ApiGroupx
from plugins.plugin_comm.remark_name_info import RemarkNameInfo
from plugins.plugin_comm.plugin_comm import (
    EthZero,
    find_user_id_by_ctx,
    get_itchat_group,
    get_itchat_user,
    is_eth_address,
    is_valid_string,
    make_chat_sign_req,
    selectKeysForDict,
    send_info,
    send_reg_msg,
    send_text_with_url,
)


class GroupFilter(object):
    def __init__(self, config):
        super().__init__()
        self.config = config
        if self.config:
            self.filter_config = self.config.get("group_filter")
        else:
            self.filter_config = []

        self.group_white_list = self.filter_config.get("group_name_white_list")

        self.groupx = ApiGroupx()
        self.agent = conf().get("bot_account") or "123112312"
        self.agent_name = conf().get("bot_name")
        self.reg_url = conf().get("iknow_reg_url")
        self.recharge_url = conf().get("iknow_recharge_url")
        self.oper_dict = {
            "create_img": "生成图片",
            "summary_file": "生成文件摘要",
            "summary_link": "生成链接文字摘要",
        }

    def before_handle_context(self, e_context: EventContext):
        context = e_context["context"]

        if context.type not in [ContextType.TEXT]:
            return  # 转给系统及其它插件处理

        content = context.content
        # 2- 是 @ 我，直接转给系统及其它插件处理
        msg = context.get("msg")
        if msg.is_at:
            logger.info("--->group filter:@我的")
            return  # 转给系统及其他插件

        # 3- 是带有约定前缀的，转给系统及其它插件处理
        prefix_array = ["￥", "$", "aa#", "#"] or self.filter_config.get(
            "group_forward_prefix"
        )
        if any(msg.content.startswith(item) for item in prefix_array):
            return  # 转给系统及其他插件

        # 4- 是机器人发出的消息， 终止处理
        if msg.my_msg:
            logger.info("--->group filter:我自己发出的消息")
            e_context.action = EventAction.BREAK_PASS  # 不响应
            return
        # 5- 群名不在白名单中，中止处理
        group_name = msg.from_user_nickname
        if group_name not in self.group_white_list:
            e_context.action = EventAction.BREAK_PASS
            return  # 不响应,中止

        logger.info(
            f"[iKnowFilter] --->group filter:群在白名单中,继续处理 {group_name}"
        )  # 频率非常高

        # 6- 保存消息到数据库
        self._post_group_msg(msg)

        # 7- 不匹配关键字，中止处理
        content = context.content
        match_contain = check_contain(
            content, self.filter_config.get("group_chat_keyword")
        )
        if not match_contain:
            logger.info(
                f"--->grooup filter 无关键字,中止：{content}  {group_name} {msg.actual_user_nickname}"
            )
            e_context.action = EventAction.BREAK_PASS
            return  # 不响应,中止

        # 8- 包含关键字，转系统及其他插件处理
        logger.info(
            f"--->grooup filter 包含关键字,继续:{content} {group_name} {msg.actual_user_nickname}"
        )  # 转系统及其他插件处理

    def before_send_reply(self, e_context: EventContext):
        if e_context["reply"].type not in [ReplyType.TEXT, ReplyType.IMAGE]:
            return

        ctx = e_context["context"]
        reply = e_context["reply"]
        cmsg = e_context["context"]["msg"]

        replyMsg = reply.content
        bot = Bridge().get_bot("chat")
        all_sessions = bot.sessions
        session_id = ctx.get("session_id")
        user_session = all_sessions.build_session(session_id)

        if hasattr(bot, "calc_tokens"):
            completion_tokens, total_tokens = bot.calc_tokens(
                user_session.messages, replyMsg
            )
        else:
            completion_tokens = len(cmsg.content)
            total_tokens = len(replyMsg) + completion_tokens

        wx_user_id = cmsg.actual_user_id
        wx_user_nickname = cmsg.actual_user_nickname
        wx_group_id = cmsg.other_user_id
        user = get_itchat_user(wx_user_id,wx_user_nickname)
        group = get_itchat_group(wx_group_id)

        rm = RemarkNameInfo(user.RemarkName)
        account = rm.get_account()
        if not is_valid_string(user.NickName):
            user["NickName"] = wx_user_nickname
        if not is_eth_address(account):
            account = EthZero
        ret = self.groupx.consumeTokens(
            account,
            {
                "type": "text",
                "agent": self.agent,
                "user": selectKeysForDict(
                    user,
                    "NickName",
                    "UserName",
                    "RemarkName",
                    "Sex",
                    "Province",
                    "City",
                ),
                "group": selectKeysForDict(
                    group, "NickName", "UserName", "RemarkName", "DisplayName"
                ),
                "total_tokens": total_tokens,
                "completion_tokens": completion_tokens,
            },
        )
        if ret:
            # 写入服务器返回的account到user remarkname中
            if is_eth_address(ret["account"]) and account != ret["account"]:
                rm.set_account(ret["account"])
                itchat.set_alias(user.UserName, rm.get_remark_name())
                user.update()
                itchat.dump_login_status()

            balance = ret["balanceAITokens"]
            if ret["success"] is False:
                logger.warn(f"======>[IKnowFilter] consumeTokens fail {ret}")
                # itchat.send_msg(msg, toUserName=to_user_id)
                #    send_text_with_url(
                #        e_context,
                #        f"积分不足，为不影响您正常使用，请及时充值。\n(余额: {balance})",
                #        self.recharge_url,
                #    )

                return
            logger.info(f"======>[IKnowFilter] consumeTokens success", ret)
        else:
            logger.warn(f"======>[IKnowFilter] consumeTokens fail", ret)
            # 未注册用户暂时不禁用。
            # send_text_reg(e_context, f"消费积分失败，请点击链接注册。")
            # e_context.action = EventAction.BREAK_PASS
            return

    def _post_group_msg(self, cmsg):
        wx_user_id = cmsg.actual_user_id
        wx_user_nickname = cmsg.actual_user_nickname
        wx_group_id = cmsg.other_user_id
        user = get_itchat_user(wx_user_id)
        group = get_itchat_group(wx_group_id)

        rm = RemarkNameInfo(user.RemarkName)
        account = rm.get_account()
        if not is_valid_string(user.NickName):
            user["NickName"] = wx_user_nickname
        self.groupx.post_chat_record_group_not_at(
            account,
            {
                "agent": self.agent,
                "user": user,
                "group": group,
                "content": cmsg.content,
            },
        )
