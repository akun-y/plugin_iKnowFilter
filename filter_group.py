# encoding:utf-8

"""
filter_group.py - 群聊消息过滤器

功能:
- 根据配置的白名单和关键词过滤群聊消息
- 记录群聊消息到数据库
- 处理群聊消息的计费

修改历史:
- 2025-04-30: 添加文件注释说明
- 2025-04-30: 优化群聊消息过滤逻辑
- 2025-04-30: 完善计费功能

作者: Trae AI
"""

import json
import os
from sys import prefix

from bridge.bridge import Bridge
from bridge.reply import ReplyType

# from lib import itchat
from common.singleton import singleton
import plugins
from bridge.context import ContextType
from common.log import logger
from plugins import *
from channel.chat_channel import check_contain, check_prefix
from plugins.plugin_comm.api.api_groupx import ApiGroupx

# from plugins.plugin_comm.remark_name_info import RemarkNameInfo
from plugins.plugin_comm.groupx.groupx_users_man import GroupxUserMan
from plugins.plugin_comm.plugin_comm import (
    EthZero,
    find_actual_user_id_by_ctx,
    is_eth_address,
    is_valid_string,
    make_chat_sign_req,
    make_wxgroup_by_ctx,
    make_wxuser_by_ctx,
    selectKeysForDict,
    send_reg_msg,
    send_text_with_url,
)

from plugins.plugin_iKnowFilter.filter_base import FilterBase

