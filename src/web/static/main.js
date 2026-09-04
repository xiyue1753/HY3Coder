const $=s=>document.querySelector(s);
let CHARTS={}, STATE={questions:[],detail:null,round:0,rounds:[]};
const VERDICT_CN={CORRECT:'正确',PROCESS_INCORRECT:'过程错误',ANSWER_INCORRECT:'答案错误',SILENT_FAILURE:'沉默失败'};
const KIND_CN={understand:'题意',approach:'思路',complexity:'复杂度',implement:'实现',selftest:'自测'};
const TYPE_CN={misread:'题意误读',concept:'概念',calculation:'计算',missing_condition:'条件遗漏',jump:'跳步',format:'格式',logic:'逻辑',boundary:'边界',complexity:'复杂度',other:'其他'};

async function j(url){const r=await fetch(url);if(!r.ok)throw new Error(await r.text());return r.json()}

// ---------- 导航 ----------
document.querySelectorAll('.nav-item').forEach(el=>{
  if(el.tagName==='A')return;   // 外链（如 /browse）交给浏览器默认跳转
  el.onclick=()=>{
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
  };
});

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
  // 渲染到单题回放页左侧列表（紧凑列表：题号+判定+场景）
  const el=$('#dList');
  if(!el)return;
  const opts=o=>`<option value="">全部</option>`+o;
  el.innerHTML=`
    <div class="flex flex-wrap items-center gap-2 mb-2 text-sm">
      <span class="muted">共 ${total} 条</span>
      <select onchange="QUIERY_STATE.scene=this.value;QUIERY_STATE.offset=0;loadQuestions()" class="fbtn">${opts(['algorithm'].map(s=>`<option value="${s}" ${QUIERY_STATE.scene===s?'selected':''}>${s}</option>`).join(''))}</select>
      <select onchange="QUIERY_STATE.tier=this.value;QUIERY_STATE.offset=0;loadQuestions()" class="fbtn">${opts(['basic','medium','hard'].map(t=>`<option value="${t}" ${QUIERY_STATE.tier===t?'selected':''}>${t}</option>`).join(''))}</select>
      <select onchange="QUIERY_STATE.verdict=this.value;QUIERY_STATE.offset=0;loadQuestions()" class="fbtn">${opts(['CORRECT','PROCESS_INCORRECT','SILENT_FAILURE','ANSWER_INCORRECT','FAILED'].map(v=>`<option value="${v}" ${QUIERY_STATE.verdict===v?'selected':''}>${VERDICT_CN[v]||v}</option>`).join(''))}</select>
      <select onchange="QUIERY_STATE.source=this.value;QUIERY_STATE.offset=0;loadQuestions()" class="fbtn">${opts(['run-eval','interactive'].map(s=>`<option value="${s}" ${QUIERY_STATE.source===s?'selected':''}>${s}</option>`).join(''))}</select>
    </div>
    <div style="max-height:260px;overflow-y:auto;display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:4px">
      ${list.map(x=>`<div class="ditem" onclick="openDetail('${x.question_id}')">
        <span class="mono" style="font-size:12px">${x.question_id}</span>
        <span class="tag v-${x.verdict}">${VERDICT_CN[x.verdict]||x.verdict}</span>
        <span class="muted" style="font-size:11px">${x.scene}/${x.difficulty}</span>
      </div>`).join('')||'<div class="muted">无匹配记录</div>'}
    </div>
    <div class="flex items-center gap-2 mt-2 text-sm">
      <button class="fbtn" onclick="QUIERY_STATE.offset=Math.max(0,QUIERY_STATE.offset-QUIERY_STATE.limit);loadQuestions()" ${QUIERY_STATE.offset<=0?'disabled':''}>上一页</button>
      <span class="muted">第 ${Math.floor(QUIERY_STATE.offset/QUIERY_STATE.limit)+1} 页</span>
      <button class="fbtn" onclick="QUIERY_STATE.offset+=QUIERY_STATE.limit;loadQuestions()" ${QUIERY_STATE.offset+QUIERY_STATE.limit>=total?'disabled':''}>下一页</button>
    </div>`;
}
// 单题回放页搜索：题号/关键词 → 定位并显示详情
async function detailSearchGo(){
  const q=$('#detailSearch').value.trim();
  if(!q)return;
  QUIERY_STATE.keyword=q;QUIERY_STATE.offset=0;
  await loadQuestions();
  // 若精确命中某题，直接打开详情
  const hit=STATE.questions.find(x=>x.question_id.toLowerCase()===q.toLowerCase());
  if(hit)openDetail(hit.question_id);
}
function openDetail(qid){document.querySelectorAll('.nav-item').forEach(x=>x.classList.remove('active'));
  document.querySelectorAll('main section').forEach(s=>s.style.display='none');
  $('#view-detail').style.display='block';$('#pageTitle').textContent='单题过程回放';loadDetail(qid)}
