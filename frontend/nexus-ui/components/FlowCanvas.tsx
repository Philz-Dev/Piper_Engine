'use client';
import React from 'react';
import { ReactFlow, Background, Controls } from '@xyflow/react';
import '@xyflow/react/dist/style.css';

interface FlowCanvasProps {
  nodes: any[];
  edges: any[];
  onNodesChange: (changes: any) => void;
  onEdgesChange: (changes: any) => void;
  onConnect: (params: any) => void;
  nodeTypes: any;
  onNodeClick: (event: any, node: any) => void;
  onPaneClick: () => void;
  defaultEdgeOptions: any;
}

const FlowCanvas = ({ 
  nodes, 
  edges, 
  onNodesChange, 
  onEdgesChange, 
  onConnect, 
  nodeTypes, 
  onNodeClick, 
  onPaneClick,
  defaultEdgeOptions 
}: FlowCanvasProps) => {
  return (
    <div style={{ width: '100%', height: '100%', minHeight: '500px' }}>
      <ReactFlow 
        nodes={nodes} 
        edges={edges} 
        nodeTypes={nodeTypes} 
        onNodesChange={onNodesChange} 
        onEdgesChange={onEdgesChange} 
        onConnect={onConnect}
        onNodeClick={onNodeClick}
        onPaneClick={onPaneClick}
        deleteKeyCode={["Backspace", "Delete"]}
        defaultEdgeOptions={defaultEdgeOptions}
        colorMode="dark"
        fitView
      >
        <Background color="#111" variant="lines" gap={50} className="opacity-10" />
        <Controls className="bg-[#080808] border border-[#1a1a1a] fill-[#4ade80]" />
      </ReactFlow>
    </div>
  );
}

// ✅ MANDATORY: Default export for the dynamic loader
export default FlowCanvas;