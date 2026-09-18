import { useEffect, useState } from "react";
import { aiApi } from "../api";

interface DraftLog {
  id: number;
  storeId: number;
  storeName: string;
  imageUrl: string;
  note: string | null;
  suggestedName: string | null;
  success: boolean;
  errorMessage: string | null;
  promptTokens: number | null;
  completionTokens: number | null;
  estimatedCostUsd: number | null;
  createdAt: string;
}

interface CommentLog {
  id: number;
  store_id: number;
  store_name: string | null;
  username: string;
  comment: string;
  ai_provider: string | null;
  intent: string | null;
  label_text: string | null;
  skip_response: boolean;
  success: boolean;
  error_message: string | null;
  prompt_tokens: number | null;
  completion_tokens: number | null;
  estimated_cost_usd: number | null;
  created_at: string;
}

type Tab = "photos" | "comments";

export default function AiUsagePage() {
  const [tab, setTab] = useState<Tab>("comments");

  const [logs, setLogs] = useState<DraftLog[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [commentLogs, setCommentLogs] = useState<CommentLog[]>([]);
  const [commentLoading, setCommentLoading] = useState(true);
  const [commentError, setCommentError] = useState<string | null>(null);

  const load = () => {
    aiApi
      .get<DraftLog[]>("/ai-usage/product-drafts")
      .then((res) => {
        setLogs(res.data);
        setError(null);
      })
      .catch(() => setError("No se pudo cargar el registro de uso"))
      .finally(() => setLoading(false));
  };

  const loadComments = () => {
    aiApi
      .get<CommentLog[]>("/ai-usage/comment-classifications")
      .then((res) => {
        setCommentLogs(res.data);
        setCommentError(null);
      })
      .catch(() => setCommentError("No se pudo cargar el registro de clasificación"))
      .finally(() => setCommentLoading(false));
  };

  useEffect(() => {
    load();
    loadComments();
    const interval = setInterval(() => {
      load();
      loadComments();
    }, 8000);
    return () => clearInterval(interval);
  }, []);

  const totalCost = logs.reduce((sum, l) => sum + (l.estimatedCostUsd || 0), 0);
  const failures = logs.filter((l) => !l.success).length;
  const commentFailures = commentLogs.filter((l) => !l.success).length;
  const skipped = commentLogs.filter((l) => l.skip_response).length;
  const commentTotalCost = commentLogs.reduce((sum, l) => sum + (l.estimated_cost_usd || 0), 0);

  return (
    <div className="p-8">
      <h2 className="font-headline text-xl font-bold text-on-surface mb-1">Uso de IA</h2>
      <p className="text-sm text-on-surface-variant mb-6">
        Todo lo que la IA analiza o decide, para poder auditarlo sin mirar logs de servidor.
      </p>

      <div className="flex gap-2 mb-6 border-b border-outline-variant/10">
        <button
          onClick={() => setTab("comments")}
          className={`px-4 py-2 text-sm font-semibold border-b-2 -mb-px ${
            tab === "comments"
              ? "border-primary text-on-surface"
              : "border-transparent text-on-surface-variant"
          }`}
        >
          Clasificación de comentarios (live)
        </button>
        <button
          onClick={() => setTab("photos")}
          className={`px-4 py-2 text-sm font-semibold border-b-2 -mb-px ${
            tab === "photos"
              ? "border-primary text-on-surface"
              : "border-transparent text-on-surface-variant"
          }`}
        >
          Cargar productos con foto
        </button>
      </div>

      {tab === "comments" && (
        <>
          <p className="text-sm text-on-surface-variant mb-4">
            Cada comentario del live que pasa por el agente - qué etiqueta eligió, con qué proveedor de
            IA, si falló.
          </p>

          {commentError && (
            <div className="mb-4 p-3 rounded-lg bg-error/10 border border-error text-error text-sm">
              {commentError}
            </div>
          )}

          <div className="flex gap-4 mb-6">
            <div className="bg-surface-container-high rounded-xl p-4 min-w-[160px]">
              <p className="text-xs text-on-surface-variant uppercase tracking-widest font-label">
                Comentarios
              </p>
              <p className="text-2xl font-bold text-on-surface">{commentLogs.length}</p>
            </div>
            <div className="bg-surface-container-high rounded-xl p-4 min-w-[160px]">
              <p className="text-xs text-on-surface-variant uppercase tracking-widest font-label">
                Sin etiquetas propias
              </p>
              <p className="text-2xl font-bold text-on-surface-variant">{skipped}</p>
            </div>
            <div className="bg-surface-container-high rounded-xl p-4 min-w-[160px]">
              <p className="text-xs text-on-surface-variant uppercase tracking-widest font-label">
                Fallidas
              </p>
              <p className="text-2xl font-bold text-error">{commentFailures}</p>
            </div>
            <div className="bg-surface-container-high rounded-xl p-4 min-w-[160px]">
              <p className="text-xs text-on-surface-variant uppercase tracking-widest font-label">
                Costo estimado
              </p>
              <p className="text-2xl font-bold text-secondary">${commentTotalCost.toFixed(4)} USD</p>
            </div>
          </div>

          {commentLoading ? (
            <p className="text-on-surface-variant text-sm">Cargando…</p>
          ) : commentLogs.length === 0 ? (
            <p className="text-on-surface-variant text-sm">Todavía no ha llegado ningún comentario.</p>
          ) : (
            <div className="bg-surface-container rounded-xl overflow-hidden">
              <table className="w-full text-sm">
                <thead className="bg-surface-container-high text-on-surface-variant text-left">
                  <tr>
                    <th className="px-4 py-3 font-label">Fecha</th>
                    <th className="px-4 py-3 font-label">Tienda</th>
                    <th className="px-4 py-3 font-label">Usuario</th>
                    <th className="px-4 py-3 font-label">Comentario</th>
                    <th className="px-4 py-3 font-label">Proveedor</th>
                    <th className="px-4 py-3 font-label">Etiqueta elegida</th>
                    <th className="px-4 py-3 font-label">Estado</th>
                    <th className="px-4 py-3 font-label text-right">Costo</th>
                  </tr>
                </thead>
                <tbody>
                  {commentLogs.map((log) => (
                    <tr key={log.id} className="border-t border-outline-variant/10">
                      <td className="px-4 py-3 text-on-surface-variant whitespace-nowrap">
                        {new Date(log.created_at).toLocaleString()}
                      </td>
                      <td className="px-4 py-3 text-on-surface">{log.store_name || log.store_id}</td>
                      <td className="px-4 py-3 text-on-surface-variant">{log.username}</td>
                      <td
                        className="px-4 py-3 text-on-surface-variant max-w-[280px] truncate"
                        title={log.comment}
                      >
                        {log.comment}
                      </td>
                      <td className="px-4 py-3 text-on-surface-variant">{log.ai_provider || "—"}</td>
                      <td className="px-4 py-3 text-on-surface">
                        {log.label_text || "—"}
                        {log.skip_response && (
                          <span className="ml-2 text-xs text-on-surface-variant">(sin responder)</span>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        <span
                          className={`px-2 py-1 rounded-full text-xs font-label ${
                            log.success ? "bg-secondary/10 text-secondary" : "bg-error/10 text-error"
                          }`}
                          title={log.error_message || ""}
                        >
                          {log.success ? "OK" : "Falló"}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-right text-on-surface-variant">
                        {log.estimated_cost_usd ? `$${log.estimated_cost_usd.toFixed(5)}` : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}

      {tab === "photos" && (
        <>
          <p className="text-sm text-on-surface-variant mb-4">
            Cada vez que un vendedor analiza una foto de producto con IA (DeepSeek), queda registrado aquí.
          </p>

          {error && (
            <div className="mb-4 p-3 rounded-lg bg-error/10 border border-error text-error text-sm">
              {error}
            </div>
          )}

          <div className="flex gap-4 mb-6">
            <div className="bg-surface-container-high rounded-xl p-4 min-w-[160px]">
              <p className="text-xs text-on-surface-variant uppercase tracking-widest font-label">Llamadas</p>
              <p className="text-2xl font-bold text-on-surface">{logs.length}</p>
            </div>
            <div className="bg-surface-container-high rounded-xl p-4 min-w-[160px]">
              <p className="text-xs text-on-surface-variant uppercase tracking-widest font-label">Fallidas</p>
              <p className="text-2xl font-bold text-error">{failures}</p>
            </div>
            <div className="bg-surface-container-high rounded-xl p-4 min-w-[160px]">
              <p className="text-xs text-on-surface-variant uppercase tracking-widest font-label">Costo estimado</p>
              <p className="text-2xl font-bold text-secondary">${totalCost.toFixed(4)} USD</p>
            </div>
          </div>

          {loading ? (
            <p className="text-on-surface-variant text-sm">Cargando…</p>
          ) : logs.length === 0 ? (
            <p className="text-on-surface-variant text-sm">Todavía nadie ha usado "Cargar con foto".</p>
          ) : (
            <div className="bg-surface-container rounded-xl overflow-hidden">
              <table className="w-full text-sm">
                <thead className="bg-surface-container-high text-on-surface-variant text-left">
                  <tr>
                    <th className="px-4 py-3 font-label">Fecha</th>
                    <th className="px-4 py-3 font-label">Tienda</th>
                    <th className="px-4 py-3 font-label">Foto</th>
                    <th className="px-4 py-3 font-label">Nota</th>
                    <th className="px-4 py-3 font-label">Sugerencia IA</th>
                    <th className="px-4 py-3 font-label">Estado</th>
                    <th className="px-4 py-3 font-label text-right">Costo</th>
                  </tr>
                </thead>
                <tbody>
                  {logs.map((log) => (
                    <tr key={log.id} className="border-t border-outline-variant/10">
                      <td className="px-4 py-3 text-on-surface-variant whitespace-nowrap">
                        {new Date(log.createdAt).toLocaleString()}
                      </td>
                      <td className="px-4 py-3 text-on-surface">{log.storeName}</td>
                      <td className="px-4 py-3">
                        <img src={log.imageUrl} alt="" className="w-10 h-10 object-cover rounded-lg" />
                      </td>
                      <td className="px-4 py-3 text-on-surface-variant max-w-[200px] truncate" title={log.note || ""}>
                        {log.note || "—"}
                      </td>
                      <td className="px-4 py-3 text-on-surface">
                        {log.success ? log.suggestedName || "—" : (
                          <span className="text-error" title={log.errorMessage || ""}>Error</span>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        <span
                          className={`px-2 py-1 rounded-full text-xs font-label ${
                            log.success ? "bg-secondary/10 text-secondary" : "bg-error/10 text-error"
                          }`}
                        >
                          {log.success ? "OK" : "Falló"}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-right text-on-surface-variant">
                        {log.estimatedCostUsd != null ? `$${log.estimatedCostUsd.toFixed(5)}` : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </div>
  );
}
