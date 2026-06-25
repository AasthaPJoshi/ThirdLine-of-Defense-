import { BrowserRouter, Routes, Route, NavLink, useParams, useNavigate } from 'react-router-dom'
import { useState, useEffect, useCallback, ReactNode } from 'react'
import {
  LayoutDashboard, ShieldAlert, ClipboardCheck, BookLock, BarChart3,
  Shield, Activity, ChevronRight, ChevronDown, ChevronUp,
  CheckCircle2, XCircle, AlertTriangle, Lock, Eye, FileText
} from 'lucide-react'

/* ── Types ─────────────────────────────────────────────────────────────────── */
interface Agent { agent_id:string; name:string; business_line:string; materiality_tier:string; interaction_count:number; finding_count:number; highest_severity:string|null; risk_color:string; dimensions_failed:string[]; last_audited:string|null }
interface Finding { finding_id:string; agent_id:string; dimension:string; severity:string; title:string; status:string; control_id:string|null; failure_count:number; avg_score:number; drafted_at:string }
interface QueueItem { queue_id:string; finding_id:string; agent_id:string; severity:string; title:string; dimension:string; draft_text:string; control_id:string|null; queued_at:string; sla_deadline:string|null; status:string; assigned_to:string|null }
interface LedgerEntry { seq:number; finding_id:string; agent_id:string; event_type:string; actor:string; finding_hash:string; chain_hash:string; event_ts:string }
interface Metrics { f1:number; precision:number; recall:number; true_positives:number; false_positives:number; false_negatives:number; agents_evaluated:number; agents_detected:number; total_findings:number; total_interactions:number; findings_by_severity:Record<string,number>; ledger_intact:boolean; last_run_id:string|null }

/* ── API ────────────────────────────────────────────────────────────────────── */
const get = async <T,>(path: string): Promise<T> => { const r = await fetch(`/api/v1${path}`); if (!r.ok) throw new Error(`${r.status}`); return r.json() }
const post = async <T,>(path: string, body: object): Promise<T> => { const r = await fetch(`/api/v1${path}`, { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body) }); if (!r.ok) throw new Error(`${r.status}`); return r.json() }

/* ── Severity colours ──────────────────────────────────────────────────────── */
const SEV_TEXT:Record<string,string> = { CRITICAL:'text-red-400', HIGH:'text-orange-400', MEDIUM:'text-yellow-400', LOW:'text-blue-400' }
const SEV_BG:Record<string,string>   = { CRITICAL:'bg-red-500/10 border-red-500/30', HIGH:'bg-orange-500/10 border-orange-500/30', MEDIUM:'bg-yellow-500/10 border-yellow-500/30', LOW:'bg-blue-500/10 border-blue-500/30' }
const RISK_DOT:Record<string,string> = { red:'bg-red-500 shadow-[0_0_8px_#FF3B5C]', amber:'bg-orange-400 shadow-[0_0_8px_#FF8C00]', green:'bg-emerald-500 shadow-[0_0_8px_#00E676]', gray:'bg-slate-500' }

/* ── Small shared components ───────────────────────────────────────────────── */
const SevBadge = ({ sev }:{ sev:string }) => <span className={`text-xs font-bold px-2 py-0.5 rounded border ${SEV_TEXT[sev]??'text-slate-400'} ${SEV_BG[sev]??'bg-slate-500/10 border-slate-500/30'}`}>{sev}</span>

const DimTag = ({ dim }:{ dim:string }) => {
  const c:Record<string,string> = { hallucination:'bg-purple-500/10 text-purple-300 border-purple-500/25', bias:'bg-pink-500/10 text-pink-300 border-pink-500/25', drift:'bg-cyan-500/10 text-cyan-300 border-cyan-500/25', robustness:'bg-red-500/10 text-red-300 border-red-500/25', reliability:'bg-blue-500/10 text-blue-300 border-blue-500/25' }
  return <span className={`text-xs px-2 py-0.5 rounded border ${c[dim]??'bg-slate-500/10 text-slate-300 border-slate-500/25'}`}>{dim}</span>
}

const StatusBadge = ({ status }:{ status:string }) => {
  const c:Record<string,string> = { PENDING:'bg-yellow-500/10 text-yellow-400 border-yellow-500/25', PENDING_REVIEW:'bg-yellow-500/10 text-yellow-400 border-yellow-500/25', APPROVED:'bg-green-500/10 text-green-400 border-green-500/25', REJECTED:'bg-slate-500/10 text-slate-400 border-slate-500/25' }
  return <span className={`text-xs px-2 py-0.5 rounded border ${c[status]??c.PENDING}`}>{status.replace('_',' ')}</span>
}

const ScoreBar = ({ score, threshold=0.75 }:{ score:number; threshold?:number }) => {
  const pass = score >= threshold
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-1.5 rounded-full bg-slate-800">
        <div className={`h-1.5 rounded-full ${pass?'bg-emerald-500':'bg-red-500'}`} style={{width:`${Math.round(score*100)}%`}} />
      </div>
      <span className={`text-xs font-mono w-9 text-right ${pass?'text-emerald-400':'text-red-400'}`}>{score.toFixed(2)}</span>
    </div>
  )
}

const Spinner = () => <div className="flex justify-center py-16"><div className="w-8 h-8 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" /></div>

