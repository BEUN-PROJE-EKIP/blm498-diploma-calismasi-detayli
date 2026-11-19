import React, { useCallback, useEffect, useState } from "react";
import { komut, useDurum } from "./api.js";
import UstBar from "./bilesenler/UstBar.jsx";
import KameraKarti from "./bilesenler/KameraKarti.jsx";
import SistemKarti from "./bilesenler/SistemKarti.jsx";
import GorevKarti from "./bilesenler/GorevKarti.jsx";
import UcusKarti from "./bilesenler/UcusKarti.jsx";
import ManuelKarti from "./bilesenler/ManuelKarti.jsx";
import HaritaKarti from "./bilesenler/HaritaKarti.jsx";

function ilkTema() {
  try {
    const kayitli = localStorage.getItem("panel-tema");
    if (kayitli === "acik" || kayitli === "koyu") return kayitli;
  } catch { /* depolama kapalı olabilir */ }
  return "acik"; // varsayılan: açık tema
}

export default function App() {
  const { durum, bagli } = useDurum();
  const [bildirim, setBildirim] = useState(null);
  const [tema, setTema] = useState(ilkTema);

  useEffect(() => {
    document.documentElement.dataset.theme = tema === "acik" ? "light" : "dark";
    try { localStorage.setItem("panel-tema", tema); } catch { /* yok say */ }
  }, [tema]);

  // Komut gönder ve sonucu kısa bir bildirimle göster.
  const gonder = useCallback(async (yol, govde) => {
    const s = await komut(yol, govde);
    if (s.ileti) {
      setBildirim({ ok: s.ok, ileti: s.ileti, k: Date.now() });
      setTimeout(() => setBildirim((b) => (b && Date.now() - b.k >= 3900 ? null : b)), 4000);
    }
    return s;
  }, []);

  const sistemDurum = durum?.sistem?.durum ?? "bilinmiyor";
  const sistemAcik = ["hazir", "gorev", "gorev_bitti"].includes(sistemDurum);
  const araclar = durum?.araclar ?? [1, 2, 3].map((no) => ({ no }));

  return (
    <div className="sayfa">
      <UstBar durum={durum} bagli={bagli} tema={tema} temaDegistir={() => setTema((t) => (t === "koyu" ? "acik" : "koyu"))} />

      <section className="kameralar">
        {araclar.map((a) => (
          <KameraKarti
            key={a.no}
            arac={a}
            kamera={durum?.gazebo?.kameralar?.[a.no]}
            partition={durum?.gazebo?.partition}
            manuel={durum?.manuel_arac === a.no}
          />
        ))}
      </section>

      <section className="alt">
        <div className="komutlar">
          <div className="ust-komutlar">
            <SistemKarti durum={durum} gonder={gonder} />
            <GorevKarti durum={durum} sistemAcik={sistemAcik} gonder={gonder} />
          </div>
          <div className="alt-komutlar">
            <UcusKarti durum={durum} sistemAcik={sistemAcik} gonder={gonder} />
            <ManuelKarti durum={durum} sistemAcik={sistemAcik} gonder={gonder} />
          </div>
        </div>
        <HaritaKarti durum={durum} />
      </section>

      {bildirim && (
        <div className={`bildirim ${bildirim.ok ? "iyi" : "kotu"}`} key={bildirim.k} role="status">
          {bildirim.ileti}
        </div>
      )}
    </div>
  );
}
