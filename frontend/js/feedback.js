/**
 * Hydrograf Feedback — the dialog „Zgłoś uwagę” (DEV-15.12).
 *
 * Sends the message and the context of the view: the map mode, its parameters (map,
 * clicked point, watershed scalars, hydrograph settings, profile line). No contact, no
 * page URL, no browser data and no event log; the API adds the app version. The hint
 * under the field names the operator's e-mail for a reply (js/terms.js).
 */
(function () {
    'use strict';

    window.Hydrograf = window.Hydrograf || {};

    var HYDROGRAPH_INPUT_IDS = [
        'hydro-duration', 'hydro-probability', 'hydro-hietogram-type',
        'hydro-alpha', 'hydro-beta', 'hydro-uh-model', 'hydro-tc-method',
        'hydro-tc-runoff-coeff', 'hydro-tc-retardance',
        'hydro-nash-estimation',
        'hydro-snyder-ct', 'hydro-snyder-cp',
    ];

    var els = {};
    // After a successful send the form stays locked until the dialog is closed
    var sent = false;
    var closeTimer = null;

    function readHydrographSettings() {
        var settings = {};
        HYDROGRAPH_INPUT_IDS.forEach(function (id) {
            var el = document.getElementById(id);
            if (el && el.value !== '') {
                settings[id.replace('hydro-', '')] = el.value;
            }
        });
        return settings;
    }

    function watershedSummary(data) {
        // Scalar fields only: the boundary GeoJSON would exceed the size limit of the API
        if (!data || !data.watershed) return null;
        var summary = {};
        Object.keys(data.watershed).forEach(function (key) {
            var value = data.watershed[key];
            if (value === null || typeof value !== 'object') {
                summary[key] = value;
            }
        });
        return summary;
    }

    /** The parameters of the view: what the user set up, nothing of the browser. */
    function readParameters() {
        var params = {};
        try {
            var map = Hydrograf.map && Hydrograf.map._getMap && Hydrograf.map._getMap();
            if (map) {
                var center = map.getCenter();
                params.map = {
                    center: { lat: center.lat, lng: center.lng },
                    zoom: map.getZoom(),
                    baseLayer: (Hydrograf.layers && Hydrograf.layers.getBaseLayerName)
                        ? Hydrograf.layers.getBaseLayerName() : null,
                    activeOverlays: (Hydrograf.layers && Hydrograf.layers.getActiveOverlays)
                        ? Hydrograf.layers.getActiveOverlays() : [],
                };
            }
            if (Hydrograf.app) {
                params.clickCoords = Hydrograf.app.getClickCoords();
                params.watershed = watershedSummary(Hydrograf.app.getCurrentWatershed());
                if (params.watershed && Hydrograf.map.getStreamsThreshold) {
                    params.watershed.streams_threshold_m2 = Hydrograf.map.getStreamsThreshold();
                }
            }
            params.hydrograph = readHydrographSettings();
            if (Hydrograf.profile && Hydrograf.profile.getLineLatLngs) {
                params.profileLine = Hydrograf.profile.getLineLatLngs();
            }
        } catch (err) {
            params.error = String(err).slice(0, 200);
        }
        return params;
    }

    function currentView() {
        return (Hydrograf.app && Hydrograf.app.getClickMode) ? Hydrograf.app.getClickMode() : 'browse';
    }

    function updateCharCount() {
        els.charCount.textContent = String(els.message.value.length);
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
        els.submitBtn.disabled = locked;
    }

    function resetForm() {
        sent = false;
        els.message.value = '';
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
            showStatus('Wiadomość nie może być pusta.', true);
            els.message.focus();
            return;
        }
        // Exactly the members the API accepts; any other one is refused (400)
        var payload = {
            message: message,
            context: {
                view: currentView(),
                station: null,
                parameters: readParameters(),
            },
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
            charCount: document.getElementById('feedback-char-count'),
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
