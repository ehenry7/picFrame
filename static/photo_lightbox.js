function attachPhotoLightboxActions(lightbox) {
    let cleanup = () => {};
    let toolbarSlide = null;

    function showActions(slide) {
        if (!slide.slideNode || slide.slideNode !== lightbox.getActiveSlide()) return;
        if (toolbarSlide === slide.slideNode) return;
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
            filter.setAttribute('aria-label', filter.options[filter.selectedIndex].textContent.trim());
            sourceSelect.value = filter.value;
            sourceSelect.dispatchEvent(new Event('change', { bubbles: true }));
            updateStrengthAvailability();
        });
        const photo = sourceSelect.dataset.photo;
        const labels = window.photoEditLabels;
        const strengthLabel = document.createElement('label');
        strengthLabel.textContent = labels.strength;
        const strength = document.createElement('input');
        strength.type = 'range';
        strength.min = '0';
        strength.max = '100';
        strength.step = '1';
        strength.value = '100';
        strength.style.width = '90px';
        strength.disabled = true;
        const strengthValue = document.createElement('span');
        strengthValue.textContent = '100%';
        strengthLabel.append(strength, strengthValue);
        bar.append(strengthLabel);
        let detailsLoaded = false;
        function updateStrengthAvailability() {
            strength.disabled = !detailsLoaded || ['none', 'original', 'polaroid', 'postcard'].includes(filter.value);
        }
        strength.addEventListener('input', () => {
            strengthValue.textContent = strength.value + '%';
        });
        strength.addEventListener('change', async () => {
            try {
                const value = Number(strength.value) / 100;
                await photoEditor.applyFilter(photo, filter.value, value);
                photoEditor.setStrength(photo, value);
            } catch (error) { alert(error.message); }
        });
        photoEditor.details(photo).then(details => {
            if (!bar.isConnected) return;
            strength.value = Math.round(details.strength * 100);
            strengthValue.textContent = strength.value + '%';
            detailsLoaded = true;
            updateStrengthAvailability();
        }).catch(error => alert(error.message));

        const before = document.createElement('button');
        before.type = 'button';
        before.title = before.ariaLabel = labels.before;
        before.innerHTML = '<i class="fas fa-adjust" aria-hidden="true"></i>';
        bar.append(before);
        let comparing = false;
        const restore = () => {
            comparing = false;
            const image = slide.slideNode.querySelector('.gslide-image img');
            if (image) image.src = tile.querySelector('img').src;
        };
        const compare = () => {
            comparing = true;
            const image = slide.slideNode.querySelector('.gslide-image img');
            if (image) image.src = '/api/photo_edits?before=1&photo=' + encodeURIComponent(photo);
        };
        before.addEventListener('pointerdown', event => {
            before.setPointerCapture(event.pointerId);
            compare();
        });
        before.addEventListener('pointerup', restore);
        before.addEventListener('pointercancel', restore);
        before.addEventListener('lostpointercapture', restore);
        before.addEventListener('keydown', event => {
            if ([' ', 'Enter'].includes(event.key)) { event.preventDefault(); compare(); }
        });
        before.addEventListener('keyup', restore);
        before.addEventListener('blur', restore);

        const location = document.createElement('button');
        location.type = 'button';
        location.title = location.ariaLabel = labels.location;
        location.innerHTML = '<i class="fas fa-map-marker-alt" aria-hidden="true"></i>';
        bar.append(location);
        let locationDialog;

        const dateBtn = document.createElement('button');
        dateBtn.type = 'button';
        dateBtn.title = dateBtn.ariaLabel = labels.editDate;
        dateBtn.innerHTML = '<i class="fas fa-calendar" aria-hidden="true"></i>';
        bar.append(dateBtn);
        let dateDialog;
        dateBtn.addEventListener('click', async () => {
            try {
                const details = await photoEditor.details(photo);
                dateDialog = document.createElement('dialog');
                const form = document.createElement('form');
                const label = document.createElement('label');
                label.textContent = labels.captureDate;
                const input = document.createElement('input');
                input.type = 'date';
                const raw = details.date || '';
                if (raw) {
                    input.value = raw.split('T')[0];
                }
                label.append(input);
                form.append(label);
                const status = document.createElement('p');
                status.setAttribute('role', 'status');
                form.append(status);
                if (details.manual_date) {
                    const hint = document.createElement('p');
                    hint.style.cssText = 'font-size:0.8em;color:#888';
                    hint.textContent = labels.dateOverride;
                    form.append(hint);
                } else if (details.date_source === 'file') {
                    const hint = document.createElement('p');
                    hint.style.cssText = 'font-size:0.8em;color:#888';
                    hint.textContent = labels.dateFromFile || 'Date from file (no EXIF data)';
                    form.append(hint);
                }
                async function persistDate(value) {
                    const buttons = form.querySelectorAll('button');
                    buttons.forEach(button => button.disabled = true);
                    try {
                        await photoEditor.date(photo, value);
                        dateDialog.close();
                    } catch (error) {
                        status.textContent = error.message;
                    } finally { buttons.forEach(button => button.disabled = false); }
                }
                for (const key of ['save', 'clear', 'cancel']) {
                    const button = document.createElement('button');
                    button.type = key === 'save' ? 'submit' : 'button';
                    button.textContent = labels[key];
                    if (key === 'clear') button.onclick = () => persistDate('');
                    if (key === 'cancel') button.onclick = () => dateDialog.close();
                    form.append(button);
                }
                form.onsubmit = event => {
                    event.preventDefault();
                    persistDate(input.value);
                };
                dateDialog.append(form);
                slide.slideNode.closest('.glightbox-container').append(dateDialog);
                dateDialog.onclose = () => dateDialog.remove();
                dateDialog.showModal();
            } catch (error) { alert(error.message); }
        });

        location.addEventListener('click', async () => {
            try {
                const details = await photoEditor.details(photo);
                locationDialog = document.createElement('dialog');
                const form = document.createElement('form');
                const fields = {};
                for (const key of ['city', 'country']) {
                    const label = document.createElement('label');
                    label.textContent = labels[key];
                    const input = document.createElement('input');
                    input.value = details[key];
                    input.maxLength = 160;
                    fields[key] = input;
                    label.append(input);
                    form.append(label);
                }
                const countries = document.createElement('datalist');
                countries.id = 'photo-location-countries';
                details.countries.forEach(name => {
                    const option = document.createElement('option');
                    option.value = name;
                    countries.append(option);
                });
                fields.country.setAttribute('list', countries.id);
                form.append(countries);
                const status = document.createElement('p');
                status.setAttribute('role', 'status');
                form.append(status);
                async function persist(value) {
                    const buttons = form.querySelectorAll('button');
                    buttons.forEach(button => button.disabled = true);
                    try {
                        await photoEditor.location(photo, value);
                        locationDialog.close();
                    } catch (error) {
                        status.textContent = error.message;
                    } finally { buttons.forEach(button => button.disabled = false); }
                }
                for (const key of ['save', 'clear', 'cancel']) {
                    const button = document.createElement('button');
                    button.type = key === 'save' ? 'submit' : 'button';
                    button.textContent = labels[key];
                    if (key === 'clear') button.onclick = () => persist(null);
                    if (key === 'cancel') button.onclick = () => locationDialog.close();
                    form.append(button);
                }
                form.onsubmit = event => {
                    event.preventDefault();
                    persist({city: fields.city.value, country: fields.country.value});
                };
                locationDialog.append(form);
                slide.slideNode.closest('.glightbox-container').append(locationDialog);
                locationDialog.onclose = () => locationDialog.remove();
                locationDialog.showModal();
            } catch (error) { alert(error.message); }
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
            if (!comparing && enlarged && enlarged.src !== image.src) enlarged.src = image.src;
        });
        imageObserver.observe(image, { attributes: true, attributeFilter: ['src'] });
        observers.push(imageObserver);
        slide.slideNode.closest('.glightbox-container').append(bar);
        toolbarSlide = slide.slideNode;
        cleanup = () => {
            toolbarSlide = null;
            locationDialog?.remove();
            dateDialog?.remove();
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
