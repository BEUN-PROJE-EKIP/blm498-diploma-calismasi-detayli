import React, { useEffect, useRef, useState } from "react";
import { komut } from "../api.js";
import Ikon from "./Ikon.jsx";

// 6. kutu: fiziksel oyun kolu ile manuel sürüş (tarayıcı Gamepad API; standart eşleme, Mod 2).
//   Sol çubuk:  yukarı/aşağı = tırmanma/alçalma, sağ/sol = dönüş (sapma)
//   Sağ çubuk:  yukarı/aşağı = ileri/geri,       sağ/sol = sağa/sola kayma
//   LB / RB: sürülecek İHA'yı seç (sürüş kapalıyken) · START: sürüşü başlat/bitir
const OLU_BOLGE = 0.12;
const GONDERIM_MS = 50; // 20 Hz

function olu(v) {
  if (Math.abs(v) < OLU_BOLGE) return 0;
  return Math.sign(v) * ((Math.abs(v) - OLU_BOLGE) / (1 - OLU_BOLGE));
}

function useOyunKolu() {
  const [kol, setKol] = useState(null); // { ad, eksen: {ileri, sag, yukari, donus}, tuslar: [] }
  useEffect(() => {
    let rafId;
    const dongu = () => {
      const pads = navigator.getGamepads ? Array.from(navigator.getGamepads()).filter(Boolean) : [];
      const p = pads[0];
      if (p) {
        const a = p.axes;
        setKol({
          ad: p.id,
          eksen: {
            donus: olu(a[0] ?? 0),
            yukari: -olu(a[1] ?? 0),
            sag: olu(a[2] ?? 0),
            ileri: -olu(a[3] ?? 0),
          },
          tuslar: p.buttons.map((b) => b.pressed),
        });
      } else {
        setKol(null);
      }
      rafId = requestAnimationFrame(dongu);
    };
    rafId = requestAnimationFrame(dongu);
    return () => cancelAnimationFrame(rafId);
  }, []);
  return kol;
}

function Cubuk({ x, y, ust, alt }) {
  return (
    <div className="cubuk">
      <div className="cubuk-alan">
        <span className="cubuk-arti" />
        <span className="cubuk-nokta" style={{ left: `${50 + x * 42}%`, top: `${50 - y * 42}%` }} />
      </div>
      <strong>{ust}</strong>
      <small>{alt}</small>
    </div>
  );
}

export default function ManuelKarti({ durum, sistemAcik, gonder }) {
  const kol = useOyunKolu();
  const [secili, setSecili] = useState(1);
  const surulen = durum?.manuel_arac ?? null;
  const araclar = durum?.araclar ?? [];
  const gorevde = durum?.sistem?.durum === "gorev";
  const eksenRef = useRef(null);
  const oncekiTus = useRef([]);
  eksenRef.current = kol?.eksen ?? null;

  // Sürüş açıkken eksenleri 20 Hz gönder (arka uç 0,5 sn komut gelmezse aracı durdurur).
  useEffect(() => {
    if (surulen == null) return undefined;
    const id = setInterval(() => {
      const e = eksenRef.current ?? { ileri: 0, sag: 0, yukari: 0, donus: 0 };
      komut("/api/manuel/eksen", e);
    }, GONDERIM_MS);
    return () => clearInterval(id);
  }, [surulen]);

  // Oyun kolu tuşları: LB(4)/RB(5) İHA seçimi, START(9) başlat/bitir
  useEffect(() => {
    if (!kol) return;
    const t = kol.tuslar;
    const basildi = (i) => t[i] && !oncekiTus.current[i];
    if (surulen == null && araclar.length) {
      if (basildi(4)) setSecili((s) => ((s + araclar.length - 2) % araclar.length) + 1);
      if (basildi(5)) setSecili((s) => (s % araclar.length) + 1);
    }
    if (basildi(9)) {
      if (surulen != null) gonder("/api/manuel/bitir");
      else if (sistemAcik && !gorevde) gonder("/api/manuel/baslat", { arac: secili });
    }
    oncekiTus.current = t;
  }, [kol, surulen, araclar.length, secili, sistemAcik, gorevde, gonder]);

  const e = kol?.eksen ?? { ileri: 0, sag: 0, yukari: 0, donus: 0 };
  const hedef = araclar.find((a) => a.no === secili);
  const baslatilabilir = sistemAcik && !gorevde && kol && hedef?.havada;

  return (
    <article className="kart manuel">
      <header className="kart-baslik">
        <h2>Manuel sürüş</h2>
        <span className={`kucuk-rozet ${kol ? "iyi" : ""}`}>{kol ? "Kol bağlı" : "Kol yok"}</span>
      </header>

      {!kol && (
        <p className="ipucu">
          Oyun kolunu takıp herhangi bir tuşuna basın; tarayıcı kolu ilk tuş basımında tanır.
        </p>
      )}

      <div className="iha-sec" role="radiogroup" aria-label="Sürülecek İHA">
        {(araclar.length ? araclar : [{ no: 1 }, { no: 2 }, { no: 3 }]).map((a) => (
          <button
            key={a.no}
            role="radio"
            aria-checked={secili === a.no}
            className={`${secili === a.no ? "secili" : ""} ${surulen === a.no ? "suruluyor" : ""}`}
            style={{ "--renk": `var(--iha${a.no})` }}
            disabled={surulen != null}
            onClick={() => setSecili(a.no)}
          >
            İHA {a.no}
          </button>
        ))}
      </div>

      <div className="cubuklar">
        <Cubuk x={e.donus} y={e.yukari} ust="Sol çubuk" alt="İrtifa · Dönüş" />
        <Cubuk x={e.sag} y={e.ileri} ust="Sağ çubuk" alt="İleri · Yan" />
      </div>

      <p className="kisayol"><kbd>LB</kbd>/<kbd>RB</kbd> İHA seç · <kbd>START</kbd> başlat/bitir</p>

      {surulen != null ? (
        <button className="eylem tehlike" onClick={() => gonder("/api/manuel/bitir")}>
          <span className="eylem-ikon"><Ikon ad="dur" /></span>
          <span className="eylem-metin">
            <strong>İHA {surulen} sürüşünü bitir</strong>
            <small>Araç yerinde asılı kalır (Hold)</small>
          </span>
        </button>
      ) : (
        <button
          className="eylem"
          disabled={!baslatilabilir}
          onClick={() => gonder("/api/manuel/baslat", { arac: secili })}
        >
          <span className="eylem-ikon"><Ikon ad="kol" /></span>
          <span className="eylem-metin">
            <strong>İHA {secili} manuel sürüş</strong>
            <small>
              {!kol ? "Oyun kolu gerekli" : gorevde ? "Görev sürerken kapalı" : hedef?.havada ? "Offboard hız kontrolü" : "Önce kalkış yapın"}
            </small>
          </span>
        </button>
      )}
    </article>
  );
}
