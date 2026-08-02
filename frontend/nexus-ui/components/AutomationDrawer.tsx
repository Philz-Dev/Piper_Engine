import React, { useState, useEffect } from 'react';
import { X, FileCode, PlayCircle, Activity, Maximize2, Terminal as TerminalIcon, CheckCircle2, AlertCircle } from 'lucide-react';

interface LogEntry {
  timestamp: string;
  level: 'info' | 'warn' | 'error';
  category: 'technical' | 'user';
  message: string;
  ui_hint?: { action: string } | null;
}

interface DrawerProps {
  isOpen: boolean;
  onClose: () => void;
  onExpand: (clientId: string, taskId: string) => void;
  clientId: string; // Updated
  taskId: string;   // Updated
  isDark: boolean;
}

const AutomationDrawer: React.FC<DrawerProps> = ({ isOpen, onClose, onExpand, clientId, taskId, isDark }) => {
  const [viewMode, setViewMode] = useState<'activity' | 'terminal'>('activity');
  // Store the two streams separately
  const [logsData, setLogsData] = useState<{execution: LogEntry[], validation: LogEntry[]}>({ execution: [], validation: [] });

  // Merge and sort logs for the UI
  const currentLogs = [...logsData.execution, ...logsData.validation].sort(
    (a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime()
  );

  // WebSocket for Live Updates
  useEffect(() => {
    if (!isOpen || !clientId || !taskId) return;

    // Updated to match the specific backend endpoint structure
    const ws = new WebSocket(`ws://localhost:8099/ws/logs/${clientId}/${taskId}`);

    ws.onmessage = (event) => {
      const message = JSON.parse(event.data);
      const data = message.data || message; // Handle both init/update shapes
      
      if (data.execution_logs || data.validation_logs) {
        setLogsData({
          execution: data.execution_logs?.logs || [],
          validation: data.validation_logs || []
        });
      }
    };

    return () => ws.close();
  }, [isOpen, clientId, taskId]);

  if (!isOpen || !clientId || !taskId) return null;

  return (
    <>
      {/* Backdrop */}
      <div className="fixed inset-0 bg-black/40 backdrop-blur-sm z-[110] animate-in fade-in duration-300" onClick={onClose} />
      
      {/* Panel */}
      <div className={`fixed right-0 top-0 h-screen w-[500px] z-[120] shadow-2xl transform transition-transform duration-300 ease-in-out border-l flex flex-col animate-in slide-in-from-right
        ${isDark ? 'bg-[#0a0a0a] border-zinc-800 text-white' : 'bg-white border-slate-200 text-slate-900'}`}>
        
        {/* Header */}
        <div className="p-6 border-b border-zinc-800/50 flex items-center justify-between">
          <div>
            <h2 className="text-lg font-bold flex items-center gap-2">
              <FileCode className="text-blue-500" size={18} />
              {taskId}
            </h2>
            <p className="text-[10px] text-zinc-500 uppercase font-bold tracking-widest mt-1">Automation Console</p>
          </div>
          <div className="flex items-center gap-2">
             <button 
              onClick={() => onExpand(clientId, taskId)}
              className={`p-2 rounded-lg transition-colors ${isDark ? 'hover:bg-zinc-800 text-zinc-400 hover:text-blue-400' : 'hover:bg-slate-100 text-slate-500 hover:text-blue-600'}`}
              title="Open Full Debugger"
            >
              <Maximize2 size={18} />
            </button>
            <button onClick={onClose} className={`p-2 rounded-lg transition-colors ${isDark ? 'hover:bg-zinc-800' : 'hover:bg-slate-100'}`}>
              <X size={20} />
            </button>
          </div>
        </div>

        {/* Content Tabs */}
        <div className="flex-1 overflow-y-auto p-6">
          <div className="flex gap-4 mb-6 border-b border-zinc-800/50 pb-2">
            <button 
              onClick={() => setViewMode('activity')}
              className={`text-xs font-bold flex items-center gap-2 pb-2 transition-all border-b-2 ${
                viewMode === 'activity' 
                ? 'text-blue-500 border-blue-500' 
                : 'text-zinc-500 border-transparent opacity-50'
              }`}
            >
              <Activity size={14} /> Activity
            </button>
            <button 
              onClick={() => setViewMode('terminal')}
              className={`text-xs font-bold flex items-center gap-2 pb-2 transition-all border-b-2 ${
                viewMode === 'terminal' 
                ? 'text-blue-500 border-blue-500' 
                : 'text-zinc-500 border-transparent opacity-50'
              }`}
            >
              <TerminalIcon size={14} /> Terminal
            </button>
          </div>

          {/* Conditional Rendering based on viewMode */}
          {viewMode === 'activity' ? (
            /* DYNAMIC STEP TIMELINE */
            <div className="flex flex-col gap-8 py-2">
              {currentLogs.filter(log => log.category === 'user').map((log, idx) => (
                <div key={idx} className="flex gap-4 items-start relative">
                  {/* Connecting Line - Only show if not the last item */}
                  {idx < currentLogs.filter(l => l.category === 'user').length - 1 && (
                    <div className="absolute left-4 top-8 bottom-[-20px] w-[2px] bg-zinc-800/50" />
                  )}
                  
                  <div className={`w-8 h-8 rounded-full flex items-center justify-center shrink-0 z-10 ${log.level === 'error' ? 'bg-red-500/20 text-red-500' : 'bg-green-500/20 text-green-500'}`}>
                    {log.level === 'error' ? <AlertCircle size={16} /> : <CheckCircle2 size={16} />}
                  </div>
                  <div className={log.level === 'error' ? `bg-red-500/5 border border-red-500/20 p-4 rounded-xl flex-1 ${isDark ? 'bg-red-950/10' : 'bg-red-50/50'}` : ''}>
                    <p className={`text-sm font-bold ${log.level === 'error' ? 'text-red-400' : ''}`}>{log.level === 'error' ? 'Connection Problem' : 'Log Entry'}</p>
                    <p className={`text-xs mt-1 leading-relaxed ${log.level === 'error' ? 'text-red-300/70' : 'text-zinc-500'}`}>
                      {log.message}
                    </p>
                    {log.ui_hint && (
                      <button className="mt-3 text-[10px] bg-red-500/20 hover:bg-red-500/30 text-red-400 px-3 py-1.5 rounded-md font-bold uppercase tracking-wider transition-colors">
                        {log.ui_hint.action}
                      </button>
                    )}
                    <span className="text-[10px] text-zinc-600 font-mono mt-2 block">{new Date(log.timestamp).toLocaleTimeString()}</span>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            /* DYNAMIC TERMINAL VIEW */
            <div className={`rounded-xl p-4 font-mono text-[11px] leading-relaxed h-[500px] overflow-y-auto animate-in fade-in zoom-in-95 duration-200
              ${isDark ? 'bg-black border border-zinc-800 text-zinc-300' : 'bg-slate-900 text-slate-200'}`}>
              <div className="flex flex-col gap-2">
                <p className="text-blue-400 opacity-50 font-bold uppercase text-[9px] mb-2">// PIPER ENGINE v1.0.0 EXECUTION LOG</p>
                {currentLogs.map((log, idx) => (
                  <div key={idx} className="flex gap-3">
                    <span className="text-zinc-600">[{new Date(log.timestamp).toLocaleTimeString()}]</span>
                    <span className={`${log.level === 'error' ? 'text-red-500' : log.level === 'warn' ? 'text-yellow-500' : 'text-blue-400'}`}>{log.level.toUpperCase()}</span>
                    <span>{log.message}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Footer Actions */}
        <div className="p-6 border-t border-zinc-800/50 bg-zinc-900/10 flex gap-3">
          <button className="flex-1 bg-blue-600 hover:bg-blue-500 text-white font-bold py-2.5 rounded-xl flex items-center justify-center gap-2 transition-all shadow-lg shadow-blue-600/20">
            <PlayCircle size={18} /> Trigger Now
          </button>
        </div>
      </div>
    </>
  );
};

export default AutomationDrawer;