function handler(context) {
    // 1. Process your data and explicitly return the output object
    return {
        dev_name: "philzzzzzz"
    };
}

// 2. Export the handler so runner.js can require it
module.exports = { handler };