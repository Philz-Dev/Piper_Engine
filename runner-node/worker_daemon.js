const { spawn } = require('child_process');
const Redis = require('ioredis');

const redisHost = process.env.REDIS_HOST || "redis-broker";
const redisPort = parseInt(process.env.REDIS_PORT || "6379", 10);

const r = new Redis({
    host: redisHost,
    port: redisPort,
    retryStrategy: (times) => Math.min(times * 50, 2000)
});

const WORKER_STREAM = "piper_node_stream";
const GROUP_NAME = "node_workers";
const CONSUMER_NAME = process.env.SANDBOX_WORKER_NAME || "node-worker-1";

async function initConsumerGroup() {
    try {
        await r.xgroup("CREATE", WORKER_STREAM, GROUP_NAME, "0", "MKSTREAM");
    } catch (e) {
        // Group already exists, safe to ignore
    }
}

async function processStreamTask(taskData) {
    const filePath = taskData.file_path;
    const context = taskData.context || {};
    const responseChannel = taskData.response_channel;

    // Configure environment variables for the single-shot runner.js execution
    const env = {
        ...process.env,
        PIPER_CONTEXT: JSON.stringify(context),
        PYTHONUNBUFFERED: "1"
    };
    if (responseChannel) {
        env.PIPER_RESPONSE_CHANNEL = responseChannel;
    }

    // Invoke your single-shot runner.js safely via child_process
    const cmdArgs = ['/app/runner-node/runner.js', filePath];
    
    try {
        const child = spawn('node', cmdArgs, { env, stdio: 'inherit' });
        
        await new Promise((resolve) => {
            const timer = setTimeout(() => {
                child.kill('SIGKILL');
                if (responseChannel) {
                    r.publish(responseChannel, JSON.stringify({ error: "Subprocess execution timed out after 30 seconds" }));
                }
                resolve();
            }, 30000);

            child.on('close', () => {
                clearTimeout(timer);
                resolve();
            });
            
            child.on('error', (err) => {
                clearTimeout(timer);
                if (responseChannel) {
                    r.publish(responseChannel, JSON.stringify({ error: `Subprocess launch crash: ${err.message}` }));
                }
                resolve();
            });
        });
    } catch (e) {
        if (responseChannel) {
            await r.publish(responseChannel, JSON.stringify({ error: `Subprocess launch crash: ${e.message}` }));
        }
    }
}

async function main() {
    await initConsumerGroup();
    console.log(`Node Stream Worker ${CONSUMER_NAME} is listening to ${WORKER_STREAM}...`);

    while (true) {
        try {
            const results = await r.xreadgroup(
                'GROUP', GROUP_NAME, CONSUMER_NAME,
                'BLOCK', 2000,
                'COUNT', 1,
                'STREAMS', WORKER_STREAM, '>'
            );

            if (results) {
                for (const [stream, messages] of results) {
                    for (const [messageId, fields] of messages) {
                        let payloadStr = "{}";
                        if (Array.isArray(fields)) {
                            for (let i = 0; i < fields.length; i += 2) {
                                if (fields[i] === 'payload') {
                                    payloadStr = fields[i + 1];
                                    break;
                                }
                            }
                        } else if (typeof fields === 'object') {
                            payloadStr = fields.payload || "{}";
                        }

                        const taskPayload = JSON.parse(payloadStr);
                        await processStreamTask(taskPayload);
                        await r.xack(WORKER_STREAM, GROUP_NAME, messageId);
                    }
                }
            }
        } catch (e) {
            console.error(`Worker Error: ${e.message}`);
            await new Promise(res => setTimeout(res, 1000));
        }
    }
}

main();