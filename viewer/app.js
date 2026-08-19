const canvas = document.querySelector('#pitch');
const ctx = canvas.getContext('2d');
const file = document.querySelector('#file');
const range = document.querySelector('#range');
const play = document.querySelector('#play');
let rows = [], index = 0, timer = null;

file.addEventListener('change', async () => {
  load(await file.files[0].text());
});
function load(text) {
  rows = text.split(/\r?\n/).filter(Boolean).map(line => JSON.parse(line)).filter(row => row.type === 'decision');
  index = 0; range.max = Math.max(0, rows.length - 1); range.value = 0;
  range.disabled = play.disabled = rows.length === 0; render();
}
range.addEventListener('input', () => { index = Number(range.value); render(); });
play.addEventListener('click', () => {
  if (timer) { clearInterval(timer); timer = null; play.textContent = 'Play'; return; }
  play.textContent = 'Pause';
  timer = setInterval(() => { index = (index + 1) % rows.length; range.value = index; render(); }, 650);
});

function screen(pos) { return { x: 50 + (pos.x + 55) / 110 * 1000, y: 50 + (pos.y + 35) / 70 * 600 }; }
function pitch() {
  ctx.fillStyle = '#17613b'; ctx.fillRect(0, 0, 1100, 700);
  ctx.strokeStyle = '#d9f1df'; ctx.lineWidth = 3; ctx.strokeRect(50, 50, 1000, 600);
  ctx.beginPath(); ctx.moveTo(550, 50); ctx.lineTo(550, 650); ctx.stroke();
  ctx.beginPath(); ctx.arc(550, 350, 90, 0, Math.PI * 2); ctx.stroke();
  ctx.strokeRect(50, 225, 145, 250); ctx.strokeRect(905, 225, 145, 250);
  ctx.strokeRect(28, 265, 22, 170); ctx.strokeRect(1050, 265, 22, 170);
}
function render() {
  pitch(); if (!rows.length) return;
  const row = rows[index], world = row.worldAfter;
  world.players.forEach(player => {
    const p = screen(player.position), home = player.teamCode === 'home';
    ctx.beginPath(); ctx.arc(p.x, p.y, 14, 0, Math.PI * 2);
    ctx.fillStyle = home ? '#397be5' : '#df4452'; ctx.fill(); ctx.strokeStyle='#07100d'; ctx.lineWidth=2; ctx.stroke();
    ctx.fillStyle='#fff'; ctx.font='bold 12px sans-serif'; ctx.textAlign='center'; ctx.textBaseline='middle';
    ctx.fillText(player.agentId.split('_').pop(), p.x, p.y);
  });
  const ball = screen(world.ball.position); ctx.beginPath(); ctx.arc(ball.x, ball.y, 8, 0, Math.PI*2); ctx.fillStyle='#fff';ctx.fill();ctx.stroke();
  document.querySelector('#homeScore').textContent = world.score.home;
  document.querySelector('#awayScore').textContent = world.score.away;
  const seconds=Math.floor(world.gameTime); document.querySelector('#clock').textContent=`${String(Math.floor(seconds/60)).padStart(2,'0')}:${String(seconds%60).padStart(2,'0')}`;
  document.querySelector('#tick').textContent=`decision ${row.decisionTick}`;
  document.querySelector('#decisions').innerHTML = row.agentResults.map(result => `<article class="card ${result.teamId === 0 ? 'home':'away'}">
    <strong>${result.teamId === 0 ? 'HOME':'AWAY'} P${result.playerId}</strong>
    <p class="${result.status === 'valid' ? 'ok':'bad'}">${result.status} · ${result.latencyMs} ms</p>
    <p><code>${result.wireCommand?.commandType || 'IDLE'}</code></p>
    ${result.error ? `<p>${result.error}</p>`:''}</article>`).join('');
}
pitch();
const logUrl = new URLSearchParams(location.search).get('log');
if (logUrl) fetch(logUrl).then(response => {
  if (!response.ok) throw new Error(`Replay request failed: ${response.status}`);
  return response.text();
}).then(load).catch(error => {
  document.querySelector('#decisions').innerHTML = `<p class="bad">${error.message}</p>`;
});
