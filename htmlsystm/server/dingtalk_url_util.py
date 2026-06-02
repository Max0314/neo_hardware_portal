# -*- coding: utf-8 -*-
"""钉钉客户端内 openapp 跳转链接构建。"""
from __future__ import annotations

import urllib.parse
from typing import Optional

from server.config import DINGTALK_CONFIG, PUBLIC_BASE_URL


def build_dingtalk_openapp_url(redirect_path: str, base_url: Optional[str] = None) -> str:
    """
    构建 dingtalk://.../openapp 链接，在钉钉工作台内打开 H5 页面。
    redirect_path: 以 / 开头的站内路径，如 /announcement-detail/123
    """
    path = (redirect_path or '').strip()
    if not path.startswith('/'):
        path = '/' + path

    base = (base_url or PUBLIC_BASE_URL or '').rstrip('/')
    if not base:
        redirect_url = path
    else:
        redirect_url = f"{base}{path}"

    agent_id_raw = str(DINGTALK_CONFIG.get('agent_id', '') or '')
    if agent_id_raw.endswith('G'):
        agent_id_raw = agent_id_raw[:-1]
    appid = f"0_{agent_id_raw}" if agent_id_raw else "0_4118967622"
    corpid = DINGTALK_CONFIG.get('corp_id', '') or ''

    return (
        f"dingtalk://dingtalkclient/action/openapp?corpid={corpid}"
        f"&container_type=work_platform&appid={appid}&redirect_type=jump"
        f"&redirect_url={urllib.parse.quote(redirect_url, safe='')}"
    )


def build_announcement_detail_dingtalk_url(announcement_id: str, base_url: Optional[str] = None) -> str:
    aid = str(announcement_id or '').strip()
    return build_dingtalk_openapp_url(f"/announcement-detail/{aid}", base_url)


def build_review_center_dingtalk_url(base_url: Optional[str] = None) -> str:
    return build_dingtalk_openapp_url('/review-center', base_url)


def build_material_db_dingtalk_url(base_url: Optional[str] = None) -> str:
    """物料数据库页（NEO systm_tool）。"""
    path = '/neo/systm_tool/material-database.html'
    return build_dingtalk_openapp_url(path, base_url)
