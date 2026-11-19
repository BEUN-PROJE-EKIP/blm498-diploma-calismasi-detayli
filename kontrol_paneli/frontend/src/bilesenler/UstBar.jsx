import React from "react";
import Ikon from "./Ikon.jsx";

export const DURUM_ADI = {
  kapali: "Sistem kapalı",
  baslatiliyor: "Başlatılıyor",
  durduruluyor: "Durduruluyor",
  gorev_hazirlaniyor: "Görev hazırlanıyor",
  hazir: "Sistem hazır",
  gorev: "Görev sürüyor",
  gorev_bitti: "Görev bitti",
  bilinmiyor: "Bağlanıyor",
};

const DURUM_TON = {
  kapali: "notr", baslatiliyor: "uyari", durduruluyor: "uyari", gorev_hazirlaniyor: "uyari",
  hazir: "iyi", gorev: "bilgi", gorev_bitti: "iyi", bilinmiyor: "notr",
};

function saat(sn) {
  if (sn == null) return "--:--";
  const d = Math.floor(sn / 60);
  const s = Math.floor(sn % 60);
  return `${String(d).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

export default function UstBar({ durum, bagli, tema, temaDegistir }) {
  const d = bagli ? durum?.sistem?.durum ?? "bilinmiyor" : "bilinmiyor";
  // Mimari modu yalnız görev koşusunda anlamlı (kosu.sh görevsiz koşulara da varsayılan "ucta" yazar).
  const kosu = durum?.sistem?.kosu;
  const mimari = kosu?.gorev_var ? kosu.mimari : null;
  return (
    <header className="ust-bar">
      <div className="baslik">
        <span className="logo"><Ikon ad="logo" boyut={24} /></span>
        <div>
          <h1>Kontrol Paneli</h1>
          <p>Uçta yapay zekâ destekli İHA sürüsü · Simülasyon</p>
        </div>
      </div>
      <div className="ust-bilgiler">
        {mimari && mimari !== "yok" && (
          <span className="bilgi-kutu"><span className="soluk">Mod</span> {mimari === "ucta" ? "Uçta" : "Merkezi"}</span>
        )}
        <span className="bilgi-kutu"><span className="soluk">Sim. zamanı</span> <span className="rakam">{saat(durum?.gazebo?.sim_saat)}</span></span>
        <span className={`rozet ${DURUM_TON[d]}`}>
          <i className="nokta" /> {bagli ? DURUM_ADI[d] : "Panel sunucusu yok"}
        </span>
        <button className="ikon-tus" onClick={temaDegistir} title={tema === "koyu" ? "Açık tema" : "Koyu tema"} aria-label="Temayı değiştir">
          <Ikon ad={tema === "koyu" ? "gunes" : "ay"} boyut={16} />
        </button>
      </div>
    </header>
  );
}
