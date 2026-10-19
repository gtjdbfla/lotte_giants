const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const nodes = new Map();
const sortButtons = ['score','total'].map(sort=>({dataset:{sort},addEventListener(_,callback){this.click=callback;}}));
function node(selector) {
  if(!nodes.has(selector)) nodes.set(selector, {innerHTML:'',setAttribute(){},addEventListener(){},querySelectorAll(s){return s==='[data-sort]'?sortButtons:[];}});
  return nodes.get(selector);
}
const context = vm.createContext({document:{querySelector:node},location:{search:''},URLSearchParams});
const source = fs.readFileSync('site/app.js','utf8').split("document.querySelectorAll('[data-tab]')")[0];
vm.runInContext(source,context);
context.snapshot = JSON.parse(fs.readFileSync('site/data/2026.json','utf8'));
vm.runInContext("packs={'2026':snapshot};state.season='2026';state.tab='players';render=renderPlayers;",context);
for(const role of ['batting','fielding','pitching','starter','reliever']) {
  context.roleUnderTest=role;
  vm.runInContext("state.mode=['starter','reliever'].includes(roleUnderTest)?'pitching':roleUnderTest;state.role=roleUnderTest;state.sort='score';state.player=null;renderPlayers();",context);
  sortButtons[1].click();
  const eligible=context.snapshot.players[role].filter(p=>p.eligible);
  const winner=[...eligible].sort((a,b)=>b.total-a.total)[0];
  assert.equal(vm.runInContext('state.player',context),winner.id);
  assert.match(node('#players-panel').innerHTML,/가중 %p/);
  assert.match(node('#players-panel').innerHTML,/누적 스트레스 순/);
  sortButtons[0].click();
  assert.match(node('#players-panel').innerHTML,/꼴데력 지수 순/);
  assert.match(node('#players-panel').innerHTML,/<small>\/ 100<\/small>/);
}
console.log('Player metric switching: 5 roles passed');
