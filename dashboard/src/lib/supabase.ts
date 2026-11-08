import { createClient } from "@supabase/supabase-js";

const url = import.meta.env.VITE_SUPABASE_URL as string | undefined;
const anonKey = import.meta.env.VITE_SUPABASE_ANON_KEY as string | undefined;

export const configError =
  !url || !anonKey
    ? "Faltan VITE_SUPABASE_URL y VITE_SUPABASE_ANON_KEY en la configuración del panel."
    : null;

// La clave anon es pública por diseño: toda la seguridad la imponen las
// políticas RLS y las funciones de la base de datos.
export const supabase = createClient(url ?? "http://localhost", anonKey ?? "missing", {
  auth: { persistSession: true, autoRefreshToken: true },
});

export async function signedMediaUrl(path: string, seconds = 3600): Promise<string | null> {
  const { data, error } = await supabase.storage.from("media").createSignedUrl(path, seconds);
  if (error) return null;
  return data.signedUrl;
}
