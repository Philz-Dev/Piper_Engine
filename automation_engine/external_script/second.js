function handler(context) {
    // 1. Safe access check (highly recommended for pipeline builders)
    const previousStep = context.process_data || {};
    
    return {
        // Look for 'dev_name' since that's what the previous step actually returned!
        dev_namewwwwwws: previousStep.dev_name || "Unknown Developer" 
    };
}

module.exports = { handler };