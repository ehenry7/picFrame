/* Filter menu: compact dropdown with real submenus.
 *
 * Wraps an existing <select class="filter-select"> (kept hidden in the DOM as
 * the state holder, so existing change handlers still work). Panels are
 * attached to <body> with fixed positioning so they are never clipped by
 * scrolling containers (photo tiles, lightbox toolbar) and always flip to
 * stay on screen.
 */
(function () {
    let openPanel = null;
    let openSubmenu = null;
    let counter = 0;

    function closeAll() {
        if (openPanel) { openPanel.remove(); openPanel = null; }
        if (openSubmenu) { openSubmenu.remove(); openSubmenu = null; }
    }

    function keepOnScreen(element, x, y) {
        element.style.left = x + 'px';
        element.style.top = y + 'px';
        const rect = element.getBoundingClientRect();
        if (rect.right > window.innerWidth - 8) {
            element.style.left = Math.max(8, x - rect.width - 6) + 'px';
        }
        if (rect.bottom > window.innerHeight - 8) {
            element.style.top = Math.max(8, y - rect.height - 30) + 'px';
        }
    }

    function createFilterMenu(select) {
        const menuId = 'fm' + (++counter);
        const wrap = document.createElement('div');
        wrap.className = 'filter-menu';

        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'filter-menu-button';
        const current = document.createElement('span');
        current.className = 'filter-menu-current';
        const chevron = document.createElement('i');
        chevron.className = 'fas fa-chevron-down';
        chevron.setAttribute('aria-hidden', 'true');
        button.append(current, chevron);
        wrap.append(button);

        const labelFor = value => {
            const option = Array.from(select.options).find(item => item.value === value);
            return option ? option.textContent.trim() : '';
        };
        const syncLabel = () => { current.textContent = labelFor(select.value); };
        syncLabel();
        select.addEventListener('change', syncLabel);

        function choose(option) {
            select.value = option.value;
            select.dispatchEvent(new Event('change', { bubbles: true }));
            syncLabel();
            closeAll();
        }

        function makeLeaf(option) {
            const item = document.createElement('button');
            item.type = 'button';
            item.className = 'filter-menu-item';
            if (option.value === select.value) {
                item.classList.add('active');
            }
            item.textContent = option.textContent.trim();
            item.addEventListener('click', event => {
                event.stopPropagation();
                choose(option);
            });
            return item;
        }

        function buildSubmenu(optgroup, anchorRect) {
            const submenu = document.createElement('div');
            submenu.className = 'filter-menu-panel filter-submenu open';
            submenu.style.cssText = 'position:fixed;z-index:1000002;min-width:210px;max-height:60vh;overflow-y:auto;';
            Array.from(optgroup.children).forEach(option => submenu.append(makeLeaf(option)));
            document.body.append(submenu);
            submenu.addEventListener('click', event => event.stopPropagation());
            keepOnScreen(submenu, anchorRect.right + 6, anchorRect.top);
            return submenu;
        }

        const panel = document.createElement('div');
        Array.from(select.children).forEach(node => {
            if (node.tagName === 'OPTGROUP') {
                const row = document.createElement('div');
                row.className = 'filter-menu-row';
                const groupButton = document.createElement('button');
                groupButton.type = 'button';
                groupButton.className = 'filter-menu-item filter-menu-group';
                const groupLabel = document.createElement('span');
                groupLabel.textContent = node.label;
                const arrow = document.createElement('i');
                arrow.className = 'fas fa-chevron-right';
                arrow.setAttribute('aria-hidden', 'true');
                groupButton.append(groupLabel, arrow);
                groupButton.addEventListener('click', event => {
                    event.stopPropagation();
                    if (openSubmenu) { openSubmenu.remove(); openSubmenu = null; }
                    openSubmenu = buildSubmenu(node, groupButton.getBoundingClientRect());
                });
                row.append(groupButton);
                panel.append(row);
            } else if (node.tagName === 'OPTION') {
                panel.append(makeLeaf(node));
            }
        });

        button.addEventListener('click', event => {
            event.stopPropagation();
            const alreadyOpen = openPanel && openPanel.dataset.menuId === menuId;
            closeAll();
            if (alreadyOpen) { return; }
            panel.dataset.menuId = menuId;
            panel.className = 'filter-menu-panel open';
            panel.style.cssText = 'position:fixed;z-index:1000001;min-width:210px;max-height:60vh;overflow-y:auto;';
            panel.addEventListener('click', clickEvent => clickEvent.stopPropagation());
            document.body.append(panel);
            const rect = button.getBoundingClientRect();
            keepOnScreen(panel, rect.left, rect.bottom + 6);
            openPanel = panel;
        });

        return wrap;
    }

    document.addEventListener('click', closeAll);
    document.addEventListener('keydown', event => {
        if (event.key === 'Escape') { closeAll(); }
    });
    window.addEventListener('resize', closeAll);

    window.createFilterMenu = createFilterMenu;
})();
