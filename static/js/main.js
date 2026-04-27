document.addEventListener('DOMContentLoaded', function () {
    const userDropdown = document.querySelector('.user-dropdown');
    const guideButton = document.getElementById('guideButton');
    const guideModal = document.getElementById('guideModal');
    const guideClose = document.getElementById('guideClose');

    if (guideButton && guideModal && guideClose) {
        const openGuide = function () {
            guideModal.classList.add('active');
            guideModal.setAttribute('aria-hidden', 'false');
            guideClose.focus();
        };

        const closeGuide = function () {
            guideModal.classList.remove('active');
            guideModal.setAttribute('aria-hidden', 'true');
            guideButton.focus();
        };

        guideButton.addEventListener('click', openGuide);
        guideClose.addEventListener('click', closeGuide);

        guideModal.addEventListener('click', function (event) {
            if (event.target === guideModal) {
                closeGuide();
            }
        });

        document.addEventListener('keydown', function (event) {
            if (event.key === 'Escape' && guideModal.classList.contains('active')) {
                closeGuide();
            }
        });
    }

    if (userDropdown) {
        const userBtn = userDropdown.querySelector('.user-btn');
        const menu = userDropdown.querySelector('.dropdown-menu');
        if (!userBtn || !menu) return;

        userBtn.addEventListener('click', function (event) {
            event.stopPropagation();
            const isOpen = userDropdown.classList.toggle('open');
            userBtn.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
        });

        document.addEventListener('click', function (event) {
            if (!userDropdown.contains(event.target)) {
                userDropdown.classList.remove('open');
                userBtn.setAttribute('aria-expanded', 'false');
            }
        });

        document.addEventListener('keydown', function (event) {
            if (event.key === 'Escape') {
                userDropdown.classList.remove('open');
                userBtn.setAttribute('aria-expanded', 'false');
            }
        });
    }
});
