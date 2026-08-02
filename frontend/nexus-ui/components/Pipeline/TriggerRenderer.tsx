import React from 'react';
import { Trash2, RefreshCw, Plus } from 'lucide-react';

export const TriggerRenderer = ({ 
  trigger, 
  isDark, 
  isSelected, 
  getServiceColor, 
  getServiceIcon, 
  onSelect,
  onDelete,
  onReplace,
  onAddSibling
}: any) => {
  return (
    <div 
      onClick={(e) => { e.stopPropagation(); onSelect(trigger.id); }} 
      className={`flex items-center group py-2 relative cursor-pointer px-2 rounded-lg transition-colors ${isSelected ? (isDark ? 'bg-zinc-800' : 'bg-zinc-100') : ''}`}
    >
      <div className={`w-10 h-10 flex items-center justify-center border rounded-xl shadow-lg transition-all ${getServiceColor(trigger.service)} ${isSelected ? 'ring-2 ring-blue-500' : 'border-transparent'}`}>
        {getServiceIcon(trigger.service)}
      </div>
      <div className="flex flex-col ml-3 justify-center">
        <span className={`text-[11px] font-bold uppercase tracking-wider ${isDark ? 'text-zinc-500' : 'text-zinc-400'}`}>Trigger</span>
        <span className={`text-sm font-medium ${isDark ? 'text-white' : 'text-black'}`}>
          {trigger.service || 'Start'}
        </span>
      </div>

      {/* Action Controls: Absolute positioned to prevent layout shift */}
      <div className="absolute right-[-100px] opacity-0 group-hover:opacity-100 transition-opacity flex items-center gap-1 bg-white dark:bg-[#080808] border border-zinc-200 dark:border-zinc-800 rounded-lg p-1 shadow-xl">
        <button 
          onClick={(e) => { e.stopPropagation(); onAddSibling(trigger.id); }} 
          className="p-1.5 rounded hover:bg-zinc-100 dark:hover:bg-zinc-800 text-zinc-500"
          title="Add Sibling"
        > 
          <Plus size={14} /> 
        </button>
        <button 
          onClick={(e) => { e.stopPropagation(); onReplace(trigger.id); }} 
          className="p-1.5 rounded hover:bg-zinc-100 dark:hover:bg-zinc-800 text-blue-500"
          title="Replace"
        > 
          <RefreshCw size={14} /> 
        </button>
        <button 
          onClick={(e) => { e.stopPropagation(); onDelete(trigger.id); }} 
          className="p-1.5 rounded hover:bg-zinc-100 dark:hover:bg-zinc-800 text-red-500"
          title="Delete"
        > 
          <Trash2 size={14} /> 
        </button>
      </div>
    </div>
  );
};