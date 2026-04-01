import { useState, useEffect } from "react";
import { X, Activity, FileText, Code, Brackets, CheckCircle2, ChevronRight, FolderTree } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";

interface RunInspectorProps {
  jobId: string;
  runId: string;
  onClose: () => void;
}

export default function RunInspector({ jobId, runId, onClose }: RunInspectorProps) {
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState<"report" | "outputs" | "prompts">("report");
  const [selectedFile, setSelectedFile] = useState<any>(null);

  useEffect(() => {
    async function fetchRun() {
      try {
        const res = await fetch(`/api/jobs/${jobId}/runs/${runId}`);
        const json = await res.json();
        setData(json);
        if (!json.htmlReport) setActiveTab("outputs");
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
      <div className="fixed inset-0 z-50 flex items-center justify-center p-4 sm:p-8 bg-black/80 backdrop-blur-sm">
        <Activity className="w-10 h-10 text-brand-500 animate-spin opacity-50" />
      </div>
    );
  }

  const filesToDisplay = activeTab === "outputs" ? data?.stageOutputs : data?.promptPackets;

  return (
    <AnimatePresence>
      <div className="fixed inset-0 z-40 flex items-center justify-center p-4 sm:p-8 bg-black/60 backdrop-blur-sm">
        <motion.div 
          initial={{ opacity: 0, scale: 0.95, y: 10 }}
          animate={{ opacity: 1, scale: 1, y: 0 }}
          exit={{ opacity: 0, scale: 0.95, y: 10 }}
          className="bg-[#0f172a] border border-slate-700 rounded-3xl w-full max-w-6xl h-[85vh] flex flex-col overflow-hidden shadow-2xl relative"
        >
          <header className="flex justify-between items-center px-6 py-4 border-b border-slate-800 bg-[#1e293b]/50 shrink-0">
            <h2 className="text-xl font-medium text-slate-100 flex items-center gap-3">
              <CheckCircle2 className="w-5 h-5 text-emerald-400" />
              Run Inspection: <span className="text-brand-400 font-mono tracking-tight">{runId}</span>
            </h2>
            <div className="flex bg-slate-900 rounded-xl p-1 border border-slate-800">
              {data.htmlReport && (
                <button 
                  onClick={() => setActiveTab('report')} 
                  className={`px-4 py-1.5 rounded-lg text-sm font-medium transition-all ${activeTab === 'report' ? 'bg-brand-500 text-white shadow-md' : 'text-slate-400 hover:text-white'}`}
                >
                  Final Report
                </button>
              )}
              <button 
                onClick={() => { setActiveTab('outputs'); setSelectedFile(null); }} 
                className={`px-4 py-1.5 rounded-lg text-sm font-medium transition-all ${activeTab === 'outputs' ? 'bg-brand-500 text-white shadow-md' : 'text-slate-400 hover:text-white'}`}
              >
                Stage Outputs
              </button>
              <button 
                onClick={() => { setActiveTab('prompts'); setSelectedFile(null); }} 
                className={`px-4 py-1.5 rounded-lg text-sm font-medium transition-all ${activeTab === 'prompts' ? 'bg-brand-500 text-white shadow-md' : 'text-slate-400 hover:text-white'}`}
              >
                Prompts
              </button>
            </div>
            
            <div className="flex items-center gap-2">
              <button 
                onClick={() => {
                  if (data.htmlReport) {
                    navigator.clipboard.writeText(data.htmlReport);
                    alert("Report HTML copied to clipboard");
                  } else {
                    alert("No final report available to copy.");
                  }
                }}
                className="px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs rounded-lg transition-colors border border-slate-700/50"
              >
                Copy Content
              </button>
              <button 
                onClick={() => window.open(`http://localhost:3000/api/jobs/${jobId}/runs/${runId}`, '_blank')}
                className="px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs rounded-lg transition-colors border border-slate-700/50 mr-2"
              >
                Raw API
              </button>
              
              <button onClick={onClose} className="p-2 text-slate-400 hover:text-white bg-slate-800 hover:bg-slate-700 rounded-full transition-colors ml-2">
                <X className="w-4 h-4" />
              </button>
            </div>
          </header>

          <main className="flex-1 overflow-hidden flex bg-slate-950">
            {activeTab === "report" && data.htmlReport ? (
              <div className="flex-1 w-full h-full bg-white relative">
                 <iframe 
                   srcDoc={data.htmlReport} 
                   className="w-full h-full border-none"
                   title="Final HTML Report"
                 />
              </div>
            ) : (
              <div className="flex w-full h-full">
                {/* File Tree / List */}
                <div className="w-1/3 border-r border-slate-800 bg-slate-900/40 p-4 overflow-y-auto flex flex-col gap-2">
                   <div className="text-xs font-semibold uppercase tracking-wider text-slate-500 mb-2 flex items-center gap-2">
                     <FolderTree className="w-3.5 h-3.5" /> Artifacts Tree
                   </div>
                   {filesToDisplay?.length > 0 ? filesToDisplay.map((f: any) => (
                     <button
                       key={f.path}
                       onClick={() => setSelectedFile(f)}
                       className={`text-left px-3 py-2 rounded-xl text-sm transition-all flex items-center gap-3 overflow-hidden
                          ${selectedFile?.path === f.path ? 'bg-brand-500/10 border border-brand-500/20 text-brand-300' : 'text-slate-400 hover:bg-slate-800 hover:text-slate-200 border border-transparent'}
                       `}
                     >
                        {f.type === 'json' ? <Brackets className="w-4 h-4 shrink-0" /> : <Code className="w-4 h-4 shrink-0" />}
                        <span className="truncate">{f.path}</span>
                     </button>
                   )) : (
                     <p className="text-slate-500 text-sm mt-4 text-center">No artifacts found.</p>
                   )}
                </div>

                {/* File Viewer */}
                <div className="flex-1 w-2/3 bg-slate-950 flex flex-col overflow-hidden relative">
                   {selectedFile ? (
                     <>
                        <div className="bg-[#1e293b]/50 px-6 py-3 border-b border-slate-800 text-sm font-mono text-slate-300 flex items-center gap-2 shrink-0">
                          <FileText className="w-4 h-4 text-slate-500" />
                          {selectedFile.path}
                        </div>
                        <div className="flex-1 overflow-auto p-6 font-mono text-xs leading-relaxed">
                           {selectedFile.type === 'json' ? (
                             <pre className="text-emerald-300/90 whitespace-pre-wrap">{selectedFile.content}</pre>
                           ) : (
                             <div className="text-slate-300 whitespace-pre-wrap font-sans text-sm leading-relaxed max-w-3xl">
                               {selectedFile.content}
                             </div>
                           )}
                        </div>
                     </>
                   ) : (
                     <div className="flex-1 flex flex-col items-center justify-center text-slate-500">
                        <FileText className="w-12 h-12 mb-4 opacity-20" />
                        <p>Select an artifact to inspect its contents</p>
                     </div>
                   )}
                </div>
              </div>
            )}
          </main>
        </motion.div>
      </div>
    </AnimatePresence>
  );
}
