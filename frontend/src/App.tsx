import { Link, NavLink, Route, Routes, useNavigate } from "react-router-dom";
import { RequireAuth, useAuth } from "./auth";
import AccountPage from "./pages/AccountPage";
import AdminPage from "./pages/AdminPage";
import HistoryPage from "./pages/HistoryPage";
import InterviewPage from "./pages/InterviewPage";
import LoginPage from "./pages/LoginPage";
import ReportPage from "./pages/ReportPage";
import SetupPage from "./pages/SetupPage";

function Header() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  return (
    <header className="topbar">
      <Link to="/" className="brand">
        MockMate
      </Link>
      {user && (
        <nav className="nav" aria-label="Main">
          <NavLink to="/" end>
            New interview
          </NavLink>
          {!user.is_guest && <NavLink to="/history">My interviews</NavLink>}
          {user.is_admin && <NavLink to="/admin">Admin</NavLink>}
          <NavLink to="/account">{user.is_guest ? "Guest" : "Account"}</NavLink>
          <button
            className="link"
            onClick={() => {
              logout();
              navigate("/login");
            }}
          >
            Log out
          </button>
        </nav>
      )}
    </header>
  );
}

const guard = (el: React.ReactNode, admin = false) => <RequireAuth admin={admin}>{el}</RequireAuth>;

export default function App() {
  return (
    <>
      <Header />
      <main className="container">
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/" element={guard(<SetupPage />)} />
          <Route path="/interview/:id" element={guard(<InterviewPage />)} />
          <Route path="/report/:id" element={guard(<ReportPage />)} />
          <Route path="/history" element={guard(<HistoryPage />)} />
          <Route path="/account" element={guard(<AccountPage />)} />
          <Route path="/admin" element={guard(<AdminPage />, true)} />
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
