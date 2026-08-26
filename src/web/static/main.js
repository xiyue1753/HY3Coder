const $=s=>document.querySelector(s);
let CHARTS={}, STATE={questions:[],detail:null,round:0,rounds:[]};
const VERDICT_CN={CORRECT:'正确',PROCESS_INCORRECT:'过程错误',ANSWER_INCORRECT:'答案错误',SILENT_FAILURE:'沉默失败'};
const KIND_CN={understand:'题意',approach:'思路',complexity:'复杂度',implement:'实现',selftest:'自测',derive:'推导',calc:'计算',check:'检查'};
const TYPE_CN={concept:'概念',calculation:'计算',condition:'条件',jump:'跳步',format:'格式',logic:'逻辑',boundary:'边界',complexity:'复杂度',misread:'题意误读'};

async function j(url){const r=await fetch(url);if(!r.ok)throw new Error(await r.text());return r.json()}

// ---------- 导航 ----------
document.querySelectorAll('.nav-item').forEach(el=>el.onclick=()=>{
  document.querySelectorAll('.nav-item').forEach(x=>x.classList.remove('active'));
  el.classList.add('active');
  const v=el.dataset.view;
  document.querySelectorAll('main section').forEach(s=>s.style.display='none');
  $('#view-'+v).style.display='block';$('#view-'+v).classList.add('fade');
  const titles={overview:'评估总览',detail:'单题过程回放',golden:'Golden 样本库',audit:'人工抽检',interact:'交互式解题'};
  $('#pageTitle').textContent=titles[v];
  if(v==='detail'&&!STATE.questions.length)loadQuestions();
  if(v==='golden')loadGolden();
  if(v==='audit')loadAudit();
});
function goSearch(){const q=$('#globalSearch').value.trim();if(!q)return;$('#pageTitle').textContent='单题过程回放';loadDetail(q)}

// ---------- 总览 ----------
async function loadOverview(){
  const s=await j('/api/summary');
  $('#kpiN').innerHTML=`<div class="v">${s.n}</div><div class="l">已评估题目</div>`;
  $('#kpiAns').innerHTML=`<div class="v">${s.answer_accuracy==null?'—':(s.answer_accuracy*100).toFixed(1)+'%'}</div><div class="l">答案准确率</div>`;
  $('#kpiProc').innerHTML=`<div class="v">${s.process_correctness==null?'—':(s.process_correctness*100).toFixed(1)+'%'}</div><div class="l">过程正确率</div>`;
  const sf=(s.verdict_dist||{})['SILENT_FAILURE']||0;
  $('#kpiFail').innerHTML=`<div class="v">${sf}</div><div class="l">沉默失败检出</div>`;
  // tier chart
  const tiers=Object.values(s.per_tier||{});
  if(CHARTS.tier)CHARTS.tier.destroy();
  CHARTS.tier=new Chart($('#chartTier'),{type:'bar',data:{labels:Object.keys(s.per_tier||{}),
    datasets:[{label:'过程正确率',data:tiers.map(t=>t.process_correctness),backgroundColor:'#4F6DF5',borderRadius:6},
      {label:'答案准确率',data:tiers.map(t=>t.answer_accuracy),backgroundColor:'#3DD68C',borderRadius:6}]},
    options:{responsive:true,plugins:{legend:{labels:{color:'#9AA0B4'}}},scales:{y:{min:0,max:1,ticks:{color:'#9AA0B4'}},x:{ticks:{color:'#9AA0B4'}}}}});
  const vd=Object.entries(s.verdict_dist||{});
  if(CHARTS.verdict)CHARTS.verdict.destroy();
  CHARTS.verdict=new Chart($('#chartVerdict'),{type:'doughnut',data:{labels:vd.map(x=>VERDICT_CN[x[0]]||x[0]),datasets:[{data:vd.map(x=>x[1]),backgroundColor:['#3DD68C','#FF5D5D','#FFB020','#FF7A9C']}]},
    options:{plugins:{legend:{labels:{color:'#9AA0B4'}}}}});
  const ed=Object.entries(s.error_type_dist||{});
  if(CHARTS.errors)CHARTS.errors.destroy();
  CHARTS.errors=new Chart($('#chartErrors'),{type:'polarArea',data:{labels:ed.map(x=>TYPE_CN[x[0]]||x[0]),datasets:[{data:ed.map(x=>x[1]),backgroundColor:['#4F6DF5','#7C8CF8','#3DD68C','#FFB020','#FF5D5D','#FF7A9C','#36c5f4','#9AA0B4','#a78bfa']}]},
    options:{plugins:{legend:{labels:{color:'#9AA0B4'}}}}});
  if(s.refine){
    const r=s.refine;
    $('#refineBox').innerHTML=`<div class="bar-row"><span class="lab">修正前</span><div class="bar"><i style="width:${r.before_correct*100}%"></i></div><b class="mono">${(r.before_correct*100).toFixed(0)}%</b></div>
      <div class="bar-row"><span class="lab">修正后</span><div class="bar"><i style="width:${r.after_correct*100}%;background:linear-gradient(90deg,#3DD68C,#2bb673)"></i></div><b class="mono">${(r.after_correct*100).toFixed(0)}%</b></div>
      <div class="mt-3 text-sm muted">样本 ${r.n} 题 · 收敛 ${(r.converged*100).toFixed(0)}% · 提升 ${(r.improved*100).toFixed(0)}%</div>`;
  }
  const g=await j('/api/golden');
  $('#goldenBox').innerHTML=g.slice(0,5).map(x=>`<div class="flex items-center gap-2 mb-2"><span class="tag v-SILENT_FAILURE">${TYPE_CN[x.flaw_type]||x.flaw_type}</span><span class="text-sm">${x.question.title}</span></div>`).join('')+`<div class="text-sm muted mt-2">共 ${g.length} 条 · 见 Golden 库</div>`;
}

