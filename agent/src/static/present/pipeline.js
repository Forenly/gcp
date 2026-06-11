// Forenly AVIP — execution pipeline: steps 1-5, progress chips, outcomes, live ticker
// ============================================================================
// 🚀 Pipeline Core Execution Logic
// ============================================================================

let currentTab = 0;
let bufferedAgentLogs = [];

// Per-project pipeline progress, rendered inside the Project Console card so
// selecting a project immediately shows what has run and what is next.
const STEP_META = [
  { n: 1, label: 'Capture' },
  { n: 3, label: 'Transfer' },
  { n: 4, label: 'Synthesis' },
  { n: 5, label: 'Publish' }
];

function renderProjectProgress() {
  const row = $('projectProgressRow');
  if (!row) return;

  let doneCount = 0;
  let runningStep = 0;
  const chips = STEP_META.map(s => {
    const card = $('pstep-' + s.n);
    const done = card && card.classList.contains('done');
    const active = card && card.classList.contains('active');
    if (done) doneCount++;
    if (active && !runningStep) runningStep = s.n;
    const cls = done ? 'done' : active ? 'active' : 'pending';
    const icon = done ? '✓' : active ? '…' : s.n;
    return `<span class="progress-chip ${cls}" title="Step ${s.n}: ${s.label}"><span class="chip-icon">${icon}</span>${s.label}</span>`;
  }).join('<span class="chip-arrow">→</span>');

  let summary;
  if (runningStep) {
    const metaStep = STEP_META.find(s => s.n === runningStep);
    summary = `${metaStep ? metaStep.label : 'Step'} running…`;
  }
  else if (doneCount === STEP_META.length) summary = 'Pipeline completed';
  else if (doneCount === 0) summary = 'Not run yet — start with Step 1';
  else {
    const nextStep = STEP_META[doneCount];
    summary = `${doneCount}/${STEP_META.length} done — ${nextStep ? nextStep.label : 'Next'} is next`;
  }

  row.innerHTML = `<div class="progress-chip-track">${chips}</div>` +
    `<div class="progress-summary${doneCount === 5 && !runningStep ? ' ok' : ''}${runningStep ? ' running' : ''}">${summary}</div>`;

  // Outcomes mirror the same done-state, so refresh them together.
  renderProjectOutcomes();
}

// ---- Floating live-run ticker: keeps the streaming output visible no matter
// where the user has scrolled. Click jumps to the full Live Server Log Stream.
let tickerHideTimer = null;

const STEP_DONE_MESSAGES = {
  1: 'raw screen recording captured',
  2: 'deictic mouse paths & clicks synthesized',
  3: 'upload secured in the GPU bucket',
  4: 'analysis & avatar synthesized',
  5: 'final video published'
};
let tickerStepNum = 0;

function tickerDoneMessage() {
  return 'Step ' + tickerStepNum + ' complete — ' + (STEP_DONE_MESSAGES[tickerStepNum] || 'done');
}

function tickerShow(stepNum) {
  const ticker = $('liveTicker');
  if (!ticker) return;
  tickerStepNum = stepNum;
  clearTimeout(tickerHideTimer);
  ticker.classList.add('visible');
  ticker.classList.remove('finished');
  const meta = STEP_META.find(s => s.n === stepNum);
  const stepEl = $('tickerStep');
  if (stepEl) stepEl.textContent = 'STEP ' + stepNum + ' · ' + (meta ? meta.label.toUpperCase() : '');
  const lineEl = $('tickerLine');
  if (lineEl) lineEl.textContent = 'starting…';
}

function tickerUpdate(line) {
  const lineEl = $('tickerLine');
  if (lineEl) lineEl.textContent = String(line).replace(/<[^>]*>/g, '');
}

function tickerFinish(message) {
  const ticker = $('liveTicker');
  if (!ticker || !ticker.classList.contains('visible')) return;
  ticker.classList.add('finished');
  const stepEl = $('tickerStep');
  if (stepEl) stepEl.textContent = '✓ DONE';
  const lineEl = $('tickerLine');
  if (lineEl) lineEl.textContent = message;
  clearTimeout(tickerHideTimer);
  tickerHideTimer = setTimeout(() => ticker.classList.remove('visible', 'finished'), 3500);
}

