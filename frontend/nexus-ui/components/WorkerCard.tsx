import React from 'react';
import { Play, Square, Settings, Database } from 'lucide-react';

interface WorkerProps { name: string; status: 'running' | 'stopped'; }

export const WorkerCard = ({ name, status }: WorkerProps) => {
  const isRunning = status === 'running';

  return (
    <div className="bg-[#0c0c0c] border border-slate-800 p-6 rounded-2xl hover:border-cyan-500/40 transition-all group">
      <div className="flex justify-between items-start mb-6">
        <div className="flex items-center gap-3">
          <div className={`w-3 h-3 rounded-full ${isRunning ? 'bg-cyan-500 shadow-[0_0_10px_#22d3ee]' : 'bg-slate-700'}`} />
          <h3 className="text-lg font-bold tracking-tight">{name}</h3>
        </div>
        <button className="text-slate-500 hover:text-white transition-colors">
          <Settings size={18} />
        </button>
      </div>

      <div className="space-y-3 mb-8">
        <div className="flex justify-between text-sm">
          <span className="text-slate-500">Instance Type</span>
          <span className="text-slate-300 font-mono">Standard-v1</span>
        </div>
        <div className="flex justify-between text-sm">
          <span className="text-slate-500">Database Connection</span>
          <span className="text-cyan-400 flex items-center gap-1"><Database size={12}/> Healthy</span>
        </div>
      </div>

      <div className="flex gap-3">
        <button className={`flex-1 py-2.5 rounded-xl font-semibold flex items-center justify-center gap-2 transition-all ${
          isRunning ? 'bg-slate-800 text-slate-400 cursor-not-allowed' : 'bg-cyan-600 hover:bg-cyan-500 text-white shadow-lg shadow-cyan-900/20'
        }`}>
          <Play size={16} /> Deploy
        </button>
        <button className="px-4 py-2.5 bg-slate-900 border border-slate-800 rounded-xl hover:bg-red-950/30 hover:text-red-400 hover:border-red-900/50 transition-all">
          <Square size={16} />
        </button>
      </div>
    </div>
  );
};