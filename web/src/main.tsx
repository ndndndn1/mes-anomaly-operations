import React, {useState} from "react";
import {createRoot} from "react-dom/client";

function App() {
  const [result, setResult] = useState("Ready");
  async function verify() {
    const samples = Array.from({length: 6}, (_, index) => ({
      timestamp: new Date(Date.now() + index * 1000).toISOString(), values: {temperature: index === 5 ? 92 : 45 + index * 0.02}
    }));
    const response = await fetch("/api/judge", {method: "POST", headers: {"content-type": "application/json"},
      body: JSON.stringify({lineId: "demo", equipmentId: "press-1", limits: {temperature: {low: 10, high: 80}}, samples})});
    const body = await response.json();
    setResult(JSON.stringify(body, null, 2));
  }
  return <main><h1>MES anomaly operations</h1><p>Evaluate ordered sensor batches against absolute and robust statistical limits.</p><button onClick={verify}>Run verification</button><pre>{result}</pre></main>;
}

createRoot(document.getElementById("root")!).render(<App/>);
