// Arka uç ile konuşma: durum Server-Sent Events ile gelir, komutlar POST ile gider.
import { useEffect, useState } from "react";

export function useDurum() {
  const [durum, setDurum] = useState(null);
  const [bagli, setBagli] = useState(false);
  useEffect(() => {
    let es;
    let zamanlayici;
    const ac = () => {
      es = new EventSource("/api/olaylar");
      es.onopen = () => setBagli(true);
      es.onmessage = (e) => setDurum(JSON.parse(e.data));
      es.onerror = () => {
        setBagli(false);
        es.close();
        zamanlayici = setTimeout(ac, 2000);
      };
    };
    ac();
    return () => {
      clearTimeout(zamanlayici);
      es && es.close();
    };
  }, []);
  return { durum, bagli };
}

export async function komut(yol, govde = {}) {
  try {
    const r = await fetch(yol, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(govde),
    });
    return await r.json();
  } catch (e) {
    return { ok: false, ileti: "Panel sunucusuna ulaşılamadı" };
  }
}
