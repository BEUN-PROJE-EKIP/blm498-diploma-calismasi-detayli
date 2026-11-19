import React, { useEffect, useState } from "react";
import Ikon from "./Ikon.jsx";

// Genel harita: Gazebo'daki tepeden kameranın canlı görüntüsü + üstünde İHA işaretleri.
// Kamera kuzey yukarı (dünya +Y), doğu sağa (dünya +X) bakar; iğne deliği izdüşümüyle dünya → piksel.
function izdusum(h, x, y, z) {
  const W = h.genislik_px;
  const H = h.yukseklik_px;
  const f = W / 2 / Math.tan(h.hfov_rad / 2);
  const derinlik = Math.max(1, h.yukseklik_m - (z ?? 0));
  return {
    u: W / 2 + ((x - h.merkez_m[0]) * f) / derinlik,
    v: H / 2 - ((y - h.merkez_m[1]) * f) / derinlik,
    olcek: f / derinlik, // piksel / metre
  };
}

// İşaretler ve yazıları: araçlar birbirine yakınken (ör. 3 m arayla, ~7 piksel) yazılar üst üste binmesin diye
// alt alta dizilir; yerinden kayan yazı işaretine ince bir çizgiyle bağlanır.
const YAZI_GEN = 128;
const YAZI_YUK = 21;
function isaretleriYerlestir(araclar, pozlar, h, r) {
  const liste = araclar
    .filter((a) => pozlar[a.no])
    .map((a) => {
      const p = pozlar[a.no];
      const { u, v } = izdusum(h, p.x, p.y, p.z);
      // yaw: dünya +X'ten saat yönünün tersine; ekranda v aşağı arttığı için y bileşeni ters
      return { no: a.no, u, v, z: p.z, r, ux: Math.cos(p.yaw), uy: -Math.sin(p.yaw) };
    })
    .sort((a, b) => a.v - b.v || a.u - b.u);
  const yerlesen = [];
  for (const m of liste) {
    m.lx = m.u + r + 8;
    m.ly = m.v - r + 4;
    while (yerlesen.some((y) => Math.abs(y.lx - m.lx) < YAZI_GEN && Math.abs(y.ly - m.ly) < YAZI_YUK)) m.ly += YAZI_YUK;
    m.ayrik = m.ly - (m.v - r + 4) > 1;
    yerlesen.push(m);
  }
  return liste;
}

function HaritaGorunum({ durum, buyuk }) {
  const h = durum?.gazebo?.harita;
  const partition = durum?.gazebo?.partition;
  if (!h) return <div className="harita-ekran bos">Harita bekleniyor…</div>;
  const W = h.genislik_px;
  const H = h.yukseklik_px;
  const pozlar = durum?.gazebo?.pozlar ?? {};
  const araclar = durum?.araclar ?? [];
  const yer = izdusum(h, h.merkez_m[0], h.merkez_m[1], 0);
  const olcek50 = 50 * yer.olcek; // 50 m ölçek çubuğu
  const isaretler = isaretleriYerlestir(araclar, pozlar, h, buyuk ? 9 : 11);

  return (
    <div className={`harita-ekran ${buyuk ? "buyuk" : ""}`} style={{ aspectRatio: `${W} / ${H}` }}>
      {h.canli && partition ? (
        <img src={`/api/harita.mjpg?p=${partition}`} alt="Gazebo ortamının kuş bakışı anlık görüntüsü" />
      ) : (
        <div className="harita-izgara">
          <span>{h.durum === "ekleniyor" ? "Harita kamerası ekleniyor" : "Kuş bakışı görüntü bekleniyor"}</span>
        </div>
      )}
      <svg viewBox={`0 0 ${W} ${H}`} className="harita-katman" aria-hidden>
        {isaretler.map((m) => (
          <g key={m.no} style={{ "--renk": `var(--iha${m.no})` }}>
            {m.ayrik && <line x1={m.u + m.r} y1={m.v} x2={m.lx - 3} y2={m.ly - 5} className="isaret-bag" />}
            <g transform={`translate(${m.u},${m.v})`}>
              <circle r={m.r * 1.9} className="isaret-hale" />
              <circle r={m.r} className="isaret" />
              <line x1={0} y1={0} x2={m.ux * m.r * 2} y2={m.uy * m.r * 2} className="isaret-yon" />
            </g>
            <text x={m.lx} y={m.ly} className="isaret-yazi">
              İHA {m.no} · {Math.max(0, m.z).toFixed(0)} m
            </text>
          </g>
        ))}
        <g transform={`translate(${W - olcek50 - 24},${H - 22})`} className="olcek">
          <line x1={0} y1={0} x2={olcek50} y2={0} />
          <line x1={0} y1={-5} x2={0} y2={5} />
          <line x1={olcek50} y1={-5} x2={olcek50} y2={5} />
          <text x={olcek50 / 2} y={-8}>50 m</text>
        </g>
        <g transform="translate(32,44)" className="pusula">
          <circle r={16} />
          <path d="M0,-11 L5,4 L0,1 L-5,4 Z" />
          <text y={-20}>K</text>
        </g>
      </svg>
    </div>
  );
}

export default function HaritaKarti({ durum }) {
  const [tamEkran, setTamEkran] = useState(false);
  useEffect(() => {
    if (!tamEkran) return undefined;
    const tus = (e) => e.key === "Escape" && setTamEkran(false);
    window.addEventListener("keydown", tus);
    return () => window.removeEventListener("keydown", tus);
  }, [tamEkran]);

  return (
    <article className="kart harita">
      <header className="kart-baslik">
        <h2>Genel harita</h2>
        <span className="kart-alt-baslik">Gazebo · kuş bakışı</span>
        <button className="ikon-tus" title="Tam ekran" aria-label="Haritayı tam ekran aç" onClick={() => setTamEkran(true)}>
          <Ikon ad="buyut" boyut={16} />
        </button>
      </header>
      <HaritaGorunum durum={durum} />

      {tamEkran && (
        <div className="ortu tam-ekran" role="dialog" aria-modal="true" aria-label="Genel harita, tam ekran" onClick={() => setTamEkran(false)}>
          <div className="tam-ekran-ic" onClick={(e) => e.stopPropagation()}>
            <header className="kart-baslik">
              <h2>Genel harita</h2>
              <span className="kart-alt-baslik">Kapatmak için Esc</span>
              <button className="ikon-tus" title="Kapat" aria-label="Kapat" onClick={() => setTamEkran(false)}>
                <Ikon ad="kapat" boyut={16} />
              </button>
            </header>
            <HaritaGorunum durum={durum} buyuk />
          </div>
        </div>
      )}
    </article>
  );
}
