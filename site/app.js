const $ = (s) => document.querySelector(s);
const esc = (v) => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const num = (v, n=0) => Number(v || 0).toLocaleString('ko-KR', {minimumFractionDigits:n, maximumFractionDigits:n});
const pct = (v) => `${num(v * 100, 1)}%`;
const COLORS={LT:'#a72d3d',LG:'#8f244b',HT:'#b13d39',SS:'#4166a0',SK:'#af3036',OB:'#3a4763',KT:'#353b43',NC:'#476f80',HH:'#bd672d',WO:'#6b3546'};
const MARKS={LT:'G',LG:'LG',HT:'K',SS:'S',SK:'SSG',OB:'D',KT:'kt',NC:'NC',HH:'H',WO:'K'};
const params = new URLSearchParams(location.search);
const state={tab:params.get('tab')==='players'?'players':'teams',season:params.get('season')||'2025',team:params.get('team')||'LT',mode:'batting',role:'pitching',sort:'score',includeSmall:false,player:null};
const cache=new Map(); let meta, packs, gameRequest=0;
const read = async (url) => { const r=await fetch(url); if(!r.ok) throw new Error(`자료를 불러오지 못했습니다 (${r.status})`); return r.json(); };
const mark=(t)=>`<span class="team-mark" style="--team-color:${COLORS[t]||'#555'}">${MARKS[t]||esc(t)}</span>`;
const name=(t)=>meta.teams[t]||t;
const mode=()=>state.mode==='pitching'?state.role:state.mode;
const current=()=>packs[state.season==='all'?'2025':state.season];
const selectedGames=()=>state.season==='all'?[...packs['2024'].games,...packs['2025'].games]:current().games;

function updateURL(extra={}) {
  const q=new URLSearchParams({...Object.fromEntries(new URLSearchParams(location.search)),season:state.season,tab:state.tab,team:state.team,...extra});
  for(const k of ['game']) if(extra[k]==='') q.delete(k);
  history.replaceState(null,'',`${location.pathname}?${q}`);
}

function teamsFrom(games) {
  if(state.season!=='all') return current().teams;
  const losses=games.filter(g=>g.lost); const prior=losses.reduce((a,g)=>a+g.score,0)/losses.length;
  return Object.entries(meta.teams).map(([team,n])=>{
    const own=games.filter(g=>g.team===team), lost=own.filter(g=>g.lost), hope=own.filter(g=>g.promise);
    const total=lost.reduce((a,g)=>a+g.score,0);
    return {team,name:n,games:own.length,losses:lost.length,wins:own.filter(g=>g.won).length,ties:own.filter(g=>g.tied).length,score:(total+10*prior)/(lost.length+10),rawMean:total/lost.length,total,hopeGames:hope.length,hopeLosses:hope.filter(g=>g.lost).length,lateBlown:lost.filter(g=>g.lateBlown).length,comebackLosses:lost.filter(g=>g.recovery>0).length,oneRunLosses:lost.filter(g=>Math.abs(g.homeScore-g.awayScore)===1).length};
  }).sort((a,b)=>b.score-a.score);
}

function render() {
  $('#status').hidden=true;
  if(state.tab==='players'&&state.season==='all') state.season='2025';
  $('#season').value=state.season;
  $('#season option[value=all]').disabled=state.tab==='players';
  for(const tab of ['teams','players']) {
    $(`#${tab}-tab`).setAttribute('aria-selected',String(state.tab===tab));
    $(`#${tab}-tab`).tabIndex=state.tab===tab?0:-1;
    $(`#${tab}-panel`).hidden=state.tab!==tab;
  }
  const count=state.season==='all'?1440:720;
  $('#coverage-line').textContent=`${state.season==='all'?'2024–2025':state.season} 정규시즌 · ${num(count)}경기 검산`;
  if(state.tab==='teams') renderTeams(); else renderPlayers();
  updateURL();
}

