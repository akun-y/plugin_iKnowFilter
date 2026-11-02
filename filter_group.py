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
import time
from typing import Optional, TypedDict
from bridge.reply import ReplyType

# from lib import itchat
from channel.contact_info import ContactInfo
from bridge.context import ContextType
from common.log import logger
from plugins import *
from channel.chat_channel import check_contain

# from plugins.plugin_comm.remark_name_info import RemarkNameInfo
from plugins.plugin_comm.constants import EthZero
from plugins.plugin_comm.contacts.mycontacts import contact_to_groupx_channel, get_chatroom_form_channel
from plugins.plugin_comm.groupx.groupx_users_man import ContactFromSrv, ContactFromSrv_to_groupx, GroupxUserMan
from plugins.plugin_comm.plugin_comm import (
    is_eth_address,
    make_wxgroup_by_ctx,
    make_wxuser_by_ctx,
    send_text,
    send_text_with_url,
)

from plugins.plugin_iKnowFilter.filter_base import FilterBase


def _brief_result(ret):
    try:
        text = json.dumps(ret, ensure_ascii=False, default=str)
    except TypeError:
        text = str(ret)
    if len(text) > 500:
        text = text[:500] + "...(截断)"
    return text


class FilterGroup(FilterBase):
    def __init__(self, config, groupx, contacts_groupx: GroupxUserMan):
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
        self.robot_account = conf().get("bot_account", EthZero)
        self.robot_name = conf().get("bot_name")

    def before_handle_context(self, e_context: EventContext):
        context = e_context["context"]

        content = context.content
        msg = context.get("msg")
        
        wx_group = make_wxgroup_by_ctx(context)
        group_name = wx_group.get("name", "")
        wx_user = make_wxuser_by_ctx(context)
        # 1- 保存消息到数据库。未授权时不访问 API
        ret = None
        if self.groupx.cow_token:
            ret = self._post_group_msg(msg)
            logger.info(f"[filtGrp] ======>保存消息到groupx:群:{group_name}\n服务器返回:\n{ret}")
        if ret:
            results = ret.get("results", None)
            if results and len(results) > 0:
                group_object_id = results[0].get("groupOID", "")
                missingItemsGroup = ret.get("missingItemsGroup", None)
                memberCount = ret.get("memberCount", 0)
                result_body = results[0].get("result") or {}
                wx_group = make_wxgroup_by_ctx(context)
                if group_object_id and group_object_id != wx_group.get("objectId"):
                    self._set_contact_info({**wx_group,"objectId": group_object_id})
                if context.type != ContextType.JOIN_GROUP and (missingItemsGroup or memberCount < 1):
                    logger.warn(f"[filtGrp] 需要补充群信息,msg:{msg}")
                    channel_type = conf().get("channel_type", "wx") or 'wx'
                    chatroom = get_chatroom_form_channel(channel_type, wx_group.get("wxid"), msg)
                    if chatroom:
                        # 将wx_group 和 chatroom 合并
                        member_list= chatroom.get("member_list")
                        if member_list:
                            # 为 member_list 所有成员调用contact_to_groupx_channel 转换为groupx 格式
                            member_list = [contact_to_groupx_channel(channel_type,member) for member in member_list]
                            #contact_to_groupx_channel(channel_type, wx_group.get("wxid"), member_list)                        
                            wx_group["member_list"]= member_list
                            groupx_contact = ContactFromSrv_to_groupx(wx_group)
                            # 如需后续使用 merged_group，可替换下方 chatroom 为 merged_group
                        
                            self.groupx.post_groups( self.robot_account, self.robot_name, [groupx_contact], channel_type)
                            logger.warn(f"[filtGrp] [{group_name}]群信息不完整，补充发送给服务器:{groupx_contact}")
                    else:
                        logger.error("[filtGrp] 获取群成员及详细信息失败")

                # 设置 user objectId
                user_object_id = results[0].get("userOID", "")
                gx_user_account = result_body.get("account", "")
                wx_user = make_wxuser_by_ctx(context)
                if user_object_id and user_object_id != wx_user.get("objectId"):
                    self._set_contact_info(
                        {
                            **wx_user,
                            "objectId": user_object_id,
                            "account": gx_user_account
                        }
                    )
                if gx_user_account and gx_user_account != wx_user.get("account"):
                    self._set_contact_info(
                        { 
                            **wx_user,
                            "objectId": user_object_id,
                            "account": gx_user_account
                        }
                    )

                # 服务端已生成打卡/卡路里答复但未发出时，由本机发到群并停止后续 AI
                if not results[0].get("sendResult"):
                    show_text = (result_body.get("showText") or "").strip()
                    show_text2 = (result_body.get("showText2") or "").strip()
                    if show_text or show_text2:
                        if show_text:
                            send_text(e_context, show_text)
                            logger.warning(f"[filtGrp] 已发送服务端答复 showText len={len(show_text)}")
                        if show_text2:
                            time.sleep(1.2)
                            send_text(e_context, show_text2)
                            logger.warning(f"[filtGrp] 已发送服务端答复 showText2 len={len(show_text2)}")
                        e_context.action = EventAction.BREAK_PASS
                        return

        if context.type == ContextType.JOIN_GROUP and self.groupx.cow_token:
            self._push_join_group(context, wx_group)

        # 2- 是带有约定前缀的，转给系统及其它插件处理
        if any(msg.content.startswith(item) for item in self.prefix_array):
            logger.warn(f"[filtGrp] =====>是带有约定前缀的，转给系统及其它插件处理 {msg.content}")
            return  # 转给系统及其他插件

        # 3- 是机器人发出的消息， 终止处理
        if msg.my_msg:
            logger.warning("[filtGrp] --->group filter:我自己发出的消息")
            e_context.action = EventAction.BREAK_PASS  # 不响应
            return

        # 4- 无关键字也继续派发给其他插件处理
        if (
            group_name in self.group_chat_keyword_ignore
            or "ALL_GROUP" in self.group_white_list
        ):
            logger.info(
                f"[filtGrp] --->group filter:群在'关键字'忽略名单中,继续处理 {group_name}"
            )  # 频率非常高
            return  # 转给系统及其他插件
        # 6- 群名不在白名单中，中止处理
        if (
            group_name not in self.group_white_list
            and "ALL_GROUP" not in self.group_white_list
        ):
            e_context.action = EventAction.BREAK_PASS
            return  # 不响应,中止

        # logger.info(f"[filtGrp]群在白名单中,继续处理 {group_name}")  # 频率非常高

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
        account = user.get("account", "")
        ret = self._consume_tokens(
            account, user, group, total_tokens, completion_tokens, replyMsg, cmsg
        )
        if ret:
            # 写入服务器返回的account到user remarkname中
            if is_eth_address(ret["account"]) and account != ret["account"]:
                self._set_contact_info({ 
                        **user,
                        "account": ret["account"]
                    })

            balance = ret["balanceAITokens"]
            if ret["success"] is False:
                logger.warn(f"======>[filtGrp] consumeTokens fail {ret}")
                #itchat.send_msg(msg, toUserName=to_user_id)
                chat_billing_enabled = conf().get("chat_billing_enabled", False)
                if chat_billing_enabled:
                    send_text_with_url(
                        e_context,f"积分不足，请及时充值或购买套餐。\n(余额: {balance})",
                        ret.get('payMiniAppUrl',self.recharge_url),
                    )
                    e_context.action = EventAction.BREAK_PASS
                    return
                else:
                    logger.warn(f"======>[filtGrp] 积分不足但聊天收费开关未开启，允许继续使用。余额: {balance}")
            logger.warn(f"======>[filtGrp] consumeTokens successl {ret}")
        else:
            logger.warn(f"======>[filtGrp] consumeTokens fail {ret}")
            chat_billing_enabled = conf().get("chat_billing_enabled", False)
            if chat_billing_enabled:
                send_text_with_url(
                    e_context,
                    "消费积分失败，请点击链接注册。",
                    self.reg_url,
                )
                e_context.action = EventAction.BREAK_PASS
                return
            else:
                logger.warn(f"======>[filtGrp] 消费积分失败但聊天收费开关未开启，允许继续使用。")

    def _push_join_group(self, context, wx_group):
        """入群后把这一群的成员和新成员推到 groupx。群名为空时不覆盖服务器上的群名。"""
        msg = context.get("msg")
        group_id = wx_group.get("wxid") or getattr(msg, "other_user_id", "")
        group_name = wx_group.get("name") or getattr(msg, "other_user_nickname", "") or ""
        channel_type = conf().get("channel_type", "wx") or "wx"
        chatroom = get_chatroom_form_channel(channel_type, group_id, msg)
        raw_members = chatroom.get("member_list") if isinstance(chatroom, dict) else None
        members = [
            contact_to_groupx_channel(channel_type, member)
            for member in (raw_members or [])
            if isinstance(member, dict)
        ]
        payload = {"UserName": group_id, "MemberList": members}
        if group_name:
            payload["NickName"] = group_name
        logger.info(
            f"[filtGrp] 入群推送群资料 group={group_id} name={group_name or '(空)'} members={len(members)}"
        )
        try:
            ret = self.groupx.post_groups(self.robot_account, self.robot_name, [payload], channel_type)
            logger.info(f"[filtGrp] 入群群资料返回: {_brief_result(ret)}")
        except Exception as exc:
            logger.error(f"[filtGrp] 入群群资料失败: {exc}")

        contacts = getattr(msg, "join_contacts", None) or []
        friends = [
            contact_to_groupx_channel(channel_type, contact)
            for contact in contacts
            if isinstance(contact, dict)
        ]
        logger.info(
            f"[filtGrp] 入群推送新成员通讯录 count={len(friends)} "
            f"ids={[contact.get('user_id') for contact in contacts if isinstance(contact, dict)]}"
        )
        if not friends:
            return
        try:
            ret = self.groupx.post_friends(self.robot_account, self.robot_name, friends, channel_type)
            logger.info(f"[filtGrp] 入群通讯录返回: {_brief_result(ret)}")
        except Exception as exc:
            logger.error(f"[filtGrp] 入群通讯录失败: {exc}")

    def _post_group_msg(self, cmsg):
        try:
            wx_user_id = cmsg.actual_user_id or cmsg.from_user_id
            wx_user_nickname = cmsg.actual_user_nickname or cmsg.from_user_nickname

            wx_group_id = cmsg.other_user_id
            wx_group_nickname = cmsg.other_user_nickname

            group = {
                "UserName": wx_group_id,
                "NickName": wx_group_nickname,
                "RemarkName": "",
            }  # get_itchat_group(wx_group_id)

            user = self._get_user_info(wx_user_id, wx_user_nickname)
            account = user.get("account", "") if user else ""
            source = ""
            if getattr(cmsg, "scf", False):
                source = "wcferry"
            elif getattr(cmsg, "wework", False):
                source = "wework"
            
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
                    "thumb": getattr(cmsg._rawmsg, "thumb", ""),
                    "extra": getattr(cmsg._rawmsg, "extra", ""),
                    "source": source,
                    "system_name": getattr(self, "system_name", ""),
                },
            )
        except Exception as e:
            logger.error(f"======>[filtGrp] _post_group_msg fail {e}")
