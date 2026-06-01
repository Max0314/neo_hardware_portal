#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
巴巴塔文件聊天室 · 环境与接口检查脚本
检查后端是否运行、文件 API / WebSocket 是否可用，以及页面依赖的 URL 是否一致。
运行方式（在项目根目录）：
  python systm_tool/check_babata_chat.py
  python -m systm_tool.check_babata_chat
"""
import json
import os
import sys
import urllib.error
import urllib.request
import urllib.parse
from pathlib import Path

# 默认后端地址（与 巴巴塔文件聊天室.html 中一致）
BASE_URL = os.environ.get("BABATA_API_BASE", "http://localhost:8000")
WS_URL = os.environ.get("BABATA_WS_URL", "ws://localhost:8000/ws")

# 项目根目录
ROOT = Path(__file__).resolve().parent.parent
HTML_FILE = ROOT / "systm_tool" / "巴巴塔文件聊天室.html"


def ok(msg):
    print(f"  [OK] {msg}")


def fail(msg):
    print(f"  [FAIL] {msg}")


def warn(msg):
    print(f"  [WARN] {msg}")


def section(title):
    print(f"\n--- {title} ---")


def http_get(url, timeout=5):
    req = urllib.request.Request(url, method="GET")
    req.add_header("Accept", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.getcode(), r.read().decode("utf-8")


def main():
    print("巴巴塔文件聊天室 · 环境检查")
    print("后端 BASE_URL:", BASE_URL)
    print("WebSocket URL:", WS_URL)

    has_error = False

    # 1. 后端是否存活
    section("1. 后端服务")
    try:
        code, body = http_get(f"{BASE_URL}/")
        data = json.loads(body)
        if data.get("status") == "running":
            ok("后端服务正常")
        else:
            fail(f"后端返回异常: {data}")
            has_error = True
    except urllib.error.URLError as e:
        fail(f"无法连接后端: {e}")
        has_error = True
    except Exception as e:
        fail(f"请求失败: {e}")
        has_error = True

    # 2. 文件系统 API：roots
    section("2. 文件系统 API · 盘符列表")
    try:
        code, body = http_get(f"{BASE_URL}/api/fs/roots")
        roots = json.loads(body)
        if isinstance(roots, list):
            ok(f"/api/fs/roots 返回 {len(roots)} 个盘符/根")
            for r in roots[:5]:
                name = r.get("name", r.get("path", ""))
                print(f"      - {name}")
            if len(roots) > 5:
                print(f"      ... 共 {len(roots)} 项")
        else:
            fail(f"/api/fs/roots 返回非列表: {type(roots)}")
            has_error = True
    except urllib.error.URLError as e:
        fail(f"请求 /api/fs/roots 失败: {e}")
        has_error = True
    except Exception as e:
        fail(f"/api/fs/roots 异常: {e}")
        has_error = True

    # 3. 文件系统 API：list（用第一个盘符）
    section("3. 文件系统 API · 目录列表")
    try:
        code, body = http_get(f"{BASE_URL}/api/fs/roots")
        roots = json.loads(body)
        if roots:
            first_path = roots[0].get("path", roots[0].get("name", ""))
            if first_path:
                list_url = f"{BASE_URL}/api/fs/list?path={urllib.parse.quote(first_path)}"
                code2, body2 = http_get(list_url)
                items = json.loads(body2)
                if isinstance(items, list):
                    ok(f"/api/fs/list 正常，首盘下共 {len(items)} 项")
                else:
                    fail(f"/api/fs/list 返回非列表")
                    has_error = True
            else:
                warn("未找到首盘 path，跳过 list 测试")
        else:
            warn("无盘符，跳过 list 测试")
    except Exception as e:
        fail(f"/api/fs/list 测试异常: {e}")
        has_error = True

    # 4. WebSocket（可选）
    section("4. WebSocket 连接")
    try:
        import websocket  # type: ignore
        ws = websocket.create_connection(WS_URL, timeout=3)
        ws.close()
        ok("WebSocket 可连接")
    except ImportError:
        warn("未安装 websocket-client，跳过 WebSocket 检查（pip install websocket-client）")
    except Exception as e:
        fail(f"WebSocket 连接失败: {e}")
        has_error = True

    # 5. 巴巴塔页面文件与 URL 一致性
    section("5. 巴巴塔文件聊天室页面")
    if not HTML_FILE.exists():
        fail(f"页面文件不存在: {HTML_FILE}")
        has_error = True
    else:
        ok(f"页面文件存在: {HTML_FILE.name}")
        text = HTML_FILE.read_text(encoding="utf-8")
        base_in_html = "localhost:8000" in text or "127.0.0.1:8000" in text
        if base_in_html:
            ok("页面内包含 localhost:8000 / 127.0.0.1:8000")
        else:
            warn("页面内未找到 localhost:8000，请确认 API 地址与后端一致")
        if "api/fs/roots" in text and "api/fs/list" in text:
            ok("页面内包含 /api/fs/roots 与 /api/fs/list")
        else:
            fail("页面内缺少文件 API 路径引用")
            has_error = True

    # 6. 文件索引 API（可选，依赖 workspace）
    section("6. 文件索引 API")
    try:
        code, body = http_get(f"{BASE_URL}/api/fs/roots")
        roots = json.loads(body)
        if roots:
            wp = roots[0].get("path", roots[0].get("name", ""))
            if wp:
                url = f"{BASE_URL}/api/fs/file_index?workspace_path={urllib.parse.quote(wp)}"
                code2, body2 = http_get(url)
                idx = json.loads(body2)
                if isinstance(idx, list):
                    ok(f"/api/fs/file_index 正常，当前 workspace 索引条数: {len(idx)}")
                else:
                    fail("/api/fs/file_index 返回非列表")
                    has_error = True
        else:
            warn("无盘符，跳过 file_index 测试")
    except Exception as e:
        fail(f"/api/fs/file_index 异常: {e}")
        has_error = True

    # 汇总
    section("汇总")
    if has_error:
        print("存在失败项，请根据上方 [FAIL] 排查。")
        print("常见原因：后端未启动（在项目根执行 uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000）")
        sys.exit(1)
    print("所有检查通过，可打开 巴巴塔文件聊天室.html 使用。")
    sys.exit(0)


if __name__ == "__main__":
    main()
