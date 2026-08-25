const $ = selector => document.querySelector(selector);
const canvas = $('#pitch');
const ctx = canvas.getContext('2d');
const fileInput = $('#file');
const range = $('#range');
const playButton = $('#play');
const canvasPlay = $('#canvasPlay');
const speed = $('#speed');
const replayList = $('#replayList');

const PUBLIC_BASE_URL = 'https://afc.ivanlukov.com';
const REPLAY_CATALOG = [
  {
    label: 'Nova Vertical vs KD Verticalis',
    path: '/var/matches/matches/20260825T145557Z-68034493aaca-nova-vertical-vs-kd-verticalis.ndjson'
  },
  {
    label: 'Nova Vertical vs Vertical Wingbacks',
    path: '/var/matches/matches/20260825T145557Z-e30cd57afd23-nova-vertical-vs-vertical-wingbacks.ndjson'
  },
  {
    label: 'KD Verticalis vs Vertical Wingbacks',
    path: '/var/matches/matches/20260825T145557Z-46f6e7cce201-kd-verticalis-vs-vertical-wingbacks.ndjson'
  }
].map(replay => ({
  ...replay,
  logUrl: `${PUBLIC_BASE_URL}${replay.path}`,
  viewerUrl: `${PUBLIC_BASE_URL}/viewer/?log=${encodeURIComponent(`${PUBLIC_BASE_URL}${replay.path}`)}`
}));

let rows = [];
let simulationFrames = [];
let physicsHz = 0;
let match = null;
let teamNames = new Map();
let duration = 0;
let startTime = 0;
let playhead = 0;
let playing = false;
let animationFrame = null;
let previousFrameTime = null;
let renderedDecision = -1;
let renderedEventFrame = -1;
let activeReplayUrl = '';

const clamp = (value, min, max) => Math.max(min, Math.min(max, value));
const escapeHtml = value => String(value ?? '').replace(/[&<>'"]/g, character => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'
})[character]);

function cleanTeamName(team) {
  if (!team) return 'Unknown team';
  return `${team.teamId || 'nova'} · ${team.teamVersion || 'v1'}`;
}

function compactReplayName(path) {
  return path.split('/').pop()
    .replace(/^\d{8}T\d{6}Z-[0-9a-f]+-/, '')
    .replace(/-seed\d+(?:-[^.]+)?\.ndjson$/, '')
    .replace(/\.ndjson$/, '')
    .replace(/-home-vs-/g, '  vs  ')
    .replace(/-away/g, '')
    .replace(/-/g, ' ')
    .replace(/\bc(\d{3})\b/g, (_, number) => `C${number}`)
    .replace(/\b\w/g, letter => letter.toUpperCase());
}

function renderCatalog() {
  replayList.innerHTML = `<section class="replay-group">
    <h2>Internal tournament</h2>
    ${REPLAY_CATALOG.map(replay => `<a class="replay-item ${activeReplayUrl === replay.logUrl ? 'active' : ''}" href="${escapeHtml(replay.viewerUrl)}">
      <span>${escapeHtml(replay.label)}</span><span class="watch">Watch</span>
    </a>`).join('')}
  </section>`;
}

fileInput.addEventListener('change', async () => {
  const selected = fileInput.files[0];
  if (!selected) return;
  stopPlayback();
  const customTitle = selected.name.replace(/\.(ndjson|jsonl)$/i, '').replace(/-/g, ' ');
  setMatchContext(customTitle, 'Local replay', 'Loading from your device…');
  setLoading(true);
  try {
    const records = parseNdjson(await selected.text());
    const recordingHeader = records.find(record => record.type === 'simulation_recording_started');
    if (recordingHeader) {
      match = recordingHeader.match || null;
      rows = [];
      activeReplayUrl = '';
      applySimulationRecording(records, true);
      const home = teamNames.get(0) || 'Home';
      const away = teamNames.get(1) || 'Away';
      setMatchContext(`${home} vs ${away}`, 'Local 60 Hz recording', 'Exact engine recording loaded directly from your device.');
      renderCatalog();
      return;
    }

    setMatchContext(customTitle, 'Local decision log', 'Loaded from your device.');
    loadReplayRecords(records, '');
    playButton.disabled = true;
    canvasPlay.disabled = true;
    range.disabled = true;
    $('#playbackState').textContent = '60 Hz file required';
    $('#metadata').textContent += ' · choose the matching .frames.ndjson file for exact playback';
  } catch (error) {
    setLoading(false);
    playButton.disabled = true;
    canvasPlay.disabled = true;
    range.disabled = true;
    $('#playbackState').textContent = 'Load failed';
    $('#metadata').textContent = error.message;
  }
});

