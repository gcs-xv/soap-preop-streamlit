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
# Helpers for IVFD, Puasa, Antibiotik automation
# -------------------------
def parse_hhmm(s: str):
    """Accepts '08.00', '08:00', '8.00', '8:0' etc. Returns (hour, minute) or None."""
    s = clean(s)
    if not s:
        return None
    s = s.replace('.', ':')
    m = re.match(r'^(\d{1,2}):(\d{1,2})$', s)
    if not m:
        return None
    h = int(m.group(1))
    mi = int(m.group(2))
    if h < 0 or h > 23 or mi < 0 or mi > 59:
        return None
    return (h, mi)

def fmt_time(h: int, mi: int) -> str:
    return f"{h:02d}.{mi:02d}"

def minus_minutes(h: int, mi: int, minutes: int):
    total = h * 60 + mi - minutes
    total %= (24 * 60)
    return (total // 60, total % 60)

def maintenance_ml_per_hr_421(weight_kg: float) -> float:
    """4-2-1 rule maintenance fluid (mL/hr). For convenience only; must be verified clinically."""
    w = max(0.0, float(weight_kg))
    if w <= 10:
        return 4.0 * w
    if w <= 20:
        return 40.0 + 2.0 * (w - 10.0)
    return 60.0 + 1.0 * (w - 20.0)

def tpm_from_ml_per_hr(ml_per_hr: float, drip_factor_gtt_per_ml: int = 20) -> int:
    """Convert mL/hr to drops per minute (tpm) given drip factor (gtt/mL)."""
    try:
        return int(round((float(ml_per_hr) * int(drip_factor_gtt_per_ml)) / 60.0))
    except Exception:
        return 0

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

    # New fields for BB/TB and tindakan/anestesi guess, minlap penunjang, jam operasi, etc.
    bb: float = 0.0
    tb: float = 0.0
    tindakan_guess: str = ""
    anestesi_guess: str = ""
    minlap_penunjang_raw: str = ""   # raw block with indentation preserved
    minlap_jam_operasi: str = ""     # e.g. 08.00
    minlap_zona_waktu: str = ""      # e.g. WITA
    dpjp_anestesi: str = ""          # optional
    sirkuler: str = ""               # optional

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

    # BB/TB from Status Generalis or O block
    bb_txt = pick1(o_block, r"\bBB\s*:?\s*([0-9]+(?:\.[0-9]+)?)\s*kg", re.IGNORECASE)
    tb_txt = pick1(o_block, r"\bTB\s*:?\s*([0-9]+(?:\.[0-9]+)?)\s*cm", re.IGNORECASE)
    try:
        p.bb = float(bb_txt) if bb_txt else 0.0
    except Exception:
        p.bb = 0.0
    try:
        p.tb = float(tb_txt) if tb_txt else 0.0
    except Exception:
        p.tb = 0.0

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

    # Guess tindakan + anestesi from P block
    t_guess, a_guess = tindakan_from_p_block(raw)
    p.tindakan_guess = t_guess
    p.anestesi_guess = a_guess

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
# Tindakan dari P block helper
# -------------------------
def tindakan_from_p_block(raw: str) -> tuple[str, str]:
    """Try to extract tindakan + anestesi from the last 'Pro ...' line in P section of raw SOAP."""
    p_block = pick_block(raw, r"\bP\s*:\s*", r"\n\s*(Izin|Mohon|Residen|DPJP)\s*:\s*")
    if not p_block:
        p_block = pick_block(raw, r"\bP\s*:\s*", r"\Z")
    p_block = normalize_bullets(p_block)
    if not p_block:
        return ("", "")

    # find last line containing 'Pro ...'
    lines = [ln.strip() for ln in p_block.splitlines() if ln.strip()]
    pro_lines = [ln for ln in lines if re.search(r"\bPro\b", ln, re.IGNORECASE)]
    if not pro_lines:
        return ("", "")
    last = pro_lines[-1]
    last = re.sub(r"^•\s*", "", last)

    # capture tindakan
    m = re.search(r"\bPro\b\s*(.+?)\s*(?:dalam\s+([^\n()]+)|\(|$)", last, re.IGNORECASE)
    if not m:
        return ("", "")
    tindakan = clean(m.group(1))
    anest = clean(m.group(2)) if m.lastindex and m.lastindex >= 2 else ""
    # cleanup common trailing text
    tindakan = re.sub(r"\s*menunggu\s+penjadwalan\.?$", "", tindakan, flags=re.IGNORECASE).strip()
    tindakan = re.sub(r"\s*pada\s+hari\s+.+$", "", tindakan, flags=re.IGNORECASE).strip()
    tindakan = re.sub(r"\s*Pukul\s+.+$", "", tindakan, flags=re.IGNORECASE).strip()
    tindakan = re.sub(r"\s*di\s+.+$", "", tindakan, flags=re.IGNORECASE).strip()

    return (tindakan, anest)

# -------------------------
# Minlap parser (preserve formatting)
# -------------------------
def parse_minlap(minlap_text: str) -> dict:
    """Parse key fields from Minlap; preserve penunjang formatting as-is."""
    t = (minlap_text or "").strip("\n")
    if not t:
        return {}

    out = {}

    # BB/TB
    bb = pick1(t, r"\bBB\s*:\s*([0-9]+(?:\.[0-9]+)?)\s*kg", re.IGNORECASE)
    tb = pick1(t, r"\bTB\s*:\s*([0-9]+(?:\.[0-9]+)?)\s*cm", re.IGNORECASE)
    try:
        out["bb"] = float(bb) if bb else 0.0
    except Exception:
        out["bb"] = 0.0
    try:
        out["tb"] = float(tb) if tb else 0.0
    except Exception:
        out["tb"] = 0.0

    # Penunjang raw block (keep spacing)
    m = re.search(r"Pemeriksaan\s+penunjang\s*:\s*(.*?)(?:\n\s*A\s*:|\n\s*P\s*:|\Z)", t, re.IGNORECASE | re.DOTALL)
    if m:
        block = m.group(0).strip("\n")
        # keep exactly as written, but ensure it starts with 'Pemeriksaan penunjang'
        out["penunjang_raw"] = block

    # Tindakan + anestesi from Minlap P line
    p_line = pick1(t, r"\bP\s*:\s*(.+)", re.IGNORECASE)
    if p_line:
        m2 = re.search(r"\bPro\b\s*(.+?)\s*(?:dalam\s+([^\n]+))?", p_line, re.IGNORECASE)
        if m2:
            out["tindakan"] = clean(m2.group(1))
            out["anestesi"] = clean(m2.group(2))

    # Jam operasi & zona from 'Pukul : *08.00 WITA*'
    m3 = re.search(r"Pukul\s*:\s*\*?\s*(\d{1,2}[\.:]\d{2})\s*([A-Z]{3,4})\s*\*?", t, re.IGNORECASE)
    if m3:
        out["jam_operasi"] = m3.group(1).replace(":", ".")
        out["zona_waktu"] = m3.group(2).upper()

    # DPJP Anestesi & Sirkuler
    out["dpjp_anestesi"] = clean(pick1(t, r"DPJP\s+Anestesi\s*:\s*(.+)", re.IGNORECASE))
    out["sirkuler"] = clean(pick1(t, r"Sirkuler\s*:\s*(.+)", re.IGNORECASE))

    return out

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
    penunjang_raw: str,
    plan_items: list[str],
    meds_items: list[str] | None,
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

    # Penunjang block: prefer raw (Minlap) to preserve indentation/spacing exactly
    pen_block = ""
    if clean(penunjang_raw):
        pen_block = clean(penunjang_raw).rstrip() + "\n\n"
    elif penunjang_items:
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

    meds_block = ""
    if meds_items:
        meds_lines = [clean(x) for x in meds_items if clean(x)]
        if meds_lines:
            meds_block = "\nMedikasi:\n" + "\n".join([f"•⁠  ⁠{x}" for x in meds_lines]) + "\n"

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
        + meds_block
        + "Mohon instruksi selanjutnya, Dokter.\n"
        + "Terima kasih.\n\n"
        + f"Residen: {residen}\n\n"
        + f"DPJP: {dpjp}\n"
    )
    return out

