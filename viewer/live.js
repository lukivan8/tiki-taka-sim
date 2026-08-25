const $ = selector => document.querySelector(selector);
const canvas = $('#pitch');
const ctx = canvas.getContext('2d');
const form = $('#matchForm');
const homeSelect = $('#homeTeam');
const awaySelect = $('#awayTeam');
const homeFormationSelect = $('#homeFormation');
const awayFormationSelect = $('#awayFormation');
const startButton = $('#startMatch');
const inviteToken = $('#inviteToken');

let teams = [];
let formations = [];
let activeMatch = null;
let stream = null;
let exactFrames = 0;
let streamStartedAt = 0;
let recentEvents = [];

inviteToken.value = sessionStorage.getItem('afcInviteToken') || '';

function authHeaders(extra = {}) {
  const token = inviteToken.value.trim();
  return token ? { ...extra, authorization: `Bearer ${token}` } : extra;
}

inviteToken.addEventListener('input', () => {
  sessionStorage.setItem('afcInviteToken', inviteToken.value.trim());
  startButton.disabled = !inviteToken.value.trim() || !teams.length;
});

const escapeHtml = value => String(value ?? '').replace(/[&<>'"]/g, character => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'
})[character]);

async function loadTeams() {
  const response = await fetch('/api/teams');
  if (!response.ok) throw new Error('Live simulator API is not available. Start it with make run-live-simulator.');
  const catalog = await response.json();
  teams = catalog.teams;
  formations = catalog.formations;
  const options = teams.map(team => `<option value="${escapeHtml(team.id)}">${escapeHtml(team.name)}</option>`).join('');
  const formationOptions = formations.map(formation => `<option value="${escapeHtml(formation.id)}">${escapeHtml(formation.label)}</option>`).join('');
  homeSelect.innerHTML = options;
  awaySelect.innerHTML = options;
  homeFormationSelect.innerHTML = formationOptions;
  awayFormationSelect.innerHTML = formationOptions;
  homeSelect.value = teams[0]?.id || '';
  awaySelect.value = teams[1]?.id || teams[0]?.id || '';
  homeFormationSelect.value = '1-1-1-2';
  awayFormationSelect.value = '1-1-1-2';
  $('#teamCount').textContent = `${teams.length}`;
  $('#teamCatalog').innerHTML = teams.map(team => `<article class="team-card" data-team="${escapeHtml(team.id)}">
    <div><strong>${escapeHtml(team.name)}</strong><span>${escapeHtml(team.style)}</span></div>
    <p>${escapeHtml(team.description)}</p>
  </article>`).join('');
  startButton.disabled = !inviteToken.value.trim();
  updatePreview();
}

function selectedTeam(select) { return teams.find(team => team.id === select.value); }
function selectedFormation(select) { return formations.find(formation => formation.id === select.value); }
function applyTeamFormation(teamSelect, formationSelect) {
  const team = selectedTeam(teamSelect);
  if (team?.defaultFormation && formations.some(formation => formation.id === team.defaultFormation)) {
    formationSelect.value = team.defaultFormation;
  }
}

function updatePreview() {
  const home = selectedTeam(homeSelect);
  const away = selectedTeam(awaySelect);
  if (!home || !away || activeMatch) return;
  $('#homeName').textContent = home.name;
  $('#awayName').textContent = away.name;
  $('#matchTitle').textContent = `${home.name} vs ${away.name}`;
  const homeFormation = selectedFormation(homeFormationSelect);
  const awayFormation = selectedFormation(awayFormationSelect);
  if (homeFormation && awayFormation) {
    $('#matchReason').textContent = `${homeFormation.label} vs ${awayFormation.label} · both teams start in their own half.`;
  }
  document.querySelectorAll('.team-card').forEach(card => {
    card.classList.toggle('selected-home', card.dataset.team === home.id);
    card.classList.toggle('selected-away', card.dataset.team === away.id);
  });
}