async function loadReplayUrl(url) {
  stopPlayback();
  setLoading(true);
  setMatchContext(compactReplayName(url), 'AWS Nova replay', 'Exact recorded arena simulation.');
  try {
    const response = await fetch(url);
    if (!response.ok) throw new Error(`Replay request failed: ${response.status}`);
    loadReplayText(await response.text(), url);
    await loadSimulationRecording(url);
  } catch (error) {
    setLoading(false);
    $('#decisions').innerHTML = `<p class="bad">${escapeHtml(error.message)}</p>`;
    $('#playbackState').textContent = 'Load failed';
  }
}

function setMatchContext(title, kicker, reason) {
  $('#matchTitle').textContent = title;
  $('#matchKicker').textContent = kicker;
  $('#matchReason').textContent = reason;
}

function setLoading(isLoading) {
  $('#playbackState').textContent = isLoading ? 'Loading' : 'Ready';
  playButton.disabled = isLoading || !rows.length;
  canvasPlay.disabled = playButton.disabled;
}

function loadReplayText(text, url) {
  loadReplayRecords(parseNdjson(text), url);
}

function parseNdjson(text) {
  return text.split(/\r?\n/).filter(Boolean).map(line => JSON.parse(line));
}

function loadReplayRecords(replay, url) {
  match = replay.find(row => row.type === 'match_started') || null;
  rows = replay.filter(row => row.type === 'decision' && row.worldBefore && row.worldAfter)
    .sort((left, right) => left.worldBefore.gameTime - right.worldBefore.gameTime);
  if (!rows.length) throw new Error('This replay has no recorded simulation transitions.');

  activeReplayUrl = url;
  simulationFrames = [];
  physicsHz = 0;
  teamNames = new Map((match?.teams || []).map(team => [team.side, cleanTeamName(team)]));
  startTime = rows[0].worldBefore.gameTime;
  duration = rows.at(-1).worldAfter.gameTime - startTime;
  playhead = 0;
  renderedDecision = -1;
  renderedEventFrame = -1;
  range.min = 0;
  range.max = duration;
  range.value = 0;
  range.disabled = false;
  playButton.disabled = false;
  canvasPlay.disabled = false;
  $('#duration').textContent = formatClock(duration, false);
  $('#homeName').textContent = teamNames.get(0) || 'Home';
  $('#awayName').textContent = teamNames.get(1) || 'Away';
  const arena = match?.arena?.arenaVersion || match?.arenaVersion || 'unknown arena';
  $('#metadata').textContent = `${arena} · seed ${match?.seed ?? 'unknown'} · loading physics recording…`;
  setLoading(false);
  updatePlaybackUi();
  if (url) {
    playButton.disabled = true;
    canvasPlay.disabled = true;
    range.disabled = true;
    $('#playbackState').textContent = 'Loading recording';
  }
  renderCatalog();
  renderAt(playhead, true);
}

function recordingUrlFor(replayUrl) {
  const match = replayUrl.match(/^(.*)\/matches\/(.+\.ndjson)$/);
  if (!match) return null;
  return `${match[1]}/recordings/${match[2].replace(/\.ndjson$/, '.frames.ndjson')}`;
}

async function loadSimulationRecording(replayUrl) {
  const recordingUrl = recordingUrlFor(replayUrl);
  if (!recordingUrl) {
    $('#playbackState').textContent = 'Recording required';
    $('#metadata').textContent += ' · playback disabled: no engine recording';
    return;
  }
  const response = await fetch(recordingUrl);
  if (!response.ok) {
    playButton.disabled = true;
    canvasPlay.disabled = true;
    range.disabled = true;
    $('#playbackState').textContent = 'Recording required';
    $('#metadata').textContent += ' · playback disabled: exact engine recording unavailable';
    return;
  }
  const records = parseNdjson(await response.text());
  applySimulationRecording(records);
}