# -------------------------
# Streamlit UI (Mobile-first)
# -------------------------
st.set_page_config(page_title="SOAP → Pre-Op", layout="centered")
st.title("SOAP Terjaring → SOAP Pre-Op")

# Preset DPJP (boleh tambah)
DPJP_PRESETS = [
    "drg. Husnul Basyar, Sp.B.M.Mf.",
    "drg. Abul Fauzi, Sp.B.M.Mf., Subsp.Tr.Mf.S.Tm.",
    "Dr. drg. Andi Tajrin, M.Kes., Sp.B.M.Mf., Subsp.C.O.Mf.",
]

# Plan library yang GENERIK (biar tidak kaku)
DEFAULT_PLAN_LIBRARY = [
    "ACC TS Anestesi",
    "IVFD (isi sesuai)",
    "Puasa pre-op (isi sesuai)",
    "Sikat gigi sebelum tidur & sebelum ke kamar operasi",
    "Gunakan masker bedah saat ke kamar operasi",
    "Antibiotik profilaksis (isi sesuai)",
    "Siap darah/PRC (jika perlu)",
]

def dedupe_case_insensitive(lines: list[str]) -> list[str]:
    out = []
    seen = set()
    for x in lines:
        k = x.strip().lower()
        if not k:
            continue
        if k in seen:
            continue
        seen.add(k)
        out.append(x.strip())
    return out

