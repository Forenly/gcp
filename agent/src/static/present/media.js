// Forenly AVIP — media & reports: video library, showcase tabs, avatar player
// ============================================================================
// 📊 Endpoints & UI Rendering Integration
// ============================================================================

// Filenames that really exist on the server — lets the UI decide which project
// artifacts are playable vs simulated. Refreshed on every loadVideoList().
let serverVideoFiles = new Set();

function loadVideoList() {
  const container = $('videoListContainer');
  if (!container) return;

  container.innerHTML = '<div style="text-align: center; color: var(--text-muted); padding: 20px; font-size: 13px;">Loading videos...</div>';

  fetch('/api/videos')
    .then(r => r.json())
    .then(videos => {
      serverVideoFiles = new Set((videos || []).map(v => v.filename));
      renderProjectOutcomes();  // playability of step outcomes may have changed

      const systemDefaults = [
        'talking_avatar.mp4', 
        'talking_avatar_em3.mp4', 
        'talking_avatar_em3_8s.mp4', 
        'talking_avatar_hallo512.mp4', 
        'talking_avatar_hallo512_5s.mp4', 
        'talking_avatar_hallo512_8s.mp4', 
        'talking_avatar_opencv_backup.mp4', 
        'talking_avatar_opencv_backup_5s.mp4', 
        'talking_avatar_opencv_backup_8s.mp4', 
        'forenly_mower_marketing.mp4', 
        'downloaded_video.mp4'
      ];
      videos = (videos || []).filter(v => !systemDefaults.includes(v.filename));

      // Project-scoped library: the canned demo assets belong to the default
      // projects; a custom project only lists files prefixed with its own slug
      // (e.g. asd_*), so real outputs of its runs appear here automatically.
      // Default projects in turn hide files owned by custom projects.
      const select = $('projectSelect');
      if (select && select.value) {
        if (isDefaultProject(select.value)) {
          const customSlugs = getProjects().filter(p => !isDefaultProject(p.id)).map(p => projectSlug(p.name) + '_');
          videos = videos.filter(v => !customSlugs.some(s => v.filename.startsWith(s)));
        } else {
          const slug = currentRecordingFilename().replace('_recording.mp4', '');
          videos = videos.filter(v => v.filename.startsWith(slug + '_'));
        }
      }

      // No real files for this project → hide the whole card instead of showing
      // an empty shell (the in-card step outcomes already tell the story).
      const card = $('videoManagerView');
      if (!videos || videos.length === 0) {
        if (card) card.style.display = 'none';
        container.innerHTML = '';
        return;
      }
      if (card) card.style.display = 'flex';

      container.innerHTML = videos.map(video => {
        const isVeo = video.filename.startsWith('veo_');
        const iconClass = isVeo ? 'veo' : '';
        const icon = isVeo ? '✨' : '🤖';
        
        const dateStr = new Date(video.created_at * 1000).toLocaleString('en-US', {
          day: '2-digit',
          month: '2-digit',
          year: 'numeric',
          hour: '2-digit',
          minute: '2-digit'
        });
        
        let displayTitle = video.filename;
        if (video.filename === 'talking_avatar.mp4') {
          displayTitle = 'Default Narrator Avatar';
        } else if (video.filename === 'forenly_mower_marketing.mp4') {
          displayTitle = 'Forenly Promo Video';
        } else if (video.filename === 'downloaded_video.mp4') {
          displayTitle = 'Original Screen Recording';
        } else if (video.filename === 'forenly_ai_recording.mp4') {
          displayTitle = 'Forenly AI Screen Recording (Playwright)';
        } else if (video.filename.startsWith('render_')) {
          displayTitle = 'Remotion: ' + video.filename.replace('render_', '').replace('.mp4', '');
        } else if (video.filename.startsWith('veo_')) {
          displayTitle = 'Veo Synthesis: ' + video.filename.replace('veo_', '').replace('.mp4', '');
        }
        
        return `
          <div class="video-row-item">
            <div class="video-row-left">
              <div class="video-row-icon ${iconClass}">${icon}</div>
              <div class="video-row-info">
                <div class="video-row-title" title="${video.filename}">${displayTitle}</div>
                <div class="video-row-meta">
                  <span style="color: var(--accent-green); font-weight: bold; font-size: 10px; background: rgba(137,178,70,0.1); padding: 1px 6px; border-radius: 4px;">${video.type}</span>
                  <span>${video.size_mb} MB</span>
                  <span>•</span>
                  <span>${dateStr}</span>
                </div>
              </div>
            </div>
            <div class="video-row-actions">
              <button class="video-row-btn video-row-btn-play" onclick="openVideoModal('${video.filename}')">▶ Play</button>
              <button class="video-row-btn video-row-btn-delete" onclick="deleteSelectedVideo('${video.filename}')">Delete</button>
            </div>
          </div>
        `;
      }).join('');
    })
    .catch(err => {
      const card = $('videoManagerView');
      if (card) card.style.display = 'flex';
      container.innerHTML = `<div style="text-align: center; color: #f85149; padding: 20px;">Error: ${err.message}</div>`;
    });
}

