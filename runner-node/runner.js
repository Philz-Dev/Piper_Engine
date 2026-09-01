const fs = require('fs');
const path = require('path');

const context_data = JSON.parse(process.env.PIPER_CONTEXT || "{}");

function writeResult(data) {
    process.stdout.write("PIPER_RESULT_START\n");
    process.stdout.write(JSON.stringify(data || {}));
    process.stdout.write("\nPIPER_RESULT_END\n");
}

async function main() {
    const userScriptFile = process.argv[2];

    if (!userScriptFile) {
        writeResult({ error: "No user script provided" });
        process.exit(1);
    }

    let handler;
    try {
        const targetPath = path.isAbsolute(userScriptFile)
            ? userScriptFile
            : path.join(process.cwd(), userScriptFile);

        const userModule = require(targetPath);
        handler = userModule.handler;

        if (typeof handler !== 'function') {
            throw new Error("Export a 'handler' function: module.exports = { handler };");
        }
    } catch (e) {
        writeResult({ error: `Load Error: ${e.message}` });
        process.exit(1);
    }

    try {
        const output = await handler(context_data);
        writeResult(output || {});
    } catch (e) {
        writeResult({ error: `Execution Error: ${e.message}` });
        process.exit(1);
    }
}

main();