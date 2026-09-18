import axios from "axios";

// Backend nuevo (este servicio, FastAPI)
export const AI_API_BASE_URL = import.meta.env.VITE_AI_API_URL || "http://localhost:8000";

// Backend NestJS existente de LiveShop (login y datos de tiendas)
export const LIVESHOP_API_BASE_URL = import.meta.env.VITE_LIVESHOP_API_URL || "http://localhost:3000/api";

const TOKEN_KEY = "liveshop_ai_token";

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string) {
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken() {
  localStorage.removeItem(TOKEN_KEY);
}

export const aiApi = axios.create({ baseURL: AI_API_BASE_URL });
export const liveshopApi = axios.create({ baseURL: LIVESHOP_API_BASE_URL });

function attachAuth(instance: typeof aiApi) {
  instance.interceptors.request.use((config) => {
    const token = getToken();
    if (token) {
      config.headers = config.headers ?? {};
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  });
}

function attachAuthErrorRedirect(instance: typeof aiApi) {
  instance.interceptors.response.use(
    (res) => res,
    (err) => {
      if (err?.response?.status === 401) {
        clearToken();
        if (window.location.pathname !== "/login") {
          window.location.href = "/login";
        }
      }
      return Promise.reject(err);
    }
  );
}

attachAuth(aiApi);
attachAuth(liveshopApi);
attachAuthErrorRedirect(aiApi);
attachAuthErrorRedirect(liveshopApi);

export async function login(email: string, password: string): Promise<void> {
  // auth.controller.ts espera { username, password } (username = email) y
  // devuelve el JWT como string plano, no envuelto en un objeto.
  const { data } = await liveshopApi.post("/auth/login", { username: email, password });
  if (!data || typeof data !== "string") {
    throw new Error("Credenciales invalidas");
  }
  setToken(data);
}
