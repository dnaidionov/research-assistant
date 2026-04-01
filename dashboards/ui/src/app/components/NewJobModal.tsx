import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { X, Briefcase, TagIcon, Plus } from "lucide-react";

interface NewJobModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSuccess: (job: any) => void;
  metadata: { tags: string[]; families: string[] };
}

export default function NewJobModal({ isOpen, onClose, onSuccess, metadata }: NewJobModalProps) {
  const [name, setName] = useState("");
  const [family, setFamily] = useState("neutral");
  const [newFamily, setNewFamily] = useState("");
  const [tags, setTags] = useState<string[]>([]);
  const [tagInput, setTagInput] = useState("");
  const [visibility, setVisibility] = useState<"private" | "public">("private");
  const [brief, setBrief] = useState("");
  const [loading, setLoading] = useState(false);
  
  const handleAddTag = () => {
    if (tagInput.trim() && !tags.includes(tagInput.trim())) {
      setTags([...tags, tagInput.trim()]);
      setTagInput("");
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;

    setLoading(true);
    try {
      const res = await fetch("/api/jobs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: name.trim(),
          family: family === "__new__" ? newFamily.trim() : family,
          visibility,
          tags,
          brief_excerpt: brief.trim()
        }),
      });
      const data = await res.json();
      if (data.success) {
        onSuccess(data.job);
        onClose();
        setName("");
        setFamily("neutral");
        setNewFamily("");
        setTags([]);
        setVisibility("private");
        setBrief("");
      } else {
        alert(data.error);
      }
    } catch (err) {
      console.error(err);
      alert("Failed to create job");
    } finally {
      setLoading(false);
    }
  };

  const jobIdPreview = name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/(^-|-$)/g, '');

  return (
    <AnimatePresence>
      {isOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 sm:p-8">
          <motion.div 
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="absolute inset-0 bg-black/60 backdrop-blur-sm"
            onClick={onClose}
          />
          <motion.div 
            initial={{ opacity: 0, scale: 0.95, y: 10 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95, y: -10 }}
            className="relative bg-[#0f172a] border border-slate-800 rounded-3xl w-full max-w-2xl overflow-hidden shadow-2xl flex flex-col z-10"
          >
            <div className="flex justify-between items-center px-8 py-6 border-b border-slate-800/50 bg-[#1e293b]/30">
              <h2 className="text-2xl font-semibold flex items-center gap-3">
                <div className="p-2 bg-brand-500/10 rounded-xl text-brand-400">
                  <Briefcase className="w-6 h-6" />
                </div>
                Initialize Workspace
              </h2>
              <button type="button" onClick={onClose} className="p-2 hover:bg-slate-800 rounded-full transition-colors text-slate-400 hover:text-white">
                <X className="w-5 h-5" />
              </button>
            </div>

            <form onSubmit={handleSubmit} className="p-8 flex flex-col gap-6 overflow-y-auto max-h-[70vh]">
              <div className="flex flex-col gap-2">
                <label className="text-sm font-medium text-slate-400 uppercase tracking-widest">Display Name</label>
                <input 
                  type="text" 
                  value={name} 
                  onChange={e => setName(e.target.value)} 
                  required
                  className="bg-slate-900 border border-slate-700/50 rounded-xl px-4 py-3 text-white focus:outline-none focus:ring-2 focus:ring-brand-500 transition-all font-medium placeholder:text-slate-600"
                  placeholder="e.g. Through-Wall Georadar Upgrade"
                />
                <p className="text-xs text-slate-500 mt-1 font-mono">
                  ID generated: <span className="text-brand-400">{jobIdPreview || "..."}</span>
                </p>
              </div>

              <div className="flex gap-4">
                <div className="flex flex-col gap-2 flex-1">
                  <label className="text-sm font-medium text-slate-400 uppercase tracking-widest">Research Family</label>
                  <select 
                    value={family}
                    onChange={e => setFamily(e.target.value)}
                    className="bg-slate-900 border border-slate-700/50 rounded-xl px-4 py-3 text-white focus:outline-none focus:ring-2 focus:ring-brand-500 outline-none appearance-none"
                  >
                    {metadata.families.map(fam => (
                      <option key={fam} value={fam}>{fam}</option>
                    ))}
                    {!metadata.families.includes('neutral') && <option value="neutral">neutral</option>}
                    <option value="__new__">+ Create New Family</option>
                  </select>
                  {family === "__new__" && (
                    <input 
                      type="text" 
                      value={newFamily} 
                      onChange={e => setNewFamily(e.target.value)} 
                      placeholder="New family name"
                      className="mt-2 bg-slate-900 border border-brand-500/50 rounded-xl px-4 py-3 text-white focus:outline-none focus:ring-2 focus:ring-brand-500 placeholder:text-slate-600"
                      required
                    />
                  )}
                </div>
                
                <div className="flex flex-col gap-2 flex-1">
                  <label className="text-sm font-medium text-slate-400 uppercase tracking-widest">Visibility</label>
                  <select 
                    value={visibility}
                    onChange={e => setVisibility(e.target.value as any)}
                    className="bg-slate-900 border border-slate-700/50 rounded-xl px-4 py-3 text-white focus:outline-none focus:ring-2 focus:ring-brand-500 outline-none appearance-none"
                  >
                    <option value="private">Private</option>
                    <option value="public">Public</option>
                  </select>
                </div>
              </div>

              <div className="flex flex-col gap-2">
                <label className="text-sm font-medium text-slate-400 uppercase tracking-widest">Tags</label>
                <div className="bg-slate-900 border border-slate-700/50 rounded-xl p-2 flex flex-wrap gap-2 focus-within:ring-2 focus-within:ring-brand-500 transition-all">
                  {tags.map(tag => (
                    <span key={tag} className="flex items-center gap-1 bg-slate-800 text-brand-300 px-3 py-1 rounded-lg text-sm font-medium border border-brand-500/20">
                      <TagIcon className="w-3 h-3" /> {tag}
                      <button type="button" onClick={() => setTags(tags.filter(t => t !== tag))} className="ml-1 text-slate-500 hover:text-white">
                        <X className="w-3 h-3" />
                      </button>
                    </span>
                  ))}
                  <input 
                    type="text" 
                    value={tagInput}
                    onChange={e => setTagInput(e.target.value)}
                    onKeyDown={e => { if(e.key === 'Enter') { e.preventDefault(); handleAddTag(); } }}
                    placeholder={tags.length === 0 ? "Type and press enter..." : ""}
                    className="bg-transparent text-white outline-none flex-1 min-w-[120px] px-2 py-1 placeholder:text-slate-600"
                  />
                  <button type="button" onClick={handleAddTag} className="hidden" />
                </div>
                <div className="flex flex-wrap gap-2 mt-2">
                  {metadata.tags.filter(t => !tags.includes(t)).map(tag => (
                    <button 
                      type="button" 
                      key={tag}
                      onClick={() => setTags([...tags, tag])}
                      className="text-xs px-2 py-1 rounded-md bg-slate-800/50 text-slate-400 hover:text-white hover:bg-slate-800 border border-slate-700/50 transition-colors cursor-pointer flex items-center gap-1"
                    >
                      <Plus className="w-3 h-3" /> {tag}
                    </button>
                  ))}
                </div>
              </div>

              <div className="flex flex-col gap-2">
                <label className="text-sm font-medium text-slate-400 uppercase tracking-widest">Initial Brief (Optional)</label>
                <textarea 
                  value={brief} 
                  onChange={e => setBrief(e.target.value)} 
                  rows={4}
                  className="bg-slate-900 border border-slate-700/50 rounded-xl px-4 py-3 text-white focus:outline-none focus:ring-2 focus:ring-brand-500 transition-all placeholder:text-slate-600 resize-none font-sans"
                  placeholder="A short description used to populate the initial brief.md file..."
                />
              </div>

              <div className="mt-4 flex justify-end gap-4 pt-6 border-t border-slate-800/50">
                <button 
                  type="button" 
                  onClick={onClose}
                  className="px-6 py-3 rounded-full font-medium text-slate-300 hover:bg-slate-800 transition-colors cursor-pointer"
                >
                  Cancel
                </button>
                <button 
                  type="submit" 
                  disabled={loading || !name.trim()}
                  className="px-8 py-3 rounded-full font-medium text-white bg-gradient-to-r from-brand-600 to-brand-500 hover:from-brand-500 hover:to-brand-400 shadow-lg shadow-brand-500/20 disabled:opacity-50 disabled:cursor-not-allowed transition-all active:scale-95 cursor-pointer"
                >
                  {loading ? "Creating..." : "Create Job"}
                </button>
              </div>
            </form>
          </motion.div>
        </div>
      )}
    </AnimatePresence>
  );
}
