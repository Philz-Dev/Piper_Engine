'use client';
import React from 'react';
import { Handle, Position } from '@xyflow/react';
import { Mail, Zap } from 'lucide-react';

const Icons: { [key: string]: any } = {
  gmail: <Mail size={32} className="text-red-500" />,
  hubspot: <Zap size={32} className="text-orange-500" />
};

export default function ActionNode({ data, selected }: any) {
  const Icon = Icons[data.type] || <Zap size={32} />;

  return (
    <div className="flex flex-col items-center group">
      <div className={`
        w-20 h-20 rounded-[30px] border-[2px] flex items-center justify-center transition-all
        ${selected ? 'border-green-400 bg-black scale-110 shadow-[0_0_20px_rgba(74,222,128,0.2)]' : 'border-white/10 bg-[#0a0a0b]'}
      `}>
        <Handle type="target" position={Position.Left} className="!bg-cyan-400 !border-none !w-2 !h-6 !rounded-full" />
        {Icon}
        <Handle type="source" position={Position.Right} className="!bg-cyan-400 !border-none !w-2 !h-6 !rounded-full" />
      </div>
      <span className="mt-2 text-[10px] font-bold uppercase tracking-tighter text-white/40">{data.type}</span>
    </div>
  );
}