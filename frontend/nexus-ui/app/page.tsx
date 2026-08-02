"use client";
import { useState, useEffect } from 'react';
import { usePiperConnection } from '@/hooks/usePiperConnection';
import Sidebar from '@/components/Sidebar';
import Dashboard from '@/components/Dashboard';
import InstallationGuide from '@/components/InstallationGuide';
import AuthModal from '@/components/Intervention';
import { Search, Bell, HelpCircle, Grid, Sun, Moon, Loader2 } from 'lucide-react';
import BuilderPage from '@/components/build';
import SettingsPage from '@/components/Settings';
import SubscriptionPage from '@/components/Subscription';
import AIchatbox from '@/components/AIchatbox';
import ClovoAuthPortal from '@/components/AuthScreen';
import { checkUserAccess } from '@/lib/api';

export default function Home() {
  // SINGLE SOURCE OF TRUTH: Initialize hook once
  const [userId, setUserId] = useState<string>('');
  const [userEmail, setUserEmail] = useState<string>('');
  const [activeClient, setActiveClient] = useState<string>('');

  const piperData = usePiperConnection(activeClient, userId);
  const { 
    engineActive, 
    engineLoading, 
    activeIntervention, 
    globalStats, 
    send, 
    setActiveIntervention,
    getScriptContent
  } = piperData;

  const [activeTab, setActiveTab] = useState('containers');
  const [selectedAutomation, setSelectedAutomation] = useState<string | null>(null);
  const [theme, setTheme] = useState<'dark' | 'light' | null>(null);
  const [checkingAuth, setCheckingAuth] = useState(true); 
  const [isAuthenticated, setIsAuthenticated] = useState<boolean | null>(null);
  const [isInstalled, setIsInstalled] = useState<boolean | null>(null);

  // --- ACCESS & AUTH CHECK ---
  useEffect(() => {
    async function verifyStatus() {
      setCheckingAuth(true);
      const stored = localStorage.getItem('piper_user');
      if (stored) {
        try {
          const parsed = JSON.parse(stored);
          const id = parsed.id || parsed.userId; // Fallback to email if id not present
          const email = parsed.email;

          console.log("Extracted IDs:", { id, email });
          
          if (id && email) {
            setUserId(id);
            setUserEmail(email);
            setIsAuthenticated(true);
            const data = await checkUserAccess(email);
            setIsInstalled(data.is_installed);
          } else {
            setIsAuthenticated(false);
          }
        } catch (err) {
          console.error("Access check failed:", err);
          setIsAuthenticated(false);
        }
      } else {
        setIsAuthenticated(false);
      }
      setCheckingAuth(false);
    }
    verifyStatus();
  }, []);

  // --- THEME LOGIC ---
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

  const handleResolveIntervention = async (id: number) => {
    try {
      // If we are connected locally via WebRTC, send the instruction over the Data Channel
      if (send) {
        send("resolve_intervention", { id });
        setActiveIntervention(null);
      } else {
        // Fallback to traditional HTTP server endpoint if no active WebRTC data channel exists
        const response = await fetch(`/api/v1/resolve-intervention/${id}`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
        });
        if (response.ok) setActiveIntervention(null);
      }
    } catch (err) {
      console.error("Error resolving intervention:", err);
    }
  };

  const handleAuthSuccess = (userData: any) => {
    localStorage.setItem('piper_user', JSON.stringify(userData));
    console.log('user data:      ',   userData)
    const id = userData?.id || userData?.userId;
    const email = userData?.email;
    if (id) setUserId(id);
    if (email) setUserEmail(email);
    setIsAuthenticated(true);
    window.location.reload();
  };

  const toggleTheme = () => setTheme(theme === 'dark' ? 'light' : 'dark');
  const isDark = theme !== 'light';

  if (theme === null || checkingAuth || isAuthenticated === null) {
    return <div className="h-screen w-screen bg-background flex items-center justify-center"><Loader2 className="animate-spin text-foreground" /></div>;
  }

  if (!isAuthenticated) {
    return (
      <div className="h-screen w-screen bg-background flex flex-col overflow-hidden">
        <ClovoAuthPortal onSuccess={handleAuthSuccess} theme={theme || 'dark'} toggleTheme={toggleTheme} />
      </div>
    );
  }
  
  return (
    <div className={`flex flex-col h-screen font-sans antialiased overflow-hidden bg-background text-foreground`}>
      
      <AuthModal 
        intervention={activeIntervention} 
        onClose={() => setActiveIntervention(null)}
        onResolve={handleResolveIntervention}
      />

      <header className="h-[55px] border-b flex items-center px-6 shrink-0 z-[60] bg-header border-header-border text-header-text">
        <div className="flex items-center gap-3 w-[180px] shrink-0">
          <div className="w-6 h-6 border rounded-sm flex items-center justify-center text-[10px] font-bold border-foreground/40 text-foreground">P</div>
          <span className="font-bold tracking-tight text-sm uppercase text-header-text">clovo</span>
        </div>

        <div className="flex-1 flex justify-center px-10">
          <div className="relative w-full max-w-xl">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-foreground/60" size={14} />
            <input 
              type="text" 
              placeholder="Search..." 
              className="w-full border rounded-md px-10 py-1.5 text-xs focus:outline-none bg-surface border-border-light focus:border-foreground/50 transition-colors text-foreground placeholder:text-foreground/50"
            />
          </div>
        </div>

        <div className="flex items-center gap-6 ml-auto shrink-0">
          <button onClick={toggleTheme} className="p-1.5 rounded-md hover:bg-header-text/10 text-header-text/40">
            {isDark ? <Sun size={18} /> : <Moon size={18} />}
          </button>
          <HelpCircle size={18} className="text-header-text/40 hover:text-header-text cursor-pointer" />
          <div className="relative cursor-pointer">
            <Bell size={18} className="text-header-text/40 hover:text-header-text" />
            <span className="absolute -top-1 -right-1 text-[8px] px-1 font-bold rounded-full border bg-header-text text-header border-header">3</span>
          </div>
          <Grid size={18} className="text-header-text/40 hover:text-header-text cursor-pointer" />
          <button 
            onClick={() => {
              localStorage.removeItem('piper_user');
              setIsAuthenticated(false);
            }} 
            className="border px-4 py-1 rounded text-xs font-bold transition-all border-header-text/20 bg-header-text text-header hover:bg-header-text/90"
          >
            Sign out
          </button>
        </div>
      </header>

      {engineLoading || isInstalled === null ? (
        <div className="flex-1 flex items-center justify-center">
          <Loader2 className="animate-spin text-primary" size={32} />
        </div>
      ) : !isInstalled ? (
        <div className="flex-1 overflow-y-auto">
          <InstallationGuide 
            theme={theme || 'dark'} 
            installToken="PIPER-772-X90" 
            engineActive={engineActive} 
            userEmail={userId}
          />
        </div>
      ) : (
        <div className="flex flex-1 overflow-hidden animate-in fade-in duration-500">
          <Sidebar 
            activeTab={activeTab} 
            setActiveTab={(tab) => { setActiveTab(tab); setSelectedAutomation(null); }} 
            theme={theme} 
          />
          
          <main className={`flex-1 flex flex-col overflow-hidden bg-background text-foreground`}>
            <div className={`flex-1 ${activeTab === 'subscription' ? 'overflow-y-auto' : 'overflow-hidden'}`}>
              {selectedAutomation ? (
                <div className="h-full flex flex-col p-10 animate-in fade-in duration-300">
                  <button 
                    onClick={() => setSelectedAutomation(null)}
                    className={`mb-8 text-[10px] uppercase tracking-widest flex items-center gap-2 text-foreground/40 hover:text-foreground`}
                  >
                    ← Back to Containers
                  </button>
                  <div className={`w-full flex-1 border rounded-lg border-dashed flex flex-col items-center justify-center border-border ${isDark ? 'bg-card' : 'bg-background'}`}>
                      <p className={`text-xs uppercase tracking-[0.3em] font-bold italic text-foreground/20`}>Module Details: {selectedAutomation}</p>
                  </div>
                </div>
              ) : (
                <>
                    {/* Props passed from unified piperData source */}
                    {activeTab === 'containers' && (
                      <Dashboard 
                        {...piperData} 
                        activeClient={activeClient}        // New prop
                        setActiveClient={setActiveClient}  // New prop
                        onSelectRow={(id) => setSelectedAutomation(id)}
                        theme={theme!} 
                        userId={userId} 
                      />
                    )}
                    {activeTab === 'builds' && (
                      <BuilderPage 
                        {...piperData} 
                        theme={theme} 
                        systemState={piperData.systemState || []} 
                        fetchSystemState={piperData.fetchSystemState} 
                        getScriptContent={getScriptContent}
                      />
                    )}
                    {activeTab === 'ask-gordon' && <AIchatbox theme={theme} />}
                    {activeTab === 'subscription' && <SubscriptionPage />}
                    {activeTab === 'settings' && <SettingsPage theme={theme} />}
                </>
              )}
            </div>

            <footer className="h-10 border-t flex items-center px-6 text-[10px] justify-between shrink-0 bg-header border-header-border text-header-text/40">
              <div className="flex items-center gap-4">
                <div className="flex items-center gap-2">
                  <div className={`w-2 h-2 rounded-full ${engineActive ? 'animate-pulse bg-header-text shadow-[0_0_8px_rgb(var(--headertext)/0.4)]' : 'bg-red-500/80 shadow-[0_0_8px_rgba(239,68,68,0.4)]'}`} />
                  <span className="font-bold uppercase text-header-text/80">
                    {engineActive ? 'Engine running' : 'Engine offline'}
                  </span>
                </div>
                <div className="flex items-center gap-4 border-l pl-4 uppercase tracking-tighter font-mono border-header-border">
                  <span>RAM {globalStats.ram}</span>
                  <span>CPU {globalStats.cpu}</span>
                  <span>DISK {globalStats.disk}</span>
                </div>
              </div>
              <div className="flex items-center gap-4 uppercase font-bold">
                  <span>Piper Engine</span>
                  <span className="underline decoration-dotted text-header-text/80">v4.57.0</span>
              </div>
            </footer>
          </main>
        </div>
      )}
    </div>
  );
}