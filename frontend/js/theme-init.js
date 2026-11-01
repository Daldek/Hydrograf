/**
 * Hydrograf theme bootstrap.
 *
 * Loaded synchronously in <head> so the stored theme applies before first paint.
 * "auto" (or nothing stored) follows the OS colour scheme.
 */
(function () {
    'use strict';

    try {
        var theme = localStorage.getItem('nogat-theme');
        if (theme === 'light' || theme === 'dark') {
            document.documentElement.dataset.theme = theme;
        }
    } catch (e) {
        // Storage unavailable (privacy mode): keep the OS theme.
    }
})();
