const fs = require('fs');
const path = require('path');

async function main() {
    // 1. Get the filename from args
    const userScriptFile = process.argv[2];
    if (!userScriptFile) {
        console.log(JSON.stringify({ error: "No user script provided" }));
        process.exit(1);
    }

    // 2. Load the User's Code
    let handler;
    try {
        // We resolve the absolute path to the mounted user file
        const userModule = require(path.resolve(__dirname, userScriptFile));
        handler = userModule.handler;
        
        if (typeof handler !== 'function') {
            throw new Error("The script must export a 'handler' function: module.exports = { handler };");
        }
    } catch (e) {
        console.log(JSON.stringify({ error: `Load Error: ${e.message}` }));
        process.exit(1);
    }

    // 3. Receive Context from Stdin (File Descriptor 0)
    try {
        const inputData = fs.readFileSync(0, 'utf8');
        const context = inputData ? JSON.parse(inputData) : {};

        // 4. Execute User Logic (supports async/await)
        const output = await handler(context);

        // 5. Standardize the Return
        process.stdout.write("PIPER_RESULT_START\n");
        process.stdout.write(JSON.stringify(output));
        process.stdout.write("\nPIPER_RESULT_END\n");

    } catch (e) {
        console.log(JSON.stringify({ error: `Execution Error: ${e.message}` }));
        process.exit(1);
    }
}

main();