// ---------------------------------------------------------------------------
// Outcome modal: Play/View on any output opens it in a lightbox.
// ---------------------------------------------------------------------------
function openVideoModal(filename, title) {
  const body = $('outcomeModalBody');
  const heading = $('outcomeModalTitle');
  const modal = $('outcomeModal');
  if (!body || !modal) return;
  if (heading) heading.textContent = title || ('🎬 ' + filename);
  body.innerHTML = `<video src="/api/videos/play/${encodeURIComponent(filename)}?v=${Date.now()}" controls autoplay playsinline style="display: block;"></video>`;
  modal.classList.add('open');
}

function openReportModal() {
  const body = $('outcomeModalBody');
  const heading = $('outcomeModalTitle');
  const modal = $('outcomeModal');
  const view = $('showcaseView');
  if (!body || !modal || !view) return;
  if (heading) heading.textContent = '📋 Detailed Semantic Reports & Transcription';
  body.innerHTML = '';
  body.appendChild(view);          // move the live card in (listeners intact)
  view.style.display = 'block';
  loadAndRenderData();
  modal.classList.add('open');
}

function closeOutcomeModal() {
  const modal = $('outcomeModal');
  const body = $('outcomeModalBody');
  if (!modal || !body) return;
  modal.classList.remove('open');
  const vid = body.querySelector('video');
  if (vid) vid.pause();
  const view = body.querySelector('#showcaseView');
  if (view) {
    const home = $('showcaseHome');
    if (home) home.appendChild(view);  // return the report card to its page slot
  }
  if (!view) body.innerHTML = '';
}

document.addEventListener('keydown', e => {
  if (e.key === 'Escape') closeOutcomeModal();
});

function deleteSelectedVideo(filename) {
  if (!confirm(`Are you sure you want to permanently delete the video "${filename}"?`)) {
    return;
  }
  
  fetch(`/api/videos/${encodeURIComponent(filename)}`, { method: 'DELETE' })
    .then(r => {
      if (!r.ok) return r.json().then(d => { throw new Error(d.detail || 'Could not be deleted'); });
      return r.json();
    })
    .then(data => {
      loadVideoList();
      // If the deleted file is open in the modal, close it.
      const modalVid = document.querySelector('#outcomeModalBody video');
      if (modalVid && modalVid.src.includes(encodeURIComponent(filename))) {
        closeOutcomeModal();
      }
    })
    .catch(err => {
      alert('Error: ' + err.message);
    });
}

function switchTab(index) {
  currentTab = index;
  const btns = document.querySelectorAll('.tab-btn');
  const contents = document.querySelectorAll('.tab-content');

  btns.forEach((btn, i) => {
    btn.classList.toggle('active', i === index);
  });
  contents.forEach((content, i) => {
    content.classList.toggle('active', i === index);
  });
}

function setShowcaseVisible(visible) {
  const view = $('showcaseView');
  const placeholder = $('waitingPlaceholder');
  if (view && placeholder) {
    if (visible) {
      view.style.display = 'block';
      placeholder.style.display = 'none';
    } else {
      view.style.display = 'none';
      placeholder.style.display = 'flex';
    }
  }
}