// ---------- 单题回放 ----------
let QUIERY_STATE={offset:0, limit:100, scene:'', verdict:'', tier:'', source:'', keyword:''};
function buildQueryParams(){
  const p=new URLSearchParams({limit:String(QUIERY_STATE.limit), offset:String(QUIERY_STATE.offset)});
  if(QUIERY_STATE.scene)p.set('scene',QUIERY_STATE.scene);
  if(QUIERY_STATE.verdict)p.set('verdict',QUIERY_STATE.verdict);
  if(QUIERY_STATE.tier)p.set('tier',QUIERY_STATE.tier);
  if(QUIERY_STATE.source)p.set('source',QUIERY_STATE.source);
  if(QUIERY_STATE.keyword)p.set('keyword',QUIERY_STATE.keyword);
  return p.toString();
}
async function loadQuestions(){
  const d=await j('/api/questions?'+buildQueryParams());
  const list=d.items||[];STATE.questions=list;
  const total=d.total||0;
  // 总览下题目表格（含筛选 + 分页）
  let sec=$('#questionTable');
  if(sec)sec.remove();
  const wrap=document.createElement('div');wrap.id='questionTable';wrap.className='panel mt-5 fade';
  const opts=o=>`<option value="">全部</option>`+o;
  wrap.innerHTML=`
    <div class="flex items-center gap-2 mb-2"><h3 class="text-base font-medium">题目列表</h3>
      <span class="muted text-sm">共 ${total} 条</span></div>
    <div class="flex flex-wrap items-center gap-2 mb-3 text-sm">
      <select onchange="QUIERY_STATE.scene=this.value;QUIERY_STATE.offset=0;loadQuestions()" class="fbtn">${opts(['math','algorithm'].map(s=>`<option value="${s}" ${QUIERY_STATE.scene===s?'selected':''}>${s}</option>`).join(''))}</select>
      <select onchange="QUIERY_STATE.tier=this.value;QUIERY_STATE.offset=0;loadQuestions()" class="fbtn">${opts(['basic','medium','hard'].map(t=>`<option value="${t}" ${QUIERY_STATE.tier===t?'selected':''}>${t}</option>`).join(''))}</select>
      <select onchange="QUIERY_STATE.verdict=this.value;QUIERY_STATE.offset=0;loadQuestions()" class="fbtn">${opts(['CORRECT','PROCESS_INCORRECT','SILENT_FAILURE','ANSWER_INCORRECT','FAILED'].map(v=>`<option value="${v}" ${QUIERY_STATE.verdict===v?'selected':''}>${VERDICT_CN[v]||v}</option>`).join(''))}</select>
      <select onchange="QUIERY_STATE.source=this.value;QUIERY_STATE.offset=0;loadQuestions()" class="fbtn">${opts(['run-eval','interactive'].map(s=>`<option value="${s}" ${QUIERY_STATE.source===s?'selected':''}>${s}</option>`).join(''))}</select>
      <input class="search" style="width:160px" placeholder="搜索题号/关键词" value="${QUIERY_STATE.keyword}" onkeydown="if(event.key==='Enter'){QUIERY_STATE.keyword=this.value;QUIERY_STATE.offset=0;loadQuestions()}">
      <button class="fbtn" onclick="QUIERY_STATE.offset=0;loadQuestions()">搜索</button>
    </div>
    <table class="dt"><thead><tr><th>题号</th><th>场景</th><th>难度</th><th>判定</th><th>来源</th><th>答案</th><th>置信度</th><th>错误类型</th></tr></thead>
    <tbody>${list.map(x=>`<tr onclick="openDetail('${x.question_id}')"><td class="mono">${x.question_id}</td><td>${x.scene}</td><td>${x.difficulty}</td>
      <td><span class="tag v-${x.verdict}">${VERDICT_CN[x.verdict]||x.verdict}</span></td>
      <td class="muted">${x.source||'—'}</td>
      <td>${x.answer_correct==null?'—':(x.answer_correct?'✓':'✗')}</td><td class="mono">${(x.confidence||0).toFixed(2)}</td>
      <td class="muted">${(x.error_types||[]).map(t=>TYPE_CN[t]||t).join(', ')||'—'}</td></tr>`).join('')||'<tr><td colspan="8" class="muted">无匹配记录</td></tr>'}</tbody></table>
    <div class="flex items-center gap-2 mt-3 text-sm">
      <button class="fbtn" onclick="QUIERY_STATE.offset=Math.max(0,QUIERY_STATE.offset-QUIERY_STATE.limit);loadQuestions()" ${QUIERY_STATE.offset<=0?'disabled':''}>上一页</button>
      <span class="muted">第 ${Math.floor(QUIERY_STATE.offset/QUIERY_STATE.limit)+1} 页</span>
      <button class="fbtn" onclick="QUIERY_STATE.offset+=QUIERY_STATE.limit;loadQuestions()" ${QUIERY_STATE.offset+QUIERY_STATE.limit>=total?'disabled':''}>下一页</button>
      <span class="muted">每页 ${QUIERY_STATE.limit} 条</span>
    </div>`;
  $('#view-overview').appendChild(wrap);
}
function openDetail(qid){document.querySelectorAll('.nav-item').forEach(x=>x.classList.remove('active'));
  document.querySelectorAll('main section').forEach(s=>s.style.display='none');
  $('#view-detail').style.display='block';$('#pageTitle').textContent='单题过程回放';loadDetail(qid)}