def parse_if_needed(raw_text: str):
    """Auto-parse whenever raw text changes."""
    if "raw_prev" not in st.session_state:
        st.session_state["raw_prev"] = ""
    if raw_text.strip() and raw_text != st.session_state["raw_prev"]:
        st.session_state["parsed"] = parse_raw_soap(raw_text)
        st.session_state["raw_prev"] = raw_text

def reset_all():
    for k in list(st.session_state.keys()):
        del st.session_state[k]

# Top bar actions
cA, cB = st.columns(2)
with cA:
    if st.button("🔄 Reset", use_container_width=True):
        reset_all()
        st.rerun()
with cB:
    st.caption("Tip: paling enak dipakai di HP — alurnya 1) Paste → 2) Edit → 3) Output")

tab1, tab2, tab3 = st.tabs(["1) Paste", "2) Edit", "3) Output"])

# -------------------------
# TAB 1: Paste
# -------------------------
with tab1:
    st.subheader("Paste SOAP mentah")
    raw = st.text_area(
        "Tempel SOAP Rawat Jalan / non pre-op di sini",
        height=260,
        placeholder="Contoh: Assalamualaikum... (Rawat Jalan)...\nTn./Ny./An. ... / L/P / ...\nS: ...\nO: ...\nA: ...\nP: ...\nResiden: ...\nDPJP: ..."
    )

    st.subheader("Opsional: paste MINLAP (paling disarankan)")
    minlap_text = st.text_area(
        "Paste Minlap di sini (format tetap, nanti penunjang & jam operasi ikut terisi)",
        height=220,
        placeholder="Contoh:\n1. Nama / ...\nPerempuan BB: 49 kg, TB: 159 cm ...\nPemeriksaan penunjang :\n- OPG ...\n- Lab Darah (...)\n  • WBC : ...\n- HBsAg : ...\n  Kesan : ...\n- Thorax ...\n  Kesan: ...\nA : ...\nP : Pro ... dalam general anestesi\nPukul : *08.00 WITA*\nDPJP Anestesi: ...\nSirkuler : ..."
    )
    st.session_state["minlap_text_cache"] = minlap_text

    parse_if_needed(raw)

    # Optional parse ulang button
    if st.button("Parse ulang", type="primary", use_container_width=True):
        if raw.strip():
            st.session_state["parsed"] = parse_raw_soap(raw)
            st.session_state["raw_prev"] = raw
            st.success("Berhasil parse.")
        else:
            st.warning("SOAP mentah masih kosong.")

    parsed = st.session_state.get("parsed", ParsedSoap(penunjang_items=[]))

    with st.expander("Lihat hasil parse (preview singkat)"):
        st.write("**Nama:**", parsed.nama or "-")
        st.write("**RM:**", parsed.rm or "-")
        st.write("**Residen:**", parsed.residen or "-")
        st.write("**DPJP:**", parsed.dpjp or "-")
        st.write("**Penunjang terdeteksi:**")
        st.write("\n".join([f"- {x}" for x in (parsed.penunjang_items or [])]) or "-")

