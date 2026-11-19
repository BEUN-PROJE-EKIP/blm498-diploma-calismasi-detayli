import React, { useEffect, useRef } from "react";

// Tarayıcının confirm() kutusu yerine panelle uyumlu onay penceresi. Esc: vazgeç, Enter: onayla.
export default function Onay({ baslik, metin, onayMetni = "Onayla", onOnay, onVazgec }) {
  const onayRef = useRef(null);
  useEffect(() => {
    onayRef.current?.focus();
    const tus = (e) => e.key === "Escape" && onVazgec();
    window.addEventListener("keydown", tus);
    return () => window.removeEventListener("keydown", tus);
  }, [onVazgec]);

  return (
    <div className="ortu" role="presentation" onClick={onVazgec}>
      <div className="onay" role="alertdialog" aria-modal="true" aria-labelledby="onay-baslik" onClick={(e) => e.stopPropagation()}>
        <h3 id="onay-baslik">{baslik}</h3>
        <p>{metin}</p>
        <div className="onay-tuslar">
          <button className="tus ikincil" onClick={onVazgec}>Vazgeç</button>
          <button className="tus birincil" ref={onayRef} onClick={onOnay}>{onayMetni}</button>
        </div>
      </div>
    </div>
  );
}