async function loadDetail(qid){
  const d=await j('/api/questions/'+qid);STATE.detail=d;
  const q=d.question, e=d.eval;
  $('#dQuestion').innerHTML=`<div class="text-sm">${q?q.prompt:d.question_id}</div>
    <div class="flex items-center gap-2 mt-3"><span class="tag v-${e.verification.verdict}">${VERDICT_CN[e.verification.verdict]}</span>
    <span class="tag">${e.scene} · ${e.difficulty}</span>${e.answer_correct?'<span class="tag" style="color:var(--ok)">答案正确</span>':'<span class="tag" style="color:var(--bad)">答案存疑</span>'}</div>`;
  $('#dMeta').innerHTML=`<div class="muted text-sm">标准答案：<span class="mono">${q?q.standard_answer:'—'}</span></div>
    <div class="muted text-sm mt-1">模型答案：<span class="mono">${e.answer.final_answer||'—'}</span></div>
    <div class="muted text-sm mt-1">测试通过率：${e.test_pass_rate==null?'—':e.test_pass_rate}</div>
    <div class="muted text-sm mt-1">置信度：<span class="mono">${e.verification.confidence.toFixed(2)}</span> · 仲裁：${e.verification.arbiter}</div>`;
  // findings
  $('#dFindings').innerHTML=(e.verification.findings||[]).map(f=>`<div class="finding"><b>${TYPE_CN[f.error_type]||f.error_type}</b> · 第${f.step_id??'—'}步：${f.detail}</div>`).join('');
  // refine rounds
  const r=d.refine;STATE.rounds=[];
  if(r&&r.rounds&&r.rounds.length){
    const tabs=['第1轮'].concat(r.rounds.map(x=>'第'+(x.round_no+1)+'轮'));
    // 轮1=initial 判定后；rounds[0]=第2轮…
    STATE.rounds=[{answer:null,v:r.initial,label:'初始判定'},...r.rounds.map(x=>({answer:x.revised_answer,v:x.verification,label:'轮'+x.round_no}))];
    $('#roundTabs').innerHTML=STATE.rounds.map((x,i)=>`<span class="round-tab ${i===STATE.rounds.length-1?'active':''}" onclick="showRound(${i})">${x.label}</span>`).join('');
    STATE.round=STATE.rounds.length-1;
  }else{$('#roundTabs').innerHTML='';STATE.round=0;STATE.rounds=[{answer:e.answer,v:e.verification,label:'最终'}];STATE.round=0}
  renderSteps();
}
function showRound(i){STATE.round=i;document.querySelectorAll('.round-tab').forEach((x,idx)=>x.classList.toggle('active',idx===i));renderSteps()}
function renderSteps(){
  const x=STATE.rounds[STATE.round];const ans=x.answer||STATE.detail.eval.answer;
  const errIds=new Set((x.v.findings||[]).map(f=>f.step_id).filter(v=>v!=null));
  $('#dSteps').innerHTML=(ans.steps||[]).map(s=>`<div class="step-card ${errIds.has(s.id)?'err':x.v.verdict==='CORRECT'?'ok':''}" title="依赖：${s.deps.join(',')||'无'}">
    <div class="k">${s.kind} · STEP ${s.id}</div><div class="mt-1">${s.content}</div>
    <div class="mt-1 text-sm" style="color:var(--pri2)">→ ${s.conclusion}</div></div>`).join('')||'<div class="muted">无步骤</div>';
  const v=x.v;const errs=v.findings||[];
  const note=errs.length?`<div class="mt-2 finding"><b>验证器检出 ${errs.length} 处错误（${VERDICT_CN[v.verdict]}）</b></div>`:`<div class="mt-2 text-sm" style="color:var(--ok)">验证判定：${VERDICT_CN[v.verdict]} · 置信度 ${v.confidence.toFixed(2)}</div>`;
  const ex=$('#verdictNote');if(ex)ex.remove();
  const el=document.createElement('div');el.id='verdictNote';el.innerHTML=note;$('#dFindings').after(el);
}

