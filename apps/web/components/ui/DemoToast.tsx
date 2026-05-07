"use client";

import { useCallback, useEffect, useState } from "react";

export function useDemoToast() {
  const [msg, setMsg] = useState<string | null>(null);

  const show = useCallback((message: string) => {
    setMsg(message);
  }, []);

  useEffect(() => {
    if (!msg) return;
    const id = setTimeout(() => setMsg(null), 2500);
    return () => clearTimeout(id);
  }, [msg]);

  return { show, msg };
}

export function DemoToast({ msg }: { msg: string | null }) {
  if (!msg) return null;
  return (
    <div
      role="status"
      aria-live="polite"
      style={{
        position: "fixed",
        bottom: 24,
        right: 24,
        background: "var(--ink, #0a0e1a)",
        color: "#fff",
        padding: "11px 18px",
        borderRadius: 10,
        fontSize: 13,
        fontWeight: 500,
        zIndex: 9999,
        boxShadow: "0 8px 32px rgba(10,14,26,.25)",
        display: "flex",
        alignItems: "center",
        gap: 10,
        maxWidth: 340,
        lineHeight: 1.4,
        animation: "vb-reveal 0.2s ease both",
        fontFamily: "'Inter', system-ui, sans-serif",
      }}
    >
      <span style={{ color: "#86efac", fontSize: 16, flexShrink: 0 }}>✓</span>
      {msg}
    </div>
  );
}
