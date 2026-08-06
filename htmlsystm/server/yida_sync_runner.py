# -*- coding: utf-8 -*-
"""宜搭→物料库 同步运行器（阶段3）：手动触发的后台同步 + 每天定时同步。

- 手动：物料库页「从宜搭同步」按钮 → POST /api/material-db/yida-sync → 后台线程跑全量。
- 定时：每天 DAILY_SYNC_HOUR 点自动跑一次。
- 状态：GET /api/material-db/yida-sync-status 查进度/上次结果。
"""
from __future__ import annotations

import threading
import time
from datetime import datetime
from typing import Any, Dict, Tuple

from server.logger import logger
from server.yida_config import YIDA_SYNC_SCHEDULER_ENABLED

# 每天定时同步的小时（0-23），可用环境变量覆盖
import os
DAILY_SYNC_HOUR = int(os.getenv('YIDA_SYNC_HOUR', '3'))
try:
    import fcntl
except ImportError:  # pragma: no cover - Windows/dev fallback
    fcntl = None

_lock = threading.Lock()
_state: Dict[str, Any] = {
    'running': False,
    'started_at': None,
    'finished_at': None,
    'by': None,
    'summary': None,   # sync_material_forms 的返回(total/ok/failed/results)
    'error': None,
}
_scheduler_thread = None
_scheduler_lock_file = None


def get_status() -> Dict[str, Any]:
    with _lock:
        return dict(_state)


def _do_sync(user_display: str) -> None:
    from server.material_yida_projection import sync_material_forms
    try:
        summary = sync_material_forms(user_display=user_display)
        with _lock:
            _state['summary'] = summary
            _state['error'] = None
        logger.info(f"宜搭同步完成: {summary.get('ok')}/{summary.get('total')} 成功, {summary.get('failed')} 失败")
    except Exception as e:
        logger.error(f"宜搭同步异常: {e}", exc_info=True)
        with _lock:
            _state['error'] = str(e)
    finally:
        with _lock:
            _state['running'] = False
            _state['finished_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def start_background_sync(user_display: str = '手动同步') -> Tuple[bool, str]:
    """启动一次后台同步。已有任务在跑则拒绝。Returns: (started, message)。"""
    with _lock:
        if _state['running']:
            return False, '同步已在进行中，请稍候'
        _state.update({
            'running': True,
            'started_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'finished_at': None, 'by': user_display, 'summary': None, 'error': None,
        })
    threading.Thread(target=_do_sync, args=(user_display,), daemon=True).start()
    return True, '已启动后台同步'


def _scheduler_loop():
    """每天 DAILY_SYNC_HOUR 点跑一次（粗粒度，按小时判定，避免重复触发）。"""
    last_run_date = None
    while True:
        try:
            now = datetime.now()
            today = now.strftime('%Y-%m-%d')
            if now.hour == DAILY_SYNC_HOUR and last_run_date != today:
                with _lock:
                    busy = _state['running']
                if not busy:
                    logger.info('定时触发宜搭→物料库同步')
                    start_background_sync(user_display='每日定时同步')
                    last_run_date = today
        except Exception as e:
            logger.warning(f'宜搭定时调度异常: {e}')
        time.sleep(300)  # 每 5 分钟检查一次


def _acquire_scheduler_process_lock() -> bool:
    """Ensure only one gunicorn worker starts the daily scheduler."""
    global _scheduler_lock_file
    if _scheduler_lock_file:
        return True
    if fcntl is None:
        return True
    try:
        from server.config import DATA_DIR
        lock_dir = os.path.join(DATA_DIR, 'locks')
        os.makedirs(lock_dir, exist_ok=True)
        lock_path = os.path.join(lock_dir, 'yida_sync_scheduler.lock')
        fh = open(lock_path, 'w')
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            fh.close()
            return False
        fh.write(str(os.getpid()))
        fh.flush()
        _scheduler_lock_file = fh
        return True
    except Exception as e:
        logger.warning(f'宜搭定时同步进程锁获取失败，将继续启动: {e}')
        return True


def start_daily_scheduler() -> None:
    """启动每日定时同步线程（应用启动时调用，幂等）。"""
    global _scheduler_thread
    if not YIDA_SYNC_SCHEDULER_ENABLED:
        logger.info('宜搭每日定时同步未启用（YIDA_SYNC_SCHEDULER_ENABLED=0）')
        return
    if _scheduler_thread and _scheduler_thread.is_alive():
        return
    if not _acquire_scheduler_process_lock():
        logger.info('宜搭每日定时同步已在其他进程中运行，跳过启动')
        return
    _scheduler_thread = threading.Thread(target=_scheduler_loop, daemon=True)
    _scheduler_thread.start()
    logger.info(f'宜搭每日定时同步已启动（每天 {DAILY_SYNC_HOUR} 点）')