$('#swapTeams').addEventListener('click', () => {
  const home = homeSelect.value;
  const homeFormation = homeFormationSelect.value;
  homeSelect.value = awaySelect.value;
  homeFormationSelect.value = awayFormationSelect.value;
  awaySelect.value = home;
  awayFormationSelect.value = homeFormation;
  updatePreview();
});
homeSelect.addEventListener('change', () => { applyTeamFormation(homeSelect, homeFormationSelect); updatePreview(); });
awaySelect.addEventListener('change', () => { applyTeamFormation(awaySelect, awayFormationSelect); updatePreview(); });
homeFormationSelect.addEventListener('change', updatePreview);
awayFormationSelect.addEventListener('change', updatePreview);

form.addEventListener('submit', async event => {
  event.preventDefault();
  if (activeMatch) {
    await fetch(`/api/matches/${activeMatch.matchId}/stop`, {
      method: 'POST', headers: authHeaders()
    });
    startButton.disabled = true;
    startButton.textContent = 'Stopping…';
    return;
  }
  await startMatch();
});

async function startMatch() {
  resetLiveUi();
  startButton.disabled = true;
  startButton.textContent = 'Starting…';
  setState('Starting', true);
  const response = await fetch('/api/matches', {
    method: 'POST', headers: authHeaders({ 'content-type': 'application/json' }),
    body: JSON.stringify({ homeTeamId: homeSelect.value, awayTeamId: awaySelect.value,
      homeFormation: homeFormationSelect.value, awayFormation: awayFormationSelect.value, seed: 42 })
  });
  const result = await response.json();
  if (!response.ok) {
    activeMatch = null;
    startButton.disabled = false;
    startButton.textContent = 'Start live match';
    setState('Failed');
    $('#matchReason').textContent = result.error || 'The match could not start.';
    return;
  }
  activeMatch = result;
  homeSelect.disabled = true;
  awaySelect.disabled = true;
  homeFormationSelect.disabled = true;
  awayFormationSelect.disabled = true;
  $('#swapTeams').disabled = true;
  startButton.disabled = false;
  startButton.textContent = 'Stop match';
  $('#pitchPrompt').classList.add('hidden');
  $('#matchTitle').textContent = `${result.home.name} vs ${result.away.name}`;
  $('#matchReason').textContent = `Match ${result.matchId} · ${result.formations.home} vs ${result.formations.away} · exact 60 Hz engine frames.`;
  stream = new EventSource(result.streamUrl);
  stream.onmessage = event => handleMessage(JSON.parse(event.data));
  stream.onerror = () => { if (activeMatch) setState('Reconnecting', true); };
}

function handleMessage(message) {
  if (message.type === 'match_started') {
    streamStartedAt = performance.now();
    exactFrames = 1;
    setState('Live', true);
    $('#physicsRate').textContent = `${message.physicsHz} Hz`;
    $('#frameCount').textContent = '1';
    renderFrame(message.frame, 0);
    return;
  }
  if (message.type === 'simulation_frame') {
    exactFrames += 1;
    renderFrame(message.frame, message.decisionTick);
    if (message.agentResults) renderDecisions(message.agentResults);
    if (message.frame.events?.length) addEvents(message.frame.events);
    $('#frameCount').textContent = exactFrames.toLocaleString();
    const elapsed = Math.max(.001, (performance.now() - streamStartedAt) / 1000);
    $('#streamRate').textContent = `${(exactFrames / elapsed).toFixed(1)} fps`;
    return;
  }
  if (message.type === 'match_ended') {
    stream?.close();
    setState(message.status === 'finished' ? 'Full time' : 'Stopped');
    const viewerUrl = `/viewer/?log=${encodeURIComponent(message.replay)}`;
    const recordingLink = message.recording
      ? ` · <a href="${escapeHtml(message.recording)}" download>download full 60 Hz recording</a>`
      : '';
    $('#matchReason').innerHTML = `Exact recording saved · <a href="${escapeHtml(viewerUrl)}">watch replay</a>${recordingLink} · <a href="${escapeHtml(message.replay)}" download>download decision log</a>`;
    finishMatch();
    return;
  }
  if (message.type === 'match_failed') {
    stream?.close();
    setState('Failed');
    $('#matchReason').textContent = message.error;
    finishMatch();
  }
}

