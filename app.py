import re
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, date
from dateutil import tz
import streamlit as st

TZ = tz.gettz("Asia/Jakarta")

# ---------------------------
# Data model
# ---------------------------
@dataclass
class Patient:
    nama: str = ""
    jk: str = ""
    umur: str = ""
    program: str = ""
    jenis_perawatan: str = ""
    kamar: str = ""
    rs: str = "RSGMP UNHAS"
    rm: str = ""

    s_text: str = ""
    eo_text: str = ""
    io_text: str = ""

    ku: str = ""
    td: str = ""
    n: str = ""
    r: str = ""
    suhu: str = ""
    spo2: str = ""
    bb: str = ""
    tb: str = ""

    diagnosis_a: str = ""
    residen: str = ""
    dpjp: str = ""

    # penunjang
    lab_tgl: str = ""
    lab_wbc: str = ""
    lab_rbc: str = ""
    lab_hgb: str = ""
    lab_hct: str = ""
    lab_plt: str = ""
    lab_aptt: str = ""
    lab_pt: str = ""
    lab_inr: str = ""
    lab_gds: str = ""
    lab_hbsag: str = ""
    lab_kesan: str = ""

    thorax_tgl: str = ""
    thorax_kesan: str = ""

# ---------------------------
# Helpers
# ---------------------------
DAY_ID = {
    "Monday": "Senin",
    "Tuesday": "Selasa",
    "Wednesday": "Rabu",
    "Thursday": "Kamis",
    "Friday": "Jumat",
    "Saturday": "Sabtu",
    "Sunday": "Minggu",
}

def day_name_id(d: date) -> str:
    en = d.strftime("%A")
    return DAY_ID.get(en, en)

def fmt_ddmmyyyy(d: date) -> str:
    return d.strftime("%d/%m/%Y")

def clean(s: str) -> str:
    return (s or "").strip()

def pick1(text: str, pattern: str, flags=0) -> str:
    m = re.search(pattern, text, flags)
    return clean(m.group(1)) if m else ""

def pick_block(text: str, start_pat: str, end_pat: str, flags=re.IGNORECASE | re.DOTALL) -> str:
    """
    Ambil blok dari setelah start_pat sampai sebelum end_pat.
    """
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
    # rapikan bullet agar konsisten
    s = s.replace("•⁠", "•").replace("• ⁠", "• ").replace("•⁠  ⁠", "• ")
    return s.strip()

