import { useState, useEffect, useRef } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Edit2, Save, X, Play, BrainCircuit, AlertTriangle, FileText, Settings, Rocket, Activity, ChevronRight, CheckCircle2, ChevronDown, ArchiveX, Clock, Eye } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import RunInspector from "./RunInspector";

interface JobDetailsProps {
  jobId: string;
  onClose: () => void;
  onRunLaunch: () => void;
  family: string; 
}

const statusColor = (status: string) => {
  switch(status) {
    case 'completed': return 'text-emerald-400 bg-emerald-500/10 border-emerald-500/20';
    case 'failed': return 'text-red-400 bg-red-500/10 border-red-500/20';
    case 'running': return 'text-amber-400 bg-amber-500/10 border-amber-500/20';
    case 'scaffolded': return 'text-slate-400 bg-slate-500/10 border-slate-500/20';
    default: return 'text-blue-400 bg-blue-500/10 border-blue-500/20';
  }
};

export default function JobDetails({ jobId, onClose, onRunLaunch, family }: JobDetailsProps) {
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  
  const [isEditingBrief, setIsEditingBrief] = useState(false);
  const [briefDraft, setBriefDraft] = useState("");
  
  const [isConfigModalOpen, setIsConfigModalOpen] = useState(false);
  const [isConfigEditing, setIsConfigEditing] = useState(false);
  const [configDraft, setConfigDraft] = useState("");
  const [saving, setSaving] = useState(false);

  const [savingBrief, setSavingBrief] = useState(false);
  const [isBriefRichText, setIsBriefRichText] = useState(true);
  
  const [dirtyFields, setDirtyFields] = useState(false);
  const [showUnsavedWarning, setShowUnsavedWarning] = useState(false);
  const [pendingAction, setPendingAction] = useState<(() => void) | null>(null);

  const [isRunning, setIsRunning] = useState(false);
  const [showRunConsole, setShowRunConsole] = useState(false);
  const [runLogs, setRunLogs] = useState("");
  const logsEndRef = useRef<HTMLDivElement>(null);
  
  const [selectedRun, setSelectedRun] = useState<string | null>(null);
  const [isBriefCollapsed, setIsBriefCollapsed] = useState(false);

  const fetchDetails = async () => {
    try {
      const res = await fetch(`/api/jobs/${jobId}`);
      const json = await res.json();
      setData(json);
      // Only reset drafts if we are not actively engaging them or if they are untouched over multiple fetches
      if (!isEditingBrief) setBriefDraft(json.brief || "");
      if (!isConfigModalOpen) setConfigDraft(json.config || "");
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchDetails();
  }, [jobId]);

  // Background poller when running
  useEffect(() => {
    let interval: NodeJS.Timeout;
    if (isRunning) {
      interval = setInterval(fetchDetails, 5000);
    }
    return () => clearInterval(interval);
  }, [isRunning, jobId]);

  // Auto-scroll run logs
  useEffect(() => {
    if (showRunConsole && logsEndRef.current) {
      logsEndRef.current.scrollIntoView();
    }
  }, [runLogs, showRunConsole]);

  useEffect(() => {
    const hasChanges = data && (briefDraft !== data.brief);
    setDirtyFields(!!hasChanges);
  }, [briefDraft, data]);

  const handleSaveBrief = async (autoSaveForRun = false) => {
    setSavingBrief(true);
    try {
      await fetch(`/api/jobs/${jobId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ brief: briefDraft })
      });
      setData((prev: any) => ({ ...prev, brief: briefDraft }));
      setDirtyFields(false);
      if (!autoSaveForRun) setIsEditingBrief(false);
      
      if (pendingAction) {
        pendingAction();
        setPendingAction(null);
      }
    } catch (err) {
      alert("Failed to save brief");
    } finally {
      setSavingBrief(false);
      setShowUnsavedWarning(false);
    }
  };

  const handleSaveConfig = async () => {
    setSaving(true);
    try {
      await fetch(`/api/jobs/${jobId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ config: configDraft })
      });
      setData((prev: any) => ({ ...prev, config: configDraft }));
      setIsConfigEditing(false);
    } catch(e) {
      alert("Failed to save config");
    } finally {
      setSaving(false);
    }
  };

  const handleCancelEditBrief = () => {
    if (dirtyFields) {
      setPendingAction(() => () => setIsEditingBrief(false));
      setShowUnsavedWarning(true);
    } else {
      setIsEditingBrief(false);
    }
  };

  const handleSelectRun = (r: string) => {
    setSelectedRun(r);
    setIsBriefCollapsed(true);
  };

  const handleClose = () => {
    if (isEditingBrief && dirtyFields) {
      setPendingAction(() => onClose);
      setShowUnsavedWarning(true);
    } else {
      onClose();
    }
  };

  const handleRun = async () => {
    if (isEditingBrief && dirtyFields) {
      await handleSaveBrief(true);
    }
    
    setIsRunning(true);
    setShowRunConsole(true);
    setRunLogs("");
    
    try {
      const res = await fetch(`/api/jobs/${jobId}/run`, { method: "POST" });
      if (res.body) {
        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          setRunLogs((prev) => prev + decoder.decode(value));
        }
      }
    } catch (e) {
      setRunLogs((prev) => prev + `\nRun failed: ${e}\n`);
    } finally {
      setIsRunning(false);
      await fetchDetails();
    }
  };

  if (loading || !data) {
    return (
      <div className="flex-1 flex items-center justify-center min-h-[400px]">
        <Activity className="w-8 h-8 text-brand-500 animate-spin opacity-50" />
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full animate-in fade-in slide-in-from-right-8 duration-500 relative">
      <header className="flex items-center justify-between pb-6 border-b border-slate-800 shrink-0">
        <div className="flex items-center gap-4">
          <button 
            onClick={handleClose}
            className="p-2 hover:bg-slate-800 rounded-full transition-colors text-slate-400 hover:text-white"
          >
            <X className="w-5 h-5" />
          </button>
          <h2 className="text-2xl font-semibold text-slate-100 font-mono tracking-tight">{jobId}</h2>
        </div>
        
        <div className="flex items-center gap-3">
          {/* Status Summary Card */}
          <button 
            onClick={() => setShowRunConsole(true)}
            className={`flex items-center gap-2 px-4 py-2 rounded-xl transition-all border text-sm font-medium ${
              isRunning ? 'bg-amber-500/10 border-amber-500/30 text-amber-400 hover:bg-amber-500/20' 
                        : 'bg-slate-800/50 border-slate-700/50 text-slate-400 hover:bg-slate-800'
            }`}
          >
            {isRunning ? <Clock className="w-4 h-4 animate-spin-slow" /> : <Activity className="w-4 h-4" />}
            {isRunning ? 'Execution in Progress' : 'Job Idle'}
          </button>

          {data.runs?.length > 0 && family && family.toLowerCase() !== 'neutral' && (
             <button className="flex items-center gap-2 px-4 py-2 bg-purple-500/10 hover:bg-purple-500/20 text-purple-400 rounded-xl transition-colors border border-purple-500/20 text-sm font-medium">
               <Rocket className="w-4 h-4" /> Train {family}
             </button>
          )}

          <button 
            onClick={() => { 
              setConfigDraft(data.config); 
              setIsConfigEditing(false); 
              setIsConfigModalOpen(true); 
            }}
            className="flex items-center gap-2 px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-xl transition-colors text-sm font-medium border border-slate-700/50"
          >
            <Settings className="w-4 h-4" /> Config
          </button>

          {!isEditingBrief ? (
            <button 
              onClick={() => { setIsEditingBrief(true); setIsBriefCollapsed(false); setSelectedRun(null); }}
              className="flex items-center gap-2 px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-xl transition-colors text-sm font-medium border border-slate-700/50"
            >
              <Edit2 className="w-4 h-4" /> Edit Brief
            </button>
          ) : (
            <div className="flex items-center gap-2">
              <button 
                onClick={handleCancelEditBrief}
                className="px-4 py-2 text-slate-400 hover:text-slate-200 text-sm font-medium transition-colors"
              >
                 Cancel
              </button>
              <button 
                onClick={() => handleSaveBrief()}
                disabled={!dirtyFields || savingBrief}
                className="flex items-center gap-2 px-4 py-2 bg-emerald-500/10 hover:bg-emerald-500/20 text-emerald-400 disabled:opacity-50 disabled:grayscale rounded-xl transition-colors border border-emerald-500/20 text-sm font-medium"
              >
                <Save className="w-4 h-4" /> {savingBrief ? "Saving..." : "Save Brief"}
              </button>
            </div>
          )}

          <div className="w-px h-6 bg-slate-800 mx-1" />

          <button 
            onClick={handleRun}
            disabled={isRunning}
            className="flex items-center gap-2 px-6 py-2 bg-gradient-to-r from-brand-600 to-brand-500 hover:from-brand-500 hover:to-brand-400 text-white rounded-xl shadow-lg shadow-brand-500/20 disabled:from-slate-700 disabled:to-slate-800 disabled:text-slate-500 disabled:shadow-none transition-all font-medium"
          >
            <Play className="w-4 h-4" /> Launch Run
          </button>
        </div>
      </header>

      <div className="flex flex-1 mt-6 h-full gap-6 overflow-hidden">
        
        {/* Left Sidebar: Runs */}
        <div className="w-64 flex flex-col shrink-0 border-r border-slate-800/80 pr-6 overflow-y-auto">
           <h3 className="text-sm font-medium uppercase tracking-widest text-slate-500 mb-4 flex items-center gap-2">
             <BrainCircuit className="w-4 h-4" /> Execution History
           </h3>
           <div className="flex flex-col gap-3">
             {data.runs?.length > 0 ? data.runs.map((r: any) => (
                <button
                  key={r.id}
                  onClick={() => handleSelectRun(r.id)}
                  className={`flex flex-col text-left px-5 py-3 rounded-2xl border transition-all ${
                     selectedRun === r.id 
                       ? 'bg-brand-500/10 border-brand-500/40' 
                       : 'bg-slate-900 border-slate-700/50 hover:bg-slate-800 hover:border-slate-600'
                  }`}
                >
                  <p className={`font-mono font-medium ${selectedRun === r.id ? 'text-brand-300' : 'text-slate-300'}`}>
                    {r.id}
                  </p>
                  <div className={`mt-2 inline-flex items-center gap-1.5 px-2 py-0.5 rounded-md text-xs font-semibold capitalize border backdrop-blur-sm w-fit ${statusColor(r.status)}`}>
                     {r.status === 'completed' && <CheckCircle2 className="w-3 h-3" />}
                     {r.status === 'running' && <Activity className="w-3 h-3" />}
                     {r.status === 'scaffolded' && <Clock className="w-3 h-3" />}
                     {r.status === 'failed' && <AlertTriangle className="w-3 h-3" />}
                     {r.status}
                  </div>
                </button>
             )) : (
                <div className="text-slate-500 text-sm mt-4 p-4 border border-dashed border-slate-800 rounded-2xl flex flex-col items-center justify-center text-center gap-2">
                  <ArchiveX className="w-6 h-6 opacity-30"/>
                  <p>No runs available</p>
                </div>
             )}
           </div>
        </div>

        {/* Right Main Content */}
        <div className="flex-1 flex flex-col gap-4 overflow-hidden relative">
           
           {/* Brief Card */}
           <div className={`flex flex-col shrink-0 bg-surface border border-slate-800/60 rounded-3xl overflow-hidden shadow-lg transition-all duration-300 ${isBriefCollapsed ? 'min-h-[64px]' : 'flex-1'}`}>
              <div 
                onClick={() => setIsBriefCollapsed(!isBriefCollapsed)}
                className="w-full px-6 py-4 flex justify-between items-center bg-slate-800/20 border-b border-slate-800/50 shrink-0 cursor-pointer hover:bg-slate-800/40 transition-colors"
               >
                <div className="flex items-center gap-3 text-emerald-400 font-medium hover:text-emerald-300">
                  <FileText className="w-5 h-5" /> Research Brief (brief.md)
                </div>
                <div className="flex items-center gap-4" onClick={e => e.stopPropagation()}>
                  {!isBriefCollapsed && !isEditingBrief && (
                     <div className="flex items-center gap-2 text-xs font-medium bg-slate-900 border border-slate-700/50 p-1 rounded-lg">
                       <button 
                         onClick={() => setIsBriefRichText(true)} 
                         className={`px-3 py-1 rounded-md transition-colors ${isBriefRichText ? 'bg-slate-700 text-white shadow-sm' : 'text-slate-400 hover:text-slate-200'}`}
                       >
                         Rich Text
                       </button>
                       <button 
                         onClick={() => setIsBriefRichText(false)} 
                         className={`px-3 py-1 rounded-md transition-colors ${!isBriefRichText ? 'bg-slate-700 text-white shadow-sm' : 'text-slate-400 hover:text-slate-200'}`}
                       >
                         Raw
                       </button>
                     </div>
                  )}
                  <button onClick={() => setIsBriefCollapsed(!isBriefCollapsed)}>
                    {isBriefCollapsed ? (
                      <span className="text-xs text-slate-500 uppercase tracking-widest font-medium hover:text-emerald-400 transition-colors flex items-center gap-1">Expand <ChevronDown className="w-3 h-3"/></span>
                    ) : (
                      <span className="text-xs text-slate-500 uppercase tracking-widest font-medium hover:text-red-400 transition-colors">Collapse</span>
                    )}
                  </button>
                </div>
              </div>

              <div className={`flex-1 transition-all overflow-hidden ${isBriefCollapsed ? 'hidden' : 'flex flex-col p-6'}`}>
                {isEditingBrief ? (
                  <textarea
                    value={briefDraft}
                    onChange={(e) => setBriefDraft(e.target.value)}
                    className="flex-1 w-full bg-slate-900/80 border border-slate-700/50 rounded-xl p-4 text-sm font-mono text-slate-300 focus:outline-none focus:ring-2 focus:ring-emerald-500 transition-all resize-none leading-relaxed"
                  />
                ) : (
                  <div className="flex-1 w-full bg-slate-900/50 border border-slate-800 rounded-xl p-4 overflow-auto">
                    {isBriefRichText ? (
                       <div className="prose prose-invert prose-emerald max-w-none prose-p:text-slate-300 prose-headings:text-slate-200">
                         <ReactMarkdown remarkPlugins={[remarkGfm]}>
                           {data.brief || "No brief found."}
                         </ReactMarkdown>
                       </div>
                    ) : (
                       <pre className="text-sm text-slate-400 whitespace-pre-wrap font-mono leading-relaxed">
                         {data.brief || "No brief found."}
                       </pre>
                    )}
                  </div>
                )}
              </div>
           </div>

           {/* Inlined Run Inspector */}
           {selectedRun && (
             <div className={`flex-1 overflow-hidden flex flex-col transition-all ${!isBriefCollapsed && 'hidden'}`}>
                <div className="flex-1 flex bg-surface border border-slate-800/60 rounded-3xl overflow-hidden shadow-xl">
                   <RunInspector 
                     jobId={jobId} 
                     runId={selectedRun} 
                     onClose={() => { setSelectedRun(null); setIsBriefCollapsed(false); }} 
                   />
                </div>
             </div>
           )}

        </div>
      </div>

      {/* Config Modal overlay */}
      <AnimatePresence>
         {isConfigModalOpen && (
           <div className="fixed inset-0 z-[60] flex items-center justify-center p-4 sm:p-8">
              <motion.div initial={{opacity:0}} animate={{opacity:1}} exit={{opacity:0}} onClick={() => setIsConfigModalOpen(false)} className="absolute inset-0 bg-black/60 backdrop-blur-sm" />
              <motion.div 
                initial={{opacity: 0, scale: 0.95, y: 10}} animate={{opacity: 1, scale: 1, y: 0}} exit={{opacity: 0, scale: 0.95, y: 10}}
                className="bg-[#0f172a] relative z-10 w-full max-w-4xl h-[80vh] flex flex-col border border-slate-700/50 rounded-3xl shadow-2xl overflow-hidden"
              >
                 <div className="px-6 py-4 border-b border-slate-800 bg-[#1e293b]/50 flex justify-between items-center">
                   <h2 className="text-lg font-medium text-brand-400 flex items-center gap-2"><Settings className="w-5 h-5"/> Configuration</h2>
                   <div className="flex items-center gap-2">
                     {!isConfigEditing ? (
                        <button onClick={() => setIsConfigEditing(true)} className="px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg text-sm font-medium transition-colors border border-slate-700/50 flex items-center gap-2"><Edit2 className="w-3.5 h-3.5"/> Edit</button>
                     ) : (
                        <button onClick={() => { setConfigDraft(data.config); setIsConfigEditing(false); }} className="px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg text-sm font-medium transition-colors border border-slate-700/50 flex items-center gap-2"><Eye className="w-3.5 h-3.5"/> View</button>
                     )}
                     <div className="w-px h-4 bg-slate-700 mx-1"></div>
                     <button onClick={() => setIsConfigModalOpen(false)} className="p-1.5 hover:bg-slate-700/50 rounded-full text-slate-400 hover:text-white transition-colors"><X className="w-5 h-5"/></button>
                   </div>
                 </div>
                 <div className="flex-1 p-6 bg-slate-950 overflow-hidden flex flex-col h-full">
                    {isConfigEditing ? (
                       <textarea
                         value={configDraft}
                         onChange={e => setConfigDraft(e.target.value)}
                         className="flex-1 w-full bg-slate-900/80 border border-slate-700/50 rounded-xl p-4 text-sm font-mono text-slate-300 focus:outline-none focus:ring-2 focus:ring-brand-500 transition-all resize-none"
                       />
                    ) : (
                       <pre className="flex-1 w-full bg-slate-900/80 border border-slate-700/50 rounded-xl p-6 text-sm font-mono text-slate-300 overflow-auto">
                         {configDraft || "No configuration contents"}
                       </pre>
                    )}
                 </div>
                 <div className="px-6 py-4 border-t border-slate-800 bg-[#0f172a] flex justify-end gap-3 shrink-0">
                    <button onClick={() => setIsConfigModalOpen(false)} className="px-4 py-2 hover:bg-slate-800 rounded-xl font-medium text-slate-400 transition-colors">Close</button>
                    {isConfigEditing && (
                       <button onClick={handleSaveConfig} disabled={saving} className="px-6 py-2 bg-brand-500 hover:bg-brand-400 text-white rounded-xl font-medium transition-colors shadow-lg shadow-brand-500/20">{saving ? "Saving..." : "Save Config"}</button>
                    )}
                 </div>
              </motion.div>
           </div>
         )}
      </AnimatePresence>

      <AnimatePresence>
        {showUnsavedWarning && (
          <div className="fixed inset-0 z-[70] flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm">
            <motion.div 
              initial={{ scale: 0.9, opacity: 0 }} 
              animate={{ scale: 1, opacity: 1 }} 
              exit={{ scale: 0.9, opacity: 0 }}
              className="bg-slate-900 border border-amber-500/20 rounded-2xl w-full max-w-md p-6 shadow-2xl flex flex-col gap-4"
            >
              <div className="flex items-center gap-3 text-amber-500">
                <AlertTriangle className="w-6 h-6" />
                <h3 className="text-xl font-medium text-white">Unsaved Changes</h3>
              </div>
              <p className="text-slate-400 text-sm">
                You have unsaved edits in your brief. Proceeding will discard them. Would you like to save before continuing?
              </p>
              <div className="flex justify-end gap-3 mt-4">
                <button 
                  onClick={() => {
                    const action = pendingAction;
                    setPendingAction(null);
                    setShowUnsavedWarning(false);
                    if (action) action(); // Discard and proceed
                  }}
                  className="px-4 py-2 rounded-xl text-slate-400 hover:text-red-400 font-medium transition-colors"
                >
                  Discard Changes
                </button>
                <button 
                  onClick={() => handleSaveBrief()}
                  className="px-6 py-2 rounded-xl bg-amber-500 hover:bg-amber-400 text-black font-medium transition-colors"
                >
                  Save & Continue
                </button>
              </div>
            </motion.div>
          </div>
        )}
      </AnimatePresence>

      <AnimatePresence>
        {showRunConsole && (
          <div className="fixed inset-0 z-[60] flex items-center justify-center p-4 sm:p-8">
             <motion.div initial={{opacity:0}} animate={{opacity:1}} exit={{opacity:0}} onClick={() => setShowRunConsole(false)} className="absolute inset-0 bg-black/80 backdrop-blur-sm" />
             <motion.div 
              initial={{ opacity: 0, scale: 0.95, y: 10 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.95, y: 10 }}
              className="bg-[#0f172a] relative z-10 border border-brand-500/50 rounded-3xl w-full max-w-4xl h-[80vh] flex flex-col overflow-hidden shadow-2xl shadow-brand-500/20"
            >
              <div className="flex justify-between items-center px-6 py-4 border-b border-slate-800 bg-[#1e293b]/50">
                <h3 className="text-xl font-medium text-brand-400 flex items-center gap-3">
                  {isRunning ? <Activity className="w-5 h-5 animate-pulse" /> : <CheckCircle2 className="w-5 h-5 text-emerald-400" />} 
                  {isRunning ? "Executing Run Flow..." : "Run Completed"}
                </h3>
                <button 
                  onClick={() => setShowRunConsole(false)}
                  className="p-2 text-slate-400 hover:text-white bg-slate-800 hover:bg-slate-700 rounded-full transition-colors"
                  title="Hide Console (Process keeps running)"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>
              <div className="flex-1 p-6 overflow-y-auto bg-black font-mono text-sm leading-relaxed">
                <pre className="text-emerald-400 whitespace-pre-wrap">{runLogs || "Initializing run sequence..."}</pre>
                <div className="h-4 pointer-events-none" ref={logsEndRef} />
              </div>
            </motion.div>
          </div>
        )}
      </AnimatePresence>
    </div>
  );
}
