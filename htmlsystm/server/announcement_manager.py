"""
公告管理器 - 处理公告的存储和管理
"""
import os
import json
import uuid
import base64
from datetime import datetime
import shutil
import urllib.parse
import threading
import platform
import unicodedata

from server.html_sanitize import sanitize_announcement_content, sanitize_announcement_title

# 根据操作系统导入文件锁模块
try:
    import fcntl  # Unix/Linux文件锁
    HAS_FCNTL = True
except ImportError:
    HAS_FCNTL = False

try:
    import msvcrt  # Windows文件锁
    HAS_MSVCRT = True
except ImportError:
    HAS_MSVCRT = False

from server.announcement_config import *
from server.config import (
    MAX_ATTACHMENT_SIZE, MAX_ATTACHMENTS_PER_ANNOUNCEMENT,
    ALLOWED_ATTACHMENT_EXTENSIONS, BLOCKED_ATTACHMENT_EXTENSIONS,
    ENABLE_RECYCLE_BIN, RECYCLE_BIN_RETENTION_DAYS, MAX_VERSION_HISTORY
)
from server.security import InputValidator
from server.logger import logger
from server.object_store import build_store_from_env
from server.tree_mirror import TreeMirror

# 公告目录 → 对象存储 的写通镜像（进程内单例；多个 AnnouncementManager 实例共享）。
# STORAGE_BACKEND=local 时 store 为 None，镜像整体空转，行为与历史版本完全一致。
_MIRRORS: dict = {}
_MIRRORS_LOCK = threading.Lock()


def _announcement_mirror(base_dir: str) -> TreeMirror:
    with _MIRRORS_LOCK:
        mirror = _MIRRORS.get(base_dir)
        if mirror is None:
            store = build_store_from_env('announcements')
            mirror = TreeMirror(base_dir, store)
            _MIRRORS[base_dir] = mirror
            if store is not None:
                # 卷丢失后的整树恢复（本地非空则跳过），随后后台对账自愈漏传
                restored = mirror.restore_all()
                if restored:
                    logger.info('公告目录已从对象存储恢复 %d 个文件', restored)

                def _reconcile_loop():
                    import time as _time
                    _time.sleep(60)
                    while True:
                        try:
                            mirror.reconcile()
                        except Exception as e:  # noqa: BLE001
                            logger.warning('公告镜像对账异常: %s', e)
                        _time.sleep(6 * 3600)

                threading.Thread(target=_reconcile_loop, daemon=True,
                                 name='announcement-mirror-reconcile').start()
        return mirror

# 常见文件 magic bytes 校验（扩展名与实际内容不符时拒绝）
_ATTACHMENT_MAGIC_CHECKS = {
    '.pdf': [b'%PDF'],
    '.zip': [b'PK\x03\x04', b'PK\x05\x06'],
    '.docx': [b'PK\x03\x04'],
    '.xlsx': [b'PK\x03\x04'],
    '.pptx': [b'PK\x03\x04'],
    '.png': [b'\x89PNG\r\n\x1a\n'],
    '.jpg': [b'\xff\xd8\xff'],
    '.jpeg': [b'\xff\xd8\xff'],
    '.gif': [b'GIF87a', b'GIF89a'],
    '.webp': [b'RIFF'],
    '.bmp': [b'BM'],
}

