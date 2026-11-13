/**
 * Hydrograf Terms — the regulamin of a public deployment (DEV-15.7, DEV-15.8, DEV-15.12).
 *
 * One GET /api/terms: {url, operator_email}, both null on a local run, and the lines of
 * the service's PMAXTP data, {attribution, terms_notice}. With a url the page's footer
 * (#site-footer, the statement and the link „Regulamin”) is shown, every <nogat-app-menu>
 * and <nogat-sources> gets the `terms` attribute (the kit ends the menu's list and the
 * strip's dialog with „Regulamin”) and the hint of „Zgłoś uwagę” (#feedback-hint) names
 * the operator's e-mail for a reply. A failed or non-OK answer means no terms and no
 * lines. Loaded by the map and the guide. window.Hydrograf.terms.ready resolves to
 * {url, operator_email, attribution, terms_notice}, never rejects; the welcome window
 * shows the lines (js/welcome.js).
 */
(function () {
    'use strict';

    window.Hydrograf = window.Hydrograf || {};

    var NONE = { url: null, operator_email: null, attribution: [], terms_notice: [] };

    function text(value) {
        return typeof value === 'string' && value !== '' ? value : null;
    }

    function showFooter(url) {
        var footer = document.getElementById('site-footer');
        if (!footer) return;
        var link = document.getElementById('terms-link');
        if (link) link.href = url;
        footer.hidden = false;
    }

    function fillFeedbackHint(email) {
        var hint = document.getElementById('feedback-hint');
        if (!hint) return;
        var mail = document.createElement('a');
        mail.id = 'feedback-email';
        mail.href = 'mailto:' + email;
        mail.textContent = email;
        hint.replaceChildren(
            'Nie wpisuj danych osobowych. Jeśli chcesz odpowiedzi, napisz na ', mail);
    }

    function apply(terms) {
        if (!terms.url) return;
        showFooter(terms.url);
        document.querySelectorAll('nogat-app-menu, nogat-sources').forEach(function (element) {
            element.setAttribute('terms', terms.url);
        });
        if (terms.operator_email) fillFeedbackHint(terms.operator_email);
    }

    var ready = fetch('/api/terms')
        .then(function (response) { return response.ok ? response.json() : NONE; })
        .catch(function () { return NONE; })
        .then(function (body) {
            // The guide loads no attribution.js: it shows no lines
            var lines = Hydrograf.attribution ? Hydrograf.attribution.lines(body) : NONE;
            var terms = {
                url: body ? text(body.url) : null,
                operator_email: body ? text(body.operator_email) : null,
                attribution: lines.attribution,
                terms_notice: lines.terms_notice,
            };
            // Deferred: the document is parsed, every element above is there
            apply(terms);
            return terms;
        });

    window.Hydrograf.terms = {
        ready: ready,
    };
})();