function finishMatch() {
  activeMatch = null;
  stream = null;
  homeSelect.disabled = false;
  awaySelect.disabled = false;
  homeFormationSelect.disabled = false;
  awayFormationSelect.disabled = false;
  $('#swapTeams').disabled = false;
  startButton.disabled = false;
  startButton.textContent = 'Start another match';
}

function resetLiveUi() {
  exactFrames = 0;
  recentEvents = [];
  $('#frameCount').textContent = '0';
  $('#streamRate').textContent = '0.0 fps';
  $('#homeScore').textContent = '0';
  $('#awayScore').textContent = '0';
  $('#clock').textContent = '00:00.0';
  $('#tick').textContent = 'decision 0';
  $('#events').innerHTML = '<p class="muted">Waiting for the first event.</p>';
  $('#decisions').innerHTML = '<p class="muted decision-placeholder">Waiting for the first decision.</p>';
}

function setState(label, live = false) {
  $('#liveState').textContent = label;
  $('#liveState').classList.toggle('playing', live);
}

function renderFrame(frame, decisionTick) {
  const world = recordedWorld(frame);
  drawPitch(world);
  $('#homeScore').textContent = world.score.home;
  $('#awayScore').textContent = world.score.away;
  $('#clock').textContent = formatClock(world.gameTime);
  $('#tick').textContent = `decision ${decisionTick}`;
  $('#playMode').textContent = String(world.playMode || 'OPEN PLAY').replaceAll('_', ' ');
}

function recordedWorld(frame) {
  return {
    gameTime: frame.time, score: { home: frame.score[0], away: frame.score[1] }, playMode: frame.mode,
    players: frame.players.map(player => ({ teamCode: player[0] === 0 ? 'home' : 'away',
      agentId: `agentId_${player[1]}`, position: { x: player[2], y: player[3] } })),
    ball: { position: { x: frame.ball[0], y: frame.ball[1], z: frame.ball[2] },
      isFree: frame.ball[3], possessionTeamId: frame.ball[4],
      possessionAgentId: frame.ball[5] == null ? null : `agentId_${frame.ball[5]}` }
  };
}

function formatClock(seconds) {
  const safe = Math.max(0, seconds || 0);
  return `${String(Math.floor(safe / 60)).padStart(2, '0')}:${String(Math.floor(safe % 60)).padStart(2, '0')}.${Math.floor((safe % 1) * 10)}`;
}

function screenPosition(position) {
  return { x: 80 + ((position.x + 55) / 110) * 1040, y: 49 + ((position.y + 35) / 70) * 662 };
}

function drawPitch(world) {
  const gradient = ctx.createLinearGradient(0, 0, canvas.width, canvas.height);
  gradient.addColorStop(0, '#19623a'); gradient.addColorStop(.5, '#0f4d2d'); gradient.addColorStop(1, '#174f31');
  ctx.fillStyle = gradient; ctx.fillRect(0, 0, canvas.width, canvas.height);
  for (let stripe = 0; stripe < 10; stripe += 1) {
    ctx.fillStyle = stripe % 2 ? '#ffffff08' : '#00000006'; ctx.fillRect(80 + stripe * 104, 49, 104, 662);
  }
  ctx.strokeStyle = '#ddf4dfcc'; ctx.lineWidth = 2.5; ctx.strokeRect(80, 49, 1040, 662);
  ctx.beginPath(); ctx.moveTo(600, 49); ctx.lineTo(600, 711); ctx.stroke();
  ctx.beginPath(); ctx.arc(600, 380, 91, 0, Math.PI * 2); ctx.stroke();
  ctx.beginPath(); ctx.arc(600, 380, 3, 0, Math.PI * 2); ctx.fillStyle = '#e5f4e8'; ctx.fill();
  ctx.strokeRect(80, 228, 156, 304); ctx.strokeRect(964, 228, 156, 304);
  ctx.strokeRect(80, 328, 58, 104); ctx.strokeRect(1062, 328, 58, 104);
  ctx.strokeStyle = '#d8eee0aa'; ctx.strokeRect(60, 345, 20, 70); ctx.strokeRect(1120, 345, 20, 70);
  world.players.forEach(drawPlayer); drawBall(world.ball);
}