function renderTeams() {
  const games=selectedGames(), teams=teamsFrom(games), rank=teams.findIndex(t=>t.team===state.team);
  const own=teams[rank]||teams.find(t=>t.team==='LT'); state.team=own.team;
  const topGames=games.filter(g=>g.team===own.team&&g.lost).sort((a,b)=>b.score-a.score).slice(0,6);
  $('#teams-panel').innerHTML=`
    <div class="hero-grid">
      <article class="spotlight"><div class="kicker">HOPE, THEN HEARTBREAK</div><h2>${esc(own.name)}의 희망고문 <span class="tiny">${rank+1}위 / 10구단</span></h2><div class="big-number">${num(own.score,1)} <small>/ 100</small></div><div class="under">패배 한 경기당 스트레스 강도 · 표본 보정 적용</div></article>
      <article class="summary-card"><h3>${esc(own.name)} 팬에게 남은 기록</h3><div class="metrics"><div><div class="value">${num(own.lateBlown)}<small>후반 리드 후 패배</small></div></div><div><div class="value">${num(own.comebackLosses)}<small>추격하며 기대 준 패배</small></div></div><div><div class="value">${own.hopeGames?num(100*own.hopeLosses/own.hopeGames,1):'—'}<small>희망 확보 후 패배율 %</small></div></div></div><p class="footnote">${num(own.wins)}승 ${num(own.losses)}패 ${num(own.ties)}무 · 후반 기대승점 65% 이상 ${own.hopeGames}경기 중 ${own.hopeLosses}패</p></article>
    </div>
    <div class="section-title"><h2>어느 구단이 가장 희망고문했을까</h2><p>구단 이름을 누르면 그 팀의 스트레스 경기를 볼 수 있어요</p></div>
    <div class="panel"><div class="table-wrap"><table><thead><tr><th>순위</th><th>구단</th><th>희망고문 점수 ↓</th><th>후반 리드 후 패배</th><th>희망 후 패배</th><th>승–패–무</th><th>누적 스트레스</th></tr></thead><tbody>${teams.map((t,i)=>`<tr class="${t.team===state.team?'selected':''}"><td>${i+1}</td><td><button class="name-button" data-team="${t.team}" aria-pressed="${t.team===state.team}">${mark(t.team)}${esc(t.name)}</button></td><td class="score-cell"><span class="bar"><i style="width:${Math.min(t.score,100)}%"></i></span>${num(t.score,1)}</td><td>${t.lateBlown}</td><td>${t.hopeLosses} / ${t.hopeGames}</td><td class="muted">${t.wins}–${t.losses}–${t.ties}</td><td class="muted">${num(t.total)}</td></tr>`).join('')}</tbody></table></div><div class="table-note">희망 후 패배 = 6회 이후 기대승점 65% 이상이었던 경기 중 패배 · 누적값은 경기 수의 영향을 받으므로 대표 순위와 구분합니다</div></div>
    <div class="section-title"><h2>${esc(own.name)}, 이 경기는 잊기 어려웠다</h2><p>스트레스 점수가 높은 패배 TOP 6</p></div>
    <div class="cards">${topGames.map(g=>gameCard(g)).join('')}</div>`;
  $('#teams-panel').querySelectorAll('[data-team]').forEach(b=>b.addEventListener('click',()=>{state.team=b.dataset.team;render();}));
  wireGames($('#teams-panel'));
}

function gameCard(g) {
  const isHome=g.team===g.home, teamScore=isHome?g.homeScore:g.awayScore, oppScore=isHome?g.awayScore:g.homeScore;
  return `<button class="game-card" data-game="${esc(g.id)}" data-game-team="${g.team}"><span class="date">${esc(g.date.replaceAll('-','.'))}<span>${isHome?'홈':'원정'}${g.stadium?' · '+esc(g.stadium):''}</span></span><h3>${esc(name(g.team))} vs ${esc(name(g.opponent))}</h3><div class="game-score">${teamScore} : ${oppScore}<span>패배</span></div><div class="hope">최고 기대승점 ${pct(g.peak)} → 패배</div><div class="tags">${g.tags.slice(0,3).map(t=>`<span class="tag">${esc(t)}</span>`).join('')||'<span class="tag">리드와 추격의 기록</span>'}</div><span class="card-link">그날의 흐름 보기 ↗ <strong>${num(g.score,1)}점</strong></span></button>`;
}

