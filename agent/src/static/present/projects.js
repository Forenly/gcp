// Forenly AVIP — project console: CRUD + per-project state isolation (localStorage)
// ============================================================================
// 📁 Project Management & State Isolation Logic
// ============================================================================

const defaultProjects = [
  { id: "lawn-advisor", name: "Lawn Advisor Presentation", url: "https://lawn.forenly.ai/presentation" },
  { id: "forenly-ai", name: "Forenly AI Platform", url: "https://forenly.ai" }
];

// Only forenly-ai is the canned instant demo (its real recording ships with the
// repo). lawn-advisor runs the REAL pipeline so its video always matches its URL.
function isDefaultProject(projectId) {
  return projectId === 'forenly-ai';
}

function projectSlug(name) {
  return String(name || '').toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '') || 'project';
}

function getProjects() {
  try {
    return JSON.parse(localStorage.getItem('avip_projects') || '[]');
  } catch (e) {
    return [];
  }
}

// Default projects ship with a real canned recording of their target page; custom
// projects get a project-slug filename and an archived-file note instead, so the
// shown artifact never claims to be a page it isn't.
function currentRecordingFilename() {
  const select = $('projectSelect');
  if (!select || !select.value || isDefaultProject(select.value)) return 'forenly_ai_recording.mp4';
  const proj = getProjects().find(p => p.id === select.value);
  return projectSlug(proj && proj.name) + '_recording.mp4';
}

// Tracks the project whose state currently occupies the DOM. select.value already
// points at the NEW project inside onchange, so saves during a switch need this.
let currentProjectId = null;
// Live setInterval handles of any running step simulation. Cleared on project
// switch so one project's run never bleeds logs into another project's state.
let activeStepTimers = [];

function registerStepTimer(timer) {
  activeStepTimers.push(timer);
}

function releaseStepTimer(timer) {
  clearInterval(timer);
  activeStepTimers = activeStepTimers.filter(t => t !== timer);
}

function cancelActiveRun() {
  if (activeStepTimers.length === 0) return;
  activeStepTimers.forEach(clearInterval);
  activeStepTimers = [];
  tickerHide();

  for (let i = 1; i <= 5; i++) {
    const card = $('pstep-' + i);
    if (card) card.classList.remove('active');
    const btn = $('runStep' + i);
    if (btn) btn.innerHTML = '▶ Run';
  }
  enableStepButtons();
}

function applyProjectState(state) {
  if (!state) return;
  state.logs = state.logs || {};

  // Set step logs and step container card classes
  for (let i = 1; i <= 5; i++) {
    const logsEl = $('step' + i + 'Logs');
    if (logsEl) {
      logsEl.innerHTML = state.logs['step' + i] || '';
    }
    
    const card = $('pstep-' + i);
    if (card) {
      card.classList.remove('active', 'done');
      if (state.stepActive && state.stepActive[i - 1]) {
        card.classList.add('active');
      } else if (state.stepsDone && state.stepsDone[i - 1]) {
        card.classList.add('done');
      }
    }
  }
  
  // Set container visibilities with strict defensive defaults and programmatic state validation
  const select = $('projectSelect');
  const isDefault = !select || !select.value || isDefaultProject(select.value);
  
  // Show the captured video container once Step 1 (Capture) is done, for both default and custom projects!
  const isStep1Done = state.stepsDone && state.stepsDone[0];
  const s1Vid = $('step1VideoContainer');
  if (s1Vid) {
    const showS1Vid = isStep1Done;
    s1Vid.style.display = showS1Vid ? ((state.visibility && state.visibility.step1VideoContainer) || 'block') : 'none';
    if (showS1Vid) {
      const s1Player = $('step1VideoPlayer');
      if (s1Player) {
        const expectedSrc = isDefault ? '/api/videos/play/forenly_ai_recording.mp4' : ('/api/videos/play/' + currentRecordingFilename());
        if (s1Player.src.indexOf(expectedSrc) === -1) {
          s1Player.src = expectedSrc;
        }
      }
    }
  }
  
  const isStep3ActiveOrDone = (state.stepActive && state.stepActive[2]) || (state.stepsDone && state.stepsDone[2]);
  const s3Prog = $('step3ProgressContainer');
  if (s3Prog) {
    s3Prog.style.display = isStep3ActiveOrDone ? ((state.visibility && state.visibility.step3ProgressContainer) || 'block') : 'none';
  }
  const s3Bar = $('step3ProgressBar');
  if (s3Bar) {
    s3Bar.style.width = (state.visibility && state.visibility.step3ProgressBarWidth) || '0%';
  }
  setStep3UploadDone(!!(state.stepsDone && state.stepsDone[2]));
  
  const isStep4Done = state.stepsDone && state.stepsDone[3];
  const s4Res = $('step4ResultsContainer');
  if (s4Res) {
    s4Res.style.display = isStep4Done ? ((state.visibility && state.visibility.step4ResultsContainer) || 'block') : 'none';
  }
  
  const isStep5Done = state.stepsDone && state.stepsDone[4];
  const s5Vid = $('step5VideoContainer');
  if (s5Vid) {
    s5Vid.style.display = isStep5Done ? ((state.visibility && state.visibility.step5VideoContainer) || 'block') : 'none';
  }
  const s5Met = $('avatarMetricsCard');
  if (s5Met) {
    s5Met.style.display = isStep5Done ? ((state.visibility && state.visibility.avatarMetricsCard) || 'flex') : 'none';
  }
  
  // Showcase view (tab section) visibility
  const isStep4Or5Done = state.stepsDone && (state.stepsDone[3] || state.stepsDone[4]);
  const hasShowcase = isStep4Or5Done && (state.visibility && state.visibility.showcaseView === 'block');
  setShowcaseVisible(hasShowcase);
  if (hasShowcase) {
    loadAndRenderData();
  }
  
  // Sync step buttons state
  enableStepButtons();
  renderProjectProgress();
}