function applySimulationRecording(records, portable = false) {
  const header = records.find(record => record.type === 'simulation_recording_started');
  simulationFrames = records.filter(record => record.type === 'simulation_frame');
  physicsHz = Number(header?.physicsHz || 60);
  if (!simulationFrames.length) throw new Error('The physics recording contains no frames.');
  if (!match && header?.match) match = header.match;
  teamNames = new Map((match?.teams || []).map(team => [team.side, cleanTeamName(team)]));
  $('#homeName').textContent = teamNames.get(0) || 'Home';
  $('#awayName').textContent = teamNames.get(1) || 'Away';
  if (!rows.length) {
    rows = [{
      decisionTick: 0,
      worldBefore: recordedWorld(simulationFrames[0]),
      worldAfter: recordedWorld(simulationFrames.at(-1)),
      agentResults: [],
      events: []
    }];
  }
  startTime = simulationFrames[0].time;
  duration = simulationFrames.at(-1).time - startTime;
  playhead = 0;
  renderedDecision = -1;
  renderedEventFrame = -1;
  range.max = duration;
  range.value = 0;
  range.disabled = false;
  playButton.disabled = false;
  canvasPlay.disabled = false;
  $('#duration').textContent = formatClock(duration, false);
  const arena = match?.arena?.arenaVersion || match?.arenaVersion || 'unknown arena';
  $('#metadata').textContent = `${arena} · seed ${match?.seed ?? 'unknown'} · ${simulationFrames.length.toLocaleString()} engine frames at ${physicsHz}Hz · exact physics recording · no interpolation`;
  $('#playbackState').textContent = 'Physics recording';
  if (portable) renderDecisions([]);
  renderAt(0, true);
}

function findSegment(simulationTime) {
  let low = 0;
  let high = rows.length - 1;
  while (low < high) {
    const middle = Math.floor((low + high) / 2);
    if (rows[middle].worldAfter.gameTime < simulationTime) low = middle + 1;
    else high = middle;
  }
  return low;
}

function renderAt(relativeTime, forceDetails = false) {
  if (!rows.length) return;
  const simulationTime = startTime + clamp(relativeTime, 0, duration);
  const segmentIndex = findSegment(simulationTime);
  const row = rows[segmentIndex];
  let world;
  let exactFrameIndex = -1;
  if (simulationFrames.length) {
    exactFrameIndex = clamp(Math.round((simulationTime - startTime) * physicsHz), 0, simulationFrames.length - 1);
    world = recordedWorld(simulationFrames[exactFrameIndex]);
  } else {
    // Never invent motion between sparse decisions. Playback stays disabled
    // until an exact engine recording is available.
    world = row.worldBefore;
  }
  drawPitch(world);

  $('#homeScore').textContent = world.score.home;
  $('#awayScore').textContent = world.score.away;
  $('#clock').textContent = formatClock(world.gameTime, true);
  $('#tick').textContent = `decision ${row.decisionTick}`;
  $('#elapsed').textContent = formatClock(relativeTime, false);
  $('#playMode').textContent = String(world.playMode || 'OPEN PLAY').replaceAll('_', ' ');
  range.value = relativeTime;

  const decisionChanged = forceDetails || renderedDecision !== segmentIndex;
  if (decisionChanged) {
    renderedDecision = segmentIndex;
    renderDecisions(row.agentResults || []);
  }
  if (simulationFrames.length) {
    const eventFrame = latestEventFrame(exactFrameIndex);
    if (forceDetails || eventFrame !== renderedEventFrame) {
      renderedEventFrame = eventFrame;
      renderEvents(eventFrame >= 0 ? simulationFrames[eventFrame].events || [] : []);
    }
  } else if (decisionChanged) {
    renderEvents(row.events || []);
  }
}

function recordedWorld(frame) {
  return {
    gameTime: frame.time,
    score: { home: frame.score[0], away: frame.score[1] },
    playMode: frame.mode,
    players: frame.players.map(player => ({
      teamCode: player[0] === 0 ? 'home' : 'away',
      agentId: `agentId_${player[1]}`,
      position: { x: player[2], y: player[3] },
      isSprinting: false
    })),
    ball: {
      position: { x: frame.ball[0], y: frame.ball[1], z: frame.ball[2] },
      isFree: frame.ball[3],
      possessionTeamId: frame.ball[4],
      possessionAgentId: frame.ball[5] == null ? null : `agentId_${frame.ball[5]}`
    }
  };
}

