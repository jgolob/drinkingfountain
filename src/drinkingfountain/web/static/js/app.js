document.addEventListener('DOMContentLoaded', function () {
    const form = document.getElementById('render-form');
    const renderBtn = document.getElementById('render-btn');
    const renderBtnText = document.getElementById('render-btn-text');
    const renderSpinner = document.getElementById('render-spinner');
    const newRenderBtn = document.getElementById('new-render-btn');
    const pauseRenderBtn = document.getElementById('pause-render-btn');
    const resumeRenderBtn = document.getElementById('resume-render-btn');
    const cancelRenderBtn = document.getElementById('cancel-render-btn');
    const errorDisplay = document.getElementById('error-display');
    const resultsSection = document.getElementById('results-section');
    const resultTitle = document.getElementById('result-title');
    const scriptDisplay = document.getElementById('script-display');
    const audioPlayerBar = document.getElementById('audio-player-bar');
    const audioPlayer = document.getElementById('audio-player');
    const downloadLink = document.getElementById('download-link');
    const progressPanel = document.getElementById('progress-panel');
    const progressStage = document.getElementById('progress-stage');
    const progressPercent = document.getElementById('progress-percent');
    const progressBar = document.getElementById('progress-bar');
    const progressMessage = document.getElementById('progress-message');
    const narratorVoiceSelect = document.getElementById('narrator-voice-select');
    const voiceOverrides = document.getElementById('voice-overrides');
    const voiceMapEmpty = document.getElementById('voice-map-empty');
    const addVoiceOverrideBtn = document.getElementById('add-voice-override');
    const scriptInput = document.getElementById('script');
    const scriptFileInput = document.getElementById('script_file');

    let availableVoices = [];
    let overrideCount = 0;
    let scriptInfoTimer = null;
    let progressTimer = null;
    let currentRenderId = null;
    let currentProgressUrl = null;

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
            refreshScriptInfo();
        })
        .catch(() => {});

    scriptInput.addEventListener('input', function () {
        scheduleScriptInfoRefresh();
    });

    narratorVoiceSelect.addEventListener('change', function () {
        refreshScriptInfo();
    });

    scriptFileInput.addEventListener('change', function () {
        errorDisplay.classList.add('d-none');
        const file = scriptFileInput.files && scriptFileInput.files[0];
        if (!file) return;

        const reader = new FileReader();
        reader.onload = function () {
            scriptInput.value = String(reader.result || '');
            refreshScriptInfo();
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
        addVoiceOverrideRow('', '');
    });

    // Form submission
    form.addEventListener('submit', function (e) {
        e.preventDefault();
        errorDisplay.classList.add('d-none');
        resultsSection.classList.add('d-none');
        audioPlayerBar.classList.add('d-none');
        downloadLink.classList.add('d-none');
        renderBtn.disabled = true;
        renderBtnText.textContent = 'Rendering...';
        renderSpinner.classList.remove('d-none');
        showProgress({ stage: 'queued', message: 'Uploading render request', percent: 0 });
        setRenderControls('queued');

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

                if (resp.data.status === 'queued' && resp.data.progress_url) {
                    currentRenderId = resp.data.render_id;
                    currentProgressUrl = resp.data.progress_url;
                    pollProgress(resp.data.progress_url);
                    return;
                }

                finishRender(resp.data);
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
        downloadLink.classList.add('d-none');
        progressPanel.classList.add('d-none');
        newRenderBtn.classList.add('d-none');
        setRenderControls('idle');
        window.clearTimeout(progressTimer);
        currentRenderId = null;
        currentProgressUrl = null;
        audioPlayer.pause();
        audioPlayer.removeAttribute('src');
        scriptDisplay.innerHTML = '';
    });

    pauseRenderBtn.addEventListener('click', function () {
        sendRenderControl('pause');
    });

    resumeRenderBtn.addEventListener('click', function () {
        sendRenderControl('resume');
    });

    cancelRenderBtn.addEventListener('click', function () {
        sendRenderControl('cancel');
    });

    function sendRenderControl(action) {
        if (!currentRenderId) return;
        fetch('/' + action + '/' + currentRenderId, { method: 'POST' })
            .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, data: d }; }); })
            .then(function (resp) {
                if (!resp.ok || resp.data.error) {
                    throw new Error(resp.data.error || 'Could not update render.');
                }
                if (action === 'pause') {
                    setRenderControls('paused');
                    showProgress({ stage: 'paused', message: 'Render paused', percent: progressPercent.textContent });
                } else if (action === 'resume') {
                    setRenderControls('running');
                    showProgress({ stage: 'rendering', message: 'Render resumed', percent: progressPercent.textContent });
                    if (currentProgressUrl) pollProgress(currentProgressUrl);
                } else if (action === 'cancel') {
                    setRenderControls('cancelling');
                    showProgress({ stage: 'cancelling', message: 'Cancelling render', percent: progressPercent.textContent });
                }
            })
            .catch(function (err) {
                errorDisplay.textContent = err.message;
                errorDisplay.classList.remove('d-none');
            });
    }

    function pollProgress(progressUrl) {
        window.clearTimeout(progressTimer);
        fetch(progressUrl)
            .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, data: d }; }); })
            .then(function (resp) {
                if (!resp.ok || resp.data.error) {
                    throw new Error(resp.data.error || 'Render failed.');
                }

                showProgress(resp.data.progress || {});
                setRenderControls(resp.data.status);

                if (resp.data.status === 'complete') {
                    finishRender(resp.data);
                    return;
                }

                if (resp.data.status === 'cancelled') {
                    renderBtn.disabled = false;
                    renderBtnText.textContent = 'Render Audio';
                    renderSpinner.classList.add('d-none');
                    newRenderBtn.classList.remove('d-none');
                    setRenderControls('cancelled');
                    return;
                }

                if (resp.data.status === 'failed') {
                    throw new Error(resp.data.error || 'Render failed.');
                }

                progressTimer = window.setTimeout(function () {
                    pollProgress(progressUrl);
                }, 1000);
            })
            .catch(function (err) {
                renderBtn.disabled = false;
                renderBtnText.textContent = 'Render Audio';
                renderSpinner.classList.add('d-none');
                progressPanel.classList.add('d-none');
                errorDisplay.textContent = err.message;
                errorDisplay.classList.remove('d-none');
            });
    }

    function showProgress(progress) {
        const percentValue = Number.parseFloat(String(progress.percent || 0));
        const percent = Math.max(0, Math.min(100, Number.isNaN(percentValue) ? 0 : percentValue));
        progressPanel.classList.remove('d-none');
        progressStage.textContent = progress.stage || 'Rendering';
        progressPercent.textContent = Math.round(percent) + '%';
        progressBar.style.width = percent + '%';
        progressMessage.textContent = progress.message || 'Rendering...';
    }

    function finishRender(data) {
        renderBtn.disabled = false;
        renderBtnText.textContent = 'Render Audio';
        renderSpinner.classList.add('d-none');
        setRenderControls('complete');
        showProgress({ stage: 'complete', message: 'Render complete', percent: 100 });
        newRenderBtn.classList.remove('d-none');
        setupPlayer(data);
    }

    function setupPlayer(data) {
        resultTitle.textContent = data.script_title || 'Untitled';
        var durationMin = (data.duration / 60).toFixed(1);
        resultTitle.textContent += ' (' + durationMin + ' min)';

        audioPlayer.src = data.audio_url;
        audioPlayerBar.classList.remove('d-none');
        if (data.download_url) {
            downloadLink.href = data.download_url;
            downloadLink.download = data.download_name || '';
            downloadLink.classList.remove('d-none');
        }

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

    function scheduleScriptInfoRefresh() {
        window.clearTimeout(scriptInfoTimer);
        scriptInfoTimer = window.setTimeout(refreshScriptInfo, 450);
    }

    function refreshScriptInfo() {
        const scriptText = scriptInput.value.trim();
        if (!scriptText) {
            setVoiceMapEmpty('Add a script to populate characters and suggested voices.');
            return;
        }

        const existing = collectVoiceOverrides();
        const formData = new FormData();
        formData.append('script', scriptInput.value);
        formData.append('narrator_voice', narratorVoiceSelect.value || '');

        fetch('/api/script-info', { method: 'POST', body: formData })
            .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, data: d }; }); })
            .then(function (resp) {
                if (!resp.ok || resp.data.error) {
                    setVoiceMapEmpty(resp.data.error || 'Could not parse characters.');
                    return;
                }
                populateVoiceOverrides(resp.data.characters || [], resp.data.assignments || {}, existing);
            })
            .catch(function () {
                setVoiceMapEmpty('Could not parse characters.');
            });
    }

    function populateVoiceOverrides(characters, assignments, existing) {
        voiceOverrides.innerHTML = '';
        overrideCount = 0;

        if (!characters.length) {
            setVoiceMapEmpty('No dialogue characters found yet.');
            return;
        }

        voiceMapEmpty.classList.add('d-none');
        characters.forEach(function (character) {
            addVoiceOverrideRow(character, existing[character] || assignments[character] || '');
        });
    }

    function addVoiceOverrideRow(character, selectedVoice) {
        overrideCount++;
        const row = document.createElement('div');
        row.className = 'voice-override-row';
        row.innerHTML =
            '<div>' +
            '<input type="text" class="form-control" name="voice_char_' + overrideCount + '" placeholder="Character name" value="' + escapeHtml(character) + '">' +
            '</div>' +
            '<div>' +
            '<select class="form-select" name="voice_id_' + overrideCount + '">' +
            '<option value="">Select voice...</option>' +
            availableVoices.map(function (v) {
                var selected = v === selectedVoice ? ' selected' : '';
                return '<option value="' + escapeHtml(v) + '"' + selected + '>' + escapeHtml(v) + '</option>';
            }).join('') +
            '</select>' +
            '</div>' +
            '<div>' +
            '<button type="button" class="btn btn-outline-danger remove-override">Remove</button>' +
            '</div>';
        voiceOverrides.appendChild(row);
        row.querySelector('.remove-override').addEventListener('click', function () {
            row.remove();
            if (!voiceOverrides.children.length) {
                setVoiceMapEmpty('No character voice overrides configured.');
            }
        });
    }

    function collectVoiceOverrides() {
        const existing = {};
        voiceOverrides.querySelectorAll('.voice-override-row').forEach(function (row) {
            const characterInput = row.querySelector('input[name^="voice_char_"]');
            const voiceSelect = row.querySelector('select[name^="voice_id_"]');
            const character = characterInput ? characterInput.value.trim() : '';
            const voice = voiceSelect ? voiceSelect.value.trim() : '';
            if (character && voice) {
                existing[character] = voice;
            }
        });
        return existing;
    }

    function setVoiceMapEmpty(message) {
        voiceOverrides.innerHTML = '';
        overrideCount = 0;
        voiceMapEmpty.textContent = message;
        voiceMapEmpty.classList.remove('d-none');
    }

    function setRenderControls(status) {
        pauseRenderBtn.classList.add('d-none');
        resumeRenderBtn.classList.add('d-none');
        cancelRenderBtn.classList.add('d-none');

        if (status === 'queued' || status === 'running' || status === 'cancelling') {
            pauseRenderBtn.classList.toggle('d-none', status === 'cancelling');
            cancelRenderBtn.classList.remove('d-none');
        } else if (status === 'paused') {
            resumeRenderBtn.classList.remove('d-none');
            cancelRenderBtn.classList.remove('d-none');
        }
    }
});
