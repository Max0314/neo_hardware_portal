from fastapi import (
    FastAPI,
    WebSocket,
    WebSocketDisconnect,
    UploadFile,
    File,
    Form,
    Request,
)
import asyncio
import hashlib
import json
import os
import threading
import time
from dotenv import load_dotenv
from datetime import datetime, timedelta
import uuid
from pathlib import Path
from typing import Optional, List, Dict, Any
import aiohttp
from openai import AsyncOpenAI
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse, Response

from backend.websocket.manager import ConnectionManager
from backend.ai.adapters import AIAdapterManager
from backend.models.message import MessageStore
from backend.utils.role_prompt_builder import RolePromptBuilder
from backend.utils.context_optimizer import ContextOptimizer
from backend.utils.response_cache import ResponseCache
from backend.models.knowledge_base import create_knowledge_base
from backend.utils.babata_processor import BabataProcessor, TaskAction
from backend.utils.netlist_parser import PadsNetlistParser, NetlistComparator
from backend.utils.netlist_analyzer import NetlistAnalyzer
from backend.models.netlist_result import NetlistResultStore
from backend.models.dashboard_metrics import (
    count_netlist_need_check_items,
    month_range,
)
from backend.models.dashboard_metrics_factory import create_dashboard_metrics_store
from backend.constants.user_levels import level_from_points
from backend.event_triggers import event_handler
from backend.models.memory_store import MemoryItemStore
from backend.memory.memory_service import MemoryService
from backend.memory.vector_backend import create_vector_memory_backend
from backend.memory.extract_pipeline import (
    init_extract_queue,
    run_memory_extract_worker,
    enqueue_extract,
)
from backend.memory.types import ExtractJob, MemoryRecallContext, RecallStep, RecallStrategy

# 向量存储（可选功能）
try:
    from backend.models.vector_store import VectorStore
    VECTOR_STORE_AVAILABLE = True
except ImportError:
    print("警告: chromadb未安装，向量记忆功能将不可用")
    VECTOR_STORE_AVAILABLE = False
    VectorStore = None

# 加载.env文件（从项目根目录）
env_path = Path(__file__).parent.parent / '.env'
# 尝试多种方式加载
load_dotenv(dotenv_path=env_path, override=True)
load_dotenv(override=True)  # 也从当前工作目录加载
print(f"加载.env文件: {env_path}")
print(f".env文件存在: {env_path.exists()}")
print("[ai-keys] 启动后将通过加密库或环境变量解析 API Key（不在日志中输出密钥内容）")

# 数据目录：未设置时与当前工作目录一致；Docker 中可设为 /data 并挂载卷
_chatroom_data = Path(os.getenv("CHATROOM_DATA_DIR", "").strip() or ".")
_chatroom_data.mkdir(parents=True, exist_ok=True)
CHATROOM_DB_PATH = str(_chatroom_data / "chatroom.db")
NETLIST_RESULTS_DIR = str(_chatroom_data / "netlist_results")
DASHBOARD_METRICS_DB_PATH = str(_chatroom_data / "dashboard_metrics.db")
KNOWLEDGE_BASES_DIR = str(_chatroom_data / "knowledge_bases")


def _make_knowledge_base(role_id: str, use_vector: bool):
    return create_knowledge_base(
        role_id,
        use_vector=use_vector,
        db_path=CHATROOM_DB_PATH,
        persist_directory=KNOWLEDGE_BASES_DIR,
    )


from backend.services.ai_key_resolver import (
    init_ai_key_resolver,
    has_provider,
    get_secret_async,
    save_provider_secret,
    delete_provider_secret,
    list_providers_status,
)
from backend.models.ai_provider_keys import get_provider, AI_KEY_PROVIDERS
from backend.ai.bailian_models import (
    BAILIAN_MODELS,
    build_mention_alias_map,
    get_api_model,
    get_bailian_model,
    is_bailian_ai_id,
    resolve_base_ai_id,
)


def _resolve_base_ai_id(ai_id: str) -> str:
    return resolve_base_ai_id(ai_id or "") or (ai_id or "")


async def _is_ai_invokable(ai_config: dict) -> bool:
    """判断 AI 是否可调用（前端勾选或已配置 API Key）。"""
    if ai_config.get("id") == "babata":
        return False
    if ai_config.get("enabled"):
        return True
    ai_id = ai_config.get("id") or ""
    base_ai = ai_config.get("baseAI") or _resolve_base_ai_id(ai_id)
    if base_ai.startswith("bailian-"):
        return await has_provider("bailian")
    if str(ai_id).startswith("custom-"):
        return await has_provider(base_ai)
    return await has_provider(ai_id)


async def _enrich_mentioned_ai_config(ai_config: dict) -> dict:
    """@ 提及临时激活：合并服务端 API Key 可用性，避免前端未传 enabled 导致静默跳过。"""
    cfg = dict(ai_config)
    if await _is_ai_invokable(cfg):
        cfg["enabled"] = True
    return cfg


async def _provider_enabled_for_api(ai_id: str) -> bool:
    return await has_provider(ai_id)


async def _build_llm_provider_catalog() -> list:
    """内置大模型列表（enabled 反映加密库或环境变量是否已配置）。"""
    specs = [
        ("gpt-4", "ChatGPT", "🤖", "OpenAI GPT-4"),
        ("claude-3", "Claude", "👽", "Anthropic Claude 3"),
        ("gemini", "Gemini", "⭐", "Google Gemini"),
        ("deepseek", "DeepSeek", "🧠", "DeepSeek V3.2"),
        ("doubao", "豆包 SEED Mini", "\U0001f525", "火山方舟 Doubao SEED-2.0-Mini"),
    ]
    out = []
    for pid, name, avatar, desc in specs:
        out.append(
            {
                "id": pid,
                "name": name,
                "avatar": avatar,
                "description": desc,
                "enabled": await _provider_enabled_for_api(pid),
                "baseAI": pid,
                "isCustom": False,
            }
        )
    bailian_enabled = await has_provider("bailian")
    for spec in BAILIAN_MODELS:
        entry = {
            "id": spec.id,
            "name": spec.name,
            "avatar": spec.avatar,
            "description": spec.description,
            "enabled": bailian_enabled,
            "baseAI": spec.id,
            "isCustom": False,
        }
        if spec.supports_reasoning:
            entry["supportsReasoning"] = True
            entry["enableReasoning"] = spec.default_enable_reasoning
        out.append(entry)
    return out


app = FastAPI(title="NEO AI Chatroom API")

# 与 htmlsystm 打通：Docker 内置 http://htmlsystm:8000
HTMLSYSTM_INTERNAL_URL = os.getenv("HTMLSYSTM_INTERNAL_URL", "").strip().rstrip("/")
NEO_INTERNAL_SECRET = (os.getenv("NEO_INTERNAL_SECRET") or "").strip()
NEO_DEV_MODE = os.getenv("NEO_DEV_MODE", "").strip().lower() in ("1", "true", "yes")
HTMLSYSTM_AUTH_TIMEOUT_SEC = float(os.getenv("HTMLSYSTM_AUTH_TIMEOUT_SEC", "45"))


def _user_key_from_user(user: Optional[Dict[str, Any]]) -> str:
    """与 htmlsystm resolve_neo_user_key / auth/check userKey 一致。"""
    if not user:
        return ""
    uk = user.get("userKey") or user.get("user_key")
    if uk is not None and str(uk).strip():
        return str(uk).strip()
    raw = user.get("userid") or user.get("username") or user.get("id")
    return str(raw).strip() if raw is not None else ""


def _can_manage_model_config(user: Optional[Dict[str, Any]]) -> bool:
    """管理组 / 管理员 / 超级管理员可配置 AI 模型密钥。"""
    if not user:
        return False
    if str(user.get("username", "")).lower() == "zzw":
        return True
    roles = user.get("roles") or []
    if isinstance(roles, str):
        roles = [roles]
    return any(r in roles for r in ("management", "admin", "super_admin"))


def _build_points_alias_map(active_users: List[Dict[str, str]]) -> Dict[str, str]:
    """username 等非规范键 -> 排行榜 userKey（钉钉 userid）。"""
    aliases: Dict[str, str] = {}
    for u in active_users:
        canonical = str(u.get("userKey") or "").strip()
        if not canonical:
            continue
        alt = str(u.get("username") or "").strip()
        if alt and alt != canonical:
            aliases[alt] = canonical
    return aliases


def _merge_points_map(
    points_map: Dict[str, Dict[str, float]],
    active_users: List[Dict[str, str]],
) -> Dict[str, Dict[str, float]]:
    """合并曾用 username 记账的积分到规范 userKey。"""
    merged = {k: dict(v) for k, v in points_map.items()}
    for u in active_users:
        canonical = str(u.get("userKey") or "").strip()
        alt = str(u.get("username") or "").strip()
        if not canonical or not alt or alt == canonical:
            continue
        alt_pts = merged.get(alt)
        if not alt_pts:
            continue
        if canonical not in merged:
            merged[canonical] = {"total": 0.0, "month": 0.0}
        merged[canonical]["total"] = round(
            float(merged[canonical]["total"]) + float(alt_pts.get("total", 0)), 1
        )
        merged[canonical]["month"] = round(
            float(merged[canonical]["month"]) + float(alt_pts.get("month", 0)), 1
        )
    return merged


def _get_user_points_merged(
    user_key: str,
    active_users: List[Dict[str, str]],
) -> Dict[str, float]:
    """当前用户积分：规范键 + 历史 username 别名之和。"""
    uk = (user_key or "").strip()
    if not uk:
        return {"total": 0.0, "month": 0.0}
    pts = dict(dashboard_metrics_store.get_user_points(uk))
    for u in active_users:
        if str(u.get("userKey") or "").strip() != uk:
            continue
        alt = str(u.get("username") or "").strip()
        if alt and alt != uk:
            alt_pts = dashboard_metrics_store.get_user_points(alt)
            pts["total"] = round(float(pts.get("total", 0)) + float(alt_pts.get("total", 0)), 1)
            pts["month"] = round(float(pts.get("month", 0)) + float(alt_pts.get("month", 0)), 1)
        break
    return pts


_points_aliases_consolidated = False


def _maybe_consolidate_points_aliases(active_users: List[Dict[str, str]]) -> None:
    """一次性把 point_events 中 username 键改写为 userid（需 MySQL/SQLite 存储）。"""
    global _points_aliases_consolidated
    if _points_aliases_consolidated:
        return
    aliases = _build_points_alias_map(active_users)
    if not aliases:
        _points_aliases_consolidated = True
        return
    consolidate = getattr(dashboard_metrics_store, "consolidate_user_key_aliases", None)
    if not callable(consolidate):
        _points_aliases_consolidated = True
        return
    try:
        n = consolidate(aliases)
        if n:
            print(f"[leaderboard] 已合并历史积分别名 {n} 条 -> 规范 userKey")
    except Exception as e:
        print(f"[leaderboard] 合并积分别名失败（展示层仍会合并）: {e}")
    _points_aliases_consolidated = True


async def _fetch_htmlsystm_active_users() -> List[Dict[str, str]]:
    """从管理系统拉取激活用户（Docker 内网内部接口，不依赖 Cookie 转发）。"""
    if not HTMLSYSTM_INTERNAL_URL:
        return [{"userKey": "dev", "name": "本地开发"}]
    url = f"{HTMLSYSTM_INTERNAL_URL}/api/internal/neo/active-users"
    timeout = aiohttp.ClientTimeout(total=30)
    headers = {"X-Neo-Internal-Secret": NEO_INTERNAL_SECRET}
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, headers=headers) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    print(f"[leaderboard] 内部用户列表 HTTP {resp.status}: {body[:200]}")
                    return []
                data = await resp.json()
                if not data.get("success"):
                    return []
                users = data.get("users") or []
                out: List[Dict[str, str]] = []
                for u in users:
                    if not isinstance(u, dict):
                        continue
                    uk = str(u.get("userKey") or "").strip()
                    if not uk:
                        continue
                    name = str(u.get("name") or uk).strip() or uk
                    username = str(u.get("username") or "").strip()
                    out.append({"userKey": uk, "name": name, "username": username})
                return out
    except Exception as e:
        print(f"[leaderboard] 拉取激活用户失败: {e}")
        return []


_AUTH_VERIFY_CACHE_TTL_SEC = 10.0
_auth_verify_cache: Dict[str, tuple] = {}
_htmlsystm_http_session: Optional[aiohttp.ClientSession] = None


def _htmlsystm_auth_timeout() -> aiohttp.ClientTimeout:
    return aiohttp.ClientTimeout(
        total=HTMLSYSTM_AUTH_TIMEOUT_SEC,
        connect=min(10.0, HTMLSYSTM_AUTH_TIMEOUT_SEC),
        sock_read=HTMLSYSTM_AUTH_TIMEOUT_SEC,
    )


async def _get_htmlsystm_http_session() -> aiohttp.ClientSession:
    global _htmlsystm_http_session
    if _htmlsystm_http_session is None or _htmlsystm_http_session.closed:
        _htmlsystm_http_session = aiohttp.ClientSession(timeout=_htmlsystm_auth_timeout())
    return _htmlsystm_http_session


async def _verify_htmlsystm_user(cookie_header: str) -> Optional[Dict[str, Any]]:
    """调用管理系统校验 session（优先轻量内网接口）。"""
    if not HTMLSYSTM_INTERNAL_URL:
        if NEO_DEV_MODE:
            return {"id": 0, "username": "dev", "name": "本地开发", "userid": "dev"}
        return None
    cookie_header = cookie_header or ""
    if not cookie_header.strip():
        return None
    cache_key = hashlib.sha256(cookie_header.encode("utf-8", errors="ignore")).hexdigest()
    now = time.monotonic()
    cached = _auth_verify_cache.get(cache_key)
    if cached is not None:
        user_cached, expires_at = cached
        if now < expires_at:
            return user_cached
        _auth_verify_cache.pop(cache_key, None)
    verify_urls = [
        f"{HTMLSYSTM_INTERNAL_URL}/api/internal/neo/verify-session",
        f"{HTMLSYSTM_INTERNAL_URL}/api/auth/check",
    ]
    verify_headers = {"Cookie": cookie_header}
    if NEO_INTERNAL_SECRET:
        verify_headers["X-Neo-Internal-Secret"] = NEO_INTERNAL_SECRET
    session = await _get_htmlsystm_http_session()
    last_err: Optional[Exception] = None
    for url in verify_urls:
        try:
            async with session.get(url, headers=verify_headers) as resp:
                if resp.status != 200:
                    _auth_verify_cache.pop(cache_key, None)
                    body_preview = ""
                    try:
                        body_preview = (await resp.text())[:200]
                    except Exception:
                        pass
                    print(
                        f"[auth] htmlsystm 校验 HTTP {resp.status} ({url})"
                        + (f": {body_preview}" if body_preview else "")
                    )
                    continue
                data = await resp.json()
                if data.get("authenticated") and isinstance(data.get("user"), dict):
                    user = data["user"]
                    _auth_verify_cache[cache_key] = (user, now + _AUTH_VERIFY_CACHE_TTL_SEC)
                    if len(_auth_verify_cache) > 512:
                        _auth_verify_cache.clear()
                    return user
                _auth_verify_cache.pop(cache_key, None)
                return None
        except Exception as e:
            last_err = e
            continue
    if last_err is not None:
        err_label = type(last_err).__name__
        err_msg = str(last_err).strip()
        if err_msg:
            print(f"[auth] htmlsystm 校验失败 ({err_label}): {err_msg}")
        else:
            print(f"[auth] htmlsystm 校验失败 ({err_label})")
    return None


@app.middleware("http")
async def _htmlsystm_auth_middleware(request: Request, call_next):
    if request.method == "OPTIONS":
        return await call_next(request)
    path = request.url.path
    if not path.startswith("/api/"):
        return await call_next(request)
    # 由路由自行校验 Cookie，避免未登录时整页无法拉取「当前用户」展示
    if path in ("/api/auth/me", "/api/internal/points-event", "/api/health/live"):
        return await call_next(request)
    if not HTMLSYSTM_INTERNAL_URL:
        if NEO_DEV_MODE:
            return await call_next(request)
        return JSONResponse(
            {"detail": "服务未配置身份校验，请设置 HTMLSYSTM_INTERNAL_URL"},
            status_code=503,
        )
    cookie_header = request.headers.get("cookie", "")
    user = await _verify_htmlsystm_user(cookie_header)
    if not user:
        return JSONResponse(
            {"detail": "未登录或会话已失效，请先登录管理系统"},
            status_code=401,
        )
    request.state.htmlsystm_user = user
    return await call_next(request)

# CORS：同源 + PUBLIC_BASE_URL 白名单（禁止 * + credentials）
def _neo_cors_origins() -> list:
    origins = []
    public_base = (os.getenv("PUBLIC_BASE_URL") or "").strip().rstrip("/")
    if public_base:
        origins.append(public_base)
        if public_base.startswith("https://"):
            origins.append("http://" + public_base[8:])
        elif public_base.startswith("http://"):
            origins.append("https://" + public_base[7:])
    return origins


app.add_middleware(
    CORSMiddleware,
    allow_origins=_neo_cors_origins() or ["http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-CSRF-Token"],
)

# 初始化管理器
manager = ConnectionManager()
message_store = MessageStore(db_path=CHATROOM_DB_PATH)
init_ai_key_resolver(message_store, _chatroom_data)
ai_manager = AIAdapterManager()
vector_store = None
if VECTOR_STORE_AVAILABLE:
    try:
        vector_store = VectorStore()
    except Exception as e:
        print(f"警告: 向量存储初始化失败，已禁用: {e}")
        VECTOR_STORE_AVAILABLE = False