function renderPlayers() {
  const pack=current(), field=state.mode==='fielding', role=mode();
  const players=(pack.players[role]||[]).filter(p=>state.includeSmall||p.eligible).sort((a,b)=>(b[state.sort]-a[state.sort])||(state.sort==='score'&&!field?b.rate-a.rate:0)||(b.total-a.total));
  const selected=players.find(p=>p.id===state.player)||players[0];state.player=selected?.id;
  const f=pack.coverage.fielding;
  const contextNote=field?`시즌 실책 ${f.boxErrors}개를 이닝별로 대조했습니다. 야수 책임 ${f.assignedErrors}개를 연결했고, 투수 실책 ${f.pitcherErrors}개와 책임 불명확 ${f.ambiguousErrors}개는 야수 순위에서 제외했습니다.`:'이기고 있거나 추격 가능한 접전에서 기대승점을 잃은 장면을 집계합니다. 누적 순위는 기회 수의 영향을 받고, 지수는 기회당 손실에 표본 보정을 적용합니다.';
  $('#players-panel').innerHTML=`
    <div class="mode-bar"><div class="segmented" role="group" aria-label="선수 부문">${[['batting','야수 · 타격'],['fielding','야수 · 수비'],['pitching','투수']].map(([m,label])=>`<button data-mode="${m}" class="${state.mode===m?'active':''}" aria-pressed="${state.mode===m}">${label}</button>`).join('')}</div><div class="segmented" role="group" aria-label="정렬 기준"><button data-sort="score" class="${state.sort==='score'?'active':''}">꼴데력 지수</button><button data-sort="total" class="${state.sort==='total'?'active':''}">누적 스트레스</button></div></div>
    ${state.mode==='pitching'?`<div class="role-row"><span>등판 역할</span>${[['pitching','전체'],['starter','선발 등판'],['reliever','불펜 등판']].map(([m,label])=>`<button data-role="${m}" class="${state.role===m?'active':''}" aria-pressed="${state.role===m}">${label}</button>`).join('')}<span>같은 선수도 등판별 역할로 나눠 집계합니다</span></div>`:''}
    ${selected?`<div class="player-grid"><article class="spotlight"><div class="kicker">LOTTE GIANTS · ${esc(pack.season)} ARCHIVE</div><h2>${esc(selected.name)} <span class="tiny">${esc(field?'야수 수비':state.mode==='batting'?'야수 타격':{'pitching':'투수 전체','starter':'선발 등판','reliever':'불펜 등판'}[role])}</span></h2><div class="big-number">${num(selected.score,1)} <small>/ 100</small></div><div class="under">2024 롯데 동일 부문 기준 상대 지수${!selected.eligible?' · 표본 부족, 잠정':''}</div><div class="player-meta">${selected.games}경기 · ${field?selected.errors+'개 실책':selected.opportunities+'회 스트레스 기회'}</div></article><article class="player-note"><h3>${field?'수비가 남긴 순간':'잘하고 못하고보다, 언제 무너졌는가'}</h3><p>${contextNote}</p><p style="margin-top:12px">${field?'수비 이닝·처리 기회가 확보되지 않아 수비 능력이나 실책률 순위는 제공하지 않습니다.':'타석 단위 연구용 기대승점 변화입니다. 투수 부문은 실책 출루 타석을 제외하지만 모든 수비·주루 영향을 분리한 순수 투수 책임은 아닙니다.'}</p></article></div>`:''}
    <div class="section-title"><h2>${pack.season} 롯데 선수 기록</h2><label class="tiny muted"><input type="checkbox" id="include-small" ${state.includeSmall?'checked':''}> 표본 부족 선수도 보기</label></div>
    <div class="panel"><div class="table-wrap"><table><thead><tr><th>순위</th><th>선수</th><th>꼴데력 지수</th><th>${field?'확인 실책':'스트레스 기회'}</th><th>${field?'출장 경기':'100기회당 보정 손실'}</th><th>누적 스트레스</th>${field?'':'<th>패배 경기에서</th>'}</tr></thead><tbody>${players.map((p,i)=>`<tr class="${p.id===state.player?'selected':''}"><td>${i+1}</td><td><button class="name-button" data-player="${esc(p.id)}">${esc(p.name)}${!p.eligible?'<span class="provisional">잠정</span>':''}</button></td><td class="score-cell"><span class="bar"><i style="width:${p.score}%"></i></span>${num(p.score,1)}</td><td>${field?p.errors:p.opportunities}</td><td class="muted">${field?p.games:num(p.rate,1)}</td><td>${num(p.total,1)}</td>${field?'':`<td class="muted">${num(p.lossGameStress,1)}</td>`}</tr>`).join('')||'<tr><td colspan="7">조건에 맞는 선수가 없습니다</td></tr>'}</tbody></table></div><div class="table-note">${field?'수비 지수는 상황별 실책 손실 누적값의 2024 기준 분위 · 30경기 이상 선수 기본 표시':'타격 100타석 / 투수 60상대 타석 및 스트레스 기회 15회 이상 기본 표시 · 20기회만큼 평균으로 보정 · 지수는 2024 동일 부문 기준 분위'}</div></div>
    ${selected?`<div class="section-title"><h2>${esc(selected.name)}, 점수에 남은 장면들</h2><p>스트레스 손실이 큰 장면 · 경기를 눌러 전체 흐름을 확인하세요</p></div><div class="panel player-moments">${selected.moments.map(m=>moment(m,field)).join('')||'<div class="empty">이 기준에 해당하는 스트레스 장면이 없습니다</div>'}</div>`:''}`;
  $('#players-panel').querySelectorAll('[data-mode]').forEach(b=>b.addEventListener('click',()=>{state.mode=b.dataset.mode;state.player=null;render();}));
  $('#players-panel').querySelectorAll('[data-role]').forEach(b=>b.addEventListener('click',()=>{state.role=b.dataset.role;state.player=null;render();}));
  $('#players-panel').querySelectorAll('[data-sort]').forEach(b=>b.addEventListener('click',()=>{state.sort=b.dataset.sort;render();}));
  $('#players-panel').querySelectorAll('[data-player]').forEach(b=>b.addEventListener('click',()=>{state.player=b.dataset.player;render();}));
  $('#include-small').addEventListener('change',e=>{state.includeSmall=e.target.checked;render();});
  wireGames($('#players-panel'));
}