# ---------------------------
# Parsing SOAP mentah
# ---------------------------
def parse_raw_soap(raw: str) -> Patient:
    raw = raw.strip()
    p = Patient()

    # RS / default
    if re.search(r"RSGMP\s*UNHAS", raw, re.IGNORECASE):
        p.rs = "RSGMP UNHAS"

    # Identitas: ambil baris yang mengandung "An."
    # Contoh: "An. Fikri ... / L / 8 Tahun ..."
    ident_line = pick1(raw, r"(An\.\s*[^\n]+)")
    if ident_line:
        parts = [x.strip() for x in ident_line.split("/") if x.strip()]
        # parts[0] biasanya "An. Nama"
        if parts:
            p.nama = re.sub(r"^An\.\s*", "", parts[0]).strip()
        if len(parts) >= 2:
            p.jk = parts[1]
        if len(parts) >= 3:
            p.umur = parts[2]
        # cari program / perawatan / RM dari line itu juga kalau ada
        # RM biasanya tidak selalu di baris yang sama, jadi cari global juga

    # JK kadang "Laki-laki" di S:
    if not p.jk:
        jk2 = pick1(raw, r"/\s*([LP])\s*/")
        p.jk = jk2

    # Program: BAKSOS/CCC
    prog = pick1(raw, r"\b(BAKSOS|Baksos|CCC)\b")
    if prog:
        p.program = "BAKSOS" if prog.lower() == "baksos" else prog

    # Jenis perawatan
    if re.search(r"Rawat\s+Inap", raw, re.IGNORECASE):
        p.jenis_perawatan = "Rawat Inap"
    elif re.search(r"Rawat\s+Jalan", raw, re.IGNORECASE):
        p.jenis_perawatan = "Rawat Jalan"

    # RM
    p.rm = pick1(raw, r"RM\.?\s*[:.]?\s*([0-9.]+)", re.IGNORECASE) or pick1(raw, r"RM\s*([0-9.]+)", re.IGNORECASE)

    # S, O, A blocks
    p.s_text = pick_block(raw, r"\bS\s*:\s*", r"\n\s*O\s*:\s*")
    o_block = pick_block(raw, r"\bO\s*:\s*", r"\n\s*A\s*:\s*")
    a_block = pick_block(raw, r"\bA\s*:\s*", r"\n\s*P\s*:\s*")

    # Diagnosis A: ambil seluruh isi A block (biasanya sudah 1 baris bullet)
    p.diagnosis_a = normalize_bullets(a_block)

    # vitals dari o_block
    # KU
    p.ku = pick1(o_block, r"KU\s*[: ]\s*([^\n]+)", re.IGNORECASE)
    # TD
    p.td = pick1(o_block, r"TD\s*[: ]\s*([0-9\-\/]+)\s*mmHg", re.IGNORECASE) or pick1(o_block, r"TD\s*[: ]\s*([^\n]+)", re.IGNORECASE)
    # N
    p.n = pick1(o_block, r"\bN\s*[: ]\s*([0-9]+)\s*x", re.IGNORECASE)
    # R / P
    p.r = pick1(o_block, r"\bR\s*[: ]\s*([0-9]+)\s*x", re.IGNORECASE) or pick1(o_block, r"\bP\s*[: ]\s*([0-9]+)\s*x", re.IGNORECASE)
    # Suhu
    p.suhu = pick1(o_block, r"\bS\s*[: ]\s*([0-9.]+)\s*°", re.IGNORECASE)
    # SpO2
    p.spo2 = pick1(o_block, r"SpO2\s*[: ]\s*([0-9]+)\s*%?", re.IGNORECASE)
    # BB/TB
    p.bb = pick1(o_block, r"BB\s*[: ]\s*([0-9.]+)\s*kg", re.IGNORECASE)
    p.tb = pick1(o_block, r"TB\s*[: ]\s*([0-9.]+)\s*cm", re.IGNORECASE)

    # EO/IO blocks (dalam Status Lokalis)
    p.eo_text = normalize_bullets(pick_block(o_block, r"E\.?O\s*:\s*", r"\n\s*I\.?O\s*:\s*"))
    p.io_text = normalize_bullets(pick_block(o_block, r"I\.?O\s*:\s*", r"\n\s*(A\s*:|Pemeriksaan|$)"))

    # Residen / DPJP
    p.residen = pick1(raw, r"Residen\s*:?\s*([^\n]+)", re.IGNORECASE)
    p.dpjp = pick1(raw, r"DPJP\s*:?\s*([^\n]+)", re.IGNORECASE)

    return p

# ---------------------------
# Parsing blok LAB (opsional)
# ---------------------------
def parse_lab_block(p: Patient, lab_text: str) -> Patient:
    """
    Kamu bisa paste blok lab seperti yang di contoh:
    • Lab darah (29/12/2025)
      • WBC : 7.40 ...
      • RBC : ...
      ...
    Kesan : ....
    """
    t = lab_text.strip()
    if not t:
        return p

    p.lab_tgl = pick1(t, r"\(\s*([0-9]{1,2}/[0-9]{1,2}/[0-9]{4})\s*\)", re.IGNORECASE) or p.lab_tgl

    def val(key):
        # ambil apapun setelah "KEY :"
        return pick1(t, rf"\b{re.escape(key)}\b\s*[: ]\s*([^\n\r]+)", re.IGNORECASE)

    p.lab_wbc = val("WBC") or p.lab_wbc
    p.lab_rbc = val("RBC") or p.lab_rbc
    p.lab_hgb = val("HGB") or p.lab_hgb
    p.lab_hct = val("HCT") or p.lab_hct
    p.lab_plt = val("PLT") or p.lab_plt
    p.lab_aptt = val("aPTT") or p.lab_aptt
    # PT kadang "PT : 15.1 INR 1.10 ..."
    pt_line = val("PT")
    if pt_line:
        p.lab_pt = pt_line
        inr = pick1(pt_line, r"INR\s*([0-9.]+)", re.IGNORECASE)
        if inr:
            p.lab_inr = inr
    p.lab_gds = val("GDS") or p.lab_gds
    p.lab_hbsag = val("HBsAg") or p.lab_hbsag
    p.lab_kesan = pick1(t, r"\bKesan\s*:\s*([^\n\r]+)", re.IGNORECASE) or p.lab_kesan
    return p

def parse_thorax_block(p: Patient, thorax_text: str) -> Patient:
    t = thorax_text.strip()
    if not t:
        return p
    p.thorax_tgl = pick1(t, r"\(\s*([0-9]{1,2}/[0-9]{1,2}/[0-9]{4})\s*\)", re.IGNORECASE) or p.thorax_tgl
    p.thorax_kesan = pick1(t, r"\bKesan\s*:\s*([^\n\r]+)", re.IGNORECASE) or p.thorax_kesan
    return p

