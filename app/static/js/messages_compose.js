/**
 * Shared compose UI: lock input and swap send icon for spinner while posting.
 */
(function (global) {
    'use strict';

    function setChatSendingState(form, isSending) {
        if (!form || !form.isConnected) {
            return;
        }

        var compose = form.closest('.chat-compose');
        var input = form.querySelector('#chatComposeInput') || form.querySelector('.chat-compose-input');
        var sendBtn = form.querySelector('#chatSendBtn') || form.querySelector('.chat-send-btn');
        var icon = sendBtn && sendBtn.querySelector('.chat-send-btn-icon');
        var spinner = sendBtn && sendBtn.querySelector('.chat-send-btn-spinner');
        var replyClose = compose && compose.querySelector('#chatReplyPreviewClose');

        form.classList.toggle('chat-compose-form--sending', !!isSending);

        if (input) {
            input.disabled = !!isSending;
        }

        if (sendBtn) {
            sendBtn.disabled = !!isSending;
            sendBtn.classList.toggle('chat-send-btn--sending', !!isSending);
            sendBtn.setAttribute('aria-busy', isSending ? 'true' : 'false');
            sendBtn.setAttribute('aria-label', isSending ? 'Sending message' : 'Send message');
        }

        if (icon) {
            icon.hidden = !!isSending;
        }

        if (spinner) {
            spinner.hidden = !isSending;
        }

        form.querySelectorAll('.chat-email-toggle input').forEach(function (el) {
            el.disabled = !!isSending;
        });

        if (replyClose) {
            replyClose.disabled = !!isSending;
        }

        global.requestAnimationFrame(function () {
            form.dispatchEvent(new CustomEvent('chat-compose-layout-change', { bubbles: true }));
        });
    }

    function applyChatReadReceipts(receipts) {
        if (!receipts || !receipts.length) {
            return;
        }
        receipts.forEach(function (item) {
            var row = document.getElementById('message-' + item.message_id);
            if (!row) {
                return;
            }
            var receipt = row.querySelector('.chat-read-receipt');
            if (!receipt) {
                return;
            }
            var status = item.status === 'read' ? 'read' : 'sent';
            receipt.className = 'chat-read-receipt chat-read-receipt--' + status;
            receipt.title = status === 'read' ? 'Seen' : 'Sent';
            receipt.setAttribute('aria-label', receipt.title);
            receipt.innerHTML = status === 'read'
                ? '<i class="bi bi-check2-all" aria-hidden="true"></i>'
                : '<i class="bi bi-check2" aria-hidden="true"></i>';
        });
    }

    global.setChatSendingState = setChatSendingState;
    global.applyChatReadReceipts = applyChatReadReceipts;
})(window);
