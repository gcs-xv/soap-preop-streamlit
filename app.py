import re
from dataclasses import dataclass
from datetime import datetime, timedelta, date
from dateutil import tz
import streamlit as st

TZ = tz.gettz("Asia/Jakarta")

DAY_ID = {
    "Monday": "Senin",
    "Tuesday": "Selasa",
    "Wednesday": "Rabu",
    "Thursday": "Kamis",
    "Friday": "Jumat",
    "Saturday": "Sabtu",
    "Sunday": "Minggu",
}

# -------------------------
# Small helpers
# -------------------------
def day_name_id(d: date) -> str:
    return DAY_ID.get(d.strftime("%A"), d.strftime("%A"))

def fmt_ddmmyyyy(d: date) -> str:
    return d.strftime("%d/%m/%Y")

def clean(s: str) -> str:
    return (s or "").strip()

def pick1(text: str, pattern: str, flags=0) -> str:
    m = re.search(pattern, text, flags)
    return clean(m.group(1)) if m else ""

def pick_block(text: str, start_pat: str, end_pat: str) -> str:
    flags = re.IGNORECASE | re.DOTALL
    m1 = re.search(start_pat, text, flags)
    if not m1:
        return ""
    start = m1.end()
    m2 = re.search(end_pat, text[start:], flags)
    end = start + (m2.start() if m2 else len(text[start:]))
    return clean(text[start:end])

def normalize_bullets(s: str) -> str:
    if not s:
        return ""
    s = s.replace("•⁠", "•").replace("• ⁠", "• ").replace("•⁠  ⁠", "• ")
    # rapikan spasi
    s = re.sub(r"[ \t]+\n", "\n", s)
    return s.strip()

def split_residen_text(s: str) -> str:
    """
    Terima input bebas:
    - "drg. A, drg. B, drg. C"
    - multi-line
    Output: satu baris rapi pakai koma
    """
    if not s:
        return ""
    s = s.replace("\n", ",")
    parts = [p.strip() for p in s.split(",") if p.strip()]
    return ", ".join(parts)

# -------------------------
# Models
# -------------------------
@dataclass
class ParsedSoap:
    sapaan: str = "Assalamualaikum, Dokter."
    pembuka: str = "Maaf mengganggu. Izin melaporkan pasien"
    jenis_laporan: str = ""         # Rawat Jalan / Rencana Operasi (di output kita pakai pre-op)
    rs: str = "RSGMP UNHAS"
    ident_line: str = ""

    nama: str = ""
    jk: str = ""
    umur: str = ""
    pembiayaan: str = ""            # BPJS/Umum/etc
    jenis_perawatan: str = ""       # Rawat Jalan/Inap
    kamar: str = ""                 # untuk pre-op biasanya ada
    rm: str = ""

    S: str = ""
    O_generalis: str = ""
    EO: str = ""
    IO: str = ""
    penunjang_items: list = None    # list[str]
    A: str = ""

    residen: str = ""
    dpjp: str = ""