async function loadDetail(qid){
  const d=await j('/api/questions/'+qid);STATE.detail=d;
  const q=d.question, e=d.eval;
  $('#dQuestion').innerHTML=`<div class="text-sm md-bound">${q?renderMath(q.prompt):d.question_id}</div>
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
  $('#dSteps').innerHTML=`<div class="md-bound" style="max-height:460px">${(ans.steps||[]).map(s=>`<div class="step-card ${errIds.has(s.id)?'err':x.v.verdict==='CORRECT'?'ok':''}" title="依赖：${s.deps.join(',')||'无'}">
    <div class="k">${s.kind} · STEP ${s.id}</div><div class="mt-1">${renderMath(s.content)}</div>
    <div class="mt-1 text-sm" style="color:var(--pri2)">→ ${renderMath(s.conclusion)}</div></div>`).join('')||'<div class="muted">无步骤</div>'}
    </div>`;
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
  const meta=await j('/api/meta');
  const cmd=meta.audit_command||'python -m src.cli audit --results <正式评测文件>';
  $('#auditTable').innerHTML=a.length?`<table class="dt"><thead><tr><th>题号</th><th>人工判定</th><th>错误步骤</th><th>误报</th><th>备注</th></tr></thead>
    <tbody>${a.map(x=>`<tr><td class="mono">${x.question_id}</td><td>${x.verdict_human||'待标注'}</td>
    <td class="mono">${x.error_step_id??'—'}</td><td>${x.is_false_positive?'是':'否'}</td><td class="muted">${x.note||''}</td></tr>`).join('')}</tbody></table>`
    :`<div class="muted">暂无抽检记录，运行 <span class="mono">${cmd}</span> 生成标注模板</div>`;
}

// ---------- 交互式解题 ----------
// ---------- 交互式解题：辅助函数 ----------
// 用 marked 渲染 Markdown + KaTeX 渲染 $$..$$ 与 $..$ 公式。
// 顺序：先提取公式（KaTeX）用占位符保护，再对剩余文本做 marked ——
// 若先 marked 会把公式里的 < > 转义成 &lt; &gt;，KaTeX 拿到后渲染乱码。
function renderMath(text){
  if(!text) return '';
  const katexHtml = [];
  let safe = text;
  if (window.katex) {
    safe = text.replace(/\$\$([\s\S]+?)\$\$/g, (m, exp) => {
      try { katexHtml.push(katex.renderToString(exp, {displayMode:true, throwOnError:false})); }
      catch(e){ katexHtml.push(''); }
      return '\u0000K' + (katexHtml.length - 1) + '\u0000';
    }).replace(/\$([^$\n]+?)\$/g, (m, exp) => {
      try { katexHtml.push(katex.renderToString(exp, {displayMode:false, throwOnError:false})); }
      catch(e){ katexHtml.push(''); }
      return '\u0000K' + (katexHtml.length - 1) + '\u0000';
    });
  }
  let html;
  try { html = (window.marked ? marked.parse(safe) : escapeHtml(safe)); }
  catch(e){ html = escapeHtml(safe); }
  html = html.replace(/\u0000K(\d+)\u0000/g, (m, i) => katexHtml[+i] || '');
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
  if(e.target && e.target.id==='iSamples') previewSamples();
});

// 阶段到前端展示文案/顺序（eval 与 refine 共用前缀）
const PHASE_PILLS_EVAL=['solve','answer','execute','static','verify'];
const PHASE_PILLS_REFINE=['solve','answer','verify','revise','verify'];
const PHASE_CN={
  solve:'求解', answer:'已生成过程', execute:'沙盒执行', static:'静态校验',
  verify:'过程评估', revise:'修正', done:'完成'
};
function renderInterimAnswer(ans){
  const body=$('#iResultBody');
  if(!ans)return;
  const steps=(ans.steps)||[];
  body.style.alignItems='stretch';body.style.justifyContent='flex-start';body.style.display='block';
  body.innerHTML=`<div class="flex items-center gap-2 mb-2"><span class="tag" style="color:var(--pri)">解答过程已生成</span>
    <span class="muted text-sm">等待过程评估完成，最终判定将更新于此</span></div>
    ${steps.map((s,i)=>`<div class="step-card step-in" style="animation-delay:${i*0.12}s" title="依赖：${(s.deps||[]).join(',')||'无'}">
      <div class="k">${KIND_CN[s.kind]||s.kind} · STEP ${s.id}</div>
      <div class="mt-1">${renderMath(s.content)}</div>
      <div class="mt-1 text-sm" style="color:var(--pri2)">→ ${renderMath(s.conclusion)}</div></div>`).join('')||'<div class="muted">无步骤</div>'}`;
  if(ans.code){
    const el=document.createElement('details');
    el.style.marginTop='10px';
    el.innerHTML=`<summary class="text-sm muted cursor-pointer">查看模型生成代码</summary>
      <pre class="mono" style="background:var(--input-bg);border:1px solid var(--line);border-radius:8px;padding:10px;overflow:auto;font-size:12px;white-space:pre-wrap">${escapeHtml(ans.code)}</pre>`;
    body.appendChild(el);
  }
}
function renderFinalResult(d){
  const body=$('#iResultBody');
  body.style.alignItems='stretch';body.style.justifyContent='flex-start';body.style.display='block';
  // 统一视图模型：eval 与 refine 返回结构不同，按模式分派
  let verdict, findings, answer, initialVerdict=null, roundCount=0;
  if(d.mode==='refine'){
    const rf=d.refine;
    if(!rf)throw new Error('refine 响应缺失');
    verdict=rf.final; findings=(rf.final&&rf.final.findings)||[];
    initialVerdict=(rf.initial&&rf.initial.verdict)||null;
    roundCount=(rf.rounds||[]).length;
    const last=rf.rounds&&rf.rounds.length?rf.rounds[rf.rounds.length-1]:null;
    answer=last?last.revised_answer:(rf.error?null:null);
    if(!answer&&rf.error)throw new Error('修正失败：'+rf.error);
  }else{
    const ev=d.eval;
    if(!ev)throw new Error('eval 响应缺失');
    verdict=ev.verification; findings=(verdict&&verdict.findings)||[];
    answer=ev.answer;
  }
  const steps=(answer&&answer.steps)||[];
  const errIds=new Set(findings.map(f=>f.step_id).filter(x=>x!=null));
  let html=`<div class="flex items-center gap-2 mb-2"><span class="tag v-${verdict.verdict}">${VERDICT_CN[verdict.verdict]}</span>
    <span class="muted">${d.mode==='refine'?'修正闭环':'一次性评估'}</span>
    <span class="text-sm muted">耗时 ${d.elapsed??'—'}s · 调用 ${d.cost_calls??'—'} 次</span></div>`;
  if(d.mode==='refine'){html+=`<div class="text-sm muted mb-2">初始判定：${VERDICT_CN[initialVerdict]||'—'} → 最终：${VERDICT_CN[verdict.verdict]}（${roundCount} 轮修正）</div>`;}
  if(d.exec){const ex=d.exec;
    html+=`<div class="mt-2 mb-2 text-sm">沙盒执行：
      <span style="color:${ex.test_pass_rate>=1?'var(--ok)':'var(--warn)'}">${ex.test_pass_rate==null?'—':Math.round(ex.test_pass_rate*100)+'% 通过'}</span>
      ${ex.error?`<span class="finding" style="margin-left:6px">${ex.error}</span>`:''}</div>`;}
  html+=steps.map((s,i)=>`<div class="step-card step-in ${errIds.has(s.id)?'err':verdict.verdict==='CORRECT'?'ok':''}" style="animation-delay:${i*0.08}s" title="依赖：${(s.deps||[]).join(',')||'无'}">
    <div class="k">${KIND_CN[s.kind]||s.kind} · STEP ${s.id}${errIds.has(s.id)?' · 检出错误':''}</div>
    <div class="mt-1">${renderMath(s.content)}</div><div class="mt-1 text-sm" style="color:var(--pri2)">→ ${renderMath(s.conclusion)}</div></div>`).join('')
    || '<div class="muted">无步骤</div>';
  if(answer && answer.code){
    html+=`<div class="mt-3"><details><summary class="text-sm muted cursor-pointer">查看模型生成代码</summary>
      <pre class="mono" style="background:var(--input-bg);border:1px solid var(--line);border-radius:8px;padding:10px;overflow:auto;font-size:12px;white-space:pre-wrap">${escapeHtml(answer.code)}</pre></details></div>`;
  }
  html+=`<div class="mt-2 text-sm muted">最终答案：<span class="mono">${(answer&&answer.final_answer)||'—'}</span></div>`;
  html+=`<div id="iFindings"></div>`;
  body.innerHTML=html;
  const fEl=body.querySelector('#iFindings');
  if(fEl)fEl.innerHTML=findings.length
    ? findings.map(f=>`<div class="finding"><b>${TYPE_CN[f.error_type]||f.error_type}</b> · 第${f.step_id??'—'}步：${f.detail}</div>`).join('')
    : `<div class="text-sm muted mt-2">未检出过程错误 · 置信度 ${(verdict.confidence??0).toFixed(2)}
        <span class="mono" title="置信度 = 验证器对判定结果的自评确信度（0~1）：由 V1/V2 两视角独立审查后合并；同判取较高置信度，分歧则经仲裁决定。数值来自验证器，非统计置信区间。" style="cursor:help;border-bottom:1px dotted var(--line)">ⓘ</span>
        <span class="muted">仲裁：${verdict.arbiter||'—'}</span>
      </div>`;
}
function resetResultArea(){
  UI_STAGE={mode:'eval', pills:null, cursor:-1};
  const body=$('#iResultBody');
  body.style.alignItems='center';body.style.justifyContent='center';
  body.innerHTML='结果将显示在这里';
  $('#iProgress').style.display='none';
  $('#iProgressSteps').innerHTML='';
  $('#iProgressElapsed').textContent='';
  const spin=$('#iProgress .spin'); if(spin)spin.style.display='inline-block';
  const mark=$('#iProgressMark'); if(mark)mark.style.display='none';
}
// 阶段推进状态：记录 refine 的轮次循环，保证徽章连续点亮
let UI_STAGE={mode:'eval', pills:null, cursor:-1, render:0};
function phaseIndex(phase, mode){
  const pills=mode==='refine'?PHASE_PILLS_REFINE:PHASE_PILLS_EVAL;
  // solve/answer/execute/static/verify 及 revise-N/verify-N 归一化到 pills 下标
  const norm=phase.replace(/-\d+$/,'');
  const mapRefine={solve:0,answer:1,verify:2,revise:3}; // verify 归一后可能回跳（轮次）
  const mapEval={solve:0,answer:1,execute:2,static:3,verify:4};
  const map=mode==='refine'?mapRefine:mapEval;
  if(phase==='verify'||phase==='verify-1'||phase==='verify-2'||phase==='verify-3')
    return mode==='refine'?2:4;
  if(map[norm]!==undefined)return map[norm];
  return -1;
}
function advancePhaseUI(phase, mode, elapsed){
  UI_STAGE.mode=mode;
  $('#iProgress').style.display='block';
  const idx=phaseIndex(phase, mode);
  if(idx>=0)UI_STAGE.cursor=Math.max(UI_STAGE.cursor, idx);
  $('#iProgressMsg').textContent='阶段：'+ (PHASE_CN[phase.replace(/-\d+$/,'')]||phase.replace(/-\d+$/,''))+(/-?\d+$/.test(phase)?'（第'+phase.split('-')[1]+'轮）':'');
  if(elapsed)$('#iProgressElapsed').textContent=elapsed+'s';
  renderPhasePills(mode);
}
function renderPhasePills(mode){
  const pills=mode==='refine'?PHASE_PILLS_REFINE:PHASE_PILLS_EVAL;
  $('#iProgressSteps').innerHTML=pills.map((p,i)=>{
    const cls=i<UI_STAGE.cursor?'phase-pill done':(i===UI_STAGE.cursor?'phase-pill active':'phase-pill');
    let label=PHASE_CN[p]||p;
    if(p==='revise'&&mode==='refine')label='修正';
    return `<span class="${cls}">${label}</span>`;
  }).join('');
}
function setPhaseUI(phase, mode, elapsed){
  UI_STAGE.mode=mode;
  $('#iProgress').style.display='block';
  $('#iProgressMsg').textContent=phase==='done'?'评估完成':(PHASE_CN[phase]?('阶段：'+PHASE_CN[phase]):phase);
  if(elapsed)$('#iProgressElapsed').textContent=elapsed+'s';
  // done/failed：停止转圈，改为完成图标
  const spin=$('#iProgress .spin');
  if(spin)spin.style.display=(phase==='done'||phase==='failed')?'none':'inline-block';
  const mark=$('#iProgressMark');
  if(mark){
    mark.style.display=(phase==='done'||phase==='failed')?'inline-flex':'none';
    mark.style.color=phase==='done'?'var(--ok)':'var(--bad)';
    mark.textContent=phase==='done'?'✓':'✕';
  }
  if(phase==='done')UI_STAGE.cursor=(mode==='refine'?PHASE_PILLS_REFINE:PHASE_PILLS_EVAL).length;
  renderPhasePills(mode);
}
async function interact(){
  const btn=$('#iGo');btn.disabled=true;btn.textContent='求解中…';
  resetResultArea();
  const scene='algorithm';
  try{
    const prompt = $('#iPrompt2').value;
    const body = { scene, prompt, refine:$('#iRefine').checked };
    const samples=parseSamples($('#iSamples').value);
    body.samples = samples;
    if($('#iAnswer').value) body.answer = $('#iAnswer').value;
    // 异步 job：提交后轮询阶段，过程先渲染（answer 阶段即展示步骤）
    const r=await fetch('/api/interact/job',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    const d=await r.json();
    if(!r.ok)throw new Error(d.detail||'failed');
    const jobId=d.job_id;
    setPhaseUI('solve', d.mode, '');
    // 轮询状态（SSE 端点存在但轮询更简单稳定；两个端点可任选）
    let finalPayload=null, answerShown=false;
    for(let tries=0; tries<600; tries++){
      await new Promise(res=>setTimeout(res,500));
      let st;
      try{ st=await (await fetch('/api/interact/job/'+jobId)).json(); }
      catch(e){ continue; }
      // 阶段按序推进：即使 execute/static 毫秒级被轮询跳过，
      // 用"已到达阶段 → 之前的全部点亮"保证徽章顺序完整
      if(st.phase && st.phase!=='done' && st.phase!=='failed'){
        advancePhaseUI(st.phase, d.mode, st.elapsed);
      }
      if(st.answer && !answerShown){ answerShown=true; renderInterimAnswer(st.answer); }   // B：先展示过程
      if(st.result){ finalPayload=st.result; break; }
      if(st.status==='failed'){ throw new Error(st.error||'运行失败'); }
    }
    if(!finalPayload) throw new Error('等待超时：求解未在预期时间内完成');
    setPhaseUI('done', d.mode, finalPayload.elapsed);
    renderFinalResult(finalPayload);
  }catch(e){
    const body=$('#iResultBody');
    body.style.alignItems='center';body.style.justifyContent='center';
    body.innerHTML=`<div class="finding"><b>出错：</b>${escapeHtml(e.message||String(e))}</div>`;
  }
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
loadQuestions();   // 初始即加载题目列表，无需切换页面
