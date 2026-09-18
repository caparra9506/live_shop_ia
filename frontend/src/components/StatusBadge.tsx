const STYLES: Record<string, string> = {
  connected: "bg-secondary/20 text-secondary",
  connecting: "bg-primary/20 text-primary",
  disconnected: "bg-error/20 text-error",
};

export default function StatusBadge({ status }: { status: string }) {
  const labels: Record<string, string> = {
    connected: "Conectado",
    connecting: "Conectando…",
    disconnected: "Desconectado",
  };
  return (
    <span className={`px-3 py-1 rounded-full text-xs font-semibold ${STYLES[status] ?? STYLES.disconnected}`}>
      {labels[status] ?? status}
    </span>
  );
}