memory_item_store = MemoryItemStore(db_path=CHATROOM_DB_PATH)
try:
    vector_memory_backend = create_vector_memory_backend()
except Exception as e:
    print(f"警告: 记忆向量后端初始化失败: {e}")
    vector_memory_backend = None
memory_service = MemoryService(memory_item_store, vector_memory_backend)
context_optimizer = ContextOptimizer()  # 上下文优化器
response_cache = ResponseCache(ttl_minutes=60, max_entries=1000)  # 响应缓存

# 角色知识库缓存
role_knowledge_bases = {}  # {role_id: KnowledgeBase}
role_knowledge_bases_lock = threading.Lock()


def _ensure_role_knowledge_base(full_role_id: str):
    with role_knowledge_bases_lock:
        if full_role_id not in role_knowledge_bases:
            role_knowledge_bases[full_role_id] = _make_knowledge_base(
                full_role_id,
                VECTOR_STORE_AVAILABLE,
            )
        return role_knowledge_bases[full_role_id]


def _get_role_knowledge_base_optional(full_role_id: str):
    with role_knowledge_bases_lock:
        return role_knowledge_bases.get(full_role_id)


def _remove_role_knowledge_base(full_role_id: str) -> None:
    with role_knowledge_bases_lock:
        role_knowledge_bases.pop(full_role_id, None)


def _ensure_babata_knowledge_base():
    with role_knowledge_bases_lock:
        if "babata" not in role_knowledge_bases:
            role_knowledge_bases["babata"] = _make_knowledge_base("babata", False)
        return role_knowledge_bases.get("babata")


context_optimizer = ContextOptimizer()  # 上下文优化器
response_cache = ResponseCache(ttl_minutes=60, max_entries=1000)  # 响应缓存
babata_processor = BabataProcessor()  # 巴巴塔处理器
netlist_result_store = NetlistResultStore(storage_dir=NETLIST_RESULTS_DIR)  # 网表结果存储
dashboard_metrics_store, dashboard_metrics_storage_kind = create_dashboard_metrics_store(
    DASHBOARD_METRICS_DB_PATH
)


@app.on_event("startup")
async def _startup_layered_memory():
    try:
        await memory_item_store.init_db()
        init_extract_queue(int(os.getenv("MEMORY_EXTRACT_QUEUE_SIZE", "500")))
        asyncio.create_task(
            run_memory_extract_worker(message_store, memory_item_store, memory_service)
        )
        print("[memory] 分层记忆：表已初始化，抽取 worker 已启动")
    except Exception as e:
        print(f"[memory] 启动分层记忆失败（服务仍可运行）: {e}", exc_info=True)


@app.on_event("shutdown")
async def _shutdown_htmlsystm_http_session():
    global _htmlsystm_http_session
    if _htmlsystm_http_session is not None and not _htmlsystm_http_session.closed:
        await _htmlsystm_http_session.close()
    _htmlsystm_http_session = None


@app.get("/api/auth/me")
async def auth_me(request: Request) -> Dict[str, Any]:
    """供 NEO 前端展示当前用户，与管理系统 /api/auth/check 一致（携带 session_id）。"""
    if not HTMLSYSTM_INTERNAL_URL:
        return {
            "authenticated": True,
            "user": {"id": 0, "username": "dev", "name": "本地开发", "nickname": ""},
        }
    cookie_header = request.headers.get("cookie", "")
    user = await _verify_htmlsystm_user(cookie_header)
    if not user:
        return {"authenticated": False, "user": None}
    return {"authenticated": True, "user": user}


@app.api_route(
    "/api/material-db/{subpath:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
)
async def proxy_material_db_to_htmlsystm(subpath: str, request: Request):
    """
    物料库 / 替换对 API 由 htmlsystm 提供（MySQL）。
    仅部署 NEO 或 /api 误指向本服务时，转发到 HTMLSYSTM_INTERNAL_URL。
    """
    if not HTMLSYSTM_INTERNAL_URL:
        return JSONResponse(
            {
                "success": False,
                "error": "物料库与替换对需连接管理系统，请使用根目录统一部署或配置 HTMLSYSTM_INTERNAL_URL",
            },
            status_code=503,
        )
    target = f"{HTMLSYSTM_INTERNAL_URL}/api/material-db/{subpath}"
    if request.url.query:
        target = f"{target}?{request.url.query}"
    body = await request.body()
    fwd: Dict[str, str] = {}
    cookie = request.headers.get("cookie")
    if cookie:
        fwd["Cookie"] = cookie
    content_type = request.headers.get("content-type")
    if content_type:
        fwd["Content-Type"] = content_type
    unlock = request.headers.get("x-material-unlock-token")
    if unlock:
        fwd["X-Material-Unlock-Token"] = unlock
    timeout = aiohttp.ClientTimeout(total=120)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.request(
                request.method,
                target,
                data=body if body else None,
                headers=fwd,
                allow_redirects=False,
            ) as resp:
                raw = await resp.read()
                out_headers: Dict[str, str] = {}
                resp_ct = resp.headers.get("Content-Type")
                if resp_ct:
                    out_headers["Content-Type"] = resp_ct
                return Response(content=raw, status_code=resp.status, headers=out_headers)
    except Exception as e:
        print(f"[material-db proxy] 转发失败: {e}")
        return JSONResponse(
            {"success": False, "error": f"无法连接管理系统: {e}"},
            status_code=502,
        )


async def stream_deepseek_response(
    websocket: WebSocket,
    ai_id: str,
    message_id: str,
    user_message: str,
    optimized_history: list,
    enhanced_system_prompt: Optional[str],
    enable_reasoning: bool,
    max_tokens: int = None,
) -> str:
    """
    使用 DeepSeek 流式输出，将思考过程和回答边生成边通过 WebSocket 推送给前端。
    参考 OpenAI SDK 流式用法：stream=True 时 create 返回异步生成器，需 async for 迭代。
    """
    api_key = (await get_secret_async("deepseek") or "").strip()
    if not api_key:
        raise ValueError(
            "DeepSeek API Key 未配置。请在 AI 工作室「API 密钥」中保存，"
            "或在服务器环境变量 DEEPSEEK_API_KEY 中设置。"
        )

    _raw_base = (os.getenv("DEEPSEEK_BASE_URL") or "").strip().rstrip("/")
    deepseek_base = _raw_base if _raw_base else "https://api.deepseek.com"

    # 构造 messages（与 DeepSeekAdapter 逻辑保持一致）
    messages = []
    if enhanced_system_prompt:
        messages.append({"role": "system", "content": enhanced_system_prompt})

    for h in optimized_history:
        role = h.get("role")
        content = h.get("content", "")
        if role in ("user", "assistant"):
            messages.append({"role": role, "content": content})

    messages.append({"role": "user", "content": user_message})

    thinking_text = ""
    answer_text = ""
    finish_reason = None
    print(f"[DeepSeek 流式] 开始处理 ai_id={ai_id} message_id={message_id}")

    # 使用 OpenAI 兼容的 AsyncOpenAI 客户端（DeepSeek API 兼容 OpenAI 格式）
    client = AsyncOpenAI(
        api_key=api_key,
        base_url=deepseek_base or "https://api.deepseek.com",
    )

    # DeepSeek 接口对 max_tokens 有严格上限；超出会直接 400
    DEEPSEEK_MAX_TOKENS = 8192
    safe_max_tokens = max_tokens if isinstance(max_tokens, int) and max_tokens > 0 else DEEPSEEK_MAX_TOKENS
    if safe_max_tokens > DEEPSEEK_MAX_TOKENS:
        print(f"[DeepSeek 流式] max_tokens={safe_max_tokens} 超出上限，已自动降到 {DEEPSEEK_MAX_TOKENS}")
        safe_max_tokens = DEEPSEEK_MAX_TOKENS

    request_params = {
        "model": "deepseek-reasoner" if enable_reasoning else "deepseek-chat",
        "messages": messages,
        "stream": True,
        "max_tokens": safe_max_tokens,  # DeepSeek 最大 8192
    }
    if not enable_reasoning:
        request_params["temperature"] = 0.7

    # 关键：await create 得到流对象，再 async for 迭代（参考 OpenAI 官方示例）
    try:
        stream = await client.chat.completions.create(**request_params)
    except Exception as e:
        err = str(e).strip() or repr(e)
        print(f"[DeepSeek 流式] API 请求失败: {err}")
        raise ValueError(f"DeepSeek API 不可用: {err}") from e

    async for chunk in stream:
        if not chunk.choices:
            continue
        fr = getattr(chunk.choices[0], "finish_reason", None)
        if fr:
            finish_reason = fr
        delta = chunk.choices[0].delta
        if delta is None:
            continue
        # 思考过程（deepseek-reasoner 模型），OpenAI SDK 的 delta 为对象
        reasoning_part = getattr(delta, "reasoning_content", None)
        if reasoning_part:
            thinking_text += reasoning_part
        # 正式回答内容
        content_part = getattr(delta, "content", None)
        if content_part:
            answer_text += content_part

        if not thinking_text and not answer_text:
            continue

        full_content = ""
        if thinking_text:
            full_content += f"💭 **思考过程：**\n{thinking_text}\n\n"
        full_content += f"**最终回答：**\n{answer_text}"

        await websocket.send_json({
            "type": "ai_stream",
            "ai_model": ai_id,
            "message_id": message_id,
            "content": full_content,
            "timestamp": datetime.now().isoformat()
        })

    full = ""
    if thinking_text:
        full += f"💭 **思考过程：**\n{thinking_text}\n\n"
    full += f"**最终回答：**\n{answer_text}"
    return full, finish_reason


async def stream_ark_doubao_response(
    websocket: WebSocket,
    ai_id: str,
    message_id: str,
    user_message: str,
    optimized_history: list,
    enhanced_system_prompt: Optional[str],
    max_tokens: int = None,
) -> str:
    """
    火山方舟豆包流式输出（OpenAI 兼容 /chat/completions）。
    多模态可走 responses API；本聊天室文本对话使用 chat.completions。
    """
    api_key = await get_secret_async("doubao")
    if not api_key:
        raise ValueError("豆包 API Key 未配置，请在「API 密钥」中保存或设置 ARK_API_KEY")

    base_url = os.getenv(
        "ARK_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3"
    )
    model = os.getenv("ARK_DOUBAO_MODEL", "doubao-seed-2-0-mini-260215")

    messages = []
    if enhanced_system_prompt:
        messages.append({"role": "system", "content": enhanced_system_prompt})
    for h in optimized_history:
        role = h.get("role")
        content = h.get("content", "")
        if role in ("user", "assistant"):
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": user_message})

    ark_cap = int(os.getenv("ARK_MAX_OUTPUT_TOKENS", "8192"))
    safe_max = max_tokens if isinstance(max_tokens, int) and max_tokens > 0 else ark_cap
    if safe_max > ark_cap:
        print(f"[豆包流式] max_tokens={safe_max} 超出 ARK_MAX_OUTPUT_TOKENS={ark_cap}，已截断")
        safe_max = ark_cap

    client = AsyncOpenAI(api_key=api_key, base_url=base_url)
    stream = await client.chat.completions.create(
        model=model,
        messages=messages,
        stream=True,
        max_tokens=safe_max,
        temperature=0.7,
    )

    answer_text = ""
    finish_reason = None
    async for chunk in stream:
        if not chunk.choices:
            continue
        fr = getattr(chunk.choices[0], "finish_reason", None)
        if fr:
            finish_reason = fr
        delta = chunk.choices[0].delta
        if delta is None:
            continue
        content_part = getattr(delta, "content", None)
        if content_part:
            answer_text += content_part
            await websocket.send_json({
                "type": "ai_stream",
                "ai_model": ai_id,
                "message_id": message_id,
                "content": answer_text,
                "timestamp": datetime.now().isoformat(),
            })

    return answer_text, finish_reason


async def stream_bailian_response(
    websocket: WebSocket,
    ai_id: str,
    message_id: str,
    user_message: str,
    optimized_history: list,
    enhanced_system_prompt: Optional[str],
    enable_reasoning: bool,
    max_tokens: int = None,
) -> str:
    """百炼 DashScope OpenAI 兼容流式输出。"""
    spec = get_bailian_model(ai_id)
    if not spec:
        raise ValueError(f"未知百炼模型: {ai_id}")

    api_key = (await get_secret_async("bailian") or "").strip()
    if not api_key:
        raise ValueError(
            "百炼 API Key 未配置。请在「API 密钥」中保存百炼密钥，"
            "或设置环境变量 DASHSCOPE_API_KEY。"
        )

    base_url = (
        (os.getenv("DASHSCOPE_BASE_URL") or "https://dashscope.aliyuncs.com/compatible-mode/v1")
        .strip()
        .rstrip("/")
    )
    reasoning_effort = (os.getenv("DASHSCOPE_REASONING_EFFORT") or "high").strip() or "high"
    cap = int(os.getenv("BAILIAN_MAX_OUTPUT_TOKENS", str(spec.max_tokens)))
    safe_max = max_tokens if isinstance(max_tokens, int) and max_tokens > 0 else cap
    if safe_max > cap:
        print(f"[百炼流式] max_tokens={safe_max} 超出上限 {cap}，已截断")
        safe_max = cap

    use_reasoning = enable_reasoning
    if spec.supports_reasoning and not enable_reasoning:
        use_reasoning = spec.default_enable_reasoning

    messages = []
    if enhanced_system_prompt:
        messages.append({"role": "system", "content": enhanced_system_prompt})
    for h in optimized_history:
        role = h.get("role")
        content = h.get("content", "")
        if role in ("user", "assistant"):
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": user_message})

    client = AsyncOpenAI(api_key=api_key, base_url=base_url)
    api_model = get_api_model(ai_id)

    request_params: Dict[str, Any] = {
        "model": api_model,
        "messages": messages,
        "stream": True,
        "max_tokens": safe_max,
        "stream_options": {"include_usage": True},
    }
    extra_body: Dict[str, Any] = {}
    if spec.supports_reasoning:
        extra_body["enable_thinking"] = bool(use_reasoning)
        if use_reasoning and spec.use_reasoning_effort:
            extra_body["reasoning_effort"] = reasoning_effort
    if extra_body:
        request_params["extra_body"] = extra_body
    if not (spec.supports_reasoning and use_reasoning):
        request_params["temperature"] = spec.default_temperature

    print(f"[百炼流式] ai_id={ai_id} model={api_model} message_id={message_id}")

    try:
        stream = await client.chat.completions.create(**request_params)
    except Exception as e:
        err = str(e).strip() or repr(e)
        print(f"[百炼流式] API 请求失败: {err}")
        raise ValueError(f"百炼 API 不可用: {err}") from e

    thinking_text = ""
    answer_text = ""
    finish_reason = None
    async for chunk in stream:
        if not chunk.choices:
            continue
        fr = getattr(chunk.choices[0], "finish_reason", None)
        if fr:
            finish_reason = fr
        delta = chunk.choices[0].delta
        if delta is None:
            continue
        reasoning_part = getattr(delta, "reasoning_content", None)
        if reasoning_part:
            thinking_text += reasoning_part
        content_part = getattr(delta, "content", None)
        if content_part:
            answer_text += content_part

        if not thinking_text and not answer_text:
            continue

        full_content = ""
        if thinking_text:
            full_content += f"💭 **思考过程：**\n{thinking_text}\n\n"
        full_content += f"**最终回答：**\n{answer_text}"

        await websocket.send_json({
            "type": "ai_stream",
            "ai_model": ai_id,
            "message_id": message_id,
            "content": full_content,
            "timestamp": datetime.now().isoformat(),
        })

    full = ""
    if thinking_text:
        full += f"💭 **思考过程：**\n{thinking_text}\n\n"
    full += f"**最终回答：**\n{answer_text}"
    return full, finish_reason


@app.get("/")
async def root():
    return {"message": "NEO AI Chatroom API", "status": "running"}


# ===================== 本地文件管理 API =====================

class FileItem(BaseModel):
    name: str
    path: str
    is_dir: bool
    size: int
    modified: float
    description: Optional[str] = None
    keywords: Optional[List[str]] = None


def _normalize_path(raw: str) -> Path:
    """
    统一处理前端传入的路径，避免奇怪的 .. 注入。
    由于这是本机自用工具，这里不限定到单一根目录，但仍做规范化。
    """
    p = Path(raw).expanduser().resolve()
    return p


@app.get("/api/fs/roots")
async def list_roots() -> List[FileItem]:
    """
    返回可用盘符（Windows）或根路径（其他系统）。
    """
    roots: List[FileItem] = []
    if os.name == "nt":
        import string
        for letter in string.ascii_uppercase:
            drive = f"{letter}:\\"
            if os.path.exists(drive):
                try:
                    stat = os.stat(drive)
                    roots.append(FileItem(
                        name=drive,
                        path=drive,
                        is_dir=True,
                        size=getattr(stat, "st_size", 0),
                        modified=stat.st_mtime,
                    ))
                except PermissionError:
                    continue
    else:
        root = Path("/")
        stat = root.stat()
        roots.append(FileItem(
            name="/",
            path=str(root),
            is_dir=True,
            size=getattr(stat, "st_size", 0),
            modified=stat.st_mtime,
            description=None,
            keywords=None,
        ))
    return roots


