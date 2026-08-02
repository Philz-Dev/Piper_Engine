"use client";
import React, { useState } from 'react';
import { Box, Zap, Terminal, Settings, CreditCard } from 'lucide-react';

interface SidebarProps {
  activeTab: string;
  setActiveTab: (tab: string) => void;
  theme: 'dark' | 'light';
}

const Sidebar: React.FC<SidebarProps> = ({ activeTab, setActiveTab, theme }) => {
  const [isHovered, setIsHovered] = useState(false);
  const isDark = theme === 'dark';
  const isCompact = activeTab === 'builds';
  const isExpanded = !isCompact || isHovered;

  const menu = [
    { id: 'ask-gordon', label: 'Ask Gordon', icon: <Terminal size={16} />, beta: true },
    { id: 'containers', label: 'Dashboard', icon: <Box size={16} /> },
    { id: 'subscription', label: 'Subscription', icon: <CreditCard size={16} /> },
    { id: 'builds', label: 'Builds', icon: <Zap size={16} /> },
    { id: 'sep1', type: 'separator' },
    { id: 'settings', label: 'Settings', icon: <Settings size={16} /> },
  ];

  return (
    <aside 
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
      className={`${!isExpanded ? 'w-16' : 'w-[180px]'} border-r h-full flex flex-col shrink-0 bg-black border-[#262626] transition-all duration-300 ease-in-out overflow-hidden`}
    >
      <nav className="flex-1 px-3 mt-4 flex flex-col gap-1">
        {menu.map((item, i) => {
          if (item.type === 'separator') return (
            <hr key={i} className={`my-4 opacity-10 border-white transition-all duration-300 ${!isExpanded ? 'mx-2' : ''}`} />
          );
          
          const active = activeTab === item.id;
          
          return (
            <button
              key={item.id}
              onClick={() => setActiveTab(item.id!)}
              className={`w-full flex items-center justify-start gap-3 px-3 py-2.5 rounded transition-all group ${
                active 
                  ? (isDark ? 'bg-white/10 text-white font-bold' : 'bg-[lightgray] text-black font-bold') 
                  : (isDark ? 'text-white/40 hover:text-white' : 'text-slate-500 hover:text-slate-300')
              }`}
            >
              <span className={`shrink-0 transition-colors ${active ? (isDark ? 'text-white' : 'text-black') : ''}`}>
                {React.cloneElement(item.icon as React.ReactElement, { size: 15, strokeWidth: 2 })}
              </span>
              
              {/* Labels and Badges are hidden via opacity instead of being removed from DOM */}
              <div className={`flex items-center justify-between flex-1 overflow-hidden transition-opacity duration-300 ${isExpanded ? 'opacity-100' : 'opacity-0 pointer-events-none'}`}>
                <span className="text-[11px] uppercase tracking-wide font-medium whitespace-nowrap">
                  {item.label}
                </span>
                {item.beta && (
                  <span className={`text-[7px] font-black border px-1 rounded uppercase ${
                    active 
                      ? (isDark ? 'border-white/40 text-white' : 'border-black/20 text-black') 
                      : 'border-white/10 text-white/20'
                  }`}>
                    Beta
                  </span>
                )}
              </div>
            </button>
          );
        })}
      </nav>
    </aside>
  );
};

export default Sidebar;