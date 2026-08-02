"use client";
import React, { useState, useEffect, useRef } from 'react';
import { Play, Square, Trash2, MoreVertical, ChevronRight, Loader2, ChevronDown, Check, Globe, Lock, KeyRound } from 'lucide-react';
import AutomationDrawer from './AutomationDrawer';

interface DashboardProps {
  onSelectRow: (id: string) => void;
  activeClient: string;
  setActiveClient: (client: string) => void;
  theme: 'dark' | 'light';
  send: (type: string, payload?: any) => void;
  userId: string;
  // Unified Piper Data Props
  automations: any[];
  clients: string[];
  status: any;
  loading: boolean;
  toggleAutomation: (name: string, action: string, client: string) => Promise<void>;
  deleteAutomation: (client: string, name: string) => Promise<void>;
  fetchAutomations: (client: string) => Promise<void>;
  unlockEngine: (password: string) => Promise<boolean>;
  globalStats: { cpu: string; ram: string; disk: string };
}

const Dashboard: React.FC<DashboardProps> = ({ 
  onSelectRow, 
  theme, 
  send, 
  userId,
  activeClient,
  setActiveClient,
  automations,
  clients,
  status,
  loading,
  toggleAutomation,
  deleteAutomation,
  fetchAutomations,
  unlockEngine
}) => {
  const isDark = theme === 'dark';
  const switcherRef = useRef<HTMLDivElement>(null);
  
  // State management
  const [totalStats, setTotalStats] = useState({ cpu: "0.00%", mem: "0.00MB" });
  const [isSwitcherOpen, setIsSwitcherOpen] = useState(false);
  const [rows, setRows] = useState<any[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [isLocalLoading, setIsLocalLoading] = useState(false);
  const [activeAutomation, setActiveAutomation] = useState<string | null>(null);
  const [password, setPassword] = useState("");
  const [authError, setAuthError] = useState("");

  // Sync rows from props
  useEffect(() => {
    setRows(automations || []);
  }, [automations]);

  // Handle Initial Client Selection
  useEffect(() => {
    if (clients && clients.length > 0 && !activeClient) {
      setActiveClient(clients[0]);
    }
  }, [clients, activeClient]);

  const handleUnlock = async () => {
    setIsLocalLoading(true);
    setAuthError(""); 
    try {
      const success = await unlockEngine(password);
      if (!success) {
        setAuthError("Invalid Master Password");
      }
    } catch (err) {
      setAuthError("Connection error with Piper Engine");
    } finally {
      setIsLocalLoading(false);
    }
  };

  const toggleContainer = async (e: React.MouseEvent, containerName: string, currentStatus: string) => {
    e.stopPropagation();
    const action = currentStatus === 'running' ? 'stop' : 'start';
    
    // Optimistic UI update
    setRows(prev => prev.map(r => r.name === containerName ? { ...r, status: 'processing' } : r));
    
    try {
      await toggleAutomation(containerName, action, activeClient);
    } catch (error) { 
      console.error("Toggle failed:", error); 
    }
  };

  const handleDelete = async (e: React.MouseEvent, containerName: string) => {
    e.stopPropagation();
    if (!window.confirm(`Are you sure you want to permanently delete ${containerName}?`)) return;

    setIsLocalLoading(true);
    try {
      await deleteAutomation(activeClient, containerName);
      setSelected(prev => prev.filter(id => id !== containerName));
    } catch (error) {
      console.error("Delete request failed:", error);
    } finally {
      setIsLocalLoading(false);
    }
  };

  const handleSelectAll = (e: React.ChangeEvent<HTMLInputElement>) => {
    setSelected(e.target.checked ? rows.map(r => r.id) : []);
  };

  const toggleSelect = (e: React.MouseEvent, id: string) => {
    e.stopPropagation();
    setSelected(prev => prev.includes(id) ? prev.filter(item => item !== id) : [...prev, id]);
  };

  const renderStatusCircle = (row: any) => {
    const status = row.status;
    if (status === 'processing') return <Loader2 size={12} className={`animate-spin ${isDark ? 'text-blue-400' : 'text-blue-500'}`} />;
    const isRunning = status === 'running';
    const color = isRunning ? (isDark ? '#22c55e' : '#16a34a') : (isDark ? '#52525b' : '#cbd5e1');
    return (
      <div className="relative flex items-center justify-center h-4 w-4">
        {isRunning && <div className="absolute rounded-full opacity-60 animate-ping" style={{ width: '8px', height: '8px', backgroundColor: color }} />}
        <div className="rounded-full transition-all duration-300 relative z-10" style={{ width: '8px', height: '8px', backgroundColor: color, boxShadow: isRunning ? `0 0 12px ${color}aa` : 'none' }} />
      </div>
    );
  };

  if (status?.locked === null) {
    return (
      <div className={`w-full min-h-screen flex items-center justify-center ${isDark ? 'bg-black' : 'bg-white'}`}>
        <Loader2 className="animate-spin text-blue-500" size={32} />
      </div>
    );
  }

  return (
    <div className="relative w-full min-h-screen">
      <AutomationDrawer 
        isOpen={!!activeAutomation} 
        onClose={() => setActiveAutomation(null)} 
        clientId={activeClient}          
        taskId={activeAutomation || ""}
        isDark={isDark}
        onExpand={(client, task) => window.location.href = `/editor/${client}/${task}`}
      />

      {status?.locked && (
        <div className="absolute inset-0 z-[100] flex items-center justify-center backdrop-blur-md bg-black/10">
          <div className={`p-8 rounded-2xl border shadow-2xl w-full max-w-md ${isDark ? 'bg-zinc-900/90 border-zinc-800' : 'bg-white/90 border-slate-200'}`}>
             <div className="flex flex-col items-center text-center mb-6">
               <div className={`p-4 rounded-full mb-4 ${isDark ? 'bg-blue-500/10' : 'bg-blue-50'}`}>
                  <Lock size={32} className="text-blue-500" />
               </div>
               <h2 className={`text-xl font-bold ${isDark ? 'text-white' : 'text-slate-900'}`}>
                 {status.exists ? "Engine Locked" : "Setup Engine"}
               </h2>
               <p className={`text-sm mt-2 ${isDark ? 'text-zinc-400' : 'text-slate-500'}`}>
                 {status.exists ? "Enter your Master Password to access the Piper Engine dashboard." : "No Master Password detected."}
               </p>
             </div>

             <div className="space-y-4">
               <div className="relative">
                 <KeyRound size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-zinc-500" />
                 <input 
                   type="password" 
                   placeholder={status.exists ? "Master Password" : "Create Master Password"}
                   value={password}
                   onChange={(e) => setPassword(e.target.value)}
                   onKeyDown={(e) => e.key === 'Enter' && handleUnlock()}
                   className={`w-full pl-10 pr-4 py-2.5 rounded-xl border outline-none transition-all ${isDark ? 'bg-black border-zinc-800 focus:border-blue-500' : 'bg-slate-50 border-slate-200 focus:border-blue-500'}`}
                 />
               </div>
               {authError && <p className="text-red-500 text-[11px] font-bold text-center uppercase">{authError}</p>}
               <button onClick={handleUnlock} disabled={isLocalLoading} className="w-full bg-blue-600 text-white font-semibold py-2.5 rounded-xl">
                 {isLocalLoading ? <Loader2 size={18} className="animate-spin mx-auto" /> : (status.exists ? "Unlock Dashboard" : "Initialize Engine")}
               </button>
             </div>
          </div>
        </div>
      )}

      <div className={`w-full p-6 transition-all duration-300 ${isDark ? 'text-white' : 'text-slate-900'} ${status?.locked ? 'blur-sm pointer-events-none opacity-0' : 'opacity-100'}`}>
        <div className="flex items-center justify-between mb-6 pt-2">
          <h1 className="text-xl font-bold tracking-tight">Dashboard</h1>
          <div className="relative" ref={switcherRef}>
            <button onClick={() => setIsSwitcherOpen(!isSwitcherOpen)} className={`flex items-center gap-3 px-3 py-1.5 rounded-lg border ${isDark ? 'bg-[#0f0f0f] border-zinc-800' : 'bg-white border-slate-200 shadow-sm'}`}>
              <div className={`p-1 rounded-md ${isDark ? 'bg-zinc-800' : 'bg-slate-100'}`}><Globe size={14} className="text-blue-500" /></div>
              <div className="text-left">
                <p className="text-[10px] uppercase font-bold text-zinc-500">Current Client</p>
                <p className="text-xs font-semibold">{activeClient || "Searching..."}</p>
              </div>
              <ChevronDown size={14} className={isSwitcherOpen ? 'rotate-180' : ''} />
            </button>
            {isSwitcherOpen && (
              <div className={`absolute right-0 mt-2 w-56 rounded-xl border z-50 ${isDark ? 'bg-zinc-900 border-zinc-800' : 'bg-white border-slate-200'}`}>
                {clients?.map(client => (
                  <button key={client} onClick={() => { setActiveClient(client); setIsSwitcherOpen(false); }} className="w-full flex items-center justify-between px-3 py-2 text-xs hover:bg-blue-500/10">
                    {client} {activeClient === client && <Check size={14} className="text-blue-500" />}
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>

        <div className="flex items-start justify-between mb-6">
          <div className="flex gap-20">
            <div>
              <p className="text-[10px] uppercase font-bold text-zinc-500">CPU Usage</p>
              <p className="text-lg font-medium">{totalStats.cpu}</p>
            </div>
            <div>
              <p className="text-[10px] uppercase font-bold text-zinc-500">Memory Usage</p>
              <p className="text-lg font-medium">{totalStats.mem}</p>
            </div>
          </div>
          
          <div className="min-h-[45px] flex items-end">
            {selected.length > 0 && (
              <div className={`flex items-center gap-6 px-4 py-2 rounded-lg border animate-in fade-in slide-in-from-top-2 duration-300 ${isDark ? 'bg-zinc-900/50 border-zinc-800' : 'bg-slate-50 border-slate-200 shadow-sm'}`}>
                <span className="text-[10px] font-bold text-blue-500 uppercase mr-2">{selected.length} Selected</span>
                <button 
                  className="hover:scale-110 transition-transform"
                  onClick={(e) => {
                    e.stopPropagation();
                    const selectedRows = rows.filter(r => selected.includes(r.id));
                    selectedRows.forEach(r => {
                      if (r.status !== 'running') toggleContainer(e, r.name, r.status);
                    });
                  }}
                >
                  <Play size={16} className="text-zinc-500 hover:text-green-500" />
                </button>
                <button 
                  className="hover:scale-110 transition-transform"
                  onClick={(e) => {
                    e.stopPropagation();
                    const selectedRows = rows.filter(r => selected.includes(r.id));
                    selectedRows.forEach(r => {
                      if (r.status === 'running') toggleContainer(e, r.name, r.status);
                    });
                  }}
                >
                  <Square size={15} fill="#3b82f6" stroke="none" className="hover:opacity-80" />
                </button>
                <button className="hover:scale-110 transition-transform">
                  <MoreVertical size={16} className="text-zinc-500" />
                </button>
                <div className={`w-px h-4 ${isDark ? 'bg-zinc-800' : 'bg-slate-200'}`} />
                <button 
                  onClick={(e) => {
                    e.stopPropagation();
                    const selectedRows = rows.filter(r => selected.includes(r.id));
                    if (window.confirm(`Are you sure you want to delete ${selectedRows.length} automations?`)) {
                      selectedRows.forEach(r => handleDelete(e, r.name));
                    }
                  }}
                  className="hover:scale-110 transition-transform"
                >
                  <Trash2 size={16} className="text-red-500" />
                </button>
              </div>
            )}
          </div>
        </div>

        <div className={`border rounded-md overflow-y-auto relative max-h-[calc(100vh-280px)] overscroll-behavior-contain ${isDark ? 'border-zinc-800 bg-black' : 'border-slate-200 bg-white'}`}>
          <table className="w-full text-left text-[12px] border-collapse">
            <thead className="sticky top-0 z-20 bg-inherit">
              <tr className={`border-b ${isDark ? 'bg-zinc-900 border-zinc-800 text-zinc-400' : 'bg-slate-50 border-slate-200'}`}>
                <th className="py-3 px-4 w-12 text-center"><input type="checkbox" onChange={handleSelectAll} checked={selected.length === rows.length && rows.length > 0} /></th>
                <th className="py-3 px-0 w-6"></th>
                <th className="py-4 px-2 w-10"></th>
                <th className="py-4 px-4">Automation File</th>
                <th className="py-3 px-4">CPU Usage</th>
                <th className="py-3 px-4 text-center">Memory</th>
                <th className="py-3 px-4 w-[140px]">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-800/50">
              {loading ? (
                <tr><td colSpan={7} className="py-20 text-center"><Loader2 className="animate-spin inline" /> Loading...</td></tr>
              ) : rows.length === 0 ? (
              <tr>
                <td colSpan={7} className="py-20 text-center">
                  <div className="flex flex-col items-center gap-2 opacity-50">
                    <Globe size={32} className="text-zinc-500 mb-2" />
                    <p className="text-sm font-medium">No automations found for this client</p>
                    <p className="text-[11px]">Upload a .yml file to the waterfall folder to get started.</p>
                  </div>
                </td>
              </tr>           
              ) : (
                rows.map((row) => (
                <tr 
                  key={row.id} 
                  onClick={() => setActiveAutomation(row.name)}
                  className={`cursor-pointer group transition-colors ${
                    activeAutomation === row.name 
                      ? (isDark ? 'bg-blue-500/10' : 'bg-blue-50') 
                      : (isDark ? 'hover:bg-white/[0.02]' : 'hover:bg-slate-50')
                  }`}
                >
                  <td className="py-3 px-4 text-center" onClick={(e) => toggleSelect(e, row.id)}><input type="checkbox" checked={selected.includes(row.id)} readOnly /></td>
                  <td className="py-3 px-0">{renderStatusCircle(row)}</td>
                  <td className="py-3 px-2"><ChevronRight size={14} className="text-zinc-600 transition-transform group-hover:translate-x-1" /></td>
                  <td className={`py-3 px-4 underline decoration-dotted text-[14px] font-medium ${isDark ? 'text-blue-400' : 'text-black'}`}>
                    {row.name}
                  </td>
                  <td className="py-3 px-4 text-zinc-500 font-mono">
                    {row.cpu || "0.00%"}
                  </td>
                  <td className="py-3 px-4 text-center text-zinc-500">
                    {row.mem || "0.00MB"}
                  </td>
                  <td className="py-3 px-4" onClick={(e) => e.stopPropagation()}>
                    <div className="flex items-center gap-6">
                      <button onClick={(e) => toggleContainer(e, row.name, row.status)} disabled={row.status === 'processing'}>
                        {row.status === 'running' ? <Square size={15} fill="#3b82f6" stroke="none" /> : <Play size={16} className="text-zinc-500" />}
                      </button>
                      <button className="text-zinc-500"><MoreVertical size={16} /></button>
                      <button onClick={(e) => handleDelete(e, row.name)}>
                        <Trash2 size={16} className="text-red-500 hover:scale-110 transition-transform" />
                      </button>
                    </div>
                  </td>
                </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};

export default Dashboard;