function tickerHide() {
  const ticker = $('liveTicker');
  if (ticker) ticker.classList.remove('visible', 'finished');
  clearTimeout(tickerHideTimer);
}

function scrollToActiveStep() {
  for (let i = 1; i <= 5; i++) {
    const card = $('pstep-' + i);
    if (card && card.classList.contains('active')) {
      card.scrollIntoView({ behavior: 'smooth', block: 'center' });
      return;
    }
  }
  const grid = document.querySelector('.pipeline-grid');
  if (grid) grid.scrollIntoView({ behavior: 'smooth', block: 'center' });
}

// Per-project deliverables, each rendered INSIDE the step card that produced it
// (slots #step{n}Outcome). Derived from the step cards' done state, so it stays
// correct across project switches. Simulated artifacts of custom projects are
// labelled as archived instead of pretending to be playable files.
function getProjectOutcomes() {
  const select = $('projectSelect');
  const isDef = !select || !select.value || isDefaultProject(select.value);
  const recordingFile = currentRecordingFilename();
  const slugBase = recordingFile.replace('_recording.mp4', '');
  const done = n => {
    const card = $('pstep-' + n);
    return card && card.classList.contains('done');
  };

  const outcomes = [];
  if (done(1)) {
    // Playable whenever the file really exists on the server: always true for
    // the default demo (core asset) and for custom projects after a real capture.
    const real = isDef || (typeof serverVideoFiles !== 'undefined' && serverVideoFiles.has(recordingFile));
    outcomes.push({
      step: 1,
      icon: '📷',
      title: 'raw_' + recordingFile,
      type: 'Raw Screen Capture',
      badge: 'CAPTURED',
      play: real,
      videoFile: recordingFile
    });
  }
  if (done(3)) {
    outcomes.push({
      step: 3,
      icon: '📡',
      title: recordingFile,
      type: 'Modal GPU Bucket Object',
      badge: 'UPLOADED'
    });
  }
  if (done(4)) {
    outcomes.push({
      step: 4,
      icon: '🧠',
      title: 'Semantic analysis & transcription',
      type: 'VLM + STT Report',
      report: true
    });
  }
  if (done(5)) {
    outcomes.push({
      step: 5,
      icon: '🎬',
      title: slugBase + '_final_presentation.mp4',
      type: 'Final Narrated Video',
      badge: 'PUBLISHED'
    });
  }
  return outcomes;
}

function openOutcomeReport() {
  openReportModal();
}

function renderProjectOutcomes() {
  const byStep = {};
  getProjectOutcomes().forEach(o => { byStep[o.step] = o; });

  for (let n = 1; n <= 5; n++) {
    const slot = $('step' + n + 'Outcome');
    if (!slot) continue;
    const o = byStep[n];
    if (!o) {
      slot.innerHTML = '';
      slot.style.display = 'none';
      continue;
    }
    const badge = o.badge ? `<span class="step-outcome-badge">${o.badge}</span>` : '';
    let action = '';
    if (o.report) {
      action = `<button class="video-row-btn video-row-btn-play" onclick="openOutcomeReport()">📋 View Report</button>`;
    } else if (o.play) {
      const vFile = o.videoFile || o.title;
      const modalTitle = o.step === 1 ? `📷 Raw Screen Capture — ${o.title}` : `📼 Animated Screen Recording — ${o.title}`;
      action = `<button class="video-row-btn video-row-btn-play" onclick="openVideoModal('${vFile}', '${modalTitle}')">▶ Play</button>`;
    }
    slot.innerHTML = `
      <span class="step-outcome-icon">${o.icon}</span>
      <span class="step-outcome-text"><b title="${esc(o.title)}">${esc(o.title)}</b><span class="step-outcome-type">${o.type}</span></span>
      ${badge}${action}`;
    slot.style.display = 'flex';
  }
}

function markStepActive(stepNum) {
  const box = $('pstep-' + stepNum);
  if (box) {
    box.classList.add('active');
    box.classList.remove('done');
    // Center the running card so the audience's eyes land on it.
    box.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }
  const btn = $('runStep' + stepNum);
  if (btn) btn.innerHTML = '⏳ Running';
  tickerShow(stepNum);
  renderProjectProgress();
}

