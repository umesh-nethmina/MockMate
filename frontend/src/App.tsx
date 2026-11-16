import { useEffect, useState } from "react";
import { api } from "./api";

type Health = { status: string; environment: string };

export default function App() {
  const [health, setHealth] = useState<string>("checking…");

  useEffect(() => {
    api<Health>("/health")
      .then((h) => setHealth(`${h.status} (${h.environment})`))
      .catch((e: Error) => setHealth(`unreachable: ${e.message}`));
  }, []);

  return (
    <main className="container">
      <h1>MockMate</h1>
      <p className="muted">AI mock interviews with scored feedback.</p>
      <p>
        API: <strong>{health}</strong>
      </p>
    </main>
  );
}
