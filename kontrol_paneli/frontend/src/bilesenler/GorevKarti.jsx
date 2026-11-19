import React, { useState } from "react";
import Ikon from "./Ikon.jsx";
import Onay from "./Onay.jsx";

const MODLAR = [
  { deger: "ucta", ad: "Uçta", aciklama: "Çıkarım her İHA'da yapılır" },
  { deger: "merkezi", ad: "Merkezi", aciklama: "Çıkarım yer istasyonunda yapılır" },
];

// 1. kutu: mod seçimi, 2. kutu: görevi başlat
export default function GorevKarti({ durum, sistemAcik, gonder }) {
  const [mod, setMod] = useState("ucta");
  const [onayAcik, setOnayAcik] = useState(false);
  const d = durum?.sistem?.durum;
  const gorevde = d === "gorev" || d === "gorev_hazirlaniyor";
  const kosu = durum?.sistem?.kosu;
  const bitti = d === "gorev_bitti";
  const modAdi = MODLAR.find((m) => m.deger === mod).ad;

  return (
    <article className="kart gorev">
      <header className="kart-baslik">
        <h2>Görev</h2>
        {gorevde && <span className="kucuk-rozet bilgi">Sürüyor</span>}
        {bitti && (
          <span className={`kucuk-rozet ${kosu?.gorev_cikis === 0 ? "iyi" : "kotu"}`}>
            {kosu?.gorev_cikis === 0 ? "Tamamlandı" : `Çıkış kodu ${kosu?.gorev_cikis}`}
          </span>
        )}
      </header>

      <div className="alan-etiketi">Mimari modu</div>
      <div className="bolumlu" role="radiogroup" aria-label="Mimari modu">
        {MODLAR.map((m) => (
          <button
            key={m.deger}
            role="radio"
            aria-checked={mod === m.deger}
            className={mod === m.deger ? "secili" : ""}
            disabled={gorevde}
            onClick={() => setMod(m.deger)}
          >
            <strong>{m.ad}</strong>
            <small>{m.aciklama}</small>
          </button>
        ))}
      </div>

      <button className="eylem" disabled={!sistemAcik || gorevde} onClick={() => setOnayAcik(true)}>
        <span className="eylem-ikon"><Ikon ad="oynat" /></span>
        <span className="eylem-metin">
          <strong>Görevi başlat</strong>
          <small>{sistemAcik ? `Tarama görevi · ${modAdi} mod` : "Önce sistemi başlatın"}</small>
        </span>
      </button>

      {onayAcik && (
        <Onay
          baslik="Görev başlatılsın mı?"
          metin={`Görev ${modAdi} modda başlatılacak. Simülasyon temiz bir koşuyla yeniden açılır; araçlar başlangıç konumundan kalkar.`}
          onayMetni="Görevi başlat"
          onVazgec={() => setOnayAcik(false)}
          onOnay={() => {
            setOnayAcik(false);
            gonder("/api/gorev/baslat", { mod });
          }}
        />
      )}
    </article>
  );
}
