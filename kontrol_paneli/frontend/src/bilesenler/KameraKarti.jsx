import React from "react";
import Ikon from "./Ikon.jsx";

function deger(v, birim, basamak = 1) {
  return v == null ? "—" : `${Number(v).toFixed(basamak)} ${birim}`;
}

export default function KameraKarti({ arac, kamera, partition, manuel }) {
  const canli = kamera?.canli;
  return (
    <article className="kart kamera" style={{ "--renk": `var(--iha${arac.no})` }}>
      <header className="kamera-baslik">
        <span className="iha-adi"><i className="renk-cizgi" />İHA {arac.no}</span>
        {manuel && <span className="kucuk-rozet uyari">Manuel</span>}
        <span className={`kucuk-rozet ${canli ? "canli" : ""}`}>{canli ? "Canlı" : "Görüntü yok"}</span>
      </header>
      <div className="kamera-ekran">
        {canli && partition ? (
          // partition değişince (yeni koşu) akış yeniden açılır
          <img src={`/api/kamera/${arac.no}.mjpg?p=${partition}`} alt={`İHA ${arac.no} kamera görüntüsü`} />
        ) : (
          <div className="goruntu-yok">
            <Ikon ad="kamera" boyut={28} />
            <span>Kamera akışı bekleniyor</span>
          </div>
        )}
      </div>
      <dl className="telemetri">
        <div><dt>İrtifa</dt><dd>{deger(arac.irtifa_m, "m")}</dd></div>
        <div><dt>Hız</dt><dd>{deger(arac.yer_hizi_ms, "m/s")}</dd></div>
        <div><dt>Batarya</dt><dd>{arac.batarya == null ? "—" : `%${Math.round(arac.batarya)}`}</dd></div>
        <div><dt>Mod</dt><dd className={arac.silahli ? "silahli" : ""}>{arac.bagli ? (arac.mod ?? "—") : "Bağlı değil"}</dd></div>
      </dl>
    </article>
  );
}