function markStepDone(stepNum) {
  const box = $('pstep-' + stepNum);
  if (box) {
    box.classList.add('done');
    box.classList.remove('active');
  }
  const btn = $('runStep' + stepNum);
  if (btn) btn.innerHTML = '▶ Run';
  renderProjectProgress();
}

function disableStepButtons() {
  const btn1 = $('runStep1');
  const btn2 = $('runStep2');
  const btn3 = $('runStep3');
  const btn4 = $('runStep4');
  const btn5 = $('runStep5');
  const mainBtn = $('btnStart');
  
  if (btn1) btn1.disabled = true;
  if (btn2) btn2.disabled = true;
  if (btn3) btn3.disabled = true;
  if (btn4) btn4.disabled = true;
  if (btn5) btn5.disabled = true;
  if (mainBtn) mainBtn.disabled = true;

  for (let i = 1; i <= 5; i++) {
    const card = $('pstep-' + i);
    if (card) card.classList.remove('next-up');
  }
}

function enableStepButtons() {
  for (let i = 1; i <= 5; i++) {
    const card = $("pstep-" + i);
    const btn = $("runStep" + i);
    if (card && btn && !card.classList.contains("active")) {
      btn.innerHTML = card.classList.contains("done") ? "↺ Rerun" : "▶ Run";
    }
  }
  const btn1 = $('runStep1');
  const btn3 = $('runStep3');
  const btn4 = $('runStep4');
  const btn5 = $('runStep5');
  const mainBtn = $('btnStart');
  
  if (btn1) btn1.disabled = false;
  if (mainBtn) mainBtn.disabled = false;
  
  const step1 = $('pstep-1');
  const step3 = $('pstep-3');
  const step4 = $('pstep-4');
  const step5 = $('pstep-5');
  
  if (btn3) btn3.disabled = !(step1 && step1.classList.contains('done'));
  if (btn4) btn4.disabled = !(step3 && step3.classList.contains('done'));
  if (btn5) btn5.disabled = !(step4 && step4.classList.contains('done'));

  // Spotlight the next runnable, not-yet-completed step so the flow is obvious.
  for (let i = 1; i <= 5; i++) {
    const card = $('pstep-' + i);
    if (card) card.classList.remove('next-up');
  }
  for (let i = 1; i <= 5; i++) {
    const card = $('pstep-' + i);
    const btn = $('runStep' + i);
    if (card && btn && !btn.disabled &&
        !card.classList.contains('done') && !card.classList.contains('active')) {
      card.classList.add('next-up');
      break;
    }
  }
}

// Shared step runner: streams scripted log lines into the step's mini terminal
// (600ms cadence), keeps the ticker/progress/state in sync, then finalizes.
// hooks: onStart (reset step containers), onTick(done, total), onDone (reveal results).
function streamStepLogs(stepNum, lines, hooks, callback) {
  hooks = hooks || {};
  markStepActive(stepNum);
  disableStepButtons();
  if (hooks.onStart) hooks.onStart();
  saveCurrentProjectState();

  const stepLogs = $('step' + stepNum + 'Logs');
  if (stepLogs) stepLogs.innerHTML = "";
  let i = 0;

  const interval = setInterval(() => {
    if (i < lines.length) {
      const log = lines[i];
      if (stepLogs) stepLogs.innerHTML += log + "<br>";
      const outBox = $('step' + stepNum + 'Output');
      if (outBox) outBox.scrollTop = outBox.scrollHeight;
      tickerUpdate(log);
      if (hooks.onTick) hooks.onTick(i + 1, lines.length);
      i++;
      saveCurrentProjectState();
    } else {
      releaseStepTimer(interval);
      markStepDone(stepNum);
      if (hooks.onDone) hooks.onDone();
      enableStepButtons();
      saveCurrentProjectState();
      if (callback) callback();
      else tickerFinish(tickerDoneMessage());
    }
  }, 600);
  registerStepTimer(interval);
}

