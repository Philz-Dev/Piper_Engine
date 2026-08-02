"use client";
import React from 'react';
import { Lock, KeyRound, Loader2 } from 'lucide-react';

interface AuthOverlayProps {
  isDark: boolean;
  passwordExists: boolean;
  password: string;
  setPassword: (val: string) => void;
  authError: string;
  loading: boolean;
  onUnlock: () => void;
}

const AuthOverlay: React.FC<AuthOverlayProps> = ({
  isDark,
  passwordExists,
  password,
  setPassword,
  authError,
  loading,
  onUnlock,
}) => {
  return (
    <div className="absolute inset-0 z-[100] flex items-center justify-center backdrop-blur-md bg-modal-overlay">
      <div className={`p-8 rounded-2xl border shadow-2xl w-full max-w-md ${isDark ? 'bg-surface border-border' : 'bg-surface border-border'}`}>
        <div className="flex flex-col items-center text-center mb-6">
          <div className={`p-4 rounded-full mb-4 ${isDark ? 'bg-dash-blue-alpha' : 'bg-dash-blue-alpha'}`}>
            <Lock size={32} className="text-pipeline-selected" />
          </div>
          <h2 className={`text-xl font-bold ${isDark ? 'text-background' : 'text-foreground'}`}>
            {passwordExists ? "Engine Locked" : "Setup Engine"}
          </h2>
          <p className={`text-sm mt-2 ${isDark ? 'text-dash-slate-text' : 'text-dash-slate-text'}`}>
            {passwordExists ? "Enter your Master Password to access the Piper Engine dashboard." : "No Master Password detected."}
          </p>
        </div>

        <div className="space-y-4">
          <div className="relative">
            <KeyRound size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-dash-zinc-muted" />
            <input 
              type="password" 
              placeholder={passwordExists ? "Master Password" : "Create Master Password"}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && onUnlock()}
              className={`w-full pl-10 pr-4 py-2.5 rounded-xl border outline-none transition-all ${isDark ? 'bg-field-input border-border focus:border-pipeline-selected' : 'bg-field-input border-border focus:border-pipeline-selected'}`}
            />
          </div>
          {authError && <p className="text-log-error text-[11px] font-bold text-center uppercase">{authError}</p>}
          <button onClick={onUnlock} disabled={loading} className="w-full bg-primary text-background font-semibold py-2.5 rounded-xl">
            {loading ? <Loader2 size={18} className="animate-spin mx-auto" /> : (passwordExists ? "Unlock Dashboard" : "Initialize Engine")}
          </button>
        </div>
      </div>
    </div>
  );
};

export default AuthOverlay;