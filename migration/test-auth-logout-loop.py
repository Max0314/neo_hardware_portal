#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""重复测试：登录 → 校验会话 → 退出 → 校验未登录。

用法（在项目根目录）:
  export AUTH_TEST_PASSWORD='你的密码'
  python3 migration/test-auth-logout-loop.py --user 20461992

依赖: Python 3.6+ 标准库；HTTPS 自签证书默认跳过校验（仅测试环境）。
"""
import argparse
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from http.cookiejar import CookieJar


def _load_dotenv_port(root):
    port = os.environ.get("GATEWAY_PUBLISH_PORT", "8000")
    env_path = os.path.join(root, ".env")
    if os.path.isfile(env_path):
        with open(env_path, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, val = line.split("=", 1)
                key = key.strip()
                val = val.strip().strip('"').strip("'")
                if key == "GATEWAY_PUBLISH_PORT" and val:
                    port = val
    # 本机脚本测试用 127.0.0.1；PUBLIC_BASE_URL 是对外浏览器地址，本机连 LAN IP 可能卡死
    base = os.environ.get("AUTH_TEST_BASE", "").strip().rstrip("/")
    if not base:
        base = "https://127.0.0.1:{0}".format(port)
    return base, port


def _ssl_context(insecure):
    ctx = ssl.create_default_context()
    if insecure:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _request(opener, method, url, data=None, timeout=60.0):
    headers = {}
    body = None
    if data is not None:
        body = urllib.parse.urlencode(data).encode("utf-8")
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    req = urllib.request.Request(url, data=body, headers=headers)
    req.get_method = lambda m=method: m
    started = time.time()
    with opener.open(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
        elapsed_ms = int((time.time() - started) * 1000)
        try:
            payload = json.loads(raw)
        except ValueError:
            payload = raw[:300]
        return resp.getcode(), elapsed_ms, payload


def run_round(base, username, password, timeout, insecure, round_no):
    cj = CookieJar()
    ctx = _ssl_context(insecure)
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(cj),
        urllib.request.HTTPSHandler(context=ctx),
    )
    result = {"round": round_no, "pass": False, "steps": []}

    def step(name, method, path, data=None):
        url = base.rstrip("/") + path
        print("  ... {0} {1}".format(method, path), flush=True)
        try:
            status, ms, payload = _request(opener, method, url, data=data, timeout=timeout)
            result["steps"].append({"name": name, "http": status, "ms": ms, "ok": True})
            return status, ms, payload
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            try:
                payload = json.loads(raw)
            except ValueError:
                payload = raw[:300]
            result["steps"].append(
                {"name": name, "http": exc.code, "ms": 0, "ok": False, "error": str(exc)}
            )
            return exc.code, 0, payload
        except Exception as exc:
            result["steps"].append({"name": name, "http": 0, "ms": 0, "ok": False, "error": str(exc)})
            raise

    status, ms, body = step(
        "login",
        "POST",
        "/api/auth/login",
        {"username": username, "password": password},
    )
    login_ok = isinstance(body, dict) and body.get("success") is True
    if not login_ok:
        result["fail_reason"] = "login failed: HTTP {0} {1}".format(status, body)
        return result

    status, ms, body = step("check_after_login", "GET", "/api/auth/check?lite=1")
    auth_in = isinstance(body, dict) and body.get("authenticated") is True
    if not auth_in:
        result["fail_reason"] = "check after login: authenticated=false ({0})".format(body)
        return result

    status, ms, body = step("logout", "GET", "/api/auth/logout")
    if status != 200:
        result["fail_reason"] = "logout HTTP {0}".format(status)
        return result

    status, ms, body = step("check_after_logout", "GET", "/api/auth/check?lite=1")
    auth_out = isinstance(body, dict) and body.get("authenticated") is True
    if auth_out:
        result["fail_reason"] = "still authenticated after logout"
        return result

    status, ms, body = step("get_home", "GET", "/")
    if status >= 500:
        result["fail_reason"] = "GET / returned HTTP {0}".format(status)
        return result

    result["pass"] = True
    return result


def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(script_dir)
    default_base, _ = _load_dotenv_port(root)

    parser = argparse.ArgumentParser(description="重复测试登录/退出 API 流程")
    parser.add_argument("--base", default=default_base, help="网关根 URL（默认 {0}）".format(default_base))
    parser.add_argument("--user", default=os.environ.get("AUTH_TEST_USER", "20461992"))
    parser.add_argument(
        "--password",
        default=os.environ.get("AUTH_TEST_PASSWORD", os.environ.get("AUTH_TEST_PASS", "")),
        help="密码（建议用环境变量 AUTH_TEST_PASSWORD，勿写入仓库）",
    )
    parser.add_argument("--rounds", type=int, default=3, help="循环次数（默认 3）")
    parser.add_argument("--timeout", type=float, default=60.0, help="单次请求超时秒数（默认 60）")
    parser.add_argument("--pause", type=float, default=0.5, help="每轮间隔秒数")
    parser.add_argument("--insecure", action="store_true", default=True, help="跳过 TLS 校验（默认开启）")
    parser.add_argument("--secure", action="store_true", help="启用 TLS 证书校验")
    args = parser.parse_args()

    if args.secure:
        args.insecure = False

    if not args.password:
        print("错误: 请设置 --password 或环境变量 AUTH_TEST_PASSWORD", file=sys.stderr)
        return 2

    print("========== 登录/退出循环测试 ==========")
    print("目标: {0}".format(args.base))
    print("账号: {0}".format(args.user))
    print("轮数: {0}  超时: {1}s".format(args.rounds, args.timeout))
    print("Python: {0}".format(sys.version.split()[0]))
    print()

    all_ok = True
    for i in range(1, args.rounds + 1):
        print("--- 第 {0}/{1} 轮 ---".format(i, args.rounds))
        try:
            row = run_round(
                args.base,
                args.user,
                args.password,
                args.timeout,
                args.insecure,
                i,
            )
        except Exception as exc:
            print("  异常: {0}".format(exc))
            all_ok = False
            if i < args.rounds and args.pause > 0:
                time.sleep(args.pause)
            continue

        for s in row.get("steps", []):
            name = s.get("name", "?")
            http = s.get("http", 0)
            ms = s.get("ms", 0)
            mark = "OK" if s.get("ok") else "FAIL"
            extra = " err={0}".format(s.get("error")) if s.get("error") else ""
            print("  [{0}] {1}: HTTP {2} ({3}ms){4}".format(mark, name, http, ms, extra))

        if row.get("pass"):
            print("  => 本轮通过")
        else:
            all_ok = False
            print("  => 本轮失败: {0}".format(row.get("fail_reason", "unknown")))
        print()
        if i < args.rounds and args.pause > 0:
            time.sleep(args.pause)

    print("========== 总结 ==========")
    if all_ok:
        print("全部通过")
        return 0
    print("存在失败项，请结合上方步骤与 docker compose logs htmlsystm gateway")
    return 1


if __name__ == "__main__":
    sys.exit(main())