@app.get("/api/fs/list", response_model=List[FileItem])
async def list_dir(path: Optional[str] = None) -> List[FileItem]:
    """
    列出指定目录下的文件/子目录。
    path 为空时，等价于 /api/fs/roots。
    """
    if not path:
        return await list_roots()

    target = _normalize_path(path)
    if not target.exists():
        raise JSONResponse(status_code=404, content={"detail": "路径不存在"})
    if not target.is_dir():
        raise JSONResponse(status_code=400, content={"detail": "不是目录"})

    items: List[FileItem] = []
    try:
        for entry in target.iterdir():
            try:
                stat = entry.stat()
            except PermissionError:
                continue
            # 读取目录上的元数据（如果存在 .ai_meta.json）
            desc: Optional[str] = None
            kws: Optional[List[str]] = None
            if entry.is_dir():
                meta_file = entry / ".ai_meta.json"
                if meta_file.exists():
                    try:
                        meta = json.loads(meta_file.read_text(encoding="utf-8"))
                        desc = meta.get("description")
                        if isinstance(meta.get("keywords"), list):
                            kws = [str(x) for x in meta["keywords"]]
                    except Exception:
                        pass

            items.append(FileItem(
                name=entry.name,
                path=str(entry),
                is_dir=entry.is_dir(),
                size=getattr(stat, "st_size", 0),
                modified=stat.st_mtime,
                description=desc,
                keywords=kws,
            ))
    except PermissionError:
        raise JSONResponse(status_code=403, content={"detail": "无权限访问该目录"})

    # 目录在前，文件在后，按名称排序
    items.sort(key=lambda x: (not x.is_dir, x.name.lower()))
    return items


class FileWriteRequest(BaseModel):
    path: str
    content: str
    overwrite: bool = True


@app.post("/api/fs/write")
async def write_file(req: FileWriteRequest):
    """
    写入/创建文本文件（UTF-8）。
    """
    target = _normalize_path(req.path)
    if target.exists() and not req.overwrite:
        return JSONResponse(status_code=409, content={"detail": "文件已存在，且未允许覆盖"})

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(req.content, encoding="utf-8")
    except PermissionError:
        return JSONResponse(status_code=403, content={"detail": "无写入权限"})

    return {"success": True}


class FileDeleteRequest(BaseModel):
    path: str


@app.post("/api/fs/delete")
async def delete_file(req: FileDeleteRequest):
    """
    删除单个文件。
    """
    target = _normalize_path(req.path)
    if not target.exists():
        return JSONResponse(status_code=404, content={"detail": "文件不存在"})
    if target.is_dir():
        return JSONResponse(status_code=400, content={"detail": "暂不支持删除目录"})

    try:
        target.unlink()
    except PermissionError:
        return JSONResponse(status_code=403, content={"detail": "无删除权限"})

    return {"success": True}


class FolderCreateRequest(BaseModel):
    parent_path: str
    name: str
    description: Optional[str] = None
    keywords: Optional[List[str]] = None


@app.post("/api/fs/create_folder")
async def create_folder(req: FolderCreateRequest):
    """
    在指定父目录下创建文件夹，并写入描述/关键词元数据（保存在新建目录内的 .ai_meta.json 中）。
    """
    parent = _normalize_path(req.parent_path)
    if not parent.exists() or not parent.is_dir():
        return JSONResponse(status_code=400, content={"detail": "父目录不存在或不是目录"})

    target = parent / req.name
    try:
        target.mkdir(parents=False, exist_ok=False)
    except FileExistsError:
        return JSONResponse(status_code=409, content={"detail": "同名文件或目录已存在"})
    except PermissionError:
        return JSONResponse(status_code=403, content={"detail": "无权限创建目录"})

    # 写入元数据
    meta = {
        "description": req.description or "",
        "keywords": req.keywords or [],
    }
    try:
        meta_path = target / ".ai_meta.json"
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        # 元数据写失败不影响目录创建
        pass

    return {"success": True, "path": str(target)}


class FileIndexEntry(BaseModel):
    id: str
    workspace_path: str
    temp_dir: str
    files: List[str]
    description: str
    keywords: List[str]
    uploaded_at: str
    stored_at: Optional[str] = None
    target_dir: Optional[str] = None


def _get_index_path(workspace_path: str) -> Path:
    ws = _normalize_path(workspace_path)
    return ws / ".ai_workspace_index.json"


def _load_index(workspace_path: str) -> List[Dict[str, Any]]:
    index_path = _get_index_path(workspace_path)
    if not index_path.exists():
        return []
    try:
        data = json.loads(index_path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
    except Exception:
        return []
    return []


def _save_index(workspace_path: str, entries: List[Dict[str, Any]]) -> None:
    index_path = _get_index_path(workspace_path)
    try:
        index_path.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        print(f"[文件索引] 写入失败: {e}")


@app.get("/api/fs/file_index", response_model=List[FileIndexEntry])
async def get_file_index(workspace_path: str):
    """
    获取指定 workspace 下的所有文件索引条目。
    """
    entries = _load_index(workspace_path)
    # 过滤字段，以防文件被手工修改
    cleaned: List[FileIndexEntry] = []
    for e in entries:
        try:
            cleaned.append(FileIndexEntry(**e))
        except Exception:
            continue
    return cleaned


@app.post("/api/fs/file_index/add", response_model=FileIndexEntry)
async def add_file_index(entry: FileIndexEntry):
    """
    新增 / 覆盖一条文件索引记录（前端生成 id 和时间戳，后端仅负责持久化）。
    """
    ws = entry.workspace_path
    entries = _load_index(ws)
    # 若已存在相同 id，则覆盖
    new_list: List[Dict[str, Any]] = [e for e in entries if e.get("id") != entry.id]
    new_list.append(entry.dict())
    _save_index(ws, new_list)
    return entry


@app.post("/api/fs/upload_temp")
async def upload_temp_files(
    parent_path: str = Form(...),
    files: List[UploadFile] = File(...)
):
    """
    将上传的文件保存到指定 workspace 目录下的临时子目录（.ai_workspace_tmp）。
    """
    base_dir = _normalize_path(parent_path)
    if not base_dir.exists() or not base_dir.is_dir():
        return JSONResponse(status_code=400, content={"detail": "workspace 路径不存在或不是目录"})

    temp_dir = base_dir / ".ai_workspace_tmp"
    try:
        temp_dir.mkdir(parents=True, exist_ok=True)
    except PermissionError:
        return JSONResponse(status_code=403, content={"detail": "无权限创建临时目录"})

    saved_files: List[str] = []
    for f in files:
        try:
            target = temp_dir / f.filename
            content = await f.read()
            with open(target, "wb") as out:
                out.write(content)
            saved_files.append(str(target))
        except PermissionError:
            return JSONResponse(status_code=403, content={"detail": f"写入文件失败: {f.filename}"})

    return {"success": True, "saved": saved_files, "workspace_temp": str(temp_dir)}


@app.get("/api/fs/download")
async def download_file(path: str):
    """
    以下载形式返回指定路径的文件（用于前端“打开文件”）。
    """
    target = _normalize_path(path)
    if not target.exists() or not target.is_file():
        return JSONResponse(status_code=404, content={"detail": "文件不存在"})
    try:
        return FileResponse(str(target), filename=target.name)
    except PermissionError:
        return JSONResponse(status_code=403, content={"detail": "无权限读取该文件"})


@app.get("/api/ais")
async def get_available_ais():
    """获取可用的AI列表（包括自定义角色和巴巴塔）"""
    # 获取管理员配置
    admin_config = await message_store.get_admin_config()
    admin_name = admin_config.get("admin_name", "巴巴塔")
    admin_enabled = admin_config.get("enabled", 1)
    
    babata_entry = {
        "id": "babata",
        "name": admin_name,
        "avatar": "🤖",
        "description": "智能秘书助手，负责预处理和任务管理",
        "enabled": bool(admin_enabled),
        "baseAI": "babata",
        "isCustom": False,
        "isAdmin": True,
    }
    base_ais = [babata_entry] + await _build_llm_provider_catalog()
    
    # 获取自定义AI角色
    custom_roles = await message_store.get_custom_ai_roles()
    custom_ais = []
    for role in custom_roles:
        custom_ais.append({
            "id": f"custom-{role['base_ai']}-{role['id']}",
            "name": role['name'],
            "avatar": role['avatar'],
            "description": role.get('description', ''),
            "enabled": await has_provider(role["base_ai"]),
            "baseAI": role['base_ai'],
            "rolePrompt": role['role_prompt'],
            "isCustom": True,
        })
    
    return {
        "ais": base_ais + custom_ais
    }


@app.get("/api/settings/ai-keys")
async def get_ai_keys_settings(request: Request):
    """列出各 AI 密钥配置状态（仅掩码，不返回明文）。"""
    user = getattr(request.state, "htmlsystm_user", None)
    if not _can_manage_model_config(user):
        return JSONResponse(
            status_code=403,
            content={"success": False, "error": "仅管理组可配置模型"},
        )
    providers = await list_providers_status()
    return {"success": True, "providers": providers}


@app.put("/api/settings/ai-keys/{provider_id}")
async def put_ai_key_setting(provider_id: str, request: Request):
    """保存 API Key（加密入库，响应不含明文）。"""
    user = getattr(request.state, "htmlsystm_user", None)
    if not _can_manage_model_config(user):
        return JSONResponse(
            status_code=403,
            content={"success": False, "error": "仅管理组可配置模型"},
        )
    if not get_provider(provider_id):
        return JSONResponse(status_code=400, content={"success": False, "error": "未知的服务商"})
    data = await request.json()
    api_key = (data.get("api_key") or "").strip()
    if not api_key:
        return JSONResponse(status_code=400, content={"success": False, "error": "请填写 API Key"})
    try:
        await save_provider_secret(provider_id, api_key)
    except ValueError as e:
        return JSONResponse(status_code=400, content={"success": False, "error": str(e)})
    except Exception as e:
        print(f"[ai-keys] 保存失败: {e}")
        return JSONResponse(status_code=500, content={"success": False, "error": "保存失败"})
    providers = await list_providers_status()
    row = next((p for p in providers if p["id"] == provider_id), None)
    return {"success": True, "provider": row}


@app.delete("/api/settings/ai-keys/{provider_id}")
async def delete_ai_key_setting(provider_id: str, request: Request):
    """删除加密库中的 Key（仍可使用环境变量）。"""
    user = getattr(request.state, "htmlsystm_user", None)
    if not _can_manage_model_config(user):
        return JSONResponse(
            status_code=403,
            content={"success": False, "error": "仅管理组可配置模型"},
        )
    if not get_provider(provider_id):
        return JSONResponse(status_code=400, content={"success": False, "error": "未知的服务商"})
    await delete_provider_secret(provider_id)
    providers = await list_providers_status()
    row = next((p for p in providers if p["id"] == provider_id), None)
    return {"success": True, "provider": row}


@app.get("/api/settings/schematic-review-prompt")
async def get_schematic_review_prompt_setting(request: Request):
    """获取原理图评审提示词（普通用户只读；管理员可见历史）。"""
    from backend.services.schematic_review_prompt import get_prompt_payload

    user = getattr(request.state, "htmlsystm_user", None)
    if not user:
        return JSONResponse(status_code=401, content={"success": False, "error": "未登录"})
    return await get_prompt_payload(message_store, user)


@app.put("/api/settings/schematic-review-prompt")
async def put_schematic_review_prompt_setting(request: Request):
    """保存原理图评审提示词（管理员），自动写入历史备份。"""
    from backend.services.schematic_review_prompt import save_prompt

    user = getattr(request.state, "htmlsystm_user", None)
    if not _can_manage_model_config(user):
        return JSONResponse(
            status_code=403,
            content={"success": False, "error": "仅管理组可配置评审提示词"},
        )
    data = await request.json()
    prompt = (data.get("prompt") or "").strip()
    note = (data.get("note") or "").strip()
    default_ai_id = data.get("default_ai_id")
    if not prompt:
        return JSONResponse(status_code=400, content={"success": False, "error": "提示词不能为空"})
    try:
        return await save_prompt(message_store, user, prompt, note, default_ai_id=default_ai_id)
    except ValueError as e:
        return JSONResponse(status_code=400, content={"success": False, "error": str(e)})
    except Exception as e:
        print(f"[schematic-prompt] 保存失败: {e}")
        return JSONResponse(status_code=500, content={"success": False, "error": "保存失败"})


@app.post("/api/settings/schematic-review-prompt/restore/{history_id}")
async def restore_schematic_review_prompt_setting(history_id: str, request: Request):
    """恢复历史提示词版本（管理员）。"""
    from backend.services.schematic_review_prompt import restore_prompt

    user = getattr(request.state, "htmlsystm_user", None)
    if not _can_manage_model_config(user):
        return JSONResponse(
            status_code=403,
            content={"success": False, "error": "仅管理组可配置评审提示词"},
        )
    try:
        return await restore_prompt(message_store, user, history_id)
    except ValueError as e:
        return JSONResponse(status_code=404, content={"success": False, "error": str(e)})
    except Exception as e:
        print(f"[schematic-prompt] 恢复失败: {e}")
        return JSONResponse(status_code=500, content={"success": False, "error": "恢复失败"})


@app.get("/api/schematic-review/history")
async def list_schematic_review_history(request: Request):
    """当前用户的原理图 AI 审核历史列表。"""
    user = getattr(request.state, "htmlsystm_user", None)
    uk = _user_key_from_user(user)
    if not uk:
        return JSONResponse(status_code=401, content={"success": False, "error": "未登录"})
    rows = await message_store.list_schematic_review_history(uk, limit=50)
    return {"success": True, "records": rows}


@app.get("/api/schematic-review/history/{history_id}")
async def get_schematic_review_history_item(history_id: str, request: Request):
    """获取单条原理图 AI 审核历史详情。"""
    user = getattr(request.state, "htmlsystm_user", None)
    uk = _user_key_from_user(user)
    if not uk:
        return JSONResponse(status_code=401, content={"success": False, "error": "未登录"})
    row = await message_store.get_schematic_review_history(history_id, uk)
    if not row:
        return JSONResponse(status_code=404, content={"success": False, "error": "记录不存在"})
    return {"success": True, "record": row}


@app.post("/api/schematic-review/history")
async def create_schematic_review_history(request: Request):
    """保存原理图 AI 审核历史（通常在导出报告后）。"""
    from backend.services.schematic_review_history import serialize_review_payload

    user = getattr(request.state, "htmlsystm_user", None)
    uk = _user_key_from_user(user)
    if not uk:
        return JSONResponse(status_code=401, content={"success": False, "error": "未登录"})
    data = await request.json()
    title = (data.get("title") or data.get("netlist_name") or "原理图审核").strip()
    netlist_result_id = (data.get("netlist_result_id") or "").strip() or None
    summary = data.get("summary") or {}
    payload = serialize_review_payload(
        aggregated_review_summary=data.get("aggregated_review_summary"),
        ai_review_entries=data.get("ai_review_entries") or [],
        cleaned_netlist_text=data.get("cleaned_netlist_text") or "",
        check_dispositions=data.get("check_dispositions") or {},
        default_ai_name=data.get("default_ai_name") or "",
        netlist_name=data.get("netlist_name") or title,
    )
    if not payload.get("aggregated_review_summary"):
        return JSONResponse(
            status_code=400, content={"success": False, "error": "缺少评审结果，无法保存历史"}
        )
    try:
        row = await message_store.save_schematic_review_history(
            user_key=uk,
            title=title,
            netlist_result_id=netlist_result_id,
            summary_pass=int(summary.get("pass") or 0),
            summary_warning=int(summary.get("warning") or 0),
            summary_info=int(summary.get("info") or 0),
            payload=payload,
        )
        return {"success": True, "record": row}
    except ValueError as e:
        return JSONResponse(status_code=400, content={"success": False, "error": str(e)})
    except Exception as e:
        print(f"[schematic-history] 保存失败: {e}")
        return JSONResponse(status_code=500, content={"success": False, "error": "保存失败"})


class MemoryTemplateCreate(BaseModel):
    id: str
    kind: str
    name: str
    json_schema: str
    prompt_hint: str = ""
    version: int = 1
    enabled: bool = True


class RecallStrategyBody(BaseModel):
    steps: List[RecallStep]
    max_total: int = 8


@app.get("/api/memory/templates")
async def api_memory_list_templates():
    """分层记忆：列出抽取模板（含禁用项）。"""
    return {"templates": await memory_item_store.list_templates(enabled_only=False)}


@app.post("/api/memory/templates")
async def api_memory_upsert_template(tpl: MemoryTemplateCreate):
    """创建或更新记忆抽取模板。"""
    await memory_item_store.upsert_template(
        template_id=tpl.id,
        kind=tpl.kind,
        name=tpl.name,
        json_schema=tpl.json_schema,
        prompt_hint=tpl.prompt_hint,
        version=tpl.version,
        enabled=tpl.enabled,
    )
    return {"success": True}


@app.get("/api/memory/recall-strategy")
async def api_memory_get_recall_strategy():
    st = await memory_item_store.get_recall_strategy()
    return {"strategy": st.model_dump()}


@app.put("/api/memory/recall-strategy")
async def api_memory_put_recall_strategy(body: RecallStrategyBody):
    st = RecallStrategy(steps=body.steps, max_total=body.max_total)
    await memory_item_store.set_recall_strategy(st)
    return {"success": True}


@app.post("/api/custom-ai")
async def create_custom_ai(request: Request):
    """创建自定义AI角色"""
    try:
        data = await request.json()
        print(f"[创建角色] 收到请求数据: {data}")
        
        # 验证必需字段
        if not data.get("name"):
            return JSONResponse(
                status_code=400,
                content={"success": False, "error": "角色名称不能为空"}
            )
        
        if not data.get("baseAI"):
            return JSONResponse(
                status_code=400,
                content={"success": False, "error": "基础AI不能为空"}
            )
        
        if not data.get("rolePrompt"):
            return JSONResponse(
                status_code=400,
                content={"success": False, "error": "角色设定不能为空"}
            )
        
        role_id = str(uuid.uuid4())
        
        # 获取角色配置（如果有）
        role_config = data.get("roleConfig")
        
        print(f"[创建角色] 准备保存，角色ID: {role_id}")
        
        await message_store.save_custom_ai_role(
            role_id=role_id,
            name=data.get("name"),
            avatar=data.get("avatar", "🤖"),
            base_ai=data.get("baseAI"),
            role_prompt=data.get("rolePrompt", ""),
            description=data.get("description", ""),
            role_config=role_config
        )
        
        print(f"[创建角色] 保存成功，角色ID: {role_id}")
        
        return {"success": True, "id": role_id}
    
    except Exception as e:
        print(f"[创建角色] 错误: {e}")
        import traceback
        traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": str(e)}
        )


