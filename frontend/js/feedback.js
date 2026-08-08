/**
 * Hydrograf Feedback — modal form for tester feedback submissions.
 */
(function () {
    'use strict';

    window.Hydrograf = window.Hydrograf || {};

    var els = {};
    var modal = null;

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
        els.status.classList.remove('d-none', 'text-danger', 'text-success');
        els.status.classList.add(isError ? 'text-danger' : 'text-success');
        els.status.textContent = msg;
    }

    function openModal() {
        if (Hydrograf.map && Hydrograf.map.isDrawing && Hydrograf.map.isDrawing()) {
            Hydrograf.map.cancelDrawing();
        }
        els.status.classList.add('d-none');
        updatePreview();
        modal.show();
    }

    async function submit() {
        var message = els.message.value.trim();
        if (!message) {
            showStatus('Opis nie może być pusty.', true);
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
            setTimeout(function () { modal.hide(); }, 2000);
        } catch (e) {
            showStatus(e.message, true);
        } finally {
            els.submitBtn.disabled = false;
        }
    }

    function init() {
        var modalEl = document.getElementById('feedback-modal');
        var openBtn = document.getElementById('feedback-open-btn');
        if (!modalEl || !openBtn || typeof bootstrap === 'undefined') return;

        els = {
            message: document.getElementById('feedback-message'),
            contact: document.getElementById('feedback-contact'),
            charCount: document.getElementById('feedback-char-count'),
            diagnosticsCheckbox: document.getElementById('feedback-diagnostics'),
            preview: document.getElementById('feedback-diagnostics-preview'),
            status: document.getElementById('feedback-status'),
            submitBtn: document.getElementById('feedback-submit-btn'),
        };
        modal = bootstrap.Modal.getOrCreateInstance(modalEl);
        openBtn.addEventListener('click', openModal);
        els.message.addEventListener('input', updateCharCount);
        els.submitBtn.addEventListener('click', submit);
        modalEl.addEventListener('shown.bs.modal', function () { els.message.focus(); });
    }

    window.Hydrograf.feedback = {
        init: init,
    };
})();
