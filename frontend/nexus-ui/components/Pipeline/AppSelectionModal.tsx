"use client";
import React, { useState, useEffect } from 'react';
import { X, ChevronLeft, ChevronRight, Search } from 'lucide-react';
import { AVAILABLE_APPS } from '@/components/Pipeline/PipelineUtils';

interface AppSelectionModalProps {
  isOpen: boolean;
  onClose: () => void;
  isDark: boolean;
  appCategories: string[];
  onAddStep: (serviceName: string, category: string) => void;
}

export const AppSelectionModal = ({ 
  isOpen, 
  onClose, 
  isDark, 
  appCategories, 
  onAddStep 
}: AppSelectionModalProps) => {
  const [selectedCategory, setSelectedCategory] = useState('All');
  const [selectedApp, setSelectedApp] = useState<any>(null);
  const [searchQuery, setSearchQuery] = useState('');

  // Reset drill-down when modal closes or category changes
  useEffect(() => {
    if (!isOpen) {
      setSelectedApp(null);
      setSearchQuery('');
      setSelectedCategory('All');
    }
  }, [isOpen]);

  useEffect(() => {
    setSelectedApp(null);
    setSearchQuery('');
  }, [selectedCategory]);

  if (!isOpen) return null;

  // Pre-calculate filtered lists
  const filteredApps = AVAILABLE_APPS.filter(app => 
    (selectedCategory === 'All' || app.actions?.some((a: any) => a.category === selectedCategory)) && 
    (app.name.toLowerCase().includes(searchQuery.toLowerCase()))
  );

  const filteredActions = (selectedApp?.actions || []).filter((action: any) => 
    (selectedCategory === 'All' || action.category === selectedCategory) && 
    (action.name.toLowerCase().includes(searchQuery.toLowerCase()))
  );

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/40 backdrop-blur-sm p-4 animate-in fade-in duration-200">
      <div className={`w-[560px] rounded-2xl shadow-2xl border flex flex-col h-[80vh] overflow-hidden ${isDark ? 'bg-[#121212] border-white/10' : 'bg-white border-gray-200'}`}>
        
        {/* Header / Search */}
        <div className="p-4 border-b border-white/5">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-3">
              {selectedApp && (
                <button onClick={() => setSelectedApp(null)} className={`p-1 rounded-md transition-colors ${isDark ? 'hover:bg-zinc-800' : 'hover:bg-zinc-100'}`}>
                  <ChevronLeft size={18} />
                </button>
              )}
              <h2 className="text-lg font-semibold tracking-tight">
                {selectedApp ? selectedApp.name : 'Add Step'}
              </h2>
            </div>
            <button 
              onClick={onClose} 
              className={`p-1.5 rounded-full transition-colors ${isDark ? 'hover:bg-zinc-800' : 'hover:bg-zinc-100'}`}
            >
              <X size={18} />
            </button>
          </div>

          <div className="relative group">
            <Search className={`absolute left-3 top-1/2 -translate-y-1/2 ${isDark ? 'text-zinc-500' : 'text-zinc-400'}`} size={16} />
            <input
              autoFocus
              placeholder={`Search ${selectedApp ? 'actions' : 'apps'}...`}
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className={`w-full pl-10 pr-4 py-2.5 rounded-lg border outline-none transition-all ${isDark ? 'bg-zinc-900 border-zinc-800 focus:border-blue-500 text-white' : 'bg-zinc-50 border-gray-200 focus:border-blue-500'}`}
            />
          </div>
        </div>

        {/* Category Filter */}
        {!selectedApp && (
          <div className="flex flex-wrap items-center gap-1.5 px-4 pt-4 pb-2">
            {appCategories.map((cat) => (
              <button
                key={cat}
                onClick={() => setSelectedCategory(cat)}
                className={`px-3 py-1.5 rounded-full text-xs font-medium whitespace-nowrap transition-all ${
                  selectedCategory === cat
                    ? 'bg-blue-600 text-white shadow-sm'
                    : isDark ? 'bg-zinc-800 text-zinc-400 hover:bg-zinc-700' : 'bg-zinc-100 text-zinc-600 hover:bg-zinc-200'
                }`}
              >
                {cat}
              </button>
            ))}
          </div>
        )}

        {/* Content Area */}
        <div className="flex-1 overflow-y-auto p-2 scrollbar-thin scrollbar-thumb-zinc-700 scrollbar-track-transparent">
          <div className="space-y-1">
            {!selectedApp ? (
              filteredApps.length > 0 ? (
                filteredApps.map((app) => (
                  <button 
                    key={app.name} 
                    onClick={() => setSelectedApp(app)} 
                    className={`w-full flex items-center justify-between px-4 py-3 rounded-lg transition-all border group ${isDark ? 'hover:bg-zinc-800/50 border-transparent hover:border-zinc-700' : 'hover:bg-zinc-50 border-transparent hover:border-gray-100'}`}
                  >
                    <div className="flex items-center gap-3">
                      <div className={`w-8 h-8 rounded flex items-center justify-center ${isDark ? 'bg-zinc-800 text-zinc-300' : 'bg-zinc-100 text-zinc-600'}`}>
                          {app.icon ? (
                            <img src={app.icon} alt={app.name} className="w-5 h-5 object-contain" />
                          ) : (
                            <span className="font-bold text-xs">{app.name.charAt(0)}</span>
                          )}
                      </div>
                      <div className="flex flex-col items-start">
                        <span className="text-sm font-medium">{app.name}</span>
                        <span className="text-[11px] opacity-60">{app.desc}</span>
                      </div>
                    </div>
                    <ChevronRight size={14} className="opacity-0 group-hover:opacity-100 transition-opacity" />
                  </button>
                ))
              ) : (
                <div className="p-8 text-center text-zinc-500 text-sm">
                  No apps available in this category.
                </div>
              )
            ) : (
              filteredActions.length > 0 ? (
                filteredActions.map((action: any) => (
                  <button 
                    key={action.name} 
                    onClick={() => onAddStep(action.service, action.category)} 
                    className={`w-full flex items-center justify-between px-4 py-3 rounded-lg transition-all ${isDark ? 'hover:bg-zinc-800/50' : 'hover:bg-zinc-50'}`}
                  >
                     <div className="flex items-center gap-3">
                        <div className={`w-2 h-2 rounded-full ${isDark ? 'bg-blue-500' : 'bg-blue-600'}`} />
                        <span className="text-sm font-medium">{action.name}</span>
                     </div>
                     <span className="text-[10px] uppercase tracking-wider opacity-50 px-2 py-0.5 rounded border border-current">{action.category}</span>
                  </button>
                ))
              ) : (
                <div className="p-8 text-center text-zinc-500 text-sm">
                  No actions available for this selection.
                </div>
              )
            )}
          </div>
        </div>
      </div>
    </div>
  );
};