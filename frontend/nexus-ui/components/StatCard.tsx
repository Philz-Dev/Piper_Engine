import React from 'react';

interface StatProps { icon: React.ReactNode; label: string; value: string; color: 'cyan' | 'violet'; }

export const StatCard = ({ icon, label, value, color }: StatProps) => {
  const colorMap = {
    cyan: "text-cyan-400 border-cyan-500/20 bg-cyan-500/5",
    violet: "text-violet-400 border-violet-500/20 bg-violet-500/5"
  };

  return (
    <div className={`p-4 rounded-xl border ${colorMap[color]} flex items-center gap-4`}>
      <div className="p-2 bg-slate-900 rounded-lg">{icon}</div>
      <div>
        <p className="text-slate-500 text-xs uppercase tracking-wider">{label}</p>
        <p className="text-2xl font-bold font-mono">{value}</p>
      </div>
    </div>
  );
};