import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import "./styles.css";
import { Layout } from "./components/Layout";
import { AuthProvider, useAuth } from "./lib/auth";
import { configError } from "./lib/supabase";
import { Actividad } from "./pages/Actividad";
import { Aprobaciones } from "./pages/Aprobaciones";
import { Calendario } from "./pages/Calendario";
import { Configuracion } from "./pages/Configuracion";
import { Estadisticas } from "./pages/Estadisticas";
import { Historial } from "./pages/Historial";
import { Investigacion } from "./pages/Investigacion";
import { Login } from "./pages/Login";
import { Resumen } from "./pages/Resumen";
import { Tareas } from "./pages/Tareas";
import { Videos } from "./pages/Videos";

function Gate() {
  const { session, profile, loading, signOut } = useAuth();
  if (configError) {
    return (
      <div className="login">
        <div className="card error">{configError}</div>
      </div>
    );
  }
  if (loading) return <div className="login">Cargando…</div>;
  if (!session) return <Login />;
  if (!profile) {
    return (
      <div className="login">
        <div className="card stack">
          <h2>Cuenta sin acceso</h2>
          <p>Tu usuario no tiene perfil en PUAVI AI. Pide a la persona propietaria que te dé acceso.</p>
          <button className="btn" onClick={() => void signOut()}>
            Cerrar sesión
          </button>
        </div>
      </div>
    );
  }
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Resumen />} />
        <Route path="aprobaciones" element={<Aprobaciones />} />
        <Route path="actividad" element={<Actividad />} />
        <Route path="calendario" element={<Calendario />} />
        <Route path="videos" element={<Videos />} />
        <Route path="investigacion" element={<Investigacion />} />
        <Route path="estadisticas" element={<Estadisticas />} />
        <Route path="tareas" element={<Tareas />} />
        <Route path="historial" element={<Historial />} />
        <Route path="configuracion" element={<Configuracion />} />
        <Route path="*" element={<Resumen />} />
      </Route>
    </Routes>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <AuthProvider>
        <Gate />
      </AuthProvider>
    </BrowserRouter>
  </StrictMode>,
);
