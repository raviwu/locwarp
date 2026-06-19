'use strict'

// Escape a string for embedding inside an AppleScript double-quoted string
// literal: backslash first, then double-quote.
function escapeAppleScriptString(s) {
  return String(s).replace(/\\/g, '\\\\').replace(/"/g, '\\"')
}

module.exports = { escapeAppleScriptString }
