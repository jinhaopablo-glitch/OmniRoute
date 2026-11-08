import { useCallback, useEffect, useRef, useState } from "react";

export interface DataState<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
  reload: () => void;
}

/**
 * Carga datos con una función asíncrona y los refresca cada `refreshMs`.
 * `fn` debe lanzar un Error con un mensaje legible si falla.
 */
export function useData<T>(fn: () => Promise<T>, deps: unknown[] = [], refreshMs = 60_000): DataState<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const fnRef = useRef(fn);
  fnRef.current = fn;

  const load = useCallback(async () => {
    try {
      const result = await fnRef.current();
      setData(result);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error desconocido");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    setLoading(true);
    void load();
    if (!refreshMs) return;
    const id = window.setInterval(() => {
      if (document.visibilityState === "visible") void load();
    }, refreshMs);
    return () => window.clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return { data, error, loading, reload: () => void load() };
}

/** Convierte el resultado de Supabase en datos o en un Error en español. */
export function unwrap<T>(res: { data: T | null; error: { message: string } | null }): T {
  if (res.error) throw new Error(translateError(res.error.message));
  return (res.data ?? ([] as unknown)) as T;
}

export function translateError(message: string): string {
  if (/JWT|session|not authenticated/i.test(message)) return "Tu sesión ha caducado. Vuelve a entrar.";
  if (/permission denied|insufficient/i.test(message)) return "No tienes permiso para esta acción.";
  if (/Failed to fetch|NetworkError/i.test(message)) return "No hay conexión con el servidor.";
  return message;
}