# ---------------------------
# Generate SOAP Pre-Op
# ---------------------------
def build_penunjang(p: Patient) -> str:
    lines = []
    any_lab = any([p.lab_tgl, p.lab_wbc, p.lab_rbc, p.lab_hgb, p.lab_hct, p.lab_plt, p.lab_aptt, p.lab_pt, p.lab_inr, p.lab_gds, p.lab_hbsag, p.lab_kesan])
    any_thx = any([p.thorax_tgl, p.thorax_kesan])
    if not (any_lab or any_thx):
        return ""

    lines.append("Pemeriksaan Penunjang :")
    if any_lab:
        lines.append(f"•⁠  ⁠Lab darah ({p.lab_tgl or '-'})")
        if p.lab_wbc: lines.append(f"  • WBC : {p.lab_wbc}")
        if p.lab_rbc: lines.append(f"  • RBC : {p.lab_rbc}")
        if p.lab_hgb: lines.append(f"  • HGB : {p.lab_hgb}")
        if p.lab_hct: lines.append(f"  • HCT : {p.lab_hct}")
        if p.lab_plt: lines.append(f"  • PLT : {p.lab_plt}")
        if p.lab_aptt: lines.append(f"  • aPTT : {p.lab_aptt}")
        if p.lab_pt: lines.append(f"  • PT   : {p.lab_pt}")
        if p.lab_gds: lines.append(f"  • GDS : {p.lab_gds}")
        if p.lab_hbsag: lines.append(f"•⁠  ⁠HBsAg : {p.lab_hbsag}")
        if p.lab_kesan: lines.append(f"Kesan : {p.lab_kesan}")

    if any_thx:
        lines.append(f"•⁠  ⁠Thorax X-Ray ({p.thorax_tgl or '-'})")
        if p.thorax_kesan: lines.append(f"Kesan : {p.thorax_kesan}")

    return "\n".join(lines)

def generate_preop_text(
    p: Patient,
    tindakan: str,
    anestesi: str,
    jenis_perawatan: str,
    kamar: str,
    program: str,
    zona_waktu: str,
    jam_puasa: str,
    siap_darah: str,
    ivfd: str,
    antibiotik: str,
    dosis_ab: str,
    jam_ab: str,
    jam_operasi: str,
    operasi_h_plus: int = 1
) -> str:
    today = datetime.now(TZ).date()
    op_date = today + timedelta(days=operasi_h_plus)

    hari_today = day_name_id(today)
    hari_op = day_name_id(op_date)
    tgl_today = fmt_ddmmyyyy(today)
    tgl_op = fmt_ddmmyyyy(op_date)

    status_generalis = []
    status_generalis.append(f"KU {p.ku}" if p.ku else "KU Baik, Compos Mentis")
    status_generalis.append(f"TD : {p.td or '---/--'} mmHg")
    if p.n: status_generalis.append(f"N : {p.n} x/Menit")
    if p.r: status_generalis.append(f"R : {p.r} x/Menit")
    if p.suhu: status_generalis.append(f"S : {p.suhu}⁰C")
    if p.spo2: status_generalis.append(f"SpO2 : {p.spo2}% (Free Air)")
    if p.bb: status_generalis.append(f"BB: {p.bb} kg")
    if p.tb: status_generalis.append(f"TB: {p.tb} cm")

    penunjang = build_penunjang(p)
    penunjang_block = f"\n\n{penunjang}" if penunjang else ""

    plan_lines = []
    plan_lines.append("•⁠  ⁠Acc TS Anestesi")
    if siap_darah:
        plan_lines.append(f"•⁠  ⁠{siap_darah}")
    if ivfd:
        plan_lines.append(f"•⁠  ⁠{ivfd}")
    plan_lines.append(f"•⁠  ⁠Puasa 6 jam pre op atau sesuai instruksi dari TS. Anestesi yaitu mulai Pukul {jam_puasa} {zona_waktu}")
    plan_lines.append("•⁠  ⁠Pasien menyikat gigi sebelum tidur dan sebelum ke kamar operasi")
    plan_lines.append("•⁠  ⁠Gunakan masker bedah saat ke kamar operasi")
    plan_lines.append(f"•⁠  ⁠Pasien rencana diberikan antibiotik profilaksis {antibiotik} {dosis_ab}, 1 jam sebelum operasi (skin test terlebih dahulu) pada Pukul {jam_ab} {zona_waktu}")
    plan_lines.append(f"•⁠  ⁠Pro {tindakan} dalam {anestesi} pada hari {hari_op}, {tgl_op} Pukul {jam_operasi} {zona_waktu} di {p.rs}")

    preop = f"""Assalamualaikum dokter. 
Maaf mengganggu, izin melaporkan Pasien Rencana Operasi {p.rs}, {hari_today} ({tgl_today}) 

An. {p.nama} / {p.jk} / {p.umur} / {program} / {jenis_perawatan} / {kamar} / {p.rs} / RM. {p.rm}

S : 
{p.s_text or "(S tidak terdeteksi — paste ulang SOAP mentah)"}

O :
Status Generalis : 
{chr(10).join(status_generalis)}

Status Lokalis
E.O :
{p.eo_text or "•⁠  ⁠(EO tidak terdeteksi)"}

I.O: 
{p.io_text or "•⁠  ⁠(IO tidak terdeteksi)"}{penunjang_block}

A : 
{p.diagnosis_a or "•⁠  ⁠(A tidak terdeteksi)"}

P:
{chr(10).join(plan_lines)}

Mohon Instruksi selanjutnya dokter
Terima Kasih. 

Residen: {p.residen or "-"}

DPJP : {p.dpjp or "-"}
"""
    return preop

