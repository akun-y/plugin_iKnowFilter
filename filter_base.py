# encoding:utf-8
"""
filter_base.py: iKnow过滤器基础类

该模块实现了iKnow过滤器的基础功能类，用于处理微信消息的过滤、用户信息获取和token计算等核心功能。

主要功能：
1. 计算消息token数量
2. 获取用户和群组信息
3. 处理token消耗统计
4. 消息来源识别

类:
    FilterBase: 过滤器基础类，提供了token计算、用户信息获取等基础方法

依赖:
    - bridge.bridge: 用于获取bot实例
    - bridge.reply: 用于处理回复类型
    - bridge.context: 用于处理上下文类型
    - common.log: 日志记录
    - plugins.plugin_comm.plugin_comm: 通用工具函数

修改历史:
    - 2025-04-30: 添加详细文档注释
    - 2024-xx-xx: 初始版本

作者: [项目维护者]
版权: Copyright (c) 2024-2025
"""

from bridge.bridge import Bridge
from bridge.reply import ReplyType
from bridge.context import ContextType
from channel.contact_info import ContactInfo, make_contact_info
from common.log import logger
from config import conf, load_config
from plugins.plugin_comm.groupx.groupx_users_man import GroupxUserMan
from plugins.plugin_comm.groupx.groupx_users_man import ContactFromSrv
from plugins.plugin_comm.plugin_comm import (
    EthZero,
    is_eth_address,
    is_valid_string,
    selectKeysForDict,
)

class FilterBase(object):
    def __init__(self, config, groupx, contacts_groupx:GroupxUserMan):
        self.config = config
        self.groupx = groupx
        self.contacts_groupx = contacts_groupx
        self.agent = conf().get("bot_account") or "123112312"
        self.agent_name = conf().get("bot_name")
        self.system_name = conf().get("system_name")
        self.reg_url = conf().get("iknow_reg_url")
        self.recharge_url = conf().get("iknow_recharge_url")
        self.oper_dict = {
            "create_img": "生成图片",
            "summary_file": "生成文件摘要",
            "summary_link": "生成链接文字摘要",
        }

    def _calc_tokens(self, cmsg, replyMsg, reply):
        bot = Bridge().get_bot("chat")
        all_sessions = bot.sessions
        session_id = cmsg.get("session_id")
        user_session = all_sessions.build_session(session_id)

        if hasattr(bot, "calc_tokens"):
            completion_tokens, total_tokens = bot.calc_tokens(
                user_session.messages, replyMsg
            )
        else:
            completion_tokens = len(cmsg.content)
            if isinstance(replyMsg, str):
                reply_tokens = len(replyMsg)
            else:
                if reply.type == ReplyType.IMAGE:
                    reply_tokens = 1000
                else:
                    reply_tokens = 0
                logger.warning(f"非文本类型的回复消息: {type(replyMsg)}")
            total_tokens = reply_tokens + completion_tokens
        return completion_tokens, total_tokens

    def _get_user_info(self, wx_user_id, wx_user_nickname)->ContactFromSrv:
        contact = self.contacts_groupx.get_contact(wx_user_id)
        user_object_id = contact.get("objectId", "")
        wx_user_alias = contact.get("alias", "")
        wx_user_account = contact.get("account", "")
        
        user = {
            "wxid": wx_user_id,
            "UserName": wx_user_id,
            "NickName": wx_user_nickname,
            "objectId": user_object_id,
            "alias": wx_user_alias,
            "account": wx_user_account,
        }
        return ContactFromSrv(**user)
         

    def _set_contact_info(self, contact:ContactFromSrv):
        if not contact.get("wxid", None):
            logger.error("设置联系人信息失败: wxid 不能为空")
            return 
        if not contact.get("objectId", None):
            logger.error("设置联系人信息失败: objectId 不能为空")
            return
        self.contacts_groupx.set_contact(contact)
        return

    def _get_contact_info(self, wx_group_id, wx_group_nickname):
        contact = self.contacts_groupx.get_contact(wx_group_id)
        group_object_id = contact.get("objectId", "")
        wx_group_alias = contact.get("alias", "")

        group = {
            "wxid": wx_group_id,
            "UserName": wx_group_id,
            "NickName": wx_group_nickname,
            "RemarkName": "",
            "objectId": group_object_id,
            "alias": wx_group_alias,
        }
        return group

    def _consume_tokens(self, account, user, group, total_tokens, completion_tokens, replyMsg,cmsg):
        if not is_valid_string(user.get("NickName", None)):
            user["NickName"] = user.get("wxid", "")
        if not is_eth_address(account):
            account = EthZero

        payload = {
            "type": "text",
            "agent": self.agent,
            "user": selectKeysForDict(
                user,
                "wxid",
                "NickName",
                "UserName",
                "RemarkName",
                "Sex",
                "Province",
                "City",
                "objectId",
                "alias",
                "account",
            ),
            "total_tokens": total_tokens,
            "completion_tokens": completion_tokens,
            "reply_text": replyMsg,
            "source": self.get_source(cmsg),
        }

        if group:
            payload["group"] = selectKeysForDict(
                group,
                "wxid",
                "NickName",
                "UserName",
                "RemarkName",
                "DisplayName",
                "objectId",
                "alias",
            )

        ret = self.groupx.consumeTokens(account, payload)
        return ret

    def get_source(self, cmsg):
        source  = conf().get("channel_type",None)
        if source:
            return source
        if getattr(cmsg, 'scf', False):
            return "wcferry" # hook
        if getattr(cmsg, 'wework', False):
            return "wework" # 企业微信
        to_user_id = getattr(cmsg, 'to_user_id', '')
        if to_user_id.startswith("gh_"):
            return "wechatmp" # 公众号
        return "noname"