function moment(m,field=false) {
  return `<button class="moment-button" data-game="${esc(m.game)}" data-game-team="LT"><span class="date">${esc(m.date.slice(5).replace('-','.'))} · ${m.inning}회${m.half==='top'?'초':'말'}</span><span><strong>${field?'공식 실책':esc(m.batter)+' · '+esc(m.event)}</strong><small>${m.before?`홈 ${m.before[0]} : 원정 ${m.before[1]}`:''}${field?'':` · 투수 ${esc(m.pitcher)}`} ${m.lost===true?'· 패배 경기':''}${m.lost===false?'· 승리/무승부 경기':''}</small></span><span class="loss">−${num(Math.abs(m.wpa),1)}<small>기대승점 %p</small></span></button>`;
}
function wireGames(root) { root.querySelectorAll('[data-game]').forEach(b=>b.addEventListener('click',()=>showGame(b.dataset.game,b.dataset.gameTeam||'LT'))); }

function chart(g,team) {
  const home=team===g.home, points=g.points, maxX=points.length-1;
  const x=(i)=>48+i/maxX*744,y=(p)=>211-(home?p:1-p)*170;
  const path=points.map((p,i)=>`${i?'L':'M'}${x(i).toFixed(2)},${y(p[5]).toFixed(2)}`).join(' ');
  const ticks=[];for(let i=1;i<points.length;i++) if(i===1||points[i][1]!==points[i-1][1])ticks.push([i,points[i][1]]);
  return `<svg id="we-chart" viewBox="0 0 820 255" role="img" aria-label="${esc(name(team))}의 타석별 기대승점 변화 그래프"><title>${esc(name(team))}의 기대승점. 가로축은 경기 진행 순서입니다.</title>${[0,.25,.5,.75,1].map(v=>`<line x1="48" x2="792" y1="${y(home?v:1-v)}" y2="${y(home?v:1-v)}" stroke="${v===.5?'#c4c8c9':'#eeefeb'}" ${v===.5?'stroke-dasharray="5 5"':''}/><text x="38" y="${y(home?v:1-v)+3}" text-anchor="end" font-size="10" fill="#8a8f93">${v*100}%</text>`).join('')}<path d="${path} L792,211 L48,211 Z" fill="#a72d3d0d"/><path d="${path}" fill="none" stroke="#a72d3d" stroke-width="2.3"/>${ticks.map(([i,inn])=>`<text x="${x(i)}" y="235" text-anchor="middle" font-size="10" fill="#81868a">${inn}회</text>`).join('')}<circle cx="792" cy="${y(points.at(-1)[5])}" r="4" fill="#a72d3d"/></svg>`;
}