// ---------- Golden ----------
async function loadGolden(){
  const g=await j('/api/golden');
  $('#goldenList').innerHTML=g.map(x=>`<div class="panel mb-4" style="border-left:3px solid var(--warn)">
    <div class="flex items-center gap-2 mb-2">
      <span class="tag v-SILENT_FAILURE">${TYPE_CN[x.flaw_type]||x.flaw_type}</span>
      <b>${x.question.title}</b><span class="tag">${x.question.scene}</span></div>
    <div class="text-sm muted mb-2">${x.question.prompt}</div>
    <div class="text-sm muted mb-2">标准答案：<span class="mono">${x.question.standard_answer}</span> · 陷阱答案：<span class="mono">${x.flaw_answer.final_answer}</span></div>
    <div class="text-sm" style="color:var(--warn)">构造说明：${x.construction_note}</div>
    <div class="mt-2"><details><summary class="text-sm muted cursor-pointer">查看陷阱过程</summary>
      ${(x.flaw_answer.steps||[]).map(s=>`<div class="step-card err" style="margin:6px 0"><div class="k">${s.kind} · STEP ${s.id}</div><div>${s.content}</div><div class="text-sm" style="color:var(--pri2)">→ ${s.conclusion}</div></div>`).join('')}
    </details></div></div>`).join('');
}

// ---------- 抽检 ----------
async function loadAudit(){
  const a=await j('/api/audit');
  $('#auditTable').innerHTML=a.length?`<table class="dt"><thead><tr><th>题号</th><th>人工判定</th><th>错误步骤</th><th>误报</th><th>备注</th></tr></thead>
    <tbody>${a.map(x=>`<tr><td class="mono">${x.question_id}</td><td>${x.verdict_human||'待标注'}</td>
    <td class="mono">${x.error_step_id??'—'}</td><td>${x.is_false_positive?'是':'否'}</td><td class="muted">${x.note||''}</td></tr>`).join('')}</tbody></table>`
    :'<div class="muted">暂无抽检记录，运行 <span class="mono">python -m src.cli audit --results data/outputs/eval_math.jsonl</span> 生成标注模板</div>';
}

