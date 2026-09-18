import { FormEvent, useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { aiApi, liveshopApi } from "../api";
import StatusBadge from "../components/StatusBadge";

interface Store {
  id: number;
  name: string;
  phone: string;
}

interface StoreAiConfig {
  store_id: number;
  ai_provider: string;
  ai_api_key: string;
  system_prompt: string;
  chatwoot_account_id: number | null;
  chatwoot_api_token: string;
  chatwoot_inbox_id: number | null;
  labels: Record<string, string>;
  extra_labels: { title: string; color: string }[];
  missing_fixed_labels: string[];
}

interface InfraSettings {
  evolution_api_key: string;
  chatwoot_base_url: string;
  chatwoot_public_url: string;
  chatwoot_platform_api_key: string;
  chatwoot_admin_token: string;
}

interface WhatsappStatus {
  store_id: number;
  status: string;
  qr_code: string | null;
}

type Tab = "whatsapp" | "ai" | "chatwoot" | "labels";

const TABS: { key: Tab; label: string }[] = [
  { key: "whatsapp", label: "WhatsApp" },
  { key: "ai", label: "Inteligencia artificial" },
  { key: "chatwoot", label: "Chatwoot" },
  { key: "labels", label: "Etiquetas" },
];

const LABEL_META: { key: string; field: string; dot: string; question: string }[] = [
  { key: "venta", field: "label_venta", dot: "bg-secondary", question: "Cuando quiere comprar" },
  { key: "queja", field: "label_queja", dot: "bg-error", question: "Cuando se queja" },
  { key: "soporte", field: "label_soporte", dot: "bg-primary", question: "Cuando pide soporte" },
  { key: "no_registrado", field: "label_no_registrado", dot: "bg-on-surface-variant", question: "Contacto nuevo" },
];

export default function StoreDetailPage() {
  const { storeId } = useParams();
  const navigate = useNavigate();
  const id = Number(storeId);

  const [store, setStore] = useState<Store | null>(null);
  const [current, setCurrent] = useState<StoreAiConfig | null>(null);
  const [infra, setInfra] = useState<InfraSettings | null>(null);
  const [wa, setWa] = useState<WhatsappStatus | null>(null);
  const [tab, setTab] = useState<Tab>("whatsapp");
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);

  const [provider, setProvider] = useState("openai");
  const [apiKey, setApiKey] = useState("");
  const [prompt, setPrompt] = useState("");

  const [chatwootAccountId, setChatwootAccountId] = useState("");
  const [chatwootToken, setChatwootToken] = useState("");
  const [platformKey, setPlatformKey] = useState("");
  const [adminToken, setAdminToken] = useState("");
  const [showPlatformField, setShowPlatformField] = useState(false);
  const [showAdminField, setShowAdminField] = useState(false);

  const [labelFields, setLabelFields] = useState<Record<string, string>>({});
  const [newExtraLabel, setNewExtraLabel] = useState("");
  const [newExtraColor, setNewExtraColor] = useState("#5c6bc0");
  // Se lee el valor directo del input al agregar (en vez de confiar solo en
  // newExtraLabel) - si se hace clic muy rápido después de escribir, el
  // estado de React puede no haber alcanzado a actualizarse todavía.
  const newExtraLabelRef = useRef<HTMLInputElement>(null);
  // Refleja cuáles de las 4 fijas NO existen hoy como Label en Chatwoot -
  // viene del servidor (que lo chequea contra Chatwoot real) en cada carga,
  // así que persiste entre recargas en vez de resetearse siempre a "todas
  // visibles" como pasaba cuando esto era solo un estado local del navegador.
  const [hiddenFixedLabels, setHiddenFixedLabels] = useState<Record<string, boolean>>({});

  const load = () => {
    liveshopApi.get<Store>(`/stores/${id}`).then((res) => setStore(res.data));
    aiApi.get<StoreAiConfig>(`/stores/${id}/ai-config`).then((res) => {
      setCurrent(res.data);
      setProvider(res.data.ai_provider);
      setPrompt(res.data.system_prompt);
      setChatwootAccountId(res.data.chatwoot_account_id ? String(res.data.chatwoot_account_id) : "");
      setHiddenFixedLabels(
        Object.fromEntries((res.data.missing_fixed_labels || []).map((key) => [key, true]))
      );
    });
    aiApi.get<InfraSettings>("/settings").then((res) => setInfra(res.data));
    aiApi.get<WhatsappStatus>(`/stores/${id}/whatsapp/status`).then((res) => setWa(res.data));
  };

  useEffect(load, [id]);

  useEffect(() => {
    if (wa?.status !== "connecting") return;
    const interval = setInterval(() => {
      aiApi.get<WhatsappStatus>(`/stores/${id}/whatsapp/status`).then((res) => setWa(res.data));
    }, 4000);
    return () => clearInterval(interval);
  }, [wa?.status, id]);

  // El QR de WhatsApp expira a los pocos segundos - mientras se este
  // esperando el escaneo, se pide uno nuevo cada 25s sin que el usuario
  // tenga que hacer nada.
  useEffect(() => {
    if (wa?.status !== "connecting" || !wa?.qr_code) return;
    const interval = setInterval(() => {
      aiApi.post<WhatsappStatus>(`/stores/${id}/whatsapp/connect`).then((res) => setWa(res.data));
    }, 25000);
    return () => clearInterval(interval);
  }, [wa?.status, wa?.qr_code, id]);

  const flash = () => {
    setSaved(true);
    setTimeout(() => setSaved(false), 2500);
  };

  const connectWhatsapp = async () => {
    setError(null);
    setBusy(true);
    try {
      const { data } = await aiApi.post<WhatsappStatus>(`/stores/${id}/whatsapp/connect`);
      setWa(data);
    } catch (err: any) {
      setError(err?.response?.data?.detail ?? "No se pudo conectar WhatsApp");
    } finally {
      setBusy(false);
    }
  };

  const disconnectWhatsapp = async () => {
    if (!confirm("¿Desconectar WhatsApp de esta tienda? Vas a necesitar escanear el QR de nuevo para reconectar.")) return;
    setError(null);
    setBusy(true);
    try {
      const { data } = await aiApi.post<WhatsappStatus>(`/stores/${id}/whatsapp/disconnect`);
      setWa(data);
    } catch (err: any) {
      setError(err?.response?.data?.detail ?? "No se pudo desconectar WhatsApp");
    } finally {
      setBusy(false);
    }
  };

  const saveAi = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    try {
      await aiApi.put(`/stores/${id}/ai-config`, {
        ai_provider: provider,
        ai_api_key: apiKey || undefined,
        system_prompt: prompt || undefined,
      });
      setApiKey("");
      flash();
      load();
    } catch (err: any) {
      setError(err?.response?.data?.detail ?? "No se pudo guardar");
    }
  };

  const provisionChatwoot = async () => {
    setError(null);
    setBusy(true);
    try {
      const infraUpdate: Record<string, string> = {};
      if (platformKey) infraUpdate.chatwoot_platform_api_key = platformKey;
      if (adminToken) infraUpdate.chatwoot_admin_token = adminToken;
      if (Object.keys(infraUpdate).length > 0) {
        await aiApi.put("/settings", infraUpdate);
        setPlatformKey("");
        setAdminToken("");
        setShowPlatformField(false);
        setShowAdminField(false);
      }
      await aiApi.post(`/stores/${id}/chatwoot/provision`);
      flash();
      load();
    } catch (err: any) {
      setError(err?.response?.data?.detail ?? "No se pudo crear la cuenta automáticamente");
    } finally {
      setBusy(false);
    }
  };

  const createAutomationUser = async () => {
    setError(null);
    setBusy(true);
    try {
      await aiApi.post("/settings/chatwoot/create-automation-user");
      setShowAdminField(false);
      flash();
      load();
    } catch (err: any) {
      setError(err?.response?.data?.detail ?? "No se pudo crear el usuario de automatización");
    } finally {
      setBusy(false);
    }
  };

  const deleteChatwoot = async () => {
    if (!confirm("¿Eliminar la cuenta de Chatwoot de esta tienda? Se pierden sus conversaciones e historial ahí.")) return;
    setError(null);
    setBusy(true);
    try {
      await aiApi.delete(`/stores/${id}/chatwoot`);
      flash();
      load();
    } catch (err: any) {
      setError(err?.response?.data?.detail ?? "No se pudo eliminar la cuenta");
    } finally {
      setBusy(false);
    }
  };

  const saveChatwootManual = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    try {
      await aiApi.put(`/stores/${id}/ai-config`, {
        chatwoot_account_id: chatwootAccountId ? Number(chatwootAccountId) : undefined,
        chatwoot_api_token: chatwootToken || undefined,
      });
      setChatwootToken("");
      flash();
      load();
    } catch (err: any) {
      setError(err?.response?.data?.detail ?? "No se pudo guardar");
    }
  };

  const saveLabels = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    try {
      await aiApi.put(`/stores/${id}/ai-config`, {
        ...Object.fromEntries(Object.entries(labelFields).filter(([, v]) => v)),
      });
      flash();
      load();
    } catch (err: any) {
      setError(err?.response?.data?.detail ?? "No se pudo guardar");
    }
  };

  const addExtraLabel = async () => {
    // Se lee directo del DOM, no de newExtraLabel - si el clic llega justo
    // después de escribir, el estado de React puede ir un paso atrás.
    const title = (newExtraLabelRef.current?.value ?? newExtraLabel).trim();
    if (!title) return;
    setError(null);
    try {
      // POST dedicado (no manda la lista completa) - el servidor lee su
      // propio estado más reciente y agrega ahí, para que un borrado y un
      // agregado seguidos no se pisen entre sí.
      await aiApi.post(`/stores/${id}/ai-config/extra-labels`, { title, color: newExtraColor });
      setNewExtraLabel("");
      flash();
      load();
    } catch (err: any) {
      setError(err?.response?.data?.detail ?? "No se pudo agregar la etiqueta");
    }
  };

  const removeExtraLabel = async (title: string) => {
    setError(null);
    try {
      await aiApi.delete(`/stores/${id}/ai-config/extra-labels/${encodeURIComponent(title)}`);
      flash();
      load();
    } catch (err: any) {
      setError(err?.response?.data?.detail ?? "No se pudo quitar la etiqueta");
    }
  };

  if (!store || !current) return <p className="p-8 text-on-surface-variant">Cargando…</p>;

  const waConnected = wa?.status === "connected";
  const chatwootHasAccount = Boolean(current.chatwoot_account_id);
  const chatwootReady = Boolean(current.chatwoot_account_id && current.chatwoot_inbox_id);

  return (
    <div className="p-8 max-w-3xl">
      <button
        onClick={() => navigate("/stores")}
        className="text-sm text-on-surface-variant hover:text-on-surface mb-4"
      >
        ← Tiendas
      </button>

      <div className="flex items-center gap-3 mb-8">
        <h2 className="font-headline text-2xl font-bold">{store.name}</h2>
        <StatusBadge status={waConnected ? "connected" : "disconnected"} />
      </div>

      {/* Flotantes (fixed) para no empujar el contenido de abajo - si no,
          un clic justo después de guardar cae en el lugar equivocado porque
          todo se corre hacia abajo mientras el aviso está visible. */}
      {saved && (
        <div className="fixed top-4 right-4 z-50 p-3 rounded-lg bg-secondary/10 border border-secondary text-secondary text-sm shadow-lg">
          Guardado correctamente.
        </div>
      )}
      {error && (
        <div className="fixed top-4 right-4 z-50 p-3 rounded-lg bg-error/10 border border-error text-error text-sm shadow-lg max-w-sm">
          {error}
        </div>
      )}

      <div className="flex gap-1 mb-6 border-b border-outline/20">
        {TABS.map((t) => (
          <button
            key={t.key}
            onClick={() => {
              setError(null);
              setTab(t.key);
            }}
            className={`px-4 py-3 text-sm font-semibold border-b-2 transition-colors ${
              tab === t.key
                ? "border-primary text-on-surface"
                : "border-transparent text-on-surface-variant hover:text-on-surface"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === "whatsapp" && (
        <div className="bg-surface-container rounded-2xl p-8">
          <div className="flex items-center gap-4 mb-6">
            <div className="flex-1">
              <p className="font-semibold">Estado</p>
              <p className="text-sm text-on-surface-variant">
                {waConnected ? "Conectado" : wa?.status === "connecting" ? "Conectando…" : "Desconectado"}
              </p>
            </div>
            {waConnected ? (
              <button
                onClick={disconnectWhatsapp}
                disabled={busy}
                className="px-4 py-2 rounded-lg bg-error/20 text-error text-sm font-semibold hover:opacity-90 disabled:opacity-50"
              >
                Desconectar
              </button>
            ) : (
              <button
                onClick={connectWhatsapp}
                disabled={busy}
                className="px-4 py-2 rounded-lg bg-primary text-on-primary text-sm font-semibold hover:opacity-90 disabled:opacity-50"
              >
                {busy ? "…" : wa?.qr_code ? "Refrescar QR" : "Conectar"}
              </button>
            )}
          </div>
          {wa?.qr_code && !waConnected && (
            <div>
              <div className="p-6 bg-white rounded-xl flex justify-center max-w-xs mx-auto">
                <img
                  src={wa.qr_code.startsWith("data:") ? wa.qr_code : `data:image/png;base64,${wa.qr_code}`}
                  alt="QR de WhatsApp"
                  className="w-full"
                />
              </div>
              <p className="text-xs text-on-surface-variant text-center mt-3">
                El QR expira rápido - se refresca solo cada 25s. Si ya no sirve, dale "Refrescar QR".
              </p>
            </div>
          )}
        </div>
      )}

      {tab === "ai" && (
        <form onSubmit={saveAi} className="bg-surface-container rounded-2xl p-8 space-y-5">
          <div>
            <label className="block text-sm font-semibold mb-2">Proveedor</label>
            <select
              value={provider}
              onChange={(e) => setProvider(e.target.value)}
              className="w-full max-w-xs px-4 py-3 rounded-lg bg-surface-container-high text-on-surface outline-none"
            >
              <option value="openai">OpenAI</option>
              <option value="deepseek">DeepSeek</option>
            </select>
          </div>
          <div>
            <label className="block text-sm font-semibold mb-2">
              API Key de {provider === "openai" ? "OpenAI" : "DeepSeek"}
            </label>
            <input
              type="text"
              placeholder={`Actual: ${current.ai_api_key || "sin configurar"}`}
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              className="w-full px-4 py-3 rounded-lg bg-surface-container-high text-on-surface outline-none"
            />
          </div>
          <div>
            <label className="block text-sm font-semibold mb-2">Prompt / comportamiento del agente</label>
            <textarea
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              rows={6}
              className="w-full px-4 py-3 rounded-lg bg-surface-container-high text-on-surface outline-none resize-none"
            />
          </div>
          <button type="submit" className="px-6 py-3 rounded-lg bg-primary text-on-primary font-semibold">
            Guardar
          </button>
        </form>
      )}

      {tab === "chatwoot" && (
        <div className="bg-surface-container rounded-2xl p-8 space-y-6">
          <div className="flex items-center gap-4">
            <div className="flex-1">
              <p className="font-semibold">Estado</p>
              <p className="text-sm text-on-surface-variant">
                {chatwootReady
                  ? `Cuenta #${current.chatwoot_account_id}`
                  : chatwootHasAccount
                  ? `Cuenta #${current.chatwoot_account_id} · falta el buzón`
                  : "Sin configurar"}
              </p>
            </div>
            {chatwootReady && (
              <button
                onClick={deleteChatwoot}
                disabled={busy}
                className="px-4 py-2 rounded-lg bg-error/20 text-error text-sm font-semibold hover:opacity-90 disabled:opacity-50"
              >
                Eliminar cuenta
              </button>
            )}
          </div>

          <div className="p-4 rounded-lg bg-surface-container-high">
            <div className="flex items-center justify-between mb-2">
              <label className="text-sm font-semibold">
                Platform API Key (una sola vez, sirve para todas las tiendas)
              </label>
              {infra?.chatwoot_platform_api_key && !showPlatformField && (
                <button
                  type="button"
                  onClick={() => setShowPlatformField(true)}
                  className="text-xs text-primary hover:underline"
                >
                  Cambiar
                </button>
              )}
            </div>
            {infra?.chatwoot_public_url && (!infra?.chatwoot_platform_api_key || showPlatformField) && (
              <a
                href={`${infra.chatwoot_public_url}/super_admin/platform_apps`}
                target="_blank"
                rel="noreferrer"
                className="inline-block mb-2 text-xs text-secondary hover:underline"
              >
                Abrir Chatwoot → Super Admin → Platform Apps ↗
              </a>
            )}
            {infra?.chatwoot_platform_api_key && !showPlatformField ? (
              <p className="text-sm text-on-surface-variant">Configurada: {infra.chatwoot_platform_api_key}</p>
            ) : (
              <input
                type="text"
                placeholder="Pega aquí el Access Token del Platform App"
                value={platformKey}
                onChange={(e) => setPlatformKey(e.target.value)}
                className="w-full px-4 py-3 rounded-lg bg-surface text-on-surface outline-none"
              />
            )}
          </div>
          <div className="p-4 rounded-lg bg-surface-container-high">
            <div className="flex items-center justify-between mb-2">
              <label className="text-sm font-semibold">Tu token personal (una sola vez, para crear el buzón)</label>
              {infra?.chatwoot_admin_token && !showAdminField && (
                <button
                  type="button"
                  onClick={() => setShowAdminField(true)}
                  className="text-xs text-primary hover:underline"
                >
                  Cambiar
                </button>
              )}
            </div>
            {(!infra?.chatwoot_admin_token || showAdminField) && (
              <button
                type="button"
                onClick={createAutomationUser}
                disabled={busy || !infra?.chatwoot_platform_api_key}
                className="w-full mb-3 px-4 py-2.5 rounded-lg bg-secondary/20 text-secondary text-sm font-semibold hover:bg-secondary/30 disabled:opacity-50"
              >
                {busy ? "Creando..." : "✨ Crear usuario de automatización (recomendado, sin salir de aquí)"}
              </button>
            )}
            {infra?.chatwoot_public_url && (!infra?.chatwoot_admin_token || showAdminField) && (
              <details className="mb-2">
                <summary className="text-xs text-on-surface-variant cursor-pointer">
                  O pégalo manualmente (si ya tienes un token que quieras usar)
                </summary>
                <a
                  href={`${infra.chatwoot_public_url}/app/accounts/1/profile/settings`}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-block mt-2 mb-1 text-xs text-secondary hover:underline"
                >
                  Abrir Chatwoot → Perfil (cuenta "Automatization") → Control de acceso a la API ↗
                </a>
                <p className="text-xs text-on-surface-variant/70 mb-2">
                  Te lleva directo a tu perfil dentro de la cuenta "Automatization" (id 1, la más
                  estable) - el token que ahí encuentres sirve igual sin importar la cuenta.
                </p>
              </details>
            )}
            {infra?.chatwoot_admin_token && !showAdminField ? (
              <p className="text-sm text-on-surface-variant">Configurado: {infra.chatwoot_admin_token}</p>
            ) : (
              <input
                type="text"
                placeholder="Pega aquí tu Personal Access Token"
                value={adminToken}
                onChange={(e) => setAdminToken(e.target.value)}
                className="w-full px-4 py-3 rounded-lg bg-surface text-on-surface outline-none"
              />
            )}
          </div>

          <button
            onClick={provisionChatwoot}
            disabled={busy}
            className="w-full py-3 rounded-lg bg-secondary/20 text-secondary font-semibold disabled:opacity-50"
          >
            {busy ? "Creando…" : chatwootReady ? "Recrear automático" : "Crear automático"}
          </button>

          <form onSubmit={saveChatwootManual} className="space-y-3 pt-4 border-t border-outline/20">
            <p className="text-sm text-on-surface-variant">O pega los datos si ya los tienes:</p>
            <input
              type="number"
              value={chatwootAccountId}
              onChange={(e) => setChatwootAccountId(e.target.value)}
              placeholder="Account ID"
              className="w-full px-4 py-3 rounded-lg bg-surface-container-high text-on-surface outline-none"
            />
            <input
              type="text"
              placeholder={`Access Token - Actual: ${current.chatwoot_api_token || "sin configurar"}`}
              value={chatwootToken}
              onChange={(e) => setChatwootToken(e.target.value)}
              className="w-full px-4 py-3 rounded-lg bg-surface-container-high text-on-surface outline-none"
            />
            <button type="submit" className="px-6 py-3 rounded-lg bg-surface-container-high font-semibold">
              Guardar manual
            </button>
          </form>
        </div>
      )}

      {tab === "labels" && (
        <form onSubmit={saveLabels} className="bg-surface-container rounded-2xl p-8 space-y-4">
          <p className="text-sm text-on-surface-variant mb-2">
            Así se ven las etiquetas de cada conversación, tanto en tu panel como en Chatwoot.
          </p>

          {/* Las 4 fijas - la IA las sigue usando para clasificar aunque se
              quiten de aquí, pero al quitarlas desaparecen de esta lista (no
              queda fila fantasma) - igual que las libres. */}
          {LABEL_META.map(({ key, field, dot, question }) =>
            hiddenFixedLabels[key] ? null : (
              <div key={key} className="flex items-center gap-3">
                <span className={`w-2.5 h-2.5 rounded-full shrink-0 ${dot}`} />
                <span className="text-sm text-on-surface-variant w-48 shrink-0">{question}</span>
                <input
                  type="text"
                  defaultValue={current.labels[key]}
                  onChange={(e) => setLabelFields((prev) => ({ ...prev, [field]: e.target.value }))}
                  className="flex-1 px-4 py-2.5 rounded-lg bg-surface-container-high text-on-surface outline-none"
                />
                <button
                  type="button"
                  onClick={() => {
                    removeExtraLabel(current.labels[key]);
                    setHiddenFixedLabels((prev) => ({ ...prev, [key]: true }));
                  }}
                  className="text-error hover:opacity-70 px-1"
                  title="Quitar esta etiqueta de Chatwoot (la IA sigue clasificando esta categoría igual)"
                >
                  ×
                </button>
              </div>
            )
          )}

          {/* Libres - las que agregas tú, en la misma lista */}
          {current.extra_labels.map(({ title, color }) => (
            <div key={title} className="flex items-center gap-3">
              <span className="w-2.5 h-2.5 rounded-full shrink-0" style={{ backgroundColor: color }} />
              <span className="flex-1 text-sm text-on-surface">{title}</span>
              <button
                type="button"
                onClick={() => removeExtraLabel(title)}
                className="text-error hover:opacity-70 px-1"
                title="Quitar"
              >
                ×
              </button>
            </div>
          ))}

          {/* Agregar una libre nueva, al final de la misma lista */}
          <div className="flex items-center gap-3 pt-2 border-t border-outline/10">
            <input
              type="color"
              value={newExtraColor}
              onChange={(e) => setNewExtraColor(e.target.value)}
              title="Color de la etiqueta"
              className="w-9 h-9 rounded-lg bg-surface-container-high cursor-pointer shrink-0 p-1"
            />
            <input
              ref={newExtraLabelRef}
              type="text"
              autoComplete="off"
              autoCorrect="off"
              spellCheck={false}
              value={newExtraLabel}
              onChange={(e) => setNewExtraLabel(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && (e.preventDefault(), addExtraLabel())}
              placeholder="Ej: VIP, Devolución, Urgente..."
              className="flex-1 px-4 py-2.5 rounded-lg bg-surface-container-high text-on-surface outline-none"
            />
            <button
              type="button"
              onClick={addExtraLabel}
              className="px-5 py-2.5 rounded-lg bg-secondary/20 text-secondary font-semibold hover:bg-secondary/30 whitespace-nowrap"
            >
              + Agregar
            </button>
          </div>

          <p className="text-xs text-on-surface-variant/70">
            Las 4 primeras las usa la IA para clasificar - la "×" solo borra el Label de Chatwoot y
            oculta la fila (no se puede desactivar del todo); "Guardar" las vuelve a crear en Chatwoot.
            Las de abajo son libres, para que las uses tú mismo en Chatwoot - se agregan/quitan al
            instante, sin necesidad de "Guardar".
          </p>
          <button type="submit" className="px-6 py-3 rounded-lg bg-primary text-on-primary font-semibold">
            Guardar
          </button>
        </form>
      )}
    </div>
  );
}
