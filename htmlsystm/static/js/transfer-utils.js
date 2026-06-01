/**
 * 文件传输工具：上传/下载进度 + 全页锁定
 */
(function (global) {
    'use strict';

    var isTransferring = false;
    var overlayEl = null;
    var beforeUnloadHandler = null;

    var ALLOWED_ATTACHMENT_EXTENSIONS = [
        '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',
        '.txt', '.csv', '.md',
        '.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp',
        '.zip', '.rar', '.7z',
        '.dwg', '.dxf', '.step', '.stp'
    ];

    var ALLOWED_IMAGE_EXTENSIONS = ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp'];

    function getExtension(filename) {
        var dot = filename.lastIndexOf('.');
        return dot >= 0 ? filename.slice(dot).toLowerCase() : '';
    }

    function isAllowedAttachment(filename) {
        return ALLOWED_ATTACHMENT_EXTENSIONS.indexOf(getExtension(filename)) >= 0;
    }

    function isAllowedImage(filename) {
        return ALLOWED_IMAGE_EXTENSIONS.indexOf(getExtension(filename)) >= 0;
    }

    function formatBytes(bytes) {
        if (!bytes || bytes <= 0) return '0 B';
        if (bytes < 1024) return bytes + ' B';
        if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
        return (bytes / (1024 * 1024)).toFixed(2) + ' MB';
    }

    function ensureOverlay() {
        if (overlayEl) return overlayEl;
        overlayEl = document.createElement('div');
        overlayEl.className = 'neo-transfer-overlay';
        overlayEl.style.display = 'none';
        overlayEl.innerHTML =
            '<div class="neo-transfer-panel">' +
                '<h3 id="neo-transfer-title">正在传输</h3>' +
                '<p id="neo-transfer-status">请稍候...</p>' +
                '<div class="neo-progress-track">' +
                    '<div class="neo-progress-fill" id="neo-transfer-bar" style="width:0%">0%</div>' +
                '</div>' +
                '<div class="neo-transfer-warning">请勿关闭页面或进行其他操作</div>' +
            '</div>';
        document.body.appendChild(overlayEl);
        return overlayEl;
    }

    function showOverlay(title, status, percent) {
        ensureOverlay();
        isTransferring = true;
        overlayEl.style.display = 'flex';
        document.getElementById('neo-transfer-title').textContent = title || '正在传输';
        updateOverlay(status, percent);
        document.body.style.overflow = 'hidden';
        if (!beforeUnloadHandler) {
            beforeUnloadHandler = function (e) {
                e.preventDefault();
                e.returnValue = '文件正在传输中，确定要离开吗？';
                return e.returnValue;
            };
            window.addEventListener('beforeunload', beforeUnloadHandler);
        }
    }

    function updateOverlay(status, percent) {
        var bar = document.getElementById('neo-transfer-bar');
        var statusEl = document.getElementById('neo-transfer-status');
        if (statusEl && status !== undefined) statusEl.textContent = status;
        if (bar && percent !== undefined) {
            var p = Math.min(100, Math.max(0, Math.round(percent)));
            bar.style.width = p + '%';
            bar.textContent = p + '%';
        }
    }

    function hideOverlay() {
        isTransferring = false;
        if (overlayEl) overlayEl.style.display = 'none';
        document.body.style.overflow = '';
        if (beforeUnloadHandler) {
            window.removeEventListener('beforeunload', beforeUnloadHandler);
            beforeUnloadHandler = null;
        }
    }

    function lockPageElements() {
        document.querySelectorAll('button, input, select, textarea, a, [contenteditable="true"]').forEach(function (el) {
            if (el.closest('.neo-transfer-overlay')) return;
            el.setAttribute('data-neo-was-disabled', el.disabled ? '1' : '0');
            if (el.tagName === 'A') {
                el.setAttribute('data-neo-href', el.href || '');
                el.removeAttribute('href');
                el.style.pointerEvents = 'none';
            } else if (el.getAttribute('contenteditable') === 'true') {
                el.setAttribute('contenteditable', 'false');
            } else {
                el.disabled = true;
            }
        });
    }

    function unlockPageElements() {
        document.querySelectorAll('[data-neo-was-disabled]').forEach(function (el) {
            var wasDisabled = el.getAttribute('data-neo-was-disabled') === '1';
            if (el.tagName === 'A') {
                var href = el.getAttribute('data-neo-href');
                if (href) el.href = href;
                el.removeAttribute('data-neo-href');
                el.style.pointerEvents = '';
            } else if (el.hasAttribute('contenteditable')) {
                el.setAttribute('contenteditable', 'true');
            } else {
                el.disabled = wasDisabled;
            }
            el.removeAttribute('data-neo-was-disabled');
        });
    }

    function xhrUpload(url, data, options) {
        options = options || {};
        return new Promise(function (resolve, reject) {
            showOverlay(options.title || '正在上传', options.status || '准备上传...', 0);
            lockPageElements();

            var xhr = new XMLHttpRequest();
            var body = typeof data === 'string' ? data : JSON.stringify(data);

            xhr.open('POST', url, true);
            xhr.setRequestHeader('Content-Type', 'application/json');

            xhr.upload.onprogress = function (e) {
                if (e.lengthComputable) {
                    var pct = (e.loaded / e.total) * 100;
                    updateOverlay(
                        '已上传 ' + formatBytes(e.loaded) + ' / ' + formatBytes(e.total),
                        pct
                    );
                } else {
                    updateOverlay('已上传 ' + formatBytes(e.loaded), undefined);
                }
            };

            xhr.onload = function () {
                hideOverlay();
                unlockPageElements();
                try {
                    var result = JSON.parse(xhr.responseText);
                    if (xhr.status >= 200 && xhr.status < 300) {
                        resolve(result);
                    } else {
                        reject(new Error(result.error || result.message || ('HTTP ' + xhr.status)));
                    }
                } catch (err) {
                    if (xhr.status >= 200 && xhr.status < 300) {
                        resolve({ success: true, raw: xhr.responseText });
                    } else {
                        reject(new Error('服务器响应异常 (HTTP ' + xhr.status + ')'));
                    }
                }
            };

            xhr.onerror = function () {
                hideOverlay();
                unlockPageElements();
                reject(new Error('网络错误，上传失败'));
            };

            xhr.onabort = function () {
                hideOverlay();
                unlockPageElements();
                reject(new Error('上传已取消'));
            };

            updateOverlay('正在上传 ' + formatBytes(body.length) + '...', 0);
            xhr.send(body);
        });
    }

    function downloadWithProgress(url, filename, options) {
        options = options || {};
        return new Promise(function (resolve, reject) {
            showOverlay(options.title || '正在下载', '连接服务器...', 0);
            lockPageElements();

            var xhr = new XMLHttpRequest();
            xhr.open('GET', url, true);
            xhr.withCredentials = true;
            xhr.responseType = 'blob';

            xhr.onprogress = function (e) {
                if (e.lengthComputable) {
                    var pct = (e.loaded / e.total) * 100;
                    updateOverlay(
                        '已下载 ' + formatBytes(e.loaded) + ' / ' + formatBytes(e.total),
                        pct
                    );
                } else {
                    updateOverlay('已下载 ' + formatBytes(e.loaded), undefined);
                }
            };

            xhr.onload = function () {
                hideOverlay();
                unlockPageElements();

                if (xhr.status >= 200 && xhr.status < 300) {
                    var ct = (xhr.getResponseHeader('Content-Type') || '').toLowerCase();
                    if (ct.indexOf('application/json') >= 0) {
                        reject(new Error('下载失败：服务器返回了错误信息而非文件'));
                        return;
                    }
                    var blob = xhr.response;
                    var blobUrl = URL.createObjectURL(blob);
                    var link = document.createElement('a');
                    link.href = blobUrl;
                    link.download = filename || 'download';
                    link.style.display = 'none';
                    document.body.appendChild(link);
                    link.click();
                    setTimeout(function () {
                        document.body.removeChild(link);
                        URL.revokeObjectURL(blobUrl);
                    }, 200);
                    resolve({ success: true });
                } else {
                    var msg = xhr.status === 404 ? '文件不存在或无权访问' :
                              xhr.status === 403 ? '无权下载此附件' :
                              xhr.status === 401 ? '请先登录' :
                              '下载失败 (HTTP ' + xhr.status + ')';
                    reject(new Error(msg));
                }
            };

            xhr.onerror = function () {
                hideOverlay();
                unlockPageElements();
                reject(new Error('网络错误，下载失败'));
            };

            xhr.send();
        });
    }

    function bindDownloadButtons(container) {
        if (!container || container.getAttribute('data-download-bound') === '1') return;
        container.setAttribute('data-download-bound', '1');
        container.addEventListener('click', function (e) {
            var btn = e.target.closest('[data-download-url]');
            if (!btn) return;
            e.preventDefault();
            if (isTransferring) return;
            var url = btn.getAttribute('data-download-url');
            var rawName = btn.getAttribute('data-filename') || 'download';
            var filename = rawName;
            try { filename = decodeURIComponent(rawName); } catch (e) { /* keep raw */ }
            downloadWithProgress(url, filename).catch(function (err) {
                alert(err.message || '下载失败');
            });
        });
    }

    global.TransferUtils = {
        isTransferring: function () { return isTransferring; },
        isAllowedAttachment: isAllowedAttachment,
        isAllowedImage: isAllowedImage,
        getExtension: getExtension,
        formatBytes: formatBytes,
        showOverlay: showOverlay,
        updateOverlay: updateOverlay,
        hideOverlay: hideOverlay,
        lockPageElements: lockPageElements,
        unlockPageElements: unlockPageElements,
        xhrUpload: xhrUpload,
        downloadWithProgress: downloadWithProgress,
        bindDownloadButtons: bindDownloadButtons,
        ALLOWED_ATTACHMENT_EXTENSIONS: ALLOWED_ATTACHMENT_EXTENSIONS
    };
})(window);