# ---------------------------
# Streamlit UI
# ---------------------------
st.set_page_config(page_title="SOAP → Pre-Op Generator", layout="wide")
st.title("SOAP Terjaring → SOAP Pre-Op (Auto H+1)")

col1, col2 = st.columns([1, 1])

with col1:
    st.subheader("1) Tempel SOAP mentah")
    raw = st.text_area("SOAP mentah (Rawat Jalan / non Pre-Op)", height=340, placeholder="Paste di sini...")

    st.subheader("2) (Opsional) Tempel hasil lab & thorax (biar nggak input satu-satu)")
    lab_block = st.text_area("Blok Lab (opsional)", height=140, placeholder="Misal: Lab darah (29/12/2025)\nWBC: ...\nPT: ... INR ...\nKesan: ...")
    thorax_block = st.text_area("Blok Thorax (opsional)", height=100, placeholder="Misal: Thorax X-Ray (29/12/2025)\nKesan: ...")

with col2:
    st.subheader("Setting Pre-Op (default bisa kamu ubah cepat)")
    tindakan = st.text_input("Tindakan", value="Rekonstruksi palatum")
    anestesi = st.text_input("Anestesi", value="general anestesi")
    program = st.text_input("Program (BAKSOS/CCC)", value="BAKSOS")
    jenis_perawatan = st.text_input("Jenis perawatan", value="Rawat Inap")
    kamar = st.text_input("Kamar/Bed", value="Kamar Molar Bed ...")

    st.divider()
    zona_waktu = st.text_input("Zona waktu", value="WITA")
    jam_puasa = st.text_input("Mulai puasa (jam)", value="02.00")
    jam_operasi = st.text_input("Jam operasi", value="08.00")

    siap_darah = st.text_input("Siap darah (opsional)", value="Siap darah 1 bag PRC")
    ivfd = st.text_input("IVFD (opsional)", value="IVFD RL 16 tpm (makrodrips)")

    st.divider()
    antibiotik = st.text_input("Antibiotik profilaksis", value="ceftriaxone")
    dosis_ab = st.text_input("Dosis", value="1 gr")
    jam_ab = st.text_input("Jam pemberian", value="07.00")

st.divider()

if st.button("Generate SOAP Pre-Op", type="primary"):
    if not raw.strip():
        st.error("SOAP mentah masih kosong.")
    else:
        p = parse_raw_soap(raw)
        p = parse_lab_block(p, lab_block)
        p = parse_thorax_block(p, thorax_block)

        out = generate_preop_text(
            p=p,
            tindakan=tindakan,
            anestesi=anestesi,
            jenis_perawatan=jenis_perawatan,
            kamar=kamar,
            program=program,
            zona_waktu=zona_waktu,
            jam_puasa=jam_puasa,
            siap_darah=siap_darah.strip(),
            ivfd=ivfd.strip(),
            antibiotik=antibiotik,
            dosis_ab=dosis_ab,
            jam_ab=jam_ab,
            jam_operasi=jam_operasi,
            operasi_h_plus=1
        )

        st.success("Berhasil generate. Silakan copy / download.")
        st.subheader("Output SOAP Pre-Op")
        st.text_area("SOAP Pre-Op", value=out, height=520)

        st.download_button(
            "Download .txt",
            data=out.encode("utf-8"),
            file_name="soap_preop.txt",
            mime="text/plain",
        )

        with st.expander("Debug: hasil parse field"):
            st.json(asdict(p))
