"use client";
import React from 'react';
import { 
  Terminal, 
  Copy, 
  Check, 
  Download, 
  Monitor, 
  Server, 
  Zap, 
  Shield, 
  Globe,
  Code2, 
  MessageSquare,
  ArrowRight,
  Loader2 
} from 'lucide-react';

interface Props {
  theme: 'dark' | 'light' | null;
  installToken: string;
  engineActive: boolean; 
}

const InstallationGuide: React.FC<Props> = ({ theme, installToken, engineActive }) => {
  const [copied, setCopied] = React.useState(false);
  const isDark = theme !== 'light';
  
  const command = `curl -sSL https://get.piperengine.io | bash -s -- --token ${installToken}`;

  const handleCopy = () => {
    navigator.clipboard.writeText(command);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className={`min-h-screen w-full flex flex-col ${isDark ? 'bg-[#050505] text-white' : 'bg-slate-50 text-slate-900'}`}>
      
      {/* --- NAVIGATION BAR --- */}
      <nav className={`sticky top-0 z-50 backdrop-blur-md border-b ${isDark ? 'border-white/5 bg-black/50' : 'border-slate-200 bg-white/70'}`}>
        <div className="max-w-7xl mx-auto px-6 h-16 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 bg-blue-600 rounded-lg flex items-center justify-center">
              <Zap size={18} className="text-white fill-current" />
            </div>
            <span className="font-bold tracking-tighter text-xl uppercase">Piper Cloud</span>
          </div>
          <div className="hidden md:flex items-center gap-8 text-sm font-medium opacity-70">
            <a href="#" className="hover:opacity-100 transition-opacity">Documentation</a>
            <a href="#" className="hover:opacity-100 transition-opacity">Community</a>
            <a href="#" className="hover:opacity-100 transition-opacity">Support</a>
          </div>

          {/* DYNAMIC STATUS SECTION */}
          <div className="flex items-center gap-3">
            {!engineActive ? (
              /* State 1: Before the user runs the code */
              <span className="text-[10px] uppercase tracking-widest font-bold opacity-30 animate-pulse">
                Awaiting Connection
              </span>
            ) : (
              /* State 2: Once the code is executed and backend signals active */
              <button className="text-xs font-bold px-4 py-2 rounded-full border border-blue-500/20 bg-blue-500/5 text-blue-400/60 flex items-center gap-2 cursor-wait">
                <Loader2 size={12} className="animate-spin" />
                Setup in Progress
              </button>
            )}
          </div>
        </div>
      </nav>

      {/* --- MAIN CONTENT SECTION --- */}
      <main className="flex-grow flex flex-col items-center py-20 px-6">
        <div className="max-w-4xl w-full animate-in fade-in slide-in-from-bottom-8 duration-1000">
          
          <div className="text-center mb-16">
            <h1 className={`text-5xl font-black tracking-tight mb-6 bg-clip-text text-transparent bg-gradient-to-b ${
              isDark ? 'from-white to-white/40' : 'from-slate-900 to-slate-500'
            }`}>
              Set Up Your Environment
            </h1>
            <p className={`text-lg max-w-2xl mx-auto ${isDark ? 'text-zinc-400' : 'text-slate-600'}`}>
              Piper Engine requires a secure connection to your infrastructure. Choose your preferred deployment method below to get started.
            </p>
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-5 gap-8 items-stretch">
            <div className={`lg:col-span-3 p-8 rounded-3xl border relative overflow-hidden transition-all ${
              isDark ? 'bg-zinc-900/40 border-white/5 shadow-2xl' : 'bg-white border-slate-200 shadow-xl'
            }`}>
              <div className="flex items-center justify-between mb-8">
                <div className="flex items-center gap-3">
                  <div className="p-2 bg-blue-500/10 rounded-lg">
                    <Server size={20} className="text-blue-500" />
                  </div>
                  <h3 className="font-bold text-lg">Server CLI</h3>
                </div>
              </div>

              <div className={`relative group p-6 rounded-2xl font-mono text-[13px] border transition-all mb-8 ${
                isDark ? 'bg-black border-white/10 text-blue-400' : 'bg-slate-900 border-slate-800 text-blue-300'
              }`}>
                <div className="pr-12 break-all leading-relaxed">
                  {command}
                </div>
                <button 
                  onClick={handleCopy}
                  className="absolute top-5 right-5 p-2 rounded-lg bg-white/5 hover:bg-white/10 border border-white/10 transition-all"
                >
                  {copied ? <Check size={16} className="text-green-500" /> : <Copy size={16} className="opacity-50" />}
                </button>
              </div>

              <div className="space-y-4">
                <div className="flex items-center gap-3 text-xs opacity-50">
                  <Shield size={14} />
                  <span>Secure TLS encryption active</span>
                </div>
                <div className="flex items-center gap-3 text-xs opacity-50">
                  <Monitor size={14} />
                  <span>Compatible with Linux, macOS, and WSL</span>
                </div>
              </div>
            </div>

            <div className={`lg:col-span-2 p-8 rounded-3xl border flex flex-col justify-between transition-all ${
              isDark ? 'bg-blue-600/5 border-blue-500/20' : 'bg-blue-50 border-blue-100'
            }`}>
              <div>
                <div className="p-3 bg-blue-500/10 rounded-2xl inline-block mb-6">
                  <Download size={24} className="text-blue-500" />
                </div>
                <h4 className="text-xl font-bold mb-3 text-blue-500">Desktop App</h4>
                <p className="text-sm opacity-70 leading-relaxed mb-8">
                  Prefer a visual interface? Download our native Windows installer to manage your engine with one click.
                </p>
              </div>
              <button className="w-full py-4 rounded-2xl bg-blue-600 hover:bg-blue-500 text-white font-bold transition-all shadow-lg shadow-blue-600/30">
                Download for Windows
              </button>
            </div>
          </div>
        </div>
      </main>

      {/* --- FOOTER --- */}
      <footer className={`border-t py-12 ${isDark ? 'border-white/5 bg-black' : 'border-slate-200 bg-white'}`}>
        <div className="max-w-7xl mx-auto px-6">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-12 mb-12">
            <div className="col-span-2 md:col-span-1">
              <div className="flex items-center gap-2 mb-6">
                <Zap size={20} className="text-blue-500" />
                <span className="font-bold tracking-tight uppercase">Piper</span>
              </div>
              <p className="text-sm opacity-50 leading-relaxed">
                The high-speed visual automation engine for modern developers.
              </p>
            </div>
            <div>
              <h5 className="font-bold text-xs uppercase tracking-widest mb-6 opacity-40">Product</h5>
              <ul className="text-sm space-y-4 opacity-70 font-medium">
                <li><a href="#" className="hover:text-blue-500 transition-colors">Features</a></li>
                <li><a href="#" className="hover:text-blue-500 transition-colors">Enterprise</a></li>
                <li><a href="#" className="hover:text-blue-500 transition-colors">Pricing</a></li>
              </ul>
            </div>
            <div>
              <h5 className="font-bold text-xs uppercase tracking-widest mb-6 opacity-40">Company</h5>
              <ul className="text-sm space-y-4 opacity-70 font-medium">
                <li><a href="#" className="hover:text-blue-500 transition-colors">About Us</a></li>
                <li><a href="#" className="hover:text-blue-500 transition-colors">Careers</a></li>
                <li><a href="#" className="hover:text-blue-500 transition-colors">Privacy</a></li>
              </ul>
            </div>
            <div>
              <h5 className="font-bold text-xs uppercase tracking-widest mb-6 opacity-40">Social</h5>
              <div className="flex gap-4">
                <MessageSquare size={20} className="opacity-50 hover:opacity-100 cursor-pointer" />
                <Code2 size={20} className="opacity-50 hover:opacity-100 cursor-pointer" />
                <Globe size={20} className="opacity-50 hover:opacity-100 cursor-pointer" />
              </div>
            </div>
          </div>
          <div className="pt-8 border-t border-white/5 text-[11px] opacity-30 flex justify-between uppercase tracking-widest">
            <span>© 2026 Philz-Dev Systems</span>
            <span>All Systems Operational</span>
          </div>
        </div>
      </footer>
    </div>
  );
};

export default InstallationGuide;