async function showGame(id,team) {
  const request=++gameRequest;const dialog=$('#game-dialog');
  $('#game-content').innerHTML='<div class="loading">그날의 경기 기록을 불러오는 중</div>';
  if(!dialog.open)dialog.showModal();
  updateURL({game:id,team});
  try {
    const g=cache.has(id)?cache.get(id):await read(`./data/games/${encodeURIComponent(id)}.json`);cache.set(id,g);
    if(request!==gameRequest||!dialog.open)return;
    const pack=packs[id.slice(0,4)], entry=pack.games.find(r=>r.id===id&&r.team===team)||pack.games.find(r=>r.id===id);
    team=entry.team; const isHome=team===g.home;
    const p=g.points.map(p=>isHome?p[5]:1-p[5]);
    const drops=g.points.slice(1).map((r,i)=>({r,delta:p[i+1]-p[i],i:i+1})).filter(x=>x.delta<0).sort((a,b)=>a.delta-b.delta).slice(0,5);
    $('#game-content').innerHTML=`<div class="eyebrow">THE GAME WE REMEMBER</div><h2>${esc(name(g.away))} ${g.awayScore} : ${g.homeScore} ${esc(name(g.home))}</h2><div class="dialog-meta">${esc(g.date)} · ${g.stadium?esc(g.stadium)+' · ':''}${esc(name(team))} 팬의 시점 · ${entry.lost?'패배':entry.won?'승리':'무승부'}</div><div class="tags" style="margin-top:14px"><span class="tag red">경기 스트레스 ${num(entry.score,1)}점</span><span class="tag">최고 기대승점 ${pct(Math.max(...p))}</span>${entry.tags.map(t=>`<span class="tag">${esc(t)}</span>`).join('')}</div><div class="chart-wrap">${chart(g,team)}</div><p class="chart-note" id="chart-caption">선을 따라 움직이면 당시 상황을 볼 수 있어요 · 기대승점 = 승리 1점 + 무승부 0.5점의 모형 기대값</p><div class="section-title"><h2>희망이 꺾인 순간</h2><p>단일 타석 기대승점 하락 TOP 5</p></div><div class="panel">${drops.map(({r,delta})=>`<div class="moment-button"><span class="date">${r[1]}회${r[2]?'말':'초'}</span><span><strong>${esc(r[6])} · ${esc(r[8])}</strong><small>투수 ${esc(r[7])} · 홈 ${r[3]} : 원정 ${r[4]}</small></span><span class="loss">${num(delta*100,1)}<small>기대승점 %p</small></span></div>`).join('')}</div><p class="tiny muted">경기 점수 구성: 유리함 회수 ${num(entry.surrender,1)}점 + 추격 후 회수 ${num(entry.recovery,1)}점 + 반복 회수 ${num(Math.min(entry.cycles/2,1)*10,1)}점${entry.lost?'':' · 승리·무승부의 희망고문 패배 점수는 0점'}</p><div class="dialog-actions"><a href="${esc(g.sourceUrl)}" target="_blank" rel="noopener noreferrer">원 경기 기록 보기 ↗</a><button id="copy-link">이 경기 링크 복사</button><span id="copy-status" role="status"></span></div>`;
    const svg=$('#we-chart');
    svg.addEventListener('pointermove',e=>{const box=svg.getBoundingClientRect(),xx=(e.clientX-box.left)/box.width*820;const i=Math.max(0,Math.min(g.points.length-1,Math.round((xx-48)/744*(g.points.length-1))));const r=g.points[i];$('#chart-caption').textContent=`${r[1]}회${r[2]?'말':'초'} · ${r[6]} ${r[8]} · 홈 ${r[3]} : 원정 ${r[4]} · ${name(team)} 기대승점 ${pct(p[i])}`;});
    $('#copy-link').addEventListener('click',async()=>{try{await navigator.clipboard.writeText(location.href);$('#copy-status').textContent='복사했어요';}catch{$('#copy-status').textContent='주소창의 링크를 복사해주세요';}});
  } catch(e) { if(request===gameRequest)$('#game-content').innerHTML=`<div class="empty">${esc(e.message)}<br>닫고 다시 시도해주세요</div>`; }
}

