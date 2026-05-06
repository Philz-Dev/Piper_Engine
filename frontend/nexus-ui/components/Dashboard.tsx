"use client";
import React, { useState, useEffect, useRef } from 'react';
import { Play, Square, Trash2, MoreVertical, ChevronRight, Loader2, ChevronDown, Check, Globe, Lock, KeyRound } from 'lucide-react';

const API_BASE = "http://localhost:8099/api/v1";

interface DashboardProps {
  onSelectRow: (id: string) => void;
  theme: 'dark' | 'light';
}

const Dashboard: React.FC<DashboardProps> = ({ onSelectRow, theme }) => {
  const isDark = theme === 'dark';
  const switcherRef = useRef<HTMLDivElement>(null);
  
  // States
  const [clients, setClients] = useState<string[]>([]);
  const [activeClient, setActiveClient] = useState("");
  const [isSwitcherOpen, setIsSwitcherOpen] = useState(false);
  const [rows, setRows] = useState<any[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  
  // Security States
  const [isLocked, setIsLocked] = useState<boolean | null>(null); 
  const [passwordExists, setPasswordExists] = useState(false); 
  const [password, setPassword] = useState("");
  const [authError, setAuthError] = useState("");

  useEffect(() => {
    fetch(`${API_BASE}/status`)
      .then(res => res.json())
      .then(data => {
        setIsLocked(data.locked);
        setPasswordExists(data.exists);
      })
      .catch(err => {
        console.error("Status check failed", err);
        setIsLocked(true); 
      });
  }, []);

  const handleUnlock = async () => {
    setLoading(true);
    setAuthError(""); 
    try {
      const res = await fetch(`${API_BASE}/unlock`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ password })
      });
      
      const data = await res.json();

      if (res.ok) {
        setIsLocked(false);
        setAuthError("");
        loadInitialData();
      } else {
        setAuthError(data.detail || "Invalid Master Password");
      }
    } catch (err) {
      setAuthError("Connection error with Piper Engine");
    } finally {
      setLoading(false);
    }
  };

  const loadInitialData = () => {
    fetch(`${API_BASE}/clients`)
      .then(res => res.json())
      .then(data => {
        setClients(data);
        if (data.length > 0) setActiveClient(data[0]);
      })
      .catch(err => console.error("API Error (Clients):", err));
  };

  useEffect(() => {
    if (isLocked === false) loadInitialData();
  }, [isLocked]);

  useEffect(() => {
    if (!activeClient || isLocked !== false) return;
    
    setLoading(true);
    fetch(`${API_BASE}/automations/${activeClient}`)
      .then(res => res.json())
      .then(data => {
        setRows(data);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, [activeClient, isLocked]);

  const toggleContainer = async (e: React.MouseEvent, containerName: string, currentStatus: string) => {
    e.stopPropagation();
    const action = currentStatus === 'running' ? 'stop' : 'start';
    setRows(prev => prev.map(r => r.name === containerName ? { ...r, status: 'processing' } : r));
    try {
      const res = await fetch(`${API_BASE}/toggle/${containerName}?action=${action}&client_name=${activeClient}`, { method: 'POST' });
      if (res.ok) {
        setRows(prev => prev.map(r => r.name === containerName ? { ...r, status: action === 'start' ? 'running' : 'stopped' } : r));
      } else {
        const refresh = await fetch(`${API_BASE}/automations/${activeClient}`);
        const updatedData = await refresh.json();
        setRows(updatedData);
      }
    } catch (error) { console.error("Toggle failed:", error); }
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

  if (isLocked === null) {
    return (
      <div className={`w-full min-h-screen flex items-center justify-center ${isDark ? 'bg-black' : 'bg-white'}`}>
        <Loader2 className="animate-spin text-blue-500" size={32} />
      </div>
    );
  }

  return (
    <div className="relative w-full min-h-screen">
      {isLocked && (
        <div className="absolute inset-0 z-[100] flex items-center justify-center backdrop-blur-md bg-black/10">
           <div className={`p-8 rounded-2xl border shadow-2xl w-full max-w-md ${isDark ? 'bg-zinc-900/90 border-zinc-800' : 'bg-white/90 border-slate-200'}`}>
              <div className="flex flex-col items-center text-center mb-6">
                <div className={`p-4 rounded-full mb-4 ${isDark ? 'bg-blue-500/10' : 'bg-blue-50'}`}>
                  <Lock size={32} className="text-blue-500" />
                </div>
                <h2 className={`text-xl font-bold ${isDark ? 'text-white' : 'text-slate-900'}`}>
                  {passwordExists ? "Engine Locked" : "Setup Engine"}
                </h2>
                <p className={`text-sm mt-2 ${isDark ? 'text-zinc-400' : 'text-slate-500'}`}>
                  {passwordExists ? "Enter your Master Password to access the Piper Engine dashboard." : "No Master Password detected."}
                </p>
              </div>

              <div className="space-y-4">
                <div className="relative">
                  <KeyRound size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-zinc-500" />
                  <input 
                    type="password" 
                    placeholder={passwordExists ? "Master Password" : "Create Master Password"}
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    onKeyDown={(e) => e.key === 'Enter' && handleUnlock()}
                    className={`w-full pl-10 pr-4 py-2.5 rounded-xl border outline-none transition-all ${isDark ? 'bg-black border-zinc-800 focus:border-blue-500' : 'bg-slate-50 border-slate-200 focus:border-blue-500'}`}
                  />
                </div>
                {authError && <p className="text-red-500 text-[11px] font-bold text-center uppercase">{authError}</p>}
                <button onClick={handleUnlock} disabled={loading} className="w-full bg-blue-600 text-white font-semibold py-2.5 rounded-xl">
                  {loading ? <Loader2 size={18} className="animate-spin mx-auto" /> : (passwordExists ? "Unlock Dashboard" : "Initialize Engine")}
                </button>
              </div>
           </div>
        </div>
      )}

      <div className={`w-full p-6 transition-all duration-300 ${isDark ? 'text-white' : 'text-slate-900'} ${isLocked ? 'blur-sm pointer-events-none opacity-0' : 'opacity-100'}`}>
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
                {clients.map(client => (
                  <button key={client} onClick={() => { setActiveClient(client); setIsSwitcherOpen(false); }} className="w-full flex items-center justify-between px-3 py-2 text-xs hover:bg-blue-500/10">
                    {client} {activeClient === client && <Check size={14} className="text-blue-500" />}
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>

        <div className="flex gap-20 mb-6">
          <div><p className="text-[10px] uppercase font-bold text-zinc-500">CPU Usage</p><p className="text-lg font-medium">59.76%</p></div>
          <div><p className="text-[10px] uppercase font-bold text-zinc-500">Memory Usage</p><p className="text-lg font-medium">123.69MB</p></div>
        </div>

        {/* 
            TABLE CONTAINER: 
            Added max-h-[450px] to act as the boundary.
            Added overflow-y-auto to enable scrolling within the box.
        */}
        <div className={`border rounded-md overflow-y-auto max-h-[450px] ${isDark ? 'border-zinc-800 bg-black' : 'border-slate-200 bg-white'}`}>
          <table className="w-full text-left text-[12px] border-collapse">
            {/* Sticky Header to keep columns visible while scrolling */}
            <thead className="sticky top-0 z-20">
              <tr className={`border-b ${isDark ? 'bg-zinc-900 border-zinc-800 text-zinc-400' : 'bg-slate-50 border-slate-200'}`}>
                <th className="py-3 px-4 w-12 text-center"><input type="checkbox" onChange={handleSelectAll} checked={selected.length === rows.length && rows.length > 0} /></th>
                <th className="py-3 px-0 w-6"></th>
                <th className="py-4 px-2 w-10"></th>
                <th className="py-4 px-4">Automation File</th>
                <th className="py-3 px-4">Container ID</th>
                <th className="py-3 px-4 text-center">Port(s)</th>
                <th className="py-3 px-4 w-[140px]">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-800/50">
              {loading ? (
                <tr><td colSpan={7} className="py-20 text-center"><Loader2 className="animate-spin inline" /> Loading...</td></tr>
              ) : rows.map((row) => (
                <tr key={row.id} className="hover:bg-white/[0.02]" onClick={() => onSelectRow(row.name)}>
                  <td className="py-3 px-4 text-center" onClick={(e) => toggleSelect(e, row.id)}><input type="checkbox" checked={selected.includes(row.id)} readOnly /></td>
                  <td className="py-3 px-0">{renderStatusCircle(row)}</td>
                  <td className="py-3 px-2"><ChevronRight size={14} className="text-zinc-600" /></td>
                  <td className="py-3 px-4 text-blue-400 underline decoration-dotted">{row.name}.yml</td>
                  <td className="py-3 px-4 text-zinc-500 font-mono">{row.id || "pending..."}</td>
                  <td className="py-3 px-4 text-center text-zinc-500">{row.ports || "-"}</td>
                  <td className="py-3 px-4" onClick={(e) => e.stopPropagation()}>
                    <div className="flex items-center gap-6">
                      <button onClick={(e) => toggleContainer(e, row.name, row.status)} disabled={row.status === 'processing'}>
                        {row.status === 'running' ? <Square size={15} fill="#3b82f6" stroke="none" /> : <Play size={16} className="text-zinc-500" />}
                      </button>
                      <button className="text-zinc-500"><MoreVertical size={16} /></button>
                      <button><Trash2 size={16} className="text-red-500" /></button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};

export default Dashboard;