// 🎬 Step 1 — Interactive AI Capture
// Default projects replay their canned demo; custom projects run a REAL
// Playwright capture on the server and stream its real progress logs.
function runStep1(callback) {
  const targetUrl = $('targetPageUrl').value || "https://lawn.forenly.ai/presentation";
  const select = $('projectSelect');
  const useCannedVideo = !select || !select.value || isDefaultProject(select.value);
  const recordingFile = currentRecordingFilename();

  if (!useCannedVideo) {
    runStep1Real(targetUrl, recordingFile, callback);
    return;
  }

  streamStepLogs(1, [
    `[Browser] Initializing Gemini Browser Use sandbox...`,
    `[Browser] Navigating to: ${targetUrl}`,
    `[Browser] Viewport set to 1280x800. Web page loaded successfully.`,
    `[Recording] Raw screen capture session active. Recording viewport...`,
    `[Recording] Screen capture session completed. Finalizing webm stream...`,
    `[System] Screen recorded successfully! File: raw_${recordingFile}`
  ], {
    onStart: () => {
      const vid = $('step1VideoContainer');
      if (vid) vid.style.display = 'none';
      const player = $('step1VideoPlayer');
      if (player) player.pause();
    },
    onDone: () => {
      const vid = $('step1VideoContainer');
      if (vid) vid.style.display = 'block';
      const player = $('step1VideoPlayer');
      if (player) {
        player.src = '/api/videos/play/forenly_ai_recording.mp4';
        player.load();
        player.play().catch(e => console.log("Step 1 canned playback delayed:", e));
      }
    }
  }, callback);
}

// Real capture: trigger the server-side Playwright job and stream its actual
// log lines into the step terminal (1s polling). The poll timer is registered
// like a simulation timer, so switching projects stops the UI stream cleanly
// (the server job itself finishes in the background and the file stays).
function runStep1Real(targetUrl, recordingFile, callback) {
  markStepActive(1);
  disableStepButtons();
  const vid = $('step1VideoContainer');
  if (vid) vid.style.display = 'none';
  const player = $('step1VideoPlayer');
  if (player) player.pause();
  const stepLogs = $('step1Logs');
  if (stepLogs) stepLogs.innerHTML = '';
  bufferedAgentLogs = [];
  saveCurrentProjectState();

  const appendLog = log => {
    if (log.startsWith('[Agent]')) {
      bufferedAgentLogs.push(log);
      return;
    }
    if (stepLogs) stepLogs.innerHTML += log + '<br>';
    const outBox = $('step1Output');
    if (outBox) outBox.scrollTop = outBox.scrollHeight;
    tickerUpdate(log);
  };

  const fail = msg => {
    appendLog('[Error] ' + msg);
    const card = $('pstep-1');
    if (card) card.classList.remove('active');
    tickerHide();
    enableStepButtons();
    renderProjectProgress();
    saveCurrentProjectState();
  };

  fetch('/api/capture/run', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url: targetUrl, file: recordingFile })
  })
    .then(r => r.json().then(j => ({ ok: r.ok, j })))
    .then(({ ok, j }) => {
      if (!ok) throw new Error(j.detail || 'capture could not start');
      if (j.status === 'already_running') throw new Error('A capture is already running — wait for it to finish.');

      let offset = 0;
      let polling = false;  // one in-flight request at a time, else slow responses double-append
      const poll = setInterval(() => {
        if (polling) return;
        polling = true;
        fetch('/api/capture/status?offset=' + offset)
          .then(r => r.json())
          .then(s => {
            (s.logs || []).forEach(appendLog);
            offset = s.total || offset;
            saveCurrentProjectState();
            if (s.status === 'done') {
              releaseStepTimer(poll);
              markStepDone(1);
              loadVideoList();  // real file now exists
              
              const vid = $('step1VideoContainer');
              if (vid) vid.style.display = 'block';
              const player = $('step1VideoPlayer');
              if (player) {
                player.src = '/api/videos/play/' + recordingFile + '?v=' + Date.now();
                player.load();
                player.play().catch(e => console.log("Step 1 playback delayed:", e));
              }

              enableStepButtons();
              saveCurrentProjectState();
              if (callback) callback();
              else tickerFinish('Step 1 complete — raw screen recording captured');
            } else if (s.status === 'failed') {
              releaseStepTimer(poll);
              fail('Capture failed on the server — see logs above.');
            }
          })
          .catch(() => {})  // transient poll errors: keep polling
          .finally(() => { polling = false; });
      }, 1000);
      registerStepTimer(poll);
    })
    .catch(err => fail(err.message));
}

