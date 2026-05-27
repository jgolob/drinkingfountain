document.addEventListener('DOMContentLoaded', function () {
    const form = document.getElementById('render-form');
    const renderBtn = document.getElementById('render-btn');
    const renderBtnText = document.getElementById('render-btn-text');
    const renderSpinner = document.getElementById('render-spinner');
    const newRenderBtn = document.getElementById('new-render-btn');
    const errorDisplay = document.getElementById('error-display');
    const resultsSection = document.getElementById('results-section');
    const resultTitle = document.getElementById('result-title');
    const scriptDisplay = document.getElementById('script-display');
    const audioPlayerBar = document.getElementById('audio-player-bar');
    const audioPlayer = document.getElementById('audio-player');
    const narratorVoiceSelect = document.getElementById('narrator-voice-select');
    const voiceOverrides = document.getElementById('voice-overrides');
    const addVoiceOverrideBtn = document.getElementById('add-voice-override');
    const scriptInput = document.getElementById('script');
    const scriptFileInput = document.getElementById('script_file');

    let availableVoices = [];
    let overrideCount = 0;

    // Load voices on page load
    fetch('/api/voices')
        .then(r => r.json())
        .then(data => {
            availableVoices = data.voices || [];
            availableVoices.forEach(v => {
                const opt = document.createElement('option');
                opt.value = v;
                opt.textContent = v;
                narratorVoiceSelect.appendChild(opt);
            });
        })
        .catch(() => {});

    scriptFileInput.addEventListener('change', function () {
        errorDisplay.classList.add('d-none');
        const file = scriptFileInput.files && scriptFileInput.files[0];
        if (!file) return;

        const reader = new FileReader();
        reader.onload = function () {
            scriptInput.value = String(reader.result || '');
        };
        reader.onerror = function () {
            errorDisplay.textContent = 'Could not read the selected script file.';
            errorDisplay.classList.remove('d-none');
            scriptFileInput.value = '';
        };
        reader.readAsText(file);
    });

    // Voice override management
    addVoiceOverrideBtn.addEventListener('click', function () {
        overrideCount++;
        const row = document.createElement('div');
        row.className = 'voice-override-row';
        row.innerHTML =
            '<div>' +
            '<input type="text" class="form-control" name="voice_char_' + overrideCount + '" placeholder="Character name">' +
            '</div>' +
            '<div>' +
            '<select class="form-select" name="voice_id_' + overrideCount + '">' +
            '<option value="">Select voice...</option>' +
            availableVoices.map(function (v) { return '<option value="' + v + '">' + v + '</option>'; }).join('') +
            '</select>' +
            '</div>' +
            '<div>' +
            '<button type="button" class="btn btn-outline-danger remove-override">Remove</button>' +
            '</div>';
        voiceOverrides.appendChild(row);
        row.querySelector('.remove-override').addEventListener('click', function () {
            row.remove();
        });
    });

    // Form submission
    form.addEventListener('submit', function (e) {
        e.preventDefault();
        errorDisplay.classList.add('d-none');
        resultsSection.classList.add('d-none');
        audioPlayerBar.classList.add('d-none');
        renderBtn.disabled = true;
        renderBtnText.textContent = 'Rendering...';
        renderSpinner.classList.remove('d-none');

        const formData = new FormData(form);

        fetch('/render', { method: 'POST', body: formData })
            .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, data: d }; }); })
            .then(function (resp) {
                renderBtn.disabled = false;
                renderBtnText.textContent = 'Render Audio';
                renderSpinner.classList.add('d-none');

                if (!resp.ok || resp.data.error) {
                    errorDisplay.textContent = resp.data.error || 'Render failed.';
                    errorDisplay.classList.remove('d-none');
                    return;
                }

                newRenderBtn.classList.remove('d-none');
                setupPlayer(resp.data);
            })
            .catch(function (err) {
                renderBtn.disabled = false;
                renderBtnText.textContent = 'Render Audio';
                renderSpinner.classList.add('d-none');
                errorDisplay.textContent = 'Network error: ' + err.message;
                errorDisplay.classList.remove('d-none');
            });
    });

    newRenderBtn.addEventListener('click', function () {
        resultsSection.classList.add('d-none');
        audioPlayerBar.classList.add('d-none');
        newRenderBtn.classList.add('d-none');
        audioPlayer.pause();
        audioPlayer.removeAttribute('src');
        scriptDisplay.innerHTML = '';
    });

    function setupPlayer(data) {
        resultTitle.textContent = data.script_title || 'Untitled';
        var durationMin = (data.duration / 60).toFixed(1);
        resultTitle.textContent += ' (' + durationMin + ' min)';

        audioPlayer.src = data.audio_url;
        audioPlayerBar.classList.remove('d-none');

        fetch(data.timing_url)
            .then(function (r) { return r.json(); })
            .then(function (timing) {
                renderScriptBlocks(timing.blocks || []);
                resultsSection.classList.remove('d-none');
                wireSync();
            })
            .catch(function () {
                resultsSection.classList.remove('d-none');
            });
    }

    function renderScriptBlocks(blocks) {
        scriptDisplay.innerHTML = '';
        blocks.forEach(function (block, idx) {
            var el = document.createElement('div');
            el.className = 'script-block block-' + block.type;
            el.dataset.start = block.start;
            el.dataset.end = block.end;
            el.dataset.index = idx;

            if (block.type === 'scene_heading') {
                el.innerHTML = '<div class="block-text">' + escapeHtml(block.text) + '</div>';
            } else if (block.type === 'dialogue') {
                el.innerHTML =
                    '<div class="block-character">' + escapeHtml(block.character || '') + '</div>' +
                    '<div class="block-text">' + escapeHtml(block.text) + '</div>';
            } else {
                el.innerHTML = '<div class="block-text">' + escapeHtml(block.text) + '</div>';
            }

            el.addEventListener('click', function () {
                audioPlayer.currentTime = parseFloat(block.start);
                if (audioPlayer.paused) {
                    audioPlayer.play();
                }
            });

            scriptDisplay.appendChild(el);
        });
    }

    function wireSync() {
        var blocks = scriptDisplay.querySelectorAll('.script-block');
        var lastActive = null;

        audioPlayer.addEventListener('timeupdate', function () {
            var t = audioPlayer.currentTime;
            var found = null;
            for (var i = 0; i < blocks.length; i++) {
                var s = parseFloat(blocks[i].dataset.start);
                var e = parseFloat(blocks[i].dataset.end);
                if (t >= s && t < e) {
                    found = blocks[i];
                    break;
                }
            }

            if (found !== lastActive) {
                if (lastActive) lastActive.classList.remove('active');
                if (found) {
                    found.classList.add('active');
                    found.scrollIntoView({ behavior: 'smooth', block: 'center' });
                }
                lastActive = found;
            }
        });
    }

    function escapeHtml(text) {
        var div = document.createElement('div');
        div.appendChild(document.createTextNode(text));
        return div.innerHTML;
    }
});
