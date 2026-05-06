"use client";
import React from 'react';
import { Box, Layers, Database, Zap, Activity, Globe, Puzzle, Terminal, ShieldCheck, Settings } from 'lucide-react';

interface SidebarProps {
  activeTab: string;
  setActiveTab: (tab: string) => void;
  theme: 'dark' | 'light';
}

const Sidebar: React.FC<SidebarProps> = ({ activeTab, setActiveTab, theme }) => {
  const isDark = theme === 'dark';

  const menu = [
    { id: 'gordon', label: 'Ask Gordon', icon: <Terminal size={16} />, beta: true },
    { id: 'containers', label: 'Dashboard', icon: <Box size={16} /> },
    { id: 'images', label: 'Images', icon: <Layers size={16} /> },
    { id: 'volumes', label: 'Volumes', icon: <Database size={16} /> },
    { id: 'k8s', label: 'Kubernetes', icon: <Activity size={16} /> },
    { id: 'builds', label: 'Builds', icon: <Zap size={16} /> },
    { id: 'sep1', type: 'separator' },
    { id: 'models', label: 'Models', icon: <Globe size={16} /> },
    { id: 'mcp', label: 'MCP Toolkit', icon: <Puzzle size={16} />, beta: true },
    { id: 'sep2', type: 'separator' },
    { id: 'hub', label: 'Piper Hub', icon: <Globe size={16} /> },
    { id: 'scout', label: 'Piper Scout', icon: <ShieldCheck size={16} /> },
    { id: 'settings', label: 'Settings', icon: <Settings size={16} /> },
  ];

  return (
    <aside className="w-[180px] border-r h-full flex flex-col shrink-0 bg-black border-[#262626]">
      <nav className="flex-1 px-3 mt-4 flex flex-col gap-1">
        {menu.map((item, i) => {
          if (item.type === 'separator') return (
            <hr key={i} className="my-4 opacity-10 border-white" />
          );
          
          const active = activeTab === item.id;
          
          return (
            <button
              key={item.id}
              onClick={() => setActiveTab(item.id!)}
              className={`w-full flex items-center justify-between px-3 py-2.5 rounded transition-all group ${
                active 
                  ? (isDark ? 'bg-white/10 text-white font-bold' : 'bg-[lightgray] text-black font-bold') 
                  : (isDark ? 'text-white/40 hover:text-white' : 'text-slate-500 hover:text-slate-300')
              }`}
            >
              <div className="flex items-center gap-3">
                <span className={active ? (isDark ? 'text-white' : 'text-black') : 'transition-colors'}>
                  {React.cloneElement(item.icon as React.ReactElement, { size: 15, strokeWidth: 2 })}
                </span>
                <span className="text-[11px] uppercase tracking-wide font-medium">{item.label}</span>
              </div>
              {item.beta && (
                <span className={`text-[7px] font-black border px-1 rounded uppercase ${
                  active 
                    ? (isDark ? 'border-white/40 text-white' : 'border-black/20 text-black') 
                    : 'border-white/10 text-white/20'
                }`}>
                  Beta
                </span>
              )}
            </button>
          );
        })}
      </nav>
    </aside>
  );
};

export default Sidebar;