import { Ticket, Zap } from "lucide-react";
import type { ReactNode } from "react";
import { Link, NavLink, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { useAuth } from "./auth";
import { Button } from "./components/ui/button";
import { cn } from "./lib/utils";
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
  if (user && user.role !== "organizer") {
    return (
      <div className="mx-auto max-w-md py-16 text-center">
        <h1 className="font-poster text-3xl">Organizers only</h1>
        <p className="mt-2 text-muted-foreground">This page is for event organizers. Browse events to buy tickets.</p>
        <Button asChild className="mt-6">
          <Link to="/">See events</Link>
        </Button>
      </div>
    );
  }
  return <RequireAuth>{children}</RequireAuth>;
}

function NavItem({ to, children, end }: { to: string; children: ReactNode; end?: boolean }) {
  return (
    <NavLink
      to={to}
      end={end}
      className={({ isActive }) =>
        cn(
          "relative py-1 text-sm font-medium text-muted-foreground transition-colors hover:text-foreground",
          isActive && "text-foreground after:absolute after:inset-x-0 after:-bottom-[17px] after:h-[3px] after:bg-stub",
        )
      }
    >
      {children}
    </NavLink>
  );
}

function Header() {
  const { user, logout } = useAuth();
  return (
    <header className="sticky top-0 z-20 border-b border-border bg-card/95 backdrop-blur">
      <div className="mx-auto flex h-16 max-w-6xl items-center justify-between gap-4 px-4">
        <Link to="/" className="flex items-center gap-2">
          <span className="flex size-8 items-center justify-center rounded-md bg-stub">
            <Zap className="size-4 fill-ink text-ink" />
          </span>
          <span className="font-poster text-2xl">FlashTix</span>
        </Link>
        <nav className="flex items-center gap-4 sm:gap-6">
          <NavItem to="/" end>
            Events
          </NavItem>
          {user && (
            <NavItem to="/bookings">
              <span className="inline-flex items-center gap-1.5">
                <Ticket className="size-4" />
                <span className="hidden sm:inline">My tickets</span>
              </span>
            </NavItem>
          )}
          {user?.role === "organizer" && <NavItem to="/organizer">Organizer</NavItem>}
          {user ? (
            <div className="flex items-center gap-3 border-l border-border pl-4">
              <span className="hidden text-sm text-muted-foreground md:inline">{user.name}</span>
              <Button variant="ghost" size="sm" onClick={logout}>
                Log out
              </Button>
            </div>
          ) : (
            <div className="flex items-center gap-2">
              <Button asChild variant="ghost" size="sm">
                <Link to="/login">Log in</Link>
              </Button>
              <Button asChild size="sm">
                <Link to="/register">Sign up</Link>
              </Button>
            </div>
          )}
        </nav>
      </div>
    </header>
  );
}

export default function App() {
  return (
    <>
      <Header />
      <main>
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
          <Route
            path="*"
            element={
              <div className="mx-auto max-w-md py-16 text-center">
                <h1 className="font-poster text-3xl">Page not found</h1>
                <Button asChild className="mt-6">
                  <Link to="/">See events</Link>
                </Button>
              </div>
            }
          />
        </Routes>
      </main>
    </>
  );
}
