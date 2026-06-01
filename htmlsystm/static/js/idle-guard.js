/**
 * 管理系统全页：长时间无操作返回主页；会话失效则跳转登录。
 * 由 serve_template 自动注入（login/register 除外）。
 */
(function () {
    'use strict';

    var IDLE_MS = 30 * 60 * 1000;
    var HOME = '/';
    var SKIP = { '/login': 1, '/register': 1 };

    var path = window.location.pathname || '/';
    if (SKIP[path]) return;
    if (path.length > 1 && path.charAt(path.length - 1) === '/') {
        path = path.slice(0, -1);
    }

    var lastActivity = Date.now();
    var timer = null;
    var handling = false;
    var pendingOnlineCheck = false;

    function isHome() {
        return path === HOME || path === '';
    }

    function schedule() {
        if (timer) clearTimeout(timer);
        var elapsed = Date.now() - lastActivity;
        var delay = Math.max(0, IDLE_MS - elapsed);
        timer = setTimeout(onIdle, delay);
    }

    function bump() {
        lastActivity = Date.now();
        schedule();
    }

    function goLogin() {
        var here = window.location.pathname + window.location.search;
        window.location.href = '/login?redirect=' + encodeURIComponent(here || '/');
    }

    function verifySessionThen(fn) {
        fetch('/api/auth/check', { credentials: 'same-origin' })
            .then(function (r) {
                if (r.status === 401) {
                    goLogin();
                    return null;
                }
                return r.json();
            })
            .then(function (data) {
                if (data === null) return;
                if (!data || !data.authenticated) {
                    goLogin();
                    return;
                }
                fn();
            })
            .catch(function () {
                if (typeof navigator !== 'undefined' && navigator.onLine === false) {
                    pendingOnlineCheck = true;
                    return;
                }
                goLogin();
            });
    }

    function onIdle() {
        if (handling) return;
        if (Date.now() - lastActivity < IDLE_MS) {
            schedule();
            return;
        }
        handling = true;
        verifySessionThen(function () {
            if (isHome()) {
                window.location.reload();
                return;
            }
            window.location.href = HOME;
        }).finally(function () {
            handling = false;
        });
    }

    window.addEventListener('online', function () {
        if (!pendingOnlineCheck) return;
        pendingOnlineCheck = false;
        verifySessionThen(function () {
            schedule();
        });
    });

    ['mousedown', 'keydown', 'scroll', 'touchstart', 'click'].forEach(function (ev) {
        document.addEventListener(ev, bump, { passive: true });
    });

    document.addEventListener('visibilitychange', function () {
        if (document.visibilityState !== 'visible') return;
        if (Date.now() - lastActivity >= IDLE_MS) onIdle();
        else schedule();
    });

    schedule();
})();