function latestEventFrame(frameIndex) {
  for (let index = frameIndex; index >= 0; index -= 1) {
    if (simulationFrames[frameIndex].time - simulationFrames[index].time > 1.5) break;
    if ((simulationFrames[index].events || []).some(event => event.type !== 'COMMAND_APPLIED')) return index;
  }
  return -1;
}

function formatClock(seconds, tenths) {
  const safe = Math.max(0, seconds || 0);
  const minutes = Math.floor(safe / 60);
  const wholeSeconds = Math.floor(safe % 60);
  const fraction = tenths ? `.${Math.floor((safe % 1) * 10)}` : '';
  return `${String(minutes).padStart(2, '0')}:${String(wholeSeconds).padStart(2, '0')}${fraction}`;
}

function screenPosition(position) {
  return {
    x: 80 + ((position.x + 55) / 110) * 1040,
    y: 49 + ((position.y + 35) / 70) * 662
  };
}

function drawPitch(world) {
  const width = canvas.width;
  const height = canvas.height;
  const gradient = ctx.createLinearGradient(0, 0, width, height);
  gradient.addColorStop(0, '#19623a');
  gradient.addColorStop(.5, '#0f4d2d');
  gradient.addColorStop(1, '#174f31');
  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, width, height);

  for (let stripe = 0; stripe < 10; stripe += 1) {
    ctx.fillStyle = stripe % 2 ? '#ffffff08' : '#00000006';
    ctx.fillRect(80 + stripe * 104, 49, 104, 662);
  }
  ctx.strokeStyle = '#ddf4dfcc';
  ctx.lineWidth = 2.5;
  ctx.strokeRect(80, 49, 1040, 662);
  ctx.beginPath(); ctx.moveTo(600, 49); ctx.lineTo(600, 711); ctx.stroke();
  ctx.beginPath(); ctx.arc(600, 380, 91, 0, Math.PI * 2); ctx.stroke();
  ctx.beginPath(); ctx.arc(600, 380, 3, 0, Math.PI * 2); ctx.fillStyle = '#e5f4e8'; ctx.fill();
  ctx.strokeRect(80, 228, 156, 304); ctx.strokeRect(964, 228, 156, 304);
  ctx.strokeRect(80, 303, 58, 154); ctx.strokeRect(1062, 303, 58, 154);
  ctx.strokeStyle = '#d8eee0aa';
  ctx.strokeRect(60, 319, 20, 122); ctx.strokeRect(1120, 319, 20, 122);

  world.players.forEach(player => drawPlayer(player));
  drawBall(world.ball);
}

function drawPlayer(player) {
  const position = screenPosition(player.position);
  const isHome = player.teamCode === 'home';
  ctx.beginPath();
  ctx.ellipse(position.x + 2, position.y + 7, 15, 7, 0, 0, Math.PI * 2);
  ctx.fillStyle = '#03120b66';
  ctx.fill();
  if (player.isSprinting) {
    ctx.beginPath(); ctx.arc(position.x, position.y, 20, 0, Math.PI * 2);
    ctx.strokeStyle = isHome ? '#58b3ff66' : '#ff718666'; ctx.lineWidth = 3; ctx.stroke();
  }
  ctx.beginPath(); ctx.arc(position.x, position.y, 14.5, 0, Math.PI * 2);
  const fill = ctx.createRadialGradient(position.x - 4, position.y - 5, 1, position.x, position.y, 16);
  fill.addColorStop(0, isHome ? '#8bd0ff' : '#ff9aa7');
  fill.addColorStop(1, isHome ? '#2684df' : '#df3650');
  ctx.fillStyle = fill; ctx.fill();
  ctx.strokeStyle = '#07100ccc'; ctx.lineWidth = 2; ctx.stroke();
  ctx.fillStyle = '#fff'; ctx.font = '800 11px Inter, sans-serif'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
  ctx.fillText(player.agentId.split('_').pop(), position.x, position.y + .5);
}

function drawBall(ball) {
  const position = screenPosition(ball.position);
  const lift = Math.min(22, (ball.position.z || 0) * 3.2);
  ctx.beginPath(); ctx.ellipse(position.x + 2, position.y + 6, 8, 4, 0, 0, Math.PI * 2);
  ctx.fillStyle = '#03120b88'; ctx.fill();
  ctx.beginPath(); ctx.arc(position.x, position.y - lift, 7.5, 0, Math.PI * 2);
  ctx.fillStyle = '#fff'; ctx.fill(); ctx.strokeStyle = '#19211d'; ctx.lineWidth = 2; ctx.stroke();
  ctx.beginPath(); ctx.arc(position.x - 1, position.y - lift, 2.2, 0, Math.PI * 2); ctx.fillStyle = '#26332c'; ctx.fill();
}

