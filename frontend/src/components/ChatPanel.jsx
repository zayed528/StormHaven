// STUB (Abby UI + Nandan backend): chat with the StormHaven assistant via /api/chat.
// The backend answers offline (deterministic) when Bedrock isn't configured, so this works from hour 1.
// TODO: suggested-question chips for the 4 challenge questions, loading state, scroll to newest.
import React, { useState } from "react";
import { sendChat } from "../api/client.js";

export default function ChatPanel({ premiseId, scenario, profile }) {
  const [history, setHistory] = useState([]);       // Bedrock Converse shape
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);

  const send = async (e) => {
    e.preventDefault();
    if (!text.trim() || busy) return;
    // Send the whole conversation each turn; the backend is stateless.
    const next = [...history, { role: "user", content: [{ text: text.trim() }] }];
    setHistory(next); setText(""); setBusy(true);
    try {
      const { reply } = await sendChat({ history: next, premise_id: premiseId, scenario, profile });
      setHistory([...next, { role: "assistant", content: [{ text: reply }] }]);
    } catch (err) {
      setHistory([...next, { role: "assistant", content: [{ text: "Sorry, I couldn't reach the assistant. Check AEP's outage map." }] }]);
    } finally { setBusy(false); }
  };

  return (
    <section className="chat" aria-label="Ask StormHaven">
      <h2>Ask StormHaven</h2>
      <div className="chat-log" aria-live="polite">
        {history.map((m, i) => <p key={i} className={m.role}>{m.content[0].text}</p>)}
      </div>
      <form onSubmit={send}>
        <input value={text} onChange={(e) => setText(e.target.value)} placeholder="e.g. Will I lose power?"
          aria-label="Your question" disabled={!premiseId} />
        <button type="submit" disabled={!premiseId || busy}>{busy ? "…" : "Send"}</button>
      </form>
      {!premiseId && <p className="muted">Select your home on the map first.</p>}
    </section>
  );
}
