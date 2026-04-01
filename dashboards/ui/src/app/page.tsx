"use client";

import { useEffect, useState } from "react";
import { 
  Briefcase, 
  FolderLock, 
  GlobeLock, 
  Activity, 
  Archive, 
  ChevronRight,
  Plus
} from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";

import NewJobModal from "./components/NewJobModal";

import JobDetails from "./components/JobDetails";

interface Job {
  job_id: string;
  display_name: string;
  local_path: string;
  visibility: "private" | "public";
  status: "active" | "archived";
  tags?: string[];
  family?: string;
}

export default function JobsDashboard() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [metadata, setMetadata] = useState<{ tags: string[]; families: string[] }>({ tags: [], families: [] });
  const [loading, setLoading] = useState(true);
  const [selectedJob, setSelectedJob] = useState<string | null>(null);
  const [isModalOpen, setIsModalOpen] = useState(false);

  useEffect(() => {
    async function loadJobs() {
      try {
        const res = await fetch("/api/jobs");
        const data = await res.json();
        setJobs(data.jobs || []);
        if (data.metadata) setMetadata(data.metadata);
      } catch (err) {
        console.error(err);
      } finally {
        setLoading(false);
      }
    }
    loadJobs();
  }, []);

  if (loading) {
    return (
      <div className="flex-1 flex flex-col justify-center items-center h-full min-h-[500px]">
        <motion.div
          animate={{ rotate: 360 }}
          transition={{ repeat: Infinity, duration: 1, ease: "linear" }}
        >
          <Activity className="w-10 h-10 text-brand-500 opacity-50" />
        </motion.div>
        <p className="mt-4 text-slate-400 font-light tracking-wide">Loading matrix...</p>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full gap-8 py-8 animate-in fade-in duration-500 overflow-hidden">
      {selectedJob ? (
        <JobDetails 
          jobId={selectedJob}
          family={jobs.find(j => j.job_id === selectedJob)?.family || 'neutral'}
          onClose={() => setSelectedJob(null)}
          onRunLaunch={() => alert('Run placeholder')}
        />
      ) : (
        <>
          <header className="flex items-center justify-between shrink-0">
            <div>
              <h1 className="text-4xl font-semibold tracking-tight text-transparent bg-clip-text bg-gradient-to-r from-brand-300 to-emerald-300">
                Research Jobs
              </h1>
              <p className="text-slate-400 mt-2 font-light text-lg">
                Manage your agentic knowledge spaces and pipelines.
              </p>
            </div>
            
            <button 
              onClick={() => setIsModalOpen(true)}
              className="flex items-center gap-2 bg-gradient-to-r from-brand-600 to-brand-500 hover:from-brand-500 hover:to-brand-400 text-white px-6 py-3 rounded-full shadow-lg shadow-brand-500/20 transition-all active:scale-95 font-medium tracking-wide cursor-pointer"
            >
              <Plus className="w-5 h-5" />
              <span>New Job</span>
            </button>
          </header>

          <main className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6 flex-1 overflow-y-auto pb-8 pr-2">
            <AnimatePresence>
              {jobs.map((job) => (
                <motion.div
                  layout
                  initial={{ opacity: 0, y: 20 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, scale: 0.95 }}
                  key={job.job_id}
                  onClick={() => setSelectedJob(job.job_id)}
                  className={`
                    group relative bg-surface border border-border rounded-3xl p-6 cursor-pointer overflow-hidden
                    transition-all duration-300 hover:bg-surface-hover hover:border-brand-500/30 hover:shadow-xl hover:shadow-brand-500/10
                    ${selectedJob === job.job_id ? "ring-2 ring-brand-500 ring-offset-2 ring-offset-slate-950" : ""}
                  `}
                >
                  <div className="absolute top-0 left-0 w-full h-1 bg-gradient-to-r from-transparent via-brand-500/50 to-transparent opacity-0 group-hover:opacity-100 transition-opacity" />
                  
                  <div className="flex justify-between items-start mb-4">
                    <div className="p-3 rounded-2xl bg-slate-800/50 text-brand-400 group-hover:bg-brand-500/10 group-hover:text-brand-300 transition-colors">
                      <Briefcase className="w-6 h-6" />
                    </div>
                    <div className="flex items-center gap-2">
                      <span className={`px-3 py-1 text-xs font-semibold uppercase tracking-wider rounded-full backdrop-blur-sm 
                        ${job.status === 'active' 
                          ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20' 
                          : 'bg-slate-500/10 text-slate-400 border border-slate-500/20'}`}>
                        {job.status === 'active' 
                          ? <span className="flex items-center gap-1"><Activity className="w-3 h-3"/> Active</span> 
                          : <span className="flex items-center gap-1"><Archive className="w-3 h-3"/> Archived</span>}
                      </span>
                    </div>
                  </div>
                  
                  <h2 className="text-xl font-medium text-slate-100 mb-2 truncate group-hover:text-white transition-colors" title={job.display_name}>
                    {job.display_name}
                  </h2>
                  
                  <p className="text-slate-400 text-sm font-mono truncate mb-6" title={job.job_id}>
                    {job.job_id}
                  </p>
                  
                  <div className="flex flex-wrap items-center gap-4 mt-auto">
                    <div className="flex items-center gap-1.5 text-xs text-slate-400 bg-slate-800/50 px-3 py-1.5 rounded-lg border border-slate-700/50">
                      {job.visibility === 'private' ? <FolderLock className="w-3.5 h-3.5" /> : <GlobeLock className="w-3.5 h-3.5" />}
                      <span className="capitalize">{job.visibility}</span>
                    </div>
                    
                    {job.tags?.map((tag) => (
                      <span key={tag} className="text-xs text-slate-300 bg-slate-800 px-3 py-1.5 rounded-lg border border-slate-700">
                        {tag}
                      </span>
                    ))}
                  </div>

                  {selectedJob === job.job_id && (
                    <motion.div 
                      initial={{ opacity: 0 }} 
                      animate={{ opacity: 1 }} 
                      className="absolute bottom-4 right-4 bg-brand-500 text-white p-2 rounded-full shadow-lg"
                    >
                      <ChevronRight className="w-5 h-5" />
                    </motion.div>
                  )}
                </motion.div>
              ))}
            </AnimatePresence>

            {jobs.length === 0 && !loading && (
              <div className="col-span-1 md:col-span-2 lg:col-span-3 flex-1 flex flex-col items-center justify-center border-2 border-dashed border-slate-800 rounded-3xl p-12 text-center">
                <Briefcase className="w-16 h-16 text-slate-700 mb-4" />
                <h3 className="text-xl font-medium text-slate-300">No Jobs Found</h3>
                <p className="text-slate-500 mt-2 max-w-md">You haven't created any research jobs yet. Tap 'New Job' to initialize a workspace.</p>
              </div>
            )}
          </main>
        </>
      )}

      <NewJobModal
        isOpen={isModalOpen}
        onClose={() => setIsModalOpen(false)}
        metadata={metadata}
        onSuccess={(newJob) => {
          setJobs([newJob, ...jobs]);
          setSelectedJob(newJob.job_id);
        }}
      />
    </div>
  );
}