function renderEvents(events) {
  const meaningful = events.filter(event => event.type !== 'COMMAND_APPLIED');
  const shown = meaningful.length ? meaningful : events.slice(0, 10);
  $('#events').innerHTML = shown.length ? shown.map(event => {
    const details = [event.command, event.player && `team ${event.player.team_id} · P${event.player.player_id}`, event.teamId != null && `team ${event.teamId}`].filter(Boolean).join(' · ');
    return `<div class="event"><span class="event-type">${escapeHtml(String(event.type).replaceAll('_', ' '))}</span><span class="event-detail">${escapeHtml(details)}</span></div>`;
  }).join('') : '<p class="muted">No events during this transition.</p>';
}

function renderDecisions(results) {
  $('#decisions').innerHTML = results.length ? results.map(result => `<div class="decision-card ${result.teamId === 0 ? 'home' : 'away'}">
    <header><strong><span class="player">P${result.playerId}</span> ${escapeHtml(teamNames.get(result.teamId) || `Team ${result.teamId}`)}</strong><span class="latency ${result.status === 'valid' ? '' : 'bad'}">${escapeHtml(result.status)} · ${escapeHtml(result.latencyMs)}ms</span></header>
    <code>${escapeHtml(result.wireCommand?.commandType || 'IDLE')}</code>
  </div>`).join('') : '<p class="muted">This portable recording contains exact physics frames; agent decisions remain in the smaller decision log.</p>';
}

function updatePlaybackUi() {
  playButton.textContent = playing ? 'Pause' : (playhead >= duration ? 'Replay' : 'Play');
  canvasPlay.textContent = playing ? 'Ⅱ' : '▶';
  canvasPlay.classList.toggle('hidden', playing);
  $('#playbackState').textContent = playing ? `${speed.value}× playing` : (playhead >= duration ? 'Finished' : 'Ready');
  $('#playbackState').classList.toggle('playing', playing);
}

function togglePlayback() {
  if (!rows.length) return;
  if (playing) {
    stopPlayback();
    return;
  }
  if (playhead >= duration) playhead = 0;
  playing = true;
  previousFrameTime = performance.now();
  updatePlaybackUi();
  animationFrame = requestAnimationFrame(animate);
}

function stopPlayback() {
  playing = false;
  previousFrameTime = null;
  if (animationFrame) cancelAnimationFrame(animationFrame);
  animationFrame = null;
  updatePlaybackUi();
}

function animate(timestamp) {
  if (!playing) return;
  const elapsed = Math.min(.1, (timestamp - previousFrameTime) / 1000);
  previousFrameTime = timestamp;
  playhead = Math.min(duration, playhead + elapsed * Number(speed.value));
  renderAt(playhead);
  if (playhead >= duration) {
    stopPlayback();
    return;
  }
  animationFrame = requestAnimationFrame(animate);
}

playButton.addEventListener('click', togglePlayback);
canvasPlay.addEventListener('click', togglePlayback);
range.addEventListener('input', () => {
  stopPlayback();
  playhead = Number(range.value);
  renderAt(playhead, true);
});
speed.addEventListener('change', updatePlaybackUi);
window.addEventListener('keydown', event => {
  if (event.code === 'Space' && !['INPUT', 'SELECT'].includes(document.activeElement.tagName)) {
    event.preventDefault();
    togglePlayback();
  }
});
window.addEventListener('popstate', () => {
  const requested = new URLSearchParams(location.search).get('log');
  if (requested) loadReplayUrl(requested);
});

drawPitch({ players: [], ball: { position: { x: 0, y: 0, z: 0 } } });
renderCatalog();
const requested = new URLSearchParams(location.search).get('log');
if (requested) {
  loadReplayUrl(requested);
} else {
  setLoading(false);
  $('#playbackState').textContent = 'No replay';
  setMatchContext('Open a generated match', 'AWS Nova replay', 'Use a replay link from the live match or choose a local .frames.ndjson file.');
}
