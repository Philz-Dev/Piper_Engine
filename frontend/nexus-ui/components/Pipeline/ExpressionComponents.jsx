import React from 'react';

export const FunctionNode = ({ node, updateNode }) => {
  if (node.type === 'Literal') {
    return (
      <input 
        className="bg-field-input border border-border rounded px-2 py-1 text-xs"
        value={node.value} 
        onChange={(e) => updateNode({ ...node, value: e.target.value })} 
      />
    );
  }

  return (
    <div className="flex flex-col gap-1 border border-border p-2 rounded bg-surface">
      <span className="text-xs font-bold text-pipeline-selected">{node.name}</span>
      <div className="flex flex-wrap gap-2 pl-4">
        {node.args.map((arg, i) => (
          <FunctionNode 
            key={i} 
            node={arg} 
            updateNode={(newArg) => {
              const newArgs = [...node.args];
              newArgs[i] = newArg;
              updateNode({ ...node, args: newArgs });
            }} 
          />
        ))}
      </div>
    </div>
  );
};

export const ExpressionEditor = ({ astList, onChange }) => {
  return (
    <div className="flex flex-col gap-4">
      {astList.map((ast, index) => (
        <div key={index} className="expression-block p-2 border border-border rounded">
          <FunctionNode 
            node={ast} 
            updateNode={(newNode) => {
              // This is a simplified handler; you would implement logic here 
              // to reconstruct the string from the AST and pass it up
            }} 
          />
        </div>
      ))}
    </div>
  );
};