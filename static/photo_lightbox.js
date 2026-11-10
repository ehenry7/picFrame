function attachPhotoLightboxActions(lightbox) {
    let cleanup = () => {};

    function showActions(slide) {
        if (!slide.slideNode || slide.slideNode !== lightbox.getActiveSlide()) return;
        cleanup();
        const tile = slide.trigger?.closest('.photo-tile');
        const sourceSelect = tile?.querySelector('.filter-select');
        if (!sourceSelect) return;
        const enlarged = slide.slideNode.querySelector('.gslide-image img');
        if (enlarged && enlarged.src !== tile.querySelector('img').src) {
            enlarged.src = tile.querySelector('img').src;
        }

        const bar = document.createElement('div');
        const observers = [];
        bar.className = 'photo-lightbox-actions';
        bar.setAttribute('role', 'group');
        bar.addEventListener('click', event => event.stopPropagation());
        bar.addEventListener('keydown', event => {
            if (event.key !== 'Escape') event.stopPropagation();
        });
        const filter = sourceSelect.cloneNode(true);
        filter.value = sourceSelect.value;
        filter.setAttribute('aria-label', sourceSelect.options[sourceSelect.selectedIndex].textContent.trim());
        bar.append(filter);
        filter.addEventListener('change', () => {
            sourceSelect.value = filter.value;
            sourceSelect.dispatchEvent(new Event('change', { bubbles: true }));
        });

        const caption = tile.querySelector('.generic-text-input');
        if (caption) {
            const input = caption.cloneNode(true);
            input.value = caption.value;
            input.removeAttribute('id');
            input.setAttribute('aria-label', caption.placeholder);
            input.addEventListener('input', () => {
                caption.value = input.value;
                caption.dispatchEvent(new Event('input', { bubbles: true }));
            });
            bar.append(input);
            const status = document.createElement('span');
            bar.append(status);
            const originalStatus = tile.querySelector('.generic-text-status');
            if (originalStatus) {
                const statusObserver = new MutationObserver(() => {
                    status.replaceChildren(...Array.from(originalStatus.childNodes, node => node.cloneNode(true)));
                });
                statusObserver.observe(originalStatus, { childList: true, subtree: true, attributes: true });
                observers.push(statusObserver);
            }
        }

        for (const selector of ['.favorite-btn', '.crop-photo-btn', '.delete-button']) {
            const original = tile.querySelector(selector);
            if (!original) continue;
            const button = original.cloneNode(true);
            button.setAttribute('aria-label', original.title);
            const icon = document.createElement('i');
            icon.className = selector === '.favorite-btn' ? 'fas fa-star' :
                selector === '.crop-photo-btn' ? 'fas fa-cut' : 'fas fa-trash-alt';
            icon.setAttribute('aria-hidden', 'true');
            button.replaceChildren(icon);
            button.addEventListener('click', () => {
                // Crop uses its existing modal, which must not sit underneath the lightbox.
                if (selector === '.crop-photo-btn') lightbox.close();
                original.click();
            });
            bar.append(button);
            const observer = new MutationObserver(() => {
                button.className = original.className;
                button.disabled = original.disabled;
            });
            observer.observe(original, { attributes: true, attributeFilter: ['class', 'disabled'] });
            observers.push(observer);
        }

        const image = tile.querySelector('img');
        const imageObserver = new MutationObserver(() => {
            const enlarged = slide.slideNode.querySelector('.gslide-image img');
            if (enlarged && enlarged.src !== image.src) enlarged.src = image.src;
        });
        imageObserver.observe(image, { attributes: true, attributeFilter: ['src'] });
        observers.push(imageObserver);
        slide.slideNode.closest('.glightbox-container').append(bar);
        cleanup = () => {
            observers.forEach(observer => observer.disconnect());
            bar.remove();
        };
    }

    lightbox.on('slide_after_load', showActions);
    lightbox.on('slide_before_change', ({ current }) => {
        cleanup();
        requestAnimationFrame(() => {
            if (current.slideIndex === lightbox.index) {
                showActions({ trigger: current.trigger, slideNode: lightbox.getActiveSlide() });
            }
        });
    });
    lightbox.on('slide_changed', ({ current }) => showActions(current));
    lightbox.on('close', () => cleanup());
}