function getCurrentProjectState() {
  const select = $('projectSelect');
  if (!select || !select.value) return null;
  
  const stepActive = [];
  const stepsDone = [];
  for (let i = 1; i <= 5; i++) {
    const card = $('pstep-' + i);
    stepActive.push(card ? card.classList.contains('active') : false);
    stepsDone.push(card ? card.classList.contains('done') : false);
  }
  
  const s1Vid = $('step1VideoContainer');
  const s3Prog = $('step3ProgressContainer');
  const s3Bar = $('step3ProgressBar');
  const s4Res = $('step4ResultsContainer');
  const s5Vid = $('step5VideoContainer');
  const s5Met = $('avatarMetricsCard');
  const view = $('showcaseView');
  
  return {
    logs: {
      step1: $('step1Logs') ? $('step1Logs').innerHTML : '',
      step2: $('step2Logs') ? $('step2Logs').innerHTML : '',
      step3: $('step3Logs') ? $('step3Logs').innerHTML : '',
      step4: $('step4Logs') ? $('step4Logs').innerHTML : '',
      step5: $('step5Logs') ? $('step5Logs').innerHTML : ''
    },
    stepsDone,
    stepActive,
    visibility: {
      step1VideoContainer: s1Vid ? s1Vid.style.display : 'none',
      step3ProgressContainer: s3Prog ? s3Prog.style.display : 'none',
      step3ProgressBarWidth: s3Bar ? s3Bar.style.width : '0%',
      step4ResultsContainer: s4Res ? s4Res.style.display : 'none',
      step5VideoContainer: s5Vid ? s5Vid.style.display : 'none',
      avatarMetricsCard: s5Met ? s5Met.style.display : 'none',
      showcaseView: view ? view.style.display : 'none'
    }
  };
}

function saveCurrentProjectState() {
  try {
    const select = $('projectSelect');
    if (!select || !select.value) return;
    const projectId = select.value;
    const state = getCurrentProjectState();
    if (state) {
      localStorage.setItem('avip_project_state_' + projectId, JSON.stringify(state));
    }
  } catch (err) {
    console.error("Error saving current project state:", err);
  }
}