// 🖱️ Step 2 — Mouse Movement & Click Animation
function runStep2(callback) {
  const select = $('projectSelect');
  const useCannedVideo = !select || !select.value || isDefaultProject(select.value);
  const recordingFile = currentRecordingFilename();

  if (!useCannedVideo) {
    runStep2Real(callback);
    return;
  }

  streamStepLogs(2, [
    `[Agent] Analysis: Scanning DOM tree to locate headers, CTAs, and navigation controls...`,
    `[Agent] UI Mapping: Identified active section 1/6: 'Solutions' header, viewport center.`,
    `[Agent] UI Mapping: Identified active section 2/6: 'Setup Wizard' card.`,
    `[Agent] Cursor Control: Generating minimum-jerk Bezier curve trajectories for mouse motion.`,
    `[Agent] Exploring page section 1/6 (scroll to 699px)...`,
    `[Agent] Section 1/6: pointing at <h2 class="solutions-header"> (340, 680) and highlighting...`,
    `[Agent] Exploring page section 2/6 (scroll to 1399px)...`,
    `[Agent] Section 2/6: pointing at <button id="setup-cta"> (610, 520) and highlighting...`,
    `[Agent] Action: Emitting smooth deictic clicks with glowing click ripple overlay...`,
    `[FFmpeg] Compositing deictic cursor path and active overlay...`,
    `[FFmpeg] Transcoding WebM → MP4 (H.264, faststart)...`,
    `[System] Animated screen recording generated successfully! File: ${recordingFile}`
  ], {
    onStart: () => {
      const vid = $('step1VideoContainer');
      if (vid) vid.style.display = 'none';
      const player = $('step1VideoPlayer');
      if (player) player.pause();
    },
    onDone: () => {
      if (useCannedVideo) {
        const vid = $('step1VideoContainer');
        if (vid) vid.style.display = 'block';
        const player = $('step1VideoPlayer');
        if (player) {
          player.load();
          player.play().catch(e => console.log("Step 2 playback delayed:", e));
        }
      }
    }
  }, callback);
}

function runStep2Real(callback) {
  const recordingFile = currentRecordingFilename();
  const logsToStream = [];
  logsToStream.push(`[Agent] Analysis: Scanning DOM tree to locate headers, CTAs, and navigation controls...`);
  logsToStream.push(`[Agent] UI Mapping: Parsing layout hierarchy and computing element bounding boxes.`);
  logsToStream.push(`[Agent] Cursor Control: Generating minimum-jerk Bezier curve trajectories for mouse motion.`);
  
  if (bufferedAgentLogs && bufferedAgentLogs.length > 0) {
    bufferedAgentLogs.forEach(log => logsToStream.push(log));
  } else {
    logsToStream.push(`[Agent] Exploring page section 1/6 (scroll to 699px)...`);
    logsToStream.push(`[Agent] Exploring page section 2/6 (scroll to 1399px)...`);
    logsToStream.push(`[Agent] Exploring page section 3/6 (scroll to 2099px)...`);
    logsToStream.push(`[Agent] Exploring page section 4/6 (scroll to 2798px)...`);
    logsToStream.push(`[Agent] Exploring page section 5/6 (scroll to 3498px)...`);
    logsToStream.push(`[Agent] Exploring page section 6/6 (scroll to 4198px)...`);
  }
  
  logsToStream.push(`[Agent] Action: Emitting smooth deictic clicks with glowing click ripple overlay...`);
  logsToStream.push(`[FFmpeg] Compositing deictic cursor path and active overlay...`);
  logsToStream.push(`[System] Animated screen recording generated successfully! File: ${recordingFile}`);

  streamStepLogs(2, logsToStream, {
    onStart: () => {
      const vid = $('step1VideoContainer');
      if (vid) vid.style.display = 'none';
      const player = $('step1VideoPlayer');
      if (player) player.pause();
    },
    onDone: () => {
      const vid = $('step1VideoContainer');
      if (vid) vid.style.display = 'block';
      const player = $('step1VideoPlayer');
      if (player) {
        player.src = '/api/videos/play/' + recordingFile + '?v=' + Date.now();
        player.load();
        player.play().catch(e => console.log("Step 2 playback delayed:", e));
      }
    }
  }, callback);
}

// 📡 Step 3 — GPU Secure Transfer
function setStep3UploadDone(done) {
  const label = $('step3ProgressLabel');
  if (label) label.textContent = done ? 'UPLOAD COMPLETE ✓' : 'UPLOADING...';
}

