const fs = require('fs');
const path = require('path');
const Redis = require('ioredis');

const context_data = JSON.parse(process.env.PIPER_CONTEXT || "{}");
const resultKey = process.env.PIPER_RESULT_KEY;
const redisHost = process.env.REDIS_HOST || "redis-broker";
const redisPort = parseInt(process.env.REDIS_PORT || "6379", 10);

const r = new Redis({
    host: redisHost,
    port: redisPort,
    retryStrategy: () => null // Avoid infinite loop retries inside the sandbox
});

const responseChannel = process.env.PIPER_RESPONSE_CHANNEL;

async function writeResult(data) {
    if (responseChannel) {
        try {
            await r.publish(responseChannel, JSON.stringify(data || {}));
        } catch (e) {
            console.error(JSON.stringify({ error: `Redis Publish Error: {e.message}` }));
        } finally {
            await r.quit();
        }
    } else {
        process.stdout.write("PIPER_RESULT_START\n");
        process.stdout.write(JSON.stringify(data || {}));
        process.stdout.write("\nPIPER_RESULT_END\n");
        await r.quit();
    }
}

async function main() {
    const userScriptFile = process.argv[2];
    
    if (!userScriptFile) {
        await writeResult({ error: "No user script provided" });
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
        await writeResult({ error: `Load Error: ${e.message}` });
        process.exit(1);
    }

    try {
        const output = await handler(context_data);
        await writeResult(output || {});
    } catch (e) {
        await writeResult({ error: `Execution Error: ${e.message}` });
        process.exit(1);
    }
}

main();