# -------------------------
# TAB 2: Edit (simple phone form)
# -------------------------
with tab2:
    parsed = st.session_state.get("parsed", ParsedSoap(penunjang_items=[]))

    st.subheader("Identitas")
    nama = st.text_input("Nama (Tn./Ny./An.)", value=parsed.nama or "")
    jk = st.text_input("JK", value=parsed.jk or "")
    umur = st.text_input("Umur", value=parsed.umur or "")
    pembiayaan = st.text_input("Pembiayaan", value=parsed.pembiayaan or "BPJS")
    jenis_perawatan = st.text_input("Jenis perawatan", value="Rawat Inap")
    kamar = st.text_input("Kamar/Bed", value=parsed.kamar or "")

    # Default BB from SOAP; can be overridden by Minlap
    bb_default = float(parsed.bb) if getattr(parsed, "bb", 0.0) else 0.0
    bb = st.number_input("BB (kg)", min_value=0.0, max_value=200.0, value=bb_default, step=0.1)

    rm = st.text_input("RM", value=parsed.rm or "")
    rs = st.text_input("RS", value=parsed.rs or "RSGMP UNHAS")

    st.divider()

    st.subheader("Jadwal operasi (otomatis H+1, bisa diganti)")
    today = datetime.now(TZ).date()
    default_op = today + timedelta(days=1)

    tanggal_laporan = st.date_input("Tanggal laporan", value=today)
    tanggal_operasi = st.date_input("Tanggal operasi", value=default_op)

    # Defaults from Minlap if pasted
    minlap_info = parse_minlap(st.session_state.get("minlap_text_cache", ""))
    if minlap_info.get("bb"):
        bb = float(minlap_info.get("bb", bb))
    jam_default = minlap_info.get("jam_operasi") or "08.00"
    zona_default = minlap_info.get("zona_waktu") or "WITA"

    c1, c2 = st.columns(2)
    with c1:
        jam_operasi = st.text_input("Jam operasi", value=jam_default)
    with c2:
        zona_waktu = st.text_input("Zona waktu", value=zona_default)

    anest_default = "general anestesi"
    if getattr(parsed, "anestesi_guess", ""):
        anest_default = parsed.anestesi_guess
    if minlap_info.get("anestesi"):
        anest_default = minlap_info.get("anestesi")
    anestesi = st.text_input("Anestesi", value=anest_default or "general anestesi")

    # ---- Auto times from Jam Operasi ----
    op_parsed = parse_hhmm(jam_operasi)
    default_puasa = ""
    default_ab = ""
    if op_parsed:
        ph, pm = minus_minutes(op_parsed[0], op_parsed[1], 6 * 60)
        ah, am = minus_minutes(op_parsed[0], op_parsed[1], 60)
        default_puasa = fmt_time(ph, pm)
        default_ab = fmt_time(ah, am)

    st.subheader("Bagian P (yang wajib & sering berubah)")

    cP1, cP2, cP3 = st.columns(3)
    with cP1:
        include_ivfd = st.toggle("IVFD", value=True)
    with cP2:
        include_puasa = st.toggle("Puasa 6 jam", value=True)
    with cP3:
        include_ab = st.toggle("Antibiotik 1 jam", value=True)

    # IVFD
    ivfd_line = ""
    if include_ivfd:
        st.caption("IVFD hampir selalu ada. Kamu bisa isi manual, atau pakai saran dari BB (rule 4-2-1) untuk percepat.")
        drip_factor = st.selectbox("Set drip", options=[20, 60], index=0, help="Makrodrips biasanya 20 gtt/mL; Mikrodrips 60 gtt/mL.")
        suggested_tpm = 0
        if bb and bb > 0:
            mlhr = maintenance_ml_per_hr_421(bb)
            suggested_tpm = tpm_from_ml_per_hr(mlhr, drip_factor)
        cI1, cI2 = st.columns(2)
        with cI1:
            ivfd_cairan = st.text_input("Cairan", value="RL")
        with cI2:
            ivfd_tpm = st.number_input("tpm", min_value=0, max_value=200, value=int(suggested_tpm) if suggested_tpm else 0, step=1)

        drip_label = "makrodrips" if drip_factor == 20 else "mikrodrips"
        if ivfd_tpm > 0:
            ivfd_line = f"IVFD {ivfd_cairan} {ivfd_tpm} tpm ({drip_label})"
        else:
            ivfd_line = f"IVFD {ivfd_cairan} (isi tpm) ({drip_label})"

    # Puasa
    puasa_mulai = ""
    if include_puasa:
        puasa_mulai = st.text_input("Mulai puasa (auto = operasi - 6 jam)", value=default_puasa)

    # Antibiotik profilaksis
    ab_nama = ""
    ab_dosis = ""
    ab_jam = ""
    ab_skin_test = True
    if include_ab:
        cA1, cA2 = st.columns(2)
        with cA1:
            ab_nama = st.text_input("Antibiotik profilaksis", value="Ceftriaxone")
        with cA2:
            ab_dosis = st.text_input("Dosis", value="1 gr")
        ab_jam = st.text_input("Jam antibiotik (auto = operasi - 1 jam)", value=default_ab)
        ab_skin_test = st.checkbox("Tambahkan '(skin test terlebih dahulu)'", value=True)

    tindakan_default = getattr(parsed, "tindakan_guess", "") or ""
    if minlap_info.get("tindakan"):
        tindakan_default = minlap_info.get("tindakan")
    tindakan_line = st.text_input(
        "Tindakan (otomatis dari P mentah kalau ada)",
        value=tindakan_default
    )

    st.divider()

    st.subheader("Isi SOAP (auto dari mentah, kamu bisa edit)")
    S = st.text_area("S", value=parsed.S or "", height=140)
    O_generalis = st.text_area("O - Status Generalis", value=parsed.O_generalis or "", height=120)
    EO = st.text_area("EO", value=parsed.EO or "", height=120)
    IO = st.text_area("IO", value=parsed.IO or "", height=120)
    A = st.text_area("A", value=parsed.A or "", height=100)

    st.divider()

    st.subheader("Pemeriksaan Penunjang")
    penunjang_raw_default = minlap_info.get("penunjang_raw", "")

    if penunjang_raw_default:
        st.caption("Minlap terdeteksi: penunjang akan mengikuti format Minlap (spasi & indent dipertahankan).")

    penunjang_raw = st.text_area(
        "Jika kamu paste Minlap, biarkan apa adanya. Kalau kosong, pakai mode list di bawah.",
        value=penunjang_raw_default,
        height=260,
        placeholder="Paste blok 'Pemeriksaan penunjang :' dari Minlap di sini untuk menjaga format."
    )

    st.caption("Mode alternatif (list): kalau kamu tidak pakai Minlap, isi 1 baris = 1 item.")
    base_pen = list(parsed.penunjang_items or [])
    penunjang_editor = st.text_area(
        "Penunjang (list)",
        value="\n".join(base_pen),
        height=160,
        placeholder="OPG X-Ray (tanggal)\nThorax X-Ray (tanggal)\nLab darah (tanggal)"
    )
    penunjang_items = dedupe_case_insensitive([x for x in penunjang_editor.splitlines() if x.strip()])

    st.divider()

    st.subheader("Plan (tinggal pilih + tambah sendiri)")
    picked = st.multiselect(
        "Centang plan umum (boleh edit di bawah)",
        options=DEFAULT_PLAN_LIBRARY,
        default=["ACC TS Anestesi", "Sikat gigi sebelum tidur & sebelum ke kamar operasi", "Gunakan masker bedah saat ke kamar operasi"],
    )

    custom_plan = st.text_area(
        "Tambahan plan (1 baris = 1 item, bebas)",
        height=120,
        placeholder="Contoh:\nIVFD RL 20 tpm (makrodrips)\nPuasa mulai 01.30 WITA\nAntibiotik profilaksis Ceftriaxone inj 1 gr jam 06.30 WITA\nSiap darah 1 bag PRC"
    )

    plan_lines = picked + [x.strip() for x in custom_plan.splitlines() if x.strip()]

    # Auto-insert common required/structured lines
    if include_ivfd and ivfd_line:
        plan_lines.append(ivfd_line)

    if include_puasa and clean(puasa_mulai):
        plan_lines.append(
            f"Puasa 6 jam pre op atau sesuai instruksi dari TS. Anestesi yaitu mulai Pukul {puasa_mulai} {zona_waktu}"
        )

    if include_ab:
        ab_display = " ".join([x for x in [clean(ab_nama), clean(ab_dosis)] if x])
        if not ab_display:
            ab_display = "(isi antibiotik)"
        skin_phrase = " (skin test terlebih dahulu)" if ab_skin_test else ""
        if clean(ab_jam):
            plan_lines.append(
                f"Pasien rencana diberikan antibiotik profilaksis {ab_display}, 1 jam sebelum operasi{skin_phrase} pada Pukul {ab_jam} {zona_waktu}"
            )

    # Deduplicate plan lines while preserving order
    plan_lines = dedupe_case_insensitive(plan_lines)

    st.subheader("Medikasi (opsional)")
    meds_text = st.text_area(
        "1 baris = 1 obat",
        height=120,
        placeholder="Contoh:\nAmpicillin Sulbactam inj 1500 mg/8 jam/IV\nMetronidazole inj 500 mg/8 jam/IV"
    )
    meds_items = [x.strip() for x in meds_text.splitlines() if x.strip()]

    st.divider()

    st.subheader("Residen & DPJP")
    st.caption("Residen selalu berbeda-beda — paste aja. Nanti otomatis dirapihin jadi koma-koma.")
    residen_in = st.text_area(
        "Residen",
        value=parsed.residen or "",
        height=80,
        placeholder="Contoh: drg. Reza, drg. Mike, drg. Amal"
    )
    residen_out = split_residen_text(residen_in)

    dpjp_choice = st.selectbox("DPJP (preset)", DPJP_PRESETS, index=0)
    dpjp_custom = st.text_input("DPJP (kalau mau override)", value=parsed.dpjp or "")
    dpjp_final = dpjp_custom.strip() if dpjp_custom.strip() else dpjp_choice

    # Store edited data to session for Output tab
    st.session_state["edited"] = {
        "nama": nama, "jk": jk, "umur": umur, "pembiayaan": pembiayaan,
        "jenis_perawatan": jenis_perawatan, "kamar": kamar, "rm": rm, "rs": rs,
        "tanggal_laporan": tanggal_laporan, "tanggal_operasi": tanggal_operasi,
        "jam_operasi": jam_operasi, "zona_waktu": zona_waktu,
        "anestesi": anestesi, "tindakan_line": tindakan_line,
        "S": S, "O_generalis": O_generalis, "EO": EO, "IO": IO, "A": A,
        "penunjang_items": penunjang_items,
        "penunjang_raw": penunjang_raw,
        "plan_lines": plan_lines,
        "residen": residen_out,
        "dpjp": dpjp_final,
        "bb": bb,
        "meds_items": meds_items,
        "dpjp_anestesi": minlap_info.get("dpjp_anestesi", ""),
        "sirkuler": minlap_info.get("sirkuler", ""),
    }

    st.success("✅ Sudah siap. Lanjut ke tab 3) Output.")

