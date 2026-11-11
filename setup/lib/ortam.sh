#!/usr/bin/env bash
# setup/lib/ortam.sh — ortam kaydı işlevleri: kurulu apt paketleri ve NVIDIA/CUDA sürümleri. `source` edilmek için yazılmıştır
# (common.sh'ten SONRA). ortam_kaydi.sh ve lib/rapor.sh kullanır.
# Kayıtlar yalnız izlenebilirlik içindir (kurulumu kısıtlamaz); tarih, makine adı ve kullanıcı adı içermez, LC_ALL=C ile sıralıdır.

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    echo "Bu dosya doğrudan çalıştırılmaz; bir betikten 'source' edilir." >&2
    exit 1
fi

# shellcheck disable=SC2034  # değişkenler bu kitaplığı kaynaklayan betiklerde kullanılır
ORTAM_APT_FILE="$SETUP_DIR/locks/apt-surumleri.txt"
# shellcheck disable=SC2034
ORTAM_NV_FILE="$SETUP_DIR/locks/nvidia-cuda.txt"

# ortam_apt_now : kurulu (durumu 'ii' olan) bütün apt paketleri, satır biçimi "paket sürüm mimari"
ortam_apt_now() {
    dpkg-query -W -f='${db:Status-Abbrev} ${Package} ${Version} ${Architecture}\n' | awk '$1 == "ii" { print $2, $3, $4 }' | LC_ALL=C sort
}

# ortam_nvidia_now : ilk satır "sürücü=… cuda=…"; sonra adı nvidia/libnvidia/cuda ile başlayan apt paketleri (yoksa "apt: yok")
ortam_nvidia_now() {
    local drv cuda pk
    drv="$(nvidia-smi --query-gpu=driver_version --format=csv,noheader 2>/dev/null | sed -n 1p || true)"
    cuda="$(nvidia-smi 2>/dev/null | sed -n 's/.*CUDA Version: *\([0-9][0-9.]*\).*/\1/p' | sed -n 1p || true)"
    echo "sürücü=${drv:-yok} cuda=${cuda:-yok}"
    pk="$(ortam_apt_now | awk '$1 ~ /^(nvidia|libnvidia|cuda)/')"
    if [[ -n "$pk" ]]; then echo "$pk"; else echo "apt: yok"; fi
    echo "# not: torch CUDA kütüphaneleri pip ile gelir; sürümleri setup/locks/python-requirements.lock.txt içindedir"
}

# ortam_apt_diff <kayıt> <şimdi> : farkları "+ paket sürüm mimari" (eklenen), "- …" (kaldırılan), "~ paket eski -> yeni mimari"
# (sürümü değişen) biçiminde, sıralı yazar. Girdiyi sonuna kadar okur (SIGPIPE yok).
ortam_apt_diff() {
    awk '
        FNR == NR { old[$1 " " $3] = $2; next }
        { k = $1 " " $3; seen[k] = 1
          if (!(k in old)) print "+ " $1 " " $2 " " $3
          else if (old[k] != $2) print "~ " $1 " " old[k] " -> " $2 " " $3 }
        END { for (k in old) if (!(k in seen)) { split(k, a, " "); print "- " a[1] " " old[k] " " a[2] } }
    ' "$1" "$2" | LC_ALL=C sort -k2
}
