/**
 * Hydrograf explanation markers.
 *
 * A small round (i) button after a label opens one shared tooltip with the
 * text from Hydrograf.infoTexts: on hover, on keyboard focus and on tap
 * (tap or click pins it, a second one closes it); Esc or a tap outside closes
 * it. The tooltip stays inside the panel that holds the button. Selects with
 * applicability texts (UH model, Tc method, Nash estimation) also get a
 * compact note under them that follows the selected option.
 */
(function () {
    'use strict';

    window.Hydrograf = window.Hydrograf || {};

    var TIP_ID = 'info-tip';
    var GAP = 6;            // px between the button and the tooltip
    var EDGE = 8;           // px kept free at the panel edges
    var MAX_WIDTH = 280;    // px
    var HIDE_DELAY_MS = 120;

    /** Form controls whose static <label for> gets an (i). */
    var FORM_FIELDS = [
        'hydro-duration', 'hydro-probability', 'hydro-hietogram-type',
        'hydro-alpha', 'hydro-beta',
        'hydro-uh-model', 'hydro-tc-method',
        'hydro-tc-runoff-coeff', 'hydro-tc-retardance', 'hydro-tc-overland-length',
        'hydro-nash-estimation', 'hydro-nash-n',
        'hydro-snyder-ct', 'hydro-snyder-cp',
    ];

    /** Selects with a per-option applicability note ("<id>:<value>" texts). */
    var NOTE_SELECTS = ['hydro-uh-model', 'hydro-tc-method', 'hydro-nash-estimation'];

    var tip = null;
    var current = null;     // button whose tooltip is shown
    var pinned = false;     // opened by click/tap: survives mouse-out and scroll
    var hideTimer = null;
    var lastPointer = 'mouse';

    function texts() {
        return window.Hydrograf.infoTexts || {};
    }

    // ── Buttons ────────────────────────────────────────────────────────

    /** Create the (i) button for `key`; null when there is no text for it. */
    function button(key, label) {
        if (!texts()[key]) return null;
        var btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'info-btn';
        btn.dataset.infoKey = key;
        btn.dataset.infoLabel = label;
        btn.setAttribute('aria-label', 'Wyjaśnienie: ' + label);
        btn.textContent = 'i';
        return btn;
    }

    /** Append an (i) for `key` to `el`; label defaults to the element's text. */
    function attach(el, key, label) {
        var text = (label || el.textContent).replace(/\s+/g, ' ').trim();
        var btn = button(key, text);
        if (btn) el.appendChild(btn);
        return btn;
    }

    /** Wrap a static form label so the (i) sits right after it. */
    function decorateLabel(id) {
        var label = document.querySelector('label[for="' + id + '"]');
        if (!label || label.parentNode.classList.contains('info-label')) return;
        var btn = button(id, label.textContent.trim());
        if (!btn) return;
        var wrap = document.createElement('div');
        wrap.className = 'label info-label';
        label.parentNode.insertBefore(wrap, label);
        wrap.appendChild(label);
        wrap.appendChild(btn);
    }

    // ── Applicability notes ────────────────────────────────────────────

    function applicability(select) {
        var entry = texts()[select.id + ':' + select.value];
        return entry && typeof entry === 'object' ? entry : null;
    }

    function updateNote(select) {
        var note = document.getElementById(select.id + '-note');
        var entry = applicability(select);
        note.textContent = '';
        note.hidden = !entry;
        if (!entry) return;
        var head = document.createElement('span');
        head.className = 'info-note-k';
        head.textContent = 'Zakres stosowalności: ';
        note.appendChild(head);
        note.appendChild(document.createTextNode(entry.note));
        if (current && current.dataset.infoKey === select.id) render(current);
    }

    function addNote(id) {
        var select = document.getElementById(id);
        if (!select || document.getElementById(id + '-note')) return;
        var note = document.createElement('p');
        note.id = id + '-note';
        note.className = 'info-note';
        select.insertAdjacentElement('afterend', note);
        select.setAttribute('aria-describedby', note.id);
        select.addEventListener('change', function () { updateNote(select); });
        updateNote(select);
    }

    // ── Tooltip ────────────────────────────────────────────────────────

    function paragraph(text, heading) {
        var p = document.createElement('p');
        if (heading) {
            var strong = document.createElement('strong');
            strong.textContent = heading;
            p.appendChild(strong);
            p.appendChild(document.createElement('br'));
        }
        p.appendChild(document.createTextNode(text));
        return p;
    }

    function render(btn) {
        var key = btn.dataset.infoKey;
        tip.textContent = '';
        var title = document.createElement('div');
        title.className = 'info-tip-title';
        title.textContent = btn.dataset.infoLabel;
        tip.appendChild(title);
        tip.appendChild(paragraph(texts()[key]));

        var select = document.getElementById(key);
        if (select && select.tagName === 'SELECT') {
            var entry = applicability(select);
            if (entry) {
                var option = select.options[select.selectedIndex];
                tip.appendChild(paragraph(entry.text,
                    'Zakres stosowalności — ' + (option ? option.textContent : select.value)));
            }
        }
    }

    /** Visible area of the panel holding `btn`, clipped to the viewport. */
    function bounds(btn) {
        var box = { left: 0, top: 0, right: window.innerWidth, bottom: window.innerHeight };
        var panel = btn.closest('.view-panel');
        if (panel) {
            var r = panel.getBoundingClientRect();
            box.left = Math.max(box.left, r.left);
            box.top = Math.max(box.top, r.top);
            box.right = Math.min(box.right, r.right);
            box.bottom = Math.min(box.bottom, r.bottom);
        }
        return box;
    }

    function position(btn) {
        if (!btn.isConnected) { hide(); return; }
        var box = bounds(btn);
        var b = btn.getBoundingClientRect();
        if (b.bottom < box.top || b.top > box.bottom) { hide(); return; }

        tip.style.maxWidth = Math.max(0, Math.min(MAX_WIDTH, box.right - box.left - 2 * EDGE)) + 'px';
        tip.style.left = '0px';
        tip.style.top = '0px';
        var t = tip.getBoundingClientRect();

        var left = b.left + b.width / 2 - t.width / 2;
        left = Math.min(left, box.right - EDGE - t.width);
        left = Math.max(left, box.left + EDGE);

        var top = b.bottom + GAP;
        var below = top + t.height <= box.bottom - EDGE;
        if (!below) {
            var above = b.top - GAP - t.height;
            top = above >= box.top + EDGE ? above : Math.max(box.top + EDGE, box.bottom - EDGE - t.height);
        }
        tip.dataset.side = below ? 'below' : 'above';
        tip.style.left = Math.round(left) + 'px';
        tip.style.top = Math.round(top) + 'px';
    }

    function show(btn, pin) {
        clearTimeout(hideTimer);
        if (current && current !== btn) hide();
        current = btn;
        pinned = pin;
        render(btn);
        tip.hidden = false;
        btn.setAttribute('aria-describedby', TIP_ID);
        btn.classList.add('active');
        position(btn);
    }

    function hide() {
        clearTimeout(hideTimer);
        if (!current) return;
        current.removeAttribute('aria-describedby');
        current.classList.remove('active');
        current = null;
        pinned = false;
        tip.hidden = true;
    }

    function scheduleHide() {
        clearTimeout(hideTimer);
        hideTimer = setTimeout(hide, HIDE_DELAY_MS);
    }

    function infoButton(target) {
        return target && target.closest ? target.closest('.info-btn') : null;
    }

    // ── Events (delegated, so rows rendered later work too) ────────────

    function onPointerDown(e) {
        lastPointer = e.pointerType || 'mouse';
        if (current && !infoButton(e.target) && !tip.contains(e.target)) hide();
    }

    function onMouseOver(e) {
        if (lastPointer === 'touch') return;
        var btn = infoButton(e.target);
        if (btn) {
            if (btn !== current) show(btn, false);
            else clearTimeout(hideTimer);
        } else if (current && tip.contains(e.target)) {
            clearTimeout(hideTimer);
        }
    }

    function onMouseOut(e) {
        if (!current || pinned || lastPointer === 'touch') return;
        var from = infoButton(e.target) === current || tip.contains(e.target);
        var to = e.relatedTarget && (infoButton(e.relatedTarget) === current || tip.contains(e.relatedTarget));
        if (from && !to && !current.matches(':focus-visible')) scheduleHide();
    }

    function onFocusIn(e) {
        var btn = infoButton(e.target);
        if (btn && btn !== current) show(btn, false);
    }

    function onFocusOut(e) {
        if (current && e.target === current && !(e.relatedTarget && tip.contains(e.relatedTarget))) hide();
    }

    function onClick(e) {
        var btn = infoButton(e.target);
        if (!btn) return;
        e.preventDefault();
        if (btn === current && pinned) hide();
        else show(btn, true);
    }

    function onKeyDown(e) {
        if (e.key === 'Escape' && current) {
            e.stopPropagation();
            e.preventDefault();
            hide();
        }
    }

    function onScroll(e) {
        if (!current || (e.target && e.target.nodeType === 1 && tip.contains(e.target))) return;
        if (pinned) position(current);
        else hide();
    }

    function init() {
        tip = document.createElement('div');
        tip.id = TIP_ID;
        tip.className = 'info-tip';
        tip.setAttribute('role', 'tooltip');
        tip.hidden = true;
        document.body.appendChild(tip);

        FORM_FIELDS.forEach(decorateLabel);
        NOTE_SELECTS.forEach(addNote);

        document.addEventListener('pointerdown', onPointerDown, true);
        document.addEventListener('mouseover', onMouseOver);
        document.addEventListener('mouseout', onMouseOut);
        document.addEventListener('focusin', onFocusIn);
        document.addEventListener('focusout', onFocusOut);
        document.addEventListener('click', onClick);
        document.addEventListener('keydown', onKeyDown, true);
        document.addEventListener('scroll', onScroll, true);
        window.addEventListener('resize', function () { if (current) position(current); });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

    window.Hydrograf.info = {
        attach: attach,
    };
})();