function loadProjectState(projectId) {
  try {
    let saved = localStorage.getItem('avip_project_state_' + projectId);
    if (saved) {
      try {
        const state = JSON.parse(saved);
        
        // --- 5-Step Pipeline Migration Check ---
        // If the loaded state has only 4 steps or its step2 contains "Awaiting upload...",
        // migrate it to the correct 5-step schema to clear stale cache.
        // Also purge lawn-advisor states from the era when it replayed the canned
        // forenly.ai recording — its video claimed to be a page it wasn't.
        const staleLawnCanned = projectId === 'lawn-advisor' && state.logs && state.logs.step1 &&
          state.logs.step1.includes('raw_forenly_ai_recording.mp4');
        if (!state.logs.step5 || (state.logs.step2 && state.logs.step2.includes("Awaiting upload")) || (state.stepsDone && state.stepsDone.length === 4) || staleLawnCanned) {
          console.log("Migrating project state for:", projectId);
          localStorage.removeItem('avip_project_state_' + projectId);
          saved = null;
        } else {
          applyProjectState(state);
          return;
        }
      } catch (e) {
        console.error("Corrupted state for project:", projectId, e);
      }
    }
    
    // No saved state. Let's initialize default!
    let projects = [];
    try {
      projects = JSON.parse(localStorage.getItem('avip_projects') || '[]');
    } catch (e) {}
    const proj = projects.find(p => p.id === projectId);
    const url = proj ? proj.url : 'https://lawn.forenly.ai/presentation';
    
    let initialState;
    // The canned demo project starts pre-loaded/cached; everything else starts clean.
    if (projectId === 'forenly-ai') {
      initialState = {
        logs: {
          step1: `[Browser] Initializing Gemini Browser Use sandbox...<br>[Browser] Navigating to: ${url}<br>[Browser] Viewport set to 1280x800. Web page loaded successfully.<br>[Recording] Raw screen capture session active. Recording viewport...<br>[Recording] Screen capture session completed. Finalizing webm stream...<br>[System] Screen recorded successfully! File: raw_forenly_ai_recording.mp4`,
          step2: `[Agent] Analysis: Scanning DOM tree to locate headers, CTAs, and navigation controls...<br>[Agent] UI Mapping: Identified active section 1/6: 'Solutions' header, viewport center.<br>[Agent] UI Mapping: Identified active section 2/6: 'Setup Wizard' card.<br>[Agent] Cursor Control: Generating minimum-jerk Bezier curve trajectories for mouse motion.<br>[Agent] Exploring page section 1/6 (scroll to 699px)...<br>[Agent] Section 1/6: pointing at &lt;h2 class="solutions-header"&gt; (340, 680) and highlighting...<br>[Agent] Exploring page section 2/6 (scroll to 1399px)...<br>[Agent] Section 2/6: pointing at &lt;button id="setup-cta"&gt; (610, 520) and highlighting...<br>[Agent] Action: Emitting smooth deictic clicks with glowing click ripple overlay...<br>[FFmpeg] Compositing deictic cursor path and active overlay...<br>[FFmpeg] Transcoding WebM → MP4 (H.264, faststart)...<br>[System] Animated screen recording generated successfully! File: forenly_ai_recording.mp4`,
          step3: '[System] Connected to Modal GPU Cloud.<br>[Upload] Raw screen recording secured in storage bucket.',
          step4: '[System] VLM Reasoning & Voice Synthesis complete.',
          step5: '[System] Compositing overlay complete.<br>[YouTube] Auto-published to channel successfully.'
        },
        stepsDone: [true, true, true, true, true],
        stepActive: [false, false, false, false, false],
        visibility: {
          step1VideoContainer: 'block',
          step3ProgressContainer: 'block',
          step3ProgressBarWidth: '100%',
          step4ResultsContainer: 'block',
          step5VideoContainer: 'block',
          avatarMetricsCard: 'flex',
          showcaseView: 'block'
        }
      };
    } else {
      // New project starts ready/unrun
      initialState = {
        logs: {
          step1: 'Awaiting screen recording...',
          step2: 'Awaiting mouse movement synthesis...',
          step3: 'Awaiting upload...',
          step4: 'Awaiting synthesis...',
          step5: 'Awaiting render...'
        },
        stepsDone: [false, false, false, false, false],
        stepActive: [false, false, false, false, false],
        visibility: {
          step1VideoContainer: 'none',
          step3ProgressContainer: 'none',
          step3ProgressBarWidth: '0%',
          step4ResultsContainer: 'none',
          step5VideoContainer: 'none',
          avatarMetricsCard: 'none',
          showcaseView: 'none'
        }
      };
    }
    
    localStorage.setItem('avip_project_state_' + projectId, JSON.stringify(initialState));
    applyProjectState(initialState);
  } catch (err) {
    console.error("Error loading project state:", err);
  }
}

function initProjects() {
  try {
    let stored = localStorage.getItem('avip_projects');
    let projects;
    try {
      projects = stored ? JSON.parse(stored) : defaultProjects;
    } catch(e) {
      projects = defaultProjects;
    }
    if (!projects || !Array.isArray(projects) || projects.length === 0) {
      projects = defaultProjects;
    }
    localStorage.setItem('avip_projects', JSON.stringify(projects));
    
    const select = $('projectSelect');
    if (select) {
      select.innerHTML = projects.map(p => `<option value="${p.id}">${esc(p.name)}</option>`).join('');
      
      const lastSelected = localStorage.getItem('avip_selected_project_id') || projects[0].id;
      const exists = projects.some(p => p.id === lastSelected);
      const selectId = exists ? lastSelected : projects[0].id;
      select.value = selectId;
      
      onProjectChange();
    }
  } catch (err) {
    console.error("Failed to initialize projects:", err);
  }
}