@app.delete("/api/custom-ai/{role_id}")
async def delete_custom_ai(role_id: str):
    """删除自定义AI角色，并将知识库移动到回收站"""
    import shutil
    from pathlib import Path
    
    # 获取角色信息
    custom_roles = await message_store.get_custom_ai_roles()
    role_info = None
    for role in custom_roles:
        if role['id'] == role_id:
            role_info = role
            break
    
    # 删除角色
    await message_store.delete_custom_ai_role(role_id)
    
    # 清理知识库缓存
    full_role_id = f"custom-{role_id}"
    _remove_role_knowledge_base(full_role_id)
    
    # 将知识库移动到回收站
    recycle_bin_dir = Path("./knowledge_recycle_bin")
    recycle_bin_dir.mkdir(exist_ok=True)
    
    knowledge_base_dir = Path("./knowledge_bases")
    full_role_id_for_path = full_role_id
    
    # 检查并移动简单知识库文件
    simple_kb_file = knowledge_base_dir / f"{full_role_id_for_path}_knowledge.json"
    if simple_kb_file.exists():
        knowledge_id = str(uuid.uuid4())
        recycle_path = recycle_bin_dir / f"{knowledge_id}_knowledge.json"
        shutil.move(str(simple_kb_file), str(recycle_path))
        
        await message_store.add_to_recycle_bin(
            knowledge_id=knowledge_id,
            original_role_id=role_id,
            original_role_name=role_info['name'] if role_info else f"角色-{role_id}",
            knowledge_type="simple",
            knowledge_path=str(recycle_path)
        )
    
    # 检查并移动向量知识库目录
    vector_kb_dir = knowledge_base_dir / full_role_id_for_path
    if vector_kb_dir.exists() and vector_kb_dir.is_dir():
        knowledge_id = str(uuid.uuid4())
        recycle_path = recycle_bin_dir / f"{knowledge_id}_vector"
        shutil.move(str(vector_kb_dir), str(recycle_path))
        
        await message_store.add_to_recycle_bin(
            knowledge_id=knowledge_id,
            original_role_id=role_id,
            original_role_name=role_info['name'] if role_info else f"角色-{role_id}",
            knowledge_type="vector",
            knowledge_path=str(recycle_path)
        )
    
    return {"success": True}


@app.post("/api/custom-ai/{role_id}/knowledge")
async def add_knowledge_to_role(role_id: str, request: Request):
    """为角色添加知识（支持图片）"""
    data = await request.json()
    text = data.get("text", "")
    metadata = data.get("metadata", {})
    image_data = data.get("image_data", None)  # Base64编码的图片
    image_path = data.get("image_path", None)  # 图片文件路径
    image_type = data.get("image_type", None)  # 图片类型（如 image/png, image/jpeg）
    event_config = data.get("event_config", None)  # 事件配置
    
    if not text:
        return {"success": False, "error": "知识内容不能为空"}
    
    # 处理巴巴塔的知识库
    if role_id == "babata":
        full_role_id = "babata"
    else:
        full_role_id = f"custom-{role_id}"
    
    knowledge_base = _ensure_role_knowledge_base(full_role_id)
    
    # 如果知识库支持图片参数，传递图片信息
    if hasattr(knowledge_base, 'add_knowledge'):
        # 检查方法签名是否支持图片和事件配置参数
        import inspect
        sig = inspect.signature(knowledge_base.add_knowledge)
        if 'event_config' in sig.parameters:
            success = knowledge_base.add_knowledge(text, metadata, image_data, image_path, image_type, event_config)
        elif 'image_data' in sig.parameters:
            success = knowledge_base.add_knowledge(text, metadata, image_data, image_path, image_type)
        else:
            success = knowledge_base.add_knowledge(text, metadata)
    else:
        success = False
    
    return {"success": success}


@app.get("/api/custom-ai/{role_id}/knowledge")
async def search_role_knowledge(role_id: str, query: str = "", top_k: int = 100):
    """搜索角色知识库（如果query为空，返回所有知识，支持巴巴塔）"""
    # 处理巴巴塔的知识库
    if role_id == "babata":
        full_role_id = "babata"
    else:
        full_role_id = f"custom-{role_id}"
    
    try:
        knowledge_base = _ensure_role_knowledge_base(full_role_id)
    except Exception:
        return {"results": []}
    
    # 如果query为空，尝试获取所有知识（简单知识库支持）
    if not query or query.strip() == "":
        # 对于简单知识库，可以返回所有知识
        if hasattr(knowledge_base, 'knowledge_chunks'):
            # 重新加载知识库（确保获取最新内容）
            knowledge_base._load_knowledge()
            # 返回问答对和知识片段
            qa_pairs = []
            if hasattr(knowledge_base, 'qa_pairs'):
                qa_pairs = knowledge_base.qa_pairs
            knowledge_chunks = knowledge_base.knowledge_chunks if hasattr(knowledge_base, 'knowledge_chunks') else []
            
            return {
                "query": "",
                "results": [chunk.get("text", "") for chunk in knowledge_chunks if chunk.get("text")],
                "qa_pairs": qa_pairs,  # 返回完整的问答对信息
                "knowledge_chunks": knowledge_chunks  # 返回完整的知识片段信息
            }
        else:
            # 向量知识库，使用空查询或返回空
            return {"results": []}
    
    # 正常搜索
    # 如果是简单知识库，确保已加载最新内容
    if hasattr(knowledge_base, '_load_knowledge'):
        knowledge_base._load_knowledge()
    
    results = knowledge_base.retrieve(query, top_k=top_k)
    
    # 如果返回的是字符串，按换行分割；如果是列表，直接使用
    if isinstance(results, str):
        result_list = results.split("\n") if results else []
    elif isinstance(results, list):
        result_list = results
    else:
        result_list = []
    
    return {
        "query": query,
        "results": result_list
    }


@app.get("/api/conversations")
async def get_conversations():
    """获取所有对话列表"""
    try:
        conversations = await message_store.get_conversations()
        return {"success": True, "conversations": conversations}
    except Exception as e:
        print(f"获取对话列表失败: {e}")
        import traceback
        traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": str(e)}
        )


@app.get("/api/conversations/{conversation_id}/messages")
async def get_conversation_messages(conversation_id: str):
    """获取指定对话的所有消息"""
    try:
        messages = await message_store.get_group_conversation_messages(conversation_id)
        return {"success": True, "messages": messages}
    except Exception as e:
        print(f"获取对话消息失败: {e}")
        import traceback
        traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": str(e)}
        )


@app.get("/api/recycle-bin")
async def get_recycle_bin():
    """获取回收站中的所有知识库"""
    items = await message_store.get_recycle_bin_items()
    return {"items": items}


@app.post("/api/recycle-bin/{knowledge_id}/restore")
async def restore_knowledge(request: Request, knowledge_id: str):
    """从回收站恢复知识库到指定角色"""
    import shutil
    from pathlib import Path
    
    data = await request.json()
    target_role_id = data.get("role_id")
    
    if not target_role_id:
        return JSONResponse(
            status_code=400,
            content={"success": False, "error": "目标角色ID不能为空"}
        )
    
    # 获取回收站中的知识库信息
    recycle_items = await message_store.get_recycle_bin_items()
    knowledge_item = None
    for item in recycle_items:
        if item['id'] == knowledge_id:
            knowledge_item = item
            break
    
    if not knowledge_item:
        return JSONResponse(
            status_code=404,
            content={"success": False, "error": "知识库不存在或已被恢复"}
        )
    
    # 移动知识库文件到目标角色
    recycle_bin_dir = Path("./knowledge_recycle_bin")
    knowledge_base_dir = Path("./knowledge_bases")
    knowledge_base_dir.mkdir(exist_ok=True)
    target_full_role_id = f"custom-{target_role_id}"
    
    recycle_path = Path(knowledge_item['knowledge_path'])
    if knowledge_item['knowledge_type'] == 'simple':
        # 简单知识库
        target_path = knowledge_base_dir / f"{target_full_role_id}_knowledge.json"
        if recycle_path.exists():
            # 如果目标文件已存在，先备份（可选：合并而不是覆盖）
            if target_path.exists():
                backup_path = knowledge_base_dir / f"{target_full_role_id}_knowledge_backup_{int(datetime.now().timestamp())}.json"
                shutil.copy2(str(target_path), str(backup_path))
            shutil.move(str(recycle_path), str(target_path))
    elif knowledge_item['knowledge_type'] == 'vector':
        # 向量知识库
        target_path = knowledge_base_dir / target_full_role_id
        if recycle_path.exists():
            # 如果目标目录已存在，先备份
            if target_path.exists():
                backup_path = knowledge_base_dir / f"{target_full_role_id}_backup_{int(datetime.now().timestamp())}"
                shutil.move(str(target_path), str(backup_path))
            shutil.move(str(recycle_path), str(target_path))
    
    # 更新数据库
    await message_store.restore_knowledge_from_recycle_bin(knowledge_id, target_role_id)
    
    # 关联知识库到角色
    await message_store.associate_knowledge_to_role(target_role_id, knowledge_id)
    
    # 清除缓存，强制重新加载
    _remove_role_knowledge_base(target_full_role_id)
    
    return {"success": True}


@app.delete("/api/recycle-bin/{knowledge_id}")
async def permanently_delete_knowledge(knowledge_id: str):
    """从回收站永久删除知识库"""
    import shutil
    from pathlib import Path
    
    # 获取知识库路径并删除
    knowledge_path = await message_store.permanently_delete_from_recycle_bin(knowledge_id)
    
    if knowledge_path:
        path = Path(knowledge_path)
        if path.exists():
            if path.is_file():
                path.unlink()
            elif path.is_dir():
                shutil.rmtree(path)
    
    return {"success": True}


@app.post("/api/netlist/compare")
async def compare_netlists(request: Request):
    """对比两个网表文件"""
    try:
        data = await request.json()
        netlist1_content = data.get("netlist1", "")
        netlist2_content = data.get("netlist2", "")
        netlist1_name = data.get("netlist1_name", "网表1")
        netlist2_name = data.get("netlist2_name", "网表2")
        
        if not netlist1_content or not netlist2_content:
            return JSONResponse(
                status_code=400,
                content={"success": False, "error": "两个网表内容不能为空"}
            )
        
        # 解析网表
        parser = PadsNetlistParser()
        netlist1 = parser.parse(netlist1_content)
        netlist2 = parser.parse(netlist2_content)
        
        # 调试信息
        print(f"[网表对比] 网表1解析结果: {len(netlist1.get('components', {}))} 个元件, {len(netlist1.get('nets', {}))} 个网络")
        print(f"[网表对比] 网表2解析结果: {len(netlist2.get('components', {}))} 个元件, {len(netlist2.get('nets', {}))} 个网络")
        
        # 对比网表
        comparator = NetlistComparator()
        comparison_result = comparator.compare(netlist1, netlist2)
        
        # 调试信息
        print(f"[网表对比] 对比结果: 新增{len(comparison_result.get('added_components', []))}个, 移除{len(comparison_result.get('removed_components', []))}个, 修改{len(comparison_result.get('changed_components', []))}个")
        
        # 保存结果
        result_id = str(uuid.uuid4())
        netlist_result_store.save_comparison_result(
            result_id=result_id,
            comparison_result=comparison_result,
            netlist1_name=netlist1_name,
            netlist2_name=netlist2_name
        )
        
        return {
            "success": True,
            "result_id": result_id,
            "result": comparison_result,
            "message": f"对比完成：新增{len(comparison_result.get('added_components', []))}个元件，移除{len(comparison_result.get('removed_components', []))}个元件"
        }
    except Exception as e:
        print(f"网表对比失败: {e}")
        import traceback
        traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": str(e)}
        )


@app.post("/api/netlist/analyze")
async def analyze_netlist(request: Request):
    """分析单个网表文件"""
    try:
        data = await request.json()
        netlist_content = data.get("netlist", "")
        netlist_name = data.get("netlist_name", "网表")
        
        if not netlist_content:
            return JSONResponse(
                status_code=400,
                content={"success": False, "error": "网表内容不能为空"}
            )
        
        # 分析网表
        analyzer = NetlistAnalyzer()
        analysis_result = analyzer.analyze(netlist_content)
        print(
            f"[网表分析] {netlist_name}: "
            f"{analysis_result['summary'].get('total_components', 0)} 个元件, "
            f"{analysis_result['summary'].get('total_nets', 0)} 个网络"
        )
        
        # 保存结果
        result_id = str(uuid.uuid4())
        netlist_result_store.save_analysis_result(
            result_id=result_id,
            analysis_result=analysis_result,
            netlist_name=netlist_name
        )
        
        return {
            "success": True,
            "result_id": result_id,
            "result": analysis_result,
            "formatted_markdown": _format_analysis_result_for_chat(analysis_result, result_id),
        }
    except Exception as e:
        print(f"网表分析失败: {e}")
        import traceback
        traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": str(e)}
        )


@app.get("/api/netlist/result/{result_id}")
async def get_netlist_result(result_id: str):
    """获取网表分析结果"""
    result = netlist_result_store.load_result(result_id)
    if result:
        payload = {"success": True, "data": result}
        if result.get("type") == "analysis" and result.get("result"):
            payload["formatted_markdown"] = _format_analysis_result_for_chat(
                result["result"], result_id
            )
        return payload
    return JSONResponse(
        status_code=404,
        content={"success": False, "error": "结果不存在"}
    )


@app.get("/api/netlist/results")
async def list_netlist_results(result_type: Optional[str] = None):
    """列出所有网表分析结果"""
    results = netlist_result_store.list_results(result_type=result_type)
    return {"success": True, "results": results}


@app.delete("/api/netlist/result/{result_id}")
async def delete_netlist_result(result_id: str):
    """删除网表分析结果"""
    success = netlist_result_store.delete_result(result_id)
    if success:
        return {"success": True}
    return JSONResponse(
        status_code=404,
        content={"success": False, "error": "结果不存在"}
    )


def _parse_iso_date(s):
    """解析日期字符串，用于看板统计"""
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00")[:19])
    except Exception:
        return None


def _week_bounds_sequence(num_weeks: int = 4):
    """从旧到新，每周 (start, end)，周一至周日。"""
    now = datetime.now()
    week_start = now - timedelta(days=now.weekday())
    week_start = week_start.replace(hour=0, minute=0, second=0, microsecond=0)
    slots = []
    for i in range(num_weeks):
        ws = week_start - timedelta(weeks=(num_weeks - 1 - i))
        we = ws + timedelta(days=7)
        slots.append((ws, we))
    return slots


def _weekly_created_counts(rows: List[Dict[str, Any]], num_weeks: int = 4) -> List[int]:
    counts = []
    for ws, we in _week_bounds_sequence(num_weeks):
        c = 0
        for r in rows:
            dt = _parse_iso_date(r.get("created_at"))
            if dt and ws <= dt < we:
                c += 1
        counts.append(c)
    return counts


def _week_axis_labels(num_weeks: int = 4) -> List[str]:
    return [f"W-{num_weeks - 1 - i}" if i < num_weeks - 1 else "本周" for i in range(num_weeks)]


class DashboardFeatureUseBody(BaseModel):
    feature: str


class DashboardBomInfoBody(BaseModel):
    info_count: int


class DashboardPointsEventBody(BaseModel):
    event: str


class InternalPointsEventBody(BaseModel):
    user_key: str
    event: str


async def _notify_leaderboard_updated() -> None:
    """积分变更后通知已连接的客户端刷新排行榜。"""
    try:
        await manager.broadcast({"type": "leaderboard_updated"})
    except Exception as e:
        print(f"[leaderboard] 广播更新失败: {e}")


@app.post("/api/dashboard/points-event")
async def post_dashboard_points_event(request: Request, body: DashboardPointsEventBody):
    """记录可兑换积分的行为（AI CHECK 导出、对比工具、SOP 完成等）。"""
    user = getattr(request.state, "htmlsystm_user", None)
    uk = _user_key_from_user(user)
    dashboard_metrics_store.record_point_event(body.event.strip(), uk or None)
    active_users = await _fetch_htmlsystm_active_users()
    my = _get_user_points_merged(uk, active_users)
    await _notify_leaderboard_updated()
    return {
        "success": True,
        "myTotalPoints": my["total"],
        "myMonthPoints": my["month"],
    }


@app.post("/api/internal/points-event")
async def internal_points_event(request: Request, body: InternalPointsEventBody):
    """htmlsystm 内网调用：物料库修改等。"""
    if not _allow_neo_internal_request(request):
        return JSONResponse(status_code=403, content={"success": False, "error": "禁止访问"})
    uk = (body.user_key or "").strip()
    if not uk:
        return JSONResponse(status_code=400, content={"success": False, "error": "缺少 user_key"})
    dashboard_metrics_store.record_point_event(body.event.strip(), uk)
    await _notify_leaderboard_updated()
    return {"success": True}


