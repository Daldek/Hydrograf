/**
 * Hydrograf hand-off to Hydrolog (results panel, ADR-068, ADR-080, ADR-082).
 *
 * The API writes the current watershed as a hand-off nogat-handoff/1: the delineation
 * without rainfall and result (`handoff` of POST /api/delineate-watershed), each
 * hydrograph with its rainfall, runoff and result for comparison (`handoff` of POST
 * /api/generate-hydrograph), and the network of „Wybierz zlewnię” → „Sieć zlewni”
 * without rainfall and the sections of its reaches (`handoff` of POST
 * /api/delineate-network). The section serves the view the panel shows: the network
 * in the option „Sieć zlewni”, the watershed otherwise. "Kopiuj do Hydrologa" puts the
 * hand-off of what the panel shows on the clipboard and "Plik przekazania" downloads it as
 * <subject>.handoff.json; Hydrolog opens both with "Wczytaj z Hydrografa", a network in
 * „Sieć i trasowanie”. The labels, the file name, the text, the clipboard and the
 * download are those of Nogat's kit, the same in every GUI (DEV-15.5: nogat-handoff.js,
 * window.Hydrograf.nogat.handoff of js/nogat.js): without the Clipboard API (plain HTTP
 * outside localhost), or when the browser refuses it, the text goes selected into a
 * field for Ctrl+C. After a copy or a download the status links „Otwórz Hydrologa” when
 * the deployment names Hydrolog's address (HYDROGRAF_GUI).
 */
(function () {
    'use strict';

    window.Hydrograf = window.Hydrograf || {};

    var TARGET = 'hydrolog';    // the GUI the hand-off goes to
    var PRODUCER = 'hydrograf'; // this GUI, as the labels of Hydrolog name it
    var UH_MODELS = { scs: 'SCS', nash: 'Nasha', snyder: 'Snydera' };

    var kit = null; // the kit's hand-off module, window.Hydrograf.nogat.handoff

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

    /**
     * The status after a copy or a download: its text and, when the deployment names
     * Hydrolog's address, the link „Otwórz Hydrologa” to the tab the app menu opens it in.
     */
    function setStatus(text) {
        els.status.textContent = text;
        var address = text && window.Hydrograf.nogat.address(TARGET);
        if (!address) return;
        var link = document.createElement('a');
        link.href = address;
        link.target = 'nogat-' + TARGET;
        link.textContent = kit.TEXTS.open(TARGET);
        els.status.append(' ', link);
    }

    /** Hide the field of the copy by hand (the kit shows it; the CSS follows the field). */
    function hideFallback() {
        els.text.hidden = true;
        els.text.value = '';
    }

    function closeFallback() {
        hideFallback();
        setStatus('');
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
            '„' + kit.TEXTS.loadFrom(PRODUCER) + '” → „' + item + '”.';
    }

    /** The clipboard, else the field of the panel, selected for Ctrl+C (the kit's copy). */
    function copy() {
        var doc = current();
        if (!doc) return;
        hideFallback();
        kit.copyHandoff(doc, els.text).then(function (where) {
            var done = where === 'clipboard' ? kit.TEXTS.copied : kit.TEXTS.copyByHand;
            setStatus(done + ' ' + hydrologPath(kit.TEXTS.paste));
        });
    }

    function download() {
        var doc = current();
        if (!doc) return;
        hideFallback();
        var name = kit.downloadHandoff(doc);
        Hydrograf.api.countDownload();
        setStatus(kit.TEXTS.saved(name) + ' ' + hydrologPath(kit.TEXTS.openFile));
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
        var section = document.getElementById('handoff');
        // Without the kit (js/nogat.js not loaded) the section stays hidden
        if (!section || !window.Hydrograf.nogat) return;
        kit = window.Hydrograf.nogat.handoff;
        els.section = section;
        els.note = document.getElementById('handoff-note');
        els.copy = document.getElementById('handoff-copy');
        els.file = document.getElementById('handoff-file');
        els.status = document.getElementById('handoff-status');
        els.text = document.getElementById('handoff-text');
        els.copy.querySelector('.handoff-label').textContent = kit.TEXTS.copyTo(TARGET);
        els.file.querySelector('.handoff-label').textContent = kit.TEXTS.file;
        els.copy.addEventListener('click', copy);
        els.file.addEventListener('click', download);
        document.getElementById('handoff-fallback-close').addEventListener('click', closeFallback);
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
