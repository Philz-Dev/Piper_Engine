"use client";
import React from 'react';
import { ChevronLeft, ChevronRight, Folder } from 'lucide-react';

interface SidebarProps {
  isSidebarExpanded: boolean;
  setIsSidebarExpanded: (expanded: boolean) => void;
  isDark: boolean;
}

export const Sidebar: React.FC<SidebarProps> = ({
  isSidebarExpanded,
  setIsSidebarExpanded,
  isDark,
}) => {
  return (
    <aside className={`${isSidebarExpanded ? 'w-60' : 'w-0 invisible pointer-events-none'} flex-shrink-0 border-r ${isDark ? 'border-white/5 bg-[#050505]' : 'border-gray-200 bg-zinc-50'} transition-all duration-300 ease-in-out z-20 flex flex-col h-full overflow-hidden`}>
      <div className="w-60 flex flex-col h-full">
        <div className="p-4 flex items-center border-b border-white/5 h-14">
          <span className={`text-xs font-mono truncate ${isDark ? 'text-zinc-400' : 'text-zinc-600'}`}>My Pipeline Project</span>
        </div>
        <div className="flex-1 overflow-y-auto">
          <div className="p-4 space-y-2">
            <div className="text-[10px] uppercase tracking-widest text-zinc-600 font-bold mb-2">Structure</div>
            <div className={`flex items-center gap-2 text-xs cursor-pointer ${isDark ? 'text-zinc-400 hover:text-white' : 'text-zinc-600 hover:text-black'}`}><Folder size={14} /> pipeline.yaml</div>
            <div className={`flex items-center gap-2 text-xs cursor-pointer ${isDark ? 'text-zinc-400 hover:text-white' : 'text-zinc-600 hover:text-black'}`}><Folder size={14} /> triggers/</div>
            <div className={`flex items-center gap-2 text-xs cursor-pointer ${isDark ? 'text-zinc-400 hover:text-white' : 'text-zinc-600 hover:text-black'}`}><Folder size={14} /> components/</div>
          </div>
        </div>
      </div>
    </aside>
  );
};