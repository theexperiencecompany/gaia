#!/usr/bin/env node
/**
 * Dummy door control server for testing
 * Runs on localhost:3001 and accepts door operation requests
 *
 * Usage: node scripts/door-server.js
 */

const http = require("http");

const PORT = 3001;
let doorState = false; // false = closed, true = open

const server = http.createServer((req, res) => {
  // Enable CORS
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Methods", "POST, OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type");

  // Handle preflight
  if (req.method === "OPTIONS") {
    res.writeHead(200);
    res.end();
    return;
  }

  if (req.method === "POST" && req.url === "/door") {
    let body = "";

    req.on("data", (chunk) => {
      body += chunk.toString();
    });

    req.on("end", () => {
      try {
        const data = JSON.parse(body);
        const { action, open } = data;

        // Update door state
        doorState = open;

        const timestamp = new Date().toISOString();

        console.log(
          `[${timestamp}] Door ${action} - State: ${
            doorState ? "OPEN" : "CLOSED"
          }`
        );

        // Simulate some processing time
        setTimeout(() => {
          res.writeHead(200, { "Content-Type": "application/json" });
          res.end(
            JSON.stringify({
              success: true,
              action,
              state: doorState ? "open" : "closed",
              timestamp,
              message: `Door successfully ${action}ed`,
            })
          );
        }, 500); // 500ms delay to simulate hardware operation
      } catch (error) {
        console.error("Error processing request:", error);
        res.writeHead(400, { "Content-Type": "application/json" });
        res.end(
          JSON.stringify({
            success: false,
            error: "Invalid request format",
          })
        );
      }
    });
  } else {
    res.writeHead(404, { "Content-Type": "application/json" });
    res.end(
      JSON.stringify({
        error: "Not found",
      })
    );
  }
});

server.listen(PORT, () => {
  console.log(`🚪 Door Control Server running on http://localhost:${PORT}`);
  console.log(`   Current door state: ${doorState ? "OPEN" : "CLOSED"}`);
  console.log(`   Waiting for commands...`);
});

// Handle shutdown gracefully
process.on("SIGINT", () => {
  console.log("\n\n👋 Shutting down door control server...");
  server.close(() => {
    console.log("✅ Server closed");
    process.exit(0);
  });
});
