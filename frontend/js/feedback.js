/**
 * Hydrograf Feedback — dialog form for tester feedback submissions.
 */
(function () {
    'use strict';

    window.Hydrograf = window.Hydrograf || {};

    var els = {};
    // After a successful send the form stays locked until the dialog is closed
    var sent = false;
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

    function cancelAutoClose() {
        if (closeTimer) {
            clearTimeout(closeTimer);
            closeTimer = null;
        }
    }

    // Locked while a submission is sending and after it was sent, so a second
    // message cannot be typed into a form that is about to close
    function setLocked(locked) {
        els.message.disabled = locked;
        els.contact.disabled = locked;
        els.diagnosticsCheckbox.disabled = locked;
        els.submitBtn.disabled = locked;
    }

    function resetForm() {
        sent = false;
        els.message.value = '';
        els.contact.value = '';
        updateCharCount();
        setLocked(false);
        els.cancelBtn.textContent = 'Anuluj';
    }

    function openModal() {
        if (Hydrograf.map && Hydrograf.map.isDrawing && Hydrograf.map.isDrawing()) {
            Hydrograf.map.cancelDrawing();
        }
        // Reopening after a sent message gives a fresh form; an unsent draft is kept
        if (sent) resetForm();
        els.status.classList.add('d-none');
        updatePreview();
        els.dialog.showModal();
        els.message.focus();
    }

    function closeModal() {
        cancelAutoClose();
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
        setLocked(true);
        try {
            await Hydrograf.api.submitFeedback(payload);
            sent = true;
            showStatus('Dziękujemy! Zgłoszenie zostało zapisane.', false);
            els.cancelBtn.textContent = 'Zamknij';
            if (els.dialog.open) {
                // Focus first: the auto-close below is cancelled by any later
                // focus, key, pointer or input event inside the dialog
                els.cancelBtn.focus();
                closeTimer = setTimeout(closeModal, 2000);
            }
        } catch (err) {
            setLocked(false);
            showStatus(err.message, true);
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
            cancelBtn: document.getElementById('feedback-cancel'),
        };
        openBtn.addEventListener('click', openModal);
        document.getElementById('feedback-close').addEventListener('click', closeModal);
        els.cancelBtn.addEventListener('click', closeModal);
        // Click on the backdrop (outside the dialog box) closes it
        dialog.addEventListener('click', function (e) {
            if (e.target === dialog) closeModal();
        });
        dialog.addEventListener('close', cancelAutoClose);
        // The user is doing something in the dialog: never close it under them
        ['keydown', 'pointerdown', 'focusin', 'input'].forEach(function (type) {
            dialog.addEventListener(type, cancelAutoClose);
        });
        els.message.addEventListener('input', updateCharCount);
        els.form.addEventListener('submit', submit);
    }

    window.Hydrograf.feedback = {
        init: init,
    };
})();
