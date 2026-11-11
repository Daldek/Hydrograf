/**
 * Hydrograf hand-off to Hydrolog (results panel, ADR-068, ADR-080).
 *
 * The API writes the current watershed as a hand-off nogat-handoff/1: the delineation
 * without rainfall and result (`handoff` of POST /api/delineate-watershed), each
 * hydrograph with its rainfall, runoff and result for comparison (`handoff` of POST
 * /api/generate-hydrograph), and the network of „Wybierz zlewnię” → „Sieć zlewni”
 * without rainfall and the sections of its reaches (`handoff` of POST
 * /api/delineate-network). The section serves the view the panel shows: the network
 * in the option „Sieć zlewni”, the watershed otherwise. "Kopiuj do Hydrologa" puts the
 * hand-off of what the panel shows on the clipboard and "Plik przekazania" downloads it as
 * <name>.handoff.json; Hydrolog opens both with "Wczytaj z Hydrografa", a network in
 * „Sieć i trasowanie”. Without the Clipboard API (plain HTTP outside localhost) the
 * copy goes through a selected text field, which stays open for Ctrl+C when the
 * browser refuses that too.
 */
(function () {
    'use strict';

    window.Hydrograf = window.Hydrograf || {};

    var UH_MODELS = { scs: 'SCS', nash: 'Nasha', snyder: 'Snydera' };

    var _watershed = null;  // delineation response the hand-off belongs to
    var _hydrograph = null; // hand-off of the hydrograph the panel shows for it
    var _network = null;    // hand-off of the network of „Sieć zlewni”
    var _networkStale = false; // the points changed after the network was delineated
    var _view = 'watershed';
    var els = {};

    /** The hand-off of what the panel shows: the network, the hydrograph or the watershed. */
    function current() {
        if (_view === 'network') return _networkStale ? null : _network;
        if (_hydrograph) return _hydrograph;
        return (_watershed && _watershed.handoff) || null;
    }

    /** The document as Hydrolog writes it: indented JSON and a final newline. */
    function documentText(doc) {
        return JSON.stringify(doc, null, 2) + '\n';
    }

    /** "<subject>.handoff.json" without the characters a file name cannot hold. */
    function fileName(subject) {
        var base = String(subject || '')
            .replace(/[\\/:*?"<>|\u0000-\u001f]+/g, '-')
            .replace(/\s+/g, ' ')
            .trim();
        return (base || 'hydrograf') + '.handoff.json';
    }

    /** Polish plural: 1 pole, 2–4 pola, 5+ pól. */
    function plural(n, one, few, many) {
        if (n === 1) return one;
        var mod10 = n % 10;
        var mod100 = n % 100;
        return (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) ? few : many;
    }

    /** A duration as the scenarios name it: 45 -> "45 min", 90 -> "1,5 h". */
    function durationText(minutes) {
        if (minutes < 60) return minutes + ' min';
        return String(minutes / 60).replace('.', ',') + ' h';
    }

    /** What the hand-off of a network holds, in words (counts of its nodes but the outlet). */
    function networkContents(doc) {
        var count = { subcatchment: 0, reach: 0, junction: 0 };
        doc.payload.nodes.forEach(function (node) {
            if (node.type in count) count[node.type] += 1;
        });
        return 'Zawiera sieć: ' +
            count.subcatchment + ' ' + plural(count.subcatchment, 'zlewnia', 'zlewnie', 'zlewni') + ', ' +
            count.reach + ' ' + plural(count.reach, 'odcinek', 'odcinki', 'odcinków') + ', ' +
            count.junction + ' ' + plural(count.junction, 'węzeł', 'węzły', 'węzłów') +
            ', bez opadu (opad sieci ustawisz w Hydrologu, w kroku „Sieć”) i bez przekrojów ' +
            'odcinków (n Manninga i szerokość uzupełnisz w Hydrologu).';
    }

    /** What the hand-off holds, in words. */
    function contents(doc) {
        if (_view === 'network') return networkContents(doc);
        var subcatchment = doc.payload.nodes[0];
        var origin = doc.provenance.watershed || {};
        var changed = origin.changed ? origin.changed.length : 0;
        var watershed = 'zlewnię' + (changed
            ? ' (' + changed + ' ' + plural(changed, 'pole zmienione', 'pola zmienione', 'pól zmienionych') +
                ' w trybie zaawansowanym)'
            : '');
        if (!subcatchment.rainfall) {
            return 'Zawiera samą ' + watershed + ', bez opadu i wyniku: hydrogram nie jest obliczony.';
        }
        var rain = doc.provenance.rainfall || {};
        var rainText = rain.source === 'pmaxtp'
            ? 'opad PMAXTP (p = ' + String(rain.probability_percent).replace('.', ',') + '%, ' +
                durationText(rain.duration_min) + ')'
            : 'własną serię opadu';
        var model = UH_MODELS[subcatchment.runoff.uh_model] || subcatchment.runoff.uh_model;
        return 'Zawiera ' + watershed + ', ' + rainText + ', hydrogram jednostkowy ' + model +
            ' i wynik (Qmax, tp, V) do porównania w Hydrologu.';
    }

    function setStatus(text) {
        els.status.textContent = text;
    }

    function hideFallback() {
        els.fallback.classList.add('d-none');
        els.text.value = '';
    }

    /** Show the hand-off of the current state: its contents, the buttons, no old status. */
    function render() {
        if (!els.section) return;
        var doc = current();
        els.section.hidden = _view === 'network' ? !_network : !_watershed;
        els.copy.disabled = !doc;
        els.file.disabled = !doc;
        if (doc) {
            els.note.textContent = contents(doc);
        } else {
            els.note.textContent = _view === 'network' && _network
                ? 'Punkty lub ich nazwy zmieniły się po obliczeniu charakterystyk: oblicz je ponownie, by przekazać sieć.'
                : '';
        }
        setStatus('');
        hideFallback();
    }

    /** Where Hydrolog opens the hand-off: a network in „Sieć i trasowanie”. */
    function hydrologPath(item) {
        return 'W Hydrologu: ' + (_view === 'network' ? '„Sieć i trasowanie” → ' : '') +
            '„Wczytaj z Hydrografa” → „' + item + '”.';
    }

    function copied() {
        setStatus('Skopiowano przekazanie. ' + hydrologPath('Wklej ze schowka'));
    }

    /**
     * Copy through the text field of the panel, selected; when the browser refuses
     * the copy the field stays open, selected, for Ctrl+C.
     */
    function copyThroughField(text) {
        els.text.value = text;
        els.fallback.classList.remove('d-none');
        els.text.focus();
        els.text.select();
        var ok = false;
        try { ok = document.execCommand('copy'); } catch (e) { ok = false; }
        if (ok) {
            hideFallback();
            copied();
        } else {
            setStatus('');
        }
    }

    function copy() {
        var doc = current();
        if (!doc) return;
        var text = documentText(doc);
        hideFallback();
        if (navigator.clipboard && window.isSecureContext) {
            navigator.clipboard.writeText(text).then(copied, function () { copyThroughField(text); });
        } else {
            copyThroughField(text);
        }
    }

    function download() {
        var doc = current();
        if (!doc) return;
        var name = fileName(doc.subject);
        var url = URL.createObjectURL(new Blob([documentText(doc)], { type: 'application/json' }));
        var link = document.createElement('a');
        link.href = url;
        link.download = name;
        link.hidden = true;
        document.body.appendChild(link);
        link.click();
        link.remove();
        setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
        hideFallback();
        setStatus('Pobrano plik „' + name + '”. ' + hydrologPath('Plik przekazania…'));
    }

    /** A new selection: its delineation response, null when there is none. */
    function showWatershed(data) {
        _watershed = data && data.watershed ? data : null;
        _hydrograph = null;
        render();
    }

    /**
     * The hydrograph the panel shows for a watershed: its hand-off, or null when the
     * result is hidden (an invalid form, an error). Answers about another watershed
     * are ignored.
     */
    function showHydrograph(data, handoff) {
        if (data !== _watershed) return;
        _hydrograph = handoff || null;
        render();
    }

    /**
     * The network of „Sieć zlewni” (js/network.js): its hand-off, null when there is
     * none; `stale` when the points or their names changed after it was computed, so it
     * is not handed off.
     */
    function showNetwork(handoff, stale) {
        _network = handoff || null;
        _networkStale = !!stale;
        render();
    }

    /** The view the panel serves: 'network' in „Sieć zlewni”, else 'watershed'. */
    function showView(view) {
        _view = view;
        render();
    }

    function init() {
        els.section = document.getElementById('handoff');
        if (!els.section) return;
        els.note = document.getElementById('handoff-note');
        els.copy = document.getElementById('handoff-copy');
        els.file = document.getElementById('handoff-file');
        els.status = document.getElementById('handoff-status');
        els.fallback = document.getElementById('handoff-fallback');
        els.text = document.getElementById('handoff-text');
        els.copy.addEventListener('click', copy);
        els.file.addEventListener('click', download);
        document.getElementById('handoff-fallback-close').addEventListener('click', hideFallback);
        render();
    }

    document.addEventListener('DOMContentLoaded', init);

    window.Hydrograf.handoff = {
        showWatershed: showWatershed,
        showHydrograph: showHydrograph,
        showNetwork: showNetwork,
        showView: showView,
    };
})();
