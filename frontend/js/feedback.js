/**
 * Hydrograf Feedback — dialog form for tester feedback submissions.
 */
(function () {
    'use strict';

    window.Hydrograf = window.Hydrograf || {};

    var els = {};
    var closeTimer = null;

    function updateCharCount() {
        els.charCount.textContent = String(els.message.value.length);
    }

    function updatePreview() {
        if (!window.Hydrograf.diagnostics) {
            els.preview.textContent = 'Diagnostyka niedostępna.';
            return;
        }
        els.preview.textContent = JSON.stringify(Hydrograf.diagnostics.snapshot(), null, 2);
    }

    function showStatus(msg, isError) {
        els.status.classList.remove('d-none', 'bad', 'ok');
        els.status.classList.add(isError ? 'bad' : 'ok');
        els.status.textContent = msg;
    }

    function openModal() {
        if (Hydrograf.map && Hydrograf.map.isDrawing && Hydrograf.map.isDrawing()) {
            Hydrograf.map.cancelDrawing();
        }
        els.status.classList.add('d-none');
        updatePreview();
        els.dialog.showModal();
        els.message.focus();
    }

    function closeModal() {
        if (closeTimer) {
            clearTimeout(closeTimer);
            closeTimer = null;
        }
        if (els.dialog.open) els.dialog.close();
    }

    async function submit(e) {
        e.preventDefault();
        var message = els.message.value.trim();
        if (!message) {
            showStatus('Opis nie może być pusty.', true);
            els.message.focus();
            return;
        }
        var payload = {
            message: message,
            contact: els.contact.value.trim() || null,
            page_url: window.location.href.slice(0, 500),
            diagnostics: (els.diagnosticsCheckbox.checked && window.Hydrograf.diagnostics)
                ? Hydrograf.diagnostics.snapshot()
                : null,
        };
        els.submitBtn.disabled = true;
        try {
            await Hydrograf.api.submitFeedback(payload);
            showStatus('Dziękujemy! Zgłoszenie zostało zapisane.', false);
            els.message.value = '';
            els.contact.value = '';
            updateCharCount();
            closeTimer = setTimeout(closeModal, 2000);
        } catch (err) {
            showStatus(err.message, true);
        } finally {
            els.submitBtn.disabled = false;
        }
    }

    function init() {
        var dialog = document.getElementById('feedback-modal');
        var openBtn = document.getElementById('feedback-open-btn');
        if (!dialog || !openBtn || typeof dialog.showModal !== 'function') return;

        els = {
            dialog: dialog,
            form: document.getElementById('feedback-form'),
            message: document.getElementById('feedback-message'),
            contact: document.getElementById('feedback-contact'),
            charCount: document.getElementById('feedback-char-count'),
            diagnosticsCheckbox: document.getElementById('feedback-diagnostics'),
            preview: document.getElementById('feedback-diagnostics-preview'),
            status: document.getElementById('feedback-status'),
            submitBtn: document.getElementById('feedback-submit-btn'),
        };
        openBtn.addEventListener('click', openModal);
        document.getElementById('feedback-close').addEventListener('click', closeModal);
        document.getElementById('feedback-cancel').addEventListener('click', closeModal);
        // Click on the backdrop (outside the dialog box) closes it
        dialog.addEventListener('click', function (e) {
            if (e.target === dialog) closeModal();
        });
        dialog.addEventListener('close', function () {
            if (closeTimer) {
                clearTimeout(closeTimer);
                closeTimer = null;
            }
        });
        els.message.addEventListener('input', updateCharCount);
        els.form.addEventListener('submit', submit);
    }

    window.Hydrograf.feedback = {
        init: init,
    };
})();