function drawPlayer(player) {
  const position = screenPosition(player.position); const home = player.teamCode === 'home';
  ctx.beginPath(); ctx.ellipse(position.x + 2, position.y + 7, 15, 7, 0, 0, Math.PI * 2); ctx.fillStyle = '#03120b66'; ctx.fill();
  ctx.beginPath(); ctx.arc(position.x, position.y, 14.5, 0, Math.PI * 2);
  const fill = ctx.createRadialGradient(position.x - 4, position.y - 5, 1, position.x, position.y, 16);
  fill.addColorStop(0, home ? '#8bd0ff' : '#ff9aa7'); fill.addColorStop(1, home ? '#2684df' : '#df3650');
  ctx.fillStyle = fill; ctx.fill(); ctx.strokeStyle = '#07100ccc'; ctx.lineWidth = 2; ctx.stroke();
  ctx.fillStyle = '#fff'; ctx.font = '800 11px Inter, sans-serif'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
  ctx.fillText(player.agentId.split('_').pop(), position.x, position.y + .5);
}

function drawBall(ball) {
  const position = screenPosition(ball.position);
  ctx.beginPath(); ctx.ellipse(position.x + 2, position.y + 6, 8, 4, 0, 0, Math.PI * 2); ctx.fillStyle = '#03120b88'; ctx.fill();
  ctx.beginPath(); ctx.arc(position.x, position.y, 7.5, 0, Math.PI * 2); ctx.fillStyle = '#fff'; ctx.fill();
  ctx.strokeStyle = '#19211d'; ctx.lineWidth = 2; ctx.stroke();
  ctx.beginPath(); ctx.arc(position.x - 1, position.y, 2.2, 0, Math.PI * 2); ctx.fillStyle = '#26332c'; ctx.fill();
}

function addEvents(events) {
  const meaningful = events.filter(event => event.type !== 'COMMAND_APPLIED');
  if (!meaningful.length) return;
  recentEvents = [...meaningful, ...recentEvents].slice(0, 12);
  $('#events').innerHTML = recentEvents.map(event => {
    const player = event.player && `team ${event.player.team_id} · P${event.player.player_id}`;
    const details = [event.command, player, event.team_id != null && `team ${event.team_id}`].filter(Boolean).join(' · ');
    return `<div class="event"><span class="event-type">${escapeHtml(String(event.type).replaceAll('_', ' '))}</span><span class="event-detail">${escapeHtml(details)}</span></div>`;
  }).join('');
}

function renderDecisions(results) {
  $('#decisions').innerHTML = results.map(result => `<div class="decision-card ${result.teamId === 0 ? 'home' : 'away'}">
    <header><strong><span class="player">P${result.playerId}</span> ${escapeHtml(result.teamIdentity.toUpperCase())}</strong><span class="latency ${result.status === 'valid' ? '' : 'bad'}">${escapeHtml(result.status)} · ${escapeHtml(result.latencyMs)}ms</span></header>
    <code>${escapeHtml(result.wireCommand?.commandType || 'IDLE')}</code>
  </div>`).join('');
}

drawPitch({ players: [], ball: { position: { x: 0, y: 0 } } });
loadTeams().catch(error => {
  setState('API offline');
  $('#matchReason').textContent = error.message;
  $('#teamCatalog').innerHTML = `<p class="bad">${escapeHtml(error.message)}</p>`;
});
