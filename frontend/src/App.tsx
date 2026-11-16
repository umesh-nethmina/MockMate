import { Link, Route, Routes } from "react-router-dom";
import SetupPage from "./pages/SetupPage";
import InterviewPage from "./pages/InterviewPage";
import ReportPage from "./pages/ReportPage";

export default function App() {
  return (
    <>
      <header className="topbar">
        <Link to="/" className="brand">
          MockMate
        </Link>
      </header>
      <main className="container">
        <Routes>
          <Route path="/" element={<SetupPage />} />
          <Route path="/interview/:id" element={<InterviewPage />} />
          <Route path="/report/:id" element={<ReportPage />} />
          <Route
            path="*"
            element={
              <p>
                Page not found. <Link to="/">Start an interview</Link>
              </p>
            }
          />
        </Routes>
      </main>
    </>
  );
}
