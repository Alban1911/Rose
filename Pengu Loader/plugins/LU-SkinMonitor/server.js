// save as server.js
import { WebSocketServer } from "ws";

const PORT = 3000;
const wss = new WebSocketServer({ port: PORT });

wss.on("connection", (ws, request) => {
    console.log(`Client connected from ${request.socket.remoteAddress}`);

    ws.on("message", (data) => {
        try {
            const payload = JSON.parse(data.toString());
            console.log(`[SkinMonitor Bridge] skin=${payload.skin} at ${new Date(payload.timestamp).toISOString()}`);
        } catch (error) {
            console.warn("[SkinMonitor Bridge] failed to parse message", error);
            console.log("Raw payload:", data.toString());
        }
    });

    ws.on("close", () => {
        console.log("Client disconnected");
    });
});

console.log(`WebSocket bridge listening on ws://localhost:${PORT}`);