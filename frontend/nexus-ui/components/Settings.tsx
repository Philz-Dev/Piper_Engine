"use client";
import React, { useState } from 'react';
import { User, Shield, Key, Layout, Bell, Save } from 'lucide-react';

interface SettingsPageProps {
  // Keeping prop signature for API compatibility, though styling now relies on CSS variables
  theme?: 'dark' | 'light';
}

export default function SettingsPage({ theme }: SettingsPageProps) {
  const [activeSubTab, setActiveSubTab] = useState('profile');

  const NavItem = ({ id, icon: Icon, label }: any) => (
    <button
      onClick={() => setActiveSubTab(id)}
      className={`w-full flex items-center gap-3 px-4 py-2 text-sm font-medium rounded-md transition-colors ${
        activeSubTab === id 
          ? 'bg-pipeline-btn text-pipeline-text-heading' 
          : 'text-pipeline-text hover:bg-border-light hover:text-pipeline-text-heading'
      }`}
    >
      <Icon size={16} />
      {label}
    </button>
  );

  return (
    <div className="h-full flex bg-background text-foreground transition-colors">
      {/* Settings Sidebar */}
      <aside className="w-64 border-r border-border p-6 space-y-6">
        <div>
          <h2 className="text-sm font-bold mb-4 px-4 text-pipeline-text-heading">Settings</h2>
          <nav className="space-y-1">
            <NavItem id="profile" icon={User} label="Profile" />
            <NavItem id="security" icon={Shield} label="Security" />
            <NavItem id="api" icon={Key} label="API Keys" />
            <NavItem id="notifications" icon={Bell} label="Notifications" />
          </nav>
        </div>
      </aside>

      {/* Main Content Area */}
      <main className="flex-1 overflow-y-auto p-10 bg-builder-pure">
        <div className="max-w-2xl space-y-10">
          <div>
            <h1 className="text-2xl font-bold mb-2 text-pipeline-text-heading">
              {activeSubTab.charAt(0).toUpperCase() + activeSubTab.slice(1)}
            </h1>
            <p className="text-sm text-pipeline-text">
              Manage your {activeSubTab} preferences and account settings.
            </p>
          </div>

          {/* Settings Card */}
          <div className="border border-border rounded-xl p-8 shadow-sm bg-surface">
            <div className="space-y-6">
              <div className="grid grid-cols-2 gap-6">
                <div className="space-y-2">
                  <label className="text-xs font-semibold uppercase tracking-wider text-pipeline-text">
                    Full Name
                  </label>
                  <input 
                    type="text" 
                    className="w-full border border-border rounded-md px-3 py-2 text-sm outline-none bg-field-input text-foreground focus:border-pipeline-selected transition-colors" 
                    placeholder="John Doe" 
                  />
                </div>
                <div className="space-y-2">
                  <label className="text-xs font-semibold uppercase tracking-wider text-pipeline-text">
                    Email
                  </label>
                  <input 
                    type="email" 
                    className="w-full border border-border rounded-md px-3 py-2 text-sm outline-none bg-field-input text-foreground focus:border-pipeline-selected transition-colors" 
                    placeholder="john@company.com" 
                  />
                </div>
              </div>

              <div className="pt-6 border-t border-border flex justify-end">
                <button className="flex items-center gap-2 px-4 py-2 rounded-md text-sm font-bold bg-foreground text-background transition-opacity hover:opacity-90">
                  <Save size={14} />
                  Save Changes
                </button>
              </div>
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}