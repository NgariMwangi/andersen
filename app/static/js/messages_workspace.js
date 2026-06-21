(function () {
    const workspace = document.getElementById('messagesWorkspace');
    if (!workspace) return;

    const inboxContentEl = document.getElementById('chatInboxContent');
    const panelEl = document.getElementById('chatWorkspacePanel');
    const inboxPollUrl = workspace.dataset.inboxPollUrl;
    const pollIntervalMs = parseInt(workspace.dataset.pollInterval, 10) || 2500;
    const messagesBase = workspace.dataset.messagesBase || '/messages';

    let selectedThreadId = parseInt(workspace.dataset.selectedThread, 10) || null;
    let inboxLastMessageId = 0;
    let inboxPollTimer = null;
    let threadPollTimer = null;
    let threadController = null;
    let keyboardCleanup = null;
    let keyboardRefresh = null;

    function threadUrl(threadId) {
        return messagesBase.replace(/\/?$/, '') + '/' + threadId;
    }

    function panelUrl(threadId) {
        return threadUrl(threadId) + '/panel';
    }

    function pollUrl(threadId) {
        return threadUrl(threadId) + '/poll';
    }

    function updateMessagesNavBadge(count) {
        const badge = document.getElementById('messagesNavBadge');
        if (!badge) return;
        const n = parseInt(count, 10) || 0;
        if (n > 0) {
            badge.textContent = n > 99 ? '99+' : String(n);
            badge.classList.remove('d-none');
        } else {
            badge.classList.add('d-none');
        }
    }

    function clearInboxUnread(threadId) {
        if (!inboxContentEl || !threadId) return;
        const item = inboxContentEl.querySelector('.js-chat-inbox-item[data-thread-id="' + threadId + '"]');
        if (!item) return;
        item.classList.remove('chat-inbox-item--unread');
        item.querySelector('.chat-inbox-unread')?.remove();
    }

    function applyUnreadState(data) {
        if (data && typeof data.unread_threads === 'number') {
            updateMessagesNavBadge(data.unread_threads);
        }
        if (selectedThreadId) {
            clearInboxUnread(selectedThreadId);
        }
    }

    function setSelectedThread(threadId) {
        selectedThreadId = threadId || null;
        workspace.dataset.selectedThread = selectedThreadId ? String(selectedThreadId) : '';
        workspace.classList.toggle('messages-workspace--thread-open', !!selectedThreadId);
        workspace.querySelectorAll('.js-chat-inbox-item').forEach(function (item) {
            const id = parseInt(item.dataset.threadId, 10);
            item.classList.toggle('chat-inbox-item--active', selectedThreadId && id === selectedThreadId);
        });
        if (selectedThreadId) {
            clearInboxUnread(selectedThreadId);
        }
    }

    function showEmptyPanel() {
        stopThreadPanel();
        panelEl.innerHTML =
            '<div class="messages-workspace-empty">' +
            '<div class="messages-workspace-empty-icon" aria-hidden="true"><i class="bi bi-chat-square-text"></i></div>' +
            '<h2 class="messages-workspace-empty-title">Andersen Messages</h2>' +
            '<p class="messages-workspace-empty-text">Select a conversation on the left to start chatting.</p>' +
            '</div>';
        setSelectedThread(null);
        if (window.history && window.history.replaceState) {
            window.history.replaceState({ threadId: null }, '', messagesBase);
        }
    }

    function stopThreadPanel() {
        if (threadPollTimer) {
            window.clearInterval(threadPollTimer);
            threadPollTimer = null;
        }
        if (keyboardCleanup) {
            keyboardCleanup();
            keyboardCleanup = null;
        }
        keyboardRefresh = null;
        threadController = null;
    }

    function bindMessageInteractions(root) {
        root?.querySelectorAll('.chat-quote[data-scroll-to]').forEach(function (quote) {
            if (quote.dataset.bound) return;
            quote.dataset.bound = '1';
            quote.addEventListener('click', function (e) {
                e.preventDefault();
                scrollToMessage(quote.dataset.scrollTo, true);
            });
        });

        root?.querySelectorAll('.chat-reply-btn').forEach(function (btn) {
            if (btn.dataset.bound) return;
            btn.dataset.bound = '1';
            btn.addEventListener('click', function (e) {
                e.preventDefault();
                const row = btn.closest('[data-message-id]');
                if (!row || !threadController) return;
                threadController.setReply(
                    row.dataset.messageId,
                    row.dataset.senderName || 'Unknown',
                    row.dataset.bodyPreview || ''
                );
            });
        });
    }

    function scrollToMessage(messageId, smooth) {
        const messagesEl = document.getElementById('chatMessages');
        if (!messagesEl) return;
        const target = document.getElementById(messageId);
        if (!target) return;

        const containerTop = messagesEl.getBoundingClientRect().top;
        const targetRect = target.getBoundingClientRect();
        const relativeTop = targetRect.top - containerTop + messagesEl.scrollTop;
        const scrollTop = relativeTop - (messagesEl.clientHeight / 2) + (targetRect.height / 2);

        messagesEl.scrollTo({
            top: Math.max(0, scrollTop),
            behavior: smooth === false ? 'auto' : 'smooth',
        });

        target.classList.remove('chat-msg-row--highlight');
        void target.offsetWidth;
        target.classList.add('chat-msg-row--highlight');
        window.setTimeout(function () {
            target.classList.remove('chat-msg-row--highlight');
        }, 1400);
    }

    function initThreadPanel(initialReplyTo) {
        stopThreadPanel();

        const page = document.getElementById('chatThreadPage');
        const messagesEl = document.getElementById('chatMessages');
        const form = document.getElementById('chatComposeForm');
        const input = document.getElementById('chatComposeInput');
        const replyIdField = document.getElementById('replyToMessageId');
        const preview = document.getElementById('chatReplyPreview');
        const previewName = document.getElementById('chatReplyPreviewName');
        const previewText = document.getElementById('chatReplyPreviewText');
        const previewClose = document.getElementById('chatReplyPreviewClose');
        const composeError = document.getElementById('chatComposeError');
        const mobileBack = document.getElementById('chatMobileBack');
        const threadId = page ? parseInt(page.dataset.messageThreadId, 10) : null;

        if (!page || !threadId) return;

        let pendingReplyId = replyIdField?.value || '';
        let sending = false;

        function syncReplyIdField() {
            if (replyIdField && pendingReplyId) {
                replyIdField.value = pendingReplyId;
            }
        }

        function lastMessageId() {
            const rows = messagesEl?.querySelectorAll('[data-message-id]');
            if (!rows || !rows.length) return 0;
            return parseInt(rows[rows.length - 1].dataset.messageId, 10) || 0;
        }

        function showError(message) {
            if (!composeError) return;
            composeError.textContent = message || '';
            composeError.classList.toggle('d-none', !message);
        }

        function appendMessages(html, messageId) {
            if (!messagesEl || !html) return false;
            if (messageId && document.getElementById('message-' + messageId)) {
                return false;
            }
            messagesEl.insertAdjacentHTML('beforeend', html);
            bindMessageInteractions(messagesEl.lastElementChild);
            return true;
        }

        function scrollToBottom(smooth) {
            if (!messagesEl) return;
            messagesEl.scrollTo({ top: messagesEl.scrollHeight, behavior: smooth ? 'smooth' : 'auto' });
        }

        function resizeInput() {
            if (!input) return;
            input.style.height = 'auto';
            input.style.height = Math.min(input.scrollHeight, 120) + 'px';
            if (keyboardRefresh) {
                keyboardRefresh();
            }
        }

        function clearReply() {
            pendingReplyId = '';
            if (replyIdField) replyIdField.value = '';
            preview?.classList.add('d-none');
            if (previewName) previewName.textContent = '';
            if (previewText) previewText.textContent = '';
        }

        function setReply(messageId, senderName, bodyPreview) {
            pendingReplyId = String(messageId);
            if (replyIdField) replyIdField.value = pendingReplyId;
            if (previewName) previewName.textContent = senderName;
            if (previewText) previewText.textContent = bodyPreview;
            preview?.classList.remove('d-none');
            input?.focus();
            resizeInput();
        }

        async function pollNewMessages() {
            if (document.hidden || sending) return;
            try {
                const response = await fetch(pollUrl(threadId) + '?after=' + lastMessageId(), {
                    headers: { 'Accept': 'application/json' },
                    credentials: 'same-origin',
                });
                if (!response.ok) return;
                const data = await response.json();
                if (!data.ok) return;

                if (data.messages?.length) {
                    let added = false;
                    data.messages.forEach(function (item) {
                        if (appendMessages(item.html, item.id)) {
                            added = true;
                        }
                    });
                    if (added) {
                        scrollToBottom(true);
                    }
                }

                if (data.receipts && typeof window.applyChatReadReceipts === 'function') {
                    window.applyChatReadReceipts(data.receipts);
                }
                applyUnreadState(data);
            } catch (err) {
                /* ignore */
            }
        }

        async function sendMessage() {
            if (!form || !input || sending) return;
            const text = input.value.trim();
            if (!text) return;

            syncReplyIdField();
            sending = true;
            showError('');
            if (typeof window.setChatSendingState === 'function') {
                window.setChatSendingState(form, true);
            }

            const formData = new FormData(form);
            formData.set('body', text);

            try {
                const response = await fetch(form.action, {
                    method: 'POST',
                    body: formData,
                    headers: {
                        'X-Requested-With': 'XMLHttpRequest',
                        'Accept': 'application/json',
                    },
                    credentials: 'same-origin',
                });
                const data = await response.json();
                if (!response.ok || !data.ok) {
                    showError(data.error || 'Could not send message.');
                    return;
                }

                appendMessages(data.html, data.message_id);
                input.value = '';
                resizeInput();
                clearReply();
                scrollToBottom(true);
                pollInbox(false);

                if (data.email_warning) {
                    showError('Message sent, but some emails could not be delivered.');
                    window.setTimeout(function () { showError(''); }, 4000);
                }
            } catch (err) {
                showError('Could not send message. Please try again.');
            } finally {
                sending = false;
                var activeForm = document.getElementById('chatComposeForm');
                if (typeof window.setChatSendingState === 'function') {
                    window.setChatSendingState(activeForm || form, false);
                }
            }
        }

        bindMessageInteractions(page);
        previewClose?.addEventListener('click', clearReply);
        mobileBack?.addEventListener('click', showEmptyPanel);

        input?.addEventListener('input', resizeInput);
        input?.addEventListener('keydown', function (e) {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                sendMessage();
            }
            if (e.key === 'Escape') clearReply();
        });

        form?.addEventListener('submit', function (e) {
            e.preventDefault();
            sendMessage();
        });

        form?.addEventListener('chat-compose-layout-change', function () {
            if (keyboardRefresh) {
                keyboardRefresh();
            }
        });

        if (initialReplyTo) {
            const row = page.querySelector('[data-message-id="' + initialReplyTo + '"]');
            if (row) {
                setReply(initialReplyTo, row.dataset.senderName || '', row.dataset.bodyPreview || '');
            }
        }

        if (!window.location.hash || window.location.hash.indexOf('#message-') !== 0) {
            scrollToBottom(false);
        } else {
            scrollToMessage(window.location.hash.slice(1), false);
        }
        resizeInput();

        if (typeof window.initChatMobileKeyboard === 'function') {
            var keyboard = window.initChatMobileKeyboard(page, input, {
                messagesEl: messagesEl,
                scrollToBottom: scrollToBottom,
            });
            keyboardCleanup = keyboard.cleanup;
            keyboardRefresh = keyboard.refresh;
        }

        threadPollTimer = window.setInterval(pollNewMessages, pollIntervalMs);
        threadController = { setReply: setReply, clearReply: clearReply };
    }

    async function loadThread(threadId, options) {
        options = options || {};
        if (!threadId) {
            showEmptyPanel();
            return;
        }

        try {
            const params = new URLSearchParams();
            if (options.replyTo) params.set('reply_to', String(options.replyTo));

            const response = await fetch(panelUrl(threadId) + (params.toString() ? '?' + params.toString() : ''), {
                headers: { 'Accept': 'application/json' },
                credentials: 'same-origin',
            });
            if (!response.ok) return;
            const data = await response.json();
            if (!data.ok || !data.html) return;

            panelEl.innerHTML = data.html;
            setSelectedThread(threadId);
            applyUnreadState(data);
            refreshInboxList();

            if (options.pushState !== false && window.history && window.history.pushState) {
                window.history.pushState({ threadId: threadId }, '', threadUrl(threadId));
            }

            if (data.title) {
                document.title = data.title + ' - Messages - ' + (document.title.split(' - ').pop() || 'HRMS');
            }

            initThreadPanel(options.replyTo || null);
        } catch (err) {
            /* ignore */
        }
    }

    function bindInboxClicks() {
        inboxContentEl?.querySelectorAll('.js-chat-inbox-item').forEach(function (item) {
            if (item.dataset.bound) return;
            item.dataset.bound = '1';
            item.addEventListener('click', function (e) {
                e.preventDefault();
                const threadId = parseInt(item.dataset.threadId, 10);
                if (!threadId || threadId === selectedThreadId) return;
                loadThread(threadId);
            });
        });
    }

    async function refreshInboxList() {
        if (!inboxContentEl) return;
        try {
            const params = new URLSearchParams();
            params.set('refresh', '1');
            if (selectedThreadId) {
                params.set('active_thread', String(selectedThreadId));
            }
            const response = await fetch(inboxPollUrl + '?' + params.toString(), {
                headers: { 'Accept': 'application/json' },
                credentials: 'same-origin',
            });
            if (!response.ok) return;
            const data = await response.json();
            if (!data.ok || !data.changed || !data.html) return;
            inboxContentEl.innerHTML = data.html;
            bindInboxClicks();
            applyUnreadState(data);
        } catch (err) {
            /* ignore */
        }
    }

    async function pollInbox(init) {
        if (!inboxContentEl || document.hidden) return;
        try {
            const params = new URLSearchParams();
            if (init) {
                params.set('init', '1');
            } else {
                params.set('after', String(inboxLastMessageId));
            }
            if (selectedThreadId) {
                params.set('active_thread', String(selectedThreadId));
            }

            const response = await fetch(inboxPollUrl + '?' + params.toString(), {
                headers: { 'Accept': 'application/json' },
                credentials: 'same-origin',
            });
            if (!response.ok) return;
            const data = await response.json();
            if (!data.ok) return;

            if (typeof data.latest_message_id === 'number') {
                inboxLastMessageId = Math.max(inboxLastMessageId, data.latest_message_id);
            }

            if (data.changed && data.html) {
                inboxContentEl.innerHTML = data.html;
                bindInboxClicks();
            }

            applyUnreadState(data);
        } catch (err) {
            /* ignore */
        }
    }

    function startInboxPolling() {
        if (inboxPollTimer) return;
        pollInbox(true).then(function () {
            inboxPollTimer = window.setInterval(function () {
                pollInbox(false);
            }, pollIntervalMs);
        });
    }

    window.addEventListener('popstate', function (e) {
        const threadId = e.state && e.state.threadId ? parseInt(e.state.threadId, 10) : null;
        if (threadId) {
            loadThread(threadId, { pushState: false });
        } else {
            showEmptyPanel();
        }
    });

    bindInboxClicks();
    startInboxPolling();

    if (selectedThreadId) {
        initThreadPanel(null);
        clearInboxUnread(selectedThreadId);
        if (window.history && window.history.replaceState) {
            window.history.replaceState({ threadId: selectedThreadId }, '', threadUrl(selectedThreadId));
        }
    }
})();