# -------------------------
# TAB 3: Output
# -------------------------
with tab3:
    st.subheader("Output SOAP Pre-Op")
    parsed = st.session_state.get("parsed", ParsedSoap(penunjang_items=[]))
    edited = st.session_state.get("edited")

    if not edited:
        st.info("Isi dulu di tab 2) Edit, lalu balik ke sini.")
    else:
        # Build a new ParsedSoap with edited content
        p2 = ParsedSoap(
            sapaan=parsed.sapaan,
            pembuka=parsed.pembuka,
            rs=edited["rs"],
            nama=edited["nama"],
            jk=edited["jk"],
            umur=edited["umur"],
            pembiayaan=edited["pembiayaan"],
            jenis_perawatan=edited["jenis_perawatan"],
            kamar=edited["kamar"],
            rm=edited["rm"],
            S=edited["S"],
            O_generalis=edited["O_generalis"],
            EO=edited["EO"],
            IO=edited["IO"],
            penunjang_items=edited["penunjang_items"],
            A=edited["A"],
            residen=edited["residen"],
            dpjp=edited["dpjp"],
        )

        output = build_preop(
            p=p2,
            tanggal_laporan=edited["tanggal_laporan"],
            tanggal_operasi=edited["tanggal_operasi"],
            jam_operasi=edited["jam_operasi"],
            zona_waktu=edited["zona_waktu"],
            tindakan_line=edited["tindakan_line"] or "(isi tindakan)",
            anestesi=edited["anestesi"],
            pembiayaan=edited["pembiayaan"],
            jenis_perawatan=edited["jenis_perawatan"],
            kamar=edited["kamar"] or "(isi kamar/bed)",
            penunjang_items=edited["penunjang_items"],
            penunjang_raw=edited.get("penunjang_raw", ""),
            plan_items=edited["plan_lines"],
            meds_items=edited.get("meds_items"),
            residen=edited["residen"] or "-",
            dpjp=edited["dpjp"] or "-",
        )

        st.text_area("SOAP Pre-Op (siap copy)", value=output, height=520)

        st.download_button(
            "Download .txt",
            data=output.encode("utf-8"),
            file_name="soap_preop.txt",
            mime="text/plain",
            use_container_width=True,
        )
