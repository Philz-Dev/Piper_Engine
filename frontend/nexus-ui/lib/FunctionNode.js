const FunctionNode = ({ node, updateNode }) => {
  if (node.type === 'Literal') {
    return <input value={node.value} onChange={(e) => updateNode({...node, value: e.target.value})} />;
  }

  // It's a function call!
  return (
    <div className="function-node">
      <span className="func-name">{node.name}</span>
      <div className="args">
        {node.args.map((arg, i) => (
          <FunctionNode key={i} node={arg} updateNode={(newArg) => {
             // Logic to update a specific argument in the AST
          }} />
        ))}
      </div>
    </div>
  );
};