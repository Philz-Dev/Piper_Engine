export const ExpressionEngine = {
  // 1. Tokenizer
  tokenize(input) {
    const tokens = [];
    const regex = /\s*([a-zA-Z_$][a-zA-Z0-9_$]*|[0-9]+|==|!=|[|(),=]|\"[^\"]*\"|'[^']*')\s*/g;
    let match;
    while ((match = regex.exec(input)) !== null) {
      const value = match[1];
      if (value === '|') tokens.push({ type: 'PIPE', value });
      else if (value === '(') tokens.push({ type: 'LPAREN', value });
      else if (value === ')') tokens.push({ type: 'RPAREN', value });
      else if (value === ',') tokens.push({ type: 'COMMA', value });
      else if (value === '=') tokens.push({ type: 'ASSIGN', value });
      else if (value.startsWith('"') || value.startsWith("'")) tokens.push({ type: 'STRING', value: value.slice(1, -1) });
      else if (!isNaN(value)) tokens.push({ type: 'NUMBER', value: parseFloat(value) });
      else tokens.push({ type: 'IDENTIFIER', value });
    }
    return tokens;
  },

  // 2. Parser (Recursive Descent)
  parse(input) {
    const tokens = this.tokenize(input);
    let pos = 0;
    const peek = () => tokens[pos];
    const eat = () => tokens[pos++];

    const parseArgs = (isCLI = false) => {
      const args = [];
      if (!isCLI && peek()?.type === 'RPAREN') return args;
      while (pos < tokens.length) {
        if (isCLI && (peek()?.type === 'PIPE' || peek()?.type === 'RPAREN' || !peek())) break;
        if (tokens[pos + 1]?.type === 'ASSIGN') {
          const key = eat().value;
          eat();
          const val = eat().value;
          args.push({ type: 'NamedArgument', key, value: { type: 'Literal', value: val } });
        } else {
          args.push(parseExpression());
        }
        if (peek()?.type === 'COMMA') eat();
        else if (!isCLI && peek()?.type !== 'RPAREN') continue;
        else break;
      }
      return args;
    };

    const parseExpression = () => {
      const token = eat();
      if (token.type === 'IDENTIFIER' && peek()?.type === 'LPAREN') {
        eat();
        const args = parseArgs(false);
        eat();
        return { type: 'CallExpression', name: token.value, args };
      }
      return { type: 'Literal', value: token.value };
    };

    let node = parseExpression();

    while (peek()?.type === 'PIPE') {
      eat();
      const nameToken = eat();
      let args = [];
      if (peek()?.type === 'LPAREN') {
        eat(); args = parseArgs(false); eat();
      } else {
        args = parseArgs(true);
      }
      node = { type: 'CallExpression', name: nameToken.value, args: [node, ...args] };
    }
    return node;
  },

  // 3. Main Interface
  process(rawString) {
    const regex = /\{\{(.*?)\}\}/g;
    return [...rawString.matchAll(regex)].map(match => this.parse(match[1]));
  },

  // 4. Compiler (Programming style)
  compile(node, data = null) {
    if (node.type === 'Literal') return node.value;
    if (node.type === 'NamedArgument') return `${node.key}=${this.compile(node.value, data)}`;

    if (data && node.args.every(arg => arg.type !== 'CallExpression')) {
      const args = [data, ...node.args].map(arg => this.compile(arg)).join(', ');
      return `${node.name}(${args})`;
    }

    const args = node.args.map(arg => {
      if (arg.type === 'CallExpression') return this.compile(arg, data);
      return this.compile(arg);
    }).join(', ');

    return `${node.name}(${args})`;
  },

  // 5. Compiler (CLI style: data | func key=val)
  compileToCLI(node) {
    if (node.type === 'Literal') return node.value;
    if (node.type === 'CallExpression') {
      const [dataNode, ...argsNodes] = node.args;
      const renderedData = this.compileToCLI(dataNode);
      const renderedArgs = argsNodes.map(arg => {
        // Enforce kwargs: key=value
        if (arg.type === 'NamedArgument') return `${arg.key}=${arg.value.value}`;
        return this.compileToCLI(arg);
      }).join(' ');
      return `${renderedData} | ${node.name} ${renderedArgs}`.trim();
    }
    return "";
  }
};