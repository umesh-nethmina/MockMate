// FR-60 / UC-05: admins add and edit coding problems. The server runs the reference solution against every
// test in the sandbox and refuses to save the problem if any test fails.
import { useEffect, useState } from "react";
import {
  archiveProblem,
  createProblem,
  listProblems,
  updateProblem,
  type AdminProblem,
  type ProblemInput,
} from "../api";

const TEMPLATE: ProblemInput = {
  title: "Reverse Words",
  difficulty: "easy",
  topic: "Strings",
  statement: "Given a sentence s, return the words in reverse order, separated by single spaces.",
  function_name: "reverse_words",
  params: ["s"],
  tests: [
    { args: ["hello world"], expected: "world hello", hidden: false },
    { args: ["  a  b "], expected: "b a", hidden: true },
  ],
  hints: ["Split the sentence into words first.", "str.split() with no argument ignores extra spaces."],
  reference_solution: "def reverse_words(s):\n    return ' '.join(reversed(s.split()))\n",
  expected_complexity: "O(n) time and O(n) space",
  is_active: true,
};

function toInput(p: AdminProblem): ProblemInput {
  return {
    title: p.title,
    difficulty: p.difficulty,
    topic: p.topic,
    statement: p.statement,
    function_name: p.function_name,
    params: p.params,
    tests: p.tests,
    hints: p.hints,
    reference_solution: p.reference_solution,
    expected_complexity: p.expected_complexity,
    is_active: p.is_active,
  };
}

export default function AdminProblems() {
  const [problems, setProblems] = useState<AdminProblem[] | null>(null);
  const [editing, setEditing] = useState<{ id: number | null; text: string } | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = () =>
    listProblems()
      .then(setProblems)
      .catch((e: Error) => setError(e.message));
  useEffect(() => {
    void load();
  }, []);

  async function save() {
    if (!editing) return;
    let body: ProblemInput;
    try {
      body = JSON.parse(editing.text) as ProblemInput;
    } catch (e) {
      setError(`That is not valid JSON: ${(e as Error).message}`);
      return;
    }
    setSaving(true);
    setError(null);
    try {
      if (editing.id === null) await createProblem(body);
      else await updateProblem(editing.id, body);
      setEditing(null);
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  }

  async function archive(p: AdminProblem) {
    if (!window.confirm(`Archive "${p.title}"? It will no longer be offered in new interviews.`)) return;
    try {
      await archiveProblem(p.id);
      await load();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <section className="card">
      <div className="row spread">
        <h2 className="h3">Coding problems</h2>
        <button
          type="button"
          onClick={() => {
            setError(null);
            setEditing({ id: null, text: JSON.stringify(TEMPLATE, null, 2) });
          }}
        >
          New problem
        </button>
      </div>

      {editing && (
        <div className="problem-editor">
          <label htmlFor="problem-json" className="small">
            {editing.id === null ? "New problem" : `Edit problem #${editing.id}`} (JSON). The reference solution is
            Python and must pass every test; mark at least one test as hidden.
          </label>
          <textarea
            id="problem-json"
            rows={22}
            spellCheck={false}
            value={editing.text}
            onChange={(e) => setEditing({ ...editing, text: e.target.value })}
          />
          <div className="row">
            <button type="button" className="primary" onClick={() => void save()} disabled={saving}>
              {saving ? "Checking reference solution…" : "Validate and save"}
            </button>
            <button type="button" className="ghost" onClick={() => setEditing(null)} disabled={saving}>
              Cancel
            </button>
          </div>
        </div>
      )}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}

      {problems === null ? (
        <p className="muted">Loading problems…</p>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Title</th>
                <th>Difficulty</th>
                <th>Topic</th>
                <th className="num">Tests</th>
                <th className="num">Used</th>
                <th>Status</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {problems.map((p) => (
                <tr key={p.id} className={p.is_active ? "" : "muted"}>
                  <td>{p.title}</td>
                  <td>{p.difficulty}</td>
                  <td>{p.topic}</td>
                  <td className="num">
                    {p.tests.filter((t) => !t.hidden).length} + {p.tests.filter((t) => t.hidden).length} hidden
                  </td>
                  <td className="num">{p.times_used}</td>
                  <td>{p.is_active ? "active" : "archived"}</td>
                  <td className="row">
                    <button
                      type="button"
                      className="link"
                      onClick={() => {
                        setError(null);
                        setEditing({ id: p.id, text: JSON.stringify(toInput(p), null, 2) });
                      }}
                    >
                      Edit
                    </button>
                    {p.is_active && (
                      <button type="button" className="link" onClick={() => void archive(p)}>
                        Archive
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