// ---------- 交互式解题 ----------
// ---------- 交互式解题：辅助函数 ----------
// 用 marked 渲染 Markdown + KaTeX 渲染 $$..$$ 与 $..$ 公式
function renderMath(text){
  if(!text) return '';
  let html;
  try { html = (window.marked ? marked.parse(text) : escapeHtml(text)); }
  catch(e){ html = escapeHtml(text); }
  if (window.katex) {
    // 行内/行间 LaTeX：$$...$$ 与 $...$
    html = html.replace(/\$\$([\s\S]+?)\$\$/g, (m, exp) => {
      try { return katex.renderToString(exp, {displayMode:true, throwOnError:false}); }
      catch(e){ return m; }
    });
    html = html.replace(/\$([^$\n]+?)\$/g, (m, exp) => {
      try { return katex.renderToString(exp, {displayMode:false, throwOnError:false}); }
      catch(e){ return m; }
    });
  }
  return html;
}
function escapeHtml(s){return String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}

// 解析算法输入输出样例：每组"输入:\n…\n输出:\n…"，多组空行分隔
function parseSamples(text){
  const out=[];
  if(!text) return out;
  const blocks = text.trim().split(/\n\s*\n/);
  for(const b of blocks){
    const m = b.match(/^\s*输入\s*[:：]\s*([\s\S]*?)\s*输出\s*[:：]\s*([\s\S]*?)\s*$/);
    if(m && (m[1].trim() || m[2].trim())){
      out.push({input:m[1].trim(), output:m[2].trim()});
    }
  }
  return out;
}

// 场景切换：数学 / 算法不同输入区；实时预览题目渲染
function switchInteractScene(){
  const isAlgo = $('#iScene').value === 'algorithm';
  $('#iMathInput').style.display = isAlgo ? 'none' : 'block';
  $('#iAlgoInput').style.display = isAlgo ? 'block' : 'none';
}
// 数学题目实时预览（Markdown + LaTeX）
function previewPrompt(){
  const txt = $('#iPrompt').value;
  const el = $('#iPromptPreview');
  if(txt.trim()){ el.style.display='block'; el.innerHTML = renderMath(txt); }
  else { el.style.display='none'; el.innerHTML=''; }
}
// 样例实时预览
function previewSamples(){
  const txt = $('#iSamples').value;
  const el = $('#iSamplesPreview');
  const list = parseSamples(txt);
  if(list.length){ el.style.display='block'; el.innerHTML='已解析 '+list.length+' 组样例：'+
    list.map((s,i)=>`<div class="mt-1"><b>样例${i+1}</b> 输入：<span class="mono">${escapeHtml(s.input)}</span> → 输出：<span class="mono">${escapeHtml(s.output)}</span></div>`).join(''); }
  else { el.style.display='none'; el.innerHTML=''; }
}
document.addEventListener('input', e=>{
  if(e.target && e.target.id==='iPrompt') previewPrompt();
  if(e.target && e.target.id==='iSamples') previewSamples();
});