def _allow_neo_internal_request(request: Request) -> bool:
    if not NEO_INTERNAL_SECRET:
        return False
    secret = request.headers.get("x-neo-internal-secret") or request.headers.get(
        "X-Neo-Internal-Secret"
    )
    return secret == NEO_INTERNAL_SECRET


@app.post("/api/dashboard/feature-use")
async def post_dashboard_feature_use(request: Request, body: DashboardFeatureUseBody):
    """记录主页等功能入口点击次数。"""
    user = getattr(request.state, "htmlsystm_user", None)
    dashboard_metrics_store.record_feature_use(
        body.feature.strip()[:128],
        user_key=_user_key_from_user(user) or None,
    )
    return {"success": True}


@app.post("/api/dashboard/bom-info-report")
async def post_dashboard_bom_info(request: Request, body: DashboardBomInfoBody):
    """BOM AI check 面板上报当前 INFO 条数（用于缺陷统计）。"""
    user = getattr(request.state, "htmlsystm_user", None)
    dashboard_metrics_store.record_bom_info_count(
        body.info_count,
        user_key=_user_key_from_user(user) or None,
    )
    return {"success": True}


def _build_leaderboard_payload(
    session_user: Optional[Dict[str, Any]],
    active_users: List[Dict[str, str]],
) -> Dict[str, Any]:
    current_key = _user_key_from_user(session_user)
    if session_user and current_key:
        display = (
            session_user.get("name")
            or session_user.get("nickname")
            or session_user.get("username")
            or current_key
        )
        if not any(u["userKey"] == current_key for u in active_users):
            active_users.append({
                "userKey": current_key,
                "name": str(display).strip() or current_key,
            })

    points_map = _merge_points_map(
        dashboard_metrics_store.user_points_totals(), active_users
    )
    entries: List[Dict[str, Any]] = []
    for u in active_users:
        uk = u["userKey"]
        pts = points_map.get(uk, {"total": 0, "month": 0})
        name = str(u.get("name") or uk)
        total_pts = float(pts.get("total", 0))
        lvl = level_from_points(total_pts)
        entries.append({
            "userKey": uk,
            "name": name,
            "totalPoints": total_pts,
            "monthPoints": float(pts.get("month", 0)),
            "level": lvl["level"],
            "levelTitle": lvl["title"],
            "isSelf": uk == current_key,
        })

    self_entry = next((e for e in entries if e["isSelf"]), None)
    my_pts = _get_user_points_merged(current_key, active_users)
    my_total = float(my_pts.get("total", 0))
    my_month = float(my_pts.get("month", 0))
    if self_entry:
        self_entry["totalPoints"] = my_total
        self_entry["monthPoints"] = my_month
    entries.sort(key=lambda x: (-x["totalPoints"], x["name"]))
    month_sorted = sorted(entries, key=lambda x: (-x["monthPoints"], x["name"]))
    total_rank = next((i + 1 for i, e in enumerate(entries) if e["isSelf"]), 0)
    month_rank = next((i + 1 for i, e in enumerate(month_sorted) if e["isSelf"]), 0)

    now = datetime.now()
    my_level = level_from_points(my_total)
    return {
        "success": True,
        "currentUserKey": current_key,
        "myTotalPoints": my_total,
        "myMonthPoints": my_month,
        "myLevel": my_level["level"],
        "myLevelTitle": my_level["title"],
        "myRankTotal": total_rank,
        "myRankMonth": month_rank,
        "entries": entries,
        "pointsRules": {
            "aiCheckExport": dashboard_metrics_store.POINTS_BY_EVENT.get("ai_check_export", 1.0),
            "materialDbEdit": dashboard_metrics_store.POINTS_BY_EVENT.get("material_db_edit", 1.0),
            "compareTool": dashboard_metrics_store.POINTS_BY_EVENT.get("compare_tool", 0.1),
            "sopComplete": dashboard_metrics_store.POINTS_BY_EVENT.get("sop_complete", 0.5),
            "monthLabel": f"{now.year}年{now.month:02d}月",
        },
    }


@app.get("/api/health/live")
async def health_live() -> Dict[str, Any]:
    """容器存活探针：不鉴权、不依赖 htmlsystm。"""
    return {"ok": True, "service": "neo-backend"}


@app.get("/api/health/persistence")
async def get_persistence_health() -> Dict[str, Any]:
    """数据持久化状态：存储类型、积分事件数、MySQL 连通性。"""
    point_events = 0
    try:
        point_events = int(dashboard_metrics_store.count_point_events())
    except Exception as e:
        return {
            "ok": False,
            "storage": dashboard_metrics_storage_kind,
            "error": str(e),
            "dataDir": str(_chatroom_data),
        }

    mysql_ok: Optional[bool] = None
    if dashboard_metrics_storage_kind == "mysql":
        mysql_ok = True
    elif (os.getenv("MYSQL_HOST") or "").strip():
        try:
            from backend.models.dashboard_metrics_mysql import DashboardMetricsMysqlStore

            DashboardMetricsMysqlStore()._ping()
            mysql_ok = True
        except Exception:
            mysql_ok = False

    degraded = dashboard_metrics_storage_kind != "mysql" and bool(
        (os.getenv("MYSQL_HOST") or "").strip()
    )
    return {
        "ok": not degraded,
        "degraded": degraded,
        "storage": dashboard_metrics_storage_kind,
        "pointEventsCount": point_events,
        "mysqlConfigured": bool((os.getenv("MYSQL_HOST") or "").strip()),
        "mysqlConnected": mysql_ok,
        "dataDir": str(_chatroom_data),
        "chatroomDbExists": Path(CHATROOM_DB_PATH).is_file(),
    }


@app.get("/api/leaderboard/scores")
async def get_leaderboard_scores(request: Request) -> Dict[str, Any]:
    """仅返回各用户积分（供前端在 /api/leaderboard 不可用时拼装）。"""
    session_user = getattr(request.state, "htmlsystm_user", None)
    current_key = _user_key_from_user(session_user)
    active_users = await _fetch_htmlsystm_active_users()
    _maybe_consolidate_points_aliases(active_users)
    points_map = _merge_points_map(
        dashboard_metrics_store.user_points_totals(), active_users
    )
    self_pts = _get_user_points_merged(current_key, active_users)
    return {
        "success": True,
        "currentUserKey": current_key,
        "pointsByUserKey": points_map,
        "myTotalPoints": float(self_pts.get("total", 0)),
        "myMonthPoints": float(self_pts.get("month", 0)),
    }


@app.get("/api/leaderboard")
async def get_leaderboard(request: Request):
    """积分排行榜：与管理系统激活用户对齐，积分来自各用户 NEO 使用行为。"""
    try:
        session_user = getattr(request.state, "htmlsystm_user", None)
        active_users = await _fetch_htmlsystm_active_users()
        _maybe_consolidate_points_aliases(active_users)
        return _build_leaderboard_payload(session_user, active_users)
    except Exception as e:
        print(f"[leaderboard] 处理失败: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": f"排行榜加载失败: {e}"},
        )


@app.get("/api/dashboard/stats")
async def get_dashboard_stats():
    """
    评审效能看板统计数据。
    组件使用次数、BOM INFO 缺陷累计、网表待检查项、按月缺陷密度等。
    """
    try:
        now = datetime.now()
        week_start = now - timedelta(days=now.weekday())
        week_start = week_start.replace(hour=0, minute=0, second=0, microsecond=0)

        all_netlist = netlist_result_store.list_results(result_type=None)
        compare_results = [r for r in all_netlist if r.get("type") == "comparison"]
        analysis_results = [r for r in all_netlist if r.get("type") == "analysis"]
        netlist_compare_total = len(compare_results)
        netlist_analyze_total = len(analysis_results)
        netlist_this_week = sum(
            1 for r in all_netlist
            if _parse_iso_date(r.get("created_at")) and _parse_iso_date(r.get("created_at")) >= week_start
        )

        netlist_need_check_total = 0
        netlist_need_check_this_week = 0
        for r in analysis_results:
            result_payload = r.get("result") or {}
            nchk = count_netlist_need_check_items(result_payload)
            netlist_need_check_total += nchk
            dt = _parse_iso_date(r.get("created_at"))
            if dt and dt >= week_start:
                netlist_need_check_this_week += nchk

        component_use_total = dashboard_metrics_store.total_feature_uses()
        component_use_this_week = dashboard_metrics_store.feature_uses_since(week_start)
        feature_breakdown = dashboard_metrics_store.feature_breakdown()

        w_labels = _week_axis_labels(4)
        w_feat = dashboard_metrics_store.weekly_feature_counts(4)
        weekly_component_use = [{"week_label": w_labels[i], "value": w_feat[i]} for i in range(4)]

        w_net = _weekly_created_counts(all_netlist, 4)
        weekly_netlist_counts = [{"week_label": w_labels[i], "value": w_net[i]} for i in range(4)]

        bom_defect_info_total = dashboard_metrics_store.sum_bom_info_all()
        bom_w = dashboard_metrics_store.weekly_bom_info_sums(4)
        weekly_bom_defect_info = [{"week_label": w_labels[i], "value": bom_w[i]} for i in range(4)]
        bom_defect_info_this_week = dashboard_metrics_store.sum_bom_info_in_range(
            week_start, week_start + timedelta(days=7)
        )

        # 按月缺陷密度：(当月 BOM INFO 上报合计 + 当月新建网表分析的待检查项合计) / 当月组件使用次数
        monthly_defect_density: List[Dict[str, Any]] = []
        y, m = now.year, now.month
        for _ in range(6):
            ms, me = month_range(y, m)
            defects_m = dashboard_metrics_store.sum_bom_info_in_range(ms, me)
            uses_m = dashboard_metrics_store.uses_in_range(ms, me)
            for r in analysis_results:
                dt = _parse_iso_date(r.get("created_at"))
                if dt and ms <= dt < me:
                    defects_m += count_netlist_need_check_items(r.get("result") or {})
            dens = defects_m / max(uses_m, 1)
            monthly_defect_density.append(
                {"label": f"{y}-{m:02d}", "value": round(dens, 4)}
            )
            m -= 1
            if m == 0:
                m = 12
                y -= 1
        monthly_defect_density.reverse()

        cur_ms, cur_me = month_range(now.year, now.month)
        defects_cur = dashboard_metrics_store.sum_bom_info_in_range(cur_ms, cur_me)
        uses_cur = dashboard_metrics_store.uses_in_range(cur_ms, cur_me)
        for r in analysis_results:
            dt = _parse_iso_date(r.get("created_at"))
            if dt and cur_ms <= dt < cur_me:
                defects_cur += count_netlist_need_check_items(r.get("result") or {})
        defect_density = round(defects_cur / max(uses_cur, 1), 4)

        defect_density_trend_pct = None
        if len(monthly_defect_density) >= 2:
            prev_v = monthly_defect_density[-2]["value"]
            cur_v = monthly_defect_density[-1]["value"]
            if prev_v and prev_v > 0:
                defect_density_trend_pct = round((cur_v - prev_v) / prev_v * 100, 2)

        raw_activity = dashboard_metrics_store.list_recent_activity(40)
        active_users = await _fetch_htmlsystm_active_users()
        name_by_key = {u["userKey"]: u["name"] for u in active_users}
        recent_activity: List[Dict[str, Any]] = []
        for item in raw_activity:
            uk = item.get("user_key")
            if uk and uk in name_by_key:
                user_name = name_by_key[uk]
            elif uk:
                user_name = str(uk)
            else:
                user_name = "访客"
            recent_activity.append({
                "kind": item.get("kind"),
                "detail": item.get("detail"),
                "user_key": uk,
                "user_name": user_name,
                "created_at": item.get("created_at"),
            })

        stats = {
            "component_use_total": component_use_total,
            "component_use_this_week": component_use_this_week,
            "weekly_component_use": weekly_component_use,
            "feature_use_breakdown": feature_breakdown,
            "netlist_compare_count": netlist_compare_total,
            "netlist_analyze_count": netlist_analyze_total,
            "netlist_count_this_week": netlist_this_week,
            "weekly_netlist_counts": weekly_netlist_counts,
            "bom_defect_info_total": bom_defect_info_total,
            "bom_defect_info_this_week": bom_defect_info_this_week,
            "weekly_bom_defect_info": weekly_bom_defect_info,
            "netlist_need_check_total": netlist_need_check_total,
            "netlist_need_check_this_week": netlist_need_check_this_week,
            "defect_density": defect_density,
            "defect_density_trend_pct": defect_density_trend_pct,
            "monthly_defect_density": monthly_defect_density,
            "recent_activity": recent_activity,
            "updated_at": now.isoformat(),
        }
        return {"success": True, "stats": stats, "updated_at": stats["updated_at"]}
    except Exception as e:
        print(f"获取看板统计失败: {e}")
        import traceback
        traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": str(e)}
        )


_DASHBOARD_FEATURE_LABELS: Dict[str, str] = {
    "dashboard": "评审效能看板",
    "leaderboard": "积分排行榜",
    "ai_studio": "AI 工作室",
    "netlist_compare": "网表对比",
    "bom_compare": "BOM 对比",
    "bom_check": "BOM AI 检查",
    "report_audit": "测试报告审核",
    "material_db": "物料数据库",
}


def _label_dashboard_feature(feature: str) -> str:
    key = (feature or "").strip()
    if not key:
        return "未知功能"
    if key in _DASHBOARD_FEATURE_LABELS:
        return _DASHBOARD_FEATURE_LABELS[key]
    if key.startswith("sop:"):
        return f"SOP · {key[4:]}"
    return key


async def _dashboard_name_by_key() -> Dict[str, str]:
    active_users = await _fetch_htmlsystm_active_users()
    return {u["userKey"]: u["name"] for u in active_users}


def _dashboard_user_display(user_key: Optional[str], name_by_key: Dict[str, str]) -> str:
    uk = (user_key or "").strip()
    if uk and uk in name_by_key:
        return name_by_key[uk]
    if uk:
        return uk
    return "访客"


@app.get("/api/dashboard/kpi-detail")
async def get_dashboard_kpi_detail(kpi: str):
    """看板 KPI 卡片明细：component_use | netlist | bom | netlist_check | defect_density"""
    try:
        key = (kpi or "").strip()
        name_by_key = await _dashboard_name_by_key()
        now = datetime.now()

        if key == "component_use":
            rows = dashboard_metrics_store.list_feature_uses(80)
            items = [
                {
                    "created_at": r["created_at"],
                    "user_name": _dashboard_user_display(r.get("user_key"), name_by_key),
                    "feature_label": _label_dashboard_feature(r.get("feature", "")),
                }
                for r in rows
            ]
            return {
                "success": True,
                "kpi": key,
                "title": "组件使用记录",
                "subtitle": "不含积分排行榜与看板入口点击",
                "items": items,
            }

        if key == "netlist":
            all_netlist = netlist_result_store.list_results(result_type=None)
            items: List[Dict[str, Any]] = []
            for r in all_netlist[:80]:
                rtype = r.get("type")
                if rtype == "comparison":
                    op = "对比"
                    name = f"{r.get('netlist1_name', '网表1')} · {r.get('netlist2_name', '网表2')}"
                else:
                    op = "分析"
                    name = str(r.get("netlist_name") or "网表")
                items.append({
                    "created_at": r.get("created_at"),
                    "operation": op,
                    "name": name,
                    "result_id": r.get("id"),
                })
            return {
                "success": True,
                "kpi": key,
                "title": "网表操作记录",
                "subtitle": "已保存的对比与分析结果",
                "items": items,
            }

        if key == "bom":
            rows = dashboard_metrics_store.list_bom_snapshots(80)
            items = [
                {
                    "created_at": r["created_at"],
                    "user_name": _dashboard_user_display(r.get("user_key"), name_by_key),
                    "info_count": r["info_count"],
                }
                for r in rows
            ]
            return {
                "success": True,
                "kpi": key,
                "title": "BOM INFO 上报记录",
                "subtitle": "各次 BOM AI check 最终预览上报",
                "items": items,
            }

        if key == "netlist_check":
            analysis_results = netlist_result_store.list_results(result_type="analysis")
            items = []
            for r in analysis_results[:80]:
                payload = r.get("result") or {}
                nchk = count_netlist_need_check_items(payload)
                items.append({
                    "created_at": r.get("created_at"),
                    "netlist_name": str(r.get("netlist_name") or "网表"),
                    "need_check_count": nchk,
                    "result_id": r.get("id"),
                })
            return {
                "success": True,
                "kpi": key,
                "title": "网表待检查项明细",
                "subtitle": "按每条分析结果统计待检查清单项",
                "items": items,
            }

        if key == "defect_density":
            analysis_results = netlist_result_store.list_results(result_type="analysis")
            monthly: List[Dict[str, Any]] = []
            y, m = now.year, now.month
            for _ in range(6):
                ms, me = month_range(y, m)
                defects_m = dashboard_metrics_store.sum_bom_info_in_range(ms, me)
                uses_m = dashboard_metrics_store.uses_in_range(ms, me)
                for r in analysis_results:
                    dt = _parse_iso_date(r.get("created_at"))
                    if dt and ms <= dt < me:
                        defects_m += count_netlist_need_check_items(r.get("result") or {})
                dens = round(defects_m / max(uses_m, 1), 4)
                monthly.append({
                    "month": f"{y}-{m:02d}",
                    "defect_items": defects_m,
                    "component_uses": uses_m,
                    "density": dens,
                })
                m -= 1
                if m == 0:
                    m = 12
                    y -= 1
            monthly.reverse()
            return {
                "success": True,
                "kpi": key,
                "title": "缺陷密度明细",
                "subtitle": "密度 = 当月缺陷项合计 ÷ 当月组件使用次数",
                "items": monthly,
            }

        return JSONResponse(
            status_code=400,
            content={"success": False, "error": f"未知 KPI 类型: {key}"},
        )
    except Exception as e:
        print(f"获取看板 KPI 明细失败: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": str(e)},
        )


