document.addEventListener('DOMContentLoaded', function () {
    const userDropdown = document.querySelector('.user-dropdown');
    if (!userDropdown) return;

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
});