async function interact(){
  const btn=$('#iGo');btn.disabled=true;btn.textContent='求解中…';
  $('#iResult').innerHTML='<div class="muted">正在调用 Hy3…</div>';
  try{
    const scene=$('#iScene').value;
    // 收集入参：数学用 iPrompt/iAnswer；算法用 iPrompt2 + 解析样例 + 参考解
    const prompt = scene==='algorithm' ? $('#iPrompt2').value : $('#iPrompt').value;
    const body = { scene, prompt, refine:$('#iRefine').checked };
    if(scene==='algorithm'){
      const samples=parseSamples($('#iSamples').value);
      body.samples = samples;
      if($('#iRefSol').value) body.answer = $('#iRefSol').value;
    } else {
      if($('#iAnswer').value) body.answer = $('#iAnswer').value;
    }
    const r=await fetch('/api/interact',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    const d=await r.json();
    if(!r.ok)throw new Error(d.detail||'failed');
    const rec=d.eval||d.refine;const v=rec.verification;
    const findings=v.findings||[];
    const errIds=new Set(findings.map(f=>f.step_id).filter(x=>x!=null));
    // 头部：判定 + 模式 + 耗时/调用次数
    let html=`<div class="flex items-center gap-2 mb-2"><span class="tag v-${v.verdict}">${VERDICT_CN[v.verdict]}</span>
      <span class="muted">${d.mode==='refine'?'修正闭环':'一次性评估'}</span>
      <span class="text-sm muted">耗时 ${d.elapsed??'—'}s · 调用 ${d.cost_calls??'—'} 次</span></div>`;
    if(d.mode==='refine'){html+=`<div class="text-sm muted mb-2">初始判定：${VERDICT_CN[d.refine.initial.verdict]} → 最终：${VERDICT_CN[v.verdict]}（${d.refine.rounds.length} 轮修正）</div>`;}
    // 沙盒执行结果（算法场景测试通过率 / 错误）
    if(d.exec){const ex=d.exec;
      html+=`<div class="mt-2 mb-2 text-sm">沙盒执行：
        <span style="color:${ex.test_pass_rate>=1?'var(--ok)':'var(--warn)'}">${ex.test_pass_rate==null?'—':Math.round(ex.test_pass_rate*100)+'% 通过'}</span>
        ${ex.error?`<span class="finding" style="margin-left:6px">${ex.error}</span>`:''}</div>`;}
    // 步骤卡片：按 findings 高亮错误步骤，Markdown/LaTeX 渲染
    html+=(rec.answer.steps||[]).map(s=>`<div class="step-card ${errIds.has(s.id)?'err':v.verdict==='CORRECT'?'ok':''}" title="依赖：${(s.deps||[]).join(',')||'无'}">
      <div class="k">${s.kind} · STEP ${s.id}${errIds.has(s.id)?' · 检出错误':''}</div>
      <div class="mt-1">${renderMath(s.content)}</div><div class="mt-1 text-sm" style="color:var(--pri2)">→ ${renderMath(s.conclusion)}</div></div>`).join('')
      || '<div class="muted">无步骤</div>';
    // 算法场景：展示模型生成的代码
    if(scene==='algorithm' && rec.answer.code){
      html+=`<div class="mt-3"><details><summary class="text-sm muted cursor-pointer">查看模型生成代码</summary>
        <pre class="mono" style="background:var(--input-bg);border:1px solid var(--line);border-radius:8px;padding:10px;overflow:auto;font-size:12px;white-space:pre-wrap">${escapeHtml(rec.answer.code)}</pre></details></div>`;
    }
    html+=`<div class="mt-2 text-sm muted">最终答案：<span class="mono">${rec.answer.final_answer}</span></div>`;
    // 错误定位 findings
    html+=`<div id="iFindings"></div>`;
    $('#iResult').innerHTML=html;
    $('#iFindings').innerHTML=findings.length
      ? findings.map(f=>`<div class="finding"><b>${TYPE_CN[f.error_type]||f.error_type}</b> · 第${f.step_id??'—'}步：${f.detail}</div>`).join('')
      : `<div class="text-sm muted mt-2">未检出过程错误 · 置信度 ${(v.confidence??0).toFixed(2)}</div>`;
  }catch(e){$('#iResult').innerHTML=`<div class="finding"><b>出错：</b>${e.message}</div>`}
  finally{btn.disabled=false;btn.textContent='开始求解'}
}

// ---------- 主题切换（仿 Hy_APP：data-theme + localStorage 持久化） ----------
function applyTheme(t){
  document.documentElement.dataset.theme = t;
  // 图标随主题切换：暗色显示太阳（切亮），亮色显示月亮（切暗）
  const sun = document.getElementById("icoSun");
  const moon = document.getElementById("icoMoon");
  if (sun) sun.style.display = t === "dark" ? "inline" : "none";
  if (moon) moon.style.display = t === "light" ? "inline" : "none";
  try { localStorage.setItem("rex_theme", t); } catch(e){}
}
function toggleTheme(){
  const cur = document.documentElement.dataset.theme === "light" ? "light" : "dark";
  applyTheme(cur === "dark" ? "light" : "dark");
}
document.addEventListener("DOMContentLoaded", ()=>{
  const btn = document.getElementById("themeBtn");
  if (btn) btn.addEventListener("click", toggleTheme);
  try {
    const saved = localStorage.getItem("rex_theme");
    if (saved) applyTheme(saved);
    else applyTheme("dark");   // 默认暗色，仿 Hy_APP
  } catch(e){}
});

// ---------- init ----------
loadOverview();
