/**
 * 统一 NEO 页头渲染
 */
(function (global) {
    'use strict';

    function renderHeader(options) {
        options = options || {};
        var pageTitle = options.pageTitle || '';
        var backUrl = options.backUrl || '/';
        var backLabel = options.backLabel || '返回主页';
        var extraActions = options.extraActions || '';

        return (
            '<div class="neo-page-header">' +
                '<div class="neo-header-brand">' +
                    '<img src="/logo.png" alt="CHANGHONG NeoNet" class="neo-brand-logo" />' +
                    '<div class="neo-brand-text">' +
                        '<div class="neo-title">NEO Hardware <span>AI</span></div>' +
                        '<div class="neo-subtitle">硬件研发部管理系统</div>' +
                        '<div class="neo-tagline">专业、高效、可靠的硬件研发管理平台</div>' +
                    '</div>' +
                '</div>' +
                '<div class="neo-header-actions">' +
                    (pageTitle ? '<span class="neo-page-title">' + pageTitle + '</span>' : '') +
                    extraActions +
                    '<a href="' + backUrl + '" class="neo-btn neo-btn-secondary">' + backLabel + '</a>' +
                '</div>' +
            '</div>'
        );
    }

    function mount(selector, options) {
        var el = typeof selector === 'string' ? document.querySelector(selector) : selector;
        if (el) el.innerHTML = renderHeader(options);
    }

    global.NeoHeader = { render: renderHeader, mount: mount };
})(window);
