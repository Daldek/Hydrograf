/**
 * Hydrograf Shell module.
 *
 * Page chrome around the map: theme switch, side panels (desktop columns,
 * phone bottom sheets) and the column resizers. Whenever the map area changes
 * size (panel width or collapse, map bar wrapping, window resize) a
 * `hydrograf:layout` event is dispatched on window so the Leaflet map can
 * re-measure itself.
 */
(function () {
    'use strict';

    window.Hydrograf = window.Hydrograf || {};

    var THEME_KEY = 'nogat-theme';
    var WIDTH_KEY = 'hydrograf-panel-widths';
    var LIMITS = { left: { min: 260, max: 560 }, right: { min: 340, max: 720 } };
    var CENTRE_MIN = 480;
    var OTHER = { left: 'right', right: 'left' };

    var phone = window.matchMedia('(max-width: 860px)');

    var view = document.getElementById('view');
    var panels = {
        left: document.getElementById('layers-panel'),
        right: document.getElementById('results-panel'),
    };
    var resizers = {
        left: document.getElementById('left-resizer'),
        right: document.getElementById('right-resizer'),
    };
    var openLayersBtn = document.getElementById('open-layers');
    var openResultsBtn = document.getElementById('open-results');

    var state = {
        open: { left: true, right: false },   // desktop columns
        sheet: null,                          // phone: 'left' | 'right' | null
        width: { left: null, right: null },   // null = CSS default
    };

    var layoutFrame = 0;

    function load(key) {
        try { return JSON.parse(localStorage.getItem(key)); } catch (e) { return null; }
    }

    function save(key, value) {
        try {
            localStorage.setItem(key, typeof value === 'string' ? value : JSON.stringify(value));
        } catch (e) {
            // Storage unavailable: the setting lasts for this page only.
        }
    }

    /** Tell the map (and anyone else) that the map area changed size; once per frame. */
    function notifyLayout() {
        if (layoutFrame) return;
        layoutFrame = requestAnimationFrame(function () {
            layoutFrame = 0;
            window.dispatchEvent(new CustomEvent('hydrograf:layout'));
        });
    }

    // ===== Theme =====

    var themeButtons = {
        auto: document.getElementById('theme-auto'),
        light: document.getElementById('theme-light'),
        dark: document.getElementById('theme-dark'),
    };

    function applyTheme(choice) {
        if (choice === 'light' || choice === 'dark') {
            document.documentElement.dataset.theme = choice;
        } else {
            delete document.documentElement.dataset.theme;
        }
        Object.keys(themeButtons).forEach(function (k) {
            themeButtons[k].setAttribute('aria-pressed', String(k === choice));
        });
    }

    // ===== Panels =====

    function isOpen(side) {
        return phone.matches ? state.sheet === side : state.open[side];
    }

    function render() {
        ['left', 'right'].forEach(function (side) {
            panels[side].classList.toggle('open', state.sheet === side);
            panels[side].classList.toggle('collapsed', !state.open[side]);
            resizers[side].hidden = !state.open[side];
        });
        openLayersBtn.classList.toggle('show', !state.open.left);
        openResultsBtn.parentElement.classList.toggle('show', !state.open.right);
        openLayersBtn.setAttribute('aria-expanded', String(isOpen('left')));
        openResultsBtn.setAttribute('aria-expanded', String(isOpen('right')));
        applyWidths();
    }

    /**
     * Open a side panel: a desktop column, or the (only) bottom sheet on phones.
     * @param {'left'|'right'} side
     */
    function open(side) {
        if (phone.matches) state.sheet = side;
        else state.open[side] = true;
        render();
    }

    /**
     * Close a side panel (collapse the column, or drop the sheet on phones).
     * @param {'left'|'right'} side
     */
    function close(side) {
        if (phone.matches) {
            if (state.sheet === side) state.sheet = null;
        } else {
            state.open[side] = false;
        }
        render();
    }

    /**
     * Toggle a side panel.
     * @param {'left'|'right'} side
     */
    function toggle(side) {
        if (isOpen(side)) close(side);
        else open(side);
    }

    // ===== Resizers =====

    function cssDefault(side) {
        var v = parseInt(getComputedStyle(document.documentElement).getPropertyValue('--' + side + '-w'), 10);
        return isNaN(v) ? LIMITS[side].min : v;
    }

    function ownClamp(side, w) {
        return Math.min(LIMITS[side].max, Math.max(LIMITS[side].min, w));
    }

    function maxFor(side) {
        var o = OTHER[side];
        var otherW = state.open[o] ? ownClamp(o, state.width[o] == null ? cssDefault(o) : state.width[o]) : 0;
        return Math.max(LIMITS[side].min, Math.min(LIMITS[side].max, view.clientWidth - otherW - CENTRE_MIN));
    }

    function clampWidth(side, w) {
        return Math.min(maxFor(side), Math.max(LIMITS[side].min, w));
    }

    function currentWidth(side) {
        return clampWidth(side, state.width[side] == null ? cssDefault(side) : state.width[side]);
    }

    function applyWidths() {
        ['left', 'right'].forEach(function (side) {
            var prop = '--' + side + '-w';
            if (phone.matches) { view.style.removeProperty(prop); return; }
            if (!state.open[side]) { view.style.setProperty(prop, '0px'); return; }
            var w = currentWidth(side);
            view.style.setProperty(prop, w + 'px');
            resizers[side].setAttribute('aria-valuenow', String(w));
            resizers[side].setAttribute('aria-valuemax', String(maxFor(side)));
        });
    }

    function setWidth(side, w) {
        state.width[side] = w == null ? null : clampWidth(side, w);
        applyWidths();
        save(WIDTH_KEY, state.width);
    }

    function bindResizer(side) {
        var r = resizers[side];
        var sign = side === 'left' ? 1 : -1;   // the right panel grows when dragged left
        var drag = null;
        var lastDown = 0;

        // Double-click is detected here: preventDefault on pointerdown suppresses native dblclick.
        r.addEventListener('pointerdown', function (e) {
            if (phone.matches || e.button !== 0) return;
            e.preventDefault();
            r.focus();
            if (e.timeStamp - lastDown < 400) {
                lastDown = 0;
                setWidth(side, null);
                return;
            }
            lastDown = e.timeStamp;
            drag = { x: e.clientX, w: currentWidth(side) };
            r.setPointerCapture(e.pointerId);
            r.classList.add('dragging');
            document.body.classList.add('resizing');
        });
        r.addEventListener('pointermove', function (e) {
            if (!drag) return;
            if (Math.abs(e.clientX - drag.x) > 3) lastDown = 0;
            state.width[side] = clampWidth(side, drag.w + sign * (e.clientX - drag.x));
            applyWidths();
        });
        function endDrag() {
            if (!drag) return;
            drag = null;
            r.classList.remove('dragging');
            document.body.classList.remove('resizing');
            save(WIDTH_KEY, state.width);
        }
        r.addEventListener('pointerup', endDrag);
        r.addEventListener('pointercancel', endDrag);
        r.addEventListener('lostpointercapture', endDrag);

        r.addEventListener('keydown', function (e) {
            if (phone.matches) return;
            var step = e.shiftKey ? 64 : 16;
            var w = currentWidth(side);
            switch (e.key) {
                case 'ArrowRight': setWidth(side, w + sign * step); break;
                case 'ArrowLeft': setWidth(side, w - sign * step); break;
                case 'Home': setWidth(side, LIMITS[side].min); break;
                case 'End': setWidth(side, maxFor(side)); break;
                case 'Enter': setWidth(side, null); break;
                default: return;
            }
            e.preventDefault();
        });
    }

    // ===== Init =====

    Object.keys(themeButtons).forEach(function (k) {
        themeButtons[k].addEventListener('click', function () {
            save(THEME_KEY, k);
            applyTheme(k);
        });
    });
    var storedTheme = null;
    try { storedTheme = localStorage.getItem(THEME_KEY); } catch (e) { /* OS theme */ }
    applyTheme(storedTheme === 'light' || storedTheme === 'dark' ? storedTheme : 'auto');

    var storedWidths = load(WIDTH_KEY);
    if (storedWidths) {
        ['left', 'right'].forEach(function (side) {
            if (typeof storedWidths[side] === 'number') state.width[side] = ownClamp(side, storedWidths[side]);
        });
    }

    document.getElementById('layers-close').addEventListener('click', function () { close('left'); });
    openLayersBtn.addEventListener('click', function () { toggle('left'); });
    openResultsBtn.addEventListener('click', function () { toggle('right'); });
    document.querySelectorAll('.view-panel .grip').forEach(function (grip) {
        grip.addEventListener('click', function () {
            close(grip.closest('.view-panel') === panels.left ? 'left' : 'right');
        });
    });
    bindResizer('left');
    bindResizer('right');
    phone.addEventListener('change', render);
    window.addEventListener('resize', applyWidths);
    new ResizeObserver(notifyLayout).observe(document.getElementById('map-wrap'));
    // Phone: the sheets stop above the foot of the view (the strip of provider lines, the footer)
    var foot = document.getElementById('view-foot');
    new ResizeObserver(function () {
        view.style.setProperty('--view-foot-h', foot.offsetHeight + 'px');
    }).observe(foot);

    // Segmented radio groups: arrow keys move and select (roving tabindex)
    document.querySelectorAll('.seg[role="radiogroup"]').forEach(function (group) {
        var buttons = Array.prototype.slice.call(group.querySelectorAll('button'));
        buttons.forEach(function (b) {
            b.tabIndex = b.getAttribute('aria-checked') === 'true' ? 0 : -1;
        });
        group.addEventListener('keydown', function (e) {
            var d = (e.key === 'ArrowRight' || e.key === 'ArrowDown') ? 1
                : (e.key === 'ArrowLeft' || e.key === 'ArrowUp') ? -1 : 0;
            if (!d) return;
            e.preventDefault();
            var i = buttons.indexOf(document.activeElement);
            var next = buttons[(i + d + buttons.length) % buttons.length];
            next.focus();
            next.click();
        });
    });

    render();

    window.Hydrograf.shell = {
        open: open,
        close: close,
        isOpen: isOpen,
        isPhone: function () { return phone.matches; },
    };
})();