class AnnouncementManager:
    # 类级别的锁字典，用于管理每个公告的文件锁
    _file_locks = {}
    _file_locks_lock = threading.Lock()  # 保护锁字典的锁
    
    def __init__(self, base_dir=None):
        # 使用绝对路径，确保基于当前脚本位置动态获取
        # 如果提供了base_dir，使用它；否则从当前文件位置计算
        if base_dir:
            # 使用提供的base_dir（通常是main.py计算的BASE_DIR）
            project_base = base_dir
        else:
            # 从当前文件位置计算（向后兼容）
            current_file_dir = os.path.dirname(os.path.abspath(__file__))
            project_base = os.path.dirname(current_file_dir)
        
        announcement_base = os.path.join(project_base, "data", "announcements")
        self.base_dir = os.path.abspath(announcement_base)
        self.temp_dir = ANNOUNCEMENT_TEMP_DIR
        self._ensure_directories()
        self._mirror = _announcement_mirror(self.base_dir)
        self._install_mirror_hooks()
        # 只在调试模式下打印初始化信息，减少日志输出
        if os.getenv('DEBUG', '').lower() in ('1', 'true', 'yes'):
            print(f"公告管理器初始化: 项目目录={project_base}, base_dir={self.base_dir}, temp_dir={self.temp_dir}")
    
    # ---------- 对象存储镜像 ----------
    # 公告逻辑本身只操作本地目录；这里在四个改动数据的公共方法外面套一层
    # finally 同步，把该公告的子树差量推到对象存储。放在方法外壁而不是散布
    # 在上百个文件操作点，是因为这些方法内部有大量早退分支和重试路径。

    _MIRRORED_METHODS = (
        ('create_announcement', 'result'),   # id 在返回值 (id, msg) 里
        ('update_announcement', 'arg'),
        ('delete_announcement', 'arg'),
        ('approve_announcement', 'arg'),
    )

    def _install_mirror_hooks(self):
        if getattr(self, '_mirror_hooks_installed', False):
            return
        self._mirror_hooks_installed = True
        if self._mirror.store is None:
            return

        def wrap(method_name, id_source):
            original = getattr(self, method_name)

            def wrapper(*args, **kwargs):
                announcement_id = None
                if id_source == 'arg':
                    announcement_id = kwargs.get('announcement_id') or (args[0] if args else None)
                try:
                    result = original(*args, **kwargs)
                    if id_source == 'result' and isinstance(result, tuple) and result and result[0]:
                        announcement_id = result[0]
                    return result
                finally:
                    # 创建路径抛异常时拿不到 id，残留文件由启动对账补传
                    if announcement_id:
                        self._mirror_sync_announcement(str(announcement_id))

            wrapper.__name__ = method_name
            setattr(self, method_name, wrapper)

        for name, id_source in self._MIRRORED_METHODS:
            wrap(name, id_source)

    def _mirror_sync_announcement(self, announcement_id):
        """同步一条公告可能存在过的所有位置：各板块、temp/<id>、temp/<user>/<id>。

        对已消失的位置（删除、跨板块移动、审批后离开 temp），sync_subtree 会
        依据状态清单清掉远端残留，因此无需区分是哪种变更。绝不抛出。
        """
        try:
            candidates = set(self._mirror.prefixes_containing(announcement_id))
            for entry in os.listdir(self.base_dir):
                entry_path = os.path.join(self.base_dir, entry)
                if not os.path.isdir(entry_path):
                    continue
                if entry == self.temp_dir:
                    if os.path.isdir(os.path.join(entry_path, announcement_id)):
                        candidates.add(f'{self.temp_dir}/{announcement_id}')
                    for user_dir in os.listdir(entry_path):
                        if os.path.isdir(os.path.join(entry_path, user_dir, announcement_id)):
                            candidates.add(f'{self.temp_dir}/{user_dir}/{announcement_id}')
                elif os.path.isdir(os.path.join(entry_path, announcement_id)):
                    candidates.add(f'{entry}/{announcement_id}')
            for rel in sorted(candidates):
                self._mirror.sync_subtree(rel)
        except Exception as e:  # noqa: BLE001 — 同步失败不还原业务操作，见 tree_mirror 模块注释
            logger.warning('公告 %s 镜像同步失败（对账会自愈）: %s', announcement_id, e)

    def _get_file_lock(self, announcement_id):
        """获取公告的文件锁（线程安全）
        
        Args:
            announcement_id: 公告ID
            
        Returns:
            文件锁对象
        """
        with self._file_locks_lock:
            if announcement_id not in self._file_locks:
                self._file_locks[announcement_id] = threading.RLock()
            return self._file_locks[announcement_id]
    
    def _acquire_metadata_lock(self, announcement_path, timeout=30):
        """获取元数据文件的文件锁（跨进程锁）
        
        Args:
            announcement_path: 公告路径
            timeout: 超时时间（秒）
            
        Returns:
            文件对象（已加锁）或None（如果获取失败）
        """
        metadata_file = os.path.join(announcement_path, 'metadata.json')
        lock_file = metadata_file + '.lock'
        
        try:
            # 确保目录存在
            os.makedirs(announcement_path, exist_ok=True)
            
            # 创建锁文件
            lock_fd = open(lock_file, 'w')
            
            # 根据操作系统选择锁机制
            system = platform.system()
            if system == 'Windows' and HAS_MSVCRT:
                # Windows使用msvcrt
                try:
                    msvcrt.locking(lock_fd.fileno(), msvcrt.LK_NBLCK, 1)
                except (IOError, OSError):
                    lock_fd.close()
                    return None
            elif HAS_FCNTL:
                # Unix/Linux使用fcntl
                try:
                    fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except (IOError, OSError):
                    lock_fd.close()
                    return None
            else:
                # 如果两个模块都不可用，只使用线程锁（不提供跨进程保护）
                print("警告: 文件锁模块不可用，仅使用线程锁（不提供跨进程保护）")
                lock_fd.close()
                return None  # 返回None表示无法获取文件锁，但线程锁仍然有效
            
            return lock_fd
        except Exception as e:
            print(f"获取文件锁失败: {e}")
            return None
    
    def _release_metadata_lock(self, lock_fd):
        """释放元数据文件的文件锁
        
        Args:
            lock_fd: 文件对象（已加锁）
        """
        if lock_fd:
            try:
                system = platform.system()
                if system == 'Windows' and HAS_MSVCRT:
                    msvcrt.locking(lock_fd.fileno(), msvcrt.LK_UNLCK, 1)
                elif HAS_FCNTL:
                    fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)
                lock_fd.close()
                # 删除锁文件
                if os.path.exists(lock_fd.name):
                    try:
                        os.remove(lock_fd.name)
                    except:
                        pass
            except Exception as e:
                print(f"释放文件锁失败: {e}")
    
    def _get_all_board_ids(self):
        """获取所有一级公告栏ID（从数据库和配置文件）"""
        board_ids = set(ANNOUNCEMENT_BOARDS.keys())
        
        # 从数据库读取一级公告栏
        try:
            from server.board_manager import BoardManager
            board_mgr = BoardManager()
            db_boards = board_mgr.get_all_boards()
            for board in db_boards:
                board_ids.add(board['id'])
        except Exception as e:
            print(f"从数据库读取公告栏失败: {e}")
        
        return board_ids
    
    def _ensure_directories(self):
        """确保必要的目录存在"""
        os.makedirs(self.base_dir, exist_ok=True)
        temp_dir_path = os.path.join(self.base_dir, self.temp_dir)
        os.makedirs(temp_dir_path, exist_ok=True)
        
        # 创建各公告栏目录（从数据库和配置文件读取）
        board_ids = self._get_all_board_ids()
        
        # 创建各公告栏目录
        for board_id in board_ids:
            board_path = os.path.join(self.base_dir, board_id)
            os.makedirs(board_path, exist_ok=True)
    
    def _get_announcement_path(self, board_id, announcement_id, is_temp=False, user_id=None):
        """获取公告路径
        
        Args:
            board_id: 公告栏ID
            announcement_id: 公告ID
            is_temp: 是否为临时文件（草稿或待审核）
            user_id: 用户ID（用于草稿时按用户组织）
        """
        if is_temp:
            if user_id and isinstance(user_id, (int, str)):
                # 草稿按用户ID组织：temp/{user_id}/{announcement_id}
                user_dir = os.path.join(self.base_dir, self.temp_dir, str(user_id))
                os.makedirs(user_dir, exist_ok=True)
                return os.path.join(user_dir, f"{announcement_id}")
            else:
                # 兼容旧格式：temp/{announcement_id}
                return os.path.join(self.base_dir, self.temp_dir, f"{announcement_id}")
        else:
            return os.path.join(self.base_dir, board_id, f"{announcement_id}")
    
    def _read_metadata(self, announcement_path):
        """读取公告元数据"""
        metadata_file = os.path.join(announcement_path, 'metadata.json')
        if os.path.exists(metadata_file):
            try:
                with open(metadata_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                print(f"读取元数据失败 {metadata_file}: {e}")
                return None
        return None
    
    def _write_metadata(self, announcement_path, metadata):
        """写入公告元数据（带重试机制和错误处理）"""
        import time
        import errno
        
        # 确保目录存在（带重试）
        max_retries = 3
        retry_delay = 0.1
        
        for attempt in range(max_retries):
            try:
                os.makedirs(announcement_path, exist_ok=True)
                break
            except (OSError, IOError) as e:
                if e.errno == errno.EIO:  # Input/output error
                    logger.error(f"创建目录I/O错误 (尝试 {attempt + 1}/{max_retries}): {announcement_path}, 错误: {e}")
                    if attempt < max_retries - 1:
                        time.sleep(retry_delay * (attempt + 1))
                        continue
                    else:
                        # 检查磁盘空间
                        try:
                            import shutil
                            stat = shutil.disk_usage(os.path.dirname(announcement_path))
                            free_gb = stat.free / (1024**3)
                            logger.error(f"磁盘可用空间: {free_gb:.2f} GB")
                            if free_gb < 0.1:
                                logger.error("磁盘空间不足")
                        except:
                            pass
                        return False
                else:
                    raise
        
        metadata_file = os.path.join(announcement_path, 'metadata.json')
        temp_file = metadata_file + '.tmp'
        
        # 使用临时文件写入，然后原子性重命名（避免部分写入）
        for attempt in range(max_retries):
            try:
                # 先写入临时文件
                with open(temp_file, 'w', encoding='utf-8') as f:
                    json.dump(metadata, f, ensure_ascii=False, indent=2)
                    f.flush()
                    os.fsync(f.fileno())  # 强制刷新到磁盘
                
                # 原子性重命名
                if os.path.exists(metadata_file):
                    os.replace(temp_file, metadata_file)
                else:
                    os.rename(temp_file, metadata_file)
                
                return True
            except (OSError, IOError) as e:
                error_msg = str(e)
                error_code = getattr(e, 'errno', None)
                
                # 清理临时文件
                try:
                    if os.path.exists(temp_file):
                        os.remove(temp_file)
                except:
                    pass
                
                if error_code == errno.EIO:  # Input/output error
                    logger.error(f"写入元数据I/O错误 (尝试 {attempt + 1}/{max_retries}): {metadata_file}, 错误: {e}")
                    if attempt < max_retries - 1:
                        time.sleep(retry_delay * (attempt + 1))
                        continue
                    else:
                        # 检查磁盘空间和权限
                        try:
                            import shutil
                            stat = shutil.disk_usage(os.path.dirname(metadata_file))
                            free_gb = stat.free / (1024**3)
                            logger.error(f"磁盘可用空间: {free_gb:.2f} GB")
                            if free_gb < 0.1:
                                logger.error("磁盘空间不足")
                        except Exception as check_e:
                            logger.error(f"检查磁盘空间失败: {check_e}")
                        
                        # 检查目录权限
                        try:
                            if not os.access(os.path.dirname(metadata_file), os.W_OK):
                                logger.error(f"目录无写权限: {os.path.dirname(metadata_file)}")
                        except:
                            pass
                        
                        logger.error(f"写入元数据最终失败: {metadata_file}, 错误: {error_msg}")
                        return False
                else:
                    logger.error(f"写入元数据失败 {metadata_file}: {e}")
                    return False
            except Exception as e:
                logger.error(f"写入元数据异常 {metadata_file}: {e}", exc_info=True)
                return False
        
        return False
    
    def _validate_attachment_file(self, filename, decoded_data):
        """校验附件文件名与内容安全性"""
        safe_name = os.path.basename(filename or '')
        if not safe_name or safe_name != filename:
            raise ValueError(f"文件名不合法：{filename}")
        if '..' in safe_name or '/' in safe_name or '\\' in safe_name:
            raise ValueError(f"文件名包含非法字符：{safe_name}")

        ext = os.path.splitext(safe_name)[1].lower()
        if ext in BLOCKED_ATTACHMENT_EXTENSIONS:
            raise ValueError(f"禁止上传的文件类型：{ext}")

        valid, err = InputValidator.validate_file_extension(safe_name, ALLOWED_ATTACHMENT_EXTENSIONS)
        if not valid:
            raise ValueError(err)

        if ext in _ATTACHMENT_MAGIC_CHECKS:
            matched = any(decoded_data.startswith(sig) for sig in _ATTACHMENT_MAGIC_CHECKS[ext])
            if not matched:
                raise ValueError(f"文件内容与扩展名不符：{safe_name}")

    def _save_attachments(self, announcement_path, attachments):
        """保存附件（带大小验证）
        
        Args:
            announcement_path: 公告路径
            attachments: 附件列表
            
        Returns:
            保存成功的附件列表
            
        Raises:
            ValueError: 如果附件大小超过限制或附件数量超过限制
        """
        if not attachments:
            return []
        
        # 检查附件数量
        if len(attachments) > MAX_ATTACHMENTS_PER_ANNOUNCEMENT:
            raise ValueError(f"附件数量超过限制：最多允许{MAX_ATTACHMENTS_PER_ANNOUNCEMENT}个附件，当前有{len(attachments)}个")
        
        attachment_dir = os.path.join(announcement_path, 'attachments')
        os.makedirs(attachment_dir, exist_ok=True)
        
        saved_attachments = []
        total_size = 0
        
        for attachment in attachments:
            try:
                # 检查单个附件大小
                attachment_size = attachment.get('size', 0)
                if attachment_size > MAX_ATTACHMENT_SIZE:
                    raise ValueError(f"附件大小超过限制：{attachment['name']} ({attachment_size / 1024 / 1024:.2f}MB) 超过最大限制 {MAX_ATTACHMENT_SIZE / 1024 / 1024:.2f}MB")
                
                # 解码base64数据并检查实际大小
                try:
                    decoded_data = base64.b64decode(attachment['data'])
                    actual_size = len(decoded_data)
                    if actual_size > MAX_ATTACHMENT_SIZE:
                        raise ValueError(f"附件大小超过限制：{attachment['name']} (实际大小: {actual_size / 1024 / 1024:.2f}MB) 超过最大限制 {MAX_ATTACHMENT_SIZE / 1024 / 1024:.2f}MB")
                except Exception as e:
                    if isinstance(e, ValueError):
                        raise
                    raise ValueError(f"附件数据解码失败：{attachment['name']}, 错误: {str(e)}")

                self._validate_attachment_file(attachment['name'], decoded_data)
                
                # 检查总大小（所有附件的累计大小）
                total_size += actual_size
                if total_size > MAX_ATTACHMENT_SIZE * MAX_ATTACHMENTS_PER_ANNOUNCEMENT:
                    raise ValueError(f"所有附件总大小超过限制：{total_size / 1024 / 1024:.2f}MB 超过最大限制 {MAX_ATTACHMENT_SIZE * MAX_ATTACHMENTS_PER_ANNOUNCEMENT / 1024 / 1024:.2f}MB")
                
                # 使用原始文件名保存，确保中文字符正确保存
                original_filename = attachment['name']
                file_path = os.path.join(attachment_dir, original_filename)
                
                # 确保目录存在（带重试）
                import time
                import errno
                max_retries = 3
                retry_delay = 0.1
                
                for attempt in range(max_retries):
                    try:
                        os.makedirs(os.path.dirname(file_path), exist_ok=True)
                        break
                    except (OSError, IOError) as e:
                        if e.errno == errno.EIO:
                            logger.error(f"创建附件目录I/O错误 (尝试 {attempt + 1}/{max_retries}): {os.path.dirname(file_path)}")
                            if attempt < max_retries - 1:
                                time.sleep(retry_delay * (attempt + 1))
                                continue
                            else:
                                raise ValueError(f"创建附件目录失败: {str(e)}")
                        else:
                            raise
                
                # 保存文件（使用临时文件，然后原子性重命名）
                temp_file_path = file_path + '.tmp'
                for attempt in range(max_retries):
                    try:
                        with open(temp_file_path, 'wb') as f:
                            f.write(decoded_data)
                            f.flush()
                            os.fsync(f.fileno())  # 强制刷新到磁盘
                        
                        # 原子性重命名
                        if os.path.exists(file_path):
                            os.replace(temp_file_path, file_path)
                        else:
                            os.rename(temp_file_path, file_path)
                        
                        break  # 成功，退出重试循环
                    except (OSError, IOError) as e:
                        error_code = getattr(e, 'errno', None)
                        
                        # 清理临时文件
                        try:
                            if os.path.exists(temp_file_path):
                                os.remove(temp_file_path)
                        except:
                            pass
                        
                        if error_code == errno.EIO:
                            logger.error(f"保存附件I/O错误 (尝试 {attempt + 1}/{max_retries}): {file_path}")
                            if attempt < max_retries - 1:
                                time.sleep(retry_delay * (attempt + 1))
                                continue
                            else:
                                # 检查磁盘空间
                                try:
                                    import shutil
                                    stat = shutil.disk_usage(os.path.dirname(file_path))
                                    free_gb = stat.free / (1024**3)
                                    logger.error(f"磁盘可用空间: {free_gb:.2f} GB")
                                    if free_gb < 0.1:
                                        raise ValueError(f"磁盘空间不足，无法保存附件: {original_filename}")
                                except ValueError:
                                    raise
                                except:
                                    pass
                                raise ValueError(f"保存附件失败: {original_filename}, I/O错误: {str(e)}")
                        else:
                            raise ValueError(f"保存附件失败: {original_filename}, 错误: {str(e)}")
                else:
                    # 所有重试都失败
                    raise ValueError(f"保存附件失败: {original_filename}, 多次重试后仍失败")
                
                # 验证文件是否保存成功
                if os.path.exists(file_path):
                    file_size = os.path.getsize(file_path)
                    saved_attachments.append({
                        'name': original_filename,
                        'size': file_size,
                        'type': attachment.get('type', 'application/octet-stream')
                    })
                    print(f"附件保存成功: {original_filename}, 路径={file_path}, 大小={file_size} bytes ({file_size / 1024 / 1024:.2f}MB)")
                else:
                    raise ValueError(f"附件保存失败: 文件不存在 {file_path}")
            except ValueError as e:
                # 清理已保存的附件
                for saved_att in saved_attachments:
                    try:
                        saved_file_path = os.path.join(attachment_dir, saved_att['name'])
                        if os.path.exists(saved_file_path):
                            os.remove(saved_file_path)
                    except:
                        pass
                raise  # 重新抛出ValueError
            except Exception as e:
                print(f"保存附件失败 {attachment.get('name', 'unknown')}: {e}")
                import traceback
                traceback.print_exc()
                # 清理已保存的附件
                for saved_att in saved_attachments:
                    try:
                        saved_file_path = os.path.join(attachment_dir, saved_att['name'])
                        if os.path.exists(saved_file_path):
                            os.remove(saved_file_path)
                    except:
                        pass
                raise ValueError(f"保存附件失败：{attachment.get('name', 'unknown')}, 错误: {str(e)}")
        
        return saved_attachments
    
    def create_announcement(self, board_id, title, content, author, priority='normal', status='draft', attachments=None, sub_board_id=None, user_id=None, author_userid=None, pending_approver_identifier=None, pending_approver_userid=None):
        """创建新公告
        
        Args:
            board_id: 公告栏ID
            title: 标题
            content: 内容
            author: 作者名称
            priority: 优先级
            status: 状态（draft/pending/approved）
            attachments: 附件列表
            sub_board_id: 二级公告栏ID
            user_id: 用户ID（用于草稿时按用户组织）
        """
        # 检查公告栏是否存在（从数据库或配置文件）
        board_ids = self._get_all_board_ids()
        if board_id not in board_ids:
            return None, "无效的公告栏"

        title = sanitize_announcement_title(title)
        content = sanitize_announcement_content(content)
        
        announcement_id = str(uuid.uuid4())
        is_temp = status in ['draft', 'pending']
        # 如果是草稿，使用用户ID组织
        announcement_path = self._get_announcement_path(board_id, announcement_id, is_temp, user_id=user_id if status == 'draft' else None)
        
        print(f"创建公告: id={announcement_id}, board={board_id}, sub_board={sub_board_id}, status={status}, path={announcement_path}")
        
        # 创建公告元数据
        metadata = {
            'id': announcement_id,
            'title': title,
            'content': content,
            'author': author,
            'original_author': author,  # 记录发起人
            'author_userid': author_userid or '',
            'board_id': board_id,
            'sub_board_id': sub_board_id,  # 添加二级公告栏ID
            'priority': priority,
            'status': status,
            'created_time': datetime.now().isoformat(),
            'updated_time': datetime.now().isoformat(),
            'publish_time': None,
            'attachments': []
        }
        
        if pending_approver_identifier:
            metadata['pending_approver_identifier'] = str(pending_approver_identifier).strip()
        if pending_approver_userid:
            metadata['pending_approver_userid'] = str(pending_approver_userid).strip()
        
        if status == 'approved':
            metadata['publish_time'] = datetime.now().isoformat()
        
        # 写入元数据
        if not self._write_metadata(announcement_path, metadata):
            return None, "保存公告元数据失败"
        
        # 写入内容文件（带重试机制）
        content_file = os.path.join(announcement_path, 'content.html')
        temp_content_file = content_file + '.tmp'
        import time
        import errno
        
        max_retries = 3
        retry_delay = 0.1
        
        for attempt in range(max_retries):
            try:
                # 先写入临时文件
                with open(temp_content_file, 'w', encoding='utf-8') as f:
                    f.write(content)
                    f.flush()
                    os.fsync(f.fileno())  # 强制刷新到磁盘
                
                # 原子性重命名
                if os.path.exists(content_file):
                    os.replace(temp_content_file, content_file)
                else:
                    os.rename(temp_content_file, content_file)
                
                break  # 成功，退出重试循环
            except (OSError, IOError) as e:
                error_code = getattr(e, 'errno', None)
                
                # 清理临时文件
                try:
                    if os.path.exists(temp_content_file):
                        os.remove(temp_content_file)
                except:
                    pass
                
                if error_code == errno.EIO:  # Input/output error
                    logger.error(f"写入内容文件I/O错误 (尝试 {attempt + 1}/{max_retries}): {content_file}, 错误: {e}")
                    if attempt < max_retries - 1:
                        time.sleep(retry_delay * (attempt + 1))
                        continue
                    else:
                        # 检查磁盘空间
                        try:
                            import shutil
                            stat = shutil.disk_usage(os.path.dirname(content_file))
                            free_gb = stat.free / (1024**3)
                            logger.error(f"磁盘可用空间: {free_gb:.2f} GB")
                            if free_gb < 0.1:
                                return None, "磁盘空间不足，无法保存公告内容"
                        except:
                            pass
                        logger.error(f"写入内容文件最终失败: {content_file}")
                        return None, f"保存公告内容失败: {str(e)}"
                else:
                    logger.error(f"写入内容文件失败: {content_file}, 错误: {e}")
                    return None, f"保存公告内容失败: {str(e)}"
            except Exception as e:
                logger.error(f"写入内容文件异常: {content_file}, 错误: {e}", exc_info=True)
                return None, f"保存公告内容失败: {str(e)}"
        else:
            # 所有重试都失败
            return None, "保存公告内容失败：多次重试后仍失败"
        
        # 保存附件
        if attachments:
            saved_attachments = self._save_attachments(announcement_path, attachments)
            metadata['attachments'] = saved_attachments
            # 更新元数据
            self._write_metadata(announcement_path, metadata)
        
        print(f"公告创建成功: {announcement_id}")
        return announcement_id, "公告创建成功"
    
    def _save_version(self, announcement_id, metadata, announcement_path):
        """保存公告的历史版本（备份HTML和附件到versions目录）
        
        历史版本保存在：announcement_path/versions/version_number/
        与最新公告存储在同一文件夹结构内，方便查看
        
        重要说明：
        - 没有版本数量限制：系统会保存所有历史版本，不会自动删除任何版本
        - 支持长期溯源：所有历史版本都会永久保存，方便多年后追溯历史记录
        - 版本号格式：使用发布时间作为版本号（YYYY-MM-DDTHH:MM:SS），确保唯一性
        - 存储内容：每个版本包含完整的元数据、内容文件和附件目录
        """
        # 创建版本目录（在公告主目录下的versions子目录）
        versions_dir = os.path.join(announcement_path, 'versions')
        os.makedirs(versions_dir, exist_ok=True)
        
        # 使用发布时间作为版本号（格式：YYYY-MM-DDTHH:MM:SS）
        publish_time = metadata.get('publish_time')
        if not publish_time:
            # 如果没有发布时间，使用更新时间
            publish_time = metadata.get('updated_time') or metadata.get('created_time')
        
        # 将时间字符串转换为版本号（移除毫秒和时区信息）
        try:
            # 处理ISO格式时间字符串
            time_str = publish_time.replace('Z', '+00:00')
            # 移除毫秒部分（如果有）
            if '.' in time_str:
                time_str = time_str.split('.')[0]
                if '+' in time_str or time_str.endswith('Z'):
                    # 保留时区信息
                    if '+' in time_str:
                        time_str = time_str.split('+')[0]
                    elif time_str.endswith('Z'):
                        time_str = time_str[:-1]
            version_time = datetime.fromisoformat(time_str)
            # 格式化为版本号：YYYY-MM-DDTHH:MM:SS
            version_number = version_time.strftime('%Y-%m-%dT%H:%M:%S')
        except Exception as e:
            # 如果解析失败，使用当前时间
            print(f"解析发布时间失败: {e}, 使用当前时间作为版本号")
            version_number = datetime.now().strftime('%Y-%m-%dT%H:%M:%S')
        
        # 检查版本是否已存在（避免重复保存）
        # 重要：系统不会删除已存在的版本，也不会限制版本数量
        # 所有历史版本都会永久保存，支持长期溯源
        version_path = os.path.join(versions_dir, version_number)
        if os.path.exists(version_path):
            print(f"历史版本已存在，跳过保存: {announcement_id}, 版本号: {version_number}")
            return True
        
        os.makedirs(version_path, exist_ok=True)
        
        # 保存版本元数据
        version_metadata = metadata.copy()
        version_metadata['version'] = version_number
        version_metadata['saved_at'] = datetime.now().isoformat()
        
        if not self._write_metadata(version_path, version_metadata):
            print(f"保存版本元数据失败: {version_path}")
            return False
        
        # 复制内容文件（HTML）
        content_file = os.path.join(announcement_path, 'content.html')
        if os.path.exists(content_file):
            version_content_file = os.path.join(version_path, 'content.html')
            try:
                shutil.copy2(content_file, version_content_file)
                print(f"已备份内容文件: {content_file} -> {version_content_file}")
            except Exception as e:
                print(f"复制内容文件失败: {e}")
                return False
        else:
            print(f"警告: 内容文件不存在: {content_file}")
        
        # 复制附件目录
        attachments_dir = os.path.join(announcement_path, 'attachments')
        if os.path.exists(attachments_dir):
            version_attachments_dir = os.path.join(version_path, 'attachments')
            try:
                if os.path.exists(version_attachments_dir):
                    shutil.rmtree(version_attachments_dir)
                shutil.copytree(attachments_dir, version_attachments_dir)
                print(f"已备份附件目录: {attachments_dir} -> {version_attachments_dir}")
            except Exception as e:
                print(f"复制附件目录失败: {e}")
                # 附件复制失败不影响版本保存
        else:
            # 如果没有附件目录，创建一个空的
            version_attachments_dir = os.path.join(version_path, 'attachments')
            os.makedirs(version_attachments_dir, exist_ok=True)
        
        print(f"✅ 已保存历史版本: {announcement_id}, 版本号: {version_number}, 路径: {version_path}")
        
        # 如果启用了版本数量限制，清理超出限制的旧版本
        if MAX_VERSION_HISTORY > 0:
            self._cleanup_old_versions(announcement_path, versions_dir)
        
        return True
    
    def _cleanup_old_versions(self, announcement_path: str, versions_dir: str):
        """清理超出限制的旧版本
        
        Args:
            announcement_path: 公告主目录路径
            versions_dir: 版本目录路径
        """
        try:
            if not os.path.exists(versions_dir):
                return
            
            # 获取所有版本目录
            version_dirs = []
            for item in os.listdir(versions_dir):
                version_path = os.path.join(versions_dir, item)
                if os.path.isdir(version_path):
                    # 尝试从版本号或保存时间获取时间戳
                    version_time = None
                    try:
                        # 版本号格式：YYYY-MM-DDTHH:MM:SS
                        version_time = datetime.fromisoformat(item.replace('T', ' '))
                    except:
                        # 如果解析失败，使用目录修改时间
                        try:
                            version_time = datetime.fromtimestamp(os.path.getmtime(version_path))
                        except:
                            pass
                    
                    if version_time:
                        version_dirs.append((item, version_path, version_time))
            
            # 按时间排序（最旧的在前）
            version_dirs.sort(key=lambda x: x[2])
            
            # 如果版本数量超过限制，删除最旧的版本
            if len(version_dirs) > MAX_VERSION_HISTORY:
                delete_count = len(version_dirs) - MAX_VERSION_HISTORY
                for i in range(delete_count):
                    version_name, version_path, version_time = version_dirs[i]
                    try:
                        shutil.rmtree(version_path)
                        logger.info(f"已删除旧版本: {version_name} (保留 {MAX_VERSION_HISTORY} 个最新版本)")
                    except Exception as e:
                        logger.warning(f"删除旧版本失败 {version_name}: {e}")
                
                logger.info(f"版本清理完成: 删除了 {delete_count} 个旧版本，保留了 {MAX_VERSION_HISTORY} 个最新版本")
        except Exception as e:
            logger.error(f"清理旧版本失败: {e}", exc_info=True)
    
    def get_all_history_versions(self):
        """获取所有公告的历史版本列表
        
        遍历所有公告栏，收集所有公告的所有历史版本。
        用于"历史公告"文件夹功能，方便用户查看所有历史版本。
        
        注意：
        - 返回所有历史版本，没有数量限制
        - 支持长期溯源，不会自动删除任何历史记录
        
        Returns:
            List[Dict]: 所有历史版本的列表，每个版本包含公告信息和版本信息
        """
        all_versions = []
        
        try:
            # 遍历所有公告栏
            for board_id in self._get_all_board_ids():
                try:
                    board_path = os.path.join(self.base_dir, board_id)
                    if not os.path.exists(board_path):
                        continue
                    
                    # 遍历该公告栏下的所有公告
                    try:
                        items = os.listdir(board_path)
                    except (OSError, PermissionError) as e:
                        logger.warning(f"无法读取公告栏目录 {board_path}: {e}")
                        continue
                    
                    for item_name in items:
                        try:
                            item_path = os.path.join(board_path, item_name)
                            if not os.path.isdir(item_path):
                                continue
                            
                            # 检查是否有versions目录
                            versions_dir = os.path.join(item_path, 'versions')
                            if not os.path.exists(versions_dir):
                                continue
                            
                            # 读取公告基本信息
                            try:
                                announcement_metadata = self._read_metadata(item_path)
                                if not announcement_metadata:
                                    continue
                            except Exception as e:
                                logger.warning(f"读取公告元数据失败 {item_path}: {e}")
                                continue
                            
                            # 遍历该公告的所有历史版本
                            try:
                                version_names = os.listdir(versions_dir)
                            except (OSError, PermissionError) as e:
                                logger.warning(f"无法读取版本目录 {versions_dir}: {e}")
                                continue
                            
                            for version_name in version_names:
                                try:
                                    version_path = os.path.join(versions_dir, version_name)
                                    if not os.path.isdir(version_path):
                                        continue
                                    
                                    try:
                                        version_metadata = self._read_metadata(version_path)
                                        if version_metadata:
                                            # 合并公告信息和版本信息
                                            version_info = {
                                                'announcement_id': announcement_metadata.get('id', item_name),
                                                'announcement_title': announcement_metadata.get('title', ''),
                                                'board_id': board_id,
                                                'board_name': ANNOUNCEMENT_BOARDS.get(board_id, board_id),
                                                'version': version_metadata.get('version', version_name),
                                                'version_title': version_metadata.get('title', ''),
                                                'version_content': version_metadata.get('content', ''),
                                                'publish_time': version_metadata.get('publish_time', version_metadata.get('created_time', '')),
                                                'author': version_metadata.get('author', ''),
                                                'original_author': version_metadata.get('original_author', ''),
                                                'priority': version_metadata.get('priority', 'normal'),
                                                'attachments': version_metadata.get('attachments', [])
                                            }
                                            all_versions.append(version_info)
                                    except Exception as e:
                                        logger.warning(f"读取版本元数据失败 {version_path}: {e}")
                                        continue
                                except Exception as e:
                                    logger.warning(f"处理版本目录失败 {version_name}: {e}")
                                    continue
                        except Exception as e:
                            logger.warning(f"处理公告目录失败 {item_name}: {e}")
                            continue
                except Exception as e:
                    logger.warning(f"处理公告栏失败 {board_id}: {e}")
                    continue
            
            # 按发布时间降序排序
            try:
                all_versions.sort(key=lambda x: x.get('publish_time', ''), reverse=True)
            except Exception as e:
                logger.warning(f"排序历史版本失败: {e}")
                # 即使排序失败，也返回数据
        
        except Exception as e:
            logger.error(f"获取所有历史版本时发生严重错误: {e}", exc_info=True)
            # 返回已收集的版本（如果有的话），而不是空列表
        
        logger.debug(f"获取所有历史版本: 共 {len(all_versions)} 个")
        return all_versions
    
    def get_versions(self, announcement_id):
        """获取公告的所有历史版本
        
        从 announcement_path/versions/ 目录读取所有历史版本
        历史版本与最新公告存储在同一文件夹结构内，方便查看
        
        注意：
        - 返回所有历史版本，没有数量限制
        - 版本按时间降序排列（最新的在前）
        - 每个版本包含完整的元数据、内容和附件信息
        """
        versions = []
        
        # 查找公告路径
        announcement_path = None
        for bid in self._get_all_board_ids():
            temp_path = self._get_announcement_path(bid, announcement_id, False)
            if os.path.exists(temp_path):
                announcement_path = temp_path
                break
        
        if not announcement_path:
            temp_path = self._get_announcement_path('', announcement_id, True)
            if os.path.exists(temp_path):
                announcement_path = temp_path
        
        if not announcement_path:
            print(f"未找到公告路径: {announcement_id}")
            return versions
        
        # 读取版本目录
        versions_dir = os.path.join(announcement_path, 'versions')
        if not os.path.exists(versions_dir):
            print(f"版本目录不存在: {versions_dir}")
            return versions
        
        print(f"读取历史版本目录: {versions_dir}")
        
        # 遍历所有版本目录
        try:
            version_names = os.listdir(versions_dir)
            print(f"找到 {len(version_names)} 个版本目录")
            
            for version_name in version_names:
                version_path = os.path.join(versions_dir, version_name)
                if not os.path.isdir(version_path):
                    continue
                
                version_metadata = self._read_metadata(version_path)
                if version_metadata:
                    # 读取版本内容
                    content_file = os.path.join(version_path, 'content.html')
                    if os.path.exists(content_file):
                        try:
                            with open(content_file, 'r', encoding='utf-8') as f:
                                version_metadata['content'] = f.read()
                        except Exception as e:
                            print(f"读取版本内容失败: {e}")
                            version_metadata['content'] = ''
                    else:
                        version_metadata['content'] = ''
                    
                    # 读取附件列表
                    version_attachments_dir = os.path.join(version_path, 'attachments')
                    if os.path.exists(version_attachments_dir):
                        attachments = []
                        try:
                            for filename in os.listdir(version_attachments_dir):
                                file_path = os.path.join(version_attachments_dir, filename)
                                if os.path.isfile(file_path):
                                    file_size = os.path.getsize(file_path)
                                    attachments.append({
                                        'name': filename,
                                        'size': file_size
                                    })
                        except Exception as e:
                            print(f"读取版本附件失败: {e}")
                        version_metadata['attachments'] = attachments
                    else:
                        version_metadata['attachments'] = []
                    
                    versions.append(version_metadata)
                    print(f"已加载历史版本: {version_name}")
        except Exception as e:
            print(f"读取版本目录失败: {e}")
        
        # 按版本号（发布时间）降序排序
        versions.sort(key=lambda x: x.get('version', ''), reverse=True)
        
        print(f"共加载 {len(versions)} 个历史版本")
        return versions
    
    def get_version(self, announcement_id, version_number):
        """获取指定版本号的公告历史版本详情"""
        # 查找公告路径
        announcement_path = None
        for bid in self._get_all_board_ids():
            temp_path = self._get_announcement_path(bid, announcement_id, False)
            if os.path.exists(temp_path):
                announcement_path = temp_path
                break
        
        if not announcement_path:
            temp_path = self._get_announcement_path('', announcement_id, True)
            if os.path.exists(temp_path):
                announcement_path = temp_path
        
        if not announcement_path:
            return None
        
        # 读取版本目录
        versions_dir = os.path.join(announcement_path, 'versions')
        if not os.path.exists(versions_dir):
            return None
        
        # 查找指定版本
        version_path = os.path.join(versions_dir, version_number)
        if not os.path.exists(version_path) or not os.path.isdir(version_path):
            return None
        
        version_metadata = self._read_metadata(version_path)
        if version_metadata:
            # 读取版本内容
            content_file = os.path.join(version_path, 'content.html')
            if os.path.exists(content_file):
                try:
                    with open(content_file, 'r', encoding='utf-8') as f:
                        version_metadata['content'] = f.read()
                except Exception as e:
                    print(f"读取版本内容失败: {e}")
                    version_metadata['content'] = ''
            
            # 读取附件列表
            attachments_dir = os.path.join(version_path, 'attachments')
            if os.path.exists(attachments_dir):
                attachments = []
                try:
                    for filename in os.listdir(attachments_dir):
                        file_path = os.path.join(attachments_dir, filename)
                        if os.path.isfile(file_path):
                            file_size = os.path.getsize(file_path)
                            attachments.append({
                                'name': filename,
                                'size': file_size,
                                'type': 'application/octet-stream'
                            })
                    version_metadata['attachments'] = attachments
                except Exception as e:
                    print(f"读取版本附件失败: {e}")
                    version_metadata['attachments'] = []
            else:
                version_metadata['attachments'] = []
        
        return version_metadata
    
    def update_announcement(self, announcement_id, board_id=None, editor=None, **updates):
        """更新公告（带文件锁保护，防止并发编辑冲突）
        
        Args:
            announcement_id: 公告ID
            board_id: 公告栏ID（可选）
            editor: 编辑人（可选，用于记录最后编辑人）
            **updates: 要更新的字段（包括content, title, attachments等）
        """
        if 'title' in updates:
            updates['title'] = sanitize_announcement_title(updates.get('title'))
        if 'content' in updates:
            updates['content'] = sanitize_announcement_content(updates.get('content'))

        # 获取线程锁（防止同一进程内并发编辑）
        thread_lock = self._get_file_lock(announcement_id)
        
        with thread_lock:
            # 首先在正式目录查找
            metadata = None
            announcement_path = None
            
            for bid in self._get_all_board_ids():
                temp_path = self._get_announcement_path(bid, announcement_id, False)
                temp_metadata = self._read_metadata(temp_path)
                if temp_metadata:
                    metadata = temp_metadata
                    announcement_path = temp_path
                    break
            
            # 在临时目录查找（需要搜索所有用户目录）
            if not metadata:
                temp_path = os.path.join(self.base_dir, self.temp_dir)
                if os.path.exists(temp_path):
                    # 先尝试旧格式：temp/{announcement_id}
                    announcement_path = os.path.join(temp_path, announcement_id)
                    metadata = self._read_metadata(announcement_path)
                    if metadata:
                        pass  # 找到了，使用这个路径
                    else:
                        # 搜索新格式：temp/{user_id}/{announcement_id}
                        for user_dir in os.listdir(temp_path):
                            user_dir_path = os.path.join(temp_path, user_dir)
                            if os.path.isdir(user_dir_path):
                                announcement_path = os.path.join(user_dir_path, announcement_id)
                                metadata = self._read_metadata(announcement_path)
                                if metadata:
                                    break  # 找到了，使用这个路径
            
            if not metadata:
                return False, "公告不存在"
            
            # 获取文件锁（防止跨进程并发编辑）
            # 注意：如果文件锁不可用（如某些系统），仍然使用线程锁保护
            lock_fd = None
            if announcement_path:
                lock_fd = self._acquire_metadata_lock(announcement_path)
                # 如果文件锁获取失败，但不为None（表示系统不支持），仍然继续（线程锁仍然有效）
                # 如果返回None且系统支持文件锁，说明有其他进程正在编辑
                if lock_fd is None and (HAS_FCNTL or HAS_MSVCRT):
                    self._release_metadata_lock(lock_fd)  # 确保释放锁
                    return False, "公告正在被其他进程编辑，请稍后重试"
            
            try:
                # 记录旧状态（在更新之前）
                old_status = metadata.get('status')
                
                # 如果公告是已发布状态，且正在编辑（有内容或标题更新），创建待审批副本
                if old_status == 'approved' and announcement_path:
                    # 检查是否有实际的内容更新
                    has_content_update = 'content' in updates or 'title' in updates or 'attachments' in updates
                    if has_content_update:
                        print(f"检测到已发布公告被编辑，创建待审批副本: {announcement_id}")
                        print(f"  原公告路径: {announcement_path}")
                        
                        # 读取当前内容（在更新之前保存，确保保存的是编辑前的版本）
                        content_file = os.path.join(announcement_path, 'content.html')
                        if os.path.exists(content_file):
                            try:
                                with open(content_file, 'r', encoding='utf-8') as f:
                                    current_content = f.read()
                                metadata['content'] = current_content
                                print(f"  已读取当前内容，长度: {len(current_content)} 字符")
                            except Exception as e:
                                print(f"  读取当前内容失败: {e}")
                        
                        # 保存当前版本为历史版本（备份HTML和附件）
                        # 历史版本保存在 announcement_path/versions/version_number/ 目录下
                        success = self._save_version(announcement_id, metadata, announcement_path)
                        if success:
                            print(f"  ✅ 历史版本保存成功: {announcement_id}")
                        else:
                            print(f"  ⚠️ 历史版本保存失败: {announcement_id}")
                        
                        # 创建待审批副本到temp目录（原公告保持approved状态不变）
                        # 获取editor的user_id（如果有），用于组织temp目录
                        editor_user_id = None
                        if editor:
                            # 尝试从editor名称获取user_id（这里可能需要从user_manager获取）
                            # 暂时使用None，使用旧格式temp/{announcement_id}
                            pass
                        
                        # 创建temp目录下的副本路径
                        temp_base = os.path.join(self.base_dir, self.temp_dir)
                        os.makedirs(temp_base, exist_ok=True)
                        temp_announcement_path = os.path.join(temp_base, announcement_id)
                        
                        # 如果temp目录下已存在，先删除
                        if os.path.exists(temp_announcement_path):
                            shutil.rmtree(temp_announcement_path)
                        
                        # 复制整个公告目录到temp
                        try:
                            shutil.copytree(announcement_path, temp_announcement_path)
                            print(f"  ✅ 已创建待审批副本到: {temp_announcement_path}")
                        except Exception as e:
                            print(f"  ⚠️ 创建待审批副本失败: {e}")
                            self._release_metadata_lock(lock_fd)
                            return False, f"创建待审批副本失败: {str(e)}"
                        
                        # 更新副本的元数据：状态改为pending，添加编辑信息
                        temp_metadata = metadata.copy()
                        temp_metadata['status'] = 'pending'
                        temp_metadata['updated_time'] = datetime.now().isoformat()
                        if editor:
                            temp_metadata['last_editor'] = editor
                            temp_metadata['last_edit_time'] = datetime.now().isoformat()
                        
                        # 将更新应用到副本的元数据
                        for key, value in updates.items():
                            if key != 'attachments':  # 附件稍后单独处理
                                temp_metadata[key] = value
                        
                        # 保存副本的元数据
                        if not self._write_metadata(temp_announcement_path, temp_metadata):
                            print(f"  ⚠️ 保存待审批副本元数据失败")
                            self._release_metadata_lock(lock_fd)
                            return False, "保存待审批副本元数据失败"
                        
                        # 更新副本的内容文件（如果有）
                        if 'content' in updates:
                            temp_content_file = os.path.join(temp_announcement_path, 'content.html')
                            try:
                                with open(temp_content_file, 'w', encoding='utf-8') as f:
                                    f.write(updates['content'])
                                print(f"  ✅ 已更新待审批副本内容")
                            except Exception as e:
                                print(f"  ⚠️ 更新待审批副本内容失败: {e}")
                        
                        # 处理附件（如果需要更新）
                        if 'attachments' in updates:
                            # 这里可以处理附件更新，暂时跳过，使用原附件
                            pass
                        
                        # 原公告保持不变（approved状态），返回成功
                        print(f"  ✅ 原公告保持approved状态，待审批副本已创建")
                        self._release_metadata_lock(lock_fd)
                        return True, "已创建待审批副本，原公告保持不变"
                
                # 记录发起人（如果还没有记录）
                if 'original_author' not in metadata or not metadata.get('original_author'):
                    metadata['original_author'] = metadata.get('author', '')
                
                # 记录最后编辑人
                if editor:
                    metadata['last_editor'] = editor
                    metadata['last_edit_time'] = datetime.now().isoformat()
                
                # 更新字段
                for key, value in updates.items():
                    if key == 'attachments':
                        # 附件单独处理
                        continue
                    metadata[key] = value
                
                metadata['updated_time'] = datetime.now().isoformat()
                
                # 获取新状态（更新后的状态）
                new_status = metadata.get('status', old_status)
                
                # 如果编辑已发布公告，强制状态为pending（不允许直接发布）
                # 但只有在实际更新了内容（content、title、attachments）时才改变状态
                # 如果只是更新元数据字段（如todo_source_id），不改变状态
                has_content_update = 'content' in updates or 'title' in updates or 'attachments' in updates
                if old_status == 'approved' and new_status == 'approved' and has_content_update:
                    new_status = 'pending'
                    metadata['status'] = 'pending'
                    print(f"警告: 已发布公告被编辑，状态强制改为pending，不允许直接发布: {announcement_id}")
                
                # 如果状态变为已发布，设置发布时间（但编辑已发布公告时不会到这里）
                if new_status == 'approved' and not metadata.get('publish_time'):
                    metadata['publish_time'] = datetime.now().isoformat()
                
                # 重新确定存储路径（如果公告栏或状态发生变化）
                new_board_id = board_id or metadata.get('board_id')
                is_temp_old = old_status in ['draft', 'pending']
                is_temp_new = new_status in ['draft', 'pending']
                
                # 需要移动公告的情况：
                # 1. 公告栏发生变化
                # 2. 状态从 draft/pending 变为 approved（需要从temp移动到正式目录）
                # 3. 状态从 approved 变为 draft/pending（需要从正式目录移动到temp）
                #    BUT: 如果是编辑已发布公告（有历史版本），不移动，保留在原位置，只改变状态
                #    这样审批拒绝时可以恢复，审批通过时才替换
                need_move = False
                is_editing_approved = (old_status == 'approved' and new_status == 'pending' and has_content_update)
                
                if new_board_id != metadata.get('board_id'):
                    need_move = True
                elif is_temp_old != is_temp_new and not is_editing_approved:
                    # 编辑已发布公告时，不移动，保留在原位置
                    need_move = True
                
                if need_move:
                    old_path = announcement_path
                    new_path = self._get_announcement_path(new_board_id, announcement_id, is_temp_new)
                    
                    if old_path != new_path:
                        # 确保目标目录存在
                        os.makedirs(os.path.dirname(new_path), exist_ok=True)
                        
                        if os.path.exists(new_path):
                            shutil.rmtree(new_path)
                        
                        # 移动公告目录
                        if os.path.exists(old_path):
                            shutil.move(old_path, new_path)
                            announcement_path = new_path
                            print(f"公告已移动: {old_path} -> {new_path}")
                        else:
                            print(f"警告: 源路径不存在 {old_path}")
                        
                        if new_board_id != metadata.get('board_id'):
                            metadata['board_id'] = new_board_id
                
                # 处理附件上传
                if 'attachments' in updates:
                    # 分离新上传的附件（有data且不为null）和已有附件（data为null或不存在）
                    new_attachments = [att for att in updates['attachments'] if att.get('data') and att.get('data') is not None]
                    existing_attachment_refs = [att for att in updates['attachments'] if not att.get('data') or att.get('data') is None]
                    
                    # 获取现有附件列表
                    existing_attachments = metadata.get('attachments', [])
                    existing_attachment_names = {att.get('name') for att in existing_attachments}
                    
                    # 保存新上传的附件
                    saved_attachments = []
                    if new_attachments:
                        saved_attachments = self._save_attachments(announcement_path, new_attachments)
                        print(f"新上传附件: {len(saved_attachments)} 个")
                    
                    # 合并已有附件（从前端传递的引用或现有附件中）
                    saved_attachment_names = {att.get('name') for att in saved_attachments}
                    referenced_names = {ref.get('name') for ref in existing_attachment_refs}
                    
                    # 添加已有附件（如果不在新上传列表中）
                    for existing_att in existing_attachments:
                        if existing_att.get('name') not in saved_attachment_names:
                            # 如果被前端引用，或者没有新附件，则保留
                            if existing_att.get('name') in referenced_names or not new_attachments:
                                saved_attachments.append(existing_att)
                    
                    metadata['attachments'] = saved_attachments
                    total_kept = len(saved_attachments) - len(new_attachments)
                    print(f"附件已更新: 共 {len(saved_attachments)} 个附件（新上传 {len(new_attachments)} 个，保留 {total_kept} 个）")
                
                # 保存更新后的元数据
                if not self._write_metadata(announcement_path, metadata):
                    self._release_metadata_lock(lock_fd)
                    return False, "更新公告失败"
                
                # 更新内容文件
                if 'content' in updates:
                    content_file = os.path.join(announcement_path, 'content.html')
                    try:
                        with open(content_file, 'w', encoding='utf-8') as f:
                            f.write(updates['content'])
                    except Exception as e:
                        print(f"更新内容文件失败: {e}")
                        self._release_metadata_lock(lock_fd)
                        return False, "更新公告内容失败"
                
                # 释放文件锁
                self._release_metadata_lock(lock_fd)
                return True, "公告更新成功"
            
            except Exception as e:
                # 发生异常时也要释放锁
                if lock_fd:
                    self._release_metadata_lock(lock_fd)
                print(f"更新公告时发生异常: {e}")
                import traceback
                traceback.print_exc()
                return False, f"更新公告失败: {str(e)}"
    
    def get_announcement(self, announcement_id):
        """获取单个公告详情
        
        优先查找temp目录中的待审批版本（编辑已发布公告时创建的副本），
        如果不存在，再查找正式目录中的已发布版本。
        这样可以确保审批页面显示的是最新的编辑内容。
        """
        # 优先在临时目录查找（编辑已发布公告时创建的待审批副本）
        temp_path = os.path.join(self.base_dir, self.temp_dir)
        if os.path.exists(temp_path):
            # 先尝试旧格式：temp/{announcement_id}
            announcement_path = os.path.join(temp_path, announcement_id)
            metadata = self._read_metadata(announcement_path)
            if metadata:
                content_file = os.path.join(announcement_path, 'content.html')
                if os.path.exists(content_file):
                    try:
                        with open(content_file, 'r', encoding='utf-8') as f:
                            metadata['content'] = f.read()
                    except Exception as e:
                        print(f"读取内容文件失败: {e}")
                        metadata['content'] = ''
                # 标记这是待审批版本
                metadata['_is_pending_review'] = True
                return metadata
        
            # 搜索新格式：temp/{user_id}/{announcement_id}
            for user_dir in os.listdir(temp_path):
                user_dir_path = os.path.join(temp_path, user_dir)
                if os.path.isdir(user_dir_path):
                    announcement_path = os.path.join(user_dir_path, announcement_id)
                    metadata = self._read_metadata(announcement_path)
                    if metadata:
                        content_file = os.path.join(announcement_path, 'content.html')
                        if os.path.exists(content_file):
                            try:
                                with open(content_file, 'r', encoding='utf-8') as f:
                                    metadata['content'] = f.read()
                            except Exception as e:
                                print(f"读取内容文件失败: {e}")
                                metadata['content'] = ''
                        # 标记这是待审批版本
                        metadata['_is_pending_review'] = True
                        return metadata
        
        # 在正式目录查找（如果temp目录中没有）
        for board_id in self._get_all_board_ids():
            announcement_path = self._get_announcement_path(board_id, announcement_id, False)
            metadata = self._read_metadata(announcement_path)
            if metadata:
                # 读取内容
                content_file = os.path.join(announcement_path, 'content.html')
                if os.path.exists(content_file):
                    try:
                        with open(content_file, 'r', encoding='utf-8') as f:
                            metadata['content'] = f.read()
                    except Exception as e:
                        print(f"读取内容文件失败: {e}")
                        metadata['content'] = ''
                return metadata
        
        return None
    
    def get_announcements(self, board_id=None, status=None, include_temp=False, sub_board_id=None):
        """获取公告列表
        
        重要：当查询approved状态的公告时，如果temp目录中有相同ID的pending副本（编辑已发布公告时创建），
        应该只返回正式目录中的approved版本，不返回temp目录中的pending副本。
        这样可以确保已发布公告在再次提交审核后，主页仍然显示原版本。
        """
        announcements = []
        approved_ids = set()  # 记录已找到的approved公告ID，用于去重
        
        # 如果指定了board_id，需要搜索所有目录并检查元数据
        # 这样可以找到那些可能被错误放置的公告
        if board_id:
            # 搜索所有公告栏目录
            for bid in self._get_all_board_ids():
                try:
                    board_path = os.path.join(self.base_dir, bid)
                    if not os.path.exists(board_path):
                        continue
                    
                    try:
                        items = os.listdir(board_path)
                    except (OSError, PermissionError) as e:
                        logger.warning(f"无法读取公告栏目录 {board_path}: {e}")
                        continue
                    
                    for item in items:
                        try:
                            item_path = os.path.join(board_path, item)
                            if os.path.isdir(item_path):
                                try:
                                    metadata = self._read_metadata(item_path)
                                    if metadata:
                                        # 检查元数据中的board_id是否匹配
                                        if metadata.get('board_id') == board_id:
                                            # 检查二级公告栏过滤
                                            if sub_board_id and metadata.get('sub_board_id') != sub_board_id:
                                                continue
                                            
                                            # 检查状态过滤
                                            ann_status = metadata.get('status')
                                            ann_id = metadata.get('id')
                                            
                                            # 如果是approved状态，记录ID（用于后续去重temp目录中的pending副本）
                                            if ann_status == 'approved' and ann_id:
                                                approved_ids.add(ann_id)
                                            
                                            if status is None or ann_status == status:
                                                announcements.append(metadata)
                                except Exception as e:
                                    logger.warning(f"读取公告元数据失败 {item_path}: {e}")
                                    continue
                        except Exception as e:
                            logger.warning(f"处理公告目录失败 {item}: {e}")
                            continue
                except Exception as e:
                    logger.warning(f"处理公告栏失败 {bid}: {e}")
                    continue
        else:
            # 如果没有指定board_id，搜索所有目录
            for bid in self._get_all_board_ids():
                try:
                    board_path = os.path.join(self.base_dir, bid)
                    if not os.path.exists(board_path):
                        continue
                    
                    try:
                        items = os.listdir(board_path)
                    except (OSError, PermissionError) as e:
                        logger.warning(f"无法读取公告栏目录 {board_path}: {e}")
                        continue
                    
                    for item in items:
                        try:
                            item_path = os.path.join(board_path, item)
                            if os.path.isdir(item_path):
                                try:
                                    metadata = self._read_metadata(item_path)
                                    if metadata:
                                        # 检查二级公告栏过滤
                                        if sub_board_id and metadata.get('sub_board_id') != sub_board_id:
                                            continue
                                        
                                        # 检查状态过滤
                                        ann_status = metadata.get('status')
                                        ann_id = metadata.get('id')
                                        
                                        # 如果是approved状态，记录ID（用于后续去重temp目录中的pending副本）
                                        if ann_status == 'approved' and ann_id:
                                            approved_ids.add(ann_id)
                                        
                                        if status is None or ann_status == status:
                                            announcements.append(metadata)
                                except Exception as e:
                                    logger.warning(f"读取公告元数据失败 {item_path}: {e}")
                                    continue
                        except Exception as e:
                            logger.warning(f"处理公告目录失败 {item}: {e}")
                            continue
                except Exception as e:
                    logger.warning(f"处理公告栏失败 {bid}: {e}")
                    continue
        
        # 搜索临时公告（如果需要）
        if include_temp:
            try:
                temp_path = os.path.join(self.base_dir, self.temp_dir)
                if os.path.exists(temp_path):
                    try:
                        items = os.listdir(temp_path)
                    except (OSError, PermissionError) as e:
                        logger.warning(f"无法读取临时目录 {temp_path}: {e}")
                        items = []
                    
                    for item in items:
                        try:
                            item_path = os.path.join(temp_path, item)
                            if not os.path.isdir(item_path):
                                continue
                            
                            # 检查是否是用户目录（按用户ID组织的草稿）
                            # 如果是用户目录，需要递归搜索其子目录
                            if item.isdigit() or (isinstance(item, str) and item.replace('-', '').isdigit()):
                                # 可能是用户ID目录，递归搜索
                                try:
                                    sub_items = os.listdir(item_path)
                                except (OSError, PermissionError) as e:
                                    logger.warning(f"无法读取用户目录 {item_path}: {e}")
                                    continue
                                
                                for sub_item in sub_items:
                                    try:
                                        sub_item_path = os.path.join(item_path, sub_item)
                                        if os.path.isdir(sub_item_path):
                                            try:
                                                metadata = self._read_metadata(sub_item_path)
                                                if metadata:
                                                    ann_id = metadata.get('id')
                                                    ann_status = metadata.get('status')
                                                    
                                                    # 重要：如果查询approved状态，且temp目录中有相同ID的pending副本（编辑已发布公告时创建），
                                                    # 应该跳过，因为正式目录中已经有approved版本了
                                                    if status == 'approved' and ann_id in approved_ids:
                                                        continue
                                                    
                                                    # 如果指定了board_id，需要检查元数据中的board_id是否匹配
                                                    if board_id and metadata.get('board_id') != board_id:
                                                        continue
                                                    
                                                    # 检查二级公告栏过滤
                                                    if sub_board_id and metadata.get('sub_board_id') != sub_board_id:
                                                        continue
                                                    
                                                    # 检查状态过滤
                                                    if status is None or ann_status == status:
                                                        announcements.append(metadata)
                                            except Exception as e:
                                                logger.warning(f"读取临时公告元数据失败 {sub_item_path}: {e}")
                                                continue
                                    except Exception as e:
                                        logger.warning(f"处理临时公告子目录失败 {sub_item}: {e}")
                                        continue
                            else:
                                # 旧格式：直接在temp目录下的公告（兼容旧数据）
                                try:
                                    metadata = self._read_metadata(item_path)
                                    if metadata:
                                        ann_id = metadata.get('id')
                                        ann_status = metadata.get('status')
                                        
                                        # 重要：如果查询approved状态，且temp目录中有相同ID的pending副本（编辑已发布公告时创建），
                                        # 应该跳过，因为正式目录中已经有approved版本了
                                        if status == 'approved' and ann_id in approved_ids:
                                            continue
                                        
                                        # 如果指定了board_id，需要检查元数据中的board_id是否匹配
                                        if board_id and metadata.get('board_id') != board_id:
                                            continue
                                        
                                        # 检查二级公告栏过滤
                                        if sub_board_id and metadata.get('sub_board_id') != sub_board_id:
                                            continue
                                        
                                        # 检查状态过滤
                                        if status is None or ann_status == status:
                                            announcements.append(metadata)
                                except Exception as e:
                                    logger.warning(f"读取临时公告元数据失败 {item_path}: {e}")
                                    continue
                        except Exception as e:
                            logger.warning(f"处理临时目录项失败 {item}: {e}")
                            continue
            except Exception as e:
                logger.warning(f"搜索临时公告时发生错误: {e}")
                # 继续执行，返回已收集的公告
        
        # 按时间排序
        try:
            announcements.sort(key=lambda x: x.get('publish_time') or x.get('created_time'), reverse=True)
        except Exception as e:
            logger.warning(f"排序公告列表失败: {e}")
            # 即使排序失败，也返回数据
        
        # 减少日志输出（高并发下print会影响性能）
        # print(f"获取公告列表: board={board_id}, sub_board={sub_board_id}, status={status}, include_temp={include_temp}, 找到{len(announcements)}条")
        return announcements
    
    def _safe_rmtree(self, announcement_path):
        """安全删除公告目录（处理 Windows 下 metadata 锁文件等）"""
        import stat
        
        lock_file = os.path.join(announcement_path, 'metadata.json.lock')
        if os.path.exists(lock_file):
            try:
                os.remove(lock_file)
            except OSError as e:
                logger.warning(f"删除锁文件失败 {lock_file}: {e}")
        
        def _onerror(func, path, exc_info):
            try:
                os.chmod(path, stat.S_IWRITE)
                func(path)
            except Exception as e:
                logger.warning(f"删除文件失败 {path}: {e}")
        
        shutil.rmtree(announcement_path, onerror=_onerror)
    
    def _delete_from_temp_dir(self, announcement_id):
        """在临时目录中查找并删除公告（草稿/待审批）"""
        temp_path = os.path.join(self.base_dir, self.temp_dir)
        if not os.path.exists(temp_path):
            return False
        
        # 旧格式：temp/{announcement_id}
        old_format_path = os.path.join(temp_path, announcement_id)
        if os.path.exists(old_format_path):
            self._safe_rmtree(old_format_path)
            return True
        
        # 新格式：temp/{user_id}/{announcement_id}
        try:
            items = os.listdir(temp_path)
        except (OSError, PermissionError) as e:
            logger.warning(f"无法读取临时目录 {temp_path}: {e}")
            return False
        
        for user_dir in items:
            user_dir_path = os.path.join(temp_path, user_dir)
            if not os.path.isdir(user_dir_path):
                continue
            announcement_path = os.path.join(user_dir_path, announcement_id)
            if os.path.exists(announcement_path):
                self._safe_rmtree(announcement_path)
                return True
        
        return False
    
    def _delete_from_formal_dirs(self, announcement_id):
        """在正式公告栏目录中查找并删除公告"""
        for board_id in self._get_all_board_ids():
            announcement_path = self._get_announcement_path(board_id, announcement_id, False)
            if os.path.exists(announcement_path):
                self._safe_rmtree(announcement_path)
                return True
        return False
    
    def delete_announcement(self, announcement_id, soft_delete=None):
        """删除公告
        
        Args:
            announcement_id: 公告ID
            soft_delete: 是否软删除（移动到回收站）。如果为None，则根据ENABLE_RECYCLE_BIN配置决定。
                        对于草稿（draft状态），通常直接删除，不使用软删除。
        
        Returns:
            (success, message) 元组
        """
        if soft_delete is None:
            soft_delete = ENABLE_RECYCLE_BIN
        
        announcement = self.get_announcement(announcement_id)
        status = announcement.get('status', '') if announcement else ''
        is_temp_status = status in ('draft', 'pending')
        if is_temp_status:
            soft_delete = False
        
        try:
            # 草稿/待审批优先从 temp 目录删除
            if is_temp_status:
                if self._delete_from_temp_dir(announcement_id):
                    return True, "公告删除成功"
                if self._delete_from_formal_dirs(announcement_id):
                    return True, "公告删除成功"
            else:
                if self._delete_from_formal_dirs(announcement_id):
                    msg = "公告删除成功（软删除功能暂未实现）" if soft_delete else "公告删除成功"
                    return True, msg
                if self._delete_from_temp_dir(announcement_id):
                    return True, "公告删除成功"
        except Exception as e:
            logger.error(f"删除公告失败 {announcement_id}: {e}", exc_info=True)
            return False, f"删除公告失败: {str(e)}"
        
        return False, "公告不存在"
    
    def approve_announcement(self, announcement_id, approve=True, comment=None, approver=None):
        """审批公告"""
        # 首先在临时目录查找待审批公告（可能是新公告或编辑已发布公告的副本）
        metadata = None
        announcement_path = None
        is_editing_approved = False
        original_announcement_path = None  # 原公告路径（如果是编辑已发布公告）
        
        temp_path = os.path.join(self.base_dir, self.temp_dir)
        if os.path.exists(temp_path):
            # 先尝试旧格式：temp/{announcement_id}
            temp_announcement_path = os.path.join(temp_path, announcement_id)
            if os.path.exists(temp_announcement_path):
                temp_metadata = self._read_metadata(temp_announcement_path)
                if temp_metadata and temp_metadata.get('status') == 'pending':
                    metadata = temp_metadata
                    announcement_path = temp_announcement_path
            else:
                # 搜索新格式：temp/{user_id}/{announcement_id}
                for user_dir in os.listdir(temp_path):
                    user_dir_path = os.path.join(temp_path, user_dir)
                    if os.path.isdir(user_dir_path):
                        temp_announcement_path = os.path.join(user_dir_path, announcement_id)
                        if os.path.exists(temp_announcement_path):
                            temp_metadata = self._read_metadata(temp_announcement_path)
                            if temp_metadata and temp_metadata.get('status') == 'pending':
                                metadata = temp_metadata
                                announcement_path = temp_announcement_path
                                break
        
        # 检查是否在正式目录有approved状态的原公告（编辑已发布公告的情况）
        if metadata and metadata.get('board_id'):
            board_id = metadata.get('board_id')
            original_path = self._get_announcement_path(board_id, announcement_id, False)
            if os.path.exists(original_path):
                original_metadata = self._read_metadata(original_path)
                if original_metadata and original_metadata.get('status') == 'approved':
                    is_editing_approved = True
                    original_announcement_path = original_path
                    print(f"检测到编辑已发布公告: 原公告在 {original_path}, 待审批副本在 {announcement_path}")
        
        if not metadata or not announcement_path:
            return False, "待审批公告不存在"
        
        board_id = metadata.get('board_id')
        print(f"审批公告: id={announcement_id}, approve={approve}, board_id={board_id}, approver={approver}, is_editing_approved={is_editing_approved}")
        
        if approve:
            # 验证board_id是否有效
            if not board_id:
                return False, "公告栏ID不能为空"
            board_ids = self._get_all_board_ids()
            if board_id not in board_ids:
                return False, f"无效的公告栏ID: {board_id}"
            
            # 批准公告
            new_status = 'approved'
            target_path = self._get_announcement_path(board_id, announcement_id, False)
            
            if is_editing_approved:
                # 编辑已发布公告的情况：用temp目录的副本替换正式目录的原公告
                print(f"编辑已发布公告审批通过，用副本替换原公告")
                print(f"  原公告路径: {original_announcement_path}")
                print(f"  副本路径: {announcement_path}")
                print(f"  目标路径: {target_path}")
            
                # 先保存原公告为历史版本（如果还没有保存）
                if original_announcement_path and os.path.exists(original_announcement_path):
                    original_metadata = self._read_metadata(original_announcement_path)
                    if original_metadata:
                        # 读取原公告内容
                        original_content_file = os.path.join(original_announcement_path, 'content.html')
                        if os.path.exists(original_content_file):
                            try:
                                with open(original_content_file, 'r', encoding='utf-8') as f:
                                    original_content = f.read()
                                original_metadata['content'] = original_content
                            except Exception as e:
                                print(f"读取原公告内容失败: {e}")
                        
                        # 保存历史版本
                        self._save_version(announcement_id, original_metadata, original_announcement_path)
                
                # 删除原公告
                if os.path.exists(target_path):
                    print(f"删除原公告: {target_path}")
                    shutil.rmtree(target_path)
            else:
                # 新公告的情况：从temp移动到正式目录
                print(f"新公告审批通过，从temp移动到正式目录")
            
            # 确保目标目录存在
            os.makedirs(os.path.dirname(target_path), exist_ok=True)
            
            # 移动/复制公告目录
            if os.path.exists(announcement_path):
                # 如果是编辑已发布公告，使用move；如果是新公告，也使用move
                shutil.move(announcement_path, target_path)
                announcement_path = target_path
                print(f"公告已成功移动到: {target_path}")
            else:
                return False, f"源路径不存在: {announcement_path}"
        else:
            # 拒绝公告
            new_status = 'rejected'
            if is_editing_approved:
                # 编辑已发布公告被拒绝：删除temp目录的副本，原公告保持不变
                print(f"编辑已发布公告审批拒绝，删除待审批副本，原公告保持不变")
                print(f"  删除副本: {announcement_path}")
                if os.path.exists(announcement_path):
                    shutil.rmtree(announcement_path)
                # 原公告保持不变，不需要更新
                print(f"公告审批完成: id={announcement_id}, status=rejected (原公告保持approved)")
                action = "拒绝"
                return True, f"公告已{action}，原公告保持不变"
            else:
                # 新公告被拒绝：状态改为rejected，保留在temp目录
                print(f"新公告审批拒绝，状态改为rejected: {announcement_path}")
        
        # 更新状态
        metadata['status'] = new_status
        metadata['updated_time'] = datetime.now().isoformat()
        if comment:
            metadata['approve_comment'] = comment
        if approver:
            metadata['approver'] = approver
            metadata['approve_time'] = datetime.now().isoformat()
        
        if new_status == 'approved':
            metadata['publish_time'] = datetime.now().isoformat()
        
        # 确保board_id在元数据中正确
        if approve and board_id:
            metadata['board_id'] = board_id
        
        if not self._write_metadata(announcement_path, metadata):
            return False, "更新公告状态失败"
        
        print(f"公告审批完成: id={announcement_id}, status={new_status}, board_id={metadata.get('board_id')}")
        action = "批准" if approve else "拒绝"
        return True, f"公告已{action}"
    
    def get_statistics(self):
        """获取公告统计信息
        
        注意：统计应该与前端显示的公告列表保持一致
        - 总公告数：只统计已发布的公告（status='approved'），不包括草稿
        - 待审批：统计待审批的公告（status='pending'）
        - 今日发布：统计今日发布的已发布公告（status='approved'）
        - 紧急公告：统计已发布的紧急公告（status='approved' 且 priority 为 high 或 urgent）
        """
        try:
            today = datetime.now().date().isoformat()
            
            # 获取已发布的公告（不包括草稿和待审批）
            approved_announcements = self.get_announcements(status='approved', include_temp=False)
            
            # 获取待审批的公告（需要包含temp目录）
            pending_announcements = self.get_announcements(status='pending', include_temp=True)
            
            # 总公告数：只统计已发布的公告
            total = len(approved_announcements)
            
            # 待审批数量
            pending = len(pending_announcements)
            
            # 今日发布的已发布公告数量
            today_count = 0
            for a in approved_announcements:
                try:
                    publish_time = a.get('publish_time')
                    # 确保值不为None且是字符串类型
                    if publish_time is not None and isinstance(publish_time, str) and len(publish_time) > 0:
                        if publish_time.startswith(today):
                            today_count += 1
                except Exception as e:
                    print(f"处理公告日期时出错: {e}, 公告数据: {a}")
                    continue
            
            # 紧急公告：只统计已发布的紧急公告
            urgent = len([a for a in approved_announcements if a.get('priority') in ['high', 'urgent']])
            
            return {
                'total': total,
                'pending': pending,
                'today': today_count,
                'urgent': urgent
            }
        except Exception as e:
            print(f"获取统计信息时出错: {e}")
            import traceback
            traceback.print_exc()
            # 返回默认值，避免系统崩溃
            return {
                'total': 0,
                'pending': 0,
                'today': 0,
                'urgent': 0
            }
    
    def get_version_attachment(self, announcement_id, version_number, filename):
        """获取历史版本附件文件路径
        
        Args:
            announcement_id: 公告ID
            version_number: 版本号
            filename: 文件名
        
        Returns:
            附件文件的完整路径，如果不存在则返回None
        """
        print(f"查找历史版本附件: announcement_id={announcement_id}, version={version_number}, filename={filename}")
        
        # 查找公告路径
        announcement_path = None
        for bid in self._get_all_board_ids():
            temp_path = self._get_announcement_path(bid, announcement_id, False)
            if os.path.exists(temp_path):
                announcement_path = temp_path
                break
        
        if not announcement_path:
            temp_path = self._get_announcement_path('', announcement_id, True)
            if os.path.exists(temp_path):
                announcement_path = temp_path
        
        if not announcement_path:
            print(f"未找到公告路径: {announcement_id}")
            return None
        
        # 查找历史版本附件目录
        versions_dir = os.path.join(announcement_path, 'versions')
        version_path = os.path.join(versions_dir, version_number)
        version_attachments_dir = os.path.join(version_path, 'attachments')
        
        if not os.path.exists(version_attachments_dir):
            print(f"历史版本附件目录不存在: {version_attachments_dir}")
            return None
        
        # 解码URL编码的文件名
        decoded_filename = filename
        try:
            decoded_filename = urllib.parse.unquote(filename)
            if decoded_filename != filename:
                print(f"文件名URL解码: {filename} -> {decoded_filename}")
        except:
            pass
        
        # 尝试多种文件名匹配方式
        for try_filename in [filename, decoded_filename]:
            attachment_path = os.path.join(version_attachments_dir, try_filename)
            if os.path.exists(attachment_path):
                print(f"找到历史版本附件: {attachment_path}")
                return attachment_path
        
        # 列出目录中的所有文件进行精确匹配
        try:
            files = os.listdir(version_attachments_dir)
            print(f"历史版本附件目录中的文件: {files}")
            for file in files:
                if file == filename or file == decoded_filename:
                    attachment_path = os.path.join(version_attachments_dir, file)
                    print(f"找到历史版本附件（精确匹配）: {attachment_path}")
                    return attachment_path
        except Exception as e:
            print(f"列出历史版本附件目录失败: {e}")
        
        print(f"历史版本附件未找到: {filename}")
        return None

    def _is_temp_announcement_path(self, announcement_path: str) -> bool:
        norm = os.path.normpath(announcement_path)
        temp_root = os.path.normpath(os.path.join(self.base_dir, self.temp_dir))
        return norm == temp_root or norm.startswith(temp_root + os.sep)

    def _iter_announcement_paths(self, announcement_id: str):
        """遍历可能存放该公告的所有目录（含未在配置中登记的一级公告栏）。"""
        seen = set()

        def _yield(path):
            ap = os.path.abspath(path)
            if ap in seen or not os.path.isdir(ap):
                return
            seen.add(ap)
            yield ap

        yield from _yield(os.path.join(self.base_dir, self.temp_dir, announcement_id))
        temp_root = os.path.join(self.base_dir, self.temp_dir)
        if os.path.isdir(temp_root):
            for name in os.listdir(temp_root):
                yield from _yield(os.path.join(temp_root, name, announcement_id))
        for board_id in self._get_all_board_ids():
            yield from _yield(self._get_announcement_path(board_id, announcement_id, False))
        if os.path.isdir(self.base_dir):
            for name in os.listdir(self.base_dir):
                if name == self.temp_dir:
                    continue
                yield from _yield(os.path.join(self.base_dir, name, announcement_id))

    def get_announcement_for_download(self, announcement_id: str):
        """下载/鉴权用：优先返回正式目录中已发布版本，避免 temp 待审副本导致无权或附件路径不一致。"""
        published = None
        fallback = None
        for ann_path in self._iter_announcement_paths(announcement_id):
            meta = self._read_metadata(ann_path)
            if not meta:
                continue
            if meta.get('status') == 'approved' and not self._is_temp_announcement_path(ann_path):
                return meta
            if not fallback:
                fallback = meta
        return fallback

    def _normalize_attachment_name(self, name: str) -> str:
        if name is None:
            return ''
        try:
            name = urllib.parse.unquote(str(name), encoding='utf-8')
        except Exception:
            name = str(name)
        return unicodedata.normalize('NFC', name).strip().lower()

    def _match_attachment_file(self, attachments_dir: str, filename: str, metadata_attachments=None):
        """在附件目录中解析真实文件路径（兼容中文名、URL 编码与 metadata 大小）。"""
        decoded_filename = filename
        try:
            decoded_filename = urllib.parse.unquote(filename, encoding='utf-8')
        except Exception:
            pass

        for try_name in (filename, decoded_filename):
            direct = os.path.join(attachments_dir, try_name)
            if os.path.isfile(direct):
                return direct

        try:
            files = [
                f for f in os.listdir(attachments_dir)
                if os.path.isfile(os.path.join(attachments_dir, f))
            ]
        except Exception as e:
            logger.debug(f"列出附件目录失败: {attachments_dir}, {e}")
            return None

        if not files:
            return None

        norm_req = self._normalize_attachment_name(decoded_filename)
        for file in files:
            if file == filename or file == decoded_filename:
                return os.path.join(attachments_dir, file)
            try:
                decoded_file = urllib.parse.unquote(file, encoding='utf-8')
                if decoded_file == filename or decoded_file == decoded_filename:
                    return os.path.join(attachments_dir, file)
            except Exception:
                pass
            if self._normalize_attachment_name(file) == norm_req:
                return os.path.join(attachments_dir, file)

        target_size = None
        if metadata_attachments:
            for att in metadata_attachments:
                att_name = att.get('name', '')
                if (
                    att_name == filename
                    or att_name == decoded_filename
                    or self._normalize_attachment_name(att_name) == norm_req
                ):
                    target_size = att.get('size')
                    break
        if target_size is not None:
            try:
                target_size = int(target_size)
            except (TypeError, ValueError):
                target_size = None
            if target_size is not None:
                size_matches = [
                    f for f in files
                    if os.path.getsize(os.path.join(attachments_dir, f)) == target_size
                ]
                if len(size_matches) == 1:
                    return os.path.join(attachments_dir, size_matches[0])

        ext = os.path.splitext(norm_req)[1] or os.path.splitext(decoded_filename)[1]
        if ext:
            ext = ext.lower()
            ext_matches = [f for f in files if f.lower().endswith(ext)]
            if len(ext_matches) == 1:
                return os.path.join(attachments_dir, ext_matches[0])
            if metadata_attachments and len(ext_matches) > 1:
                meta_names = {
                    self._normalize_attachment_name(a.get('name', ''))
                    for a in metadata_attachments
                }
                narrowed = [
                    f for f in ext_matches
                    if self._normalize_attachment_name(f) in meta_names
                ]
                if len(narrowed) == 1:
                    return os.path.join(attachments_dir, narrowed[0])

        def _ascii_base_ext(filepath: str):
            basename = os.path.basename(filepath)
            if '.' in basename:
                name_part, ext_part = basename.rsplit('.', 1)
                name_ascii = ''.join(
                    c for c in name_part
                    if ord(c) < 128 and (c.isalnum() or c in ' .-_()[]')
                )
                return name_ascii.lower().strip(), ext_part.lower()
            return basename.lower().strip(), ''

        req_base, req_ext = _ascii_base_ext(decoded_filename)
        if req_base and req_ext:
            for file in files:
                file_base, file_ext = _ascii_base_ext(file)
                if req_base == file_base and req_ext == file_ext:
                    return os.path.join(attachments_dir, file)

        if len(files) == 1:
            return os.path.join(attachments_dir, files[0])
        return None

    def get_attachment(self, announcement_id, filename, metadata=None):
        """获取附件文件路径（当前版本）"""
        logger.info(f"查找附件: announcement_id={announcement_id}, filename={filename}")
        metadata_attachments = None
        if metadata and isinstance(metadata.get('attachments'), list):
            metadata_attachments = metadata['attachments']
        elif not metadata_attachments:
            for ann_path in self._iter_announcement_paths(announcement_id):
                meta = self._read_metadata(ann_path)
                if meta and meta.get('attachments'):
                    metadata_attachments = meta['attachments']
                    break

        for ann_path in self._iter_announcement_paths(announcement_id):
            attachments_dir = os.path.join(ann_path, 'attachments')
            if not os.path.isdir(attachments_dir):
                continue
            found = self._match_attachment_file(attachments_dir, filename, metadata_attachments)
            if found:
                logger.info(f"找到附件: {found}")
                return found

        logger.warning(
            f"未找到附件: announcement_id={announcement_id}, filename={filename}"
        )
        return None
