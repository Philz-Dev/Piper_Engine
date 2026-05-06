"use client";
import React from 'react';
import { Play, Square, ChevronRight, Clock } from 'lucide-react';

interface Service {
  id: string;
  name: string;
  status: string;
  path: string;
}

interface ServiceCardProps {
  service: Service;
  onClick: (id: string) => void;
  onStart: (id: string) => void;
  onStop: (id: string) => void;
}

const ServiceCard: React.FC<ServiceCardProps> = ({ service, onClick, onStart, onStop }) => {
  const isRunning = service.status === 'running';

  return (
    <div 
      onClick={() => onClick(service.id)}
      className="bg-[#242526] border border-[#303235] rounded-xl p-5 cursor-pointer transition-all hover:border-[#404245] hover:shadow-lg group text-left"
    >
      <div className="flex justify-between items-start mb-4">
        <div>
          <h3 className="text-[#e4e6eb] font-bold text-lg leading-tight group-hover:text-blue-400 transition-colors">
            {service.name}
          </h3>
          <p className="text-[#9fa3a9] text-xs font-mono mt-1">{service.id}</p>
        </div>
        <div className={`flex items-center gap-1.5 px-2 py-1 rounded text-[10px] font-bold uppercase tracking-wider ${
          isRunning ? 'text-emerald-500 bg-emerald-500/10' : 'text-[#9fa3a9] bg-[#303235]'
        }`}>
          <div className={`w-1.5 h-1.5 rounded-full ${isRunning ? 'bg-emerald-500 animate-pulse' : 'bg-[#6a6d71]'}`} />
          {service.status}
        </div>
      </div>

      <div className="flex items-center gap-2 text-[#6a6d71] text-xs mb-6">
        <Clock size={14} />
        <span>Modified 2h ago</span>
      </div>

      <div className="flex items-center justify-between">
        <button
          onClick={(e) => {
            e.stopPropagation();
            isRunning ? onStop(service.id) : onStart(service.id);
          }}
          className={`px-4 py-2 rounded-lg flex items-center gap-2 text-sm font-bold transition-all ${
            isRunning 
            ? 'bg-rose-500/10 text-rose-500 hover:bg-rose-500 hover:text-white' 
            : 'bg-emerald-500/10 text-emerald-500 hover:bg-emerald-500 hover:text-white'
          }`}
        >
          {isRunning ? <Square size={14} fill="currentColor" /> : <Play size={14} fill="currentColor" />}
          {isRunning ? 'Stop' : 'Start'}
        </button>
        <ChevronRight size={18} className="text-[#303235] group-hover:text-[#9fa3a9] transition-colors" />
      </div>
    </div>
  );
};

export default ServiceCard;