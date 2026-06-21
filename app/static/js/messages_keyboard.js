/**
 * Keeps the chat compose bar above the on-screen keyboard on mobile.
 * Uses the Visual Viewport API where available.
 */
(function (global) {
    'use strict';

    var MOBILE_MQ = '(max-width: 991.98px)';

    function keyboardInset() {
        var vv = global.visualViewport;
        if (!vv) {
            return 0;
        }
        return Math.max(0, Math.round(global.innerHeight - vv.height - vv.offsetTop));
    }

    function isMobileChat() {
        return global.matchMedia && global.matchMedia(MOBILE_MQ).matches;
    }

    function initChatMobileKeyboard(page, input, options) {
        options = options || {};
        var compose = page && page.querySelector('.chat-compose');
        var messagesEl = options.messagesEl || page && page.querySelector('.chat-messages');
        var onLayout = typeof options.onLayout === 'function' ? options.onLayout : null;
        var rafId = null;

        if (!page || !compose) {
            return { cleanup: function () {}, refresh: function () {} };
        }

        function applyLayout() {
            if (!isMobileChat()) {
                page.classList.remove('chat-thread-page--keyboard-open');
                page.style.removeProperty('--chat-keyboard-offset');
                page.style.removeProperty('--chat-compose-height');
                if (messagesEl) {
                    messagesEl.style.removeProperty('padding-bottom');
                }
                return;
            }

            var inset = keyboardInset();
            var composeHeight = compose.offsetHeight;

            page.style.setProperty('--chat-keyboard-offset', inset + 'px');
            page.style.setProperty('--chat-compose-height', composeHeight + 'px');
            page.classList.toggle('chat-thread-page--keyboard-open', inset > 0);

            if (messagesEl) {
                messagesEl.style.paddingBottom = composeHeight + 'px';
            }

            if (onLayout) {
                onLayout(inset, composeHeight);
            }
        }

        function scheduleLayout() {
            if (rafId) {
                global.cancelAnimationFrame(rafId);
            }
            rafId = global.requestAnimationFrame(applyLayout);
        }

        function onFocus() {
            scheduleLayout();
            if (!global.visualViewport && input && input.scrollIntoView) {
                input.scrollIntoView({ block: 'nearest', inline: 'nearest' });
            }
            global.setTimeout(function () {
                scheduleLayout();
                if (typeof options.scrollToBottom === 'function') {
                    options.scrollToBottom(false);
                }
                global.setTimeout(scheduleLayout, 300);
            }, 50);
        }

        function onBlur() {
            global.setTimeout(scheduleLayout, 120);
        }

        if (global.visualViewport) {
            global.visualViewport.addEventListener('resize', scheduleLayout);
            global.visualViewport.addEventListener('scroll', scheduleLayout);
        }
        global.addEventListener('resize', scheduleLayout);
        input && input.addEventListener('focus', onFocus);
        input && input.addEventListener('blur', onBlur);

        scheduleLayout();

        return {
            cleanup: function cleanupChatMobileKeyboard() {
                if (rafId) {
                    global.cancelAnimationFrame(rafId);
                }
                if (global.visualViewport) {
                    global.visualViewport.removeEventListener('resize', scheduleLayout);
                    global.visualViewport.removeEventListener('scroll', scheduleLayout);
                }
                global.removeEventListener('resize', scheduleLayout);
                input && input.removeEventListener('focus', onFocus);
                input && input.removeEventListener('blur', onBlur);
                page.classList.remove('chat-thread-page--keyboard-open');
                page.style.removeProperty('--chat-keyboard-offset');
                page.style.removeProperty('--chat-compose-height');
                if (messagesEl) {
                    messagesEl.style.removeProperty('padding-bottom');
                }
            },
            refresh: scheduleLayout,
        };
    }

    global.initChatMobileKeyboard = initChatMobileKeyboard;
})(window);