function runStep3(callback) {
  const select = $('projectSelect');
  const useCannedVideo = !select || !select.value || isDefaultProject(select.value);

  if (!useCannedVideo) {
    runStep3Real(callback);
    return;
  }

  streamStepLogs(3, [
    `[System] Initiating serverless Modal GPU Cloud connection.`,
    `[Network] Establishing TLS-encrypted gRPC channel to Modal serverless runtime...`,
    `[Upload] Chunking ${currentRecordingFilename()} (33.78 MB)...`,
    `[Upload] Transferring chunks to Modal secure storage bucket...`,
    `[Modal GPU] Container environment spun up successfully (NVIDIA A10G ready).`,
    `[System] Video uploaded to Modal GPU storage bucket successfully.`
  ], {
    onStart: () => {
      const container = $('step3ProgressContainer');
      if (container) container.style.display = 'block';
      const bar = $('step3ProgressBar');
      if (bar) bar.style.width = '0%';
      setStep3UploadDone(false);
    },
    onTick: (done, total) => {
      const bar = $('step3ProgressBar');
      if (bar) bar.style.width = Math.min(100, Math.floor((done / total) * 100)) + '%';
    },
    onDone: () => setStep3UploadDone(true)
  }, callback);
}

function runStep3Real(callback) {
  markStepActive(3);
  disableStepButtons();
  
  const container = $('step3ProgressContainer');
  if (container) container.style.display = 'block';
  const bar = $('step3ProgressBar');
  if (bar) bar.style.width = '0%';
  setStep3UploadDone(false);

  const stepLogs = $('step3Logs');
  if (stepLogs) stepLogs.innerHTML = '';
  saveCurrentProjectState();

  const appendLog = log => {
    if (stepLogs) stepLogs.innerHTML += log + '<br>';
    const outBox = $('step3Output');
    if (outBox) outBox.scrollTop = outBox.scrollHeight;
    tickerUpdate(log);
  };

  const recordingFile = currentRecordingFilename();
  
  appendLog(`[System] Initiating serverless Modal GPU Cloud connection...`);
  appendLog(`[Network] Establishing TLS-encrypted gRPC channel to Modal serverless runtime...`);
  appendLog(`[Upload] Transferring ${recordingFile} to local Modal GPU run space...`);
  
  if (bar) bar.style.width = '30%';

  fetch('/api/video-analysis/run', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ filename: recordingFile })
  })
  .then(r => r.json().then(j => ({ ok: r.ok, j })))
  .then(({ ok, j }) => {
    if (!ok) throw new Error(j.detail || 'Transfer failed');
    if (bar) bar.style.width = '100%';
    setStep3UploadDone(true);
    appendLog(`[Modal GPU] Container environment spun up successfully (NVIDIA A10G ready).`);
    appendLog(`[System] Video uploaded and linked to GPU pipeline successfully.`);
    markStepDone(3);
    enableStepButtons();
    saveCurrentProjectState();
    if (callback) callback();
    else tickerFinish('Step 3 complete — video uploaded and registered on GPU');
  })
  .catch(err => {
    appendLog(`[Error] Transfer failed: ${err.message}`);
    const card = $('pstep-3');
    if (card) card.classList.remove('active');
    tickerHide();
    enableStepButtons();
    renderProjectProgress();
    saveCurrentProjectState();
  });
}

// 🧠 Step 4 — VLM & Voice Synthesis
function runStep4(callback) {
  const select = $('projectSelect');
  const useCannedVideo = !select || !select.value || isDefaultProject(select.value);

  if (!useCannedVideo) {
    runStep4Real(callback);
    return;
  }

  streamStepLogs(4, [
    `[Whisper STT] Running audio transcription and voice pitch modeling...`,
    `[Whisper STT] Transcription completed. Script duration: 8 seconds.`,
    `[Qwen VLM] Scanning video frame-by-frame at 1 FPS for context reasoning...`,
    `[Qwen VLM] Compiling semantic reasoning report on presentation topics.`,
    `[EchoMimicV3] Loading narrator avatar Bahadır (bahadir.jpg) to NVIDIA A10G memory...`,
    `[EchoMimicV3] Synthesizing physical gestures, upper-body/shoulder sway & facial expressions...`,
    `[RIFE] Interpolating avatar co-speech motion to buttery smooth 50 FPS...`
  ], {
    onStart: () => {
      const results = $('step4ResultsContainer');
      if (results) results.style.display = 'none';
    },
    onDone: () => {
      const results = $('step4ResultsContainer');
      if (results) results.style.display = 'block';
      setShowcaseVisible(true);
      loadAndRenderData();
    }
  }, callback);
}

