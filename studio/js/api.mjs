// Cliente del backend de Studio. No guarda credenciales: la autenticación la resuelve el servidor.
export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

async function request(url, options = {}) {
  let res;
  try {
    res = await fetch(url, { credentials: "same-origin", cache: "no-store", redirect: "manual", ...options });
  } catch (err) {
    if (err.name === "AbortError") throw err;
    throw new ApiError("No se pudo conectar con Studio. Si la sesión de acceso caducó, recarga la página.", 0);
  }
  if (res.type === "opaqueredirect") throw new ApiError("La sesión de acceso caducó. Recarga la página para volver a entrar.", 401);
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new ApiError(body.error || `Error ${res.status}`, res.status);
  return body;
}

export const getReport = (query, signal) => request(`/internal/studio/report?${query}`, { signal });

export const postAnnotation = (body) =>
  request("/internal/studio/annotations", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Studio-Request": "1" },
    body: JSON.stringify(body),
  });
