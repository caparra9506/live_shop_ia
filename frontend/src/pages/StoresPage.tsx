import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { aiApi, liveshopApi } from "../api";
import StatusBadge from "../components/StatusBadge";

interface Store {
  id: number;
  name: string;
  phone: string;
}

interface WhatsappStatus {
  store_id: number;
  status: string;
}

export default function StoresPage() {
  const [stores, setStores] = useState<Store[]>([]);
  const [statuses, setStatuses] = useState<Record<number, WhatsappStatus>>({});
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();

  useEffect(() => {
    liveshopApi
      .get<Store[]>("/stores")
      .then((res) => setStores(res.data))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (stores.length === 0) return;
    const poll = async () => {
      const entries = await Promise.all(
        stores.map(async (store) => {
          try {
            const { data } = await aiApi.get<WhatsappStatus>(`/stores/${store.id}/whatsapp/status`);
            return [store.id, data] as const;
          } catch {
            return [store.id, { store_id: store.id, status: "disconnected" }] as const;
          }
        })
      );
      setStatuses(Object.fromEntries(entries));
    };
    poll();
    const interval = setInterval(poll, 5000);
    return () => clearInterval(interval);
  }, [stores]);

  if (loading) return <p className="p-8 text-on-surface-variant">Cargando tiendas…</p>;

  return (
    <div className="p-8">
      <h2 className="font-headline text-2xl font-bold mb-6">Tiendas</h2>
      <div className="grid gap-4">
        {stores.map((store) => {
          const status = statuses[store.id]?.status ?? "disconnected";
          return (
            <div
              key={store.id}
              className="bg-surface-container rounded-xl p-5 flex items-center justify-between"
            >
              <div>
                <p className="font-semibold text-on-surface">{store.name}</p>
                <p className="text-sm text-on-surface-variant">{store.phone}</p>
              </div>
              <div className="flex items-center gap-3">
                <StatusBadge status={status} />
                <button
                  onClick={() => navigate(`/stores/${store.id}`)}
                  className="px-4 py-2 bg-primary text-on-primary rounded-lg text-sm font-semibold hover:opacity-90"
                >
                  Configurar
                </button>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
