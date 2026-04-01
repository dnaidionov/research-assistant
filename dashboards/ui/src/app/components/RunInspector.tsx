import { useState, useEffect } from "react";
import { X, Activity, FileText, Code, Brackets, CheckCircle2, FolderTree, Settings, AlignLeft, FileClock, Clock, AlertTriangle, FileJson } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

interface RunInspectorProps {
  jobId: string;
  runId: string;
  onClose: () => void;
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

const statusIcon = (status: string, className = "w-4 h-4") => {
  switch(status) {
    case 'completed': return <CheckCircle2 className={className} />;
    case 'failed': return <AlertTriangle className={className} />;
    case 'running': return <Activity className={className} />;
    case 'scaffolded': return <Clock className={className} />;
    default: return null;
  }
};

export default function RunInspector({ jobId, runId, onClose }: RunInspectorProps) {
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  
  const [activeTab, setActiveTab] = useState<"status" | "report" | "outputs" | "prompts" | "config">("report");
  const [selectedFile, setSelectedFile] = useState<any>(null);
  
  const [wrapLines, setWrapLines] = useState(true);
  const [richText, setRichText] = useState(true);

  useEffect(() => {
    async function fetchRun() {
      try {
        const res = await fetch(`/api/jobs/${jobId}/runs/${runId}`);
        const json = await res.json();
        setData(json);
        if (!json.htmlReport) setActiveTab("status");
      } catch (err) {
        console.error(err);
      } finally {
        setLoading(false);
      }
    }
    fetchRun();
  }, [jobId, runId]);

  if (loading) {
    return (
      <div className="flex w-full h-full items-center justify-center bg-slate-900/40">
        <Activity className="w-10 h-10 text-brand-500 animate-spin opacity-50" />
      </div>
    );
  }

  const runStatus = data.workflowState?.status || 'unknown';
  const filesToDisplay = activeTab === "outputs" ? data?.stageOutputs : data?.promptPackets;

  return (
    <div className="flex flex-col w-full h-full animate-in fade-in bg-slate-950">
      <header className="flex justify-between items-center px-6 py-4 border-b border-slate-800 bg-[#1e293b]/50 shrink-0">
        <div className="flex items-center gap-3">
          <h2 className="text-xl font-medium text-slate-100 flex items-center gap-2">
            Run: <span className="text-brand-400 font-mono tracking-tight">{runId}</span>
          </h2>
          <button 
            onClick={() => setActiveTab('status')}
            className={`flex items-center gap-1.5 px-3 py-1 rounded-md text-sm font-medium border transition-colors ${statusColor(runStatus)} hover:brightness-110 cursor-pointer`}
          >
            {statusIcon(runStatus)} {runStatus}
          </button>
        </div>

        <div className="flex bg-slate-900 rounded-xl p-1 border border-slate-800">
          {data.htmlReport && (
            <button 
              onClick={() => setActiveTab('report')} 
              className={`px-4 py-1.5 rounded-lg text-sm font-medium transition-all ${activeTab === 'report' ? 'bg-brand-500 text-white shadow-md' : 'text-slate-400 hover:text-white'}`}
            >
              Report
            </button>
          )}
          <button 
            onClick={() => setActiveTab('status')} 
            className={`px-4 py-1.5 rounded-lg text-sm font-medium transition-all ${activeTab === 'status' ? 'bg-brand-500 text-white shadow-md' : 'text-slate-400 hover:text-white'}`}
          >
            Status
          </button>
          <button 
            onClick={() => { setActiveTab('outputs'); setSelectedFile(null); }} 
            className={`px-4 py-1.5 rounded-lg text-sm font-medium transition-all ${activeTab === 'outputs' ? 'bg-brand-500 text-white shadow-md' : 'text-slate-400 hover:text-white'}`}
          >
            Outputs
          </button>
          <button 
            onClick={() => { setActiveTab('prompts'); setSelectedFile(null); }} 
            className={`px-4 py-1.5 rounded-lg text-sm font-medium transition-all ${activeTab === 'prompts' ? 'bg-brand-500 text-white shadow-md' : 'text-slate-400 hover:text-white'}`}
          >
            Prompts
          </button>
          {data.executionConfig && (
            <button 
              onClick={() => setActiveTab('config')} 
              className={`px-4 py-1.5 rounded-lg text-sm font-medium transition-all ${activeTab === 'config' ? 'bg-brand-500 text-white shadow-md' : 'text-slate-400 hover:text-white'}`}
            >
              Config Snapshot
            </button>
          )}
        </div>
        
        <div className="flex items-center gap-2">
          {activeTab === 'report' && data.htmlReport && (
            <button 
              onClick={() => { navigator.clipboard.writeText(data.htmlReport); alert("Report HTML copied"); }}
              className="px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs rounded-lg transition-colors border border-slate-700/50"
            >
              Copy HTML
            </button>
          )}
          <button onClick={onClose} className="p-2 text-slate-400 hover:text-white bg-slate-800 hover:bg-slate-700 rounded-full transition-colors ml-2">
            <X className="w-4 h-4" />
          </button>
        </div>
      </header>

      <main className="flex-1 overflow-hidden flex relative">
        {activeTab === "report" && data.htmlReport ? (
          <div className="flex-1 w-full h-full bg-white relative">
             <iframe 
               srcDoc={data.htmlReport} 
               className="w-full h-full border-none"
               title="Final HTML Report"
             />
          </div>
        ) : activeTab === "status" ? (
          <div className="flex-1 p-8 overflow-y-auto w-full h-full bg-slate-900/50">
             <div className="max-w-3xl mx-auto space-y-6">
               <h3 className="text-xl font-medium text-slate-200 mb-6 flex items-center gap-2">
                 <FileClock className="w-6 h-6 text-brand-400" /> Subprocess Status
               </h3>
               {data.workflowState?.stages?.map((stage: any, index: number) => {
                 let providerInfo = null;
                 if (data.executionConfig) {
                   const spaces = [
                     data.executionConfig.pipeline?.stages?.[stage.id],
                     data.executionConfig.stages?.[stage.id],
                     data.executionConfig[stage.id],
                     data.executionConfig
                   ];
                   for (const s of spaces) {
                     if (s?.provider || s?.model) {
                       providerInfo = { provider: s.provider, model: s.model };
                       break;
                     }
                   }
                 }

                 return (
                 <div key={stage.id} className="bg-slate-900 border border-slate-700/60 rounded-2xl p-6 shadow-xl relative overflow-hidden">
                   <div className="absolute top-0 left-0 w-1 h-full bg-brand-500/30" />
                   <div className="flex justify-between items-start mb-2">
                     <div>
                       <h4 className="text-lg font-medium text-slate-100">{index + 1}. {stage.id}</h4>
                       <p className="text-sm text-slate-400 mt-1">{stage.description}</p>
                     </div>
                     <span className={`px-3 py-1 flex items-center gap-1.5 rounded-md text-xs font-semibold capitalize border ${statusColor(stage.status)}`}>
                        {statusIcon(stage.status)} {stage.status}
                     </span>
                   </div>

                   {providerInfo && (
                     <div className="flex items-center gap-3 mb-4 mt-2 text-xs font-mono text-slate-400 bg-slate-800/40 w-fit px-3 py-1.5 rounded-lg border border-slate-700/50">
                       {providerInfo.provider && <span>Provider: <span className="text-brand-300">{providerInfo.provider}</span></span>}
                       {providerInfo.model && <span>Model: <span className="text-emerald-300">{providerInfo.model}</span></span>}
                     </div>
                   )}

                   {stage.substeps && Object.keys(stage.substeps).length > 0 && (
                     <div className="mt-4 pt-4 border-t border-slate-800">
                       <p className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-3">Subprocesses</p>
                       <div className="flex flex-col gap-2">
                         {Object.entries(stage.substeps).map(([key, sub]: [string, any]) => (
                           <div key={key} className="flex items-center justify-between bg-slate-800/50 px-4 py-2.5 rounded-lg border border-slate-700">
                             <span className="text-sm font-mono text-slate-300">{key}</span>
                             <span className={`flex items-center gap-1.5 text-xs capitalize font-medium ${sub.status === 'completed' ? 'text-emerald-400' : sub.status === 'running' ? 'text-amber-400' : sub.status === 'failed' ? 'text-red-400' : 'text-slate-400'}`}>
                               {statusIcon(sub.status, "w-3.5 h-3.5")} {sub.status}
                             </span>
                           </div>
                         ))}
                       </div>
                     </div>
                   )}
                 </div>
               )})}
             </div>
          </div>
        ) : activeTab === "config" ? (
          <div className="flex-1 overflow-auto p-8 font-mono text-sm leading-relaxed bg-slate-950">
             <div className="max-w-4xl mx-auto bg-slate-900 border border-slate-800 rounded-3xl p-6 shadow-xl">
               <h3 className="text-brand-400 font-medium text-lg flex items-center gap-2 mb-4 border-b border-slate-800 pb-4">
                 <Settings className="w-5 h-5"/> Execution Configuration Snapshot
               </h3>
               <pre className="text-emerald-300/90 whitespace-pre-wrap">{JSON.stringify(data.executionConfig, null, 2)}</pre>
             </div>
          </div>
        ) : (
          <div className="flex w-full h-full">
            {/* File Tree / List */}
            <div className="w-[240px] border-r border-slate-800 bg-slate-900/40 p-4 overflow-y-auto shrink-0 flex flex-col gap-2">
               <div className="text-xs font-semibold uppercase tracking-wider text-slate-500 mb-2 flex items-center gap-2">
                 <FolderTree className="w-3.5 h-3.5" /> Artifacts Tree
               </div>
               {filesToDisplay?.length > 0 ? filesToDisplay.map((f: any) => (
                 <button
                   key={f.path}
                   onClick={() => setSelectedFile(f)}
                   className={`text-left px-3 py-2 rounded-xl text-sm transition-all flex items-center gap-3 overflow-hidden
                      ${selectedFile?.path === f.path ? 'bg-brand-500/10 border border-brand-500/30 text-brand-300' : 'text-slate-400 hover:bg-slate-800 hover:text-slate-200 border border-transparent'}
                   `}
                 >
                    {f.type === 'json' ? <Brackets className="w-4 h-4 shrink-0 text-amber-500/70" /> : <Code className="w-4 h-4 shrink-0 text-sky-500/70" />}
                    <span className="truncate">{f.name}</span>
                 </button>
               )) : (
                 <p className="text-slate-500 text-sm mt-4 text-center">No artifacts found.</p>
               )}
            </div>

            {/* File Viewer */}
            <div className="flex-1 bg-slate-950 flex flex-col overflow-hidden relative">
               {selectedFile ? (
                 <>
                    {/* Viewer Options Toolbar */}
                    <div className="bg-[#1e293b]/80 px-4 py-2 border-b border-slate-800 text-sm flex items-center justify-between shrink-0">
                      <div className="font-mono text-slate-300 flex items-center gap-2">
                         <FileJson className="w-4 h-4 text-slate-500" />
                         {selectedFile.path}
                      </div>

                      <div className="flex items-center gap-4">
                        {selectedFile.type === 'md' && (
                          <div className="flex items-center gap-2 text-xs font-medium bg-slate-900 border border-slate-700/50 p-1 rounded-lg">
                            <button 
                              onClick={() => setRichText(true)} 
                              className={`px-3 py-1 rounded-md transition-colors ${richText ? 'bg-slate-700 text-white shadow-sm' : 'text-slate-400 hover:text-slate-200'}`}
                            >
                              Rich Text
                            </button>
                            <button 
                              onClick={() => setRichText(false)} 
                              className={`px-3 py-1 rounded-md transition-colors ${!richText ? 'bg-slate-700 text-white shadow-sm' : 'text-slate-400 hover:text-slate-200'}`}
                            >
                              Raw
                            </button>
                          </div>
                        )}
                        <label className="flex items-center gap-2 text-xs text-slate-400 cursor-pointer hover:text-white transition-colors">
                           <input type="checkbox" checked={wrapLines} onChange={e => setWrapLines(e.target.checked)} className="accent-brand-500 rounded cursor-pointer" />
                           <AlignLeft className="w-3.5 h-3.5" /> Wrap Lines
                        </label>
                      </div>
                    </div>
                    
                    {/* Document Content */}
                    <div className="flex-1 overflow-auto p-6 relative">
                       {selectedFile.type === 'md' && richText ? (
                          <div className="prose prose-invert prose-emerald max-w-4xl mx-auto prose-pre:bg-slate-900 prose-pre:border prose-pre:border-slate-800 text-[15px] leading-relaxed">
                            <ReactMarkdown remarkPlugins={[remarkGfm]}>
                              {selectedFile.content}
                            </ReactMarkdown>
                          </div>
                       ) : selectedFile.type === 'json' ? (
                          <pre className={`text-emerald-300/90 font-mono text-[13px] leading-snug !m-0 ${wrapLines ? 'whitespace-pre-wrap' : 'whitespace-pre'}`}>
                            {selectedFile.content}
                          </pre>
                       ) : (
                          <pre className={`text-slate-300 font-mono text-[13px] leading-snug !m-0 ${wrapLines ? 'whitespace-pre-wrap' : 'whitespace-pre'}`}>
                            {selectedFile.content}
                          </pre>
                       )}
                    </div>
                 </>
               ) : (
                 <div className="flex-1 flex flex-col items-center justify-center text-slate-600">
                    <FileText className="w-12 h-12 mb-4 opacity-20" />
                    <p>Select an artifact to inspect its contents</p>
                 </div>
               )}
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