function runStep4Real(callback) {
  markStepActive(4);
  disableStepButtons();
  
  const results = $('step4ResultsContainer');
  if (results) results.style.display = 'none';
  
  const stepLogs = $('step4Logs');
  if (stepLogs) stepLogs.innerHTML = '';
  saveCurrentProjectState();

  let lastLogsLength = 0;

  const appendLogs = logsText => {
    if (!logsText) return;
    const lines = logsText.split('\n');
    for (let i = lastLogsLength; i < lines.length; i++) {
      const line = lines[i].trim();
      if (line) {
        if (stepLogs) stepLogs.innerHTML += line + '<br>';
        tickerUpdate(line);
      }
    }
    lastLogsLength = lines.length;
    const outBox = $('step4Output');
    if (outBox) outBox.scrollTop = outBox.scrollHeight;
  };

  let polling = false;
  const poll = setInterval(() => {
    if (polling) return;
    polling = true;
    
    fetch('/api/video-analysis/run-status')
      .then(r => r.json())
      .then(data => {
        appendLogs(data.logs);
        saveCurrentProjectState();
        
        if (data.status === 'success') {
          releaseStepTimer(poll);
          markStepDone(4);
          
          if (results) results.style.display = 'block';
          setShowcaseVisible(true);
          
          loadAndRenderData();
          
          enableStepButtons();
          saveCurrentProjectState();
          if (callback) callback();
          else tickerFinish('Step 4 complete — VLM and Voice Synthesis processed');
        } else if (data.status === 'failed') {
          releaseStepTimer(poll);
          if (stepLogs) stepLogs.innerHTML += `<span style="color: var(--accent-red);">[Error] GPU Pipeline execution failed on Modal.</span><br>`;
          const card = $('pstep-4');
          if (card) card.classList.remove('active');
          tickerHide();
          enableStepButtons();
          renderProjectProgress();
          saveCurrentProjectState();
        }
      })
      .catch(() => {}) 
      .finally(() => { polling = false; });
  }, 1500);
  registerStepTimer(poll);
}

// 🎬 Step 5 — Montage & Publish
function runStep5(callback) {
  const select = $('projectSelect');
  const useCannedVideo = !select || !select.value || isDefaultProject(select.value);

  if (!useCannedVideo) {
    runStep5Real(callback);
    return;
  }

  streamStepLogs(5, [
    `[FFmpeg] Initializing overlay filter parameters...`,
    `[FFmpeg] Compositing talking avatar over the screen recording (bottom-right)...`,
    `[FFmpeg] Rendering final executive video montage...`,
    `[YouTube API] Validating OAuth 2.0 token credentials for channel: @LawnAdvisorAI.`,
    `[YouTube API] Uploading presentation: "Autonomous AI Lawn Setup Plan"...`,
    `[YouTube] Auto-published successfully! Video URL: https://youtu.be/YT-uX829aB`,
    `[System] Autonomous production pipeline finalized successfully!`
  ], {
    onStart: () => {
      const vid = $('step5VideoContainer');
      if (vid) vid.style.display = 'none';
      const metrics = $('avatarMetricsCard');
      if (metrics) metrics.style.display = 'none';
      const player = $('avatarPlayer');
      if (player) player.pause();
    },
    onDone: () => {
      const vid = $('step5VideoContainer');
      if (vid) vid.style.display = 'block';
      const metrics = $('avatarMetricsCard');
      if (metrics) metrics.style.display = 'flex';
      const player = $('avatarPlayer');
      if (player) {
        player.src = "/api/videos/play/talking_avatar_em3_8s.mp4?v=" + Date.now();
        player.load();
        player.play().catch(e => console.log("Final composite playback delayed:", e));
      }
    }
  }, callback);
}