const Card = ({ children, className='' }:{ children:ReactNode; className?:string }) => (
  <div className={`bg-[#0A1628] border border-[#1A2E4A] rounded-xl ${className}`}>{children}</div>
)

const MetricCard = ({ label, value, sub, color='text-white' }:{ label:string; value:string|number; sub?:string; color?:string }) => (
  <div className="bg-[#0A1628] border border-[#1A2E4A] rounded-xl p-4 relative overflow-hidden">
    <div className="absolute top-0 left-0 right-0 h-0.5 bg-gradient-to-r from-blue-500 to-cyan-400 opacity-60" />
    <p className="text-xs text-slate-500 uppercase tracking-widest mb-1">{label}</p>
    <p className={`text-3xl font-bold tabular-nums ${color}`}>{value}</p>
    {sub && <p className="text-xs text-slate-600 mt-1">{sub}</p>}
  </div>
)

const Toast = ({ msg, type, onDone }:{ msg:string; type:'success'|'error'; onDone:()=>void }) => {
  useEffect(() => { const t = setTimeout(onDone, 3000); return () => clearTimeout(t) }, [onDone])
  return (
    <div className={`fixed bottom-6 right-6 z-50 flex items-center gap-3 px-4 py-3 rounded-xl border shadow-2xl bg-[#0F1F38] border-[#1A2E4A] text-sm text-slate-200 animate-in slide-in-from-bottom-4`}>
      {type==='success' ? <CheckCircle2 size={15} className="text-emerald-400" /> : <XCircle size={15} className="text-red-400" />}
      {msg}
    </div>
  )
}

/* ── Sidebar ────────────────────────────────────────────────────────────────── */
const NAV = [
  { to:'/',         icon:LayoutDashboard, label:'Fleet Overview',  section:'MONITOR' },
  { to:'/findings', icon:ShieldAlert,     label:'Findings',        section:'MONITOR' },
  { to:'/review',   icon:ClipboardCheck,  label:'Review Queue',    section:'AUDIT',   badge:true },
  { to:'/ledger',   icon:BookLock,        label:'Audit Ledger',    section:'AUDIT' },
  { to:'/metrics',  icon:BarChart3,       label:'Metrics',         section:'INTELLIGENCE' },
  { to:'/shield',   icon:Shield,          label:'Shield Monitor',  section:'INTELLIGENCE' },
]