# -------------------------
# Parsing SOAP mentah (lebih robust)
# -------------------------
def parse_raw_soap(raw: str) -> ParsedSoap:
    raw = raw.strip()
    p = ParsedSoap(penunjang_items=[])

    # Sapaan/pembuka opsional: ambil baris pertama kalau cocok
    first_line = raw.splitlines()[0].strip() if raw.splitlines() else ""
    if first_line.lower().startswith("assalamualaikum"):
        p.sapaan = first_line

    # RS
    if re.search(r"RSGMP\s*UNHAS", raw, re.IGNORECASE):
        p.rs = "RSGMP UNHAS"
    else:
        # fallback: coba ambil "RSGMP ...."
        rs_guess = pick1(raw, r"(RSGMP[^\n/]+)", re.IGNORECASE)
        if rs_guess:
            p.rs = rs_guess

    # Identitas: cari baris yang mengandung "/" banyak (format kamu)
    # Biasanya satu baris setelah kalimat izin melaporkan.
    ident = pick1(raw, r"\n\s*([A-Za-z]{1,4}\.\s*[^\n]+/\s*[LP]\s*/[^\n]+)\n", re.IGNORECASE)
    if not ident:
        ident = pick1(raw, r"^(Tn\.|Ny\.|An\.)[^\n]+", re.IGNORECASE | re.MULTILINE)
    p.ident_line = ident

    if ident:
        parts = [x.strip() for x in ident.split("/") if x.strip()]
        # contoh: Tn. Imam / L / 27 Tahun / BPJS / Rawat Jalan / RSGMP Unhas / RM ...
        if parts:
            p.nama = parts[0].replace("An.", "An.").strip()
        if len(parts) >= 2:
            p.jk = parts[1]
        if len(parts) >= 3:
            p.umur = parts[2]
        # pembiayaan
        if len(parts) >= 4:
            p.pembiayaan = parts[3]
        # jenis perawatan
        if len(parts) >= 5 and ("rawat" in parts[4].lower()):
            p.jenis_perawatan = parts[4]
        # kamar (pre-op sering: Rawat Inap / Kamar ... / RS / RM)
        # kalau ada "Kamar" di salah satu part
        for part in parts:
            if part.lower().startswith("kamar"):
                p.kamar = part
        # RM
        p.rm = pick1(raw, r"RM\.?\s*([0-9.]+)", re.IGNORECASE) or pick1(raw, r"RM\s*([0-9.]+)", re.IGNORECASE)

    # S / O / A blocks
    p.S = pick_block(raw, r"\bS\s*:\s*", r"\n\s*O\s*:\s*")
    o_block = pick_block(raw, r"\bO\s*:\s*", r"\n\s*A\s*:\s*")
    p.A = pick_block(raw, r"\bA\s*:\s*", r"\n\s*P\s*:\s*")

    # O generalis & lokalis
    p.O_generalis = normalize_bullets(pick_block(o_block, r"Status\s+Generalis\s*:\s*", r"Status\s+Lokalis\s*:"))
    if not p.O_generalis:
        # fallback: ambil dari "Status Generalis" sampai sebelum "Status Lokalis" atau EO
        p.O_generalis = normalize_bullets(pick_block(o_block, r"Status\s+Generalis\s*:\s*", r"\n\s*(Status\s+Lokalis|EO\s*:|E\.?O\s*:)\s*"))

    # EO & IO
    p.EO = normalize_bullets(pick_block(o_block, r"\bEO\s*:\s*", r"\n\s*IO\s*:\s*")) or \
           normalize_bullets(pick_block(o_block, r"\bE\.?O\s*:\s*", r"\n\s*I\.?O\s*:\s*"))
    p.IO = normalize_bullets(pick_block(o_block, r"\bIO\s*:\s*", r"\n\s*(Pemeriksaan|A\s*:|$)")) or \
           normalize_bullets(pick_block(o_block, r"\bI\.?O\s*:\s*", r"\n\s*(Pemeriksaan|A\s*:|$)"))

    # Penunjang: ambil daftar bullet di bawah "Pemeriksaan Penunjang" jika ada
    pen_block = pick_block(raw, r"Pemeriksaan\s+Penunjang\s*:?\s*", r"\n\s*A\s*:\s*")
    pen_block = normalize_bullets(pen_block)
    if pen_block:
        # ambil tiap baris yang diawali bullet atau yang terlihat seperti item
        items = []
        for line in pen_block.splitlines():
            line = line.strip()
            if not line:
                continue
            # buang bullet lead
            line = re.sub(r"^•\s*", "", line)
            items.append(line)
        # dedupe sederhana
        seen = set()
        for it in items:
            k = it.lower()
            if k not in seen:
                seen.add(k)
                p.penunjang_items.append(it)

    # Residen & DPJP
    p.residen = split_residen_text(pick1(raw, r"Residen\s*:?\s*(.+)", re.IGNORECASE))
    p.dpjp = clean(pick1(raw, r"DPJP\s*:?\s*(.+)", re.IGNORECASE))

    # Rapikan A (biar bullet konsisten)
    p.A = normalize_bullets(p.A)

    return p

