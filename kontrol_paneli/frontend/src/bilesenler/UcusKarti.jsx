import React from "react";
import Ikon from "./Ikon.jsx";

// 3. kutu: toplu havaya kalkış (yalnız kalkış), 4. kutu: havadan iniş (yalnız iniş)
export default function UcusKarti({ durum, sistemAcik, gonder }) {
  const araclar = durum?.araclar ?? [];
  const bagli = araclar.filter((a) => a.bagli).length;
  const havada = araclar.filter((a) => a.havada).length;
  const gorevde = durum?.sistem?.durum === "gorev";
  const irtifa = durum?.kalkis_irtifa_m ?? 30;

  return (
    <article className="kart ucus">
      <header className="kart-baslik">
        <h2>Sürü</h2>
        <span className="kucuk-rozet">{havada}/{araclar.length || 3} havada</span>
      </header>

      <button className="eylem" disabled={!sistemAcik || bagli === 0 || gorevde} onClick={() => gonder("/api/ucus/kalkis")}>
        <span className="eylem-ikon"><Ikon ad="kalkis" /></span>
        <span className="eylem-metin">
          <strong>Toplu kalkış</strong>
          <small>Bağlı tüm İHA'lar {irtifa} m irtifaya</small>
        </span>
      </button>

      <button className="eylem" disabled={!sistemAcik || havada === 0} onClick={() => gonder("/api/ucus/inis")}>
        <span className="eylem-ikon"><Ikon ad="inis" /></span>
        <span className="eylem-metin">
          <strong>Toplu iniş</strong>
          <small>Havadaki İHA'lar bulundukları yere</small>
        </span>
      </button>

      <ul className="arac-listesi">
        {araclar.map((a) => (
          <li key={a.no} style={{ "--renk": `var(--iha${a.no})` }}>
            <i className="renk-cizgi" />
            <span className="ad">İHA {a.no}</span>
            <span className={`durum-metni ${a.bagli ? (a.havada ? "iyi" : "") : "soluk"}`}>
              {a.son_islem || (a.bagli ? (a.havada ? "Havada" : "Yerde") : "Bağlı değil")}
            </span>
          </li>
        ))}
      </ul>
    </article>
  );
}