function Sidebar({ queueCount }:{ queueCount:number }) {
  return (
    <aside className="w-60 min-h-screen bg-[#0A1628] border-r border-[#1A2E4A] flex flex-col sticky top-0 h-screen overflow-y-auto flex-shrink-0">
      {/* Logo */}
      <div className="px-5 py-5 border-b border-[#1A2E4A]">
        <div className="flex items-center gap-2.5 mb-1">
          <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-blue-500 to-cyan-400 flex items-center justify-center text-white text-sm font-black">TL</div>
          <span className="text-base font-bold text-white tracking-tight">ThirdLine</span>
        </div>
        <p className="text-[10px] text-slate-600 uppercase tracking-widest">AI Audit Platform</p>
      </div>
      {/* Status */}
      <div className="flex items-center gap-2 px-5 py-2.5 border-b border-[#1A2E4A] text-[11px] text-slate-500">
        <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 shadow-[0_0_6px_#00E676] animate-pulse" />
        All systems operational
      </div>
      {/* Nav */}
      <nav className="flex-1 px-3 py-4 space-y-0.5">
        {['MONITOR','AUDIT','INTELLIGENCE'].map(section => (
          <div key={section}>
            <p className="text-[9px] font-semibold uppercase tracking-widest text-slate-600 px-2.5 pt-3 pb-1">{section}</p>
            {NAV.filter(n => n.section===section).map(item => (
              <NavLink key={item.to} to={item.to} end={item.to==='/'} className={({ isActive }) =>
                `flex items-center gap-2.5 px-2.5 py-2 rounded-lg text-[13px] font-medium transition-all mb-0.5 border ${
                  isActive ? 'bg-blue-500/10 text-cyan-400 border-blue-500/25' : 'text-slate-400 border-transparent hover:bg-[#132040] hover:text-slate-200 hover:border-[#1A2E4A]'
                }`}>
                <item.icon size={14} />
                <span>{item.label}</span>
                {item.badge && queueCount>0 && (
                  <span className="ml-auto text-[10px] font-bold px-1.5 py-0.5 rounded-full bg-red-500/20 text-red-400 border border-red-500/30">{queueCount}</span>
                )}
              </NavLink>
            ))}
          </div>
        ))}
      </nav>
      <div className="px-5 py-3 border-t border-[#1A2E4A] text-[11px] text-slate-600">
        <div className="flex items-center gap-1.5 mb-0.5"><Lock size={9} /> Secure · Audited · Governed</div>
        <div>v1.0.0</div>
      </div>
    </aside>
  )
}

/* ── Topbar ─────────────────────────────────────────────────────────────────── */
function Topbar({ title }:{ title:string }) {
  return (
    <header className="h-14 bg-[#0A1628] border-b border-[#1A2E4A] flex items-center px-6 gap-3 sticky top-0 z-40">
      <div className="flex items-center gap-2 text-[13px] text-slate-500 flex-1">
        <span>ThirdLine</span><ChevronRight size={11} className="opacity-40" />
        <span className="text-white font-semibold">{title}</span>
      </div>
      <div className="flex items-center gap-2">
        <div className="flex items-center gap-1.5 px-2.5 py-1 bg-[#0F1F38] border border-[#1A2E4A] rounded-md text-[11px] text-slate-400">
          <Activity size={9} className="text-emerald-400" />Live
        </div>
        <div className="px-2.5 py-1 bg-[#0F1F38] border border-[#1A2E4A] rounded-md text-[11px] text-slate-400 font-mono">
          {new Date().toLocaleString('en-US',{dateStyle:'medium',timeStyle:'short'})}
        </div>
      </div>
    </header>
  )
}

/* ── Fleet Overview ─────────────────────────────────────────────────────────── */
function FleetPage() {
  const [agents, setAgents] = useState<Agent[]>([])
  const [loading, setLoading] = useState(true)
  const navigate = useNavigate()
  useEffect(() => { get<Agent[]>('/agents').then(setAgents).finally(() => setLoading(false)) }, [])
  if (loading) return <><Topbar title="Fleet Overview" /><div className="p-6"><Spinner /></div></>
  const critical = agents.filter(a=>a.highest_severity==='CRITICAL').length
  const high     = agents.filter(a=>a.highest_severity==='HIGH').length
  const clean    = agents.filter(a=>a.finding_count===0).length
  const total    = agents.reduce((s,a)=>s+a.interaction_count,0)
  return (
    <>
      <Topbar title="Fleet Overview" />
      <div className="p-6">
        <div className="mb-5">
          <h1 className="text-xl font-bold text-white tracking-tight">AI Agent Fleet</h1>
          <p className="text-sm text-slate-400 mt-0.5">Real-time risk status across {agents.length} deployed agents</p>
        </div>
        <div className="grid grid-cols-5 gap-3 mb-5">
          <MetricCard label="Total Agents"   value={agents.length}           sub="Under continuous audit" />
          <MetricCard label="Critical Risk"  value={critical}                sub="Require immediate action" color={critical>0?'text-red-400':'text-emerald-400'} />
          <MetricCard label="High Risk"      value={high}                    sub="Elevated concern"        color={high>0?'text-orange-400':'text-emerald-400'} />
          <MetricCard label="Interactions"   value={total.toLocaleString()}  sub="Total evaluated"        color="text-cyan-400" />
          <MetricCard label="Clean Agents"   value={clean}                   sub="No active findings"     color={clean>0?'text-emerald-400':'text-slate-400'} />
        </div>
        <div className="space-y-2">
          {agents.map(a => (
            <div key={a.agent_id} onClick={() => navigate(`/agents/${a.agent_id}`)}
              className={`bg-[#0A1628] border border-[#1A2E4A] rounded-xl px-5 py-4 flex items-center gap-4 cursor-pointer hover:bg-[#132040] hover:border-blue-500/30 hover:-translate-y-px transition-all group relative overflow-hidden`}>
              <div className={`absolute left-0 top-0 bottom-0 w-1 rounded-l-xl ${RISK_DOT[a.risk_color]?.split(' ')[0]??'bg-slate-600'}`} />
              <span className={`w-2.5 h-2.5 rounded-full flex-shrink-0 ml-1 ${RISK_DOT[a.risk_color]??'bg-slate-500'}`} />
              <div className="flex-1 min-w-0">
                <div className="font-semibold text-white text-sm">{a.name}</div>
                <div className="text-xs text-slate-500 mt-0.5 flex items-center gap-2">
                  <span>{a.business_line}</span>
                  <span className="text-[9px] font-bold uppercase tracking-wider px-1.5 py-0.5 bg-[#0F1F38] border border-[#1A2E4A] rounded text-slate-500">{a.materiality_tier}</span>
                </div>
                {a.dimensions_failed.length>0 && (
                  <div className="flex gap-1.5 mt-2 flex-wrap">{a.dimensions_failed.map(d=><DimTag key={d} dim={d}/>)}</div>
                )}
              </div>
              <div className="flex items-center gap-5 flex-shrink-0">
                <div className="text-right"><p className="text-[10px] text-slate-600 uppercase">Interactions</p><p className="text-sm font-mono text-slate-300">{a.interaction_count}</p></div>
                <div className="text-right"><p className="text-[10px] text-slate-600 uppercase">Findings</p><p className="text-sm font-mono text-slate-300">{a.finding_count}</p></div>
                {a.highest_severity ? <SevBadge sev={a.highest_severity} /> : <span className="text-xs font-bold px-2 py-0.5 rounded border bg-green-500/10 text-green-400 border-green-500/30">CLEAN</span>}
                <ChevronRight size={14} className="text-slate-600 group-hover:text-slate-400 transition-colors" />
              </div>
            </div>
          ))}
        </div>
      </div>
    </>
  )
}

/* ── Agent Detail ───────────────────────────────────────────────────────────── */
function AgentDetailPage() {
  const { agentId } = useParams()
  const navigate = useNavigate()
  const [detail, setDetail] = useState<any>(null)
  const [loading, setLoading] = useState(true)
  useEffect(() => { if(agentId) get<any>(`/agents/${agentId}`).then(setDetail).finally(()=>setLoading(false)) },[agentId])
  if (loading) return <><Topbar title="Agent Detail" /><div className="p-6"><Spinner /></div></>
  if (!detail)  return <><Topbar title="Agent Detail" /><div className="p-6 text-red-400">Agent not found</div></>
  const dims = ['hallucination','robustness','reliability','bias','drift']
  return (
    <>
      <Topbar title={detail.name} />
      <div className="p-6">
        <div className="flex items-center gap-3 mb-5">
          <button onClick={()=>navigate(-1)} className="text-xs text-slate-500 hover:text-slate-300 transition-colors">← Back</button>
          <div>
            <h1 className="text-xl font-bold text-white tracking-tight">{detail.name}</h1>
            <div className="flex items-center gap-2 text-xs text-slate-500 mt-0.5">
              <span>{detail.business_line}</span><span>·</span>
              <span className="text-[9px] font-bold uppercase tracking-wider px-1.5 py-0.5 bg-[#0F1F38] border border-[#1A2E4A] rounded text-slate-500">{detail.materiality_tier}</span>
              <span>·</span><span>{detail.interaction_count} interactions</span>
            </div>
          </div>
          {detail.highest_severity ? <SevBadge sev={detail.highest_severity} /> : <span className="text-xs font-bold px-2 py-0.5 rounded border bg-green-500/10 text-green-400 border-green-500/30">CLEAN</span>}
        </div>
        <p className="text-xs text-slate-500 uppercase tracking-widest mb-3">Evaluation Scorecards</p>
        <div className="grid grid-cols-3 gap-3 mb-5">
          {dims.filter(d=>detail.dimension_scores?.[d]).map(dim=>{
            const data=detail.dimension_scores[dim]; const pass=data.failures===0
            return (
              <Card key={dim} className="p-4">
                <div className="flex justify-between items-center mb-3"><DimTag dim={dim} /><span className={`text-xs font-bold ${pass?'text-emerald-400':'text-red-400'}`}>{pass?'✓ PASS':`${data.failures} FAIL`}</span></div>
                <ScoreBar score={data.avg_score} />
                <div className="mt-2 space-y-1">
                  <div className="flex justify-between text-xs text-slate-600"><span>Pass rate</span><span className="text-slate-300 font-mono">{(data.pass_rate*100).toFixed(0)}%</span></div>
                  <div className="flex justify-between text-xs text-slate-600"><span>Evaluated</span><span className="font-mono">{data.total}</span></div>
                </div>
              </Card>
            )
          })}
        </div>
        {detail.findings?.length>0 && <>
          <p className="text-xs text-slate-500 uppercase tracking-widest mb-3">Findings ({detail.findings.length})</p>
          {detail.findings.map((f:any)=>(
            <Card key={f.finding_id} className="mb-2 p-4">
              <div className="flex flex-wrap gap-2 items-center mb-2"><SevBadge sev={f.severity}/><DimTag dim={f.dimension}/><StatusBadge status={f.status}/></div>
              <p className="text-sm text-white font-medium mb-1">{f.title}</p>
              <p className="text-xs text-slate-500">{f.description?.slice(0,250)}...</p>
              <div className="mt-2"><ScoreBar score={f.avg_score}/></div>
            </Card>
          ))}
        </>}
      </div>
    </>
  )
}

/* ── Findings ───────────────────────────────────────────────────────────────── */
function FindingsPage() {
  const [findings, setFindings] = useState<Finding[]>([])
  const [loading, setLoading] = useState(true)
  const [filter, setFilter] = useState('ALL')
  useEffect(() => { get<Finding[]>('/findings').then(setFindings).finally(()=>setLoading(false)) },[])
  if (loading) return <><Topbar title="Findings" /><div className="p-6"><Spinner /></div></>
  const shown = filter==='ALL' ? findings : findings.filter(f=>f.severity===filter)
  return (
    <>
      <Topbar title="Findings" />
      <div className="p-6">
        <div className="flex justify-between items-end mb-5">
          <div><h1 className="text-xl font-bold text-white tracking-tight">Audit Findings</h1><p className="text-sm text-slate-400 mt-0.5">{findings.length} findings from the last audit run</p></div>
          <div className="flex gap-1.5">
            {['ALL','CRITICAL','HIGH','MEDIUM','LOW'].map(s=>(
              <button key={s} onClick={()=>setFilter(s)}
                className={`text-xs font-semibold px-3 py-1.5 rounded-lg border transition-all ${filter===s?'bg-blue-500 border-blue-500 text-white':'bg-[#0F1F38] border-[#1A2E4A] text-slate-400 hover:text-white'}`}>{s}</button>
            ))}
          </div>
        </div>
        {!shown.length ? (
          <div className="flex flex-col items-center py-16 text-slate-600 gap-2"><AlertTriangle size={28} className="opacity-30" /><p className="text-sm">No findings{filter!=='ALL'?` with severity ${filter}`:' found'}</p></div>
        ) : shown.map(f=>(
          <Card key={f.finding_id} className="mb-2 overflow-visible">
            <div className="flex items-center gap-3 p-4">
              <SevBadge sev={f.severity}/><DimTag dim={f.dimension}/>
              <span className="flex-1 text-sm font-medium text-white">{f.title}</span>
              <span className="text-xs text-slate-500 font-mono">{f.control_id}</span>
              <span className="text-xs text-red-400 font-mono">{f.failure_count} fail</span>
              <StatusBadge status={f.status}/>
            </div>
            <div className="px-4 pb-3"><ScoreBar score={f.avg_score}/></div>
          </Card>
        ))}
      </div>
    </>
  )
}

/* ── Review Queue ───────────────────────────────────────────────────────────── */
function ReviewQueuePage() {
  const [items, setItems]     = useState<QueueItem[]>([])
  const [loading, setLoading] = useState(true)
  const [expanded, setExpanded] = useState<string|null>(null)
  const [reviewer, setReviewer] = useState('auditor')
  const [comment, setComment]   = useState('')
  const [acting, setActing]     = useState<string|null>(null)
  const [toast, setToast]       = useState<{msg:string;type:'success'|'error'}|null>(null)
  const load = useCallback(() => { setLoading(true); get<QueueItem[]>('/review-queue').then(setItems).finally(()=>setLoading(false)) },[])
  useEffect(()=>{ load() },[load])
  const approve = async (id:string) => {
    setActing(id)
    try { await post(`/review-queue/${id}/approve`,{reviewer,comment}); setToast({msg:'Finding approved and recorded in ledger.',type:'success'}); setComment(''); setExpanded(null); load() }
    catch { setToast({msg:'Error approving finding.',type:'error'}) } finally { setActing(null) }
  }
  const reject = async (id:string) => {
    if (!comment.trim()) { setToast({msg:'Comment required to reject.',type:'error'}); return }
    setActing(id)
    try { await post(`/review-queue/${id}/reject`,{reviewer,comment}); setToast({msg:'Finding rejected.',type:'success'}); setComment(''); setExpanded(null); load() }
    catch { setToast({msg:'Error rejecting finding.',type:'error'}) } finally { setActing(null) }
  }
  if (loading) return <><Topbar title="Review Queue" /><div className="p-6"><Spinner /></div></>
  const pending  = [...items.filter(i=>i.status==='PENDING')].sort((a,b)=>({'CRITICAL':0,'HIGH':1,'MEDIUM':2,'LOW':3}[a.severity]??9)-({'CRITICAL':0,'HIGH':1,'MEDIUM':2,'LOW':3}[b.severity]??9))
  const actioned = items.filter(i=>i.status!=='PENDING')
  return (
    <>
      <Topbar title="Review Queue" />
      <div className="p-6">
        <div className="flex justify-between items-end mb-5">
          <div><h1 className="text-xl font-bold text-white tracking-tight">Human Review Queue</h1><p className="text-sm text-slate-400 mt-0.5">{pending.length} finding{pending.length!==1?'s':''} require your review</p></div>
          <div className="flex items-center gap-2"><label className="text-xs text-slate-500">Reviewer:</label><input value={reviewer} onChange={e=>setReviewer(e.target.value)} className="bg-[#0F1F38] border border-[#1A2E4A] rounded-lg px-3 py-1.5 text-sm text-white outline-none focus:border-blue-500 w-36" /></div>
        </div>
        {!pending.length ? (
          <div className="flex flex-col items-center py-16 text-slate-600 gap-2"><CheckCircle2 size={28} className="text-emerald-500 opacity-40" /><p className="text-sm">All findings reviewed.</p></div>
        ) : pending.map(item=>(
          <Card key={item.queue_id} className="mb-2">
            <div className="flex items-center gap-3 p-4 cursor-pointer" onClick={()=>setExpanded(expanded===item.queue_id?null:item.queue_id)}>
              <SevBadge sev={item.severity}/><DimTag dim={item.dimension}/>
              <span className="flex-1 text-sm font-medium text-white">{item.title}</span>
              {item.sla_deadline && <span className="text-xs text-yellow-400">SLA: {new Date(item.sla_deadline).toLocaleDateString()}</span>}
              {expanded===item.queue_id ? <ChevronUp size={14} className="text-slate-500" /> : <ChevronDown size={14} className="text-slate-500" />}
            </div>
            {expanded===item.queue_id && (
              <div className="border-t border-[#1A2E4A] p-4 space-y-3">
                <div>
                  <div className="text-xs font-semibold uppercase tracking-wider text-slate-500 mb-2 flex items-center gap-1.5"><Eye size={11}/>Workpaper Draft</div>
                  <div className="bg-[#040D1A] border border-[#1A2E4A] rounded-lg p-4 max-h-64 overflow-y-auto font-mono text-xs text-slate-400 leading-relaxed whitespace-pre-wrap">{item.draft_text}</div>
                </div>
                <div className="flex gap-4 text-xs text-slate-500">
                  <span>Control: <span className="text-slate-300">{item.control_id??'N/A'}</span></span>
                  <span>Queued: <span className="text-slate-300">{new Date(item.queued_at).toLocaleString()}</span></span>
                </div>
                <textarea value={comment} onChange={e=>setComment(e.target.value)} rows={3} placeholder="Add reviewer comment (required for rejection)..." className="w-full bg-[#0F1F38] border border-[#1A2E4A] rounded-lg p-3 text-sm text-slate-300 placeholder-slate-600 outline-none focus:border-blue-500 resize-none" />
                <div className="flex items-center gap-2">
                  <button onClick={()=>approve(item.queue_id)} disabled={!!acting} className="flex items-center gap-1.5 px-4 py-2 bg-emerald-500/10 border border-emerald-500/30 text-emerald-400 text-sm font-semibold rounded-lg hover:bg-emerald-500/20 disabled:opacity-50 transition-colors">
                    <CheckCircle2 size={14}/>{acting===item.queue_id?'Processing...':'Approve Finding'}
                  </button>
                  <button onClick={()=>reject(item.queue_id)} disabled={!!acting} className="flex items-center gap-1.5 px-4 py-2 bg-[#0F1F38] border border-[#1A2E4A] text-slate-400 text-sm font-semibold rounded-lg hover:text-white disabled:opacity-50 transition-colors">
                    <XCircle size={14}/>Reject
                  </button>
                  <div className="ml-auto flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-wider px-2.5 py-1.5 bg-blue-500/10 border border-blue-500/25 text-cyan-400 rounded-lg">
                    <Lock size={10}/>HITL Enforced
                  </div>
                </div>
              </div>
            )}
          </Card>
        ))}
        {actioned.length>0 && (
          <div className="mt-5">
            <p className="text-xs text-slate-600 uppercase tracking-widest mb-2">Actioned ({actioned.length})</p>
            {actioned.map(item=>(
              <div key={item.queue_id} className="flex items-center gap-3 px-4 py-3 bg-[#0A1628] border border-[#1A2E4A] rounded-xl mb-1.5 opacity-60">
                <SevBadge sev={item.severity}/><span className="flex-1 text-sm text-slate-400">{item.title}</span><StatusBadge status={item.status}/>
              </div>
            ))}
          </div>
        )}
      </div>
      {toast && <Toast msg={toast.msg} type={toast.type} onDone={()=>setToast(null)}/>}
    </>
  )
}

/* ── Ledger ─────────────────────────────────────────────────────────────────── */
function LedgerPage() {
  const [data, setData] = useState<any>(null)
  const [loading, setLoading] = useState(true)
  useEffect(()=>{ get<any>('/ledger').then(setData).finally(()=>setLoading(false)) },[])
  if (loading) return <><Topbar title="Audit Ledger" /><div className="p-6"><Spinner /></div></>
  const evColor=(t:string)=>t==='FINDING_APPROVED'?'text-emerald-400':t==='FINDING_REJECTED'?'text-slate-500':'text-cyan-400'
  return (
    <>
      <Topbar title="Audit Ledger" />
      <div className="p-6">
        <div className="flex justify-between items-end mb-5">
          <div><h1 className="text-xl font-bold text-white tracking-tight">Audit Ledger</h1><p className="text-sm text-slate-400 mt-0.5">Tamper-evident hash-chained record</p></div>
          <div className={`flex items-center gap-2 px-3 py-1.5 rounded-lg border text-sm font-bold ${data?.chain_intact?'bg-emerald-500/10 border-emerald-500/30 text-emerald-400':'bg-red-500/10 border-red-500/30 text-red-400'}`}>
            <BookLock size={14}/>{data?.chain_intact?'CHAIN INTACT':'CHAIN BROKEN'}
          </div>
        </div>
        <div className="grid grid-cols-3 gap-3 mb-5">
          <MetricCard label="Total Entries"  value={data?.total_entries??0} />
          <MetricCard label="Chain Status"   value={data?.chain_intact?'INTACT':'BROKEN'} color={data?.chain_intact?'text-emerald-400':'text-red-400'} />
          <MetricCard label="Algorithm"      value="SHA-256" color="text-cyan-400" />
        </div>
        {!data?.entries?.length ? (
          <div className="flex flex-col items-center py-16 text-slate-600 gap-2"><BookLock size={28} className="opacity-30"/><p className="text-sm">No ledger entries yet.</p></div>
        ) : [...data.entries].reverse().map((e:LedgerEntry)=>(
          <div key={e.seq} className="flex items-start gap-4 p-4 bg-[#0A1628] border border-[#1A2E4A] rounded-xl mb-2">
            <span className="text-xs font-mono text-slate-600 min-w-[28px]">#{e.seq}</span>
            <div className="flex-1">
              <div className={`text-xs font-bold uppercase tracking-wide mb-1 ${evColor(e.event_type)}`}>{e.event_type.replace('FINDING_','')}</div>
              <div className="text-xs text-slate-400 mb-1">Agent: <span className="text-slate-300">{e.agent_id.replace('agt-','').replace('-001','')}</span> · By: <span className="text-slate-300">{e.actor}</span></div>
              <div className="text-[10px] font-mono text-slate-600">{e.chain_hash.slice(0,48)}...</div>
            </div>
            <span className="text-xs text-slate-600 flex-shrink-0">{new Date(e.event_ts).toLocaleString()}</span>
          </div>
        ))}
      </div>
    </>
  )
}

/* ── Metrics ────────────────────────────────────────────────────────────────── */
function MetricsPage() {
  const [metrics, setMetrics] = useState<Metrics|null>(null)
  const [loading, setLoading] = useState(true)
  useEffect(()=>{ get<Metrics>('/metrics').then(setMetrics).finally(()=>setLoading(false)) },[])
  if (loading) return <><Topbar title="Metrics" /><div className="p-6"><Spinner /></div></>
  if (!metrics)  return <><Topbar title="Metrics" /><div className="p-6 text-slate-500">No metrics available</div></>
  const f1Color = metrics.f1>=0.8?'text-emerald-400':metrics.f1>=0.5?'text-yellow-400':'text-red-400'
  const C=2*Math.PI*34; const offset=C*(1-metrics.f1)
  const sevColors:Record<string,string>={CRITICAL:'bg-red-500',HIGH:'bg-orange-400',MEDIUM:'bg-yellow-400',LOW:'bg-blue-400'}
  const maxSev = Math.max(...Object.values(metrics.findings_by_severity),1)
  return (
    <>
      <Topbar title="Metrics" />
      <div className="p-6">
        <div className="mb-5"><h1 className="text-xl font-bold text-white tracking-tight">Detection Metrics</h1><p className="text-sm text-slate-400 mt-0.5">ThirdLine's own performance against known ground truth</p></div>
        {/* Hero */}
        <div className="bg-gradient-to-r from-[#0A1628] to-blue-500/5 border border-[#1A2E4A] rounded-xl p-5 mb-5 flex items-center gap-6">
          <div className="relative w-20 h-20 flex-shrink-0">
            <svg width="80" height="80" viewBox="0 0 80 80"><circle cx="40" cy="40" r="34" fill="none" stroke="#0F1F38" strokeWidth="6"/><circle cx="40" cy="40" r="34" fill="none" stroke={metrics.f1>=0.8?'#00E676':metrics.f1>=0.5?'#FFD600':'#FF3B5C'} strokeWidth="6" strokeLinecap="round" strokeDasharray={C} strokeDashoffset={offset} style={{transform:'rotate(-90deg)',transformOrigin:'center',transition:'stroke-dashoffset 1s ease'}}/></svg>
            <div className="absolute inset-0 flex flex-col items-center justify-center">
              <span className={`text-lg font-black leading-none ${f1Color}`}>{metrics.f1.toFixed(3)}</span>
              <span className="text-[9px] text-slate-600 uppercase tracking-wider">F1</span>
            </div>
          </div>
          <div>
            <h2 className="text-lg font-bold text-white mb-1">ThirdLine Detection Performance</h2>
            <p className="text-xs text-slate-400">Precision {(metrics.precision*100).toFixed(1)}% · Recall {(metrics.recall*100).toFixed(1)}% · {metrics.agents_detected}/{metrics.agents_evaluated} defects caught · {metrics.total_interactions} interactions</p>
            <div className="flex gap-4 mt-2 text-xs">
              <span className="text-emerald-400">✓ TP: {metrics.true_positives}</span>
              <span className="text-orange-400">FP: {metrics.false_positives}</span>
              <span className="text-red-400">FN: {metrics.false_negatives}</span>
              <span className={metrics.ledger_intact?'text-emerald-400':'text-red-400'}>Ledger: {metrics.ledger_intact?'INTACT':'BROKEN'}</span>
            </div>
          </div>
        </div>
        <div className="grid grid-cols-4 gap-3 mb-5">
          <MetricCard label="Precision"    value={`${(metrics.precision*100).toFixed(1)}%`} color={f1Color} sub={`${metrics.true_positives} TP, ${metrics.false_positives} FP`} />
          <MetricCard label="Recall"       value={`${(metrics.recall*100).toFixed(1)}%`}    color={metrics.recall>=0.9?'text-emerald-400':'text-yellow-400'} sub={`${metrics.agents_detected}/${metrics.agents_evaluated} detected`} />
          <MetricCard label="Interactions" value={metrics.total_interactions}                color="text-cyan-400" />
          <MetricCard label="Findings"     value={metrics.total_findings} />
        </div>
        {/* Severity bars */}
        <Card className="mb-4 p-4">
          <p className="text-xs text-slate-500 uppercase tracking-widest mb-4">Findings by Severity</p>
          {['CRITICAL','HIGH','MEDIUM','LOW'].map(s=>{
            const count=metrics.findings_by_severity[s]??0
            return (
              <div key={s} className="flex items-center gap-3 mb-3">
                <span className={`text-xs font-bold w-16 ${SEV_TEXT[s]}`}>{s}</span>
                <div className="flex-1 h-1.5 bg-[#0F1F38] rounded-full overflow-hidden">
                  <div className={`h-full rounded-full ${sevColors[s]} transition-all duration-700`} style={{width:`${(count/maxSev)*100}%`}} />
                </div>
                <span className="text-xs font-mono text-slate-300 w-4">{count}</span>
              </div>
            )
          })}
        </Card>
        {/* Resume bullet */}
        <div className="bg-blue-500/5 border border-blue-500/20 rounded-xl p-4">
          <div className="flex items-center gap-2 text-xs font-bold uppercase tracking-wider text-cyan-400 mb-2"><FileText size={11}/>Resume Bullet</div>
          <p className="text-xs text-slate-400 leading-relaxed">Architected ThirdLine, a production-grade agentic AI audit platform achieving F1={metrics.f1.toFixed(3)} (Precision {(metrics.precision*100).toFixed(1)}%, Recall {(metrics.recall*100).toFixed(1)}%) detecting {metrics.agents_detected}/{metrics.agents_evaluated} injected AI agent defects across hallucination, bias, drift, robustness, and reliability dimensions on {metrics.total_interactions} interactions, with {metrics.ledger_intact?'verified-intact':''} tamper-evident audit ledger and real-time ThirdLine Shield guardrail.</p>
        </div>
      </div>
    </>
  )
}

/* ── Shield ─────────────────────────────────────────────────────────────────── */
function ShieldPage() {
  return (
    <>
      <Topbar title="Shield Monitor" />
      <div className="p-6">
        <div className="mb-5"><h1 className="text-xl font-bold text-white tracking-tight">ThirdLine Shield</h1><p className="text-sm text-slate-400 mt-0.5">Real-time inference guardrail — prevention layer for all bank agents</p></div>
        <div className="bg-gradient-to-r from-blue-500/8 to-cyan-500/4 border border-blue-500/20 rounded-xl p-6 mb-5 flex items-center gap-5">
          <div className="w-16 h-16 bg-blue-500/10 border-2 border-blue-500/30 rounded-xl flex items-center justify-center flex-shrink-0"><Shield size={26} className="text-cyan-400"/></div>
          <div>
            <h2 className="text-lg font-bold text-white mb-1">Shield Active — All Agents Protected</h2>
            <p className="text-xs text-slate-400 mb-3">Input + Output scanning on every agent interaction · &lt;2ms overhead</p>
            <div className="flex flex-wrap gap-2">
              {['Prompt Injection','PII Redaction','Scope Validation','Harmful Content','Output Filtering'].map(f=>(
                <span key={f} className="text-[10px] font-bold uppercase tracking-wider px-2 py-1 bg-blue-500/10 border border-blue-500/25 text-cyan-400 rounded-lg">{f}</span>
              ))}
            </div>
          </div>
        </div>
        <div className="grid grid-cols-4 gap-3 mb-5">
          <MetricCard label="Layer Type"        value="Prevention" color="text-cyan-400" sub="Blocks before LLM" />
          <MetricCard label="Checks / Request"  value="5"          color="text-white"    sub="Input + output" />
          <MetricCard label="Avg Latency"       value="<2ms"       color="text-emerald-400" sub="Negligible overhead" />
          <MetricCard label="PII Patterns"      value="8"          color="text-white"    sub="SSN, CC, Email..." />
        </div>
        <Card>
          <div className="px-4 py-3 border-b border-[#1A2E4A]"><p className="text-xs text-slate-500 uppercase tracking-widest">Protection Matrix</p></div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead><tr className="border-b border-[#1A2E4A]">
                {['Check','Stage','Action on Block','Latency'].map(h=><th key={h} className="text-left text-[10px] font-semibold uppercase tracking-wider text-slate-500 px-4 py-2.5 bg-[#0F1F38]">{h}</th>)}
              </tr></thead>
              <tbody>
                {[
                  ['Prompt Injection',     'Input',  'BLOCK — never reaches LLM', '<1ms'],
                  ['PII in Query',         'Input',  'REDACT — sanitise before LLM', '<1ms'],
                  ['Harmful Intent',       'Input',  'BLOCK — compliance violation', '<1ms'],
                  ['PII in Output',        'Output', 'REDACT — strip before return', '<1ms'],
                  ['System Prompt Leak',   'Output', 'BLOCK — intercept response', '<1ms'],
                  ['Rate Limit Exceeded',  'Input',  'BLOCK — too many requests', '<1ms'],
                ].map(([check,stage,action,lat],i)=>(
                  <tr key={i} className="border-b border-[#1A2E4A]/50 hover:bg-white/[0.02]">
                    <td className="px-4 py-3 font-medium text-white">{check}</td>
                    <td className="px-4 py-3"><span className={`text-xs font-semibold px-2 py-0.5 rounded border ${stage==='Input'?'bg-slate-500/10 text-slate-400 border-slate-500/25':'bg-blue-500/10 text-blue-400 border-blue-500/25'}`}>{stage}</span></td>
                    <td className="px-4 py-3 text-xs text-slate-400">{action}</td>
                    <td className="px-4 py-3 text-xs font-mono text-slate-400">{lat}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      </div>
    </>
  )
}

/* ── App ────────────────────────────────────────────────────────────────────── */
export default function App() {
  const [queueCount, setQueueCount] = useState(0)
  useEffect(() => {
    const refresh = () => get<any[]>('/review-queue').then(q=>setQueueCount(q.filter(i=>i.status==='PENDING').length)).catch(()=>{})
    refresh()
    const id = setInterval(refresh, 30000)
    return () => clearInterval(id)
  },[])
  return (
    <BrowserRouter>
      <div className="flex min-h-screen bg-[#040D1A]">
        <Sidebar queueCount={queueCount}/>
        <div className="flex-1 flex flex-col min-w-0">
          <Routes>
            <Route path="/"                element={<FleetPage/>}/>
            <Route path="/agents/:agentId" element={<AgentDetailPage/>}/>
            <Route path="/findings"        element={<FindingsPage/>}/>
            <Route path="/review"          element={<ReviewQueuePage/>}/>
            <Route path="/ledger"          element={<LedgerPage/>}/>
            <Route path="/metrics"         element={<MetricsPage/>}/>
            <Route path="/shield"          element={<ShieldPage/>}/>
          </Routes>
        </div>
      </div>
    </BrowserRouter>
  )
}
