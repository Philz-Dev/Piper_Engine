"use client";
import React, { useState } from 'react';
import { 
  ChevronLeft, ChevronRight, ChevronDown, Database, Plus, 
  Settings, Trash2, Code, Folder, FolderOpen, FileText 
} from 'lucide-react';

interface SidebarProps {
  isSidebarExpanded: boolean;
  setIsSidebarExpanded: (expanded: boolean) => void;
  isDark: boolean;
  clients: any[];
  fileTree?: any[];
  onSelectAutomation?: (clientName: string, automation: any) => void;
  onSelectScript?: (clientName: string, script: any) => void;
  onSelectFile?: (filePath: string) => void;
}

export const Sidebar = ({ 
  isSidebarExpanded, 
  setIsSidebarExpanded, 
  isDark,
  clients,
  fileTree = [],
  onSelectAutomation,
  onSelectScript,
  onSelectFile
}: SidebarProps) => {
  const [activeTab, setActiveTab] = useState<'projects' | 'explorer'>('projects');
  const [expandedClients, setExpandedClients] = useState<Record<string, boolean>>({});
  const [expandedFolders, setExpandedFolders] = useState<Record<string, boolean>>({});
  const [activeItem, setActiveItem] = useState<string | null>(null);

  const toggleClient = (id: number) => {
    setExpandedClients(prev => ({ ...prev, [id]: !prev[id] }));
  };

  const toggleFolder = (path: string) => {
    setExpandedFolders(prev => ({ ...prev, [path]: !prev[path] }));
  };

  // Recursive component to render file tree nodes like VS Code
  const renderExplorerTree = (nodes: any[], depth = 0) => {
    if (!Array.isArray(nodes)) return null;

    return nodes.map((node, index) => {
      const isExpanded = expandedFolders[node.path];
      const isSelected = activeItem === node.path;

      if (node.type === 'directory') {
        return (
          <div key={node.path || index}>
            <div 
              onClick={() => toggleFolder(node.path)}
              className={`flex items-center gap-1.5 py-1 px-2 text-sm cursor-pointer rounded select-none ${
                isDark ? 'hover:bg-white/5 text-zinc-300' : 'hover:bg-black/5 text-zinc-800'
              }`}
              style={{ paddingLeft: `${depth * 12 + 8}px` }}
            >
              {isExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
              {isExpanded ? <FolderOpen size={14} className="text-blue-400" /> : <Folder size={14} className="text-blue-400" />}
              <span className="truncate">{node.name}</span>
            </div>
            {isExpanded && node.children && (
              <div>{renderExplorerTree(node.children, depth + 1)}</div>
            )}
          </div>
        );
      }

      return (
        <div 
          key={node.path || index}
          onClick={(e) => {
            e.stopPropagation();
            setActiveItem(node.path);
            onSelectFile?.(node.path);
          }}
          className={`flex items-center gap-2 py-1 px-2 text-sm cursor-pointer rounded ${
            isSelected 
              ? (isDark ? 'bg-blue-500/20 text-white font-medium' : 'bg-blue-500/15 text-blue-900 font-medium')
              : (isDark ? 'text-zinc-400 hover:text-white hover:bg-blue-500/10' : 'text-zinc-700 hover:text-black hover:bg-blue-500/10')
          }`}
          style={{ paddingLeft: `${depth * 12 + 24}px` }}
        >
          <FileText size={14} className={isDark ? 'text-zinc-500' : 'text-zinc-400'} />
          <span className="truncate">{node.name}</span>
        </div>
      );
    });
  };

  if (!isSidebarExpanded) {
    return (
      <div className={`w-12 border-r flex flex-col items-center py-4 gap-4 ${isDark ? 'bg-[#0a0a0a] border-white/5 text-zinc-400' : 'bg-zinc-50 border-gray-200 text-zinc-700'}`}>
        <button onClick={() => setIsSidebarExpanded(true)} className={`p-2 rounded-md ${isDark ? 'hover:bg-blue-500/20' : 'hover:bg-blue-500/10'}`}>
          <ChevronRight size={16} />
        </button>
      </div>
    );
  }

  return (
    <div className={`w-64 border-r flex flex-col ${isDark ? 'bg-[#0a0a0a] border-white/5 text-zinc-200' : 'bg-zinc-50 border-gray-200 text-zinc-800'}`}>
      
      {/* Sidebar Header with View Toggle Tabs */}
      <div className={`h-10 flex items-center justify-between px-3 border-b ${isDark ? 'border-white/5' : 'border-gray-200'}`}>
        <div className="flex items-center gap-2">
          <button 
            onClick={() => setActiveTab('projects')} 
            className={`text-xs font-bold uppercase tracking-wider px-2 py-1 rounded transition-colors ${
              activeTab === 'projects' 
                ? (isDark ? 'bg-white/10 text-white' : 'bg-black/10 text-black') 
                : 'text-zinc-500 hover:text-zinc-300'
            }`}
          >
            Projects
          </button>
          <button 
            onClick={() => setActiveTab('explorer')} 
            className={`text-xs font-bold uppercase tracking-wider px-2 py-1 rounded transition-colors ${
              activeTab === 'explorer' 
                ? (isDark ? 'bg-white/10 text-white' : 'bg-black/10 text-black') 
                : 'text-zinc-500 hover:text-zinc-300'
            }`}
          >
            Explorer
          </button>
        </div>
        <button onClick={() => setIsSidebarExpanded(false)}>
          <ChevronLeft size={16} className={isDark ? 'text-zinc-500' : 'text-zinc-600'} />
        </button>
      </div>
      
      {/* Sidebar Content Body */}
      <div className="flex-1 overflow-y-auto py-2">
        {activeTab === 'projects' ? (
          // Existing Projects / Automations view[cite: 7]
          clients.map(client => (
            <div key={client.id} className="px-2 mb-2">
              <div 
                className={`flex items-center justify-between group py-1.5 px-2 rounded cursor-pointer ${isDark ? 'hover:bg-white/5' : 'hover:bg-black/5'}`} 
                onClick={() => toggleClient(client.id)}
              >
                <div className={`flex items-center gap-2 text-base ${isDark ? 'text-zinc-300' : 'text-zinc-800'}`}>
                  {expandedClients[client.id] ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                  <Database size={14} className="text-blue-500" />
                  <span className="font-medium">{client.name}</span>
                </div>
                <button className={`opacity-0 group-hover:opacity-100 p-0.5 rounded ${isDark ? 'hover:bg-white/10 text-zinc-400' : 'hover:bg-black/10 text-zinc-600'}`}>
                  <Plus size={12} />
                </button>
              </div>

              {expandedClients[client.id] && (
                <div className={`ml-4 border-l pl-2 mt-1 ${isDark ? 'border-white/5' : 'border-gray-200'}`}>
                  <div className={`text-xs uppercase font-bold mb-1 mt-2 ${isDark ? 'text-zinc-600' : 'text-zinc-500'}`}>Automations</div>
                  {client.automations.map((auto: any, i: number) => {
                    const autoName = typeof auto === 'object' && auto !== null ? (auto.name || auto.file_path || 'Automation') : auto;
                    const isSelected = activeItem === autoName;
                    return (
                      <div 
                        key={i} 
                        onClick={(e) => {
                          e.stopPropagation();
                          setActiveItem(autoName);
                          onSelectAutomation?.(client.name, auto);
                        }}
                        className={`flex items-center justify-between py-1 px-2 text-sm cursor-pointer rounded ${
                          isSelected 
                            ? (isDark ? 'bg-blue-500/20 text-white font-medium' : 'bg-blue-500/15 text-blue-900 font-medium')
                            : (isDark ? 'text-zinc-400 hover:text-white hover:bg-blue-500/10' : 'text-zinc-700 hover:text-black hover:bg-blue-500/10')
                        }`}
                      >
                        <div className="flex items-center gap-2">
                          <Settings size={12}/> 
                          {autoName}
                        </div>
                        <button className={`hover:text-red-500 ${isDark ? 'text-zinc-500' : 'text-zinc-400'}`} onClick={(e) => e.stopPropagation()}>
                          <Trash2 size={10}/>
                        </button>
                      </div>
                    );
                  })}
                  
                  <div className={`text-xs uppercase font-bold mb-1 mt-3 ${isDark ? 'text-zinc-600' : 'text-zinc-500'}`}>Scripts</div>
                  {client.scripts.map((script: any, i: number) => {
                    const scriptName = typeof script === 'object' && script !== null ? (script.name || script.file_path || 'Script') : script;
                    const isSelected = activeItem === scriptName;
                    return (
                      <div 
                        key={i} 
                        onClick={(e) => {
                          e.stopPropagation();
                          setActiveItem(scriptName);
                          onSelectScript?.(client.name, script);
                        }}
                        className={`flex items-center justify-between py-1 px-2 text-sm cursor-pointer rounded ${
                          isSelected 
                            ? (isDark ? 'bg-emerald-500/20 text-white font-medium' : 'bg-emerald-500/15 text-emerald-900 font-medium')
                            : (isDark ? 'text-zinc-400 hover:text-white hover:bg-emerald-500/10' : 'text-zinc-700 hover:text-black hover:bg-emerald-500/10')
                        }`}
                      >
                        <div className="flex items-center gap-2">
                          <Code size={12}/> 
                          {scriptName}
                        </div>
                        <button className={`hover:text-red-500 ${isDark ? 'text-zinc-500' : 'text-zinc-400'}`} onClick={(e) => e.stopPropagation()}>
                          <Trash2 size={10}/>
                        </button>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          ))
        ) : (
          // Full Workspace File Explorer Tree View
          <div className="px-2">
            <div className={`text-xs uppercase font-bold mb-2 px-2 ${isDark ? 'text-zinc-600' : 'text-zinc-500'}`}>
              Workspace Explorer
            </div>
            {renderExplorerTree(fileTree)}
          </div>
        )}
      </div>

      <div className={`p-3 border-t ${isDark ? 'border-white/5' : 'border-gray-200'}`}>
        <button className={`w-full flex items-center justify-center gap-2 text-sm transition-colors py-2 rounded border ${
          isDark 
            ? 'text-zinc-500 hover:text-white bg-white/5 border-white/5' 
            : 'text-zinc-700 hover:text-black bg-zinc-100 border-gray-200 hover:bg-zinc-200'
        }`}>
          <Plus size={14} /> New Client
        </button>
      </div>
    </div>
  );
};