# -------------------------
# Optional: parse lab block into items (biar gak ngetik per angka)
# -------------------------
def lab_block_to_items(lab_text: str) -> list[str]:
    t = clean(lab_text)
    if not t:
        return []
    t = normalize_bullets(t)

    items = []
    # cari tanggal dalam kurung
    tgl = pick1(t, r"\(\s*([0-9]{1,2}/[0-9]{1,2}/[0-9]{4})\s*\)")
    head = f"Lab darah ({tgl})" if tgl else "Lab darah"
    items.append(head)

    # ambil lines penting (WBC/RBC/HGB/HCT/PLT/aPTT/PT/INR/CT/BT/GDS/HBsAg/Kesan)
    keys = ["WBC", "RBC", "HGB", "HCT", "PLT", "aPTT", "PT", "INR", "CT", "BT", "GDS", "HBsAg", "Kesan"]
    for k in keys:
        m = re.search(rf"\b{k}\b\s*[: ]\s*([^\n]+)", t, re.IGNORECASE)
        if m:
            val = clean(m.group(1))
            # format bullet seperti contoh kamu
            if k.lower() == "kesan":
                items.append(f"Kesan : {val}")
            else:
                items.append(f"{k} : {val}")
    return items

# -------------------------
# Output builder (Pre-Op)
# -------------------------
def build_preop(
    p: ParsedSoap,
    tanggal_laporan: date,
    tanggal_operasi: date,
    jam_operasi: str,
    zona_waktu: str,
    tindakan_line: str,
    anestesi: str,
    pembiayaan: str,
    jenis_perawatan: str,
    kamar: str,
    penunjang_items: list[str],
    plan_items: list[str],
    residen: str,
    dpjp: str,
) -> str:
    hari_lap = day_name_id(tanggal_laporan)
    hari_op = day_name_id(tanggal_operasi)

    header = (
        f"{p.sapaan}\n"
        f"{p.pembuka} pasien Rencana Operasi {p.rs} ({hari_lap}, {fmt_ddmmyyyy(tanggal_laporan)})\n\n"
    )

    ident = (
        f"{p.nama} / {p.jk} / {p.umur} / {pembiayaan} / {jenis_perawatan} / {kamar} / {p.rs} / RM {p.rm}\n\n"
    )

    # Penunjang block
    pen_block = ""
    if penunjang_items:
        pen_block = "Pemeriksaan penunjang :\n" + "\n".join([f"•⁠  ⁠{it}" for it in penunjang_items]) + "\n\n"

    # A: pastikan ada bullet kalau belum
    A_text = p.A.strip()
    if A_text and not A_text.lstrip().startswith("•"):
        A_text = "•⁠  ⁠" + A_text

    # Plan block
    P_block = "\n".join([f"•⁠  ⁠{x}" for x in plan_items if clean(x)])

    # Baris tindakan final: kita biarkan sepenuhnya editable (multi-purpose)
    # tapi default string bisa kamu buat dari P raw + setting.
    tindakan_final = (
        f"•⁠  ⁠Pro {tindakan_line} dalam {anestesi} pada hari {hari_op}, {fmt_ddmmyyyy(tanggal_operasi)} "
        f"Pukul {jam_operasi} {zona_waktu} di {p.rs}"
    )

    out = (
        header
        + ident
        + f"S: {p.S}\n\n"
        + "O:\n"
        + "Status Generalis:\n"
        + (p.O_generalis + "\n\n" if p.O_generalis else "")
        + "Status Lokalis:\n"
        + "EO:\n"
        + (p.EO + "\n\n" if p.EO else "")
        + "IO:\n"
        + (p.IO + "\n\n" if p.IO else "")
        + (pen_block if pen_block else "")
        + "A:\n"
        + (A_text + "\n\n" if A_text else "")
        + "P:\n"
        + P_block + "\n"
        + tindakan_final + "\n\n"
        + "Mohon instruksi selanjutnya, Dokter.\n"
        + "Terima kasih.\n\n"
        + f"Residen: {residen}\n\n"
        + f"DPJP: {dpjp}\n"
    )
    return out

# -------------------------
# Streamlit UI
# -------------------------
st.set_page_config(page_title="SOAP → Pre-Op Generator", layout="wide")
st.title("SOAP Terjaring → SOAP Pre-Op (fleksibel & cepat)")

