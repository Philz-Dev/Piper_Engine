"use client";
import { useState, useEffect } from 'react';
import Sidebar from '@/components/Sidebar';
import Dashboard from '@/components/Dashboard';
import InstallationGuide from '@/components/InstallationGuide';
import { Search, Bell, HelpCircle, Grid, Sun, Moon, Loader2 } from 'lucide-react';

export default function Home() {
  const [activeTab, setActiveTab] = useState('containers');
  const [selectedAutomation, setSelectedAutomation] = useState<string | null>(null);
  const [theme, setTheme] = useState<'dark' | 'light' | null>(null);
  const [engineActive, setEngineActive] = useState<boolean>(false);
  const [engineLoading, setEngineLoading] = useState<boolean>(true);

  useEffect(() => {
    const savedTheme = localStorage.getItem('piper-theme') as 'dark' | 'light';
    setTheme(savedTheme || 'dark');
  }, []);

  useEffect(() => {
    if (!theme) return;
    const root = window.document.documentElement;
    localStorage.setItem('piper-theme', theme);
    if (theme === 'light') {
      root.classList.remove('dark');
      root.style.setProperty('color-scheme', 'light');
    } else {
      root.classList.add('dark');
      root.style.setProperty('color-scheme', 'dark');
    }
  }, [theme]);

  useEffect(() => {
    let isMounted = true;
    async function checkEngine() {
      try {
        const res = await fetch('/api/v1/engine/status');
        const data = await res.json();
        if (isMounted) setEngineActive(data.status === 'active' || data.active === true);
      } catch (err) {
        if (isMounted) setEngineActive(false);
      } finally {
        if (isMounted) setEngineLoading(false);
      }
    }
    checkEngine();
    const interval = setInterval(checkEngine, 5000);
    return () => { isMounted = false; clearInterval(interval); };
  }, []);

  const toggleTheme = () => setTheme(theme === 'dark' ? 'light' : 'dark');
  const isDark = theme !== 'light';

  if (theme === null) return <div className="h-screen w-screen bg-black" />;

  return (
    // FIX 1: Changed overflow-y-auto to overflow-hidden here
    <div className={`flex flex-col h-screen font-sans antialiased overflow-hidden ${isDark ? 'bg-black' : 'bg-white'}`}>
      
      {/* HEADER */}
      <header className="h-[55px] border-b flex items-center px-6 shrink-0 z-[60] bg-black border-[#262626] !text-white">
        <div className="flex items-center gap-3 w-[180px] shrink-0">
          <div className="w-6 h-6 border rounded-sm flex items-center justify-center text-[10px] font-bold border-white/40 !text-white">P</div>
          <span className="font-bold tracking-tight text-sm uppercase !text-white">piper desktop</span>
        </div>

        <div className="flex-1 flex justify-center px-10">
          <div className="relative w-full max-w-xl">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 !text-white/20" size={14} />
            <input 
              type="text" 
              placeholder="Search..." 
              className="w-full border rounded-md px-10 py-1.5 text-xs focus:outline-none bg-[#111] border-[#262626] !text-white placeholder:!text-white/20"
            />
          </div>
        </div>

        <div className="flex items-center gap-6 ml-auto shrink-0">
          <button onClick={toggleTheme} className="p-1.5 rounded-md hover:bg-white/10 !text-white/40">
            {isDark ? <Sun size={18} /> : <Moon size={18} />}
          </button>
          <HelpCircle size={18} className="!text-white/40 hover:!text-white cursor-pointer" />
          <div className="relative cursor-pointer">
            <Bell size={18} className="!text-white/40 hover:!text-white" />
            <span className="absolute -top-1 -right-1 text-[8px] px-1 font-bold rounded-full border bg-white !text-black border-black">3</span>
          </div>
          <Grid size={18} className="!text-white/40 hover:!text-white cursor-pointer" />
          <button className="border px-4 py-1 rounded text-xs font-bold transition-all border-white/20 bg-white !text-black hover:bg-white/90">Sign in</button>
        </div>
      </header>

      {/* CONTENT AREA */}
      {engineLoading ? (
        <div className="flex-1 flex items-center justify-center">
          <Loader2 className="animate-spin text-blue-500" size={32} />
        </div>
      ) : !engineActive ? (
        <div className="flex-1 overflow-y-auto">
          <InstallationGuide 
            theme={theme || 'dark'} 
            installToken="PIPER-772-X90" 
            engineActive={engineActive} 
          />
        </div>
      ) : (
        <div className="flex flex-1 overflow-hidden animate-in fade-in duration-500">
          <Sidebar 
            activeTab={activeTab} 
            setActiveTab={(tab) => { setActiveTab(tab); setSelectedAutomation(null); }} 
            theme={theme} 
          />
          
          <main className={`flex-1 flex flex-col overflow-hidden ${isDark ? 'bg-black text-white' : 'bg-[#fafafa] text-black'}`}>
            
            {/* FIX 2: Changed overflow-y-auto to overflow-hidden and removed p-10 */}
            <div className="flex-1 overflow-hidden">
              {selectedAutomation ? (
                <div className="h-full flex flex-col p-10 animate-in fade-in duration-300">
                  <button 
                    onClick={() => setSelectedAutomation(null)}
                    className={`mb-8 text-[10px] uppercase tracking-widest flex items-center gap-2 ${isDark ? 'text-white/40 hover:text-white' : 'text-black/40 hover:text-black'}`}
                  >
                    ← Back to Containers
                  </button>
                  <div className={`w-full flex-1 border rounded-lg border-dashed flex flex-col items-center justify-center ${isDark ? 'border-[#262626] bg-[#050505]' : 'border-gray-300 bg-white'}`}>
                     <p className={`text-xs uppercase tracking-[0.3em] font-bold italic ${isDark ? 'text-white/20' : 'text-black/20'}`}>Module Details: {selectedAutomation}</p>
                  </div>
                </div>
              ) : (
                // Dashboard will now handle its own layout and scroll internal table only
                activeTab === 'containers' && <Dashboard onSelectRow={setSelectedAutomation} theme={theme!} />
              )}
            </div>

            <footer className="h-10 border-t flex items-center px-6 text-[10px] justify-between shrink-0 bg-black border-[#262626] !text-white/40">
              <div className="flex items-center gap-4">
                <div className="flex items-center gap-2">
                  <div className="w-2 h-2 rounded-full animate-pulse bg-white shadow-[0_0_8px_rgba(255,255,255,0.4)]" />
                  <span className="font-bold uppercase !text-white/80">Engine running</span>
                </div>
                <div className="flex items-center gap-4 border-l pl-4 uppercase tracking-tighter font-mono border-[#262626]">
                  <span>RAM 2.70 GB</span>
                  <span>CPU 14.80%</span>
                </div>
              </div>
              <div className="flex items-center gap-4 uppercase font-bold">
                 <span>Piper Engine</span>
                 <span className="underline decoration-dotted !text-white/80">v4.57.0</span>
              </div>
            </footer>
          </main>
        </div>
      )}
    </div>
  );
}