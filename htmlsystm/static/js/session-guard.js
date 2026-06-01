/**
 * 管理系统全页：加载与断网恢复时校验会话，失效则跳转登录（禁止 sessionStorage 假登录）。
 */
(function () {
    'use strict';

    var IDLE_MS = 30 * 60 * 1000;
    var SKIP = { '/login': 1, '/register': 1 };
    var checking = false;
    var lastHiddenAt = 0;
    var lastLoginRedirectAt = 0;

    var path = window.location.pathname || '/';
    if (SKIP[path]) return;
    if (path.length > 1 && path.charAt(path.length - 1) === '/') {
        path = path.slice(0, -1);
    }

    function loginUrl() {
        var here = window.location.pathname + window.location.search;
        return '/login?redirect=' + encodeURIComponent(here || '/');
    }

    function goLogin() {
        var now = Date.now();
        if (now - lastLoginRedirectAt < 8000) {
            return;
        }
        lastLoginRedirectAt = now;
        try {
            sessionStorage.removeItem('user');
        } catch (e) { /* ignore */ }
        window.location.href = loginUrl();
    }

    function checkSession() {
        if (checking) return Promise.resolve();
        checking = true;
        var controller = typeof AbortController !== 'undefined' ? new AbortController() : null;
        var timer = controller ? setTimeout(function () { controller.abort(); }, 12000) : null;
        return fetch('/api/auth/check', {
            credentials: 'same-origin',
            signal: controller ? controller.signal : undefined
        })
            .then(function (r) {
                if (timer) clearTimeout(timer);
                if (!r.ok) {
                    return null;
                }
                return r.json().then(function (data) {
                    return data;
                });
            })
            .then(function (data) {
                if (!data) return;
                if (data.authenticated) {
                    try {
                        if (data.user) {
                            sessionStorage.setItem('user', JSON.stringify(data.user));
                        }
                    } catch (e) { /* ignore */ }
                    return;
                }
                if (data.authenticated === false) {
                    goLogin();
                }
            })
            .catch(function (err) {
                if (timer) clearTimeout(timer);
                if (err && err.name === 'AbortError') {
                    return;
                }
                /* 网络异常或请求被取消：不踢出，避免与改密/大量 API 并发时误跳登录 */
            })
            .finally(function () {
                checking = false;
            });
    }

    document.addEventListener('visibilitychange', function () {
        if (document.visibilityState === 'hidden') {
            lastHiddenAt = Date.now();
            return;
        }
        if (document.visibilityState !== 'visible') return;
        if (lastHiddenAt && Date.now() - lastHiddenAt >= IDLE_MS) {
            checkSession();
        }
    });

    window.addEventListener('online', function () {
        checkSession();
    });

    checkSession();
})();
