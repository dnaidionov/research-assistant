import { useState, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Edit2, Save, X, Play, BrainCircuit, AlertTriangle, FileText, Settings, Rocket, Activity } from "lucide-react";
import RunInspector from "./RunInspector";

interface JobDetailsProps {
  jobId: string;
  onClose: () => void;
  onRunLaunch: () => void;
  family: string; 
}

export default function JobDetails({ jobId, onClose, onRunLaunch, family }: JobDetailsProps) {
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  
  const [isEditing, setIsEditing] = useState(false);
  const [briefDraft, setBriefDraft] = useState("");
  const [configDraft, setConfigDraft] = useState("");
  
  const [saving, setSaving] = useState(false);
  const [dirtyFields, setDirtyFields] = useState(false);
  const [showUnsavedWarning, setShowUnsavedWarning] = useState(false);
  const [pendingAction, setPendingAction] = useState<(() => void) | null>(null);

  const [isRunning, setIsRunning] = useState(false);
  const [runLogs, setRunLogs] = useState("");
  const [selectedRun, setSelectedRun] = useState<string | null>(null);

  const fetchDetails = async () => {
    try {
      const res = await fetch(`/api/jobs/${jobId}`);
      const json = await res.json();
      setData(json);
      setBriefDraft(json.brief || "");
      setConfigDraft(json.config || "");
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchDetails();
  }, [jobId]);

  useEffect(() => {
    const hasChanges = data && (briefDraft !== data.brief || configDraft !== data.config);
    setDirtyFields(!!hasChanges);
  }, [briefDraft, configDraft, data]);

  const handleSave = async (autoSaveForRun = false) => {
    setSaving(true);
    try {
      await fetch(`/api/jobs/${jobId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ brief: briefDraft, config: configDraft })
      });
      setData((prev: any) => ({ ...prev, brief: briefDraft, config: configDraft }));
      setDirtyFields(false);
      if (!autoSaveForRun) setIsEditing(false);
      
      if (pendingAction) {
        pendingAction();
        setPendingAction(null);
      }
    } catch (err) {
      alert("Failed to save changes");
    } finally {
      setSaving(false);
      setShowUnsavedWarning(false);
    }
  };

  const handleCancelEdit = () => {
    if (dirtyFields) {
      setPendingAction(() => () => setIsEditing(false));
      setShowUnsavedWarning(true);
    } else {
      setIsEditing(false);
    }
  };

  const handleClose = () => {
    if (isEditing && dirtyFields) {
      setPendingAction(() => onClose);
      setShowUnsavedWarning(true);
    } else {
      onClose();
    }
  };

  const handleRun = async () => {
    if (isEditing && dirtyFields) {
      await handleSave(true);
    }
    
    setIsRunning(true);
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
          // auto scroll bottom would go here
        }
      }
    } catch (e) {
      setRunLogs((prev) => prev + `\nRun failed: ${e}\n`);
    } finally {
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
    <div className="flex flex-col h-full animate-in fade-in slide-in-from-right-8 duration-500">
      <header className="flex items-center justify-between pb-6 border-b border-slate-800">
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
          {data.runs?.length > 0 && family && (
             <button className="flex items-center gap-2 px-4 py-2 bg-purple-500/10 hover:bg-purple-500/20 text-purple-400 rounded-xl transition-colors border border-purple-500/20 text-sm font-medium">
               <Rocket className="w-4 h-4" /> Train {family}
             </button>
          )}

          {!isEditing ? (
            <button 
              onClick={() => setIsEditing(true)}
              className="flex items-center gap-2 px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-xl transition-colors text-sm font-medium"
            >
              <Edit2 className="w-4 h-4" /> Edit Configuration
            </button>
          ) : (
            <div className="flex items-center gap-2">
              <button 
                onClick={handleCancelEdit}
                className="px-4 py-2 text-slate-400 hover:text-slate-200 text-sm font-medium transition-colors"
              >
                Cancel
              </button>
              <button 
                onClick={() => handleSave()}
                disabled={!dirtyFields || saving}
                className="flex items-center gap-2 px-4 py-2 bg-emerald-500/10 hover:bg-emerald-500/20 text-emerald-400 disabled:opacity-50 disabled:grayscale rounded-xl transition-colors border border-emerald-500/20 text-sm font-medium"
              >
                <Save className="w-4 h-4" /> {saving ? "Saving..." : "Save Changes"}
              </button>
            </div>
          )}

          <div className="w-px h-6 bg-slate-800 mx-1" />

          <button 
            onClick={handleRun}
            className="flex items-center gap-2 px-6 py-2 bg-gradient-to-r from-brand-600 to-brand-500 hover:from-brand-500 hover:to-brand-400 text-white rounded-xl shadow-lg shadow-brand-500/20 transition-all font-medium"
          >
            <Play className="w-4 h-4" /> Launch Run
          </button>
        </div>
      </header>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mt-6 flex-1 overflow-y-auto">
        
        {/* Config Card */}
        <div className="bg-surface border border-slate-800/60 rounded-3xl p-6 flex flex-col shadow-xl">
          <div className="flex items-center gap-3 mb-4 text-brand-400 font-medium">
            <Settings className="w-5 h-5" /> Configuration (config.yaml)
          </div>
          {isEditing ? (
            <textarea
              value={configDraft}
              onChange={(e) => setConfigDraft(e.target.value)}
              className="flex-1 w-full bg-slate-900/80 border border-slate-700/50 rounded-xl p-4 text-sm font-mono text-slate-300 focus:outline-none focus:ring-2 focus:ring-brand-500 transition-all resize-none"
            />
          ) : (
            <pre className="flex-1 w-full bg-slate-900/50 border border-slate-800 rounded-xl p-4 text-sm font-mono text-slate-400 overflow-auto">
              {data.config || "No configuration found."}
            </pre>
          )}
        </div>

        {/* Brief Card */}
        <div className="bg-surface border border-slate-800/60 rounded-3xl p-6 flex flex-col shadow-xl">
          <div className="flex items-center gap-3 mb-4 text-emerald-400 font-medium">
            <FileText className="w-5 h-5" /> Research Brief (brief.md)
          </div>
          {isEditing ? (
            <textarea
              value={briefDraft}
              onChange={(e) => setBriefDraft(e.target.value)}
              className="flex-1 w-full bg-slate-900/80 border border-slate-700/50 rounded-xl p-4 text-sm font-sans text-slate-300 focus:outline-none focus:ring-2 focus:ring-emerald-500 transition-all resize-none"
            />
          ) : (
            <div className="flex-1 w-full bg-slate-900/50 border border-slate-800 rounded-xl p-4 text-sm text-slate-400 overflow-auto whitespace-pre-wrap font-sans">
              {data.brief || "No brief found."}
            </div>
          )}
        </div>
      </div>

      <div className="mt-6 bg-surface border border-slate-800/60 rounded-3xl p-6 shadow-xl">
        <h3 className="text-lg font-medium text-slate-200 mb-4 flex items-center gap-2">
          <Activity className="w-5 h-5 text-brand-400" /> Run History ({data.runs?.length || 0})
        </h3>
        {data.runs?.length > 0 ? (
          <div className="flex gap-3 overflow-x-auto pb-4">
            {data.runs.map((r: string) => (
              <div 
                key={r} 
                onClick={() => setSelectedRun(r)}
                className="bg-slate-900 border border-slate-700/50 px-5 py-3 rounded-2xl min-w-[160px] cursor-pointer hover:border-brand-500/50 transition-colors"
              >
                <p className="font-mono text-slate-300 font-medium">{r}</p>
                <p className="text-xs text-brand-400 mt-1 uppercase tracking-wider">Inspect Artifacts</p>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-slate-500 text-sm">No runs have been executed for this job yet.</p>
        )}
      </div>

      {selectedRun && (
        <RunInspector 
          jobId={jobId} 
          runId={selectedRun} 
          onClose={() => setSelectedRun(null)} 
        />
      )}

      <AnimatePresence>
        {showUnsavedWarning && (
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm">
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
                You have unsaved edits in your brief or configuration. Proceeding will discard them. Would you like to save before continuing?
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
                  onClick={() => handleSave()}
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
        {isRunning && (
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4 sm:p-8 bg-black/80 backdrop-blur-sm">
            <motion.div 
              initial={{ opacity: 0, scale: 0.95 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.95 }}
              className="bg-[#0f172a] border border-brand-500/50 rounded-3xl w-full max-w-4xl h-[80vh] flex flex-col overflow-hidden shadow-2xl shadow-brand-500/20"
            >
              <div className="flex justify-between items-center px-6 py-4 border-b border-slate-800 bg-[#1e293b]/50">
                <h3 className="text-xl font-medium text-brand-400 flex items-center gap-3">
                  <Activity className="w-5 h-5 animate-pulse" /> Executing Run Flow
                </h3>
                <button 
                  onClick={() => setIsRunning(false)}
                  className="p-2 text-slate-400 hover:text-white bg-slate-800 hover:bg-slate-700 rounded-full transition-colors"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>
              <div className="flex-1 p-6 overflow-y-auto bg-black font-mono text-sm">
                <pre className="text-emerald-400 whitespace-pre-wrap leading-relaxed">{runLogs || "Initializing matrix..."}</pre>
                <div className="h-4 pointer-events-none" ref={(el) => el?.scrollIntoView()} />
              </div>
            </motion.div>
          </div>
        )}
      </AnimatePresence>
    </div>
  );
}