function loadAndRenderData(filename) {
  if (!filename) {
    const select = $('projectSelect');
    if (select && select.value) {
      const projectId = select.value;
      if (projectId === 'forenly-ai') {
        filename = 'forenly_ai_recording.mp4';
      } else if (typeof currentRecordingFilename === 'function') {
        // Real-pipeline project: ask for this recording's own (waypoint-driven) analysis.
        filename = currentRecordingFilename();
      }
    }
  }
  const url = filename ? `/api/video-analysis?filename=${encodeURIComponent(filename)}` : '/api/video-analysis';
  fetch(url)
    .then(r => {
      if(!r.ok) throw new Error('Failed to load report data.');
      return r.json();
    })
    .then(data => {
      // 1. Whisper transcription segments
      const whisperContainer = $('whisperContainer');
      if (data.segments && Array.isArray(data.segments)) {
        whisperContainer.innerHTML = data.segments.map(seg => {
          const startMin = Math.floor(seg.start / 60).toString().padStart(2, '0');
          const startSec = Math.floor(seg.start % 60).toString().padStart(2, '0');
          const endMin = Math.floor(seg.end / 60).toString().padStart(2, '0');
          const endSec = Math.floor(seg.end % 60).toString().padStart(2, '0');
          return `
            <div class="transcript-segment" data-start="${seg.start}" data-end="${seg.end}" onclick="seekTo(${seg.start})">
              <div class="transcript-time">[${startMin}:${startSec} - ${endMin}:${endSec}]</div>
              <div class="transcript-text">${esc(seg.text)}</div>
            </div>
          `;
        }).join('');
      } else {
        whisperContainer.innerHTML = `<div class="transcript-text">${esc(data.subtitles || 'No transcription data found.')}</div>`;
      }

      // 2. Qwen visual reasoning
      const qwenContainer = $('qwenContainer');
      const md = data.semantic_analysis || 'Qwen visual analysis data not found.';
      qwenContainer.innerHTML = parseMarkdownSimple(md);

      // 3. Player wave sync
      const player = $('avatarPlayer');
      const wave = $('voiceWave');

      if (player && wave) {
        player.onplay = () => wave.classList.add('playing');
        player.onpause = () => wave.classList.remove('playing');
        player.onended = () => wave.classList.remove('playing');

        player.ontimeupdate = () => {
          const time = player.currentTime;
          const segments = document.querySelectorAll('.transcript-segment');
          segments.forEach(seg => {
            const start = parseFloat(seg.getAttribute('data-start'));
            const end = parseFloat(seg.getAttribute('data-end'));
            if (time >= start && time <= end) {
              seg.classList.add('highlight');
            } else {
              seg.classList.remove('highlight');
            }
          });
        };
      }

      if ($('waitingPlaceholder')) $('waitingPlaceholder').style.display = 'none';
      setShowcaseVisible(true);
      loadVideoList();
    })
    .catch(err => {
      console.log('Error loading reports:', err);
    });
}

function seekTo(seconds) {
  const player = $('avatarPlayer');
  if (player) {
    player.currentTime = seconds;
    player.play();
  }
}

function selectAvatarModel(model) {
  const player = $('avatarPlayer');
  const badge = $('avatarBadge');
  const desc = $('avatarDesc');
  const btnEm3 = $('modelBtnEm3');
  
  const mHardware = $('metricHardware');
  const mTime = $('metricTime');
  const mCost = $('metricCost');
  const mReview = $('metricReview');
  
  if (!player) return;

  if (btnEm3) {
    btnEm3.classList.add('active');
    btnEm3.style.background = 'var(--accent-green)';
    btnEm3.style.color = '#000';
  }

  const fineTuningContainer = $('lipsyncFineTuningContainer');
  if (fineTuningContainer) fineTuningContainer.style.display = 'flex';
  player.src = '/api/videos/play/talking_avatar_em3_8s.mp4?v=' + Date.now();
  if (badge) badge.textContent = 'EchoMimicV3 (Ultra-Premium) · HD + Sabit Stüdyo';
  if (desc) desc.textContent = 'SOTA EchoMimicV3 (50 FPS RIFE) motoru ile sentezlenen profesyonel executive stüdyo sunucusu.';
  if (mHardware) mHardware.textContent = '📟 NVIDIA A100-80G';
  if (mTime) mTime.textContent = '⚡ ~22.0s (Matting +~5s)';
  if (mCost) mCost.textContent = '🏷️ $0.029 (Matting +0.5¢)';
  
  setSyncOffsetStyle('normal');
  player.load();
  player.play().catch(e => console.log("Playback interrupted or blocked:", e));
}

function setSyncOffsetStyle(offset) {
  const btnNormal = $('syncBtnNormal');
  const btnEarly = $('syncBtnEarly');
  const btnLate = $('syncBtnLate');
  
  [btnNormal, btnEarly, btnLate].forEach(btn => {
    if (btn) {
      btn.style.background = 'transparent';
      btn.style.color = 'var(--text-muted)';
      btn.classList.remove('active');
    }
  });
  
  let activeBtn = btnNormal;
  if (offset === 'early') activeBtn = btnEarly;
  else if (offset === 'late') activeBtn = btnLate;
  
  if (activeBtn) {
    activeBtn.style.background = 'rgba(255,255,255,0.08)';
    activeBtn.style.color = 'var(--accent-green)';
    activeBtn.classList.add('active');
  }
}

function setSyncOffset(offset) {
  const player = $('avatarPlayer');
  if (!player) return;
  
  setSyncOffsetStyle(offset);
  
  let videoFile = 'talking_avatar_em3_8s.mp4';
  if (offset === 'early') {
    videoFile = 'talking_avatar_em3_8s_audio_early_80ms.mp4';
  } else if (offset === 'late') {
    videoFile = 'talking_avatar_em3_8s_audio_late_80ms.mp4';
  }
  
  player.src = '/api/videos/play/' + videoFile + '?v=' + Date.now();
  player.load();
  player.play().catch(e => console.log("Playback interrupted:", e));
}

