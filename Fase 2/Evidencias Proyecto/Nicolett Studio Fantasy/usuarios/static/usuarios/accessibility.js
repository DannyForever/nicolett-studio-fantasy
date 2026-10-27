(() => {
    const toggle = document.getElementById('accessibilityToggle');
    const panel = document.getElementById('accessibilityPanel');
    const status = document.getElementById('accessibilityStatus');
    const voiceToggle = document.querySelector('[data-a11y-action="voice"]');
    const voiceOptions = document.getElementById('accessibilityVoiceOptions');
    const fontValue = document.getElementById('accessibilityFontValue');
    const fontButtons = document.querySelectorAll('[data-a11y-font]');
    const voiceRate = document.getElementById('accessibilityVoiceRate');
    if (!toggle || !panel || !status || !voiceToggle || !voiceOptions || !fontValue || fontButtons.length !== 2 || !voiceRate) return;

    const storageKey = 'nicolett-accessibility';
    const fontSteps = ['normal', 'large', 'larger'];
    const voiceRates = ['0.5', '0.75', '1', '1.25', '1.5', '1.75', '2'];
    const settings = { dark: false, contrast: false, font: 'normal', voiceRate: 1 };
    let recognition = null;
    let speechMode = '';
    let activeSpeech = null;
    let lastDictationField = null;

    const announce = (message) => {
        status.textContent = message;
    };

    const saveSettings = () => {
        try {
            window.localStorage.setItem(storageKey, JSON.stringify(settings));
        } catch (error) {
            announce('Los cambios se aplican, pero no se pueden guardar en este navegador.');
        }
    };

    try {
        const saved = JSON.parse(window.localStorage.getItem(storageKey) || '{}');
        settings.dark = saved.dark === true;
        settings.contrast = saved.contrast === true;
        settings.font = ['normal', 'large', 'larger'].includes(saved.font) ? saved.font : 'normal';
        settings.voiceRate = voiceRates.includes(String(saved.voiceRate)) ? Number(saved.voiceRate) : 1;
        if (settings.contrast) settings.dark = false;
    } catch (error) {
        announce('No se pudieron cargar los ajustes de accesibilidad guardados.');
    }

    const updateSettings = () => {
        document.documentElement.classList.toggle('accessibility-dark', settings.dark);
        document.documentElement.classList.toggle('accessibility-contrast', settings.contrast);
        if (settings.font === 'normal') {
            document.documentElement.removeAttribute('data-accessibility-font');
        } else {
            document.documentElement.setAttribute('data-accessibility-font', settings.font);
        }

        const darkButton = document.querySelector('[data-a11y-action="dark"]');
        const contrastButton = document.querySelector('[data-a11y-action="contrast"]');
        darkButton.setAttribute('aria-pressed', String(settings.dark));
        contrastButton.setAttribute('aria-pressed', String(settings.contrast));
        const fontIndex = fontSteps.indexOf(settings.font);
        const fontLabel = settings.font === 'larger' ? 'Muy grande' : settings.font === 'large' ? 'Grande' : 'Normal';
        fontValue.textContent = fontLabel;
        fontButtons.forEach((button) => {
            button.disabled = button.dataset.a11yFont === 'decrease' ? fontIndex === 0 : fontIndex === fontSteps.length - 1;
        });
        voiceRate.value = String(settings.voiceRate);
    };

    updateSettings();
    toggle.addEventListener('click', () => {
        const expanded = toggle.getAttribute('aria-expanded') === 'true';
        toggle.setAttribute('aria-expanded', String(!expanded));
        toggle.setAttribute('aria-label', expanded ? 'Abrir opciones de accesibilidad' : 'Cerrar opciones de accesibilidad');
        panel.hidden = expanded;
    });

    document.querySelector('[data-a11y-action="dark"]').addEventListener('click', () => {
        settings.dark = !settings.dark;
        if (settings.dark) settings.contrast = false;
        updateSettings();
        saveSettings();
        announce(settings.dark ? 'Modo oscuro activado. Se desactivó el contraste alto para evitar conflictos.' : 'Modo oscuro desactivado.');
    });

    document.querySelector('[data-a11y-action="contrast"]').addEventListener('click', () => {
        settings.contrast = !settings.contrast;
        if (settings.contrast) settings.dark = false;
        updateSettings();
        saveSettings();
        announce(settings.contrast ? 'Contraste alto activado. Se desactivó el modo oscuro para evitar conflictos.' : 'Contraste alto desactivado.');
    });

    fontButtons.forEach((button) => {
        button.addEventListener('click', () => {
            const currentIndex = fontSteps.indexOf(settings.font);
            const direction = button.dataset.a11yFont === 'increase' ? 1 : -1;
            const nextIndex = Math.max(0, Math.min(fontSteps.length - 1, currentIndex + direction));
            if (nextIndex === currentIndex) return;
            settings.font = fontSteps[nextIndex];
            updateSettings();
            saveSettings();
            announce(`Tamaño de letra ${fontValue.textContent.toLocaleLowerCase('es')}.`);
        });
    });

    voiceRate.addEventListener('change', () => {
        settings.voiceRate = Number(voiceRate.value);
        saveSettings();
        announce(`Velocidad de voz: ${voiceRate.options[voiceRate.selectedIndex].text}.`);
    });

    voiceToggle.addEventListener('click', () => {
        const expanded = voiceToggle.getAttribute('aria-expanded') === 'true';
        voiceToggle.setAttribute('aria-expanded', String(!expanded));
        voiceOptions.hidden = expanded;
    });

    const stopVoiceFeatures = () => {
        if (recognition) {
            recognition.abort();
            recognition = null;
        }
        window.speechSynthesis?.cancel();
        activeSpeech = null;
        announce('Lectura y escucha detenidas.');
    };

    const readPage = () => {
        if (!('speechSynthesis' in window) || typeof SpeechSynthesisUtterance === 'undefined') {
            announce('Este navegador no permite leer el contenido en voz alta.');
            return;
        }
        if (recognition) {
            recognition.abort();
            recognition = null;
        }
        const content = document.querySelector('main, [role="main"], #main-content, .main-content') || document.body;
        const readableContent = content.cloneNode(true);
        readableContent.querySelectorAll('#accessibilityWidget, script, style').forEach((element) => element.remove());
        const text = readableContent.innerText.trim();
        if (!text) {
            announce('No hay contenido disponible para leer.');
            return;
        }
        window.speechSynthesis.cancel();
        activeSpeech = new SpeechSynthesisUtterance(text);
        activeSpeech.lang = document.documentElement.lang || 'es-CL';
        activeSpeech.rate = settings.voiceRate;
        activeSpeech.onstart = () => announce('Leyendo el contenido de la página.');
        activeSpeech.onend = () => announce('Lectura finalizada.');
        activeSpeech.onerror = () => announce('No se pudo completar la lectura en voz alta.');
        window.speechSynthesis.speak(activeSpeech);
    };

    const getRecognitionConstructor = () => window.SpeechRecognition || window.webkitSpeechRecognition;
    const getRecognitionError = (error) => ({
        'not-allowed': 'No se otorgó permiso para usar el micrófono.',
        'service-not-allowed': 'El servicio de reconocimiento de voz no está permitido.',
        'no-speech': 'No se detectó voz. Inténtalo de nuevo.',
        network: 'No fue posible conectar con el servicio de reconocimiento de voz.',
        'audio-capture': 'No se encontró un micrófono disponible.',
    })[error] || 'Ocurrió un error durante el reconocimiento de voz.';

    const startListening = (mode) => {
        const Recognition = getRecognitionConstructor();
        if (!Recognition) {
            announce('El reconocimiento de voz no está disponible en este navegador. Prueba con Chrome o Edge actualizado.');
            return;
        }
        if (recognition) recognition.abort();
        window.speechSynthesis?.cancel();

        speechMode = mode;
        recognition = new Recognition();
        recognition.lang = document.documentElement.lang || 'es-CL';
        recognition.continuous = false;
        recognition.interimResults = false;
        recognition.onstart = () => announce(mode === 'dictation'
            ? 'El navegador procesará tu voz. Escuchando para dictar; habla ahora.'
            : 'El navegador procesará tu voz. Di “ir a mis citas”, “buscar…” o “leer página”.');
        recognition.onerror = (event) => announce(getRecognitionError(event.error));
        recognition.onend = () => {
            recognition = null;
        };
        recognition.onresult = (event) => {
            const phrase = Array.from(event.results)
                .map((result) => result[0].transcript)
                .join(' ')
                .trim();
            if (speechMode === 'dictation') insertDictation(phrase);
            else runVoiceCommand(phrase);
        };
        try {
            recognition.start();
        } catch (error) {
            recognition = null;
            announce('No se pudo iniciar el micrófono. Comprueba los permisos e inténtalo de nuevo.');
        }
    };

    const isDictationField = (element) => {
        if (!element || element.disabled || element.readOnly) return false;
        if (element.isContentEditable) return true;
        if (element instanceof HTMLTextAreaElement) return true;
        return element instanceof HTMLInputElement && ['text', 'search', 'email', 'tel', 'url'].includes(element.type);
    };

    document.addEventListener('focusin', (event) => {
        if (isDictationField(event.target)) lastDictationField = event.target;
    });

    const findDictationField = () => {
        if (isDictationField(lastDictationField) && lastDictationField.getClientRects().length) return lastDictationField;
        const focused = document.activeElement;
        if (isDictationField(focused)) return focused;
        return Array.from(document.querySelectorAll('input, textarea, [contenteditable="true"]'))
            .find((element) => isDictationField(element) && element.getClientRects().length);
    };

    const insertDictation = (text) => {
        const field = findDictationField();
        if (!field) {
            announce('Selecciona primero un campo de búsqueda o texto y vuelve a iniciar el dictado.');
            return;
        }
        field.focus();
        if (field.isContentEditable) {
            document.execCommand('insertText', false, text);
        } else if (field instanceof HTMLInputElement && field.type === 'email') {
            field.value = text;
        } else {
            const start = typeof field.selectionStart === 'number' ? field.selectionStart : field.value.length;
            const end = typeof field.selectionEnd === 'number' ? field.selectionEnd : field.value.length;
            field.setRangeText(text, start, end, 'end');
        }
        field.dispatchEvent(new Event('input', { bubbles: true }));
        announce('Texto dictado en el campo seleccionado.');
    };

    const normalize = (text) => text
        .normalize('NFD')
        .replace(/[\u0300-\u036f]/g, '')
        .toLocaleLowerCase('es')
        .trim();

    const runVoiceCommand = (phrase) => {
        const command = normalize(phrase);
        if (command === 'leer pagina' || command === 'leer el contenido') {
            readPage();
            return;
        }
        if (command === 'detener lectura' || command === 'detener') {
            stopVoiceFeatures();
            return;
        }
        if (command === 'volver atras' || command === 'regresar') {
            window.history.back();
            return;
        }
        if (command === 'abrir menu' || command === 'abrir el menu') {
            const menuToggle = Array.from(document.querySelectorAll('#clientMenuToggle, #publicMenuToggle, #adminSidebarToggle'))
                .find((button) => button.getClientRects().length && !button.disabled);
            if (menuToggle) {
                menuToggle.click();
                announce('Menú abierto.');
            } else announce('No hay un menú desplegable en esta página.');
            return;
        }
        if (command.startsWith('buscar ')) {
            const query = phrase.replace(/^\s*buscar\s+/i, '').trim();
            const search = Array.from(document.querySelectorAll('[data-client-search] input, input[type="search"], input[name="q"], input[name="search"]'))
                .find((field) => field.getClientRects().length && !field.disabled);
            if (!search) {
                announce('No hay un campo de búsqueda en esta página.');
                return;
            }
            search.focus();
            search.value = query;
            search.dispatchEvent(new Event('input', { bubbles: true }));
            announce(`Buscando ${query}.`);
            return;
        }

        const target = command.replace(/^(ir a|abrir)\s+/, '');
        const expandable = Array.from(document.querySelectorAll('button[aria-controls][aria-expanded]')).find((button) => {
            if (!button.getClientRects().length || button.disabled) return false;
            return normalize(`${button.innerText} ${button.getAttribute('aria-label') || ''}`).includes(target);
        });
        if (command.startsWith('abrir ') && expandable) {
            expandable.click();
            announce(`Menú ${expandable.getAttribute('aria-expanded') === 'true' ? 'abierto' : 'actualizado'}.`);
            return;
        }

        const link = Array.from(document.querySelectorAll('a[href]')).find((anchor) => {
            if (!anchor.getClientRects().length || anchor.getAttribute('aria-hidden') === 'true') return false;
            const label = normalize(`${anchor.innerText} ${anchor.getAttribute('aria-label') || ''}`);
            return label === target || label.includes(target);
        });
        if (link) {
            const destination = new URL(link.href, window.location.href);
            if (destination.origin === window.location.origin) {
                announce(`Abriendo ${link.innerText.trim() || link.getAttribute('aria-label')}.`);
                window.location.assign(destination.href);
                return;
            }
        }
        if (expandable) {
            expandable.click();
            announce('Se abrió la sección del menú solicitada.');
            return;
        }
        announce(`No encontré una opción para “${phrase}”. Prueba “ir a mis citas” o “buscar…”.`);
    };

    document.querySelectorAll('[data-a11y-voice]').forEach((button) => {
        button.addEventListener('click', () => {
            const action = button.dataset.a11yVoice;
            if (action === 'dictation' || action === 'commands') startListening(action);
            else if (action === 'read') readPage();
            else stopVoiceFeatures();
        });
    });

    document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape' && !panel.hidden) {
            panel.hidden = true;
            toggle.setAttribute('aria-expanded', 'false');
            toggle.focus();
        }
    });
    window.addEventListener('pagehide', () => {
        if (recognition) recognition.abort();
        window.speechSynthesis?.cancel();
    });
})();
