import { useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { useEffect } from "react";
import { useAuth } from "../lib/auth";
import { supabase } from "../lib/supabase";
import { useData } from "../lib/useData";

const NAV = [
  { to: "/", label: "Resumen", icon: "🏠" },
  { to: "/aprobaciones", label: "Aprobaciones", icon: "✅", badge: true },
  { to: "/actividad", label: "Actividad de agentes", icon: "🤖" },
  { to: "/calendario", label: "Calendario", icon: "📅" },
  { to: "/videos", label: "Vídeos", icon: "🎬" },
  { to: "/investigacion", label: "Investigación", icon: "🔎" },
  { to: "/estadisticas", label: "Estadísticas", icon: "📈" },
  { to: "/tareas", label: "Tareas", icon: "📝" },
  { to: "/historial", label: "Historial", icon: "🗂️" },
  { to: "/configuracion", label: "Configuración", icon: "⚙️" },
];

function Logo() {
  return (
    <svg width="30" height="30" viewBox="0 0 64 64" aria-hidden="true">
      <rect width="64" height="64" rx="16" fill="#F5EBD8" />
      <g fill="#203D2B">
        <ellipse cx="32" cy="40" rx="11" ry="9" />
        <circle cx="19" cy="27" r="5" />
        <circle cx="27" cy="19" r="5" />
        <circle cx="37" cy="19" r="5" />
        <circle cx="45" cy="27" r="5" />
      </g>
      <circle cx="32" cy="40" r="3" fill="#C66A3D" />
    </svg>
  );
}

export function Layout() {
  const { profile, signOut } = useAuth();
  const [open, setOpen] = useState(false);
  const loc = useLocation();
  useEffect(() => setOpen(false), [loc.pathname]);
  const pending = useData(async () => {
    const { count } = await supabase
      .from("proposals")
      .select("id", { count: "exact", head: true })
      .eq("status", "pending_approval");
    return count ?? 0;
  }, [loc.pathname], 30_000);

  return (
    <div className="app">
      <div className="mobile-bar">
        <Logo /> PUAVI AI
        <span className="spacer" />
        <button onClick={() => setOpen(true)} aria-label="Abrir menú">
          Menú{pending.data ? ` · ${pending.data}` : ""}
        </button>
      </div>
      <aside className={`sidebar ${open ? "open" : ""}`}>
        <div className="brand">
          <Logo />
          <div>
            PUAVI AI
            <small>Panel de marketing</small>
          </div>
          {open && (
            <button className="btn small" style={{ marginLeft: "auto" }} onClick={() => setOpen(false)}>
              Cerrar
            </button>
          )}
        </div>
        <nav className="nav" aria-label="Secciones">
          {NAV.map((n) => (
            <NavLink key={n.to} to={n.to} end={n.to === "/"}>
              <span aria-hidden="true">{n.icon}</span>
              {n.label}
              {n.badge && pending.data ? <span className="count">{pending.data}</span> : null}
            </NavLink>
          ))}
        </nav>
        <div style={{ marginTop: 24, padding: "0 12px", fontSize: "0.85rem", opacity: 0.85 }}>
          <div>{profile?.display_name}</div>
          <div style={{ opacity: 0.75 }}>{profile?.role === "owner" ? "Propietario" : "Solo lectura"}</div>
          <button className="btn small" style={{ marginTop: 10 }} onClick={() => void signOut()}>
            Cerrar sesión
          </button>
        </div>
      </aside>
      <main className="main">
        <Outlet />
      </main>
    </div>
  );
}