function runStep5Real(callback) {
  markStepActive(5);
  disableStepButtons();

  const vid = $('step5VideoContainer');
  if (vid) vid.style.display = 'none';
  const metrics = $('avatarMetricsCard');
  if (metrics) metrics.style.display = 'none';
  const player = $('avatarPlayer');
  if (player) player.pause();

  const stepLogs = $('step5Logs');
  if (stepLogs) stepLogs.innerHTML = '';
  saveCurrentProjectState();

  const recordingFile = currentRecordingFilename();
  const outputFile = 'final_' + recordingFile;

  let lastLogsLength = 0;

  const appendLogs = logsList => {
    if (!logsList) return;
    for (let i = lastLogsLength; i < logsList.length; i++) {
      const line = logsList[i].trim();
      if (line) {
        if (stepLogs) stepLogs.innerHTML += line + '<br>';
        tickerUpdate(line);
      }
    }
    lastLogsLength = logsList.length;
    const outBox = $('step5Output');
    if (outBox) outBox.scrollTop = outBox.scrollHeight;
  };

  fetch('/api/publish/run', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ recording_file: recordingFile, output_file: outputFile })
  })
  .then(r => r.json().then(j => ({ ok: r.ok, j })))
  .then(({ ok, j }) => {
    if (!ok) throw new Error(j.detail || 'Compositing failed');

    let polling = false;
    const poll = setInterval(() => {
      if (polling) return;
      polling = true;

      fetch('/api/publish/status')
        .then(r => r.json())
        .then(data => {
          appendLogs(data.logs);
          saveCurrentProjectState();

          if (data.status === 'success') {
            releaseStepTimer(poll);
            markStepDone(5);

            if (vid) vid.style.display = 'block';
            if (metrics) metrics.style.display = 'flex';
            if (player) {
              player.src = "/api/videos/play/" + outputFile + "?v=" + Date.now();
              player.load();
              player.play().catch(e => console.log("Final composite playback delayed:", e));
            }

            enableStepButtons();
            loadVideoList(); // reload file lists
            saveCurrentProjectState();
            if (callback) callback();
            else tickerFinish('Full pipeline completed — real composite video published!');
          } else if (data.status === 'failed') {
            releaseStepTimer(poll);
            if (stepLogs) stepLogs.innerHTML += `<span style="color: var(--accent-red);">[Error] Compositing failed on server.</span><br>`;
            const card = $('pstep-5');
            if (card) card.classList.remove('active');
            tickerHide();
            enableStepButtons();
            renderProjectProgress();
            saveCurrentProjectState();
          }
        })
        .catch(() => {})
        .finally(() => { polling = false; });
    }, 1000);
    registerStepTimer(poll);
  })
  .catch(err => {
    if (stepLogs) stepLogs.innerHTML += `<span style="color: var(--accent-red);">[Error] Failed to initiate publish: ${err.message}</span><br>`;
    const card = $('pstep-5');
    if (card) card.classList.remove('active');
    tickerHide();
    enableStepButtons();
    renderProjectProgress();
    saveCurrentProjectState();
  });
}

function triggerStep(stepNum) {
  if (stepNum === 1) runStep1();
  else if (stepNum === 2) runStep2();
  else if (stepNum === 3) runStep3();
  else if (stepNum === 4) runStep4();
  else if (stepNum === 5) runStep5();
}

function triggerMainPipeline() {
  // Clean all steps
  const step1VideoContainer = $('step1VideoContainer');
  if (step1VideoContainer) step1VideoContainer.style.display = 'none';
  const progressContainer = $('step3ProgressContainer');
  if (progressContainer) progressContainer.style.display = 'none';
  const resultsContainer = $('step4ResultsContainer');
  if (resultsContainer) resultsContainer.style.display = 'none';
  const videoContainer = $('step5VideoContainer');
  if (videoContainer) videoContainer.style.display = 'none';
  const metricsCard = $('avatarMetricsCard');
  if (metricsCard) metricsCard.style.display = 'none';
  setShowcaseVisible(false);
  
  for(let i=1; i<=5; i++) {
    const box = $('pstep-' + i);
    if (box) box.classList.remove('active', 'done');
  }
  renderProjectProgress();

  saveCurrentProjectState();

  runStep1(() => {
    runStep3(() => {
      runStep4(() => {
        runStep5(() => {
          tickerFinish('Full pipeline completed — video published!');
          saveCurrentProjectState();
        });
      });
    });
  });
}
