// components/Pipeline/PipelineCanvas.tsx
import React from 'react';
import { VisualBuilder } from './VisualBuilder';

export const PipelineCanvas = (props) => {
  return (
    <div className="relative flex-1 h-full overflow-hidden bg-[#050505]">
      {/* The actual Builder */}
      <div className="w-full h-full overflow-auto">
        <VisualBuilder {...props} />
      </div>

      {/* The Mini-map Overlay */}
      <div className="absolute bottom-8 right-8 w-48 h-32 bg-zinc-900/90 border border-white/10 rounded-lg shadow-2xl z-40 p-2 overflow-hidden pointer-events-none">
        <div className="text-[9px] text-zinc-500 font-bold uppercase tracking-widest mb-1">Pipeline Map</div>
        {/* Render a scaled-down snapshot of your pipeline data here */}
        <div className="w-full h-full border border-white/5 rounded bg-black/20" />
      </div>
    </div>
  );
};