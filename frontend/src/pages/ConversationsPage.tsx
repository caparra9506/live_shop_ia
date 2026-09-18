import { useEffect, useState } from "react";
import { aiApi } from "../api";

interface Conversation {
  id: number;
  store_id: number;
  contact_phone: string;
  current_label: string | null;
  created_at: string;
}

interface Message {
  id: number;
  direction: "in" | "out";
  body: string;
  created_at: string;
}

const COLUMNS: { key: string; title: string; dot: string }[] = [
  { key: "venta", title: "Venta", dot: "bg-secondary" },
  { key: "queja", title: "Queja", dot: "bg-error" },
  { key: "soporte", title: "Soporte", dot: "bg-primary" },
  { key: "no_registrado", title: "Nuevo contacto", dot: "bg-on-surface-variant" },
];

export default function ConversationsPage() {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [selected, setSelected] = useState<Conversation | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);

  const load = () => {
    aiApi.get<Conversation[]>("/conversations").then((res) => setConversations(res.data));
  };

  useEffect(() => {
    load();
    const interval = setInterval(load, 8000);
    return () => clearInterval(interval);
  }, []);

  const openConversation = async (conversation: Conversation) => {
    setSelected(conversation);
    const { data } = await aiApi.get(`/conversations/${conversation.id}`);
    setMessages(data.messages ?? []);
  };

  const columnConversations = (key: string) =>
    conversations.filter((c) => (c.current_label ?? "no_registrado") === key);

  return (
    <div className="p-8 h-screen flex flex-col">
      <h2 className="font-headline text-2xl font-bold mb-1">Conversaciones</h2>
      <p className="text-sm text-on-surface-variant mb-6">
        Agrupadas automáticamente según lo que detecta el agente en cada mensaje. Los nombres de
        etiqueta que ve el cliente en Chatwoot se configuran por tienda en "Configurar IA".
      </p>

      <div className="flex-1 flex gap-4 overflow-hidden">
        {COLUMNS.map((col) => {
          const items = columnConversations(col.key);
          return (
            <div key={col.key} className="flex-1 min-w-0 flex flex-col bg-surface-container rounded-xl p-3">
              <div className="flex items-center gap-2 mb-3 px-1">
                <span className={`w-2 h-2 rounded-full ${col.dot}`} />
                <h3 className="font-semibold text-sm">{col.title}</h3>
                <span className="text-xs text-on-surface-variant ml-auto">{items.length}</span>
              </div>
              <div className="flex-1 overflow-y-auto space-y-2">
                {items.map((c) => (
                  <button
                    key={c.id}
                    onClick={() => openConversation(c)}
                    className={`w-full text-left p-3 rounded-lg text-sm ${
                      selected?.id === c.id
                        ? "bg-primary text-on-primary"
                        : "bg-surface-container-high hover:opacity-80"
                    }`}
                  >
                    <p className="font-semibold">{c.contact_phone}</p>
                    <p className="text-xs opacity-70">Tienda #{c.store_id}</p>
                  </button>
                ))}
                {items.length === 0 && (
                  <p className="text-xs text-on-surface-variant px-1">Sin conversaciones</p>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {selected && (
        <div
          className="fixed inset-0 bg-black/60 flex items-center justify-center z-50"
          onClick={() => setSelected(null)}
        >
          <div
            className="bg-surface-container rounded-2xl p-6 max-w-lg w-full max-h-[80vh] flex flex-col"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between mb-4">
              <h3 className="font-headline text-lg font-bold">{selected.contact_phone}</h3>
              <button onClick={() => setSelected(null)} className="text-on-surface-variant text-sm">
                Cerrar
              </button>
            </div>
            <div className="flex-1 overflow-y-auto space-y-3">
              {messages.map((m) => (
                <div
                  key={m.id}
                  className={`max-w-[85%] p-3 rounded-lg text-sm ${
                    m.direction === "out"
                      ? "ml-auto bg-primary text-on-primary"
                      : "bg-surface-container-high text-on-surface"
                  }`}
                >
                  {m.body}
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
