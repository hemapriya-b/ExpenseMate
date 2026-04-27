function initAuthScene(config) {
    const scene = document.querySelector(config.sceneSelector);
    if (!scene) return;

    const leftBubble = scene.querySelector('[data-bubble-left]');
    const rightBubble = scene.querySelector('[data-bubble-right]');
    const nameInput = document.querySelector(config.nameSelector);
    const passwordInputs = (config.passwordSelectors || [])
        .map((selector) => document.querySelector(selector))
        .filter(Boolean);
    const allInputs = Array.from(scene.querySelectorAll('input'));
    const leftCharacter = scene.querySelector('.auth-character.left');
    const rightCharacter = scene.querySelector('.auth-character.right');

    function setBubbleText() {
        const value = nameInput ? nameInput.value.trim() : '';
        const active = document.activeElement;
        const isPassword = passwordInputs.includes(active);

        if (isPassword) {
            if (leftBubble) leftBubble.textContent = config.leftMessages.password;
            if (rightBubble) rightBubble.textContent = config.rightMessages.password;
            return;
        }

        if (value) {
            if (leftBubble) leftBubble.textContent = `${config.leftMessages.namePrefix}, ${value}!`;
            if (rightBubble) rightBubble.textContent = `${config.rightMessages.namePrefix}, ${value}.`;
            return;
        }

        if (active && active.id && config.leftMessages[active.id]) {
            if (leftBubble) leftBubble.textContent = config.leftMessages[active.id];
        } else if (leftBubble) {
            leftBubble.textContent = config.leftMessages.idle;
        }

        if (active && active.id && config.rightMessages[active.id]) {
            if (rightBubble) rightBubble.textContent = config.rightMessages[active.id];
        } else if (rightBubble) {
            rightBubble.textContent = config.rightMessages.idle;
        }
    }

    function updateAim() {
        const active = document.activeElement;
        if (!active || !scene.contains(active)) {
            scene.dataset.focus = 'idle';
            scene.classList.remove('is-password');
            if (leftCharacter) {
                leftCharacter.style.setProperty('--aim-y', '0px');
                leftCharacter.dataset.focusTarget = 'idle';
            }
            if (rightCharacter) {
                rightCharacter.style.setProperty('--aim-y', '0px');
                rightCharacter.dataset.focusTarget = 'idle';
            }
            setBubbleText();
            return;
        }

        const panelRect = scene.getBoundingClientRect();
        const fieldRect = active.getBoundingClientRect();
        const relativeMiddle = fieldRect.top - panelRect.top + (fieldRect.height / 2);
        const panelCenter = panelRect.height * 0.58;
        const shift = Math.max(-32, Math.min(32, (relativeMiddle - panelCenter) * 0.08));
        const focusId = active.id || 'idle';
        const isPassword = passwordInputs.includes(active);

        scene.dataset.focus = focusId;
        scene.classList.toggle('is-password', isPassword);

        if (leftCharacter) {
            leftCharacter.style.setProperty('--aim-y', `${shift}px`);
            leftCharacter.dataset.focusTarget = focusId;
        }

        if (rightCharacter) {
            rightCharacter.style.setProperty('--aim-y', `${shift}px`);
            rightCharacter.dataset.focusTarget = focusId;
        }

        setBubbleText();
    }

    allInputs.forEach((input) => {
        input.addEventListener('focus', updateAim);
        input.addEventListener('blur', () => setTimeout(updateAim, 0));
        input.addEventListener('input', setBubbleText);
    });

    window.addEventListener('resize', updateAim);
    updateAim();
    setBubbleText();
}
