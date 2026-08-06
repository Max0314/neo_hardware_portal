# -*- coding: utf-8 -*-
"""对象存储客户端：阿里云 OSS（签名 V1）+ 本地目录实现。

设计约束：
- 纯标准库。两个服务镜像（htmlsystm / neo backend）都要用，不引入 oss2 及其
  依赖链，避免构建期外网波动；签名逻辑已在生产桶上实测验证。
- 本文件是 htmlsystm/server/object_store.py 的副本（两个镜像构建上下文互不
  可见），修改时必须同步两份。

签名要点（V1）：
- CanonicalizedResource 使用未编码的原始 key；HTTP 请求路径使用 UTF-8 百分号
  编码。中文文件名（公告附件常见）依赖这一区别才能通过校验。
- 列举用 V1 ListObjects（marker 分页），其查询参数不参与签名，规避 V2
  list-type 子资源的签名歧义。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from email.utils import formatdate
from typing import Iterator, List, Optional, Tuple


class ObjectStoreError(RuntimeError):
    """对象存储操作失败（含重试耗尽）。"""


_KEY_BAD = re.compile(r'(^/)|(\.\.)|(//)|(\\)')


def _check_key(key: str) -> str:
    """拒绝可疑 key：绝对路径、.. 穿越、反斜杠、空。"""
    if not key or _KEY_BAD.search(key):
        raise ObjectStoreError(f'非法对象 key: {key!r}')
    return key


class OssStore:
    """单 Bucket 的最小 OSS 客户端。所有 key 均相对于 prefix。"""

    def __init__(self, endpoint: str, bucket: str, access_key_id: str,
                 access_key_secret: str, prefix: str = '',
                 timeout: int = 30, max_retries: int = 3):
        self.endpoint = endpoint.replace('https://', '').replace('http://', '').strip('/')
        self.bucket = bucket
        self._ak = access_key_id
        self._sk = access_key_secret
        self.prefix = prefix.strip('/')
        self.timeout = timeout
        self.max_retries = max_retries

    # ---------- 内部 ----------

    def _full_key(self, key: str) -> str:
        _check_key(key)
        return f'{self.prefix}/{key}' if self.prefix else key

    def _sign(self, method: str, resource: str, date: str,
              content_type: str = '', oss_headers: Optional[List[Tuple[str, str]]] = None) -> str:
        canon_headers = ''
        for name, value in sorted(oss_headers or []):
            canon_headers += f'{name.lower()}:{value}\n'
        to_sign = f'{method}\n\n{content_type}\n{date}\n{canon_headers}{resource}'
        digest = hmac.new(self._sk.encode(), to_sign.encode('utf-8'), hashlib.sha1).digest()
        return f'OSS {self._ak}:{base64.b64encode(digest).decode()}'

    def _request(self, method: str, key: str = '', query: str = '',
                 body: Optional[bytes] = None, content_type: str = '',
                 oss_headers: Optional[List[Tuple[str, str]]] = None,
                 ok_codes: Tuple[int, ...] = (200,)) -> Tuple[int, bytes]:
        full = self._full_key(key) if key else ''
        resource = f'/{self.bucket}/{full}'
        quoted = urllib.parse.quote(full, safe='/')
        url = f'https://{self.bucket}.{self.endpoint}/{quoted}'
        if query:
            url += f'?{query}'

        last_err: Optional[Exception] = None
        for attempt in range(self.max_retries):
            date = formatdate(usegmt=True)
            headers = {'Date': date,
                       'Authorization': self._sign(method, resource, date, content_type, oss_headers)}
            if content_type:
                headers['Content-Type'] = content_type
            for name, value in (oss_headers or []):
                headers[name] = value
            req = urllib.request.Request(url, data=body, headers=headers, method=method)
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    return resp.status, resp.read()
            except urllib.error.HTTPError as e:
                detail = e.read()[:300]
                if e.code in ok_codes:
                    return e.code, detail
                # 4xx 为确定性失败（签名/权限/不存在），重试无意义
                if 400 <= e.code < 500:
                    raise ObjectStoreError(f'OSS {method} {key or "/"} -> {e.code}: {detail!r}')
                last_err = ObjectStoreError(f'OSS {method} {key or "/"} -> {e.code}: {detail!r}')
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                last_err = ObjectStoreError(f'OSS {method} {key or "/"} 网络失败: {e}')
            if attempt < self.max_retries - 1:
                time.sleep(1.5 * (2 ** attempt))
        raise last_err if last_err else ObjectStoreError('OSS 调用失败')

    # ---------- 公共 API ----------

    def put_bytes(self, key: str, data: bytes, content_type: str = 'application/octet-stream') -> None:
        self._request('PUT', key, body=data, content_type=content_type)

    def get_bytes(self, key: str) -> Optional[bytes]:
        """对象不存在返回 None，其余错误抛异常。"""
        try:
            _, body = self._request('GET', key)
            return body
        except ObjectStoreError as e:
            if '404' in str(e):
                return None
            raise

    def exists(self, key: str) -> bool:
        try:
            self._request('HEAD', key)
            return True
        except ObjectStoreError as e:
            if '404' in str(e):
                return False
            raise

    def delete(self, key: str) -> None:
        """删除对象；对象本就不存在也视为成功（幂等）。"""
        self._request('DELETE', key, ok_codes=(200, 204))

    def copy(self, src_key: str, dst_key: str) -> None:
        src = urllib.parse.quote(f'/{self.bucket}/{self._full_key(src_key)}', safe='/')
        self._request('PUT', dst_key, oss_headers=[('x-oss-copy-source', src)])

    def iter_keys(self, key_prefix: str = '') -> Iterator[str]:
        """按前缀迭代对象 key（已剥离 store prefix）。V1 marker 分页。"""
        scoped = self._full_key(key_prefix) if key_prefix else self.prefix
        strip = f'{self.prefix}/' if self.prefix else ''
        marker = ''
        while True:
            q = 'max-keys=1000'
            if scoped:
                q += '&prefix=' + urllib.parse.quote(scoped if scoped.endswith('/') or not key_prefix else scoped, safe='/')
            if marker:
                q += '&marker=' + urllib.parse.quote(marker, safe='/')
            _, body = self._request('GET', '', query=q)
            text = body.decode('utf-8', 'replace')
            keys = re.findall(r'<Key>([^<]+)</Key>', text)
            for k in keys:
                yield k[len(strip):] if strip and k.startswith(strip) else k
            if '<IsTruncated>true</IsTruncated>' in text and keys:
                marker = keys[-1]
            else:
                return

    def delete_prefix(self, key_prefix: str) -> int:
        """删除前缀下全部对象，返回删除数。"""
        n = 0
        for k in list(self.iter_keys(key_prefix)):
            self.delete(k)
            n += 1
        return n

    def presigned_url(self, key: str, expires_sec: int = 300) -> str:
        full = self._full_key(key)
        expires = str(int(time.time()) + expires_sec)
        resource = f'/{self.bucket}/{full}'
        to_sign = f'GET\n\n\n{expires}\n{resource}'
        sig = base64.b64encode(
            hmac.new(self._sk.encode(), to_sign.encode('utf-8'), hashlib.sha1).digest()).decode()
        quoted = urllib.parse.quote(full, safe='/')
        return (f'https://{self.bucket}.{self.endpoint}/{quoted}'
                f'?OSSAccessKeyId={urllib.parse.quote(self._ak)}'
                f'&Expires={expires}&Signature={urllib.parse.quote(sig)}')


class LocalStore:
    """与 OssStore 同接口的本地目录实现（开发/回退用）。"""

    def __init__(self, root: str):
        self.root = os.path.abspath(root)
        os.makedirs(self.root, exist_ok=True)

    def _path(self, key: str) -> str:
        _check_key(key)
        p = os.path.abspath(os.path.join(self.root, key))
        if not p.startswith(self.root + os.sep) and p != self.root:
            raise ObjectStoreError(f'key 越出根目录: {key!r}')
        return p

    def put_bytes(self, key: str, data: bytes, content_type: str = '') -> None:
        p = self._path(key)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        tmp = p + '.tmp'
        with open(tmp, 'wb') as fh:
            fh.write(data)
        os.replace(tmp, p)

    def get_bytes(self, key: str) -> Optional[bytes]:
        try:
            with open(self._path(key), 'rb') as fh:
                return fh.read()
        except FileNotFoundError:
            return None

    def exists(self, key: str) -> bool:
        return os.path.isfile(self._path(key))

    def delete(self, key: str) -> None:
        try:
            os.remove(self._path(key))
        except FileNotFoundError:
            pass

    def copy(self, src_key: str, dst_key: str) -> None:
        data = self.get_bytes(src_key)
        if data is None:
            raise ObjectStoreError(f'源对象不存在: {src_key}')
        self.put_bytes(dst_key, data)

    def iter_keys(self, key_prefix: str = '') -> Iterator[str]:
        for base, _dirs, files in os.walk(self.root):
            for name in files:
                if name.endswith('.tmp'):
                    continue
                rel = os.path.relpath(os.path.join(base, name), self.root).replace(os.sep, '/')
                if not key_prefix or rel.startswith(key_prefix):
                    yield rel

    def delete_prefix(self, key_prefix: str) -> int:
        n = 0
        for k in list(self.iter_keys(key_prefix)):
            self.delete(k)
            n += 1
        return n

    def presigned_url(self, key: str, expires_sec: int = 300) -> Optional[str]:
        return None


def build_store_from_env(purpose_prefix: str = ''):
    """按环境变量构造存储。

    STORAGE_BACKEND=local 返回 None —— 调用方保持纯本地行为，这让 oss 相关
    配置缺失时系统仍可运行（迁移前/回滚后状态）。
    purpose_prefix 叠加在 OSS_PREFIX 之后，用于按模块隔离（announcements/...）。
    """
    backend = (os.getenv('STORAGE_BACKEND') or 'local').strip().lower()
    if backend != 'oss':
        return None
    endpoint = (os.getenv('OSS_ENDPOINT') or '').strip()
    bucket = (os.getenv('OSS_BUCKET') or '').strip()
    ak = (os.getenv('OSS_ACCESS_KEY_ID') or '').strip()
    sk = (os.getenv('OSS_ACCESS_KEY_SECRET') or '').strip()
    if not (endpoint and bucket and ak and sk):
        raise ObjectStoreError(
            'STORAGE_BACKEND=oss 但 OSS_ENDPOINT/OSS_BUCKET/OSS_ACCESS_KEY_ID/'
            'OSS_ACCESS_KEY_SECRET 不完整')
    prefix = (os.getenv('OSS_PREFIX') or '').strip('/')
    if purpose_prefix:
        prefix = f'{prefix}/{purpose_prefix}'.strip('/') if prefix else purpose_prefix
    return OssStore(endpoint, bucket, ak, sk, prefix=prefix)
