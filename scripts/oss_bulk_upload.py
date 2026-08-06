#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把本地目录树一次性上传到 OSS（迁移期初始灌数用）。

在应用容器内运行（htmlsystm 或 neo backend，两者都带 object_store 模块）：

    # 预演：只列出将上传什么，不发任何写请求
    python3 oss_bulk_upload.py --root /app/data/announcements --purpose announcements

    # 真正上传 + 逐对象下载回读校验 + 写 TreeMirror 状态清单
    python3 oss_bulk_upload.py --root /app/data/announcements --purpose announcements \
        --upload --verify --write-mirror-state

    # 网表结果（backend 容器）
    python3 oss_bulk_upload.py --root /data/netlist_results --purpose netlist-results --upload --verify

--write-mirror-state 生成 .mirror_state.json，让 TreeMirror 首次对账时确认
"远端已有且一致"而不是把整树再传一遍。

凭据从环境变量读取（OSS_ENDPOINT/OSS_BUCKET/OSS_PREFIX/OSS_ACCESS_KEY_ID/
OSS_ACCESS_KEY_SECRET）。脚本自身不打印任何凭据。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys

for candidate in ('/app', '/app/backend', os.path.dirname(os.path.dirname(os.path.abspath(__file__)))):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

try:
    from server.object_store import OssStore  # htmlsystm 容器
except ImportError:
    from backend.object_store import OssStore  # neo backend 容器

DEFAULT_EXCLUDE_SUFFIXES = ('.lock', '.tmp', '.swp')
DEFAULT_EXCLUDE_NAMES = ('.mirror_state.json',)
DEFAULT_EXCLUDE_PARTS = ('locks',)


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as fh:
        for chunk in iter(lambda: fh.read(1024 * 512), b''):
            h.update(chunk)
    return h.hexdigest()


def collect(root: str, extra_suffixes: tuple) -> dict:
    files = {}
    for dirpath, _dirs, names in os.walk(root):
        for name in names:
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, root).replace(os.sep, '/')
            parts = rel.split('/')
            if name in DEFAULT_EXCLUDE_NAMES:
                continue
            if name.endswith(DEFAULT_EXCLUDE_SUFFIXES) or name.endswith(extra_suffixes):
                continue
            if any(p in DEFAULT_EXCLUDE_PARTS for p in parts[:-1]):
                continue
            files[rel] = full
    return files


def main() -> int:
    ap = argparse.ArgumentParser(description='本地目录 → OSS 批量上传')
    ap.add_argument('--root', required=True, help='本地目录')
    ap.add_argument('--purpose', required=True,
                    help='对象前缀（announcements / netlist-results / knowledge / knowledge-recycle）')
    ap.add_argument('--upload', action='store_true', help='真正上传；缺省只预演')
    ap.add_argument('--verify', action='store_true', help='上传后逐对象下载回读比对 SHA-256')
    ap.add_argument('--write-mirror-state', action='store_true',
                    help='完成后写 .mirror_state.json 供 TreeMirror 复用')
    ap.add_argument('--exclude-suffix', action='append', default=[],
                    help='额外排除的文件后缀，可重复（如 .sqlite3）')
    args = ap.parse_args()

    root = os.path.abspath(args.root)
    if not os.path.isdir(root):
        print(f'[FAIL] 目录不存在: {root}')
        return 2

    endpoint = os.getenv('OSS_ENDPOINT', '').strip()
    bucket = os.getenv('OSS_BUCKET', '').strip()
    ak = os.getenv('OSS_ACCESS_KEY_ID', '').strip()
    sk = os.getenv('OSS_ACCESS_KEY_SECRET', '').strip()
    base_prefix = os.getenv('OSS_PREFIX', '').strip('/')
    if not (endpoint and bucket and ak and sk):
        print('[FAIL] 缺少 OSS_ENDPOINT/OSS_BUCKET/OSS_ACCESS_KEY_ID/OSS_ACCESS_KEY_SECRET')
        return 2
    prefix = f'{base_prefix}/{args.purpose}'.strip('/') if base_prefix else args.purpose
    store = OssStore(endpoint, bucket, ak, sk, prefix=prefix)

    files = collect(root, tuple(args.exclude_suffix))
    total_bytes = sum(os.path.getsize(p) for p in files.values())
    print(f'待处理: {len(files)} 个文件, {total_bytes / 1024 / 1024:.1f} MB')
    print(f'目标  : oss://{bucket}/{prefix}/')

    if not args.upload:
        for rel in sorted(files)[:20]:
            print(f'  (预演) {rel}')
        if len(files) > 20:
            print(f'  ... 共 {len(files)} 个')
        print('未上传任何对象。加 --upload 执行。')
        return 0

    manifest = {}
    failed = []
    for i, (rel, full) in enumerate(sorted(files.items()), 1):
        try:
            with open(full, 'rb') as fh:
                store.put_bytes(rel, fh.read())
            manifest[rel] = sha256_file(full)
        except Exception as e:  # noqa: BLE001
            failed.append(f'{rel}: {e}')
        if i % 50 == 0 or i == len(files):
            print(f'  上传 {i}/{len(files)}')
    if failed:
        print(f'[FAIL] {len(failed)} 个上传失败:')
        for f in failed[:10]:
            print(f'  {f}')
        return 1

    if args.verify:
        bad = []
        for i, (rel, sha) in enumerate(sorted(manifest.items()), 1):
            data = store.get_bytes(rel)
            if data is None or hashlib.sha256(data).hexdigest() != sha:
                bad.append(rel)
            if i % 50 == 0 or i == len(manifest):
                print(f'  校验 {i}/{len(manifest)}')
        if bad:
            print(f'[FAIL] {len(bad)} 个对象校验不一致:')
            for b in bad[:10]:
                print(f'  {b}')
            return 1
        print(f'[ OK ] 全部 {len(manifest)} 个对象回读校验一致')

    if args.write_mirror_state:
        state_path = os.path.join(root, '.mirror_state.json')
        tmp = state_path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as fh:
            json.dump(manifest, fh, ensure_ascii=False, separators=(',', ':'))
        os.replace(tmp, state_path)
        print(f'[ OK ] 已写镜像状态清单: {state_path}（{len(manifest)} 条）')

    print('[ OK ] 完成')
    return 0


if __name__ == '__main__':
    sys.exit(main())