class FilterGroup(FilterBase):
    def __init__(self, config, groupx, contacts_groupx:GroupxUserMan):
        super().__init__(config, groupx, contacts_groupx)
        if self.config:
            self.filter_config = self.config.get("group_filter")
        else:
            self.filter_config = {"group_name_white_list": []}

        self.group_white_list = self.filter_config.get("group_name_white_list", [])
        self.group_chat_keyword_ignore = self.filter_config.get(
            "group_chat_keyword_ignore", []
        )
        # 约定前缀的，转给系统及其它插件处理
        self.prefix_array = self.filter_config.get("group_forward_prefix") or []

    def before_handle_context(self, e_context: EventContext):
        context = e_context["context"]

        content = context.content
        msg = context.get("msg")
        group_name = msg.other_user_nickname or msg.from_user_nickname
        group_id = msg.other_user_id or msg.from_user_id
        # 1- 保存消息到数据库
        ret = self._post_group_msg(msg)

        if ret :
            results =  ret.get("results",None)
            if results and len(results)>0:
                group_object_id = results[0].get('groupOID','')
                wx_group = make_wxgroup_by_ctx(context)
                if(group_object_id and group_object_id != wx_group.get('objectId')):
                    self._set_contact_info({"wxid": group_id,"name": group_name,"objectId": group_object_id,"account":'',"alias":''})       
                
                user_object_id = results[0].get('userOID','')
                wx_user = make_wxuser_by_ctx(context)
                if(user_object_id and user_object_id != wx_user.get('objectId')):                   
                    self._set_contact_info({"wxid": wx_user.get("wxid"),"name": wx_user.get("name"),
                        "objectId": user_object_id,"account":wx_user.get("account"),"alias":wx_user.get("alias")})   

        logger.info(f"======>保存消息到groupx:{group_name}\n服务器返回:\n{ret}")

        # 2- 是带有约定前缀的，转给系统及其它插件处理
        if any(msg.content.startswith(item) for item in self.prefix_array):
            logger.warn(f"=====>是带有约定前缀的，转给系统及其它插件处理 {msg.content}")
            return  # 转给系统及其他插件

        # 3- 是机器人发出的消息， 终止处理
        if msg.my_msg :
            logger.warning("--->group filter:我自己发出的消息")
            e_context.action = EventAction.BREAK_PASS  # 不响应
            return

        
        # 4- 无关键字也继续派发给其他插件处理
        if (
            group_name in self.group_chat_keyword_ignore
            or "ALL_GROUP" in self.group_white_list
        ):
            logger.info(
                f"[iKnowFilter] --->group filter:群在'关键字'忽略名单中,继续处理 {group_name}"
            )  # 频率非常高
            return  # 转给系统及其他插件
        # 6- 群名不在白名单中，中止处理
        if (
            group_name not in self.group_white_list
            and "ALL_GROUP" not in self.group_white_list
        ):
            e_context.action = EventAction.BREAK_PASS
            return  # 不响应,中止

        # logger.info(f"[iKnowFilter]群在白名单中,继续处理 {group_name}")  # 频率非常高

        # 非文字内容,只记录不处理
        if context.type not in [ContextType.TEXT]:  # 转给其他插件处理
            return
        #  是 @ 我，记录,转给系统及其它插件处理
        if msg.is_at:
            logger.info("===>@我的")
            return  # 转给系统及其他插件

        # 7- 不匹配关键字，中止处理
        content = context.content
        match_contain = check_contain(
            content, self.filter_config.get("group_chat_keyword")
        )
        if not match_contain:
            logger.info(
                f'无关键字:{content}-"{group_name}"="{msg.actual_user_nickname}"'
            )
            e_context.action = EventAction.BREAK_PASS
            return  # 不响应,中止

        # 8- 包含关键字，转系统及其他插件处理
        # 注意:其他插件如果不处理,会被大模型处理
        logger.info(
            f'========>包含关键字,继续:{content}-"{group_name}"="{msg.actual_user_nickname}"'
        )  # 转系统及其他插件处理

    def before_send_reply(self, e_context: EventContext):
        if e_context["reply"].type not in [ReplyType.TEXT, ReplyType.IMAGE]:
            logger.warn("======>应答:非文字内容")
            return

        ctx = e_context["context"]
        reply = e_context["reply"]
        cmsg = e_context["context"]["msg"]

        if reply.type == ReplyType.IMAGE:
            replyMsg = "图片"
        else:
            replyMsg = reply.content
        completion_tokens, total_tokens = self._calc_tokens(ctx, replyMsg, reply)

        # 用户
        wx_user_id = cmsg.actual_user_id
        wx_user_nickname = cmsg.actual_user_nickname
        user = self._get_user_info(wx_user_id, wx_user_nickname)

        # 群
        wx_group_id = cmsg.other_user_id
        wx_group_nickname = cmsg.other_user_nickname
        group = self._get_contact_info(wx_group_id, wx_group_nickname)

        logger.warn(f"======>应答:文字内容,计费 {wx_user_nickname} {wx_group_nickname}")
        account = ""
        ret = self._consume_tokens(account, user, group, total_tokens, completion_tokens, replyMsg,cmsg)
        if ret:
            # 写入服务器返回的account到user remarkname中
            if is_eth_address(ret["account"]) and account != ret["account"]:
                pass
                
                # rm.set_account(ret["account"])
                # itchat.set_alias(user.UserName, rm.get_remark_name())
                # user.update()
                # itchat.dump_login_status()


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
            logger.warn(f"======>[IKnowFilter] consumeTokens successl {ret}")
        else:
            logger.warn(f"======>[IKnowFilter] consumeTokens fail {ret}")
            # 未注册用户暂时不禁用。
            # send_text_reg(e_context, f"消费积分失败，请点击链接注册。")
            # e_context.action = EventAction.BREAK_PASS
            return

    def _post_group_msg(self, cmsg):
        try:
            wx_user_id = cmsg.actual_user_id or cmsg.from_user_id
            wx_user_nickname = cmsg.actual_user_nickname or cmsg.from_user_nickname

            wx_group_id = cmsg.other_user_id
            wx_group_nickname = cmsg.other_user_nickname
            user = {
                "UserName": wx_user_id,
                "NickName": wx_user_nickname,
                "RemarkName": "",
            }  # get_itchat_user(wx_user_id)
            group = {
                "UserName": wx_group_id,
                "NickName": wx_group_nickname,
                "RemarkName": "",
            }  # get_itchat_group(wx_group_id)

            # rm = RemarkNameInfo(user.RemarkName)
            account = ""  # rm.get_account()
            return self.groupx.post_chat_record_group_not_at(
                account,
                {
                    "agent": self.agent,
                    "user": user,
                    "group": group,
                    "content": cmsg.content,
                    "type": cmsg.ctype.name if cmsg.ctype else "",
                    "is_at": cmsg.is_at,
                    "is_group": cmsg.is_group,
                    "time": cmsg.create_time,
                    "msgid": cmsg.msg_id,
                    "thumb": getattr(cmsg._rawmsg, 'thumb', ""),
                    "extra": getattr(cmsg._rawmsg, 'extra', ""),
                    "source": "wcferry" if getattr(cmsg, 'scf', False) else "",
                    "system_name": getattr(self, 'system_name', ""),
                },
            )
        except Exception as e:
            logger.error(f"======>[IKnowFilter] _post_group_msg fail {e}")