# Defaults/presets
DPJP_PRESETS = [
    "drg. Husnul Basyar, Sp.B.M.Mf.",
    "drg. Abul Fauzi, Sp.B.M.Mf., Subsp.Tr.Mf.S.Tm.",
    "Dr. drg. Andi Tajrin, M.Kes., Sp.B.M.Mf., Subsp.C.O.Mf.",
]
DEFAULT_PLAN_LIBRARY = [
    "ACC TS Anestesi",
    "IVFD RL 16 tpm (makrodrips)",
    "Puasa 6 jam pre op atau sesuai instruksi dari TS Anestesi yaitu mulai Pukul 02.00 WITA",
    "Pasien menyikat gigi sebelum tidur dan sebelum ke kamar operasi",
    "Gunakan masker bedah saat ke kamar operasi",
    "Pasien rencana diberikan antibiotik profilaksis Ceftriaxone inj 1 gr, 1 jam sebelum operasi (skin test terlebih dahulu) pada Pukul 07.00 WITA",
]

colL, colR = st.columns([1.2, 1])

with colL:
    st.subheader("1) Paste SOAP mentah")
    raw = st.text_area("SOAP mentah", height=330, placeholder="Paste SOAP Rawat Jalan / non pre-op di sini...")

    st.subheader("2) (Opsional) Paste hasil lab (biar auto jadi penunjang)")
    lab_text = st.text_area("Blok lab (opsional)", height=140, placeholder="Contoh: Lab Darah (30/12/2025)\nWBC : ...\nCT : ...\nBT : ...\nKesan : ...")

