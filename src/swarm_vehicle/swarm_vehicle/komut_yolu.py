"""Komut yolu iskeleti (saf mantık): yer istasyonu komutlarının araçta denetimi (belge: komutlar araç kimliği, sıra numarası ve onay durumu içerir; komut TÜRLERİNİ tanımlamaz).

Kullanıcı kararı 2026-11-14: yol uçtan uca kurulur, yeni komut türü uydurulmaz, PX4'e hiçbir şey yazılmaz. Bu yüzden denetimi geçen komut da `ACK_REJECTED` döner (neden: komut türü belgede tanımlı değil).
Denetim sırası: (1) yanlış araç → reddet; (2) tekrar ya da geriye giden sıra numarası (≤ bu araçta görülen en büyük sıra) → reddet; (3) aksi halde komut türü tanımsız → reddet.
"""
ACK_PENDING, ACK_ACCEPTED, ACK_REJECTED = 1, 2, 3

NEDEN_YANLIS_ARAC = "yanlis_arac"
NEDEN_TEKRAR_SIRA = "tekrar_ya_da_geriye_sira"
NEDEN_TUR_TANIMSIZ = "komut_turu_belgede_tanimli_degil"


def denetle(arac_kimligi, vehicle_id, sequence, son_sira):
    """Dönen: (ack_state, neden, yeni_son_sira). Her durumda ack_state ACK_REJECTED'dır (kabul edilebilecek bir komut türü yoktur)."""
    if int(vehicle_id) != int(arac_kimligi):
        return ACK_REJECTED, NEDEN_YANLIS_ARAC, son_sira
    if son_sira is not None and int(sequence) <= son_sira:
        return ACK_REJECTED, NEDEN_TEKRAR_SIRA, son_sira
    return ACK_REJECTED, NEDEN_TUR_TANIMSIZ, int(sequence)
