/**
 * Hydrograf Draggable module.
 *
 * Makes an element draggable via its handle, using pointer events
 * for unified mouse + touch support. No external dependencies.
 */
(function () {
    'use strict';

    window.Hydrograf = window.Hydrograf || {};

    /**
     * Make an element draggable by its handle.
     *
     * @param {HTMLElement} element - The element to make draggable
     * @param {HTMLElement} handle - The drag handle (e.g. header bar)
     * @param {Object} [opts] - Options
     * @param {number} [opts.margin] - Minimum margin from viewport edges (px)
     */
    function makeDraggable(element, handle, opts) {
        var margin = (opts && opts.margin) || 8;
        var offsetX = 0;
        var offsetY = 0;
        var isDragging = false;

        handle.style.cursor = 'grab';
        handle.style.touchAction = 'none';

        handle.addEventListener('pointerdown', onPointerDown);

        function onPointerDown(e) {
            // Only primary button
            if (e.button !== 0) return;
            e.preventDefault();

            isDragging = true;
            handle.style.cursor = 'grabbing';

            var rect = element.getBoundingClientRect();
            offsetX = e.clientX - rect.left;
            offsetY = e.clientY - rect.top;

            handle.setPointerCapture(e.pointerId);
            handle.addEventListener('pointermove', onPointerMove);
            handle.addEventListener('pointerup', onPointerUp);
        }

        function onPointerMove(e) {
            if (!isDragging) return;

            var newLeft = e.clientX - offsetX;
            var newTop = e.clientY - offsetY;

            // Clamp to viewport
            var vw = window.innerWidth;
            var vh = window.innerHeight;
            var rect = element.getBoundingClientRect();

            newLeft = Math.max(margin, Math.min(newLeft, vw - rect.width - margin));
            newTop = Math.max(margin, Math.min(newTop, vh - rect.height - margin));

            element.style.left = newLeft + 'px';
            element.style.top = newTop + 'px';
            element.style.right = 'auto';
        }

        function onPointerUp(e) {
            isDragging = false;
            handle.style.cursor = 'grab';
            handle.releasePointerCapture(e.pointerId);
            handle.removeEventListener('pointermove', onPointerMove);
            handle.removeEventListener('pointerup', onPointerUp);
        }
    }

    window.Hydrograf.draggable = {
        makeDraggable: makeDraggable,
    };
})();