with colR:
    st.subheader("Auto-extract → kamu tinggal edit sedikit")

    if st.button("Parse SOAP", type="primary"):
        st.session_state["parsed"] = parse_raw_soap(raw) if raw.strip() else ParsedSoap(penunjang_items=[])

    parsed: ParsedSoap = st.session_state.get("parsed", ParsedSoap(penunjang_items=[]))

    # Identitas editable (supaya multipurpose)
    st.markdown("**Identitas**")
    nama = st.text_input("Nama (termasuk Tn./Ny./An.)", value=parsed.nama or "")
    jk = st.text_input("JK", value=parsed.jk or "")
    umur = st.text_input("Umur", value=parsed.umur or "")
    pembiayaan = st.text_input("Pembiayaan", value=parsed.pembiayaan or "BPJS")
    jenis_perawatan = st.text_input("Jenis Perawatan", value="Rawat Inap")  # pre-op default rawat inap
    kamar = st.text_input("Kamar/Bed", value=parsed.kamar or "Kamar ... Bed ...")
    rm = st.text_input("RM", value=parsed.rm or "")

    st.divider()

    # Tanggal & jam (H+1 default)
    today = datetime.now(TZ).date()
    default_op = today + timedelta(days=1)
    tanggal_laporan = st.date_input("Tanggal laporan", value=today)
    tanggal_operasi = st.date_input("Tanggal operasi (default H+1)", value=default_op)

    c1, c2, c3 = st.columns(3)
    with c1:
        jam_operasi = st.text_input("Jam operasi", value="07.30")
    with c2:
        zona_waktu = st.text_input("Zona waktu", value="WITA")
    with c3:
        anestesi = st.text_input("Anestesi", value="general anestesi")

    st.divider()

    # Isi klinis editable (hasil parse jadi default)
    st.markdown("**Isi SOAP**")
    S = st.text_area("S", value=parsed.S or "", height=140)
    O_generalis = st.text_area("O - Status Generalis", value=parsed.O_generalis or "", height=120)
    EO = st.text_area("EO", value=parsed.EO or "", height=120)
    IO = st.text_area("IO", value=parsed.IO or "", height=120)
    A = st.text_area("A", value=parsed.A or "", height=90)

    st.divider()

    # Penunjang: list dinamis
    st.markdown("**Pemeriksaan Penunjang (fleksibel)**")

    # start from parsed penunjang + lab parsed
    base_penunjang = list(parsed.penunjang_items or [])
    if lab_text.strip():
        # ubah blok lab jadi items dan gabung (tanpa duplikat)
        lab_items = lab_block_to_items(lab_text)
        for it in lab_items:
            if it and it.lower() not in {x.lower() for x in base_penunjang}:
                base_penunjang.append(it)

    # Editor: multi-line, 1 item per line
    penunjang_editor = st.text_area(
        "Isi 1 item per baris (tanpa bullet juga boleh)",
        value="\n".join(base_penunjang),
        height=140,
        placeholder="Contoh:\nOPG X-Ray (17/12/2025)\nThorax X-Ray (30/12/2025)\nLab darah (30/12/2025)\nWBC : ...\nKesan : ..."
    )
    penunjang_items = [clean(x) for x in penunjang_editor.splitlines() if clean(x)]

    st.divider()

    # Plan builder: checklist dari library + custom lines
    st.markdown("**Plan Builder (ceklist + custom)**")
    st.caption("Centang yang dipakai, lalu edit jika jam/dosis berbeda. Kamu juga bisa tambah custom.")

    # Simpan state plan checked
    if "plan_checked" not in st.session_state:
        st.session_state["plan_checked"] = {item: True for item in DEFAULT_PLAN_LIBRARY}

    plan_lines = []
    for item in DEFAULT_PLAN_LIBRARY:
        checked = st.checkbox(item, value=st.session_state["plan_checked"].get(item, True), key=f"plan_{item}")
        st.session_state["plan_checked"][item] = checked
        if checked:
            plan_lines.append(item)

    custom_plan = st.text_area("Custom plan (1 item per baris)", height=110, placeholder="Contoh:\nSiap darah 1 bag PRC\nIVFD RL 20 tpm (makrodrips)")
    for line in custom_plan.splitlines():
        if clean(line):
            plan_lines.append(clean(line))

    st.divider()

    # Tindakan: jangan dipatok. FULL editable line.
    tindakan_line = st.text_input(
        "Tindakan (tanpa 'Pro' dan tanpa tanggal/jam) — bebas",
        value="Arthrocentesis bilateral + injeksi I-PRF"
    )

    st.divider()

    # Residen & DPJP
    st.markdown("**Penutup**")
    residen_detected = parsed.residen or ""
    residen_in = st.text_area("Residen (paste bebas, nanti dirapihin)", value=residen_detected, height=70)
    residen_out = split_residen_text(residen_in)

    dpjp_choice = st.selectbox("DPJP (preset)", DPJP_PRESETS, index=0)
    dpjp_custom = st.text_input("DPJP (override kalau mau)", value=parsed.dpjp or "")
    dpjp_final = dpjp_custom.strip() if dpjp_custom.strip() else dpjp_choice

# Build output button at bottom (full width feel)
st.divider()
if st.button("Generate SOAP Pre-Op", type="primary"):
    # Build a new ParsedSoap using edited values
    p2 = ParsedSoap(
        sapaan=parsed.sapaan,
        pembuka=parsed.pembuka,
        rs=parsed.rs,
        nama=nama,
        jk=jk,
        umur=umur,
        pembiayaan=pembiayaan,
        jenis_perawatan=jenis_perawatan,
        kamar=kamar,
        rm=rm,
        S=S,
        O_generalis=O_generalis,
        EO=EO,
        IO=IO,
        penunjang_items=penunjang_items,
        A=A,
        residen=residen_out,
        dpjp=dpjp_final,
    )

    output = build_preop(
        p=p2,
        tanggal_laporan=tanggal_laporan,
        tanggal_operasi=tanggal_operasi,
        jam_operasi=jam_operasi,
        zona_waktu=zona_waktu,
        tindakan_line=tindakan_line,
        anestesi=anestesi,
        pembiayaan=pembiayaan,
        jenis_perawatan=jenis_perawatan,
        kamar=kamar,
        penunjang_items=penunjang_items,
        plan_items=plan_lines,
        residen=residen_out,
        dpjp=dpjp_final,
    )

    st.success("Selesai. Tinggal copy / download.")
    st.text_area("SOAP Pre-Op", value=output, height=520)

    st.download_button(
        "Download .txt",
        data=output.encode("utf-8"),
        file_name="soap_preop.txt",
        mime="text/plain",
    )
