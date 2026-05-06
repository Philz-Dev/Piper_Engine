"use client";
import React from 'react';
import { ArrowLeft, ExternalLink, Terminal } from 'lucide-react';

interface WorkspaceProps {
  serviceId: string;
  onBack: () => void;
}

const Workspace: React.FC<WorkspaceProps> = ({ serviceId, onBack }) => {
  return (
    <div className="animate-in slide-in-from-right duration-300">
      <div className="flex items-center justify-between mb-8">
        <button onClick={onBack} className="flex items-center gap-2 text-[#9fa3a9] hover:text-white transition-colors">
          <ArrowLeft size={20} />
          <span>Back to Dashboard</span>
        </button>
        <div className="flex gap-2">
          <button className="bg-[#303235] text-white px-4 py-2 rounded-lg text-sm flex items-center gap-2">
            <ExternalLink size={16} /> Open Config
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 bg-[#1c1e21] border border-dashed border-[#303235] rounded-xl h-[600px] flex items-center justify-center text-[#6a6d71]">
          <div className="text-center">
            <div className="mb-4 opacity-20 flex justify-center">
              <Terminal size={48} />
            </div>
            <p className="text-sm font-medium">Flow Editor Loading...</p>
            <p className="text-xs mt-1 opacity-50">Rendering YAML to Visual Nodes</p>
          </div>
        </div>

        <div className="space-y-6">
          <div className="bg-[#242526] border border-[#303235] rounded-xl p-6">
            <h4 className="text-white font-bold mb-4 uppercase text-[10px] tracking-widest text-blue-500">Service Info</h4>
            <div className="space-y-4 text-sm text-left">
              <div>
                <p className="text-[#6a6d71] text-xs">Filename</p>
                <p className="text-[#e4e6eb] font-mono break-all">{serviceId}</p>
              </div>
              <div>
                <p className="text-[#6a6d71] text-xs">Target Host</p>
                <p className="text-[#e4e6eb]">127.0.0.1:8000</p>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default Workspace;