function renderMethod() {
  const audits=meta.coverage.filter(c=>meta.seasons.includes(c.year));
  $('#method-content').innerHTML=`<div class="method-grid"><article><h3>구단 점수 · 잘못한 점수가 아닙니다</h3><p>패배 경기의 후반 유리함 회수(최대 65점), 열세에서 추격한 뒤 패배(최대 25점), 6회 이후 기대승점 65%→40% 이하의 반복 회수(최대 10점)를 합칩니다. 같은 플레이를 접전·불펜·수비 점수로 반복 가산하지 않습니다.</p><p>구단 대표 점수는 패배 경기 평균에 리그 평균 10경기분을 더해 보정합니다. 경기 수와 누적 손실은 별도로 표시합니다. 경기 시작의 50%는 희망 확보로 세지 않습니다.</p></article><article><h3>선수 지수 · 기회와 역할을 구분합니다</h3><p>접전(3점 차 이내)의 상황별 기대승점 손실에 후반·희망 가중치를 적용합니다. 타격·투구는 기회당 손실을 20기회 평균으로 보정한 뒤 2024년 롯데 동일 부문의 분위로 표시합니다. 90점은 기준 선수의 약 90%보다 높은 손실이라는 뜻입니다.</p><p>수비는 상황별 공식 실책 손실 누적값을 비교합니다. 타격·투구·수비 점수는 서로 합산하지 않습니다. 선발·불펜은 실제 해당 등판의 역할입니다.</p></article><article><h3>모형과 데이터 범위</h3><p>이닝·초말·아웃·주자·점수 차로 기대승점을 추정하는 연구용 모형입니다. 공식 WPA나 실제 팬 감정의 측정값이 아닙니다. LI는 아직 구현하지 않아 LI라고 표기하지 않습니다.</p><p>2024년은 2023년으로, 2025년은 2023~2024년으로 학습했습니다. 무승부는 0.5로 보존합니다. 연장 규정별 확률 모델 분리는 후속 보완 사항입니다.</p><p>${meta.models.map(m=>`${m.season} 시간순 검증 MSE ${num(m.expectedPointsMSE,4)} (항상 50% 기준 ${num(m.constantHalfMSE,4)})`).join('<br>')}<br>타석 간 관측은 독립이 아니며 세밀한 확률 보정은 추가 검증이 필요합니다.</p></article><article><h3>검산과 제외한 기록</h3><p>${audits.map(c=>`${c.year}: ${c.games}경기 최종 점수 불일치 ${c.finalScoreMismatches}건 · 롯데 실책 ${c.fielding.observedErrors}/${c.officialLotteErrors}개 발생 확인 · 야수 책임 불명확 ${c.fielding.ambiguousErrors}개 제외`).join('<br>')}</p><p>타석 집계는 투구마다 반복된 결과를 한 번만 셉니다. 타석 중 주루·실책은 타석 기여에 섞일 수 있고, 수비는 실책 순간의 변화만 측정해 정상 처리 시의 가상 아웃 손실까지 포함하지 않습니다.</p><p>자료 버전 ${esc(meta.version)} · 빌드 ${esc(meta.builtAt.slice(0,10))}<br>정규시즌만 포함 · 2023년은 학습용이며 순위에 노출하지 않습니다.</p></article><article style="grid-column:1/-1"><h3>출처와 재현</h3><p>${meta.sources.map(s=>`<a href="${esc(s.url)}" target="_blank" rel="noopener noreferrer">${esc(s.name)} ↗</a> · ${esc(s.use)}${s.license?' · '+esc(s.license):''}`).join('<br>')}</p><p>투구별 공개 자료를 재집계하고 박스스코어·실책 이닝을 추가 대조했습니다. 원문 중계 문구는 공개하지 않습니다. 고정된 원천 revision과 계산 코드는 GitHub에서 확인할 수 있습니다.</p></article></div>`;
}

document.querySelectorAll('[data-tab]').forEach(b=>b.addEventListener('click',()=>{state.tab=b.dataset.tab;render();}));
$('.tabs').addEventListener('keydown',e=>{if(['ArrowLeft','ArrowRight','Home','End'].includes(e.key)){e.preventDefault();state.tab=e.key==='Home'?'teams':e.key==='End'?'players':state.tab==='teams'?'players':'teams';render();$(`#${state.tab}-tab`).focus();}});
$('#season').addEventListener('change',e=>{state.season=e.target.value;state.player=null;render();});
$('#game-dialog .close').addEventListener('click',()=>$('#game-dialog').close());
$('#game-dialog').addEventListener('click',e=>{if(e.target===$('#game-dialog')){const r=e.target.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)e.target.close();}});
$('#game-dialog').addEventListener('close',()=>{gameRequest++;updateURL({game:''});});

try {
  meta=await read('./data/meta.json');
  packs=Object.fromEntries(await Promise.all(meta.seasons.map(async y=>[String(y),await read(`./data/${y}.json`)])));
  if(!['2024','2025','all'].includes(state.season))state.season='2025';
  if(!meta.teams[state.team])state.team='LT';
  renderMethod();render();
  const initialGame=params.get('game');
  if(initialGame&&/^202[45]\d{4}[A-Z]{4}[012]202[45]$/.test(initialGame))showGame(initialGame,state.team);
}catch(e){$('#status').innerHTML=`기록을 불러오지 못했어요<br><span class="tiny">${esc(e.message)}</span><br><button id="retry">다시 불러오기</button>`;$('#retry').addEventListener('click',()=>location.reload());}
