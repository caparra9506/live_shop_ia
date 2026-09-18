import { NavLink } from "react-router-dom";
import { clearToken } from "../api";

const linkClass = ({ isActive }: { isActive: boolean }) =>
  `block px-4 py-3 rounded-lg font-body text-sm transition-colors ${
    isActive
      ? "bg-primary text-on-primary font-semibold"
      : "text-on-surface-variant hover:bg-surface-container-high hover:text-on-surface"
  }`;

export default function Sidebar() {
  return (
    <aside className="w-60 shrink-0 bg-surface-container min-h-screen p-4 flex flex-col gap-2">
      <h1 className="font-headline text-lg font-bold text-on-surface mb-6 px-2">LiveShop AI</h1>
      <NavLink to="/stores" className={linkClass}>
        Tiendas
      </NavLink>
      <NavLink to="/conversations" className={linkClass}>
        Conversaciones
      </NavLink>
      <NavLink to="/ai-usage" className={linkClass}>
        Uso de IA
      </NavLink>
      <NavLink to="/settings" className={linkClass}>
        Configuración
      </NavLink>
      <button
        onClick={() => {
          clearToken();
          window.location.href = "/login";
        }}
        className="mt-auto text-left px-4 py-3 rounded-lg text-sm text-error hover:bg-surface-container-high"
      >
        Cerrar sesión
      </button>
    </aside>
  );
}
