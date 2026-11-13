import { Link, NavLink, Navigate, Route, Routes, useLocation } from "react-router-dom";
import type { ReactNode } from "react";
import { useAuth } from "./auth";
import BookingsPage from "./pages/BookingsPage";
import CreateEventPage from "./pages/CreateEventPage";
import EventPage from "./pages/EventPage";
import EventsPage from "./pages/EventsPage";
import LoginPage from "./pages/LoginPage";
import OrganizerPage from "./pages/OrganizerPage";
import RegisterPage from "./pages/RegisterPage";

/** Sends anonymous visitors to /login and brings them back afterwards. */
export function RequireAuth({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  const location = useLocation();
  if (!user) return <Navigate to={`/login?next=${encodeURIComponent(location.pathname)}`} replace />;
  return children;
}

/** Organizer-only pages, by the `role` returned at login. The API enforces it too (403). */
function RequireOrganizer({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  if (user && user.role !== "organizer") return <p className="alert alert-error">Organizers only.</p>;
  return <RequireAuth>{children}</RequireAuth>;
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
        {user?.role === "organizer" && <NavLink to="/organizer">Organizer</NavLink>}
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
          <Route
            path="/organizer"
            element={
              <RequireOrganizer>
                <OrganizerPage />
              </RequireOrganizer>
            }
          />
          <Route
            path="/organizer/new"
            element={
              <RequireOrganizer>
                <CreateEventPage />
              </RequireOrganizer>
            }
          />
          <Route path="*" element={<p>Page not found.</p>} />
        </Routes>
      </main>
    </>
  );
}
