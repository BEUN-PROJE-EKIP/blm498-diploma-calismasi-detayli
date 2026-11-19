import React from "react";

// Tek tip, ince çizgili simgeler (24×24, currentColor).
const YOLLAR = {
  guc: <><path d="M12 3v8" /><path d="M6.3 7.2a8 8 0 1 0 11.4 0" /></>,
  dur: <rect x="6" y="6" width="12" height="12" rx="2" />,
  oynat: <path d="M8 5.5v13l10-6.5z" />,
  kalkis: <><path d="M12 19V7" /><path d="m6.5 12.5 5.5-5.5 5.5 5.5" /><path d="M5 4h14" /></>,
  inis: <><path d="M12 5v12" /><path d="m6.5 11.5 5.5 5.5 5.5-5.5" /><path d="M5 20h14" /></>,
  kol: <><path d="M7 8h10a4 4 0 0 1 3.9 4.9l-.8 3.4a2.4 2.4 0 0 1-4.2.9L14.6 16H9.4l-1.3 1.2a2.4 2.4 0 0 1-4.2-.9l-.8-3.4A4 4 0 0 1 7 8z" /><path d="M8 11v3M6.5 12.5h3" /><circle cx="16" cy="11.5" r=".6" /><circle cx="17.5" cy="13.5" r=".6" /></>,
  buyut: <><path d="M14 4h6v6" /><path d="M10 20H4v-6" /><path d="m20 4-7 7" /><path d="m4 20 7-7" /></>,
  kapat: <><path d="M6 6l12 12" /><path d="M18 6 6 18" /></>,
  kamera: <><path d="M4 8h3l1.5-2h7L17 8h3v11H4z" /><circle cx="12" cy="13" r="3.2" /></>,
  gunes: <><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" /></>,
  ay: <path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z" />,
  // Üstten görünüş dörtlü pervaneli İHA: gövde, dört kol, dört pervane, aşağı bakan kamera
  logo: <><rect x="9" y="9" width="6" height="6" rx="1.8" /><circle cx="12" cy="12" r=".9" /><path d="M9.6 9.6 7.4 7.4M14.4 9.6l2.2-2.2M9.6 14.4l-2.2 2.2M14.4 14.4l2.2 2.2" /><circle cx="5.6" cy="5.6" r="3" /><circle cx="18.4" cy="5.6" r="3" /><circle cx="5.6" cy="18.4" r="3" /><circle cx="18.4" cy="18.4" r="3" /></>,
};

export default function Ikon({ ad, boyut = 18, className = "" }) {
  const dolu = ad === "oynat" || ad === "dur";
  return (
    <svg
      className={`ikon ${className}`}
      width={boyut}
      height={boyut}
      viewBox="0 0 24 24"
      fill={dolu ? "currentColor" : "none"}
      stroke="currentColor"
      strokeWidth={dolu ? 0 : 1.7}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {YOLLAR[ad]}
    </svg>
  );
}