// Default projects load their own, pre-cached outputs; custom ones load clean cards.
function onProjectChange() {
  try {
    const select = $('projectSelect');
    if (!select) return;

    // Leaving a project: stop any running simulation and persist what is on
    // screen under the OUTGOING project's id (select.value is already the new one).
    if (currentProjectId && currentProjectId !== select.value) {
      cancelActiveRun();
      if (typeof closeOutcomeModal === 'function') closeOutcomeModal();
      const outgoingState = getCurrentProjectState();
      if (outgoingState) {
        localStorage.setItem('avip_project_state_' + currentProjectId, JSON.stringify(outgoingState));
      }
    }

    let projects = [];
    try {
      projects = JSON.parse(localStorage.getItem('avip_projects') || '[]');
    } catch(e) {}
    const selected = projects.find(p => p.id === select.value);
    if (selected) {
      const input = $('targetPageUrl');
      if (input) input.value = selected.url;
      localStorage.setItem('avip_selected_project_id', selected.id);
      currentProjectId = selected.id;

      loadProjectState(selected.id);
      loadVideoList();
    }
  } catch (err) {
    console.error("Error changing project:", err);
  }
}

function onProjectUrlChange() {
  try {
    const select = $('projectSelect');
    const input = $('targetPageUrl');
    if (!select || !input) return;
    let projects = [];
    try {
      projects = JSON.parse(localStorage.getItem('avip_projects') || '[]');
    } catch(e) {}
    const selected = projects.find(p => p.id === select.value);
    if (selected) {
      selected.url = input.value;
      localStorage.setItem('avip_projects', JSON.stringify(projects));
      
      // Update the URL in the step 1 log dynamically if state exists
      const saved = localStorage.getItem('avip_project_state_' + selected.id);
      if (saved) {
        try {
          const state = JSON.parse(saved);
          if (state.logs && state.logs.step1 && state.logs.step1.includes("Navigating to:")) {
            // Update line in log with new URL
            state.logs.step1 = state.logs.step1.replace(/\[Browser\] Navigating to: [^\s<]+/g, `[Browser] Navigating to: ${selected.url}`);
            localStorage.setItem('avip_project_state_' + selected.id, JSON.stringify(state));
            applyProjectState(state);
          }
        } catch(e) {}
      }
      
      saveCurrentProjectState();
    }
  } catch (err) {
    console.error("Error updating project URL:", err);
  }
}

function createProject() {
  const name = prompt("Enter new project name:");
  if (!name || !name.trim()) return;
  const url = prompt("Enter target web page URL for narration:", "https://");
  if (!url || !url.trim()) return;
  
  const projects = JSON.parse(localStorage.getItem('avip_projects') || '[]');
  const id = 'proj_' + Date.now();
  projects.push({ id, name: name.trim(), url: url.trim() });
  localStorage.setItem('avip_projects', JSON.stringify(projects));
  localStorage.setItem('avip_selected_project_id', id);
  
  const initialState = {
    logs: {
      step1: 'Awaiting screen recording...',
      step2: 'Awaiting mouse movement synthesis...',
      step3: 'Awaiting upload...',
      step4: 'Awaiting synthesis...',
      step5: 'Awaiting render...'
    },
    stepsDone: [false, false, false, false, false],
    stepActive: [false, false, false, false, false],
    visibility: {
      step1VideoContainer: 'none',
      step3ProgressContainer: 'none',
      step3ProgressBarWidth: '0%',
      step4ResultsContainer: 'none',
      step5VideoContainer: 'none',
      avatarMetricsCard: 'none',
      showcaseView: 'none'
    }
  };
  localStorage.setItem('avip_project_state_' + id, JSON.stringify(initialState));
  
  initProjects();
}

function editProject() {
  const select = $('projectSelect');
  if (!select || !select.value) return;
  const projects = JSON.parse(localStorage.getItem('avip_projects') || '[]');
  const selected = projects.find(p => p.id === select.value);
  if (!selected) return;
  
  const newName = prompt("Rename project:", selected.name);
  if (!newName || !newName.trim()) return;
  
  selected.name = newName.trim();
  localStorage.setItem('avip_projects', JSON.stringify(projects));

  initProjects();
  saveCurrentProjectState();
}

function deleteProject() {
  const select = $('projectSelect');
  if (!select || !select.value) return;
  const projects = JSON.parse(localStorage.getItem('avip_projects') || '[]');
  if (projects.length <= 1) {
    alert("Cannot delete the only project. Please keep at least one project.");
    return;
  }
  const selected = projects.find(p => p.id === select.value);
  if (!selected) return;
  
  if (!confirm(`Are you sure you want to delete project "${selected.name}"?`)) return;
  
  const filtered = projects.filter(p => p.id !== select.value);
  localStorage.setItem('avip_projects', JSON.stringify(filtered));
  localStorage.removeItem('avip_project_state_' + select.value);
  localStorage.setItem('avip_selected_project_id', filtered[0].id);

  // The on-screen state belongs to the deleted project — without this,
  // onProjectChange would persist it again under the removed id.
  cancelActiveRun();
  currentProjectId = null;

  initProjects();
}
