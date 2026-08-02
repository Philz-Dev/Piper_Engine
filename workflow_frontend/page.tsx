// components/WorkshopView.tsx
"use client";
import { useState } from 'react';
import { usePiperConnection } from '@/hooks/usePiperConnection';
import Sidebar from '@/components/Sidebar';
import Dashboard from '@/components/Dashboard';
import AuthModal from '@/components/Intervention';
import BuilderPage from '@/components/build';
import SettingsPage from '@/components/Settings';
import AIchatbox from '@/components/AIchatbox';

export default function WorkshopView({ theme, userEmail }: { theme: string, userEmail: string }) {
  const { 
    engineActive, 
    activeIntervention, 
    globalStats, 
    send, 
    setActiveIntervention 
  } = usePiperConnection();

  const [activeTab, setActiveTab] = useState('containers');
  const [selectedAutomation, setSelectedAutomation] = useState<string | null>(null);

  const handleResolveIntervention = async (id: number) => {
    if (send) {
        send("resolve_intervention", { id });
        setActiveIntervention(null);
    }
  };

  return (
    <div className="flex flex-1 overflow-hidden animate-in fade-in duration-500">
      <AuthModal 
        intervention={activeIntervention} 
        onClose={() => setActiveIntervention(null)}
        onResolve={handleResolveIntervention}
      />
      
      <Sidebar 
        activeTab={activeTab} 
        setActiveTab={(tab) => { setActiveTab(tab); setSelectedAutomation(null); }} 
        theme={theme} 
      />
      
      <main className="flex-1 flex flex-col overflow-hidden bg-background text-foreground">
        <div className="flex-1 overflow-hidden">
          {selectedAutomation ? (
             <div className="h-full p-10">
                <button onClick={() => setSelectedAutomation(null)}>← Back</button>
                <div className="border border-dashed p-4">Details: {selectedAutomation}</div>
             </div>
          ) : (
            <>
              {activeTab === 'containers' && <Dashboard theme={theme} send={send} />}
              {activeTab === 'builds' && <BuilderPage theme={theme} send={send} />}
              {activeTab === 'ask-gordon' && <AIchatbox theme={theme} />}
              {activeTab === 'settings' && <SettingsPage theme={theme} />}
            </>
          )}
        </div>

        {/* Footer Stats */}
        <footer className="h-10 border-t flex items-center px-6 text-[10px] bg-header text-header-text/40">
           <span>{engineActive ? 'Engine running' : 'Engine offline'}</span>
           <span className="ml-4">RAM: {globalStats.ram} | CPU: {globalStats.cpu}</span>
        </footer>
      </main>
    </div>
  );
}