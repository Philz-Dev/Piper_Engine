import { useState } from 'react';
import { ExpressionEngine } from './ExpressionEngine'; // Your utility

export const useExpressionManager = (initialRawString) => {
  // 1. STATE: This is what your UI components will map over
  const [expressionList, setExpressionList] = useState(() => 
    ExpressionEngine.process(initialRawString)
  );

  // 2. LOAD: Call this when you fetch new data from the backend
  const loadExpressions = (rawString) => {
    setExpressionList(ExpressionEngine.process(rawString));
  };

  // 3. SAVE: Call this when you hit the "Save" button in your UI
  const compileToYaml = () => {
    return expressionList
      .map(node => `{{${ExpressionEngine.compile(node)}}}`)
      .join(' ');
  };

  return { expressionList, setExpressionList, loadExpressions, compileToYaml };
};