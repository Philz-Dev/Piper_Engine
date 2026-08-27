const path = require("path");

/** Absolute path to the installed schemas/ tree. */
function schemasRoot() {
  return path.join(__dirname, "schemas");
}

module.exports = { schemasRoot };