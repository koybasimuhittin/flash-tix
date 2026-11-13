import { Link, NavLink, Navigate, Route, Routes, useLocation } from "react-router-dom";
import type { ReactNode } from "react";
import { useAuth } from "./auth";
import BookingsPage from "./pages/BookingsPage";
import EventPage from "./pages/EventPage";
import EventsPage from "./pages/EventsPage";
import LoginPage from "./pages/LoginPage";
import RegisterPage from "./pages/RegisterPage";

/** Sends anonymous visitors to /login and brings them back afterwards. */
export function RequireAuth({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  const location = useLocation();
  if (!user) return <Navigate to={`/login?next=${encodeURIComponent(location.pathname)}`} replace />;
  return children;
}

function Header() {
  const { user, logout } = useAuth();
  return (
    <header className="header">
      <Link to="/" className="brand">
        ⚡ FlashTix
      </Link>
      <nav className="nav">
        <NavLink to="/" end>
          Events
        </NavLink>
        {user && <NavLink to="/bookings">My bookings</NavLink>}
        {user ? (
          <>
            <span className="muted">{user.name}</span>
            <button className="link-button" onClick={logout}>
              Log out
            </button>
          </>
        ) : (
          <>
            <NavLink to="/login">Log in</NavLink>
            <NavLink to="/register">Register</NavLink>
          </>
        )}
      </nav>
    </header>
  );
}

export default function App() {
  return (
    <>
      <Header />
      <main className="container">
        <Routes>
          <Route path="/" element={<EventsPage />} />
          <Route path="/events/:id" element={<EventPage />} />
          <Route path="/login" element={<LoginPage />} />
          <Route path="/register" element={<RegisterPage />} />
          <Route
            path="/bookings"
            element={
              <RequireAuth>
                <BookingsPage />
              </RequireAuth>
            }
          />
          <Route path="*" element={<p>Page not found.</p>} />
        </Routes>
      </main>
    </>
  );
}