@app.delete("/api/custom-ai/{role_id}/knowledge")
async def delete_role_knowledge(role_id: str, request: Request):
    """删除角色的知识条目"""
    data = await request.json()
    keywords = data.get("keywords", "")
    answer = data.get("answer", None)
    text = data.get("text", None)  # 用于删除知识片段
    knowledge_id = data.get("id", None)  # 支持通过ID删除
    
    if not keywords and not text and not knowledge_id:
        return {"success": False, "error": "请提供要删除的关键词、文本或ID"}
    
    # 处理巴巴塔的知识库
    if role_id == "babata":
        full_role_id = "babata"
    else:
        full_role_id = f"custom-{role_id}"
    
    try:
        knowledge_base = _ensure_role_knowledge_base(full_role_id)
    except Exception:
        return {"success": False, "error": "知识库不存在"}
    
    # 如果提供了ID，优先通过ID删除
    if knowledge_id:
        # 尝试从数据库直接删除
        if hasattr(knowledge_base, 'use_database') and knowledge_base.use_database:
            try:
                import sqlite3
                conn = sqlite3.connect(knowledge_base.db_path)
                cursor = conn.cursor()
                cursor.execute("""
                    DELETE FROM knowledge_base
                    WHERE id = ? AND role_id = ?
                """, (knowledge_id, knowledge_base.role_id))
                deleted_count = cursor.rowcount
                conn.commit()
                conn.close()
                
                if deleted_count > 0:
                    # 重新加载知识库
                    if hasattr(knowledge_base, '_load_knowledge'):
                        knowledge_base._load_knowledge()
                    return {"success": True}
            except Exception as e:
                print(f"[知识库] 通过ID删除失败: {e}")
        
        # 如果数据库删除失败，尝试通过get_qa_pair_by_id获取信息后删除
        if hasattr(knowledge_base, 'get_qa_pair_by_id'):
            qa_pair = knowledge_base.get_qa_pair_by_id(knowledge_id)
            if qa_pair:
                keywords = qa_pair.get("keywords", "")
                answer = qa_pair.get("answer", "")
    
    # 如果是简单知识库，支持删除
    if hasattr(knowledge_base, 'delete_qa_pair') or hasattr(knowledge_base, 'delete_knowledge_chunk'):
        if keywords:
            # 删除问答对
            if hasattr(knowledge_base, 'delete_qa_pair'):
                success = knowledge_base.delete_qa_pair(keywords, answer)
                return {"success": success}
        elif text:
            # 删除知识片段
            if hasattr(knowledge_base, 'delete_knowledge_chunk'):
                success = knowledge_base.delete_knowledge_chunk(text)
                return {"success": success}
    
    return {"success": False, "error": "不支持删除操作"}


@app.get("/api/custom-ai/{role_id}/knowledge/{knowledge_id}")
async def get_knowledge_by_id(role_id: str, knowledge_id: str):
    """根据ID获取知识条目（用于获取图片）"""
    # 处理巴巴塔的知识库
    if role_id == "babata":
        full_role_id = "babata"
    else:
        full_role_id = f"custom-{role_id}"
    
    try:
        knowledge_base = _ensure_role_knowledge_base(full_role_id)
    except Exception:
        return {"success": False, "error": "知识库不存在"}
    
    if hasattr(knowledge_base, 'get_qa_pair_by_id'):
        qa_pair = knowledge_base.get_qa_pair_by_id(knowledge_id)
        if qa_pair:
            return {"success": True, "qa_pair": qa_pair}
    
    return {"success": False, "error": "未找到知识条目"}


@app.post("/api/custom-ai/{role_id}/associate-knowledge")
async def associate_knowledge_to_role(role_id: str, request: Request):
    """关联知识库到角色"""
    data = await request.json()
    knowledge_id = data.get("knowledge_id")
    
    if not knowledge_id:
        return JSONResponse(
            status_code=400,
            content={"success": False, "error": "知识库ID不能为空"}
        )
    
    await message_store.associate_knowledge_to_role(role_id, knowledge_id)
    return {"success": True}


@app.get("/api/custom-ai/{role_id}/associated-knowledge")
async def get_associated_knowledge(role_id: str):
    """获取角色关联的所有知识库"""
    associations = await message_store.get_role_knowledge_associations(role_id)
    return {"knowledge_bases": associations}


@app.delete("/api/custom-ai/{role_id}/associated-knowledge/{knowledge_id}")
async def remove_knowledge_association(role_id: str, knowledge_id: str):
    """取消角色与知识库的关联"""
    await message_store.remove_knowledge_association(role_id, knowledge_id)
    return {"success": True}


@app.get("/api/admin/config")
async def get_admin_config():
    """获取管理员配置"""
    config = await message_store.get_admin_config()
    return config


@app.post("/api/admin/config")
async def update_admin_config(request: Request):
    """更新管理员配置"""
    data = await request.json()
    admin_name = data.get("admin_name")
    enabled = data.get("enabled")
    
    await message_store.update_admin_config(
        admin_name=admin_name,
        enabled=enabled
    )
    return {"success": True}


@app.get("/api/cache/stats")
async def get_cache_stats():
    """获取缓存统计"""
    if response_cache:
        return response_cache.get_stats()
    return {"message": "缓存未启用"}


@app.post("/api/cache/clear")
async def clear_cache():
    """清空缓存"""
    if response_cache:
        response_cache.clear()
        return {"success": True, "message": "缓存已清空"}
    return {"success": False, "message": "缓存未启用"}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    if HTMLSYSTM_INTERNAL_URL:
        cookie_header = websocket.headers.get("cookie", "")
        user = await _verify_htmlsystm_user(cookie_header)
        if not user:
            await websocket.close(code=4401, reason="未登录或会话已失效")
            return
    await manager.connect(websocket)
    try:
        while True:
            try:
                data = await websocket.receive_text()
                try:
                    message_data = json.loads(data)
                    await handle_message(websocket, message_data)
                except json.JSONDecodeError:
                    await websocket.send_json({
                        "type": "error",
                        "message": "无效的JSON格式"
                    })
            except WebSocketDisconnect:
                break
            except Exception as e:
                print(f"处理消息时出错: {e}")
                await websocket.send_json({
                    "type": "error",
                    "message": f"处理消息失败: {str(e)}"
                })
    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"WebSocket错误: {e}")
    finally:
        manager.disconnect(websocket)


async def handle_message(websocket: WebSocket, data: dict):
    """处理WebSocket消息"""
    message_type = data.get("type")
    
    if message_type == "group_message":
        await handle_group_message(websocket, data)
    elif message_type == "ping":
        await websocket.send_json({"type": "pong"})
    else:
        await websocket.send_json({
            "type": "error",
            "message": f"未知的消息类型: {message_type}"
        })


