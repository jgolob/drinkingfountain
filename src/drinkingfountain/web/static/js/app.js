document.addEventListener('DOMContentLoaded', function () {
    const form = document.getElementById('render-form');
    const inputSection = document.getElementById('input-section');
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
    const livePlaybackLayout = document.getElementById('live-playback-layout');
    const liveNowScene = document.getElementById('live-now-scene');
    const liveNowLine = document.getElementById('live-now-line');
    const liveScriptContext = document.getElementById('live-script-context');
    const sceneList = document.getElementById('scene-list');
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
    let currentMode = 'file';
    let liveStateUrl = null;
    let liveScenes = [];
    let liveReadyScenes = {};
    let liveCurrentScene = 0;
    let liveDownloadStarted = false;
    let syncHandler = null;

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

                if (resp.data.mode === 'live') {
                    currentMode = 'live';
                    currentRenderId = resp.data.live_id;
                    currentProgressUrl = resp.data.progress_url;
                    liveStateUrl = resp.data.progress_url;
                    liveScenes = resp.data.scenes || [];
                    liveReadyScenes = {};
                    liveCurrentScene = 0;
                    liveDownloadStarted = false;
                    setupLivePreview(resp.data);
                    pollLiveState(resp.data.progress_url);
                    return;
                }

                currentMode = 'file';
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
        resetToEditMode();
    });

    function resetToEditMode() {
        resultsSection.classList.add('d-none');
        audioPlayerBar.classList.add('d-none');
        downloadLink.classList.add('d-none');
        progressPanel.classList.add('d-none');
        newRenderBtn.classList.add('d-none');
        setRenderControls('idle');
        window.clearTimeout(progressTimer);
        currentRenderId = null;
        currentProgressUrl = null;
        currentMode = 'file';
        liveStateUrl = null;
        liveReadyScenes = {};
        liveScenes = [];
        liveCurrentScene = 0;
        liveDownloadStarted = false;
        audioPlayer.pause();
        audioPlayer.removeAttribute('src');
        scriptDisplay.innerHTML = '';
        sceneList.innerHTML = '';
        livePlaybackLayout.classList.add('d-none');
        scriptDisplay.classList.remove('d-none');
        resultsSection.classList.remove('live-active');
        inputSection.classList.remove('live-workspace');
        liveNowScene.textContent = 'Waiting for audio.';
        liveNowLine.textContent = 'The current line will appear here as playback moves.';
        liveScriptContext.innerHTML = '';
    }

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
                    if (currentMode === 'live' && resp.data.download_url) {
                        downloadLink.href = resp.data.download_url;
                        downloadLink.download = resp.data.download_name || '';
                        downloadLink.classList.remove('d-none');
                        showProgress({ stage: 'complete', message: 'Download ready', percent: 100 });
                        newRenderBtn.classList.remove('d-none');
                        return;
                    }
                    finishRender(resp.data);
                    return;
                }

                if (resp.data.status === 'cancelled') {
                    renderBtn.disabled = false;
                    renderBtnText.textContent = 'Render Audio';
                    renderSpinner.classList.add('d-none');
                    resetToEditMode();
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

    function pollLiveState(stateUrl) {
        window.clearTimeout(progressTimer);
        fetch(stateUrl)
            .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, data: d }; }); })
            .then(function (resp) {
                if (!resp.ok || resp.data.error) {
                    throw new Error(resp.data.error || 'Live preview failed.');
                }

                showProgress(resp.data.progress || {});
                setRenderControls(resp.data.status);
                liveReadyScenes = resp.data.ready_scenes || {};
                updateLiveSceneList(resp.data);

                if (resp.data.status === 'cancelled') {
                    renderBtn.disabled = false;
                    renderBtnText.textContent = 'Render Audio';
                    renderSpinner.classList.add('d-none');
                    resetToEditMode();
                    return;
                }

                if (resp.data.status === 'failed') {
                    throw new Error(resp.data.error || 'Live preview failed.');
                }

                if (!audioPlayer.src && liveReadyScenes[String(liveCurrentScene)]) {
                    playLiveScene(liveCurrentScene);
                }

                if (resp.data.status === 'complete' && resp.data.download_requested && !liveDownloadStarted) {
                    liveDownloadStarted = true;
                    startDownloadRender();
                }

                if (resp.data.status !== 'complete' || resp.data.download_requested) {
                    progressTimer = window.setTimeout(function () {
                        pollLiveState(stateUrl);
                    }, 750);
                }
            })
            .catch(function (err) {
                renderBtn.disabled = false;
                renderBtnText.textContent = 'Render Audio';
                renderSpinner.classList.add('d-none');
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
        resultsSection.classList.remove('live-active');
        inputSection.classList.remove('live-workspace');
        livePlaybackLayout.classList.add('d-none');
        scriptDisplay.classList.remove('d-none');
        sceneList.innerHTML = '';

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

    function setupLivePreview(data) {
        resultTitle.textContent = (data.script_title || 'Untitled') + ' (live)';
        resultsSection.classList.remove('d-none');
        audioPlayerBar.classList.remove('d-none');
        downloadLink.classList.add('d-none');
        inputSection.classList.add('live-workspace');
        resultsSection.classList.add('live-active');
        scriptDisplay.classList.add('d-none');
        livePlaybackLayout.classList.remove('d-none');
        liveNowScene.textContent = 'Waiting for scene 1.';
        liveNowLine.textContent = 'Rendering the first scene now.';
        liveScriptContext.innerHTML = '';
        renderLiveSceneList(data.scenes || []);
        audioPlayer.removeAttribute('src');
    }

    function renderLiveSceneList(scenes) {
        sceneList.innerHTML = '';
        scenes.forEach(function (scene) {
            const sceneEl = document.createElement('div');
            sceneEl.className = 'script-block live-scene';
            sceneEl.dataset.sceneIndex = scene.index;
            sceneEl.innerHTML =
                '<div class="live-scene-kicker">Scene ' + (scene.index + 1) + '</div>' +
                '<div class="block-text">' + escapeHtml(scene.heading || 'Untitled Scene') + '</div>' +
                '<div class="live-scene-status">Queued</div>';
            sceneEl.addEventListener('click', function () {
                jumpToLiveScene(scene.index);
            });
            sceneList.appendChild(sceneEl);
        });
    }

    function updateLiveSceneList(state) {
        (state.scenes || liveScenes).forEach(function (scene) {
            const sceneEl = sceneList.querySelector('[data-scene-index="' + scene.index + '"]');
            if (!sceneEl) return;
            sceneEl.classList.toggle('active', scene.index === liveCurrentScene);
            sceneEl.classList.toggle('rendering', state.rendering_scene === scene.index);
            sceneEl.classList.toggle('ready', Boolean(liveReadyScenes[String(scene.index)]));

            const status = sceneEl.querySelector('.live-scene-status');
            if (status) {
                if (scene.index === state.rendering_scene) {
                    status.textContent = 'Rendering';
                } else if (liveReadyScenes[String(scene.index)]) {
                    status.textContent = scene.index === liveCurrentScene ? 'Playing' : 'Ready';
                } else {
                    status.textContent = 'Queued';
                }
            }
        });
    }

    function jumpToLiveScene(sceneIndex) {
        if (!currentRenderId || currentMode !== 'live') return;
        audioPlayer.pause();
        audioPlayer.removeAttribute('src');
        liveCurrentScene = sceneIndex;
        liveNowScene.textContent = getSceneHeading(sceneIndex);
        liveNowLine.textContent = 'Rendering this scene now.';
        liveScriptContext.innerHTML = '';
        fetch('/live/' + currentRenderId + '/play/' + sceneIndex, { method: 'POST' })
            .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, data: d }; }); })
            .then(function (resp) {
                if (!resp.ok || resp.data.error) {
                    throw new Error(resp.data.error || 'Could not queue scene.');
                }
                showProgress({ stage: 'queued', message: 'Queued scene ' + (sceneIndex + 1), percent: 0 });
                if (liveStateUrl) pollLiveState(liveStateUrl);
            })
            .catch(function (err) {
                errorDisplay.textContent = err.message;
                errorDisplay.classList.remove('d-none');
            });
    }

    function playLiveScene(sceneIndex) {
        const ready = liveReadyScenes[String(sceneIndex)];
        if (!ready) {
            showProgress({ stage: 'buffering', message: 'Waiting for scene ' + (sceneIndex + 1), percent: progressPercent.textContent });
            return;
        }
        liveCurrentScene = sceneIndex;
        audioPlayer.src = ready.audio_url;
        audioPlayerBar.classList.remove('d-none');
        liveNowScene.textContent = getSceneHeading(sceneIndex);
        liveNowLine.textContent = 'Starting scene playback.';
        renderLiveTimingLines(ready.timing || [], sceneIndex);
        wireLiveSync(sceneIndex);
        audioPlayer.play().catch(function () {});
        updateLiveSceneList({ scenes: liveScenes, ready_scenes: liveReadyScenes });
    }

    audioPlayer.addEventListener('ended', function () {
        if (currentMode !== 'live') return;
        const nextScene = liveCurrentScene + 1;
        if (nextScene >= liveScenes.length) {
            setRenderControls('complete');
            showProgress({ stage: 'complete', message: 'Live preview complete', percent: 100 });
            newRenderBtn.classList.remove('d-none');
            return;
        }
        if (liveReadyScenes[String(nextScene)]) {
            playLiveScene(nextScene);
        } else {
            liveCurrentScene = nextScene;
            showProgress({ stage: 'buffering', message: 'Waiting for scene ' + (nextScene + 1), percent: progressPercent.textContent });
            if (liveStateUrl) pollLiveState(liveStateUrl);
        }
    });

    function wireLiveSync(sceneIndex) {
        if (syncHandler) {
            audioPlayer.removeEventListener('timeupdate', syncHandler);
        }
        syncHandler = function () {
            const ready = liveReadyScenes[String(sceneIndex)];
            const blocks = ready ? ready.timing || [] : [];
            let found = null;
            for (let i = 0; i < blocks.length; i++) {
                const s = parseFloat(blocks[i].start);
                const e = parseFloat(blocks[i].end);
                if (audioPlayer.currentTime >= s && audioPlayer.currentTime < e) {
                    found = blocks[i];
                    break;
                }
            }
            if (found) {
                showLiveLine(found, sceneIndex);
            }
        };
        audioPlayer.addEventListener('timeupdate', syncHandler);
    }

    function renderLiveTimingLines(blocks, sceneIndex) {
        liveScriptContext.innerHTML = '';
        blocks.forEach(function (block, idx) {
            const el = document.createElement('div');
            el.className = 'live-line block-' + block.type;
            el.dataset.sceneIndex = sceneIndex;
            el.dataset.start = block.start;
            el.dataset.end = block.end;
            el.dataset.index = idx;
            if (block.type === 'dialogue') {
                el.innerHTML =
                    '<div class="block-character">' + escapeHtml(block.character || '') + '</div>' +
                    '<div class="block-text">' + escapeHtml(block.text || '') + '</div>';
            } else {
                el.innerHTML = '<div class="block-text">' + escapeHtml(block.text || '') + '</div>';
            }
            liveScriptContext.appendChild(el);
        });
    }

    function showLiveLine(block, sceneIndex) {
        if (block.type === 'dialogue') {
            liveNowLine.innerHTML =
                '<div class="block-character">' + escapeHtml(block.character || '') + '</div>' +
                '<div class="block-text">' + escapeHtml(block.text || '') + '</div>';
        } else {
            liveNowLine.innerHTML = '<div class="block-text">' + escapeHtml(block.text || '') + '</div>';
        }
        liveScriptContext.querySelectorAll('.live-line.active').forEach(function (line) {
            line.classList.remove('active');
        });
        const currentLine = liveScriptContext.querySelector(
            '.live-line[data-scene-index="' + sceneIndex + '"][data-start="' + block.start + '"]'
        );
        if (currentLine) {
            currentLine.classList.add('active');
            currentLine.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }
    }

    function getSceneHeading(sceneIndex) {
        const scene = liveScenes.find(function (candidate) {
            return candidate.index === sceneIndex;
        });
        return scene ? scene.heading || 'Untitled Scene' : 'Scene ' + (sceneIndex + 1);
    }

    function startDownloadRender() {
        const downloadData = new FormData(form);
        downloadData.delete('live_preview');
        downloadData.set('create_download', 'on');
        fetch('/render', { method: 'POST', body: downloadData })
            .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, data: d }; }); })
            .then(function (resp) {
                if (!resp.ok || resp.data.error) {
                    throw new Error(resp.data.error || 'Download render failed.');
                }
                currentProgressUrl = resp.data.progress_url;
                pollProgress(resp.data.progress_url);
            })
            .catch(function (err) {
                errorDisplay.textContent = err.message;
                errorDisplay.classList.remove('d-none');
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

        if (currentMode === 'live') {
            if (status === 'queued' || status === 'running' || status === 'cancelling') {
                cancelRenderBtn.classList.remove('d-none');
            }
            return;
        }

        if (status === 'queued' || status === 'running' || status === 'cancelling') {
            pauseRenderBtn.classList.toggle('d-none', status === 'cancelling');
            cancelRenderBtn.classList.remove('d-none');
        } else if (status === 'paused') {
            resumeRenderBtn.classList.remove('d-none');
            cancelRenderBtn.classList.remove('d-none');
        }
    }
});
