import React, { useEffect, useRef, useState } from "react";
import Ikon from "./Ikon.jsx";

// Sayfa açıldığında gereken yazılımları (Gazebo + 3 PX4) başlatan ve kontrolleri gösteren kart.
export default function SistemKarti({ durum, gonder }) {
  const [gunlukAcik, setGunlukAcik] = useState(false);
  const gunlukRef = useRef(null);
  const s = durum?.sistem;
  const d = s?.durum ?? "bilinmiyor";
  const mesgul = ["baslatiliyor", "durduruluyor", "gorev_hazirlaniyor"].includes(d);
  const acik = ["hazir", "gorev", "gorev_bitti"].includes(d);
  const kontroller = durum?.kontroller ?? [];
  const zorunlu = kontroller.filter((k) => !k.uyari);
  const tamam = zorunlu.filter((k) => k.ok).length;

  useEffect(() => {
    if (gunlukAcik && gunlukRef.current) gunlukRef.current.scrollTop = gunlukRef.current.scrollHeight;
  }, [gunlukAcik, s?.gunluk?.length]);

  return (
    <article className="kart sistem">
      <header className="kart-baslik">
        <h2>Sistem</h2>
        {zorunlu.length > 0 && (
          <span className={`kucuk-rozet ${tamam === zorunlu.length ? "iyi" : ""}`}>
            {tamam}/{zorunlu.length} kontrol
          </span>
        )}
      </header>

      <button
        className={`eylem ${acik ? "tehlike" : "birincil"}`}
        disabled={mesgul || !durum}
        onClick={() => gonder(acik ? "/api/sistem/durdur" : "/api/sistem/baslat")}
      >
        <span className="eylem-ikon">{mesgul ? <span className="donen" /> : <Ikon ad={acik ? "dur" : "guc"} />}</span>
        <span className="eylem-metin">
          <strong>{mesgul ? "Lütfen bekleyin" : acik ? "Sistemi durdur" : "Sistemi başlat"}</strong>
          <small>{acik ? "Gazebo ve PX4 süreçleri kapatılır" : "Gazebo ve 3 PX4 SITL açılır, denetlenir"}</small>
        </span>
      </button>

      {zorunlu.length > 0 && (
        <div className="ilerleme" aria-hidden>
          <span style={{ width: `${(tamam / zorunlu.length) * 100}%` }} />
        </div>
      )}

      <ul className="kontroller">
        {kontroller.map((k) => (
          <li key={k.ad} className={k.ok ? "ok" : k.uyari ? "uyari" : ""} title={k.ok ? "" : k.ipucu ?? ""}>
            <i className="durum-nokta" />
            {k.ad}
          </li>
        ))}
      </ul>

      {s?.hata && <p className="hata-satiri">{s.hata}</p>}

      <button className="metin-tus" onClick={() => setGunlukAcik((v) => !v)} aria-expanded={gunlukAcik}>
        {gunlukAcik ? "Günlüğü gizle" : "Günlüğü göster"}
      </button>
      {gunlukAcik && (
        <pre className="gunluk" ref={gunlukRef}>
          {(s?.gunluk ?? []).length === 0 && <div className="bilgi">Henüz kayıt yok.</div>}
          {(s?.gunluk ?? []).map((g, i) => (
            <div key={i} className={g.tur}>{g.metin}</div>
          ))}
        </pre>
      )}
    </article>
  );
}