async def handle_group_message(websocket: WebSocket, data: dict):
    """处理群聊消息 - 先由巴巴塔预处理，然后串行处理AI回复"""
    user_message = data.get("message")
    conversation_id = data.get("conversation_id", str(uuid.uuid4()))
    memory_user_id = str(data.get("user_id") or "anonymous")
    memory_group_id = str(data.get("group_id") or conversation_id)
    memory_org_id = str(data.get("org_id") or "")
    selected_ais = data.get("selected_ais", [])
    skip_event_triggers = data.get("skip_event_triggers", False)  # 审核提示词对话发出的消息不再匹配触发词
    event_max_tokens = data.get("event_max_tokens")  # 事件触发时设置的单次最大 token 用量（可选）
    skip_babata = data.get("skip_babata", False)
    review_context = data.get("review_context")
    schematic_phase = data.get("schematic_phase")

    if not user_message:
        await websocket.send_json({
            "type": "error",
            "message": "消息内容不能为空"
        })
        return
    
    # 获取管理员配置
    admin_config = await message_store.get_admin_config()
    admin_name = admin_config.get("admin_name", "巴巴塔")
    admin_enabled = admin_config.get("enabled", 1)
    
    # 保存用户消息
    user_msg_id = await message_store.save_message(
        conversation_id=conversation_id,
        role="user",
        content=user_message,
        ai_model=None
    )
    
    # 将用户消息添加到向量数据库（如果可用）
    if vector_store:
        try:
            await vector_store.add_message(
                conversation_id=conversation_id,
                message_id=user_msg_id,
                role="user",
                content=user_message
            )
        except Exception as e:
            print(f"添加用户消息到向量数据库失败: {e}")

    if os.getenv("MEMORY_EXTRACT_ENABLED", "true").lower() in ("1", "true", "yes"):
        enqueue_extract(
            ExtractJob(
                conversation_id=conversation_id,
                message_id=user_msg_id,
                user_id=memory_user_id,
                group_id=memory_group_id,
                org_id=memory_org_id,
            )
        )
    
    # 原理图 AI 审核：跳过巴巴塔，直接调用所选模型
    if skip_babata:
        ai_message = user_message
        if review_context and isinstance(review_context, dict):
            ctx_parts = []
            cleaned = review_context.get("cleanedNetlist") or review_context.get("cleaned_netlist")
            summary = review_context.get("reportSummary") or review_context.get("report_summary")
            if cleaned:
                ctx_parts.append(f"【评审上下文-清洗网表】\n{str(cleaned)}")
            if summary:
                ctx_parts.append(f"【评审上下文-报告摘要】\n{str(summary)}")
            if ctx_parts:
                ai_message = "\n\n".join(ctx_parts) + "\n\n【用户消息】\n" + user_message
        filtered_ais = [ai for ai in selected_ais if ai.get("id") != "babata"]
        await process_ais_sequentially(
            websocket=websocket,
            user_message=ai_message,
            conversation_id=conversation_id,
            selected_ais=filtered_ais,
            parent_message_id=user_msg_id,
            event_max_tokens=event_max_tokens,
            memory_user_id=memory_user_id,
            memory_group_id=memory_group_id,
            memory_org_id=memory_org_id,
            schematic_phase=schematic_phase,
        )
        await websocket.send_json({
            "type": "group_message_complete",
            "conversation_id": conversation_id,
            "user_message_id": user_msg_id,
        })
        return

    # 第一步：巴巴塔预处理（始终可用，作为低智能前置过滤）
    # 只要管理员功能开启，就先让巴巴塔尝试处理，能处理的任务就不再调用其他AI
    if admin_enabled:
        # 检查是否有其他AI被启用（除了巴巴塔）
        has_other_enabled_ai = any(ai.get("enabled", False) and ai.get("id") != "babata" for ai in selected_ais)
        
        # 先检查知识库（无论action是什么，都先检查知识库，优先于其他处理）
        knowledge_answer = None
        knowledge_matches = None
        knowledge_answer_data = None  # 保存完整的答案数据（包括图片）
        knowledge_base = _ensure_babata_knowledge_base()
        if knowledge_base:
            try:
                # 如果是简单知识库，确保已加载
                if hasattr(knowledge_base, '_load_knowledge'):
                    knowledge_base._load_knowledge()
                
                # 先获取所有匹配项
                all_matches = knowledge_base.retrieve(query=user_message, top_k=10, return_all_matches=True)
                if skip_event_triggers and all_matches and isinstance(all_matches, list):
                    all_matches = [m for m in all_matches if not m.get("event_config")]
                if all_matches and isinstance(all_matches, list) and len(all_matches) > 0:
                    # 检查是否有事件触发配置
                    event_triggers = []
                    for match in all_matches:
                        if match.get("event_config"):
                            event_triggers.append({
                                "keywords": match.get("question", ""),
                                "event_config": match.get("event_config"),
                                "match_id": match.get("id") if "id" in match else None
                            })
                    
                    if len(all_matches) == 1:
                        # 只有一个匹配，直接返回（包含图片信息）
                        knowledge_answer = all_matches[0]["answer"]
                        knowledge_answer_data = all_matches[0]  # 保存完整数据，包括图片和事件配置
                        print(f"[巴巴塔知识库] 匹配到1个答案: {all_matches[0]['question']}")
                        
                        # 检查是否有事件配置（不自动触发，传递给前端显示按钮）
                        if all_matches[0].get("event_config"):
                            print(f"[事件触发] 检测到事件配置: {all_matches[0]['event_config'].get('type')}")
                    else:
                        # 多个匹配，保存匹配列表供前端显示选择
                        knowledge_matches = all_matches
                        print(f"[巴巴塔知识库] 匹配到{len(all_matches)}个答案，需要用户选择")
                    
                    # 如果有事件触发，保存到上下文
                    if event_triggers:
                        print(f"[事件触发] 找到 {len(event_triggers)} 个事件触发配置")
            except Exception as e:
                print(f"[巴巴塔知识库] 检索失败: {e}")
                import traceback
                traceback.print_exc()
        
        # 先处理巴巴塔任务（无论是否有知识库匹配）
        task_result = babata_processor.process(user_message)
        action = task_result.get("action")
        mentioned_roles = []
        
        # 如果知识库有答案，直接返回（优先于其他处理）
        if knowledge_answer:
            babata_response = knowledge_answer
            context = {
                "messages": [],
                "last_user_message": user_message,
                "conversation_id": conversation_id
            }
            
            # 检查是否有事件配置（不自动触发，传递给前端显示按钮）
            if knowledge_answer_data and knowledge_answer_data.get("event_config"):
                event_config = knowledge_answer_data.get("event_config")
                print(f"[事件触发] 检测到事件配置，将显示按钮: {event_config.get('type')}")
                # 将事件配置添加到上下文，前端会显示按钮
                context["event_trigger"] = {
                    "event_config": event_config,
                    "keywords": knowledge_answer_data.get("question", ""),
                    "match_id": knowledge_answer_data.get("id") if "id" in knowledge_answer_data else None
                }
        elif knowledge_matches:
            # 多个匹配，生成选择提示
            matches_text = "找到多个相关答案，请选择：\n\n"
            for i, match in enumerate(knowledge_matches[:5], 1):  # 最多显示5个
                matches_text += f"{i}. {match['question']}\n"
            babata_response = matches_text
            context = {
                "messages": [],
                "last_user_message": user_message,
                "conversation_id": conversation_id,
                "knowledge_matches": knowledge_matches[:5]  # 最多5个
            }
        # 如果巴巴塔能处理（不需要API），直接返回
        elif action != TaskAction.CALL_CLOUD_API and action != TaskAction.UNKNOWN:
            # 处理@角色功能
            if action == TaskAction.MENTION_ROLES:
                keyword = task_result.get("keyword", "")
                if keyword:
                    # 获取所有可用角色
                    all_ais_response = await message_store.get_custom_ai_roles()
                    all_ais = []
                    for role in all_ais_response:
                        all_ais.append({
                            "id": f"custom-{role['base_ai']}-{role['id']}",
                            "name": role['name'],
                            "description": role.get('description', ''),
                            "rolePrompt": role.get('role_prompt', '')
                        })
                    mentioned_roles = babata_processor.find_matching_roles(keyword, all_ais)
            
            # 处理@特定助手：翻译/天气等走 AssistantRouter；@DeepSeek/@豆包 等与内置大模型同名则走 @角色 串行 API
            if action == TaskAction.MENTION_ASSISTANT:
                assistant_raw = (task_result.get("assistant") or "").strip()
                ar = assistant_raw.casefold()
                llm_alias_to_name = {
                    "deepseek": "DeepSeek",
                    "doubao": "豆包 SEED Mini",
                    "豆包": "豆包 SEED Mini",
                    "gpt-4": "ChatGPT",
                    "gpt4": "ChatGPT",
                    "chatgpt": "ChatGPT",
                    "claude-3": "Claude",
                    "claude": "Claude",
                    "gemini": "Gemini",
                }
                llm_alias_to_name.update(build_mention_alias_map())
                display_name = llm_alias_to_name.get(ar)
                if not display_name:
                    for ac in selected_ais:
                        nm = (ac.get("name") or "").strip()
                        if nm and nm.casefold() == ar:
                            display_name = nm
                            break
                if display_name:
                    mentioned_roles = [display_name]
                    action = TaskAction.MENTION_ROLES
                    task_result = {**task_result, "action": TaskAction.MENTION_ROLES}
            
            # 准备上下文信息（获取历史消息用于保存等功能）
            context = {
                "messages": [],  # 可以从conversation_id获取历史消息
                "last_user_message": user_message,
                "conversation_id": conversation_id
            }
            
            # 如果是保存对话，需要获取历史消息
            if action == TaskAction.SAVE_CONVERSATION:
                try:
                    history_messages = await message_store.get_group_conversation_messages(conversation_id)
                    # 转换为格式化的消息列表
                    formatted_messages = []
                    for msg in history_messages:
                        formatted_messages.append({
                            "sender": msg.get("role", "unknown"),
                            "name": "用户" if msg.get("role") == "user" else "AI",
                            "content": msg.get("content", ""),
                            "timestamp": msg.get("created_at", "")
                        })
                    context["messages"] = formatted_messages
                except:
                    pass
            
            # 处理网表对比和评审
            if action == TaskAction.NETLIST_COMPARE:
                # 尝试从消息中提取两个网表
                netlist1, netlist2 = _extract_netlists_from_message(user_message)
                if netlist1 and netlist2:
                    # 执行对比
                    try:
                        parser = PadsNetlistParser()
                        parsed1 = parser.parse(netlist1)
                        parsed2 = parser.parse(netlist2)
                        comparator = NetlistComparator()
                        comparison_result = comparator.compare(parsed1, parsed2)
                        
                        # 保存结果
                        result_id = str(uuid.uuid4())
                        netlist_result_store.save_comparison_result(
                            result_id=result_id,
                            comparison_result=comparison_result,
                            netlist1_name="网表1",
                            netlist2_name="网表2"
                        )
                        
                        babata_response = f"✅ 网表对比完成！\n\n📊 对比结果：\n- 新增元件：{len(comparison_result['added_components'])} 个\n- 移除元件：{len(comparison_result['removed_components'])} 个\n- 修改元件：{len(comparison_result['changed_components'])} 个\n- 新增网络：{len(comparison_result['added_nets'])} 个\n- 移除网络：{len(comparison_result['removed_nets'])} 个\n- 修改网络：{len(comparison_result['changed_nets'])} 个\n\n结果ID: {result_id}\n\n详细对比结果已保存，可在结果表格中查看。"
                    except Exception as e:
                        babata_response = f"网表对比失败：{str(e)}"
                else:
                    babata_response = "已识别到原理图对比请求。\n\n正在打开网表对比工具..."
            
            elif action == TaskAction.NETLIST_REVIEW:
                # 尝试从消息中提取网表
                netlist_content = _extract_single_netlist_from_message(user_message)
                if netlist_content:
                    # 执行分析
                    try:
                        analyzer = NetlistAnalyzer()
                        analysis_result = analyzer.analyze(netlist_content)
                        
                        # 保存结果
                        result_id = str(uuid.uuid4())
                        netlist_result_store.save_analysis_result(
                            result_id=result_id,
                            analysis_result=analysis_result,
                            netlist_name="网表"
                        )
                        
                        babata_response = _format_analysis_result_for_chat(analysis_result, result_id)
                    except Exception as e:
                        babata_response = f"网表分析失败：{str(e)}"
                else:
                    babata_response = "已识别到原理图评审请求。\n\n正在打开网表分析工具..."
            else:
                # 生成巴巴塔回复（知识库已经在前面检查过了）
                babata_response = babata_processor.format_response(task_result, mentioned_roles, context)
        
        # 确保context已初始化（在所有代码路径中）
        if 'context' not in locals():
            context = {
                "messages": [],
                "last_user_message": user_message,
                "conversation_id": conversation_id
            }
        
        # 如果知识库无答案，且action是ASK_AI_TO_LEARN，自动@其他AI（优先DeepSeek）
        should_ask_ai = False
        if not knowledge_answer and not knowledge_matches:
            if action == TaskAction.ASK_AI_TO_LEARN:
                # 提取问题（去掉"帮我问"等前缀）
                question = user_message
                for prefix in ["帮我问", "帮我问一下", "问一下", "帮我查", "帮我查一下", "让", "让AI", "让deepseek", "让DeepSeek"]:
                    if question.lower().startswith(prefix.lower()):
                        question = question[len(prefix):].strip()
                        break
                if not question:
                    question = user_message
                
                # 自动@其他AI（优先DeepSeek）
                should_ask_ai = True
                mentioned_ai_configs = []
                
                # 优先查找DeepSeek
                for ai_config in selected_ais:
                    if ai_config.get("id") == "deepseek" and ai_config.get("enabled", False):
                        mentioned_ai_configs.append(ai_config)
                        break
                
                # 如果DeepSeek不可用，使用第一个启用的AI
                if not mentioned_ai_configs:
                    for ai_config in selected_ais:
                        if ai_config.get("enabled", False) and ai_config.get("id") != "babata":
                            mentioned_ai_configs.append(ai_config)
                            break
                
                # 如果当前选择中没有，从系统全部AI列表中查找
                if not mentioned_ai_configs:
                    base_ais = await _build_llm_provider_catalog()
                    for ai in base_ais:
                        if ai.get("id") == "deepseek" and ai.get("enabled"):
                            mentioned_ai_configs.append(ai)
                            break
                    if not mentioned_ai_configs:
                        for ai in base_ais:
                            if ai.get("enabled"):
                                mentioned_ai_configs.append(ai)
                                break
                
                if mentioned_ai_configs:
                    babata_response = f"好的，我来帮您询问{mentioned_ai_configs[0].get('name', 'AI助手')}。"
                    # 将问题保存到context，供后续AI使用
                    context = {
                        "messages": [],
                        "last_user_message": question,  # 使用提取的问题
                        "conversation_id": conversation_id,
                        "original_user_message": user_message,  # 保存原始消息
                        "should_save_to_knowledge": True  # 标记可以保存到知识库
                    }
                else:
                    babata_response = (
                        "抱歉，没有可用的 AI 助手。请在工具栏打开「API 密钥」配置 DeepSeek 等密钥，"
                        "或在服务器环境变量中设置。"
                    )
        
        # 如果知识库无答案，且action是CALL_CLOUD_API或UNKNOWN，自动@其他AI（即使没有明确说"帮我问"）
        if not knowledge_answer and not knowledge_matches and not should_ask_ai:
            if action in [TaskAction.CALL_CLOUD_API, TaskAction.UNKNOWN]:
                # 尝试自动@其他AI（优先DeepSeek）
                mentioned_ai_configs = []
                
                # 优先查找DeepSeek
                for ai_config in selected_ais:
                    if ai_config.get("id") == "deepseek" and ai_config.get("enabled", False):
                        mentioned_ai_configs.append(ai_config)
                        break
                
                # 如果DeepSeek不可用，使用第一个启用的AI
                if not mentioned_ai_configs:
                    for ai_config in selected_ais:
                        if ai_config.get("enabled", False) and ai_config.get("id") != "babata":
                            mentioned_ai_configs.append(ai_config)
                            break
                
                # 如果当前选择中没有，从系统全部AI列表中查找
                if not mentioned_ai_configs:
                    base_ais = await _build_llm_provider_catalog()
                    for ai in base_ais:
                        if ai.get("id") == "deepseek" and ai.get("enabled"):
                            mentioned_ai_configs.append(ai)
                            break
                    if not mentioned_ai_configs:
                        for ai in base_ais:
                            if ai.get("enabled"):
                                mentioned_ai_configs.append(ai)
                                break
                
                if mentioned_ai_configs:
                    should_ask_ai = True
                    babata_response = f"好的，我来帮您询问{mentioned_ai_configs[0].get('name', 'AI助手')}。"
                    # 将问题保存到context，供后续AI使用
                    context = {
                        "messages": [],
                        "last_user_message": user_message,  # 使用原始问题
                        "conversation_id": conversation_id,
                        "original_user_message": user_message,  # 保存原始消息
                        "should_save_to_knowledge": True  # 标记可以保存到知识库
                    }
                else:
                    # 如果没有可用的AI，给出提示
                    babata_response = f"抱歉，我没有找到相关信息。\n\n您可以：\n1. 在知识库中添加相关问答对（点击我的头像旁边的📖按钮）\n2. 启用其他AI助手来回答这个问题\n3. 或者告诉我更多详细信息，我会尽力帮助您。"
        
        # 如果没有其他AI被启用，让巴巴塔回复（即使action是CALL_CLOUD_API或UNKNOWN）
        if not has_other_enabled_ai and not should_ask_ai:
            # 确保babata_response已设置
            if 'babata_response' not in locals():
                if not knowledge_answer and not knowledge_matches:
                    # 如果action是CALL_CLOUD_API或UNKNOWN，且知识库没有匹配，给出提示
                    if action in [TaskAction.CALL_CLOUD_API, TaskAction.UNKNOWN]:
                        babata_response = f"抱歉，我没有找到相关信息。\n\n您可以：\n1. 在知识库中添加相关问答对（点击我的头像旁边的📖按钮）\n2. 启用其他AI助手来回答这个问题\n3. 或者告诉我更多详细信息，我会尽力帮助您。"
                    else:
                        # 重新处理任务
                        task_result = babata_processor.process(user_message)
                        action = task_result.get("action")
                        mentioned_roles = []
                        babata_response = babata_processor.format_response(task_result, mentioned_roles, context)
        
        # 确保babata_response已设置（如果没有其他AI被启用，或者知识库有匹配，或者巴巴塔能处理）
        if (not has_other_enabled_ai or knowledge_answer or knowledge_matches or 
            ('babata_response' in locals() and babata_response)):
            
            # 保存巴巴塔回复
            babata_msg_id = await message_store.save_message(
                conversation_id=conversation_id,
                role="assistant",
                content=babata_response,
                ai_model="babata"
            )
            
            # 发送巴巴塔回复
            response_data = {
                "type": "ai_response",
                "ai_model": "babata",
                "message_id": babata_msg_id,
                "content": babata_response,
                "timestamp": datetime.now().isoformat(),
                "mentioned_roles": mentioned_roles  # 传递@的角色列表
            }
            
            # 如果有知识库匹配项，传递给前端
            if 'context' in locals() and "knowledge_matches" in context:
                response_data["knowledge_matches"] = context["knowledge_matches"]
            
            # 如果有事件触发配置，传递给前端（显示按钮，不自动执行）；审核提示词对话发出的消息不返回事件触发
            if not skip_event_triggers and 'context' in locals() and "event_trigger" in context:
                response_data["event_trigger"] = context["event_trigger"]
            
            # 如果有多个匹配项，检查是否有事件触发
            if not skip_event_triggers and 'context' in locals() and "knowledge_matches" in context:
                event_triggers = []
                for match in context["knowledge_matches"]:
                    if match.get("event_config"):
                        event_triggers.append({
                            "keywords": match.get("question", ""),
                            "event_config": match.get("event_config"),
                            "match_id": match.get("id") if "id" in match else None
                        })
                if event_triggers:
                    response_data["event_triggers"] = event_triggers
            
            # 如果有知识库答案的图片，传递给前端
            if knowledge_answer_data:
                image_data = knowledge_answer_data.get("image_data")
                image_path = knowledge_answer_data.get("image_path")
                image_type = knowledge_answer_data.get("image_type")
                
                print(f"[巴巴塔知识库] 检查图片数据: image_data存在={bool(image_data)}, image_path存在={bool(image_path)}, image_type={image_type}")
                
                if image_data or image_path:
                    response_data["knowledge_image"] = {
                        "image_data": image_data,
                        "image_path": image_path,
                        "image_type": image_type
                    }
                    print(f"[巴巴塔知识库] 已添加图片到响应: image_type={image_type}, image_data长度={len(image_data) if image_data else 0}")
                else:
                    print(f"[巴巴塔知识库] 未找到图片数据")
            else:
                print(f"[巴巴塔知识库] knowledge_answer_data为空或None")
            
            await websocket.send_json(response_data)
            
            # 如果知识库无答案且action是ASK_AI_TO_LEARN，自动@其他AI
            if should_ask_ai and 'mentioned_ai_configs' in locals() and mentioned_ai_configs:
                await process_ais_sequentially(
                    websocket=websocket,
                    user_message=context.get("last_user_message", user_message),  # 使用提取的问题
                    conversation_id=conversation_id,
                    selected_ais=mentioned_ai_configs,
                    parent_message_id=user_msg_id,
                    should_save_to_knowledge=True,  # 标记可以保存到知识库
                    original_user_message=user_message,  # 保存原始消息
                    event_max_tokens=event_max_tokens,
                    memory_user_id=memory_user_id,
                    memory_group_id=memory_group_id,
                    memory_org_id=memory_org_id,
                )
            
            # 如果@了角色，需要让这些角色回复（即使前端未勾选，也临时激活一次）
            if mentioned_roles and action == TaskAction.MENTION_ROLES:
                mentioned_ai_configs = []
                
                # 1. 从当前已选择的AI中匹配
                for ai_config in selected_ais:
                    if ai_config.get("name") in mentioned_roles:
                        mentioned_ai_configs.append(ai_config)
                
                # 2. 如果当前选择中没有匹配到（AI未勾选），从系统全部AI列表中查找并临时激活
                if not mentioned_ai_configs:
                    base_ais = await _build_llm_provider_catalog()
                    custom_roles = await message_store.get_custom_ai_roles()
                    for role in custom_roles:
                        base_ais.append({
                            "id": f"custom-{role['base_ai']}-{role['id']}",
                            "name": role['name'],
                            "avatar": role['avatar'],
                            "description": role.get('description', ''),
                            "enabled": await has_provider(role["base_ai"]),
                            "baseAI": role['base_ai'],
                            "rolePrompt": role['role_prompt'],
                            "roleConfig": role.get('role_config'),
                            "isCustom": True,
                        })
                    
                    # 按名称匹配被@的角色，临时作为 selected_ais 传入
                    for ai in base_ais:
                        if ai.get("name") in mentioned_roles:
                            mentioned_ai_configs.append(ai)
                
                enriched_mentions = []
                for c in mentioned_ai_configs:
                    enriched_mentions.append(await _enrich_mentioned_ai_config(c))
                mentioned_ai_configs = []
                for c in enriched_mentions:
                    if await _is_ai_invokable(c):
                        mentioned_ai_configs.append(c)
                ai_user_message = (task_result.get("content") or "").strip() or user_message

                # 串行处理被@的角色（临时激活一次）
                if mentioned_ai_configs:
                    await process_ais_sequentially(
                        websocket=websocket,
                        user_message=ai_user_message,
                        conversation_id=conversation_id,
                        selected_ais=mentioned_ai_configs,
                        parent_message_id=user_msg_id,
                        event_max_tokens=event_max_tokens,
                        memory_user_id=memory_user_id,
                        memory_group_id=memory_group_id,
                        memory_org_id=memory_org_id,
                        allow_mention_invoke=True,
                    )
                elif mentioned_roles:
                    roles_str = "、".join(mentioned_roles)
                    hint = (
                        f"已识别 @{roles_str}，但无法调用该助手。"
                        "请点击工具栏「API 密钥」保存对应 Key，或由管理员在服务器环境变量中配置。"
                    )
                    hint_id = await message_store.save_message(
                        conversation_id=conversation_id,
                        role="assistant",
                        content=hint,
                        ai_model="babata",
                    )
                    await websocket.send_json({
                        "type": "ai_response",
                        "ai_model": "babata",
                        "message_id": hint_id,
                        "content": hint,
                        "timestamp": datetime.now().isoformat(),
                    })
            
            # 发送完成状态
            await websocket.send_json({
                "type": "group_message_complete",
                "conversation_id": conversation_id,
                "user_message_id": user_msg_id
            })
            return
    
    # 第二步：如果巴巴塔无法处理，需要调用API，则串行处理所有AI
    await process_ais_sequentially(
        websocket=websocket,
        user_message=user_message,
        conversation_id=conversation_id,
        selected_ais=selected_ais,
        parent_message_id=user_msg_id,
        event_max_tokens=event_max_tokens,
        memory_user_id=memory_user_id,
        memory_group_id=memory_group_id,
        memory_org_id=memory_org_id,
    )
    
    # 发送完成状态
    await websocket.send_json({
        "type": "group_message_complete",
        "conversation_id": conversation_id,
        "user_message_id": user_msg_id
    })


