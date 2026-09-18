import { FormEvent, useEffect, useState } from "react";
import { aiApi } from "../api";

interface InfraSettings {
  evolution_api_key: string;
  chatwoot_base_url: string;
  chatwoot_public_url: string;
  chatwoot_platform_api_key: string;
  chatwoot_owner_user_id: number | null;
}

export default function SettingsPage() {
  const [current, setCurrent] = useState<InfraSettings | null>(null);
  const [evolutionKey, setEvolutionKey] = useState("");
  const [chatwootUrl, setChatwootUrl] = useState("");
  const [chatwootPublicUrl, setChatwootPublicUrl] = useState("");
  const [platformKey, setPlatformKey] = useState("");
  const [ownerUserId, setOwnerUserId] = useState("");
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = () => {
    aiApi.get<InfraSettings>("/settings").then((res) => {
      setCurrent(res.data);
      setChatwootUrl(res.data.chatwoot_base_url ?? "");
      setChatwootPublicUrl(res.data.chatwoot_public_url ?? "");
      setOwnerUserId(res.data.chatwoot_owner_user_id != null ? String(res.data.chatwoot_owner_user_id) : "");
    });
  };

  useEffect(load, []);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setSaved(false);
    try {
      await aiApi.put("/settings", {
        evolution_api_key: evolutionKey || undefined,
        chatwoot_base_url: chatwootUrl || undefined,
        chatwoot_public_url: chatwootPublicUrl || undefined,
        chatwoot_platform_api_key: platformKey || undefined,
        chatwoot_owner_user_id: ownerUserId ? parseInt(ownerUserId, 10) : undefined,
      });
      setEvolutionKey("");
      setPlatformKey("");
      setSaved(true);
      load();
    } catch (err: any) {
      setError(err?.response?.data?.detail ?? "No se pudo guardar");
    }
  };

  return (
    <div className="p-8 max-w-xl">
      <h2 className="font-headline text-2xl font-bold mb-2">Configuración - Infraestructura</h2>
      <p className="text-sm text-on-surface-variant mb-6">
        Esto es compartido por todas las tiendas (no cambia por tienda). El proveedor de IA, el prompt
        del agente y la cuenta de Chatwoot de cada tienda se configuran desde "Tiendas / WhatsApp" →
        Configurar IA.
      </p>

      {saved && (
        <div className="mb-4 p-3 rounded-lg bg-secondary/10 border border-secondary text-secondary text-sm">
          Guardado correctamente.
        </div>
      )}
      {error && (
        <div className="mb-4 p-3 rounded-lg bg-error/10 border border-error text-error text-sm">{error}</div>
      )}

      <form onSubmit={handleSubmit} className="space-y-5">
        <div>
          <label className="block text-sm font-semibold mb-1">Evolution API Key (admin, compartida)</label>
          <input
            type="text"
            placeholder={current ? `Actual: ${current.evolution_api_key}` : ""}
            value={evolutionKey}
            onChange={(e) => setEvolutionKey(e.target.value)}
            className="w-full px-4 py-3 rounded-lg bg-surface-container text-on-surface outline-none"
          />
          <p className="text-xs text-on-surface-variant mt-1">
            Administra todas las instancias/números de WhatsApp de todas las tiendas.
          </p>
        </div>

        <div>
          <label className="block text-sm font-semibold mb-1">Chatwoot - URL interna (para llamadas del servidor)</label>
          <input
            type="text"
            value={chatwootUrl}
            onChange={(e) => setChatwootUrl(e.target.value)}
            placeholder="http://liveshop-chatwoot:3000"
            className="w-full px-4 py-3 rounded-lg bg-surface-container text-on-surface outline-none"
          />
          <p className="text-xs text-on-surface-variant mt-1">
            El nombre del contenedor en la red de Docker - la usa este backend para hablarle a la API de
            Chatwoot. No es una URL que abra tu navegador.
          </p>
        </div>

        <div>
          <label className="block text-sm font-semibold mb-1">Chatwoot - URL pública (para los links del panel)</label>
          <input
            type="text"
            value={chatwootPublicUrl}
            onChange={(e) => setChatwootPublicUrl(e.target.value)}
            placeholder="http://2.24.139.178:3010"
            className="w-full px-4 py-3 rounded-lg bg-surface-container text-on-surface outline-none"
          />
          <p className="text-xs text-on-surface-variant mt-1">
            La que sí abre tu navegador - se usa para los botones "Abrir Chatwoot" en cada tienda. Cambia
            esto cuando Chatwoot tenga su propio dominio.
          </p>
        </div>

        <div className="pt-3 border-t border-outline/20">
          <label className="block text-sm font-semibold mb-1">Chatwoot - Platform API Key</label>
          <input
            type="text"
            placeholder={current ? `Actual: ${current.chatwoot_platform_api_key}` : ""}
            value={platformKey}
            onChange={(e) => setPlatformKey(e.target.value)}
            className="w-full px-4 py-3 rounded-lg bg-surface-container text-on-surface outline-none"
          />
          <p className="text-xs text-on-surface-variant mt-1">
            Se saca UNA sola vez en Chatwoot: entra a{" "}
            <code className="text-on-surface">/super_admin</code> → Platform Apps → crea uno → pestaña
            "Access Tokens". Con esto el botón "Crear cuenta automática" de cada tienda funciona solo,
            sin que tengas que volver a entrar a Chatwoot nunca más.
          </p>
        </div>

        <div>
          <label className="block text-sm font-semibold mb-1">Tu ID de usuario en Chatwoot (no el de "LiveShop Automation")</label>
          <input
            type="number"
            value={ownerUserId}
            onChange={(e) => setOwnerUserId(e.target.value)}
            placeholder="Ej: 1"
            className="w-full px-4 py-3 rounded-lg bg-surface-container text-on-surface outline-none"
          />
          <p className="text-xs text-on-surface-variant mt-1">
            Sin esto, las cuentas nuevas quedan a nombre SOLO del usuario de automatización y tú no las ves
            en la UI de Chatwoot. No es secreto, es solo un número - lo puedes ver en Chatwoot → Super
            Admin → Users, buscando tu correo.
          </p>
        </div>

        <button
          type="submit"
          className="px-6 py-3 rounded-lg bg-primary text-on-primary font-semibold hover:opacity-90"
        >
          Guardar
        </button>
      </form>
    </div>
  );
}
