// Shared by preview tiles, favorites and the enlarged view.
window.photoEditor = (() => {
    const queues = new Map();
    const strengths = new Map();
    async function request(url, data) {
        const response = await fetch(url, data === undefined ? {} : {
            method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(data)
        });
        const result = await response.json();
        if (!response.ok || result.success === false) throw new Error(result.message || `HTTP ${response.status}`);
        return result;
    }
    function tiles(photo) {
        return Array.from(document.querySelectorAll('.photo-tile')).filter(
            tile => tile.querySelector('.filter-select')?.dataset.photo === photo);
    }
    function showImage(photo, url, filter) {
        for (const tile of tiles(photo)) {
            tile.querySelector('img').src = url;
            tile.querySelector('a.glightbox').href = url;
            tile.querySelector('.filter-select').value = filter;
        }
    }
    function applyFilter(photo, filter, strength = strengths.get(photo)) {
        const previous = queues.get(photo) || Promise.resolve();
        const operation = previous.then(async () => {
            if (filter === 'none') filter = 'original';
            const body = {photo, filter};
            if (strength !== undefined) body.strength = strength;
            let url;
            if (['polaroid', 'postcard'].includes(filter)) {
                await request('/api/set_photo_filter', body);
                url = '/static/prepared/' + photo.replace(/\.[^.]+$/, `_${filter}.jpg`);
            } else {
                const result = await request('/api/apply_filter', body);
                url = result.new_path;
            }
            showImage(photo, `${url}?v=${Date.now()}`, filter);
            document.dispatchEvent(new CustomEvent('photo-edit-updated', {detail: {photo, filter}}));
        });
        // Keep the queue usable after an error; the returned operation still rejects for the UI.
        queues.set(photo, operation.catch(error => console.error('Photo edit failed:', error)));
        return operation;
    }
    function setStrength(photo, strength) {
        strengths.set(photo, strength);
    }
    async function details(photo) {
        const result = await request('/api/photo_edits?photo=' + encodeURIComponent(photo));
        strengths.set(photo, result.strength);
        return result;
    }
    async function location(photo, location) {
        const result = await request('/api/photo_edits', {photo, location});
        for (const tile of tiles(photo)) {
            const caption = tile.querySelector('.photo-location');
            if (caption) caption.textContent = caption.title = result.location_text;
        }
        return result;
    }
    async function caption(photo, text, filter) {
        const result = await request(filter === 'polaroid' ? '/api/set_polaroid_text' : '/api/set_image_text',
            {photo, text});
        const path = ['polaroid', 'postcard'].includes(filter) ?
            photo.replace(/\.[^.]+$/, `_${filter}.jpg`) : photo;
        showImage(photo, `/static/prepared/${path}?v=${Date.now()}`, filter);
        for (const tile of tiles(photo)) tile.querySelector('.generic-text-input').value = text;
        return result;
    }
    async function favorite(photo) {
        const result = await request('/api/toggle_favorite', {photo});
        for (const button of document.querySelectorAll('.favorite-btn')) {
            if (button.dataset.photo !== photo) continue;
            button.classList.toggle('text-yellow-400', result.is_favorite);
            button.classList.toggle('text-gray-400', !result.is_favorite);
        }
        return result;
    }
    async function remove(photo) {
        const response = await fetch('/delete_photo/' + photo.split('/').map(encodeURIComponent).join('/'),
            {method: 'DELETE'});
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
    }
    return {request, applyFilter, setStrength, details, location, caption, favorite, remove};
})();