async def process_ais_sequentially(
    websocket: WebSocket,
    user_message: str,
    conversation_id: str,
    selected_ais: list,
    parent_message_id: str,
    should_save_to_knowledge: bool = False,
    original_user_message: str = None,
    event_max_tokens: int = None,
    memory_user_id: str = "anonymous",
    memory_group_id: str = "",
    memory_org_id: str = "",
    allow_mention_invoke: bool = False,
    schematic_phase: str = None,
):
    """串行处理AI回复（一个接一个）"""
    previous_ai_responses = []  # 存储之前AI的回复，供后续AI参考
    
    for ai_config in selected_ais:
        ai_id = ai_config.get("id")
        
        # 跳过巴巴塔（巴巴塔已经在预处理阶段处理过了）
        if ai_id == "babata":
            continue
        # 前端未勾选的模型不调用；@ 提及时按服务端 API Key 临时激活一次
        if allow_mention_invoke:
            if not await _is_ai_invokable(ai_config):
                continue
        elif not ai_config.get("enabled", False):
            continue
        
        # 创建消息记录
        msg_id = await message_store.create_ai_message_record(
            conversation_id=conversation_id,
            ai_model=ai_id,
            status="pending",
            parent_message_id=parent_message_id
        )
    
    # 发送"思考中"状态
        await websocket.send_json({
            "type": "ai_thinking",
            "ai_model": ai_id,
            "message_id": msg_id,
            "timestamp": datetime.now().isoformat()
        })
        
        # 获取该AI的对话历史（传统方式：按时间顺序）
        time_based_history = await message_store.get_ai_conversation_history(
            conversation_id=conversation_id,
            ai_model=ai_id,
            limit=10
        )
        
        # 使用向量搜索获取相关的历史消息（语义搜索，如果可用）
        if vector_store:
            try:
                relevant_messages = await vector_store.search_relevant_messages(
                    query=user_message,
                    conversation_id=conversation_id,
                    ai_model=ai_id,
                    limit=5
                )
                
                # 合并两种历史：时间顺序 + 语义相关
                combined_history = []
                seen_ids = set()
                
                # 先添加语义相关的消息
                for msg in relevant_messages:
                    msg_key = f"{msg['role']}_{msg['content'][:50]}"
                    if msg_key not in seen_ids:
                        combined_history.append({
                            "role": msg["role"],
                            "content": msg["content"]
                        })
                        seen_ids.add(msg_key)
                
                # 再添加时间顺序的消息
                for msg in time_based_history:
                    msg_key = f"{msg['role']}_{msg['content'][:50]}"
                    if msg_key not in seen_ids:
                        combined_history.append({
                            "role": msg["role"],
                            "content": msg["content"]
                        })
                        seen_ids.add(msg_key)
                
                history = combined_history[-15:]
            except Exception as e:
                print(f"向量搜索失败，使用传统历史: {e}")
                history = time_based_history
        else:
            history = time_based_history
        
        # 将之前AI的回复添加到历史中（让AI能看到其他AI的回复）
        for prev_response in previous_ai_responses:
            history.append({
                "role": "assistant",
                "content": prev_response["content"],
                "ai_name": prev_response.get("ai_name", "")
            })
        
        role_prompt = ai_config.get("rolePrompt")
        role_config = ai_config.get("roleConfig")
        enable_reasoning = ai_config.get("enableReasoning", False)
        
        # 构建system prompt
        if role_config and role_prompt:
            role_name = ai_config.get("name", "AI助手")
            system_prompt = RolePromptBuilder.build_system_prompt(
                name=role_name,
                role_prompt=role_prompt,
                role_config=role_config
            )
        elif role_prompt:
            role_name = ai_config.get("name", "AI助手")
            system_prompt = RolePromptBuilder.build_simple_prompt(
                name=role_name,
                role_prompt=role_prompt
            )
        else:
            system_prompt = None

        memory_recall_text = ""
        if memory_service and vector_memory_backend:
            try:
                mctx = MemoryRecallContext(
                    query=user_message,
                    org_id=memory_org_id or "",
                    group_id=memory_group_id or "",
                    user_id=memory_user_id or "anonymous",
                    assistant_id=ai_id,
                    conversation_id=conversation_id,
                )
                memory_recall_text = await memory_service.recall_for_prompt(mctx)
            except Exception as e:
                print(f"[memory] recall 失败: {e}")
        
        # 获取或创建角色知识库（支持巴巴塔和自定义角色）
        knowledge_base = None
        if ai_id == "babata" or ai_id.startswith("custom-"):
            try:
                knowledge_base = _ensure_role_knowledge_base(ai_id)
            except Exception:
                knowledge_base = _get_role_knowledge_base_optional(ai_id)
        
        # 处理AI回复（串行，等待完成）
        try:
            response = await process_ai_response_sync(
            ai_id=ai_id,
            message=user_message,
            history=history,
                message_id=msg_id,
            websocket=websocket,
            conversation_id=conversation_id,
                system_prompt=system_prompt,
            enable_reasoning=enable_reasoning,
                knowledge_base=knowledge_base,
            should_save_to_knowledge=should_save_to_knowledge,
            original_user_message=original_user_message or user_message,
            max_tokens=event_max_tokens,
                memory_recall_text=memory_recall_text,
            schematic_phase=schematic_phase,
            )
            
            # 保存回复供后续AI参考
            previous_ai_responses.append({
                "ai_id": ai_id,
                "ai_name": ai_config.get("name", ""),
                "content": response
            })
        except Exception as e:
            print(f"AI {ai_id} 处理错误: {e}")


async def process_ai_response_sync(
    ai_id: str,
    message: str,
    history: list,
    message_id: str,
    websocket: WebSocket,
    conversation_id: str,
    system_prompt: Optional[str] = None,
    enable_reasoning: bool = False,
    knowledge_base = None,
    should_save_to_knowledge: bool = False,
    original_user_message: str = None,
    max_tokens: int = None,
    memory_recall_text: Optional[str] = None,
    schematic_phase: str = None,
) -> str:
    """同步处理AI回复（用于串行处理）"""
    finish_reason = None
    schematic_pre_export = schematic_phase == "pre_export"
    try:
        # 1. 从知识库检索相关知识（如果有）
        knowledge_context = None
        if knowledge_base and not schematic_pre_export:
            try:
                knowledge_context = knowledge_base.retrieve(
                    query=message,
                    top_k=3,
                    similarity_threshold=0.7,
                    max_tokens=1500
                )
                if knowledge_context:
                    print(f"[知识库] AI: {ai_id}, 检索到知识: {len(knowledge_context)} 字符")
                else:
                    print(f"[知识库] AI: {ai_id}, 未检索到相关知识")
            except Exception as e:
                print(f"[知识库] 检索失败: {e}")
        
        # 2. 优化上下文（控制token数量）
        if knowledge_context and system_prompt:
            enhanced_system_prompt = f"""{system_prompt}

【重要】以下是相关专业知识库内容，请优先参考这些信息回答：

{knowledge_context}

**重要提示：**
1. 如果知识库内容与用户问题直接相关，请优先使用知识库中的信息回答
2. 回答时请明确说明"根据知识库信息"或"根据专业知识库"
3. 如果知识库信息与问题不完全匹配，可以结合知识库信息和你的专业知识回答
4. 不要忽略知识库内容，即使你有其他知识也要优先参考知识库"""
        else:
            enhanced_system_prompt = system_prompt
            if knowledge_context:
                print(f"[知识库警告] AI: {ai_id}, 检索到知识但system_prompt为空，无法使用知识库")

        if memory_recall_text and not schematic_pre_export:
            if enhanced_system_prompt:
                enhanced_system_prompt = f"{enhanced_system_prompt}\n\n{memory_recall_text}"
            else:
                enhanced_system_prompt = memory_recall_text
        
        # 3. 压缩历史（原理图 Step1–3 导出前不压缩）
        if schematic_pre_export:
            optimized_history = history
            if not max_tokens:
                max_tokens = int(os.getenv("SCHEMATIC_MAX_OUTPUT_TOKENS", "8192"))
        else:
            optimized_history = context_optimizer.compress_history(history, max_tokens=2000)
        
        base_ai_id = _resolve_base_ai_id(ai_id)

        if base_ai_id == "deepseek":
            response, finish_reason = await stream_deepseek_response(
                websocket=websocket,
                ai_id=ai_id,
                message_id=message_id,
                user_message=message,
                optimized_history=optimized_history,
                enhanced_system_prompt=enhanced_system_prompt,
                enable_reasoning=enable_reasoning,
                max_tokens=max_tokens,
            )
        elif is_bailian_ai_id(ai_id):
            response, finish_reason = await stream_bailian_response(
                websocket=websocket,
                ai_id=ai_id,
                message_id=message_id,
                user_message=message,
                optimized_history=optimized_history,
                enhanced_system_prompt=enhanced_system_prompt,
                enable_reasoning=enable_reasoning,
                max_tokens=max_tokens,
            )
        elif base_ai_id == "doubao":
            response, finish_reason = await stream_ark_doubao_response(
                websocket=websocket,
                ai_id=ai_id,
                message_id=message_id,
                user_message=message,
                optimized_history=optimized_history,
                enhanced_system_prompt=enhanced_system_prompt,
                max_tokens=max_tokens,
            )
        else:
            # 4. 检查缓存（可选）
            cache_key = None
            if response_cache:
                messages_for_cache = [
                    {"role": "system", "content": enhanced_system_prompt or ""},
                    *optimized_history,
                    {"role": "user", "content": message}
                ]
                cache_key = response_cache.get_cache_key(messages_for_cache, include_history=False)
                cached_response = response_cache.get(cache_key)
                if cached_response:
                    response = cached_response
                    print(f"使用缓存响应（AI: {ai_id}）")
                else:
                    # 5. 调用AI适配器
                    response = await ai_manager.get_response(
                        ai_id=ai_id,
                        message=message,
                        history=optimized_history,
                        system_prompt=enhanced_system_prompt,
                        enable_reasoning=enable_reasoning
                    )
                    # 缓存响应
                    if cache_key and response:
                        response_cache.set(cache_key, response)
            else:
                # 无缓存，直接调用
                response = await ai_manager.get_response(
                    ai_id=ai_id,
                    message=message,
                    history=optimized_history,
                    system_prompt=enhanced_system_prompt,
                    enable_reasoning=enable_reasoning
                )
        
        # 解析缓存信息（从响应中提取）
        import re
        cache_info = None
        cache_match = re.search(r'__CACHE_INFO__([\d.]+)__(\d+)__(\d+)__', response)
        if cache_match:
            cache_info = {
                "hit_rate": float(cache_match.group(1)),
                "hit_tokens": int(cache_match.group(2)),
                "miss_tokens": int(cache_match.group(3))
            }
            # 从响应中移除缓存信息标记
            response = re.sub(r'__CACHE_INFO__[\d.]+__\d+__\d+__', '', response)
        
        # 保存AI回复
        final_content = response
        if final_content and final_content.strip():
            await message_store.update_ai_message(
                message_id=message_id,
                content=final_content,
                status="completed"
            )
            
            # 将AI回复添加到向量数据库（如果可用）
            if vector_store:
                try:
                    await vector_store.add_message(
                        conversation_id=conversation_id,
                        message_id=message_id,
                        role="assistant",
                        content=final_content,
                        ai_model=ai_id
                    )
                except Exception as e:
                    print(f"添加AI回复到向量数据库失败: {e}")
        else:
            await message_store.update_ai_message(
                message_id=message_id,
                content="(无回复内容)",
                status="completed"
            )
        
        # 发送AI回复
        response_data = {
            "type": "ai_response",
            "ai_model": ai_id,
            "message_id": message_id,
            "content": response,
            "cache_info": cache_info,
            "finish_reason": finish_reason,
            "timestamp": datetime.now().isoformat()
        }
        
        # 如果可以保存到知识库，添加标记和原始问题
        if should_save_to_knowledge:
            response_data["can_save_to_knowledge"] = True
            response_data["original_question"] = original_user_message or message
        
        await websocket.send_json(response_data)
        
        return response
        
    except Exception as e:
        print(f"AI {ai_id} 处理错误: {e}")
        
        # 更新消息状态为错误
        await message_store.update_ai_message(
            message_id=message_id,
            content=f"请求失败: {str(e)}",
            status="error"
        )
        
        # 发送错误信息
        await websocket.send_json({
            "type": "ai_error",
            "ai_model": ai_id,
            "message_id": message_id,
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        })
        
        return f"请求失败: {str(e)}"


async def process_ai_response(
    ai_id: str,
    message: str,
    history: list,
    message_id: str,
    websocket: WebSocket,
    conversation_id: str,
    system_prompt: Optional[str] = None,
    enable_reasoning: bool = False,
    knowledge_base = None,
    max_tokens: int = None
):
    """处理单个AI的响应"""
    try:
        # 1. 从知识库检索相关知识（如果有）
        knowledge_context = None
        if knowledge_base:
            try:
                knowledge_context = knowledge_base.retrieve(
                    query=message,
                    top_k=3,
                    similarity_threshold=0.7,
                    max_tokens=1500
                )
            except Exception as e:
                print(f"知识检索失败: {e}")
        
        # 2. 优化上下文（控制token数量）
        if knowledge_context and system_prompt:
            # 将知识上下文整合到system prompt
            enhanced_system_prompt = f"{system_prompt}\n\n以下是相关专业知识，请参考：\n{knowledge_context}"
        else:
            enhanced_system_prompt = system_prompt
        
        # 3. 压缩历史（控制token数量）
        optimized_history = context_optimizer.compress_history(history, max_tokens=2000)
        
        base_ai_id = _resolve_base_ai_id(ai_id)

        if base_ai_id == "deepseek":
            response = await stream_deepseek_response(
                websocket=websocket,
                ai_id=ai_id,
                message_id=message_id,
                user_message=message,
                optimized_history=optimized_history,
                enhanced_system_prompt=enhanced_system_prompt,
                enable_reasoning=enable_reasoning,
                max_tokens=max_tokens,
            )
        elif is_bailian_ai_id(ai_id):
            response = await stream_bailian_response(
                websocket=websocket,
                ai_id=ai_id,
                message_id=message_id,
                user_message=message,
                optimized_history=optimized_history,
                enhanced_system_prompt=enhanced_system_prompt,
                enable_reasoning=enable_reasoning,
                max_tokens=max_tokens,
            )
        elif base_ai_id == "doubao":
            response = await stream_ark_doubao_response(
                websocket=websocket,
                ai_id=ai_id,
                message_id=message_id,
                user_message=message,
                optimized_history=optimized_history,
                enhanced_system_prompt=enhanced_system_prompt,
                max_tokens=max_tokens,
            )
        else:
            # 4. 检查缓存（可选）
            cache_key = None
            if response_cache:
                messages_for_cache = [
                    {"role": "system", "content": enhanced_system_prompt or ""},
                    *optimized_history,
                    {"role": "user", "content": message}
                ]
                cache_key = response_cache.get_cache_key(messages_for_cache, include_history=False)
                cached_response = response_cache.get(cache_key)
                if cached_response:
                    response = cached_response
                    print(f"使用缓存响应（AI: {ai_id}）")
                else:
                    # 5. 调用AI适配器
                    response = await ai_manager.get_response(
                        ai_id=ai_id,
                        message=message,
                        history=optimized_history,
                        system_prompt=enhanced_system_prompt,
                        enable_reasoning=enable_reasoning
                    )
                    # 缓存响应
                    if cache_key and response:
                        response_cache.set(cache_key, response)
            else:
                # 无缓存，直接调用
                response = await ai_manager.get_response(
                    ai_id=ai_id,
                    message=message,
                    history=optimized_history,
                    system_prompt=enhanced_system_prompt,
                    enable_reasoning=enable_reasoning
                )
        
        # 解析缓存信息（从响应中提取）
        import re
        cache_info = None
        cache_match = re.search(r'__CACHE_INFO__([\d.]+)__(\d+)__(\d+)__', response)
        if cache_match:
            cache_info = {
                "hit_rate": float(cache_match.group(1)),
                "hit_tokens": int(cache_match.group(2)),
                "miss_tokens": int(cache_match.group(3))
            }
            # 从响应中移除缓存信息标记
            response = re.sub(r'__CACHE_INFO__[\d.]+__\d+__\d+__', '', response)
        
        # 保存AI回复
        final_content = response
        if final_content and final_content.strip():
            await message_store.update_ai_message(
                message_id=message_id,
                content=final_content,
                status="completed"
            )
            
            # 将AI回复添加到向量数据库（如果可用）
            if vector_store:
                try:
                    await vector_store.add_message(
                        conversation_id=conversation_id,
                        message_id=message_id,
                        role="assistant",
                        content=final_content,
                        ai_model=ai_id
                    )
                except Exception as e:
                    print(f"添加AI回复到向量数据库失败: {e}")
        else:
            await message_store.update_ai_message(
                message_id=message_id,
                content="(无回复内容)",
                status="completed"
            )
        
        # 发送AI回复
        await websocket.send_json({
            "type": "ai_response",
            "ai_model": ai_id,
            "message_id": message_id,
            "content": response,
            "cache_info": cache_info,
            "timestamp": datetime.now().isoformat()
        })
        
    except Exception as e:
        print(f"AI {ai_id} 处理错误: {e}")
        
        # 更新消息状态为错误
        await message_store.update_ai_message(
            message_id=message_id,
            content=f"请求失败: {str(e)}",
            status="error"
        )
        
        # 发送错误信息
        await websocket.send_json({
            "type": "ai_error",
            "ai_model": ai_id,
            "message_id": message_id,
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        })


def _extract_netlists_from_message(message: str) -> tuple:
    """从消息中提取两个网表"""
    # 方法1：使用分隔符
    if "---网表1---" in message and "---网表2---" in message:
        parts = message.split("---网表2---")
        if len(parts) == 2:
            netlist1_part = parts[0].split("---网表1---")
            if len(netlist1_part) == 2:
                return netlist1_part[1].strip(), parts[1].strip()
    
    # 方法2：使用代码块
    import re
    code_blocks = re.findall(r'```(?:\w+)?\n(.*?)```', message, re.DOTALL)
    if len(code_blocks) >= 2:
        return code_blocks[0].strip(), code_blocks[1].strip()
    
    # 方法3：查找*PART*标记（PADS网表特征）
    parts = re.split(r'(\*PART\*)', message)
    if len(parts) >= 4:
        # 找到两个*PART*部分
        netlist1_parts = []
        netlist2_parts = []
        current_list = None
        for i, part in enumerate(parts):
            if part == '*PART*':
                if current_list is None:
                    current_list = netlist1_parts
                    netlist1_parts.append(part)
                else:
                    current_list = netlist2_parts
                    netlist2_parts.append(part)
            elif current_list is not None:
                current_list.append(part)
        
        if netlist1_parts and netlist2_parts:
            return ''.join(netlist1_parts).strip(), ''.join(netlist2_parts).strip()
    
    return None, None


def _format_analysis_result_for_chat(analysis_result: dict, result_id: str) -> str:
    """将网表分析结果格式化为 AI 易读的 Markdown 文本（完整，无连接缩略）"""
    from backend.utils.netlist_format import format_analysis_result_markdown

    return format_analysis_result_markdown(analysis_result, result_id)


def _extract_single_netlist_from_message(message: str) -> Optional[str]:
    """从消息中提取单个网表"""
    # 方法1：查找代码块
    import re
    code_blocks = re.findall(r'```(?:\w+)?\n(.*?)```', message, re.DOTALL)
    if code_blocks:
        # 返回最长的代码块（可能是网表）
        return max(code_blocks, key=len).strip()
    
    # 方法2：查找*PART*标记
    if '*PART*' in message:
        # 提取从*PART*到*END*的内容
        match = re.search(r'(\*PART\*.*?\*END\*)', message, re.DOTALL)
        if match:
            return match.group(1).strip()
    
    # 方法3：如果消息看起来像网表（包含*PART*和*NET*）
    if '*PART*' in message and '*NET*' in message:
        return message.strip()
    
    return None


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
