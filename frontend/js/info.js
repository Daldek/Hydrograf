/**
 * Hydrograf explanation markers.
 *
 * A small round (i) button after a label opens one shared panel with the
 * structured text from Hydrograf.infoTexts, in the order of Nogat DEV-15.14:
 * title and symbol, definition, formulas with the "gdzie:" list of variables
 * and the unit, how to read the value, the literature line "Źródła:" and the
 * link to the longer explanation in the guide. Formulas are typeset as MathML
 * built with DOM calls from the notation described in info-texts.js (never
 * from HTML).
 *
 * The panel opens only on a click or tap of the (i), or Enter or Space on it
 * (never on hover or focus); the same (i) again, Esc, a click or tap outside
 * the panel, or moving the focus to another control closes it. It stays
 * inside the panel that holds the button and scrolls when taller. Selects
 * with per-option texts (UH model, Tc method, Nash estimation) also get a
 * compact applicability note under them that follows the selected option.
 * Static elements marked data-info="<key>" get an (i) at start-up; content
 * rendered later calls Hydrograf.info.attach(el, key).
 */
(function () {
    'use strict';

    window.Hydrograf = window.Hydrograf || {};

    var TIP_ID = 'info-tip';
    var GAP = 6;            // px between the button and the panel
    var EDGE = 8;           // px kept free at the panel edges
    var MAX_WIDTH = 360;    // px
    var GUIDE_URL = '/instrukcja/';

    /** Form controls whose static <label for> gets an (i). */
    var FORM_FIELDS = [
        'hydro-duration', 'hydro-probability', 'hydro-hietogram-type',
        'hydro-alpha', 'hydro-beta', 'hydro-arf', 'hydro-amc',
        'hydro-uh-model', 'hydro-tc-method',
        'hydro-tc-runoff-coeff', 'hydro-tc-retardance',
        'hydro-nash-estimation',
        'hydro-snyder-ct', 'hydro-snyder-cp',
    ];

    /** Selects with a per-option applicability note ("<id>:<value>" texts). */
    var NOTE_SELECTS = ['hydro-uh-model', 'hydro-tc-method', 'hydro-nash-estimation'];

    var tip = null;
    var current = null;     // button whose explanation is open

    function texts() {
        return window.Hydrograf.infoTexts || {};
    }

    // ── Formula notation → MathML ──────────────────────────────────────

    var MATHML_NS = 'http://www.w3.org/1998/Math/MathML';
    var TOKEN = /\s+|\\text\{([^}]*)\}|\\([A-Za-z]+)|(\d+(?:,\d+)?)|([A-Za-zĄąĆćĘęŁłŃńÓóŚśŹźŻż]+)|([\u0370-\u03ff])|([\s\S])/y;
    var GREEK = { alpha: 'α', beta: 'β', lambda: 'λ', phi: 'φ', pi: 'π', psi: 'ψ', Gamma: 'Γ', Delta: 'Δ' };
    var OPERATORS = { cdot: '⋅', times: '×', le: '≤', ge: '≥', approx: '≈', sum: '∑' };
    var GLYPHS = { '-': '−', '·': '⋅', '*': '⋅' };
    var FENCES = { '(': ')', '[': ']' };
    var UPRIGHT = 'πeΓΔΣΦΩ';    // constants and capital Greek letters

    function tokenize(src) {
        var tokens = [];
        var m;
        TOKEN.lastIndex = 0;
        while (TOKEN.lastIndex < src.length && (m = TOKEN.exec(src)) !== null) {
            if (m[1] !== undefined) tokens.push({ t: 'text', v: m[1] });
            else if (m[2] !== undefined) tokens.push({ t: 'cmd', v: m[2] });
            else if (m[3] !== undefined) tokens.push({ t: 'num', v: m[3] });
            else if (m[4] !== undefined) tokens.push({ t: 'id', v: m[4] });
            else if (m[5] !== undefined) tokens.push({ t: 'id', v: m[5] });
            else if (m[6] !== undefined && m[6] !== '\\') {
                tokens.push('{}_^'.indexOf(m[6]) >= 0 ? { t: m[6] } : { t: 'op', v: m[6] });
            }
        }
        return tokens;
    }

    function mathNode(tag, children) {
        var node = document.createElementNS(MATHML_NS, tag);
        (children || []).forEach(function (child) {
            if (child) node.appendChild(child);
        });
        return node;
    }

    function mathLeaf(tag, text) {
        var node = document.createElementNS(MATHML_NS, tag);
        node.textContent = text;
        return node;
    }

    function identifier(name) {
        var mi = mathLeaf('mi', name);
        if (name.length === 1 && UPRIGHT.indexOf(name) >= 0) mi.setAttribute('mathvariant', 'normal');
        return mi;
    }

    /** <mrow> of the tokens up to `closer` ('}', ')', ']') or the end. */
    function parseRow(state, closer) {
        var row = mathNode('mrow');
        while (state.pos < state.tokens.length) {
            var tok = state.tokens[state.pos];
            if (tok.t === closer || (tok.t === 'op' && tok.v === closer)) break;
            var atom = parseAtom(state);
            if (atom) row.appendChild(parseScripts(state, atom));
        }
        return row;
    }

    function parseScripts(state, base) {
        var sub = null;
        var sup = null;
        for (;;) {
            var tok = state.tokens[state.pos];
            if (tok && tok.t === '_' && !sub) {
                state.pos++;
                sub = parseAtom(state) || mathNode('mrow');
            } else if (tok && tok.t === '^' && !sup) {
                state.pos++;
                sup = parseAtom(state) || mathNode('mrow');
            } else {
                break;
            }
        }
        if (sub && sup) return mathNode('msubsup', [base, sub, sup]);
        if (sub) return mathNode('msub', [base, sub]);
        if (sup) return mathNode('msup', [base, sup]);
        return base;
    }

    function parseAtom(state) {
        var tok = state.tokens[state.pos++];
        if (!tok) return null;
        if (tok.t === '{') {
            var group = parseRow(state, '}');
            state.pos++;                        // closing brace
            return group;
        }
        if (tok.t === 'num') return mathLeaf('mn', tok.v);
        if (tok.t === 'id') return identifier(tok.v);
        if (tok.t === 'text') return mathLeaf('mtext', tok.v);
        if (tok.t === 'cmd') return command(state, tok.v);
        if (tok.t === 'op' && FENCES[tok.v]) {
            var inner = parseRow(state, FENCES[tok.v]);
            state.pos++;                        // closing bracket
            return fenced(tok.v, inner);
        }
        if (tok.t === 'op') return operator(GLYPHS[tok.v] || tok.v);
        return null;                            // stray '}', '_' or '^'
    }

    /** ( ... ) as one group; the brackets grow only around fractions and roots. */
    function fenced(open, inner) {
        var tall = inner.querySelector('mfrac, msqrt') !== null;
        var fences = [open, FENCES[open]].map(function (glyph) {
            var mo = mathLeaf('mo', glyph);
            if (!tall) mo.setAttribute('stretchy', 'false');
            return mo;
        });
        return mathNode('mrow', [fences[0], inner, fences[1]]);
    }

    /** <mo>; a solidus is set tight, as in print. */
    function operator(glyph) {
        var mo = mathLeaf('mo', glyph);
        if (glyph === '/') {
            mo.setAttribute('lspace', '0');
            mo.setAttribute('rspace', '0');
        }
        return mo;
    }

    function command(state, name) {
        if (name === 'frac') {
            var numerator = parseAtom(state) || mathNode('mrow');
            return mathNode('mfrac', [numerator, parseAtom(state) || mathNode('mrow')]);
        }
        if (name === 'sqrt') return mathNode('msqrt', [parseAtom(state)]);
        if (GREEK[name]) return identifier(GREEK[name]);
        if (OPERATORS[name]) return operator(OPERATORS[name]);
        return mathLeaf('mtext', '\\' + name);
    }

    /** <math> for a formula; `display` uses full-size fractions and sums. */
    function formula(src, display) {
        var math = mathNode('math', [parseRow({ tokens: tokenize(src), pos: 0 }, null)]);
        if (display) math.setAttribute('displaystyle', 'true');
        return math;
    }

    /**
     * Polish typesetting: a number stays with the word after it (1 mm,
     * 250 km²), a range does not break after its dash (0,03–30) and a
     * one-letter word (i, w, z or a symbol such as L) never ends a line.
     */
    function typeset(text) {
        return text
            .replace(/(\d) (?=\S)/g, '$1\u00a0')
            .replace(/(\d)–(?=\d)/g, '$1–\u2060')
            .replace(/(^|\s)([A-Za-ząćęłńóśźżĄĆĘŁŃÓŚŹŻ]) /g, '$1$2\u00a0');
    }

    /**
     * Append `text` to `parent`; parts between $...$ become inline formulas.
     * Punctuation right after a formula stays on its line.
     */
    function richText(parent, text) {
        var parts = String(text).split('$');
        parts.forEach(function (part, i) {
            if (!part) return;
            if (i % 2 === 0) {
                parent.appendChild(document.createTextNode(typeset(part)));
                return;
            }
            var math = formula(part, false);
            var punct = /^[.,;:!?)]+/.exec(parts[i + 1] || '');
            if (!punct) {
                parent.appendChild(math);
                return;
            }
            var group = document.createElement('span');
            group.className = 'info-nowrap';
            group.appendChild(math);
            group.appendChild(document.createTextNode(punct[0]));
            parent.appendChild(group);
            parts[i + 1] = parts[i + 1].slice(punct[0].length);
        });
        return parent;
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
        btn.setAttribute('aria-expanded', 'false');
        btn.setAttribute('aria-controls', TIP_ID);
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

    /** Give every static element marked data-info="<key>" its (i). */
    function decorateMarked() {
        document.querySelectorAll('[data-info]').forEach(function (el) {
            if (!el.querySelector('.info-btn')) attach(el, el.dataset.info);
        });
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
        note.hidden = !(entry && entry.summary);
        if (!note.hidden) {
            var head = document.createElement('span');
            head.className = 'info-note-k';
            head.textContent = 'Zakres stosowalności: ';
            note.appendChild(head);
            richText(note, entry.summary);
        }
        if (current && current.dataset.infoKey === select.id) {
            render(current);
            position(current);
        }
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

    function element(tag, className, parent) {
        var node = document.createElement(tag);
        if (className) node.className = className;
        if (parent) parent.appendChild(node);
        return node;
    }

    /** Small bold caption: a line of its own unless `inline`. */
    function caption(text, parent, inline) {
        var node = element(inline ? 'span' : 'div', 'info-tip-k', parent);
        node.textContent = text;
        return node;
    }

    /** The "gdzie:" list: [symbol, meaning, unit?] rows. */
    function variableList(parent, rows) {
        var box = element('div', 'info-tip-where', parent);
        caption('gdzie:', box);
        var dl = element('dl', 'info-tip-vars', box);
        rows.forEach(function (row) {
            element('dt', null, dl).appendChild(formula(row[0], false));
            var dd = richText(element('dd', null, dl), '– ' + row[1]);
            if (row[2]) element('span', 'info-tip-u', dd).textContent = '\u00a0[' + row[2] + ']';
        });
    }

    /** Render one structured entry; `title` is used when it has none. */
    function renderEntry(parent, entry, title) {
        var head = element('div', 'info-tip-head', parent);
        head.appendChild(document.createTextNode(entry.title || title));
        if (entry.symbol) {
            head.appendChild(document.createTextNode(' '));
            head.appendChild(formula(entry.symbol, false));
        }
        if (entry.definition) richText(element('p', 'info-tip-def', parent), entry.definition);

        var formulas = [].concat(entry.formula || []);
        if (formulas.length) {
            var box = element('div', 'info-tip-formula', parent);
            formulas.forEach(function (src) {
                element('div', 'info-tip-eq', box).appendChild(formula(src, true));
            });
        }
        if (entry.variables && entry.variables.length) variableList(parent, entry.variables);
        if (entry.unit) {
            var unit = element('p', 'info-tip-unit', parent);
            caption('Jednostka:', unit, true);
            unit.appendChild(document.createTextNode(' ' + (entry.unit === '–' ? '– (wielkość bezwymiarowa)' : entry.unit)));
        }
        if (entry.reading) richText(element('p', 'info-tip-read', parent), entry.reading);
        if (entry.sources) {
            // A reference such as "USDA-NRCS 2007 (NEH 630-16)" does not break at its hyphens
            var sources = element('p', 'info-tip-src', parent);
            caption('Źródła:', sources, true);
            richText(sources, ' ' + entry.sources.replace(/(\w)-(?=\w)/g, '$1-\u2060'));
        }
        if (entry.guide) {
            // A new tab: leaving the map would lose the user's watershed and settings
            var link = element('a', null, element('p', 'info-tip-more', parent));
            link.href = GUIDE_URL + '#' + entry.guide;
            link.target = '_blank';
            link.rel = 'noopener';
            link.textContent = 'Więcej w instrukcji';
        }
    }

    function render(btn) {
        var key = btn.dataset.infoKey;
        var entry = texts()[key];
        tip.textContent = '';
        tip.scrollTop = 0;
        renderEntry(tip, typeof entry === 'string' ? { definition: entry } : entry, btn.dataset.infoLabel);

        var select = document.getElementById(key);
        if (select && select.tagName === 'SELECT') {
            var option = applicability(select);
            if (option) {
                var chosen = select.options[select.selectedIndex];
                var name = chosen ? chosen.textContent : select.value;
                var box = element('div', 'info-tip-option', tip);
                caption('Wybrana opcja', box);
                renderEntry(box, option, name);
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
        tip.style.maxHeight = Math.max(0, box.bottom - box.top - 2 * EDGE) + 'px';
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

    function show(btn) {
        if (current) hide();
        current = btn;
        render(btn);
        tip.hidden = false;
        btn.setAttribute('aria-expanded', 'true');
        btn.setAttribute('aria-describedby', TIP_ID);
        position(btn);
    }

    function hide() {
        if (!current) return;
        current.setAttribute('aria-expanded', 'false');
        current.removeAttribute('aria-describedby');
        current = null;
        tip.hidden = true;
    }

    function infoButton(target) {
        return target && target.closest ? target.closest('.info-btn') : null;
    }

    // ── Events (delegated, so rows rendered later work too) ────────────

    function onPointerDown(e) {
        if (current && !infoButton(e.target) && !tip.contains(e.target)) hide();
    }

    /** The keyboard moved the focus to another control (a click inside the panel moves it nowhere). */
    function onFocusOut(e) {
        if (current && e.target === current && e.relatedTarget && !tip.contains(e.relatedTarget)) hide();
    }

    /** Click, tap, Enter or Space on an (i): open its explanation, or close it when it is open. */
    function onClick(e) {
        var btn = infoButton(e.target);
        if (!btn) return;
        e.preventDefault();
        if (btn === current) hide();
        else show(btn);
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
        position(current);
    }

    function init() {
        tip = document.createElement('div');
        tip.id = TIP_ID;
        tip.className = 'info-tip';
        tip.hidden = true;
        document.body.appendChild(tip);

        FORM_FIELDS.forEach(decorateLabel);
        NOTE_SELECTS.forEach(addNote);
        decorateMarked();

        document.addEventListener('pointerdown', onPointerDown, true);
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
