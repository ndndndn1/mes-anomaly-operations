import React, {useState} from "react";
import {createRoot} from "react-dom/client";

type Verdict = {timestamp: string; sensor: string; value: number; severity: string; rule: string; score: number | null};
type Evaluation = {eventId: string; replayed: boolean; evaluated: number; verdicts: Verdict[]};

function App() {
  const [eventId, setEventId] = useState(() => crypto.randomUUID());
  const [result, setResult] = useState<Evaluation | null>(null);
  const [lastPayload, setLastPayload] = useState<object | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function verify(replay = false) {
    const selectedEvent = replay ? eventId : crypto.randomUUID();
    if (!replay) setEventId(selectedEvent);
    const samples = Array.from({length: 6}, (_, index) => ({timestamp: new Date(Date.now() + index * 1000).toISOString(),
      values: {temperature: index === 5 ? 92 : 45 + index * 0.02}}));
    const nextPayload = replay && lastPayload ? lastPayload : {eventId: selectedEvent, lineId: "demo", equipmentId: "press-1",
      limits: {temperature: {low: 10, high: 80}}, samples};
    if (!replay) setLastPayload(nextPayload);
    setBusy(true); setError("");
    try {
      const response = await fetch("/api/v1/evaluations", {method: "POST", headers: {"content-type": "application/json"},
        body: JSON.stringify(nextPayload)});
      const body = await response.json();
      if (!response.ok) throw new Error(`${body.title ?? "Request failed"}: ${body.detail ?? response.status}`);
      setResult(body);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unexpected request failure");
    } finally { setBusy(false); }
  }
  return <main style={{fontFamily:"system-ui",maxWidth:960,margin:"3rem auto",padding:"0 1rem"}}>
    <h1>MES anomaly evaluation</h1>
    <p>Decision-support only. This interface does not send commands to PLCs or equipment.</p>
    <p><strong>Event ID:</strong> <code>{eventId}</code></p>
    <button disabled={busy} onClick={() => verify(false)}>Evaluate new event</button>{" "}
    <button disabled={busy || !result} onClick={() => verify(true)}>Replay same event</button>
    {error && <p role="alert" style={{color:"#a00"}}>{error}</p>}
    {result && <section><h2>{result.replayed ? "Idempotent replay" : "Committed evaluation"}</h2>
      <p>{result.evaluated} measurements evaluated.</p>
      <table style={{borderCollapse:"collapse",width:"100%"}}><thead><tr>
        <th>Time</th><th>Sensor</th><th>Value</th><th>Severity</th><th>Rule</th><th>Score</th>
      </tr></thead><tbody>{result.verdicts.map((verdict, index) => <tr key={`${verdict.timestamp}-${verdict.sensor}-${index}`}>
        <td>{new Date(verdict.timestamp).toLocaleTimeString()}</td><td>{verdict.sensor}</td><td>{verdict.value}</td>
        <td>{verdict.severity}</td><td>{verdict.rule}</td><td>{verdict.score === null ? "—" : verdict.score.toFixed(2)}</td>
      </tr>)}</tbody></table>
    </section>}
  </main>;
}

createRoot(document.getElementById("root")!).render(<App/>);
