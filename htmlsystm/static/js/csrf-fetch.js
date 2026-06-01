/**
 * 为同源 fetch 自动附加 X-CSRF-Token（与 csrf_token Cookie 双提交）。
 */
(function () {
    function readCsrfCookie() {
        var m = document.cookie.match(/(?:^|;\s*)csrf_token=([^;]+)/);
        return m ? decodeURIComponent(m[1]) : '';
    }

    var origFetch = window.fetch;
    if (!origFetch) return;

    window.fetch = function (input, init) {
        init = init || {};
        var url = typeof input === 'string' ? input : (input && input.url) || '';
        var method = ((init.method || 'GET') + '').toUpperCase();
        var needsCsrf = ['POST', 'PUT', 'DELETE', 'PATCH'].indexOf(method) >= 0;
        if (needsCsrf && url.indexOf('/api/') >= 0) {
            var token = readCsrfCookie();
            if (token) {
                var headers = new Headers(init.headers || {});
                if (!headers.has('X-CSRF-Token')) {
                    headers.set('X-CSRF-Token', token);
                }
                init.headers = headers;
            }
        }
        if (init.credentials === undefined) {
            init.credentials = 'same-origin';
        }
        return origFetch.call(this, input, init);
    };
})();
