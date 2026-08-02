"use client";
import React, { useState, useRef, useEffect } from 'react';
import { 
  Terminal, 
  Copy, 
  Check, 
  Server, 
  Monitor, 
  Zap, 
  Shield, 
  Loader2,
  Cloud,
  X,
  AlertCircle
} from 'lucide-react';
import { getEngineCommand } from '@/lib/api';

interface Props {
  theme: 'dark' | 'light' | null;
  installToken: string;
  engineActive: boolean; 
  userEmail: string;
}

const InstallationGuide: React.FC<Props> = ({ theme, installToken, engineActive, userEmail }) => {
  const [copied, setCopied] = useState(false);
  const [showVPSForm, setShowVPSForm] = useState(false);
  const [isInstalling, setIsInstalling] = useState(false);
  const [isCanceling, setIsCanceling] = useState(false);
  const [hasError, setHasError] = useState(false);
  const [isComplete, setIsComplete] = useState(false);
  const [logs, setLogs] = useState<string[]>([]);
  const [command, setCommand] = useState<string>('Loading command...');
  const ws = useRef<WebSocket | null>(null);
  const isDark = theme !== 'light';
  
  const [vpsData, setVpsData] = useState({ ip: '', user: '', password: '' });

  useEffect(() => {
    if (userEmail) {
      getEngineCommand(userEmail)
        .then(data => {
          setCommand(data.command);
        })
        .catch(err => {
          setCommand(`Error loading command: ${err.message}`);
        });
    }
  }, [userEmail]);

  const handleCopy = () => {
    navigator.clipboard.writeText(command);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const startDeployment = () => {
    setIsInstalling(true);
    setIsComplete(false);
    setIsCanceling(false);
    setHasError(false);
    setLogs([">> Initializing connection..."]);
    setShowVPSForm(false);
    
    const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
    const socket = new WebSocket(`${protocol}://${window.location.host}/ws/install/${userEmail}`);
    ws.current = socket;
    
    ws.current.onopen = () => {
      setLogs(prev => [...prev, ">> Connected to deployment server."]);
      ws.current?.send(JSON.stringify(vpsData));
    };

    ws.current.onmessage = (event) => {
      setLogs(prev => [...prev, event.data]);
      if (event.data.includes("INSTALLATION_COMPLETE")) {
        setIsComplete(true);
      }
    };

    // Handle connection errors
    ws.current.onerror = () => {
      setLogs(prev => [...prev, ">> Error: Could not connect to deployment server."]);
      setHasError(true);
    };

    // Handle unexpected closure
    ws.current.onclose = () => {
      if (!isComplete && !isCanceling && !hasError) {
        setLogs(prev => [...prev, ">> Connection lost."]);
        setHasError(true);
      }
    };
  };

  const cancelDeployment = () => {
    setIsCanceling(true);
    
    if (ws.current) {
      setLogs(prev => [...prev, ">> Termination request sent to server...", ">> Cleaning up..."]);
      
      ws.current.send(JSON.stringify({ action: 'terminate' }));
      ws.current.onmessage = null; 

      setTimeout(() => {
        if (ws.current) {
          ws.current.close();
          ws.current = null;
        }
        setIsInstalling(false);
        setIsCanceling(false);
      }, 1000);
    } else {
      setIsInstalling(false);
      setIsCanceling(false);
    }
  };

  const resetProcess = () => {
    setIsInstalling(false);
    setIsComplete(false);
    setHasError(false);
    setLogs([]);
  };

  if (isInstalling) {
    return (
      <div className={`h-full p-8 max-w-4xl mx-auto flex flex-col gap-4 overflow-hidden ${isDark ? 'bg-[#050505] text-white' : 'bg-slate-50 text-slate-900'}`}>
        <h2 className="text-xl font-bold">Deployment Progress</h2>
        
        {/* Professional dark tone execution log container */}
        <div className={`flex-1 p-6 rounded-2xl font-mono text-xs flex flex-col overflow-hidden ${isDark ? 'bg-[#0A0A0A] border border-white/10 shadow-[0_0_50px_-12px_rgba(0,0,0,0.5)]' : 'bg-slate-900 text-green-400'}`}>
          <div className="flex-1 overflow-y-auto">
            <div className="flex flex-col gap-1">
              {logs.map((log, i) => (
                <div key={i} className={`${log.includes(">> Error") ? 'text-red-400' : (isDark ? 'text-gray-300' : 'text-green-400')}`}>
                  <span className="opacity-50 mr-2">$</span>{log}
                </div>
              ))}
              
              {isCanceling && !isComplete && !hasError && (
                <div className="text-red-400 font-bold flex items-center gap-2 mt-4 animate-pulse">
                  <Loader2 size={14} className="animate-spin" />
                  <span>Processing termination...</span>
                </div>
              )}

              {isComplete && (
                <div className="text-emerald-400 font-bold mt-4 flex items-center gap-2 border-t border-emerald-500/20 pt-4">
                  <Check size={16} />
                  --- Installation Successful ---
                </div>
              )}
            </div>
          </div>
        </div>

        <div className="flex justify-end">
          {isComplete ? (
            <button 
              onClick={() => window.location.reload()} 
              className="px-6 py-2 bg-emerald-600 hover:bg-emerald-500 rounded-xl font-bold text-sm transition-all text-white"
            >
              Go to Dashboard
            </button>
          ) : hasError ? (
            <button 
              onClick={resetProcess}
              className="px-6 py-2 bg-red-500/10 border border-red-500/20 text-red-400 hover:bg-red-500/20 rounded-xl font-bold text-sm transition-all"
            >
              Close
            </button>
          ) : (
            <button 
              onClick={cancelDeployment}
              disabled={isCanceling}
              className={`px-6 py-2 border border-red-500/20 text-red-400 rounded-xl font-bold text-sm transition-all ${isCanceling ? 'opacity-50 cursor-not-allowed' : 'hover:bg-red-500/10'}`}
            >
              {isCanceling ? "Canceling..." : "Cancel Deployment"}
            </button>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className={`min-h-screen w-full flex flex-col ${isDark ? 'bg-[#050505] text-white' : 'bg-slate-50 text-slate-900'}`}>
      
      <nav className={`sticky top-0 z-50 backdrop-blur-md border-b ${isDark ? 'border-white/5 bg-black/50' : 'border-slate-200 bg-white/70'}`}>
        <div className="max-w-7xl mx-auto px-6 h-16 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 bg-blue-600 rounded-lg flex items-center justify-center">
              <Zap size={18} className="text-white fill-current" />
            </div>
            <span className="font-bold tracking-tighter text-xl uppercase">Piper Engine</span>
          </div>
          <div className="hidden md:flex items-center gap-8 text-sm font-medium opacity-70">
            <a href="#" className="hover:opacity-100 transition-opacity">Documentation</a>
            <a href="#" className="hover:opacity-100 transition-opacity">Community</a>
            <a href="#" className="hover:opacity-100 transition-opacity">Support</a>
          </div>

          <div className="flex items-center gap-3">
            {!engineActive ? (
              <span className="text-[10px] uppercase tracking-widest font-bold opacity-30 animate-pulse">
                Awaiting Connection
              </span>
            ) : (
              <button className="text-xs font-bold px-4 py-2 rounded-full border border-blue-500/20 bg-blue-500/5 text-blue-400/60 flex items-center gap-2 cursor-wait">
                <Loader2 size={12} className="animate-spin" />
                Setup in Progress
              </button>
            )}
          </div>
        </div>
      </nav>

      <main className="flex-grow flex flex-col items-center py-20 px-6">
        <div className="max-w-4xl w-full animate-in fade-in slide-in-from-bottom-8 duration-1000">
          <div className="text-center mb-16">
            <h1 className={`text-5xl font-black tracking-tight mb-6 bg-clip-text text-transparent bg-gradient-to-b ${isDark ? 'from-white to-white/40' : 'from-slate-900 to-slate-500'}`}>
              Set Up Your Environment
            </h1>
            <p className={`text-lg max-w-2xl mx-auto ${isDark ? 'text-zinc-400' : 'text-slate-600'}`}>
              Piper Engine requires a secure connection to your infrastructure. Choose your preferred deployment method below to get started.
            </p>
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-5 gap-8 items-stretch">
            <div className={`lg:col-span-3 p-8 rounded-3xl border relative overflow-hidden transition-all ${isDark ? 'bg-zinc-900/40 border-white/5 shadow-2xl' : 'bg-white border-slate-200 shadow-xl'}`}>
              <div className="flex items-center justify-between mb-8">
                <div className="flex items-center gap-3">
                  <div className="p-2 bg-blue-500/10 rounded-lg">
                    <Monitor size={20} className="text-blue-500" />
                  </div>
                  <h3 className="font-bold text-lg">Local Environment</h3>
                </div>
              </div>

              <div className={`relative group p-6 rounded-2xl font-mono text-[13px] border transition-all mb-8 ${isDark ? 'bg-black border-white/10 text-blue-400' : 'bg-slate-900 border-slate-800 text-blue-300'}`}>
                <div className="pr-12 break-all leading-relaxed">
                  {command}
                </div>
                <button onClick={handleCopy} className="absolute top-5 right-5 p-2 rounded-lg bg-white/5 hover:bg-white/10 border border-white/10 transition-all">
                  {copied ? <Check size={16} className="text-green-500" /> : <Copy size={16} className="opacity-50" />}
                </button>
              </div>

              <div className="space-y-4">
                <div className="flex items-center gap-3 text-xs opacity-50">
                  <Shield size={14} />
                  <span>Secure TLS encryption active</span>
                </div>
                <div className="flex items-center gap-3 text-xs opacity-50">
                  <Terminal size={14} />
                  <span>Compatible with Linux, macOS, and WSL</span>
                </div>
              </div>
            </div>

            <div className={`lg:col-span-2 p-8 rounded-3xl border flex flex-col justify-between transition-all ${isDark ? 'bg-blue-600/5 border-blue-500/20' : 'bg-blue-50 border-blue-100'}`}>
              <div>
                <div className="p-3 bg-blue-500/10 rounded-2xl inline-block mb-6">
                  <Cloud size={24} className="text-blue-500" />
                </div>
                <h4 className="text-xl font-bold mb-3 text-blue-500">Deploy Piper Engine To VPS</h4>
                <p className="text-sm opacity-70 leading-relaxed mb-8">
                  Need high availability? Run the install script directly on your remote Linux server to connect your cloud infrastructure.
                </p>
              </div>
              <button onClick={() => setShowVPSForm(true)} className="w-full py-4 rounded-2xl bg-blue-600 hover:bg-blue-500 text-white font-bold transition-all shadow-lg shadow-blue-600/30">
                Deploy
              </button>
            </div>
          </div>
        </div>
      </main>

      {showVPSForm && (
        <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-[100] p-4">
          <div className={`p-8 rounded-3xl w-full max-w-md border ${isDark ? 'bg-zinc-900 border-zinc-800' : 'bg-white border-slate-200'}`}>
            <div className="flex justify-between items-center mb-6">
              <h3 className="font-bold text-lg">VPS Credentials</h3>
              <button onClick={() => setShowVPSForm(false)}><X size={18}/></button>
            </div>
            <input placeholder="IP Address" className="w-full p-3 mb-3 rounded-lg border bg-transparent" onChange={e => setVpsData({...vpsData, ip: e.target.value})} />
            <input placeholder="Username" className="w-full p-3 mb-3 rounded-lg border bg-transparent" onChange={e => setVpsData({...vpsData, user: e.target.value})} />
            <input type="password" placeholder="Password/Key" className="w-full p-3 mb-6 rounded-lg border bg-transparent" onChange={e => setVpsData({...vpsData, password: e.target.value})} />
            <button onClick={startDeployment} className="w-full py-3 bg-blue-600 rounded-xl font-bold text-white">Execute Deployment</button>
          </div>
        </div>
      )}
    </div>
  );
};

export default InstallationGuide;