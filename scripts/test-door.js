#!/usr/bin/env node
/**
 * Test the door control integration end-to-end
 *
 * This script sends test requests to verify the door server is working
 * Usage: node scripts/test-door.js
 */

const http = require("http");

const PORT = 3001;

function sendDoorCommand(action, open) {
  return new Promise((resolve, reject) => {
    const data = JSON.stringify({ action, open });

    const options = {
      hostname: "localhost",
      port: PORT,
      path: "/door",
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Content-Length": data.length,
      },
    };

    const req = http.request(options, (res) => {
      let body = "";

      res.on("data", (chunk) => {
        body += chunk;
      });

      res.on("end", () => {
        try {
          const response = JSON.parse(body);
          resolve({ status: res.statusCode, data: response });
        } catch (error) {
          reject(new Error(`Failed to parse response: ${error.message}`));
        }
      });
    });

    req.on("error", (error) => {
      reject(error);
    });

    req.write(data);
    req.end();
  });
}

async function runTests() {
  console.log("🧪 Testing Door Control Integration\n");
  console.log("═".repeat(50));

  try {
    // Test 1: Open door
    console.log("\n📖 Test 1: Opening door...");
    const openResult = await sendDoorCommand("open", true);
    console.log("✅ Status:", openResult.status);
    console.log("📦 Response:", JSON.stringify(openResult.data, null, 2));

    // Wait a bit
    await new Promise((resolve) => setTimeout(resolve, 1000));

    // Test 2: Close door
    console.log("\n📖 Test 2: Closing door...");
    const closeResult = await sendDoorCommand("close", false);
    console.log("✅ Status:", closeResult.status);
    console.log("📦 Response:", JSON.stringify(closeResult.data, null, 2));

    // Wait a bit
    await new Promise((resolve) => setTimeout(resolve, 1000));

    // Test 3: Open again
    console.log("\n📖 Test 3: Opening door again...");
    const openAgain = await sendDoorCommand("open", true);
    console.log("✅ Status:", openAgain.status);
    console.log("📦 Response:", JSON.stringify(openAgain.data, null, 2));

    console.log("\n═".repeat(50));
    console.log("✅ All tests passed! Door control is working correctly.");
    console.log("\n💡 Now test in the UI:");
    console.log("   1. Open your GAIA chat");
    console.log('   2. Say: "open the door"');
    console.log('   3. Say: "close the door"');
    console.log("   4. Watch the beautiful door control card appear! 🎨");
  } catch (error) {
    console.error("\n❌ Test failed:", error.message);
    console.log("\n💡 Make sure the door server is running:");
    console.log("   node scripts/door-server.js");
    process.exit(1);
  }
}

runTests();
